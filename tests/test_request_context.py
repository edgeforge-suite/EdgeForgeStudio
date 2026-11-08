from __future__ import annotations

import importlib
import re
import time

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.main import app
from app.services.csrf import CsrfValidationError, issue_csrf_token, validate_csrf_token
from app.services.identity import AnonymousSessionIdentity, Principal
from app.services.project_file_service import serialize_project, snapshot_session_for_save
from app.services.session_context import get_current_session, get_session_store
from app.services.settings import StudioSettingsError, get_studio_settings
from app.services.signed_tokens import sign_payload
from tests.session_helpers import get_session, reset_session


def _request_with_cookie(cookie_name: str, cookie_value: str | None = None) -> Request:
    headers = []
    if cookie_value:
        headers.append((b"cookie", f"{cookie_name}={cookie_value}".encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
        }
    )


def _csrf_from_html(html: str) -> str:
    match = re.search(
        r'<meta\s+name="edgeforge-csrf-token"\s+content="([^"]+)"',
        html,
    )
    assert match, "CSRF meta tag was not rendered"
    return match.group(1)


def _signed_session_cookie(session_id: str) -> str:
    settings = get_studio_settings()
    now = int(time.time())
    return sign_payload(
        {
            "sid": session_id,
            "iat": now,
            "exp": now + settings.session_max_age_seconds,
        },
        secret=settings.session_secret,
    )


def _clear_context_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [
        "EDGEFORGE_STUDIO_SHARED_MODE",
        "STUDIO_SHARED_MODE",
        "EDGEFORGE_STUDIO_AUTH_MODE",
        "STUDIO_AUTH_MODE",
        "EDGEFORGE_STUDIO_SESSION_SECRET",
        "EDGEFORGE_STUDIO_SESSION_COOKIE_NAME",
        "EDGEFORGE_STUDIO_SESSION_MAX_AGE_SECONDS",
        "EDGEFORGE_STUDIO_SESSION_ROTATION_SECONDS",
        "EDGEFORGE_STUDIO_BUILD_RUN_ENABLED",
        "EDGEFORGE_STUDIO_ENABLE_API_DOCS",
        "EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE",
    ]:
        monkeypatch.delenv(name, raising=False)


def _shared_client_with_token(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, str]:
    _clear_context_env(monkeypatch)
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    reset_session()
    client = TestClient(app, base_url="https://testserver")
    page = client.get("/")
    return client, _csrf_from_html(page.text)


def test_settings_default_to_local_anonymous(monkeypatch):
    _clear_context_env(monkeypatch)

    settings = get_studio_settings()

    assert settings.shared_mode is False
    assert settings.auth_mode == "anonymous"
    assert settings.build_run_enabled is True
    assert settings.openapi_fetch_mode == "open"
    assert settings.cookie_secure is False
    assert settings.csrf_enforced is False


def test_settings_read_shared_mode_and_auth_aliases(monkeypatch):
    _clear_context_env(monkeypatch)
    monkeypatch.setenv("STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("STUDIO_AUTH_MODE", "proxy")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")

    settings = get_studio_settings()

    assert settings.shared_mode is True
    assert settings.auth_mode == "proxy"
    assert settings.build_run_enabled is False
    assert settings.openapi_fetch_mode == "allowlist"
    assert settings.cookie_secure is True
    assert settings.csrf_enforced is True


def test_settings_read_shared_mode_p3_gate_flags(monkeypatch):
    _clear_context_env(monkeypatch)
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_BUILD_RUN_ENABLED", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE", "disabled")

    settings = get_studio_settings()

    assert settings.shared_mode is True
    assert settings.build_run_enabled is True
    assert settings.openapi_fetch_mode == "disabled"


def test_settings_invalid_openapi_fetch_mode_uses_mode_default(monkeypatch):
    _clear_context_env(monkeypatch)
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE", "nonsense")

    assert get_studio_settings().openapi_fetch_mode == "open"

    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    assert get_studio_settings().openapi_fetch_mode == "allowlist"


def test_shared_mode_requires_non_default_session_secret(monkeypatch):
    _clear_context_env(monkeypatch)
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")

    with pytest.raises(StudioSettingsError) as exc:
        get_studio_settings()

    assert "EDGEFORGE_STUDIO_SESSION_SECRET" in str(exc.value)


def test_proxy_auth_mode_is_stubbed_with_clear_response(monkeypatch):
    _clear_context_env(monkeypatch)
    monkeypatch.setenv("EDGEFORGE_STUDIO_AUTH_MODE", "proxy")
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 501
    assert response.json()["ok"] is False
    assert "deferred to a later phase" in response.json()["error"]


