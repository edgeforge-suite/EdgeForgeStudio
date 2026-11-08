"""Manual identity-role review helpers for CRUD entity fields."""

from __future__ import annotations

import json
import re
from typing import Any, get_args

from app.models.project import (
    ClassifiedEntity,
    IdentityRoleDecision,
    IdentityRoleValue,
    ProjectSession,
)


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _date_label(value: Any, *, fallback: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return text[:10]
    return text


IDENTITY_ROLE_BEHAVIOR: dict[str, dict[str, str | bool]] = {
    "persistence_id": {
        "label": "persistence_id",
        "meaning": "Persistence row identity for this entity.",
        "current_engine_behavior": (
            "Affects generated persistence identity: Java @Id, DB primary key, and repository identity."
        ),
        "export_behavior": "Exports to Engine identity_overrides.",
        "api_behavior": "May affect generated API ID behavior where CRUD routes use the persistence ID.",
        "evidence_trail_behavior": "Not an Evidence Trail v1.1 entry.",
        "future_policy_note": "Current Engine-supported role.",
        "impact_badge": "Engine-active",
        "affects_engine": True,
    },
    "parent_reference": {
        "label": "parent_reference",
        "meaning": "Reference to another entity's identity, not this entity's row identity.",
        "current_engine_behavior": "Exported as metadata only; no generated app behavior yet.",
        "export_behavior": "Exports to identity_roles with mode: metadata_only.",
        "api_behavior": "Does not change Java, DDL, rules, APIs, or runtime behavior.",
        "evidence_trail_behavior": "Not an Evidence Trail v1.1 entry.",
        "future_policy_note": "Future behavior requires explicit relationship or rule policy.",
        "impact_badge": "Metadata-only",
        "affects_engine": False,
    },
    "business_key": {
        "label": "business_key",
        "meaning": "Natural/domain identifier such as account number or order reference.",
        "current_engine_behavior": "Exported as metadata only; no generated app behavior yet.",
        "export_behavior": "Exports to identity_roles with mode: metadata_only.",
        "api_behavior": "Does not change Java, DDL, rules, APIs, or runtime behavior.",
        "evidence_trail_behavior": "Not an Evidence Trail v1.1 entry.",
        "future_policy_note": "Future behavior requires explicit uniqueness or lookup policy.",
        "impact_badge": "Metadata-only",
        "affects_engine": False,
    },
    "event_id": {
        "label": "event_id",
        "meaning": "Upstream event or transaction identifier.",
        "current_engine_behavior": "Exported as metadata only; no generated app behavior yet.",
        "export_behavior": "Exports to identity_roles with mode: metadata_only.",
        "api_behavior": "Does not change Java, DDL, rules, APIs, or runtime behavior.",
        "evidence_trail_behavior": "Not an Evidence Trail v1.1 entry.",
        "future_policy_note": "Future behavior requires explicit event/deduplication policy.",
        "impact_badge": "Metadata-only",
        "affects_engine": False,
    },
    "idempotency_key": {
        "label": "idempotency_key",
        "meaning": "Replay/duplicate protection key for an operation.",
        "current_engine_behavior": "Exported as metadata only; no generated app behavior yet.",
        "export_behavior": "Exports to identity_roles with mode: metadata_only.",
        "api_behavior": "Does not change Java, DDL, rules, APIs, or runtime behavior.",
        "evidence_trail_behavior": "Not an Evidence Trail v1.1 entry.",
        "future_policy_note": "Future behavior requires explicit operation, retention, replay, and storage policy.",
        "impact_badge": "Metadata-only",
        "affects_engine": False,
    },
    "correlation_id": {
        "label": "correlation_id",
        "meaning": "Workflow, request, or trace correlation identifier.",
        "current_engine_behavior": "Exported as metadata only; no generated app behavior yet.",
        "export_behavior": "Exports to identity_roles with mode: metadata_only.",
        "api_behavior": "Does not change Java, DDL, rules, APIs, or runtime behavior.",
        "evidence_trail_behavior": "Not an Evidence Trail v1.1 entry.",
        "future_policy_note": "Future behavior requires explicit tracing/logging policy.",
        "impact_badge": "Metadata-only",
        "affects_engine": False,
    },
    "external_reference": {
        "label": "external_reference",
        "meaning": "Identifier assigned by an external provider or integration partner.",
        "current_engine_behavior": "Exported as metadata only; no generated app behavior yet.",
        "export_behavior": "Exports to identity_roles with mode: metadata_only.",
        "api_behavior": "Does not change Java, DDL, rules, APIs, or runtime behavior.",
        "evidence_trail_behavior": "Not an Evidence Trail v1.1 entry.",
        "future_policy_note": "Future behavior requires explicit external-reference lookup/index policy.",
        "impact_badge": "Metadata-only",
        "affects_engine": False,
    },
}
IDENTITY_ROLE_HELP: dict[str, str] = {
    role: f"{behavior['export_behavior']} {behavior['current_engine_behavior']}"
    for role, behavior in IDENTITY_ROLE_BEHAVIOR.items()
}
IDENTITY_ROLE_VALUES = frozenset(get_args(IdentityRoleValue))
if IDENTITY_ROLE_VALUES != frozenset(IDENTITY_ROLE_BEHAVIOR):
    raise RuntimeError("IDENTITY_ROLE_BEHAVIOR must describe every IdentityRoleValue.")
METADATA_ONLY_IDENTITY_ROLES = tuple(
    role for role in IDENTITY_ROLE_BEHAVIOR if role != "persistence_id"
)
IDENTITY_ROLE_OPTIONS = [
    {
        "value": "",
        "label": "No identity role",
        "help": "Clears any reviewed identity role metadata for this field.",
        "meaning": "No reviewed identity role for this field.",
        "current_engine_behavior": "No identity-role behavior is generated.",
        "export_behavior": "No identity-role export.",
        "api_behavior": "No generated API behavior.",
        "evidence_trail_behavior": "Not an Evidence Trail v1.1 entry.",
        "future_policy_note": "Choose a role only when the field's identity intent is known.",
        "impact_badge": "No role",
        "exports": False,
        "affects_engine": False,
    },
    *[
        {
            "value": role,
            "label": str(behavior["label"]),
            "help": IDENTITY_ROLE_HELP[role],
            "meaning": str(behavior["meaning"]),
            "current_engine_behavior": str(behavior["current_engine_behavior"]),
            "export_behavior": str(behavior["export_behavior"]),
            "api_behavior": str(behavior["api_behavior"]),
            "evidence_trail_behavior": str(behavior["evidence_trail_behavior"]),
            "future_policy_note": str(behavior["future_policy_note"]),
            "impact_badge": str(behavior["impact_badge"]),
            "exports": True,
            "affects_engine": bool(behavior["affects_engine"]),
        }
        for role, behavior in IDENTITY_ROLE_BEHAVIOR.items()
    ],
]


def identity_role_behavior(role: str) -> dict[str, str | bool]:
    return IDENTITY_ROLE_BEHAVIOR.get(role, {})


def identity_role_behavior_rows() -> list[dict[str, str | bool]]:
    return [
        {"value": role, **behavior}
        for role, behavior in IDENTITY_ROLE_BEHAVIOR.items()
    ]

_EXACT_WRAPPER_FIELD_KEYS = {
    _key(value)
    for value in (
        "currentPage",
        "pageSize",
        "totalElements",
        "totalPages",
        "totalItems",
        "links",
        "meta",
    )
}
_GENERIC_WRAPPER_FIELD_KEYS = {
    _key(value)
    for value in (
        "content",
        "size",
        "number",
        "sort",
        "first",
        "last",
        "empty",
        "pageable",
        "numberOfElements",
    )
}
_PAGINATION_METADATA_KEYS = _EXACT_WRAPPER_FIELD_KEYS | (_GENERIC_WRAPPER_FIELD_KEYS - {_key("content")})


def selected_canonical_entities(session: ProjectSession) -> list[str]:
    selected_names = set(session.selected_entity_names)
    seen: set[str] = set()
    names: list[str] = []
    for entity in session.classified_entities:
        if entity.name not in selected_names or entity.classification != "entity":
            continue
        canonical = entity.display_name()
        if canonical in seen:
            continue
        seen.add(canonical)
        names.append(canonical)
    return names


def authoritative_entity(session: ProjectSession, canonical_entity: str) -> ClassifiedEntity | None:
    selected_names = set(session.selected_entity_names)
    for entity in session.classified_entities:
        if (
            entity.name in selected_names
            and entity.classification == "entity"
            and entity.display_name() == canonical_entity
        ):
            return entity
    return None


def _sample_wrapper_keys(content: str | None) -> set[str]:
    if not content:
        return set()
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return set()
    if not isinstance(parsed, dict):
        return set()
    keys = {_key(key) for key in parsed}
    if _key("content") not in keys:
        return set()
    content_value = next((value for key, value in parsed.items() if _key(key) == _key("content")), None)
    if not isinstance(content_value, list):
        return set()
    if not (keys & _PAGINATION_METADATA_KEYS):
        return set()
    return keys & (_GENERIC_WRAPPER_FIELD_KEYS | _EXACT_WRAPPER_FIELD_KEYS)


def wrapper_field_keys_for_entity(session: ProjectSession, canonical_entity: str) -> set[str]:
    wrapper_keys: set[str] = set()
    for iface in session.upstream_interfaces:
        if iface.entity_name != canonical_entity:
            continue
        for operation in iface.operations:
            wrapper_keys.update(_sample_wrapper_keys(operation.response_sample_content))
            wrapper_keys.update(_sample_wrapper_keys(operation.request_sample_content))
    return wrapper_keys


def is_wrapper_identity_field(
    session: ProjectSession,
    canonical_entity: str,
    field_name: str,
) -> bool:
    field_key = _key(field_name)
    if field_key in _EXACT_WRAPPER_FIELD_KEYS:
        return True
    if field_key in _GENERIC_WRAPPER_FIELD_KEYS:
        return field_key in wrapper_field_keys_for_entity(session, canonical_entity)
    return False


def eligible_identity_fields(session: ProjectSession, canonical_entity: str) -> list[dict[str, Any]]:
    entity = authoritative_entity(session, canonical_entity)
    if entity is None:
        return []
    existing = active_identity_decisions_by_field(session).get(canonical_entity, {})
    fields: list[dict[str, Any]] = []
    for field in entity.fields:
        if is_wrapper_identity_field(session, canonical_entity, field.name):
            continue
        decision = existing.get(field.name)
        fields.append(
            {
                "name": field.name,
                "type": field.type,
                "required": field.required,
                "is_id": field.is_id,
                "current_role": decision.role if decision else "",
                "reviewed_at": _date_label(decision.reviewed_at) if decision else "",
            }
        )
    return fields


def active_identity_decisions_by_field(
    session: ProjectSession,
) -> dict[str, dict[str, IdentityRoleDecision]]:
    by_entity: dict[str, dict[str, IdentityRoleDecision]] = {}
    for decision in session.identity_role_decisions:
        entity = str(decision.entity or "").strip()
        field = str(decision.field or "").strip()
        role = str(decision.role or "").strip()
        if not entity or not field or role not in IDENTITY_ROLE_VALUES:
            continue
        by_entity.setdefault(entity, {})[field] = decision
    return by_entity


def identity_role_review_context(session: ProjectSession) -> dict[str, Any]:
    if session.app_archetype != "crud":
        return {
            "enabled": False,
            "entities": [],
            "role_options": IDENTITY_ROLE_OPTIONS,
            "role_behavior_rows": identity_role_behavior_rows(),
            "empty_reason": "Identity role review is available for CRUD projects.",
        }

    entities: list[dict[str, Any]] = []
    for canonical in selected_canonical_entities(session):
        fields = eligible_identity_fields(session, canonical)
        blocked_count = 0
        owner = authoritative_entity(session, canonical)
        if owner:
            blocked_count = max(0, len(owner.fields) - len(fields))
        entities.append(
            {
                "name": canonical,
                "fields": fields,
                "blocked_count": blocked_count,
            }
        )
    empty_reason = ""
    if not entities:
        empty_reason = "Select CRUD entities to review identity roles."
    elif not any(entity["fields"] for entity in entities):
        empty_reason = "No eligible CRUD fields are available for identity role review."
    return {
        "enabled": True,
        "entities": entities,
        "role_options": IDENTITY_ROLE_OPTIONS,
        "role_behavior_rows": identity_role_behavior_rows(),
        "empty_reason": empty_reason,
    }


def identity_overrides_for_manifest(session: ProjectSession) -> list[dict[str, str]]:
    if session.app_archetype != "crud":
        return []
    decisions = active_identity_decisions_by_field(session)
    overrides: list[dict[str, str]] = []
    for entity_name in selected_canonical_entities(session):
        entity_decisions = decisions.get(entity_name, {})
        for field in eligible_identity_fields(session, entity_name):
            decision = entity_decisions.get(field["name"])
            if decision and decision.role == "persistence_id":
                overrides.append({"entity": entity_name, "persistence_id": field["name"]})
                break
    return overrides


def identity_roles_for_manifest(session: ProjectSession) -> list[dict[str, str]]:
    if session.app_archetype != "crud":
        return []
    decisions = active_identity_decisions_by_field(session)
    roles: list[dict[str, str]] = []
    for entity_name in selected_canonical_entities(session):
        entity_decisions = decisions.get(entity_name, {})
        for field in eligible_identity_fields(session, entity_name):
            decision = entity_decisions.get(field["name"])
            if decision and decision.role in METADATA_ONLY_IDENTITY_ROLES:
                roles.append(
                    {
                        "entity": entity_name,
                        "field": field["name"],
                        "role": decision.role,
                        "mode": "metadata_only",
                    }
                )
    return roles


def identity_role_decision_entries(session: ProjectSession) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    valid_fields = {
        entity_name: {field["name"] for field in eligible_identity_fields(session, entity_name)}
        for entity_name in selected_canonical_entities(session)
    }
    for decision in session.identity_role_decisions:
        entity = str(decision.entity or "").strip()
        field = str(decision.field or "").strip()
        role = str(decision.role or "").strip()
        if role not in IDENTITY_ROLE_VALUES:
            continue
        if field not in valid_fields.get(entity, set()):
            continue
        behavior = identity_role_behavior(role)
        entries.append(
            {
                "entity": entity,
                "field": field,
                "role": role,
                "provenance": decision.provenance or "human-authored",
                "reviewed_at": _date_label(decision.reviewed_at, fallback="—"),
                "export_impact": (
                    "Exports to identity_overrides and affects generated persistence identity"
                    if role == "persistence_id"
                    else "Exports to identity_roles as metadata_only; no generated app behavior yet"
                ),
                "generation_impact": str(behavior.get("current_engine_behavior") or ""),
                "api_impact": str(behavior.get("api_behavior") or ""),
                "evidence_trail_impact": str(behavior.get("evidence_trail_behavior") or ""),
                "impact_badge": str(behavior.get("impact_badge") or ""),
                "affects_engine": bool(behavior.get("affects_engine")),
                "manifest_path": f"entities.{entity}.fields.{field}",
            }
        )
    return entries
