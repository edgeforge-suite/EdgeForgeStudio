from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    DataHandoff,
    DownstreamInterface,
    FieldMapping,
    IdentityRoleDecision,
    OperationMapping,
    OperationSample,
    SoapCanonicalInvocationConfig,
    SoapCanonicalOperationConfig,
    SoapRequestMapping,
    SoapResponseMapping,
    SoapReturnMapping,
    UpstreamInterface,
)
from app.services.session_context import get_session_store
from app.services.settings import get_studio_settings
from app.services.signed_tokens import verify_payload


def csrf_from_html(html: str) -> str:
    match = re.search(
        r'<meta\s+name="edgeforge-csrf-token"\s+content="([^"]+)"',
        html,
    )
    assert match, "CSRF meta tag was not rendered"
    return match.group(1)


def new_shared_client() -> tuple[TestClient, str]:
    client = TestClient(app, base_url="https://testserver")
    page = client.get("/")
    assert page.status_code == 200
    return client, csrf_from_html(page.text)


def session_id_from_client(client: TestClient) -> str:
    settings = get_studio_settings()
    cookie = client.cookies.get(settings.session_cookie_name)
    assert cookie, "shared-mode client did not receive a Studio session cookie"
    payload = verify_payload(cookie, secret=settings.session_secret)
    return str(payload["sid"])


def session_for_client(client: TestClient):
    return get_session_store().load(session_id_from_client(client))


def save_session_for_client(client: TestClient, session) -> None:
    assert session.session_id == session_id_from_client(client)
    get_session_store().save(session)


def csrf_headers(token: str) -> dict[str, str]:
    return {"x-edgeforge-csrf-token": token}


def require_mcp_transport() -> None:
    """Skip MCP-generate smoke when the Studio MCP client is unavailable."""
    import pytest

    pytest.importorskip(
        "fastmcp",
        reason="cross-repo MCP-generate smoke requires fastmcp (MCP transport; python>=3.10)",
    )


def assert_no_ka_noise(payload: object) -> None:
    forbidden = {
        "evidence",
        "evidence_links",
        "knowledge_url",
        "raw_suggestion_count",
        "suggestion",
        "suggestions",
    }
    if isinstance(payload, dict):
        assert forbidden.isdisjoint(payload.keys())
        for value in payload.values():
            assert_no_ka_noise(value)
    elif isinstance(payload, list):
        for item in payload:
            assert_no_ka_noise(item)


def generic_openapi_spec(entity_name: str) -> str:
    return f"""
openapi: 3.0.0
info:
  title: {entity_name} API
  version: "1.0"
paths:
  /{entity_name.lower()}s:
    post:
      operationId: create{entity_name}
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/Create{entity_name}Request'
      responses:
        "201":
          description: created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/{entity_name}'
components:
  schemas:
    {entity_name}:
      type: object
      properties:
        {entity_name.lower()}Id:
          type: string
        status:
          type: string
      required:
        - {entity_name.lower()}Id
    Create{entity_name}Request:
      type: object
      properties:
        status:
          type: string
"""


