"""PR-12 regression coverage for Step 5 focus mode and single-item saves."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.routes.downstream as downstream_route
from app.main import app
from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    DownstreamInterface,
    FieldMapping,
    IdentityRoleDecision,
    LayoutField,
)
from app.services import readiness_view
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)
ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "app" / "templates" / "step5_downstream.html"
STUDIO_JS = ROOT / "app" / "static" / "js" / "studio.js"


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _session_with_interfaces() -> tuple[DownstreamInterface, DownstreamInterface]:
    session = get_session()
    session.app_name = "Save One Fixture"
    session.bounded_context = "save-one-fixture"
    session.app_archetype = "crud"
    session.project_revision = 7
    editable = DownstreamInterface(
        name="account-xml",
        type="xml-xsd",
        version="v1",
        entity_name="Account",
        xsd_path="contracts/account.xsd",
        xsd_content="<xs:schema/>",
        root_element="AccountMessage",
        namespace="urn:account:v1",
        mapping_path="downstream/custom-account-mapping.yaml",
        field_mappings=[FieldMapping(source="Account.accountId", target="accountId")],
    )
    sibling = DownstreamInterface(
        name="audit-fixed",
        type="file-fixed-width",
        spec="downstream/audit-layout.yaml",
        spec_content="format: fixed-width\n",
        entity_name="Audit",
        layout_fields=[LayoutField(name="auditId", start=1, length=36)],
        field_mappings=[FieldMapping(source="Audit.auditId", target="auditId")],
    )
    session.downstream_interfaces = [editable, sibling]
    save_session(session)
    return editable, sibling


def _card_payload(iface: DownstreamInterface) -> dict:
    """Mirror the fields returned by the template's getCardData()."""
    return {
        "name": iface.name,
        "system": iface.system,
        "type": iface.type,
        "version": iface.version,
        "entity_name": iface.entity_name,
        "spec": iface.spec,
        "spec_content": iface.spec_content,
        "xsd_path": iface.xsd_path,
        "xsd_content": iface.xsd_content,
        "root_element": iface.root_element,
        "namespace": iface.namespace,
        "namespace_alias": iface.namespace_alias,
        "wsdl_path": iface.wsdl_path,
        "wsdl_content": iface.wsdl_content,
        "service": iface.service,
        "port": iface.port,
        "binding": iface.binding,
        "selected_operation_name": iface.selected_operation_name,
        "soap_operation_mode": iface.soap_operation_mode,
        "soap_canonical_invocation": (
            iface.soap_canonical_invocation.model_dump(mode="json")
            if iface.soap_canonical_invocation
            else None
        ),
        "sample_path": iface.sample_path,
        "layout_fields": [field.model_dump(mode="json") for field in iface.layout_fields],
        "field_mappings": [mapping.model_dump(mode="json") for mapping in iface.field_mappings],
        "sample_content": iface.sample_content,
        "csv_delimiter": None,
        "csv_has_header_row": None,
    }


def _save_one(payload: dict, *, original_name: str | None, version: str = "7"):
    return client.post(
        "/downstream/interface/save-one",
        json={
            "item": payload,
            "original_name": original_name,
            "source_of_truth_version": version,
        },
    )


def test_save_one_touches_only_selected_interface_and_returns_refresh_payload():
    editable, sibling = _session_with_interfaces()
    sibling_before = sibling.model_dump(mode="json")
    payload = _card_payload(editable)
    payload["namespace"] = "urn:account:v2"

    response = _save_one(payload, original_name=editable.name)

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["item"]["namespace"] == "urn:account:v2"
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
    assert data["board_metadata"] == {
        "artifact_path": "contracts/account.xsd",
        "family_fact": "root AccountMessage · urn:account:v2",
    }
    assert data["step_counts"]["5"] == {"count": 2, "attention": 0}
    assert any(entry == {"step": 5, "count": 2, "attention": 0} for entry in data["rail"])
    assert data["source_of_truth_version"] == "8"

    saved = get_session()
    assert saved.downstream_interfaces[1].model_dump(mode="json") == sibling_before
    expected = asdict(readiness_view.item(saved, "dsi:account-xml"))
    assert data["readiness"] == expected


def test_save_one_returns_fresh_board_metadata_after_adding_layout_path():
    _editable, sibling = _session_with_interfaces()
    session = get_session()
    saved_sibling = next(iface for iface in session.downstream_interfaces if iface.name == sibling.name)
    saved_sibling.spec = None
    saved_sibling.spec_content = None
    save_session(session)

    payload = _card_payload(saved_sibling)
    payload["spec"] = "downstream/new-layout.yaml"
    payload["spec_content"] = "format: fixed-width\n"

    response = _save_one(payload, original_name=saved_sibling.name)

    assert response.status_code == 200
    assert response.json()["board_metadata"] == {
        "artifact_path": "downstream/new-layout.yaml",
        "family_fact": "1 col · 1/1 mapped",
    }


