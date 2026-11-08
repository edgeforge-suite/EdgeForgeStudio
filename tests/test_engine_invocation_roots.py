from __future__ import annotations

import ipaddress
import os
from pathlib import Path

from fastapi.testclient import TestClient

import app.integrations.appbuilder_integration as engine_integration
from app.integrations.appbuilder_integration import (
    SubprocessResult,
    _engine_subprocess_env,
    _mcp_env,
    run_assess,
    run_generate,
    validate_manifest,
)
from app.main import app
from app.services.openapi_fetch_guard import OpenAPIFetchResponse
from app.services.session_context import _SQLITE_STORES
from app.services.settings import get_studio_settings
from tests.openapi_cache_helpers import write_openapi_cache
from tests.session_helpers import reset_session, save_session
from tests.smoke._shared import csrf_from_html, session_for_client
from tests.test_package_writer import _full_session


def _fake_result(stdout: str = "VALID\n") -> SubprocessResult:
    return SubprocessResult(
        success=True,
        returncode=0,
        stdout=stdout,
        stderr="",
        combined_output=stdout.strip(),
        duration_seconds=0.0,
        command=["stubbed"],
        cwd=None,
    )


def _configure_shared(monkeypatch, tmp_path: Path) -> Path:
    repo = tmp_path / "engine"
    repo.mkdir(parents=True)
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "f1-shared-mode-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_STATE_DIR", str(tmp_path / "studio-state"))
    monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_REPO", str(repo))
    monkeypatch.delenv("EDGEFORGE_STUDIO_ENGINE_TRANSPORT", raising=False)
    _SQLITE_STORES.clear()
    return repo


def _env_roots(env: dict[str, str]) -> list[str]:
    raw = env.get("EDGEFORGE_MCP_ALLOWED_ROOTS", "")
    return [part for part in raw.split(os.pathsep) if part]


def test_shared_validate_sets_engine_roots_and_shared_mode(monkeypatch, tmp_path):
    repo = _configure_shared(monkeypatch, tmp_path)
    manifest = tmp_path / "package" / "app-definition.yaml"
    manifest.parent.mkdir()
    manifest.write_text("app: demo\n", encoding="utf-8")
    captured: dict[str, dict[str, str]] = {}

    def fake_run_subprocess(_cmd, **kwargs):
        captured["env"] = kwargs["env"]
        return _fake_result()

    monkeypatch.setattr(engine_integration, "_run_subprocess", fake_run_subprocess)

    result = validate_manifest(manifest, str(repo))

    assert result.success is True
    assert captured["env"]["EDGEFORGE_SHARED_MODE"] == "1"
    assert _env_roots(captured["env"]) == [str(manifest.parent.resolve())]
    assert str(repo.resolve()) not in _env_roots(captured["env"])


def test_shared_assess_sets_session_workspace_roots_and_shared_mode(monkeypatch, tmp_path):
    repo = _configure_shared(monkeypatch, tmp_path)
    workspace_root = tmp_path / "studio-state" / "workspaces" / "browser-a"
    workspace_root.mkdir(parents=True)
    monkeypatch.setenv(
        "EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS",
        " B.example.,a.example,A.EXAMPLE ",
    )
    monkeypatch.setenv(
        "EDGEFORGE_OPENAPI_FETCH_ALLOWED_HOSTS",
        "ambient.example",
    )
    captured: dict[str, dict[str, str]] = {}

    def fake_run_subprocess(_cmd, **kwargs):
        captured["env"] = kwargs["env"]
        return _fake_result("assessed\n")

    monkeypatch.setattr(engine_integration, "_run_subprocess", fake_run_subprocess)
    url = "https://api.example.test/openapi.json"
    cache = write_openapi_cache(workspace_root, url)

    result = run_assess(
        url,
        str(repo),
        allowed_roots=[str(workspace_root)],
        openapi_cache_path=str(cache),
    )

    assert result.success is True
    assert captured["env"]["EDGEFORGE_SHARED_MODE"] == "1"
    assert captured["env"]["EDGEFORGE_OPENAPI_FETCH_ALLOWED_HOSTS"] == (
        "a.example,b.example"
    )
    assert _env_roots(captured["env"]) == [str(workspace_root.resolve())]
    assert str(repo.resolve()) not in _env_roots(captured["env"])