def test_anonymous_identity_issues_stable_signed_cookie(monkeypatch):
    _clear_context_env(monkeypatch)
    settings = get_studio_settings()
    provider = AnonymousSessionIdentity(settings)
    first_request = _request_with_cookie(settings.session_cookie_name)

    first_principal = provider.resolve(first_request)
    cookie_update = first_request.state.studio_session_cookie_update

    second_request = _request_with_cookie(
        settings.session_cookie_name,
        cookie_update.value,
    )
    second_principal = provider.resolve(second_request)

    assert first_principal.source == "anonymous"
    assert first_principal.user_id == second_principal.user_id
    assert first_principal.claims["anonymous_session_id"] == second_principal.claims["anonymous_session_id"]
    assert not hasattr(second_request.state, "studio_session_cookie_update")


def test_csrf_token_round_trips_for_principal(monkeypatch):
    _clear_context_env(monkeypatch)
    principal = Principal(
        user_id="anonymous:test-session",
        source="anonymous",
        claims={"anonymous_session_id": "test-session"},
    )

    token = issue_csrf_token(principal)

    assert validate_csrf_token(token, principal) is True
    with pytest.raises(CsrfValidationError):
        validate_csrf_token("not-a-valid-token", principal)


def test_first_request_sets_local_session_cookie_flags(monkeypatch):
    _clear_context_env(monkeypatch)
    reset_session()
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    cookie = response.headers.get("set-cookie", "")
    assert "edgeforge_studio_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Max-Age=" in cookie
    assert "Secure" not in cookie
    assert 'name="edgeforge-csrf-token"' in response.text


def test_shared_mode_cookie_uses_secure_flag(monkeypatch):
    _clear_context_env(monkeypatch)
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    reset_session()
    client = TestClient(app, base_url="https://testserver")

    response = client.get("/")

    assert response.status_code == 200
    cookie = response.headers.get("set-cookie", "")
    assert "edgeforge_studio_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" in cookie


def test_default_local_post_without_csrf_still_works(monkeypatch, tmp_path):
    _clear_context_env(monkeypatch)
    reset_session()
    client = TestClient(app)

    response = client.post(
        "/",
        data={
            "app_name": "Local App",
            "bounded_context": "Local",
            "app_archetype": "crud",
            "target_profile": "springboot-standard-enterprise",
            "output_path": str(tmp_path),
            "appbuilder_repo_path": str(tmp_path),
        },
        follow_redirects=False,
    )

    assert response.status_code != 403


def test_shared_mode_rejects_missing_and_forged_csrf(monkeypatch):
    _clear_context_env(monkeypatch)
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    reset_session()
    client = TestClient(app, base_url="https://testserver")
    client.get("/")

    missing = client.post("/", data={"app_name": "Blocked"}, follow_redirects=False)
    forged = client.post(
        "/",
        data={"app_name": "Blocked"},
        headers={"x-edgeforge-csrf-token": "forged"},
        follow_redirects=False,
    )

    assert missing.status_code == 403
    assert "CSRF" in missing.json()["detail"]
    assert forged.status_code == 403
    assert forged.json()["ok"] is False


