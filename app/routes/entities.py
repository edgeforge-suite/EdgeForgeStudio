"""Step 3 — Entity + Operation Selection."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.integrations.ks_integration import KSCallError, KSUnavailableError
from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    EntityRules,
    IdentityRoleDecision,
    KSEvidenceLink,
    KSReviewHistoryEntry,
    OperationMapping,
    OperationSample,
    ProjectSession,
    RuleEntry,
    UpstreamInterface,
)
from app.paths import TEMPLATE_DIR
from app.services import readiness_view
from app.services.assist_service import AssistService
from app.services.canonical_mapping_validation import (
    canonical_fields_for_entity,
    upstream_mapping_target_issues,
)
from app.services.edge_contracts import (
    EDGE_CONTRACT_TYPES,
    SOAP_MAPPING_MODE_CANONICAL,
    SOAP_WSDL_TYPE,
    XML_XSD_TYPE,
    edge_contract_readiness,
)
from app.services.identity_roles import (
    IDENTITY_ROLE_VALUES,
    active_identity_decisions_by_field,
    eligible_identity_fields,
    identity_role_behavior,
    identity_role_review_context,
    is_wrapper_identity_field,
)
from app.services.identity_roles import (
    authoritative_entity as identity_authoritative_entity,
)
from app.services.identity_roles import (
    selected_canonical_entities as identity_selected_canonical_entities,
)
from app.services.ks_lifecycle import ks_client
from app.services.ks_workspace import (
    ensure_workspace_identity,
    mark_workspace_active,
    workspace_allowed_roots,
    workspace_db_path,
)
from app.services.nav_context import build_nav_context
from app.services.openapi_service import (
    _component_schemas,
    classify_openapi_spec,
    generate_field_mapping_plan,
    generate_operation_samples,
    parse_openapi_text,
)
from app.services.session_context import (
    get_current_session,
    save_current_session,
    save_current_session_if_workspace_changed,
    workspace_session_marker,
)

router = APIRouter(prefix="/entities")
templates = Jinja2Templates(directory=TEMPLATE_DIR)
assist_service = AssistService()
PAGINATION_WRAPPER_KEYS: tuple[str, ...] = (
    "content",
    "totalElements",
    "totalPages",
    "pageable",
    "last",
    "first",
    "size",
    "number",
    "sort",
    "empty",
    "numberOfElements",
)
PAGINATION_METADATA_KEYS: tuple[str, ...] = tuple(
    key for key in PAGINATION_WRAPPER_KEYS if key != "content"
)


def _identity_id_looking(field: dict[str, Any]) -> bool:
    """Return deterministic identity candidates for the review-only filter."""
    if field.get("is_id"):
        return True
    name = str(field.get("name") or "").strip()
    field_type = str(field.get("type") or "").strip().lower()
    return bool(
        re.search(r"(?:^|[_-])(?:id|number|uuid)$", name, re.IGNORECASE)
        or re.search(r"(?:Id|ID|Number|Uuid|UUID)$", name)
        or "uuid" in field_type
    )


def _identity_role_lens_context(
    identity_role_review: dict[str, Any],
    entity_readiness_items: list[readiness_view.ReadinessItem],
) -> dict[str, Any]:
    """Project the existing identity/readiness producers into the Step 3 lens."""
    readiness_by_name = {item.display_name: item for item in entity_readiness_items}
    role_options = {
        option["value"]: option
        for option in identity_role_review.get("role_options", [])
    }
    entities: list[dict[str, Any]] = []
    persistence_count = 0
    metadata_role_count = 0
    no_role_hidden = 0

    for source_entity in identity_role_review.get("entities", []):
        fields: list[dict[str, Any]] = []
        persistence_field = None
        assigned_count = 0
        id_looking_fields: list[str] = []
        required_fields: list[str] = []
        source_fields = source_entity.get("fields", [])
        large_entity = len(source_fields) > 50

        for source_field in source_fields:
            current_role = source_field.get("current_role", "")
            option = role_options.get(current_role, role_options.get("", {}))
            field = {
                **source_field,
                "current_engine_behavior": option.get(
                    "current_engine_behavior", "No identity-role behavior is generated."
                ),
                "impact_badge": option.get("impact_badge", "No role"),
                "affects_engine": bool(option.get("affects_engine")),
                "default_visible": bool(current_role) or (
                    large_entity and bool(source_field.get("required"))
                ),
            }
            fields.append(field)
            if _identity_id_looking(source_field):
                id_looking_fields.append(source_field["name"])
            if source_field.get("required"):
                required_fields.append(source_field["name"])
            if current_role:
                assigned_count += 1
                if current_role == "persistence_id":
                    persistence_field = field
                else:
                    metadata_role_count += 1
        hidden_no_role_count = sum(
            1
            for field in fields
            if not field["current_role"] and not field["default_visible"]
        )
        no_role_hidden += hidden_no_role_count

        if persistence_field:
            persistence_count += 1
        readiness = readiness_by_name.get(source_entity["name"])
        missing_key = bool(
            readiness
            and any(blocker.code == "missing-persistence-key" for blocker in readiness.blockers)
        )
        entities.append(
            {
                **source_entity,
                "fields": fields,
                "assigned_count": assigned_count,
                "no_role_count": sum(1 for field in fields if not field["current_role"]),
                "collapsed_count": hidden_no_role_count,
                "persistence_field": persistence_field,
                "id_looking_fields": id_looking_fields,
                "required_fields": required_fields,
                "large_entity": large_entity,
                "missing_key": missing_key,
                "model_persistence_field": next(
                    (field for field in fields if field["is_id"]),
                    None,
                ),
            }
        )

    return {
        "enabled": bool(identity_role_review.get("enabled")),
        "entities": entities,
        "stats": {
            "entities": len(entities),
            "persistence_ids": persistence_count,
            "metadata_roles": metadata_role_count,
            "no_role_hidden": no_role_hidden,
        },
        "empty_reason": identity_role_review.get("empty_reason", ""),
    }


def _identity_role_lens_for_session(
    session: ProjectSession,
) -> tuple[dict[str, Any], list[readiness_view.ReadinessItem], dict[str, Any]]:
    """Build the shared identity lens projection for initial render and live saves."""
    identity_role_review = identity_role_review_context(session)
    entity_readiness_items = readiness_view.items_for_step(session, 3)
    identity_role_lens = _identity_role_lens_context(
        identity_role_review,
        entity_readiness_items,
    )
    return identity_role_review, entity_readiness_items, identity_role_lens


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _detect_paginated_wrapper_fields(content: str | None) -> list[str]:
    """Return wrapper keys only when the sample strongly resembles pagination."""
    if not content:
        return []
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(parsed, dict):
        return []
    if "content" not in parsed or not isinstance(parsed.get("content"), list):
        return []
    present_keys = [key for key in PAGINATION_WRAPPER_KEYS if key in parsed]
    if not any(key in parsed for key in PAGINATION_METADATA_KEYS):
        return []
    return present_keys


def _apply_spec_source(iface: UpstreamInterface, session: ProjectSession) -> None:
    """Sync spec/spec_url/spec_content on an interface from the current Step-2 state.

    This must be called for BOTH newly created interfaces AND reused (existing)
    interfaces so that switching ingestion mode after Step 3 has already been saved
    (e.g. file → URL, URL → manual) refreshes the exported contract reference.
    Without this, a reused interface silently exports from the old source.
    """
    if session.raw_spec_url:
        iface.spec_url = session.raw_spec_url
        iface.spec = None
        iface.spec_content = None
    elif session.raw_spec_filename and session.raw_spec_content:
        # Only unchanged embedded content with no explicit package path keeps
        # the unset state that the package writer will derive later.
        if iface.spec is not None or iface.spec_content != session.raw_spec_content:
            iface.spec = f"upstream/{session.raw_spec_filename}"
        iface.spec_content = session.raw_spec_content
        iface.spec_url = None
    else:
        # Manual / no-spec mode — clear everything so no stale reference survives
        iface.spec = None
        iface.spec_url = None
        iface.spec_content = None


def _is_step3_openapi_interface(iface: UpstreamInterface) -> bool:
    """Step 3 owns REST/OpenAPI operation interfaces, not edge-contract shells."""
    return iface.type not in EDGE_CONTRACT_TYPES


def _merge_step3_upstream_interfaces(
    existing_interfaces: list[UpstreamInterface],
    step3_interfaces: list[UpstreamInterface],
) -> list[UpstreamInterface]:
    """Replace only Step-3-owned REST/OpenAPI interfaces and preserve edge contracts."""
    step3_by_entity = {iface.entity_name: iface for iface in step3_interfaces}
    placed_entities: set[str | None] = set()
    merged: list[UpstreamInterface] = []

    for iface in existing_interfaces:
        if not _is_step3_openapi_interface(iface):
            merged.append(iface)
            continue

        replacement = step3_by_entity.get(iface.entity_name)
        if replacement is None:
            continue
        merged.append(replacement)
        placed_entities.add(replacement.entity_name)

    for iface in step3_interfaces:
        if iface.entity_name not in placed_entities:
            merged.append(iface)

    return merged


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


def _step3_ka_summary(
    session,
    selected_entities: list[str],
    validation_hint_badges: list[Any],
    identity_role_badges: list[Any],
) -> dict[str, Any]:
    """Build a read-only Step 3 KA summary without adding new KS calls."""
    selected_set = set(selected_entities)
    status_totals: dict[str, dict[str, int]] = {
        "field": {"accepted": 0, "edited": 0, "rejected": 0},
        "validation": {"accepted": 0, "edited": 0, "rejected": 0},
        "identity_role": {"accepted": 0, "edited": 0, "rejected": 0},
    }
    latest_entries: dict[str, Any] = {}

    def _entry_entity(entry: KSReviewHistoryEntry) -> str:
        context = entry.review_context if isinstance(entry.review_context, dict) else {}
        entity = str(context.get("entity") or "").strip()
        if entity:
            return entity
        match = re.match(r"^entities\.([^.]+)\.", str(entry.manifest_path or ""))
        return match.group(1) if match else ""

    def _entry_key(entry: KSReviewHistoryEntry) -> str:
        context = entry.review_context if isinstance(entry.review_context, dict) else {}
        for context_key in (
            "validation_fallback_key",
            "identity_role_fallback_key",
        ):
            if not context_key.startswith(entry.type):
                continue
            value = str(context.get(context_key) or "").strip().lower()
            if value:
                return f"{entry.type}:{context_key}:{value}"
        if entry.suggestion_id:
            return f"{entry.type}:suggestion:{entry.suggestion_id}"
        return f"{entry.type}:path:{entry.manifest_path}"

    for entry in session.ks_workspace_state.review_history:
        if entry.type not in status_totals or entry.status not in status_totals[entry.type]:
            continue
        entry_entity = _entry_entity(entry)
        if selected_set and entry_entity and entry_entity not in selected_set:
            continue
        latest_entries[_entry_key(entry)] = entry

    for entry in latest_entries.values():
        status_totals[entry.type][entry.status] += 1
    latest_statuses: dict[str, str] = {}
    for key, entry in latest_entries.items():
        latest_statuses[key] = entry.status
        if entry.suggestion_id:
            latest_statuses[f"{entry.type}:suggestion:{entry.suggestion_id}"] = entry.status
        if entry.manifest_path:
            latest_statuses[f"{entry.type}:path:{entry.manifest_path}"] = entry.status

    def _badge_count(badges: list[Any]) -> int:
        return sum(max(int(getattr(badge, "count", 0) or 0), 0) for badge in badges)

    validation_badge_count = _badge_count(validation_hint_badges)
    identity_role_badge_count = _badge_count(identity_role_badges)
    rows: list[dict[str, Any]] = [
        {
            "key": "field",
            "label": "Field suggestions",
            "pending": None,
            "note": "Open review to inspect",
            **status_totals["field"],
        },
        {
            "key": "validation",
            "label": "Validation hints",
            "pending": None,
            "note": "Open review to inspect" if validation_badge_count else "No current hints detected",
            **status_totals["validation"],
        },
        {
            "key": "identity_role",
            "label": "Identity roles",
            "pending": None,
            "note": "Open review to inspect" if identity_role_badge_count else "No current suggestions detected",
            **status_totals["identity_role"],
        },
    ]
    has_items = any(
        row.get("accepted", 0) > 0
        or row.get("edited", 0) > 0
        or row.get("rejected", 0) > 0
        for row in rows
    ) or validation_badge_count > 0 or identity_role_badge_count > 0
    return {
        "enabled": True,
        "selected_entities": selected_entities,
        "rows": rows,
        "has_items": has_items,
        "latest_statuses": latest_statuses,
        "empty_message": (
            "No Knowledge Assist items are currently available for the selected entities."
        ),
    }


def _resolve_canonical_entity(session, requested_entity: str | None) -> tuple[str | None, list[str]]:
    available_entities = _selected_canonical_entities(session)
    if not available_entities:
        return None, available_entities
    if requested_entity:
        if requested_entity in available_entities:
            return requested_entity, available_entities
        return None, available_entities
    return available_entities[0], available_entities


def _step3_field_suggestions_payload(
    session,
    selected_entity: str,
    available_entities: list[str],
    assist_result: dict[str, Any] | None,
) -> dict[str, Any]:
    if not assist_result:
        return {
            "ok": True,
            "entity": selected_entity,
            "selected_entities": available_entities,
            "suggestions": [],
            "empty": True,
            "empty_reason": "Knowledge Assist is off or unavailable for this field suggestion request.",
            "knowledge_url": "/knowledge",
        }

    if assist_result.get("ok") is False:
        warnings = [
            str(warning)
            for warning in assist_result.get("warnings", [])
            if str(warning or "").strip()
        ]
        return {
            "ok": True,
            "entity": selected_entity,
            "selected_entities": available_entities,
            "project_id": assist_result.get("project_id"),
            "suggestions": [],
            "suggestion_count": 0,
            "raw_suggestion_count": 0,
            "warnings": warnings,
            "empty": True,
            "empty_reason": f"Knowledge Assist field suggestions could not be loaded for {selected_entity}.",
            "knowledge_url": "/knowledge",
        }

    project_id = assist_result["project_id"]
    catalog_result = assist_result["catalog_result"]
    suggestion_result = assist_result.get("suggestion_result")
    if not suggestion_result:
        return {
            "entity": selected_entity,
            "selected_entities": available_entities,
            "ok": True,
            "suggestions": [],
            "empty": True,
            "empty_reason": (
                f"No indexed Knowledge Workspace field catalog is available for {selected_entity} yet."
            ),
            "knowledge_url": "/knowledge",
            "warnings": catalog_result.get("warnings", []),
        }

    suggestions, normalization_warnings = _normalize_step3_field_suggestions(
        session,
        selected_entity,
        suggestion_result.get("suggestions", []),
    )
    ks_warnings = [
        str(warning)
        for warning in suggestion_result.get("warnings", [])
        if str(warning or "").strip()
    ]
    warnings = [*ks_warnings, *normalization_warnings]
    return {
        "ok": True,
        "entity": selected_entity,
        "selected_entities": available_entities,
        "project_id": project_id,
        "suggestions": suggestions,
        "suggestion_count": len(suggestions),
        "raw_suggestion_count": suggestion_result.get("suggestion_count", len(suggestions)),
        "warnings": warnings,
        "empty": len(suggestions) == 0,
        "empty_reason": (
            f"No actionable KS field suggestions are currently available for {selected_entity}."
            if not suggestions
            else None
        ),
        "knowledge_url": "/knowledge",
    }


def _step3_drawer_payload_from_result(
    session,
    *,
    scope: str,
    canonical_entity: str,
    available_entities: list[str],
    batch_result: dict[str, Any] | None,
) -> dict[str, Any]:
    title = "Identity Role Suggestions" if scope == "identity_role" else "Validation Hints"
    if batch_result and batch_result.get("ok") is False:
        warnings = [
            str(warning)
            for warning in batch_result.get("warnings", [])
            if str(warning or "").strip()
        ]
        payload: dict[str, Any] = {
            "ok": True,
            "scope": scope,
            "title": title,
            "entity": canonical_entity,
            "scopes": [],
            "warnings": warnings,
            "empty": True,
        }
    else:
        result = batch_result.get("result") if isinstance(batch_result, dict) else None
        drawer = (
            assist_service.suggestion_drawer_from_result(
                scope=scope,
                entity=canonical_entity,
                result=result,
                session=session,
            )
            if result
            else None
        )
        payload = drawer.to_dict() if drawer else {
            "ok": True,
            "scope": scope,
            "title": title,
            "entity": canonical_entity,
            "scopes": [],
            "warnings": [],
            "empty": True,
        }

    return _finalize_step3_drawer_payload(
        session,
        scope=scope,
        canonical_entity=canonical_entity,
        available_entities=available_entities,
        payload=payload,
    )


def _finalize_step3_drawer_payload(
    session,
    *,
    scope: str,
    canonical_entity: str,
    available_entities: list[str],
    payload: dict[str, Any],
) -> dict[str, Any]:
    if scope == "identity_role":
        payload = _normalize_identity_role_drawer_payload(session, canonical_entity, payload)
        payload = _apply_identity_role_drawer_review_statuses(payload, session, canonical_entity)
        payload["review_url"] = "/entities/ks/identity-role-review"
    else:
        payload = _normalize_validation_drawer_payload(session, canonical_entity, payload)
        payload = _apply_validation_drawer_review_statuses(payload, session, canonical_entity)
        payload["review_url"] = "/entities/ks/validation-review"
    payload["selected_entities"] = available_entities
    return payload


def _authoritative_entity_owner(session, canonical_entity: str) -> ClassifiedEntity | None:
    selected_names = set(session.selected_entity_names)
    for entity in session.classified_entities:
        if entity.name in selected_names and entity.display_name() == canonical_entity:
            return entity
    for entity in session.classified_entities:
        if entity.display_name() == canonical_entity:
            return entity
    return None


def _schema_name_for_canonical_entity(session, canonical_entity: str) -> str | None:
    selected_names = set(session.selected_entity_names)
    for entity in session.classified_entities:
        if entity.name in selected_names and entity.display_name() == canonical_entity:
            return entity.name
    for entity in session.classified_entities:
        if entity.display_name() == canonical_entity:
            return entity.name
    return None


def _canonical_field_key(value: Any) -> str:
    """Match common catalog/source spellings to Studio's current CRUD field names."""
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _resolve_current_crud_field(
    session,
    canonical_entity: str,
    field_name: str,
) -> ClassifiedField | None:
    owner = _authoritative_entity_owner(session, canonical_entity)
    if owner is None:
        return None
    field_text = str(field_name or "").strip()
    if not field_text:
        return None
    for field in owner.fields:
        if field.name == field_text:
            return field
    field_key = _canonical_field_key(field_text)
    if not field_key:
        return None
    matches = [field for field in owner.fields if _canonical_field_key(field.name) == field_key]
    return matches[0] if len(matches) == 1 else None


