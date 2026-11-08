from __future__ import annotations

import csv
import io
import json
import logging
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.audit import (
    AuditEvent,
    SQLiteAuditSink,
    _classify_audit_error,
    _record_runtime_failure,
    _reset_audit_runtime_for_testing,
    emit_audit_event,
    get_audit_health_snapshot,
    get_audit_sink,
    initialize_audit,
    set_audit_sink_for_testing,
)
from app.services.settings import StudioSettingsError, get_studio_settings
from app.tools.audit_export import AUDIT_COLUMNS, audit_database_status, export_audit_csv, main
from tests.session_helpers import get_session, reset_session, save_session
from tests.test_package_writer import _full_session

DISCLOSURE = (
    "Use synthetic or approved content only. Studio does not sanitize uploaded or "
    "pasted content. Depending on the workflow, it may be retained in project state, "
    "Knowledge Workspace storage, and exported packages."
)


@pytest.fixture(autouse=True)
def reset_audit_runtime(monkeypatch):
    _reset_audit_runtime_for_testing()
    for name in (
        "EDGEFORGE_STUDIO_AUDIT_SINK",
        "EDGEFORGE_STUDIO_AUDIT_DB_PATH",
        "EDGEFORGE_STUDIO_AUDIT_RETENTION_DAYS",
    ):
        monkeypatch.delenv(name, raising=False)
    yield
    _reset_audit_runtime_for_testing()


def _shared_mode(monkeypatch) -> None:
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")


def _event(number: int = 1) -> AuditEvent:
    return AuditEvent(
        event_type=f"project.save.{number}",
        principal_id=f"anonymous:principal-{number}",
        session_id=f"session-{number}",
        project_id=f"project-{number}",
        timestamp=datetime.now(timezone.utc).isoformat(),
        outcome="success",
    )


def _csrf_from_html(html: str) -> str:
    match = re.search(r'name="edgeforge-csrf-token"\s+content="([^"]+)"', html)
    assert match
    return match.group(1)


def _sqlite_error(code: int) -> sqlite3.OperationalError:
    error = sqlite3.OperationalError("sensitive path and SQL must not be logged")
    error.sqlite_errorcode = code
    return error


def test_shared_startup_creates_exact_schema_indexes_and_removes_probe(monkeypatch) -> None:
    _shared_mode(monkeypatch)
    settings = get_studio_settings()

    with TestClient(app, base_url="https://testserver"):
        pass

    assert settings.audit_db_path.name == "studio-audit.sqlite3"
    assert settings.audit_db_path.name != "studio-sessions.sqlite3"
    conn = sqlite3.connect(settings.audit_db_path)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(audit_events)")]
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(audit_events)")}
        count = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()

    assert columns == list(AUDIT_COLUMNS)
    assert indexes == {
        "idx_audit_recorded_at",
        "idx_audit_principal_time",
        "idx_audit_event_type_time",
    }
    assert count == 0
    assert journal_mode == "wal"


def test_local_noop_startup_does_not_create_audit_storage(monkeypatch, tmp_path) -> None:
    audit_path = tmp_path / "audit-only" / "studio-audit.sqlite3"
    monkeypatch.setenv("EDGEFORGE_STUDIO_AUDIT_SINK", "noop")
    monkeypatch.setenv("EDGEFORGE_STUDIO_AUDIT_DB_PATH", str(audit_path))

    with TestClient(app):
        pass

    assert not audit_path.exists()
    assert not audit_path.parent.exists()
    assert get_audit_health_snapshot()["mode"] == "noop"


def test_shared_startup_refuses_unwritable_storage_shape(monkeypatch, tmp_path) -> None:
    _shared_mode(monkeypatch)
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("block", encoding="utf-8")
    monkeypatch.setenv(
        "EDGEFORGE_STUDIO_AUDIT_DB_PATH",
        str(blocker / "studio-audit.sqlite3"),
    )

    with pytest.raises(StudioSettingsError, match="could not initialize"):
        with TestClient(app, base_url="https://testserver"):
            pass


