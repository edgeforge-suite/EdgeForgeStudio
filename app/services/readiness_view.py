"""Read-only readiness view-model adapter for refreshed Studio surfaces.

This module wraps existing readiness producers; it does not decide exportability
on its own. PR-03 introduced edge-contract items; PR-04 added handoff/entity
items; PR-19 adds entity-scoped rule-set items.

``step_counts(session)`` returns a rail-friendly mapping:
``{step_position: {"count": int, "attention": int}}`` for every applicable
wizard step. ``attention`` counts represented items whose state is
``needs_action`` or ``blocks_export``. Later UX-refresh PRs add more producers
without changing this public shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import quote

from app.models.project import (
    DataHandoff,
    DownstreamInterface,
    EntityRules,
    ProjectSession,
    UpstreamInterface,
)
from app.services.edge_contracts import (
    EDGE_CONTRACT_TYPES,
    FILE_CSV_TYPE,
    FILE_FIXED_WIDTH_TYPE,
    INCOMPLETE,
    REFERENCE_ONLY,
    SOAP_WSDL_TYPE,
    XML_XSD_TYPE,
    EdgeContractReadiness,
    _safe_persistence_fields,
    edge_contract_readiness,
)
from app.services.edge_contracts import (
    slug as edge_slug,
)
from app.services.identity_roles import selected_canonical_entities
from app.services.staging_ddl_validation import extract_column_names_from_ddl
from app.wizard_registry import get_steps

ITEM_KIND_DOWNSTREAM_INTERFACE = "downstream_interface"
ITEM_KIND_UPSTREAM_CONTRACT = "upstream_contract"
ITEM_KIND_HANDOFF = "handoff"
ITEM_KIND_ENTITY = "entity"
ITEM_KIND_RULE_SET = "rule_set"
ITEM_KIND_PROJECT = "project"

# Full contract vocabulary is declared now; edge contracts, handoffs, entities,
# and rule sets are populated. rest/project remain reserved for later producers.
FAMILY_REST = "rest"
FAMILY_FIXED = "fixed"
FAMILY_CSV = "csv"
FAMILY_XML = "xml"
FAMILY_SOAP = "soap"
FAMILY_STAGING = "staging"
FAMILY_ENTITY = "entity"
FAMILY_RULES = "rules"

STATE_READY = "ready"
STATE_WARNING = "warning"
STATE_NEEDS_ACTION = "needs_action"
STATE_BLOCKS_EXPORT = "blocks_export"
STATE_DRAFT = "draft"

CAPABILITY_POPULATES_ENTITIES = "populates_entities"
CAPABILITY_MANIFEST_REFERENCE = "manifest_reference"
CAPABILITY_METADATA_ONLY = "metadata_only"

_ATTENTION_STATES = {STATE_NEEDS_ACTION, STATE_BLOCKS_EXPORT}
_CROSS_ENTITY_PREREQUISITE_TYPES = {
    "cross-entity-field-check",
    "cross-entity-field-compare",
    "cross-entity-field-in",
}

_FAMILY_BY_CONTRACT_TYPE = {
    FILE_FIXED_WIDTH_TYPE: FAMILY_FIXED,
    FILE_CSV_TYPE: FAMILY_CSV,
    XML_XSD_TYPE: FAMILY_XML,
    SOAP_WSDL_TYPE: FAMILY_SOAP,
}

_SECTION_REF_BY_FAMILY = {
    FAMILY_FIXED: "layout",
    FAMILY_CSV: "layout",
    FAMILY_XML: "xsd",
    FAMILY_SOAP: "wsdl",
}


@dataclass(frozen=True)
class Ref:
    code: str
    label: str
    field_ref: str | None = None
    section_ref: str | None = None
    deep_link: str | None = None


@dataclass(frozen=True)
class Cov:
    label: str
    complete: int
    total: int


@dataclass(frozen=True)
class ReadinessItem:
    item_id: str
    item_kind: str
    family: str
    display_name: str
    state: str
    export_blocking: bool
    blockers: list[Ref] = field(default_factory=list)
    warnings: list[Ref] = field(default_factory=list)
    coverage: list[Cov] = field(default_factory=list)
    capability: str = CAPABILITY_MANIFEST_REFERENCE
    source_of_truth_version: str = "1"


def items_for_step(
    session: ProjectSession,
    step: int,
    *,
    conflict_advisories: dict | None = None,
) -> list[ReadinessItem]:
    """Return represented readiness items for a wizard step position.

    ``conflict_advisories`` is an explicit Step 6 enrichment input because the
    existing advisory producer is request-scoped and may contact KS when KA is on.
    """
    route = _route_for_step(session, step)
    if route == "/upstream":
        return _upstream_contract_items(session)
    if route == "/entities":
        return _entity_items(session)
    if route == "/handoffs":
        return _handoff_items(session)
    if route == "/downstream":
        return _downstream_interface_items(session)
    if route == "/rules":
        return rule_set_items(session, conflict_advisories=conflict_advisories)
    return []


def step_counts(session: ProjectSession) -> dict[int, dict[str, int]]:
    """Return represented readiness counts for all applicable wizard steps."""
    counts: dict[int, dict[str, int]] = {}
    for step in get_steps(session.app_archetype):
        if not step.applicable:
            continue
        items = items_for_step(session, step.position)
        counts[step.position] = {
            "count": len(items),
            "attention": sum(1 for readiness_item in items if readiness_item.state in _ATTENTION_STATES),
        }
    return counts


def item(session: ProjectSession, item_id: str) -> ReadinessItem:
    """Resolve one represented readiness item by id."""
    for readiness_item in _all_items(session):
        if readiness_item.item_id == item_id:
            return readiness_item
    raise KeyError(f"Unknown readiness item '{item_id}'.")


def item_by_display_name(
    session: ProjectSession,
    display_name: str,
    *,
    item_kinds: tuple[str, ...] | None = None,
) -> ReadinessItem | None:
    """Resolve a represented item by its display name (not item_id) -- used to
    join a completeness_service.CompletenessItem's free-text message back to
    its structured ReadinessItem/deep_link, since CompletenessItem carries no
    structured reference. ``item_kinds``, when given, restricts the search to
    those kinds -- callers that know which producer a message came from (e.g.
    completeness_service's "Upstream" vs "Downstream" category) should pass
    it: upstream and downstream interfaces are independent lists with no
    cross-list name-uniqueness guarantee, so an unfiltered search could
    silently resolve to the wrong-direction item when both share a name.
    Returns None rather than raising when nothing matches (e.g. the report
    includes categories readiness_view doesn't itemize yet -- Project/Kafka/
    Rules -- or the name extraction finds no match), so callers can fall back
    to the plain, unlinked rendering."""
    for readiness_item in _all_items(session):
        if item_kinds is not None and readiness_item.item_kind not in item_kinds:
            continue
        if readiness_item.display_name == display_name:
            return readiness_item
    return None


def _all_items(session: ProjectSession) -> list[ReadinessItem]:
    items: list[ReadinessItem] = []
    for step in get_steps(session.app_archetype):
        if step.applicable:
            items.extend(items_for_step(session, step.position))
    return items


def _upstream_contract_items(session: ProjectSession) -> list[ReadinessItem]:
    return [
        _edge_contract_item(
            session,
            iface,
            direction="upstream",
            item_kind=ITEM_KIND_UPSTREAM_CONTRACT,
            item_id_prefix="usc",
            route="/upstream",
        )
        for iface in session.upstream_interfaces
        if iface.type in EDGE_CONTRACT_TYPES
    ]


def _downstream_interface_items(session: ProjectSession) -> list[ReadinessItem]:
    return [
        _edge_contract_item(
            session,
            iface,
            direction="downstream",
            item_kind=ITEM_KIND_DOWNSTREAM_INTERFACE,
            item_id_prefix="dsi",
            route="/downstream",
        )
        for iface in session.downstream_interfaces
        if iface.type in EDGE_CONTRACT_TYPES
    ]


def _handoff_items(session: ProjectSession) -> list[ReadinessItem]:
    return [_handoff_item(session, handoff) for handoff in session.data_handoffs]


def _entity_items(session: ProjectSession) -> list[ReadinessItem]:
    return [_entity_item(session, entity_name) for entity_name in selected_canonical_entities(session)]


def rule_set_items(
    session: ProjectSession,
    *,
    conflict_advisories: dict | None = None,
) -> list[ReadinessItem]:
    """Build rule-set items, optionally enriching them with existing KA advisories.

    The public wizard adapter stays pure when advisories are omitted. Step 6 passes
    the advisory payload it already fetched, avoiding a hidden Knowledge Server call
    from ambient readiness/count consumers.
    """
    represented_by_name = {
        entity_rules.entity_name: entity_rules for entity_rules in session.entity_rules
    }
    represented_names = list(selected_canonical_entities(session))
    represented_names.extend(
        name for name in represented_by_name if name not in represented_names
    )
    represented_rule_sets = [
        represented_by_name.get(entity_name)
        or EntityRules(entity_name=entity_name, rules=[], file_path=None)
        for entity_name in represented_names
    ]
    prerequisite_targets = rule_set_prerequisite_targets(represented_rule_sets)
    return [
        _rule_set_item(
            session,
            entity_rules,
            prerequisite_targets=prerequisite_targets,
            conflict_advisories=conflict_advisories,
        )
        for entity_rules in represented_rule_sets
    ]


def rule_set_item(
    session: ProjectSession,
    entity_name: str,
    *,
    conflict_advisories: dict | None = None,
) -> ReadinessItem:
    """Resolve one rule-set item while preserving optional advisory context."""
    for readiness_item in rule_set_items(
        session,
        conflict_advisories=conflict_advisories,
    ):
        if readiness_item.display_name == entity_name:
            return readiness_item
    raise KeyError(f"Unknown readiness item 'rule_set:{entity_name}'.")


def rule_set_prerequisite_targets(
    entity_rule_sets: list[EntityRules],
) -> dict[tuple[str, str], set[str]]:
    """Return prerequisites keyed by owning rule-set and FK field."""
    targets: dict[tuple[str, str], set[str]] = {}
    for entity_rules in entity_rule_sets:
        for rule in entity_rules.rules:
            if rule.type != "cross-entity-exists" or not rule.field or not rule.target_entity:
                continue
            targets.setdefault((entity_rules.entity_name, rule.field), set()).add(
                rule.target_entity
            )
    return targets


def missing_rule_set_prerequisites(
    entity_rules: EntityRules,
    prerequisite_targets: dict[tuple[str, str], set[str]],
) -> list[tuple[str, str | None]]:
    """Return dependent rules lacking a prerequisite in their owning rule-set."""
    missing: list[tuple[str, str | None]] = []
    seen: set[tuple[str, str | None]] = set()
    for rule in entity_rules.rules:
        if rule.type not in _CROSS_ENTITY_PREREQUISITE_TYPES or not rule.field:
            continue
        available = prerequisite_targets.get(
            (entity_rules.entity_name, rule.field),
            set(),
        )
        key = (rule.field, rule.target_entity)
        if available and (not rule.target_entity or rule.target_entity in available):
            continue
        if key not in seen:
            missing.append(key)
            seen.add(key)
    return missing


def _edge_contract_item(
    session: ProjectSession,
    iface: UpstreamInterface | DownstreamInterface,
    *,
    direction: str,
    item_kind: str,
    item_id_prefix: str,
    route: str,
) -> ReadinessItem:
    row = edge_contract_readiness(iface, direction=direction, session=session)
    family = _family_for_contract_type(row.type)
    section_ref = _SECTION_REF_BY_FAMILY.get(family)
    deep_link = _deep_link(route, iface.name, section_ref)
    blockers = [
        Ref(
            code=f"missing-{edge_slug(missing)}",
            label=missing,
            field_ref=edge_slug(missing),
            section_ref=section_ref,
            deep_link=deep_link,
        )
        for missing in row.required_missing
    ]
    warnings = [
        Ref(
            code="edge-contract-warning",
            label=warning,
            section_ref=section_ref,
            deep_link=deep_link,
        )
        for warning in row.warnings
    ]
    return ReadinessItem(
        item_id=f"{item_id_prefix}:{iface.name}",
        item_kind=item_kind,
        family=family,
        display_name=row.name,
        state=_state_for_edge_contract(row),
        export_blocking=row.status == INCOMPLETE,
        blockers=blockers,
        warnings=warnings,
        coverage=_coverage_for_edge_contract(row),
        capability=_capability_for_edge_contract(iface, item_kind),
        # Placeholder until conflict-echo work needs a richer source marker.
        source_of_truth_version=str(session.project_revision),
    )


def _handoff_item(session: ProjectSession, handoff: DataHandoff) -> ReadinessItem:
    ddl_present = bool(handoff.ddl_content or handoff.spec)
    mappings_present = bool(handoff.field_mappings)
    warnings: list[Ref] = []
    if not ddl_present:
        warnings.append(
            Ref(
                code="missing-ddl",
                label=f"'{handoff.name}': no DDL provided",
                field_ref="ddl",
                section_ref="ddl",
                deep_link=_deep_link("/handoffs", handoff.name, "ddl"),
            )
        )
    if not mappings_present:
        warnings.append(
            Ref(
                code="missing-field-mappings",
                label=f"'{handoff.name}': no field mappings supplied",
                field_ref="field_mappings",
                section_ref="mappings",
                deep_link=_deep_link("/handoffs", handoff.name, "mappings"),
            )
        )

    missing_columns = _missing_handoff_mapping_columns(handoff)
    if missing_columns:
        label = (
            f"'{handoff.name}': mappings reference unknown staging column(s): "
            + ", ".join(missing_columns)
        )
        warnings.append(
            Ref(
                code="mapping-target-column-missing",
                label=label,
                field_ref="field_mappings",
                section_ref="mappings",
                deep_link=_deep_link("/handoffs", handoff.name, "mappings"),
            )
        )

    return ReadinessItem(
        item_id=f"handoff:{handoff.name}",
        item_kind=ITEM_KIND_HANDOFF,
        family=FAMILY_STAGING,
        display_name=handoff.name,
        state=STATE_WARNING if warnings else STATE_READY,
        export_blocking=False,
        blockers=[],
        warnings=warnings,
        coverage=[
            Cov(
                label="Handoff requirements",
                complete=int(ddl_present) + int(mappings_present),
                total=2,
            )
        ],
        capability=CAPABILITY_MANIFEST_REFERENCE,
        source_of_truth_version=str(session.project_revision),
    )


def _entity_item(session: ProjectSession, entity_name: str) -> ReadinessItem:
    persistence_fields = _safe_persistence_fields(session, entity_name)
    ready = bool(persistence_fields)
    blockers = []
    if not ready:
        blockers.append(
            Ref(
                code="missing-persistence-key",
                label="No persistence key chosen",
                field_ref="persistence_id",
                section_ref="identity",
                deep_link=_deep_link("/entities", entity_name, "identity"),
            )
        )

    return ReadinessItem(
        item_id=f"entity:{entity_name}",
        item_kind=ITEM_KIND_ENTITY,
        family=FAMILY_ENTITY,
        display_name=entity_name,
        state=STATE_READY if ready else STATE_NEEDS_ACTION,
        export_blocking=False,
        blockers=blockers,
        warnings=[],
        coverage=[Cov(label="Persistence key", complete=1 if ready else 0, total=1)],
        capability=CAPABILITY_POPULATES_ENTITIES if ready else CAPABILITY_METADATA_ONLY,
        source_of_truth_version=str(session.project_revision),
    )


def _rule_set_item(
    session: ProjectSession,
    entity_rules: EntityRules,
    *,
    prerequisite_targets: dict[tuple[str, str], set[str]],
    conflict_advisories: dict | None,
) -> ReadinessItem:
    entity_name = entity_rules.entity_name
    blockers = [
        Ref(
            code="cross-entity-prerequisite-missing",
            label=(
                f"Add cross-entity-exists for '{field_name}'"
                + (f" targeting '{target_entity}'" if target_entity else "")
                + " first"
            ),
            field_ref=field_name,
            section_ref="cross-entity",
            deep_link=_deep_link("/rules", entity_name, "cross-entity"),
        )
        for field_name, target_entity in missing_rule_set_prerequisites(
            entity_rules,
            prerequisite_targets,
        )
    ]
    warnings = _rule_set_advisory_refs(entity_name, conflict_advisories)
    rule_fields = {rule.field for rule in entity_rules.rules if rule.field}
    entity_fields = _entity_field_names(session, entity_name)
    state = STATE_NEEDS_ACTION if blockers else STATE_WARNING if warnings else STATE_READY
    return ReadinessItem(
        item_id=f"rule_set:{entity_name}",
        item_kind=ITEM_KIND_RULE_SET,
        family=FAMILY_RULES,
        display_name=entity_name,
        state=state,
        export_blocking=False,
        blockers=blockers,
        warnings=warnings,
        coverage=[
            Cov(
                label="fields",
                complete=len(rule_fields),
                total=len(entity_fields),
            )
        ],
        capability=CAPABILITY_MANIFEST_REFERENCE,
        source_of_truth_version=str(session.project_revision),
    )


def _entity_field_names(session: ProjectSession, entity_name: str) -> set[str]:
    return {
        field.name
        for entity in session.classified_entities
        if entity.display_name() == entity_name
        for field in entity.fields
        if field.name
    }


def _rule_set_advisory_refs(
    entity_name: str,
    conflict_advisories: dict | None,
) -> list[Ref]:
    if not conflict_advisories:
        return []
    warnings: list[Ref] = []
    for group in conflict_advisories.get("groups", []):
        if group.get("entity") != entity_name:
            continue
        for advisory in group.get("items", []):
            field_name = str(advisory.get("field_name") or "").strip() or None
            label = str(advisory.get("conflict_hint") or "").strip()
            if not label:
                continue
            warnings.append(
                Ref(
                    code="rule-advisory",
                    label=label,
                    field_ref=field_name,
                    section_ref="advisories",
                    deep_link=_deep_link("/rules", entity_name, "advisories"),
                )
            )
    return warnings


def _state_for_edge_contract(row: EdgeContractReadiness) -> str:
    if row.status == INCOMPLETE:
        return STATE_BLOCKS_EXPORT
    if row.warnings:
        return STATE_WARNING
    if row.status == REFERENCE_ONLY:
        return STATE_DRAFT
    return STATE_READY


def _coverage_for_edge_contract(row: EdgeContractReadiness) -> list[Cov]:
    total = len(row.required_present) + len(row.required_missing)
    if total == 0:
        return []
    return [Cov(label="Required fields", complete=len(row.required_present), total=total)]


def _capability_for_edge_contract(
    iface: UpstreamInterface | DownstreamInterface,
    item_kind: str,
) -> str:
    if item_kind == ITEM_KIND_UPSTREAM_CONTRACT and getattr(iface, "entity_name", None):
        return CAPABILITY_POPULATES_ENTITIES
    return CAPABILITY_MANIFEST_REFERENCE


def _family_for_contract_type(contract_type: str) -> str:
    return _FAMILY_BY_CONTRACT_TYPE.get(contract_type, FAMILY_REST)


def _deep_link(route: str, item_name: str, section_ref: str | None) -> str:
    focus = quote(item_name, safe="")
    fragment = section_ref or "summary"
    return f"{route}?focus={focus}#{fragment}"


def _missing_handoff_mapping_columns(handoff: DataHandoff) -> list[str]:
    if not handoff.ddl_content or not handoff.field_mappings:
        return []
    column_names = extract_column_names_from_ddl(handoff.ddl_content)
    if column_names is None:
        return []
    normalized_column_names = {column.strip().lower() for column in column_names}
    return sorted(
        {
            mapping.target.strip()
            for mapping in handoff.field_mappings
            if mapping.target and mapping.target.strip().lower() not in normalized_column_names
        }
    )


def _route_for_step(session: ProjectSession, step_position: int) -> str | None:
    for step in get_steps(session.app_archetype):
        if step.position == step_position and step.applicable:
            return step.route
    return None
