from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    DownstreamInterface,
    FieldMapping,
    IdentityRoleDecision,
    ProjectSession,
    SoapCanonicalInvocationConfig,
    SoapCanonicalOperationConfig,
    SoapRequestMapping,
    SoapResponseMapping,
    SoapReturnMapping,
    UpstreamInterface,
)
from app.services.edge_contract_inspector import inspect_edge_contract_artifact
from app.services.edge_contracts import (
    INCOMPLETE,
    READY_TO_EXPORT,
    REFERENCE_ONLY,
    SOAP_WSDL_TYPE,
    csv_spec_content_with_controls,
    edge_contract_readiness,
    edge_contract_readiness_rows,
    payload_with_csv_controls,
    validate_edge_contract_payload,
)

SAMPLE_XSD = """<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           xmlns:acct="urn:accounts:v1"
           targetNamespace="urn:accounts:v1"
           elementFormDefault="qualified">
  <xs:import namespace="urn:common:v1" schemaLocation="common.xsd"/>
  <xs:element name="AccountStatus" type="acct:AccountStatusType"/>
  <xs:complexType name="AccountStatusType">
    <xs:sequence>
      <xs:element name="accountId" type="xs:string"/>
      <xs:choice>
        <xs:element name="status" type="xs:string"/>
      </xs:choice>
    </xs:sequence>
  </xs:complexType>
</xs:schema>
"""


SAMPLE_WSDL = """<?xml version="1.0"?>
<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/"
                  xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"
                  xmlns:tns="urn:accounts:v1"
                  targetNamespace="urn:accounts:v1">
  <wsdl:binding name="AccountServiceSoap11Binding" type="tns:AccountPortType">
    <soap:binding style="document" transport="http://schemas.xmlsoap.org/soap/http"/>
    <wsdl:operation name="GetAccountStatus">
      <soap:operation soapAction="urn:GetAccountStatus"/>
      <wsdl:input><soap:body use="literal"/></wsdl:input>
      <wsdl:output><soap:body use="literal"/></wsdl:output>
    </wsdl:operation>
  </wsdl:binding>
  <wsdl:service name="AccountService">
    <wsdl:port name="AccountServiceSoap11Port" binding="tns:AccountServiceSoap11Binding">
      <soap:address location="https://example.com/accounts"/>
    </wsdl:port>
  </wsdl:service>
</wsdl:definitions>
"""


def test_csv_spec_controls_update_existing_layout_yaml():
    updated = csv_spec_content_with_controls(
        "format: csv\nfields:\n  - name: account_id\n",
        delimiter="|",
        has_header_row=True,
    )

    assert updated == 'format: csv\ndelimiter: "|"\nhas_header_row: true\nfields:\n  - name: account_id'


def test_csv_spec_controls_preserve_reference_only_contracts():
    updated = csv_spec_content_with_controls(
        None,
        delimiter="~",
        has_header_row=False,
    )

    assert updated is None


def test_csv_spec_controls_support_tab_delimiter_payload():
    payload = payload_with_csv_controls(
        {
            "type": "file-csv",
            "spec_content": "format: csv\ndelimiter: ','\nheader: false\nfields: []\n",
            "csv_delimiter": "tab",
            "csv_has_header_row": "true",
        }
    )

    assert "delimiter: tab" in payload["spec_content"]
    assert "has_header_row: true" in payload["spec_content"]


def test_readiness_ready_upstream_xml_with_content():
    row = edge_contract_readiness(
        UpstreamInterface(
            name="account-xml",
            type="xml-xsd",
            xsd_path="contracts/account.xsd",
            xsd_content="<xs:schema/>",
            root_element="acct:Account",
        ),
        direction="upstream",
    )

    assert row.status == READY_TO_EXPORT
    assert row.will_export is True
    assert row.artifact_path == "contracts/account.xsd"
    assert row.has_content_to_write is True
    assert row.required_missing == []


