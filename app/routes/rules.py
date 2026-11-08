"""Step 6 — Rules + Legacy Notes."""

from __future__ import annotations

import json
import re
import threading
from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.models.project import (
    EntityRules,
    KSEvidenceLink,
    KSReviewHistoryEntry,
    ProjectSession,
    RuleEntry,
)
from app.paths import TEMPLATE_DIR
from app.services import readiness_view
from app.services.assist_service import AssistService
from app.services.edge_contracts import EDGE_CONTRACT_TYPES
from app.services.identity_roles import selected_canonical_entities
from app.services.nav_context import build_nav_context
from app.services.openapi_service import auto_generate_rules
from app.services.session_context import (
    get_current_session,
    save_current_session,
    save_current_session_if_workspace_changed,
    workspace_session_marker,
)
from app.services.validation_fingerprints import (
    validation_rule_constraint_matches as _validation_rule_constraint_matches,
)

router = APIRouter(prefix="/rules")
templates = Jinja2Templates(directory=TEMPLATE_DIR)
assist_service = AssistService()
_FIELD_COMPARISON_OPERATORS = {"<=", "<", ">=", ">", "=="}
_CROSS_ENTITY_FIELD_CHECK_OPERATORS = {"lt", "lte", "gt", "gte", "eq", "neq"}
_CROSS_ENTITY_FIELD_COMPARE_OPERATORS = {"lt", "lte", "gt", "gte", "eq", "neq"}
_NUMERIC_FIELD_TYPES = {"integer", "decimal", "number", "float", "double", "long", "int"}
_STRING_LIKE_FIELD_TYPES = {"string"}
_BOOLEAN_FIELD_TYPES = {"boolean", "bool"}
_DATE_FIELD_TYPES = {"date"}
_DATETIME_FIELD_TYPES = {"datetime"}
_STEP6_SUGGESTION_TYPES = {"rule", "cross_entity_rule"}
_STEP6_REVIEW_STATUSES = {"accepted", "edited", "rejected"}
_SAVE_ONE_MUTATION_LOCK = threading.RLock()


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _default_rule_file_path(entity_name: str) -> str:
    return f"rules/{_slug(entity_name)}-business-rules.yaml"


def _normalize_pattern_rule_value(value: str | None) -> str | None:
    r"""Normalize common JSON/JS-pasted regex escapes into raw regex text.

    Step 6 rule values are authored in a plain text input, but users often paste
    regexes copied from JSON or JavaScript sources where escapes are doubled
    (for example ``\\s`` instead of ``\s``).  If we persist those doubled
    escapes verbatim, the later Java generation layer escapes them again and the
    generated Bean Validation pattern ends up matching the literal sequence
    instead of the intended regex token.

    Keep the normalization intentionally narrow: collapse only the common regex
    escape sequences users are likely to paste from JSON/JS examples.
    """
    if value is None:
        return None
    normalized = re.sub(r"\\\\(?=[sSdDwWbB.])", r"\\", value)
    return normalized or None


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "1", "yes", "y"}


def _build_entity_fields_map(session: ProjectSession) -> dict[str, list[dict[str, Any]]]:
    """Merge classified entity fields by canonical entity name for Step 6 authoring."""
    entity_fields_map: dict[str, list[dict[str, Any]]] = {}
    for ce in session.classified_entities:
        if ce.classification != "entity" or not ce.fields:
            continue

        canonical = ce.display_name()
        incoming = [
            {
                "name": field.name,
                "type": field.type,
                "enum_values": list(field.enum_values),
                "required": field.required,
                "is_id": field.is_id,
            }
            for field in ce.fields
        ]
        if canonical not in entity_fields_map:
            entity_fields_map[canonical] = incoming
            continue

        seen = {field["name"] for field in entity_fields_map[canonical]}
        for field in incoming:
            if field["name"] in seen:
                continue
            entity_fields_map[canonical].append(field)
            seen.add(field["name"])

    return entity_fields_map


def _has_edge_contract_interfaces(session: ProjectSession) -> bool:
    return any(
        iface.type in EDGE_CONTRACT_TYPES
        for iface in [*session.upstream_interfaces, *session.downstream_interfaces]
    )


def _has_crud_entity_classification(session: ProjectSession) -> bool:
    return any(entity.classification == "entity" for entity in session.classified_entities)


def _entity_field_lookup(session: ProjectSession) -> dict[str, dict[str, dict[str, Any]]]:
    return {
        entity_name: {field["name"]: field for field in fields}
        for entity_name, fields in _build_entity_fields_map(session).items()
    }


def _is_numeric_field(field_meta: dict[str, Any] | None) -> bool:
    if not field_meta:
        return False
    return str(field_meta.get("type") or "").lower() in _NUMERIC_FIELD_TYPES


def _is_string_like_field(field_meta: dict[str, Any] | None) -> bool:
    if not field_meta:
        return False
    field_type = str(field_meta.get("type") or "").lower()
    if field_type in _STRING_LIKE_FIELD_TYPES:
        return True
    return bool(field_meta.get("enum_values"))


def _supports_field_check_target(field_meta: dict[str, Any] | None) -> bool:
    if not field_meta:
        return False
    field_type = str(field_meta.get("type") or "").lower()
    return (
        _is_string_like_field(field_meta)
        or field_type in _NUMERIC_FIELD_TYPES
        or field_type in _BOOLEAN_FIELD_TYPES
        or field_type in _DATE_FIELD_TYPES
        or field_type in _DATETIME_FIELD_TYPES
    )


def _expected_value_matches_field_type(field_meta: dict[str, Any] | None, expected_value: str | None) -> bool:
    if not field_meta or expected_value is None:
        return False

    field_type = str(field_meta.get("type") or "").lower()
    if _is_string_like_field(field_meta):
        return True
    if field_type in _NUMERIC_FIELD_TYPES:
        try:
            numeric_value = Decimal(expected_value)
        except (InvalidOperation, ValueError):
            return False
        if field_type in {"integer", "int", "long"}:
            return numeric_value == numeric_value.to_integral_value()
        return True
    if field_type in _BOOLEAN_FIELD_TYPES:
        return expected_value.lower() in {"true", "false"}
    if field_type in _DATE_FIELD_TYPES:
        try:
            date.fromisoformat(expected_value)
        except ValueError:
            return False
        return True
    if field_type in _DATETIME_FIELD_TYPES:
        normalized = expected_value.replace("Z", "+00:00")
        try:
            datetime.fromisoformat(normalized)
        except ValueError:
            return False
        return True
    return False


# ---------------------------------------------------------------------------
# Heuristic: detect likely server-generated ID fields
# ---------------------------------------------------------------------------

def _build_generated_id_warnings(session: ProjectSession) -> tuple[list[dict], list[str]]:
    """Return (warnings, likely_generated_id_fields) for server-generated ID detection.

    A field is heuristically marked as "likely server-generated" when:
      1. field.is_id is True, OR (field name ends with "Id" AND field type is "string")
      2. AND the field name does NOT appear as a key in ANY create-operation request
         sample body for that entity's upstream interface.

    This is a best-effort heuristic — false positives are possible.  Warnings are
    advisory only; they do not block saving or exporting.

    Returns:
        warnings: list of {"entity_field": str, "message": str}
        likely_generated_id_fields: list of "EntityName.fieldName" strings
    """
    # Build a map: canonical_name -> set of field names present in create request bodies.
    # We look at session.upstream_interfaces whose entity_name maps to a canonical entity.
    # Each interface has operations (OperationSample); we inspect request_sample_content
    # for operations whose name starts with "create" (case-insensitive).
    create_body_fields: dict[str, set[str]] = {}  # canonical_name -> {field names in body}

    # Build canonical_name lookup from classified_entities
    canonical_by_raw: dict[str, str] = {
        ce.name: ce.display_name() for ce in session.classified_entities
    }

    for iface in session.upstream_interfaces:
        # Determine the canonical entity name this interface belongs to
        raw_entity = iface.entity_name or ""
        canonical = canonical_by_raw.get(raw_entity, raw_entity)
        if not canonical:
            continue

        for op in iface.operations:
            if not op.name.lower().startswith("create"):
                continue
            # Prefer in-memory content; fall back to path-based read (not implemented
            # in Studio currently — samples are stored inline as request_sample_content).
            content_str = op.request_sample_content or ""
            if not content_str:
                continue
            try:
                body = json.loads(content_str)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(body, dict):
                continue
            if canonical not in create_body_fields:
                create_body_fields[canonical] = set()
            create_body_fields[canonical].update(body.keys())

    warnings: list[dict] = []
    likely_generated_id_fields: list[str] = []

    for ce in session.classified_entities:
        if ce.classification != "entity":
            continue
        canonical = ce.display_name()
        body_keys = create_body_fields.get(canonical, set())

        for field in ce.fields:
            # Heuristic: is_id flag OR (name ends with "Id" AND type is "string")
            is_id_field = field.is_id or (
                field.name.endswith("Id") and field.type == "string"
            )
            if not is_id_field:
                continue

            # If there are no create request samples at all we cannot determine
            # whether the field is client- or server-supplied — skip warning.
            if not body_keys and canonical not in create_body_fields:
                continue

            # Field absent from the create request body → likely server-generated.
            if field.name not in body_keys:
                entity_field = f"{canonical}.{field.name}"
                if entity_field not in likely_generated_id_fields:
                    likely_generated_id_fields.append(entity_field)
                    warnings.append({
                        "entity_field": entity_field,
                        "message": (
                            f"{entity_field} looks server-generated, so input/business-key "
                            f"rules like max-length or pattern may be ignored by AppBuilder."
                        ),
                    })

    return warnings, likely_generated_id_fields


