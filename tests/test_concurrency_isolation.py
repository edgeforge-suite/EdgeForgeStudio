from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.integrations.appbuilder_integration import SubprocessResult
from app.integrations.ks_integration import KSUnavailableError
from app.main import app
from app.services.generation_locks import acquire_generation_lock
from app.services.identity import IdentityProviderUnavailable, get_identity_provider
from app.services.ks_lifecycle import ks_client, set_ks_client_factory_for_testing
from app.services.session_context import _SQLITE_STORES
from app.services.settings import get_studio_settings
from tests.smoke._shared import (
    csrf_headers,
    make_exportable_smoke_session,
    new_shared_client,
    post_step1,
    save_session_for_client,
    session_for_client,
)


@pytest.fixture(autouse=True)
def _fail_real_ks_start(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    def fail_start(*_args, **_kwargs):
        calls.append("KSClient.start")
        raise AssertionError("P7 Studio-local concurrency tests must not start real KS")

    monkeypatch.setattr("app.integrations.ks_integration.KSClient.start", fail_start)
    yield
    assert calls == []


@dataclass(frozen=True)
class PreparedGenerateSession:
    client: TestClient
    csrf_token: str
    session_cookie: str
    export_dir: Path
    output_dir: Path
    workspace_root: Path


def _configure_shared_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    browser_tokens: Iterable[str] = ("browser-a",),
) -> None:
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "p7-shared-mode-test-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_STATE_DIR", str(tmp_path / "studio-state"))
    monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_REPO", str(tmp_path / "operator-engine"))
    monkeypatch.delenv("EDGEFORGE_STUDIO_BUILD_RUN_ENABLED", raising=False)
    monkeypatch.delenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS", raising=False)
    (tmp_path / "operator-engine").mkdir(parents=True, exist_ok=True)
    token_values = iter(browser_tokens)
    fallback = "browser-fallback"

    def next_token(_n: int = 24) -> str:
        nonlocal fallback
        try:
            fallback = next(token_values)
        except StopIteration:
            pass
        return fallback

    monkeypatch.setattr("app.services.identity.secrets.token_urlsafe", next_token)
    _SQLITE_STORES.clear()


def _prepare_exported_session(
    *,
    tmp_path: Path,
    app_name: str = "Alpha P7 App",
    bounded_context: str = "alpha-p7",
    entity_name: str = "Alpha",
    contract_name: str = "alpha",
) -> PreparedGenerateSession:
    client, csrf_token = new_shared_client()
    post_step1(
        client,
        csrf_token,
        app_name=app_name,
        bounded_context=bounded_context,
        output_path=tmp_path / "user-supplied-output",
    )
    session = session_for_client(client)
    make_exportable_smoke_session(
        session,
        entity_name=entity_name,
        contract_name=contract_name,
    )
    save_session_for_client(client, session)

    response = client.post("/export/write", headers=csrf_headers(csrf_token))
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True

    settings = get_studio_settings()
    cookie = client.cookies.get(settings.session_cookie_name)
    assert cookie
    export_dir = Path(payload["output_dir"])
    return PreparedGenerateSession(
        client=client,
        csrf_token=csrf_token,
        session_cookie=cookie,
        export_dir=export_dir,
        output_dir=export_dir / "generated-app",
        workspace_root=Path(session.workspace_root or ""),
    )


def _client_for_cookie(cookie: str) -> TestClient:
    settings = get_studio_settings()
    client = TestClient(app, base_url="https://testserver")
    client.cookies.set(settings.session_cookie_name, cookie)
    return client


def _successful_generate_result(message: str = "generated") -> SubprocessResult:
    return SubprocessResult(
        success=True,
        returncode=0,
        stdout=message,
        stderr="",
        combined_output=message,
        duration_seconds=0.01,
        command=["stubbed-generate"],
        cwd=None,
    )


def _post_generate(cookie: str, csrf_token: str) -> tuple[int, dict]:
    client = _client_for_cookie(cookie)
    response = client.post("/export/generate", headers=csrf_headers(csrf_token))
    return response.status_code, response.json()


