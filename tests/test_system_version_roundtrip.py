"""Route-level regression tests: system/version round-trip through save -> export/write -> manifest."""

import yaml
from fastapi.testclient import TestClient

from app.main import app
from tests.session_helpers import reset_session, save_session
from tests.test_package_writer import _full_session

client = TestClient(app)


def test_downstream_save_preserves_system_and_version_through_to_manifest(tmp_path):
    reset_session()

    # Seed a minimal exportable session using _full_session() as the base.
    session = _full_session()
    session.output_path = str(tmp_path)
    # Remove any pre-seeded downstream so the POST result is the only one.
    session.downstream_interfaces = []
    save_session(session)

    # POST to /downstream/save with system and version fields set.
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
                ],
                "field_mappings": [
                    {"source": "Account.accountId", "target": "account_id"},
                ],
                "sample_content": None,
            }
        ]
    })
    assert response.status_code == 200
    assert response.json()["ok"] is True

    # Export the package to tmp_path.
    write_resp = client.post("/export/write")
    assert write_resp.status_code == 200
    assert write_resp.json()["ok"] is True

    # Read the exported app-definition.yaml and verify system/version survive.
    project_dir = tmp_path / "records"
    manifest = yaml.safe_load((project_dir / "app-definition.yaml").read_text())

    downstream = manifest.get("downstream_interfaces", [])
    assert len(downstream) == 1
    assert downstream[0]["system"] == "SWIFT"
    assert downstream[0]["version"] == "v2"

    reset_session()


def test_handoff_save_preserves_system_and_version_through_to_manifest(tmp_path):
    reset_session()

    # Seed a minimal exportable session using _full_session() as the base.
    session = _full_session()
    session.output_path = str(tmp_path)
    # Remove any pre-seeded handoffs so the POST result is the only one.
    session.data_handoffs = []
    save_session(session)

    # POST to /handoffs/save with system and version fields set.
    response = client.post("/handoffs/save", json={
        "handoffs": [
            {
                "name": "account-staging",
                "system": "ETL",
                "version": "v3",
                "type": "staging-table",
                "entity_name": "Account",
                "ddl_content": "CREATE TABLE t (id VARCHAR(36) NOT NULL);",
                "field_mappings": [
                    {"source": "Account.accountId", "target": "id"},
                ],
            }
        ]
    })
    assert response.status_code == 200
    assert response.json()["ok"] is True

    # Export the package to tmp_path.
    write_resp = client.post("/export/write")
    assert write_resp.status_code == 200
    assert write_resp.json()["ok"] is True

    # Read the exported app-definition.yaml and verify system/version survive.
    project_dir = tmp_path / "records"
    manifest = yaml.safe_load((project_dir / "app-definition.yaml").read_text())

    handoffs = manifest.get("data_handoffs", [])
    assert len(handoffs) == 1
    assert handoffs[0]["system"] == "ETL"
    assert handoffs[0]["version"] == "v3"

    reset_session()