def test_readiness_blocks_xml_missing_root_element():
    row = edge_contract_readiness(
        UpstreamInterface(
            name="account-xml",
            type="xml-xsd",
            xsd_path="contracts/account.xsd",
        ),
        direction="upstream",
    )

    assert row.status == INCOMPLETE
    assert row.will_export is False
    assert "root element" in row.required_missing


def test_readiness_ready_upstream_soap_uses_engine_manifest_type():
    row = edge_contract_readiness(
        UpstreamInterface(
            name="account-soap",
            type=SOAP_WSDL_TYPE,
            wsdl_path="contracts/account.wsdl",
            wsdl_content="<definitions/>",
            selected_operation_name="GetAccount",
        ),
        direction="upstream",
    )

    assert SOAP_WSDL_TYPE == "soap-wsdl"
    assert row.type == "soap-wsdl"
    assert row.status == READY_TO_EXPORT
    assert "selected SOAP operation" in row.required_present
    assert not any("selected operation" in warning for warning in row.warnings)


def test_readiness_warns_when_upstream_soap_has_no_selected_operation():
    row = edge_contract_readiness(
        UpstreamInterface(
            name="account-soap",
            type=SOAP_WSDL_TYPE,
            wsdl_path="contracts/account.wsdl",
            wsdl_content="<definitions/>",
        ),
        direction="upstream",
    )

    assert row.status == READY_TO_EXPORT
    assert any("needs a selected operation" in warning for warning in row.warnings)


def test_readiness_blocks_incomplete_canonical_soap_mapping():
    row = edge_contract_readiness(
        UpstreamInterface(
            name="account-soap",
            type=SOAP_WSDL_TYPE,
            wsdl_path="contracts/account.wsdl",
            selected_operation_name="GetAccount",
            soap_operation_mode="canonical",
            soap_canonical_operation=SoapCanonicalOperationConfig(
                entity="Account",
                lookup_field="accountId",
                request_path="/GetAccountRequest/accountId",
            ),
        ),
        direction="upstream",
    )

    assert row.status == INCOMPLETE
    assert "response mappings" in row.required_missing


def test_readiness_accepts_complete_canonical_soap_mapping():
    session = ProjectSession()
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
    row = edge_contract_readiness(
        UpstreamInterface(
            name="account-soap",
            type=SOAP_WSDL_TYPE,
            wsdl_path="contracts/account.wsdl",
            selected_operation_name="GetAccount",
            soap_operation_mode="canonical",
            soap_canonical_operation=SoapCanonicalOperationConfig(
                entity="Account",
                lookup_field="accountId",
                request_path="/GetAccountRequest/accountId",
                response_mappings=[
                    SoapResponseMapping(source="Account.accountId", target_path="/GetAccountResponse/accountId")
                ],
            ),
        ),
        direction="upstream",
        session=session,
    )

    assert row.will_export is True
    assert "canonical read_by_id mapping" in row.required_present


def test_readiness_blocks_canonical_soap_without_verified_persistence_model():
    row = edge_contract_readiness(
        UpstreamInterface(
            name="account-soap",
            type=SOAP_WSDL_TYPE,
            wsdl_path="contracts/account.wsdl",
            selected_operation_name="GetAccount",
            soap_operation_mode="canonical",
            soap_canonical_operation=SoapCanonicalOperationConfig(
                entity="Account",
                lookup_field="accountId",
                request_path="/GetAccountRequest/accountId",
                response_mappings=[
                    SoapResponseMapping(source="Account.accountId", target_path="/GetAccountResponse/accountId")
                ],
            ),
        ),
        direction="upstream",
    )

    assert row.status == INCOMPLETE
    assert any("known canonical entity" in missing for missing in row.required_missing)
    assert any("verified persistence ID field" in missing for missing in row.required_missing)