def test_generate_returns_already_in_progress_when_output_locked(monkeypatch, tmp_path):
    _configure_shared_mode(monkeypatch, tmp_path)
    prepared = _prepare_exported_session(tmp_path=tmp_path)
    calls: list[tuple] = []

    def fail_generate(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("run_generate should not be called while output path is locked")

    monkeypatch.setattr("app.routes.export.run_generate", fail_generate)

    with acquire_generation_lock(prepared.output_dir) as acquired:
        assert acquired is True
        response = prepared.client.post(
            "/export/generate",
            headers=csrf_headers(prepared.csrf_token),
        )

    assert response.status_code == 409
    payload = response.json()
    assert payload["ok"] is False
    assert payload["output_dir"] == str(prepared.output_dir)
    assert "already in progress" in payload["error"]
    assert calls == []


def test_concurrent_same_path_generate_is_rejected_before_generation_lock(monkeypatch, tmp_path):
    _configure_shared_mode(monkeypatch, tmp_path)
    prepared = _prepare_exported_session(tmp_path=tmp_path)
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []
    call_lock = threading.Lock()

    def blocking_generate(
        _manifest_path: str,
        output_dir: str,
        _repo_path: str,
        **_kwargs,
    ):
        with call_lock:
            calls.append(output_dir)
        entered.set()
        assert release.wait(timeout=5), "generate stub was not released"
        return _successful_generate_result("generated once")

    monkeypatch.setattr("app.routes.export.run_generate", blocking_generate)
    first_result: dict[str, object] = {}
    second_result: dict[str, object] = {}

    def first_request() -> None:
        status, payload = _post_generate(prepared.session_cookie, prepared.csrf_token)
        first_result.update({"status": status, "payload": payload})

    def second_request() -> None:
        status, payload = _post_generate(prepared.session_cookie, prepared.csrf_token)
        second_result.update({"status": status, "payload": payload})

    first = threading.Thread(target=first_request)
    first.start()
    assert entered.wait(timeout=5), "first generate request never entered run_generate"

    second = threading.Thread(target=second_request)
    second.start()
    second.join(timeout=5)
    assert not second.is_alive()
    release.set()
    first.join(timeout=5)
    assert not first.is_alive()

    assert len(calls) == 1
    assert calls == [str(prepared.output_dir)]
    assert first_result["status"] == 200
    assert first_result["payload"]["ok"] is True
    assert second_result["status"] == 429
    assert second_result["payload"]["ok"] is False
    assert second_result["payload"] == {
        "ok": False,
        "error": "Request limit reached. Please retry later.",
        "retry_after": 5,
    }


def test_concurrent_distinct_session_generate_both_proceed(monkeypatch, tmp_path):
    _configure_shared_mode(monkeypatch, tmp_path, browser_tokens=("browser-a", "browser-b"))
    prepared_a = _prepare_exported_session(
        tmp_path=tmp_path,
        app_name="Alpha P7 App",
        bounded_context="alpha-p7",
        entity_name="Alpha",
        contract_name="alpha",
    )
    prepared_b = _prepare_exported_session(
        tmp_path=tmp_path,
        app_name="Beta P7 App",
        bounded_context="beta-p7",
        entity_name="Beta",
        contract_name="beta",
    )
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []
    call_lock = threading.Lock()

    def blocking_generate(
        _manifest_path: str,
        output_dir: str,
        _repo_path: str,
        **_kwargs,
    ):
        with call_lock:
            calls.append(output_dir)
            if len(calls) == 2:
                entered.set()
        assert release.wait(timeout=5), "distinct generate stubs were not released"
        return _successful_generate_result(f"generated {Path(output_dir).parent.name}")

    monkeypatch.setattr("app.routes.export.run_generate", blocking_generate)
    result_a: dict[str, object] = {}
    result_b: dict[str, object] = {}

    def post_for(prepared: PreparedGenerateSession, target: dict[str, object]) -> None:
        status, payload = _post_generate(prepared.session_cookie, prepared.csrf_token)
        target.update({"status": status, "payload": payload})

    thread_a = threading.Thread(target=post_for, args=(prepared_a, result_a))
    thread_b = threading.Thread(target=post_for, args=(prepared_b, result_b))
    thread_a.start()
    thread_b.start()
    assert entered.wait(timeout=5), "both distinct generate requests did not enter"
    release.set()
    thread_a.join(timeout=5)
    thread_b.join(timeout=5)
    assert not thread_a.is_alive()
    assert not thread_b.is_alive()

    assert sorted(calls) == sorted([str(prepared_a.output_dir), str(prepared_b.output_dir)])
    assert prepared_a.output_dir != prepared_b.output_dir
    assert prepared_a.output_dir.is_relative_to(prepared_a.workspace_root)
    assert prepared_b.output_dir.is_relative_to(prepared_b.workspace_root)
    assert result_a["status"] == 200
    assert result_a["payload"]["ok"] is True
    assert result_b["status"] == 200
    assert result_b["payload"]["ok"] is True


def test_csrf_token_from_other_session_is_rejected(monkeypatch, tmp_path):
    _configure_shared_mode(monkeypatch, tmp_path, browser_tokens=("browser-a", "browser-b"))
    _client_a, csrf_a = new_shared_client()
    client_b, _csrf_b = new_shared_client()

    response = client_b.post(
        "/upstream/ingest-url",
        headers=csrf_headers(csrf_a),
        data={"spec_url": "https://api.example.test/openapi.yaml"},
    )

    assert response.status_code == 403
    payload = response.json()
    assert payload["ok"] is False
    assert "does not match the current session" in payload["error"]


def test_parallel_two_session_catalog_no_bleed(monkeypatch, tmp_path):
    _configure_shared_mode(monkeypatch, tmp_path, browser_tokens=("browser-a", "browser-b"))
    client_a, csrf_a = new_shared_client()
    client_b, csrf_b = new_shared_client()
    errors: list[BaseException] = []

    def post_project(
        client: TestClient,
        csrf_token: str,
        *,
        app_name: str,
        bounded_context: str,
    ) -> None:
        try:
            post_step1(
                client,
                csrf_token,
                app_name=app_name,
                bounded_context=bounded_context,
                output_path=tmp_path / f"{bounded_context}-ignored-output",
            )
        except BaseException as exc:  # pragma: no cover - assertion aid
            errors.append(exc)

    thread_a = threading.Thread(
        target=post_project,
        args=(client_a, csrf_a),
        kwargs={"app_name": "Alpha Parallel App", "bounded_context": "alpha-parallel"},
    )
    thread_b = threading.Thread(
        target=post_project,
        args=(client_b, csrf_b),
        kwargs={"app_name": "Beta Parallel App", "bounded_context": "beta-parallel"},
    )
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=5)
    thread_b.join(timeout=5)

    assert not thread_a.is_alive()
    assert not thread_b.is_alive()
    assert errors == []
    session_a = session_for_client(client_a)
    session_b = session_for_client(client_b)
    assert session_a.app_name == "Alpha Parallel App"
    assert session_a.bounded_context == "alpha-parallel"
    assert session_b.app_name == "Beta Parallel App"
    assert session_b.bounded_context == "beta-parallel"
    assert session_a.session_id != session_b.session_id
    assert session_a.workspace_root != session_b.workspace_root
    page_a = client_a.get("/")
    page_b = client_b.get("/")
    assert "Alpha Parallel App" in page_a.text
    assert "Beta Parallel App" not in page_a.text
    assert "Beta Parallel App" in page_b.text
    assert "Alpha Parallel App" not in page_b.text


