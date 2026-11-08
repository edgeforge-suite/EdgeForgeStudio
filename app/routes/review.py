"""Step 7 — Review + Completeness Report."""

from __future__ import annotations

import re
from difflib import unified_diff
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.paths import TEMPLATE_DIR
from app.services import identity_roles, readiness_view
from app.services.assist_service import AssistService
from app.services.completeness_service import CompletenessReport, build_completeness_report
from app.services.edge_contracts import (
    EDGE_CONTRACT_TYPES,
    FILE_CSV_TYPE,
    FILE_FIXED_WIDTH_TYPE,
    SOAP_WSDL_TYPE,
    XML_XSD_TYPE,
    _safe_persistence_fields,
)
from app.services.evidence_trail import (
    build_review_provenance,
    mapping_path_exists_in_session,
    transform_path_exists_in_session,
)
from app.services.identity_roles import identity_role_decision_entries
from app.services.manifest_generator import generate_manifest_yaml
from app.services.nav_context import build_nav_context
from app.services.path_resolver import (
    PathResolutionError,
    contain_under_session_workspace,
    expand_user_path,
)
from app.services.rule_generator import generate_rule_yaml
from app.services.session_context import (
    get_current_session,
    save_current_session,
    save_current_session_if_workspace_changed,
    workspace_session_marker,
)
from app.services.suggestion_review_state import record_review_history_without_evidence
from app.services.validation_fingerprints import (
    validation_rule_constraint_matches as _validation_rule_constraint_matches,
)

router = APIRouter(prefix="/review")
templates = Jinja2Templates(directory=TEMPLATE_DIR)
assist_service = AssistService()
_CONFLICT_REVIEW_STATUSES = {"accepted", "edited", "rejected"}
_PORTFOLIO_REVIEW_STATUSES = {"accepted", "edited", "rejected"}


def _selected_canonical_entities(session) -> list[str]:
    selected_names = set(session.selected_entity_names)
    seen: set[str] = set()
    canonical_entities: list[str] = []

    for entity in session.classified_entities:
        if entity.name not in selected_names:
            continue
        canonical_name = entity.display_name()
        if canonical_name in seen:
            continue
        seen.add(canonical_name)
        canonical_entities.append(canonical_name)

    return canonical_entities


def _conflict_query_candidates(session, *, max_candidates: int = 8) -> list[str]:
    selected_names = set(session.selected_entity_names)
    candidates: list[str] = []

    for entity_name in _selected_canonical_entities(session):
        candidates.append(entity_name)

    for entity in session.classified_entities:
        if entity.name not in selected_names:
            continue
        for field in entity.fields[:4]:
            display_entity = entity.display_name()
            candidates.append(f"{display_entity}.{field.name}")
            candidates.append(field.name)

    for entity_rules in session.entity_rules[:4]:
        candidates.append(entity_rules.entity_name)
        for rule in entity_rules.rules[:3]:
            if rule.field:
                candidates.append(f"{entity_rules.entity_name}.{rule.field}")
                candidates.append(rule.field)
            if rule.type:
                candidates.append(rule.type)

    if session.app_name:
        candidates.append(session.app_name)

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        text = str(candidate or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        deduped.append(text)
        if len(deduped) >= max_candidates:
            break
    return deduped


def _portfolio_query_candidates(session, *, max_candidates: int = 8) -> list[str]:
    selected_names = set(session.selected_entity_names)
    candidates: list[str] = []

    if session.app_name:
        candidates.append(session.app_name)
    if session.app_archetype:
        candidates.append(session.app_archetype)

    for entity_name in _selected_canonical_entities(session):
        candidates.append(entity_name)

    for entity in session.classified_entities:
        if selected_names and entity.name not in selected_names:
            continue
        for field in entity.fields[:3]:
            candidates.append(field.name)

    if session.app_archetype == "passthrough-router":
        if session.passthrough_flow.upstream_operation_name:
            candidates.append(session.passthrough_flow.upstream_operation_name)
        for route in session.passthrough_flow.routes[:3]:
            if route.target:
                candidates.append(route.target)
    elif session.app_archetype == "kafka-integration":
        for route_model in session.kafka_route_models[:4]:
            if route_model.route_name:
                candidates.append(route_model.route_name)
        for topic_pair in session.kafka_topic_pairs[:3]:
            if topic_pair.upstream_topic:
                candidates.append(topic_pair.upstream_topic)
            if topic_pair.downstream_topic:
                candidates.append(topic_pair.downstream_topic)

    for entity_rules in session.entity_rules[:3]:
        for rule in entity_rules.rules[:2]:
            if rule.type:
                candidates.append(rule.type)

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        text = str(candidate or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        deduped.append(text)
        if len(deduped) >= max_candidates:
            break
    return deduped


def _build_manifest_drawer_state(session, manifest_yaml: str) -> dict[str, Any]:
    revisions = list(session.ks_workspace_state.manifest_revisions)
    if not revisions:
        return {
            "mode": "current-only",
            "title": "Current manifest preview",
            "note": "No prior baseline available — showing current manifest.",
            "content": manifest_yaml,
            "revision": None,
        }

    latest_revision = revisions[-1]
    export_path = (latest_revision.export_path or "").strip()
    # Revisions persisted before output-path expansion carry a raw "~/..." value;
    # without expanding it here the Step-7 baseline lookup silently misses.
    try:
        manifest_path = (
            contain_under_session_workspace(
                session, expand_user_path(export_path) / "app-definition.yaml"
            )
            if export_path
            else None
        )
    except PathResolutionError:
        manifest_path = None
    if not manifest_path or not manifest_path.exists():
        return {
            "mode": "current-only",
            "title": "Current manifest preview",
            "note": "Prior manifest revision was recorded but could not be read from disk — showing current manifest.",
            "content": manifest_yaml,
            "revision": latest_revision,
        }

    previous_manifest = manifest_path.read_text(encoding="utf-8")
    diff_lines = list(
        unified_diff(
            previous_manifest.splitlines(),
            manifest_yaml.splitlines(),
            fromfile="previous/app-definition.yaml",
            tofile="current/app-definition.yaml",
            lineterm="",
        )
    )
    if not diff_lines:
        return {
            "mode": "current-only",
            "title": "Current manifest preview",
            "note": "No line-level diff against the prior manifest revision — showing current manifest.",
            "content": manifest_yaml,
            "revision": latest_revision,
        }

    return {
        "mode": "diff",
        "title": "Manifest diff",
        "note": f"Comparing current manifest against revision {latest_revision.revision_id}.",
        "content": "\n".join(diff_lines),
        "revision": latest_revision,
    }


def _build_project_review_summary(session) -> list[dict[str, Any]]:
    summary = [
        {"label": "App Name", "value": session.app_name or "—"},
        {"label": "Bounded Context", "value": session.bounded_context or "—"},
        {"label": "Archetype", "value": session.app_archetype or "crud"},
        {"label": "Target Profile", "value": session.target_profile or "—"},
    ]

    if session.app_archetype == "passthrough-router":
        summary.extend(
            [
                {"label": "Inbound Operation", "value": session.passthrough_flow.upstream_operation_name or "—"},
                {"label": "Route Rows", "value": str(len(session.passthrough_flow.routes))},
                {"label": "Transforms", "value": str(len(session.passthrough_flow.transforms))},
            ]
        )
    elif session.app_archetype == "kafka-integration":
        summary.extend(
            [
                {"label": "Topic Routes", "value": str(len(session.kafka_topic_pairs))},
                {"label": "Route Models", "value": str(len(session.kafka_route_models))},
                {"label": "Route Transforms", "value": str(len(session.kafka_route_transforms))},
            ]
        )
    else:
        summary.extend(
            [
                {"label": "Entities", "value": str(len(session.selected_entity_names))},
                {"label": "Upstream Interfaces", "value": str(len(session.upstream_interfaces))},
                {"label": "Data Handoffs", "value": str(len(session.data_handoffs))},
                {"label": "Rule Files", "value": str(len(session.entity_rules))},
            ]
        )

    upstream_edge_contracts = _edge_contract_summary_value(session.upstream_interfaces)
    downstream_edge_contracts = _edge_contract_summary_value(session.downstream_interfaces)
    if upstream_edge_contracts:
        summary.append({"label": "Upstream Contracts", "value": upstream_edge_contracts})
    if downstream_edge_contracts:
        summary.append({"label": "Downstream Contracts", "value": downstream_edge_contracts})

    return summary


def _edge_contract_summary_value(interfaces: list[Any]) -> str | None:
    edge_contracts = [
        iface
        for iface in interfaces
        if iface.type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE, XML_XSD_TYPE, SOAP_WSDL_TYPE}
    ]
    if not edge_contracts:
        return None

    file_count = sum(1 for iface in edge_contracts if iface.type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE})
    xml_count = sum(1 for iface in edge_contracts if iface.type == XML_XSD_TYPE)
    soap_count = sum(1 for iface in edge_contracts if iface.type == SOAP_WSDL_TYPE)
    return f"{len(edge_contracts)} ({file_count} file, {xml_count} XML, {soap_count} SOAP)"


_SUPPORTED_EVIDENCE_REVIEW_TYPES = {
    "field",
    "validation",
    "rule",
    "cross_entity_rule",
    "mapping",
    "transform",
}
_PATH_SUPERSEDED_REVIEW_TYPES = {"field", "validation"}


