"""Tests for Step 1 UI label and default value fixes."""

import re

from fastapi.testclient import TestClient

from app.main import app
from app.models.project_capabilities import ProjectCapabilities
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)


def _csrf_from_html(html: str) -> str:
    match = re.search(
        r'<meta\s+name="edgeforge-csrf-token"\s+content="([^"]+)"',
        html,
    )
    assert match, "CSRF meta tag was not rendered"
    return match.group(1)


def test_step1_label_is_edgeforge_local_repo_path():
    """Step 1 HTML must use the new 'EdgeForge Local Repo Path' label."""
    reset_session()
    response = client.get("/")
    assert response.status_code == 200
    assert "EdgeForge Local Repo Path" in response.text
    # Old label must be gone
    assert "AppBuilder Repo Path" not in response.text


def test_step1_subtitle_references_edgeforge_engine():
    """Subtitle must reference EdgeForge Engine manifest, not AppBuilder."""
    reset_session()
    response = client.get("/")
    assert response.status_code == 200
    assert "EdgeForge Engine manifest" in response.text


def test_step1_default_repo_path_is_edgeforge():
    """Saving Step 1 without supplying a repo path must default to the EdgeForge path."""
    from app.routes.project import DEFAULT_EDGEFORGE_PATH
    from tests.session_helpers import get_session

    reset_session()
    client.post("/", data={
        "app_name": "TestApp",
        "bounded_context": "test",
        "target_profile": "springboot-legacy-compatible",
        "output_path": "",
        "appbuilder_repo_path": "",
    })
    session = get_session()
    assert session.appbuilder_repo_path == DEFAULT_EDGEFORGE_PATH
    reset_session()


def test_step1_shows_all_supported_target_profiles():
    """Step 1 must list all Studio-supported target profile options."""
    reset_session()
    response = client.get("/")

    assert response.status_code == 200
    assert 'value="springboot-legacy-compatible"' in response.text
    assert 'value="springboot-enterprise-postgres-java17"' in response.text
    assert 'value="springboot-standard-enterprise"' in response.text
    assert "Spring Boot Legacy Compatible (Java 17 + H2)" in response.text
    assert "Spring Boot Enterprise Postgres (Java 17 + PostgreSQL)" in response.text
    assert "Spring Boot Standard Enterprise (Java 21 + PostgreSQL)" in response.text


def test_step1_save_accepts_enterprise_postgres_java17_profile():
    """Step 1 save should persist the new Java 17 PostgreSQL enterprise profile."""
    from tests.session_helpers import get_session

    reset_session()
    response = client.post("/", data={
        "app_name": "TestApp",
        "bounded_context": "test",
        "target_profile": "springboot-enterprise-postgres-java17",
        "output_path": "",
        "appbuilder_repo_path": "",
    }, follow_redirects=False)

    assert response.status_code == 303
    session = get_session()
    assert session.target_profile == "springboot-enterprise-postgres-java17"
    reset_session()


