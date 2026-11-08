from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

from app.main import app
from app.models.project import DownstreamInterface, LayoutField
from app.services.csv_layout import project_csv_layout
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)

CSV_SPEC = """# settlement output
name: settlement-csv
format: csv
delimiter: "|" # reviewed delimiter
quote_char: '"'
escape_char: '\\'
line_separator: "\\n"
has_header_row: true
record_types:
  data:
    fields:
      - name: account_id # canonical id
        column: 1
        type: string
        format: uuid
      - name: balance
        column: 2
        type: decimal
        decimal_format: "0.00"
"""


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _seed_csv(spec_content: str = CSV_SPEC) -> DownstreamInterface:
    session = get_session()
    session.app_name = "CSV Layout Fixture"
    session.bounded_context = "csv-layout-fixture"
    session.app_archetype = "crud"
    session.project_revision = 4
    iface = DownstreamInterface(
        name="settlement-csv",
        type="file-csv",
        spec="downstream/settlement-layout.yaml",
        spec_content=spec_content,
    )
    session.downstream_interfaces = [iface]
    save_session(session)
    return iface


def _save_payload(spec: str = CSV_SPEC) -> dict:
    projection = project_csv_layout(spec)
    return {
        "name": "settlement-csv",
        "type": "file-csv",
        "spec": "downstream/settlement-layout.yaml",
        "spec_content": spec,
        "layout_fields": [],
        "field_mappings": [],
        "csv_delimiter": projection.delimiter,
        "csv_has_header_row": str(projection.has_header_row).lower(),
        "csv_layout_apply": True,
        "csv_layout_fields": projection.fields,
        "csv_layout_source_hash": projection.source_hash,
    }


def test_step5_projects_csv_rows_without_persisting_a_second_model():
    _seed_csv()

    response = client.get("/downstream?focus=settlement-csv")

    assert response.status_code == 200
    assert '"csv_layout_projection"' in response.text
    assert '"name": "account_id"' in response.text
    assert "csv-layout-fields-container" in response.text
    assert "applyDownstreamCsvControlsToSpec" not in response.text
    saved = get_session().downstream_interfaces[0]
    assert saved.layout_fields == []
    assert saved.spec_content == CSV_SPEC


def test_semantic_noop_save_preserves_csv_text_and_revision():
    _seed_csv()

    response = client.post(
        "/downstream/interface/save-one",
        json={
            "item": _save_payload(),
            "original_name": "settlement-csv",
            "source_of_truth_version": "4",
        },
    )

    assert response.status_code == 200
    assert response.json()["source_of_truth_version"] == "4"
    saved = get_session()
    assert saved.project_revision == 4
    assert saved.downstream_interfaces[0].spec_content == CSV_SPEC


def test_uppercase_engine_type_survives_step5_semantic_noop_save():
    uppercase_spec = CSV_SPEC.replace("type: decimal", "type: DECIMAL")
    _seed_csv(uppercase_spec)
    payload = _save_payload(uppercase_spec)

    assert payload["csv_layout_fields"][1]["type"] == "decimal"
    response = client.post(
        "/downstream/interface/save-one",
        json={
            "item": payload,
            "original_name": "settlement-csv",
            "source_of_truth_version": "4",
        },
    )

    assert response.status_code == 200
    assert response.json()["source_of_truth_version"] == "4"
    saved = get_session()
    assert saved.project_revision == 4
    assert saved.downstream_interfaces[0].spec_content == uppercase_spec
    assert response.json()["item"]["csv_layout_projection"]["fields"][1]["type"] == "decimal"


def test_structured_save_materializes_fields_and_preserves_advanced_yaml():
    _seed_csv()
    payload = _save_payload()
    payload["csv_layout_fields"][0]["name"] = "canonical_account_id"

    response = client.post(
        "/downstream/interface/save-one",
        json={
            "item": payload,
            "original_name": "settlement-csv",
            "source_of_truth_version": "4",
        },
    )

    assert response.status_code == 200
    saved_content = get_session().downstream_interfaces[0].spec_content or ""
    assert "name: canonical_account_id" in saved_content
    assert "# canonical id" in saved_content
    assert "format: uuid" in saved_content
    assert 'decimal_format: "0.00"' in saved_content
    assert "# reviewed delimiter" in saved_content
    assert response.json()["item"]["csv_layout_projection"]["fields"][0]["name"] == "canonical_account_id"


def test_stale_visual_projection_is_rejected_without_mutating_session():
    _seed_csv()
    payload = _save_payload()
    payload["spec_content"] = CSV_SPEC + "# manual edit\n"

    response = client.post(
        "/downstream/interface/save-one",
        json={
            "item": payload,
            "original_name": "settlement-csv",
            "source_of_truth_version": "4",
        },
    )

    assert response.status_code == 400
    assert "Inspect layout/sample again" in response.json()["blockers"][0]["label"]
    assert get_session().downstream_interfaces[0].spec_content == CSV_SPEC


