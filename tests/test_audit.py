from __future__ import annotations

import re
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.audit import AuditEvent, set_audit_sink_for_testing
from app.services.identity import Principal
from app.services.session_context import get_session_store, save_current_project
from tests.session_helpers import reset_session, save_session
from tests.test_package_writer import _full_session


class CapturingAuditSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> None:
        self.events.append(event)


def _install_sink() -> CapturingAuditSink:
    sink = CapturingAuditSink()
    set_audit_sink_for_testing(sink)
    return sink


def _csrf_from_html(html: str) -> str:
    match = re.search(
        r'<meta\s+name="edgeforge-csrf-token"\s+content="([^"]+)"',
        html,
    )
    assert match, "CSRF meta tag was not rendered"
    return match.group(1)


def _assert_event_shape_is_safe(events: list[AuditEvent]) -> None:
    allowed_keys = {
        "event_type",
        "principal_id",
        "session_id",
        "project_id",
        "timestamp",
        "outcome",
    }
    for event in events:
        payload = asdict(event)
        assert set(payload) == allowed_keys
        for key, value in payload.items():
            if value is None:
                continue
            text = str(value)
            assert "test-shared-secret" not in text
            if key != "timestamp":
                assert "/" not in text


@pytest.fixture(autouse=True)
def reset_audit_sink():
    set_audit_sink_for_testing(None)
    yield
    set_audit_sink_for_testing(None)


def test_project_create_save_and_open_emit_success_audit_events():
    reset_session()
    sink = _install_sink()
    client = TestClient(app)

    create_response = client.post(
        "/",
        data={
            "app_name": "Audit Demo",
            "bounded_context": "audit-demo",
            "app_archetype": "crud",
            "target_profile": "springboot-legacy-compatible",
        },
        follow_redirects=False,
    )
    assert create_response.status_code == 303

    save_response = client.post("/project/save")
    assert save_response.status_code == 200

    open_response = client.post(
        "/project/open",
        files={
            "project_file": (
                "audit-demo.project.json",
                save_response.content,
                "application/json",
            )
        },
        follow_redirects=False,
    )
    assert open_response.status_code == 303

    observed = [(event.event_type, event.outcome) for event in sink.events]
    assert ("project.create", "success") in observed
    assert ("project.save", "success") in observed
    assert ("project.open", "success") in observed
    assert {event.principal_id for event in sink.events} == {"anonymous:test-session"}
    assert {event.session_id for event in sink.events} == {"test-session"}
    _assert_event_shape_is_safe(sink.events)


def test_export_write_and_generate_emit_audit_events(monkeypatch, tmp_path):
    reset_session()
    sink = _install_sink()
    client = TestClient(app)
    session = _full_session()
    session.output_path = str(tmp_path)
    save_session(session)

    class FakeResult:
        success = True
        combined_output = "generated"

    monkeypatch.setattr("app.routes.export.run_generate", lambda *args, **kwargs: FakeResult())

    write_response = client.post("/export/write")
    generate_response = client.post("/export/generate")

    assert write_response.status_code == 200
    assert generate_response.status_code == 200
    observed = [(event.event_type, event.outcome) for event in sink.events]
    assert ("export.write", "success") in observed
    assert ("export.generate", "success") in observed
    _assert_event_shape_is_safe(sink.events)


def test_shared_mode_build_and_run_disabled_emit_blocked_audit_events(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    reset_session()
    sink = _install_sink()
    client = TestClient(app, base_url="https://testserver")
    page = client.get("/")
    headers = {"x-edgeforge-csrf-token": _csrf_from_html(page.text)}

    build_response = client.post("/export/build", headers=headers)
    run_response = client.post("/export/run", headers=headers)

    assert build_response.status_code == 403
    assert run_response.status_code == 403
    observed = [(event.event_type, event.outcome) for event in sink.events]
    assert ("export.build", "blocked") in observed
    assert ("export.run", "blocked") in observed
    _assert_event_shape_is_safe(sink.events)


def test_cross_principal_project_save_denial_emits_denied_audit_event():
    sink = _install_sink()
    store = get_session_store()
    alice = Principal(
        user_id="anonymous:alice",
        source="anonymous",
        claims={"anonymous_session_id": "alice"},
    )
    bob = Principal(
        user_id="anonymous:bob",
        source="anonymous",
        claims={"anonymous_session_id": "bob"},
    )
    alice_session = store.get_or_create(alice)
    alice_session.app_name = "Owned Project"
    store.save_project(alice, alice_session, project_id="owned-project")
    bob_session = store.get_or_create(bob)
    bob_request = SimpleNamespace(
        state=SimpleNamespace(
            principal=bob,
            session_store=store,
            studio_session=bob_session,
        )
    )

    with pytest.raises(PermissionError):
        save_current_project(bob_request, bob_session, project_id="owned-project")  # type: ignore[arg-type]

    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.event_type == "project.ownership"
    assert event.outcome == "denied"
    assert event.principal_id == "anonymous:bob"
    assert event.session_id == "bob"
    assert event.project_id == "owned-project"
    _assert_event_shape_is_safe(sink.events)