def test_parallel_same_workspace_ks_in_use_rejected(tmp_path):
    class FakeKSClient:
        def __init__(self, _allowed_roots: list[str], _db_path: str | None) -> None:
            self.started = False

        def start(self) -> None:
            self.started = True

        def stop(self) -> None:
            self.started = False

        def is_ready(self) -> bool:
            return self.started

    set_ks_client_factory_for_testing(FakeKSClient)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    allowed_roots = [str(workspace)]
    db_path = str(workspace / "ks" / "knowledge.sqlite3")
    entered = threading.Event()
    release = threading.Event()

    def hold_client() -> None:
        with ks_client(allowed_roots=allowed_roots, db_path=db_path):
            entered.set()
            assert release.wait(timeout=5), "KS fake client hold was not released"

    thread = threading.Thread(target=hold_client)
    thread.start()
    assert entered.wait(timeout=5), "first KS fake client did not enter"
    with pytest.raises(KSUnavailableError, match="already in use"):
        with ks_client(allowed_roots=allowed_roots, db_path=db_path):
            pass
    release.set()
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_proxy_auth_mode_raises_deferred_adapter(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_AUTH_MODE", "proxy")
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})

    with pytest.raises(IdentityProviderUnavailable, match="deferred to a later phase"):
        get_identity_provider().resolve(request)
