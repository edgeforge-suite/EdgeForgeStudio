"""Focused tests for the Step 1 kickoff workspace summary."""

from fastapi.testclient import TestClient

from app.main import app
from app.services.ks_workspace_summary import WorkspaceSummary, build_workspace_summary
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def test_step1_shows_workspace_namespace_and_document_count(monkeypatch) -> None:
    session = get_session()
    session.capabilities.knowledge_assist_enabled = True
    session.project_id = "studio-ks-demo"
    session.ks_project_id = "studio-ks-demo"
    save_session(session)

    monkeypatch.setattr(
        "app.routes.project.build_workspace_summary",
        lambda session: WorkspaceSummary(
            namespace="studio-ks-demo",
            linkage_label="studio-ks-demo",
            linkage_detail="Durable workspace linkage is preserved across local save/open.",
            ks_status="available",
            ks_status_label="Available",
            ks_status_detail="Workspace is reachable for ingest, search, and field catalog browse.",
            document_count=3,
            document_summary="3 document(s) indexed in this workspace.",
            warning=None,
        ),
    )

    response = client.get("/")

    assert response.status_code == 200
    assert "studio-ks-demo" in response.text
    assert "3 document(s) indexed in this workspace." in response.text


def test_step1_does_not_build_workspace_summary_when_assist_off(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.routes.project.build_workspace_summary",
        lambda session: (_ for _ in ()).throw(AssertionError("summary should not be built when Knowledge Assist is off")),
    )

    response = client.get("/")

    assert response.status_code == 200
    assert "Knowledge Assist is off" in response.text
    assert "Open Knowledge Workspace" not in response.text


def test_step1_builds_workspace_summary_when_assist_on(monkeypatch) -> None:
    session = get_session()
    session.capabilities.knowledge_assist_enabled = True
    save_session(session)
    seen = {"called": False}

    def fake_summary(session):
        seen["called"] = True
        return WorkspaceSummary(
            namespace="studio-ks-demo",
            linkage_label="studio-ks-demo",
            linkage_detail="Durable workspace linkage is preserved across local save/open.",
            ks_status="available",
            ks_status_label="Available",
            ks_status_detail="Workspace is reachable for ingest, search, and field catalog browse.",
            document_count=2,
            document_summary="2 document(s) indexed in this workspace.",
            warning=None,
        )

    monkeypatch.setattr("app.routes.project.build_workspace_summary", fake_summary)

    response = client.get("/")

    assert response.status_code == 200
    assert seen["called"] is True
    assert "Open Knowledge Workspace" in response.text
    assert "2 document(s) indexed in this workspace." in response.text


def test_workspace_summary_does_not_probe_ks_for_fresh_step1(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.ks_workspace_summary.ks_client",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ks_client should not be used for Step 1 summary")),
        raising=False,
    )

    summary = build_workspace_summary(get_session())

    assert summary.namespace is None
    assert summary.ks_status == "idle"
    assert summary.ks_status_label == "Ready on open"
    assert summary.warning is None


def test_workspace_summary_does_not_probe_ks_for_linked_workspace(monkeypatch) -> None:
    session = get_session()
    session.project_id = "studio-ks-demo"
    session.ks_project_id = "studio-ks-demo"
    session.ks_active = True
    save_session(session)

    monkeypatch.setattr(
        "app.services.ks_workspace_summary.ks_client",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ks_client should not be used for Step 1 summary")),
        raising=False,
    )

    summary = build_workspace_summary(session)

    assert summary.namespace == "studio-ks-demo"
    assert summary.ks_status == "linked"
    assert summary.ks_status_label == "Linked"
    assert "verify current workspace availability" in summary.ks_status_detail


def test_step1_shows_workspace_degraded_warning_without_breaking_page(monkeypatch) -> None:
    session = get_session()
    session.capabilities.knowledge_assist_enabled = True
    save_session(session)

    monkeypatch.setattr(
        "app.routes.project.build_workspace_summary",
        lambda session: WorkspaceSummary(
            namespace=None,
            linkage_label="Created on first workspace use",
            linkage_detail="Durable workspace linkage is minted once and then preserved across local save/open.",
            ks_status="degraded",
            ks_status_label="Degraded",
            ks_status_detail="Step 1 stays usable while the detailed workspace is temporarily unavailable.",
            document_count=None,
            document_summary="Document summary is unavailable until the workspace responds.",
            warning="Workspace unavailable: mock outage",
        ),
    )

    response = client.get("/")

    assert response.status_code == 200
    assert "Degraded mode:" in response.text
    assert "mock outage" in response.text
    assert "Save &amp; Continue" in response.text


def test_step1_off_state_never_renders_degraded_warning(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.routes.project.build_workspace_summary",
        lambda session: WorkspaceSummary(
            namespace=None,
            linkage_label="Created on first workspace use",
            linkage_detail="Durable workspace linkage is minted once and then preserved across local save/open.",
            ks_status="degraded",
            ks_status_label="Degraded",
            ks_status_detail="Step 1 stays usable while the detailed workspace is temporarily unavailable.",
            document_count=None,
            document_summary="Document summary is unavailable until the workspace responds.",
            warning="mock outage",
        ),
    )

    response = client.get("/")

    assert response.status_code == 200
    assert "mock outage" not in response.text
    assert "Degraded mode:" not in response.text


def test_step1_kafka_shows_topic_ingest_as_next_step(monkeypatch) -> None:
    session = get_session()
    session.app_archetype = "kafka-integration"
    save_session(session)

    monkeypatch.setattr(
        "app.routes.project.build_workspace_summary",
        lambda session: WorkspaceSummary(
            namespace=None,
            linkage_label="Created on first workspace use",
            linkage_detail="Durable workspace linkage is minted once and then preserved across local save/open.",
            ks_status="available",
            ks_status_label="Ready",
            ks_status_detail="The workspace is ready when you open the detailed workspace.",
            document_count=None,
            document_summary="Open the detailed workspace to begin document ingest.",
            warning=None,
        ),
    )

    response = client.get("/")

    assert response.status_code == 200
    assert "Topic Ingest" in response.text
    assert "consumer-group setup and your first topic pair" in response.text
