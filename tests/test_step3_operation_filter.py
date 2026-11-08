"""Tests for Step 3 operation filtering and canonical-name data attributes."""

import json
import re
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.main import app
from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    ClassifiedOperation,
    FieldMapping,
    IdentityRoleDecision,
    OperationMapping,
    OperationSample,
    SoapCanonicalOperationConfig,
    SoapResponseMapping,
    UpstreamInterface,
)
from app.services.project_file_service import serialize_project, snapshot_session
from tests.session_helpers import get_session, reset_session, save_session
from tests.test_package_writer import _full_session

client = TestClient(app)


def _step3_js() -> str:
    return Path("app/static/js/step3_entities.js").read_text(encoding="utf-8")


def _phase2_payload(html: str):
    match = re.search(r"initialPhase2Interfaces: (.*?),\n  kaEnabled:", html, re.S)
    assert match, "initialPhase2Interfaces payload not found"
    return json.loads(match.group(1))


def _seed_classified(entities, operations):
    """Seed the session with pre-classified entities and operations."""
    reset_session()
    session = get_session()
    session.app_name = "TestApp"
    session.bounded_context = "test"
    session.target_profile = "springboot-legacy-compatible"
    session.classified_entities = entities
    session.classified_operations = operations
    save_session(session)


def test_step3_entity_checkbox_has_data_canonical_attribute():
    """Every entity checkbox must carry data-canonical set to the canonical name."""
    _seed_classified(
        entities=[
            ClassifiedEntity(
                name="CustomerResponse",
                canonical_name="Customer",
                classification="entity",
            )
        ],
        operations=[],
    )

    response = client.get("/entities")
    assert response.status_code == 200
    # The checkbox for "CustomerResponse" must expose its canonical name
    assert 'data-canonical="Customer"' in response.text
    reset_session()


def test_step3_entity_without_rename_uses_name_as_canonical():
    """When canonical_name is absent the checkbox data-canonical falls back to name."""
    _seed_classified(
        entities=[
            ClassifiedEntity(name="Account", classification="entity")
        ],
        operations=[],
    )

    response = client.get("/entities")
    assert response.status_code == 200
    assert 'data-canonical="Account"' in response.text
    reset_session()


def test_step3_operation_row_carries_data_candidates():
    """Each operation <tr> must expose its entity_candidates in data-candidates."""
    _seed_classified(
        entities=[
            ClassifiedEntity(
                name="CustomerResponse",
                canonical_name="Customer",
                classification="entity",
            )
        ],
        operations=[
            ClassifiedOperation(
                name="createCustomer",
                method="POST",
                path="/customers",
                resource="customers",
                entity_candidates=["Customer"],
            )
        ],
    )

    response = client.get("/entities")
    assert response.status_code == 200
    # Operation row must expose the canonical candidate name so the JS filter can match it
    assert 'data-candidates="Customer"' in response.text
    reset_session()


def test_step3_operation_filter_js_comment_mentions_canonical():
    """The JS filter function must include the canonical-name handling comment
    so it's clear raw and canonical names are both checked."""
    reset_session()
    response = client.get("/entities")
    assert response.status_code == 200
    js = _step3_js()
    assert "canonical" in js.lower()
    assert "data-canonical" in js
    reset_session()


def test_step3_loads_extracted_static_script():
    reset_session()

    response = client.get("/entities")

    assert response.status_code == 200
    assert '<script src="/static/js/step3_entities.js"></script>' in response.text
    assert "function renderPhase2" not in response.text
    assert "function renderPhase2" in _step3_js()
    reset_session()