def _upsert_authoritative_field(
    session,
    canonical_entity: str,
    field_name: str,
    field_type: str | None,
    nullable: bool | None = None,
) -> None:
    owner = _authoritative_entity_owner(session, canonical_entity)
    normalized_name = field_name.strip()
    normalized_type = (field_type or "").strip()
    if owner is None or not normalized_name:
        return

    for field in owner.fields:
        if field.name == normalized_name:
            if normalized_type:
                field.type = normalized_type
            if nullable is not None:
                field.required = not nullable
            return

    if not normalized_type:
        return

    owner.fields.append(
        ClassifiedField(
            name=normalized_name,
            type=normalized_type,
            required=not nullable if nullable is not None else False,
        )
    )


def _manifest_path_for_field(canonical_entity: str, field_name: str) -> str:
    return f"entities.{canonical_entity}.fields.{field_name}"


def _manifest_path_for_validation(canonical_entity: str, field_name: str, validation_type: str) -> str:
    return f"entities.{canonical_entity}.fields.{field_name}.validations.{validation_type}"


def _validation_review_fallback_key(
    entity: str,
    field_name: str,
    validation_type: str,
    manifest_path: str,
    constraint_fingerprint: str = "",
) -> str:
    parts = [
        str(entity or "").strip(),
        str(field_name or "").strip(),
        _normalize_validation_type(validation_type),
        str(manifest_path or "").strip(),
        str(constraint_fingerprint or "").strip(),
    ]
    return "|".join(parts).lower()


def _load_spec_schema_context(session) -> tuple[dict[str, Any], dict[str, Any]]:
    import yaml as _yaml

    all_schemas: dict[str, Any] = {}
    if session.raw_spec_content:
        try:
            spec_doc = _yaml.safe_load(session.raw_spec_content)
            all_schemas = _component_schemas(spec_doc)
        except Exception:
            all_schemas = {}

    op_lookup = {co.name: co for co in session.classified_operations}
    return all_schemas, op_lookup


def _serialize_interface_for_phase2(
    iface: UpstreamInterface,
    all_schemas: dict[str, Any],
    op_classified_lookup: dict[str, Any],
    session=None,
) -> dict[str, Any]:
    op_mapping_lookup: dict[str, OperationMapping] = {
        om.name: om for om in iface.operation_mappings
    }
    canonical_fields = (
        canonical_fields_for_entity(session, iface.entity_name)
        if session is not None
        else None
    )
    # A live Studio session without a selected canonical model must not receive
    # speculative Entity.field suggestions. Direct helper callers that omit a
    # session retain the legacy unfiltered behavior.
    automatic_mapping_fields = canonical_fields if session is None or canonical_fields is not None else set()
    mapping_issues = upstream_mapping_target_issues(session, iface) if session is not None else []
    ops_out = []
    for op in iface.operations:
        co = op_classified_lookup.get(op.name)
        req_schema = co.request_schema if co else None
        resp_schema = co.response_schema if co else None

        req_content = op.request_sample_content
        resp_content = op.response_sample_content
        if (not req_content or not resp_content) and all_schemas:
            auto_req, auto_resp = generate_operation_samples(req_schema, resp_schema, all_schemas)
            req_content = req_content or auto_req
            resp_content = resp_content or auto_resp

        saved_om = op_mapping_lookup.get(op.name, OperationMapping(name=op.name))
        req_mappings = [{"source": m.source, "target": m.target} for m in saved_om.request_mappings]
        resp_mappings = [{"source": m.source, "target": m.target} for m in saved_om.response_mappings]
        mapping_review_items = [
            issue.message
            for issue in mapping_issues
            if issue.operation_name == op.name
        ]

        if all_schemas:
            if resp_schema:
                saved_resp_sources = {m["source"] for m in resp_mappings}
                generated, omitted = generate_field_mapping_plan(
                    resp_schema,
                    iface.entity_name,
                    all_schemas,
                    canonical_fields=automatic_mapping_fields,
                )
                for row in generated:
                    if row["source"] not in saved_resp_sources:
                        resp_mappings.append(row)
                mapping_review_items.extend(
                    _automatic_mapping_review_message("Response", source, iface.entity_name)
                    for source in omitted
                    if source not in saved_resp_sources
                )
            if req_schema:
                saved_req_sources = {m["source"] for m in req_mappings}
                generated, omitted = generate_field_mapping_plan(
                    req_schema,
                    iface.entity_name,
                    all_schemas,
                    canonical_fields=automatic_mapping_fields,
                )
                for row in generated:
                    if row["source"] not in saved_req_sources:
                        req_mappings.append(row)
                mapping_review_items.extend(
                    _automatic_mapping_review_message("Request", source, iface.entity_name)
                    for source in omitted
                    if source not in saved_req_sources
                )

        operation_payload = {
            "name": op.name,
            "request_sample_content": req_content,
            "response_sample_content": resp_content,
            "request_mappings": req_mappings,
            "response_mappings": resp_mappings,
            "pagination_wrapper_fields": _detect_paginated_wrapper_fields(resp_content),
        }
        if mapping_review_items:
            operation_payload["mapping_review_items"] = mapping_review_items
        ops_out.append(operation_payload)
    payload: dict[str, Any] = {
        "name": iface.name,
        "entity_name": iface.entity_name,
        "type": iface.type,
        "spec_url": iface.spec_url,
        "spec": iface.spec,
        "operations": ops_out,
    }
    if iface.type in EDGE_CONTRACT_TYPES:
        payload["edge_contract"] = _edge_contract_phase2_payload(iface, session)
    return payload


def _automatic_mapping_review_message(direction: str, source: str, entity_name: str | None) -> str:
    return (
        f"{direction} field '{source}' is not part of selected canonical entity "
        f"'{entity_name or 'Unknown'}'; Studio omitted the automatic mapping. "
        "Add the field explicitly to the canonical entity before mapping it, or leave it unmapped."
    )


def _edge_contract_phase2_payload(iface: UpstreamInterface, session) -> dict[str, Any]:
    readiness = edge_contract_readiness(iface, direction="upstream", session=session)
    details: list[str] = []
    mapping_summary = ""
    entity_display = iface.entity_name or ""

    if iface.type == XML_XSD_TYPE:
        if readiness.artifact_path:
            details.append(f"XSD: {readiness.artifact_path}")
        if iface.root_element:
            details.append(f"Root element: {iface.root_element}")
        if iface.namespace:
            details.append(f"Namespace: {iface.namespace}")
        if iface.entity_name and iface.field_mappings:
            mapping_summary = (
                f"Reviewed XML mapping targets {iface.entity_name} "
                f"with {len(iface.field_mappings)} field mapping(s)."
            )
        elif iface.entity_name:
            mapping_summary = f"Canonical entity linked: {iface.entity_name}. No reviewed XML field mappings yet."
        else:
            mapping_summary = "No canonical entity linked for XML mapping yet."
    elif iface.type == SOAP_WSDL_TYPE:
        if readiness.artifact_path:
            details.append(f"WSDL: {readiness.artifact_path}")
        for label, value in (
            ("Service", iface.service),
            ("Port", iface.port),
            ("Binding", iface.binding),
            ("Operation", iface.selected_operation_name),
        ):
            if value:
                details.append(f"{label}: {value}")
        mode = iface.soap_operation_mode or "adapter_only"
        canonical = iface.soap_canonical_operation
        if mode == SOAP_MAPPING_MODE_CANONICAL and canonical:
            entity_display = canonical.entity or ""
            if iface.selected_operation_name and canonical.entity and canonical.lookup_field:
                mapping_summary = (
                    f"SOAP {iface.selected_operation_name} maps to "
                    f"{canonical.entity} read_by_id using {canonical.lookup_field}."
                )
            else:
                mapping_summary = "Canonical SOAP read_by_id mapping is incomplete."
        elif iface.selected_operation_name:
            entity_display = "Adapter only"
            mapping_summary = (
                f"SOAP {iface.selected_operation_name} uses adapter-only operation mapping. "
                "No canonical entity linked."
            )
        else:
            entity_display = "No canonical entity linked"
            mapping_summary = "SOAP/WSDL contract saved. Select an operation to export inbound endpoint mapping."

    return {
        "type": iface.type,
        "type_label": readiness.type_label,
        "status": readiness.status,
        "will_export": readiness.will_export,
        "artifact_path": readiness.artifact_path,
        "required_missing": readiness.required_missing,
        "warnings": readiness.warnings,
        "has_content_to_write": readiness.has_content_to_write,
        "details": details,
        "mapping_summary": mapping_summary,
        "entity_display": entity_display,
    }


def _build_phase2_interfaces_data(session, interfaces: list[UpstreamInterface] | None = None) -> list[dict[str, Any]]:
    all_schemas, op_classified_lookup = _load_spec_schema_context(session)
    working_interfaces = interfaces if interfaces is not None else session.upstream_interfaces
    return [
        _serialize_interface_for_phase2(iface, all_schemas, op_classified_lookup, session)
        for iface in working_interfaces
    ]


def _saved_operation_assignment_map(session) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for iface in session.upstream_interfaces:
        schema_name = _schema_name_for_canonical_entity(session, iface.entity_name or "")
        if not schema_name:
            continue
        for op in iface.operations:
            assignments.setdefault(op.name, schema_name)
    return assignments