def test_readiness_blocks_restored_canonical_soap_with_invalid_response_mapping():
    session = ProjectSession()
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

    row = edge_contract_readiness(
        UpstreamInterface(
            name="account-soap",
            type=SOAP_WSDL_TYPE,
            wsdl_path="contracts/account.wsdl",
            selected_operation_name="GetAccount",
            soap_operation_mode="canonical",
            soap_canonical_operation=SoapCanonicalOperationConfig(
                entity="Account",
                lookup_field="accountId",
                request_path="/GetAccountRequest/accountId",
                response_mappings=[
                    SoapResponseMapping(source="Account.missingStatus", target_path="/GetAccountResponse/status"),
                    SoapResponseMapping(source="Account.status", target_path="GetAccountResponse/status"),
                ],
            ),
        ),
        direction="upstream",
        session=session,
    )

    assert row.status == INCOMPLETE
    missing = " ".join(row.required_missing)
    assert "Unknown SOAP response mapping field 'missingStatus'" in missing
    assert "SOAP response target path 'GetAccountResponse/status' must start with '/'" in missing


def test_readiness_blocks_soap_missing_wsdl_path():
    row = edge_contract_readiness(
        UpstreamInterface(name="account-soap", type="soap-wsdl"),
        direction="upstream",
    )

    assert row.status == INCOMPLETE
    assert row.will_export is False
    assert "wsdl_path or uploaded WSDL content" in row.required_missing


def test_readiness_accepts_downstream_soap_adapter_mapping():
    row = edge_contract_readiness(
        DownstreamInterface(
            name="customer-soap-client",
            type=SOAP_WSDL_TYPE,
            wsdl_path="contracts/customer-client.wsdl",
            wsdl_content="<definitions/>",
            selected_operation_name="syncCustomer",
        ),
        direction="downstream",
    )

    assert row.status == READY_TO_EXPORT
    assert "selected SOAP operation" in row.required_present
    assert "adapter-only operation mapping" in row.required_present


def test_readiness_accepts_downstream_soap_canonical_invoke_by_id_mapping():
    session = ProjectSession()
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

    row = edge_contract_readiness(
        DownstreamInterface(
            name="customer-soap-client",
            type=SOAP_WSDL_TYPE,
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
        ),
        direction="downstream",
        session=session,
    )

    assert row.will_export is True
    assert "canonical invoke_by_id mapping" in row.required_present


def test_readiness_blocks_downstream_canonical_soap_without_verified_persistence_model():
    row = edge_contract_readiness(
        DownstreamInterface(
            name="customer-soap-client",
            type=SOAP_WSDL_TYPE,
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
        ),
        direction="downstream",
    )

    assert row.status == INCOMPLETE
    assert any("known canonical entity" in missing for missing in row.required_missing)
    assert any("verified persistence ID field" in missing for missing in row.required_missing)


def test_readiness_blocks_downstream_canonical_soap_without_selected_operation():
    row = edge_contract_readiness(
        DownstreamInterface(
            name="customer-soap-client",
            type=SOAP_WSDL_TYPE,
            wsdl_path="contracts/customer-client.wsdl",
            soap_operation_mode="canonical",
            soap_canonical_invocation=SoapCanonicalInvocationConfig(
                entity="Customer",
                lookup_field="customerId",
            ),
        ),
        direction="downstream",
    )

    assert row.status == INCOMPLETE
    assert "selected SOAP operation" in row.required_missing


def test_readiness_blocks_downstream_canonical_soap_with_invalid_request_mapping():
    session = ProjectSession()
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

    row = edge_contract_readiness(
        DownstreamInterface(
            name="customer-soap-client",
            type=SOAP_WSDL_TYPE,
            wsdl_path="contracts/customer-client.wsdl",
            selected_operation_name="syncCustomer",
            soap_operation_mode="canonical",
            soap_canonical_invocation=SoapCanonicalInvocationConfig(
                entity="Customer",
                lookup_field="customerId",
                request_mappings=[
                    SoapRequestMapping(source="Account.accountId", target_path="SyncCustomerRequest/customerId"),
                ],
                response_mappings=[
                    SoapReturnMapping(source_path="SyncCustomerResponse/resultCode", target="resultCode"),
                ],
            ),
        ),
        direction="downstream",
        session=session,
    )

    assert row.status == INCOMPLETE
    missing = " ".join(row.required_missing)
    assert "must use canonical entity 'Customer'" in missing
    assert "flat SOAP path" in missing