def _selected_canonical_entities(session: ProjectSession) -> list[str]:
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


def _set_review_bucket(session: ProjectSession, suggestion_id: str, status: str) -> None:
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


def _remove_evidence_link(
    session: ProjectSession,
    *,
    suggestion_id: str,
) -> None:
    session.ks_workspace_state.evidence_links = [
        link
        for link in session.ks_workspace_state.evidence_links
        if link.suggestion_id != suggestion_id
    ]


def _replace_step6_evidence_link(
    session: ProjectSession,
    *,
    suggestion_id: str,
    manifest_path: str,
    status: str,
) -> None:
    _remove_evidence_link(session, suggestion_id=suggestion_id)
    provenance = "ai-accepted" if status == "accepted" else "ai-edited" if status == "edited" else None
    if provenance is None:
        return
    session.ks_workspace_state.evidence_links.append(
        KSEvidenceLink(
            manifest_path=manifest_path,
            suggestion_id=suggestion_id,
            provenance=provenance,
        )
    )


def _latest_payload(decision: dict[str, Any]) -> dict[str, Any]:
    payload = decision.get("edited_payload") if decision.get("status") == "edited" else decision.get("payload")
    return payload if isinstance(payload, dict) else {}


def _canonical_field_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _resolve_current_field_name(session: ProjectSession, entity_name: str, field_name: str | None) -> str | None:
    field_text = str(field_name or "").strip()
    if not field_text:
        return None
    selected_names = set(session.selected_entity_names)
    entities = [
        entity
        for entity in session.classified_entities
        if entity.name in selected_names and entity.display_name() == entity_name
    ] or [
        entity
        for entity in session.classified_entities
        if entity.display_name() == entity_name
    ]
    if not entities:
        return None
    fields = entities[0].fields
    for field in fields:
        if field.name == field_text:
            return field.name
    field_key = _canonical_field_key(field_text)
    matches = [field.name for field in fields if _canonical_field_key(field.name) == field_key]
    return matches[0] if len(matches) == 1 else None


def _canonicalize_rule_payload_fields(session: ProjectSession, entity_name: str, payload: dict[str, Any]) -> None:
    source_keys = (
        "field",
        "field_name",
        "source_field",
        "fk_field",
        "compare_source_field",
        "source_compare_field",
        "local_field",
    )
    for key in source_keys:
        resolved = _resolve_current_field_name(session, entity_name, _payload_text(payload, key))
        if resolved:
            payload[key] = resolved

    target_entity = _payload_text(payload, "target_entity", "target-entity", "referenced_entity")
    if target_entity:
        for key in ("target_field", "target-field"):
            resolved = _resolve_current_field_name(session, target_entity, _payload_text(payload, key))
            if resolved:
                payload[key] = resolved


