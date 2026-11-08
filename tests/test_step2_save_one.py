"""PR-15 regression coverage for Step 2 focused upstream saves."""

from __future__ import annotations

import threading
from dataclasses import asdict
from pathlib import Path

from fastapi.testclient import TestClient

import app.routes.downstream as downstream_route
from app.main import app
from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    FieldMapping,
    IdentityRoleDecision,
    OperationMapping,
    OperationSample,
    SoapCanonicalOperationConfig,
    SoapResponseMapping,
    UpstreamInterface,
)
from app.services import readiness_view
from app.services.edge_contracts import edge_contract_validation_blockers
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)
ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "app" / "templates" / "step2_upstream.html"


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _session_with_interfaces() -> tuple[UpstreamInterface, UpstreamInterface]:
    session = get_session()
    session.app_name = "Upstream Save One Fixture"
    session.bounded_context = "upstream-save-one-fixture"
    session.app_archetype = "crud"
    session.project_revision = 7
    editable = UpstreamInterface(
        name="account-xml",
        type="xml-xsd",
        version="v1",
        entity_name="Account",
        xsd_path="contracts/account.xsd",
        xsd_content="<xs:schema/>",
        root_element="AccountMessage",
        namespace="urn:account:v1",
        mapping_path="upstream/custom-account-mapping.yaml",
        field_mappings=[FieldMapping(source="accountId", target="Account.accountId")],
    )
    sibling = UpstreamInterface(
        name="audit-fixed",
        type="file-fixed-width",
        spec="upstream/audit-layout.yaml",
        spec_content="format: fixed-width\n",
        entity_name="Audit",
        field_mappings=[FieldMapping(source="auditId", target="Audit.auditId")],
    )
    session.upstream_interfaces = [editable, sibling]
    save_session(session)
    return editable, sibling


def _session_with_rich_hidden_focus_state() -> list[UpstreamInterface]:
    _session_with_interfaces()
    session = get_session()
    editable, fixed_width = session.upstream_interfaces
    editable.spec_url = "https://example.invalid/account.xml"
    editable.is_draft = True
    editable.operations = [
        OperationSample(
            name="loadAccount",
            request_sample_path="samples/load-account-request.xml",
            request_sample_content="<load/>\n",
            response_sample_path="samples/load-account-response.xml",
            response_sample_content="<account/>\n",
        )
    ]
    editable.operation_mappings = [
        OperationMapping(
            name="loadAccount",
            request_mappings=[FieldMapping(source="accountId", target="request.accountId")],
            response_mappings=[FieldMapping(source="response.accountId", target="Account.accountId")],
        )
    ]

    fixed_width.spec_content = "  format: fixed-width\n"
    fixed_width.mapping_path = "upstream/custom-audit-mapping.yaml"
    fixed_width.operations = [
        OperationSample(
            name="loadAudit",
            request_sample_path="samples/load-audit-request.txt",
            request_sample_content="AUDIT\n",
        )
    ]
    fixed_width.operation_mappings = [
        OperationMapping(
            name="loadAudit",
            request_mappings=[FieldMapping(source="auditId", target="Audit.auditId")],
        )
    ]

    session.classified_entities = [
        ClassifiedEntity(
            name="Account",
            fields=[
                ClassifiedField(name="accountId", type="string", is_id=True),
                ClassifiedField(name="status", type="string"),
            ],
        )
    ]
    session.identity_role_decisions = [
        IdentityRoleDecision(entity="Account", field="accountId", role="persistence_id")
    ]
    soap = UpstreamInterface(
        name="account-soap",
        type="soap-wsdl",
        wsdl_path="contracts/account.wsdl",
        wsdl_content="<definitions/>\n",
        service="AccountService",
        port="AccountPort",
        binding="AccountBinding",
        selected_operation_name="getAccount",
        soap_operation_mode="canonical",
        soap_handler_method="handleGetAccount",
        soap_canonical_operation=SoapCanonicalOperationConfig(
            entity="Account",
            lookup_field="accountId",
            request_path="/GetAccountRequest/accountId",
            response_mappings=[
                SoapResponseMapping(
                    source="Account.accountId",
                    target_path="/GetAccountResponse/accountId",
                ),
                SoapResponseMapping(
                    source="Account.status",
                    target_path="/GetAccountResponse/status",
                ),
            ],
        ),
        mapping_path="upstream/custom-account-soap-mapping.yaml",
        operations=[
            OperationSample(
                name="getAccount",
                request_sample_path="samples/get-account-request.xml",
                request_sample_content="<request/>\n",
                response_sample_path="samples/get-account-response.xml",
                response_sample_content="<response/>\n",
            )
        ],
        operation_mappings=[
            OperationMapping(
                name="getAccount",
                request_mappings=[FieldMapping(source="Account.accountId", target="request.accountId")],
                response_mappings=[FieldMapping(source="response.status", target="Account.status")],
            )
        ],
        is_draft=True,
    )
    session.upstream_interfaces.append(soap)
    save_session(session)
    return session.upstream_interfaces