def test_reinspection_prefers_manually_changed_yaml_over_stale_visual_controls():
    projection = project_csv_layout(CSV_SPEC)
    changed_spec = CSV_SPEC.replace('delimiter: "|"', 'delimiter: "~"')

    response = client.post(
        "/downstream/edge-contract/file-inspect",
        json={
            "direction": "downstream",
            "type": "file-csv",
            "name": "settlement-csv",
            "spec_content": changed_spec,
            "csv_delimiter": "|",
            "csv_has_header_row": "true",
            "csv_layout_apply": True,
            "csv_layout_fields": projection.fields,
            "csv_layout_source_hash": projection.source_hash,
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["csv_layout_projection"]["delimiter"] == "~"
    assert result["csv_layout_projection"]["source_hash"] != projection.source_hash


def test_reinspection_preserves_field_identity_for_metadata_safe_save():
    _seed_csv()
    projection = project_csv_layout(CSV_SPEC)
    edited_fields = [dict(field) for field in projection.fields]
    edited_fields[0]["name"] = "canonical_account_id"
    edited_fields[0]["column"] = 2
    edited_fields[1]["column"] = 1

    inspection = client.post(
        "/downstream/edge-contract/file-inspect",
        json={
            "direction": "downstream",
            "type": "file-csv",
            "name": "settlement-csv",
            "spec_content": CSV_SPEC,
            "csv_delimiter": "|",
            "csv_has_header_row": "true",
            "csv_layout_apply": True,
            "csv_layout_fields": edited_fields,
            "csv_layout_source_hash": projection.source_hash,
            "csv_layout_inspected_text": CSV_SPEC,
        },
    )

    assert inspection.status_code == 200
    inspected_fields = inspection.json()["csv_layout_projection"]["fields"]
    assert [
        (field["original_name"], field["original_column"])
        for field in inspected_fields
    ] == [("account_id", 1), ("balance", 2)]

    payload = _save_payload()
    payload["csv_layout_fields"] = inspected_fields
    saved = client.post(
        "/downstream/interface/save-one",
        json={
            "item": payload,
            "original_name": "settlement-csv",
            "source_of_truth_version": "4",
        },
    )

    assert saved.status_code == 200
    saved_content = get_session().downstream_interfaces[0].spec_content or ""
    fields = {
        field["name"]: field
        for field in yaml.safe_load(saved_content)["record_types"]["data"]["fields"]
    }
    assert fields["canonical_account_id"]["column"] == 2
    assert fields["canonical_account_id"]["format"] == "uuid"
    assert fields["balance"]["column"] == 1
    assert fields["balance"]["decimal_format"] == "0.00"
    assert "name: canonical_account_id # canonical id" in saved_content


def test_malformed_csv_content_blocks_bulk_save():
    response = client.post(
        "/downstream/save",
        json={
            "interfaces": [
                {
                    "name": "bad-csv",
                    "type": "file-csv",
                    "spec": "downstream/bad.csv-layout.yaml",
                    "spec_content": "record_types: [",
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "Malformed CSV layout/spec YAML" in " ".join(response.json()["errors"])
    assert get_session().downstream_interfaces == []


def test_reference_only_csv_remains_reference_only():
    response = client.post(
        "/downstream/save",
        json={
            "interfaces": [
                {
                    "name": "reference-csv",
                    "type": "file-csv",
                    "spec": "downstream/reference-layout.yaml",
                    "spec_content": None,
                    "csv_layout_apply": False,
                }
            ]
        },
    )

    assert response.status_code == 200
    saved = get_session().downstream_interfaces[0]
    assert saved.spec_content is None
    assert saved.layout_fields == []


def test_fixed_width_to_csv_conversion_is_explicit_in_template():
    html = client.get("/downstream").text

    assert "Convert the fixed-width field names to CSV columns 1 through N?" in html
    assert "select.value = previousType" in html
    assert "csv_layout_fields: csvFields" in html
    assert "csv_layout_apply: selectedType === 'file-csv' && csvFields.length > 0" in html


def test_csv_visual_rows_participate_in_async_inspection_stale_guard(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")

    html = client.get("/downstream").text
    context_source = html.split("function downstreamSeedPatchContext(card)", 1)[1].split(
        "function downstreamSeedPatchContextFingerprint", 1
    )[0]

    assert "csv_layout_fields: csvLayoutRows(card)" in context_source


def test_fixed_width_to_csv_conversion_persists_rows_as_engine_current_yaml():
    session = get_session()
    session.project_revision = 7
    session.downstream_interfaces = [
        DownstreamInterface(
            name="settlement-file",
            type="file-fixed-width",
            layout_fields=[
                LayoutField(name="account_id", start=1, length=36),
                LayoutField(name="status", start=37, length=12),
            ],
        )
    ]
    save_session(session)

    response = client.post(
        "/downstream/interface/save-one",
        json={
            "original_name": "settlement-file",
            "source_of_truth_version": "7",
            "item": {
                "name": "settlement-file",
                "type": "file-csv",
                "spec": "downstream/settlement-file-layout.yaml",
                "spec_content": None,
                "layout_fields": [],
                "field_mappings": [],
                "csv_delimiter": ",",
                "csv_has_header_row": "false",
                "csv_layout_apply": True,
                "csv_layout_fields": [
                    {"name": "account_id", "column": 1},
                    {"name": "status", "column": 2},
                ],
            },
        },
    )

    assert response.status_code == 200
    saved = get_session().downstream_interfaces[0]
    assert saved.type == "file-csv"
    assert saved.layout_fields == []
    projection = project_csv_layout(saved.spec_content)
    assert [(field["name"], field["column"]) for field in projection.fields] == [
        ("account_id", 1),
        ("status", 2),
    ]