def _payload_text(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _payload_values(payload: dict[str, Any], *keys: str) -> list[str]:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _constraint(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("constraint")
    return value if isinstance(value, dict) else {}


def _normalize_rule_type(value: str | None) -> str:
    normalized = (value or "").strip().replace("_", "-")
    aliases = {
        "allowed-values": "allowed-values",
        "allowedvalues": "allowed-values",
        "not-null": "not-null",
        "notnull": "not-null",
        "business-constraint": "business-constraint",
        "businessconstraint": "business-constraint",
        "cross-entity-exists": "cross-entity-exists",
        "cross-entity-reference": "cross-entity-exists",
        "fk-reference": "cross-entity-exists",
        "reference-exists": "cross-entity-exists",
        "cross-entity-field-check": "cross-entity-field-check",
        "cross-entity-field-compare": "cross-entity-field-compare",
        "cross-entity-field-in": "cross-entity-field-in",
    }
    return aliases.get(normalized, normalized)


def _entity_rules_for(session: ProjectSession, entity_name: str) -> EntityRules:
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


def _rule_identity(rule: RuleEntry) -> tuple[Any, ...]:
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


def _validation_review_path_matches_rule(manifest_path: str, entity_name: str, rule: RuleEntry) -> bool:
    parts = [part for part in str(manifest_path or "").split(".") if part]
    if len(parts) < 6 or parts[0] != "entities" or parts[2] != "fields":
        return True
    return parts[1] == entity_name and parts[3] == rule.field and parts[-1] == rule.type


def _latest_validation_review_for_rule(
    session: ProjectSession,
    rule: RuleEntry,
) -> KSReviewHistoryEntry | None:
    if not rule.suggestion_id:
        return None
    for entry in reversed(session.ks_workspace_state.review_history):
        if entry.type != "validation" or entry.suggestion_id != rule.suggestion_id:
            continue
        return entry
    return None


def _ka_validation_rule_matches_latest_review(
    session: ProjectSession,
    entity_name: str,
    rule: RuleEntry,
) -> bool | None:
    entry = _latest_validation_review_for_rule(session, rule)
    if entry is None:
        return None
    if not _validation_review_path_matches_rule(entry.manifest_path, entity_name, rule):
        return False
    context = entry.review_context if isinstance(entry.review_context, dict) else {}
    expected_fingerprint = str(context.get("constraint_fingerprint") or "").strip()
    if not _validation_rule_constraint_matches(rule, expected_fingerprint):
        return False
    return True


def _classify_saved_ka_validation_rule(
    session: ProjectSession,
    entity_name: str,
    rule: RuleEntry,
) -> RuleEntry:
    if not (
        rule.generated_by_ka
        and rule.suggestion_id
        and (rule.suggestion_type or "validation") == "validation"
    ):
        return rule
    matches_review = _ka_validation_rule_matches_latest_review(session, entity_name, rule)
    if matches_review is False:
        rule.ka_review_status = "edited"
    return rule


def _append_rule_if_missing(entity_rules: EntityRules, rule: RuleEntry) -> bool:
    incoming = _rule_identity(rule)
    for existing in entity_rules.rules:
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
            return False
    entity_rules.rules.append(rule)
    return True


def _stamp_spec_derived_rule(rule: RuleEntry) -> RuleEntry:
    stamped = rule.model_copy(deep=True)
    if not stamped.applied_by:
        stamped.applied_by = "openapi-spec"
    return stamped


def _stamp_ka_rule(rule: RuleEntry, *, suggestion_id: str, suggestion_type: str, status: str) -> RuleEntry:
    stamped = rule.model_copy(deep=True)
    stamped.suggestion_id = suggestion_id
    stamped.suggestion_type = suggestion_type
    stamped.applied_by = "knowledge_assist"
    stamped.applied_at = datetime.now(timezone.utc).isoformat()
    stamped.generated_by_ka = True
    stamped.ka_review_status = status
    return stamped


def _mark_ka_rule_review_status(
    session: ProjectSession,
    *,
    suggestion_id: str,
    status: str,
) -> int:
    updated = 0
    for entity_rules in session.entity_rules:
        for rule in entity_rules.rules:
            if rule.generated_by_ka and rule.suggestion_id == suggestion_id:
                rule.ka_review_status = status
                updated += 1
    return updated


def _merge_auto_generated_rules(session: ProjectSession, auto_rules: list[EntityRules]) -> bool:
    """Gap-fill spec-derived rules without overwriting existing manual/KA rules.

    Returns True only when persisted rule state changed.  The completion marker
    is persisted together with real rule/file-path changes, but marker-only
    bookkeeping should not turn an otherwise no-op GET render into a disk write.
    """
    changed = False
    existing_by_entity = {entity_rules.entity_name: entity_rules for entity_rules in session.entity_rules}
    completed_entities = set(session.auto_rule_merge_completed_entities)
    completed_list = list(session.auto_rule_merge_completed_entities)
    grouped_auto_rules: dict[str, list[EntityRules]] = {}
    for generated in auto_rules:
        grouped_auto_rules.setdefault(generated.entity_name, []).append(generated)

    def mark_completed(entity_name: str) -> None:
        if entity_name not in completed_entities:
            completed_entities.add(entity_name)
            completed_list.append(entity_name)

    for entity_name, generated_buckets in grouped_auto_rules.items():
        if entity_name in completed_entities:
            continue

        current = existing_by_entity.get(entity_name)
        if current is None:
            current = EntityRules(
                entity_name=entity_name,
                rules=[],
                file_path=generated_buckets[0].file_path,
            )
            session.entity_rules.append(current)
            existing_by_entity[entity_name] = current
            changed = True

        if not current.file_path:
            for generated in generated_buckets:
                if generated.file_path:
                    current.file_path = generated.file_path
                    changed = True
                    break

        existing_identities = {_rule_identity(rule) for rule in current.rules}
        existing_field_types = {(rule.field, rule.type) for rule in current.rules}
        for generated in generated_buckets:
            for rule in generated.rules:
                stamped_rule = _stamp_spec_derived_rule(rule)
                identity = _rule_identity(stamped_rule)
                if identity in existing_identities or (rule.field, rule.type) in existing_field_types:
                    continue
                current.rules.append(stamped_rule)
                existing_identities.add(identity)
                existing_field_types.add((rule.field, rule.type))
                changed = True

        mark_completed(entity_name)

    if completed_list != session.auto_rule_merge_completed_entities:
        if changed:
            session.auto_rule_merge_completed_entities = completed_list

    return changed


def _has_cross_entity_exists(entity_rules: EntityRules, field: str, target_entity: str | None) -> bool:
    return any(
        rule.type == "cross-entity-exists"
        and rule.field == field
        and (not target_entity or rule.target_entity == target_entity)
        for rule in entity_rules.rules
    )


def _manifest_path_for_rule(entity_name: str, rule: RuleEntry, fallback_id: str) -> str:
    if rule.type.startswith("cross-entity"):
        return f"rules.{entity_name}.{rule.field}.{rule.type}"
    return f"rules.{entity_name}.{fallback_id}"


def _rule_from_rule_payload(payload: dict[str, Any]) -> tuple[RuleEntry | None, str | None]:
    constraint = _constraint(payload)
    field = _payload_text(payload, "field", "field_name", "source_field")
    rule_type = _normalize_rule_type(
        _payload_text(payload, "rule_type", "type", "constraint_type")
        or _payload_text(constraint, "rule_type", "type")
    )
    if not field or not rule_type:
        return None, "Rule suggestions require field and rule_type."

    if rule_type == "allowed-values":
        values = _payload_values(constraint, "values", "allowed_values") or _payload_values(payload, "values", "allowed_values")
        if not values:
            return None, "allowed_values rule suggestions require at least one value."
        return RuleEntry(field=field, type="allowed-values", values=values), None

    if rule_type == "range":
        min_value = _payload_text(constraint, "min", "minimum") or _payload_text(payload, "min", "minimum")
        max_value = _payload_text(constraint, "max", "maximum") or _payload_text(payload, "max", "maximum")
        if not min_value and not max_value:
            return None, "range rule suggestions require min or max."
        return RuleEntry(
            field=field,
            type="range",
            value=min_value,
            values=[max_value] if max_value else [],
        ), None

    if rule_type == "not-null":
        return RuleEntry(field=field, type="not-null"), None

    if rule_type == "pattern":
        pattern = _payload_text(constraint, "pattern", "value") or _payload_text(payload, "pattern", "value")
        if not pattern:
            return None, "pattern rule suggestions require a pattern value."
        return RuleEntry(field=field, type="pattern", value=_normalize_pattern_rule_value(pattern)), None

    if rule_type == "business-constraint":
        return None, "Business constraint suggestions require manual authoring and were recorded without applying a rule."

    return None, f"Unsupported rule suggestion type '{rule_type}'."


def _cross_entity_review_only_warning(missing_parts: list[str]) -> str:
    if not missing_parts:
        return "Review saved, but rule was not applied because required cross-entity rule details were missing."
    if len(missing_parts) == 1:
        missing = missing_parts[0]
    else:
        missing = f"{', '.join(missing_parts[:-1])} and {missing_parts[-1]}"
    return f"Review saved, but rule was not applied because {missing} was missing."


def _rules_from_cross_entity_payload(
    payload: dict[str, Any],
    *,
    current_rules: EntityRules,
) -> tuple[list[RuleEntry], str | None]:
    rule_type = _normalize_rule_type(_payload_text(payload, "rule_type", "type", "constraint_type"))
    source_field = _payload_text(payload, "source_field", "fk_field", "field", "field_name")
    target_entity = _payload_text(payload, "target_entity", "target-entity", "referenced_entity")
    missing = []
    if not rule_type:
        missing.append("rule type")
    if not source_field:
        missing.append("source field")
    if not target_entity:
        missing.append("target entity")
    if missing:
        return [], _cross_entity_review_only_warning(missing)

    if rule_type == "cross-entity-exists":
        return [
            RuleEntry(
                field=source_field,
                type="cross-entity-exists",
                target_entity=target_entity,
            )
        ], None

    rules: list[RuleEntry] = []
    if not _has_cross_entity_exists(current_rules, source_field, target_entity):
        rules.append(
            RuleEntry(
                field=source_field,
                type="cross-entity-exists",
                target_entity=target_entity,
            )
        )

    target_field = _payload_text(payload, "target_field", "target-field")
    operator = _payload_text(payload, "operator")
    error_message = _payload_text(payload, "error_message", "error-message")

    if rule_type == "cross-entity-field-check":
        expected_value = _payload_text(payload, "expected_value", "expected-value", "value")
        if operator not in _CROSS_ENTITY_FIELD_CHECK_OPERATORS:
            return [], "cross-entity-field-check suggestions require a valid operator."
        if not target_field or expected_value is None:
            return [], _cross_entity_review_only_warning(
                [
                    label
                    for value, label in (
                        (target_field, "target field"),
                        (expected_value, "expected value"),
                    )
                    if value is None or str(value).strip() == ""
                ]
            )
        rules.append(
            RuleEntry(
                field=source_field,
                type=rule_type,
                target_entity=target_entity,
                target_field=target_field,
                operator=operator,
                expected_value=expected_value,
                error_message=error_message,
            )
        )
        return rules, None

    if rule_type == "cross-entity-field-compare":
        compare_source_field = _payload_text(payload, "compare_source_field", "source_compare_field", "local_field")
        if operator not in _CROSS_ENTITY_FIELD_COMPARE_OPERATORS:
            return [], "cross-entity-field-compare suggestions require a valid operator."
        if not target_field or not compare_source_field:
            return [], _cross_entity_review_only_warning(
                [
                    label
                    for value, label in (
                        (target_field, "target field"),
                        (compare_source_field, "compare source field"),
                    )
                    if not value
                ]
            )
        rules.append(
            RuleEntry(
                field=source_field,
                type=rule_type,
                target_entity=target_entity,
                target_field=target_field,
                source_field=compare_source_field,
                operator=operator,
                error_message=error_message,
            )
        )
        return rules, None

    if rule_type == "cross-entity-field-in":
        values = _payload_values(payload, "allowed_values", "allowed-values", "values")
        if not target_field or not values:
            return [], _cross_entity_review_only_warning(
                [
                    label
                    for value, label in (
                        (target_field, "target field"),
                        (values, "allowed values"),
                    )
                    if not value
                ]
            )
        rules.append(
            RuleEntry(
                field=source_field,
                type=rule_type,
                target_entity=target_entity,
                target_field=target_field,
                values=values,
                error_message=error_message,
            )
        )
        return rules, None

    return [], f"Unsupported cross-entity rule suggestion type '{rule_type}'."


def _normalize_step6_review_decisions(raw_decisions: Any) -> tuple[list[dict[str, Any]], list[str]]:
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
        manifest_path = str(item.get("manifest_path") or "").strip()

        if not suggestion_id:
            errors.append(f"Decision {index + 1} must include suggestion_id.")
            continue
        if suggestion_type not in _STEP6_SUGGESTION_TYPES:
            errors.append(f"Decision {index + 1} has unsupported suggestion_type '{suggestion_type}'.")
            continue
        if status not in _STEP6_REVIEW_STATUSES:
            errors.append(f"Decision {index + 1} has unsupported status '{status}'.")
            continue
        if not entity:
            errors.append(f"Decision {index + 1} must include entity.")
            continue
        if status in {"accepted", "edited"}:
            candidate_payload = edited_payload if status == "edited" else payload
            if not candidate_payload:
                errors.append(f"Decision {index + 1} requires a payload for {status} review.")
                continue

        normalized.append(
            {
                "suggestion_id": suggestion_id,
                "suggestion_type": suggestion_type,
                "status": status,
                "entity": entity,
                "payload": payload,
                "edited_payload": edited_payload,
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
        payload["edited_payload"] = decision["edited_payload"]
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


def _record_step6_review(
    session: ProjectSession,
    decision: dict[str, Any],
    *,
    manifest_path: str,
    evidence_backed: bool = False,
) -> None:
    _set_review_bucket(session, decision["suggestion_id"], decision["status"])
    if evidence_backed:
        _replace_step6_evidence_link(
            session,
            suggestion_id=decision["suggestion_id"],
            manifest_path=manifest_path,
            status=decision["status"],
        )
    else:
        _remove_evidence_link(session, suggestion_id=decision["suggestion_id"])
    session.ks_workspace_state.review_history.append(
        KSReviewHistoryEntry(
            suggestion_id=decision["suggestion_id"],
            type=decision["suggestion_type"],
            status=decision["status"],
            manifest_path=manifest_path,
            reviewed_at=datetime.now(timezone.utc).isoformat(),
            edited_payload=decision["edited_payload"] if decision["status"] == "edited" else None,
        )
    )


@router.post("/ka/remove-validation-rule", response_class=JSONResponse)
async def remove_ka_validation_rule(request: Request):
    body = await request.json()
    session = get_current_session(request)
    suggestion_id = _normalize_optional_text(body.get("suggestion_id"))
    entity_name = _normalize_optional_text(body.get("entity"))
    field_name = _normalize_optional_text(body.get("field"))
    rule_type = _normalize_optional_text(body.get("type"))
    if not suggestion_id:
        return JSONResponse(
            {"ok": False, "errors": ["suggestion_id is required to remove a KA-applied rule."]},
            status_code=400,
        )

    removed_count = 0
    edited_count = 0
    for entity_rules in session.entity_rules:
        if entity_name and entity_rules.entity_name != entity_name:
            continue
        kept_rules: list[RuleEntry] = []
        for rule in entity_rules.rules:
            is_candidate = (
                rule.generated_by_ka
                and rule.suggestion_id == suggestion_id
                and (rule.suggestion_type or "validation") == "validation"
                and (not field_name or rule.field == field_name)
                and (not rule_type or rule.type == rule_type)
            )
            if not is_candidate:
                kept_rules.append(rule)
                continue
            matches_review = _ka_validation_rule_matches_latest_review(session, entity_rules.entity_name, rule)
            if matches_review is False:
                rule.ka_review_status = "edited"
                kept_rules.append(rule)
                edited_count += 1
                continue
            removed_count += 1
        entity_rules.rules = kept_rules

    if edited_count and not removed_count:
        save_current_session(request, session)
        return JSONResponse(
            {
                "ok": False,
                "removed_count": 0,
                "errors": [
                    "The KA-applied rule was changed after application and was not removed. "
                    "Use the standard Step 6 delete control if you want to remove the edited rule."
                ],
            },
            status_code=409,
        )
    if not removed_count:
        return JSONResponse(
            {"ok": False, "removed_count": 0, "errors": ["No matching unchanged KA-applied validation rule was found."]},
            status_code=404,
        )

    _remove_evidence_link(session, suggestion_id=suggestion_id)
    save_current_session(request, session)
    return JSONResponse(
        {
            "ok": True,
            "removed_count": removed_count,
            "message": "Removed KA-applied validation rule from Step 6.",
        }
    )


def _rule_focus_groups(
    session: ProjectSession,
    entity_rules: EntityRules,
    entity_fields_map: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    fields = entity_fields_map.get(entity_rules.entity_name, [])
    field_meta = {field["name"]: field for field in fields}
    ordered_names = [field["name"] for field in fields]
    for rule in entity_rules.rules:
        if rule.field and rule.field not in field_meta and rule.field not in ordered_names:
            ordered_names.append(rule.field)

    prerequisite_targets = readiness_view.rule_set_prerequisite_targets(session.entity_rules)
    missing = set(
        readiness_view.missing_rule_set_prerequisites(
            entity_rules,
            prerequisite_targets,
        )
    )
    groups: list[dict[str, Any]] = []
    for field_name in ordered_names:
        field_rules = [rule for rule in entity_rules.rules if rule.field == field_name]
        dependent = next(
            (
                rule
                for rule in field_rules
                if rule.type
                in {
                    "cross-entity-field-check",
                    "cross-entity-field-compare",
                    "cross-entity-field-in",
                }
            ),
            None,
        )
        target_entity = dependent.target_entity if dependent else None
        groups.append(
            {
                "field": field_name,
                "field_type": field_meta.get(field_name, {}).get("type", "custom"),
                "rules": [rule.model_dump(mode="json") for rule in field_rules],
                "has_cross_entity_rule": dependent is not None,
                "prerequisite_satisfied": (
                    dependent is not None
                    and (field_name, target_entity) not in missing
                ),
                "prerequisite_target": target_entity,
            }
        )
    return groups


def _rule_sets_for_view(
    session: ProjectSession,
    canonical_entity_names: list[str],
) -> list[EntityRules]:
    """Include selected entities without persisting empty rule-set placeholders."""
    by_name = {entity_rules.entity_name: entity_rules for entity_rules in session.entity_rules}
    names = list(canonical_entity_names)
    names.extend(name for name in by_name if name not in names)
    return [
        by_name.get(entity_name)
        or EntityRules(entity_name=entity_name, rules=[], file_path=None)
        for entity_name in names
    ]


@router.get("", response_class=HTMLResponse)
async def step6_get(request: Request, focus: str = ""):
    session = get_current_session(request)
    nav = build_nav_context(session, "/rules")
    is_crud = session.app_archetype == "crud"
    is_kafka = session.app_archetype == "kafka-integration"
    is_passthrough = session.app_archetype == "passthrough-router"

    # Resolve canonical entity names (mirrors AppBuilder's _normalize_entity_name).
    # Rules files are loaded by AppBuilder's rules/ingestion.py which uses the
    # entity name literally as a key into metadata translation.  If the name is
    # a raw schema name like 'CustomerResponse' instead of the canonical 'Customer'
    # the rules drift away from the canonical entity the rest of Studio uses.
    canonical_map: dict[str, str] = {
        ce.name: ce.display_name() for ce in session.classified_entities
    }
    canonical_entity_names: list[str] = list(
        dict.fromkeys(canonical_map.get(name, name) for name in session.selected_entity_names)
    )

    # Auto-populate rules from spec constraints without overwriting user edits
    # or Knowledge Assist-applied rules already present for the entity.
    if session.classified_entities and not is_kafka:
        visible_entities = set(canonical_entity_names)
        auto_rules = [
            entity_rules
            for entity_rules in auto_generate_rules(session.classified_entities)
            if entity_rules.entity_name in visible_entities
        ]
        if _merge_auto_generated_rules(session, auto_rules):
            save_current_session(request, session)

    rule_sets_for_view = _rule_sets_for_view(session, canonical_entity_names)

    # Pre-serialize entity_rules so Jinja2's tojson filter gets plain dicts.
    # Pydantic models are not JSON-serializable by the default stdlib encoder that
    # Jinja2's tojson filter uses.
    entity_rules_data = [er.model_dump() for er in session.entity_rules]

    entity_fields_map = _build_entity_fields_map(session)

    generated_id_warnings, likely_generated_id_fields = _build_generated_id_warnings(session)
    workspace_before = workspace_session_marker(session)
    conflict_advisories = _rule_conflict_advisories(session)
    rule_suggestion_badges = []
    if is_crud:
        rule_suggestion_badges = assist_service.get_rule_suggestion_badges_batch(
            session,
            entities=canonical_entity_names,
        )
    save_current_session_if_workspace_changed(request, session, workspace_before)

    rule_set_readiness_items = readiness_view.items_for_step(
        session,
        6,
        conflict_advisories=conflict_advisories,
    )
    rule_set_board_metadata = {
        entity_rules.entity_name: _rule_set_board_metadata(
            session,
            entity_rules,
            conflict_advisories=conflict_advisories,
        )
        for entity_rules in rule_sets_for_view
    }
    focus_rule_set = next(
        (
            entity_rules
            for entity_rules in rule_sets_for_view
            if entity_rules.entity_name == focus
        ),
        None,
    )
    focus_name = focus_rule_set.entity_name if focus_rule_set is not None else None
    focus_item = (
        _readiness_payload(
            session,
            focus_name,
            conflict_advisories=conflict_advisories,
        )
        if focus_name
        else None
    )
    if focus_item is None:
        focus_name = None
        focus_rule_set = None
    # The focused card already contains its own prerequisite rows. Do not seed
    # it with prerequisites from unrelated entity rule-sets.
    cross_entity_prerequisite_targets: dict[str, list[str]] = {}

    back_route = "/downstream"
    if is_kafka:
        back_route = "/kafka/transforms"
    elif is_passthrough:
        back_route = "/passthrough"

    shell_rail_default = (
        "expanded"
        if is_crud and conflict_advisories.get("has_items")
        else "collapsed"
    )

    return templates.TemplateResponse(request, "step6_rules.html", {
        "request": request,
        "session": session,
        "step": 6,
        "is_crud_rules": is_crud,
        "is_kafka_rules": is_kafka,
        "is_passthrough_rules": is_passthrough,
        "selected_entities": canonical_entity_names,
        "has_edge_contract_interfaces": _has_edge_contract_interfaces(session),
        "is_edge_contract_only_rules": (
            _has_edge_contract_interfaces(session)
            and not _has_crud_entity_classification(session)
        ),
        "canonical_entity_names": canonical_entity_names,
        "entity_rules_data": entity_rules_data,
        "entity_fields_map": entity_fields_map,
        "conflict_advisories": conflict_advisories,
        "rule_set_readiness_items": rule_set_readiness_items,
        "rule_set_board_metadata": rule_set_board_metadata,
        "focus_name": focus_name,
        "focus_item": focus_item,
        "focus_rule_set": (
            focus_rule_set.model_dump(mode="json") if focus_rule_set else None
        ),
        "focus_rule_groups": (
            _rule_focus_groups(session, focus_rule_set, entity_fields_map)
            if focus_rule_set
            else []
        ),
        "focus_source_of_truth_version": str(session.project_revision),
        "cross_entity_prerequisite_targets": cross_entity_prerequisite_targets,
        "rule_suggestion_badges": rule_suggestion_badges,
        "generated_id_warnings": generated_id_warnings,
        "likely_generated_id_fields": likely_generated_id_fields,
        "back_route": back_route,
        "shell_rail_default": shell_rail_default,
        **nav,
    })


@router.get("/ks/drawer", response_class=JSONResponse)
async def step6_ks_drawer(
    request: Request,
    scope: str = Query("rules"),
    entity: str = Query(""),
):
    session = get_current_session(request)
    if session.app_archetype != "crud":
        return JSONResponse(
            {
                "ok": False,
                "warning": "Step 6 Knowledge Assist drawers are available for CRUD projects only.",
            },
            status_code=400,
        )
    if scope not in {"rules", "cross_entity_rules"}:
        return JSONResponse(
            {
                "ok": False,
                "warning": f"Unsupported Step 6 Knowledge Assist drawer scope '{scope}'.",
            },
            status_code=400,
        )

    canonical_entities = _selected_canonical_entities(session)
    normalized_entity = entity.strip()
    title = "Rule Suggestions" if scope == "rules" else "Cross-Entity Rule Suggestions"
    if normalized_entity not in canonical_entities:
        return JSONResponse(
            {
                "ok": True,
                "scope": scope,
                "title": title,
                "entity": normalized_entity or None,
                "selected_entities": canonical_entities,
                "scopes": [],
                "warnings": [],
                "empty": True,
            }
        )

    workspace_before = workspace_session_marker(session)
    drawer = (
        assist_service.fetch_rule_suggestion_drawer(session, entity=normalized_entity)
        if scope == "rules"
        else assist_service.fetch_suggestion_drawer(
            session,
            scope=scope,
            entity=normalized_entity,
        )
    )
    save_current_session_if_workspace_changed(request, session, workspace_before)
    payload = drawer.to_dict() if drawer else {
        "ok": True,
        "scope": scope,
        "title": title,
        "entity": normalized_entity,
        "scopes": [],
        "warnings": [],
        "empty": True,
    }
    payload["selected_entities"] = canonical_entities
    payload["review_url"] = "/rules/ks/review"
    return JSONResponse(payload)


@router.post("/ks/review", response_class=JSONResponse)
async def step6_ks_review(request: Request):
    session = get_current_session(request)
    if session.app_archetype != "crud":
        return JSONResponse(
            {"ok": False, "errors": ["Step 6 rule suggestion review is available for CRUD projects only."]},
            status_code=400,
        )
    if not session.capabilities.knowledge_assist_enabled:
        return JSONResponse(
            {"ok": False, "errors": ["Knowledge Assist is off; no rule suggestion decisions were submitted."]},
            status_code=400,
        )

    body = await request.json()
    decisions, errors = _normalize_step6_review_decisions(body.get("decisions"))
    if errors:
        return JSONResponse({"ok": False, "errors": errors}, status_code=400)
    if not decisions:
        return JSONResponse(
            {
                "ok": True,
                "skipped": True,
                "message": "No staged rule suggestion decisions to save.",
                "outcomes": [],
                "saved_count": 0,
                "failed_count": 0,
                "applied_count": 0,
                "warnings": [],
            }
        )

    candidate_rules: dict[str, list[RuleEntry]] = {}
    candidate_paths: dict[str, str] = {}
    preflight_warnings: list[str] = []
    preflight_errors: list[str] = []
    preview_rules: dict[str, EntityRules] = {
        entity_rules.entity_name: EntityRules(
            entity_name=entity_rules.entity_name,
            rules=[rule.model_copy(deep=True) for rule in entity_rules.rules],
            file_path=entity_rules.file_path,
        )
        for entity_rules in session.entity_rules
    }

    for decision in decisions:
        status = decision["status"]
        suggestion_id = decision["suggestion_id"]
        entity_name = decision["entity"]
        payload = _latest_payload(decision)
        preview_entity_rules = preview_rules.setdefault(
            entity_name,
            EntityRules(entity_name=entity_name, rules=[], file_path=f"rules/{_slug(entity_name)}-business-rules.yaml"),
        )

        rules: list[RuleEntry] = []
        warning: str | None = None
        if status in {"accepted", "edited"}:
            _canonicalize_rule_payload_fields(session, entity_name, payload)
            if decision["suggestion_type"] == "rule":
                rule, warning = _rule_from_rule_payload(payload)
                rules = [rule] if rule is not None else []
            else:
                rules, warning = _rules_from_cross_entity_payload(
                    payload,
                    current_rules=preview_entity_rules,
                )

            if warning:
                allowed_review_only = (
                    "manual authoring" in warning
                    or warning.startswith("Review saved, but rule was not applied")
                )
                if allowed_review_only:
                    preflight_warnings.append(f"{suggestion_id}: {warning}")
                else:
                    preflight_errors.append(f"{suggestion_id}: {warning}")
                    continue

            stamped_rules = [
                _stamp_ka_rule(
                    rule,
                    suggestion_id=suggestion_id,
                    suggestion_type=decision["suggestion_type"],
                    status=status,
                )
                for rule in rules
            ]
            for stamped_rule in stamped_rules:
                _append_rule_if_missing(preview_entity_rules, stamped_rule)
            rules = stamped_rules

        candidate_rules[suggestion_id] = rules
        if status in {"accepted", "edited"} and rules:
            candidate_paths[suggestion_id] = _manifest_path_for_rule(entity_name, rules[-1], suggestion_id)
        else:
            candidate_paths[suggestion_id] = decision["manifest_path"] or f"rules.{entity_name}.{suggestion_id}"

    if preflight_errors:
        return JSONResponse({"ok": False, "errors": preflight_errors}, status_code=400)

    ks_result = assist_service.submit_rule_suggestion_decisions(
        session,
        decisions=[_ks_review_payload(decision) for decision in decisions],
    )
    if ks_result is None:
        return JSONResponse(
            {
                "ok": True,
                "degraded": True,
                "message": "Rule suggestion review could not be saved. Manual Step 6 authoring remains available.",
                "outcomes": [],
                "saved_count": 0,
                "failed_count": len(decisions),
                "applied_count": 0,
                "warnings": preflight_warnings,
            }
        )

    successful_ids = _successful_outcome_ids(ks_result, decisions)
    outcomes: list[dict[str, Any]] = []
    applied_count = 0
    warnings = list(preflight_warnings)

    for decision in decisions:
        suggestion_id = decision["suggestion_id"]
        success = suggestion_id in successful_ids
        applied = False
        if success:
            manifest_path = candidate_paths[suggestion_id]
            rules = candidate_rules.get(suggestion_id, [])
            evidence_backed = False
            if decision["status"] in {"accepted", "edited"} and rules:
                entity_rules = _entity_rules_for(session, decision["entity"])
                applied_rules = 0
                for rule in rules:
                    if _append_rule_if_missing(entity_rules, rule):
                        applied_rules += 1
                if applied_rules:
                    applied = True
                    applied_count += applied_rules
                    evidence_backed = True
                else:
                    duplicate = all(
                        any(_rule_identity(existing) == _rule_identity(rule) for existing in entity_rules.rules)
                        for rule in rules
                    )
                    evidence_backed = duplicate
                    warnings.append(f"{suggestion_id}: matching rule already exists; review was recorded without duplicating it.")
            elif decision["status"] in {"accepted", "edited"}:
                _remove_evidence_link(session, suggestion_id=suggestion_id)
            elif decision["status"] == "rejected":
                retained_count = _mark_ka_rule_review_status(
                    session,
                    suggestion_id=suggestion_id,
                    status="rejected",
                )
                if retained_count:
                    warnings.append(
                        f"{suggestion_id}: Reject records review only; existing generated rule remains until manually removed."
                    )
            _record_step6_review(
                session,
                decision,
                manifest_path=manifest_path,
                evidence_backed=evidence_backed,
            )

        outcomes.append(
            {
                "suggestion_id": suggestion_id,
                "status": decision["status"],
                "success": success,
                "applied": applied,
                "manifest_path": candidate_paths.get(suggestion_id),
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
                f"Saved {saved_count} rule suggestion decision(s); applied {applied_count} rule(s)."
            ),
            "outcomes": outcomes,
            "saved_count": saved_count,
            "failed_count": failed_count,
            "applied_count": applied_count,
            "warnings": warnings,
        }
    )


def _raw_cross_entity_targets(raw_rules: list[dict[str, Any]]) -> dict[str, str]:
    targets: dict[str, str] = {}
    for raw_rule in raw_rules:
        if (raw_rule.get("type") or "").strip() != "cross-entity-exists":
            continue
        fk_field = (raw_rule.get("field") or "").strip()
        target_entity = (raw_rule.get("target_entity") or "").strip()
        if fk_field and target_entity:
            targets[fk_field] = target_entity
    return targets


def _resolve_cross_entity_target(
    field: str,
    requested_target: str | None,
    prerequisite_targets: dict[str, str | set[str]],
) -> str | None:
    available = prerequisite_targets.get(field)
    if isinstance(available, str):
        return available
    if not available:
        return None
    if requested_target and requested_target in available:
        return requested_target
    if len(available) == 1:
        return next(iter(available))
    return None


def _build_one_entity_rules(
    raw: dict[str, Any],
    *,
    session: ProjectSession,
    entity_fields_lookup: dict[str, dict[str, dict[str, Any]]],
    prerequisite_targets: dict[str, str | set[str]] | None = None,
) -> tuple[EntityRules | None, list[str]]:
    """Build one rule-set through the validation shared by bulk and save-one."""
    entity_name = str(raw.get("entity_name") or "").strip()
    if not entity_name:
        return None, []

    source_fields = entity_fields_lookup.get(entity_name, {})
    raw_rules = raw.get("rules", [])
    if not isinstance(raw_rules, list):
        return None, [f"{entity_name}: rules must be a list."]
    cross_entity_targets = prerequisite_targets or _raw_cross_entity_targets(raw_rules)
    validation_errors: list[str] = []
    rules: list[RuleEntry] = []
    for r in raw_rules:
        if not isinstance(r, dict):
            validation_errors.append(f"{entity_name}: each rule must be an object.")
            continue
        field = r.get("field", "").strip()
        rule_type = r.get("type", "").strip()
        if not rule_type:
            continue
        if not field and rule_type in {
            "cross-entity-field-check",
            "cross-entity-field-compare",
            "cross-entity-field-in",
        }:
            validation_errors.append(
                f"{entity_name}: {rule_type} requires an FK field."
            )
            continue
        if not field:
            continue
        operator = (r.get("operator") or "").strip() or None
        compare_to_field = (r.get("compare_to_field") or "").strip() or None
        target_field = _normalize_optional_text(r.get("target_field"))
        source_field = _normalize_optional_text(r.get("source_field"))
        expected_value = _normalize_optional_text(r.get("expected_value"))
        error_message = _normalize_optional_text(r.get("error_message"))
        values = [str(v).strip() for v in (r.get("values", []) or []) if str(v).strip()]
        target_entity = _normalize_optional_text(r.get("target_entity"))

        if rule_type == "field-comparison":
            if not operator:
                validation_errors.append(
                    f"{entity_name}.{field}: field-comparison requires an operator."
                )
                continue
            if operator not in _FIELD_COMPARISON_OPERATORS:
                validation_errors.append(
                    f"{entity_name}.{field}: field-comparison operator must be one of {sorted(_FIELD_COMPARISON_OPERATORS)}."
                )
                continue
            if not compare_to_field:
                validation_errors.append(
                    f"{entity_name}.{field}: field-comparison requires a compare-to-field."
                )
                continue

        if rule_type in {
            "cross-entity-field-check",
            "cross-entity-field-compare",
            "cross-entity-field-in",
        }:
            if field not in source_fields:
                validation_errors.append(
                    f"{entity_name}.{field}: field must exist on the source entity."
                )
                continue

            target_entity = _resolve_cross_entity_target(
                field,
                target_entity,
                cross_entity_targets,
            )
            if not target_entity:
                validation_errors.append(
                    f"{entity_name}.{field}: add a cross-entity-exists rule for this field first."
                )
                continue

            target_fields = entity_fields_lookup.get(target_entity)
            if not target_fields:
                validation_errors.append(
                    f"{entity_name}.{field}: could not resolve target entity '{target_entity}'."
                )
                continue

            if not target_field:
                validation_errors.append(
                    f"{entity_name}.{field}: {rule_type} requires a target-field."
                )
                continue

            target_field_meta = target_fields.get(target_field)
            if not target_field_meta:
                validation_errors.append(
                    f"{entity_name}.{field}: target-field '{target_field}' must exist on {target_entity}."
                )
                continue

            if rule_type == "cross-entity-field-check":
                if operator not in _CROSS_ENTITY_FIELD_CHECK_OPERATORS:
                    validation_errors.append(
                        f"{entity_name}.{field}: cross-entity-field-check operator must be one of {sorted(_CROSS_ENTITY_FIELD_CHECK_OPERATORS)}."
                    )
                    continue
                if not expected_value:
                    validation_errors.append(
                        f"{entity_name}.{field}: cross-entity-field-check requires an expected-value."
                    )
                    continue
                if not _supports_field_check_target(target_field_meta):
                    validation_errors.append(
                        f"{entity_name}.{field}: cross-entity-field-check target-field must be string, numeric, boolean, date, or datetime."
                    )
                    continue
                if not _expected_value_matches_field_type(target_field_meta, expected_value):
                    validation_errors.append(
                        f"{entity_name}.{field}: cross-entity-field-check expected-value is incompatible with target-field '{target_field}'."
                    )
                    continue

            elif rule_type == "cross-entity-field-compare":
                if operator not in _CROSS_ENTITY_FIELD_COMPARE_OPERATORS:
                    validation_errors.append(
                        f"{entity_name}.{field}: cross-entity-field-compare operator must be one of {sorted(_CROSS_ENTITY_FIELD_COMPARE_OPERATORS)}."
                    )
                    continue
                if not source_field:
                    validation_errors.append(
                        f"{entity_name}.{field}: cross-entity-field-compare requires a source-field."
                    )
                    continue
                source_field_meta = source_fields.get(source_field)
                if not source_field_meta:
                    validation_errors.append(
                        f"{entity_name}.{field}: source-field '{source_field}' must exist on the source entity."
                    )
                    continue
                if not _is_numeric_field(target_field_meta) or not _is_numeric_field(source_field_meta):
                    validation_errors.append(
                        f"{entity_name}.{field}: cross-entity-field-compare requires numeric source-field and target-field values."
                    )
                    continue

            elif rule_type == "cross-entity-field-in":
                if not values:
                    validation_errors.append(
                        f"{entity_name}.{field}: cross-entity-field-in requires at least one allowed value."
                    )
                    continue
                if not _is_string_like_field(target_field_meta):
                    validation_errors.append(
                        f"{entity_name}.{field}: cross-entity-field-in target-field must be string or enum-like."
                    )
                    continue

        entry = RuleEntry(
            field=field,
            type=rule_type,
            values=values,
            value=(
                _normalize_pattern_rule_value(r.get("value"))
                if rule_type == "pattern"
                else (r.get("value") or None)
            ),
            target_entity=target_entity,
            operator=operator,
            compare_to_field=compare_to_field,
            target_field=target_field,
            source_field=source_field,
            expected_value=expected_value,
            error_message=error_message,
            suggestion_id=_normalize_optional_text(r.get("suggestion_id")),
            suggestion_type=_normalize_optional_text(r.get("suggestion_type")),
            applied_by=_normalize_optional_text(r.get("applied_by")) or "manual",
            applied_at=_normalize_optional_text(r.get("applied_at")),
            generated_by_ka=_coerce_bool(r.get("generated_by_ka")),
            ka_review_status=_normalize_optional_text(r.get("ka_review_status")),
        )
        entry = _classify_saved_ka_validation_rule(session, entity_name, entry)
        rules.append(entry)

    if validation_errors:
        return None, validation_errors
    return (
        EntityRules(
            entity_name=entity_name,
            rules=rules,
            file_path=_default_rule_file_path(entity_name),
        ),
        [],
    )


@router.post("/save", response_class=JSONResponse)
async def step6_save(request: Request):
    """
    Body: {
      entity_rules: [
        {
          entity_name: str,
          rules: [
            {field, type, values?: [], value?: str, target_entity?: str}
          ]
        }
      ],
      legacy_notes: str,
      legacy_slug: str
    }
    """
    body = await request.json()
    session = get_current_session(request)
    validation_errors: list[str] = []
    entity_fields_lookup = _entity_field_lookup(session)

    entity_rules: list[EntityRules] = []
    for raw in body.get("entity_rules", []):
        built, errors = _build_one_entity_rules(
            raw,
            session=session,
            entity_fields_lookup=entity_fields_lookup,
        )
        validation_errors.extend(errors)
        if built is not None:
            entity_rules.append(built)

    if validation_errors:
        return JSONResponse({"ok": False, "errors": validation_errors}, status_code=400)

    session.entity_rules = entity_rules
    submitted_entity_names = [entity_rules.entity_name for entity_rules in entity_rules]
    reviewed_entities = list(dict.fromkeys(submitted_entity_names))
    session.auto_rule_merge_completed_entities = reviewed_entities
    # body.get(..., "") only uses the default when the key is absent.
    # JS sends null (not omits) for empty fields, so we use `or ""` to
    # coerce None → "" before calling .strip().
    session.legacy_notes = (body.get("legacy_notes") or "").strip() or None
    raw_slug = (body.get("legacy_slug") or "").strip()
    session.legacy_slug = _slug(raw_slug) if raw_slug else _slug(session.bounded_context or "app")
    save_current_session(request, session)
    return JSONResponse({"ok": True})


def _reload_session_for_save_one(
    request: Request,
    cached_session: ProjectSession,
) -> ProjectSession:
    if not cached_session.session_id:
        return cached_session
    store = getattr(request.state, "session_store", None)
    if store is None:
        return cached_session
    session = store.load(cached_session.session_id)
    request.state.studio_session = session
    return session


def _save_one_prerequisite_targets(
    session: ProjectSession,
    raw_rules: list[dict[str, Any]],
    *,
    entity_name: str,
    names_being_replaced: set[str],
) -> dict[str, set[str]]:
    persisted = [
        entity_rules
        for entity_rules in session.entity_rules
        if entity_rules.entity_name not in names_being_replaced
    ]
    session_targets = readiness_view.rule_set_prerequisite_targets(persisted)
    targets = {
        field: set(available)
        for (owner, field), available in session_targets.items()
        if owner == entity_name
    }
    for field, target in _raw_cross_entity_targets(raw_rules).items():
        targets.setdefault(field, set()).add(target)
    return targets


def _replace_rule_set(
    entity_rule_sets: list[EntityRules],
    saved: EntityRules,
    *,
    original_name: str | None,
) -> list[EntityRules]:
    replacement_name = original_name or saved.entity_name
    replacement_index = next(
        (
            index
            for index, entity_rules in enumerate(entity_rule_sets)
            if entity_rules.entity_name == replacement_name
        ),
        None,
    )
    result: list[EntityRules] = []
    inserted = False
    for index, entity_rules in enumerate(entity_rule_sets):
        if index == replacement_index:
            result.append(saved)
            inserted = True
            continue
        if entity_rules.entity_name in {replacement_name, saved.entity_name}:
            continue
        result.append(entity_rules)
    if not inserted:
        result.append(saved)
    return result


def _preserve_rule_file_path(
    saved: EntityRules,
    existing: EntityRules | None,
) -> None:
    """Keep omitted server-owned paths, including ``None`` from older projects."""
    if existing is None:
        return
    existing_default = _default_rule_file_path(existing.entity_name)
    if existing.entity_name == saved.entity_name or existing.file_path != existing_default:
        saved.file_path = existing.file_path


def _rule_validation_blockers(errors: list[str]) -> list[dict[str, str | None]]:
    blockers: list[dict[str, str | None]] = []
    for error in errors:
        field_match = re.match(r"^[^.]+\.([^:]+):", error)
        field_ref = field_match.group(1).strip() if field_match else None
        prerequisite_missing = "add a cross-entity-exists rule" in error.lower()
        section_ref = "cross-entity" if prerequisite_missing else "rules"
        blockers.append(
            {
                "code": (
                    "cross-entity-prerequisite-missing"
                    if prerequisite_missing
                    else f"invalid-{_slug(error)[:64] or 'rule'}"
                ),
                "label": error,
                "field_ref": field_ref,
                "section_ref": section_ref,
            }
        )
    return blockers


def _rule_conflict_advisories(session: ProjectSession) -> dict[str, Any]:
    represented_rule_sets = _rule_sets_for_view(
        session,
        selected_canonical_entities(session),
    )
    return assist_service.get_advisory_conflicts(
        session,
        canonical_entities=[
            entity_rules.entity_name for entity_rules in represented_rule_sets
        ],
    )


def _readiness_payload(
    session: ProjectSession,
    entity_name: str,
    *,
    conflict_advisories: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    try:
        return asdict(
            readiness_view.rule_set_item(
                session,
                entity_name,
                conflict_advisories=conflict_advisories,
            )
        )
    except KeyError:
        return None


def _rule_set_board_metadata(
    session: ProjectSession,
    entity_rules: EntityRules,
    *,
    conflict_advisories: dict[str, Any] | None = None,
) -> dict[str, Any]:
    readiness = readiness_view.rule_set_item(
        session,
        entity_rules.entity_name,
        conflict_advisories=conflict_advisories,
    )
    provenance = {"spec_derived": 0, "manual": 0, "ka_applied": 0}
    for rule in entity_rules.rules:
        if rule.generated_by_ka:
            provenance["ka_applied"] += 1
        elif rule.applied_by == "openapi-spec":
            provenance["spec_derived"] += 1
        else:
            provenance["manual"] += 1
    coverage = readiness.coverage[0] if readiness.coverage else None
    return {
        "rule_count": len(entity_rules.rules),
        "file_path": entity_rules.file_path,
        "fields_complete": coverage.complete if coverage else 0,
        "fields_total": coverage.total if coverage else 0,
        "advisory_count": len(readiness.warnings),
        **provenance,
    }


@router.post("/save-one", response_class=JSONResponse)
async def save_one_rule_set(request: Request):
    body = await request.json()
    cached_session = get_current_session(request)
    with _SAVE_ONE_MUTATION_LOCK:
        session = _reload_session_for_save_one(request, cached_session)
        return _save_one_rule_set_body(request, body, session)


def _save_one_rule_set_body(
    request: Request,
    body: dict[str, Any],
    session: ProjectSession,
) -> JSONResponse:
    raw = body.get("item")
    if not isinstance(raw, dict):
        blockers = _rule_validation_blockers(["A rule-set item is required."])
        return JSONResponse({"ok": False, "blockers": blockers}, status_code=400)

    entity_name = _normalize_optional_text(raw.get("entity_name")) or ""
    original_name = _normalize_optional_text(body.get("original_name"))
    supplied_version = _normalize_optional_text(body.get("source_of_truth_version"))
    current_version = str(session.project_revision)
    if supplied_version is not None and supplied_version != current_version:
        fresh_name = original_name or entity_name
        fresh = next(
            (
                entity_rules
                for entity_rules in session.entity_rules
                if entity_rules.entity_name == fresh_name
            ),
            None,
        )
        conflict_advisories = _rule_conflict_advisories(session)
        return JSONResponse(
            {
                "ok": False,
                "error": "This rule-set changed after the editor was opened.",
                "item": fresh.model_dump(mode="json") if fresh else None,
                "readiness": (
                    _readiness_payload(
                        session,
                        fresh.entity_name,
                        conflict_advisories=conflict_advisories,
                    )
                    if fresh
                    else None
                ),
                "recovery": "review-current-item" if fresh else "reload-current-list",
                "current_items": [
                    {"name": entity_rules.entity_name, "type": "rule_set"}
                    for entity_rules in session.entity_rules
                ],
                "source_of_truth_version": current_version,
            },
            status_code=409,
        )

    if not entity_name:
        blockers = _rule_validation_blockers(["Rule-set entity name is required."])
        return JSONResponse({"ok": False, "blockers": blockers}, status_code=400)
    duplicate_name = any(
        entity_rules.entity_name == entity_name for entity_rules in session.entity_rules
    )
    if (original_name is None and duplicate_name) or (
        original_name and entity_name != original_name and duplicate_name
    ):
        return JSONResponse(
            {
                "ok": False,
                "blockers": [
                    {
                        "code": "duplicate-name",
                        "label": f"A rule-set for '{entity_name}' already exists.",
                        "field_ref": "entity_name",
                        "section_ref": "rules",
                    }
                ],
            },
            status_code=400,
        )

    raw_rules = raw.get("rules", [])
    if not isinstance(raw_rules, list):
        blockers = _rule_validation_blockers([f"{entity_name}: rules must be a list."])
        return JSONResponse({"ok": False, "blockers": blockers}, status_code=400)
    prerequisite_targets = _save_one_prerequisite_targets(
        session,
        raw_rules,
        entity_name=entity_name,
        names_being_replaced={name for name in {original_name, entity_name} if name},
    )
    saved, errors = _build_one_entity_rules(
        raw,
        session=session,
        entity_fields_lookup=_entity_field_lookup(session),
        prerequisite_targets=prerequisite_targets,
    )
    if errors or saved is None:
        blockers = _rule_validation_blockers(errors or ["The rule-set could not be saved."])
        return JSONResponse(
            {"ok": False, "errors": errors, "blockers": blockers},
            status_code=400,
        )

    existing_name = original_name or entity_name
    existing = next(
        (
            entity_rules
            for entity_rules in session.entity_rules
            if entity_rules.entity_name == existing_name
        ),
        None,
    )
    _preserve_rule_file_path(saved, existing)

    before = [entity_rules.model_dump(mode="json") for entity_rules in session.entity_rules]
    empty_selected_placeholder = (
        existing is None
        and not saved.rules
        and saved.entity_name in selected_canonical_entities(session)
    )
    if empty_selected_placeholder:
        saved.file_path = None
        updated = list(session.entity_rules)
    else:
        updated = _replace_rule_set(
            session.entity_rules,
            saved,
            original_name=original_name,
        )
    after = [entity_rules.model_dump(mode="json") for entity_rules in updated]
    if after != before:
        session.entity_rules = updated
        reviewed = list(session.auto_rule_merge_completed_entities)
        for name in {original_name, saved.entity_name}:
            if name and name in reviewed:
                reviewed.remove(name)
        reviewed.append(saved.entity_name)
        session.auto_rule_merge_completed_entities = list(dict.fromkeys(reviewed))
        session.project_revision = max(1, session.project_revision) + 1
        save_current_session(request, session)
        current_version = str(session.project_revision)

    workspace_before = workspace_session_marker(session)
    conflict_advisories = _rule_conflict_advisories(session)
    save_current_session_if_workspace_changed(request, session, workspace_before)
    readiness = _readiness_payload(
        session,
        saved.entity_name,
        conflict_advisories=conflict_advisories,
    )
    if readiness is None:
        raise RuntimeError(f"Saved rule-set '{saved.entity_name}' has no readiness item.")
    counts = readiness_view.step_counts(session)
    all_readiness = readiness_view.rule_set_items(
        session,
        conflict_advisories=conflict_advisories,
    )
    represented_rule_sets = _rule_sets_for_view(
        session,
        selected_canonical_entities(session),
    )
    affected_readiness = [
        asdict(readiness_item)
        for readiness_item in all_readiness
        if readiness_item.display_name != saved.entity_name
    ]
    affected_board_metadata = {
        entity_rules.entity_name: _rule_set_board_metadata(
            session,
            entity_rules,
            conflict_advisories=conflict_advisories,
        )
        for entity_rules in represented_rule_sets
        if entity_rules.entity_name != saved.entity_name
    }
    rail = [
        {"step": step, "count": values["count"], "attention": values["attention"]}
        for step, values in sorted(counts.items())
    ]
    return JSONResponse(
        {
            "ok": True,
            "item": saved.model_dump(mode="json"),
            "readiness": readiness,
            "board_metadata": _rule_set_board_metadata(
                session,
                saved,
                conflict_advisories=conflict_advisories,
            ),
            "affected_readiness": affected_readiness,
            "affected_board_metadata": affected_board_metadata,
            "step_counts": counts,
            "rail": rail,
            "warnings": readiness["warnings"],
            "source_of_truth_version": current_version,
        }
    )


@router.post("/legacy-notes/save", response_class=JSONResponse)
async def save_legacy_notes(request: Request):
    body = await request.json()
    cached_session = get_current_session(request)
    with _SAVE_ONE_MUTATION_LOCK:
        session = _reload_session_for_save_one(request, cached_session)
        supplied_version = _normalize_optional_text(body.get("source_of_truth_version"))
        current_version = str(session.project_revision)
        if supplied_version is not None and supplied_version != current_version:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "Legacy notes changed after this page was opened.",
                    "legacy_notes": session.legacy_notes,
                    "legacy_slug": session.legacy_slug,
                    "source_of_truth_version": current_version,
                },
                status_code=409,
            )

        raw_notes = body.get("legacy_notes")
        raw_slug = body.get("legacy_slug")
        if raw_notes is not None and not isinstance(raw_notes, str):
            return JSONResponse(
                {"ok": False, "error": "Legacy notes must be text."},
                status_code=400,
            )
        if raw_slug is not None and not isinstance(raw_slug, str):
            return JSONResponse(
                {"ok": False, "error": "Legacy notes slug must be text."},
                status_code=400,
            )

        legacy_notes = (raw_notes or "").strip() or None
        normalized_slug = (raw_slug or "").strip()
        legacy_slug = (
            _slug(normalized_slug)
            if normalized_slug
            else _slug(session.bounded_context or "app")
        )
        if (legacy_notes, legacy_slug) != (session.legacy_notes, session.legacy_slug):
            session.legacy_notes = legacy_notes
            session.legacy_slug = legacy_slug
            session.project_revision = max(1, session.project_revision) + 1
            save_current_session(request, session)
            current_version = str(session.project_revision)

        return JSONResponse(
            {
                "ok": True,
                "legacy_notes": session.legacy_notes,
                "legacy_slug": session.legacy_slug,
                "source_of_truth_version": current_version,
            }
        )


@router.get("/next")
async def step6_next():
    return RedirectResponse("/review", status_code=303)
