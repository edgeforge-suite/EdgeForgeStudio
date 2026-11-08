"""Regression coverage for Step 4 single-item handoff persistence."""

from __future__ import annotations

import threading
from dataclasses import asdict
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.routes.handoffs as handoffs_route
from app.main import app
from app.models.project import DataHandoff, FieldMapping
from app.services import readiness_view
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)
TEMPLATE = Path(__file__).resolve().parents[1] / "app" / "templates" / "step4_handoffs.html"


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _ddl(table: str = "account_stage") -> str:
    return (
        f"CREATE TABLE {table} (\n"
        "  account_id VARCHAR(36) NOT NULL,\n"
        "  status VARCHAR(32)\n"
        ");"
    )


def _session_with_handoffs() -> tuple[DataHandoff, DataHandoff]:
    session = get_session()
    session.app_name = "Step 4 Save One"
    session.bounded_context = "step-four-save-one"
    session.app_archetype = "crud"
    session.project_revision = 7
    editable = DataHandoff(
        name="account-stage",
        system="ETL",
        type="staging-table",
        version="v1",
        spec="data-handoffs/account-stage.sql",
        ddl_content=_ddl(),
        table_name="account_stage",
        mapping_path="data-handoffs/account-stage-mapping.yaml",
        field_mappings=[FieldMapping(source="Account.accountId", target="account_id")],
        entity_name="Account",
    )
    sibling = DataHandoff(
        name="audit-stage",
        type="staging-table",
        spec="data-handoffs/audit-stage.sql",
        ddl_content="CREATE TABLE audit_stage (audit_id VARCHAR(36));",
        table_name="audit_stage",
        mapping_path="data-handoffs/audit-stage-mapping.yaml",
        field_mappings=[FieldMapping(source="Audit.auditId", target="audit_id")],
        entity_name="Audit",
    )
    session.data_handoffs = [editable, sibling]
    save_session(session)
    return editable, sibling


def _card_payload(handoff: DataHandoff) -> dict:
    return {
        "name": handoff.name,
        "system": handoff.system,
        "type": handoff.type,
        "version": handoff.version,
        "entity_name": handoff.entity_name,
        "table_name": handoff.table_name,
        "ddl_content": handoff.ddl_content,
        "field_mappings": [
            mapping.model_dump(mode="json") for mapping in handoff.field_mappings
        ],
    }


def _save_one(payload: dict, *, original_name: str | None, version: str = "7"):
    return client.post(
        "/handoffs/save-one",
        json={
            "item": payload,
            "original_name": original_name,
            "source_of_truth_version": version,
        },
    )


def test_save_one_touches_only_selected_handoff_and_returns_five_surface_payload():
    editable, sibling = _session_with_handoffs()
    sibling_before = sibling.model_dump(mode="json")
    payload = _card_payload(editable)
    payload["system"] = "Warehouse"

    response = _save_one(payload, original_name=editable.name)

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["item"]["system"] == "Warehouse"
    assert set(data["readiness"]) == {
        "item_id",
        "item_kind",
        "family",
        "display_name",
        "state",
        "export_blocking",
        "blockers",
        "warnings",
        "coverage",
        "capability",
        "source_of_truth_version",
    }
    assert data["readiness"]["item_id"] == "handoff:account-stage"
    assert data["board_metadata"] == {"fact": "account_stage · 2 cols · 1/2 mapped"}
    assert data["step_counts"]["4"] == {"count": 2, "attention": 0}
    assert {"step": 4, "count": 2, "attention": 0} in data["rail"]
    assert data["source_of_truth_version"] == "8"
    saved = get_session()
    assert saved.data_handoffs[1].model_dump(mode="json") == sibling_before
    assert data["readiness"] == asdict(readiness_view.item(saved, "handoff:account-stage"))


def test_save_one_returns_fresh_board_metadata_after_removing_last_mapping():
    editable, _ = _session_with_handoffs()
    payload = _card_payload(editable)
    payload["field_mappings"] = []

    response = _save_one(payload, original_name=editable.name)

    assert response.status_code == 200
    assert response.json()["board_metadata"] == {
        "fact": "account_stage · 2 cols · 0/2 mapped"
    }


def test_unchanged_save_one_is_a_whole_project_noop():
    editable, _ = _session_with_handoffs()
    before = get_session().model_dump(mode="json")

    response = _save_one(_card_payload(editable), original_name=editable.name)

    assert response.status_code == 200
    assert response.json()["source_of_truth_version"] == "7"
    assert get_session().model_dump(mode="json") == before


