"""Tests for Step 8 Build & Run UI and routes."""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models.project import BuildRunRoute, BuildRunState
from app.services.build_run_service import BuildResult, StartResult, build_run_disabled_message
from app.services.build_run_service import build_generated_app as service_build_generated_app
from app.services.build_run_service import start_generated_app as service_start_generated_app
from tests.session_helpers import get_session, reset_session, save_session
from tests.test_package_writer import _full_session

client = TestClient(app)


def _csrf_from_html(html: str) -> str:
    match = re.search(
        r'<meta\s+name="edgeforge-csrf-token"\s+content="([^"]+)"',
        html,
    )
    assert match, "CSRF meta tag was not rendered"
    return match.group(1)


def _shared_client() -> tuple[TestClient, dict[str, str]]:
    shared_client = TestClient(app, base_url="https://testserver")
    page = shared_client.get("/")
    assert page.status_code == 200
    return shared_client, {"x-edgeforge-csrf-token": _csrf_from_html(page.text)}


def _seed_exported_session(tmp_path, with_generated_app: bool = False) -> Path:
    reset_session()
    session = _full_session()
    session.output_path = str(tmp_path)
    save_session(session)
    write_resp = client.post("/export/write")
    assert write_resp.status_code == 200
    export_dir = Path(write_resp.json()["output_dir"])
    if with_generated_app:
        (export_dir / "generated-app").mkdir(parents=True, exist_ok=True)
    return export_dir


def _seed_generated_app_session(tmp_path) -> Path:
    reset_session()
    session = _full_session()
    generated_app = tmp_path / "generated-app"
    generated_app.mkdir(parents=True)
    session.build_run.generated_app_path = str(generated_app)
    save_session(session)
    return generated_app


def test_step8_hides_build_run_panel_before_generate(tmp_path):
    _seed_exported_session(tmp_path, with_generated_app=False)
    response = client.get("/export")
    assert response.status_code == 200
    assert 'id="build-run-panel" class="hidden"' in response.text
    assert "Local app base URL" in response.text
    assert "8a" in response.text
    assert "Manifest Package" in response.text
    assert "8b" in response.text
    assert "Engine Actions" in response.text
    reset_session()


def test_step8_shows_build_run_panel_when_generated_app_exists(tmp_path):
    export_dir = _seed_exported_session(tmp_path, with_generated_app=True)
    response = client.get("/export")
    assert response.status_code == 200
    # build-run-panel is now inside section 8b (no longer a separate 8c section)
    assert 'id="build-run-panel"' in response.text
    assert "hidden" not in response.text.split('id="build-run-panel"')[1].split('>')[0]
    assert "Local app base URL" in response.text
    assert str(export_dir / "generated-app") in response.text
    reset_session()


def test_export_build_updates_session_state(tmp_path, monkeypatch):
    export_dir = _seed_exported_session(tmp_path, with_generated_app=True)
    generated_app = export_dir / "generated-app"

    def fake_build(path: str):
        assert path == str(generated_app)
        return BuildResult(
            success=True,
            output="BUILD OK",
            command=["mvn", "clean", "package", "-DskipTests"],
            log_path="/tmp/build.log",
            summary="Build succeeded.",
            jar_path=str(generated_app / "target" / "demo.jar"),
            route_summary=[BuildRunRoute(method="GET", path="/api/v1/customers", controller="CustomerController")],
        )

    monkeypatch.setattr("app.routes.export.build_generated_app", fake_build)

    response = client.post("/export/build")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["build_status"] == "build_succeeded"
    assert data["jar_path"].endswith("demo.jar")
    assert data["route_summary"][0]["path"] == "/api/v1/customers"

    session = get_session()
    assert session.build_run.build_status == "build_succeeded"
    assert session.build_run.jar_path and session.build_run.jar_path.endswith("demo.jar")
    reset_session()


