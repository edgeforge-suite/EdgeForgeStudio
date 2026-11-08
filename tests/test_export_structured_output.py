"""Tests for structured warning/error output from export_validate and export_generate."""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.main import app
from tests.session_helpers import reset_session, save_session
from tests.test_package_writer import _full_session

client = TestClient(app)


def _seed_exportable_session(tmp_path):
    """Seed a fully exportable session with last_export_path pointing into tmp_path."""
    reset_session()
    session = _full_session()
    session.output_path = str(tmp_path)
    save_session(session)
    # Write the package so last_export_path is set and app-definition.yaml exists.
    write_resp = client.post("/export/write")
    assert write_resp.status_code == 200
    assert write_resp.json()["ok"] is True


def test_export_validate_returns_structured_warnings_and_errors(tmp_path, monkeypatch):
    _seed_exportable_session(tmp_path)

    fake_result = MagicMock()
    fake_result.success = False
    fake_result.combined_output = "WARNING: something advisory\nERROR: manifest invalid\n"

    monkeypatch.setattr("app.routes.export.validate_manifest", lambda *args, **kwargs: fake_result)

    response = client.post("/export/validate")
    assert response.status_code == 200
    data = response.json()

    assert data["ok"] is False
    assert len(data["warnings"]) >= 1
    assert "something advisory" in data["warnings"][0]
    assert len(data["errors"]) >= 1
    assert "manifest invalid" in data["errors"][0]

    reset_session()


def test_export_generate_extracts_generation_warning_block(tmp_path, monkeypatch):
    _seed_exportable_session(tmp_path)

    fake_result = MagicMock()
    fake_result.success = True
    fake_result.combined_output = (
        "Generated application at: /tmp/x\n"
        "Harness: PASSED\n"
        "Generation warnings:\n"
        "  - synthetic-customer-api: Sample field 'address' in operation 'createCustomer' response auto-included in canonical model; add an explicit mapping to silence this warning.\n"
        "  - synthetic-customer-api: Sample field 'country' in operation 'createCustomer' response auto-included in canonical model; add an explicit mapping to silence this warning.\n"
    )

    monkeypatch.setattr("app.routes.export.run_generate", lambda *args, **kwargs: fake_result)

    response = client.post("/export/generate")
    assert response.status_code == 200
    data = response.json()

    assert data["ok"] is True
    assert len(data["warnings"]) == 2
    assert any("address" in w for w in data["warnings"])
    assert any("country" in w for w in data["warnings"])
    assert data["errors"] == []

    reset_session()


def test_export_generate_surfaces_mcp_warnings_and_errors(tmp_path, monkeypatch):
    _seed_exportable_session(tmp_path)

    fake_result = MagicMock()
    fake_result.success = False
    fake_result.combined_output = (
        "Generation failed via Engine MCP.\n"
        "WARNING: translation used default route metadata\n"
        "ERROR: downstream mapping is missing\n"
    )

    monkeypatch.setattr("app.routes.export.run_generate", lambda *args, **kwargs: fake_result)

    response = client.post("/export/generate")
    assert response.status_code == 200
    data = response.json()

    assert data["ok"] is False
    assert data["warnings"] == ["translation used default route metadata"]
    assert data["errors"] == ["downstream mapping is missing"]
    assert data["summary"] == "downstream mapping is missing"

    reset_session()


def test_export_validate_no_warnings_no_errors_returns_empty_arrays(tmp_path, monkeypatch):
    _seed_exportable_session(tmp_path)

    fake_result = MagicMock()
    fake_result.success = True
    fake_result.combined_output = "Validation passed.\n"

    monkeypatch.setattr("app.routes.export.validate_manifest", lambda *args, **kwargs: fake_result)

    response = client.post("/export/validate")
    assert response.status_code == 200
    data = response.json()

    assert data["ok"] is True
    assert data["warnings"] == []
    assert data["errors"] == []

    reset_session()