def test_shared_generate_mcp_env_sets_roots_and_disables_cli_fallback(monkeypatch, tmp_path):
    repo = _configure_shared(monkeypatch, tmp_path)
    manifest = tmp_path / "workspace" / "export" / "app-definition.yaml"
    output_dir = tmp_path / "workspace" / "export" / "generated-app"
    manifest.parent.mkdir(parents=True)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(
        "EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS",
        "internal.example",
    )
    monkeypatch.setenv(
        "EDGEFORGE_OPENAPI_FETCH_ALLOWED_HOSTS",
        "ambient.example",
    )
    cli_calls: list[object] = []

    env = _mcp_env(str(manifest), str(output_dir), repo)
    assert env["EDGEFORGE_SHARED_MODE"] == "1"
    assert env["EDGEFORGE_OPENAPI_FETCH_ALLOWED_HOSTS"] == "internal.example"
    assert _env_roots(env) == [str(manifest.parent.resolve())]
    assert str(repo.resolve()) not in _env_roots(env)

    def unavailable_mcp(_manifest_path: str, _output_dir: str, _repo: Path):
        return SubprocessResult(
            success=False,
            returncode=-1,
            stdout="",
            stderr="Engine MCP unavailable",
            combined_output="Engine MCP unavailable",
            duration_seconds=0.0,
            command=["mcp", "edgeforge-engine", "generate_app"],
            cwd=str(repo),
        )

    def fail_cli(*args, **kwargs):
        cli_calls.append((args, kwargs))
        raise AssertionError("shared-mode generate must not use CLI fallback")

    monkeypatch.setattr(engine_integration, "_run_generate_mcp", unavailable_mcp)
    monkeypatch.setattr(engine_integration, "_run_subprocess", fail_cli)

    result = run_generate(str(manifest), str(output_dir), str(repo))

    assert result.success is False
    assert "subprocess fallback is disabled" in result.combined_output
    assert cli_calls == []


def test_local_engine_invocations_do_not_add_shared_root_env(monkeypatch, tmp_path):
    repo = tmp_path / "engine"
    repo.mkdir()
    manifest = tmp_path / "package" / "app-definition.yaml"
    manifest.parent.mkdir()
    manifest.write_text("app: demo\n", encoding="utf-8")
    captured_envs: list[dict[str, str]] = []

    def fake_run_subprocess(_cmd, **kwargs):
        captured_envs.append(kwargs["env"])
        return _fake_result()

    monkeypatch.delenv("EDGEFORGE_STUDIO_SHARED_MODE", raising=False)
    monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_TRANSPORT", "subprocess")
    monkeypatch.setenv("EDGEFORGE_SHARED_MODE", "1")
    monkeypatch.setenv("EDGEFORGE_MCP_ALLOWED_ROOTS", str(tmp_path / "external-root"))
    monkeypatch.setenv(
        "EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS",
        "public.example",
    )
    monkeypatch.setenv(
        "EDGEFORGE_OPENAPI_FETCH_ALLOWED_HOSTS",
        "ambient.example",
    )
    monkeypatch.setattr(engine_integration, "_run_subprocess", fake_run_subprocess)
    url = "http://localhost/openapi.json"
    cache = write_openapi_cache(tmp_path, url)

    validate_manifest(manifest, str(repo))
    run_assess(
        url,
        str(repo),
        openapi_cache_path=str(cache),
    )
    run_generate(str(manifest), str(tmp_path / "generated-app"), str(repo))

    assert len(captured_envs) == 3
    for env in captured_envs:
        assert "EDGEFORGE_SHARED_MODE" not in env
        assert "EDGEFORGE_MCP_ALLOWED_ROOTS" not in env
        assert env["EDGEFORGE_OPENAPI_FETCH_ALLOWED_HOSTS"] == "public.example"


