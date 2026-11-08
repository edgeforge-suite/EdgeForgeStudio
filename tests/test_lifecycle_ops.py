from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.integrations.appbuilder_integration import (
    SubprocessResult,
    run_assess,
    run_generate,
    validate_manifest,
)
from app.models.project import ProjectSession
from app.services.build_run_service import build_generated_app
from app.services.identity import Principal
from app.services.ks_workspace import workspace_db_path
from app.services.quotas import (
    QuotaExceededError,
    ensure_ks_db_quota,
    ensure_session_disk_quota,
)
from app.services.settings import get_studio_settings
from app.services.sqlite_session_store import SqliteSessionStore
from tests.openapi_cache_helpers import write_openapi_cache


def _principal(session_id: str) -> Principal:
    return Principal(
        user_id=f"anonymous:{session_id}",
        source="anonymous",
        claims={"anonymous_session_id": session_id},
    )


def test_lifecycle_settings_read_env(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_MAX_SESSION_DISK_BYTES", "101")
    monkeypatch.setenv("EDGEFORGE_STUDIO_MAX_PROJECTS_PER_PRINCIPAL", "7")
    monkeypatch.setenv("EDGEFORGE_STUDIO_MAX_KS_DB_BYTES", "202")
    monkeypatch.setenv("EDGEFORGE_STUDIO_MAX_KS_SUBPROCESSES", "3")
    monkeypatch.setenv("EDGEFORGE_STUDIO_KS_IDLE_TTL_SECONDS", "17")
    monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_VALIDATE_TIMEOUT_SECONDS", "4")
    monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_ASSESS_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_GENERATE_TIMEOUT_SECONDS", "6")
    monkeypatch.setenv("EDGEFORGE_STUDIO_BUILD_TIMEOUT_SECONDS", "8")

    settings = get_studio_settings()

    assert settings.max_session_disk_bytes == 101
    assert settings.max_projects_per_principal == 7
    assert settings.max_ks_db_bytes == 202
    assert settings.max_ks_subprocesses == 3
    assert settings.ks_idle_ttl_seconds == 17
    assert settings.engine_validate_timeout_seconds == 4
    assert settings.engine_assess_timeout_seconds == 5
    assert settings.engine_generate_timeout_seconds == 6
    assert settings.build_timeout_seconds == 8


def test_session_disk_quota_rejects_projected_workspace_size(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "payload.bin").write_bytes(b"12345")
    session = ProjectSession(session_id="quota-session", workspace_root=str(workspace))
    monkeypatch.setenv("EDGEFORGE_STUDIO_MAX_SESSION_DISK_BYTES", "6")

    with pytest.raises(QuotaExceededError, match="Session workspace quota exceeded"):
        ensure_session_disk_quota(session, additional_bytes=2)


def test_ks_db_quota_rejects_existing_database_over_limit(monkeypatch, tmp_path):
    session = ProjectSession(session_id="ks-quota", workspace_root=str(tmp_path / "workspace"))
    db_path = Path(workspace_db_path(session))
    db_path.write_bytes(b"12345")
    monkeypatch.setenv("EDGEFORGE_STUDIO_MAX_KS_DB_BYTES", "4")

    with pytest.raises(QuotaExceededError, match="Knowledge Workspace database quota exceeded"):
        ensure_ks_db_quota(session)


def test_project_count_quota_rejects_new_catalog_entry(monkeypatch, tmp_path):
    monkeypatch.setenv("EDGEFORGE_STUDIO_MAX_PROJECTS_PER_PRINCIPAL", "1")
    store = SqliteSessionStore(state_dir=tmp_path)
    principal = _principal("project-quota")
    session = store.get_or_create(principal)

    with pytest.raises(QuotaExceededError, match="Project quota exceeded"):
        store.save_project(principal, session, project_id="new-project")


def test_appbuilder_timeouts_use_lifecycle_settings(monkeypatch, tmp_path):
    repo = tmp_path / "engine"
    repo.mkdir()
    manifest = tmp_path / "app-definition.yaml"
    manifest.write_text("app: demo\n", encoding="utf-8")
    captured: list[int] = []

    def fake_run_subprocess(cmd, **kwargs):
        captured.append(kwargs["timeout"])
        return SubprocessResult(
            success=True,
            returncode=0,
            stdout="VALID\n",
            stderr="",
            combined_output="VALID",
            duration_seconds=0.0,
            command=list(cmd),
            cwd=kwargs.get("cwd"),
        )

    monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_VALIDATE_TIMEOUT_SECONDS", "11")
    monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_ASSESS_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_GENERATE_TIMEOUT_SECONDS", "13")
    monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_TRANSPORT", "subprocess")
    monkeypatch.setattr("app.integrations.appbuilder_integration._run_subprocess", fake_run_subprocess)
    url = "http://example.com/openapi.json"
    cache = write_openapi_cache(tmp_path, url)

    validate_manifest(manifest, str(repo))
    run_assess(
        url,
        str(repo),
        openapi_cache_path=str(cache),
    )
    run_generate(str(manifest), str(tmp_path / "generated-app"), str(repo))

    assert captured == [11, 12, 13]


def test_build_timeout_uses_lifecycle_setting(monkeypatch, tmp_path):
    app_dir = tmp_path / "generated-app"
    target = app_dir / "target"
    target.mkdir(parents=True)
    (target / "demo.jar").write_text("", encoding="utf-8")
    captured: dict[str, int] = {}

    def fake_run(*args, **kwargs):
        captured["timeout"] = kwargs["timeout"]
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "built"
        proc.stderr = ""
        return proc

    monkeypatch.setenv("EDGEFORGE_STUDIO_BUILD_TIMEOUT_SECONDS", "14")
    monkeypatch.setattr("app.services.build_run_service.subprocess.run", fake_run)

    result = build_generated_app(str(app_dir))

    assert result.success is True
    assert captured["timeout"] == 14