def test_save_one_rename_replaces_original_atomically_without_changing_count():
    editable, _ = _session_with_interfaces()
    payload = _card_payload(editable)
    payload["name"] = "account-xml-v2"

    response = _save_one(payload, original_name="account-xml")

    assert response.status_code == 200
    names = [iface.name for iface in get_session().downstream_interfaces]
    assert names == ["account-xml-v2", "audit-fixed"]
    assert response.json()["readiness"]["item_id"] == "dsi:account-xml-v2"


def _seed_single_downstream(iface: DownstreamInterface) -> DownstreamInterface:
    session = get_session()
    session.app_name = "F4 Fixture"
    session.bounded_context = "f4-fixture"
    session.app_archetype = "crud"
    session.project_revision = 7
    session.downstream_interfaces = [iface]
    save_session(session)
    return iface


def test_rename_regenerates_auto_derived_paths_from_the_new_name():
    """E2E Finding 4: when the persisted paths were the STUDIO-DERIVED defaults
    for the old name (the common case for a visually-authored contract), a
    rename must regenerate them from the new identity so the manifest stops
    referencing downstream/<old-name>-*.yaml. Content is preserved."""
    iface = DownstreamInterface(
        name="account-xml",
        type="xml-xsd",
        entity_name="Account",
        xsd_path="downstream/account-xml-schema.xsd",  # == default for this identity
        xsd_content="<xs:schema/>",
        root_element="AccountMessage",
        namespace="urn:account:v1",
        mapping_path="downstream/account-xml-mapping.yaml",  # == default
        field_mappings=[FieldMapping(source="Account.accountId", target="accountId")],
    )
    _seed_single_downstream(iface)
    payload = _card_payload(iface)
    payload["name"] = "account-xml-v2"

    response = _save_one(payload, original_name="account-xml")
    assert response.status_code == 200, response.text

    renamed = next(i for i in get_session().downstream_interfaces if i.name == "account-xml-v2")
    assert renamed.mapping_path == "downstream/account-xml-v2-mapping.yaml"
    assert renamed.xsd_path == "downstream/account-xml-v2-schema.xsd"
    assert "account-xml-mapping" not in (renamed.mapping_path or "")
    # The reviewed XSD content rides along unchanged.
    assert renamed.xsd_content == "<xs:schema/>"


def test_rename_preserves_custom_and_reference_artifact_paths():
    """The reviewer's counter-case: paths that are NOT the identity default --
    a custom mapping_path and an author-supplied reference XSD -- are editable,
    persisted state and must survive a rename untouched."""
    editable, _ = _session_with_interfaces()  # custom mapping + contracts/account.xsd
    assert editable.mapping_path == "downstream/custom-account-mapping.yaml"
    payload = _card_payload(editable)
    payload["name"] = "account-xml-v2"

    response = _save_one(payload, original_name="account-xml")
    assert response.status_code == 200, response.text

    renamed = next(i for i in get_session().downstream_interfaces if i.name == "account-xml-v2")
    assert renamed.mapping_path == "downstream/custom-account-mapping.yaml"
    assert renamed.xsd_path == "contracts/account.xsd"


def test_reference_only_xml_rename_succeeds_without_dropping_the_reference():
    """Regression for the P1 in the first cut: a reference-only xml-xsd contract
    (xsd_path points at an author-managed schema, no pasted content) must rename
    without a 400 -- the earlier blanket drop removed xsd_path before validation
    and the save failed with 'require xsd_path or uploaded XSD content'."""
    iface = DownstreamInterface(
        name="account-ref",
        type="xml-xsd",
        entity_name="Account",
        xsd_path="contracts/shared-account-schema.xsd",
        root_element="Account",
        namespace="urn:account",
        field_mappings=[FieldMapping(source="Account.accountId", target="accountId")],
    )
    _seed_single_downstream(iface)
    payload = _card_payload(iface)
    payload["name"] = "account-ref-v2"

    response = _save_one(payload, original_name="account-ref")
    assert response.status_code == 200, response.text

    renamed = next(i for i in get_session().downstream_interfaces if i.name == "account-ref-v2")
    assert renamed.xsd_path == "contracts/shared-account-schema.xsd"


def test_type_change_keeps_a_newly_submitted_artifact_path():
    """Regression for the second P1: converting fixed-width -> CSV while the
    client submits a NEW spec path must keep that path, not discard it."""
    iface = DownstreamInterface(
        name="audit",
        type="file-fixed-width",
        entity_name="Audit",
        spec="downstream/audit-layout.yaml",
        spec_content="format: fixed-width\n",
        layout_fields=[LayoutField(name="auditId", start=1, length=36)],
        field_mappings=[FieldMapping(source="Audit.auditId", target="auditId")],
    )
    _seed_single_downstream(iface)
    payload = _card_payload(iface)
    payload["type"] = "file-csv"
    payload["spec"] = "contracts/reviewed-csv-layout.yaml"  # explicit new path
    payload["spec_content"] = (
        "format: csv\ndelimiter: \",\"\nhas_header_row: true\n"
        "record_types:\n  data:\n    fields:\n      - name: auditId\n        column: 1\n"
    )
    payload["layout_fields"] = []

    response = _save_one(payload, original_name="audit")
    assert response.status_code == 200, response.text

    converted = next(i for i in get_session().downstream_interfaces if i.name == "audit")
    assert converted.type == "file-csv"
    assert converted.spec == "contracts/reviewed-csv-layout.yaml"