def _payload(iface: UpstreamInterface) -> dict:
    """Mirror the form fields returned by ``upstreamEdgeContractPayload``."""
    return {
        "direction": "upstream",
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
        "soap_handler_method": iface.soap_handler_method,
        "soap_canonical_operation": (
            iface.soap_canonical_operation.model_dump(mode="json")
            if iface.soap_canonical_operation
            else None
        ),
        "field_mappings": [mapping.model_dump(mode="json") for mapping in iface.field_mappings],
        "sample_path": iface.sample_path,
        "sample_content": iface.sample_content,
        "csv_delimiter": None,
        "csv_has_header_row": None,
    }


def _save_one(payload: dict, *, original_name: str | None, version: str = "7"):
    return client.post(
        "/upstream/edge-contract/save",
        json={
            "item": payload,
            "original_name": original_name,
            "source_of_truth_version": version,
        },
    )


def test_save_one_returns_additive_five_surface_payload_and_preserves_sibling():
    editable, sibling = _session_with_interfaces()
    sibling_before = sibling.model_dump(mode="json")
    payload = _payload(editable)
    payload["namespace"] = "urn:account:v2"

    response = _save_one(payload, original_name=editable.name)

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["message"]
    assert data["interface"] == data["item"]
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
    assert data["readiness"]["item_id"] == "usc:account-xml"
    assert data["board_metadata"] == {
        "artifact_path": "contracts/account.xsd",
        "family_fact": "root AccountMessage · urn:account:v2",
    }
    assert data["step_counts"]["2"] == {"count": 2, "attention": 0}
    assert {"step", "count", "attention"} == set(data["rail"][0])
    assert any(entry == {"step": 2, "count": 2, "attention": 0} for entry in data["rail"])
    assert data["source_of_truth_version"] == "8"

    saved = get_session()
    assert saved.upstream_interfaces[1].model_dump(mode="json") == sibling_before
    assert data["readiness"] == asdict(readiness_view.item(saved, "usc:account-xml"))


def test_original_name_rename_replaces_old_row_without_orphan():
    editable, _ = _session_with_interfaces()
    payload = _payload(editable)
    payload["name"] = "account-xml-v2"

    response = _save_one(payload, original_name=editable.name)

    assert response.status_code == 200
    assert [iface.name for iface in get_session().upstream_interfaces] == [
        "account-xml-v2",
        "audit-fixed",
    ]
    assert response.json()["readiness"]["item_id"] == "usc:account-xml-v2"


def _session_with_default_path_interface() -> UpstreamInterface:
    """An xml-xsd upstream interface whose artifact paths are the Studio-derived
    defaults for its name -- the state write_package_result leaves after an export.
    A later rename must re-point them so the manifest tracks the new identity."""
    session = get_session()
    session.app_name = "Upstream Rename Fixture"
    session.bounded_context = "upstream-rename-fixture"
    session.app_archetype = "crud"
    session.project_revision = 7
    iface = UpstreamInterface(
        name="acct",
        type="xml-xsd",
        version="v1",
        entity_name="Account",
        xsd_content="<xs:schema/>",
        xsd_path="upstream/acct-schema.xsd",  # == default_artifact_path(upstream, acct, xml-xsd)
        root_element="AccountMessage",
        namespace="urn:account:v1",
        mapping_path="upstream/acct-mapping.yaml",  # == default_upstream_xml_mapping_path(acct)
        field_mappings=[FieldMapping(source="accountId", target="Account.accountId")],
    )
    session.upstream_interfaces = [iface]
    save_session(session)
    return iface