def _customer_session() -> ProjectSession:
    session = ProjectSession()
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
    return session


def _valid_downstream_soap_payload() -> dict:
    return {
        "name": "customer-soap-client",
        "type": SOAP_WSDL_TYPE,
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
                {"source": "Customer.customerId", "target_path": "/SyncCustomerRequest/customerId"}
            ],
            "response": {
                "mode": "return_only",
                "response_mappings": [
                    {"source_path": "/SyncCustomerResponse/resultCode", "target": "resultCode"}
                ],
            },
        },
    }


def test_validate_downstream_soap_canonical_payload_accepts_complete_mapping():
    errors = validate_edge_contract_payload(
        _valid_downstream_soap_payload(),
        direction="downstream",
        session=_customer_session(),
    )

    assert errors == []


def test_validate_downstream_soap_canonical_payload_rejects_invalid_mode_and_kind():
    payload = _valid_downstream_soap_payload()
    payload["soap_operation_mode"] = "magic"

    assert "mode must be adapter_only or canonical" in " ".join(
        validate_edge_contract_payload(payload, direction="downstream", session=_customer_session())
    )

    payload = _valid_downstream_soap_payload()
    payload["soap_canonical_invocation"]["kind"] = "read_by_id"

    assert "kind must be invoke_by_id" in " ".join(
        validate_edge_contract_payload(payload, direction="downstream", session=_customer_session())
    )


def test_validate_downstream_soap_canonical_payload_rejects_missing_mappings():
    payload = _valid_downstream_soap_payload()
    payload["soap_canonical_invocation"]["request_mappings"] = []
    payload["soap_canonical_invocation"]["response"]["response_mappings"] = []

    errors = validate_edge_contract_payload(payload, direction="downstream", session=_customer_session())

    assert any("requires at least one request mapping" in error for error in errors)
    assert any("requires at least one response mapping" in error for error in errors)


def test_validate_downstream_soap_canonical_payload_rejects_invalid_response_mode_and_paths():
    payload = _valid_downstream_soap_payload()
    payload["soap_canonical_invocation"]["response"]["mode"] = "persist"
    payload["soap_canonical_invocation"]["request_mappings"][0]["target_path"] = "SyncCustomerRequest/customerId"
    payload["soap_canonical_invocation"]["response"]["response_mappings"][0]["source_path"] = (
        "SyncCustomerResponse/resultCode"
    )

    errors = " ".join(validate_edge_contract_payload(payload, direction="downstream", session=_customer_session()))

    assert "response mode must be return_only" in errors
    assert "SOAP request mapping target path" in errors
    assert "SOAP response mapping source path" in errors
    assert "flat SOAP path" in errors


def test_validate_downstream_soap_canonical_payload_rejects_duplicate_mappings_and_bad_response_target():
    payload = _valid_downstream_soap_payload()
    payload["soap_canonical_invocation"]["request_mappings"].append(
        {"source": "Customer.customerId", "target_path": "/SyncCustomerRequest/status"}
    )
    payload["soap_canonical_invocation"]["request_mappings"].append(
        {"source": "Customer.status", "target_path": "/SyncCustomerRequest/customerId"}
    )
    payload["soap_canonical_invocation"]["response"]["response_mappings"].append(
        {"source_path": "/SyncCustomerResponse/resultCode", "target": "message"}
    )
    payload["soap_canonical_invocation"]["response"]["response_mappings"].append(
        {"source_path": "/SyncCustomerResponse/message", "target": "resultCode"}
    )
    payload["soap_canonical_invocation"]["response"]["response_mappings"].append(
        {"source_path": "/SyncCustomerResponse/diagnostic", "target": "result-code"}
    )

    errors = " ".join(validate_edge_contract_payload(payload, direction="downstream", session=_customer_session()))

    assert "SOAP request mapping source 'Customer.customerId' is used more than once" in errors
    assert "SOAP request mapping target path '/SyncCustomerRequest/customerId' is used more than once" in errors
    assert "SOAP response mapping source path '/SyncCustomerResponse/resultCode' is used more than once" in errors
    assert "SOAP response mapping target 'resultCode' is used more than once" in errors
    assert "SOAP response mapping target 'result-code' is not a supported response field name" in errors