def test_type_change_from_auto_derived_paths_refreshes_manifest_identity():
    """The end-to-end goal: converting a contract whose paths were auto-derived
    leaves the exported manifest referencing only the new identity -- no stale
    fixed-width mapping filename survives (E2E Finding 4)."""
    import tempfile
    from pathlib import Path

    import yaml

    from app.services.package_writer import write_package

    iface = DownstreamInterface(
        name="audit-fixed",
        type="file-fixed-width",
        entity_name="Audit",
        spec="downstream/audit-fixed-layout.yaml",  # == default
        spec_content="format: fixed-width\n",
        mapping_path="downstream/audit-fixed-mapping.yaml",  # == default
        layout_fields=[LayoutField(name="auditId", start=1, length=36)],
        field_mappings=[FieldMapping(source="Audit.auditId", target="auditId")],
    )
    _seed_single_downstream(iface)
    payload = _card_payload(iface)
    payload["name"] = "audit-daily"
    payload["type"] = "file-csv"
    payload["spec_content"] = (
        "format: csv\ndelimiter: \",\"\nhas_header_row: true\n"
        "record_types:\n  data:\n    fields:\n      - name: auditId\n        column: 1\n"
    )
    payload["layout_fields"] = []

    response = _save_one(payload, original_name="audit-fixed")
    assert response.status_code == 200, response.text

    converted = next(i for i in get_session().downstream_interfaces if i.name == "audit-daily")
    assert converted.type == "file-csv"

    with tempfile.TemporaryDirectory() as tmp:
        write_package(get_session(), Path(tmp))
        project_dir = next(Path(tmp).iterdir())
        manifest = yaml.safe_load((project_dir / "app-definition.yaml").read_text())
        entry = next(d for d in manifest["downstream_interfaces"] if d["name"] == "audit-daily")
        assert "audit-daily" in (entry.get("mapping") or "")
        assert "audit-fixed" not in (entry.get("mapping") or "")
        assert "audit-fixed" not in yaml.safe_dump(manifest)


def test_create_collision_is_rejected_without_overwriting_existing_item():
    editable, _ = _session_with_interfaces()
    before = get_session().model_dump(mode="json")
    payload = _card_payload(editable)
    payload["version"] = "v2"

    response = _save_one(payload, original_name=None)

    assert response.status_code == 400
    assert response.json()["blockers"][0]["code"] == "duplicate-name"
    assert get_session().model_dump(mode="json") == before


def test_rename_collision_is_rejected_without_overwriting_sibling():
    editable, _ = _session_with_interfaces()
    before = get_session().model_dump(mode="json")
    payload = _card_payload(editable)
    payload["name"] = "audit-fixed"

    response = _save_one(payload, original_name="account-xml")

    assert response.status_code == 400
    assert response.json()["blockers"] == [
        {
            "code": "duplicate-name",
            "label": "A downstream interface named 'audit-fixed' already exists.",
            "field_ref": "name",
            "section_ref": "contract",
        }
    ]
    assert get_session().model_dump(mode="json") == before


def test_invalid_save_one_returns_deep_link_blocker_shape_without_mutation():
    _session_with_interfaces()
    before = get_session().model_dump(mode="json")

    response = _save_one(
        {"name": "broken-xml", "type": "xml-xsd"},
        original_name=None,
    )

    assert response.status_code == 400
    data = response.json()
    assert data["ok"] is False
    assert data["blockers"]
    for blocker in data["blockers"]:
        assert set(blocker) == {"code", "label", "field_ref", "section_ref"}
        assert blocker["code"]
        assert blocker["label"]
        assert blocker["field_ref"]
        assert blocker["section_ref"] == "xsd"
    assert get_session().model_dump(mode="json") == before


def test_unchanged_save_one_is_a_whole_project_noop():
    editable, _ = _session_with_interfaces()
    before = get_session().model_dump(mode="json")

    response = _save_one(_card_payload(editable), original_name=editable.name)

    assert response.status_code == 200
    assert response.json()["source_of_truth_version"] == "7"
    assert get_session().model_dump(mode="json") == before


def test_stale_source_version_returns_409_with_fresh_readiness_and_no_mutation():
    editable, _ = _session_with_interfaces()
    before = get_session().model_dump(mode="json")
    payload = _card_payload(editable)
    payload["namespace"] = "urn:stale-edit"

    response = _save_one(payload, original_name=editable.name, version="6")

    assert response.status_code == 409
    data = response.json()
    assert data["ok"] is False
    assert data["item"]["name"] == "account-xml"
    assert data["item"]["namespace"] == "urn:account:v1"
    assert data["readiness"]["item_id"] == "dsi:account-xml"
    assert data["recovery"] == "review-current-item"
    assert data["source_of_truth_version"] == "7"
    assert get_session().model_dump(mode="json") == before