def _latest_supported_review_entries(session) -> list[Any]:
    latest_entries: list[Any] = []
    seen: set[str] = set()
    for entry in reversed(session.ks_workspace_state.review_history):
        if entry.type not in _SUPPORTED_EVIDENCE_REVIEW_TYPES or entry.suggestion_id in seen:
            continue
        seen.add(entry.suggestion_id)
        latest_entries.append(entry)
    return latest_entries


def _build_evidence_coverage(session) -> dict[str, Any]:
    latest_entries = _latest_supported_review_entries(session)
    latest_by_suggestion_id = {entry.suggestion_id: entry for entry in latest_entries}
    latest_by_manifest_path: dict[str, Any] = {}
    for entry in reversed(session.ks_workspace_state.review_history):
        if entry.type not in _PATH_SUPERSEDED_REVIEW_TYPES or not entry.manifest_path:
            continue
        latest_by_manifest_path.setdefault(entry.manifest_path, entry)

    coverage_entries = [
        entry
        for entry in latest_entries
        if latest_by_manifest_path.get(entry.manifest_path, entry).suggestion_id == entry.suggestion_id
    ]
    linked_keys: set[tuple[str, str]] = set()
    for link in session.ks_workspace_state.evidence_links:
        entry = latest_by_suggestion_id.get(link.suggestion_id)
        latest_for_path = latest_by_manifest_path.get(link.manifest_path)
        if latest_for_path is not None and latest_for_path.suggestion_id != link.suggestion_id:
            continue
        if entry and not _review_entry_artifact_exists(session, entry):
            continue
        linked_keys.add((link.suggestion_id, link.manifest_path))
    for entry in coverage_entries:
        if entry.type in {"mapping", "transform"} and entry.status in {"accepted", "edited"}:
            if _review_entry_artifact_exists(session, entry):
                linked_keys.add((entry.suggestion_id, entry.manifest_path))

    linked_count = sum(
        1
        for entry in coverage_entries
        if entry.status in {"accepted", "edited"}
        and (entry.suggestion_id, entry.manifest_path) in linked_keys
    )
    without_evidence = sum(
        1
        for entry in coverage_entries
        if entry.status in {"accepted", "edited"}
        and _review_entry_artifact_exists(session, entry)
        and (entry.suggestion_id, entry.manifest_path) not in linked_keys
    )
    total_reviewed = len(coverage_entries)
    return {
        "linked": linked_count,
        "without_evidence": without_evidence,
        "accepted": sum(1 for entry in coverage_entries if entry.status == "accepted"),
        "edited": sum(1 for entry in coverage_entries if entry.status == "edited"),
        "rejected": sum(1 for entry in coverage_entries if entry.status == "rejected"),
        "total_reviewed": total_reviewed,
    }


def _review_entry_artifact_exists(session, entry: Any) -> bool:
    if entry.type == "mapping":
        return mapping_path_exists_in_session(session, entry.manifest_path, entry)
    if entry.type == "transform":
        return transform_path_exists_in_session(session, entry.manifest_path, entry)
    if entry.type in {"rule", "cross_entity_rule"}:
        return _rule_review_entry_exists_in_session(session, entry)
    if entry.type == "validation":
        return _validation_review_entry_exists_in_session(session, entry)
    return True


def _rule_review_entry_exists_in_session(session, entry: Any) -> bool:
    parts = [part for part in str(entry.manifest_path or "").split(".") if part]
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


def _validation_review_entry_exists_in_session(session, entry: Any) -> bool:
    parts = [part for part in str(entry.manifest_path or "").split(".") if part]
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


_DECISION_TYPE_LABELS = {
    "field": "Field",
    "validation": "Validation",
    "rule": "Rule",
    "cross_entity_rule": "Cross-entity rule",
    "mapping": "Mapping",
    "transform": "Transform",
    "conflict": "Conflict",
    "portfolio": "Portfolio",
    "identity_role": "Identity role",
}

_DECISION_GROUP_LABELS = {
    "generated": "Generated artifact decisions",
    "advisory": "Advisory reviews",
    "manual_identity": "Manual identity decisions",
    "current_rules": "Manual/current Step 6 rules",
    "noop": "No-op / already satisfied reviews",
}

_DECISION_ENTITY_KEYS = (
    "entity",
    "entity_name",
    "canonical_entity",
    "source_entity",
    "target_entity",
)


def _decision_entity_from_manifest_path(manifest_path: str) -> str:
    parts = [part for part in str(manifest_path or "").split(".") if part]
    if len(parts) >= 2 and parts[0] in {"entities", "rules"}:
        return parts[1]
    return ""


def _append_decision_entity(entities: list[str], value: Any) -> None:
    if isinstance(value, dict):
        for key in _DECISION_ENTITY_KEYS:
            _append_decision_entity(entities, value.get(key))
        return
    if isinstance(value, list):
        for item in value:
            _append_decision_entity(entities, item)
        return
    text = str(value or "").strip()
    if not text:
        return
    if text not in entities:
        entities.append(text)


def _decision_entities_from_payloads(*payloads: Any) -> list[str]:
    entities: list[str] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key in _DECISION_ENTITY_KEYS:
            _append_decision_entity(entities, payload.get(key))
        for key in ("entities", "entity_names", "canonical_entities"):
            _append_decision_entity(entities, payload.get(key))
    return entities


def _decision_semantic_for_review(entry: Any, *, group: str) -> str:
    context = entry.review_context if isinstance(getattr(entry, "review_context", None), dict) else {}
    semantics = context.get("suggestion_semantics") if isinstance(context.get("suggestion_semantics"), dict) else {}
    category = str(semantics.get("category") or context.get("category") or "").strip().lower()
    if "already" in category or "no change" in category or "satisfied" in category:
        return "noop"
    if group == "advisory":
        return "advisory"
    return "generated"


def _decorate_decision_entry(
    entry: dict[str, Any],
    *,
    decision_type: str,
    decision_group: str,
    decision_semantic: str | None = None,
    entity: str = "",
    entities: list[str] | None = None,
) -> dict[str, Any]:
    decision_entities = list(entities or [])
    _append_decision_entity(decision_entities, entity)
    if not decision_entities:
        _append_decision_entity(
            decision_entities,
            _decision_entity_from_manifest_path(str(entry.get("manifest_path") or "")),
        )
    entry["decision_type"] = decision_type
    entry["decision_group"] = decision_group
    entry["decision_semantic"] = decision_semantic or decision_group
    entry["decision_entities"] = decision_entities
    entry["decision_entity"] = decision_entities[0] if decision_entities else ""
    return entry


def _decision_filter_key(kind: str, value: str) -> str:
    return f"{kind}:{value}"


