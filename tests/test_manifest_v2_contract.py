"""Manifest 2.0 producer and Engine mismatch diagnostics."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from app.integrations import appbuilder_integration as engine_integration
from app.integrations.appbuilder_integration import (
    SubprocessResult,
    run_apply,
    run_assess,
    run_change_plan,
    run_generate,
    validate_manifest,
)
from app.models.project import STUDIO_PROJECT_SCHEMA_VERSION
from app.services.evidence_trail import _EVIDENCE_TRAIL_SCHEMA_VERSION
from app.services.manifest_contract import (
    STUDIO_MANIFEST_SCHEMA_VERSION,
    manifest_version_mismatch_diagnostic,
)
from app.services.regen_preview import CHANGE_PLAN_SUPPORTED_MAJOR
from tests.openapi_cache_helpers import write_openapi_cache

_OLD_ENGINE_ERROR = "ValueError: Unknown schema_version '2.0'. Supported versions: 1.0"
_OLD_ENGINE_DIAGNOSTIC = (
    "This package uses manifest schema_version '2.0', but the configured EdgeForge Engine does "
    "not support it. Use the paired EdgeForge Engine release that supports manifest 2.0, then "
    "retry."
)
_STALE_PACKAGE_ERROR = "schema_version: '1.0' is not one of ['2.0']"
_STALE_PACKAGE_DIAGNOSTIC = (
    "This package uses manifest schema_version '1.0', while this Studio exports manifest 2.0. "
    "Reopen its saved Studio project and export it again, then use the paired EdgeForge Engine "
    "release that supports manifest 2.0."
)
_GENERIC_VERSION_DIAGNOSTIC = (
    "The package and configured EdgeForge Engine use incompatible manifest schema versions. "
    "This Studio exports manifest 2.0. Reopen the saved Studio project and export it again, and "
    "use the paired EdgeForge Engine release that supports manifest 2.0."
)
_ACTIVE_PROOF_RUNNERS = (
    "proof_run_engine_mcp_generate.py",
    "proof_run_petstore.py",
    "proof_run_codat_customer_downstream_handoff.py",
    "proof_run_configcat_permission_groups.py",
)


def _failure_result(message: str = _OLD_ENGINE_ERROR) -> SubprocessResult:
    return SubprocessResult(
        success=False,
        returncode=1,
        stdout="",
        stderr=message,
        combined_output=message,
        duration_seconds=0.01,
        command=["engine"],
        cwd="/tmp/engine",
    )


def test_manifest_and_independent_contract_versions_remain_distinct():
    assert STUDIO_MANIFEST_SCHEMA_VERSION == "2.0"
    assert STUDIO_PROJECT_SCHEMA_VERSION == "1.4"
    assert CHANGE_PLAN_SUPPORTED_MAJOR == 1
    assert _EVIDENCE_TRAIL_SCHEMA_VERSION == "1.1"


def test_manifest_version_diagnostic_distinguishes_old_engine_from_stale_package():
    assert manifest_version_mismatch_diagnostic(_OLD_ENGINE_ERROR) == _OLD_ENGINE_DIAGNOSTIC
    assert (
        manifest_version_mismatch_diagnostic(_STALE_PACKAGE_ERROR)
        == _STALE_PACKAGE_DIAGNOSTIC
    )
    assert (
        manifest_version_mismatch_diagnostic(
            "Unsupported manifest schema_version. Supported versions: 2.0"
        )
        == _GENERIC_VERSION_DIAGNOSTIC
    )


def test_active_proof_runners_use_the_manifest_producer_constant():
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"

    for script_name in _ACTIVE_PROOF_RUNNERS:
        source = (scripts_dir / script_name).read_text(encoding="utf-8")
        assert "STUDIO_MANIFEST_SCHEMA_VERSION" in source
        assert not re.search(r"schema_version[^\n]*1\.0", source), script_name


def test_synthetic_mcp_proof_has_a_self_contained_supported_write_contract(tmp_path):
    from app.services.package_writer import write_package_result
    from app.services.project_file_service import (
        deserialize_project,
        serialize_project,
        snapshot_session,
    )
    from scripts.proof_run_engine_mcp_generate import _full_session

    session = _full_session(tmp_path, tmp_path / "engine")
    project = snapshot_session(session)
    assert deserialize_project(serialize_project(project)) == project
    assert not session.capabilities.knowledge_assist_enabled
    result = write_package_result(session, tmp_path)
    assert result.warnings == []
    contract_path = next((result.project_dir / "contracts").glob("*-spec.json"))
    contract = json.loads(contract_path.read_text())
    operation = contract["paths"]["/notes"]["post"]
    assert operation["operationId"] == "createNote"
    assert operation["requestBody"]["required"] is True
    assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/Note"
    mapping = session.upstream_interfaces[0].operation_mappings[0]
    assert {row.target for row in mapping.request_mappings} == {"Note.label", "Note.state"}
    assert {row.target for row in mapping.response_mappings} == {"Note.noteId", "Note.label", "Note.state"}


def test_manifest_version_diagnostic_does_not_capture_unrelated_validation_errors():
    assert manifest_version_mismatch_diagnostic("schema_version: Field required") is None
    assert manifest_version_mismatch_diagnostic("entities: Field required") is None
    assert manifest_version_mismatch_diagnostic("Invalid manifest: mapping target is missing") is None


def test_validation_returns_actionable_version_message_and_logs_safe_projection(
    monkeypatch,
    tmp_path,
    caplog,
):
    monkeypatch.setattr(engine_integration, "_run_subprocess", lambda *_args, **_kwargs: _failure_result())

    with caplog.at_level(logging.ERROR):
        result = validate_manifest(tmp_path / "app-definition.yaml", str(tmp_path))

    assert result.combined_output == _OLD_ENGINE_DIAGNOSTIC
    assert result.stderr == _OLD_ENGINE_ERROR
    assert result.diagnostic_id in caplog.text
    assert _OLD_ENGINE_DIAGNOSTIC in caplog.text
    assert _OLD_ENGINE_ERROR not in caplog.text


def test_validation_tells_users_to_reexport_a_stale_package(monkeypatch, tmp_path):
    monkeypatch.setattr(
        engine_integration,
        "_run_subprocess",
        lambda *_args, **_kwargs: _failure_result(_STALE_PACKAGE_ERROR),
    )

    result = validate_manifest(tmp_path / "app-definition.yaml", str(tmp_path))

    assert result.combined_output == _STALE_PACKAGE_DIAGNOSTIC
    assert result.stderr == _STALE_PACKAGE_ERROR


def test_cli_and_mcp_generation_return_the_same_version_diagnostic(monkeypatch, tmp_path):
    monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_TRANSPORT", "subprocess")
    monkeypatch.setattr(engine_integration, "_run_subprocess", lambda *_args, **_kwargs: _failure_result())

    cli_result = run_generate(
        str(tmp_path / "app-definition.yaml"),
        str(tmp_path / "generated"),
        str(tmp_path),
    )

    async def fake_mcp_call(*_args, **_kwargs):
        return {
            "success": False,
            "output_dir": str(tmp_path / "generated"),
            "files_written": [],
            "warnings": [],
            "errors": [_OLD_ENGINE_ERROR],
        }

    monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_TRANSPORT", "mcp")
    monkeypatch.setattr(engine_integration, "_call_generate_app_mcp", fake_mcp_call)
    mcp_result = run_generate(
        str(tmp_path / "app-definition.yaml"),
        str(tmp_path / "generated"),
        str(tmp_path),
    )

    assert cli_result.combined_output == _OLD_ENGINE_DIAGNOSTIC
    assert cli_result.stderr == _OLD_ENGINE_ERROR
    assert mcp_result.combined_output == _OLD_ENGINE_DIAGNOSTIC
    assert _OLD_ENGINE_ERROR in mcp_result.stderr


def test_mcp_tool_exception_with_version_error_is_diagnosed(monkeypatch, tmp_path):
    async def failing_mcp_call(*_args, **_kwargs):
        raise RuntimeError(_OLD_ENGINE_ERROR)

    monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_TRANSPORT", "mcp")
    monkeypatch.setattr(engine_integration, "_call_generate_app_mcp", failing_mcp_call)

    result = run_generate(
        str(tmp_path / "app-definition.yaml"),
        str(tmp_path / "generated"),
        str(tmp_path),
    )

    assert result.combined_output == _OLD_ENGINE_DIAGNOSTIC
    assert _OLD_ENGINE_ERROR in result.stderr


def test_change_plan_and_apply_return_the_same_version_diagnostic(monkeypatch, tmp_path):
    repo = tmp_path / "engine"
    package = tmp_path / "package"
    manifest = package / "app-definition.yaml"
    repo.mkdir()
    package.mkdir()
    manifest.write_text("schema_version: '2.0'\n", encoding="utf-8")
    monkeypatch.setattr(engine_integration, "_run_subprocess", lambda *_args, **_kwargs: _failure_result())

    plan = run_change_plan(
        manifest,
        package,
        str(repo),
        allowed_roots=[str(package)],
    )
    apply = run_apply(
        manifest,
        package,
        str(repo),
        approved_plan_hash="approved-plan",
        allowed_roots=[str(package)],
    )

    assert plan.error == _OLD_ENGINE_DIAGNOSTIC
    assert plan.subprocess.stderr == _OLD_ENGINE_ERROR
    assert apply.error == _OLD_ENGINE_DIAGNOSTIC
    assert apply.subprocess.stderr == _OLD_ENGINE_ERROR


def test_assess_keeps_unrelated_subprocess_treatment(monkeypatch, tmp_path):
    monkeypatch.setattr(engine_integration, "_run_subprocess", lambda *_args, **_kwargs: _failure_result())
    url = "https://example.invalid/openapi.yaml"
    cache = write_openapi_cache(tmp_path, url)

    result = run_assess(
        url,
        str(tmp_path),
        openapi_cache_path=str(cache),
    )

    assert result.combined_output == _OLD_ENGINE_ERROR


def test_unrelated_manifest_validation_error_keeps_normal_message(monkeypatch, tmp_path):
    message = "ValidationError: entities: Field required"
    monkeypatch.setattr(
        engine_integration,
        "_run_subprocess",
        lambda *_args, **_kwargs: _failure_result(message),
    )

    result = validate_manifest(Path(tmp_path / "app-definition.yaml"), str(tmp_path))

    assert result.combined_output == f"Manifest validation failed: {message}"