def _restore_missing_operation_inventory(session: ProjectSession) -> bool:
    """Rebuild omitted OpenAPI operation metadata in older project snapshots.

    Some valid saved projects carry the selected operations and their mappings on
    upstream interfaces but have an empty ``classified_operations`` list.  Step 3
    cannot render operation controls from that shape, so an otherwise ordinary
    selection save would submit an empty operation set.  Only accept a recovered
    inventory when it covers every saved operation; partial recovery would make
    the same destructive ambiguity possible for the omitted names.
    """
    if session.app_archetype != "crud" or session.classified_operations:
        return False

    selected_entities = set(_selected_canonical_entities(session))
    saved_operation_names = [
        operation.name
        for iface in session.upstream_interfaces
        if _is_step3_openapi_interface(iface) and iface.entity_name in selected_entities
        for operation in iface.operations
    ]
    if not saved_operation_names or not session.raw_spec_content:
        return False

    try:
        spec = parse_openapi_text(session.raw_spec_content)
        _, recovered_operations = classify_openapi_spec(spec)
    except Exception:
        return False

    recovered_names = {operation.name for operation in recovered_operations}
    if not set(saved_operation_names).issubset(recovered_names):
        return False

    session.classified_operations = recovered_operations
    session.selected_operation_names = list(dict.fromkeys(
        [*session.selected_operation_names, *saved_operation_names]
    ))
    return True


def _set_review_bucket(session, suggestion_id: str, status: str) -> None:
    review_state = session.ks_workspace_state.suggestion_review_state
    for values in (
        review_state.accepted_ids,
        review_state.edited_ids,
        review_state.rejected_ids,
    ):
        while suggestion_id in values:
            values.remove(suggestion_id)

    if status == "accepted":
        review_state.accepted_ids.append(suggestion_id)
    elif status == "edited":
        review_state.edited_ids.append(suggestion_id)
    elif status == "rejected":
        review_state.rejected_ids.append(suggestion_id)


def _replace_evidence_link(
    session,
    suggestion_id: str,
    manifest_path: str,
    status: str,
) -> None:
    if status in {"accepted", "edited"}:
        session.ks_workspace_state.evidence_links = [
            link
            for link in session.ks_workspace_state.evidence_links
            if link.suggestion_id != suggestion_id and link.manifest_path != manifest_path
        ]
    else:
        session.ks_workspace_state.evidence_links = [
            link
            for link in session.ks_workspace_state.evidence_links
            if link.suggestion_id != suggestion_id
        ]

    if status == "accepted":
        provenance = "ai-accepted"
    elif status == "edited":
        provenance = "ai-edited"
    else:
        provenance = None

    if provenance is None:
        return

    session.ks_workspace_state.evidence_links.append(
        KSEvidenceLink(
            manifest_path=manifest_path,
            suggestion_id=suggestion_id,
            provenance=provenance,
        )
    )


_VALIDATION_TYPES = {
    "length",
    "not-null",
    "max-length",
    "min-length",
    "pattern",
    "range",
    "precision-scale",
}


