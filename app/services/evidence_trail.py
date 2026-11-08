"""Knowledge Server provenance helpers for Step 7 review and Step 8 export."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import yaml

from app.integrations.ks_integration import KSCallError, KSUnavailableError
from app.models.project import KSEvidenceLink, KSReviewHistoryEntry, ProjectSession
from app.services.edge_contract_file_inspector import inspect_file_contract_layout
from app.services.edge_contracts import (
    FILE_CSV_TYPE,
    FILE_FIXED_WIDTH_TYPE,
    SOAP_MAPPING_MODE_CANONICAL,
    SOAP_WSDL_TYPE,
    XML_XSD_TYPE,
    clean_package_path,
    default_downstream_xml_mapping_path,
    default_soap_operation_mapping_path,
    default_upstream_xml_mapping_path,
)
from app.services.ks_lifecycle import ks_client
from app.services.ks_workspace import (
    current_workspace_identity,
    workspace_allowed_roots,
    workspace_db_path,
)
from app.services.validation_fingerprints import (
    validation_rule_constraint_matches as _validation_rule_constraint_matches,
)

_EVIDENCE_TRAIL_SCHEMA_VERSION = "1.1"
_FIELD_MANIFEST_PATH_RE = re.compile(r"^entities\.(?P<entity>[^.]+)\.fields\.(?P<field>[^.]+)$")
_SUPPORTED_PROVENANCE_VALUES = {"ai-accepted", "ai-edited"}
_SUPPORTED_SUGGESTION_TYPES = (
    "field",
    "validation",
    "rule",
    "cross_entity_rule",
    "mapping",
    "transform",
)
_PATH_SUPERSEDED_SUGGESTION_TYPES = {"field", "validation"}
_SCOPE_BY_SUGGESTION_TYPE = {
    "field": "fields",
    "validation": "validations",
    "rule": "rules",
    "cross_entity_rule": "cross_entity_rules",
    "mapping": "mappings",
    "transform": "transforms",
}
_FILE_CONTRACT_TYPES = {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE}
_HUMAN_AUTHORED_PROVENANCE = "human-authored"


class EvidenceTrailError(RuntimeError):
    """Raised when Studio cannot build a valid evidence-trail sidecar."""


@dataclass(frozen=True)
class EvidenceTrailBuildResult:
    payload: dict[str, Any]
    revision_id: str
    exported_at: str
    manifest_hash: str


def parse_field_manifest_path(manifest_path: str) -> tuple[str, str] | None:
    match = _FIELD_MANIFEST_PATH_RE.fullmatch(manifest_path.strip())
    if not match:
        return None
    return match.group("entity"), match.group("field")


def build_review_provenance(session: ProjectSession) -> dict[str, Any]:
    """Build the bounded Step 7 provenance view from current in-session state."""
    latest_entries = _latest_field_review_entries(session.ks_workspace_state.review_history)
    latest_entry_positions = _latest_field_review_positions(session.ks_workspace_state.review_history)
    evidence_by_key = {
        (link.suggestion_id, link.manifest_path): link
        for link in session.ks_workspace_state.evidence_links
        if parse_field_manifest_path(link.manifest_path) is not None
    }
    latest_linked_positions_by_manifest_path: dict[str, int] = {}
    for entry in latest_entries:
        if entry.status not in {"accepted", "edited"}:
            continue
        if entry.type != "field":
            continue
        if (entry.suggestion_id, entry.manifest_path) not in evidence_by_key:
            continue
        position = latest_entry_positions.get(entry.suggestion_id, -1)
        latest_linked_positions_by_manifest_path[entry.manifest_path] = max(
            latest_linked_positions_by_manifest_path.get(entry.manifest_path, -1),
            position,
        )

    entries: list[dict[str, Any]] = []
    warnings: list[str] = []
    no_evidence_count = 0

    for entry in latest_entries:
        manifest_parts = parse_field_manifest_path(entry.manifest_path)
        if manifest_parts is None:
            warnings.append(
                "Current KS provenance export supports field manifest paths only: "
                f"{entry.manifest_path}"
            )

        matching_link = evidence_by_key.get((entry.suggestion_id, entry.manifest_path))
        has_evidence = matching_link is not None
        is_superseded = (
            entry.status in {"accepted", "edited"}
            and not has_evidence
            and latest_linked_positions_by_manifest_path.get(entry.manifest_path, -1)
            > latest_entry_positions.get(entry.suggestion_id, -1)
        )
        if entry.status in {"accepted", "edited"} and not has_evidence and not is_superseded:
            no_evidence_count += 1

        if entry.status == "rejected":
            provenance_class = "rejected"
            evidence_label = "Not evidence-backed"
        elif matching_link is not None:
            provenance_class = matching_link.provenance
            evidence_label = "Evidence-backed"
        elif is_superseded:
            provenance_class = "superseded"
            evidence_label = "Superseded by newer linked review"
        else:
            provenance_class = "no-evidence"
            evidence_label = "Not evidence-backed"

        entries.append(
            {
                "suggestion_id": entry.suggestion_id,
                "manifest_path": entry.manifest_path,
                "status": entry.status,
                "reviewed_at": entry.reviewed_at,
                "provenance_class": provenance_class,
                "evidence_label": evidence_label,
                "has_evidence": has_evidence,
                "is_superseded": is_superseded,
                "unsupported_path": manifest_parts is None,
            }
        )

    return {
        "summary": {
            "accepted_count": sum(1 for entry in latest_entries if entry.status == "accepted"),
            "edited_count": sum(1 for entry in latest_entries if entry.status == "edited"),
            "rejected_count": sum(1 for entry in latest_entries if entry.status == "rejected"),
            "linked_evidence_count": len(evidence_by_key),
            "no_evidence_count": no_evidence_count,
        },
        "entries": entries,
        "warnings": warnings,
        "empty": len(entries) == 0,
    }


def build_evidence_trail(
    session: ProjectSession,
    *,
    manifest_yaml: str,
    export_path: str,
) -> EvidenceTrailBuildResult:
    """Build the Step 8 evidence-trail payload from current Studio workspace state."""
    revision_id = f"rev-{uuid4()}"
    exported_at = datetime.now(timezone.utc).isoformat()
    manifest_hash = f"sha256:{hashlib.sha256(manifest_yaml.encode('utf-8')).hexdigest()}"
    knowledge_assist_enabled = session.capabilities.knowledge_assist_enabled
    project_id = current_workspace_identity(session) if knowledge_assist_enabled else None
    typed_links: list[tuple[KSEvidenceLink, str]] = []
    skipped_links: list[str] = []
    no_evidence_count = 0
    if knowledge_assist_enabled:
        typed_links, skipped_links = _typed_supported_evidence_links(session)
        no_evidence_count = _supported_no_evidence_count(session, typed_links)

    # Deterministic, human-authored edge-contract evidence is independent of
    # Knowledge Assist: it never calls KS and is emitted even when KA is OFF.
    file_contract_links = _file_contract_evidence_links(session)
    xml_xsd_links = _xml_xsd_evidence_links(session)
    soap_wsdl_links = _soap_wsdl_evidence_links(session)

    payload: dict[str, Any] = {
        "schema_version": _EVIDENCE_TRAIL_SCHEMA_VERSION,
        "project_id": project_id,
        "manifest_revision_id": revision_id,
        "exported_at": exported_at,
        "evidence_links": [],
        "provenance_summary": {
            "human_authored": 0,
            "ai_accepted": 0,
            "ai_edited": 0,
            "no_evidence": no_evidence_count,
            "by_type": {suggestion_type: 0 for suggestion_type in _SUPPORTED_SUGGESTION_TYPES},
        },
    }
    if skipped_links:
        payload["warnings"] = skipped_links

    if typed_links:
        if not project_id:
            raise EvidenceTrailError(
                "Evidence-trail export cannot expand KS citations because the project "
                "does not have durable KS linkage."
            )

        try:
            with ks_client(
                allowed_roots=workspace_allowed_roots(session),
                db_path=workspace_db_path(session),
            ) as client:
                for link, suggestion_type in typed_links:
                    payload["evidence_links"].append(
                        _build_sidecar_evidence_link(client, project_id, session, link, suggestion_type)
                    )
        except KSUnavailableError as exc:
            raise EvidenceTrailError(
                f"Knowledge Server unavailable while expanding evidence-trail citations: {exc}"
            ) from exc
        except KSCallError as exc:
            raise EvidenceTrailError(
                f"Knowledge Server failed while expanding evidence-trail citations: "
                f"{exc.error_message}"
            ) from exc

    # Append deterministic edge-contract evidence after any Knowledge Assist links so KA link
    # ordering is preserved for existing consumers/tests.
    payload["evidence_links"].extend(file_contract_links)
    payload["evidence_links"].extend(xml_xsd_links)
    payload["evidence_links"].extend(soap_wsdl_links)
    _finalize_provenance_summary(payload)

    return EvidenceTrailBuildResult(
        payload=payload,
        revision_id=revision_id,
        exported_at=exported_at,
        manifest_hash=manifest_hash,
    )


def _finalize_provenance_summary(payload: dict[str, Any]) -> None:
    """Recompute provenance counts from the final evidence-link set.

    ``no_evidence`` is preserved as already computed from Knowledge Assist review
    state; the remaining counts are derived from the emitted evidence links so
    Knowledge Assist and human-authored file-contract evidence are counted
    consistently.
    """
    evidence_links = payload["evidence_links"]
    summary = payload["provenance_summary"]
    summary["human_authored"] = sum(
        1 for link in evidence_links if link.get("provenance") == _HUMAN_AUTHORED_PROVENANCE
    )
    summary["ai_accepted"] = sum(
        1 for link in evidence_links if link.get("provenance") == "ai-accepted"
    )
    summary["ai_edited"] = sum(
        1 for link in evidence_links if link.get("provenance") == "ai-edited"
    )
    summary["by_type"] = {
        suggestion_type: sum(
            1 for link in evidence_links if link.get("suggestion_type") == suggestion_type
        )
        for suggestion_type in _SUPPORTED_SUGGESTION_TYPES
    }


def _latest_field_review_entries(review_history: list[KSReviewHistoryEntry]) -> list[KSReviewHistoryEntry]:
    latest_entries: list[KSReviewHistoryEntry] = []
    seen_suggestion_ids: set[str] = set()

    for entry in reversed(review_history):
        if entry.type != "field" or entry.suggestion_id in seen_suggestion_ids:
            continue
        seen_suggestion_ids.add(entry.suggestion_id)
        latest_entries.append(entry)

    return latest_entries


def _latest_field_review_positions(review_history: list[KSReviewHistoryEntry]) -> dict[str, int]:
    positions: dict[str, int] = {}
    for index, entry in enumerate(review_history):
        if entry.type != "field":
            continue
        positions[entry.suggestion_id] = index
    return positions


def _latest_supported_review_entries(review_history: list[KSReviewHistoryEntry]) -> list[KSReviewHistoryEntry]:
    latest_entries: list[KSReviewHistoryEntry] = []
    seen_suggestion_ids: set[str] = set()

    for entry in reversed(review_history):
        if entry.type not in _SUPPORTED_SUGGESTION_TYPES or entry.suggestion_id in seen_suggestion_ids:
            continue
        seen_suggestion_ids.add(entry.suggestion_id)
        latest_entries.append(entry)

    return latest_entries


def _latest_supported_review_positions(review_history: list[KSReviewHistoryEntry]) -> dict[str, int]:
    positions: dict[str, int] = {}
    for index, entry in enumerate(review_history):
        if entry.type not in _SUPPORTED_SUGGESTION_TYPES:
            continue
        positions[entry.suggestion_id] = index
    return positions


def _typed_supported_evidence_links(session: ProjectSession) -> tuple[list[tuple[KSEvidenceLink, str]], list[str]]:
    latest_entries = _latest_supported_review_entries(session.ks_workspace_state.review_history)
    latest_by_suggestion_id = {entry.suggestion_id: entry for entry in latest_entries}
    latest_by_manifest_path: dict[str, KSReviewHistoryEntry] = {}
    for entry in reversed(session.ks_workspace_state.review_history):
        if entry.type not in _PATH_SUPERSEDED_SUGGESTION_TYPES or not entry.manifest_path:
            continue
        latest_by_manifest_path.setdefault(entry.manifest_path, entry)
    typed_links: list[tuple[KSEvidenceLink, str]] = []
    warnings: list[str] = []
    seen_keys: set[tuple[str, str]] = set()

    for link in session.ks_workspace_state.evidence_links:
        latest_for_path = latest_by_manifest_path.get(link.manifest_path)
        if latest_for_path is not None and latest_for_path.suggestion_id != link.suggestion_id:
            warnings.append(
                "Skipped stale evidence link superseded by a newer review entry: "
                f"{link.manifest_path}"
            )
            continue
        entry = latest_by_suggestion_id.get(link.suggestion_id)
        if entry is not None:
            if entry.manifest_path != link.manifest_path:
                warnings.append(
                    "Skipped stale evidence link whose manifest path no longer matches "
                    f"the latest review entry: {link.manifest_path}"
                )
                continue
            if entry.status not in {"accepted", "edited"}:
                continue
            if entry.type in _SUPPORTED_SUGGESTION_TYPES:
                if not _review_entry_artifact_exists(session, entry):
                    warnings.append(_artifact_absent_warning(entry))
                    continue
                typed_links.append((link, entry.type))
                seen_keys.add((link.suggestion_id, link.manifest_path))
                continue

        if parse_field_manifest_path(link.manifest_path) is not None:
            typed_links.append((link, "field"))
            seen_keys.add((link.suggestion_id, link.manifest_path))
            continue

        warnings.append(
            "Skipped unsupported evidence link without supported review history: "
            f"{link.manifest_path}"
        )

    for entry in reversed(list(latest_by_suggestion_id.values())):
        latest_for_path = latest_by_manifest_path.get(entry.manifest_path)
        if latest_for_path is not None and latest_for_path.suggestion_id != entry.suggestion_id:
            continue
        if entry.type not in {"mapping", "transform"} or entry.status not in {"accepted", "edited"}:
            continue
        key = (entry.suggestion_id, entry.manifest_path)
        if key in seen_keys:
            continue
        if not _review_entry_artifact_exists(session, entry):
            warnings.append(_artifact_absent_warning(entry))
            continue
        provenance = "ai-edited" if entry.status == "edited" else "ai-accepted"
        typed_links.append(
            (
                KSEvidenceLink(
                    manifest_path=entry.manifest_path,
                    suggestion_id=entry.suggestion_id,
                    provenance=provenance,
                ),
                entry.type,
            )
        )
        seen_keys.add(key)

    return typed_links, warnings


def _supported_no_evidence_count(
    session: ProjectSession,
    typed_links: list[tuple[KSEvidenceLink, str]],
) -> int:
    evidence_by_key = {
        (link.suggestion_id, link.manifest_path)
        for link, _suggestion_type in typed_links
    }
    latest_entries = _latest_supported_review_entries(session.ks_workspace_state.review_history)
    latest_entry_positions = _latest_supported_review_positions(session.ks_workspace_state.review_history)
    latest_by_manifest_path: dict[str, KSReviewHistoryEntry] = {}
    for entry in reversed(session.ks_workspace_state.review_history):
        if entry.type not in _PATH_SUPERSEDED_SUGGESTION_TYPES or not entry.manifest_path:
            continue
        latest_by_manifest_path.setdefault(entry.manifest_path, entry)
    latest_linked_positions_by_manifest_path: dict[str, int] = {}
    for entry in latest_entries:
        if entry.status not in {"accepted", "edited"}:
            continue
        if (entry.suggestion_id, entry.manifest_path) not in evidence_by_key:
            continue
        position = latest_entry_positions.get(entry.suggestion_id, -1)
        latest_linked_positions_by_manifest_path[entry.manifest_path] = max(
            latest_linked_positions_by_manifest_path.get(entry.manifest_path, -1),
            position,
        )

    no_evidence_count = 0
    for entry in latest_entries:
        latest_for_path = latest_by_manifest_path.get(entry.manifest_path)
        if latest_for_path is not None and latest_for_path.suggestion_id != entry.suggestion_id:
            continue
        if entry.status not in {"accepted", "edited"}:
            continue
        if (entry.suggestion_id, entry.manifest_path) in evidence_by_key:
            continue
        if not _review_entry_artifact_exists(session, entry):
            continue
        is_superseded = (
            entry.type == "field"
            and
            latest_linked_positions_by_manifest_path.get(entry.manifest_path, -1)
            > latest_entry_positions.get(entry.suggestion_id, -1)
        )
        if not is_superseded:
            no_evidence_count += 1
    return no_evidence_count


def _build_sidecar_evidence_link(
    client,
    project_id: str,
    session: ProjectSession,
    link: KSEvidenceLink,
    suggestion_type: str,
) -> dict[str, Any]:
    if link.provenance not in _SUPPORTED_PROVENANCE_VALUES:
        raise EvidenceTrailError(
            "Evidence-trail export supports accepted/edited Knowledge Assist links only. "
            f"Unsupported provenance '{link.provenance}' was found for {link.manifest_path}."
        )
    scope = _SCOPE_BY_SUGGESTION_TYPE.get(suggestion_type)
    if scope is None:
        raise EvidenceTrailError(
            f"Evidence-trail export does not support suggestion type '{suggestion_type}'."
        )

    result = client.get_suggestion_evidence_chain(
        project_id=project_id,
        scope=scope,
        suggestion_id=link.suggestion_id,
    )
    citations = _extract_citations(result, link.manifest_path)
    suggestion = result.get("suggestion")

    sidecar_link: dict[str, Any] = {
        "manifest_path": link.manifest_path,
        "suggestion_type": suggestion_type,
        "provenance": link.provenance,
        "suggestion_id": link.suggestion_id,
        "citations": citations,
    }
    confidence = None
    if isinstance(suggestion, dict):
        if suggestion_type == "field":
            confidence = suggestion.get("consistency_score", suggestion.get("confidence"))
        else:
            confidence = suggestion.get("confidence", suggestion.get("consistency_score"))
    if isinstance(confidence, (int, float)):
        sidecar_link["confidence"] = confidence
    if suggestion_type == "mapping":
        sidecar_link["decision"] = "edited" if link.provenance == "ai-edited" else "accepted"
        sidecar_link.update(
            _mapping_evidence_metadata(
                session,
                link.manifest_path,
                result,
                _latest_review_entry_for_link(session, link),
            )
        )
    elif suggestion_type == "transform":
        sidecar_link["decision"] = "edited" if link.provenance == "ai-edited" else "accepted"
        sidecar_link.update(
            _transform_evidence_metadata(
                session,
                link.manifest_path,
                result,
                _latest_review_entry_for_link(session, link),
            )
        )
    return sidecar_link


def _mapping_evidence_metadata(
    session: ProjectSession,
    manifest_path: str,
    result: dict[str, Any],
    review_entry: KSReviewHistoryEntry | None = None,
) -> dict[str, Any]:
    metadata = mapping_path_current_metadata(session, manifest_path, review_entry) or _parse_mapping_manifest_path(manifest_path)
    suggestion = result.get("suggestion")
    payload: dict[str, Any] = {}
    if isinstance(suggestion, dict):
        raw_payload = suggestion.get("payload")
        if isinstance(raw_payload, dict):
            payload = raw_payload
        else:
            payload = suggestion

    route_name = _first_text(metadata.get("route_name"), payload.get("route_name"))
    direction = _first_text(metadata.get("direction"), payload.get("direction"))
    source_field = _first_text(
        metadata.get("source_field"),
        payload.get("source_field"),
        payload.get("source"),
    )
    target_field = _first_text(
        metadata.get("target_field"),
        payload.get("target_field"),
        payload.get("target"),
    )

    output = {
        key: value
        for key, value in {
            "mapping_context": metadata.get("mapping_context"),
            "route_name": route_name,
            "direction": direction,
            "source_field": source_field,
            "target_field": target_field,
        }.items()
        if value
    }
    return output


def _transform_evidence_metadata(
    session: ProjectSession,
    manifest_path: str,
    result: dict[str, Any],
    review_entry: KSReviewHistoryEntry | None = None,
) -> dict[str, Any]:
    current_metadata = transform_path_current_metadata(session, manifest_path, review_entry)
    metadata = current_metadata or {}
    suggestion = result.get("suggestion")
    payload: dict[str, Any] = {}
    if current_metadata is None and isinstance(suggestion, dict):
        raw_payload = suggestion.get("payload")
        if isinstance(raw_payload, dict):
            payload = raw_payload
        else:
            payload = suggestion

    value_map = metadata.get("value_map")
    if current_metadata is None and value_map in ({}, None):
        value_map = payload.get("value_map")

    output = {
        key: value
        for key, value in {
            "route_name": _first_text(metadata.get("route_name"), payload.get("route_name")),
            "target_id": _first_text(metadata.get("target_id"), payload.get("target_id")),
            "direction": _first_text(metadata.get("direction"), payload.get("direction")),
            "source_field": _first_text(
                metadata.get("source"),
                metadata.get("source_field"),
                payload.get("source"),
                payload.get("source_field"),
            ),
            "target_field": _first_text(
                metadata.get("target"),
                metadata.get("target_field"),
                payload.get("target"),
                payload.get("target_field"),
            ),
            "default_value": _first_text(
                metadata.get("default_value"),
                payload.get("default_value"),
                payload.get("default"),
            ),
            "constant": _first_text(metadata.get("constant"), payload.get("constant")),
            "type_coercion": _first_text(metadata.get("type_coercion"), payload.get("type_coercion")),
        }.items()
        if value
    }
    if isinstance(value_map, dict) and value_map:
        output["value_map"] = {str(key): str(value) for key, value in value_map.items()}
    return output


def _latest_review_entry_for_link(
    session: ProjectSession,
    link: KSEvidenceLink,
) -> KSReviewHistoryEntry | None:
    for entry in reversed(session.ks_workspace_state.review_history):
        if (
            entry.suggestion_id == link.suggestion_id
            and entry.manifest_path == link.manifest_path
            and entry.type in _SUPPORTED_SUGGESTION_TYPES
        ):
            return entry
    return None


def _mapping_review_context(
    manifest_path: str,
    review_entry: KSReviewHistoryEntry | None,
) -> dict[str, str]:
    if review_entry is None:
        return {}

    parsed = _parse_mapping_manifest_path(manifest_path)
    raw_context = review_entry.review_context if isinstance(review_entry.review_context, dict) else {}
    raw_payload = review_entry.edited_payload if isinstance(review_entry.edited_payload, dict) else {}

    mapping_context = _first_text(
        raw_context.get("mapping_context"),
        raw_payload.get("mapping_context"),
        parsed.get("mapping_context"),
    )
    source_field = _first_text(
        raw_context.get("source_field"),
        raw_context.get("source"),
        raw_payload.get("source_field"),
        raw_payload.get("source"),
    )
    target_field = _first_text(
        raw_context.get("target_field"),
        raw_context.get("target"),
        raw_payload.get("target_field"),
        raw_payload.get("target"),
    )
    if not mapping_context or not source_field or not target_field:
        return {}

    return {
        key: value
        for key, value in {
            "mapping_context": mapping_context,
            "route_name": _first_text(raw_context.get("route_name"), raw_payload.get("route_name"), parsed.get("route_name")),
            "direction": _first_text(raw_context.get("direction"), raw_payload.get("direction"), parsed.get("direction")),
            "source_field": source_field,
            "target_field": target_field,
        }.items()
        if value
    }


def _mapping_context_current_metadata(
    session: ProjectSession,
    context: dict[str, str],
) -> dict[str, str] | None:
    source = context.get("source_field", "")
    target = context.get("target_field", "")
    if not source or not target:
        return None

    if context.get("mapping_context") == "passthrough":
        route_name = context.get("route_name", "")
        if route_name and session.passthrough_flow.upstream_operation_name != route_name:
            return None
        for transform in session.passthrough_flow.transforms:
            if transform.source == source and transform.target == target:
                return {
                    "mapping_context": "passthrough",
                    "route_name": session.passthrough_flow.upstream_operation_name or route_name,
                    "direction": "request",
                    "source_field": transform.source,
                    "target_field": transform.target,
                }
        return None

    if context.get("mapping_context") == "kafka":
        route_name = context.get("route_name", "")
        direction = context.get("direction", "request")
        for transform in session.kafka_route_transforms:
            if transform.route_name != route_name:
                continue
            rows = transform.response_mappings if direction == "response" else transform.mappings
            for row in rows:
                if row.source_field == source and row.target_field == target:
                    return {
                        "mapping_context": "kafka",
                        "route_name": transform.route_name,
                        "direction": direction,
                        "source_field": row.source_field,
                        "target_field": row.target_field,
                    }
        return None

    return None


def _transform_review_context(
    manifest_path: str,
    review_entry: KSReviewHistoryEntry | None,
) -> dict[str, Any]:
    if review_entry is None:
        return {}

    raw_context = review_entry.review_context if isinstance(review_entry.review_context, dict) else {}
    raw_payload = review_entry.edited_payload if isinstance(review_entry.edited_payload, dict) else {}
    route_name = _first_text(raw_context.get("route_name"), raw_payload.get("route_name"))
    target_id = _first_text(raw_context.get("target_id"), raw_payload.get("target_id"))
    direction = _first_text(raw_context.get("direction"), raw_payload.get("direction"))
    target = _first_text(
        raw_context.get("target"),
        raw_context.get("target_field"),
        raw_payload.get("target"),
        raw_payload.get("target_field"),
    )
    if not route_name or not target_id or direction not in {"request", "response"} or not target:
        return {}

    value_map = raw_context.get("value_map")
    if not isinstance(value_map, dict):
        value_map = raw_payload.get("value_map")
    if not isinstance(value_map, dict):
        value_map = {}

    return {
        "route_name": route_name,
        "target_id": target_id,
        "direction": direction,
        "source": _first_text(raw_context.get("source"), raw_context.get("source_field"), raw_payload.get("source"), raw_payload.get("source_field")),
        "target": target,
        "default_value": _nullable_text(raw_context.get("default_value"), raw_payload.get("default_value"), raw_payload.get("default")),
        "constant": _nullable_text(raw_context.get("constant"), raw_payload.get("constant")),
        "value_map": {str(key): str(value) for key, value in value_map.items()},
        "type_coercion": _nullable_text(raw_context.get("type_coercion"), raw_payload.get("type_coercion")),
    }


def _transform_row_metadata(row, *, route_name: str, target_id: str, direction: str) -> dict[str, Any]:
    return {
        "route_name": route_name,
        "target_id": target_id,
        "direction": direction,
        "source": row.source,
        "target": row.target,
        "default_value": row.default_value,
        "constant": row.constant,
        "value_map": dict(row.value_map),
        "type_coercion": row.type_coercion,
    }


def _transform_metadata_matches_row(context: dict[str, Any], metadata: dict[str, Any]) -> bool:
    return (
        context.get("route_name") == metadata.get("route_name")
        and context.get("target_id") == metadata.get("target_id")
        and context.get("direction") == metadata.get("direction")
        and context.get("source", "") == metadata.get("source", "")
        and context.get("target") == metadata.get("target")
        and context.get("default_value") == metadata.get("default_value")
        and context.get("constant") == metadata.get("constant")
        and (context.get("value_map") or {}) == (metadata.get("value_map") or {})
        and context.get("type_coercion") == metadata.get("type_coercion")
    )


def transform_path_current_metadata(
    session: ProjectSession,
    manifest_path: str,
    review_entry: KSReviewHistoryEntry | None = None,
) -> dict[str, Any] | None:
    """Return transform metadata only when the reviewed row is still present."""

    context = _transform_review_context(manifest_path, review_entry)
    if not context:
        return None

    for transform in session.kafka_route_transforms:
        if transform.route_name != context["route_name"]:
            continue
        for target_transform in transform.router_target_transforms:
            if target_transform.target_id != context["target_id"]:
                continue
            rows = (
                target_transform.response_transform_rows
                if context["direction"] == "response"
                else target_transform.request_transform_rows
            )
            for row in rows:
                metadata = _transform_row_metadata(
                    row,
                    route_name=transform.route_name,
                    target_id=target_transform.target_id,
                    direction=context["direction"],
                )
                if _transform_metadata_matches_row(context, metadata):
                    return metadata
    return None


def transform_path_exists_in_session(
    session: ProjectSession,
    manifest_path: str,
    review_entry: KSReviewHistoryEntry | None = None,
) -> bool:
    return transform_path_current_metadata(session, manifest_path, review_entry) is not None


def _review_entry_artifact_exists(session: ProjectSession, entry: KSReviewHistoryEntry) -> bool:
    if entry.type == "mapping":
        return mapping_path_exists_in_session(session, entry.manifest_path, entry)
    if entry.type == "transform":
        return transform_path_exists_in_session(session, entry.manifest_path, entry)
    if entry.type in {"rule", "cross_entity_rule"}:
        return _rule_review_entry_exists_in_session(session, entry)
    if entry.type == "validation":
        return _validation_review_entry_exists_in_session(session, entry)
    return True


def _rule_review_entry_exists_in_session(session: ProjectSession, entry: KSReviewHistoryEntry) -> bool:
    parts = [part for part in entry.manifest_path.strip().split(".") if part]
    if len(parts) < 4 or parts[0] != "rules":
        return True
    entity_name = parts[1]
    field_name = parts[2]
    rule_type = ".".join(parts[3:])
    return any(
        entity_rules.entity_name == entity_name
        and any(
            rule.field == field_name
            and rule.type == rule_type
            and rule.generated_by_ka
            and rule.suggestion_id == entry.suggestion_id
            for rule in entity_rules.rules
        )
        for entity_rules in session.entity_rules
    )


def _validation_review_entry_exists_in_session(session: ProjectSession, entry: KSReviewHistoryEntry) -> bool:
    parts = [part for part in entry.manifest_path.strip().split(".") if part]
    if len(parts) < 6 or parts[0] != "entities" or parts[2] != "fields":
        return True
    entity_name = parts[1]
    field_name = parts[3]
    validation_type = parts[-1]
    context = entry.review_context if isinstance(entry.review_context, dict) else {}
    expected_fingerprint = str(context.get("constraint_fingerprint") or "").strip()
    return any(
        entity_rules.entity_name == entity_name
        and any(
            rule.field == field_name
            and rule.type == validation_type
            and rule.generated_by_ka
            and rule.suggestion_id == entry.suggestion_id
            and _validation_rule_constraint_matches(rule, expected_fingerprint)
            for rule in entity_rules.rules
        )
        for entity_rules in session.entity_rules
    )


def _artifact_absent_warning(entry: KSReviewHistoryEntry) -> str:
    if entry.type == "mapping":
        return (
            "Skipped mapping evidence because the current transform row is absent: "
            f"{entry.manifest_path}"
        )
    if entry.type in {"rule", "cross_entity_rule", "validation"}:
        return (
            f"Skipped {entry.type} evidence because the current generated rule is absent: "
            f"{entry.manifest_path}"
        )
    return (
        f"Skipped {entry.type} evidence because the current generated artifact is absent: "
        f"{entry.manifest_path}"
    )


def _mapping_metadata_needs_review_context(metadata: dict[str, str]) -> bool:
    return any("." in metadata.get(key, "") for key in ("route_name", "source_field", "target_field"))


def mapping_path_current_metadata(
    session: ProjectSession,
    manifest_path: str,
    review_entry: KSReviewHistoryEntry | None = None,
) -> dict[str, str] | None:
    """Return mapping metadata only when the review path matches a current row.

    Mapping source/target field paths may contain dots, so this helper compares
    against persisted review context when available. Legacy raw-path matching is
    retained only for unambiguous paths because dot-concatenated source/target
    fields can otherwise collide with a different current row.
    """

    review_context = _mapping_review_context(manifest_path, review_entry)
    if review_context:
        return _mapping_context_current_metadata(session, review_context)

    raw_path = manifest_path.strip()
    for transform in session.passthrough_flow.transforms:
        route_name = session.passthrough_flow.upstream_operation_name or ""
        candidates = []
        if route_name:
            candidates.append(
                f"passthrough.{route_name}.transforms.{transform.source}.{transform.target}"
            )
        candidates.append(f"mappings.passthrough.{transform.source}.{transform.target}")
        if raw_path in candidates:
            metadata = {
                "mapping_context": "passthrough",
                "route_name": route_name,
                "direction": "request",
                "source_field": transform.source,
                "target_field": transform.target,
            }
            return None if _mapping_metadata_needs_review_context(metadata) else metadata

    for transform in session.kafka_route_transforms:
        for direction, rows in (
            ("request", transform.mappings),
            ("response", transform.response_mappings),
        ):
            for row in rows:
                candidates = [
                    f"async_routes.{transform.route_name}.transform_mapping.{direction}.{row.source_field}.{row.target_field}",
                    f"mappings.kafka.{transform.route_name}.{direction}.{row.source_field}.{row.target_field}",
                ]
                if raw_path in candidates:
                    metadata = {
                        "mapping_context": "kafka",
                        "route_name": transform.route_name,
                        "direction": direction,
                        "source_field": row.source_field,
                        "target_field": row.target_field,
                    }
                    return None if _mapping_metadata_needs_review_context(metadata) else metadata
    return None


def _parse_mapping_manifest_path(manifest_path: str) -> dict[str, str]:
    parts = [part for part in manifest_path.strip().split(".") if part]
    if len(parts) >= 5 and parts[0] == "passthrough" and parts[2] == "transforms":
        return {
            "mapping_context": "passthrough",
            "route_name": parts[1],
            "direction": "request",
            "source_field": parts[3],
            "target_field": ".".join(parts[4:]),
        }
    if len(parts) >= 6 and parts[0] == "async_routes" and parts[2] == "transform_mapping":
        return {
            "mapping_context": "kafka",
            "route_name": parts[1],
            "direction": parts[3],
            "source_field": parts[4],
            "target_field": ".".join(parts[5:]),
        }
    if len(parts) >= 4 and parts[0] == "mappings" and parts[1] == "passthrough":
        return {
            "mapping_context": "passthrough",
            "direction": "request",
            "source_field": parts[2],
            "target_field": ".".join(parts[3:]),
        }
    if len(parts) >= 6 and parts[0] == "mappings" and parts[1] == "kafka":
        return {
            "mapping_context": "kafka",
            "route_name": parts[2],
            "direction": parts[3],
            "source_field": parts[4],
            "target_field": ".".join(parts[5:]),
        }
    return {"mapping_context": "mapping"}


def mapping_path_exists_in_session(
    session: ProjectSession,
    manifest_path: str,
    review_entry: KSReviewHistoryEntry | None = None,
) -> bool:
    return mapping_path_current_metadata(session, manifest_path, review_entry) is not None


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _nullable_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        return text if text else None
    return None


def _extract_citations(result: dict[str, Any], manifest_path: str) -> list[dict[str, Any]]:
    evidence_chunks = result.get("evidence_chunks")
    if not isinstance(evidence_chunks, list) or not evidence_chunks:
        raise EvidenceTrailError(
            "Evidence-trail export could not resolve citations for "
            f"{manifest_path} from the current Knowledge Server workspace."
        )

    citations: list[dict[str, Any]] = []
    for chunk in evidence_chunks:
        citation = chunk.get("citation") if isinstance(chunk, dict) else None
        if not isinstance(citation, dict):
            raise EvidenceTrailError(
                "Evidence-trail export received malformed citation data for "
                f"{manifest_path} from the current Knowledge Server workspace."
            )
        citations.append(
            {
                key: citation[key]
                for key in (
                    "document_id",
                    "document_name",
                    "chunk_id",
                    "content_hash",
                    "parser_version",
                    "page",
                    "section",
                    "heading",
                    "char_offset",
                    "snippet",
                )
                if key in citation and citation[key] is not None
            }
        )

    if not citations:
        raise EvidenceTrailError(
            f"Evidence-trail export received no usable citations for {manifest_path}."
        )
    return citations


# ---------------------------------------------------------------------------
# Deterministic file-contract evidence (fixed-width and CSV)
# ---------------------------------------------------------------------------
#
# These records are human-authored Studio decisions derived only from the
# exported package model (layout/spec content, field mappings, and samples).
# They never call Knowledge Server and are emitted regardless of the Knowledge
# Assist toggle.  All paths are package-relative; absolute/URL paths are
# dropped.  Unknown optional metadata is omitted rather than invented.


def _file_contract_evidence_links(session: ProjectSession) -> list[dict[str, Any]]:
    """Build deterministic file-contract evidence links for the package.

    Upstream interfaces are inbound (file -> canonical); downstream interfaces
    are outbound (canonical -> file).  Only ``file-fixed-width`` and
    ``file-csv`` interfaces produce records.  Data handoffs are intentionally
    excluded: file/XML/SOAP edge contracts are never routed through
    ``data_handoffs[]``.
    """
    links: list[dict[str, Any]] = []
    for iface in session.upstream_interfaces:
        if iface.type in _FILE_CONTRACT_TYPES:
            links.extend(_file_contract_data_field_links(iface, direction="upstream"))
            links.extend(_file_contract_trailer_links(iface, direction="upstream"))
    for iface in session.downstream_interfaces:
        if iface.type in _FILE_CONTRACT_TYPES:
            links.extend(_file_contract_data_field_links(iface, direction="downstream"))
            links.extend(_file_contract_trailer_links(iface, direction="downstream"))
    return links


def _file_contract_data_field_links(iface: Any, *, direction: str) -> list[dict[str, Any]]:
    field_mappings = getattr(iface, "field_mappings", None) or []
    if not field_mappings:
        return []

    # Keep the sidecar aligned with exported artifacts. Upstream file mapping
    # YAML (and its manifest `mapping:` reference) is written only when both
    # field_mappings and entity_name are present (package_writer /
    # manifest_generator). Without entity_name no canonical mapping is exported,
    # so emitting mapping-derived field evidence with a canonical `target_path`
    # would describe an artifact the package does not contain. Downstream file
    # mappings export on field_mappings alone, so they are unaffected.
    if direction == "upstream" and not str(getattr(iface, "entity_name", "") or "").strip():
        return []

    layout_by_field, delimiter = _file_field_layout(iface)
    file_format = "fixed-width" if iface.type == FILE_FIXED_WIDTH_TYPE else "csv"
    artifact_type = "fixed_width_layout" if iface.type == FILE_FIXED_WIDTH_TYPE else "csv_layout"
    interface_direction = "upstream" if direction == "upstream" else "downstream"
    flow_direction = "inbound" if direction == "upstream" else "outbound"
    source_artifact = _safe_package_path(getattr(iface, "spec", None))
    sample_artifact = _file_sample_artifact(iface)

    links: list[dict[str, Any]] = []
    for mapping in field_mappings:
        if direction == "upstream":
            file_field = str(getattr(mapping, "source", "") or "").strip()
            canonical = _qualify_canonical(getattr(mapping, "target", ""), getattr(iface, "entity_name", None))
            source_path, target_path = file_field, canonical
        else:
            file_field = str(getattr(mapping, "target", "") or "").strip()
            canonical = str(getattr(mapping, "source", "") or "").strip()
            source_path, target_path = canonical, file_field
        if not file_field:
            continue

        layout = layout_by_field.get(file_field, {})
        metadata = _compact_metadata(
            {
                "source_artifact": source_artifact,
                "artifact_type": artifact_type,
                "contract_name": iface.name,
                "contract_type": iface.type,
                "interface_name": iface.name,
                "interface_direction": interface_direction,
                "file_format": file_format,
                "layout_field": file_field,
                "record_type": "data",
                "field_position": layout.get("field_position"),
                "field_length": layout.get("field_length"),
                "csv_column_index": layout.get("csv_column_index"),
                "delimiter": delimiter if file_format == "csv" else None,
                "direction": flow_direction,
                "source_path": source_path,
                "target_path": target_path,
                "sample_artifact": sample_artifact,
            }
        )
        links.append(
            {
                "manifest_path": f"{interface_direction}_interfaces.{iface.name}.layout.{file_field}",
                "suggestion_type": "field",
                "provenance": _HUMAN_AUTHORED_PROVENANCE,
                "citations": [],
                "metadata": metadata,
            }
        )
    return links


def _file_contract_trailer_links(iface: Any, *, direction: str) -> list[dict[str, Any]]:
    """Emit trailer/control validation evidence only when explicitly defined.

    A trailer record is emitted for a trailer field only when the pasted
    layout/spec content carries an explicit control ``value_source`` for that
    field (via ``control_mappings.trailer`` or a ``value_source`` key on the
    trailer field).  Contracts that do not define a trailer, or define a trailer
    without a control value source, produce no trailer evidence.
    """
    spec_content = getattr(iface, "spec_content", None)
    if not spec_content:
        return []
    try:
        payload = yaml.safe_load(spec_content)
    except yaml.YAMLError:
        return []
    if not isinstance(payload, dict):
        return []
    record_types = payload.get("record_types")
    trailer = record_types.get("trailer") if isinstance(record_types, dict) else None
    if not isinstance(trailer, dict):
        return []
    trailer_fields = trailer.get("fields")
    if not isinstance(trailer_fields, list):
        return []

    control_lookup: dict[str, dict[str, Any]] = {}
    control_mappings = payload.get("control_mappings")
    if isinstance(control_mappings, dict):
        trailer_controls = control_mappings.get("trailer")
        if isinstance(trailer_controls, list):
            for entry in trailer_controls:
                if isinstance(entry, dict):
                    source = str(entry.get("source") or "").strip()
                    if source:
                        control_lookup[source] = entry

    file_format = "fixed-width" if iface.type == FILE_FIXED_WIDTH_TYPE else "csv"
    artifact_type = "fixed_width_layout" if iface.type == FILE_FIXED_WIDTH_TYPE else "csv_layout"
    interface_direction = "upstream" if direction == "upstream" else "downstream"
    flow_direction = "inbound" if direction == "upstream" else "outbound"
    source_artifact = _safe_package_path(getattr(iface, "spec", None))
    delimiter = _file_field_layout(iface)[1] if file_format == "csv" else None

    links: list[dict[str, Any]] = []
    for field in trailer_fields:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name") or "").strip()
        if not name:
            continue
        control = control_lookup.get(name, {})
        value_source = str(control.get("value_source") or field.get("value_source") or "").strip()
        if not value_source:
            # Never invent control semantics for a trailer field with no source.
            continue
        metadata = _compact_metadata(
            {
                "source_artifact": source_artifact,
                "artifact_type": artifact_type,
                "contract_name": iface.name,
                "contract_type": iface.type,
                "interface_name": iface.name,
                "interface_direction": interface_direction,
                "mapping_scope": "trailer_validation",
                "file_format": file_format,
                "record_type": "trailer",
                "layout_field": name,
                "field_position": _optional_int(field.get("position")) if file_format == "fixed-width" else None,
                "field_length": _optional_int(field.get("length")) if file_format == "fixed-width" else None,
                "csv_column_index": _optional_int(field.get("column")) if file_format == "csv" else None,
                "delimiter": delimiter if file_format == "csv" else None,
                "value_source": value_source,
                "decimal_format": _clean_str(field.get("decimal_format")),
                "type_coercion": _clean_str(control.get("type_coercion")),
                "direction": flow_direction,
            }
        )
        links.append(
            {
                "manifest_path": f"{interface_direction}_interfaces.{iface.name}.trailer.{name}",
                "suggestion_type": "validation",
                "provenance": _HUMAN_AUTHORED_PROVENANCE,
                "citations": [],
                "metadata": metadata,
            }
        )
    return links


def _file_field_layout(iface: Any) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Index data-record layout details by file field name.

    Returns ``(by_field, delimiter)`` where ``by_field`` maps a file field name
    to its available positional metadata (``field_position``/``field_length``
    for fixed-width or ``csv_column_index`` for CSV) and ``delimiter`` is the
    CSV delimiter when applicable.  Reuses the deterministic file-layout
    inspector for pasted spec content and the downstream ``layout_fields`` model
    for fixed-width layouts authored structurally.
    """
    by_field: dict[str, dict[str, Any]] = {}
    delimiter: str | None = None

    spec_content = getattr(iface, "spec_content", None)
    if spec_content:
        inspected = inspect_file_contract_layout(iface.type, spec_content)
        if inspected.get("ok"):
            layout = inspected.get("layout") or {}
            if iface.type == FILE_FIXED_WIDTH_TYPE:
                for field in layout.get("fields") or []:
                    name = _clean_str(field.get("name"))
                    if not name:
                        continue
                    entry: dict[str, Any] = {}
                    if field.get("start"):
                        entry["field_position"] = field["start"]
                    if field.get("length"):
                        entry["field_length"] = field["length"]
                    by_field[name] = entry
            else:
                raw_delimiter = layout.get("delimiter")
                if isinstance(raw_delimiter, str) and raw_delimiter:
                    delimiter = raw_delimiter
                for field in layout.get("fields") or []:
                    name = _clean_str(field.get("name"))
                    if not name:
                        continue
                    entry = {}
                    if field.get("column"):
                        entry["csv_column_index"] = field["column"]
                    by_field[name] = entry

    if iface.type == FILE_FIXED_WIDTH_TYPE:
        for layout_field in getattr(iface, "layout_fields", None) or []:
            name = _clean_str(getattr(layout_field, "name", None))
            if not name:
                continue
            entry = by_field.setdefault(name, {})
            if "field_position" not in entry and getattr(layout_field, "start", None):
                entry["field_position"] = layout_field.start
            if "field_length" not in entry and getattr(layout_field, "length", None):
                entry["field_length"] = layout_field.length

    return by_field, delimiter


