"""Tests for Step 5 fixed-width ID sizing guidance."""

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.main import app
from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    DownstreamInterface,
    FieldMapping,
    IdentityRoleDecision,
    LayoutField,
    SoapCanonicalInvocationConfig,
    SoapRequestMapping,
    SoapReturnMapping,
)
from app.routes.downstream import _build_fixed_width_id_warnings
from tests.session_helpers import get_session, reset_session, save_session
from tests.test_edge_contracts import SAMPLE_WSDL, SAMPLE_XSD
from tests.test_package_writer import _full_session

client = TestClient(app)


def test_fixed_width_id_guidance_warns_for_likely_id_field_under_36():
    warnings = _build_fixed_width_id_warnings(
        "payments-file",
        [LayoutField(name="paymentId", start=1, length=20)],
    )

    assert len(warnings) == 1
    assert warnings[0]["interface"] == "payments-file"
    assert warnings[0]["field"] == "paymentId"
    assert "UUID-style identifier" in warnings[0]["message"]
    assert "Use length 36 unless the project has an explicit non-UUID identity strategy." in warnings[0]["message"]


def test_fixed_width_id_guidance_warns_for_mapped_canonical_id_under_36():
    warnings = _build_fixed_width_id_warnings(
        "accounts-file",
        [LayoutField(name="account_number", start=1, length=12)],
        [FieldMapping(source="Account.accountId", target="account_number")],
    )

    assert len(warnings) == 1
    assert warnings[0]["interface"] == "accounts-file"
    assert warnings[0]["field"] == "account_number"
    assert "Use length 36 unless the project has an explicit non-UUID identity strategy." in warnings[0]["message"]


def test_fixed_width_id_guidance_suppresses_warning_at_36_or_above():
    warnings = _build_fixed_width_id_warnings(
        "payments-file",
        [LayoutField(name="internationalPaymentId", start=1, length=36)],
    )

    assert warnings == []


def test_fixed_width_id_guidance_ignores_non_id_fields():
    warnings = _build_fixed_width_id_warnings(
        "payments-file",
        [LayoutField(name="currency", start=1, length=3)],
    )

    assert warnings == []


def test_downstream_save_returns_advisory_warnings_without_changing_export_contract(tmp_path):
    reset_session()
    session = _full_session()
    session.output_path = str(tmp_path)
    session.downstream_interfaces = []
    save_session(session)

    response = client.post("/downstream/save", json={
        "interfaces": [
            {
                "name": "eod-file",
                "system": "SWIFT",
                "version": "v2",
                "type": "file-fixed-width",
                "entity_name": "Account",
                "layout_fields": [
                    {"name": "account_id", "start": 1, "length": 12},
                    {"name": "currency", "start": 13, "length": 3},
                ],
                "field_mappings": [
                    {"source": "Account.accountId", "target": "account_id"},
                ],
                "sample_content": None,
            }
        ]
    })

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert len(payload["warnings"]) == 1
    assert payload["warnings"][0]["field"] == "account_id"
    assert "Use length 36 unless the project has an explicit non-UUID identity strategy." in payload["warnings"][0]["message"]

    write_resp = client.post("/export/write")
    assert write_resp.status_code == 200
    assert write_resp.json()["ok"] is True

    manifest = yaml.safe_load((tmp_path / "records" / "app-definition.yaml").read_text())
    downstream = manifest["downstream_interfaces"][0]
    assert downstream["spec"] == "downstream/eod-file-layout.yaml"

    layout = yaml.safe_load((tmp_path / "records" / downstream["spec"]).read_text())
    fields = layout["record_types"]["data"]["fields"]
    assert fields[0]["name"] == "account_id"
    assert fields[0]["position"] == 1
    assert fields[0]["length"] == 12

    reset_session()