def _normalize_validation_type(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _payload_text(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _field_suggestion_name(suggestion: dict[str, Any]) -> str:
    field_name = _payload_text(suggestion, "field_name", "field", "target_field")
    if field_name:
        return field_name
    payload = suggestion.get("payload")
    if isinstance(payload, dict):
        return _payload_text(payload, "field_name", "field", "target_field") or ""
    return ""


def _normalize_field_suggestion_row(suggestion: Any) -> Any:
    if not isinstance(suggestion, dict):
        return suggestion

    normalized = dict(suggestion)
    field_name = _field_suggestion_name(normalized)
    if field_name:
        normalized["field_name"] = field_name
        payload = normalized.get("payload")
        if isinstance(payload, dict):
            normalized_payload = dict(payload)
            normalized_payload.setdefault("field_name", field_name)
            normalized["payload"] = normalized_payload
    return normalized


def _suggested_field_type(suggestion: dict[str, Any]) -> str:
    payload = suggestion.get("payload") if isinstance(suggestion.get("payload"), dict) else {}
    return (
        _payload_text(suggestion, "suggested_type", "field_type", "type")
        or _payload_text(payload, "suggested_type", "field_type", "type")
        or ""
    )


def _coerce_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    return None


def _suggested_field_nullable(suggestion: dict[str, Any]) -> bool | None:
    payload = suggestion.get("payload") if isinstance(suggestion.get("payload"), dict) else {}
    for source in (suggestion, payload):
        if source.get("suggested_nullable") is not None:
            return _coerce_optional_bool(source.get("suggested_nullable"))
        if source.get("nullable") is not None:
            return _coerce_optional_bool(source.get("nullable"))
        if source.get("required") is not None:
            required = _coerce_optional_bool(source.get("required"))
            return None if required is None else not required
    return None


def _suggested_field_description(suggestion: dict[str, Any]) -> str:
    payload = suggestion.get("payload") if isinstance(suggestion.get("payload"), dict) else {}
    return (
        _payload_text(suggestion, "suggested_description", "description", "field_description")
        or _payload_text(payload, "suggested_description", "description", "field_description")
        or ""
    )


def _normalize_semantic_value(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _semantic_values_changed(current: Any, suggested: Any) -> bool:
    if isinstance(current, bool) or isinstance(suggested, bool):
        current_bool = _coerce_optional_bool(current)
        suggested_bool = _coerce_optional_bool(suggested)
        if current_bool is not None or suggested_bool is not None:
            return current_bool != suggested_bool
    return _normalize_semantic_value(current) != _normalize_semantic_value(suggested)


def _has_semantic_suggestion(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    return bool(str(value).strip())


def _field_delta(label: str, current: Any, suggested: Any, *, compare_missing: bool = False) -> dict[str, Any]:
    changed = (
        _semantic_values_changed(current, suggested)
        if compare_missing or _has_semantic_suggestion(suggested)
        else False
    )
    return {
        "label": label,
        "current": current,
        "suggested": suggested,
        "changed": changed,
    }


def _field_suggestion_semantics(
    current_field: ClassifiedField | None,
    *,
    current_field_name: str,
    suggested_field_name: str,
    suggested_type: str,
    suggested_nullable: bool | None,
    suggested_description: str,
) -> dict[str, Any]:
    current_type = current_field.type if current_field else ""
    current_nullable = (not current_field.required) if current_field else None
    current_description = str(getattr(current_field, "description", "") or "")

    deltas: list[dict[str, Any]] = [
        _field_delta("Field name", current_field_name, suggested_field_name, compare_missing=True),
        _field_delta("Type", current_type, suggested_type),
        _field_delta("Nullable", current_nullable, suggested_nullable),
        _field_delta("Description", current_description, suggested_description),
    ]
    changed_count = sum(1 for delta in deltas if delta.get("changed"))

    impacts: list[str] = []
    has_generated_impact = False
    if current_field is None:
        if suggested_type:
            impacts.append("Will add field")
            has_generated_impact = True
        else:
            impacts.append("Review needed. Knowledge Assist did not provide a field type, so Studio cannot add this field yet.")
    else:
        if suggested_type and _normalize_semantic_value(current_type) != _normalize_semantic_value(suggested_type):
            impacts.append("Will update type")
            has_generated_impact = True
        if suggested_nullable is not None and current_nullable != suggested_nullable:
            impacts.append("Will update nullable")
            has_generated_impact = True
        if suggested_description and _normalize_semantic_value(current_description) != _normalize_semantic_value(suggested_description):
            impacts.append("Description differs; Studio records the suggested description in review history only.")
    if not impacts:
        impacts.append("No change. Existing model already matches Knowledge Assist evidence.")

    already_satisfied = current_field is not None and impacts[0].startswith("No change")
    return {
        "category": (
            "Already satisfied"
            if already_satisfied
            else "Applies generated change"
            if has_generated_impact
            else "Review needed"
        ),
        "already_satisfied": already_satisfied,
        "impact": impacts,
        "deltas": deltas,
        "changed_count": changed_count,
        "compared_count": len(deltas),
        "current": {
            "field_name": current_field_name,
            "type": current_type,
            "nullable": current_nullable,
            "description": current_description,
        },
        "suggested": {
            "field_name": suggested_field_name,
            "type": suggested_type,
            "nullable": suggested_nullable,
            "description": suggested_description,
        },
    }


def _normalize_step3_field_suggestion_row(session, canonical_entity: str, suggestion: Any) -> Any:
    normalized = _normalize_field_suggestion_row(suggestion)
    if not isinstance(normalized, dict):
        return normalized
    field_name = str(normalized.get("field_name") or "").strip()
    resolved = _resolve_current_crud_field(session, canonical_entity, field_name)
    suggested_type = _suggested_field_type(normalized)
    suggested_nullable = _suggested_field_nullable(normalized)
    suggested_description = _suggested_field_description(normalized)
    if suggested_type:
        normalized.setdefault("suggested_type", suggested_type)
    if suggested_nullable is not None:
        normalized.setdefault("suggested_nullable", suggested_nullable)
    if suggested_description:
        normalized.setdefault("suggested_description", suggested_description)
    if resolved is not None:
        if resolved.name != field_name:
            normalized.setdefault("source_field_name", field_name)
            normalized["field_name"] = resolved.name
            payload = normalized.get("payload")
            if isinstance(payload, dict):
                normalized_payload = dict(payload)
                normalized_payload.setdefault("source_field_name", field_name)
                normalized_payload["field_name"] = resolved.name
                normalized["payload"] = normalized_payload
        normalized["current_field"] = {
            "field_name": resolved.name,
            "type": resolved.type,
            "nullable": not resolved.required,
            "description": str(getattr(resolved, "description", "") or ""),
        }
        normalized["suggestion_semantics"] = _field_suggestion_semantics(
            resolved,
            current_field_name=resolved.name,
            suggested_field_name=normalized["field_name"],
            suggested_type=suggested_type,
            suggested_nullable=suggested_nullable,
            suggested_description=suggested_description,
        )
        return normalized

    if not field_name or str(normalized.get("conflict_hint") or "").strip():
        normalized["actionable"] = False
        normalized["catalog_only_reason"] = (
            "This conflict hint references catalog evidence for a field that is not in "
            "the current CRUD model."
            if field_name
            else "Field name missing; this suggestion is catalog evidence only."
        )
        normalized["suggestion_semantics"] = {
            "category": "Advisory only",
            "already_satisfied": False,
            "impact": [normalized["catalog_only_reason"]],
            "deltas": [],
            "changed_count": 0,
            "compared_count": 0,
        }
    else:
        normalized["suggestion_semantics"] = _field_suggestion_semantics(
            None,
            current_field_name="",
            suggested_field_name=field_name,
            suggested_type=suggested_type,
            suggested_nullable=suggested_nullable,
            suggested_description=suggested_description,
        )
        if not suggested_type:
            normalized["actionable"] = False
            normalized["catalog_only_reason"] = (
                "Knowledge Assist suggested a new field but did not provide a type. "
                "Add a field type before Studio can apply it."
            )
    return normalized


def _normalize_step3_field_suggestions(
    session,
    canonical_entity: str,
    raw_suggestions: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Normalize Step 3 field suggestions and drop malformed blank-field rows."""
    normalized_rows: list[dict[str, Any]] = []
    skipped_blank = 0
    if not isinstance(raw_suggestions, list):
        return [], ["Knowledge Assist returned malformed field suggestions."]

    for suggestion in raw_suggestions:
        normalized = _normalize_step3_field_suggestion_row(session, canonical_entity, suggestion)
        if not isinstance(normalized, dict):
            continue
        if not str(normalized.get("field_name") or "").strip():
            skipped_blank += 1
            continue
        normalized_rows.append(normalized)

    warnings: list[str] = []
    if skipped_blank:
        warnings.append(
            f"Skipped {skipped_blank} malformed Knowledge Assist field suggestion"
            f"{'s' if skipped_blank != 1 else ''} without a field name."
        )
    return normalized_rows, warnings


def _validation_drawer_field_name(row: dict[str, Any]) -> str:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    return (
        _payload_text(row, "field", "field_name", "target_field")
        or _payload_text(payload, "field", "field_name", "target_field")
        or ""
    )


def _normalize_validation_drawer_payload(
    session,
    canonical_entity: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    scopes = payload.get("scopes")
    if not isinstance(scopes, list):
        return payload

    for scope in scopes:
        if not isinstance(scope, dict):
            continue
        rows = scope.get("rows")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            field_name = _validation_drawer_field_name(row)
            resolved = _resolve_current_crud_field(session, canonical_entity, field_name)
            if resolved is None:
                row_payload = dict(row_payload)
                row_payload["actionable"] = False
                row_payload["catalog_only_reason"] = (
                    f"Field '{canonical_entity}.{field_name or 'unknown'}' is not available "
                    "in the current CRUD model."
                )
                row["payload"] = row_payload
                row["status"] = row.get("status") or "catalog-only"
                warnings = row.get("warnings") if isinstance(row.get("warnings"), list) else []
                row["warnings"] = [
                    *warnings,
                    row_payload["catalog_only_reason"],
                ]
                continue

            if resolved.name != field_name:
                row_payload = dict(row_payload)
                row_payload.setdefault("source_field_name", field_name)
                row_payload["field"] = resolved.name
                row_payload["field_name"] = resolved.name
                if "target_field" in row_payload:
                    row_payload["target_field"] = resolved.name
                row["payload"] = row_payload
            row["title"] = f"Validation hint for {resolved.name}"
            row["manifest_path"] = _manifest_path_for_validation(
                canonical_entity,
                resolved.name,
                _validation_type_from_payload(row_payload) or "unknown",
            )
    return payload


def _validation_row_fallback_key(canonical_entity: str, row: dict[str, Any]) -> str:
    row_payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    field_name = _validation_drawer_field_name(row)
    validation_type = _validation_type_from_payload(row_payload) or "unknown"
    manifest_path = str(row.get("manifest_path") or "").strip()
    if not manifest_path:
        manifest_path = _manifest_path_for_validation(canonical_entity, field_name, validation_type)
    return _validation_review_fallback_key(
        canonical_entity,
        field_name,
        validation_type,
        manifest_path,
        _validation_constraint_fingerprint(row_payload),
    )


def _entry_validation_fallback_key(entry: KSReviewHistoryEntry) -> str:
    context = entry.review_context if isinstance(entry.review_context, dict) else {}
    if context.get("validation_fallback_key"):
        return str(context.get("validation_fallback_key") or "").strip().lower()
    return _validation_review_fallback_key(
        str(context.get("entity") or "").strip(),
        str(context.get("field") or "").strip(),
        str(context.get("validation_type") or "").strip(),
        entry.manifest_path,
        str(context.get("constraint_fingerprint") or "").strip(),
    )


def _apply_validation_drawer_review_statuses(
    payload: dict[str, Any],
    session,
    canonical_entity: str,
) -> dict[str, Any]:
    latest_by_id: dict[str, KSReviewHistoryEntry] = {}
    latest_by_key: dict[str, KSReviewHistoryEntry] = {}
    for entry in session.ks_workspace_state.review_history:
        if entry.type != "validation":
            continue
        latest_by_id[entry.suggestion_id] = entry
        fallback_key = _entry_validation_fallback_key(entry)
        if fallback_key.strip("|"):
            latest_by_key[fallback_key] = entry

    drawer_scopes = payload.get("scopes")
    if not isinstance(drawer_scopes, list):
        return payload
    for scope in drawer_scopes:
        rows = scope.get("rows") if isinstance(scope, dict) else None
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            suggestion_id = str(row.get("suggestion_id") or "").strip()
            fallback_key = _validation_row_fallback_key(canonical_entity, row)
            entry = (
                latest_by_id.get(suggestion_id)
                or latest_by_key.get(fallback_key)
            )
            if entry is None:
                continue
            row["status"] = entry.status
            row_payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            row_payload = dict(row_payload)
            row_payload["studio_review_status"] = entry.status
            row_payload["studio_reviewed_at"] = entry.reviewed_at
            row_payload["studio_review_match"] = (
                "suggestion_id"
                if entry.suggestion_id == suggestion_id
                else "validation_context"
            )
            if isinstance(entry.edited_payload, dict):
                row_payload["studio_edited_payload"] = entry.edited_payload
            row["payload"] = row_payload
    return payload


def _identity_role_from_payload(payload: dict[str, Any]) -> str:
    return _payload_text(payload, "role", "suggested_role", "identity_role")


def _identity_role_fallback_key(entity: str, field: str, role: str) -> str:
    return "|".join(
        [
            str(entity or "").strip(),
            str(field or "").strip(),
            str(role or "").strip(),
        ]
    ).lower()


def _normalize_identity_role_drawer_payload(
    session,
    canonical_entity: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    scopes = payload.get("scopes")
    if not isinstance(scopes, list):
        return payload

    for scope in scopes:
        if not isinstance(scope, dict):
            continue
        rows = scope.get("rows")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            row_payload = dict(row_payload)
            suggestion_entity = _payload_text(row_payload, "entity", "entity_name", "canonical_entity") or canonical_entity
            field_name = _payload_text(row_payload, "field", "field_name", "target_field")
            role = _identity_role_from_payload(row_payload)
            resolved = (
                _resolve_current_crud_field(session, canonical_entity, field_name)
                if suggestion_entity == canonical_entity
                else None
            )
            action_reason = ""
            if suggestion_entity != canonical_entity:
                action_reason = (
                    f"Knowledge Assist returned this identity suggestion for '{suggestion_entity}', "
                    f"but this drawer is reviewing '{canonical_entity}'."
                )
            elif resolved is None:
                action_reason = (
                    f"Field '{canonical_entity}.{field_name or 'unknown'}' is not available "
                    "in the current CRUD model."
                )
            elif is_wrapper_identity_field(session, canonical_entity, resolved.name):
                action_reason = (
                    f"Field '{canonical_entity}.{resolved.name}' is a transport wrapper/page field "
                    "and cannot receive an identity role."
                )
            elif role not in IDENTITY_ROLE_VALUES:
                action_reason = f"Identity role '{role or 'unknown'}' is not supported."

            row_payload["entity"] = canonical_entity
            if resolved is not None:
                if resolved.name != field_name:
                    row_payload.setdefault("source_field_name", field_name)
                row_payload["field"] = resolved.name
                row_payload["field_name"] = resolved.name
                row["manifest_path"] = _manifest_path_for_field(canonical_entity, resolved.name)
            if role:
                row_payload["suggested_role"] = role
                row_payload["role"] = role

            semantics = dict(row_payload.get("suggestion_semantics") or {})
            if action_reason:
                row_payload["actionable"] = False
                row_payload["catalog_only_reason"] = action_reason
                row["status"] = row.get("status") or "catalog-only"
                warnings = row.get("warnings") if isinstance(row.get("warnings"), list) else []
                row["warnings"] = [*warnings, action_reason]
                semantics["category"] = "Review needed"
            elif not semantics.get("category"):
                semantics["category"] = (
                    "Applies generated change" if role == "persistence_id" else "Advisory only"
                )
            behavior = identity_role_behavior(role)
            default_impact = " ".join(
                str(behavior.get(key) or "").strip()
                for key in ("current_engine_behavior", "export_behavior", "api_behavior")
                if str(behavior.get(key) or "").strip()
            )
            semantics.setdefault("export_impact", default_impact)
            row_payload["suggestion_semantics"] = semantics
            row["payload"] = row_payload
    return payload


def _apply_identity_role_drawer_review_statuses(
    payload: dict[str, Any],
    session,
    canonical_entity: str,
) -> dict[str, Any]:
    latest_by_id: dict[str, KSReviewHistoryEntry] = {}
    latest_by_key: dict[str, KSReviewHistoryEntry] = {}
    for entry in session.ks_workspace_state.review_history:
        if entry.type != "identity_role":
            continue
        latest_by_id[entry.suggestion_id] = entry
        context = entry.review_context if isinstance(entry.review_context, dict) else {}
        key = _identity_role_fallback_key(
            str(context.get("entity") or "").strip(),
            str(context.get("field") or "").strip(),
            str(context.get("role") or "").strip(),
        )
        if key.strip("|"):
            latest_by_key[key] = entry

    drawer_scopes = payload.get("scopes")
    if not isinstance(drawer_scopes, list):
        return payload
    for scope in drawer_scopes:
        rows = scope.get("rows") if isinstance(scope, dict) else None
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            suggestion_id = str(row.get("suggestion_id") or "").strip()
            field = _payload_text(row_payload, "field", "field_name", "target_field")
            role = _identity_role_from_payload(row_payload)
            entry = latest_by_id.get(suggestion_id) or latest_by_key.get(
                _identity_role_fallback_key(canonical_entity, field, role)
            )
            if entry is None:
                continue
            row["status"] = entry.status
            row_payload = dict(row_payload)
            row_payload["studio_review_status"] = entry.status
            row_payload["studio_reviewed_at"] = entry.reviewed_at
            if isinstance(entry.edited_payload, dict):
                row_payload["studio_edited_payload"] = entry.edited_payload
            row["payload"] = row_payload
    return payload


def _constraint_payload(payload: dict[str, Any]) -> dict[str, Any]:
    constraint = payload.get("constraint")
    return constraint if isinstance(constraint, dict) else {}


def _payload_int(payload: dict[str, Any], *keys: str) -> tuple[int | None, str | None]:
    raw = None
    for key in keys:
        if payload.get(key) is not None:
            raw = payload.get(key)
            break
    if raw is None or str(raw).strip() == "":
        return None, None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None, f"'{raw}' must be an integer."
    if value < 0:
        return None, f"'{raw}' must be zero or greater."
    return value, None


def _payload_float(payload: dict[str, Any], *keys: str) -> tuple[float | None, str | None]:
    raw = None
    for key in keys:
        if payload.get(key) is not None:
            raw = payload.get(key)
            break
    if raw is None or str(raw).strip() == "":
        return None, None
    try:
        return float(str(raw).strip()), None
    except (TypeError, ValueError):
        return None, f"'{raw}' must be numeric."


def _field_for_validation_payload(
    session,
    canonical_entity: str,
    payload: dict[str, Any],
) -> tuple[ClassifiedField | None, str]:
    field_name = _payload_text(payload, "field", "field_name", "target_field") or ""
    if not field_name:
        return None, "Validation hints require a target field."
    owner = _authoritative_entity_owner(session, canonical_entity)
    if owner is None:
        return None, f"Entity '{canonical_entity}' is not available in the current CRUD model."
    resolved = _resolve_current_crud_field(session, canonical_entity, field_name)
    if resolved is not None:
        return resolved, ""
    return None, f"Field '{canonical_entity}.{field_name}' is not available in the current CRUD model."


def _canonicalize_validation_payload_field(
    session,
    canonical_entity: str,
    payload: dict[str, Any],
) -> tuple[ClassifiedField | None, str | None]:
    field_name = _payload_text(payload, "field", "field_name", "target_field") or ""
    if not field_name:
        return None, "Validation hints require a target field."
    resolved = _resolve_current_crud_field(session, canonical_entity, field_name)
    if resolved is None:
        return None, f"Field '{canonical_entity}.{field_name}' is not available in the current CRUD model."
    payload["field"] = resolved.name
    if "target_field" in payload:
        payload["target_field"] = resolved.name
    return resolved, None


def _validation_type_from_payload(payload: dict[str, Any]) -> str:
    constraint = _constraint_payload(payload)
    return _normalize_validation_type(
        _payload_text(payload, "validation_type", "rule_type", "type", "constraint_type")
        or _payload_text(constraint, "validation_type", "rule_type", "type", "constraint_type")
    )


def _validation_rule_types_from_payload(payload: dict[str, Any]) -> list[str]:
    validation_type = _validation_type_from_payload(payload)
    if validation_type != "length":
        return [validation_type] if validation_type else []
    constraint = _constraint_payload(payload)
    merged = {**constraint, **payload}
    rule_types: list[str] = []
    if any(merged.get(key) is not None for key in ("min_length", "minLength", "min", "minimum")):
        rule_types.append("min-length")
    if any(merged.get(key) is not None for key in ("max_length", "maxLength", "max", "maximum")):
        rule_types.append("max-length")
    return rule_types or ["length"]


def _payload_first_value(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload.get(key) is not None:
            return payload.get(key)
    return None


def _normalize_fingerprint_value(value: Any) -> str:
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if isinstance(value, list):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if value is None:
        return ""
    return str(value).strip()


def _validation_constraint_fingerprint(payload: dict[str, Any]) -> str:
    constraint = _constraint_payload(payload)
    merged = {**constraint, **payload}
    validation_type = _validation_type_from_payload(merged)
    fingerprint_items: list[tuple[str, str]] = []

    def add_first(canonical_key: str, *aliases: str) -> None:
        value = _payload_first_value(merged, *aliases)
        if value is not None and str(value).strip() != "":
            fingerprint_items.append((canonical_key, _normalize_fingerprint_value(value)))

    if validation_type in {"max-length", "length"}:
        add_first("max", "max_length", "maxLength", "max", "maximum", "value")
    if validation_type in {"min-length", "length"}:
        add_first("min", "min_length", "minLength", "min", "minimum", "value")
    if validation_type == "pattern":
        add_first("pattern", "pattern", "regex", "value")
    if validation_type == "range":
        add_first("min", "minimum", "min", "min_value")
        add_first("max", "maximum", "max", "max_value")
    if validation_type == "precision-scale":
        add_first("precision", "precision")
        add_first("scale", "scale")
    for key in ("required", "nullable", "not_null"):
        if key in merged:
            fingerprint_items.append((key, _normalize_fingerprint_value(merged.get(key))))
    if merged.get("values") is not None:
        fingerprint_items.append(("values", _normalize_fingerprint_value(merged.get("values"))))
    if merged.get("allowed_values") is not None:
        fingerprint_items.append(("allowed_values", _normalize_fingerprint_value(merged.get("allowed_values"))))
    return "|".join(f"{key}={value}" for key, value in sorted(fingerprint_items))


def _sanitize_validation_edited_payload(
    edited_payload: dict[str, Any],
    *,
    entity: str,
    original_payload: dict[str, Any],
) -> dict[str, Any]:
    """Build the compact KS validation edited payload from drawer/editor state."""

    constraint = _constraint_payload(edited_payload)
    field_name = _payload_text(
        edited_payload,
        "field",
        "field_name",
        "target_field",
    ) or _payload_text(original_payload, "field", "field_name", "target_field")
    validation_type = _validation_type_from_payload(edited_payload) or _validation_type_from_payload(original_payload)

    sanitized: dict[str, Any] = {
        "entity": entity,
        "field": field_name or "",
        "validation_type": validation_type,
    }

    pattern = (
        _payload_text(edited_payload, "pattern", "regex")
        or _payload_text(constraint, "pattern", "regex")
    )
    if not pattern and validation_type == "pattern":
        pattern = _payload_text(edited_payload, "value") or _payload_text(constraint, "value")
    if pattern:
        sanitized["pattern"] = pattern

    for canonical_key, aliases, value_types in (
        ("min", ("min", "minimum", "min_length", "minLength", "min_value"), {"min-length", "length"}),
        ("max", ("max", "maximum", "max_length", "maxLength", "max_value"), {"max-length", "length"}),
    ):
        value = _payload_first_value(edited_payload, *aliases)
        if value is None:
            value = _payload_first_value(constraint, *aliases)
        if value is None and validation_type in value_types:
            value = _payload_first_value(edited_payload, "value")
        if value is None and validation_type in value_types:
            value = _payload_first_value(constraint, "value")
        if value is not None:
            sanitized[canonical_key] = value
            if canonical_key == "min":
                sanitized["min_length"] = value
            if canonical_key == "max":
                sanitized["max_length"] = value

    for key in ("required", "nullable", "not_null"):
        if key in edited_payload:
            sanitized[key] = edited_payload[key]
        elif key in constraint:
            sanitized[key] = constraint[key]

    for key in ("precision", "scale"):
        value = _payload_first_value(edited_payload, key)
        if value is None:
            value = _payload_first_value(constraint, key)
        if value is not None:
            sanitized[key] = value

    return {key: value for key, value in sanitized.items() if value is not None}


def _manifest_path_for_validation_decision(
    decision: dict[str, Any],
    payload: dict[str, Any],
) -> str:
    """Use the effective payload for edited reviews so provenance follows edits."""
    if decision["status"] != "edited" and decision["manifest_path"]:
        return decision["manifest_path"]

    field_name = _payload_text(payload, "field", "field_name", "target_field") or decision["field_name"] or "unknown"
    validation_type = _validation_type_from_payload(payload) or decision["validation_type"] or "unknown"
    return _manifest_path_for_validation(decision["entity"], field_name, validation_type)


def _rule_identity(rule: RuleEntry) -> tuple:
    return (
        rule.field,
        rule.type,
        tuple(rule.values),
        rule.value,
        rule.target_entity,
        rule.operator,
        rule.compare_to_field,
        rule.target_field,
        rule.source_field,
        rule.expected_value,
        rule.error_message,
    )


def _entity_rules_for(session, entity_name: str) -> EntityRules:
    for entity_rules in session.entity_rules:
        if entity_rules.entity_name == entity_name:
            if not entity_rules.file_path:
                entity_rules.file_path = f"rules/{_slug(entity_name)}-business-rules.yaml"
            return entity_rules
    entity_rules = EntityRules(
        entity_name=entity_name,
        rules=[],
        file_path=f"rules/{_slug(entity_name)}-business-rules.yaml",
    )
    session.entity_rules.append(entity_rules)
    return entity_rules


def _upsert_validation_rules(session, entity_name: str, rules: list[RuleEntry]) -> int:
    if not rules:
        return 0
    entity_rules = _entity_rules_for(session, entity_name)
    applied_count = 0
    for rule in rules:
        incoming = _rule_identity(rule)
        applied = False
        for index, existing in enumerate(entity_rules.rules):
            if _rule_identity(existing) == incoming:
                if (
                    rule.generated_by_ka
                    and existing.generated_by_ka
                    and existing.suggestion_id == rule.suggestion_id
                ):
                    existing.suggestion_id = rule.suggestion_id
                    existing.suggestion_type = rule.suggestion_type
                    existing.applied_by = rule.applied_by
                    existing.applied_at = rule.applied_at
                    existing.generated_by_ka = rule.generated_by_ka
                    existing.ka_review_status = rule.ka_review_status
                applied = True
                break
            if existing.field == rule.field and existing.type == rule.type:
                entity_rules.rules[index] = rule
                applied_count += 1
                applied = True
                break
        if not applied:
            entity_rules.rules.append(rule)
            applied_count += 1
    return applied_count


def _stamp_ka_validation_rule(rule: RuleEntry, *, suggestion_id: str, status: str) -> RuleEntry:
    stamped = rule.model_copy(deep=True)
    stamped.suggestion_id = suggestion_id
    stamped.suggestion_type = "validation"
    stamped.applied_by = "knowledge_assist"
    stamped.applied_at = datetime.now(timezone.utc).isoformat()
    stamped.generated_by_ka = True
    stamped.ka_review_status = status
    return stamped


def _mark_ka_validation_rules_review_status(
    session,
    *,
    suggestion_id: str,
    status: str,
    expected_rules: list[RuleEntry] | None = None,
) -> dict[str, int]:
    updated = 0
    edited = 0
    expected_identities = {_rule_identity(rule) for rule in (expected_rules or [])}
    for entity_rules in session.entity_rules:
        for rule in entity_rules.rules:
            if rule.generated_by_ka and rule.suggestion_id == suggestion_id:
                if expected_identities and _rule_identity(rule) not in expected_identities:
                    rule.ka_review_status = "edited"
                    edited += 1
                    continue
                rule.ka_review_status = status
                updated += 1
    return {"updated": updated, "edited": edited}


def _expected_validation_rules_for_decision(
    session,
    decision: dict[str, Any],
    payload: dict[str, Any],
) -> list[RuleEntry]:
    field, _field_error = _field_for_validation_payload(session, decision["entity"], payload)
    if field is None:
        return []
    validation_types = _validation_rule_types_from_payload(payload)
    working_field = field.model_copy(deep=True)
    rules, warning = _apply_validation_payload_to_field(working_field, payload, validation_types)
    return [] if warning else rules


def _validation_rule_for_field(field: ClassifiedField, validation_type: str) -> RuleEntry | None:
    if validation_type == "not-null":
        return RuleEntry(field=field.name, type="not-null")
    if validation_type == "max-length" and field.max_length is not None:
        return RuleEntry(field=field.name, type="max-length", value=str(field.max_length))
    if validation_type == "min-length" and field.min_length is not None:
        return RuleEntry(field=field.name, type="min-length", value=str(field.min_length))
    if validation_type == "pattern" and field.pattern is not None:
        return RuleEntry(field=field.name, type="pattern", value=field.pattern)
    if validation_type == "range" and (field.minimum is not None or field.maximum is not None):
        entry = RuleEntry(field=field.name, type="range")
        if field.minimum is not None:
            entry.value = str(field.minimum)
        if field.maximum is not None:
            entry.values = [str(field.maximum)]
        return entry
    return None


def _apply_validation_payload_to_field(
    field: ClassifiedField,
    payload: dict[str, Any],
    validation_types: list[str],
) -> tuple[list[RuleEntry], str | None]:
    constraint = _constraint_payload(payload)
    merged = {**constraint, **payload}
    rules: list[RuleEntry] = []

    for validation_type in validation_types:
        if validation_type == "not-null":
            field.required = True
            rule = _validation_rule_for_field(field, validation_type)
            if rule:
                rules.append(rule)
            continue

        if validation_type == "max-length":
            value, error = _payload_int(merged, "max_length", "maxLength", "max", "maximum", "value")
            if error:
                return [], f"max_length validation {error}"
            if value is None:
                return [], "max_length validation requires a max value."
            field.max_length = value
            rule = _validation_rule_for_field(field, validation_type)
            if rule:
                rules.append(rule)
            continue

        if validation_type == "min-length":
            value, error = _payload_int(merged, "min_length", "minLength", "min", "minimum", "value")
            if error:
                return [], f"min_length validation {error}"
            if value is None:
                return [], "min_length validation requires a min value."
            field.min_length = value
            rule = _validation_rule_for_field(field, validation_type)
            if rule:
                rules.append(rule)
            continue

        if validation_type == "pattern":
            pattern = _payload_text(merged, "pattern", "regex", "value")
            if not pattern:
                return [], "pattern validation requires a non-empty pattern."
            field.pattern = pattern
            rule = _validation_rule_for_field(field, validation_type)
            if rule:
                rules.append(rule)
            continue

        if validation_type == "range":
            minimum, min_error = _payload_float(merged, "minimum", "min", "min_value")
            maximum, max_error = _payload_float(merged, "maximum", "max", "max_value")
            if min_error:
                return [], f"range validation minimum {min_error}"
            if max_error:
                return [], f"range validation maximum {max_error}"
            if minimum is None and maximum is None:
                return [], "range validation requires minimum or maximum."
            field.minimum = minimum
            field.maximum = maximum
            rule = _validation_rule_for_field(field, validation_type)
            if rule:
                rules.append(rule)
            continue

        if validation_type == "precision-scale":
            return [], "precision_scale validation requires manual authoring in this Studio slice."

        return [], f"Unsupported validation_type '{validation_type}'."

    return rules, None


def _normalize_validation_review_decisions(raw_decisions: Any) -> tuple[list[dict[str, Any]], list[str]]:
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
        entity = str(item.get("entity") or "").strip()
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        edited_payload = item.get("edited_payload") if isinstance(item.get("edited_payload"), dict) else None
        if status == "edited" and isinstance(edited_payload, dict):
            edited_payload = _sanitize_validation_edited_payload(
                edited_payload,
                entity=entity,
                original_payload=payload,
            )
        candidate_payload = edited_payload if status == "edited" else payload
        validation_type = _validation_type_from_payload(candidate_payload if isinstance(candidate_payload, dict) else {})
        field_name = _payload_text(candidate_payload if isinstance(candidate_payload, dict) else {}, "field", "field_name", "target_field")
        manifest_path = str(item.get("manifest_path") or "").strip()

        if not suggestion_id:
            errors.append(f"Decision {index + 1} must include suggestion_id.")
            continue
        if suggestion_type not in {"validation", "validations"}:
            errors.append(f"Decision {index + 1} has unsupported suggestion_type '{suggestion_type}'.")
            continue
        if status not in {"accepted", "edited", "rejected"}:
            errors.append(f"Decision {index + 1} has unsupported status '{status}'.")
            continue
        if not entity:
            errors.append(f"Decision {index + 1} must include entity.")
            continue
        if status in {"accepted", "edited"}:
            if not isinstance(candidate_payload, dict) or not candidate_payload:
                errors.append(f"Decision {index + 1} requires a payload for {status} review.")
                continue
            if not field_name:
                errors.append(f"Decision {index + 1} requires a target field.")
                continue
            if validation_type not in _VALIDATION_TYPES:
                errors.append(f"Decision {index + 1} has unsupported validation_type '{validation_type}'.")
                continue
            if validation_type == "pattern":
                merged = {**_constraint_payload(candidate_payload), **candidate_payload}
                if not _payload_text(merged, "pattern", "regex", "value"):
                    errors.append(f"Decision {index + 1} requires a non-empty pattern.")
                    continue

        normalized.append(
            {
                "suggestion_id": suggestion_id,
                "suggestion_type": "validation",
                "status": status,
                "entity": entity,
                "payload": payload,
                "edited_payload": edited_payload,
                "field_name": field_name or "",
                "validation_type": validation_type,
                "manifest_path": manifest_path,
            }
        )

    return normalized, errors


def _ks_review_payload(decision: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "suggestion_id": decision["suggestion_id"],
        "status": decision["status"],
    }
    if decision["status"] == "edited":
        if decision.get("suggestion_type") == "identity_role":
            payload["edited_payload"] = _identity_role_ks_edited_payload(decision)
        else:
            payload["edited_payload"] = decision["edited_payload"]
    return payload


def _identity_role_ks_edited_payload(decision: dict[str, Any]) -> dict[str, str]:
    edited_payload = decision.get("edited_payload")
    edited_payload = edited_payload if isinstance(edited_payload, dict) else {}
    role = str(decision.get("role") or _identity_role_from_payload(edited_payload) or "").strip()
    payload = {
        "entity": str(decision.get("entity") or "").strip(),
        "field": str(decision.get("field") or "").strip(),
        "role": role,
        "suggested_role": role,
    }
    rationale = _payload_text(edited_payload, "rationale", "review_rationale", "note")
    if rationale:
        payload["rationale"] = rationale
    return payload


def _normalize_identity_role_review_decisions(raw_decisions: Any) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(raw_decisions, list):
        return [], ["Review decisions must be a list."]

    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, item in enumerate(raw_decisions, start=1):
        if not isinstance(item, dict):
            errors.append(f"Decision {index} must be an object.")
            continue

        suggestion_id = str(item.get("suggestion_id") or "").strip()
        suggestion_type = str(item.get("suggestion_type") or "").strip()
        status = str(item.get("status") or "").strip()
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        edited_payload = item.get("edited_payload") if isinstance(item.get("edited_payload"), dict) else None
        effective_payload = {**payload, **edited_payload} if status == "edited" and isinstance(edited_payload, dict) else payload
        entity = str(item.get("entity") or _payload_text(effective_payload, "entity", "entity_name", "canonical_entity")).strip()
        field = _payload_text(effective_payload, "field", "field_name", "target_field")
        role = _identity_role_from_payload(effective_payload)
        manifest_path = str(item.get("manifest_path") or "").strip()
        if not manifest_path and entity and field:
            manifest_path = _manifest_path_for_field(entity, field)

        if not suggestion_id:
            errors.append(f"Decision {index} must include suggestion_id.")
            continue
        if suggestion_type and suggestion_type != "identity_role":
            errors.append(f"Decision {index} has unsupported suggestion_type '{suggestion_type}'.")
            continue
        if status not in {"accepted", "edited", "rejected"}:
            errors.append(f"Decision {index} has unsupported status '{status}'.")
            continue
        if not entity:
            errors.append(f"Decision {index} must include entity.")
            continue
        if not field:
            errors.append(f"Decision {index} must include a target field.")
            continue
        if status in {"accepted", "edited"} and role not in IDENTITY_ROLE_VALUES:
            errors.append(f"Decision {index} has unsupported identity role '{role or 'unknown'}'.")
            continue
        if status == "edited":
            rationale = _payload_text(edited_payload or {}, "rationale", "review_rationale", "note")
            edited_payload = {
                "entity": entity,
                "field": field,
                "role": role,
                "suggested_role": role,
            }
            if rationale:
                edited_payload["rationale"] = rationale

        normalized.append(
            {
                "suggestion_id": suggestion_id,
                "suggestion_type": "identity_role",
                "status": status,
                "entity": entity,
                "field": field,
                "role": role,
                "payload": payload,
                "edited_payload": edited_payload,
                "manifest_path": manifest_path,
            }
        )
    return normalized, errors


def _identity_role_assignment_error(session, decision: dict[str, Any]) -> str | None:
    entity = decision["entity"]
    field = decision["field"]
    role = decision["role"]
    if entity not in set(identity_selected_canonical_entities(session)):
        return f"Unknown CRUD entity '{entity}'."
    resolved = _resolve_current_crud_field(session, entity, field)
    if resolved is None:
        return f"Unknown field '{entity}.{field}'."
    if is_wrapper_identity_field(session, entity, resolved.name):
        return f"Field '{entity}.{resolved.name}' is a transport wrapper/page field and cannot receive an identity role."
    if role not in IDENTITY_ROLE_VALUES:
        return f"Invalid identity role '{role}' for {entity}.{resolved.name}."
    decision["field"] = resolved.name
    decision["manifest_path"] = _manifest_path_for_field(entity, resolved.name)
    return None


def _identity_role_batch_errors(decisions: list[dict[str, Any]]) -> list[str]:
    """Validate accepted/edited identity role decisions as one effective batch."""
    errors: list[str] = []
    seen_fields: set[tuple[str, str]] = set()
    persistence_by_entity: dict[str, str] = {}
    for decision in decisions:
        if decision["status"] not in {"accepted", "edited"}:
            continue
        entity = decision["entity"]
        field = decision["field"]
        role = decision["role"]
        field_key = (entity, field)
        if field_key in seen_fields:
            errors.append(
                f"Field '{entity}.{field}' can have only one active identity role in this review batch."
            )
            continue
        seen_fields.add(field_key)

        if role == "persistence_id":
            existing_field = persistence_by_entity.get(entity)
            if existing_field and existing_field != field:
                errors.append(
                    f"Entity '{entity}' can have only one active persistence_id in this review batch."
                )
                continue
            persistence_by_entity[entity] = field
    return errors


def _upsert_ka_identity_role_decision(session, decision: dict[str, Any], *, reviewed_at: str) -> None:
    entity = decision["entity"]
    field = decision["field"]
    role = decision["role"]
    retained: list[IdentityRoleDecision] = []
    for existing in session.identity_role_decisions:
        if existing.entity == entity and existing.field == field:
            continue
        if role == "persistence_id" and existing.entity == entity and existing.role == "persistence_id":
            continue
        retained.append(existing)
    retained.append(
        IdentityRoleDecision(
            entity=entity,
            field=field,
            role=role,
            provenance="knowledge-assist",
            reviewed_at=reviewed_at,
        )
    )
    session.identity_role_decisions = retained


def _record_identity_role_review(
    session,
    decision: dict[str, Any],
    *,
    reviewed_at: str,
) -> None:
    effective_payload = decision["edited_payload"] if decision["status"] == "edited" else decision["payload"]
    effective_payload = effective_payload if isinstance(effective_payload, dict) else {}
    role = decision["role"] or _identity_role_from_payload(effective_payload)
    behavior = identity_role_behavior(role)
    _set_review_bucket(session, decision["suggestion_id"], decision["status"])
    session.ks_workspace_state.review_history.append(
        KSReviewHistoryEntry(
            suggestion_id=decision["suggestion_id"],
            type="identity_role",
            status=decision["status"],
            manifest_path=decision["manifest_path"],
            reviewed_at=reviewed_at,
            edited_payload=decision["edited_payload"] if decision["status"] == "edited" else None,
            review_context={
                "entity": decision["entity"],
                "field": decision["field"],
                "role": role,
                "provenance": "knowledge-assist",
                "export_impact": str(behavior.get("export_behavior") or ""),
                "generation_impact": str(behavior.get("current_engine_behavior") or ""),
                "identity_role_fallback_key": _identity_role_fallback_key(
                    decision["entity"],
                    decision["field"],
                    role,
                ),
            },
        )
    )


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


def _ks_outcomes_by_suggestion_id(ks_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    outcomes = ks_result.get("outcomes", [])
    if not isinstance(outcomes, list):
        return {}
    return {
        str(outcome.get("suggestion_id")): outcome
        for outcome in outcomes
        if isinstance(outcome, dict) and outcome.get("suggestion_id") is not None
    }


def _ks_outcome_messages(outcome: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    error = str(outcome.get("error") or "").strip()
    if error:
        messages.append(error)
    warnings = outcome.get("warnings")
    if isinstance(warnings, list):
        messages.extend(str(warning).strip() for warning in warnings if str(warning or "").strip())
    elif warnings:
        messages.append(str(warnings).strip())
    return messages


def _record_validation_review(
    session,
    decision: dict[str, Any],
    *,
    manifest_path: str,
) -> None:
    effective_payload = decision["edited_payload"] if decision["status"] == "edited" else decision["payload"]
    effective_payload = effective_payload if isinstance(effective_payload, dict) else {}
    constraint_fingerprint = _validation_constraint_fingerprint(effective_payload)
    _set_review_bucket(session, decision["suggestion_id"], decision["status"])
    _replace_evidence_link(
        session,
        decision["suggestion_id"],
        manifest_path,
        decision["status"],
    )
    session.ks_workspace_state.review_history.append(
        KSReviewHistoryEntry(
            suggestion_id=decision["suggestion_id"],
            type="validation",
            status=decision["status"],
            manifest_path=manifest_path,
            reviewed_at=datetime.now(timezone.utc).isoformat(),
            edited_payload=decision["edited_payload"] if decision["status"] == "edited" else None,
            review_context={
                "entity": decision["entity"],
                "field": decision["field_name"],
                "validation_type": decision["validation_type"],
                "constraint_fingerprint": constraint_fingerprint,
                "validation_fallback_key": _validation_review_fallback_key(
                    decision["entity"],
                    decision["field_name"],
                    decision["validation_type"],
                    manifest_path,
                    constraint_fingerprint,
                ),
            },
        )
    )


def _payload_value(payload: dict[str, Any], key: str, fallback: Any) -> Any:
    if key in payload:
        return payload.get(key)
    return fallback


def _normalize_review_decisions(raw_decisions: Any) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(raw_decisions, list):
        return [], ["Review decisions must be a list."]

    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, item in enumerate(raw_decisions):
        if not isinstance(item, dict):
            errors.append(f"Decision {index + 1} must be an object.")
            continue

        suggestion_id = str(item.get("suggestion_id") or "").strip()
        entity = str(item.get("entity") or "").strip()
        field_name = str(item.get("field_name") or "").strip()
        status = str(item.get("status") or "").strip()

        if not suggestion_id or not entity or not field_name or not status:
            errors.append(
                f"Decision {index + 1} must include suggestion_id, entity, field_name, and status."
            )
            continue
        if status not in {"accepted", "edited", "rejected"}:
            errors.append(f"Decision {index + 1} has unsupported status '{status}'.")
            continue

        raw_payload = item.get("edited_payload")
        edited_payload = raw_payload if isinstance(raw_payload, dict) else {}
        final_field_name = str(
            _payload_value(edited_payload, "field_name", field_name) or field_name
        ).strip()
        final_type = _payload_value(edited_payload, "suggested_type", item.get("suggested_type"))
        final_nullable = _payload_value(
            edited_payload,
            "suggested_nullable",
            item.get("suggested_nullable"),
        )
        final_description = _payload_value(
            edited_payload,
            "suggested_description",
            item.get("suggested_description"),
        )

        normalized_payload = None
        if status == "edited":
            normalized_payload = {
                "field_name": final_field_name,
                "suggested_type": final_type,
                "suggested_nullable": final_nullable,
                "suggested_description": final_description,
            }

        normalized.append(
            {
                "suggestion_id": suggestion_id,
                "entity": entity,
                "field_name": field_name,
                "status": status,
                "suggested_type": item.get("suggested_type"),
                "suggested_nullable": item.get("suggested_nullable"),
                "suggested_description": item.get("suggested_description"),
                "edited_payload": normalized_payload,
                "final_field_name": final_field_name,
                "final_type": final_type,
                "final_nullable": final_nullable,
                "final_description": final_description,
            }
        )

    return normalized, errors


def _field_review_preflight_errors(session, decisions: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for decision in decisions:
        if decision["status"] not in {"accepted", "edited"}:
            continue
        current_field = _resolve_current_crud_field(
            session,
            decision["entity"],
            decision["final_field_name"],
        )
        if current_field is None and not str(decision.get("final_type") or "").strip():
            errors.append(
                f"Suggestion '{decision['suggestion_id']}' cannot add "
                f"{decision['entity']}.{decision['final_field_name']} because no field type was provided."
            )
    return errors


def _apply_review_outcome(session, decision: dict[str, Any]) -> None:
    suggestion_id = decision["suggestion_id"]
    status = decision["status"]
    canonical_entity = decision["entity"]
    final_field_name = decision["final_field_name"]
    manifest_path = _manifest_path_for_field(canonical_entity, final_field_name)

    _set_review_bucket(session, suggestion_id, status)
    _replace_evidence_link(session, suggestion_id, manifest_path, status)

    session.ks_workspace_state.review_history.append(
        KSReviewHistoryEntry(
            suggestion_id=suggestion_id,
            type="field",
            status=status,
            manifest_path=manifest_path,
            reviewed_at=datetime.now(timezone.utc).isoformat(),
            edited_payload=decision["edited_payload"] if status == "edited" else None,
        )
    )

    if status in {"accepted", "edited"}:
        _upsert_authoritative_field(
            session,
            canonical_entity,
            final_field_name,
            decision["final_type"],
            decision["final_nullable"],
        )


@router.get("", response_class=HTMLResponse)
async def step3_get(request: Request):
    session = get_current_session(request)
    if _restore_missing_operation_inventory(session):
        save_current_session(request, session)
    workspace_before = workspace_session_marker(session)
    ks_selected_entities = _selected_canonical_entities(session)
    ks_field_review = assist_service.get_step3_field_review_context(
        session,
        selected_entities=ks_selected_entities,
    )
    validation_hint_badges = []
    identity_role_badges = []
    identity_role_suggestion_entities = [
        entity for entity in ks_selected_entities if eligible_identity_fields(session, entity)
    ]
    if ks_field_review.enabled and ks_selected_entities and (session.project_id or session.ks_project_id):
        validation_hint_badges, identity_role_badges = assist_service.batch_fetch_step3_badge_counts(
            session,
            validation_entities=ks_selected_entities,
            identity_entities=identity_role_suggestion_entities,
        )
    save_current_session_if_workspace_changed(request, session, workspace_before)
    nav = build_nav_context(session, "/entities")
    initial_phase2_interfaces = _build_phase2_interfaces_data(session)
    identity_role_review, entity_readiness_items, identity_role_lens = (
        _identity_role_lens_for_session(session)
    )
    ka_summary = _step3_ka_summary(
        session,
        selected_entities=ks_selected_entities,
        validation_hint_badges=validation_hint_badges,
        identity_role_badges=identity_role_badges,
    )
    return templates.TemplateResponse(request, "step3_entities.html", {
        "request": request,
        "session": session,
        "step": 3,
        **nav,
        "entities": session.classified_entities,
        "operations": session.classified_operations,
        "pagination_wrapper_keys": PAGINATION_WRAPPER_KEYS,
        "ks_selected_entities": ks_selected_entities,
        "ks_field_review": ks_field_review,
        "validation_hint_badges": validation_hint_badges,
        "identity_role_badges": identity_role_badges,
        "identity_role_suggestion_entities": identity_role_suggestion_entities,
        "ka_summary": ka_summary,
        "saved_operation_assignments": _saved_operation_assignment_map(session),
        "initial_phase2_interfaces": initial_phase2_interfaces,
        "identity_role_review": identity_role_review,
        "entity_readiness_items": entity_readiness_items,
        "identity_role_lens": identity_role_lens,
        "shell_rail_default": ks_field_review.rail_default,
    })


@router.post("/identity-roles", response_class=JSONResponse)
async def save_identity_roles(request: Request):
    """Persist manual identity role decisions for selected CRUD entity fields."""
    session = get_current_session(request)
    if session.app_archetype != "crud":
        return JSONResponse(
            {"ok": False, "error": "Identity role review is available for CRUD projects only."},
            status_code=400,
        )

    body = await request.json()
    raw_decisions = body.get("decisions", [])
    if not isinstance(raw_decisions, list):
        return JSONResponse({"ok": False, "error": "decisions must be a list."}, status_code=400)

    available_entities = set(identity_selected_canonical_entities(session))
    current_by_field = active_identity_decisions_by_field(session)
    new_by_entity: dict[str, dict[str, IdentityRoleDecision]] = {
        entity: dict(fields) for entity, fields in current_by_field.items()
    }
    errors: list[str] = []
    payload_persistence_entities: dict[str, str] = {}
    payload_field_keys: set[tuple[str, str]] = set()
    now = datetime.now(timezone.utc).isoformat()

    for index, item in enumerate(raw_decisions, start=1):
        if not isinstance(item, dict):
            errors.append(f"Decision {index} must be an object.")
            continue
        entity = str(item.get("entity") or "").strip()
        field = str(item.get("field") or "").strip()
        role = str(item.get("role") or "").strip()

        if entity not in available_entities:
            errors.append(f"Unknown CRUD entity '{entity}'.")
            continue
        owner = identity_authoritative_entity(session, entity)
        if owner is None:
            errors.append(f"Unknown CRUD entity '{entity}'.")
            continue
        field_names = {existing.name for existing in owner.fields}
        if field not in field_names:
            errors.append(f"Unknown field '{entity}.{field}'.")
            continue
        if is_wrapper_identity_field(session, entity, field):
            errors.append(f"Field '{entity}.{field}' is a transport wrapper/page field and cannot receive an identity role.")
            continue
        if role and role not in IDENTITY_ROLE_VALUES:
            errors.append(f"Invalid identity role '{role}' for {entity}.{field}.")
            continue
        field_key = (entity, field)
        if field_key in payload_field_keys:
            errors.append(f"Field '{entity}.{field}' can have only one active identity role.")
            continue
        payload_field_keys.add(field_key)

        entity_decisions = new_by_entity.setdefault(entity, {})
        if not role:
            entity_decisions.pop(field, None)
            continue

        if role == "persistence_id":
            existing_payload_field = payload_persistence_entities.get(entity)
            if existing_payload_field and existing_payload_field != field:
                errors.append(f"Entity '{entity}' can have only one active persistence_id.")
                continue
            payload_persistence_entities[entity] = field
            for existing_field, existing_decision in list(entity_decisions.items()):
                if existing_field != field and existing_decision.role == "persistence_id":
                    entity_decisions.pop(existing_field, None)

        entity_decisions[field] = IdentityRoleDecision(
            entity=entity,
            field=field,
            role=role,
            provenance="human-authored",
            reviewed_at=now,
        )

    if errors:
        return JSONResponse({"ok": False, "errors": errors}, status_code=400)

    active_decisions: list[IdentityRoleDecision] = []
    for entity in identity_selected_canonical_entities(session):
        for field_info in eligible_identity_fields(session, entity):
            decision = new_by_entity.get(entity, {}).get(field_info["name"])
            if decision:
                active_decisions.append(decision)

    session.identity_role_decisions = active_decisions
    save_current_session(request, session)
    _, _, identity_role_lens = _identity_role_lens_for_session(session)
    return JSONResponse(
        {
            "ok": True,
            "saved_count": len(active_decisions),
            "decisions": [decision.model_dump() for decision in active_decisions],
            "stats": identity_role_lens["stats"],
            "entities": identity_role_lens["entities"],
        }
    )


@router.post("/save", response_class=JSONResponse)
async def step3_save(request: Request):
    """Save entity/operation selections and build upstream interface entries."""
    body = await request.json()
    session = get_current_session(request)

    selected_entities = body.get("entities", [])   # list of entity names
    selected_ops = body.get("operations", [])       # list of op names
    entity_op_map = body.get("entity_op_map", {})  # {entity_name: [op_name, ...]}

    session.selected_entity_names = selected_entities
    operation_selection_submitted = bool(selected_ops) or any(
        bool(operation_names)
        for operation_names in entity_op_map.values()
    )

    # Resolve canonical entity names from classified entities (mirrors AppBuilder normalization)
    canonical_map: dict[str, str] = {}
    for ce in session.classified_entities:
        canonical_map[ce.name] = ce.display_name()

    # -----------------------------------------------------------------------
    # Group selected schema names by canonical name and merge their operations.
    # AppBuilder's _normalize_entity_name + _merge_fields collapses multiple
    # *Response/*Request schemas into one canonical entity (e.g. CustomerResponse
    # + GetCustomerResponse both → Customer). Studio must do the same so that
    # exactly one interface is created per canonical name — not one per schema.
    # -----------------------------------------------------------------------
    from collections import OrderedDict

    # canonical_name → ordered-unique list of operation names
    canonical_ops: OrderedDict[str, list[str]] = OrderedDict()
    for schema_name in selected_entities:
        canonical = canonical_map.get(schema_name, schema_name)
        if canonical not in canonical_ops:
            canonical_ops[canonical] = []
        for op_name in entity_op_map.get(schema_name, []):
            if op_name not in canonical_ops[canonical]:
                canonical_ops[canonical].append(op_name)

    # Build one Step-3-owned REST/OpenAPI upstream interface per canonical entity
    # name. Edge-contract interfaces are authored in Step 2 and must survive
    # Step 3 CRUD/OpenAPI saves untouched.
    existing_upstream_interfaces = list(session.upstream_interfaces)
    existing = {
        iface.entity_name: iface
        for iface in existing_upstream_interfaces
        if _is_step3_openapi_interface(iface)
    }
    new_interfaces: list[UpstreamInterface] = []
    effective_selected_ops = list(selected_ops)

    for canonical_name, ops_for_entity in canonical_ops.items():
        # Re-use existing interface data if already defined
        iface = existing.get(canonical_name)
        if (
            iface is not None
            and not session.classified_operations
            and not operation_selection_submitted
            and (iface.operations or iface.operation_mappings)
        ):
            # Older snapshots may have no classified operation inventory, so
            # the browser has no operation controls to submit. Preserve that
            # interface-owned authoring verbatim rather than treating the
            # missing controls as an intentional clear.
            new_interfaces.append(iface)
            effective_selected_ops.extend(operation.name for operation in iface.operations)
            continue
        if iface is None:
            entity_slug = _slug(canonical_name)
            iface = UpstreamInterface(
                name=f"{_slug(session.bounded_context or 'app')}-{entity_slug}-api",
                system=None,
                type="rest-json",
                entity_name=canonical_name,  # always store canonical name
                is_draft=True,
            )
            # Sync spec source fields from current Step-2 ingestion state
            _apply_spec_source(iface, session)
        else:
            iface.entity_name = canonical_name
            # Refresh spec source — user may have re-ingested from a different
            # source (file → URL, URL → manual, etc.) since this interface was
            # first built.  Without re-syncing, the reused interface silently
            # exports the old contract reference rather than the current one.
            _apply_spec_source(iface, session)

        # Build the selected operation list. Reuse the complete saved sample so
        # custom package paths survive a semantically unchanged selection save.
        existing_op_content: dict[str, OperationSample] = {
            op.name: op for op in iface.operations
        }
        iface.operations = [
            existing_op_content[op_name].model_copy(deep=True)
            if op_name in existing_op_content
            else OperationSample(
                name=op_name,
                # Paths set, but NO content until Phase 2 is filled.
                # has_sample() requires content, so these don't appear in
                # the manifest until the user enters JSON bodies.
                request_sample_path=f"upstream/sample-{_slug(op_name)}-request.json",
                response_sample_path=f"upstream/sample-{_slug(op_name)}-response.json",
            )
            for op_name in ops_for_entity
        ]

        # Reconcile operation_mappings: remove entries for operations that are
        # no longer in the selection.  Leaving stale mapping entries causes
        # AppBuilder to raise 'Mapping declares unknown operation <name>'.
        current_op_names = set(ops_for_entity)
        iface.operation_mappings = [
            om for om in iface.operation_mappings
            if om.name in current_op_names
        ]

        new_interfaces.append(iface)

    session.selected_operation_names = list(dict.fromkeys(effective_selected_ops))
    session.upstream_interfaces = _merge_step3_upstream_interfaces(
        existing_upstream_interfaces,
        new_interfaces,
    )
    save_current_session(request, session)

    interfaces_data = _build_phase2_interfaces_data(session, new_interfaces)
    return JSONResponse({
        "ok": True,
        "interface_count": len(new_interfaces),
        "interfaces": interfaces_data,
        "selected_canonical_entities": list(canonical_ops.keys()),
    })


@router.get("/ks/suggestions", response_class=JSONResponse)
async def step3_ks_suggestions(
    request: Request,
    entity: Optional[str] = Query(None),
):
    session = get_current_session(request)
    if session.app_archetype != "crud":
        return JSONResponse(
            {
                "ok": False,
                "warning": "Step 3 KS field suggestions are available for CRUD projects only.",
                "suggestions": [],
            },
            status_code=400,
        )

    selected_entity, available_entities = _resolve_canonical_entity(session, entity)
    if not selected_entity:
        return JSONResponse(
            {
                "ok": True,
                "entity": entity,
                "selected_entities": available_entities,
                "suggestions": [],
                "empty": True,
                "empty_reason": "Save at least one CRUD entity selection in Step 3 to fetch KS field suggestions.",
                "knowledge_url": "/knowledge",
            }
        )

    workspace_before = workspace_session_marker(session)
    assist_result = assist_service.fetch_field_suggestions(session, entity=selected_entity)
    save_current_session_if_workspace_changed(request, session, workspace_before)
    if not assist_result:
        return JSONResponse(
            {
                "ok": True,
                "entity": selected_entity,
                "selected_entities": available_entities,
                "suggestions": [],
                "empty": True,
                "empty_reason": "Knowledge Assist is off or unavailable for this field suggestion request.",
                "knowledge_url": "/knowledge",
            }
        )

    return JSONResponse(_step3_field_suggestions_payload(session, selected_entity, available_entities, assist_result))


@router.get("/ks/drawer", response_class=JSONResponse)
async def step3_ks_drawer(
    request: Request,
    scope: str = Query("validations"),
    entity: str = Query(""),
):
    session = get_current_session(request)
    if session.app_archetype != "crud":
        return JSONResponse(
            {
                "ok": False,
                "warning": "Step 3 Knowledge Assist drawers are available for CRUD projects only.",
            },
            status_code=400,
        )
    if scope not in {"validations", "identity_role"}:
        return JSONResponse(
            {
                "ok": False,
                "warning": f"Unsupported Step 3 Knowledge Assist drawer scope '{scope}'.",
            },
            status_code=400,
        )

    canonical_entity, available_entities = _resolve_canonical_entity(
        session,
        entity.strip() or None,
    )
    if not canonical_entity:
        return JSONResponse(
            {
                "ok": True,
                "scope": scope,
                "title": "Identity Role Suggestions" if scope == "identity_role" else "Validation Hints",
                "entity": entity,
                "selected_entities": available_entities,
                "scopes": [],
                "warnings": [],
                "empty": True,
            }
        )
    if scope == "identity_role" and not eligible_identity_fields(session, canonical_entity):
        return JSONResponse(
            {
                "ok": True,
                "scope": scope,
                "title": "Identity Role Suggestions",
                "entity": canonical_entity,
                "selected_entities": available_entities,
                "scopes": [],
                "warnings": [],
                "empty": True,
            }
        )

    workspace_before = workspace_session_marker(session)
    drawer = assist_service.fetch_suggestion_drawer(
        session,
        scope=scope,
        entity=canonical_entity,
    )
    save_current_session_if_workspace_changed(request, session, workspace_before)
    payload = drawer.to_dict() if drawer else {
        "ok": True,
        "scope": scope,
        "title": "Identity Role Suggestions" if scope == "identity_role" else "Validation Hints",
        "entity": canonical_entity,
        "scopes": [],
        "warnings": [],
        "empty": True,
    }
    payload = _finalize_step3_drawer_payload(
        session,
        scope=scope,
        canonical_entity=canonical_entity,
        available_entities=available_entities,
        payload=payload,
    )
    return JSONResponse(payload)


@router.get("/ks/full-review", response_class=JSONResponse)
async def step3_ks_full_review(
    request: Request,
    entities: Optional[str] = Query(None),
):
    session = get_current_session(request)
    if session.app_archetype != "crud":
        return JSONResponse(
            {
                "ok": False,
                "warning": "Step 3 Knowledge Assist full review is available for CRUD projects only.",
                "selected_entities": [],
                "identity_review_entities": [],
                "entities": [],
                "warnings": [],
            },
            status_code=400,
        )

    available_entities = _selected_canonical_entities(session)
    selected_entities = list(available_entities)
    if entities:
        requested = [item.strip() for item in entities.split(",") if item.strip()]
        unknown = [item for item in requested if item not in available_entities]
        if unknown:
            return JSONResponse(
                {
                    "ok": False,
                    "warning": (
                        "Full-review entity override must reference selected Step 3 entities: "
                        + ", ".join(unknown)
                    ),
                    "selected_entities": available_entities,
                    "identity_review_entities": [],
                    "entities": [],
                    "warnings": [],
                },
                status_code=400,
            )
        requested_set = set(requested)
        selected_entities = [entity for entity in available_entities if entity in requested_set]

    identity_review_entities = [
        entity for entity in selected_entities if eligible_identity_fields(session, entity)
    ]
    if not session.capabilities.knowledge_assist_enabled or not selected_entities:
        return JSONResponse(
            {
                "ok": True,
                "selected_entities": selected_entities,
                "identity_review_entities": identity_review_entities,
                "entities": [],
                "warnings": [],
            }
        )

    workspace_before = workspace_session_marker(session)
    batch = assist_service.batch_fetch_step3_full_review(
        session,
        entities=selected_entities,
        identity_entities=identity_review_entities,
        max_suggestions=50,
    )
    save_current_session_if_workspace_changed(request, session, workspace_before)
    batch_entities = batch.get("entities") if isinstance(batch.get("entities"), dict) else {}
    response_entities: list[dict[str, Any]] = []
    for canonical_entity in selected_entities:
        block = batch_entities.get(canonical_entity) if isinstance(batch_entities, dict) else {}
        block = block if isinstance(block, dict) else {}
        field_payload = _step3_field_suggestions_payload(
            session,
            canonical_entity,
            available_entities,
            block.get("field") if isinstance(block.get("field"), dict) else None,
        )
        validation_payload = _step3_drawer_payload_from_result(
            session,
            scope="validations",
            canonical_entity=canonical_entity,
            available_entities=available_entities,
            batch_result=block.get("validations") if isinstance(block.get("validations"), dict) else None,
        )
        identity_payload = None
        if canonical_entity in identity_review_entities:
            identity_payload = _step3_drawer_payload_from_result(
                session,
                scope="identity_role",
                canonical_entity=canonical_entity,
                available_entities=available_entities,
                batch_result=block.get("identity_role") if isinstance(block.get("identity_role"), dict) else None,
            )
        response_entities.append(
            {
                "entity": canonical_entity,
                "field": field_payload,
                "validations": validation_payload,
                "identity_role": identity_payload,
            }
        )

    return JSONResponse(
        {
            "ok": True,
            "selected_entities": selected_entities,
            "identity_review_entities": identity_review_entities,
            "entities": response_entities,
            "warnings": [
                str(warning)
                for warning in batch.get("warnings", [])
                if str(warning or "").strip()
            ],
        }
    )


@router.post("/ks/identity-role-review", response_class=JSONResponse)
async def step3_ks_identity_role_review(request: Request):
    session = get_current_session(request)
    if session.app_archetype != "crud":
        return JSONResponse(
            {"ok": False, "errors": ["Step 3 identity role review is available for CRUD projects only."]},
            status_code=400,
        )
    if not session.capabilities.knowledge_assist_enabled:
        return JSONResponse(
            {"ok": False, "errors": ["Knowledge Assist is off; no identity-role suggestion decisions were submitted."]},
            status_code=400,
        )

    body = await request.json()
    decisions, errors = _normalize_identity_role_review_decisions(body.get("decisions"))
    if errors:
        return JSONResponse({"ok": False, "errors": errors}, status_code=400)
    if not decisions:
        return JSONResponse(
            {
                "ok": True,
                "skipped": True,
                "message": "No staged identity-role suggestion decisions to save.",
                "outcomes": [],
                "saved_count": 0,
                "failed_count": 0,
                "applied_count": 0,
                "warnings": [],
            }
        )

    preflight_errors: list[str] = []
    for decision in decisions:
        if decision["status"] not in {"accepted", "edited"}:
            continue
        error = _identity_role_assignment_error(session, decision)
        if error:
            preflight_errors.append(f"{decision['suggestion_id']}: {error}")
    if not preflight_errors:
        preflight_errors.extend(_identity_role_batch_errors(decisions))

    if preflight_errors:
        return JSONResponse({"ok": False, "errors": preflight_errors}, status_code=400)

    ks_result = assist_service.submit_identity_role_suggestion_decisions(
        session,
        decisions=[_ks_review_payload(decision) for decision in decisions],
    )
    if ks_result is None:
        return JSONResponse(
            {
                "ok": True,
                "degraded": True,
                "message": "Identity-role suggestion review could not be saved. Manual identity role review remains available.",
                "outcomes": [],
                "saved_count": 0,
                "failed_count": len(decisions),
                "applied_count": 0,
                "warnings": [],
            }
        )

    successful_ids = _successful_outcome_ids(ks_result, decisions)
    ks_outcomes = _ks_outcomes_by_suggestion_id(ks_result)
    outcomes: list[dict[str, Any]] = []
    warnings: list[str] = []
    errors_out: list[str] = []
    applied_count = 0
    reviewed_at = datetime.now(timezone.utc).isoformat()

    for decision in decisions:
        suggestion_id = decision["suggestion_id"]
        success = suggestion_id in successful_ids
        ks_outcome = ks_outcomes.get(suggestion_id, {})
        outcome_messages = _ks_outcome_messages(ks_outcome)
        if success:
            warnings.extend(f"{suggestion_id}: {message}" for message in outcome_messages)
        else:
            error = str(ks_outcome.get("error") or "").strip()
            if error:
                errors_out.append(f"{suggestion_id}: {error}")
            warnings.extend(
                f"{suggestion_id}: {message}"
                for message in _ks_outcome_messages({"warnings": ks_outcome.get("warnings")})
            )

        applied = False
        if success:
            if decision["status"] in {"accepted", "edited"}:
                _upsert_ka_identity_role_decision(session, decision, reviewed_at=reviewed_at)
                applied = True
                applied_count += 1
            _record_identity_role_review(session, decision, reviewed_at=reviewed_at)

        outcomes.append(
            {
                "suggestion_id": suggestion_id,
                "status": decision["status"],
                "success": success,
                "applied": applied,
                "manifest_path": decision.get("manifest_path"),
                "error": ks_outcome.get("error"),
                "warnings": ks_outcome.get("warnings", []),
            }
        )

    save_current_session(request, session)
    saved_count = sum(1 for outcome in outcomes if outcome["success"])
    failed_count = len(outcomes) - saved_count
    _, _, identity_role_lens = _identity_role_lens_for_session(session)
    return JSONResponse(
        {
            "ok": failed_count == 0,
            "partial_failure": failed_count > 0,
            "message": f"Saved {saved_count} identity-role suggestion decision(s); applied {applied_count} identity role(s).",
            "outcomes": outcomes,
            "saved_count": saved_count,
            "failed_count": failed_count,
            "applied_count": applied_count,
            "warnings": warnings,
            "errors": errors_out,
            "refresh": applied_count > 0,
            "stats": identity_role_lens["stats"],
            "entities": identity_role_lens["entities"],
        }
    )


@router.post("/ks/validation-review", response_class=JSONResponse)
async def step3_ks_validation_review(request: Request):
    session = get_current_session(request)
    if session.app_archetype != "crud":
        return JSONResponse(
            {"ok": False, "errors": ["Step 3 validation hint review is available for CRUD projects only."]},
            status_code=400,
        )
    if not session.capabilities.knowledge_assist_enabled:
        return JSONResponse(
            {"ok": False, "errors": ["Knowledge Assist is off; no validation hint decisions were submitted."]},
            status_code=400,
        )

    body = await request.json()
    decisions, errors = _normalize_validation_review_decisions(body.get("decisions"))
    if errors:
        return JSONResponse({"ok": False, "errors": errors}, status_code=400)
    if not decisions:
        return JSONResponse(
            {
                "ok": True,
                "skipped": True,
                "message": "No staged validation hint decisions to save.",
                "outcomes": [],
                "saved_count": 0,
                "failed_count": 0,
                "applied_count": 0,
                "warnings": [],
            }
        )

    preflight_errors: list[str] = []
    preflight_warnings: list[str] = []
    candidate_paths: dict[str, str] = {}

    for decision in decisions:
        suggestion_id = decision["suggestion_id"]
        entity_name = decision["entity"]
        status = decision["status"]
        payload = decision["edited_payload"] if status == "edited" else decision["payload"]
        payload = payload if isinstance(payload, dict) else {}

        if status not in {"accepted", "edited"}:
            candidate_paths[suggestion_id] = _manifest_path_for_validation_decision(decision, payload)
            continue

        field, field_error = _canonicalize_validation_payload_field(session, entity_name, payload)
        if field_error:
            preflight_errors.append(f"{suggestion_id}: {field_error}")
            continue

        validation_types = _validation_rule_types_from_payload(payload)
        decision["field_name"] = field.name if field is not None else decision["field_name"]
        candidate_paths[suggestion_id] = _manifest_path_for_validation_decision(decision, payload)

        working_field = field.model_copy(deep=True)
        rules, warning = _apply_validation_payload_to_field(working_field, payload, validation_types)
        if warning:
            allowed_review_only = "manual authoring" in warning
            if allowed_review_only:
                preflight_warnings.append(f"{suggestion_id}: {warning}")
            else:
                preflight_errors.append(f"{suggestion_id}: {warning}")
                continue

    if preflight_errors:
        return JSONResponse({"ok": False, "errors": preflight_errors}, status_code=400)

    ks_result = assist_service.submit_validation_suggestion_decisions(
        session,
        decisions=[_ks_review_payload(decision) for decision in decisions],
    )
    if ks_result is None:
        return JSONResponse(
            {
                "ok": True,
                "degraded": True,
                "message": "Validation hint review could not be saved. Manual Step 3 authoring remains available.",
                "outcomes": [],
                "saved_count": 0,
                "failed_count": len(decisions),
                "applied_count": 0,
                "warnings": preflight_warnings,
            }
        )

    successful_ids = _successful_outcome_ids(ks_result, decisions)
    ks_outcomes = _ks_outcomes_by_suggestion_id(ks_result)
    outcomes: list[dict[str, Any]] = []
    applied_count = 0
    warnings = list(preflight_warnings)
    errors: list[str] = []

    for decision in decisions:
        suggestion_id = decision["suggestion_id"]
        success = suggestion_id in successful_ids
        ks_outcome = ks_outcomes.get(suggestion_id, {})
        outcome_messages = _ks_outcome_messages(ks_outcome)
        if success:
            warnings.extend(f"{suggestion_id}: {message}" for message in outcome_messages)
        else:
            error = str(ks_outcome.get("error") or "").strip()
            if error:
                errors.append(f"{suggestion_id}: {error}")
            warnings.extend(
                f"{suggestion_id}: {message}"
                for message in _ks_outcome_messages({"warnings": ks_outcome.get("warnings")})
            )
        applied = False
        if success:
            manifest_path = candidate_paths[suggestion_id]
            _record_validation_review(session, decision, manifest_path=manifest_path)
            if decision["status"] in {"accepted", "edited"}:
                payload = decision["edited_payload"] if decision["status"] == "edited" else decision["payload"]
                payload = payload if isinstance(payload, dict) else {}
                field, field_error = _field_for_validation_payload(session, decision["entity"], payload)
                if field is None:
                    warnings.append(f"{suggestion_id}: {field_error}")
                else:
                    validation_types = _validation_rule_types_from_payload(payload)
                    rules, warning = _apply_validation_payload_to_field(field, payload, validation_types)
                    if warning:
                        warnings.append(f"{suggestion_id}: {warning}")
                    else:
                        rules = [
                            _stamp_ka_validation_rule(
                                rule,
                                suggestion_id=suggestion_id,
                                status=decision["status"],
                            )
                            for rule in rules
                        ]
                        applied_count_for_decision = _upsert_validation_rules(session, decision["entity"], rules)
                        applied = applied_count_for_decision > 0
                        applied_count += applied_count_for_decision
                        if not applied and rules:
                            warnings.append(f"{suggestion_id}: matching validation rule already exists; review was recorded without duplicating it.")
            elif decision["status"] == "rejected":
                payload = decision["payload"] if isinstance(decision["payload"], dict) else {}
                expected_rules = _expected_validation_rules_for_decision(session, decision, payload)
                retained_state = _mark_ka_validation_rules_review_status(
                    session,
                    suggestion_id=suggestion_id,
                    status="rejected",
                    expected_rules=expected_rules,
                )
                if retained_state["updated"]:
                    warnings.append(
                        f"{suggestion_id}: Reject recorded. The KA-applied rule remains until removed in Step 6."
                    )
                if retained_state["edited"]:
                    warnings.append(
                        f"{suggestion_id}: Reject recorded. A KA-applied rule was changed after application and remains as KA-applied, edited."
                    )

        outcomes.append(
            {
                "suggestion_id": suggestion_id,
                "status": decision["status"],
                "success": success,
                "applied": applied,
                "manifest_path": candidate_paths.get(suggestion_id),
                "error": ks_outcome.get("error"),
                "warnings": ks_outcome.get("warnings", []),
            }
        )

    save_current_session(request, session)
    saved_count = sum(1 for outcome in outcomes if outcome["success"])
    failed_count = len(outcomes) - saved_count
    return JSONResponse(
        {
            "ok": failed_count == 0,
            "partial_failure": failed_count > 0,
            "message": f"Saved {saved_count} validation hint decision(s); applied {applied_count} validation rule(s).",
            "outcomes": outcomes,
            "saved_count": saved_count,
            "failed_count": failed_count,
            "applied_count": applied_count,
            "warnings": warnings,
            "errors": errors,
        }
    )


@router.get("/ks/evidence", response_class=JSONResponse)
async def step3_ks_evidence(
    request: Request,
    entity: str = Query(""),
    field_name: str = Query(""),
    suggestion_id: str = Query(""),
):
    session = get_current_session(request)
    if session.app_archetype != "crud":
        return JSONResponse(
            {
                "ok": False,
                "warning": "Step 3 KS evidence is available for CRUD projects only.",
            },
            status_code=400,
        )

    canonical_entity, available_entities = _resolve_canonical_entity(session, entity.strip() or None)
    requested_field_name = field_name.strip()
    resolved_field = (
        _resolve_current_crud_field(session, canonical_entity, requested_field_name)
        if canonical_entity
        else None
    )
    normalized_field_name = resolved_field.name if resolved_field is not None else requested_field_name
    if not canonical_entity or not normalized_field_name:
        return JSONResponse(
            {
                "ok": False,
                "warning": "Entity and field_name are required to load KS evidence.",
                "selected_entities": available_entities,
            },
            status_code=400,
        )

    workspace_before = workspace_session_marker(session)
    result = assist_service.get_field_evidence_chain(
        session,
        entity=canonical_entity,
        field_name=normalized_field_name,
        suggestion_id=suggestion_id.strip() or None,
    )
    save_current_session_if_workspace_changed(request, session, workspace_before)
    if result is None:
        return JSONResponse(
            {
                "ok": True,
                "entity": canonical_entity,
                "field_name": normalized_field_name,
                "suggestion": None,
                "definitions": [],
                "evidence_chunks": [],
                "source_count": 0,
                "warnings": [],
            }
        )

    return JSONResponse(
        {
            "ok": True,
            "entity": canonical_entity,
            "field_name": normalized_field_name,
            "suggestion": result.get("suggestion"),
            "definitions": result.get("definitions", []),
            "evidence_chunks": result.get("evidence_chunks", []),
            "source_count": result.get("source_count", 0),
            "warnings": result.get("warnings", []),
        }
    )


@router.post("/ks/review", response_class=JSONResponse)
async def step3_ks_review(request: Request):
    session = get_current_session(request)
    if session.app_archetype != "crud":
        return JSONResponse(
            {
                "ok": False,
                "warning": "Step 3 KS field suggestion review is available for CRUD projects only.",
            },
            status_code=400,
        )

    body = await request.json()
    decisions, errors = _normalize_review_decisions(body.get("decisions"))
    if errors:
        return JSONResponse(
            {
                "ok": False,
                "errors": errors,
            },
            status_code=400,
        )
    if not decisions:
        return JSONResponse(
            {
                "ok": True,
                "skipped": True,
                "message": "No staged suggestion decisions to save.",
                "outcomes": [],
            }
        )
    if not session.capabilities.knowledge_assist_enabled:
        return JSONResponse(
            {
                "ok": True,
                "skipped": True,
                "message": "Knowledge Assist is off; no suggestion decisions were submitted.",
                "outcomes": [],
            }
        )
    preflight_errors = _field_review_preflight_errors(session, decisions)
    if preflight_errors:
        return JSONResponse(
            {
                "ok": False,
                "errors": preflight_errors,
            },
            status_code=400,
        )

    project_id = ensure_workspace_identity(session)
    ks_decisions: list[dict[str, Any]] = []
    decision_by_id: dict[str, dict[str, Any]] = {}
    for decision in decisions:
        manifest_path = _manifest_path_for_field(
            decision["entity"],
            decision["final_field_name"],
        )
        if decision["status"] == "edited":
            edited_payload = dict(decision["edited_payload"] or {})
            edited_payload["manifest_path"] = manifest_path
            decision["edited_payload"] = edited_payload
            ks_decisions.append(
                {
                    "suggestion_id": decision["suggestion_id"],
                    "status": decision["status"],
                    "edited_payload": edited_payload,
                }
            )
        else:
            ks_decisions.append(
                {
                    "suggestion_id": decision["suggestion_id"],
                    "status": decision["status"],
                }
            )
        decision_by_id[decision["suggestion_id"]] = decision

    try:
        with ks_client(
            allowed_roots=workspace_allowed_roots(session),
            db_path=workspace_db_path(session),
        ) as client:
            result = client.submit_suggestion_decisions(
                project_id=project_id,
                decisions=ks_decisions,
            )
            mark_workspace_active(session)
    except KSUnavailableError as exc:
        return JSONResponse(
            {
                "ok": False,
                "degraded": True,
                "warning": f"Knowledge Server unavailable: {exc}",
                "outcomes": [],
            }
        )
    except KSCallError as exc:
        return JSONResponse(
            {
                "ok": False,
                "degraded": True,
                "warning": f"Knowledge Server review submission failed: {exc.error_message}",
                "outcomes": [],
            }
        )

    outcomes = result.get("outcomes", [])
    saved_count = 0
    failed_count = 0
    for outcome in outcomes:
        suggestion_id = str(outcome.get("suggestion_id") or "")
        if outcome.get("success") is True and suggestion_id in decision_by_id:
            _apply_review_outcome(session, decision_by_id[suggestion_id])
            saved_count += 1
        elif suggestion_id:
            failed_count += 1

    if saved_count:
        save_current_session(request, session)

    partial_failure = saved_count > 0 and failed_count > 0
    ok = failed_count == 0
    if partial_failure:
        message = f"Saved {saved_count} suggestion decision(s), but {failed_count} failed."
    elif ok:
        message = f"Saved {saved_count} suggestion decision(s)."
    else:
        message = "No suggestion decisions were saved."

    return JSONResponse(
        {
            "ok": ok,
            "partial_failure": partial_failure,
            "saved_count": saved_count,
            "failed_count": failed_count,
            "message": message,
            "outcomes": outcomes,
            "warnings": result.get("warnings", []),
        }
    )


@router.get("/next", response_class=HTMLResponse)
async def step3_next():
    return RedirectResponse("/handoffs", status_code=303)