def _file_sample_artifact(iface: Any) -> str | None:
    """Return the package-relative sample path only when a sample is written."""
    if not getattr(iface, "sample_content", None):
        return None
    samples = getattr(iface, "samples", None) or []
    if samples:
        return _safe_package_path(samples[0])
    return _safe_package_path(getattr(iface, "sample_path", None))


# ---------------------------------------------------------------------------
# Deterministic XML/XSD edge-contract evidence
# ---------------------------------------------------------------------------
#
# These records describe reviewed XML/XSD contract metadata and explicit
# XML/canonical mappings that Studio already exports.  They are human-authored,
# package-local, and never require Knowledge Server.  Mapping records are
# emitted only when the corresponding mapping YAML is exportable.


def _xml_xsd_evidence_links(session: ProjectSession) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for iface in session.upstream_interfaces:
        if iface.type == XML_XSD_TYPE:
            links.extend(_xml_xsd_interface_links(iface, direction="upstream"))
    for iface in session.downstream_interfaces:
        if iface.type == XML_XSD_TYPE:
            links.extend(_xml_xsd_interface_links(iface, direction="downstream"))
    return links


def _xml_xsd_interface_links(iface: Any, *, direction: str) -> list[dict[str, Any]]:
    source_artifact = _xml_xsd_artifact_path(iface)
    root_element = _clean_str(getattr(iface, "root_element", None))
    if not source_artifact or not root_element:
        # Keep sidecar aligned with manifest export: incomplete XML contracts
        # are skipped/blocked elsewhere and should not produce evidence claims.
        return []

    interface_direction = "upstream" if direction == "upstream" else "downstream"
    mapping_scope = "inbound" if direction == "upstream" else "outbound"
    sample_artifact = _xml_sample_artifact(iface)
    common_metadata = {
        "source_artifact": source_artifact,
        "artifact_type": "xsd",
        "contract_name": iface.name,
        "contract_type": iface.type,
        "interface_name": iface.name,
        "interface_direction": interface_direction,
        "mapping_scope": mapping_scope,
        "xml_root": root_element,
        "namespace": _clean_str(getattr(iface, "namespace", None)),
        "xsd_path": source_artifact,
        "sample_artifact": sample_artifact,
        "sample_path": sample_artifact,
    }

    links: list[dict[str, Any]] = [
        {
            "manifest_path": f"{interface_direction}_interfaces.{iface.name}.xsd.{root_element}",
            "suggestion_type": "validation",
            "provenance": _HUMAN_AUTHORED_PROVENANCE,
            "citations": [],
            "metadata": _compact_metadata(
                {
                    **common_metadata,
                    "source_path": source_artifact,
                }
            ),
        }
    ]

    field_mappings = getattr(iface, "field_mappings", None) or []
    entity_name = _clean_str(getattr(iface, "entity_name", None))
    mapping_artifact = _xml_mapping_artifact(iface, direction=direction)
    if not field_mappings or not entity_name or not mapping_artifact:
        return links

    for mapping in field_mappings:
        if direction == "upstream":
            xml_path = _clean_str(getattr(mapping, "source", None))
            canonical_path = _qualify_canonical(getattr(mapping, "target", None), entity_name)
            source_path, target_path = xml_path, canonical_path
        else:
            canonical_path = _qualify_canonical(getattr(mapping, "source", None), entity_name)
            xml_path = _clean_str(getattr(mapping, "target", None))
            source_path, target_path = canonical_path, xml_path
        if not xml_path or not canonical_path:
            continue

        links.append(
            {
                "manifest_path": (
                    f"{interface_direction}_interfaces.{iface.name}.mappings."
                    f"{_evidence_path_token(source_path)}.{_evidence_path_token(target_path)}"
                ),
                "suggestion_type": "mapping",
                "provenance": _HUMAN_AUTHORED_PROVENANCE,
                "citations": [],
                "metadata": _compact_metadata(
                    {
                        **common_metadata,
                        "source_path": source_path,
                        "target_path": target_path,
                        "xpath": xml_path,
                        "xml_field_kind": _xml_field_kind(xml_path, root_element=root_element),
                        "sample_xpath": xml_path if sample_artifact else None,
                    }
                ),
            }
        )
    return links