def test_rename_repoints_studio_default_artifact_paths():
    """E2E Finding 4, upstream side: a rename must not leave manifest artifact
    paths pinned to the old identity. xsd_path and mapping_path here are the
    Studio defaults for 'acct', so a rename must track the new name -- otherwise
    the manifest and every future export point at upstream/acct-*."""
    iface = _session_with_default_path_interface()
    payload = _payload(iface)
    payload["name"] = "account"

    response = _save_one(payload, original_name="acct")

    assert response.status_code == 200
    saved = get_session().upstream_interfaces[0]
    assert saved.name == "account"
    assert saved.xsd_path == "upstream/account-schema.xsd"
    assert saved.mapping_path == "upstream/account-mapping.yaml"


def test_rename_preserves_author_supplied_artifact_paths():
    """A custom/reference path never equals a Studio default, so it belongs to the
    author, not Studio, and must survive a rename untouched (the content-gate that
    kept the downstream fix from discarding real references)."""
    editable, _ = _session_with_interfaces()  # xsd_path/mapping_path are custom here
    payload = _payload(editable)
    payload["name"] = "account-xml-v2"

    response = _save_one(payload, original_name=editable.name)

    assert response.status_code == 200
    saved = get_session().upstream_interfaces[0]
    assert saved.name == "account-xml-v2"
    assert saved.xsd_path == "contracts/account.xsd"
    assert saved.mapping_path == "upstream/custom-account-mapping.yaml"


def test_repoint_covers_every_upstream_derived_default_by_type():
    """Unit coverage that _repoint_renamed_upstream_default_paths mirrors
    write_package_result across the edge-contract types focus mode saves: SOAP
    (wsdl_path + operation mapping), file (spec + file mapping), and the shared
    sample_path -- each re-derived from the new name only when it was the old
    default."""
    from app.routes.upstream import _repoint_renamed_upstream_default_paths

    soap = UpstreamInterface(
        name="pay",
        type="soap-wsdl",
        entity_name="Payment",
        wsdl_content="<wsdl/>",
        wsdl_path="upstream/pay-contract.wsdl",
        selected_operation_name="createPayment",
        mapping_path="mappings/pay-operation-mapping.yaml",
        sample_content="<x/>",
        sample_path="upstream/pay-sample.xml",
    )
    renamed = soap.model_copy(update={"name": "payment"})
    _repoint_renamed_upstream_default_paths(renamed, soap)
    assert renamed.wsdl_path == "upstream/payment-contract.wsdl"
    assert renamed.mapping_path == "mappings/payment-operation-mapping.yaml"
    assert renamed.sample_path == "upstream/payment-sample.xml"

    fixed_width = UpstreamInterface(
        name="audit",
        type="file-fixed-width",
        entity_name="Audit",
        spec_content="format: fixed-width\n",
        spec="upstream/audit-layout.yaml",
        field_mappings=[FieldMapping(source="auditId", target="Audit.auditId")],
        mapping_path="upstream/audit-mapping.yaml",
    )
    fw_renamed = fixed_width.model_copy(update={"name": "audit-log"})
    _repoint_renamed_upstream_default_paths(fw_renamed, fixed_width)
    assert fw_renamed.spec == "upstream/audit-log-layout.yaml"
    assert fw_renamed.mapping_path == "upstream/audit-log-mapping.yaml"