def test_local_mode_export_build_disabled_by_operator_reports_the_right_reason(
    monkeypatch, tmp_path
):
    """Route-level regression (PR #279 review, P2).

    Honoring EDGEFORGE_STUDIO_BUILD_RUN_ENABLED=false in local mode must not
    surface a message blaming "shared-mode policy" for something shared mode
    had nothing to do with -- the pure settings assertion in
    test_studio_settings.py proves the flag itself is read correctly, but
    can't see what the route actually tells the caller.
    """
    monkeypatch.setenv("EDGEFORGE_STUDIO_BUILD_RUN_ENABLED", "false")
    _seed_generated_app_session(tmp_path)

    def fail_build(*args, **kwargs):
        raise AssertionError("build helper should not be called when Build & Run is disabled")

    monkeypatch.setattr("app.routes.export.build_generated_app", fail_build)

    response = client.post("/export/build")

    assert response.status_code == 403
    body = response.json()
    assert body["ok"] is False
    assert "shared-mode" not in body["error"].lower(), (
        f"a local-mode operator disable reported a shared-mode reason: {body['error']!r}"
    )
    assert body["error"] == build_run_disabled_message(False)
    reset_session()


def test_shared_mode_export_build_is_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    _seed_generated_app_session(tmp_path)
    shared_client, headers = _shared_client()

    def fail_build(*args, **kwargs):
        raise AssertionError("build helper should not be called when Build & Run is disabled")

    monkeypatch.setattr("app.routes.export.build_generated_app", fail_build)

    response = shared_client.post("/export/build", headers=headers)

    assert response.status_code == 403
    assert response.json()["ok"] is False
    assert response.json()["error"] == build_run_disabled_message(True)
    assert get_session().build_run.build_status == "idle"
    reset_session()


def test_shared_mode_export_build_can_be_enabled_by_operator(monkeypatch, tmp_path):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_BUILD_RUN_ENABLED", "true")
    generated_app = _seed_generated_app_session(tmp_path)
    shared_client, headers = _shared_client()

    def fake_build(path: str):
        assert path == str(generated_app)
        return BuildResult(
            success=True,
            output="BUILD OK",
            command=["mvn", "clean", "package", "-DskipTests"],
            log_path="/tmp/build.log",
            summary="Build succeeded.",
            jar_path=str(generated_app / "target" / "demo.jar"),
            route_summary=[],
        )

    monkeypatch.setattr("app.routes.export.build_generated_app", fake_build)

    response = shared_client.post("/export/build", headers=headers)

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert get_session().build_run.build_status == "build_succeeded"
    reset_session()


def test_export_run_returns_runtime_metadata(tmp_path, monkeypatch):
    export_dir = _seed_exported_session(tmp_path, with_generated_app=True)
    session = get_session()
    session.build_run.generated_app_path = str(export_dir / "generated-app")
    session.build_run.build_status = "build_succeeded"
    session.build_run.jar_path = str(export_dir / "generated-app" / "target" / "demo.jar")
    save_session(session)

    def fake_start(state):
        state.run_status = "starting"
        state.run_summary = "Application is starting."
        state.pid = 43210
        state.port = 18088
        state.app_url = "http://127.0.0.1:18088"
        state.health_url = "http://127.0.0.1:18088/actuator/health"
        return StartResult(success=True, summary=state.run_summary, state=state)

    def fake_status(state):
        return {
            "generated_app_path": state.generated_app_path,
            "build_status": state.build_status,
            "build_summary": state.build_summary,
            "build_log_path": state.build_log_path,
            "run_status": state.run_status,
            "run_summary": state.run_summary,
            "run_log_path": "/tmp/run.log",
            "app_url": state.app_url,
            "health_url": state.health_url,
            "health_ok": False,
            "health_body": "",
            "port": state.port,
            "pid": state.pid,
            "jar_path": state.jar_path,
            "route_summary": [],
            "log_tail": "starting...",
        }

    monkeypatch.setattr("app.routes.export.start_generated_app", fake_start)
    monkeypatch.setattr("app.routes.export.status_payload", fake_status)

    response = client.post("/export/run")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["run_status"] == "starting"
    assert data["app_url"] == "http://127.0.0.1:18088"
    assert data["health_url"].endswith("/actuator/health")
    reset_session()


def test_shared_mode_export_run_is_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    generated_app = _seed_generated_app_session(tmp_path)
    session = get_session()
    session.build_run.build_status = "build_succeeded"
    session.build_run.jar_path = str(generated_app / "target" / "demo.jar")
    save_session(session)
    shared_client, headers = _shared_client()

    def fail_start(*args, **kwargs):
        raise AssertionError("start helper should not be called when Build & Run is disabled")

    monkeypatch.setattr("app.routes.export.start_generated_app", fail_start)

    response = shared_client.post("/export/run", headers=headers)

    assert response.status_code == 403
    assert response.json()["ok"] is False
    assert response.json()["error"] == build_run_disabled_message(True)
    assert get_session().build_run.run_status == "idle"
    reset_session()


