from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.middleware.browser_security import BROWSER_SECURITY_HEADERS
from tests.session_helpers import reset_session, save_session
from tests.test_package_writer import _full_session

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)


def _assert_security_headers(response) -> None:
    for name, value in BROWSER_SECURITY_HEADERS.items():
        assert response.headers[name] == value
    csp = response.headers["content-security-policy"]
    assert "script-src" not in csp
    assert "style-src" not in csp
    assert "default-src" not in csp


def _run_app_probe(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    script = (
        "from fastapi.testclient import TestClient\n"
        "from app.main import app\n"
        "client = TestClient(app)\n"
        "print(client.get('/docs').status_code)\n"
        "print(client.get('/redoc').status_code)\n"
        "print(client.get('/openapi.json').status_code)\n"
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_api_documentation_surfaces_are_disabled_by_default():
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_local_explicit_opt_in_enables_all_api_documentation_surfaces():
    env = os.environ.copy()
    env.pop("EDGEFORGE_STUDIO_SHARED_MODE", None)
    env.pop("STUDIO_SHARED_MODE", None)
    env["EDGEFORGE_STUDIO_ENABLE_API_DOCS"] = "true"

    completed = _run_app_probe(env)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.splitlines() == ["200", "200", "200"]


def test_shared_mode_api_documentation_opt_in_refuses_startup():
    env = os.environ.copy()
    env["EDGEFORGE_STUDIO_SHARED_MODE"] = "true"
    env["EDGEFORGE_STUDIO_SESSION_SECRET"] = "test-shared-secret"
    env["EDGEFORGE_STUDIO_ENABLE_API_DOCS"] = "true"

    completed = _run_app_probe(env)

    assert completed.returncode != 0
    assert "EDGEFORGE_STUDIO_ENABLE_API_DOCS cannot be enabled" in completed.stderr


def test_security_headers_cover_html_json_static_redirect_and_4xx():
    reset_session()
    responses = [
        client.get("/"),
        client.post("/api/validate/staging-ddl", json={"ddl": ""}),
        client.get("/static/css/studio.css"),
        client.post(
            "/",
            data={"app_name": "Header proof", "bounded_context": "header-proof"},
            follow_redirects=False,
        ),
        client.get("/route-that-does-not-exist"),
    ]

    assert [response.status_code for response in responses] == [200, 200, 200, 303, 404]
    for response in responses:
        _assert_security_headers(response)
    reset_session()


def test_security_headers_cover_caught_5xx_response(tmp_path, monkeypatch):
    reset_session()
    session = _full_session()
    session.output_path = str(tmp_path)
    save_session(session)
    monkeypatch.setattr(
        "app.routes.export.write_package_result",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("synthetic failure")),
    )

    response = client.post("/export/write")

    assert response.status_code == 500
    _assert_security_headers(response)
    reset_session()


def test_security_headers_cover_unhandled_5xx_response():
    async def fail_unhandled():
        raise RuntimeError("synthetic unhandled failure")

    app.add_api_route(
        "/__tests/browser-security-unhandled",
        fail_unhandled,
        methods=["GET"],
    )
    response = TestClient(app, raise_server_exceptions=False).get(
        "/__tests/browser-security-unhandled"
    )

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert "synthetic unhandled failure" not in response.text
    _assert_security_headers(response)