def test_step3_restores_saved_operation_assignment_and_phase2_payload_on_reload():
    """A reopened Step 3 session should preserve operation assignment and Phase 2 state."""
    _seed_classified(
        entities=[
            ClassifiedEntity(
                name="CustomerResponse",
                canonical_name="Customer",
                classification="entity",
            )
        ],
        operations=[
            ClassifiedOperation(
                name="lookupCustomer",
                method="GET",
                path="/customers/{id}",
                resource="customers",
                entity_candidates=[],
            )
        ],
    )
    session = get_session()
    session.selected_entity_names = ["CustomerResponse"]
    session.selected_operation_names = ["lookupCustomer"]
    session.upstream_interfaces = [
        UpstreamInterface(
            name="customer-api",
            entity_name="Customer",
            operations=[
                OperationSample(
                    name="lookupCustomer",
                    request_sample_content='{"customerId":"C-001"}',
                    response_sample_content='{"customerId":"C-001","status":"ACTIVE"}',
                )
            ],
        )
    ]
    save_session(session)

    response = client.get("/entities")

    assert response.status_code == 200
    assert 'initialPhase2Interfaces:' in response.text
    assert 'customer-api' in response.text
    assert 'lookupCustomer' in response.text
    assert re.search(
        r'<option value="CustomerResponse"\s+selected>',
        response.text,
    )
    assert '\\"customerId\\":\\"C-001\\"' in response.text
    reset_session()


def test_old_project_operation_inventory_survives_step3_save_and_export(tmp_path):
    """A reopened project may own operations on interfaces but omit their UI inventory."""
    reset_session()
    old_project = _full_session()
    old_project.raw_spec_url = None
    old_project.raw_spec_filename = "account-openapi.yaml"
    old_project.raw_spec_content = yaml.safe_dump(
        {
            "openapi": "3.1.0",
            "info": {"title": "Account API", "version": "1.0"},
            "paths": {
                "/accounts": {
                    "post": {
                        "operationId": "createAccount",
                        "responses": {"201": {"description": "created"}},
                    }
                }
            },
            "components": {
                "schemas": {
                    "Account": {
                        "type": "object",
                        "properties": {"accountId": {"type": "string"}},
                    }
                }
            },
        },
        sort_keys=False,
    )
    old_project.classified_operations = []
    old_project.selected_operation_names = ["createAccount"]
    iface = old_project.upstream_interfaces[0]
    iface.spec_url = None
    iface.spec = "contracts/account-openapi.yaml"
    iface.spec_content = old_project.raw_spec_content
    operation_before = iface.operations[0].model_dump(mode="json")
    mappings_before = iface.operation_mappings[0].model_dump(mode="json")

    opened = client.post(
        "/project/open",
        files={
            "project_file": (
                "old-project.json",
                serialize_project(snapshot_session(old_project)).encode("utf-8"),
                "application/json",
            )
        },
        follow_redirects=False,
    )
    assert opened.status_code == 303

    page = client.get("/entities")
    assert page.status_code == 200
    assert 'value="createAccount"' in page.text
    assert re.search(r'id="op-createAccount"[^>]*checked', page.text)
    assert [operation.name for operation in get_session().classified_operations] == [
        "createAccount"
    ]

    saved = client.post(
        "/entities/save",
        json={
            "entities": ["Account"],
            "operations": ["createAccount"],
            "entity_op_map": {"Account": ["createAccount"]},
        },
    )
    assert saved.status_code == 200

    persisted = get_session()
    persisted_iface = persisted.upstream_interfaces[0]
    assert persisted_iface.operations[0].model_dump(mode="json") == operation_before
    assert persisted_iface.operation_mappings[0].model_dump(mode="json") == mappings_before

    persisted.output_path = str(tmp_path)
    save_session(persisted)
    exported = client.post("/export/write")
    assert exported.status_code == 200
    files = exported.json()["files"]
    assert "upstream/synthetic-account-api-mapping.yaml" in files
    assert "upstream/create-account-request.json" in files
    assert "upstream/create-account-response.json" in files
    manifest = yaml.safe_load((tmp_path / "records" / "app-definition.yaml").read_text())
    assert manifest["upstream_interfaces"][0]["mapping"] == (
        "upstream/synthetic-account-api-mapping.yaml"
    )
    reset_session()