def test_validate_downstream_soap_canonical_payload_uses_operation_metadata_for_paths_and_required_fields():
    payload = _valid_downstream_soap_payload()
    payload["soap_operation_candidates"] = [
        {
            "name": "syncCustomer",
            "input_fields": [
                {"path": "/SyncCustomerRequest/customerId", "type": "string", "required": True},
                {"path": "/SyncCustomerRequest/status", "type": "boolean", "required": True},
            ],
            "output_fields": [
                {"path": "/SyncCustomerResponse/resultCode", "type": "string", "required": True},
                {"path": "/SyncCustomerResponse/message", "type": "string", "required": True},
            ],
        }
    ]
    payload["soap_canonical_invocation"]["request_mappings"][0]["target_path"] = "/SyncCustomerRequest/ghost"

    session = _customer_session()
    session.classified_entities[0].fields[1].type = "decimal"
    payload["soap_canonical_invocation"]["request_mappings"].append(
        {"source": "Customer.status", "target_path": "/SyncCustomerRequest/status"}
    )

    errors = " ".join(validate_edge_contract_payload(payload, direction="downstream", session=session))

    assert "Unknown SOAP request mapping target path '/SyncCustomerRequest/ghost'" in errors
    assert "Required SOAP request field '/SyncCustomerRequest/customerId' is not mapped" in errors
    assert "is not compatible with SOAP target path '/SyncCustomerRequest/status' type 'boolean'" in errors
    assert "Required SOAP response field '/SyncCustomerResponse/message' is not mapped" in errors


def test_readiness_marks_downstream_soap_canonical_wsdl_checks_as_engine_deferred():
    row = edge_contract_readiness(
        DownstreamInterface(
            name="customer-soap-client",
            type=SOAP_WSDL_TYPE,
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
        ),
        direction="downstream",
        session=_customer_session(),
    )

    assert row.will_export is True
    assert row.warnings == []
    assert any("Engine validates WSDL request/response paths during generation" in note for note in row.notes)


def test_readiness_reference_only_contract_warns_but_exports():
    row = edge_contract_readiness(
        DownstreamInterface(
            name="account-csv",
            type="file-csv",
            spec="downstream/account-csv-layout.yaml",
        ),
        direction="downstream",
    )

    assert row.status == REFERENCE_ONLY
    assert row.will_export is True
    assert row.has_content_to_write is False
    assert any("no uploaded artifact content" in warning for warning in row.warnings)


def test_upstream_file_readiness_is_ready_with_reviewed_mappings():
    row = edge_contract_readiness(
        UpstreamInterface(
            name="account-csv-in",
            type="file-csv",
            spec="upstream/account-csv-layout.yaml",
            spec_content="format: csv\nfields: []\n",
            entity_name="Account",
            field_mappings=[FieldMapping(source="account_id", target="accountId")],
        ),
        direction="upstream",
    )

    assert row.status == READY_TO_EXPORT
    assert row.will_export is True
    assert not any("file-to-canonical mappings" in warning for warning in row.warnings)


def test_upstream_file_readiness_warns_when_reviewed_mappings_are_missing():
    row = edge_contract_readiness(
        UpstreamInterface(
            name="account-csv-in",
            type="file-csv",
            spec="upstream/account-csv-layout.yaml",
            spec_content="format: csv\nfields: []\n",
        ),
        direction="upstream",
    )

    assert row.status == READY_TO_EXPORT
    assert any("No explicit file-to-canonical mappings" in warning for warning in row.warnings)