def test_real_intervening_save_advances_version_and_makes_second_editor_stale():
    editable, _ = _session_with_interfaces()
    first_payload = _card_payload(editable)
    first_payload["namespace"] = "urn:first-editor"
    second_payload = _card_payload(editable)
    second_payload["namespace"] = "urn:second-editor"

    first = _save_one(first_payload, original_name=editable.name, version="7")
    second = _save_one(second_payload, original_name=editable.name, version="7")

    assert first.status_code == 200
    assert first.json()["source_of_truth_version"] == "8"
    assert second.status_code == 409
    conflict = second.json()
    assert conflict["source_of_truth_version"] == "8"
    assert conflict["item"]["namespace"] == "urn:first-editor"
    assert conflict["readiness"]["source_of_truth_version"] == "8"
    assert get_session().downstream_interfaces[0].namespace == "urn:first-editor"


def test_concurrent_same_version_save_one_allows_exactly_one_mutation():
    editable, _ = _session_with_interfaces()
    barrier = threading.Barrier(3)
    responses: list = []
    response_lock = threading.Lock()

    def submit(namespace: str) -> None:
        payload = _card_payload(editable)
        payload["namespace"] = namespace
        barrier.wait(timeout=5)
        response = _save_one(payload, original_name=editable.name, version="7")
        with response_lock:
            responses.append(response)

    first = threading.Thread(target=submit, args=("urn:concurrent-a",))
    second = threading.Thread(target=submit, args=("urn:concurrent-b",))
    first.start()
    second.start()
    barrier.wait(timeout=5)
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert {response.json()["source_of_truth_version"] for response in responses} == {"8"}
    saved_namespace = get_session().downstream_interfaces[0].namespace
    assert saved_namespace in {"urn:concurrent-a", "urn:concurrent-b"}
    conflict = next(response.json() for response in responses if response.status_code == 409)
    assert conflict["item"]["namespace"] == saved_namespace


def test_stale_editor_after_concurrent_rename_gets_current_list_recovery():
    editable, _ = _session_with_interfaces()
    winning_payload = _card_payload(editable)
    winning_payload["name"] = "account-xml-current"
    stale_payload = _card_payload(editable)
    stale_payload["name"] = "account-xml-draft"

    winning = _save_one(winning_payload, original_name="account-xml", version="7")
    stale = _save_one(stale_payload, original_name="account-xml", version="7")

    assert winning.status_code == 200
    assert stale.status_code == 409
    conflict = stale.json()
    assert conflict["item"] is None
    assert conflict["readiness"] is None
    assert conflict["recovery"] == "reload-current-list"
    assert conflict["source_of_truth_version"] == "8"
    assert {item["name"] for item in conflict["current_items"]} == {
        "account-xml-current",
        "audit-fixed",
    }


def test_bulk_and_save_one_feed_byte_identical_item_payload_to_shared_builder(monkeypatch):
    original_builder = downstream_route._build_downstream_interface
    captured: list[dict] = []

    def capture(raw, *, session):
        captured.append(raw)
        return original_builder(raw, session=session)

    monkeypatch.setattr(downstream_route, "_build_downstream_interface", capture)
    payload = {
        "name": "same-payload",
        "type": "file-csv",
        "spec": "downstream/same-payload.yaml",
        "spec_content": (
            "format: csv\n"
            "delimiter: '|'\n"
            "has_header_row: true\n"
            "record_types:\n"
            "  data:\n"
            "    fields:\n"
            "      - name: id\n"
            "        column: 1\n"
        ),
        "entity_name": "Record",
        "field_mappings": [{"source": "Record.id", "target": "id"}],
        "csv_delimiter": "|",
        "csv_has_header_row": "true",
    }

    bulk = client.post("/downstream/save", json={"interfaces": [payload]})
    assert bulk.status_code == 200
    reset_session()
    single = client.post(
        "/downstream/interface/save-one",
        json={"item": payload, "original_name": None},
    )
    assert single.status_code == 200
    assert captured == [payload, payload]


@pytest.mark.parametrize("focus", ["missing", None])
def test_flag_on_unknown_or_absent_focus_renders_board_mode(monkeypatch, focus):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _session_with_interfaces()
    url = "/downstream" if focus is None else f"/downstream?focus={focus}"

    html = client.get(url).text

    assert 'data-uxr-board="downstream"' in html
    assert "data-uxr-focus-editor=" not in html