def test_spec_only_handoff_reference_survives_unchanged_save_one():
    session = get_session()
    session.app_archetype = "crud"
    session.project_revision = 3
    session.data_handoffs = [
        DataHandoff(
            name="reviewed-ddl",
            type="staging-table",
            spec="data-handoffs/reviewed-ddl.sql",
            entity_name="Account",
        )
    ]
    save_session(session)

    response = client.post(
        "/handoffs/save-one",
        json={
            "item": {
                "name": "reviewed-ddl",
                "type": "staging-table",
                "entity_name": "Account",
                "ddl_content": None,
                "field_mappings": [],
            },
            "original_name": "reviewed-ddl",
            "source_of_truth_version": "3",
        },
    )

    assert response.status_code == 200
    assert response.json()["source_of_truth_version"] == "3"
    assert get_session().data_handoffs[0].spec == "data-handoffs/reviewed-ddl.sql"


def test_save_one_rename_is_atomic_and_create_or_rename_collisions_are_rejected():
    editable, _ = _session_with_handoffs()
    renamed = _card_payload(editable)
    renamed["name"] = "account-stage-v2"

    response = _save_one(renamed, original_name="account-stage")

    assert response.status_code == 200
    assert [handoff.name for handoff in get_session().data_handoffs] == [
        "account-stage-v2",
        "audit-stage",
    ]

    reset_session()
    editable, _ = _session_with_handoffs()
    before = get_session().model_dump(mode="json")
    create_collision = _save_one(_card_payload(editable), original_name=None)
    assert create_collision.status_code == 400
    assert create_collision.json()["blockers"][0]["code"] == "duplicate-name"
    assert get_session().model_dump(mode="json") == before

    rename_collision_payload = _card_payload(editable)
    rename_collision_payload["name"] = "audit-stage"
    rename_collision = _save_one(rename_collision_payload, original_name="account-stage")
    assert rename_collision.status_code == 400
    assert rename_collision.json()["blockers"][0]["field_ref"] == "name"
    assert get_session().model_dump(mode="json") == before


def test_stale_version_returns_fresh_item_and_concurrent_save_allows_one_mutation():
    editable, _ = _session_with_handoffs()
    stale_payload = _card_payload(editable)
    stale_payload["system"] = "Stale"

    stale = _save_one(stale_payload, original_name=editable.name, version="6")

    assert stale.status_code == 409
    conflict = stale.json()
    assert conflict["item"]["system"] == "ETL"
    assert conflict["readiness"]["item_id"] == "handoff:account-stage"
    assert conflict["recovery"] == "review-current-item"
    assert conflict["source_of_truth_version"] == "7"

    barrier = threading.Barrier(3)
    responses = []
    response_lock = threading.Lock()

    def submit(system: str) -> None:
        payload = _card_payload(editable)
        payload["system"] = system
        barrier.wait(timeout=5)
        result = _save_one(payload, original_name=editable.name, version="7")
        with response_lock:
            responses.append(result)

    first = threading.Thread(target=submit, args=("Concurrent A",))
    second = threading.Thread(target=submit, args=("Concurrent B",))
    first.start()
    second.start()
    barrier.wait(timeout=5)
    first.join(timeout=5)
    second.join(timeout=5)

    assert sorted(response.status_code for response in responses) == [200, 409]
    assert {response.json()["source_of_truth_version"] for response in responses} == {"8"}


def test_stale_rename_never_recovers_an_unrelated_dirty_name_collision():
    session = get_session()
    session.app_archetype = "crud"
    session.project_revision = 9
    session.data_handoffs = [
        DataHandoff(name="draft-new-name", type="staging-table")
    ]
    save_session(session)

    response = client.post(
        "/handoffs/save-one",
        json={
            "item": {"name": "draft-new-name", "type": "staging-table"},
            "original_name": "removed-original",
            "source_of_truth_version": "8",
        },
    )

    assert response.status_code == 409
    conflict = response.json()
    assert conflict["item"] is None
    assert conflict["readiness"] is None
    assert conflict["recovery"] == "reload-current-list"
    assert conflict["current_items"] == [
        {"name": "draft-new-name", "type": "staging-table"}
    ]


@pytest.mark.parametrize("invalid_ddl", [None, {}, [], 42, True, "   "])
def test_save_one_cannot_erase_existing_ddl_with_an_invalid_generated_result(invalid_ddl):
    editable, _ = _session_with_handoffs()
    before = get_session().model_dump(mode="json")
    payload = _card_payload(editable)
    payload["ddl_content"] = invalid_ddl

    response = _save_one(payload, original_name=editable.name)

    assert response.status_code == 400
    blocker = response.json()["blockers"][0]
    assert blocker["field_ref"] == "ddl_content"
    assert blocker["section_ref"] == "ddl"
    if invalid_ddl is None or isinstance(invalid_ddl, str):
        assert "Generated DDL is required" in blocker["label"]
    else:
        assert blocker["label"] == "DDL content must be text."
    assert get_session().model_dump(mode="json") == before


