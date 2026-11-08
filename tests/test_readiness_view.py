from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    DataHandoff,
    DownstreamInterface,
    FieldMapping,
    IdentityRoleDecision,
    ProjectSession,
    UpstreamInterface,
)
from app.services.completeness_service import build_completeness_report
from app.services.edge_contracts import INCOMPLETE, edge_contract_readiness
from app.services.project_file_service import deserialize_project, serialize_project, snapshot_session
from app.services.readiness_view import (
    CAPABILITY_MANIFEST_REFERENCE,
    CAPABILITY_METADATA_ONLY,
    CAPABILITY_POPULATES_ENTITIES,
    FAMILY_CSV,
    FAMILY_ENTITY,
    FAMILY_FIXED,
    FAMILY_SOAP,
    FAMILY_STAGING,
    FAMILY_XML,
    ITEM_KIND_DOWNSTREAM_INTERFACE,
    ITEM_KIND_ENTITY,
    ITEM_KIND_HANDOFF,
    ITEM_KIND_UPSTREAM_CONTRACT,
    STATE_BLOCKS_EXPORT,
    STATE_NEEDS_ACTION,
    STATE_READY,
    STATE_WARNING,
    item,
    items_for_step,
    step_counts,
)


def _readiness_session() -> ProjectSession:
    session = ProjectSession(
        app_name="Readiness Smoke",
        bounded_context="readiness-smoke",
        app_archetype="crud",
        target_profile="hexagonal",
        project_revision=7,
    )
    session.upstream_interfaces = [
        UpstreamInterface(
            name="rest-api",
            type="rest-json",
            spec="contracts/rest-openapi.yaml",
            entity_name="Account",
        ),
        UpstreamInterface(name="fixed-missing", type="file-fixed-width"),
        UpstreamInterface(
            name="xml-warning",
            type="xml-xsd",
            xsd_path="contracts/account.xsd",
            xsd_content="<xs:schema xmlns:xs='http://www.w3.org/2001/XMLSchema'/>",
            root_element="AccountMessage",
        ),
        UpstreamInterface(
            name="csv-ready",
            type="file-csv",
            spec="upstream/account-layout.yaml",
            spec_content="format: delimited\ndelimiter: ','\nfields:\n  - name: accountId\n",
            entity_name="Account",
            field_mappings=[
                FieldMapping(source="accountId", target="Account.accountId"),
                FieldMapping(source="status", target="Account.status"),
            ],
        ),
        UpstreamInterface(
            name="soap-reference",
            type="soap-wsdl",
            wsdl_path="contracts/account.wsdl",
        ),
    ]
    session.downstream_interfaces = [
        DownstreamInterface(
            name="fixed-out-ready",
            type="file-fixed-width",
            spec="downstream/account-layout.yaml",
            spec_content="format: fixed-width\nrecord_types:\n  data:\n    fields: []\n",
            entity_name="Account",
            field_mappings=[FieldMapping(source="Account.accountId", target="accountId")],
        ),
        DownstreamInterface(name="soap-out-missing", type="soap-wsdl"),
    ]
    return session


def _account_stage_ddl() -> str:
    return """CREATE TABLE account_stage (
    account_id VARCHAR(36),
    status VARCHAR(20)
);
"""


def _phase04_session() -> ProjectSession:
    session = _readiness_session()
    session.classified_entities = [
        ClassifiedEntity(
            name="ExplicitEntity",
            fields=[ClassifiedField(name="businessKey", type="string")],
        ),
        ClassifiedEntity(
            name="FallbackEntity",
            fields=[ClassifiedField(name="fallbackId", type="string", is_id=True)],
        ),
        ClassifiedEntity(
            name="MissingEntity",
            fields=[ClassifiedField(name="code", type="string")],
        ),
    ]
    session.selected_entity_names = ["ExplicitEntity", "FallbackEntity", "MissingEntity"]
    session.identity_role_decisions = [
        IdentityRoleDecision(
            entity="ExplicitEntity",
            field="businessKey",
            role="persistence_id",
        )
    ]
    session.data_handoffs = [
        DataHandoff(
            name="ready-handoff",
            ddl_content=_account_stage_ddl(),
            field_mappings=[
                FieldMapping(source="ExplicitEntity.businessKey", target="account_id"),
                FieldMapping(source="ExplicitEntity.status", target="status"),
            ],
        ),
        DataHandoff(
            name="missing-ddl",
            field_mappings=[FieldMapping(source="ExplicitEntity.businessKey", target="account_id")],
        ),
        DataHandoff(name="missing-mappings", ddl_content=_account_stage_ddl()),
        DataHandoff(name="missing-both"),
    ]
    return session