def _iter_decision_history_entries(*histories: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for history in histories:
        raw_entries = history.get("entries")
        if isinstance(raw_entries, list):
            entries.extend(entry for entry in raw_entries if isinstance(entry, dict))
    return entries


def _build_decision_history_filters(*histories: dict[str, Any]) -> dict[str, Any]:
    entries = _iter_decision_history_entries(*histories)
    counts: dict[str, int] = {}
    entity_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    group_counts: dict[str, int] = {}
    semantic_counts: dict[str, int] = {}

    for entry in entries:
        counts["all"] = counts.get("all", 0) + 1
        raw_entities = entry.get("decision_entities")
        entities = raw_entities if isinstance(raw_entities, list) else [entry.get("decision_entity")]
        decision_type = str(entry.get("decision_type") or "").strip()
        decision_group = str(entry.get("decision_group") or "").strip()
        decision_semantic = str(entry.get("decision_semantic") or "").strip()
        for entity_value in entities:
            entity = str(entity_value or "").strip()
            if not entity:
                continue
            entity_counts[entity] = entity_counts.get(entity, 0) + 1
        if decision_type:
            type_counts[decision_type] = type_counts.get(decision_type, 0) + 1
        if decision_group:
            group_counts[decision_group] = group_counts.get(decision_group, 0) + 1
        if decision_semantic:
            semantic_counts[decision_semantic] = semantic_counts.get(decision_semantic, 0) + 1

    filters: list[dict[str, Any]] = []
    for group_key in ("generated", "advisory", "manual_identity", "noop", "current_rules"):
        count = group_counts.get(group_key, 0)
        if group_key == "noop":
            count = semantic_counts.get("noop", 0)
        if count:
            filters.append(
                {
                    "label": _DECISION_GROUP_LABELS[group_key],
                    "value": (
                        _decision_filter_key("semantic", "noop")
                        if group_key == "noop"
                        else _decision_filter_key("group", group_key)
                    ),
                    "count": count,
                    "kind": "group",
                }
            )
    for entity in sorted(entity_counts):
        filters.append(
            {
                "label": entity,
                "value": _decision_filter_key("entity", entity),
                "count": entity_counts[entity],
                "kind": "entity",
            }
        )
    for type_key in (
        "field",
        "validation",
        "rule",
        "cross_entity_rule",
        "mapping",
        "transform",
        "conflict",
        "portfolio",
        "identity_role",
    ):
        count = type_counts.get(type_key, 0)
        if count:
            filters.append(
                {
                    "label": _DECISION_TYPE_LABELS[type_key],
                    "value": _decision_filter_key("type", type_key),
                    "count": count,
                    "kind": "type",
                }
            )
    return {
        "total": counts.get("all", 0),
        "filters": filters,
    }


def _build_rule_review_summary(rule) -> str:
    if rule.type == "cross-entity-exists":
        if rule.target_entity:
            return f"Requires matching {rule.target_entity} record."
        return "Requires matching related record."
    if rule.type == "field-comparison":
        if rule.operator and rule.compare_to_field:
            return f"Compare against {rule.compare_to_field} with operator {rule.operator}."
        return "Field comparison rule."
    if rule.type == "cross-entity-field-check":
        parts = []
        if rule.target_entity and rule.target_field:
            parts.append(f"Checks {rule.target_entity}.{rule.target_field}")
        if rule.operator and rule.expected_value is not None:
            parts.append(f"{rule.operator} {rule.expected_value}")
        return " ".join(parts) or "Cross-entity field check."
    if rule.type == "cross-entity-field-compare":
        parts = []
        if rule.target_entity and rule.target_field:
            parts.append(f"Compares against {rule.target_entity}.{rule.target_field}")
        if rule.source_field and rule.operator:
            parts.append(f"using {rule.source_field} {rule.operator}")
        return " ".join(parts) or "Cross-entity field compare."
    if rule.type == "cross-entity-field-in":
        if rule.target_entity and rule.target_field:
            return f"Checks {rule.target_entity}.{rule.target_field} against allowed values."
        return "Cross-entity inclusion rule."
    if rule.type == "allowed-values":
        return f"Allowed values: {', '.join(rule.values)}" if rule.values else "Allowed values rule."
    if rule.type == "range":
        bounds: list[str] = []
        if rule.value is not None:
            bounds.append(f"min {rule.value}")
        if rule.values:
            bounds.append(f"max {rule.values[0]}")
        return ", ".join(bounds) if bounds else "Range rule."
    if rule.type in {"default", "max-length", "min-length", "pattern"}:
        if rule.value is not None:
            return f"Value: {rule.value}"
        return f"{rule.type} rule."
    return f"{rule.type} rule."


def _build_step6_rule_review_artifacts(session) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []

    for entity_rules in session.entity_rules:
        for rule in entity_rules.rules:
            manifest_path = f"rules.{entity_rules.entity_name}.{rule.field}.{rule.type}"
            is_cross_entity = str(rule.type or "").startswith("cross-entity")
            if rule.generated_by_ka:
                provenance_class = "KA-applied rule"
                evidence_label = "Knowledge Assist applied rule"
                decision_semantic = "ka-applied-rule"
                reviewed_at = rule.applied_at or "—"
            else:
                provenance_class = "Manual/imported/spec-derived rule"
                evidence_label = "Current Step 6 rule set"
                decision_semantic = "manual-current-rule"
                reviewed_at = "—"
            legacy_provenance_class = "ka-applied-rule" if rule.generated_by_ka else "current-rule-set"
            entries.append(
                _decorate_decision_entry(
                    {
                        "entity_name": entity_rules.entity_name,
                        "field_name": rule.field,
                        "rule_type": rule.type,
                        "manifest_path": manifest_path,
                        "file_path": entity_rules.file_path
                        or f"rules/{entity_rules.entity_name.lower()}-business-rules.yaml",
                        "provenance_class": provenance_class,
                        "evidence_label": evidence_label,
                        "reviewed_at": reviewed_at,
                        "summary": _build_rule_review_summary(rule),
                        "legacy_provenance_class": legacy_provenance_class,
                        "suggestion_id": rule.suggestion_id or "",
                        "suggestion_type": rule.suggestion_type or "",
                        "ka_review_status": rule.ka_review_status or "",
                    },
                    decision_type="cross_entity_rule" if is_cross_entity else "rule",
                    decision_group="current_rules",
                    decision_semantic=decision_semantic,
                    entity=entity_rules.entity_name,
                )
            )

    return {
        "entries": entries,
        "count": len(entries),
        "empty": len(entries) == 0,
    }


def _build_rule_yaml_previews(session) -> dict[str, Any]:
    previews: list[dict[str, Any]] = []
    for entity_rules in session.entity_rules:
        if not entity_rules.rules:
            continue
        previews.append(
            {
                "entity_name": entity_rules.entity_name,
                "file_path": entity_rules.file_path or f"rules/{entity_rules.entity_name.lower()}-business-rules.yaml",
                "content": generate_rule_yaml(entity_rules),
            }
        )
    return {
        "previews": previews,
        "empty": len(previews) == 0,
    }


def _build_identity_role_history(session) -> dict[str, Any]:
    latest_reviews: dict[tuple[str, str, str], Any] = {}
    for review_entry in session.ks_workspace_state.review_history:
        if review_entry.type != "identity_role":
            continue
        if review_entry.status not in {"accepted", "edited"}:
            continue
        context = review_entry.review_context if isinstance(review_entry.review_context, dict) else {}
        key = (
            str(context.get("entity") or "").strip(),
            str(context.get("field") or "").strip(),
            str(context.get("role") or "").strip(),
        )
        if all(key):
            latest_reviews[key] = review_entry

    entries: list[dict[str, Any]] = []
    active_keys: set[tuple[str, str, str]] = set()
    for entry in identity_role_decision_entries(session):
        key = (
            str(entry.get("entity") or "").strip(),
            str(entry.get("field") or "").strip(),
            str(entry.get("role") or "").strip(),
        )
        active_keys.add(key)
        provenance = str(entry.get("provenance") or "human-authored").strip()
        matched_review = latest_reviews.get(key) if provenance == "knowledge-assist" else None
        display_entry = {
            **entry,
            "status": matched_review.status if matched_review else "active",
            "suggestion_id": matched_review.suggestion_id if matched_review else "",
            "provenance": "Knowledge Assist" if provenance == "knowledge-assist" else "human-authored",
        }
        entries.append(
            _decorate_decision_entry(
                display_entry,
                decision_type="identity_role",
                decision_group="manual_identity",
                decision_semantic="ka_identity" if provenance == "knowledge-assist" else "manual_identity",
                entity=str(entry.get("entity") or ""),
            )
        )

    for review_entry in session.ks_workspace_state.review_history:
        if review_entry.type != "identity_role" or review_entry.status != "rejected":
            continue
        context = review_entry.review_context if isinstance(review_entry.review_context, dict) else {}
        key = (
            str(context.get("entity") or "").strip(),
            str(context.get("field") or "").strip(),
            str(context.get("role") or "").strip(),
        )
        if not all(key) or key in active_keys:
            continue
        entries.append(
            _decorate_decision_entry(
                {
                    "entity": key[0],
                    "field": key[1],
                    "role": key[2],
                    "provenance": "Knowledge Assist",
                    "status": "rejected",
                    "reviewed_at": review_entry.reviewed_at[:10] if review_entry.reviewed_at else "—",
                    "export_impact": "Rejected review only; no Engine export and no evidence-trail entry",
                    "generation_impact": "Rejected review only; no generated app behavior.",
                    "api_impact": "Rejected review only; no generated API behavior.",
                    "evidence_trail_impact": "No Evidence Trail entry for rejected identity-role reviews.",
                    "impact_badge": "Review only",
                    "affects_engine": False,
                    "manifest_path": review_entry.manifest_path,
                    "suggestion_id": review_entry.suggestion_id,
                },
                decision_type="identity_role",
                decision_group="manual_identity",
                decision_semantic="ka_identity",
                entity=key[0],
            )
        )
    return {
        "entries": entries,
        "count": len(entries),
        "empty": len(entries) == 0,
    }


def _review_display_label(provenance_class: str, status: str = "") -> str:
    normalized = str(provenance_class or status or "").strip().lower()
    return {
        "ai-accepted": "Accepted from KA",
        "ai-edited": "Edited from KA",
        "ai-rejected": "Rejected KA suggestion",
        "rejected": "Rejected KA suggestion",
    }.get(normalized, str(provenance_class or status or "").strip())


def _attach_provenance_display_labels(history: dict[str, Any]) -> dict[str, Any]:
    entries = history.get("entries")
    if not isinstance(entries, list):
        return history
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry["provenance_label"] = _review_display_label(
            str(entry.get("provenance_class") or ""),
            str(entry.get("status") or ""),
        )
        _decorate_decision_entry(
            entry,
            decision_type="field",
            decision_group="generated",
            decision_semantic="generated",
        )
    return history


def _build_ka_rule_review_history(session) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for entry in session.ks_workspace_state.review_history:
        if entry.type not in {"rule", "cross_entity_rule"}:
            continue
        provenance_class = {
            "accepted": "ai-accepted",
            "edited": "ai-edited",
            "rejected": "rejected",
        }.get(entry.status, entry.status)
        entries.append(
            _decorate_decision_entry(
                {
                    "suggestion_id": entry.suggestion_id,
                    "type": entry.type,
                    "status": entry.status,
                    "manifest_path": entry.manifest_path,
                    "reviewed_at": entry.reviewed_at,
                    "provenance_class": provenance_class,
                    "provenance_label": _review_display_label(provenance_class, entry.status),
                    "has_evidence": False,
                },
                decision_type=entry.type,
                decision_group="generated",
                decision_semantic=_decision_semantic_for_review(entry, group="generated"),
            )
        )

    return {
        "entries": entries,
        "count": len(entries),
        "empty": len(entries) == 0,
    }


def _build_ka_validation_review_history(session) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    latest_entries: dict[str, Any] = {}
    for entry in session.ks_workspace_state.review_history:
        if entry.type != "validation":
            continue
        latest_entries[entry.manifest_path or entry.suggestion_id] = entry
    for entry in latest_entries.values():
        provenance_class = {
            "accepted": "ai-accepted",
            "edited": "ai-edited",
            "rejected": "rejected",
        }.get(entry.status, entry.status)
        review_context = entry.review_context if isinstance(entry.review_context, dict) else {}
        entries.append(
            _decorate_decision_entry(
                {
                    "suggestion_id": entry.suggestion_id,
                    "status": entry.status,
                    "manifest_path": entry.manifest_path,
                    "reviewed_at": entry.reviewed_at,
                    "provenance_class": provenance_class,
                    "provenance_label": _review_display_label(provenance_class, entry.status),
                },
                decision_type="validation",
                decision_group="generated",
                decision_semantic=_decision_semantic_for_review(entry, group="generated"),
                entity=str(review_context.get("entity") or "").strip(),
            )
        )

    return {
        "entries": entries,
        "count": len(entries),
        "empty": len(entries) == 0,
    }


def _build_ka_mapping_review_history(session) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for entry in session.ks_workspace_state.review_history:
        if entry.type != "mapping":
            continue
        provenance_class = {
            "accepted": "ai-accepted",
            "edited": "ai-edited",
            "rejected": "rejected",
        }.get(entry.status, entry.status)
        review_context = entry.review_context if isinstance(entry.review_context, dict) else {}
        edited_payload = entry.edited_payload if isinstance(entry.edited_payload, dict) else {}
        entries.append(
            _decorate_decision_entry(
                {
                    "suggestion_id": entry.suggestion_id,
                    "status": entry.status,
                    "manifest_path": entry.manifest_path,
                    "reviewed_at": entry.reviewed_at,
                    "provenance_class": provenance_class,
                    "provenance_label": _review_display_label(provenance_class, entry.status),
                    "has_evidence": entry.status in {"accepted", "edited"},
                },
                decision_type="mapping",
                decision_group="generated",
                decision_semantic=_decision_semantic_for_review(entry, group="generated"),
                entities=_decision_entities_from_payloads(review_context, edited_payload),
            )
        )

    return {
        "entries": entries,
        "count": len(entries),
        "empty": len(entries) == 0,
    }


def _build_ka_transform_review_history(session) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for entry in session.ks_workspace_state.review_history:
        if entry.type != "transform":
            continue
        provenance_class = {
            "accepted": "ai-accepted",
            "edited": "ai-edited",
            "rejected": "rejected",
        }.get(entry.status, entry.status)
        review_context = entry.review_context if isinstance(entry.review_context, dict) else {}
        edited_payload = entry.edited_payload if isinstance(entry.edited_payload, dict) else {}
        entries.append(
            _decorate_decision_entry(
                {
                    "suggestion_id": entry.suggestion_id,
                    "status": entry.status,
                    "manifest_path": entry.manifest_path,
                    "reviewed_at": entry.reviewed_at,
                    "provenance_class": provenance_class,
                    "provenance_label": _review_display_label(provenance_class, entry.status),
                    "has_evidence": entry.status in {"accepted", "edited"}
                    and transform_path_exists_in_session(session, entry.manifest_path, entry),
                    "route_name": str(review_context.get("route_name") or "").strip(),
                    "target_id": str(review_context.get("target_id") or "").strip(),
                    "direction": str(review_context.get("direction") or "").strip(),
                },
                decision_type="transform",
                decision_group="generated",
                decision_semantic=_decision_semantic_for_review(entry, group="generated"),
                entities=_decision_entities_from_payloads(review_context, edited_payload),
            )
        )

    return {
        "entries": entries,
        "count": len(entries),
        "empty": len(entries) == 0,
    }


def _build_ka_conflict_review_history(session) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for entry in session.ks_workspace_state.review_history:
        if entry.type != "conflict_resolution":
            continue
        provenance_class = {
            "accepted": "acknowledged",
            "edited": "resolution-note",
            "rejected": "dismissed",
        }.get(entry.status, entry.status)
        edited_payload = entry.edited_payload if isinstance(entry.edited_payload, dict) else {}
        review_context = entry.review_context if isinstance(entry.review_context, dict) else {}
        entries.append(
            _decorate_decision_entry(
                {
                    "suggestion_id": entry.suggestion_id,
                    "status": entry.status,
                    "manifest_path": entry.manifest_path,
                    "reviewed_at": entry.reviewed_at,
                    "provenance_class": provenance_class,
                    "provenance_label": provenance_class,
                    "conflict_summary": str(review_context.get("conflict_summary") or "").strip(),
                    "entity": str(review_context.get("entity") or "").strip(),
                    "field": str(review_context.get("field") or "").strip(),
                    "difference_category": str(
                        review_context.get("difference_category") or ""
                    ).strip(),
                    "normalized_field_mapping": str(
                        review_context.get("normalized_field_mapping") or ""
                    ).strip(),
                    "document_labels": list(review_context.get("document_labels") or []),
                    "resolution_note": str(edited_payload.get("resolution_note") or "").strip(),
                    "preferred_document_id": str(
                        edited_payload.get("preferred_document_id") or ""
                    ).strip(),
                    "preferred_document_label": str(
                        edited_payload.get("preferred_document_label")
                        or review_context.get("preferred_document_label")
                        or ""
                    ).strip(),
                },
                decision_type="conflict",
                decision_group="advisory",
                decision_semantic="advisory",
                entity=str(review_context.get("entity") or "").strip(),
            )
        )

    return {
        "entries": entries,
        "count": len(entries),
        "empty": len(entries) == 0,
    }


def _build_ka_portfolio_review_history(session) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for entry in session.ks_workspace_state.review_history:
        if entry.type != "portfolio_reuse":
            continue
        provenance_class = {
            "accepted": "useful",
            "edited": "reuse-note",
            "rejected": "dismissed",
        }.get(entry.status, entry.status)
        edited_payload = entry.edited_payload if isinstance(entry.edited_payload, dict) else {}
        review_context = entry.review_context if isinstance(entry.review_context, dict) else {}
        entries.append(
            _decorate_decision_entry(
                {
                    "suggestion_id": entry.suggestion_id,
                    "status": entry.status,
                    "manifest_path": entry.manifest_path,
                    "reviewed_at": entry.reviewed_at,
                    "provenance_class": provenance_class,
                    "provenance_label": provenance_class,
                    "reuse_note": str(edited_payload.get("reuse_note") or "").strip(),
                    "rationale": str(edited_payload.get("rationale") or "").strip(),
                    "target_step": str(edited_payload.get("target_step") or "").strip(),
                    "target_manifest_path": str(
                        edited_payload.get("target_manifest_path") or ""
                    ).strip(),
                    "matched_project_id": str(
                        review_context.get("matched_project_id") or ""
                    ).strip(),
                    "document_labels": list(review_context.get("document_labels") or []),
                },
                decision_type="portfolio",
                decision_group="advisory",
                decision_semantic="advisory",
            )
        )

    return {
        "entries": entries,
        "count": len(entries),
        "empty": len(entries) == 0,
    }


def _apply_step7_review_statuses(payload: dict[str, Any], session, scope: str) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for entry in session.ks_workspace_state.review_history:
        if entry.type == scope:
            latest[entry.suggestion_id] = entry
    if not latest:
        return payload

    drawer_scopes = payload.get("scopes")
    if not isinstance(drawer_scopes, list):
        return payload
    for drawer_scope in drawer_scopes:
        if not isinstance(drawer_scope, dict):
            continue
        rows = drawer_scope.get("rows")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            entry = latest.get(str(row.get("suggestion_id") or ""))
            if entry is None:
                continue
            row["status"] = entry.status
            payload_data = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            payload_data = dict(payload_data)
            payload_data["studio_review_status"] = entry.status
            payload_data["studio_reviewed_at"] = entry.reviewed_at
            if isinstance(entry.edited_payload, dict):
                payload_data["studio_edited_payload"] = entry.edited_payload
                payload_data["studio_resolution_note"] = str(
                    entry.edited_payload.get("resolution_note") or ""
                ).strip()
            review_context = entry.review_context if isinstance(entry.review_context, dict) else {}
            payload_data["studio_review_context"] = review_context
            for key in (
                "conflict_summary",
                "entity",
                "field",
                "difference_category",
                "normalized_field_mapping",
                "preferred_document_id",
                "preferred_document_label",
            ):
                value = review_context.get(key)
                if value and not payload_data.get(key):
                    payload_data[key] = value
            for key in ("document_ids", "document_labels", "document_options"):
                value = review_context.get(key)
                if value and not payload_data.get(key):
                    payload_data[key] = value
            row["payload"] = payload_data
    return payload


def _successful_outcome_ids(ks_result: dict[str, Any], decisions: list[dict[str, Any]]) -> set[str]:
    outcomes = ks_result.get("outcomes", [])
    if isinstance(outcomes, list) and outcomes:
        return {
            str(outcome.get("suggestion_id"))
            for outcome in outcomes
            if isinstance(outcome, dict)
            and outcome.get("success", True)
            and outcome.get("suggestion_id") is not None
        }
    return {decision["suggestion_id"] for decision in decisions} if ks_result.get("success", True) else set()


def _conflict_payload_document_ids(payload: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in ("document_ids", "source_document_ids", "document_refs", "documents", "document_options"):
        value = payload.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    text = str(item.get("document_id") or item.get("id") or "").strip()
                else:
                    text = str(item or "").strip()
                if text:
                    ids.add(text)
        elif isinstance(value, dict):
            text = str(value.get("document_id") or value.get("id") or "").strip()
            if text:
                ids.add(text)
        elif value:
            ids.add(str(value).strip())
    return ids


def _conflict_payload_document_labels(payload: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for key in ("document_options", "documents", "document_refs"):
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            label = str(
                item.get("document_name")
                or item.get("document_label")
                or item.get("name")
                or item.get("label")
                or item.get("document_id")
                or item.get("id")
                or ""
            ).strip()
            if label:
                labels.append(label)
    for key in ("document_labels", "document_names"):
        value = payload.get(key)
        if isinstance(value, list):
            labels.extend(str(item or "").strip() for item in value if str(item or "").strip())
        elif value:
            labels.append(str(value).strip())
    seen: set[str] = set()
    deduped: list[str] = []
    for label in labels:
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(label)
    return deduped


def _conflict_payload_document_label(payload: dict[str, Any], document_id: str) -> str:
    if not document_id:
        return ""
    for key in ("document_options", "documents", "document_refs"):
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("document_id") or item.get("id") or "").strip()
            if item_id != document_id:
                continue
            return str(
                item.get("document_name")
                or item.get("document_label")
                or item.get("name")
                or item.get("label")
                or item_id
            ).strip()
    document_ids = payload.get("document_ids") if isinstance(payload.get("document_ids"), list) else []
    document_labels = payload.get("document_labels") if isinstance(payload.get("document_labels"), list) else []
    for index, item in enumerate(document_ids):
        if str(item or "").strip() == document_id and index < len(document_labels):
            return str(document_labels[index] or "").strip()
    return document_id


def _conflict_payload_review_context(
    payload: dict[str, Any],
    edited_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    review_context: dict[str, Any] = {
        "conflict_query": str(payload.get("conflict_query") or "").strip(),
        "conflict_summary": str(
            payload.get("conflict_summary") or payload.get("summary") or ""
        ).strip(),
        "entity": str(payload.get("entity") or payload.get("entity_name") or "").strip(),
        "field": str(payload.get("field") or payload.get("field_name") or "").strip(),
        "difference_category": str(payload.get("difference_category") or "").strip(),
        "normalized_field_mapping": str(
            payload.get("normalized_field_mapping") or payload.get("field_mapping") or ""
        ).strip(),
        "document_ids": sorted(_conflict_payload_document_ids(payload)),
        "document_labels": _conflict_payload_document_labels(payload),
    }
    document_options = payload.get("document_options")
    if isinstance(document_options, list):
        review_context["document_options"] = [
            {
                "id": str(item.get("id") or item.get("document_id") or "").strip(),
                "label": str(
                    item.get("label")
                    or item.get("document_name")
                    or item.get("document_label")
                    or ""
                ).strip(),
            }
            for item in document_options
            if isinstance(item, dict)
            and str(item.get("id") or item.get("document_id") or "").strip()
        ]
    if isinstance(edited_payload, dict):
        preferred_document_id = str(edited_payload.get("preferred_document_id") or "").strip()
        if preferred_document_id:
            review_context["preferred_document_id"] = preferred_document_id
            review_context["preferred_document_label"] = str(
                edited_payload.get("preferred_document_label")
                or _conflict_payload_document_label(payload, preferred_document_id)
                or ""
            ).strip()
    return {
        key: value
        for key, value in review_context.items()
        if value not in ("", [], {}, None)
    }


def _ka_generated_history_has_entries(*histories: dict[str, Any]) -> bool:
    return any(not history.get("empty", True) for history in histories)


def _normalize_conflict_review_decisions(raw_decisions: Any) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(raw_decisions, list):
        return [], ["Review decisions must be a list."]

    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, item in enumerate(raw_decisions):
        if not isinstance(item, dict):
            errors.append(f"Decision {index + 1} must be an object.")
            continue

        suggestion_id = str(item.get("suggestion_id") or "").strip()
        suggestion_type = str(item.get("suggestion_type") or "").strip()
        status = str(item.get("status") or "").strip()
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        edited_payload = item.get("edited_payload") if isinstance(item.get("edited_payload"), dict) else None

        if not suggestion_id:
            errors.append(f"Decision {index + 1} must include suggestion_id.")
            continue
        if suggestion_type != "conflict_resolution":
            errors.append(f"Decision {index + 1} has unsupported suggestion_type '{suggestion_type}'.")
            continue
        if status not in _CONFLICT_REVIEW_STATUSES:
            errors.append(f"Decision {index + 1} has unsupported status '{status}'.")
            continue
        if status == "edited":
            if not edited_payload:
                errors.append(f"Decision {index + 1} requires edited_payload for edited review.")
                continue
            resolution_note = str(edited_payload.get("resolution_note") or "").strip()
            if not resolution_note:
                errors.append(f"Decision {index + 1} requires resolution_note for edited review.")
                continue
            preferred_document_id = str(
                edited_payload.get("preferred_document_id") or ""
            ).strip()
            allowed_document_ids = _conflict_payload_document_ids(payload)
            if preferred_document_id and (
                not allowed_document_ids or preferred_document_id not in allowed_document_ids
            ):
                errors.append(
                    f"Decision {index + 1} preferred_document_id must belong to this conflict suggestion."
                )
                continue

        normalized.append(
            {
                "suggestion_id": suggestion_id,
                "suggestion_type": suggestion_type,
                "status": status,
                "payload": payload,
                "edited_payload": edited_payload,
                "manifest_path": f"conflicts.{suggestion_id}",
            }
        )
    return normalized, errors


def _ks_conflict_review_payload(decision: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "suggestion_id": decision["suggestion_id"],
        "status": decision["status"],
    }
    if decision["status"] == "edited":
        payload["edited_payload"] = decision["edited_payload"]
    return payload


def _portfolio_payload_list(payload: dict[str, Any], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    text = str(
                        item.get("document_name")
                        or item.get("name")
                        or item.get("document_id")
                        or item.get("id")
                        or ""
                    ).strip()
                else:
                    text = str(item or "").strip()
                if text:
                    values.append(text)
        elif isinstance(value, dict):
            text = str(
                value.get("document_name")
                or value.get("name")
                or value.get("document_id")
                or value.get("id")
                or ""
            ).strip()
            if text:
                values.append(text)
        elif value:
            values.append(str(value).strip())
    return sorted(set(values))


def _normalize_portfolio_review_decisions(raw_decisions: Any) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(raw_decisions, list):
        return [], ["Review decisions must be a list."]

    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, item in enumerate(raw_decisions):
        if not isinstance(item, dict):
            errors.append(f"Decision {index + 1} must be an object.")
            continue

        suggestion_id = str(item.get("suggestion_id") or "").strip()
        suggestion_type = str(item.get("suggestion_type") or "").strip()
        status = str(item.get("status") or "").strip()
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        edited_payload = item.get("edited_payload") if isinstance(item.get("edited_payload"), dict) else None

        if not suggestion_id:
            errors.append(f"Decision {index + 1} must include suggestion_id.")
            continue
        if suggestion_type != "portfolio_reuse":
            errors.append(f"Decision {index + 1} has unsupported suggestion_type '{suggestion_type}'.")
            continue
        if status not in _PORTFOLIO_REVIEW_STATUSES:
            errors.append(f"Decision {index + 1} has unsupported status '{status}'.")
            continue
        if status == "edited":
            if not edited_payload:
                errors.append(f"Decision {index + 1} requires edited_payload for edited review.")
                continue
            reuse_note = str(edited_payload.get("reuse_note") or "").strip()
            rationale = str(edited_payload.get("rationale") or "").strip()
            if not reuse_note and not rationale:
                errors.append(
                    f"Decision {index + 1} requires reuse_note or rationale for edited portfolio review."
                )
                continue

        normalized.append(
            {
                "suggestion_id": suggestion_id,
                "suggestion_type": suggestion_type,
                "status": status,
                "payload": payload,
                "edited_payload": edited_payload,
                "manifest_path": f"portfolio_reuse.{suggestion_id}",
            }
        )
    return normalized, errors


def _ks_portfolio_review_payload(decision: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "suggestion_id": decision["suggestion_id"],
        "status": decision["status"],
    }
    if decision["status"] == "edited":
        payload["edited_payload"] = decision["edited_payload"]
    return payload


# Verified convention (completeness_service.py, every per-item message): each
# message starts with the item's name, single-quoted -- f"'{name}': ...". This
# is the only join key back to readiness_view items; CompletenessItem itself
# carries no structured reference (PR-16). Greedy match to the LAST "':" in
# the message (not the first "'") so a name that itself contains an
# apostrophe (e.g. "customer's-feed") isn't truncated -- a message never
# contains the literal substring "':" before the real name/message boundary.
_COMPLETENESS_NAME_RE = re.compile(r"^'(.+)':")

# Only these completeness categories carry the f"'{name}': ..." convention
# *and* currently have a shipped `?focus=` editor to link into. PR-16 (#250)
# originally restricted this to Downstream only: at that time /upstream and
# /handoffs both ignored `?focus=` and had no `id="<section_ref>"` anchors, so
# a link into either would have landed on the legacy bulk page and silently
# ignored the item/section. That premise is now stale -- PR-14 (step4_get
# accepts `focus`, `id="ddl"`/`id="mappings"`/`id="identity"` anchors) and
# PR-15 (step2_get accepts `focus`, `id="layout"`/`id="xsd"`/`id="wsdl"`
# anchors) shipped their focus editors. Upstream/DataHandoff were re-added here
# in PR-21, and PR-24 made those refreshed routes unconditional.
# Project/Kafka/Rules (and Entities/Legacy, which never use the per-name
# message shape) intentionally still have no entry -- readiness_view doesn't
# itemize them yet, so their items render unlinked per the PR-16 scope boundary.
_COMPLETENESS_CATEGORY_ITEM_KINDS: dict[str, tuple[str, ...]] = {
    "Upstream": (readiness_view.ITEM_KIND_UPSTREAM_CONTRACT,),
    "Downstream": (readiness_view.ITEM_KIND_DOWNSTREAM_INTERFACE,),
    "DataHandoff": (readiness_view.ITEM_KIND_HANDOFF,),
}


def _completeness_deep_links(session, report: CompletenessReport) -> dict[tuple[str, str], str]:
    """Map each (category, message) of a completeness report to a deep_link.

    CompletenessItem carries no structured reference back to the
    readiness_view item it was derived from -- only a free-text message. The
    leading quoted name in that message (see _COMPLETENESS_NAME_RE) is used as
    a join key back to readiness_view.item_by_display_name(). Restricting the
    lookup to the item kind(s) that category can represent matters: upstream
    and downstream interfaces are independent lists that are not guaranteed to
    have distinct names, so an unscoped-by-kind lookup could resolve a
    Downstream advisory to an Upstream item's deep_link (or vice versa) when
    both share a name. The result is keyed by (category, message) rather than
    message alone for the same reason -- two different items (e.g. an
    upstream and downstream interface sharing a name and type) can otherwise
    produce byte-identical message text.

    A resolved item's blockers/warnings all share one deep_link (computed once
    per item in readiness_view), so the first available Ref's deep_link is
    correct for every *problem* message belonging to that item -- but a READY
    completeness row for that same item must never get one: a single
    interface can emit both a READY line (e.g. "has mappings defined") and a
    WARNING line (e.g. "no DDL provided") for two different requirement
    dimensions in the same report, and attaching the item's (unrelated)
    blocker/warning deep_link to the READY line would point a green row at
    someone else's problem section (re-review finding, PR-16 #250). Only
    WARNING/MANUAL_FOLLOW_UP rows are advisories worth deep-linking; READY
    rows are skipped outright, regardless of what the resolved item's own
    blockers/warnings contain.

    Any of the following yields no entry, so callers must render the plain,
    unlinked message -- never crash, never drop the item: the item's own
    status is READY; the message doesn't match the naming convention; the
    category isn't one with a shipped focus editor to link into yet; no item
    matches by name; or the matched item has no blocker/warning to source a
    deep_link from.
    """
    links: dict[tuple[str, str], str] = {}
    for item in report.items:
        if item.status == "READY":
            continue
        match = _COMPLETENESS_NAME_RE.match(item.message)
        if not match:
            continue
        item_kinds = _COMPLETENESS_CATEGORY_ITEM_KINDS.get(item.category)
        if item_kinds is None:
            # Category has no shipped focus editor to link into (or isn't
            # itemized by readiness_view at all) -- e.g. Upstream/DataHandoff
            # today. item_by_display_name treats item_kinds=None as
            # "unfiltered", not "skip", so this must be an explicit continue
            # rather than passing None through -- otherwise an Upstream
            # message could still resolve (unfiltered) to some item's
            # deep_link pointing at a route that ignores `?focus=` entirely.
            continue
        resolved = readiness_view.item_by_display_name(session, match.group(1), item_kinds=item_kinds)
        if resolved is None:
            continue
        refs = resolved.blockers or resolved.warnings
        if not refs:
            continue
        # A resolved item can carry refs that point at DIFFERENT sections -- a
        # handoff emits missing-DDL at #ddl and missing-mappings at #mappings
        # (readiness_view._handoff_item). Each readiness Ref.label is the same
        # "'{name}': ..." string as the completeness message it describes, so
        # match the message to its own ref and use THAT section's deep_link;
        # fall back to the first ref only when nothing matches (defensive).
        ref = next((r for r in refs if r.label == item.message), refs[0])
        deep_link = ref.deep_link
        if deep_link:
            links[(item.category, item.message)] = deep_link
    return links


# ---------------------------------------------------------------------------
# PR-21: Step 7 Contract Trace Lens (flag-on only).
#
# Single-producer rule: every pill/state/blocker the Trace Lens shows is the
# *same* readiness_view.ReadinessItem the Step 2/3/4/5 boards and Export
# already read -- this module only groups those items by entity and by
# "connected to the current entity or not". readiness_view.py itself is
# consume-only here (items_for_step / item_by_display_name), never modified,
# never re-derived.
#
# The entity `card` (key/field_count/role_count/contract_count) is the one
# exception: it is descriptive metadata, not a pill/state/blocker, so it is
# sourced directly from identity_roles/edge_contracts (the same helpers
# readiness_view._entity_item itself calls) rather than through a
# ReadinessItem, which has no field for any of these counts.
# ---------------------------------------------------------------------------

_TRACE_READY_STATES = {readiness_view.STATE_READY, readiness_view.STATE_DRAFT}
_TRACE_WARNING_STATES = {readiness_view.STATE_WARNING, readiness_view.STATE_NEEDS_ACTION}
_TRACE_ATTENTION_STATES = {readiness_view.STATE_BLOCKS_EXPORT, readiness_view.STATE_NEEDS_ACTION}
_TRACE_LENS_EMPTY_SUMMARY: dict[str, int] = {"ready": 0, "warnings": 0, "blocks_export": 0}


def _trace_lens_summary(*item_lists: list[readiness_view.ReadinessItem]) -> dict[str, int]:
    """Ready / Warnings / Blocks export counts for the `.rsummary` strip,
    bucketed purely from readiness_view states -- never recomputed from the
    completeness report. `draft` (reference-only edge contracts) buckets with
    `ready`, mirroring the existing Step 5 triage board precedent
    (tests/test_step5_triage_board.py::
    test_draft_state_and_alt_capability_render_correctly renders draft in the
    "Ready" group). `needs_action` (today only emitted by entity items, for a
    missing persistence key) is never export_blocking, so it buckets with
    `warning` rather than `blocks_export`."""
    ready = warnings = blocks_export = 0
    for items in item_lists:
        for readiness_item in items:
            if readiness_item.state in _TRACE_READY_STATES:
                ready += 1
            elif readiness_item.state in _TRACE_WARNING_STATES:
                warnings += 1
            elif readiness_item.state == readiness_view.STATE_BLOCKS_EXPORT:
                blocks_export += 1
    return {"ready": ready, "warnings": warnings, "blocks_export": blocks_export}


def _export_gate(report) -> dict[str, Any]:
    """The authoritative export gate, for the flag-on Step-7 summary strip.

    `trace_lens_summary` counts readiness_view items for Steps 2-5 only, but
    what actually blocks export is the completeness report -- `/export` gates
    on `report.is_exportable()` (app/routes/export.py), which is true iff
    there are no MANUAL_FOLLOW_UP items. Project-level blockers (a missing
    `target_profile`, say) never become readiness_view items, so they are
    invisible to that strip.

    Before PR-23 that gap was masked: the legacy `.review-summary-strip`
    rendered alongside and carried the manual-follow-up count. PR-23 made the
    readiness strip the *sole* flag-on summary, which turned the gap into a
    false-green -- an all-zero, `uxr-zone-ready` strip while Step 8 refuses to
    export. This surfaces the gate explicitly so the summary can never
    contradict Step 8.

    Precomputed here rather than as `report.manual()|length` in Jinja so the
    template keeps doing no arithmetic of its own.
    """
    return {
        "exportable": report.is_exportable(),
        "blocker_count": len(report.manual()),
    }


def _interface_trace_ref(session, iface, *, item_kind: str) -> dict[str, Any]:
    """One Upstream/Downstream trace_ref.

    `readiness` is the interface's OWN joined readiness_view.ReadinessItem when
    readiness_view itemizes its type (the EDGE_CONTRACT_TYPES); it drives the
    pill and, for a blocker, the Fix link.

    `entity_readiness` is the ReadinessItem of the ENTITY this interface
    populates, used only when the interface itself is not itemized -- a
    REST/OpenAPI upstream is the bulk CRUD ingestion source and readiness_view
    does not model it as its own item, but the entity it populates IS itemized.
    Per the mock ("3 ops - populates Account" + a readiness pill) and the "one
    truth" rule, such a row carries the populated entity's readiness FROM THE
    SAME P6 MODEL rather than being unlabeled. It is a pill only (state); the
    entity's Fix affordance lives on the entity, not on the source row.

    A ref with neither (e.g. a REST interface whose entity_name resolves to no
    classified entity) still renders an explicit "Source" label -- never a
    silent, unlabeled row."""
    matched = readiness_view.item_by_display_name(session, iface.name, item_kinds=(item_kind,))
    family = matched.family if matched is not None else readiness_view.FAMILY_REST

    entity_readiness = None
    if matched is None and getattr(iface, "entity_name", None):
        entity_readiness = readiness_view.item_by_display_name(
            session, iface.entity_name, item_kinds=(readiness_view.ITEM_KIND_ENTITY,)
        )

    if matched is None and item_kind == readiness_view.ITEM_KIND_UPSTREAM_CONTRACT:
        # Only unitemized upstream interfaces carry `operations` in the model
        # (DownstreamInterface has no `operations` field at all) -- every
        # other case below falls back to the field_mappings count, which is
        # modeled on both directions.
        op_count = len(iface.operations)
        provenance_detail = f"{op_count} operation{'' if op_count == 1 else 's'}"
    else:
        map_count = len(iface.field_mappings)
        provenance_detail = f"{map_count} mapping{'' if map_count == 1 else 's'}"
    if matched is None and getattr(iface, "entity_name", None):
        provenance_detail = f"{provenance_detail} · populates {iface.entity_name}"

    return {
        "name": iface.name,
        "family": family,
        "provenance_detail": provenance_detail,
        "readiness": matched,
        "entity_readiness": entity_readiness,
    }


def _handoff_trace_ref(session, handoff) -> dict[str, Any]:
    """One handoff trace_ref. readiness_view._handoff_items() builds an item
    for every session.data_handoffs entry unconditionally, so `matched` is
    expected to always resolve here -- the FAMILY_STAGING fallback is
    defensive only, so this never crashes if that ever changes."""
    matched = readiness_view.item_by_display_name(
        session, handoff.name, item_kinds=(readiness_view.ITEM_KIND_HANDOFF,)
    )
    family = matched.family if matched is not None else readiness_view.FAMILY_STAGING
    map_count = len(handoff.field_mappings)
    provenance_detail = f"{map_count} mapping{'' if map_count == 1 else 's'}"
    if handoff.table_name:
        provenance_detail = f"{handoff.table_name} · {provenance_detail}"
    return {
        "name": handoff.name,
        "family": family,
        "provenance_detail": provenance_detail,
        "readiness": matched,
    }


def _trace_lens_entity_card(session, canonical: str) -> dict[str, Any]:
    """Descriptive entity-card metadata -- never a pill/state/blocker, so it
    is not subject to the single-producer readiness_view rule the trace_refs/
    unrelated_blockers are. `field_count` comes from
    identity_roles.authoritative_entity (the same CRUD-entity lookup
    readiness_view._entity_item's own ready/needs_action state is ultimately
    keyed to); `key` comes directly from
    edge_contracts._safe_persistence_fields -- the same helper
    readiness_view._entity_item calls to decide entity readiness -- taking
    the alphabetically-first field when more than one is set, so the card
    always shows a deterministic single key rather than an arbitrary one;
    `contract_count` counts this entity's upstream+downstream interfaces
    whose type is an edge-contract type (EDGE_CONTRACT_TYPES), i.e. excludes
    REST/OpenAPI interfaces and staging handoffs -- matching the design
    mock's own "N contracts" count."""
    entity = identity_roles.authoritative_entity(session, canonical)
    field_count = len(entity.fields) if entity is not None else 0
    persistence_fields = _safe_persistence_fields(session, canonical)
    key = min(persistence_fields) if persistence_fields else None
    role_count = len(identity_roles.active_identity_decisions_by_field(session).get(canonical, {}))
    contract_count = sum(
        1
        for iface in (*session.upstream_interfaces, *session.downstream_interfaces)
        if iface.entity_name == canonical and iface.type in EDGE_CONTRACT_TYPES
    )
    return {
        "key": key,
        "field_count": field_count,
        "role_count": role_count,
        "contract_count": contract_count,
    }


def _trace_lens_entity(
    session,
    canonical: str,
    attention_items: list[readiness_view.ReadinessItem],
) -> dict[str, Any]:
    upstream_refs = [
        _interface_trace_ref(session, iface, item_kind=readiness_view.ITEM_KIND_UPSTREAM_CONTRACT)
        for iface in session.upstream_interfaces
        if iface.entity_name == canonical
    ]
    downstream_refs = [
        _interface_trace_ref(session, iface, item_kind=readiness_view.ITEM_KIND_DOWNSTREAM_INTERFACE)
        for iface in session.downstream_interfaces
        if iface.entity_name == canonical
    ]
    handoff_refs = [
        _handoff_trace_ref(session, handoff)
        for handoff in session.data_handoffs
        if handoff.entity_name == canonical
    ]

    own_keys = {(readiness_view.ITEM_KIND_UPSTREAM_CONTRACT, ref["name"]) for ref in upstream_refs}
    own_keys |= {(readiness_view.ITEM_KIND_DOWNSTREAM_INTERFACE, ref["name"]) for ref in downstream_refs}
    own_keys |= {(readiness_view.ITEM_KIND_HANDOFF, ref["name"]) for ref in handoff_refs}

    # Every blocker of every unrelated represented attention item -- not just
    # blockers[0]. An item with two blockers (e.g. an xml-xsd interface
    # missing both xsd_path and root element) must surface both chips, or
    # tracing another entity silently hides the second one. Package-wide
    # blockers that are not item-shaped remain owned by the completeness gate.
    unrelated_blockers = [
        {"label": blk.label, "deep_link": blk.deep_link}
        for readiness_item in attention_items
        if (readiness_item.item_kind, readiness_item.display_name) not in own_keys
        for blk in readiness_item.blockers
    ]

    return {
        "entity": canonical,
        "card": _trace_lens_entity_card(session, canonical),
        "upstream": upstream_refs,
        "downstream": downstream_refs,
        "handoffs": handoff_refs,
        "unrelated_blockers": unrelated_blockers,
    }


def _trace_lens_context(session) -> dict[str, Any]:
    """Build the full Trace Lens context: the `.rsummary` counts plus one
    entity block per identity_roles.selected_canonical_entities(session) --
    the same CRUD-entity selection readiness_view._entity_items() itself
    calls for step 3, so `trace_lens_entities` lines up 1:1 with
    items_for_step(session, 3)."""
    upstream_items = readiness_view.items_for_step(session, 2)
    entity_items = readiness_view.items_for_step(session, 3)
    handoff_items = readiness_view.items_for_step(session, 4)
    downstream_items = readiness_view.items_for_step(session, 5)

    summary = _trace_lens_summary(upstream_items, entity_items, handoff_items, downstream_items)

    # Unrelated-blockers candidates are scoped to represented steps 2/4/5
    # (interfaces + handoffs) only -- never step 3 (entity items) or
    # unitemized project-level completeness blockers -- per the build packet:
    # an entity's own needs_action (missing persistence key) is about that
    # entity itself, not "a blocker connected to some other entity", so it
    # never belongs in any entity's unrelated-blockers strip.
    attention_items = [
        readiness_item
        for readiness_item in (*upstream_items, *handoff_items, *downstream_items)
        if readiness_item.state in _TRACE_ATTENTION_STATES or readiness_item.export_blocking
    ]

    entities = [
        _trace_lens_entity(session, canonical, attention_items)
        for canonical in identity_roles.selected_canonical_entities(session)
    ]
    return {"summary": summary, "entities": entities}


@router.get("", response_class=HTMLResponse)
async def step7_get(request: Request):
    session = get_current_session(request)
    nav = build_nav_context(session, "/review")
    manifest_yaml = generate_manifest_yaml(session)
    report = build_completeness_report(session)
    completeness_deep_links = _completeness_deep_links(session, report)
    provenance = _attach_provenance_display_labels(build_review_provenance(session))
    workspace_before = workspace_session_marker(session)
    advisory_conflicts = assist_service.get_advisory_conflicts(
        session,
        canonical_entities=_selected_canonical_entities(session),
        include_empty_state=False,
    )
    knowledge_assist_enabled = assist_service.is_enabled(session)
    manifest_drawer = _build_manifest_drawer_state(session, manifest_yaml)
    project_summary = _build_project_review_summary(session)
    evidence_coverage = _build_evidence_coverage(session)
    step6_rule_artifacts = _build_step6_rule_review_artifacts(session)
    identity_role_history = _build_identity_role_history(session)
    rule_yaml_previews = _build_rule_yaml_previews(session)
    ka_validation_review_history = _build_ka_validation_review_history(session)
    ka_rule_review_history = _build_ka_rule_review_history(session)
    ka_mapping_review_history = _build_ka_mapping_review_history(session)
    ka_transform_review_history = _build_ka_transform_review_history(session)
    ka_conflict_review_history = _build_ka_conflict_review_history(session)
    ka_portfolio_review_history = _build_ka_portfolio_review_history(session)
    ka_generated_history_has_entries = _ka_generated_history_has_entries(
        provenance,
        ka_validation_review_history,
        ka_rule_review_history,
        ka_mapping_review_history,
        ka_transform_review_history,
    )
    ka_advisory_history_has_entries = _ka_generated_history_has_entries(
        ka_conflict_review_history,
        ka_portfolio_review_history,
    )
    decision_history_filters = _build_decision_history_filters(
        provenance,
        ka_validation_review_history,
        ka_rule_review_history,
        ka_mapping_review_history,
        ka_transform_review_history,
        ka_conflict_review_history,
        ka_portfolio_review_history,
        identity_role_history,
        step6_rule_artifacts,
    )
    ka_decision_history_empty = all(
        history.get("empty", True)
        for history in (
            provenance,
            ka_validation_review_history,
            ka_rule_review_history,
            ka_mapping_review_history,
            ka_transform_review_history,
            ka_conflict_review_history,
            ka_portfolio_review_history,
        )
    )
    conflict_query_candidates = _conflict_query_candidates(session)
    conflict_resolution_badge = assist_service.get_conflict_resolution_badge(
        session,
        query_candidates=conflict_query_candidates,
        drawer_url="/review/ks/drawer?scope=conflict_resolution",
    )
    portfolio_query_candidates = _portfolio_query_candidates(session)
    portfolio_reuse_badge = assist_service.get_portfolio_reuse_badge(
        session,
        query_candidates=portfolio_query_candidates,
        drawer_url="/review/ks/drawer?scope=portfolio_reuse",
    )
    # Step 7 always renders the Trace Lens after the PR-24 flag retirement.
    trace_lens = _trace_lens_context(session)
    trace_lens_summary = trace_lens["summary"] if trace_lens else _TRACE_LENS_EMPTY_SUMMARY
    trace_lens_entities = trace_lens["entities"] if trace_lens else []
    save_current_session_if_workspace_changed(request, session, workspace_before)
    return templates.TemplateResponse(request, "step7_review.html", {
        "request": request,
        "session": session,
        "step": 7,
        "manifest_yaml": manifest_yaml,
        "report": report,
        "export_gate": _export_gate(report),
        "completeness_deep_links": completeness_deep_links,
        "ks_provenance": provenance,
        "knowledge_assist_enabled": knowledge_assist_enabled,
        "advisory_conflicts": advisory_conflicts,
        "manifest_drawer": manifest_drawer,
        "project_summary": project_summary,
        "evidence_coverage": evidence_coverage,
        "step6_rule_artifacts": step6_rule_artifacts,
        "identity_role_history": identity_role_history,
        "rule_yaml_previews": rule_yaml_previews,
        "ka_validation_review_history": ka_validation_review_history,
        "ka_rule_review_history": ka_rule_review_history,
        "ka_mapping_review_history": ka_mapping_review_history,
        "ka_transform_review_history": ka_transform_review_history,
        "ka_conflict_review_history": ka_conflict_review_history,
        "ka_portfolio_review_history": ka_portfolio_review_history,
        "ka_generated_history_has_entries": ka_generated_history_has_entries,
        "ka_advisory_history_has_entries": ka_advisory_history_has_entries,
        "ka_decision_history_empty": ka_decision_history_empty,
        "decision_history_filters": decision_history_filters,
        "conflict_resolution_badge": conflict_resolution_badge,
        "portfolio_reuse_badge": portfolio_reuse_badge,
        "trace_lens_summary": trace_lens_summary,
        "trace_lens_entities": trace_lens_entities,
        "shell_drawer_default": "expanded",
        "shell_rail_default": "collapsed",
        **nav,
    })


@router.post("/approve", response_class=JSONResponse)
async def review_approve(request: Request):
    session = get_current_session(request)
    payload = await request.json()
    session.review_approved = bool(payload.get("approved", True))
    save_current_session(request, session)
    return JSONResponse(
        {
            "ok": True,
            "review_approved": session.review_approved,
        }
    )


@router.get("/manifest-preview", response_class=JSONResponse)
async def manifest_preview(request: Request):
    session = get_current_session(request)
    return JSONResponse({"yaml": generate_manifest_yaml(session)})


@router.get("/ks/drawer", response_class=JSONResponse)
async def review_ks_drawer(request: Request, scope: str = Query("conflict_resolution")):
    session = get_current_session(request)
    if scope not in {"conflict_resolution", "portfolio_reuse"}:
        return JSONResponse(
            {
                "ok": False,
                "warning": f"Unsupported review Knowledge Assist drawer scope '{scope}'.",
            },
            status_code=400,
        )
    if scope == "conflict_resolution":
        workspace_before = workspace_session_marker(session)
        drawer = assist_service.fetch_conflict_resolution_drawer(
            session,
            query_candidates=_conflict_query_candidates(session),
        )
        fallback_title = "Conflict Resolution Suggestions"
    else:
        workspace_before = workspace_session_marker(session)
        drawer = assist_service.fetch_portfolio_reuse_drawer(
            session,
            query_candidates=_portfolio_query_candidates(session),
        )
        fallback_title = "Portfolio Reuse Suggestions"
    save_current_session_if_workspace_changed(request, session, workspace_before)

    payload = drawer.to_dict() if drawer else {
        "ok": True,
        "scope": scope,
        "title": fallback_title,
        "entity": None,
        "scopes": [],
        "warnings": [],
        "empty": True,
    }
    payload = _apply_step7_review_statuses(payload, session, scope)
    if payload.get("ok") is not False and assist_service.is_enabled(session):
        payload["review_url"] = "/review/ks/review"
    return JSONResponse(payload)


@router.post("/ks/review", response_class=JSONResponse)
async def review_ks_review(request: Request):
    session = get_current_session(request)
    if not assist_service.is_enabled(session):
        return JSONResponse(
            {
                "ok": False,
                "message": "Knowledge Assist is off. Enable it in Step 1 before reviewing Step 7 suggestions.",
                "saved_count": 0,
                "failed_count": 0,
                "outcomes": [],
            },
            status_code=400,
        )

    payload = await request.json()
    raw_decisions = payload.get("decisions")
    raw_list = raw_decisions if isinstance(raw_decisions, list) else []
    suggestion_types = {
        str(item.get("suggestion_type") or "").strip()
        for item in raw_list
        if isinstance(item, dict)
    }
    if suggestion_types == {"portfolio_reuse"}:
        decisions, errors = _normalize_portfolio_review_decisions(raw_decisions)
        decision_kind = "portfolio"
    elif suggestion_types <= {"conflict_resolution"}:
        decisions, errors = _normalize_conflict_review_decisions(raw_decisions)
        decision_kind = "conflict"
    else:
        decisions, errors = [], ["Review decisions must use a single supported Step 7 suggestion type."]
    if errors:
        return JSONResponse({"ok": False, "errors": errors}, status_code=400)
    if not decisions:
        return JSONResponse(
            {
                "ok": True,
                "skipped": True,
                "message": "No staged Step 7 review decisions to save.",
                "outcomes": [],
                "saved_count": 0,
                "failed_count": 0,
                "warnings": [],
            }
        )

    if decision_kind == "portfolio":
        ks_result = assist_service.submit_portfolio_reuse_decisions(
            session,
            decisions=[_ks_portfolio_review_payload(decision) for decision in decisions],
        )
        failure_message = "Portfolio review decisions could not be saved. Please try again."
    else:
        ks_result = assist_service.submit_conflict_resolution_decisions(
            session,
            decisions=[_ks_conflict_review_payload(decision) for decision in decisions],
        )
        failure_message = "Conflict review decisions could not be saved. Please try again."
    if ks_result is None:
        return JSONResponse(
            {
                "ok": False,
                "message": failure_message,
                "outcomes": [],
                "saved_count": 0,
                "failed_count": len(decisions),
                "warnings": [],
            },
            status_code=503,
        )

    successful_ids = _successful_outcome_ids(ks_result, decisions)
    outcomes: list[dict[str, Any]] = []
    for decision in decisions:
        suggestion_id = decision["suggestion_id"]
        success = suggestion_id in successful_ids
        if success:
            if decision_kind == "portfolio":
                review_context = {
                    "portfolio_query": str(
                        decision["payload"].get("portfolio_query") or ""
                    ).strip(),
                    "matched_project_id": str(
                        decision["payload"].get("matched_project_id") or ""
                    ).strip(),
                    "document_ids": _portfolio_payload_list(
                        decision["payload"],
                        "document_ids",
                        "source_document_ids",
                        "documents",
                    ),
                    "document_labels": _portfolio_payload_list(
                        decision["payload"],
                        "document_labels",
                        "document_names",
                        "documents",
                    ),
                }
                suggestion_type = "portfolio_reuse"
            else:
                review_context = _conflict_payload_review_context(
                    decision["payload"],
                    decision["edited_payload"] if decision["status"] == "edited" else None,
                )
                suggestion_type = "conflict_resolution"
            edited_payload = decision["edited_payload"] if decision["status"] == "edited" else None
            record_review_history_without_evidence(
                session,
                suggestion_id=suggestion_id,
                suggestion_type=suggestion_type,
                status=decision["status"],
                manifest_path=decision["manifest_path"],
                edited_payload=edited_payload,
                review_context=review_context,
            )
        outcomes.append(
            {
                "suggestion_id": suggestion_id,
                "status": decision["status"],
                "success": success,
                "manifest_path": decision["manifest_path"],
            }
        )

    save_current_session(request, session)
    saved_count = sum(1 for outcome in outcomes if outcome["success"])
    failed_count = len(outcomes) - saved_count
    return JSONResponse(
        {
            "ok": failed_count == 0,
            "partial_failure": failed_count > 0,
            "message": (
                f"Saved {saved_count} Step 7 review decision"
                f"{'' if saved_count == 1 else 's'}."
            ),
            "outcomes": outcomes,
            "saved_count": saved_count,
            "failed_count": failed_count,
            "warnings": [],
            "refresh": saved_count > 0,
        }
    )