def make_exportable_smoke_session(session, *, entity_name: str, contract_name: str) -> None:
    entity_id = f"{entity_name[0].lower()}{entity_name[1:]}Id"
    create_operation = f"create{entity_name}"
    session.raw_spec_content = generic_openapi_spec(entity_name)
    session.raw_spec_filename = f"{contract_name}-openapi.yaml"
    session.raw_spec_url = None
    session.classified_entities = [
        ClassifiedEntity(
            name=entity_name,
            fields=[
                ClassifiedField(name=entity_id, type="string", required=True, is_id=True),
                ClassifiedField(name="status", type="string"),
            ],
            classification="entity",
            confidence="confirmed",
        )
    ]
    session.selected_entity_names = [entity_name]
    session.classified_operations = []
    session.selected_operation_names = [create_operation]
    session.upstream_interfaces = [
        UpstreamInterface(
            name=f"{contract_name}-api",
            system="source-system",
            type="rest-json",
            version="1.0",
            spec=f"contracts/{contract_name}-openapi.yaml",
            spec_content=session.raw_spec_content,
            entity_name=entity_name,
            operations=[
                OperationSample(
                    name=create_operation,
                    request_sample_path=f"upstream/{contract_name}-request.json",
                    response_sample_path=f"upstream/{contract_name}-response.json",
                    request_sample_content='{"status":"draft"}',
                    response_sample_content=f'{{"{entity_id}":"id-1","status":"draft"}}',
                )
            ],
            operation_mappings=[
                OperationMapping(
                    name=create_operation,
                    request_mappings=[FieldMapping(source="status", target=f"{entity_name}.status")],
                    response_mappings=[FieldMapping(source=entity_id, target=f"{entity_name}.{entity_id}")],
                )
            ],
            mapping_path=f"upstream/{contract_name}-mapping.yaml",
        )
    ]
    session.downstream_interfaces = [
        DownstreamInterface(
            name=f"{contract_name}-fixed-file",
            system="target-system",
            type="file-fixed-width",
            version="1.0",
            spec=f"downstream/{contract_name}-layout.yaml",
            spec_content=(
                "format: fixed-width\n"
                "record_types:\n"
                "  data:\n"
                "    fields:\n"
                f"      - name: {entity_id}\n"
                "        position: 1\n"
                "        length: 36\n"
                "      - name: status\n"
                "        position: 37\n"
                "        length: 12\n"
            ),
            entity_name=entity_name,
            field_mappings=[
                FieldMapping(source=f"{entity_name}.{entity_id}", target=entity_id),
                FieldMapping(source=f"{entity_name}.status", target="status"),
            ],
            mapping_path=f"downstream/{contract_name}-mapping.yaml",
        )
    ]
    session.data_handoffs = []
    session.entity_rules = []
    session.capabilities.knowledge_assist_enabled = False
    session.ks_active = False