def test_step1_shared_mode_ignores_user_supplied_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    reset_session()
    shared_client = TestClient(app, base_url="https://testserver")
    page = shared_client.get("/")
    token = _csrf_from_html(page.text)

    response = shared_client.post(
        "/",
        data={
            "app_name": "Shared Paths",
            "bounded_context": "shared",
            "app_archetype": "crud",
            "target_profile": "springboot-standard-enterprise",
            "output_path": str(tmp_path / "evil-output"),
            "appbuilder_repo_path": str(tmp_path / "evil-engine"),
        },
        headers={"x-edgeforge-csrf-token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    session = get_session()
    assert session.output_path == ""
    assert session.appbuilder_repo_path == ""
    reset_session()


def test_step1_repo_path_input_has_edgeforge_placeholder():
    """The repo path input should have a placeholder hinting at the EdgeForge path."""
    reset_session()
    response = client.get("/")
    assert response.status_code == 200
    assert "EdgeForge" in response.text
    # Hint text should mention local filesystem
    assert "Local filesystem path" in response.text


def test_step1_fresh_session_pre_fills_edgeforge_path():
    """A fresh GET / must pre-fill the repo path input with the EdgeForge path, not AppBuilder."""
    from app.routes.project import DEFAULT_EDGEFORGE_PATH
    from tests.session_helpers import get_session

    reset_session()
    response = client.get("/")
    assert response.status_code == 200
    # The model default flows into the template value="{{ session.appbuilder_repo_path }}"
    session = get_session()
    assert "AppBuilder" not in session.appbuilder_repo_path
    assert session.appbuilder_repo_path == DEFAULT_EDGEFORGE_PATH
    # Also verify the rendered HTML contains the EdgeForge path, not the old AppBuilder path
    assert "/Documents/GitHub/EdgeForge" in response.text or DEFAULT_EDGEFORGE_PATH in response.text


def test_step1_fresh_session_uses_env_default_repo_path(monkeypatch):
    from app.models.project import ProjectSession
    from app.services.runtime_defaults import DEFAULT_EDGEFORGE_PATH_ENV

    monkeypatch.setenv(DEFAULT_EDGEFORGE_PATH_ENV, "/workspace/EdgeForge")

    session = ProjectSession()

    assert session.appbuilder_repo_path == "/workspace/EdgeForge"


def test_docker_mode_defaults_engine_and_output_paths(monkeypatch):
    from app.models.project import ProjectSession
    from app.services.runtime_defaults import (
        DEFAULT_EDGEFORGE_PATH_ENV,
        DEFAULT_OUTPUT_PATH_ENV,
        DOCKER_MODE_ENV,
        default_output_path,
    )

    monkeypatch.delenv(DEFAULT_EDGEFORGE_PATH_ENV, raising=False)
    monkeypatch.delenv(DEFAULT_OUTPUT_PATH_ENV, raising=False)
    monkeypatch.setenv(DOCKER_MODE_ENV, "1")

    session = ProjectSession()

    assert session.appbuilder_repo_path == "/workspace/EdgeForge"
    assert default_output_path() == "/workspace/data/GeneratedApps"


def test_docker_mode_ignores_host_style_default_path_env(monkeypatch):
    from app.models.project import ProjectSession
    from app.services.runtime_defaults import (
        DEFAULT_EDGEFORGE_PATH_ENV,
        DEFAULT_OUTPUT_PATH_ENV,
        DOCKER_MODE_ENV,
        default_output_path,
    )

    monkeypatch.setenv(DOCKER_MODE_ENV, "1")
    monkeypatch.setenv(DEFAULT_EDGEFORGE_PATH_ENV, "/Users/example/Documents/GitHub/EdgeForge")
    monkeypatch.setenv(DEFAULT_OUTPUT_PATH_ENV, "/Users/example/Documents/GeneratedApps")

    session = ProjectSession()

    assert session.appbuilder_repo_path == "/workspace/EdgeForge"
    assert default_output_path() == "/workspace/data/GeneratedApps"


def test_step1_shows_docker_path_correction_notice(monkeypatch):
    from app.services.runtime_defaults import (
        DEFAULT_EDGEFORGE_PATH_ENV,
        DEFAULT_OUTPUT_PATH_ENV,
        DOCKER_MODE_ENV,
    )

    monkeypatch.setenv(DOCKER_MODE_ENV, "1")
    monkeypatch.delenv(DEFAULT_EDGEFORGE_PATH_ENV, raising=False)
    monkeypatch.delenv(DEFAULT_OUTPUT_PATH_ENV, raising=False)
    reset_session()

    response = client.get("/?project_notice=docker-paths-corrected")

    assert response.status_code == 200
    assert "Project paths were adjusted for this runtime. Review Engine Path and Output Path before exporting." in response.text
    assert "Docker Studio corrected host paths" not in response.text
    assert response.text.index("Project paths were adjusted for this runtime") < response.text.index("data-knowledge-assist-panel")


def test_step1_archetype_switch_stops_managed_app_before_reset(monkeypatch):
    """Switching archetypes in Step 1 must stop any managed app before reset clears state."""
    from tests.session_helpers import get_session, save_session

    reset_session()
    session = get_session()
    session.app_name = "Demo"
    session.bounded_context = "demo"
    session.app_archetype = "crud"
    session.target_profile = "springboot-legacy-compatible"
    session.project_id = "existing-workspace"
    session.ks_project_id = "existing-workspace"
    session.ks_active = True
    session.capabilities = ProjectCapabilities(knowledge_assist_enabled=True)
    session.review_approved = True
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["s-1"]
    session.build_run.generated_app_path = "/tmp/generated-app"
    session.build_run.run_status = "running"
    session.build_run.pid = 4321
    save_session(session)

    seen = {"called": False, "pid": None, "path": None}

    def fake_stop(build_run):
        seen["called"] = True
        seen["pid"] = build_run.pid
        seen["path"] = build_run.generated_app_path
        build_run.run_status = "stopped"
        build_run.pid = None

    monkeypatch.setattr("app.routes.project.stop_generated_app", fake_stop)

    response = client.post("/", data={
        "app_name": "Demo",
        "bounded_context": "demo",
        "app_archetype": "passthrough-router",
        "target_profile": "springboot-legacy-compatible",
        "output_path": "",
        "appbuilder_repo_path": "",
    }, follow_redirects=False)

    assert response.status_code == 303
    assert seen["called"] is True
    assert seen["pid"] == 4321
    assert seen["path"] == "/tmp/generated-app"

    session = get_session()
    assert session.app_archetype == "passthrough-router"
    assert session.project_id is None
    assert session.ks_project_id is None
    assert session.ks_active is False
    assert session.capabilities.knowledge_assist_enabled is False
    assert session.review_approved is False
    assert session.ks_workspace_state.suggestion_review_state.accepted_ids == []
    assert session.build_run.pid is None
    assert session.build_run.generated_app_path is None
    assert session.build_run.run_status == "idle"
    reset_session()


def test_step1_shows_knowledge_assist_toggle_off_by_default():
    reset_session()
    response = client.get("/")

    assert response.status_code == 200
    assert "Knowledge Assist" in response.text
    assert "Knowledge Assist is off" in response.text
    assert "Enable it in Step 1 to use the Knowledge Workspace" not in response.text
    assert 'name="knowledge_assist_enabled"' in response.text
    assert 'href="/knowledge"' not in response.text
    assert "KS Status" not in response.text
    assert "Workspace Status" not in response.text
    assert "Degraded mode:" not in response.text


def test_step1_shows_assist_off_notice_from_knowledge_redirect():
    reset_session()
    response = client.get("/?assist_notice=knowledge-off")

    assert response.status_code == 200
    assert "Knowledge Assist is off. Enable it in Step 1 to use the Knowledge Workspace." in response.text
    assert 'id="knowledge-assist-settings"' in response.text
    assert "Use the On/Off switch in this panel, then save Step 1." in response.text
    assert 'href="/knowledge"' not in response.text


def test_step1_renders_required_core_fields_and_next_step_cue():
    reset_session()
    response = client.get("/")

    assert response.status_code == 200
    assert "App Type / Archetype" in response.text
    assert "App Name" in response.text
    assert "Bounded Context" in response.text
    assert "Target Profile" in response.text
    assert "Output Path" in response.text
    assert "EdgeForge Local Repo Path" in response.text
    assert "Next Step" in response.text
    assert "Upstream Contract" in response.text


def test_step1_removes_stale_workspace_out_of_scope_copy():
    reset_session()
    response = client.get("/")

    assert response.status_code == 200
    assert "Review persistence, evidence export, reconnect automation, and manifest prefill are still out of scope." not in response.text
    assert "This bounded Phase 5 slice adds durable save/open linkage only." not in response.text
    assert "broader suggestion scopes, manifest prefill, richer reconnect automation" in response.text


def test_step1_post_without_toggle_stores_knowledge_assist_off():
    reset_session()
    response = client.post("/", data={
        "app_name": "TestApp",
        "bounded_context": "test",
        "app_archetype": "crud",
        "target_profile": "springboot-legacy-compatible",
        "output_path": "",
        "appbuilder_repo_path": "",
    }, follow_redirects=False)

    assert response.status_code == 303
    session = get_session()
    assert session.capabilities.knowledge_assist_enabled is False
    assert session.ks_active is False


def test_step1_post_with_toggle_on_stores_user_intent_without_starting_workspace():
    reset_session()
    response = client.post("/", data={
        "app_name": "TestApp",
        "bounded_context": "test",
        "app_archetype": "crud",
        "target_profile": "springboot-legacy-compatible",
        "output_path": "",
        "appbuilder_repo_path": "",
        "knowledge_assist_enabled": "on",
    }, follow_redirects=False)

    assert response.status_code == 303
    session = get_session()
    assert session.capabilities.knowledge_assist_enabled is True
    assert session.ks_active is False
    assert session.project_id is None
    assert session.ks_project_id is None


def test_step1_post_toggle_off_preserves_dormant_workspace_state():
    reset_session()
    session = get_session()
    session.project_id = "workspace-123"
    session.ks_project_id = "workspace-123"
    session.ks_active = True
    session.capabilities.knowledge_assist_enabled = True
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["s-1"]
    save_session(session)

    response = client.post("/", data={
        "app_name": "TestApp",
        "bounded_context": "test",
        "app_archetype": "crud",
        "target_profile": "springboot-legacy-compatible",
        "output_path": "",
        "appbuilder_repo_path": "",
    }, follow_redirects=False)

    assert response.status_code == 303
    refreshed = get_session()
    assert refreshed.capabilities.knowledge_assist_enabled is False
    assert refreshed.ks_active is False
    assert refreshed.project_id == "workspace-123"
    assert refreshed.ks_project_id == "workspace-123"
    assert refreshed.ks_workspace_state.suggestion_review_state.accepted_ids == ["s-1"]