def test_real_handoff_validation_errors_return_actionable_blockers_without_mutation():
    editable, _ = _session_with_handoffs()
    before = get_session().model_dump(mode="json")
    manual_mismatch = _card_payload(editable)
    manual_mismatch["ddl_content"] = _ddl("other_stage")

    mismatch = _save_one(manual_mismatch, original_name=editable.name)

    assert mismatch.status_code == 400
    mismatch_blockers = mismatch.json()["blockers"]
    assert mismatch_blockers
    assert {blocker["field_ref"] for blocker in mismatch_blockers} == {"ddl_content"}
    assert {blocker["section_ref"] for blocker in mismatch_blockers} == {"ddl"}
    assert get_session().model_dump(mode="json") == before

    bad_mapping = _card_payload(editable)
    bad_mapping["field_mappings"] = [
        {"source": "Account.missing", "target": "missing_column"}
    ]
    response = _save_one(bad_mapping, original_name=editable.name)
    assert response.status_code == 400
    blockers = response.json()["blockers"]
    assert all(set(blocker) == {"code", "label", "field_ref", "section_ref"} for blocker in blockers)
    assert {blocker["field_ref"] for blocker in blockers} == {"field_mappings"}
    assert {blocker["section_ref"] for blocker in blockers} == {"mappings"}
    assert get_session().model_dump(mode="json") == before


def test_real_400_field_refs_are_covered_by_the_editor_selector_map():
    editable, _ = _session_with_handoffs()
    bad_mapping = _card_payload(editable)
    bad_mapping["field_mappings"] = [
        {"source": "Account.missing", "target": "missing_column"}
    ]
    responses = [
        _save_one(bad_mapping, original_name=editable.name),
        _save_one({**_card_payload(editable), "ddl_content": _ddl("other")}, original_name=editable.name),
    ]
    field_refs = {
        blocker["field_ref"]
        for response in responses
        for blocker in response.json()["blockers"]
    }
    template = TEMPLATE.read_text(encoding="utf-8")
    map_start = template.index("const UXR_HANDOFF_FIELD_SELECTORS = {")
    map_end = template.index("};", map_start)
    selector_map = template[map_start:map_end]

    assert field_refs == {"ddl_content", "field_mappings"}
    for field_ref in field_refs:
        assert f"{field_ref}:" in selector_map


def test_blocker_classification_uses_exact_name_errors_not_name_substrings():
    required = handoffs_route._handoff_validation_blockers(["Handoff name is required."])[0]
    future = handoffs_route._handoff_validation_blockers(
        ["A future validation mentions a table name without a stable mapping."]
    )[0]

    assert (required["field_ref"], required["section_ref"]) == ("name", "identity")
    assert (future["field_ref"], future["section_ref"]) == ("ddl_content", "ddl")


def test_bulk_and_save_one_feed_identical_payload_to_shared_builder(monkeypatch):
    original_builder = handoffs_route._build_one_handoff
    captured: list[dict] = []

    def capture(raw, *, session, existing_handoffs):
        captured.append(raw)
        return original_builder(raw, session=session, existing_handoffs=existing_handoffs)

    monkeypatch.setattr(handoffs_route, "_build_one_handoff", capture)
    payload = {
        "name": "same-payload",
        "system": "ETL",
        "type": "staging-table",
        "entity_name": "Record",
        "table_name": "record_stage",
        "ddl_content": "CREATE TABLE record_stage (record_id VARCHAR(36));",
        "field_mappings": [{"source": "Record.recordId", "target": "record_id"}],
    }

    bulk = client.post("/handoffs/save", json={"handoffs": [payload]})
    assert bulk.status_code == 200
    reset_session()
    single = client.post(
        "/handoffs/save-one",
        json={"item": payload, "original_name": None},
    )
    assert single.status_code == 200
    assert captured == [payload, payload]


def test_legacy_whole_list_response_shape_is_unchanged():
    response = client.post(
        "/handoffs/save",
        json={
            "handoffs": [
                {
                    "name": "legacy-stage",
                    "type": "staging-table",
                    "table_name": "legacy_stage",
                    "ddl_content": "CREATE TABLE legacy_stage (id VARCHAR(36));",
                    "field_mappings": [],
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "count": 1, "warnings": []}