def test_items_for_step_maps_edge_contract_states_and_filters_rest():
    session = _readiness_session()

    upstream_items = items_for_step(session, 2)
    by_id = {readiness_item.item_id: readiness_item for readiness_item in upstream_items}

    assert list(by_id) == [
        "usc:fixed-missing",
        "usc:xml-warning",
        "usc:csv-ready",
        "usc:soap-reference",
    ]
    assert "usc:rest-api" not in by_id

    fixed = by_id["usc:fixed-missing"]
    assert fixed.item_kind == ITEM_KIND_UPSTREAM_CONTRACT
    assert fixed.family == FAMILY_FIXED
    assert fixed.state == STATE_BLOCKS_EXPORT
    assert fixed.export_blocking is True
    assert fixed.blockers[0].code.startswith("missing-")
    assert fixed.blockers[0].section_ref == "layout"
    assert fixed.blockers[0].deep_link == "/upstream?focus=fixed-missing#layout"

    xml = by_id["usc:xml-warning"]
    assert xml.family == FAMILY_XML
    assert xml.state == STATE_WARNING
    assert xml.export_blocking is False
    assert xml.warnings

    csv = by_id["usc:csv-ready"]
    assert csv.family == FAMILY_CSV
    assert csv.state == STATE_READY
    assert csv.capability == CAPABILITY_POPULATES_ENTITIES
    assert csv.source_of_truth_version == "7"

    soap = by_id["usc:soap-reference"]
    assert soap.family == FAMILY_SOAP
    assert soap.state == STATE_WARNING
    assert soap.export_blocking is False


def test_downstream_items_use_downstream_prefix_and_manifest_reference_capability():
    session = _readiness_session()

    downstream_items = items_for_step(session, 5)
    by_id = {readiness_item.item_id: readiness_item for readiness_item in downstream_items}

    assert list(by_id) == ["dsi:fixed-out-ready", "dsi:soap-out-missing"]
    assert by_id["dsi:fixed-out-ready"].item_kind == ITEM_KIND_DOWNSTREAM_INTERFACE
    assert by_id["dsi:fixed-out-ready"].state == STATE_READY
    assert by_id["dsi:fixed-out-ready"].capability == CAPABILITY_MANIFEST_REFERENCE
    assert by_id["dsi:soap-out-missing"].state == STATE_BLOCKS_EXPORT
    assert by_id["dsi:soap-out-missing"].blockers[0].deep_link == (
        "/downstream?focus=soap-out-missing#wsdl"
    )


def test_export_blocking_parity_for_represented_edge_contract_items():
    session = _readiness_session()

    upstream_by_name = {iface.name: iface for iface in session.upstream_interfaces}
    for readiness_item in items_for_step(session, 2):
        iface = upstream_by_name[readiness_item.item_id.removeprefix("usc:")]
        row = edge_contract_readiness(iface, direction="upstream", session=session)
        assert readiness_item.export_blocking is (row.status == INCOMPLETE)

    downstream_by_name = {iface.name: iface for iface in session.downstream_interfaces}
    for readiness_item in items_for_step(session, 5):
        iface = downstream_by_name[readiness_item.item_id.removeprefix("dsi:")]
        row = edge_contract_readiness(iface, direction="downstream", session=session)
        assert readiness_item.export_blocking is (row.status == INCOMPLETE)


def test_item_resolves_same_data_and_raises_for_unknown_id():
    session = _readiness_session()

    resolved = item(session, "usc:csv-ready")
    listed = next(
        readiness_item
        for readiness_item in items_for_step(session, 2)
        if readiness_item.item_id == "usc:csv-ready"
    )

    assert resolved == listed
    with pytest.raises(KeyError, match="Unknown readiness item"):
        item(session, "usc:nope")


def test_step_counts_include_applicable_steps_with_attention_counts():
    session = _phase04_session()

    counts = step_counts(session)

    assert counts[1] == {"count": 0, "attention": 0}
    assert counts[2] == {"count": 4, "attention": 1}
    assert counts[3] == {"count": 3, "attention": 1}
    assert counts[4] == {"count": 4, "attention": 0}
    assert counts[5] == {"count": 2, "attention": 1}
    assert counts[8] == {"count": 0, "attention": 0}


def test_readiness_items_are_deterministic_for_same_session():
    session = _phase04_session()

    first = [
        asdict(readiness_item)
        for step in (2, 3, 4, 5)
        for readiness_item in items_for_step(session, step)
    ]
    second = [
        asdict(readiness_item)
        for step in (2, 3, 4, 5)
        for readiness_item in items_for_step(session, step)
    ]

    assert second == first


def test_readiness_adapter_is_computed_only_for_project_round_trip():
    session = _phase04_session()
    before_items = [
        asdict(readiness_item)
        for step in (2, 3, 4, 5)
        for readiness_item in items_for_step(session, step)
    ]

    project = snapshot_session(session)
    encoded = serialize_project(project)
    decoded = deserialize_project(encoded)
    encoded_again = serialize_project(decoded)

    assert json.loads(encoded_again) == json.loads(encoded)
    assert "ReadinessItem" not in encoded
    assert [
        asdict(readiness_item)
        for step in (2, 3, 4, 5)
        for readiness_item in items_for_step(session, step)
    ] == before_items