def test_upstream_file_readiness_warns_when_mapping_entity_is_blank():
    row = edge_contract_readiness(
        UpstreamInterface(
            name="account-csv-in",
            type="file-csv",
            spec="upstream/account-csv-layout.yaml",
            spec_content="format: csv\nfields: []\n",
            field_mappings=[FieldMapping(source="account_id", target="accountId")],
        ),
        direction="upstream",
    )

    assert row.status == READY_TO_EXPORT
    assert any("canonical entity name is blank" in warning for warning in row.warnings)


def test_xml_readiness_warns_when_runtime_mappings_are_missing():
    row = edge_contract_readiness(
        UpstreamInterface(
            name="account-xml-in",
            type="xml-xsd",
            xsd_path="contracts/account.xsd",
            xsd_content="<xs:schema/>",
            root_element="AccountMessage",
        ),
        direction="upstream",
    )

    assert row.status == READY_TO_EXPORT
    assert any("XML-to-canonical mappings" in warning for warning in row.warnings)


def test_xml_readiness_is_guided_when_reviewed_mappings_exist():
    row = edge_contract_readiness(
        UpstreamInterface(
            name="account-xml-in",
            type="xml-xsd",
            xsd_path="contracts/account.xsd",
            xsd_content="<xs:schema/>",
            root_element="AccountMessage",
            entity_name="Account",
            field_mappings=[FieldMapping(source="accountId", target="Account.accountId")],
        ),
        direction="upstream",
    )

    assert row.status == READY_TO_EXPORT
    assert not any("XML-to-canonical mappings" in warning for warning in row.warnings)


def test_readiness_blocks_path_traversal():
    row = edge_contract_readiness(
        UpstreamInterface(
            name="unsafe-xml",
            type="xml-xsd",
            xsd_path="../schema.xsd",
            root_element="Root",
        ),
        direction="upstream",
    )

    assert row.status == INCOMPLETE
    assert row.will_export is False
    assert any("cannot contain '..'" in warning for warning in row.warnings)


def test_readiness_blocks_url_like_artifact_path():
    row = edge_contract_readiness(
        UpstreamInterface(
            name="url-xml",
            type="xml-xsd",
            xsd_path="https://example.com/schema.xsd",
            root_element="Root",
        ),
        direction="upstream",
    )

    assert row.status == INCOMPLETE
    assert row.will_export is False
    assert any("not URLs" in warning for warning in row.warnings)


def test_readiness_rows_ignores_absent_edge_contracts():
    assert edge_contract_readiness_rows([], direction="upstream") == []


def test_xml_xsd_inspector_extracts_namespace_and_root_candidates():
    result = inspect_edge_contract_artifact("xml-xsd", SAMPLE_XSD)

    assert result["ok"] is True
    assert result["candidates"]["target_namespace"] == "urn:accounts:v1"
    assert result["candidates"]["namespace_alias"] == "acct"
    roots = result["candidates"]["root_elements"]
    assert roots[0]["name"] == "AccountStatus"
    assert roots[0]["qualified_name"] == "acct:AccountStatus"
    assert any("Unresolved XSD import" in warning for warning in result["warnings"])
    assert any("xs:choice" in warning for warning in result["warnings"])


def test_xml_xsd_inspector_extracts_field_candidates_for_mapping_seed():
    result = inspect_edge_contract_artifact("xml-xsd", SAMPLE_XSD)

    fields = result["candidates"]["fields"]

    assert {"name": "accountId", "kind": "element", "type": "xs:string", "required": True} in fields
    assert not any(field["name"] == "status" for field in fields)