def test_shared_allowed_roots_are_per_session_and_exclude_repo(monkeypatch, tmp_path):
    repo = _configure_shared(monkeypatch, tmp_path)
    workspace_a = tmp_path / "studio-state" / "workspaces" / "browser-a"
    workspace_b = tmp_path / "studio-state" / "workspaces" / "browser-b"

    env_a = _engine_subprocess_env(repo, allowed_roots=[str(workspace_a)], settings=get_studio_settings())
    env_b = _engine_subprocess_env(repo, allowed_roots=[str(workspace_b)], settings=get_studio_settings())

    assert _env_roots(env_a) == [str(workspace_a.resolve())]
    assert _env_roots(env_b) == [str(workspace_b.resolve())]
    assert _env_roots(env_a) != _env_roots(env_b)
    assert str(repo.resolve()) not in _env_roots(env_a)
    assert str(repo.resolve()) not in _env_roots(env_b)


def test_export_routes_pass_per_session_roots_to_engine_invocations(monkeypatch, tmp_path):
    repo = _configure_shared(monkeypatch, tmp_path)
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS", "example.com")
    monkeypatch.setattr(
        "app.services.openapi_fetch_guard._resolved_addresses",
        lambda host, port, **_kwargs: {ipaddress.ip_address("93.184.216.34")},
    )
    monkeypatch.setattr(
        "app.routes.export.fetch_url_with_policy",
        lambda url, settings: OpenAPIFetchResponse(
            text='{"openapi":"3.1.0","info":{"title":"Test","version":"1"},"paths":{}}',
            status_code=200,
        ),
    )
    reset_session()
    seeded = _full_session()
    seeded.appbuilder_repo_path = str(tmp_path / "user-engine")
    save_session(seeded)
    client = TestClient(app, base_url="https://testserver")
    page = client.get("/")
    headers = {"x-edgeforge-csrf-token": csrf_from_html(page.text)}
    write_response = client.post("/export/write", headers=headers)
    assert write_response.status_code == 200
    manifest_parent = Path(write_response.json()["output_dir"])
    workspace_root = Path(session_for_client(client).workspace_root or "")
    captured: dict[str, list[str] | str] = {}

    def fake_validate(manifest_path: Path, repo_path: str, *, allowed_roots: list[str] | None = None):
        captured["validate_repo"] = repo_path
        captured["validate_roots"] = list(allowed_roots or [])
        assert manifest_path == manifest_parent / "app-definition.yaml"
        return _fake_result()

    def fake_assess(
        spec_url: str,
        repo_path: str,
        output_path=None,
        *,
        allowed_roots: list[str] | None = None,
        openapi_cache_path: str | None = None,
    ):
        captured["assess_repo"] = repo_path
        captured["assess_roots"] = list(allowed_roots or [])
        assert output_path is None
        assert openapi_cache_path is not None
        assert Path(openapi_cache_path).is_file()
        assert Path(openapi_cache_path).is_relative_to(workspace_root)
        return _fake_result("assessed\n")

    monkeypatch.setattr("app.routes.export.validate_manifest", fake_validate)
    monkeypatch.setattr("app.routes.export.run_assess", fake_assess)

    validate_response = client.post("/export/validate", headers=headers)
    assess_response = client.post("/export/assess", headers=headers)

    assert validate_response.status_code == 200
    assert assess_response.status_code == 200
    assert captured["validate_repo"] == str(repo)
    assert captured["assess_repo"] == str(repo)
    assert captured["validate_roots"] == [str(manifest_parent)]
    assert captured["assess_roots"] == [str(workspace_root)]