def test_downstream_save_warns_when_mapping_sources_id_to_short_fixed_width_field():
    reset_session()
    session = _full_session()
    session.downstream_interfaces = []
    save_session(session)

    response = client.post("/downstream/save", json={
        "interfaces": [
            {
                "name": "account-file",
                "type": "file-fixed-width",
                "entity_name": "Account",
                "layout_fields": [
                    {"name": "account_number", "start": 1, "length": 12},
                ],
                "field_mappings": [
                    {"source": "Account.accountId", "target": "account_number"},
                ],
            }
        ]
    })

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["warnings"][0]["field"] == "account_number"
    assert "UUID-style identifier" in payload["warnings"][0]["message"]
    assert "explicit non-UUID identity strategy" in payload["warnings"][0]["message"]
    reset_session()


def test_downstream_save_preserves_layout_lock_without_exporting_it(tmp_path):
    reset_session()
    session = _full_session()
    session.output_path = str(tmp_path)
    session.downstream_interfaces = []
    save_session(session)

    response = client.post("/downstream/save", json={
        "interfaces": [
            {
                "name": "eod-file",
                "type": "file-fixed-width",
                "entity_name": "Account",
                "layout_fields": [
                    {"name": "account_id", "start": 1, "length": 12, "locked_start": True},
                    {"name": "currency", "start": 13, "length": 3, "locked_start": False},
                ],
                "field_mappings": [],
            }
        ]
    })

    assert response.status_code == 200
    assert response.json()["ok"] is True
    saved = get_session().downstream_interfaces[0].layout_fields
    assert saved[0].locked_start is True
    assert saved[1].locked_start is False

    write_resp = client.post("/export/write")
    assert write_resp.status_code == 200
    layout = yaml.safe_load((tmp_path / "records" / "downstream/eod-file-layout.yaml").read_text())
    fields = layout["record_types"]["data"]["fields"]
    assert fields[0] == {"name": "account_id", "position": 1, "length": 12}
    assert "locked_start" not in fields[0]

    reset_session()


def test_downstream_page_contains_fixed_width_reflow_and_lock_controls():
    reset_session()
    session = _full_session()
    session.downstream_interfaces = []
    save_session(session)

    response = client.get("/downstream")

    assert response.status_code == 200
    html = response.text
    assert "Lock start" in html
    assert "Positions reflowed after length change." in html
    assert "reflowLayoutAfterLengthChange" in html
    assert "Locked row" in html
    assert "contiguous reflow expects" in html

    reset_session()


def test_downstream_edge_contract_card_uses_placeholder_and_type_specific_sections():
    reset_session()
    session = _full_session()
    session.downstream_interfaces = []
    save_session(session)

    response = client.get("/downstream")

    assert response.status_code == 200
    html = response.text
    assert "Select contract type..." in html
    assert "uploaded artifact content" not in html
    assert "Enter the package-relative artifact path and optionally paste reviewed content." in html
    assert "Format-specific inspection helps select metadata" in html
    assert "Inspect artifact" in html
    assert "Inspect layout/sample" in html
    assert "inspectDownstreamFileContract" in html
    assert "CSV delimiter" in html
    assert "Has header row" in html
    assert "iface-csv-delimiter" in html
    assert "iface-csv-has-header" in html
    assert "card.querySelector('.iface-sample')?.value || ''" in html
    assert "Populate visual layout rows" in html
    assert "Seed mapping rows from inspected fields" in html
    assert "Canonical entity link (optional)" in html
    assert "This does not create a canonical entity or mapping" in html
    assert "Canonical-to-contract mappings" in html
    assert "Source is a canonical path such as" in html
    assert "target is a file or XML field such as" in html
    assert "Seed mapping rows from layout fields" in html
    assert "Enter canonical entity link before seeding source paths." in html
    assert "XML/XSD runtime generation needs reviewed canonical-to-XML mappings." in html
    assert "Seed XML mapping rows from inspected fields" in html
    assert "Use length 36 unless the project has an explicit non-UUID identity strategy." in html
    assert "seedDownstreamFileMappings" in html
    assert "layoutFieldNamesForCard" in html
    assert "Saved with guidance" in html
    assert "Saved new downstream interfaces" in html
    assert "setTimeout(() => location.href = '/rules'" in html
    assert "fixed-width-layout-section" in html
    assert "file-mapping-section" in html
    assert "type === 'file-csv'" in html
    assert "type === 'xml-xsd'" in html
    assert "type === 'soap-wsdl'" in html
    assert "SOAP operation mode" in html
    assert "Adapter only" in html
    assert "Canonical invoke by ID" in html
    assert "POST /soap/outbound/{contractName}/{operationName}" in html
    assert "Canonical invoke by ID mapping" in html
    assert "Request body field" in html
    assert "return_only" in html
    assert "addSoapRequestMappingRowEl" in html
    assert "addSoapResponseMappingRowEl" in html
    assert "collectDownstreamSoapCanonicalInvocation" in html
    assert "card.querySelector('.fixed-width-layout-section')?.classList.add('hidden')" in html
    assert "show('.fixed-width-layout-section')" in html

    reset_session()