def test_shared_mode_accepts_native_form_body_token(monkeypatch, tmp_path):
    client, token = _shared_client_with_token(monkeypatch)

    response = client.post(
        "/",
        data={
            "app_name": "Shared Form",
            "bounded_context": "Shared",
            "app_archetype": "crud",
            "target_profile": "springboot-standard-enterprise",
            "output_path": str(tmp_path),
            "appbuilder_repo_path": str(tmp_path),
            "_edgeforge_csrf_token": token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303


def test_shared_mode_native_form_routes_accept_valid_body_token(monkeypatch):
    client, token = _shared_client_with_token(monkeypatch)
    project_json = serialize_project(snapshot_session_for_save(get_session()))

    cases = [
        (
            "/project/save",
            {"data": {"_edgeforge_csrf_token": token}, "follow_redirects": False},
            {200},
        ),
        (
            "/project/open",
            {
                "data": {"_edgeforge_csrf_token": token},
                "files": {"project_file": ("project.json", project_json.encode("utf-8"), "application/json")},
                "follow_redirects": False,
            },
            {303},
        ),
        (
            "/knowledge/upload",
            {
                "data": {"_edgeforge_csrf_token": token, "description": "doc"},
                "files": {"document_file": ("notes.md", b"# Notes", "text/markdown")},
                "follow_redirects": False,
            },
            {303},
        ),
        (
            "/knowledge/delete",
            {
                "data": {
                    "_edgeforge_csrf_token": token,
                    "document_id": "doc-1",
                    "document_name": "notes.md",
                },
                "follow_redirects": False,
            },
            {303},
        ),
    ]

    for path, kwargs, expected_statuses in cases:
        response = client.post(path, **kwargs)
        assert response.status_code in expected_statuses, path


def test_shared_mode_native_form_routes_reject_missing_and_forged_body_tokens(monkeypatch):
    client, _token = _shared_client_with_token(monkeypatch)

    cases = [
        ("/", {"data": {"app_name": "Blocked"}, "follow_redirects": False}),
        ("/project/save", {"data": {}, "follow_redirects": False}),
        (
            "/project/open",
            {
                "data": {},
                "files": {"project_file": ("project.json", b"{}", "application/json")},
                "follow_redirects": False,
            },
        ),
        (
            "/knowledge/upload",
            {
                "data": {"description": "doc"},
                "files": {"document_file": ("notes.md", b"# Notes", "text/markdown")},
                "follow_redirects": False,
            },
        ),
        (
            "/knowledge/delete",
            {
                "data": {"document_id": "doc-1", "document_name": "notes.md"},
                "follow_redirects": False,
            },
        ),
        ("/regen/apply", {"data": {"approved_plan_hash": "hash"}, "follow_redirects": False}),
    ]

    for path, kwargs in cases:
        missing = client.post(path, **kwargs)
        assert missing.status_code == 403, path

        forged_kwargs = dict(kwargs)
        forged_data = dict(forged_kwargs.get("data") or {})
        forged_data["_edgeforge_csrf_token"] = "forged"
        forged_kwargs["data"] = forged_data
        forged = client.post(path, **forged_kwargs)
        assert forged.status_code == 403, path


def test_shared_mode_accepts_valid_csrf_header(monkeypatch, tmp_path):
    _clear_context_env(monkeypatch)
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    reset_session()
    client = TestClient(app, base_url="https://testserver")
    page = client.get("/")
    token = _csrf_from_html(page.text)

    response = client.post(
        "/",
        data={
            "app_name": "Shared App",
            "bounded_context": "Shared",
            "app_archetype": "crud",
            "target_profile": "springboot-standard-enterprise",
            "output_path": str(tmp_path),
            "appbuilder_repo_path": str(tmp_path),
        },
        headers={"x-edgeforge-csrf-token": token},
        follow_redirects=False,
    )

    assert response.status_code != 403


def test_global_session_store_backdoor_is_removed():
    legacy_module = importlib.import_module("app.services.session_store")

    for accessor_name in ("get_session", "save_session", "reset_session"):
        with pytest.raises(RuntimeError, match="Global Studio session access has been removed"):
            getattr(legacy_module, accessor_name)


def test_sqlite_session_store_backs_request_sessions(monkeypatch):
    _clear_context_env(monkeypatch)
    principal = Principal(user_id="anonymous:one", source="anonymous")
    store = get_session_store()

    loaded = store.get_or_create(principal)
    loaded.app_name = "Stored App"
    store.save(loaded)

    assert store.load(loaded.session_id or "").app_name == "Stored App"
    assert store.get_or_create(principal).app_name == "Stored App"


def test_get_current_session_uses_request_context_store(monkeypatch):
    _clear_context_env(monkeypatch)
    request = _request_with_cookie(get_studio_settings().session_cookie_name)
    request.state.principal = Principal(user_id="anonymous:request", source="anonymous")
    request.state.session_store = get_session_store()

    session = get_current_session(request)

    assert session is get_current_session(request)
    assert request.state.studio_session is session


def test_two_browser_cookies_get_isolated_project_sessions(monkeypatch, tmp_path):
    _clear_context_env(monkeypatch)
    settings = get_studio_settings()
    client_a = TestClient(app)
    client_b = TestClient(app)
    client_a.cookies.set(settings.session_cookie_name, _signed_session_cookie("browser-a"))
    client_b.cookies.set(settings.session_cookie_name, _signed_session_cookie("browser-b"))

    for client, name in ((client_a, "Browser A App"), (client_b, "Browser B App")):
        response = client.post(
            "/",
            data={
                "app_name": name,
                "bounded_context": "Isolation",
                "app_archetype": "crud",
                "target_profile": "springboot-standard-enterprise",
                "output_path": str(tmp_path / name.replace(" ", "-")),
                "appbuilder_repo_path": str(tmp_path),
            },
            follow_redirects=False,
        )
        assert response.status_code in {303, 307}

    store = get_session_store()
    session_a = store.get_or_create(Principal(user_id="anonymous:browser-a", source="anonymous"))
    session_b = store.get_or_create(Principal(user_id="anonymous:browser-b", source="anonymous"))

    assert session_a.app_name == "Browser A App"
    assert session_b.app_name == "Browser B App"
    assert session_a.session_id != session_b.session_id
    assert session_a.workspace_root != session_b.workspace_root
