"""Durable, minimal audit events for Studio ownership and high-risk actions."""

from __future__ import annotations

import errno
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Protocol

from starlette.requests import Request

from app.models.project import ProjectSession
from app.services.identity import Principal, get_current_principal
from app.services.settings import StudioSettings, StudioSettingsError, get_studio_settings

AuditOutcome = Literal["success", "denied", "blocked"]

logger = logging.getLogger(__name__)

_AUDIT_BUSY_TIMEOUT_MS = 2_000
_AUDIT_CLEANUP_INTERVAL_SECONDS = 60 * 60
_AUDIT_WARNING_INTERVAL_SECONDS = 60
_AUDIT_ERROR_KINDS = {
    "database_locked",
    "storage_full",
    "permission_denied",
    "io_error",
    "invalid_storage",
    "unknown",
}

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS audit_events (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type   TEXT NOT NULL,
  principal_id TEXT NOT NULL,
  session_id   TEXT NOT NULL,
  project_id   TEXT,
  outcome      TEXT NOT NULL CHECK (outcome IN ('success','denied','blocked')),
  timestamp    TEXT NOT NULL,
  recorded_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_recorded_at
  ON audit_events (recorded_at);
CREATE INDEX IF NOT EXISTS idx_audit_principal_time
  ON audit_events (principal_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_audit_event_type_time
  ON audit_events (event_type, recorded_at);
"""

_RETENTION_SQL = """
DELETE FROM audit_events
WHERE id IN (
  SELECT id FROM audit_events
  WHERE recorded_at < :cutoff
  ORDER BY recorded_at
  LIMIT 5000
)
"""


@dataclass(frozen=True)
class AuditEvent:
    event_type: str
    principal_id: str
    session_id: str
    project_id: str | None
    timestamp: str
    outcome: AuditOutcome


class AuditSink(Protocol):
    def emit(self, event: AuditEvent) -> None:
        """Emit one audit event without raising to the caller."""


class NoOpAuditSink:
    def emit(self, event: AuditEvent) -> None:
        return None


class _AuditProcessHealth:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._mode = "noop"
        self._healthy = True
        self._failed_events = 0
        self._last_error_at: str | None = None
        self._last_error_kind: str | None = None
        self._last_warning_by_kind: dict[str, float] = {}

    def configure(self, mode: str) -> None:
        with self._lock:
            self._mode = mode
            self._healthy = True
            self._failed_events = 0
            self._last_error_at = None
            self._last_error_kind = None
            self._last_warning_by_kind.clear()

    def record_failure(self, kind: str) -> bool:
        if kind not in _AUDIT_ERROR_KINDS:
            kind = "unknown"
        now_monotonic = time.monotonic()
        with self._lock:
            self._healthy = False
            self._failed_events += 1
            self._last_error_at = _utc_now_iso()
            self._last_error_kind = kind
            last_warning = self._last_warning_by_kind.get(kind)
            should_warn = (
                last_warning is None
                or now_monotonic - last_warning >= _AUDIT_WARNING_INTERVAL_SECONDS
            )
            if should_warn:
                self._last_warning_by_kind[kind] = now_monotonic
            return should_warn

    def record_success(self) -> None:
        with self._lock:
            self._healthy = True
            self._last_error_kind = None

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "mode": self._mode,
                "healthy": self._healthy,
                "failed_events": self._failed_events,
                "last_error_at": self._last_error_at,
                "last_error_kind": self._last_error_kind,
            }


class SQLiteAuditSink:
    """Persist each event with an audit-only, short-lived SQLite connection."""

    def __init__(self, *, db_path: Path, retention_days: int) -> None:
        self.db_path = db_path
        self.retention_days = retention_days
        self._cleanup_lock = threading.RLock()
        self._last_cleanup_attempt_monotonic: float | None = None
        self._cleanup_healthy = True

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=_AUDIT_BUSY_TIMEOUT_MS / 1_000)
        try:
            self._configure_connection(conn)
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(_SCHEMA_SQL)
            self._verify_schema(conn)
            probe_time = _utc_now_iso()
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO audit_events(
                      event_type, principal_id, session_id, project_id,
                      outcome, timestamp, recorded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "__startup_probe__",
                        "startup",
                        "startup",
                        None,
                        "success",
                        probe_time,
                        probe_time,
                    ),
                )
                conn.execute("DELETE FROM audit_events WHERE id = ?", (cursor.lastrowid,))
        finally:
            conn.close()

        self._delete_expired_rows()
        with self._cleanup_lock:
            self._last_cleanup_attempt_monotonic = time.monotonic()

    def emit(self, event: AuditEvent) -> None:
        try:
            self._insert_event(event)
        except Exception as exc:  # Audit remains best-effort after the mutation.
            _record_runtime_failure(exc)
            return

        if self._run_scheduled_cleanup():
            _AUDIT_HEALTH.record_success()

    def _insert_event(self, event: AuditEvent) -> None:
        conn = self._runtime_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO audit_events(
                      event_type, principal_id, session_id, project_id,
                      outcome, timestamp, recorded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_type,
                        event.principal_id,
                        event.session_id,
                        event.project_id,
                        event.outcome,
                        event.timestamp,
                        _utc_now_iso(),
                    ),
                )
        finally:
            conn.close()

    def _run_scheduled_cleanup(self) -> bool:
        now = time.monotonic()
        with self._cleanup_lock:
            if (
                self._last_cleanup_attempt_monotonic is not None
                and now - self._last_cleanup_attempt_monotonic
                < _AUDIT_CLEANUP_INTERVAL_SECONDS
            ):
                return self._cleanup_healthy
            # Claim the interval before attempting cleanup so failures do not retry
            # on every request.
            self._last_cleanup_attempt_monotonic = now

        try:
            self._delete_expired_rows()
        except Exception as exc:
            with self._cleanup_lock:
                self._cleanup_healthy = False
            _record_runtime_failure(exc)
            return False
        with self._cleanup_lock:
            self._cleanup_healthy = True
        return True

    def _delete_expired_rows(self) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.retention_days)).isoformat()
        conn = self._runtime_connection()
        try:
            with conn:
                cursor = conn.execute(_RETENTION_SQL, {"cutoff": cutoff})
                return max(cursor.rowcount, 0)
        finally:
            conn.close()

    def _runtime_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=_AUDIT_BUSY_TIMEOUT_MS / 1_000)
        try:
            self._configure_connection(conn)
        except Exception:
            conn.close()
            raise
        return conn

    @staticmethod
    def _configure_connection(conn: sqlite3.Connection) -> None:
        conn.execute(f"PRAGMA busy_timeout = {_AUDIT_BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA synchronous = NORMAL")

    @staticmethod
    def _verify_schema(conn: sqlite3.Connection) -> None:
        expected_columns = [
            "id",
            "event_type",
            "principal_id",
            "session_id",
            "project_id",
            "outcome",
            "timestamp",
            "recorded_at",
        ]
        columns = [str(row[1]) for row in conn.execute("PRAGMA table_info(audit_events)")]
        if columns != expected_columns:
            raise RuntimeError("Audit schema does not match the required version.")
        indexes = {
            str(row[1]) for row in conn.execute("PRAGMA index_list(audit_events)")
        }
        expected_indexes = {
            "idx_audit_recorded_at",
            "idx_audit_principal_time",
            "idx_audit_event_type_time",
        }
        if not expected_indexes.issubset(indexes):
            raise RuntimeError("Audit indexes do not match the required version.")


_NOOP_SINK = NoOpAuditSink()
_TEST_SINK: AuditSink | None = None
_AUDIT_HEALTH = _AuditProcessHealth()
_ACTIVE_SINK: AuditSink = _NOOP_SINK
_ACTIVE_CONFIG: tuple[str, str, int] | None = None
_ACTIVE_SINK_LOCK = threading.RLock()


def set_audit_sink_for_testing(sink: AuditSink | None) -> None:
    """Install a process-local sink override for tests."""

    global _TEST_SINK
    _TEST_SINK = sink


def initialize_audit(settings: StudioSettings | None = None) -> None:
    """Initialize configured audit storage before the application serves requests."""

    global _ACTIVE_CONFIG, _ACTIVE_SINK
    settings = settings or get_studio_settings()
    if settings.audit_sink == "noop":
        with _ACTIVE_SINK_LOCK:
            _ACTIVE_SINK = _NOOP_SINK
            _ACTIVE_CONFIG = _settings_key(settings)
        _AUDIT_HEALTH.configure("noop")
        return

    sink = SQLiteAuditSink(
        db_path=settings.audit_db_path,
        retention_days=settings.audit_retention_days,
    )
    try:
        sink.initialize()
    except Exception:
        raise StudioSettingsError(
            "Studio could not initialize the configured SQLite audit store."
        ) from None
    with _ACTIVE_SINK_LOCK:
        _ACTIVE_SINK = sink
        _ACTIVE_CONFIG = _settings_key(settings)
    _AUDIT_HEALTH.configure("sqlite")


def get_audit_health_snapshot() -> dict[str, object]:
    """Return the sanitized live process state used by request rendering."""

    return _AUDIT_HEALTH.snapshot()


def get_audit_sink(settings: StudioSettings | None = None) -> AuditSink:
    if _TEST_SINK is not None:
        return _TEST_SINK

    settings = settings or get_studio_settings()
    if settings.audit_sink == "noop":
        return _NOOP_SINK
    with _ACTIVE_SINK_LOCK:
        if _ACTIVE_CONFIG == _settings_key(settings):
            return _ACTIVE_SINK
    # Production initializes the matching sink in application lifespan. Keeping
    # this no-op avoids creating storage from tests or code that bypasses startup.
    return _NOOP_SINK


def audit(
    request: Request,
    event_type: str,
    *,
    outcome: AuditOutcome,
    project_id: str | None = None,
) -> None:
    """Build and emit a minimal event without changing user-visible behavior."""

    try:
        principal = _principal_from_request(request)
        session = getattr(request.state, "studio_session", None)
        emit_audit_event(
            event_type,
            principal_id=principal.user_id,
            session_id=_session_id(session),
            project_id=project_id if project_id is not None else _project_id(session),
            outcome=outcome,
        )
    except Exception as exc:  # Defensive: audit must not change route results.
        _record_runtime_failure(exc)


def emit_audit_event(
    event_type: str,
    *,
    principal_id: str,
    session_id: str,
    outcome: AuditOutcome,
    project_id: str | None = None,
) -> None:
    """Emit an audit event when no request context is available."""

    try:
        event = AuditEvent(
            event_type=event_type,
            principal_id=principal_id,
            session_id=session_id,
            project_id=project_id,
            timestamp=_utc_now_iso(),
            outcome=outcome,
        )
        get_audit_sink().emit(event)
    except Exception as exc:  # Test/custom sinks may still raise.
        _record_runtime_failure(exc)


def _settings_key(settings: StudioSettings) -> tuple[str, str, int]:
    return (
        settings.audit_sink,
        str(settings.audit_db_path.expanduser().resolve(strict=False)),
        settings.audit_retention_days,
    )


def _record_runtime_failure(exc: BaseException) -> None:
    kind = _classify_audit_error(exc)
    if _AUDIT_HEALTH.record_failure(kind):
        logger.warning("Studio audit persistence degraded (error_kind=%s).", kind)


def _classify_audit_error(exc: BaseException) -> str:
    if isinstance(exc, PermissionError):
        return "permission_denied"
    if isinstance(exc, OSError):
        if exc.errno in {errno.EACCES, errno.EPERM, errno.EROFS}:
            return "permission_denied"
        if exc.errno == errno.ENOSPC:
            return "storage_full"
        if exc.errno == errno.EIO:
            return "io_error"
    sqlite_code = getattr(exc, "sqlite_errorcode", None)
    if isinstance(sqlite_code, int):
        primary_code = sqlite_code & 0xFF
        if primary_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
            return "database_locked"
        if primary_code == sqlite3.SQLITE_FULL:
            return "storage_full"
        if primary_code in {sqlite3.SQLITE_READONLY, sqlite3.SQLITE_CANTOPEN}:
            return "permission_denied"
        if primary_code == sqlite3.SQLITE_IOERR:
            return "io_error"
        if primary_code in {
            sqlite3.SQLITE_CORRUPT,
            sqlite3.SQLITE_NOTADB,
            sqlite3.SQLITE_SCHEMA,
            sqlite3.SQLITE_CONSTRAINT,
        }:
            return "invalid_storage"
    return "unknown"


def _reset_audit_runtime_for_testing() -> None:
    global _ACTIVE_CONFIG, _ACTIVE_SINK, _TEST_SINK
    with _ACTIVE_SINK_LOCK:
        _ACTIVE_SINK = _NOOP_SINK
        _ACTIVE_CONFIG = None
    _TEST_SINK = None
    _AUDIT_HEALTH.configure("noop")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _principal_from_request(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if isinstance(principal, Principal):
        return principal
    return get_current_principal(request)


def _session_id(session: object) -> str:
    if isinstance(session, ProjectSession):
        return str(session.session_id or "")
    return ""


def _project_id(session: object) -> str | None:
    if not isinstance(session, ProjectSession):
        return None
    return session.project_id or session.ks_project_id