def make_combined_edge_contract_session(session, *, entity_name: str, contract_name: str) -> None:
    """Seed a compact CRUD project with all Studio-owned edge-contract families."""
    make_exportable_smoke_session(session, entity_name=entity_name, contract_name=contract_name)
    entity_id = f"{entity_name[0].lower()}{entity_name[1:]}Id"
    namespace = f"urn:edgeforge:smoke:{contract_name}:v1"
    soap_in_namespace = f"urn:edgeforge:smoke:{contract_name}-soap-in:v1"
    soap_out_namespace = f"urn:edgeforge:smoke:{contract_name}-soap-out:v1"
    get_operation = f"get{entity_name}"
    sync_operation = f"sync{entity_name}"

    session.identity_role_decisions = [
        IdentityRoleDecision(entity=entity_name, field=entity_id, role="persistence_id")
    ]
    session.upstream_interfaces.extend(
        [
            UpstreamInterface(
                name=f"{contract_name}-csv-in",
                system="source-system",
                type="file-csv",
                version="1.0",
                spec=f"upstream/{contract_name}-csv-layout.yaml",
                spec_content=_csv_layout(entity_id),
                entity_name=entity_name,
                field_mappings=[
                    FieldMapping(source=entity_id, target=f"{entity_name}.{entity_id}"),
                    FieldMapping(source="status", target=f"{entity_name}.status"),
                ],
                mapping_path=f"upstream/{contract_name}-csv-mapping.yaml",
                sample_path=f"upstream/{contract_name}-sample.csv",
                sample_content=f"{entity_id}|status\nid-1|draft\n",
            ),
            UpstreamInterface(
                name=f"{contract_name}-xml-in",
                system="source-system",
                type="xml-xsd",
                version="1.0",
                xsd_path=f"contracts/{contract_name}-in.xsd",
                xsd_content=_xml_xsd(entity_name, namespace),
                root_element=f"{entity_name}Message",
                namespace=namespace,
                namespace_alias="smk",
                entity_name=entity_name,
                field_mappings=[
                    FieldMapping(
                        source=entity_id,
                        target=f"{entity_name}.{entity_id}",
                    ),
                    FieldMapping(
                        source="status",
                        target=f"{entity_name}.status",
                    ),
                ],
                mapping_path=f"mappings/{contract_name}-xml-in-mapping.yaml",
                sample_path=f"samples/{contract_name}.xml",
                sample_content=_xml_sample(entity_name, entity_id, namespace),
            ),
            UpstreamInterface(
                name=f"{contract_name}-soap-service",
                system="source-system",
                type="soap-wsdl",
                version="1.0",
                wsdl_path=f"contracts/{contract_name}-soap-service.wsdl",
                wsdl_content=_soap_read_wsdl(entity_name, entity_id, soap_in_namespace),
                service=f"{entity_name}Service",
                port=f"{entity_name}ServicePort",
                binding=f"{entity_name}SoapBinding",
                namespace=soap_in_namespace,
                selected_operation_name=get_operation,
                soap_operation_mode="canonical",
                soap_canonical_operation=SoapCanonicalOperationConfig(
                    entity=entity_name,
                    lookup_field=entity_id,
                    request_path=f"/Get{entity_name}Request/{entity_id}",
                    response_mappings=[
                        SoapResponseMapping(
                            source=f"{entity_name}.{entity_id}",
                            target_path=f"/Get{entity_name}Response/{entity_id}",
                        ),
                        SoapResponseMapping(
                            source=f"{entity_name}.status",
                            target_path=f"/Get{entity_name}Response/status",
                        ),
                    ],
                    not_found_fault=f"{entity_name}NotFoundFault",
                    not_found_message=f"{entity_name} not found",
                ),
            ),
        ]
    )
    session.downstream_interfaces.extend(
        [
            DownstreamInterface(
                name=f"{contract_name}-csv-out",
                system="target-system",
                type="file-csv",
                version="1.0",
                spec=f"downstream/{contract_name}-csv-layout.yaml",
                spec_content=_csv_layout(entity_id, delimiter="~"),
                entity_name=entity_name,
                field_mappings=[
                    FieldMapping(source=f"{entity_name}.{entity_id}", target=entity_id),
                    FieldMapping(source=f"{entity_name}.status", target="status"),
                ],
                mapping_path=f"downstream/{contract_name}-csv-mapping.yaml",
            ),
            DownstreamInterface(
                name=f"{contract_name}-xml-out",
                system="target-system",
                type="xml-xsd",
                version="1.0",
                xsd_path=f"contracts/{contract_name}-out.xsd",
                xsd_content=_xml_xsd(entity_name, namespace),
                root_element=f"{entity_name}Message",
                namespace=namespace,
                namespace_alias="smk",
                entity_name=entity_name,
                field_mappings=[
                    FieldMapping(
                        source=f"{entity_name}.{entity_id}",
                        target=entity_id,
                    ),
                    FieldMapping(
                        source=f"{entity_name}.status",
                        target="status",
                    ),
                ],
                mapping_path=f"mappings/{contract_name}-xml-out-mapping.yaml",
            ),
            DownstreamInterface(
                name=f"{contract_name}-soap-client",
                system="target-system",
                type="soap-wsdl",
                version="1.0",
                wsdl_path=f"contracts/{contract_name}-soap-client.wsdl",
                wsdl_content=_soap_sync_wsdl(entity_name, entity_id, soap_out_namespace),
                service=f"{entity_name}SyncService",
                port=f"{entity_name}SyncServicePort",
                binding=f"{entity_name}SyncSoapBinding",
                namespace=soap_out_namespace,
                selected_operation_name=sync_operation,
                soap_operation_mode="canonical",
                soap_canonical_invocation=SoapCanonicalInvocationConfig(
                    entity=entity_name,
                    lookup_field=entity_id,
                    request_field="id",
                    request_mappings=[
                        SoapRequestMapping(
                            source=f"{entity_name}.{entity_id}",
                            target_path=f"/Sync{entity_name}Request/{entity_id}",
                        ),
                        SoapRequestMapping(
                            source=f"{entity_name}.status",
                            target_path=f"/Sync{entity_name}Request/status",
                        ),
                    ],
                    response_mode="return_only",
                    response_mappings=[
                        SoapReturnMapping(
                            source_path=f"/Sync{entity_name}Response/resultCode",
                            target="resultCode",
                        ),
                        SoapReturnMapping(
                            source_path=f"/Sync{entity_name}Response/message",
                            target="message",
                        ),
                    ],
                ),
            ),
        ]
    )
    session.data_handoffs = [
        DataHandoff(
            name=f"{contract_name}-staging-table",
            system="staging-system",
            type="staging-table",
            version="1.0",
            spec=f"data-handoffs/{contract_name}-staging-table.sql",
            ddl_content=(
                f"CREATE TABLE {contract_name}_staging "
                f"({entity_id} VARCHAR(36) NOT NULL, status VARCHAR(32));"
            ),
            table_name=f"{contract_name}_staging",
            entity_name=entity_name,
            field_mappings=[
                FieldMapping(source=f"{entity_name}.{entity_id}", target=entity_id),
                FieldMapping(source=f"{entity_name}.status", target="status"),
            ],
            mapping_path=f"data-handoffs/{contract_name}-staging-mapping.yaml",
        )
    ]


