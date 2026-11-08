"""Tests for actionable, sanitized Step 8 Engine diagnostics."""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.main import app
from app.routes.export import _extract_actionable_summary
from tests.session_helpers import reset_session, save_session
from tests.test_package_writer import _full_session

client = TestClient(app)


def _seed_with_export(tmp_path):
    reset_session()
    session = _full_session()
    session.output_path = str(tmp_path)
    save_session(session)
    resp = client.post("/export/write")
    assert resp.json()["ok"] is True


def test_extract_actionable_summary_prefers_exception_tail():
    output = (
        "Traceback (most recent call last):\n"
        "  File \"<string>\", line 4, in <module>\n"
        "ValueError: Routing field 'paymentType' is not present in the passthrough upstream request contract\n"
    )
    assert _extract_actionable_summary(output) == (
        "ValueError: Routing field 'paymentType' is not present in the passthrough upstream request contract"
    )


def test_extract_actionable_summary_uses_signal_line_in_middle():
    output = (
        "Starting validation...\n"
        "Routing field 'paymentType' is not present in the passthrough upstream request contract\n"
        "Validation aborted.\n"
    )
    assert _extract_actionable_summary(output) == (
        "Routing field 'paymentType' is not present in the passthrough upstream request contract"
    )


def test_extract_actionable_summary_handles_passthrough_target_error():
    output = (
        "Checking routing rows...\n"
        "Transform target 'missingTarget' is not present in the passthrough downstream request contracts\n"
        "See raw output for more details.\n"
    )
    assert _extract_actionable_summary(output) == (
        "Transform target 'missingTarget' is not present in the passthrough downstream request contracts"
    )


def test_extract_actionable_summary_falls_back_to_first_meaningful_line():
    output = "stderr: connection refused while contacting local service\nmore text later"
    assert _extract_actionable_summary(output) == "stderr: connection refused while contacting local service"


def test_validate_failure_without_prefixed_lines_surfaces_in_errors(tmp_path, monkeypatch):
    """A raw traceback failure must appear in errors[], not just message."""
    _seed_with_export(tmp_path)

    fake = MagicMock()
    fake.success = False
    fake.combined_output = (
        "Traceback (most recent call last):\n"
        "  File \"<string>\", line 4, in <module>\n"
        "pydantic.ValidationError: 1 validation error for ProjectDefinition\n"
        "  schema_version: field required"
    )

    monkeypatch.setattr("app.routes.export.validate_manifest", lambda *a, **kw: fake)

    resp = client.post("/export/validate")
    assert resp.status_code == 200
    data = resp.json()

    assert data["ok"] is False
    assert len(data["errors"]) >= 1
    assert "ValidationError" in data["summary"]
    # The actionable error text must be in the errors list
    full_errors = " ".join(data["errors"])
    assert "pydantic" in full_errors or "schema_version" in full_errors or "ValidationError" in full_errors
    assert data["diagnostic_id"].startswith("diag-")
    assert data["diagnostic_id"] in data["message"]
    assert "Traceback" not in data["message"]

    reset_session()


def test_generate_failure_without_prefixed_lines_surfaces_in_errors(tmp_path, monkeypatch):
    """A generate failure with no structured lines must appear in errors[]."""
    _seed_with_export(tmp_path)

    fake = MagicMock()
    fake.success = False
    fake.combined_output = (
        "Traceback (most recent call last):\n"
        "  File \"/path/to/cli.py\", line 42, in generate\n"
        "KeyError: 'upstream_interfaces'"
    )

    monkeypatch.setattr("app.routes.export.run_generate", lambda *a, **kw: fake)

    resp = client.post("/export/generate")
    assert resp.status_code == 200
    data = resp.json()

    assert data["ok"] is False
    assert len(data["errors"]) >= 1
    assert data["summary"] == "KeyError: 'upstream_interfaces'"
    full_errors = " ".join(data["errors"])
    assert "KeyError" in full_errors or "upstream_interfaces" in full_errors
    assert data["diagnostic_id"].startswith("diag-")
    assert "/path/to/cli.py" not in data["message"]
    assert "Traceback" not in data["message"]

    reset_session()


def test_validate_success_still_has_empty_errors(tmp_path, monkeypatch):
    """Successful validation must still return empty errors list."""
    _seed_with_export(tmp_path)

    fake = MagicMock()
    fake.success = True
    fake.combined_output = "Manifest is valid (passed AppBuilder validation)"

    monkeypatch.setattr("app.routes.export.validate_manifest", lambda *a, **kw: fake)

    resp = client.post("/export/validate")
    data = resp.json()
    assert data["ok"] is True
    assert data["errors"] == []
    assert data["summary"] is None

    reset_session()


def test_validate_failure_with_error_prefix_still_works(tmp_path, monkeypatch):
    """Failures that already use ERROR: prefix must still populate errors list correctly."""
    _seed_with_export(tmp_path)

    fake = MagicMock()
    fake.success = False
    fake.combined_output = "ERROR: schema_version is required\nERROR: app_name missing"

    monkeypatch.setattr("app.routes.export.validate_manifest", lambda *a, **kw: fake)

    resp = client.post("/export/validate")
    data = resp.json()
    assert data["ok"] is False
    assert len(data["errors"]) == 2
    assert any("schema_version" in e for e in data["errors"])
    assert data["summary"] == "schema_version is required"

    reset_session()


def test_validate_subprocess_os_error_returns_json_failure(tmp_path, monkeypatch):
    """A validation subprocess startup OSError must not become an HTTP 500."""
    _seed_with_export(tmp_path)

    monkeypatch.setattr(
        "app.routes.export.validate_manifest",
        lambda *a, **kw: (_ for _ in ()).throw(OSError(35, "Resource deadlock avoided")),
    )

    resp = client.post("/export/validate")
    assert resp.status_code == 200
    data = resp.json()

    assert data["ok"] is False
    assert "Resource deadlock avoided" in data["summary"]
    assert any("Resource deadlock avoided" in error for error in data["errors"])

    reset_session()