def test_shared_startup_refuses_an_incompatible_existing_schema(monkeypatch, tmp_path) -> None:
    _shared_mode(monkeypatch)
    db_path = tmp_path / "incompatible-audit.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE audit_events (id INTEGER PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setenv("EDGEFORGE_STUDIO_AUDIT_DB_PATH", str(db_path))

    with pytest.raises(StudioSettingsError, match="could not initialize"):
        with TestClient(app, base_url="https://testserver"):
            pass


def test_shared_startup_refuses_session_database_as_audit_store(monkeypatch, tmp_path) -> None:
    _shared_mode(monkeypatch)
    monkeypatch.setenv("EDGEFORGE_STUDIO_STATE_DIR", str(tmp_path))
    monkeypatch.setenv(
        "EDGEFORGE_STUDIO_AUDIT_DB_PATH",
        str(tmp_path / "studio-sessions.sqlite3"),
    )

    with pytest.raises(StudioSettingsError, match="must not refer to the Studio session"):
        with TestClient(app, base_url="https://testserver"):
            pass


def test_sqlite_sink_persists_only_locked_event_fields_plus_recorded_at(monkeypatch) -> None:
    _shared_mode(monkeypatch)
    settings = get_studio_settings()
    initialize_audit(settings)
    event = _event()

    get_audit_sink().emit(event)

    conn = sqlite3.connect(settings.audit_db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM audit_events").fetchone()
    finally:
        conn.close()
    assert tuple(row.keys()) == AUDIT_COLUMNS
    assert {
        "event_type": row["event_type"],
        "principal_id": row["principal_id"],
        "session_id": row["session_id"],
        "project_id": row["project_id"],
        "outcome": row["outcome"],
        "timestamp": row["timestamp"],
    } == {
        "event_type": event.event_type,
        "principal_id": event.principal_id,
        "session_id": event.session_id,
        "project_id": event.project_id,
        "outcome": event.outcome,
        "timestamp": event.timestamp,
    }
    assert datetime.fromisoformat(row["recorded_at"]).tzinfo is not None


def test_concurrent_audit_writes_use_independent_connections(monkeypatch) -> None:
    _shared_mode(monkeypatch)
    settings = get_studio_settings()
    initialize_audit(settings)

    threads = [
        threading.Thread(
            target=emit_audit_event,
            kwargs={
                "event_type": "project.save",
                "principal_id": f"anonymous:{index}",
                "session_id": f"session-{index}",
                "project_id": f"project-{index}",
                "outcome": "success",
            },
        )
        for index in range(30)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    conn = sqlite3.connect(settings.audit_db_path)
    try:
        rows = conn.execute(
            "SELECT principal_id, session_id FROM audit_events ORDER BY principal_id"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 30
    assert get_audit_health_snapshot()["healthy"] is True


def test_runtime_failure_is_sanitized_rate_limited_and_recovers(
    monkeypatch,
    caplog,
) -> None:
    _shared_mode(monkeypatch)
    initialize_audit(get_studio_settings())
    sink = get_audit_sink()
    assert isinstance(sink, SQLiteAuditSink)
    original_insert = sink._insert_event

    caplog.set_level(logging.WARNING, logger="app.services.audit")
    monkeypatch.setattr(
        sink,
        "_insert_event",
        lambda _event: (_ for _ in ()).throw(_sqlite_error(sqlite3.SQLITE_FULL)),
    )
    sink.emit(_event(1))
    sink.emit(_event(2))

    degraded = get_audit_health_snapshot()
    assert degraded["healthy"] is False
    assert degraded["failed_events"] == 2
    assert degraded["last_error_kind"] == "storage_full"
    assert degraded["last_error_at"] is not None
    assert caplog.text.count("error_kind=storage_full") == 1
    assert "sensitive path" not in caplog.text

    monkeypatch.setattr(sink, "_insert_event", original_insert)
    sink.emit(_event(3))

    recovered = get_audit_health_snapshot()
    assert recovered["healthy"] is True
    assert recovered["failed_events"] == 2
    assert recovered["last_error_at"] == degraded["last_error_at"]
    assert recovered["last_error_kind"] is None


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (PermissionError("secret"), "permission_denied"),
        (_sqlite_error(sqlite3.SQLITE_BUSY), "database_locked"),
        (_sqlite_error(sqlite3.SQLITE_FULL), "storage_full"),
        (_sqlite_error(sqlite3.SQLITE_IOERR), "io_error"),
        (_sqlite_error(sqlite3.SQLITE_CORRUPT), "invalid_storage"),
        (RuntimeError("secret"), "unknown"),
    ],
)
def test_error_classifier_is_closed_and_message_independent(error, kind) -> None:
    assert _classify_audit_error(error) == kind


def test_lock_timeout_is_bounded_and_degrades_without_raising(monkeypatch) -> None:
    _shared_mode(monkeypatch)
    settings = get_studio_settings()
    initialize_audit(settings)
    sink = get_audit_sink()
    assert isinstance(sink, SQLiteAuditSink)
    locker = sqlite3.connect(settings.audit_db_path)
    try:
        locker.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        sink.emit(_event())
        elapsed = time.monotonic() - started
    finally:
        locker.rollback()
        locker.close()

    assert 1.5 <= elapsed < 4
    health = get_audit_health_snapshot()
    assert health["healthy"] is False
    assert health["last_error_kind"] == "database_locked"


def test_retention_deletes_at_most_5000_rows_using_recorded_at(monkeypatch) -> None:
    _shared_mode(monkeypatch)
    settings = get_studio_settings()
    initialize_audit(settings)
    sink = get_audit_sink()
    assert isinstance(sink, SQLiteAuditSink)
    old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
    fresh = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(settings.audit_db_path)
    try:
        conn.executemany(
            """
            INSERT INTO audit_events(
              event_type, principal_id, session_id, project_id,
              outcome, timestamp, recorded_at
            ) VALUES ('project.save', 'p', 's', NULL, 'success', ?, ?)
            """,
            [(fresh, old)] * 5001 + [(old, fresh)],
        )
        conn.commit()
    finally:
        conn.close()

    sink._last_cleanup_attempt_monotonic = None
    sink.emit(_event())

    conn = sqlite3.connect(settings.audit_db_path)
    try:
        old_count = conn.execute(
            "SELECT COUNT(*) FROM audit_events WHERE recorded_at = ?", (old,)
        ).fetchone()[0]
        fresh_count = conn.execute(
            "SELECT COUNT(*) FROM audit_events WHERE recorded_at >= ?", (fresh,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert old_count == 1
    assert fresh_count == 2


def test_failed_cleanup_is_not_retried_on_each_write(monkeypatch) -> None:
    _shared_mode(monkeypatch)
    initialize_audit(get_studio_settings())
    sink = get_audit_sink()
    assert isinstance(sink, SQLiteAuditSink)
    attempts = 0

    def fail_cleanup() -> int:
        nonlocal attempts
        attempts += 1
        raise _sqlite_error(sqlite3.SQLITE_IOERR)

    monkeypatch.setattr(sink, "_delete_expired_rows", fail_cleanup)
    sink._last_cleanup_attempt_monotonic = None
    sink.emit(_event(1))
    degraded = get_audit_health_snapshot()
    sink.emit(_event(2))
    still_degraded = get_audit_health_snapshot()

    assert attempts == 1
    assert degraded["healthy"] is False
    assert still_degraded["healthy"] is False
    assert still_degraded["failed_events"] == degraded["failed_events"]
    assert still_degraded["last_error_kind"] == "io_error"

    monkeypatch.setattr(sink, "_delete_expired_rows", lambda: 0)
    sink._last_cleanup_attempt_monotonic = None
    sink.emit(_event(3))

    recovered = get_audit_health_snapshot()
    assert recovered["healthy"] is True
    assert recovered["failed_events"] == degraded["failed_events"]
    assert recovered["last_error_kind"] is None


def test_audit_failure_after_export_write_does_not_change_success(monkeypatch, tmp_path) -> None:
    class FailingSink:
        def emit(self, _event) -> None:
            raise PermissionError("/secret/audit.sqlite3")

    reset_session()
    session = _full_session()
    session.output_path = str(tmp_path)
    save_session(session)
    set_audit_sink_for_testing(FailingSink())

    response = TestClient(app).post("/export/write")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert (Path(response.json()["output_dir"]) / "app-definition.yaml").exists()


def test_shared_banner_appears_on_next_request_and_clears_after_recovery(monkeypatch) -> None:
    _shared_mode(monkeypatch)
    with TestClient(app, base_url="https://testserver") as client:
        initial = client.get("/")
        assert "data-audit-health-banner" not in initial.text
        sink = get_audit_sink()
        assert isinstance(sink, SQLiteAuditSink)
        original_insert = sink._insert_event
        monkeypatch.setattr(
            sink,
            "_insert_event",
            lambda _event: (_ for _ in ()).throw(PermissionError("/secret/path")),
        )
        response_n = client.post(
            "/project/open",
            data={"_edgeforge_csrf_token": _csrf_from_html(initial.text)},
            files={"project_file": ("invalid.json", b"{", "application/json")},
        )
        assert response_n.status_code == 400
        assert "data-audit-health-banner" not in response_n.text

        response_n_plus_one = client.get("/")
        assert "data-audit-health-banner" in response_n_plus_one.text
        assert "/secret/path" not in response_n_plus_one.text

        monkeypatch.setattr(sink, "_insert_event", original_insert)
        sink.emit(_event())
        recovered = client.get("/")
        assert "data-audit-health-banner" not in recovered.text


def test_local_mode_never_renders_degraded_banner(monkeypatch) -> None:
    monkeypatch.setenv("EDGEFORGE_STUDIO_AUDIT_SINK", "noop")
    with TestClient(app) as client:
        _record_runtime_failure(RuntimeError("secret"))
        response = client.get("/")

    assert get_audit_health_snapshot()["healthy"] is False
    assert "data-audit-health-banner" not in response.text


def test_no_browser_audit_or_health_api_is_added() -> None:
    client = TestClient(app)
    for path in ("/health", "/status", "/audit", "/audit/status"):
        assert client.get(path).status_code == 404


def test_cli_status_and_export_are_read_only_and_deterministic(monkeypatch, tmp_path) -> None:
    _shared_mode(monkeypatch)
    settings = get_studio_settings()
    initialize_audit(settings)
    sink = get_audit_sink()
    assert isinstance(sink, SQLiteAuditSink)
    sink.emit(_event(2))
    sink.emit(_event(1))

    status = audit_database_status(settings)
    assert set(status) == {
        "mode",
        "db_path",
        "db_reachable",
        "row_count",
        "oldest_recorded_at",
        "newest_recorded_at",
    }
    assert status["mode"] == "sqlite"
    assert status["db_reachable"] is True
    assert status["row_count"] == 2
    assert "healthy" not in status
    assert "failed_events" not in status

    csv_path = tmp_path / "audit.csv"
    count = export_audit_csv(
        settings,
        since="2000-01-01T00:00:00Z",
        out_path=csv_path,
    )
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert count == 2
    assert tuple(rows[0]) == AUDIT_COLUMNS
    assert [(row["recorded_at"], row["id"]) for row in rows] == sorted(
        (row["recorded_at"], row["id"]) for row in rows
    )

    output = io.StringIO()
    assert main(["--status"], stdout=output) == 0
    assert json.loads(output.getvalue())["row_count"] == 2


def test_cli_missing_database_does_not_create_it(monkeypatch, tmp_path) -> None:
    missing = tmp_path / "missing" / "audit.sqlite3"
    monkeypatch.setenv("EDGEFORGE_STUDIO_AUDIT_DB_PATH", str(missing))

    output = io.StringIO()
    exit_code = main(["--status"], stdout=output)

    assert exit_code == 1
    assert json.loads(output.getvalue())["db_reachable"] is False
    assert not missing.exists()
    assert not missing.parent.exists()


def test_cli_export_refuses_database_aliases_and_sqlite_sidecars(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    _shared_mode(monkeypatch)
    settings = get_studio_settings()
    initialize_audit(settings)
    sink = get_audit_sink()
    assert isinstance(sink, SQLiteAuditSink)
    sink.emit(_event())

    conn = sqlite3.connect(settings.audit_db_path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    finally:
        conn.close()
    before = settings.audit_db_path.read_bytes()
    symlink_alias = tmp_path / "audit-symlink.sqlite3"
    symlink_alias.symlink_to(settings.audit_db_path)
    hardlink_alias = tmp_path / "audit-hardlink.sqlite3"
    hardlink_alias.hardlink_to(settings.audit_db_path)
    destinations = (
        settings.audit_db_path,
        symlink_alias,
        hardlink_alias,
        Path(f"{settings.audit_db_path}-wal"),
        Path(f"{settings.audit_db_path}-shm"),
        Path(f"{settings.audit_db_path}-journal"),
    )

    for destination in destinations:
        with pytest.raises(ValueError, match="must not refer to the audit database"):
            export_audit_csv(
                settings,
                since="2000-01-01T00:00:00Z",
                out_path=destination,
            )
        assert settings.audit_db_path.read_bytes() == before
        conn = sqlite3.connect(settings.audit_db_path)
        try:
            assert conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 1
        finally:
            conn.close()

    assert (
        main(
            [
                "--since",
                "2000-01-01T00:00:00Z",
                "--out",
                str(settings.audit_db_path),
            ]
        )
        == 2
    )
    assert "must not refer to the audit database" in capsys.readouterr().err


def test_cli_export_neutralizes_spreadsheet_formulas_without_mutating_database(
    monkeypatch,
    tmp_path,
) -> None:
    _shared_mode(monkeypatch)
    settings = get_studio_settings()
    initialize_audit(settings)
    sink = get_audit_sink()
    assert isinstance(sink, SQLiteAuditSink)
    hostile_values = (
        '=HYPERLINK("https://attacker.invalid","open")',
        "+1+1",
        "-2+3",
        "@SUM(1,1)",
        "  =1+1",
        "\t+1+1",
        "\r-1+1",
        "\n@SUM(1,1)",
        "\x00=1+1",
        "\ufeff=1+1",
    )
    for index, project_id in enumerate(hostile_values, start=1):
        sink.emit(
            AuditEvent(
                event_type=f"=event-{index}",
                principal_id=f" +principal-{index}",
                session_id=f"\t-session-{index}",
                project_id=project_id,
                outcome="success",
                timestamp=f"@timestamp-{index}",
            )
        )

    csv_path = tmp_path / "formula-safe-audit.csv"
    assert (
        export_audit_csv(
            settings,
            since="2000-01-01T00:00:00Z",
            out_path=csv_path,
        )
        == len(hostile_values)
    )

    with csv_path.open(newline="", encoding="utf-8") as handle:
        exported = list(csv.DictReader(handle))
    assert [row["event_type"] for row in exported] == [
        f"'=event-{index}" for index in range(1, len(hostile_values) + 1)
    ]
    assert [row["principal_id"] for row in exported] == [
        f"' +principal-{index}" for index in range(1, len(hostile_values) + 1)
    ]
    assert [row["session_id"] for row in exported] == [
        f"'\t-session-{index}" for index in range(1, len(hostile_values) + 1)
    ]
    assert [row["project_id"] for row in exported] == [
        f"'{value}" for value in hostile_values
    ]
    assert [row["timestamp"] for row in exported] == [
        f"'@timestamp-{index}" for index in range(1, len(hostile_values) + 1)
    ]

    conn = sqlite3.connect(settings.audit_db_path)
    try:
        stored = conn.execute(
            """
            SELECT event_type, principal_id, session_id, project_id, timestamp
            FROM audit_events
            ORDER BY id
            """
        ).fetchall()
    finally:
        conn.close()
    assert stored == [
        (
            f"=event-{index}",
            f" +principal-{index}",
            f"\t-session-{index}",
            project_id,
            f"@timestamp-{index}",
        )
        for index, project_id in enumerate(hostile_values, start=1)
    ]


def test_disclosures_render_at_project_open_step2_and_knowledge_upload(monkeypatch) -> None:
    client = TestClient(app)
    assert DISCLOSURE in client.get("/").text
    assert client.get("/upstream").text.count(DISCLOSURE) >= 2

    class FakeClient:
        def list_documents(self, project_id: str):
            return {"documents": [], "warnings": []}

        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {"fields": [], "warnings": []}

    @contextmanager
    def fake_ks_client(**_kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.routes.knowledge.ks_client", fake_ks_client)
    session = get_session()
    session.capabilities.knowledge_assist_enabled = True
    save_session(session)

    knowledge = client.get("/knowledge")
    assert knowledge.status_code == 200
    assert knowledge.text.count(DISCLOSURE) >= 2