def _xml_xsd_artifact_path(iface: Any) -> str | None:
    return _safe_package_path(getattr(iface, "xsd_path", None)) or _safe_package_path(
        getattr(iface, "spec", None)
    )


def _xml_sample_artifact(iface: Any) -> str | None:
    if not getattr(iface, "sample_content", None):
        return None
    return _safe_package_path(getattr(iface, "sample_path", None))


def _xml_mapping_artifact(iface: Any, *, direction: str) -> str | None:
    if not (getattr(iface, "field_mappings", None) or []):
        return None
    if not _clean_str(getattr(iface, "entity_name", None)):
        return None
    explicit = _safe_package_path(getattr(iface, "mapping_path", None))
    if explicit:
        return explicit
    if direction == "upstream":
        return default_upstream_xml_mapping_path(iface.name)
    return default_downstream_xml_mapping_path(iface.name)


def _xml_field_kind(xpath: str, *, root_element: str | None = None) -> str:
    text = xpath.strip()
    normalized = text.strip("/")
    root = (root_element or "").strip().strip("/")
    if root and normalized == root:
        return "root"
    if normalized.startswith("@") or "/@" in text:
        return "attribute"
    return "element"


def _evidence_path_token(value: Any) -> str:
    text = str(value or "").strip().strip("/")
    text = text.replace("/@", "/attr-")
    token = re.sub(r"[^A-Za-z0-9_-]+", "-", text)
    token = re.sub(r"-+", "-", token).strip("-")
    return token or "unknown"