def test_downstream_file_contract_inspection_returns_layout_and_sample_preview():
    reset_session()
    session = _full_session()
    session.downstream_interfaces = []
    save_session(session)

    response = client.post(
        "/downstream/edge-contract/file-inspect",
        json={
            "direction": "downstream",
            "type": "file-fixed-width",
            "spec_content": (
                "format: fixed-width\n"
                "record_types:\n"
                "  data:\n"
                "    fields:\n"
                "      - name: account_id\n"
                "        position: 1\n"
                "        length: 36\n"
                "      - name: status\n"
                "        position: 37\n"
                "        length: 6\n"
            ),
            "sample_content": "123456789012345678901234567890123456ACTIVE",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["layout"]["fields"][0]["name"] == "account_id"
    assert payload["sample_preview"]["rows"][0]["values"][1] == {
        "field": "status",
        "value": "ACTIVE",
    }
    assert get_session().downstream_interfaces == []
    reset_session()


def test_downstream_file_contract_inspection_preserves_sample_padding():
    reset_session()
    session = _full_session()
    session.downstream_interfaces = []
    save_session(session)

    response = client.post(
        "/downstream/edge-contract/file-inspect",
        json={
            "direction": "downstream",
            "type": "file-fixed-width",
            "spec_content": (
                "format: fixed-width\n"
                "record_types:\n"
                "  data:\n"
                "    fields:\n"
                "      - name: padded_name\n"
                "        position: 1\n"
                "        length: 6\n"
                "      - name: status\n"
                "        position: 7\n"
                "        length: 6\n"
            ),
            "sample_content": "  AB  ACTIVE  ",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["sample_preview"]["rows"][0]["line"] == "  AB  ACTIVE  "
    assert payload["sample_preview"]["rows"][0]["values"][0]["value"] == "  AB  "
    reset_session()


def test_downstream_file_contract_inspection_rejects_non_file_types():
    response = client.post(
        "/downstream/edge-contract/file-inspect",
        json={
            "direction": "downstream",
            "type": "soap-wsdl",
            "spec_content": "fields: []",
        },
    )

    assert response.status_code == 400
    assert "file-fixed-width and file-csv" in response.json()["errors"][0]
    reset_session()


def test_downstream_file_contract_inspection_uses_csv_controls_over_yaml():
    reset_session()
    session = _full_session()
    session.downstream_interfaces = []
    save_session(session)

    response = client.post(
        "/downstream/edge-contract/file-inspect",
        json={
            "direction": "downstream",
            "type": "file-csv",
            "spec_content": "format: csv\ndelimiter: ','\nfields:\n  - name: account_id\n  - name: status\n",
            "sample_content": "A123~ACTIVE\n",
            "csv_delimiter": "~",
            "csv_has_header_row": "true",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["layout"]["delimiter"] == "~"
    assert payload["layout"]["has_header_row"] is True
    assert payload["sample_preview"]["rows"][0]["columns"][1]["value"] == "ACTIVE"
    reset_session()


def test_downstream_edge_contract_shell_rejects_missing_contract_type():
    reset_session()
    session = _full_session()
    session.downstream_interfaces = []
    save_session(session)

    response = client.post(
        "/downstream/save",
        json={
            "interfaces": [
                {
                    "name": "blank-type",
                    "spec": "downstream/blank-layout.yaml",
                }
            ]
        },
    )

    assert response.status_code == 400
    assert any("Select a contract type before saving." in error for error in response.json()["errors"])
    assert get_session().downstream_interfaces == []
    reset_session()


def test_downstream_edge_contract_shell_saves_csv_xml_and_soap():
    reset_session()
    session = _full_session()
    session.downstream_interfaces = []
    save_session(session)

    response = client.post(
        "/downstream/save",
        json={
            "interfaces": [
                {
                    "name": "csv-out",
                    "type": "file-csv",
                    "spec": "downstream/csv-layout.yaml",
                    "spec_content": (
                        "format: csv\n"
                        "record_types:\n"
                        "  data:\n"
                        "    fields:\n"
                        "      - name: account_id\n"
                        "        column: 1\n"
                    ),
                    "csv_delimiter": "~",
                    "csv_has_header_row": "true",
                },
                {
                    "name": "xml-out",
                    "type": "xml-xsd",
                    "xsd_path": "contracts/out.xsd",
                    "root_element": "acct:Out",
                },
                {
                    "name": "soap-out",
                    "type": "soap-wsdl",
                    "wsdl_path": "contracts/out.wsdl",
                    "service": "OutService",
                    "selected_operation_name": "SubmitOut",
                },
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    saved = get_session().downstream_interfaces
    assert [iface.type for iface in saved] == ["file-csv", "xml-xsd", "soap-wsdl"]
    assert saved[0].spec == "downstream/csv-layout.yaml"
    saved_csv = yaml.safe_load(saved[0].spec_content)
    assert saved_csv["delimiter"] == "~"
    assert saved_csv["has_header_row"] is True
    assert saved[0].entity_name is None
    assert saved[1].root_element == "acct:Out"
    assert saved[1].entity_name is None
    assert saved[2].wsdl_path == "contracts/out.wsdl"
    assert saved[2].selected_operation_name == "SubmitOut"
    assert saved[2].entity_name is None
    reset_session()


def test_downstream_edge_contract_shell_saves_soap_canonical_invoke_by_id():
    reset_session()
    session = _full_session()
    session.classified_entities = [
        ClassifiedEntity(
            name="Customer",
            fields=[
                ClassifiedField(name="customerId", type="string", is_id=True),
                ClassifiedField(name="status", type="string"),
            ],
        )
    ]
    session.identity_role_decisions = [
        IdentityRoleDecision(entity="Customer", field="customerId", role="persistence_id")
    ]
    session.downstream_interfaces = []
    save_session(session)

    response = client.post(
        "/downstream/save",
        json={
            "interfaces": [
                {
                    "name": "customer-soap-client",
                    "type": "soap-wsdl",
                    "wsdl_path": "contracts/customer-client.wsdl",
                    "service": "CustomerSyncService",
                    "port": "CustomerSyncServicePort",
                    "binding": "CustomerSyncServiceBinding",
                    "selected_operation_name": "syncCustomer",
                    "soap_operation_mode": "canonical",
                    "soap_canonical_invocation": {
                        "kind": "invoke_by_id",
                        "entity": "Customer",
                        "lookup": {
                            "request_field": "id",
                            "field": "customerId",
                        },
                        "request_mappings": [
                            {
                                "source": "Customer.customerId",
                                "target_path": "/SyncCustomerRequest/customerId",
                            }
                        ],
                        "response": {
                            "mode": "return_only",
                            "response_mappings": [
                                {
                                    "source_path": "/SyncCustomerResponse/resultCode",
                                    "target": "resultCode",
                                }
                            ],
                        },
                    },
                }
            ]
        },
    )

    assert response.status_code == 200
    saved = get_session().downstream_interfaces[0]
    assert saved.soap_operation_mode == "canonical"
    assert saved.mapping_path == "mappings/customer-soap-client-operation-mapping.yaml"
    assert saved.soap_canonical_invocation is not None
    assert saved.soap_canonical_invocation.kind == "invoke_by_id"
    assert saved.soap_canonical_invocation.lookup_field == "customerId"
    assert saved.soap_canonical_invocation.request_mappings[0].target_path == "/SyncCustomerRequest/customerId"
    assert saved.soap_canonical_invocation.response_mappings[0].source_path == "/SyncCustomerResponse/resultCode"
    reset_session()


def test_downstream_soap_canonical_save_infers_blank_entity_link_from_mapping_config():
    reset_session()
    session = _full_session()
    session.classified_entities = [
        ClassifiedEntity(
            name="Customer",
            fields=[
                ClassifiedField(name="customerId", type="string", is_id=True),
                ClassifiedField(name="status", type="string"),
            ],
        )
    ]
    session.identity_role_decisions = [
        IdentityRoleDecision(entity="Customer", field="customerId", role="persistence_id")
    ]
    session.downstream_interfaces = []
    save_session(session)

    response = client.post(
        "/downstream/save",
        json={
            "interfaces": [
                {
                    "name": "customer-sync-client",
                    "type": "soap-wsdl",
                    "entity_name": None,
                    "wsdl_path": "contracts/customer-client.wsdl",
                    "service": "CustomerSyncService",
                    "port": "CustomerSyncServicePort",
                    "binding": "CustomerSyncServiceBinding",
                    "selected_operation_name": "syncCustomer",
                    "soap_operation_mode": "canonical",
                    "soap_canonical_invocation": {
                        "kind": "invoke_by_id",
                        "entity": "Customer",
                        "lookup": {
                            "request_field": "id",
                            "field": "customerId",
                        },
                        "request_mappings": [
                            {
                                "source": "Customer.customerId",
                                "target_path": "/SyncCustomerRequest/customerId",
                            }
                        ],
                        "response": {
                            "mode": "return_only",
                            "response_mappings": [
                                {
                                    "source_path": "/SyncCustomerResponse/resultCode",
                                    "target": "resultCode",
                                }
                            ],
                        },
                    },
                }
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    saved = get_session().downstream_interfaces[0]
    assert saved.name == "customer-sync-client"
    assert saved.entity_name == "Customer"
    assert saved.soap_canonical_invocation is not None
    assert saved.soap_canonical_invocation.entity == "Customer"
    assert saved.mapping_path == "mappings/customer-sync-client-operation-mapping.yaml"
    reset_session()


def test_downstream_soap_canonical_save_rejects_invalid_lookup_request_field():
    reset_session()
    session = _full_session()
    session.classified_entities = [
        ClassifiedEntity(
            name="Customer",
            fields=[ClassifiedField(name="customerId", type="string", is_id=True)],
        )
    ]
    session.identity_role_decisions = [
        IdentityRoleDecision(entity="Customer", field="customerId", role="persistence_id")
    ]
    session.downstream_interfaces = []
    save_session(session)

    response = client.post(
        "/downstream/save",
        json={
            "interfaces": [
                {
                    "name": "customer-soap-client",
                    "type": "soap-wsdl",
                    "wsdl_path": "contracts/customer-client.wsdl",
                    "selected_operation_name": "syncCustomer",
                    "soap_operation_mode": "canonical",
                    "soap_canonical_invocation": {
                        "kind": "invoke_by_id",
                        "entity": "Customer",
                        "lookup": {
                            "request_field": "customerId",
                            "field": "customerId",
                        },
                        "request_mappings": [
                            {
                                "source": "Customer.customerId",
                                "target_path": "/SyncCustomerRequest/customerId",
                            }
                        ],
                        "response": {
                            "mode": "return_only",
                            "response_mappings": [
                                {
                                    "source_path": "/SyncCustomerResponse/resultCode",
                                    "target": "resultCode",
                                }
                            ],
                        },
                    },
                }
            ]
        },
    )

    assert response.status_code == 400
    assert response.json()["ok"] is False
    assert any("lookup request field must be id" in error for error in response.json()["errors"])
    assert get_session().downstream_interfaces == []
    reset_session()


def test_post_json_handles_non_json_server_errors_gracefully():
    source = Path("app/static/js/studio.js").read_text(encoding="utf-8")

    assert "await r.text()" in source
    assert "JSON.parse" in source
    assert "Server returned ${r.status}" in source
    assert "errors: [`Server returned ${r.status}: ${message}`]" in source


def test_downstream_soap_canonical_save_rejects_duplicate_rows_and_bad_response_target():
    reset_session()
    session = _full_session()
    session.classified_entities = [
        ClassifiedEntity(
            name="Customer",
            fields=[
                ClassifiedField(name="customerId", type="string", is_id=True),
                ClassifiedField(name="status", type="string"),
            ],
        )
    ]
    session.identity_role_decisions = [
        IdentityRoleDecision(entity="Customer", field="customerId", role="persistence_id")
    ]
    session.downstream_interfaces = []
    save_session(session)

    response = client.post(
        "/downstream/save",
        json={
            "interfaces": [
                {
                    "name": "customer-soap-client",
                    "type": "soap-wsdl",
                    "wsdl_path": "contracts/customer-client.wsdl",
                    "selected_operation_name": "syncCustomer",
                    "soap_operation_mode": "canonical",
                    "soap_canonical_invocation": {
                        "kind": "invoke_by_id",
                        "entity": "Customer",
                        "lookup": {
                            "request_field": "id",
                            "field": "customerId",
                        },
                        "request_mappings": [
                            {
                                "source": "Customer.customerId",
                                "target_path": "/SyncCustomerRequest/customerId",
                            },
                            {
                                "source": "Customer.status",
                                "target_path": "/SyncCustomerRequest/customerId",
                            },
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
                }
            ]
        },
    )

    assert response.status_code == 400
    errors = " ".join(response.json()["errors"])
    assert "target path '/SyncCustomerRequest/customerId' is used more than once" in errors
    assert "target 'result-code' is not a supported response field name" in errors
    assert get_session().downstream_interfaces == []
    reset_session()


def test_downstream_edge_contract_shell_saves_xml_canonical_mappings():
    reset_session()
    session = _full_session()
    session.downstream_interfaces = []
    save_session(session)

    response = client.post(
        "/downstream/save",
        json={
            "interfaces": [
                {
                    "name": "account-xml-out",
                    "type": "xml-xsd",
                    "xsd_path": "contracts/account.xsd",
                    "root_element": "AccountMessage",
                    "entity_name": "Account",
                    "field_mappings": [
                        {"source": "Account.accountId", "target": "accountId"},
                        {"source": "Account.sourceSystem", "target": "sourceSystem"},
                        {"source": "", "target": "ignored"},
                    ],
                }
            ]
        },
    )

    assert response.status_code == 200
    saved = get_session().downstream_interfaces[0]
    assert saved.type == "xml-xsd"
    assert saved.entity_name == "Account"
    assert saved.mapping_path == "downstream/account-xml-out-mapping.yaml"
    assert [(m.source, m.target) for m in saved.field_mappings] == [
        ("Account.accountId", "accountId"),
        ("Account.sourceSystem", "sourceSystem"),
    ]
    reset_session()


def test_downstream_save_guidance_for_spec_content_only_fixed_width_is_non_blocking():
    reset_session()
    session = _full_session()
    session.downstream_interfaces = []
    save_session(session)

    response = client.post(
        "/downstream/save",
        json={
            "interfaces": [
                {
                    "name": "fixed-spec-only",
                    "type": "file-fixed-width",
                    "spec": "downstream/fixed-spec-only-layout.yaml",
                    "spec_content": (
                        "format: fixed-width\n"
                        "record_types:\n"
                        "  data:\n"
                        "    fields:\n"
                        "      - name: account_id\n"
                        "        position: 1\n"
                        "        length: 12\n"
                    ),
                }
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    messages = [warning["message"] for warning in payload["warnings"]]
    assert "No visual layout rows are saved. Studio will still export the reviewed layout/spec content when present." in messages
    assert "No field mappings are saved. Full file operation/mapping authoring is a later slice." in messages
    assert get_session().downstream_interfaces[0].entity_name is None
    reset_session()


def test_downstream_edge_contract_shell_rejects_incomplete_xml():
    reset_session()
    session = _full_session()
    session.downstream_interfaces = []
    save_session(session)

    response = client.post(
        "/downstream/save",
        json={
            "interfaces": [
                {
                    "name": "xml-out",
                    "type": "xml-xsd",
                    "xsd_path": "contracts/out.xsd",
                }
            ]
        },
    )

    assert response.status_code == 400
    assert any("root element" in error for error in response.json()["errors"])
    assert get_session().downstream_interfaces == []
    reset_session()


def test_downstream_edge_contract_shell_rejects_absolute_artifact_path():
    reset_session()
    session = _full_session()
    session.downstream_interfaces = []
    save_session(session)

    response = client.post(
        "/downstream/save",
        json={
            "interfaces": [
                {
                    "name": "xml-out",
                    "type": "xml-xsd",
                    "xsd_path": "/tmp/out.xsd",
                    "root_element": "acct:Out",
                }
            ]
        },
    )

    assert response.status_code == 400
    assert any("relative, not absolute" in error for error in response.json()["errors"])
    assert get_session().downstream_interfaces == []
    reset_session()


def test_downstream_page_shows_edge_contract_readiness_summary():
    reset_session()
    session = _full_session()
    session.downstream_interfaces = [
        DownstreamInterface(
            name="csv-out",
            type="file-csv",
            spec="downstream/csv-layout.yaml",
        )
    ]
    save_session(session)

    response = client.get("/downstream")

    assert response.status_code == 200
    assert 'data-uxr-board="downstream"' in response.text
    assert "Review" in response.text
    assert "downstream/csv-layout.yaml" in response.text
    assert "uploaded artifact content" not in response.text
    assert "Saved File Contract Specs" in response.text
    assert "Reference only: Studio will export the manifest path, but no layout/spec content will be written." in response.text
    reset_session()


def test_downstream_page_shows_outbound_soap_mapping_readiness_note_not_warning():
    reset_session()
    session = _full_session()
    session.classified_entities = [
        ClassifiedEntity(
            name="Customer",
            fields=[
                ClassifiedField(name="customerId", type="string", is_id=True),
                ClassifiedField(name="status", type="string"),
            ],
        )
    ]
    session.identity_role_decisions = [
        IdentityRoleDecision(entity="Customer", field="customerId", role="persistence_id")
    ]
    session.downstream_interfaces = [
        DownstreamInterface(
            name="customer-sync-client",
            type="soap-wsdl",
            wsdl_path="contracts/customer-client.wsdl",
            wsdl_content="<definitions/>",
            selected_operation_name="syncCustomer",
            soap_operation_mode="canonical",
            soap_canonical_invocation=SoapCanonicalInvocationConfig(
                entity="Customer",
                lookup_field="customerId",
                request_mappings=[
                    SoapRequestMapping(source="Customer.customerId", target_path="/SyncCustomerRequest/customerId"),
                ],
                response_mappings=[
                    SoapReturnMapping(source_path="/SyncCustomerResponse/resultCode", target="resultCode"),
                ],
            ),
        )
    ]
    save_session(session)

    response = client.get("/downstream?focus=customer-sync-client")

    assert response.status_code == 200
    assert 'data-uxr-focus-editor="customer-sync-client"' in response.text
    assert "SOAP operation mode" in response.text
    assert "Canonical-to-SOAP request mappings" in response.text
    assert "Engine validation verifies detailed WSDL request/response paths" not in response.text
    reset_session()


def test_downstream_page_shows_saved_file_contract_spec_content_preview():
    reset_session()
    session = _full_session()
    session.downstream_interfaces = [
        DownstreamInterface(
            name="account-csv",
            type="file-csv",
            spec="downstream/account-outbound-csv-layout.yaml",
            spec_content="format: csv\nfields:\n  - name: account_id\n",
        )
    ]
    save_session(session)

    response = client.get("/downstream")

    assert response.status_code == 200
    assert "Saved File Contract Specs" in response.text
    assert "Saved layout/spec content" in response.text
    assert "downstream/account-outbound-csv-layout.yaml" in response.text
    assert "Studio writes this layout/spec file into the exported package. It is not generated by the app at runtime." in response.text
    assert "Layout is stored as reviewed spec content. Field-level visual editing arrives in a later file layout review slice." in response.text
    assert "format: csv" in response.text
    reset_session()


def test_downstream_page_shows_saved_fixed_width_id_length_guidance():
    reset_session()
    session = _full_session()
    session.downstream_interfaces = [
        DownstreamInterface(
            name="account-fixed",
            type="file-fixed-width",
            spec="downstream/account-fixed-layout.yaml",
            spec_content=(
                "format: fixed-width\n"
                "record_types:\n"
                "  data:\n"
                "    fields:\n"
                "      - name: account_number\n"
                "        position: 1\n"
                "        length: 12\n"
            ),
            layout_fields=[
                LayoutField(name="account_number", start=1, length=12),
            ],
            field_mappings=[
                FieldMapping(source="Account.accountId", target="account_number"),
            ],
        )
    ]
    save_session(session)

    response = client.get("/downstream")

    assert response.status_code == 200
    assert "Saved File Contract Specs" in response.text
    assert "Fixed-width ID length guidance" in response.text
    assert "account_number is length 12" in response.text
    assert "Use length 36 unless the project has an explicit non-UUID identity strategy." in response.text
    reset_session()


def test_downstream_page_restores_saved_edge_contract_types():
    reset_session()
    session = _full_session()
    session.downstream_interfaces = [
        DownstreamInterface(name="fw-out", type="file-fixed-width", spec="downstream/fw-layout.yaml"),
        DownstreamInterface(name="xml-out", type="xml-xsd", xsd_path="contracts/out.xsd", root_element="acct:Out"),
        DownstreamInterface(name="soap-out", type="soap-wsdl", wsdl_path="contracts/out.wsdl"),
    ]
    save_session(session)

    response = client.get("/downstream")

    assert response.status_code == 200
    assert '"type": "file-fixed-width"' in response.text
    assert '"type": "xml-xsd"' in response.text
    assert '"type": "soap-wsdl"' in response.text
    assert "card.querySelector('.iface-type').value = data.type || ''" in response.text
    reset_session()


def test_downstream_edge_contract_inspect_xml_and_soap_returns_candidates_without_saving():
    reset_session()
    session = _full_session()
    session.downstream_interfaces = []
    save_session(session)

    xml_response = client.post(
        "/downstream/edge-contract/inspect",
        json={
            "direction": "downstream",
            "type": "xml-xsd",
            "content": SAMPLE_XSD,
        },
    )
    soap_response = client.post(
        "/downstream/edge-contract/inspect",
        json={
            "direction": "downstream",
            "type": "soap-wsdl",
            "content": SAMPLE_WSDL,
        },
    )

    assert xml_response.status_code == 200
    assert xml_response.json()["candidates"]["root_elements"][0]["qualified_name"] == "acct:AccountStatus"
    assert soap_response.status_code == 200
    assert soap_response.json()["selected"]["operation"] == "GetAccountStatus"
    assert get_session().downstream_interfaces == []
    reset_session()