def post_step1(
    client: TestClient,
    csrf_token: str,
    *,
    app_name: str,
    bounded_context: str,
    output_path: Path,
) -> None:
    response = client.post(
        "/",
        data={
            "_edgeforge_csrf_token": csrf_token,
            "app_name": app_name,
            "bounded_context": bounded_context,
            "app_archetype": "crud",
            "target_profile": "springboot-standard-enterprise",
            "output_path": str(output_path),
            "appbuilder_repo_path": "/tmp/user-supplied-engine",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def assert_csrf_enforced(client: TestClient) -> None:
    native_blocked = client.post(
        "/",
        data={
            "app_name": "Blocked Native",
            "bounded_context": "blocked-native",
            "app_archetype": "crud",
            "target_profile": "springboot-standard-enterprise",
        },
        follow_redirects=False,
    )
    assert native_blocked.status_code == 403
    assert_no_ka_noise(native_blocked.json())

    fetch_blocked = client.post(
        "/upstream/ingest-url",
        data={"spec_url": "https://api.example.test/openapi.yaml"},
    )
    assert fetch_blocked.status_code == 403
    assert_no_ka_noise(fetch_blocked.json())
    assert session_for_client(client).raw_spec_url is None


def assert_build_run_rejected_server_side(client: TestClient, csrf_token: str) -> None:
    build_blocked = client.post("/export/build", headers=csrf_headers(csrf_token))
    run_blocked = client.post("/export/run", headers=csrf_headers(csrf_token))
    assert build_blocked.status_code == 403
    assert run_blocked.status_code == 403
    assert_no_ka_noise(build_blocked.json())
    assert_no_ka_noise(run_blocked.json())


def assert_server_owned_paths(
    *,
    output_a: Path,
    output_b: Path,
    workspace_a: Path,
    workspace_b: Path,
    evil_a: Path,
    evil_b: Path,
) -> None:
    assert output_a != output_b
    assert_path_under(output_a, workspace_a)
    assert_path_under(output_b, workspace_b)
    assert not output_a.is_relative_to(output_b)
    assert not output_b.is_relative_to(output_a)
    assert not evil_a.exists()
    assert not evil_b.exists()


def assert_openapi_url_policy(client: TestClient, csrf_token: str) -> None:
    import app.services.openapi_fetch_guard as openapi_fetch_guard

    original_open = openapi_fetch_guard._open_url

    def fail_network(*_args, **_kwargs):
        raise AssertionError("loopback URL should be rejected before any network call")

    try:
        openapi_fetch_guard._open_url = fail_network
        loopback_rejected = client.post(
            "/upstream/ingest-url",
            headers=csrf_headers(csrf_token),
            data={"spec_url": "http://127.0.0.1:8081/v3/api-docs"},
        )
    finally:
        openapi_fetch_guard._open_url = original_open
    assert loopback_rejected.status_code == 400
    assert loopback_rejected.json()["ok"] is False
    assert "host is not allowed" in loopback_rejected.json()["error"]
    assert_no_ka_noise(loopback_rejected.json())


def upload_openapi(client: TestClient, csrf_token: str, *, filename: str, entity_name: str) -> dict:
    response = client.post(
        "/upstream/ingest-file",
        headers=csrf_headers(csrf_token),
        files={
            "spec_file": (
                filename,
                generic_openapi_spec(entity_name),
                "application/yaml",
            )
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert_no_ka_noise(payload)
    return payload


def export_package(client: TestClient, csrf_token: str) -> dict:
    response = client.post("/export/write", headers=csrf_headers(csrf_token))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert_no_ka_noise(payload)
    return payload


def assert_path_under(path: str | Path, root: str | Path) -> None:
    assert Path(path).resolve().is_relative_to(Path(root).resolve())


def _csv_layout(field_name: str, *, delimiter: str = "|") -> str:
    return (
        "format: csv\n"
        f"delimiter: \"{delimiter}\"\n"
        "has_header_row: true\n"
        "record_types:\n"
        "  data:\n"
        "    fields:\n"
        f"      - name: {field_name}\n"
        "        column: 1\n"
        "        type: string\n"
        "        required: true\n"
        "      - name: status\n"
        "        column: 2\n"
        "        type: string\n"
        "        required: true\n"
    )


def _xml_xsd(entity_name: str, namespace: str) -> str:
    entity_id = f"{entity_name[0].lower()}{entity_name[1:]}Id"
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        f"<xs:schema xmlns:xs=\"http://www.w3.org/2001/XMLSchema\" targetNamespace=\"{namespace}\" "
        f"xmlns:tns=\"{namespace}\" elementFormDefault=\"qualified\">\n"
        f"  <xs:element name=\"{entity_name}Message\">\n"
        "    <xs:complexType>\n"
        "      <xs:sequence>\n"
        f"        <xs:element name=\"{entity_id}\" type=\"xs:string\"/>\n"
        "        <xs:element name=\"status\" type=\"xs:string\"/>\n"
        "      </xs:sequence>\n"
        "    </xs:complexType>\n"
        "  </xs:element>\n"
        "</xs:schema>\n"
    )


def _xml_sample(entity_name: str, entity_id: str, namespace: str) -> str:
    return (
        f"<{entity_name}Message xmlns=\"{namespace}\">"
        f"<{entity_id}>id-1</{entity_id}><status>draft</status>"
        f"</{entity_name}Message>\n"
    )


def _soap_read_wsdl(entity_name: str, entity_id: str, namespace: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/"
    xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"
    xmlns:xs="http://www.w3.org/2001/XMLSchema"
    xmlns:tns="{namespace}"
    targetNamespace="{namespace}">
  <wsdl:types>
    <xs:schema targetNamespace="{namespace}" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:tns="{namespace}" elementFormDefault="qualified">
      <xs:element name="Get{entity_name}Request">
        <xs:complexType><xs:sequence><xs:element name="{entity_id}" type="xs:string"/></xs:sequence></xs:complexType>
      </xs:element>
      <xs:element name="Get{entity_name}Response">
        <xs:complexType><xs:sequence><xs:element name="{entity_id}" type="xs:string"/><xs:element name="status" type="xs:string"/></xs:sequence></xs:complexType>
      </xs:element>
      <xs:element name="{entity_name}NotFoundFault">
        <xs:complexType><xs:sequence><xs:element name="message" type="xs:string"/></xs:sequence></xs:complexType>
      </xs:element>
    </xs:schema>
  </wsdl:types>
  <wsdl:message name="Get{entity_name}RequestMessage"><wsdl:part name="parameters" element="tns:Get{entity_name}Request"/></wsdl:message>
  <wsdl:message name="Get{entity_name}ResponseMessage"><wsdl:part name="parameters" element="tns:Get{entity_name}Response"/></wsdl:message>
  <wsdl:message name="{entity_name}FaultMessage"><wsdl:part name="parameters" element="tns:{entity_name}NotFoundFault"/></wsdl:message>
  <wsdl:portType name="{entity_name}PortType">
    <wsdl:operation name="get{entity_name}">
      <wsdl:input message="tns:Get{entity_name}RequestMessage"/>
      <wsdl:output message="tns:Get{entity_name}ResponseMessage"/>
      <wsdl:fault name="{entity_name}NotFoundFault" message="tns:{entity_name}FaultMessage"/>
    </wsdl:operation>
  </wsdl:portType>
  <wsdl:binding name="{entity_name}SoapBinding" type="tns:{entity_name}PortType">
    <soap:binding style="document" transport="http://schemas.xmlsoap.org/soap/http"/>
    <wsdl:operation name="get{entity_name}">
      <soap:operation soapAction="urn:get{entity_name}"/>
      <wsdl:input><soap:body use="literal"/></wsdl:input>
      <wsdl:output><soap:body use="literal"/></wsdl:output>
      <wsdl:fault name="{entity_name}NotFoundFault"><soap:fault name="{entity_name}NotFoundFault" use="literal"/></wsdl:fault>
    </wsdl:operation>
  </wsdl:binding>
  <wsdl:service name="{entity_name}Service">
    <wsdl:port name="{entity_name}ServicePort" binding="tns:{entity_name}SoapBinding">
      <soap:address location="https://example.invalid/service"/>
    </wsdl:port>
  </wsdl:service>
</wsdl:definitions>
"""


def _soap_sync_wsdl(entity_name: str, entity_id: str, namespace: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/"
    xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"
    xmlns:xs="http://www.w3.org/2001/XMLSchema"
    xmlns:tns="{namespace}"
    targetNamespace="{namespace}">
  <wsdl:types>
    <xs:schema targetNamespace="{namespace}" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:tns="{namespace}" elementFormDefault="qualified">
      <xs:element name="Sync{entity_name}Request">
        <xs:complexType><xs:sequence><xs:element name="{entity_id}" type="xs:string"/><xs:element name="status" type="xs:string"/></xs:sequence></xs:complexType>
      </xs:element>
      <xs:element name="Sync{entity_name}Response">
        <xs:complexType><xs:sequence><xs:element name="resultCode" type="xs:string"/><xs:element name="message" type="xs:string" minOccurs="0"/></xs:sequence></xs:complexType>
      </xs:element>
    </xs:schema>
  </wsdl:types>
  <wsdl:message name="Sync{entity_name}RequestMessage"><wsdl:part name="parameters" element="tns:Sync{entity_name}Request"/></wsdl:message>
  <wsdl:message name="Sync{entity_name}ResponseMessage"><wsdl:part name="parameters" element="tns:Sync{entity_name}Response"/></wsdl:message>
  <wsdl:portType name="{entity_name}SyncPortType">
    <wsdl:operation name="sync{entity_name}">
      <wsdl:input message="tns:Sync{entity_name}RequestMessage"/>
      <wsdl:output message="tns:Sync{entity_name}ResponseMessage"/>
    </wsdl:operation>
  </wsdl:portType>
  <wsdl:binding name="{entity_name}SyncSoapBinding" type="tns:{entity_name}SyncPortType">
    <soap:binding style="document" transport="http://schemas.xmlsoap.org/soap/http"/>
    <wsdl:operation name="sync{entity_name}">
      <soap:operation soapAction="urn:sync{entity_name}"/>
      <wsdl:input><soap:body use="literal"/></wsdl:input>
      <wsdl:output><soap:body use="literal"/></wsdl:output>
    </wsdl:operation>
  </wsdl:binding>
  <wsdl:service name="{entity_name}SyncService">
    <wsdl:port name="{entity_name}SyncServicePort" binding="tns:{entity_name}SyncSoapBinding">
      <soap:address location="https://example.invalid/sync"/>
    </wsdl:port>
  </wsdl:service>
</wsdl:definitions>
"""