# ---------------------------------------------------------------------------
# Deterministic SOAP/WSDL edge-contract evidence
# ---------------------------------------------------------------------------
#
# These records describe reviewed WSDL operation selections and explicit
# SOAP/canonical mappings that Studio already exports. Adapter-only mappings
# produce operation validation evidence only; canonical records are emitted
# only when the exported operation mapping YAML carries canonical configuration.


def _soap_wsdl_evidence_links(session: ProjectSession) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for iface in session.upstream_interfaces:
        if iface.type == SOAP_WSDL_TYPE:
            links.extend(_soap_wsdl_interface_links(iface, direction="upstream"))
    for iface in session.downstream_interfaces:
        if iface.type == SOAP_WSDL_TYPE:
            links.extend(_soap_wsdl_interface_links(iface, direction="downstream"))
    return links


def _soap_wsdl_interface_links(iface: Any, *, direction: str) -> list[dict[str, Any]]:
    source_artifact = _soap_wsdl_artifact_path(iface)
    operation = _clean_str(getattr(iface, "selected_operation_name", None))
    mapping_artifact = _soap_operation_mapping_artifact(iface)
    if not source_artifact or not operation or not mapping_artifact:
        return []

    interface_direction = "upstream" if direction == "upstream" else "downstream"
    flow_scope = "inbound" if direction == "upstream" else "outbound"
    sample_artifact = _soap_sample_artifact(iface)
    common_metadata = {
        "source_artifact": source_artifact,
        "artifact_type": "wsdl",
        "contract_name": iface.name,
        "contract_type": iface.type,
        "interface_name": iface.name,
        "interface_direction": interface_direction,
        "mapping_scope": flow_scope,
        "sample_artifact": sample_artifact,
        "sample_path": sample_artifact,
        "namespace": _clean_str(getattr(iface, "namespace", None)),
        "operation_name": operation,
        "wsdl_service": _clean_str(getattr(iface, "service", None)),
        "wsdl_port": _clean_str(getattr(iface, "port", None)),
        "wsdl_binding": _clean_str(getattr(iface, "binding", None)),
        "wsdl_operation": operation,
        "mapping_artifact": mapping_artifact,
    }

    links: list[dict[str, Any]] = [
        {
            "manifest_path": f"{interface_direction}_interfaces.{iface.name}.soap.operation.{_evidence_path_token(operation)}",
            "suggestion_type": "validation",
            "provenance": _HUMAN_AUTHORED_PROVENANCE,
            "citations": [],
            "metadata": _compact_metadata(common_metadata),
        }
    ]

    mode = _clean_str(getattr(iface, "soap_operation_mode", None)) or "adapter_only"
    if mode != SOAP_MAPPING_MODE_CANONICAL:
        return links

    if direction == "upstream":
        links.extend(
            _soap_upstream_canonical_links(
                iface,
                operation=operation,
                common_metadata=common_metadata,
            )
        )
    else:
        links.extend(
            _soap_downstream_canonical_links(
                iface,
                operation=operation,
                common_metadata=common_metadata,
            )
        )
    return links