def test_xml_xsd_inspector_does_not_seed_nested_or_complex_fields():
    result = inspect_edge_contract_artifact(
        "xml-xsd",
        """<?xml version="1.0"?>
        <xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
          <xs:element name="AccountMessage" type="AccountMessageType"/>
          <xs:complexType name="AddressType">
            <xs:sequence>
              <xs:element name="city" type="xs:string"/>
            </xs:sequence>
          </xs:complexType>
          <xs:complexType name="AccountMessageType">
            <xs:sequence>
              <xs:element name="accountId" type="xs:string"/>
              <xs:element name="address" type="AddressType"/>
              <xs:element name="inlineDetails">
                <xs:complexType>
                  <xs:sequence>
                    <xs:element name="memo" type="xs:string"/>
                  </xs:sequence>
                </xs:complexType>
              </xs:element>
            </xs:sequence>
            <xs:attribute name="sourceSystem" type="xs:string" use="required"/>
          </xs:complexType>
        </xs:schema>""",
    )

    fields = result["candidates"]["fields"]

    assert result["ok"] is True
    assert [field["name"] for field in fields] == ["sourceSystem", "accountId"]
    assert any("field 'address' is nested or complex" in warning for warning in result["warnings"])
    assert any("field 'inlineDetails' is nested or complex" in warning for warning in result["warnings"])
    assert not any(field["name"] in {"address", "city", "inlineDetails", "memo"} for field in fields)


def test_xml_xsd_inspector_returns_clean_error_for_malformed_content():
    result = inspect_edge_contract_artifact("xml-xsd", "<xs:schema>")

    assert result["ok"] is False
    assert any("Malformed XSD" in error for error in result["errors"])


def test_xml_xsd_inspector_rejects_dtd_and_entity_declarations_before_parse():
    result = inspect_edge_contract_artifact(
        "xml-xsd",
        """<!DOCTYPE xs:schema [
          <!ENTITY inflated "entity expansion must not run">
        ]>
        <xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
          <xs:element name="Unsafe" type="xs:string">&inflated;</xs:element>
        </xs:schema>""",
    )

    assert result["ok"] is False
    assert result["errors"] == ["XSD inspection does not allow DTD or entity declarations."]


def test_soap_wsdl_inspector_extracts_service_port_binding_operation():
    result = inspect_edge_contract_artifact("soap-wsdl", SAMPLE_WSDL)

    assert result["ok"] is True
    assert result["candidates"]["target_namespace"] == "urn:accounts:v1"
    assert result["selected"] == {
        "service": "AccountService",
        "port": "AccountServiceSoap11Port",
        "binding": "AccountServiceSoap11Binding",
        "operation": "GetAccountStatus",
    }
    assert result["candidates"]["services"][0]["name"] == "AccountService"
    assert result["candidates"]["ports"][0]["binding"] == "AccountServiceSoap11Binding"
    assert result["candidates"]["bindings"][0]["is_soap"] is True
    assert result["candidates"]["operations"][0]["soap_action"] == "urn:GetAccountStatus"


def test_soap_wsdl_inspector_warns_for_ambiguous_and_non_soap_shapes():
    result = inspect_edge_contract_artifact(
        "soap-wsdl",
        """<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/">
          <wsdl:binding name="PlainBinding" type="tns:PortType"/>
          <wsdl:service name="One"/>
          <wsdl:service name="Two"/>
        </wsdl:definitions>""",
    )

    assert result["ok"] is True
    assert any("Multiple WSDL services" in warning for warning in result["warnings"])
    assert any("not a SOAP binding" in warning for warning in result["warnings"])
    assert any("No SOAP binding" in warning for warning in result["warnings"])


def test_soap_wsdl_inspector_returns_clean_error_for_missing_content():
    result = inspect_edge_contract_artifact("soap-wsdl", "")

    assert result["ok"] is False
    assert result["errors"] == [
        "Paste WSDL content before inspection. Reference-only contracts can still export if complete."
    ]


def test_soap_wsdl_inspector_rejects_dtd_and_entity_declarations_before_parse():
    result = inspect_edge_contract_artifact(
        "soap-wsdl",
        """<!DOCTYPE wsdl:definitions [
          <!ENTITY inflated "entity expansion must not run">
        ]>
        <wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/">
          &inflated;
        </wsdl:definitions>""",
    )

    assert result["ok"] is False
    assert result["errors"] == ["WSDL inspection does not allow DTD or entity declarations."]