def test_step3_empty_hidden_operation_payload_preserves_interface_authoring():
    """Missing controls are not interpreted as a clear when recovery is unavailable."""
    _seed_classified(
        entities=[ClassifiedEntity(name="Account", classification="entity")],
        operations=[],
    )
    session = get_session()
    session.selected_entity_names = ["Account"]
    session.selected_operation_names = ["createAccount"]
    session.upstream_interfaces = [
        UpstreamInterface(
            name="account-api",
            type="rest-json",
            entity_name="Account",
            operations=[
                OperationSample(
                    name="createAccount",
                    request_sample_path="upstream/custom-request.json",
                    request_sample_content='{"accountId":"A-1"}',
                )
            ],
            operation_mappings=[
                OperationMapping(
                    name="createAccount",
                    request_mappings=[
                        FieldMapping(source="accountId", target="Account.accountId")
                    ],
                )
            ],
            mapping_path="upstream/account-mapping.yaml",
        )
    ]
    save_session(session)
    before = get_session().upstream_interfaces[0].model_dump(mode="json")

    response = client.post(
        "/entities/save",
        json={
            "entities": ["Account"],
            "operations": [],
            "entity_op_map": {},
        },
    )

    assert response.status_code == 200
    persisted = get_session()
    assert persisted.upstream_interfaces[0].model_dump(mode="json") == before
    assert persisted.selected_operation_names == ["createAccount"]
    reset_session()


def test_step3_primitive_ref_sample_and_request_only_mapping_review():
    spec = {
        "openapi": "3.1.0",
        "components": {
            "schemas": {
                "CurrencyCode": {"type": "string", "example": "USD"},
                "CreateAccountRequest": {
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string", "example": "A-1"},
                        "currency_code": {"$ref": "#/components/schemas/CurrencyCode"},
                    },
                },
                "CreateAccountResponse": {
                    "type": "object",
                    "properties": {"account_id": {"type": "string"}},
                },
            }
        },
    }
    _seed_classified(
        entities=[
            ClassifiedEntity(
                name="CreateAccountResponse",
                canonical_name="Account",
                classification="entity",
                fields=[ClassifiedField(name="account_id", type="string")],
            )
        ],
        operations=[
            ClassifiedOperation(
                name="createAccount",
                method="POST",
                path="/accounts",
                resource="accounts",
                request_schema="CreateAccountRequest",
                response_schema="CreateAccountResponse",
            )
        ],
    )
    session = get_session()
    session.raw_spec_content = yaml.safe_dump(spec, sort_keys=False)
    session.selected_entity_names = ["CreateAccountResponse"]
    session.selected_operation_names = ["createAccount"]
    session.upstream_interfaces = [
        UpstreamInterface(
            name="account-api",
            type="rest-json",
            entity_name="Account",
            operations=[OperationSample(name="createAccount")],
        )
    ]
    save_session(session)

    response = client.get("/entities")
    operation = _phase2_payload(response.text)[0]["operations"][0]

    assert json.loads(operation["request_sample_content"])["currency_code"] == "USD"
    assert operation["request_mappings"] == [
        {"source": "account_id", "target": "Account.account_id"}
    ]
    assert any(
        "currency_code" in message and "omitted the automatic mapping" in message
        for message in operation["mapping_review_items"]
    )
    assert "data-mapping-review" in _step3_js()
    reset_session()


