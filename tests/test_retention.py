from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from starlette.requests import Request

from app.integrations.ks_integration import KSClient
from app.models.project import ProjectSession
from app.services.audit import AuditEvent, set_audit_sink_for_testing
from app.services.identity import Principal
from app.services.ks_lifecycle import (
    ks_client,
    reset_ks_lifecycle_for_testing,
    set_ks_client_factory_for_testing,
)
from app.services.retention import (
    DURABLE_SUBDIR,
    remove_workspace_fully,
    remove_workspace_preserving_durable,
)
from app.services.session_context import (
    _reset_retention_sweeper_for_testing,
    get_current_session,
)
from app.services.sqlite_session_store import SqliteSessionStore


class CapturingAuditSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> None:
        self.events.append(event)


class FakeKSClient:
    instances: list[FakeKSClient] = []

    def __init__(self, allowed_roots: list[str], db_path: str | None = None) -> None:
        self.allowed_roots = allowed_roots
        self.db_path = db_path
        self.started = False
        self.stopped = False
        FakeKSClient.instances.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True
        self.started = False

    def is_ready(self) -> bool:
        return self.started and not self.stopped


@pytest.fixture(autouse=True)
def reset_process_state():
    reset_ks_lifecycle_for_testing()
    set_audit_sink_for_testing(None)
    yield
    reset_ks_lifecycle_for_testing()
    set_audit_sink_for_testing(None)


def _principal(session_id: str) -> Principal:
    return Principal(
        user_id=f"anonymous:{session_id}",
        source="anonymous",
        claims={"anonymous_session_id": session_id},
    )


def _active_project_id(session_id: str) -> str:
    return f"{session_id}:active"


def _future_now_iso() -> str:
    return datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat()


def _request(principal: Principal, store: object) -> Request:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
        }
    )
    request.state.principal = principal
    request.state.session_store = store
    return request


def test_purge_expired_removes_workspace_and_cascades_catalog_rows(tmp_path):
    sink = CapturingAuditSink()
    set_audit_sink_for_testing(sink)
    store = SqliteSessionStore(state_dir=tmp_path)
    principal = _principal("expired-browser")
    session = store.get_or_create(principal)
    workspace = Path(session.workspace_root or "")
    (workspace / "exports").mkdir()
    (workspace / "exports" / "package.zip").write_text("package", encoding="utf-8")

    purged = store.purge_expired_sessions(now_iso=_future_now_iso())

    assert purged == 1
    assert not workspace.exists()
    assert store.list_projects(principal) == []
    with pytest.raises(KeyError):
        store.load(session.session_id or "")
    assert [(event.event_type, event.session_id, event.outcome) for event in sink.events] == [
        ("session.purge", "expired-browser", "success")
    ]


def test_purge_preserves_managed_artifacts_and_catalog_handle(tmp_path):
    store = SqliteSessionStore(state_dir=tmp_path)
    principal = _principal("durable-browser")
    session = store.get_or_create(principal)
    workspace = Path(session.workspace_root or "")
    durable = workspace / DURABLE_SUBDIR
    durable.mkdir()
    (durable / "baseline.json").write_text("durable", encoding="utf-8")
    (workspace / "ks").mkdir()
    (workspace / "ks" / "knowledge.sqlite3").write_text("volatile", encoding="utf-8")

    purged = store.purge_expired_sessions(now_iso=_future_now_iso())

    assert purged == 0
    assert workspace.exists()
    assert (durable / "baseline.json").read_text(encoding="utf-8") == "durable"
    assert not (workspace / "ks").exists()
    assert [project.project_id for project in store.list_projects(principal)] == [
        _active_project_id("durable-browser")
    ]
    assert store.load(session.session_id or "").session_id == "durable-browser"


def test_purge_skips_recently_seen_session(tmp_path):
    store = SqliteSessionStore(state_dir=tmp_path)
    principal = _principal("active-browser")
    session = store.get_or_create(principal)
    workspace = Path(session.workspace_root or "")
    (workspace / "output").mkdir()
    (workspace / "output" / "package").write_text("fresh", encoding="utf-8")

    purged = store.purge_expired_sessions(now_iso=datetime.now(timezone.utc).isoformat())

    assert purged == 0
    assert (workspace / "output" / "package").exists()
    assert store.get_project(principal, _active_project_id("active-browser")) is not None


def test_purge_stops_workspace_ks_client_before_removing_files(tmp_path):
    store = SqliteSessionStore(state_dir=tmp_path)
    principal = _principal("ks-browser")
    session = store.get_or_create(principal)
    workspace = Path(session.workspace_root or "")
    allowed_root = workspace / "ks"
    allowed_root.mkdir()
    set_ks_client_factory_for_testing(FakeKSClient)

    with ks_client([str(allowed_root)], db_path=str(allowed_root / "knowledge.sqlite3")) as client:
        assert client.started is True

    purged = store.purge_expired_sessions(now_iso=_future_now_iso())

    assert purged == 1
    assert FakeKSClient.instances[0].stopped is True
    assert not workspace.exists()


def test_reset_cleans_workspace_contents_but_preserves_managed_artifacts(tmp_path):
    sink = CapturingAuditSink()
    set_audit_sink_for_testing(sink)
    store = SqliteSessionStore(state_dir=tmp_path)
    principal = _principal("reset-browser")
    session = store.get_or_create(principal)
    workspace = Path(session.workspace_root or "")
    durable = workspace / DURABLE_SUBDIR
    durable.mkdir()
    (durable / "baseline.json").write_text("durable", encoding="utf-8")
    (workspace / "exports").mkdir()
    (workspace / "exports" / "package.zip").write_text("volatile", encoding="utf-8")

    reset = store.reset("reset-browser")

    assert reset.session_id == "reset-browser"
    assert workspace.exists()
    assert (durable / "baseline.json").exists()
    assert not (workspace / "exports").exists()
    assert [(event.event_type, event.session_id, event.outcome) for event in sink.events] == [
        ("session.reset.cleanup", "reset-browser", "success")
    ]


