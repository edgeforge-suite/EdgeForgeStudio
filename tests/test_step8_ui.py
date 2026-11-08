"""Tests for Step 8 two-section UI layout and demo flag in the run command."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models.project import BuildRunState, UpstreamInterface
from app.services.build_run_service import start_generated_app, status_payload
from tests.session_helpers import get_session, reset_session, save_session
from tests.test_package_writer import _full_session

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_session(tmp_path, with_generated_app: bool = False) -> Path:
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


# ---------------------------------------------------------------------------
# Part A — Layout tests
# ---------------------------------------------------------------------------

def test_step8_renders_two_sections_8a_and_8b(tmp_path):
    _seed_session(tmp_path)
    response = client.get("/export")
    assert response.status_code == 200
    assert "8a" in response.text
    assert "Manifest Package" in response.text
    assert "8b" in response.text
    assert "Engine Actions" in response.text
    reset_session()


def test_step8_has_no_8c_section(tmp_path):
    _seed_session(tmp_path)
    response = client.get("/export")
    assert response.status_code == 200
    # The chip "8c" must not appear as a section label (the s8-chip span)
    assert ">8c<" not in response.text
    reset_session()


def test_step8_8a_subheading(tmp_path):
    _seed_session(tmp_path)
    response = client.get("/export")
    assert response.status_code == 200
    assert "Create and validate the Engine input package." in response.text
    assert "evidence-trail.json" in response.text
    assert "Package artifacts" in response.text
    assert "Revision checkpoint" in response.text
    reset_session()


def test_step8_8b_subheading(tmp_path):
    _seed_session(tmp_path)
    response = client.get("/export")
    assert response.status_code == 200
    assert "Generate, build, and run the application from the exported package." in response.text
    reset_session()


def test_step8_8a_contains_write_validate_assess_download(tmp_path):
    _seed_session(tmp_path)
    response = client.get("/export")
    assert response.status_code == 200
    text = response.text

    # Locate the 8a section (before the 8b chip)
    idx_8a = text.index(">8a<")
    idx_8b = text.index(">8b<")
    section_8a = text[idx_8a:idx_8b]

    assert "Write to Disk" in section_8a
    assert "Validate Package" in section_8a
    assert "Assess Source APIs" in section_8a
    assert "Download ZIP" in section_8a
    assert "downloadZipAfterWrite()" in section_8a
    assert 'href="/export/download-zip"' not in section_8a
    reset_session()


def test_step8_8a_does_not_contain_generate_build_run_stop(tmp_path):
    _seed_session(tmp_path)
    response = client.get("/export")
    assert response.status_code == 200
    text = response.text

    idx_8a = text.index(">8a<")
    idx_8b = text.index(">8b<")
    section_8a = text[idx_8a:idx_8b]

    # Generate App button must not appear in 8a
    assert "Generate App" not in section_8a
    # Build / Run / Stop action buttons must not appear in 8a
    assert "btn-build-app" not in section_8a
    assert "btn-run-app" not in section_8a
    assert "btn-stop-app" not in section_8a
    reset_session()


def test_step8_8b_contains_generate_build_run_stop_refresh(tmp_path):
    _seed_session(tmp_path, with_generated_app=True)
    response = client.get("/export")
    assert response.status_code == 200
    text = response.text

    idx_8b = text.index(">8b<")
    section_8b = text[idx_8b:]

    assert "Generate App" in section_8b
    assert "btn-build-app" in section_8b
    assert "btn-run-app" in section_8b
    assert "btn-stop-app" in section_8b
    assert "btn-refresh-app" in section_8b
    reset_session()


def test_step8_8b_does_not_duplicate_package_actions(tmp_path):
    _seed_session(tmp_path)
    response = client.get("/export")
    assert response.status_code == 200
    text = response.text

    idx_8b = text.index(">8b<")
    section_8b = text[idx_8b:]

    # Package-only actions must NOT appear inside 8b
    assert "Write to Disk" not in section_8b
    assert "Validate Package" not in section_8b
    assert "Assess Source APIs" not in section_8b
    # Download ZIP anchor is also package-only
    assert "download-zip" not in section_8b
    reset_session()


def test_step8_title(tmp_path):
    _seed_session(tmp_path)
    response = client.get("/export")
    assert response.status_code == 200
    assert "Step 8: Export Package &amp; Run Generated App" in response.text
    reset_session()


def test_step8_assess_button_label(tmp_path):
    _seed_session(tmp_path)
    response = client.get("/export")
    assert response.status_code == 200
    assert "Assess Source APIs" in response.text
    # Old label must be gone
    assert "Run appbuilder assess" not in response.text
    reset_session()


def test_step8_demo_flag_note_visible(tmp_path):
    _seed_session(tmp_path, with_generated_app=True)
    response = client.get("/export")
    assert response.status_code == 200
    assert "demo/test endpoints via a runtime flag" in response.text
    assert "not written to generated source" in response.text
    reset_session()


def test_step8_surfaces_latest_revision_checkpoint_and_artifact_downloads(tmp_path):
    _seed_session(tmp_path)
    response = client.get("/export")
    assert response.status_code == 200
    assert "Output directory" in response.text
    assert "app-definition.yaml" in response.text
    assert "studio-project.json" in response.text
    assert "Openable Studio authoring snapshot that produced this package." in response.text
    assert "Knowledge Assist provenance sidecar for supported suggestion types." in response.text
    assert "Source API assessment snapshot. Refreshed when Assess Source APIs runs." in response.text
    assert "Revision ID" in response.text
    assert "Manifest Hash" in response.text
    assert "/export/artifact/evidence-trail.json" in response.text
    reset_session()


def test_step8_export_write_returns_reference_only_edge_contract_warnings(tmp_path):
    _seed_session(tmp_path)
    session = get_session()
    session.upstream_interfaces.append(
        UpstreamInterface(
            name="account-xml",
            type="xml-xsd",
            xsd_path="contracts/account.xsd",
            root_element="acct:Account",
        )
    )
    save_session(session)

    response = client.post("/export/write")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert any("account-xml" in warning for warning in payload["warnings"])
    assert any("no uploaded artifact content" in warning for warning in payload["warnings"])
    reset_session()


def test_step8_warns_when_engine_repo_path_is_host_only_in_docker(tmp_path, monkeypatch):
    _seed_session(tmp_path)
    monkeypatch.setenv("EDGEFORGE_STUDIO_DEFAULT_ENGINE_REPO", "/workspace/EdgeForge")
    session = get_session()
    session.appbuilder_repo_path = "/Users/example/Documents/GitHub/EdgeForge"
    save_session(session)

    response = client.get("/export")

    assert response.status_code == 200
    assert "This project was saved with an Engine path that does not exist here." in response.text
    assert "set EdgeForge Local Repo Path to `/workspace/EdgeForge` in Step 1" in response.text


def test_step8_validate_returns_clear_engine_path_error(tmp_path, monkeypatch):
    _seed_session(tmp_path)
    monkeypatch.setenv("EDGEFORGE_STUDIO_DEFAULT_ENGINE_REPO", "/workspace/EdgeForge")
    session = get_session()
    session.appbuilder_repo_path = "/Users/example/Documents/GitHub/EdgeForge"
    save_session(session)

    response = client.post("/export/validate")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert "In Docker, set EdgeForge Local Repo Path to /workspace/EdgeForge in Step 1." in payload["summary"]


def test_export_write_blocks_host_output_path_in_docker(monkeypatch):
    from app.services.runtime_defaults import DOCKER_MODE_ENV

    monkeypatch.setenv(DOCKER_MODE_ENV, "1")
    reset_session()
    session = _full_session()
    session.output_path = "/Users/example/Documents/EdgeForgeGeneratedApps"
    save_session(session)

    response = client.post("/export/write")

    assert response.status_code == 400
    payload = response.json()
    assert payload["ok"] is False
    assert "Docker Studio cannot export to host path /Users/example/Documents/EdgeForgeGeneratedApps" in payload["error"]
    assert "/workspace/data/GeneratedApps" in payload["error"]
    reset_session()


def test_export_write_allows_host_output_path_outside_docker(tmp_path, monkeypatch):
    from app.services.runtime_defaults import DOCKER_MODE_ENV

    monkeypatch.setenv(DOCKER_MODE_ENV, "0")
    reset_session()
    session = _full_session()
    session.output_path = str(tmp_path)
    save_session(session)

    response = client.post("/export/write")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    reset_session()


def test_docker_status_payload_uses_studio_proxy_url(monkeypatch):
    from app.services.runtime_defaults import DOCKER_MODE_ENV, PUBLIC_BASE_URL_ENV

    monkeypatch.setenv(DOCKER_MODE_ENV, "1")
    monkeypatch.setenv(PUBLIC_BASE_URL_ENV, "http://127.0.0.1:8083")
    state = BuildRunState(
        generated_app_path="/workspace/data/GeneratedApps/demo/generated-app",
        app_url="http://127.0.0.1:18080",
        health_url="http://127.0.0.1:18080/actuator/health",
        port=18080,
    )

    payload = status_payload(state)

    assert payload["app_url"] == "http://127.0.0.1:8083/export/generated-app/18080"
    assert payload["health_url"] == "http://127.0.0.1:8083/export/generated-app/18080/actuator/health"
    assert payload["internal_app_url"] == "http://127.0.0.1:18080"


def test_generated_app_proxy_rejects_unmanaged_port(monkeypatch):
    from app.services.runtime_defaults import DOCKER_MODE_ENV

    monkeypatch.setenv(DOCKER_MODE_ENV, "1")
    reset_session()
    session = get_session()
    session.build_run.port = 18080
    session.build_run.pid = 12345
    session.build_run.run_status = "running"
    save_session(session)

    response = client.get("/export/generated-app/18081/actuator/health")

    assert response.status_code == 404
    reset_session()


def test_generated_app_proxy_allows_managed_port(monkeypatch):
    from app.services.runtime_defaults import DOCKER_MODE_ENV

    class FakeResponse:
        status_code = 200
        content = b"managed generated app"
        headers = {
            "content-type": "text/plain",
            "content-length": "999",
            "content-encoding": "gzip",
        }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, method, url, content=None, headers=None):
            assert method == "GET"
            assert url == "http://127.0.0.1:18080/health"
            assert headers["accept-encoding"] == "identity"
            return FakeResponse()

    monkeypatch.setenv(DOCKER_MODE_ENV, "1")
    monkeypatch.setattr("app.routes.export.httpx.AsyncClient", FakeAsyncClient)
    reset_session()
    try:
        session = get_session()
        session.build_run.port = 18080
        session.build_run.pid = 12345
        session.build_run.run_status = "running"
        save_session(session)

        response = client.get("/export/generated-app/18080/health")

        assert response.status_code == 200
        assert response.text == "managed generated app"
        assert response.headers.get("content-length") != "999"
        assert "content-encoding" not in {key.lower() for key in response.headers}
    finally:
        reset_session()


def test_generated_app_proxy_injects_fetch_rewrite_for_html(monkeypatch):
    from app.services.runtime_defaults import DOCKER_MODE_ENV

    class FakeResponse:
        status_code = 200
        content = b"<html><head><title>Generated</title></head><body><script src=\"/app.js\"></script></body></html>"
        headers = {"content-type": "text/html; charset=utf-8"}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, method, url, content=None, headers=None):
            assert url == "http://127.0.0.1:18080/"
            return FakeResponse()

    monkeypatch.setenv(DOCKER_MODE_ENV, "1")
    monkeypatch.setattr("app.routes.export.httpx.AsyncClient", FakeAsyncClient)
    reset_session()
    try:
        session = get_session()
        session.build_run.port = 18080
        session.build_run.pid = 12345
        session.build_run.run_status = "running"
        save_session(session)

        response = client.get("/export/generated-app/18080/")

        assert response.status_code == 200
        assert "data-edgeforge-generated-app-proxy" in response.text
        assert 'const proxyBase = "/export/generated-app/18080";' in response.text
        assert "value.startsWith(proxyBase + \"/\")" in response.text
        assert "value.startsWith(\"/export/generated-app/\")" in response.text
        assert response.text.index("data-edgeforge-generated-app-proxy") < response.text.index("src=\"/app.js\"")
    finally:
        reset_session()


def test_generated_app_proxy_does_not_modify_non_html(monkeypatch):
    from app.services.runtime_defaults import DOCKER_MODE_ENV

    class FakeResponse:
        status_code = 200
        content = b'{"ok":true}'
        headers = {"content-type": "application/json"}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, method, url, content=None, headers=None):
            assert url == "http://127.0.0.1:18080/api/demo/entities/Customer"
            return FakeResponse()

    monkeypatch.setenv(DOCKER_MODE_ENV, "1")
    monkeypatch.setattr("app.routes.export.httpx.AsyncClient", FakeAsyncClient)
    reset_session()
    try:
        session = get_session()
        session.build_run.port = 18080
        session.build_run.pid = 12345
        session.build_run.run_status = "running"
        save_session(session)

        response = client.get("/export/generated-app/18080/api/demo/entities/Customer")

        assert response.status_code == 200
        assert response.text == '{"ok":true}'
        assert "edgeforge-generated-app-proxy" not in response.text
    finally:
        reset_session()


def test_generated_app_proxy_preserves_post_body_content_type_and_query(monkeypatch):
    from app.services.runtime_defaults import DOCKER_MODE_ENV

    captured = {}

    class FakeResponse:
        status_code = 201
        content = b'{"id":1}'
        headers = {"content-type": "application/json"}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, method, url, content=None, headers=None):
            captured["method"] = method
            captured["url"] = url
            captured["content"] = content
            captured["content_type"] = headers.get("content-type")
            return FakeResponse()

    monkeypatch.setenv(DOCKER_MODE_ENV, "1")
    monkeypatch.setattr("app.routes.export.httpx.AsyncClient", FakeAsyncClient)
    reset_session()
    try:
        session = get_session()
        session.build_run.port = 18080
        session.build_run.pid = 12345
        session.build_run.run_status = "running"
        save_session(session)

        response = client.post(
            "/export/generated-app/18080/customers?dryRun=true",
            json={"name": "Ada"},
        )

        assert response.status_code == 201
        assert captured == {
            "method": "POST",
            "url": "http://127.0.0.1:18080/customers?dryRun=true",
            "content": b'{"name":"Ada"}',
            "content_type": "application/json",
        }
    finally:
        reset_session()


# ---------------------------------------------------------------------------
# Part B — Demo flag in java run command
# ---------------------------------------------------------------------------

def test_start_generated_app_command_includes_demo_flag(tmp_path, monkeypatch):
    """start_generated_app must pass --appbuilder.demo.enabled=true to the JVM."""
    app_dir = tmp_path / "generated-app"
    app_dir.mkdir(parents=True, exist_ok=True)
    jar_path = app_dir / "target" / "demo.jar"
    jar_path.parent.mkdir(parents=True, exist_ok=True)
    jar_path.write_text("", encoding="utf-8")

    captured = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd

        class FakeProc:
            pid = 99999

        return FakeProc()

    monkeypatch.setattr("app.services.build_run_service.choose_port", lambda port: 18099)
    monkeypatch.setattr("subprocess.Popen", fake_popen)

    state = BuildRunState(
        generated_app_path=str(app_dir),
        jar_path=str(jar_path),
    )

    result = start_generated_app(state)

    assert result.success is True
    cmd = captured["cmd"]
    assert "--server.port=18099" in cmd
    assert "--appbuilder.demo.enabled=true" in cmd


def test_start_generated_app_command_has_server_port_before_demo_flag(tmp_path, monkeypatch):
    """--server.port must appear before --appbuilder.demo.enabled=true in the command."""
    app_dir = tmp_path / "generated-app"
    app_dir.mkdir(parents=True, exist_ok=True)
    jar_path = app_dir / "target" / "demo.jar"
    jar_path.parent.mkdir(parents=True, exist_ok=True)
    jar_path.write_text("", encoding="utf-8")

    captured = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd

        class FakeProc:
            pid = 88888

        return FakeProc()

    monkeypatch.setattr("app.services.build_run_service.choose_port", lambda port: 18090)
    monkeypatch.setattr("subprocess.Popen", fake_popen)

    state = BuildRunState(
        generated_app_path=str(app_dir),
        jar_path=str(jar_path),
    )

    start_generated_app(state)

    cmd = captured["cmd"]
    port_idx = next(i for i, arg in enumerate(cmd) if arg.startswith("--server.port="))
    demo_idx = cmd.index("--appbuilder.demo.enabled=true")
    assert port_idx < demo_idx
