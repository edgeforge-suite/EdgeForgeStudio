"""Validate inbound mapping paths and OpenAPI canonical targets."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.project import ProjectSession, UpstreamInterface


@dataclass(frozen=True)
class CanonicalMappingIssue:
    interface_name: str
    operation_name: str | None
    mapping_side: str
    source: str
    target: str
    message: str


def selected_canonical_field_inventory(session: ProjectSession) -> dict[str, set[str]]:
    """Return fields for selected, entity-classified canonical models."""
    selected = set(session.selected_entity_names)
    inventory: dict[str, set[str]] = {}
    for entity in session.classified_entities:
        canonical = entity.display_name()
        if entity.classification != "entity":
            continue
        if entity.name not in selected and canonical not in selected:
            continue
        inventory.setdefault(canonical, set()).update(field.name for field in entity.fields)
    return inventory


def canonical_fields_for_entity(
    session: ProjectSession,
    entity_name: str | None,
) -> set[str] | None:
    if not entity_name:
        return None
    return selected_canonical_field_inventory(session).get(entity_name)


def canonical_mapping_target_error(
    session: ProjectSession,
    *,
    expected_entity: str | None,
    target: str,
) -> str | None:
    """Return why an inbound mapping target is unsafe, or ``None``."""
    raw_target = str(target or "")
    clean_target = raw_target.strip()
    if not clean_target:
        return "Canonical mapping target is required."
    if raw_target != clean_target:
        return (
            f"Canonical mapping target '{raw_target}' must not contain leading or trailing "
            "whitespace."
        )
    if not expected_entity:
        return f"Canonical mapping target '{clean_target}' requires a selected canonical entity."

    if "." in clean_target:
        target_entity, target_field = clean_target.split(".", 1)
    else:
        target_entity, target_field = expected_entity, clean_target

    if target_entity != expected_entity:
        return (
            f"Canonical mapping target '{clean_target}' must use selected entity "
            f"'{expected_entity}'."
        )

    fields = canonical_fields_for_entity(session, expected_entity)
    if fields is None:
        return (
            f"Canonical mapping target '{clean_target}' cannot be verified because selected entity "
            f"'{expected_entity}' has no canonical model."
        )
    if not target_field or target_field not in fields:
        return (
            f"Canonical mapping target '{clean_target}' is not a field on selected entity "
            f"'{expected_entity}'. Add the field explicitly to the canonical entity or "
            "remove/remap this row."
        )
    return None


def mapping_path_whitespace_error(value: str, *, label: str) -> str | None:
    """Reject paths whose validated form differs from what Engine will receive."""
    raw_value = str(value or "")
    if raw_value != raw_value.strip():
        return (
            f"Mapping {label} '{raw_value}' must not contain leading or trailing whitespace."
        )
    return None


def upstream_mapping_target_issues(
    session: ProjectSession,
    iface: UpstreamInterface,
) -> list[CanonicalMappingIssue]:
    """Validate every inbound target exported for one upstream interface."""
    issues: list[CanonicalMappingIssue] = []

    def add_issue(
        *,
        operation_name: str | None,
        mapping_side: str,
        source: str,
        target: str,
        validate_canonical_target: bool,
    ) -> None:
        location = f" → operation '{operation_name}'" if operation_name else ""
        errors = [
            error
            for error in (
                mapping_path_whitespace_error(source, label="source"),
                mapping_path_whitespace_error(target, label="target"),
            )
            if error is not None
        ]
        if validate_canonical_target and not errors:
            target_error = canonical_mapping_target_error(
                session,
                expected_entity=iface.entity_name,
                target=target,
            )
            if target_error is not None:
                errors.append(target_error)
        for error in errors:
            issues.append(
                CanonicalMappingIssue(
                    interface_name=iface.name,
                    operation_name=operation_name,
                    mapping_side=mapping_side,
                    source=source,
                    target=target,
                    message=(
                        f"'{iface.name}'{location}: {mapping_side} mapping '{source}' → "
                        f"'{target}' is invalid. {error}"
                    ),
                )
            )

    # Edge-contract-only file/XML projects intentionally have no CRUD model.
    # Their field mappings remain Engine-supported, but raw paths must still be
    # byte-canonical because the package writer emits them unchanged.
    for mapping in iface.field_mappings:
        add_issue(
            operation_name=None,
            mapping_side="field",
            source=mapping.source,
            target=mapping.target,
            validate_canonical_target=False,
        )
    for operation in iface.operation_mappings:
        for mapping in operation.request_mappings:
            add_issue(
                operation_name=operation.name,
                mapping_side="request",
                source=mapping.source,
                target=mapping.target,
                validate_canonical_target=iface.type == "rest-json",
            )
        for mapping in operation.response_mappings:
            add_issue(
                operation_name=operation.name,
                mapping_side="response",
                source=mapping.source,
                target=mapping.target,
                validate_canonical_target=iface.type == "rest-json",
            )
    return issues


def all_upstream_mapping_target_issues(
    session: ProjectSession,
) -> list[CanonicalMappingIssue]:
    return [
        issue
        for iface in session.upstream_interfaces
        for issue in upstream_mapping_target_issues(session, iface)
    ]