def test_legacy_flat_payload_still_upserts_same_name_and_keeps_legacy_fields():
    editable, _ = _session_with_interfaces()
    payload = _payload(editable)
    payload["namespace"] = "urn:legacy-flat"

    response = client.post("/upstream/edge-contract/save", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["message"]
    assert data["interface"]["namespace"] == "urn:legacy-flat"
    assert data["item"] == data["interface"]
    assert [iface.name for iface in get_session().upstream_interfaces] == [
        "audit-fixed",
        "account-xml",
    ]


def test_focused_create_collision_is_rejected_without_overwrite():
    editable, _ = _session_with_interfaces()
    before = get_session().model_dump(mode="json")

    response = _save_one(_payload(editable), original_name=None)

    assert response.status_code == 400
    assert response.json()["errors"] == ["An upstream interface named 'account-xml' already exists."]
    assert response.json()["blockers"] == [
        {
            "code": "duplicate-name",
            "label": "An upstream interface named 'account-xml' already exists.",
            "field_ref": "name",
            "section_ref": "contract",
        }
    ]
    assert get_session().model_dump(mode="json") == before


def test_unchanged_focused_save_is_a_whole_project_noop():
    editable, _ = _session_with_interfaces()
    before = get_session().model_dump(mode="json")

    response = _save_one(_payload(editable), original_name=editable.name)

    assert response.status_code == 200
    assert response.json()["source_of_truth_version"] == "7"
    assert get_session().model_dump(mode="json") == before


def test_untouched_focused_saves_preserve_hidden_operation_state_and_raw_content():
    interfaces = _session_with_rich_hidden_focus_state()
    before = get_session().model_dump(mode="json")

    for interface in interfaces:
        payload = _payload(interface)
        # ``edgeValue`` trims text controls before the browser posts them.
        for field in ("spec_content", "xsd_content", "wsdl_content", "sample_content"):
            if isinstance(payload[field], str):
                payload[field] = payload[field].strip()
        response = _save_one(payload, original_name=interface.name)

        assert response.status_code == 200
        assert response.json()["source_of_truth_version"] == "7"
        assert get_session().model_dump(mode="json") == before


def test_focused_soap_to_xml_type_change_clears_incompatible_hidden_soap_state():
    interfaces = _session_with_rich_hidden_focus_state()
    soap = next(interface for interface in interfaces if interface.name == "account-soap")
    old_mapping_path = soap.mapping_path
    payload = _payload(soap)
    payload.update(
        {
            "type": "xml-xsd",
            "entity_name": "Account",
            "xsd_path": "contracts/account.xsd",
            "xsd_content": "<xs:schema/>",
            "root_element": "AccountMessage",
            "namespace": "urn:account:v1",
            "namespace_alias": "acct",
            "field_mappings": [{"source": "accountId", "target": "Account.accountId"}],
        }
    )

    response = _save_one(payload, original_name=soap.name)

    assert response.status_code == 200
    assert response.json()["source_of_truth_version"] == "8"
    saved = next(interface for interface in get_session().upstream_interfaces if interface.name == soap.name)
    assert saved.type == "xml-xsd"
    assert saved.is_draft is True
    assert saved.mapping_path == "upstream/account-soap-mapping.yaml"
    assert saved.mapping_path != old_mapping_path
    assert saved.operations == []
    assert saved.operation_mappings == []
    assert saved.selected_operation_name is None
    assert saved.wsdl_path is None
    assert saved.wsdl_content is None


def test_stale_version_returns_fresh_item_and_does_not_mutate():
    editable, _ = _session_with_interfaces()
    before = get_session().model_dump(mode="json")
    payload = _payload(editable)
    payload["namespace"] = "urn:stale-edit"

    response = _save_one(payload, original_name=editable.name, version="6")

    assert response.status_code == 409
    data = response.json()
    assert data["ok"] is False
    assert data["item"]["name"] == editable.name
    assert data["item"]["namespace"] == "urn:account:v1"
    assert data["readiness"]["item_id"] == "usc:account-xml"
    assert data["recovery"] == "review-current-item"
    assert data["source_of_truth_version"] == "7"
    assert get_session().model_dump(mode="json") == before


def test_stale_rename_recovery_does_not_attach_the_dirty_proposed_name():
    editable, _ = _session_with_interfaces()
    session = get_session()
    session.upstream_interfaces = [
        UpstreamInterface(
            name="dirty-new-name",
            type="xml-xsd",
            xsd_path="contracts/unrelated.xsd",
            root_element="Unrelated",
        )
    ]
    session.project_revision = 9
    save_session(session)
    before = get_session().model_dump(mode="json")
    payload = _payload(editable)
    payload["name"] = "dirty-new-name"

    response = _save_one(payload, original_name=editable.name, version="8")

    assert response.status_code == 409
    data = response.json()
    assert data["item"] is None
    assert data["readiness"] is None
    assert data["recovery"] == "reload-current-list"
    assert data["current_items"] == [{"name": "dirty-new-name", "type": "xml-xsd"}]
    assert get_session().model_dump(mode="json") == before


def test_stale_focused_draft_returns_conflict_before_local_validation():
    editable, _ = _session_with_interfaces()
    stale_payload = {"name": editable.name, "type": "xml-xsd", "direction": "downstream"}

    response = _save_one(stale_payload, original_name=editable.name, version="6")

    assert response.status_code == 409
    assert response.json()["item"]["name"] == editable.name
    assert response.json()["recovery"] == "review-current-item"


def test_concurrent_same_version_saves_allow_one_mutation_and_one_conflict():
    editable, _ = _session_with_interfaces()
    barrier = threading.Barrier(3)
    responses: list = []
    response_lock = threading.Lock()

    def submit(namespace: str) -> None:
        payload = _payload(editable)
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
    saved_namespace = get_session().upstream_interfaces[0].namespace
    assert saved_namespace in {"urn:concurrent-a", "urn:concurrent-b"}


def test_real_400_keeps_legacy_errors_and_maps_each_field_ref_to_focus_control():
    _session_with_interfaces()
    response = _save_one(
        {"direction": "upstream", "name": "broken-xml", "type": "xml-xsd"},
        original_name=None,
    )

    assert response.status_code == 400
    data = response.json()
    assert data["errors"]
    blockers = data["blockers"]
    assert {blocker["field_ref"] for blocker in blockers} == {"xsd_path", "root_element"}
    assert all(set(blocker) == {"code", "label", "field_ref", "section_ref"} for blocker in blockers)

    template = TEMPLATE.read_text(encoding="utf-8")
    map_start = template.index("const UXR_UPSTREAM_SAVE_BLOCKER_FIELD_SELECTORS = {")
    map_end = template.index("};", map_start)
    selector_map = template[map_start:map_end]
    for field_ref in {blocker["field_ref"] for blocker in blockers}:
        assert f"{field_ref}:" in selector_map
    assert "xsd_path: '#edge-contract-xsd-path'" in selector_map
    assert "root_element: '#edge-contract-root-element'" in selector_map
    assert 'id="edge-contract-xsd-path"' in template
    assert 'id="edge-contract-root-element"' in template


def test_upstream_uses_the_shared_validator_blocker_mapping_and_soap_operation_is_warn_only():
    assert downstream_route._validation_blockers is edge_contract_validation_blockers

    _session_with_interfaces()
    response = _save_one(
        {
            "direction": "upstream",
            "name": "adapter-soap",
            "type": "soap-wsdl",
            "wsdl_path": "contracts/adapter.wsdl",
            "soap_operation_mode": "adapter_only",
        },
        original_name=None,
    )

    assert response.status_code == 200
    assert response.json()["readiness"]["state"] == "warning"
    assert "selected_operation_name" not in {
        blocker["field_ref"] for blocker in response.json().get("blockers", [])
    }


def test_upstream_soap_blockers_target_operation_and_response_mapping_controls():
    _session_with_interfaces()
    session = get_session()
    session.classified_entities = [
        ClassifiedEntity(
            name="Account",
            fields=[ClassifiedField(name="accountId", type="string", is_id=True)],
        )
    ]
    session.identity_role_decisions = [
        IdentityRoleDecision(entity="Account", field="accountId", role="persistence_id")
    ]
    save_session(session)

    missing_operation = _save_one(
        {
            "direction": "upstream",
            "name": "missing-operation",
            "type": "soap-wsdl",
            "wsdl_path": "contracts/account.wsdl",
            "soap_operation_mode": "canonical",
            "soap_canonical_operation": {"entity": "Account"},
        },
        original_name=None,
    )
    missing_mappings = _save_one(
        {
            "direction": "upstream",
            "name": "missing-response-mappings",
            "type": "soap-wsdl",
            "wsdl_path": "contracts/account.wsdl",
            "selected_operation_name": "getAccount",
            "soap_operation_mode": "canonical",
            "soap_canonical_operation": {
                "entity": "Account",
                "lookup_field": "accountId",
                "request_path": "/GetAccountRequest/accountId",
                "response_mappings": [],
            },
        },
        original_name=None,
    )

    assert missing_operation.status_code == 400
    assert "selected_operation_name" in {
        blocker["field_ref"] for blocker in missing_operation.json()["blockers"]
    }
    assert missing_mappings.status_code == 400
    assert "soap_response_mappings" in {
        blocker["field_ref"] for blocker in missing_mappings.json()["blockers"]
    }

    template = TEMPLATE.read_text(encoding="utf-8")
    assert "selected_operation_name: '#edge-contract-operation'" in template
    assert "#edge-contract-soap-add-response-mapping" in template
    assert 'id="edge-contract-soap-add-response-mapping"' in template
