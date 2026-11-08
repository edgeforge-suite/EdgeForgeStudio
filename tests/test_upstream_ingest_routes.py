"""Route-level tests for Step 2 OpenAPI ingest flows."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.main import app
from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    IdentityRoleDecision,
    UpstreamInterface,
)
from app.services.upload_limits import DEFAULT_MAX_UPLOAD_BYTES, max_upload_bytes
from tests.session_helpers import get_session, reset_session, save_session
from tests.test_edge_contracts import SAMPLE_WSDL, SAMPLE_XSD
from tests.test_openapi_service import SAMPLE_SPEC

client = TestClient(app)

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _shared_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    client = TestClient(app, base_url="https://testserver")
    response = client.get("/")
    assert response.status_code == 200
    return client


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def test_ingest_file_accepts_yaml_upload_and_persists_session_state():
    yaml_text = yaml.safe_dump(SAMPLE_SPEC, sort_keys=False)

    response = client.post(
        "/upstream/ingest-file",
        files={"spec_file": ("sample-spec.yaml", yaml_text, "application/yaml")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert {entity["name"] for entity in body["entities"]} >= {"Account", "CreateAccountRequest"}
    assert {op["name"] for op in body["operations"]} == {"createAccount", "getAccount"}

    session = get_session()
    assert session.raw_spec_filename == "sample-spec.yaml"
    assert session.raw_spec_url is None
    assert session.raw_spec_content == yaml_text
    assert any(entity.name == "Account" for entity in session.classified_entities)


def test_upload_limit_env_falls_back_for_invalid_values(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_MAX_UPLOAD_BYTES", "not-a-number")
    assert max_upload_bytes() == DEFAULT_MAX_UPLOAD_BYTES

    monkeypatch.setenv("EDGEFORGE_STUDIO_MAX_UPLOAD_BYTES", "0")
    assert max_upload_bytes() == DEFAULT_MAX_UPLOAD_BYTES


def test_ingest_file_rejects_oversized_upload_without_mutating_session(monkeypatch):
    yaml_text = yaml.safe_dump(SAMPLE_SPEC, sort_keys=False)
    monkeypatch.setenv("EDGEFORGE_STUDIO_MAX_UPLOAD_BYTES", str(len(yaml_text) - 1))
    session = get_session()
    session.raw_spec_url = "https://example.com/original.yaml"
    session.raw_spec_content = "openapi: 3.0.0\ninfo: {title: Original, version: '1'}\npaths: {}\n"
    session.raw_spec_filename = None
    save_session(session)

    response = client.post(
        "/upstream/ingest-file",
        files={"spec_file": ("sample-spec.yaml", yaml_text, "application/yaml")},
    )

    assert response.status_code == 413
    body = response.json()
    assert body == {"ok": False, "error": f"Uploaded file exceeds the {len(yaml_text) - 1} bytes limit."}
    session = get_session()
    assert session.raw_spec_url == "https://example.com/original.yaml"
    assert session.raw_spec_filename is None
    assert session.raw_spec_content == "openapi: 3.0.0\ninfo: {title: Original, version: '1'}\npaths: {}\n"
    assert session.classified_entities == []
    assert session.classified_operations == []


def test_shared_mode_tokenless_ingest_url_rejects_before_mutating_session(monkeypatch):
    session = get_session()
    session.raw_spec_url = "https://example.com/original.yaml"
    session.raw_spec_content = "openapi: 3.0.0\ninfo: {title: Original, version: '1'}\npaths: {}\n"
    session.raw_spec_filename = None
    save_session(session)
    called = {"fetch": False}

    def fake_fetch(_url: str):
        called["fetch"] = True
        return SAMPLE_SPEC

    monkeypatch.setattr("app.routes.upstream.fetch_openapi_from_url", fake_fetch)
    shared_client = _shared_client(monkeypatch)

    response = shared_client.post(
        "/upstream/ingest-url",
        data={"spec_url": "https://example.com/openapi.yaml"},
    )

    assert response.status_code == 403
    assert called["fetch"] is False
    session = get_session()
    assert session.raw_spec_url == "https://example.com/original.yaml"
    assert session.raw_spec_filename is None
    assert session.raw_spec_content == "openapi: 3.0.0\ninfo: {title: Original, version: '1'}\npaths: {}\n"
    assert session.classified_entities == []
    assert session.classified_operations == []


def test_shared_mode_tokenless_ingest_file_rejects_before_mutating_session(monkeypatch):
    yaml_text = yaml.safe_dump(SAMPLE_SPEC, sort_keys=False)
    session = get_session()
    session.raw_spec_url = "https://example.com/original.yaml"
    session.raw_spec_content = "openapi: 3.0.0\ninfo: {title: Original, version: '1'}\npaths: {}\n"
    session.raw_spec_filename = None
    save_session(session)
    called = {"parse": False}

    def fake_parse(_content: str):
        called["parse"] = True
        return SAMPLE_SPEC

    monkeypatch.setattr("app.routes.upstream.parse_openapi_text", fake_parse)
    shared_client = _shared_client(monkeypatch)

    response = shared_client.post(
        "/upstream/ingest-file",
        files={"spec_file": ("sample-spec.yaml", yaml_text, "application/yaml")},
    )

    assert response.status_code == 403
    assert called["parse"] is False
    session = get_session()
    assert session.raw_spec_url == "https://example.com/original.yaml"
    assert session.raw_spec_filename is None
    assert session.raw_spec_content == "openapi: 3.0.0\ninfo: {title: Original, version: '1'}\npaths: {}\n"
    assert session.classified_entities == []
    assert session.classified_operations == []


def test_ingest_file_accepts_upload_at_exact_limit(monkeypatch):
    yaml_text = yaml.safe_dump(SAMPLE_SPEC, sort_keys=False)
    monkeypatch.setenv("EDGEFORGE_STUDIO_MAX_UPLOAD_BYTES", str(len(yaml_text)))

    response = client.post(
        "/upstream/ingest-file",
        files={"spec_file": ("sample-spec.yaml", yaml_text, "application/yaml")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert any(entity["name"] == "Account" for entity in body["entities"])


def test_ingest_url_rejects_blocked_scheme_before_network(monkeypatch):
    def fail_get(*args, **kwargs):
        raise AssertionError("network should not be called for blocked OpenAPI URLs")

    monkeypatch.setattr("app.services.openapi_fetch_guard._open_url", fail_get)

    response = client.post("/upstream/ingest-url", data={"spec_url": "file:///tmp/spec.yaml"})

    assert response.status_code == 400
    body = response.json()
    assert body == {"ok": False, "error": "OpenAPI URL must use http or https."}
    session = get_session()
    assert session.raw_spec_url is None
    assert session.raw_spec_content is None
    assert session.classified_entities == []
    assert session.classified_operations == []


def test_ingest_file_accepts_json_upload_and_persists_session_state():
    json_text = json.dumps(SAMPLE_SPEC)

    response = client.post(
        "/upstream/ingest-file",
        files={"spec_file": ("sample-spec.json", json_text, "application/json")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert {entity["name"] for entity in body["entities"]} >= {"Account", "PageableObject"}
    assert {op["name"] for op in body["operations"]} == {"createAccount", "getAccount"}

    session = get_session()
    assert session.raw_spec_filename == "sample-spec.json"
    assert session.raw_spec_url is None
    assert session.raw_spec_content == json_text
    assert any(op.name == "createAccount" for op in session.classified_operations)


def test_ingest_file_handles_nested_response_ref_and_envelope_fixture():
    fixture_path = FIXTURE_DIR / "parcel-response-upload.yaml"
    yaml_text = fixture_path.read_text(encoding="utf-8")

    response = client.post(
        "/upstream/ingest-file",
        files={"spec_file": (fixture_path.name, yaml_text, "application/yaml")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True

    wrapped_entity = next(
        entity for entity in body["entities"] if entity["name"] == "ParcelResponse"
    )
    assert wrapped_entity["classification"] == "entity"
    assert wrapped_entity["canonical_name"] == "ParcelNote"
    assert {field["name"] for field in wrapped_entity["fields"]} == {
        "parcelId",
        "label",
        "priority",
    }

    create_op = next(op for op in body["operations"] if op["name"] == "createParcel")
    assert create_op["response_schema"] == "ParcelResponse"
    assert create_op["path"] == "/parcel-notes"
    assert create_op["entity_candidates"] == ["ParcelNote"]


def test_real_uploaded_yaml_ingest_flows_cleanly_into_step3():
    fixture_path = FIXTURE_DIR / "parcel-response-upload.yaml"
    yaml_text = fixture_path.read_text(encoding="utf-8")

    ingest_response = client.post(
        "/upstream/ingest-file",
        files={"spec_file": (fixture_path.name, yaml_text, "application/yaml")},
    )
    assert ingest_response.status_code == 200
    assert ingest_response.json()["ok"] is True

    classify_response = client.get("/upstream/classify-debug")
    assert classify_response.status_code == 200
    classify_body = classify_response.json()
    assert classify_body["ok"] is True
    assert any(
        row["name"] == "ParcelResponse"
        for row in classify_body["by_classification"]["entity"]
    )

    step3_response = client.get("/entities")
    assert step3_response.status_code == 200
    assert "No entities classified yet." not in step3_response.text
    assert "ParcelNote" in step3_response.text
    save = client.post("/entities/save", json={
        "entities": ["ParcelResponse"],
        "operations": ["createParcel"],
        "entity_op_map": {"ParcelResponse": ["createParcel"]},
    })
    assert save.status_code == 200
    assert save.json()["ok"] is True
    session = get_session()
    # Browser selection stays keyed by the raw schema, not its canonical owner.
    assert session.selected_entity_names == ["ParcelResponse"]
    assert session.upstream_interfaces[0].entity_name == "ParcelNote"
    assert [op.name for op in session.upstream_interfaces[0].operations] == ["createParcel"]


def test_upstream_edge_contract_shell_saves_xml_without_classifying():
    response = client.post(
        "/upstream/edge-contract/save",
        json={
            "direction": "upstream",
            "name": "account-xml-feed",
            "type": "xml-xsd",
            "xsd_path": "contracts/account.xsd",
            "root_element": "acct:Account",
            "xsd_content": "<xs:schema/>",
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    session = get_session()
    assert session.upstream_interfaces[0].type == "xml-xsd"
    assert session.upstream_interfaces[0].xsd_path == "contracts/account.xsd"
    assert session.upstream_interfaces[0].root_element == "acct:Account"
    assert session.classified_entities == []
    assert session.classified_operations == []


def test_upstream_edge_contract_shell_rejects_missing_direction_and_remote_xml_url():
    response = client.post(
        "/upstream/edge-contract/save",
        json={
            "name": "account-xml-feed",
            "type": "xml-xsd",
            "spec_url": "https://example.com/account.xsd",
            "root_element": "Account",
        },
    )

    assert response.status_code == 400
    assert "direction" in response.json()["errors"][0]

    response = client.post(
        "/upstream/edge-contract/save",
        json={
            "direction": "upstream",
            "name": "account-xml-feed",
            "type": "xml-xsd",
            "spec_url": "https://example.com/account.xsd",
            "xsd_path": "contracts/account.xsd",
            "root_element": "Account",
        },
    )

    assert response.status_code == 400
    assert any("spec_url" in error for error in response.json()["errors"])


def test_upstream_edge_contract_shell_rejects_missing_contract_type():
    response = client.post(
        "/upstream/edge-contract/save",
        json={
            "direction": "upstream",
            "name": "account-feed",
            "spec": "upstream/account-feed-layout.yaml",
        },
    )

    assert response.status_code == 400
    assert "Select a contract type before saving." in response.json()["errors"]


def test_upstream_edge_contract_shell_rejects_path_traversal():
    response = client.post(
        "/upstream/edge-contract/save",
        json={
            "direction": "upstream",
            "name": "unsafe-xml",
            "type": "xml-xsd",
            "xsd_path": "../unsafe.xsd",
            "root_element": "Root",
        },
    )

    assert response.status_code == 400
    assert any("cannot contain '..'" in error for error in response.json()["errors"])


def test_upstream_edge_contract_shell_rejects_url_like_artifact_path():
    response = client.post(
        "/upstream/edge-contract/save",
        json={
            "direction": "upstream",
            "name": "url-xml",
            "type": "xml-xsd",
            "xsd_path": "https://example.com/schema.xsd",
            "root_element": "Root",
        },
    )

    assert response.status_code == 400
    assert any("not URLs" in error for error in response.json()["errors"])


def test_upstream_page_shows_edge_contract_readiness_summary(monkeypatch):
    # This assertion exercises the frozen legacy seed action. Pin its flag
    # state so the suite can also run under the refreshed Step 2 experience.
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    response = client.get("/upstream")
    assert response.status_code == 200
    assert "Saved contracts will appear in Loaded Edge Contracts after you save them." in response.text
    assert "Enter the package-relative artifact path and optionally paste reviewed content." in response.text
    assert "Format-specific inspection helps select metadata" in response.text
    assert "Canonical mapping" in response.text
    assert "This maps parsed file/XML fields to canonical metadata. It does not infer entities automatically." in response.text
    assert "Plain canonical targets like" in response.text
    assert "function buildUpstreamMappingSeedRows(names)" in response.text
    assert "renderDeterministicSeedPatch" in response.text
    assert "Enter canonical entity name before seeding target paths." in response.text
    assert "XML/XSD runtime generation needs reviewed XML-to-canonical mappings." in response.text
    assert "Inspect layout/sample" in response.text
    assert "inspectUpstreamFileContract" in response.text
    assert "CSV delimiter" in response.text
    assert "Has header row" in response.text
    assert "edge-contract-csv-delimiter" in response.text
    assert "edge-contract-csv-has-header" in response.text
    assert "Seed mapping rows from inspected fields" in response.text
    assert "edgeRawValue('edge-contract-sample-content')" in response.text
    assert "fileFieldToCanonicalField" in response.text
    assert "edge-map-source" in response.text
    assert "edge-map-target" in response.text
    assert "Seed XML mapping rows from inspected fields" in response.text
    assert "Inspect artifact" in response.text

    response = client.post(
        "/upstream/edge-contract/save",
        json={
            "direction": "upstream",
            "name": "account-xml-feed",
            "type": "xml-xsd",
            "xsd_path": "contracts/account.xsd",
            "root_element": "acct:Account",
        },
    )
    assert response.status_code == 200

    page = client.get("/upstream")

    assert page.status_code == 200
    assert "Loaded Edge Contracts" in page.text
    assert 'data-uxr-board="upstream"' in page.text
    assert "Review" in page.text
    assert "contracts/account.xsd" in page.text
    assert "Saved contracts will appear in Loaded Edge Contracts after you save them." not in page.text


def test_upstream_loaded_csv_summary_shows_delimiter_and_header_row():
    session = get_session()
    session.upstream_interfaces = [
        UpstreamInterface(
            name="account-csv-in",
            type="file-csv",
            spec="upstream/account-csv-layout.yaml",
            spec_content='format: csv\ndelimiter: "|"\nhas_header_row: true\nfields: []\n',
        )
    ]
    save_session(session)

    response = client.get("/upstream")

    assert response.status_code == 200
    assert "Loaded Edge Contracts" in response.text
    assert "delimiter pipe (|)" in response.text
    assert "header true" in response.text


def test_upstream_loaded_csv_summary_shows_tab_delimiter_readably():
    session = get_session()
    session.upstream_interfaces = [
        UpstreamInterface(
            name="account-csv-in",
            type="file-csv",
            spec="upstream/account-csv-layout.yaml",
            spec_content="format: csv\ndelimiter: tab\nhas_header_row: false\nfields: []\n",
        )
    ]
    save_session(session)

    response = client.get("/upstream")

    assert response.status_code == 200
    assert "delimiter tab" in response.text
    assert "header false" in response.text
    assert "Delimiter: <code>\t</code>" not in response.text


def test_upstream_loaded_non_csv_summary_does_not_show_csv_details():
    session = get_session()
    session.upstream_interfaces = [
        UpstreamInterface(
            name="account-fixed-in",
            type="file-fixed-width",
            spec="upstream/account-fixed-layout.yaml",
            spec_content=(
                "format: fixed-width\n"
                "record_types:\n"
                "  data:\n"
                "    fields: []\n"
            ),
        ),
        UpstreamInterface(
            name="account-xml-in",
            type="xml-xsd",
            xsd_path="contracts/account.xsd",
            root_element="Account",
        ),
    ]
    save_session(session)

    response = client.get("/upstream")

    assert response.status_code == 200
    assert "Loaded Edge Contracts" in response.text
    assert "Delimiter: <code>pipe (|)</code>" not in response.text
    assert "Header row: true" not in response.text


def test_upstream_loaded_csv_summary_shows_comma_delimiter_readably():
    session = get_session()
    session.upstream_interfaces = [
        UpstreamInterface(
            name="account-csv-in",
            type="file-csv",
            spec="upstream/account-csv-layout.yaml",
            spec_content="format: csv\ndelimiter: ','\nhas_header_row: true\nfields: []\n",
        )
    ]
    save_session(session)

    response = client.get("/upstream")

    assert response.status_code == 200
    assert "delimiter comma (,)" in response.text
    assert "Delimiter: <code>,</code>" not in response.text
    assert "header true" in response.text


def test_upstream_loaded_csv_summary_shows_not_specified_when_header_absent():
    session = get_session()
    session.upstream_interfaces = [
        UpstreamInterface(
            name="account-csv-in",
            type="file-csv",
            spec="upstream/account-csv-layout.yaml",
            spec_content="format: csv\ndelimiter: '|'\nfields: []\n",
        )
    ]
    save_session(session)

    response = client.get("/upstream")

    assert response.status_code == 200
    assert "delimiter pipe (|)" in response.text
    row_start = response.text.index('data-uxr-row-name="account-csv-in"')
    row_window = response.text[row_start : row_start + 1200]
    assert "header " not in row_window
    assert "Header row: true" not in response.text
    assert "Header row: false" not in response.text


def test_upstream_loaded_csv_summary_absent_for_csv_without_spec_content():
    session = get_session()
    session.upstream_interfaces = [
        UpstreamInterface(
            name="account-csv-ref",
            type="file-csv",
            spec="upstream/account-csv-layout.yaml",
        )
    ]
    save_session(session)

    response = client.get("/upstream")

    assert response.status_code == 200
    assert "Loaded Edge Contracts" in response.text
    assert "account-csv-ref" in response.text
    assert "Delimiter: <code>" not in response.text
    assert "Header row:" not in response.text


def test_upstream_loaded_csv_summary_absent_for_csv_with_unparseable_spec():
    session = get_session()
    session.upstream_interfaces = [
        UpstreamInterface(
            name="account-csv-broken",
            type="file-csv",
            spec="upstream/account-csv-layout.yaml",
            spec_content=": broken: yaml: [unclosed\n",
        )
    ]
    save_session(session)

    response = client.get("/upstream")

    assert response.status_code == 200
    assert "Loaded Edge Contracts" in response.text
    assert "Delimiter: <code>" not in response.text
    assert "Header row:" not in response.text


def test_upstream_loaded_csv_summary_shows_per_contract_for_multiple_csv_interfaces():
    session = get_session()
    session.upstream_interfaces = [
        UpstreamInterface(
            name="account-csv-pipe",
            type="file-csv",
            spec="upstream/account-pipe-layout.yaml",
            spec_content="format: csv\ndelimiter: '|'\nhas_header_row: true\nfields: []\n",
        ),
        UpstreamInterface(
            name="account-csv-comma",
            type="file-csv",
            spec="upstream/account-comma-layout.yaml",
            spec_content="format: csv\ndelimiter: ','\nhas_header_row: false\nfields: []\n",
        ),
    ]
    save_session(session)

    response = client.get("/upstream")

    assert response.status_code == 200
    text = response.text
    assert "account-csv-pipe" in text
    assert "account-csv-comma" in text
    pipe_pos = text.find("account-csv-pipe")
    comma_pos = text.find("account-csv-comma")
    pipe_delim_pos = text.find("pipe (|)", pipe_pos)
    comma_delim_pos = text.find("comma (,)", comma_pos)
    assert pipe_delim_pos > pipe_pos, "pipe delimiter label must follow pipe contract row"
    assert comma_delim_pos > comma_pos, "comma delimiter label must follow comma contract row"
    assert text.count("delimiter pipe (|) · header true") == 1
    assert text.count("delimiter comma (,) · header false") == 1


def test_upstream_loaded_csv_summary_visible_after_save_round_trip():
    response = client.post(
        "/upstream/edge-contract/save",
        json={
            "direction": "upstream",
            "name": "account-csv-in",
            "type": "file-csv",
            "spec": "upstream/account-csv-in-layout.yaml",
            "spec_content": "format: csv\nfields: []\n",
            "csv_delimiter": "|",
            "csv_has_header_row": "true",
        },
    )
    assert response.status_code == 200

    page = client.get("/upstream")

    assert page.status_code == 200
    assert "delimiter pipe (|)" in page.text
    assert "header true" in page.text


def test_upstream_file_contract_inspection_returns_layout_and_sample_preview():
    response = client.post(
        "/upstream/edge-contract/file-inspect",
        json={
            "direction": "upstream",
            "type": "file-csv",
            "spec_content": "format: csv\ndelimiter: '|'\nfields:\n  - name: account_id\n  - name: status\n",
            "sample_content": "A123|ACTIVE\n",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["layout"]["delimiter"] == "|"
    assert payload["layout"]["fields"][0]["name"] == "account_id"
    assert payload["sample_preview"]["rows"][0]["columns"][1]["value"] == "ACTIVE"


def test_upstream_file_contract_inspection_uses_csv_controls_over_yaml():
    response = client.post(
        "/upstream/edge-contract/file-inspect",
        json={
            "direction": "upstream",
            "type": "file-csv",
            "spec_content": "format: csv\ndelimiter: ','\nfields:\n  - name: account_id\n  - name: status\n",
            "sample_content": "A123|ACTIVE\n",
            "csv_delimiter": "|",
            "csv_has_header_row": "true",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["layout"]["delimiter"] == "|"
    assert payload["layout"]["has_header_row"] is True
    assert payload["sample_preview"]["rows"][0]["columns"][1]["value"] == "ACTIVE"


def test_upstream_file_contract_inspection_preserves_sample_padding():
    response = client.post(
        "/upstream/edge-contract/file-inspect",
        json={
            "direction": "upstream",
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


def test_upstream_file_contract_inspection_rejects_non_file_types():
    response = client.post(
        "/upstream/edge-contract/file-inspect",
        json={
            "direction": "upstream",
            "type": "xml-xsd",
            "spec_content": "fields: []",
        },
    )

    assert response.status_code == 400
    assert "file-fixed-width and file-csv" in response.json()["errors"][0]


def test_upstream_edge_contract_shell_saves_file_canonical_mappings():
    response = client.post(
        "/upstream/edge-contract/save",
        json={
            "direction": "upstream",
            "name": "account-csv-in",
            "type": "file-csv",
            "spec": "upstream/account-csv-layout.yaml",
            "spec_content": "format: csv\nfields: []\n",
            "csv_delimiter": "|",
            "csv_has_header_row": "true",
            "entity_name": "Account",
            "field_mappings": [
                {"source": "account_id", "target": "accountId"},
                {"source": "status", "target": "Account.status"},
                {"source": "", "target": "ignored"},
            ],
        },
    )

    assert response.status_code == 200
    saved = get_session().upstream_interfaces[0]
    assert saved.type == "file-csv"
    assert saved.entity_name == "Account"
    assert saved.mapping_path == "upstream/account-csv-in-mapping.yaml"
    assert 'delimiter: "|"' in saved.spec_content
    assert "has_header_row: true" in saved.spec_content
    assert [(m.source, m.target) for m in saved.field_mappings] == [
        ("account_id", "accountId"),
        ("status", "Account.status"),
    ]


def test_upstream_edge_contract_shell_saves_xml_canonical_mappings():
    response = client.post(
        "/upstream/edge-contract/save",
        json={
            "direction": "upstream",
            "name": "account-xml-in",
            "type": "xml-xsd",
            "xsd_path": "contracts/account.xsd",
            "root_element": "AccountMessage",
            "entity_name": "Account",
            "field_mappings": [
                {"source": "accountId", "target": "accountId"},
                {"source": "sourceSystem", "target": "Account.sourceSystem"},
                {"source": "", "target": "ignored"},
            ],
        },
    )

    assert response.status_code == 200
    saved = get_session().upstream_interfaces[0]
    assert saved.type == "xml-xsd"
    assert saved.entity_name == "Account"
    assert saved.mapping_path == "upstream/account-xml-in-mapping.yaml"
    assert [(m.source, m.target) for m in saved.field_mappings] == [
        ("accountId", "accountId"),
        ("sourceSystem", "Account.sourceSystem"),
    ]


def test_step2_edge_contract_only_project_shows_saved_state_and_navigation():
    session = get_session()
    session.raw_spec_content = None
    session.raw_spec_url = None
    session.raw_spec_filename = None
    session.classified_entities = []
    session.classified_operations = []
    session.upstream_interfaces = [
        UpstreamInterface(
            name="account-xml-feed",
            type="xml-xsd",
            xsd_path="contracts/account.xsd",
            root_element="acct:Account",
        )
    ]
    save_session(session)

    response = client.get("/upstream")

    assert response.status_code == 200
    assert "Loaded Edge Contracts" in response.text
    assert "This reopened project has reviewed edge-contract interface references." in response.text
    assert response.text.index("Loaded Edge Contracts") < response.text.index("Add Upstream Edge Contract")
    assert "No OpenAPI classification source is loaded for Step 3 entity modeling." in response.text
    assert "Current Contract Source" not in response.text
    assert "Previous" in response.text
    assert 'href="/"' in response.text
    assert "Continue through wizard" in response.text
    assert 'href="/entities"' in response.text
    assert "Add one upstream contract at a time." in response.text
    assert "Multiple upstream edge contracts are supported. Save one contract at a time." in response.text
    assert "Enter the package-relative artifact path and optionally paste reviewed content." in response.text
    assert "Inspection reads pasted artifact content to help select contract metadata." in response.text
    assert "Select contract type..." in response.text
    assert "Fixed-width file" in response.text

    step3 = client.get("/entities")
    assert step3.status_code == 200
    assert "No OpenAPI-classified entities are loaded." in step3.text
    assert "Studio does not yet derive CRUD entities or operations from XML/XSD, SOAP/WSDL, or file contracts." in step3.text
    assert "Entity modeling is optional for this edge-contract package." in step3.text
    assert 'href="/upstream"' in step3.text
    assert 'href="/handoffs"' in step3.text
    assert "ingest an API spec" not in step3.text


def test_step2_openapi_classified_project_keeps_classification_results_and_navigation():
    yaml_text = yaml.safe_dump(SAMPLE_SPEC, sort_keys=False)
    ingest_response = client.post(
        "/upstream/ingest-file",
        files={"spec_file": ("sample-spec.yaml", yaml_text, "application/yaml")},
    )
    assert ingest_response.status_code == 200

    response = client.get("/upstream")

    assert response.status_code == 200
    assert "Classification Results" in response.text
    assert "Current Contract Source" in response.text
    assert "Uploaded Spec File" in response.text
    assert "Continue to Entity Model" in response.text
    assert 'href="/entities"' in response.text


def test_upstream_edge_contract_inspect_xml_returns_candidates_without_saving():
    response = client.post(
        "/upstream/edge-contract/inspect",
        json={
            "direction": "upstream",
            "type": "xml-xsd",
            "content": SAMPLE_XSD,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["candidates"]["target_namespace"] == "urn:accounts:v1"
    assert body["candidates"]["root_elements"][0]["qualified_name"] == "acct:AccountStatus"
    assert get_session().upstream_interfaces == []


def test_upstream_edge_contract_inspect_soap_returns_candidates_without_saving():
    response = client.post(
        "/upstream/edge-contract/inspect",
        json={
            "direction": "upstream",
            "type": "soap-wsdl",
            "content": SAMPLE_WSDL,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["selected"]["service"] == "AccountService"
    assert body["selected"]["port"] == "AccountServiceSoap11Port"
    assert body["selected"]["binding"] == "AccountServiceSoap11Binding"
    assert body["selected"]["operation"] == "GetAccountStatus"
    assert get_session().upstream_interfaces == []


def test_step2_shows_soap_operation_mapping_mode_controls():
    response = client.get("/upstream")

    assert response.status_code == 200
    assert "SOAP operation mapping" in response.text
    assert "Adapter-only handler scaffold" in response.text
    assert "Canonical read_by_id lookup" in response.text
    assert "SOAP body/header/fault field mapping beyond this" in response.text


def test_upstream_edge_contract_save_preserves_inspected_soap_operation():
    response = client.post(
        "/upstream/edge-contract/save",
        json={
            "direction": "upstream",
            "name": "account-soap",
            "type": "soap-wsdl",
            "wsdl_path": "contracts/account.wsdl",
            "wsdl_content": SAMPLE_WSDL,
            "service": "AccountService",
            "port": "AccountServiceSoap11Port",
            "binding": "AccountServiceSoap11Binding",
            "selected_operation_name": "GetAccountStatus",
        },
    )

    assert response.status_code == 200
    saved = get_session().upstream_interfaces[0]
    assert saved.type == "soap-wsdl"
    assert saved.selected_operation_name == "GetAccountStatus"
    assert [op.name for op in saved.operations] == ["GetAccountStatus"]
    assert saved.mapping_path == "mappings/account-soap-operation-mapping.yaml"

    response = client.post(
        "/upstream/edge-contract/save",
        json={
            "direction": "upstream",
            "name": "account-soap",
            "type": "soap-wsdl",
            "wsdl_path": "contracts/account.wsdl",
            "wsdl_content": SAMPLE_WSDL,
            "service": "AccountService",
            "port": "AccountServiceSoap11Port",
            "binding": "AccountServiceSoap11Binding",
            "selected_operation_name": "CloseAccount",
        },
    )

    assert response.status_code == 200
    saved = get_session().upstream_interfaces[0]
    assert saved.selected_operation_name == "CloseAccount"
    assert [op.name for op in saved.operations] == ["CloseAccount"]
    assert "GetAccountStatus" not in [op.name for op in saved.operations]
    assert saved.soap_operation_mode == "adapter_only"
    assert saved.soap_canonical_operation is None


def test_upstream_edge_contract_save_preserves_soap_canonical_read_by_id_mapping():
    session = get_session()
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
    save_session(session)

    response = client.post(
        "/upstream/edge-contract/save",
        json={
            "direction": "upstream",
            "name": "customer-soap",
            "type": "soap-wsdl",
            "wsdl_path": "contracts/customer.wsdl",
            "wsdl_content": SAMPLE_WSDL,
            "service": "CustomerService",
            "port": "CustomerServicePort",
            "binding": "CustomerServiceBinding",
            "selected_operation_name": "getCustomer",
            "soap_operation_mode": "canonical",
            "soap_handler_method": "handleGetCustomer",
            "soap_canonical_operation": {
                "kind": "read_by_id",
                "entity": "Customer",
                "lookup": {
                    "field": "customerId",
                    "request_path": "/GetCustomerRequest/customerId",
                },
                "response_mappings": [
                    {
                        "source": "Customer.customerId",
                        "target_path": "/GetCustomerResponse/customerId",
                    },
                    {
                        "source": "Customer.status",
                        "target_path": "/GetCustomerResponse/status",
                    },
                ],
                "not_found_fault": {
                    "fault": "customerFault",
                    "message": "Customer not found",
                },
            },
        },
    )

    assert response.status_code == 200
    saved = get_session().upstream_interfaces[0]
    assert saved.soap_operation_mode == "canonical"
    assert saved.soap_handler_method == "handleGetCustomer"
    assert saved.soap_canonical_operation is not None
    assert saved.soap_canonical_operation.entity == "Customer"
    assert saved.soap_canonical_operation.lookup_field == "customerId"
    assert saved.soap_canonical_operation.request_path == "/GetCustomerRequest/customerId"
    assert [(row.source, row.target_path) for row in saved.soap_canonical_operation.response_mappings] == [
        ("Customer.customerId", "/GetCustomerResponse/customerId"),
        ("Customer.status", "/GetCustomerResponse/status"),
    ]


def test_upstream_edge_contract_save_rejects_invalid_soap_canonical_mapping():
    session = get_session()
    session.classified_entities = [
        ClassifiedEntity(
            name="Customer",
            fields=[
                ClassifiedField(name="customerId", type="string", is_id=True),
                ClassifiedField(name="status", type="string"),
            ],
        )
    ]
    save_session(session)

    response = client.post(
        "/upstream/edge-contract/save",
        json={
            "direction": "upstream",
            "name": "customer-soap",
            "type": "soap-wsdl",
            "wsdl_path": "contracts/customer.wsdl",
            "selected_operation_name": "getCustomer",
            "soap_operation_mode": "canonical",
            "soap_canonical_operation": {
                "kind": "read_by_id",
                "entity": "Customer",
                "lookup": {
                    "field": "missingId",
                    "request_path": "GetCustomerRequest/customerId",
                },
                "response_mappings": [
                    {
                        "source": "Customer.missingStatus",
                        "target_path": "GetCustomerResponse/status",
                    }
                ],
            },
        },
    )

    assert response.status_code == 400
    errors = " ".join(response.json()["errors"])
    assert "Unknown lookup field 'missingId'" in errors
    assert "request path" in errors
    assert "Unknown SOAP response mapping field 'missingStatus'" in errors


def test_upstream_edge_contract_save_rejects_canonical_without_verified_model():
    response = client.post(
        "/upstream/edge-contract/save",
        json={
            "direction": "upstream",
            "name": "customer-soap",
            "type": "soap-wsdl",
            "wsdl_path": "contracts/customer.wsdl",
            "selected_operation_name": "getCustomer",
            "soap_operation_mode": "canonical",
            "soap_canonical_operation": {
                "kind": "read_by_id",
                "entity": "Customer",
                "lookup": {
                    "field": "customerId",
                    "request_path": "/GetCustomerRequest/customerId",
                },
                "response_mappings": [
                    {
                        "source": "Customer.customerId",
                        "target_path": "/GetCustomerResponse/customerId",
                    }
                ],
            },
        },
    )

    assert response.status_code == 400
    errors = " ".join(response.json()["errors"])
    assert "known canonical entity model" in errors
    assert "verified persistence ID field" in errors


def test_upstream_edge_contract_save_rejects_cross_entity_soap_response_source():
    session = get_session()
    session.classified_entities = [
        ClassifiedEntity(
            name="Customer",
            fields=[
                ClassifiedField(name="customerId", type="string", is_id=True),
                ClassifiedField(name="status", type="string"),
            ],
        ),
        ClassifiedEntity(
            name="Account",
            fields=[ClassifiedField(name="status", type="string")],
        ),
    ]
    session.identity_role_decisions = [
        IdentityRoleDecision(entity="Customer", field="customerId", role="persistence_id")
    ]
    save_session(session)

    response = client.post(
        "/upstream/edge-contract/save",
        json={
            "direction": "upstream",
            "name": "customer-soap",
            "type": "soap-wsdl",
            "wsdl_path": "contracts/customer.wsdl",
            "selected_operation_name": "getCustomer",
            "soap_operation_mode": "canonical",
            "soap_canonical_operation": {
                "kind": "read_by_id",
                "entity": "Customer",
                "lookup": {
                    "field": "customerId",
                    "request_path": "/GetCustomerRequest/customerId",
                },
                "response_mappings": [
                    {
                        "source": "Account.status",
                        "target_path": "/GetCustomerResponse/status",
                    }
                ],
            },
        },
    )

    assert response.status_code == 400
    assert any("must use canonical entity 'Customer'" in error for error in response.json()["errors"])


def test_upstream_edge_contract_save_rejects_adapter_with_canonical_config():
    response = client.post(
        "/upstream/edge-contract/save",
        json={
            "direction": "upstream",
            "name": "customer-soap",
            "type": "soap-wsdl",
            "wsdl_path": "contracts/customer.wsdl",
            "selected_operation_name": "getCustomer",
            "soap_operation_mode": "adapter_only",
            "soap_canonical_operation": {
                "kind": "read_by_id",
                "entity": "Customer",
            },
        },
    )

    assert response.status_code == 400
    assert any("Adapter-only" in error for error in response.json()["errors"])


def test_upstream_edge_contract_save_rejects_unknown_soap_mapping_mode():
    response = client.post(
        "/upstream/edge-contract/save",
        json={
            "direction": "upstream",
            "name": "customer-soap",
            "type": "soap-wsdl",
            "wsdl_path": "contracts/customer.wsdl",
            "selected_operation_name": "getCustomer",
            "soap_operation_mode": "magic",
        },
    )

    assert response.status_code == 400
    assert response.json()["errors"] == ["SOAP operation mapping mode must be adapter_only or canonical."]