def _soap_upstream_canonical_links(
    iface: Any,
    *,
    operation: str,
    common_metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    config = getattr(iface, "soap_canonical_operation", None)
    if config is None:
        return []

    entity = _clean_str(getattr(config, "entity", None))
    lookup_field = _clean_str(getattr(config, "lookup_field", None))
    request_path = _clean_str(getattr(config, "request_path", None))
    if not entity or not lookup_field or not request_path:
        return []
    canonical_lookup = _qualify_canonical(lookup_field, entity)

    links: list[dict[str, Any]] = [
        _soap_lookup_field_link(
            iface,
            common_metadata=common_metadata,
            operation=operation,
            direction="upstream",
            source_path=request_path,
            target_path=canonical_lookup,
            soap_body_path=request_path,
        ),
        _soap_mapping_link(
            iface,
            common_metadata=common_metadata,
            operation=operation,
            direction="upstream",
            mapping_scope="request",
            source_path=request_path,
            target_path=canonical_lookup,
            soap_body_path=request_path,
        ),
    ]

    for mapping in getattr(config, "response_mappings", None) or []:
        source_path = _clean_str(getattr(mapping, "source", None))
        target_path = _clean_str(getattr(mapping, "target_path", None))
        if not source_path or not target_path:
            continue
        links.append(
            _soap_mapping_link(
                iface,
                common_metadata=common_metadata,
                operation=operation,
                direction="upstream",
                mapping_scope="response",
                source_path=source_path,
                target_path=target_path,
                soap_body_path=target_path,
            )
        )

    fault_name = _clean_str(getattr(config, "not_found_fault", None))
    if fault_name:
        links.append(
            {
                "manifest_path": (
                    f"upstream_interfaces.{iface.name}.soap.fault."
                    f"{_evidence_path_token(operation)}.{_evidence_path_token(fault_name)}"
                ),
                "suggestion_type": "validation",
                "provenance": _HUMAN_AUTHORED_PROVENANCE,
                "citations": [],
                "metadata": _compact_metadata(
                    {
                        **common_metadata,
                        "mapping_scope": "fault",
                        "source_path": canonical_lookup,
                        "target_path": fault_name,
                        "soap_fault": fault_name,
                    }
                ),
            }
        )
    return links


def _soap_downstream_canonical_links(
    iface: Any,
    *,
    operation: str,
    common_metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    config = getattr(iface, "soap_canonical_invocation", None)
    if config is None:
        return []

    entity = _clean_str(getattr(config, "entity", None))
    lookup_field = _clean_str(getattr(config, "lookup_field", None))
    request_field = _clean_str(getattr(config, "request_field", None)) or "id"
    if not entity or not lookup_field:
        return []
    canonical_lookup = _qualify_canonical(lookup_field, entity)

    links: list[dict[str, Any]] = [
        _soap_lookup_field_link(
            iface,
            common_metadata=common_metadata,
            operation=operation,
            direction="downstream",
            source_path=request_field,
            target_path=canonical_lookup,
            soap_body_path=None,
        )
    ]

    for mapping in getattr(config, "request_mappings", None) or []:
        source_path = _clean_str(getattr(mapping, "source", None))
        target_path = _clean_str(getattr(mapping, "target_path", None))
        if not source_path or not target_path:
            continue
        links.append(
            _soap_mapping_link(
                iface,
                common_metadata=common_metadata,
                operation=operation,
                direction="downstream",
                mapping_scope="request",
                source_path=source_path,
                target_path=target_path,
                soap_body_path=target_path,
            )
        )

    for mapping in getattr(config, "response_mappings", None) or []:
        source_path = _clean_str(getattr(mapping, "source_path", None))
        target_path = _clean_str(getattr(mapping, "target", None))
        if not source_path or not target_path:
            continue
        links.append(
            _soap_mapping_link(
                iface,
                common_metadata=common_metadata,
                operation=operation,
                direction="downstream",
                mapping_scope="response",
                source_path=source_path,
                target_path=target_path,
                soap_body_path=source_path,
            )
        )
    return links


def _soap_lookup_field_link(
    iface: Any,
    *,
    common_metadata: dict[str, Any],
    operation: str,
    direction: str,
    source_path: str,
    target_path: str,
    soap_body_path: str | None,
) -> dict[str, Any]:
    interface_direction = "upstream" if direction == "upstream" else "downstream"
    metadata: dict[str, Any] = {
        **common_metadata,
        "mapping_scope": "lookup",
        "source_path": source_path,
        "target_path": target_path,
        "soap_body_path": soap_body_path,
    }
    return {
        "manifest_path": (
            f"{interface_direction}_interfaces.{iface.name}.soap.lookup."
            f"{_evidence_path_token(operation)}.{_evidence_path_token(target_path)}"
        ),
        "suggestion_type": "field",
        "provenance": _HUMAN_AUTHORED_PROVENANCE,
        "citations": [],
        "metadata": _compact_metadata(metadata),
    }


def _soap_mapping_link(
    iface: Any,
    *,
    common_metadata: dict[str, Any],
    operation: str,
    direction: str,
    mapping_scope: str,
    source_path: str,
    target_path: str,
    soap_body_path: str | None,
) -> dict[str, Any]:
    interface_direction = "upstream" if direction == "upstream" else "downstream"
    metadata: dict[str, Any] = {
        **common_metadata,
        "mapping_scope": mapping_scope,
        "source_path": source_path,
        "target_path": target_path,
        "soap_body_path": soap_body_path,
    }
    return {
        "manifest_path": (
            f"{interface_direction}_interfaces.{iface.name}.soap.{mapping_scope}."
            f"{_evidence_path_token(operation)}.{_evidence_path_token(source_path)}."
            f"{_evidence_path_token(target_path)}"
        ),
        "suggestion_type": "mapping",
        "provenance": _HUMAN_AUTHORED_PROVENANCE,
        "citations": [],
        "metadata": _compact_metadata(metadata),
    }


def _soap_wsdl_artifact_path(iface: Any) -> str | None:
    return _safe_package_path(getattr(iface, "wsdl_path", None)) or _safe_package_path(
        getattr(iface, "spec", None)
    )


def _soap_sample_artifact(iface: Any) -> str | None:
    if not getattr(iface, "sample_content", None):
        return None
    return _safe_package_path(getattr(iface, "sample_path", None))


def _soap_operation_mapping_artifact(iface: Any) -> str | None:
    if not _clean_str(getattr(iface, "selected_operation_name", None)):
        return None
    return _safe_package_path(getattr(iface, "mapping_path", None)) or default_soap_operation_mapping_path(
        iface.name
    )


def _qualify_canonical(target: Any, entity: Any) -> str:
    text = str(target or "").strip()
    if not text:
        return ""
    entity_name = str(entity or "").strip()
    if entity_name and "." not in text:
        return f"{entity_name}.{text}"
    return text


def _safe_package_path(value: Any) -> str | None:
    """Return a normalized package-relative path, or None for empty/absolute/URL."""
    try:
        return clean_package_path(value)
    except ValueError:
        return None


def _compact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Drop unknown (None/blank) optional metadata while preserving order."""
    compact: dict[str, Any] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        compact[key] = value
    return compact


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