def test_reset_audit_observes_only_committed_session_state(tmp_path):
    store = SqliteSessionStore(state_dir=tmp_path)
    principal = _principal("commit-visible-browser")
    session = store.get_or_create(principal)
    session.app_name = "Before"
    store.save(session)
    observed_app_names: list[str] = []

    class ObservingAuditSink:
        def emit(self, _event: AuditEvent) -> None:
            observed_app_names.append(store.load("commit-visible-browser").app_name)

    set_audit_sink_for_testing(ObservingAuditSink())

    reset = store.reset("commit-visible-browser")

    assert reset.app_name != "Before"
    assert observed_app_names == [reset.app_name]


class _CommitFailingConnection:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __getattr__(self, name: str):
        return getattr(self._conn, name)

    def __enter__(self):
        self._conn.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            self._conn.rollback()
            raise sqlite3.OperationalError("forced commit failure")
        return self._conn.__exit__(exc_type, exc_value, traceback)

    def close(self) -> None:
        self._conn.close()


@pytest.mark.parametrize("mutation", ["reset", "delete", "purge"])
def test_cleanup_success_audit_is_not_emitted_when_commit_fails(
    monkeypatch,
    tmp_path,
    mutation,
):
    store = SqliteSessionStore(state_dir=tmp_path)
    principal = _principal(f"failed-{mutation}-browser")
    session = store.get_or_create(principal)
    sink = CapturingAuditSink()
    set_audit_sink_for_testing(sink)
    real_connect = store._connect
    monkeypatch.setattr(
        store,
        "_connect",
        lambda: _CommitFailingConnection(real_connect()),
    )

    with pytest.raises(sqlite3.OperationalError, match="forced commit failure"):
        if mutation == "reset":
            store.reset(session.session_id or "")
        elif mutation == "delete":
            store.delete_project(principal, _active_project_id(session.session_id or ""))
        else:
            store.purge_expired_sessions(now_iso=_future_now_iso())

    assert sink.events == []


def test_delete_last_project_removes_workspace_including_managed_artifacts(tmp_path):
    sink = CapturingAuditSink()
    set_audit_sink_for_testing(sink)
    store = SqliteSessionStore(state_dir=tmp_path)
    principal = _principal("delete-browser")
    session = store.get_or_create(principal)
    workspace = Path(session.workspace_root or "")
    durable = workspace / DURABLE_SUBDIR
    durable.mkdir()
    (durable / "baseline.json").write_text("durable", encoding="utf-8")

    store.delete_project(principal, _active_project_id("delete-browser"))

    assert not workspace.exists()
    assert store.list_projects(principal) == []
    assert [(event.event_type, event.project_id, event.outcome) for event in sink.events] == [
        ("project.delete.cleanup", _active_project_id("delete-browser"), "success")
    ]


def test_delete_project_keeps_workspace_when_other_projects_remain(tmp_path):
    store = SqliteSessionStore(state_dir=tmp_path)
    principal = _principal("multi-project-browser")
    session = store.get_or_create(principal)
    workspace = Path(session.workspace_root or "")
    (workspace / "shared.txt").write_text("keep", encoding="utf-8")
    store.save_project(principal, session, project_id="extra-project")

    store.delete_project(principal, "extra-project")

    assert workspace.exists()
    assert (workspace / "shared.txt").exists()
    assert store.get_project(principal, _active_project_id("multi-project-browser")) is not None


def test_retention_path_safety_rejects_targets_outside_workspace_base(tmp_path):
    base = tmp_path / "workspaces"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(ValueError, match="outside the workspace base"):
        remove_workspace_preserving_durable(outside, workspaces_base=base)
    with pytest.raises(ValueError, match="outside the workspace base"):
        remove_workspace_fully(outside, workspaces_base=base)


def test_lazy_sweeper_runs_at_most_once_per_minute(monkeypatch):
    class FakeStore:
        def __init__(self) -> None:
            self.purge_count = 0

        def purge_expired_sessions(self, *, now_iso: str | None = None) -> int:
            self.purge_count += 1
            return 0

        def get_or_create(self, principal: Principal) -> ProjectSession:
            session = ProjectSession(session_id=f"session-{self.purge_count}")
            return session

    store = FakeStore()
    principal = _principal("sweeper-browser")
    times = iter([100.0, 120.0, 161.0])
    monkeypatch.setattr("app.services.session_context.time.monotonic", lambda: next(times))
    _reset_retention_sweeper_for_testing()

    get_current_session(_request(principal, store))
    get_current_session(_request(principal, store))
    get_current_session(_request(principal, store))

    assert store.purge_count == 2


def test_purge_path_does_not_start_ks_when_ka_off(monkeypatch, tmp_path):
    def fail_start(self):  # pragma: no cover - failure path
        raise AssertionError("Retention purge must not start KS")

    monkeypatch.setattr(KSClient, "start", fail_start)
    store = SqliteSessionStore(state_dir=tmp_path)
    principal = _principal("ka-off-browser")
    store.get_or_create(principal)

    assert store.purge_expired_sessions(now_iso=_future_now_iso()) == 1