def test_handoff_items_match_completeness_warning_ceiling():
    session = _phase04_session()

    handoff_items = items_for_step(session, 4)
    by_id = {readiness_item.item_id: readiness_item for readiness_item in handoff_items}
    report = build_completeness_report(session)

    assert list(by_id) == [
        "handoff:ready-handoff",
        "handoff:missing-ddl",
        "handoff:missing-mappings",
        "handoff:missing-both",
    ]
    for readiness_item in handoff_items:
        handoff_name = readiness_item.item_id.removeprefix("handoff:")
        completeness_statuses = [
            completeness_item.status
            for completeness_item in report.items
            if completeness_item.category == "DataHandoff"
            and completeness_item.message.startswith(f"'{handoff_name}':")
        ]
        assert completeness_statuses
        assert readiness_item.state == (
            STATE_WARNING if "WARNING" in completeness_statuses else STATE_READY
        )
        assert readiness_item.export_blocking is False
        assert readiness_item.blockers == []

    assert by_id["handoff:ready-handoff"].item_kind == ITEM_KIND_HANDOFF
    assert by_id["handoff:ready-handoff"].family == FAMILY_STAGING
    assert by_id["handoff:ready-handoff"].capability == CAPABILITY_MANIFEST_REFERENCE
    assert by_id["handoff:missing-ddl"].warnings[0].code == "missing-ddl"
    assert by_id["handoff:missing-mappings"].warnings[0].code == "missing-field-mappings"


def test_handoff_warns_when_mapping_targets_parseable_missing_ddl_column():
    session = ProjectSession(app_name="DDL Warning", app_archetype="crud")
    session.data_handoffs = [
        DataHandoff(
            name="column-mismatch",
            ddl_content=_account_stage_ddl(),
            field_mappings=[FieldMapping(source="ExplicitEntity.status", target="unknown_column")],
        )
    ]

    readiness_item = items_for_step(session, 4)[0]

    assert readiness_item.state == STATE_WARNING
    assert readiness_item.export_blocking is False
    assert [warning.code for warning in readiness_item.warnings] == [
        "mapping-target-column-missing"
    ]


def test_handoff_ddl_column_check_is_case_insensitive_for_unquoted_identifiers():
    session = ProjectSession(app_name="DDL Case", app_archetype="crud")
    session.data_handoffs = [
        DataHandoff(
            name="case-match",
            ddl_content="""CREATE TABLE account_stage (
    ACCOUNT_ID VARCHAR(36)
);
""",
            field_mappings=[FieldMapping(source="ExplicitEntity.businessKey", target="account_id")],
        )
    ]

    readiness_item = items_for_step(session, 4)[0]

    assert readiness_item.state == STATE_READY
    assert "mapping-target-column-missing" not in {
        warning.code for warning in readiness_item.warnings
    }


def test_entity_items_use_explicit_decision_fallback_id_and_missing_key_states():
    session = _phase04_session()

    entity_items = items_for_step(session, 3)
    by_id = {readiness_item.item_id: readiness_item for readiness_item in entity_items}

    assert list(by_id) == [
        "entity:ExplicitEntity",
        "entity:FallbackEntity",
        "entity:MissingEntity",
    ]
    explicit = by_id["entity:ExplicitEntity"]
    assert explicit.item_kind == ITEM_KIND_ENTITY
    assert explicit.family == FAMILY_ENTITY
    assert explicit.state == STATE_READY
    assert explicit.export_blocking is False
    assert explicit.capability == CAPABILITY_POPULATES_ENTITIES

    fallback = by_id["entity:FallbackEntity"]
    assert fallback.state == STATE_READY
    assert fallback.export_blocking is False
    assert fallback.capability == CAPABILITY_POPULATES_ENTITIES

    missing = by_id["entity:MissingEntity"]
    assert missing.state == STATE_NEEDS_ACTION
    assert missing.export_blocking is False
    assert missing.capability == CAPABILITY_METADATA_ONLY
    assert [blocker.code for blocker in missing.blockers] == ["missing-persistence-key"]
    assert missing.blockers[0].deep_link == "/entities?focus=MissingEntity#identity"


def test_entity_items_are_scoped_to_crud_entities_route():
    session = ProjectSession(app_name="Kafka", app_archetype="kafka-integration")
    session.classified_entities = [
        ClassifiedEntity(
            name="EventRecord",
            fields=[ClassifiedField(name="eventId", type="string", is_id=True)],
        )
    ]
    session.selected_entity_names = ["EventRecord"]
    session.data_handoffs = [
        DataHandoff(
            name="kafka-handoff",
            ddl_content=_account_stage_ddl(),
            field_mappings=[FieldMapping(source="EventRecord.eventId", target="account_id")],
        )
    ]

    assert items_for_step(session, 3) == []
    with pytest.raises(KeyError, match="Unknown readiness item"):
        item(session, "entity:EventRecord")
    with pytest.raises(KeyError, match="Unknown readiness item"):
        item(session, "handoff:kafka-handoff")


def test_item_resolves_handoff_and_entity_items():
    session = _phase04_session()

    handoff = item(session, "handoff:ready-handoff")
    entity = item(session, "entity:MissingEntity")

    assert handoff == items_for_step(session, 4)[0]
    assert entity == items_for_step(session, 3)[2]