def test_step3_save_preserves_upstream_edge_contract_interfaces_in_mixed_project():
    _seed_classified(
        entities=[
            ClassifiedEntity(
                name="Customer",
                fields=[
                    ClassifiedField(name="customerId", type="string", is_id=True),
                    ClassifiedField(name="status", type="string"),
                ],
            )
        ],
        operations=[
            ClassifiedOperation(
                name="lookupCustomer",
                method="GET",
                path="/customers/{id}",
                resource="customers",
                entity_candidates=["Customer"],
            )
        ],
    )
    session = get_session()
    session.bounded_context = "customer"
    session.raw_spec_url = "https://example.com/customer-openapi.json"
    session.upstream_interfaces = [
        UpstreamInterface(
            name="account-fixed-in",
            type="file-fixed-width",
            spec="upstream/account-fixed-layout.yaml",
            entity_name="Account",
            field_mappings=[FieldMapping(source="account_id", target="Account.accountId")],
        ),
        UpstreamInterface(
            name="account-csv-in",
            type="file-csv",
            spec="upstream/account-csv-layout.yaml",
            entity_name="Account",
            field_mappings=[FieldMapping(source="account_number", target="Account.accountId")],
        ),
        UpstreamInterface(
            name="account-xml-in",
            type="xml-xsd",
            xsd_path="upstream/account.xsd",
            root_element="Account",
            entity_name="Account",
            field_mappings=[FieldMapping(source="/Account/accountId", target="Account.accountId")],
        ),
        UpstreamInterface(
            name="customer-soap-in",
            type="soap-wsdl",
            wsdl_path="upstream/customer.wsdl",
            selected_operation_name="getCustomer",
            entity_name="Customer",
        ),
        UpstreamInterface(
            name="customer-api",
            type="rest-json",
            entity_name="Customer",
            spec_url="https://example.com/old-openapi.json",
            operations=[OperationSample(name="staleCustomerLookup")],
        ),
    ]
    save_session(session)

    response = client.post(
        "/entities/save",
        json={
            "entities": ["Customer"],
            "operations": ["lookupCustomer"],
            "entity_op_map": {"Customer": ["lookupCustomer"]},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["interface_count"] == 1

    saved = get_session().upstream_interfaces
    assert [iface.name for iface in saved] == [
        "account-fixed-in",
        "account-csv-in",
        "account-xml-in",
        "customer-soap-in",
        "customer-api",
    ]
    assert [iface.type for iface in saved] == [
        "file-fixed-width",
        "file-csv",
        "xml-xsd",
        "soap-wsdl",
        "rest-json",
    ]
    assert saved[0].spec == "upstream/account-fixed-layout.yaml"
    assert saved[1].spec == "upstream/account-csv-layout.yaml"
    assert saved[2].xsd_path == "upstream/account.xsd"
    assert saved[3].wsdl_path == "upstream/customer.wsdl"
    assert saved[3].selected_operation_name == "getCustomer"

    rest = saved[4]
    assert rest.entity_name == "Customer"
    assert rest.spec_url == "https://example.com/customer-openapi.json"
    assert [op.name for op in rest.operations] == ["lookupCustomer"]
    assert "staleCustomerLookup" not in [op.name for op in rest.operations]
    reset_session()


def test_step3_xml_edge_contract_phase2_payload_uses_xsd_readiness_not_openapi_spec_warning():
    reset_session()
    session = get_session()
    session.app_name = "Edge XML"
    session.bounded_context = "edge-xml"
    session.target_profile = "springboot-legacy-compatible"
    session.upstream_interfaces = [
        UpstreamInterface(
            name="account-xml-in",
            type="xml-xsd",
            xsd_path="contracts/account.xsd",
            root_element="acct:Account",
            namespace="urn:accounts:v1",
            entity_name="Account",
            field_mappings=[FieldMapping(source="accountId", target="Account.accountId")],
        )
    ]
    save_session(session)

    response = client.get("/entities")
    payload = _phase2_payload(response.text)

    assert response.status_code == 200
    edge = payload[0]["edge_contract"]
    assert edge["type"] == "xml-xsd"
    assert edge["artifact_path"] == "contracts/account.xsd"
    assert "Root element: acct:Account" in edge["details"]
    assert "Namespace: urn:accounts:v1" in edge["details"]
    assert "Reviewed XML mapping targets Account" in edge["mapping_summary"]
    assert "No spec or spec_url" not in json.dumps(payload[0])
    reset_session()


def test_step3_soap_canonical_phase2_payload_shows_read_by_id_summary_and_entity():
    reset_session()
    session = get_session()
    session.app_name = "Edge SOAP"
    session.bounded_context = "edge-soap"
    session.target_profile = "springboot-legacy-compatible"
    session.classified_entities = [
        ClassifiedEntity(
            name="Customer",
            fields=[
                # is_id makes readiness align with export without needing OpenAPI samples here.
                ClassifiedField(name="customerId", type="string", is_id=True),
                ClassifiedField(name="status", type="string"),
            ],
        )
    ]
    session.identity_role_decisions = [
        IdentityRoleDecision(entity="Customer", field="customerId", role="persistence_id")
    ]
    session.upstream_interfaces = [
        UpstreamInterface(
            name="customer-soap-in",
            type="soap-wsdl",
            wsdl_path="contracts/customer.wsdl",
            service="CustomerService",
            port="CustomerPort",
            binding="CustomerBinding",
            selected_operation_name="getCustomer",
            soap_operation_mode="canonical",
            soap_canonical_operation=SoapCanonicalOperationConfig(
                entity="Customer",
                lookup_field="customerId",
                request_path="/GetCustomerRequest/customerId",
                response_mappings=[
                    SoapResponseMapping(
                        source="Customer.customerId",
                        target_path="/GetCustomerResponse/customerId",
                    ),
                    SoapResponseMapping(source="Customer.status", target_path="/GetCustomerResponse/status"),
                ],
            ),
        )
    ]
    save_session(session)

    response = client.get("/entities")
    payload = _phase2_payload(response.text)

    assert response.status_code == 200
    edge = payload[0]["edge_contract"]
    assert edge["type"] == "soap-wsdl"
    assert edge["entity_display"] == "Customer"
    assert edge["mapping_summary"] == "SOAP getCustomer maps to Customer read_by_id using customerId."
    assert "WSDL: contracts/customer.wsdl" in edge["details"]
    assert "Entity: null" not in json.dumps(payload[0])
    assert "No spec or spec_url" not in json.dumps(payload[0])
    reset_session()


def test_step3_edge_contract_renderer_skips_openapi_operation_sample_panel():
    response = client.get("/entities")

    assert response.status_code == 200
    js = _step3_js()
    assert "if (edgeContract) {" in js
    assert "OpenAPI operation samples for this edge contract" in js
    assert js.index("if (edgeContract) {") < js.index("at least one sample body per operation")
    reset_session()


def test_step3_soap_adapter_payload_does_not_show_null_entity():
    reset_session()
    session = get_session()
    session.app_name = "Edge SOAP"
    session.bounded_context = "edge-soap"
    session.target_profile = "springboot-legacy-compatible"
    session.upstream_interfaces = [
        UpstreamInterface(
            name="customer-soap-in",
            type="soap-wsdl",
            wsdl_path="contracts/customer.wsdl",
            selected_operation_name="getCustomer",
        )
    ]
    save_session(session)

    response = client.get("/entities")
    payload = _phase2_payload(response.text)

    edge = payload[0]["edge_contract"]
    assert edge["entity_display"] == "Adapter only"
    assert "adapter-only operation mapping" in edge["mapping_summary"]
    assert "Entity: null" not in json.dumps(payload[0])
    reset_session()


def test_step3_rest_openapi_missing_spec_warning_remains_available():
    reset_session()
    session = get_session()
    session.app_name = "OpenAPI"
    session.bounded_context = "openapi"
    session.target_profile = "springboot-legacy-compatible"
    session.upstream_interfaces = [
        UpstreamInterface(name="account-api", type="rest-json", entity_name="Account")
    ]
    save_session(session)

    response = client.get("/entities")
    payload = _phase2_payload(response.text)

    assert response.status_code == 200
    assert "No spec or spec_url" in _step3_js()
    assert "edge_contract" not in payload[0]
    reset_session()


def test_step3_template_uses_inline_js_safe_arg_helper_for_restored_phase2_actions():
    """Reopened Phase 2 action buttons must use JS-safe argument escaping, not raw HTML escaping."""
    response = client.get("/entities")

    assert response.status_code == 200
    js = _step3_js()
    assert "function escapeInlineJsArg(value)" in js
    assert 'onclick="addMappingRow(\'op-req-mapping-rows\', ${escapeInlineJsArg(iface.name)}, ${escapeInlineJsArg(op.name)}, ${escapeInlineJsArg(iface.entity_name)})"' in js
    assert 'onclick="addMappingRow(\'op-resp-mapping-rows\', ${escapeInlineJsArg(iface.name)}, ${escapeInlineJsArg(op.name)}, ${escapeInlineJsArg(iface.entity_name)})"' in js
    reset_session()