def test_shared_mode_export_run_can_be_enabled_by_operator(monkeypatch, tmp_path):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_BUILD_RUN_ENABLED", "true")
    generated_app = _seed_generated_app_session(tmp_path)
    session = get_session()
    session.build_run.build_status = "build_succeeded"
    session.build_run.jar_path = str(generated_app / "target" / "demo.jar")
    save_session(session)
    shared_client, headers = _shared_client()

    def fake_start(state):
        state.run_status = "starting"
        state.run_summary = "Application is starting."
        state.pid = 43210
        return StartResult(success=True, summary=state.run_summary, state=state)

    monkeypatch.setattr("app.routes.export.start_generated_app", fake_start)

    response = shared_client.post("/export/run", headers=headers)

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert get_session().build_run.run_status == "starting"
    reset_session()


def test_build_run_service_refuses_when_shared_mode_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")

    build_result = service_build_generated_app(str(tmp_path / "generated-app"))
    start_state = BuildRunState(
        generated_app_path=str(tmp_path / "generated-app"),
        jar_path=str(tmp_path / "generated-app" / "target" / "demo.jar"),
    )
    start_result = service_start_generated_app(start_state)

    assert build_result.success is False
    assert build_result.summary == build_run_disabled_message(True)
    assert start_result.success is False
    assert start_result.summary == build_run_disabled_message(True)
    assert start_state.run_status == "run_failed"


def test_export_stop_marks_session_stopped(tmp_path, monkeypatch):
    export_dir = _seed_exported_session(tmp_path, with_generated_app=True)
    session = get_session()
    session.build_run.generated_app_path = str(export_dir / "generated-app")
    session.build_run.run_status = "running"
    session.build_run.pid = 1234
    save_session(session)

    def fake_stop(state):
        state.run_status = "stopped"
        state.run_summary = "Application stopped."
        state.pid = None
        return state

    monkeypatch.setattr("app.routes.export.stop_generated_app", fake_stop)

    response = client.post("/export/stop")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["run_status"] == "stopped"
    assert data["pid"] is None
    reset_session()


def test_export_generate_stops_managed_app_before_resetting_build_run_state(tmp_path, monkeypatch):
    export_dir = _seed_exported_session(tmp_path, with_generated_app=True)
    session = get_session()
    session.build_run.generated_app_path = str(export_dir / "generated-app")
    session.build_run.run_status = "running"
    session.build_run.pid = 4567
    session.build_run.build_status = "build_succeeded"
    session.build_run.jar_path = str(export_dir / "generated-app" / "target" / "demo.jar")
    save_session(session)

    stopped = {"called": False, "pid": None}

    def fake_run_generate(*args, **kwargs):
        class Result:
            success = True
            combined_output = "Generated application at: /tmp/out/generated-app"
        return Result()

    def fake_stop(state):
        stopped["called"] = True
        stopped["pid"] = state.pid
        state.run_status = "stopped"
        state.pid = None
        return state

    monkeypatch.setattr("app.routes.export.run_generate", fake_run_generate)
    monkeypatch.setattr("app.routes.export.stop_generated_app", fake_stop)

    response = client.post("/export/generate")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert stopped["called"] is True
    assert stopped["pid"] == 4567

    session = get_session()
    assert session.build_run.generated_app_path == str(export_dir / "generated-app")
    assert session.build_run.run_status == "idle"
    assert session.build_run.pid is None
    reset_session()


def test_export_reset_stops_managed_app_before_clearing_session(tmp_path, monkeypatch):
    export_dir = _seed_exported_session(tmp_path, with_generated_app=True)
    session = get_session()
    session.build_run.generated_app_path = str(export_dir / "generated-app")
    session.build_run.run_status = "running"
    session.build_run.pid = 9876
    save_session(session)

    stopped = {"called": False, "pid": None}

    def fake_stop(state):
        stopped["called"] = True
        stopped["pid"] = state.pid
        state.run_status = "stopped"
        state.pid = None
        return state

    monkeypatch.setattr("app.routes.export.stop_generated_app", fake_stop)

    response = client.post("/export/reset")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert stopped["called"] is True
    assert stopped["pid"] == 9876

    session = get_session()
    assert session.build_run.pid is None
    assert session.build_run.run_status == "idle"
    assert session.build_run.generated_app_path is None
    reset_session()