def test_known_focus_renders_split_editor_from_readiness(monkeypatch):
    # PR-17 gives EDGEFORGE_STUDIO_UX_SPLIT its first real consumer -- pin it
    # off explicitly rather than letting this test's "single-panel" scenario
    # (by definition the split-off case) silently depend on whatever the
    # ambient process env happens to be. Before PR-17, ux_split had no
    # template consumer at all, so this test passed regardless of the
    # variable's value; a whole-suite run with EDGEFORGE_STUDIO_UX_SPLIT=true
    # in the outer shell env would otherwise now flip this into split mode
    # and fail the assertion below for the wrong reason.
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "false")
    _session_with_interfaces()

    response = client.get("/downstream?focus=account-xml")
    html = response.text

    assert response.status_code == 200
    assert 'data-uxr-focus-editor="account-xml"' in html
    assert 'data-source-of-truth-version="7"' in html
    assert 'data-uxr-save-one' in html
    assert 'data-uxr-cancel-focus' in html
    assert 'data-uxr-tab-badges' in html
    assert 'data-uxr-board="downstream"' in html
    assert 'data-uxr-split="true"' in html
    assert "Save &amp; Continue" not in html


def test_focus_mode_preserves_large_repeated_layout_payload(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = get_session()
    session.app_archetype = "crud"
    session.downstream_interfaces = [
        DownstreamInterface(
            name="large-fixed",
            type="file-fixed-width",
            spec="downstream/large-fixed.yaml",
            spec_content="format: fixed-width\n",
            layout_fields=[
                LayoutField(name=f"field_{index}", start=index + 1, length=1)
                for index in range(55)
            ],
        )
    ]
    save_session(session)

    html = client.get("/downstream?focus=large-fixed").text

    assert 'data-uxr-focus-editor="large-fixed"' in html
    start = html.index("const existing = ") + len("const existing = ")
    restored = json.loads(html[start : html.index(";", start)])
    assert [field["name"] for field in restored[0]["layout_fields"]] == [
        f"field_{index}" for index in range(55)
    ]


def test_retired_flag_off_value_still_honors_focus_query(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    _session_with_interfaces()

    html = client.get("/downstream?focus=account-xml").text

    assert 'data-uxr-focus-editor="account-xml"' in html
    assert 'data-uxr-split="true"' in html
    assert 'onclick="saveAll()">Save &amp; Continue' not in html
    assert "uxrSaveFocusedInterface" in html


def test_static_client_contract_preserves_cancel_dirty_and_single_payload_paths():
    template = TEMPLATE.read_text(encoding="utf-8")
    studio_js = STUDIO_JS.read_text(encoding="utf-8")

    assert "function createDirtyTracker({ snapshot })" in studio_js
    assert "window.addEventListener('beforeunload'" in studio_js
    assert "const isDirty = () => JSON.stringify(snapshot())" in studio_js
    assert "document.addEventListener('click', guardNavigation, true)" in studio_js
    assert "data-dirty-navigation" in template
    assert "uxrDirtyTracker?.isDirty()" in template
    assert "uxrRestoreFocusedCardFromSaved();" in template
    assert "itemPayload = getCardData(card)" in template
    assert "item: itemPayload" in template
    assert "async function saveNewInterfaces()" in template
    assert "postJSON('/downstream/save'" not in template
    assert "postJSON('/downstream/interface/save-one'" in template
    assert "uxrUpdateBoardRowFromSaved(data.readiness" in template
    assert "uxrRenderEditorReadiness(data.readiness)" in template
    assert "uxrUpdateAmbientAndRail(data)" in template
    # PR-17a item 6: Edit is now a real <a href> link -- native navigation
    # replaces the old programmatic window.location.href click handler,
    # which also makes it dirty-guardable via studio.js's guardNavigation
    # (it only matches a[href] / [data-dirty-navigation], never a bare
    # <button>, and a programmatic assignment can't be intercepted anyway).
    assert "window.location.href = button.dataset.uxrFocusUrl" not in template
    assert "['ArrowDown', 'ArrowUp']" in template
    assert ".uxr-board-row:not(.hidden) [data-uxr-edit-target]" in template
    assert "uxrLastSavedItem = JSON.parse(JSON.stringify(data.item))" in template
    assert "uxrRenderEditorReadiness(data.readiness)" in template
    focused_save_start = template.index("async function uxrSaveFocusedInterface()")
    conflict_start = template.index("if (!data.ok)", focused_save_start)
    conflict_end = template.index("uxrRenderSaveBlockers(data.blockers)", conflict_start)
    conflict_branch = template[conflict_start:conflict_end]
    assert "uxrPresentSaveConflict(data)" in conflict_branch
    assert "uxrRestoreFocusedCardFromSaved()" not in conflict_branch
    assert "function uxrReloadConflictServerItem()" in template
    assert "function uxrReturnToCurrentBoard()" in template
    assert "data-uxr-conflict-reload" in template
    assert "data-uxr-conflict-board" in template
    assert 'role="status" aria-live="polite"' in template
    assert "if (confirmedDeparture || !isDirty()) return" in studio_js
    assert "confirmedDeparture = true" in studio_js


def test_board_edit_control_is_a_real_link_and_updater_sets_href_not_dataset():
    """PR-17a item 6: the board Edit control is now a real <a href> link
    (mirroring Step 2's already-correct precedent at step2_upstream.html:193),
    not a JS-navigated <button data-uxr-focus-url>. uxrUpdateBoardRowFromSaved
    (called after a rename) must therefore update the link's href directly --
    a now-nonexistent data-uxr-focus-url dataset property would silently
    no-op instead of updating the link."""
    template = TEMPLATE.read_text(encoding="utf-8")

    assert (
        '<a href="/downstream?focus={{ item.display_name | urlencode }}" '
        'class="uxr-board-edit-btn" data-uxr-edit-target="{{ item.display_name }}">Edit</a>'
    ) in template
    assert "data-uxr-focus-url" not in template
    macro_start = template.index("{% macro uxr_ds_row")
    macro_end = template.index("{% endmacro %}", macro_start)
    assert "<button" not in template[macro_start:macro_end], (
        "the row macro's Edit control must be a real <a>, not a <button>"
    )

    fn_start = template.index("function uxrUpdateBoardRowFromSaved")
    fn_end = template.index("\n}", fn_start)
    fn_body = template[fn_start:fn_end]
    assert "edit.href = `/downstream?focus=${encodeURIComponent(readiness.display_name)}`;" in fn_body


def test_updater_repaints_the_family_tile_on_a_type_change():
    """E2E Finding 5: changing a downstream contract's type (e.g. fixed-width
    -> CSV) and saving left the board row's family monogram tile still showing
    the old family until a full reload. readiness.family already reflects the
    new type in the save-one response (readiness_view._family_for_contract_type),
    so this is a client-only gap: uxrUpdateBoardRowFromSaved updated the
    data-uxr-row-family attribute but never repainted the visible .uxr-fam-tile
    (class + monogram + aria-label). Mirrors Step 2's already-correct block at
    step2_upstream.html (UXR_UPSTREAM_FAMILY_* + the tile rewrite)."""
    template = TEMPLATE.read_text(encoding="utf-8")

    # JS-side family maps exist (Jinja uxr_family_mono/label are not reachable
    # from the client updater). Downstream board rows only ever carry the four
    # edge-contract families.
    assert "const UXR_DOWNSTREAM_FAMILY_MONO = { fixed: 'FIX', csv: 'CSV', xml: 'XML', soap: 'SOAP' };" in template
    assert "const UXR_DOWNSTREAM_FAMILY_LABEL = {" in template

    fn_start = template.index("function uxrUpdateBoardRowFromSaved")
    fn_end = template.index("\n}", fn_start)
    fn_body = template[fn_start:fn_end]

    # The tile's class, monogram text, and aria-label are all repainted from
    # readiness.family -- not just the invisible data attribute.
    assert "const tile = row.querySelector('.uxr-fam-tile');" in fn_body
    assert "tile.className = `uxr-fam-tile uxr-fam-${readiness.family}`;" in fn_body
    assert "UXR_DOWNSTREAM_FAMILY_MONO[readiness.family]" in fn_body
    assert "UXR_DOWNSTREAM_FAMILY_LABEL[readiness.family]" in fn_body
    assert "tile.setAttribute('aria-label'," in fn_body
    assert "edit.dataset.uxrFocusUrl" not in fn_body


def test_save_one_validation_blocker_field_refs_match_the_clients_selector_map():
    """Regression for a re-review finding on PR #250: a save-one validation
    failure (400) previously rendered only a plain warning list -- the
    locked contract (implementation-design.md L143-144) requires it to also
    drive tab badges + field focus. This resolves field_ref via a SEPARATE
    map from the one readiness_view blockers use (UXR_SAVE_BLOCKER_FIELD_
    SELECTORS): _validation_blockers (app/routes/downstream.py) keys
    field_ref by the raw payload field name, not a slugified label. Verified
    against a real 400 response rather than a hand-written expectation."""
    _session_with_interfaces()
    template = TEMPLATE.read_text(encoding="utf-8")
    map_start = template.index("const UXR_SAVE_BLOCKER_FIELD_SELECTORS = {")
    map_end = template.index("};", map_start)
    map_body = template[map_start:map_end]

    response = _save_one({"name": "broken-xml", "type": "xml-xsd"}, original_name=None)
    assert response.status_code == 400
    blockers = response.json()["blockers"]
    field_refs = {blocker["field_ref"] for blocker in blockers}
    assert field_refs == {"xsd_path", "root_element"}
    for field_ref in field_refs:
        assert f"{field_ref}:" in map_body, f"{field_ref!r} missing from UXR_SAVE_BLOCKER_FIELD_SELECTORS"

    assert "xsd_path: '.iface-xsd-path'" in map_body
    assert "root_element: '.iface-root-element'" in map_body
    assert 'class="iface-xsd-path"' in template
    assert 'class="iface-root-element"' in template


def test_save_one_missing_wsdl_path_field_ref_matches_the_clients_selector_map():
    _session_with_interfaces()
    response = _save_one({"name": "broken-wsdl", "type": "soap-wsdl"}, original_name=None)

    assert response.status_code == 400
    blockers = response.json()["blockers"]
    assert any(blocker["field_ref"] == "wsdl_path" for blocker in blockers)

    template = TEMPLATE.read_text(encoding="utf-8")
    assert "wsdl_path: '.iface-wsdl-path'" in template
    assert 'class="iface-wsdl-path"' in template


def test_save_one_missing_name_field_ref_matches_the_clients_selector_map():
    _session_with_interfaces()
    response = _save_one({"name": "", "type": "xml-xsd"}, original_name=None)

    assert response.status_code == 400
    blockers = response.json()["blockers"]
    assert any(blocker["field_ref"] == "name" for blocker in blockers)

    template = TEMPLATE.read_text(encoding="utf-8")
    assert "name: '.iface-name'" in template
    assert 'class="iface-name"' in template


def test_canonical_soap_validation_blocker_focuses_the_canonical_entity_control():
    """A real canonical-mode 400 must name an editable control, not the
    section-only ``wsdl`` fallback that can scroll but cannot focus."""
    _session_with_interfaces()
    response = _save_one(
        {
            "name": "broken-canonical-soap",
            "type": "soap-wsdl",
            "wsdl_path": "contracts/broken.wsdl",
            "selected_operation_name": "SyncRecord",
            "soap_operation_mode": "canonical",
            "soap_canonical_invocation": {
                "kind": "invoke_by_id",
                "entity": None,
                "lookup": {"request_field": "id", "field": None},
                "request_mappings": [],
                "response": {"mode": "return_only", "response_mappings": []},
            },
        },
        original_name=None,
    )

    assert response.status_code == 400
    blockers = response.json()["blockers"]
    config_blocker = next(
        blocker
        for blocker in blockers
        if "canonical invocation configuration" in blocker["label"].lower()
    )
    assert config_blocker["section_ref"] == "wsdl"
    assert config_blocker["field_ref"] == "soap_canonical_entity"

    template = TEMPLATE.read_text(encoding="utf-8")
    assert "soap_canonical_entity: '.soap-canonical-entity'" in template
    assert 'class="soap-canonical-entity"' in template


def test_canonical_soap_nested_validation_refs_all_resolve_to_real_controls():
    """Exercise the non-empty config path so lookup and both mapping
    families cannot silently regress to the section-only fallback."""
    _session_with_interfaces()
    response = _save_one(
        {
            "name": "incomplete-canonical-soap",
            "type": "soap-wsdl",
            "wsdl_path": "contracts/incomplete.wsdl",
            "selected_operation_name": "SyncRecord",
            "soap_operation_mode": "canonical",
            "soap_canonical_invocation": {
                "kind": "invoke_by_id",
                "entity": "Record",
                "lookup": {"request_field": "id", "field": None},
                "request_mappings": [],
                "response": {"mode": "return_only", "response_mappings": []},
            },
        },
        original_name=None,
    )

    assert response.status_code == 400
    blockers = response.json()["blockers"]
    field_refs = {blocker["field_ref"] for blocker in blockers}
    assert {
        "soap_lookup_field",
        "soap_request_mappings",
        "soap_response_mappings",
        "soap_canonical_entity",
    } <= field_refs
    assert "wsdl" not in field_refs

    template = TEMPLATE.read_text(encoding="utf-8")
    selector_start = template.index("const UXR_SAVE_BLOCKER_FIELD_SELECTORS = {")
    selector_end = template.index("};", selector_start)
    selector_map = template[selector_start:selector_end]
    for field_ref in field_refs:
        assert f"{field_ref}:" in selector_map

    assert 'class="soap-lookup-field"' in template
    assert 'class="soap-request-source"' in template
    assert 'class="soap-response-source-path"' in template


def test_canonical_soap_mapping_errors_take_precedence_over_generic_name_and_type_words():
    """Real validator messages contain generic words such as ``type`` and
    ``field name``; those must focus the mapping controls, not the contract's
    top-level type/name inputs."""
    _session_with_interfaces()
    session = get_session()
    session.classified_entities = [
        ClassifiedEntity(
            name="Customer",
            classification="entity",
            fields=[
                ClassifiedField(name="customerId", type="string", is_id=True),
                ClassifiedField(name="status", type="decimal"),
            ],
        )
    ]
    session.identity_role_decisions = [
        IdentityRoleDecision(entity="Customer", field="customerId", role="persistence_id")
    ]
    save_session(session)

    response = _save_one(
        {
            "name": "invalid-mapping-soap",
            "type": "soap-wsdl",
            "wsdl_path": "contracts/invalid-mapping.wsdl",
            "selected_operation_name": "syncCustomer",
            "soap_operation_mode": "canonical",
            "soap_operation_candidates": [
                {
                    "name": "syncCustomer",
                    "input_fields": [
                        {
                            "path": "/SyncCustomerRequest/status",
                            "type": "boolean",
                            "required": True,
                        }
                    ],
                    "output_fields": [
                        {
                            "path": "/SyncCustomerResponse/resultCode",
                            "type": "string",
                            "required": True,
                        }
                    ],
                }
            ],
            "soap_canonical_invocation": {
                "kind": "invoke_by_id",
                "entity": "Customer",
                "lookup": {"request_field": "id", "field": "customerId"},
                "request_mappings": [
                    {
                        "source": "Customer.status",
                        "target_path": "/SyncCustomerRequest/status",
                    }
                ],
                "response": {
                    "mode": "return_only",
                    "response_mappings": [
                        {
                            "source_path": "/SyncCustomerResponse/resultCode",
                            "target": "result-code",
                        }
                    ],
                },
            },
        },
        original_name=None,
    )

    assert response.status_code == 400
    blockers = response.json()["blockers"]
    request_type = next(
        blocker for blocker in blockers if "is not compatible" in blocker["label"]
    )
    response_name = next(
        blocker for blocker in blockers if "not a supported response field name" in blocker["label"]
    )
    assert request_type["field_ref"] == "soap_request_mappings"
    assert response_name["field_ref"] == "soap_response_mappings"
    assert request_type["field_ref"] != "type"
    assert response_name["field_ref"] != "name"


def test_save_one_validation_failure_rebuilds_tab_badges_and_focuses_first_field():
    """Static source check (this repo has no jsdom, per the existing
    precedent in test_step5_tab_badge_focus.py) that uxrRenderSaveBlockers
    -- the 400-path handler -- rebuilds [data-uxr-tab-badges] from the
    blockers array (same element/shape uxrRenderEditorReadiness uses for a
    successful save) and scrolls/focuses the first blocker's field via the
    same shared helpers the badge-click and on-load-hash paths use."""
    template = TEMPLATE.read_text(encoding="utf-8")
    start = template.index("function uxrRenderSaveBlockers(blockers)")
    end = template.index("\n}\n", start)
    body = template[start:end]

    assert "document.querySelector('[data-uxr-tab-badges]')" in body
    assert "badges.replaceChildren()" in body
    assert "badge.dataset.sectionRef = blocker.section_ref" in body
    assert "badge.dataset.fieldRef = blocker.field_ref" in body

    assert "uxrFocusedCard()" in body
    assert "uxrScrollToSectionInCard(card, first.section_ref" in body
    assert "uxrFieldRefSelector(card, first.field_ref" in body
    assert "card.querySelector(selector)?.focus();" in body


def test_reference_only_path_matching_the_default_filename_is_preserved():
    """P2 (second review round): a reference-only contract whose author-supplied
    path happens to equal Studio's default derived filename must still be
    preserved on rename -- it has no generated content, so dropping it fails
    validation. `existing_value == old_default` alone can't distinguish a
    generated default from a coincidentally-named reference; the interface
    having the content Studio would write is what makes a path 'generated'."""
    iface = DownstreamInterface(
        name="account-ref",
        type="xml-xsd",
        entity_name="Account",
        # exactly the default for this identity, but a reference (no xsd_content).
        xsd_path="downstream/account-ref-schema.xsd",
        root_element="Account",
        namespace="urn:account",
        field_mappings=[FieldMapping(source="Account.accountId", target="accountId")],
    )
    _seed_single_downstream(iface)
    payload = _card_payload(iface)
    payload["name"] = "account-ref-v2"

    response = _save_one(payload, original_name="account-ref")
    assert response.status_code == 200, response.text
    renamed = next(i for i in get_session().downstream_interfaces if i.name == "account-ref-v2")
    assert renamed.xsd_path == "downstream/account-ref-schema.xsd"


def test_soap_rename_refreshes_the_operation_mapping_in_the_export():
    """P2 (third review round): a SOAP downstream mapping is generated from
    selected_operation_name, not field_mappings, so the content gate that
    decides whether mapping_path is regenerable must use that signal. Without
    it a SOAP rename kept the old-name operation mapping, and export wrote and
    referenced mappings/<old-name>-operation-mapping.yaml."""
    import tempfile
    from pathlib import Path

    import yaml

    from app.services.package_writer import write_package

    iface = DownstreamInterface(
        name="account-soap",
        type="soap-wsdl",
        entity_name="Account",
        wsdl_path="contracts/account.wsdl",
        wsdl_content="<definitions/>",
        service="AccountService",
        port="AccountPort",
        binding="AccountBinding",
        selected_operation_name="syncAccount",
        mapping_path="mappings/account-soap-operation-mapping.yaml",  # == default, no field_mappings
    )
    _seed_single_downstream(iface)
    payload = _card_payload(iface)
    payload["name"] = "account-soap-v2"

    response = _save_one(payload, original_name="account-soap")
    assert response.status_code == 200, response.text

    with tempfile.TemporaryDirectory() as tmp:
        write_package(get_session(), Path(tmp))
        project_dir = next(Path(tmp).iterdir())
        manifest = yaml.safe_load((project_dir / "app-definition.yaml").read_text())
        entry = next(d for d in manifest["downstream_interfaces"] if d["name"] == "account-soap-v2")
        assert entry.get("mapping") == "mappings/account-soap-v2-operation-mapping.yaml"
        assert "account-soap-operation-mapping.yaml" not in yaml.safe_dump(manifest)
        written = [str(p.relative_to(project_dir)) for p in project_dir.rglob("*") if p.is_file()]
        assert not any("account-soap-operation-mapping.yaml" in f for f in written)
