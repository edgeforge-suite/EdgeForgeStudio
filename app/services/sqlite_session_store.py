"""SQLite-backed SessionStore implementation for Studio P2."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models.project import ProjectSession
from app.services.audit import emit_audit_event
from app.services.identity import Principal
from app.services.ks_lifecycle import stop_ks_clients_for_workspace
from app.services.project_file_service import (
    deserialize_project,
    restore_session,
)
from app.services.quotas import QuotaExceededError
from app.services.retention import (
    clean_workspace_contents_preserving_durable,
    has_durable_artifacts,
    remove_workspace_fully,
    remove_workspace_preserving_durable,
)
from app.services.session_context import ProjectCatalogEntry
from app.services.settings import get_studio_settings

ACTIVE_PROJECT_SUFFIX = "active"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _session_id_for_principal(principal: Principal) -> str:
    anonymous_id = str(principal.claims.get("anonymous_session_id") or "").strip()
    if anonymous_id:
        return anonymous_id
    return uuid.uuid4().hex


def _project_name(session: ProjectSession) -> str:
    return session.app_name or session.bounded_context or "Untitled project"


class SqliteSessionStore:
    """SQLite-backed session/project catalog with one active project per session."""

    def __init__(self, *, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir)
        self.db_path = self.state_dir / "studio-sessions.sqlite3"
        self.workspace_root_dir = self.state_dir / "workspaces"
        self._lock = threading.RLock()
        self._ensure_schema()

    def get_or_create(self, principal: Principal) -> ProjectSession:
        with self._lock, closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT session_id, workspace_root FROM sessions WHERE principal_id = ?",
                (principal.user_id,),
            ).fetchone()
            now = _utc_now_iso()
            if row is None:
                session_id = _session_id_for_principal(principal)
                workspace_root = str(self.workspace_root_dir / session_id)
                Path(workspace_root).mkdir(parents=True, exist_ok=True)
                conn.execute(
                    """
                    INSERT INTO sessions(session_id, principal_id, created_at, last_seen_at, workspace_root)
                    VALUES(?, ?, ?, ?, ?)
                    """,
                    (session_id, principal.user_id, now, now, workspace_root),
                )
                session = self._new_session(session_id=session_id, workspace_root=workspace_root)
                self._upsert_active_project(conn, principal=principal, session=session, now=now)
                return session

            session_id = str(row["session_id"])
            workspace_root = str(row["workspace_root"])
            Path(workspace_root).mkdir(parents=True, exist_ok=True)
            conn.execute(
                "UPDATE sessions SET last_seen_at = ? WHERE session_id = ?",
                (now, session_id),
            )
            return self._load_active_project(
                conn,
                principal=principal,
                session_id=session_id,
                workspace_root=workspace_root,
            )

    def load(self, session_id: str) -> ProjectSession:
        with self._lock, closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT principal_id, workspace_root FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown Studio session '{session_id}'.")
            conn.execute(
                "UPDATE sessions SET last_seen_at = ? WHERE session_id = ?",
                (_utc_now_iso(), session_id),
            )
            principal = Principal(user_id=str(row["principal_id"]), source="anonymous")
            return self._load_active_project(
                conn,
                principal=principal,
                session_id=session_id,
                workspace_root=str(row["workspace_root"]),
            )

    def save(self, session: ProjectSession) -> None:
        session_id = session.session_id
        if not session_id:
            raise ValueError("Cannot save a Studio session without session_id metadata.")
        with self._lock, closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT principal_id, workspace_root FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown Studio session '{session_id}'.")
            workspace_root = str(row["workspace_root"])
            session.workspace_root = workspace_root
            principal = Principal(user_id=str(row["principal_id"]), source="anonymous")
            self._upsert_active_project(
                conn,
                principal=principal,
                session=session,
                now=_utc_now_iso(),
            )

    def reset(self, session_id: str) -> ProjectSession:
        with self._lock, closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT principal_id, workspace_root FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown Studio session '{session_id}'.")
            workspace_root = str(row["workspace_root"])
            principal = Principal(user_id=str(row["principal_id"]), source="anonymous")
            session = self._new_session(session_id=session_id, workspace_root=workspace_root)
            self._upsert_active_project(
                conn,
                principal=principal,
                session=session,
                now=_utc_now_iso(),
            )
            stop_ks_clients_for_workspace(workspace_root)
            clean_workspace_contents_preserving_durable(
                Path(workspace_root),
                workspaces_base=self.workspace_root_dir,
            )
        emit_audit_event(
            "session.reset.cleanup",
            principal_id=principal.user_id,
            session_id=session_id,
            outcome="success",
        )
        return session

    def list_projects(self, principal: Principal) -> list[ProjectCatalogEntry]:
        with self._lock, closing(self._connect()) as conn, conn:
            rows = conn.execute(
                """
                SELECT project_id, principal_id, session_id, name, created_at, updated_at
                FROM projects
                WHERE principal_id = ?
                ORDER BY updated_at DESC, created_at DESC, project_id ASC
                """,
                (principal.user_id,),
            ).fetchall()
            return [self._catalog_entry(row) for row in rows]

    def get_project(self, principal: Principal, project_id: str) -> ProjectSession | None:
        with self._lock, closing(self._connect()) as conn, conn:
            row = conn.execute(
                """
                SELECT p.state_json, p.session_id, s.workspace_root
                FROM projects p
                JOIN sessions s ON s.session_id = p.session_id
                WHERE p.project_id = ? AND p.principal_id = ?
                """,
                (project_id, principal.user_id),
            ).fetchone()
            if row is None:
                return None
            return self._session_from_state(
                state_json=str(row["state_json"]),
                session_id=str(row["session_id"]),
                workspace_root=str(row["workspace_root"]),
            )

    def save_project(
        self,
        principal: Principal,
        session: ProjectSession,
        *,
        project_id: str | None = None,
    ) -> ProjectCatalogEntry:
        if not session.session_id:
            raise ValueError("Cannot save a project without session_id metadata.")
        with self._lock, closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT workspace_root FROM sessions WHERE session_id = ? AND principal_id = ?",
                (session.session_id, principal.user_id),
            ).fetchone()
            if row is None:
                raise KeyError(
                    f"Unknown Studio session '{session.session_id}' for current principal."
                )
            session.workspace_root = str(row["workspace_root"])
            now = _utc_now_iso()
            self._assert_project_id_available_for_principal(
                conn,
                principal=principal,
                project_id=project_id or self._active_project_id(session.session_id),
            )
            self._assert_project_count_within_quota(
                conn,
                principal=principal,
                project_id=project_id or self._active_project_id(session.session_id),
            )
            return self._upsert_project(
                conn,
                principal=principal,
                session=session,
                project_id=project_id or self._active_project_id(session.session_id),
                now=now,
            )

    def delete_project(self, principal: Principal, project_id: str) -> None:
        with self._lock, closing(self._connect()) as conn, conn:
            row = conn.execute(
                """
                SELECT p.session_id, s.workspace_root
                FROM projects p
                JOIN sessions s ON s.session_id = p.session_id
                WHERE p.project_id = ? AND p.principal_id = ?
                """,
                (project_id, principal.user_id),
            ).fetchone()
            conn.execute(
                "DELETE FROM projects WHERE project_id = ? AND principal_id = ?",
                (project_id, principal.user_id),
            )
            if row is None:
                return

            session_id = str(row["session_id"])
            workspace_root = str(row["workspace_root"])
            remaining = conn.execute(
                "SELECT COUNT(*) AS count FROM projects WHERE session_id = ?",
                (session_id,),
            ).fetchone()["count"]
            if int(remaining) > 0:
                # Per-project filesystem sub-area ownership is deferred; the
                # session workspace is shared while any project row remains.
                return

            stop_ks_clients_for_workspace(workspace_root)
            remove_workspace_fully(Path(workspace_root), workspaces_base=self.workspace_root_dir)
        emit_audit_event(
            "project.delete.cleanup",
            principal_id=principal.user_id,
            session_id=session_id,
            project_id=project_id,
            outcome="success",
        )

    def purge_expired_sessions(self, *, now_iso: str | None = None) -> int:
        settings = get_studio_settings()
        now = _parse_iso_datetime(now_iso or _utc_now_iso())
        cutoff = (now - timedelta(seconds=settings.session_idle_ttl_seconds)).isoformat()
        purged = 0
        audit_events: list[tuple[str, str]] = []
        with self._lock, closing(self._connect()) as conn, conn:
            rows = conn.execute(
                """
                SELECT session_id, principal_id, workspace_root
                FROM sessions
                WHERE last_seen_at < ?
                ORDER BY last_seen_at ASC, session_id ASC
                """,
                (cutoff,),
            ).fetchall()
            for row in rows:
                session_id = str(row["session_id"])
                principal_id = str(row["principal_id"])
                workspace_root = str(row["workspace_root"])
                workspace_path = Path(workspace_root)
                stop_ks_clients_for_workspace(workspace_root)
                if has_durable_artifacts(workspace_path):
                    clean_workspace_contents_preserving_durable(
                        workspace_path,
                        workspaces_base=self.workspace_root_dir,
                    )
                    continue
                remove_workspace_preserving_durable(
                    workspace_path,
                    workspaces_base=self.workspace_root_dir,
                )
                conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
                audit_events.append((principal_id, session_id))
                purged += 1
        for principal_id, session_id in audit_events:
            emit_audit_event(
                "session.purge",
                principal_id=principal_id,
                session_id=session_id,
                outcome="success",
            )
        return purged

    def _connect(self) -> sqlite3.Connection:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_root_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _ensure_schema(self) -> None:
        with self._lock, closing(self._connect()) as conn, conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                  session_id TEXT PRIMARY KEY,
                  principal_id TEXT NOT NULL UNIQUE,
                  created_at TEXT NOT NULL,
                  last_seen_at TEXT NOT NULL,
                  workspace_root TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS projects (
                  project_id TEXT PRIMARY KEY,
                  principal_id TEXT NOT NULL,
                  session_id TEXT NOT NULL,
                  name TEXT NOT NULL,
                  state_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_projects_principal_id
                  ON projects(principal_id);
                CREATE INDEX IF NOT EXISTS idx_projects_session_id
                  ON projects(session_id);
                """
            )

    def _new_session(self, *, session_id: str, workspace_root: str) -> ProjectSession:
        session = ProjectSession()
        session.is_brand_new = True
        session.session_id = session_id
        session.workspace_root = workspace_root
        return session

    def _load_active_project(
        self,
        conn: sqlite3.Connection,
        *,
        principal: Principal,
        session_id: str,
        workspace_root: str,
    ) -> ProjectSession:
        row = conn.execute(
            "SELECT state_json FROM projects WHERE project_id = ?",
            (self._active_project_id(session_id),),
        ).fetchone()
        if row is None:
            session = self._new_session(session_id=session_id, workspace_root=workspace_root)
            self._upsert_active_project(
                conn,
                principal=principal,
                session=session,
                now=_utc_now_iso(),
            )
            return session
        return self._session_from_state(
            state_json=str(row["state_json"]),
            session_id=session_id,
            workspace_root=workspace_root,
        )

    def _session_from_state(
        self,
        *,
        state_json: str,
        session_id: str,
        workspace_root: str,
    ) -> ProjectSession:
        raw_state = json.loads(state_json)
        if isinstance(raw_state, dict) and "studio_project_schema_version" in raw_state:
            project = deserialize_project(state_json)
            session = ProjectSession()
            restore_session(project, session)
        else:
            session = ProjectSession.model_validate(raw_state)
        session.session_id = session_id
        session.workspace_root = workspace_root
        return session

    def _upsert_active_project(
        self,
        conn: sqlite3.Connection,
        *,
        principal: Principal,
        session: ProjectSession,
        now: str,
    ) -> ProjectCatalogEntry:
        return self._upsert_project(
            conn,
            principal=principal,
            session=session,
            project_id=self._active_project_id(session.session_id or ""),
            now=now,
        )

    def _upsert_project(
        self,
        conn: sqlite3.Connection,
        *,
        principal: Principal,
        session: ProjectSession,
        project_id: str,
        now: str,
    ) -> ProjectCatalogEntry:
        state_json = session.model_dump_json()
        name = _project_name(session)
        existing = conn.execute(
            "SELECT created_at FROM projects WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        created_at = str(existing["created_at"]) if existing else now
        conn.execute(
            """
            INSERT INTO projects(project_id, principal_id, session_id, name, state_json, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
              principal_id = excluded.principal_id,
              session_id = excluded.session_id,
              name = excluded.name,
              state_json = excluded.state_json,
              updated_at = excluded.updated_at
            """,
            (
                project_id,
                principal.user_id,
                session.session_id,
                name,
                state_json,
                created_at,
                now,
            ),
        )
        return ProjectCatalogEntry(
            project_id=project_id,
            principal_id=principal.user_id,
            session_id=session.session_id or "",
            name=name,
            created_at=created_at,
            updated_at=now,
        )

    @staticmethod
    def _assert_project_id_available_for_principal(
        conn: sqlite3.Connection,
        *,
        principal: Principal,
        project_id: str,
    ) -> None:
        existing = conn.execute(
            "SELECT principal_id FROM projects WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        if existing is not None and str(existing["principal_id"]) != principal.user_id:
            raise PermissionError(
                f"Project id '{project_id}' belongs to a different Studio principal."
            )

    @staticmethod
    def _assert_project_count_within_quota(
        conn: sqlite3.Connection,
        *,
        principal: Principal,
        project_id: str,
    ) -> None:
        existing = conn.execute(
            "SELECT 1 FROM projects WHERE project_id = ? AND principal_id = ?",
            (project_id, principal.user_id),
        ).fetchone()
        if existing is not None:
            return
        count = conn.execute(
            "SELECT COUNT(*) AS count FROM projects WHERE principal_id = ?",
            (principal.user_id,),
        ).fetchone()["count"]
        limit = get_studio_settings().max_projects_per_principal
        if int(count) >= limit:
            raise QuotaExceededError(
                f"Project quota exceeded: principal already has {count} project"
                f"{'' if count == 1 else 's'}; limit is {limit}."
            )

    @staticmethod
    def _active_project_id(session_id: str) -> str:
        return f"{session_id}:{ACTIVE_PROJECT_SUFFIX}"

    @staticmethod
    def _catalog_entry(row: sqlite3.Row) -> ProjectCatalogEntry:
        return ProjectCatalogEntry(
            project_id=str(row["project_id"]),
            principal_id=str(row["principal_id"]),
            session_id=str(row["session_id"]),
            name=str(row["name"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
