"""SessionStore seam for future request-keyed Studio sessions."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Protocol

from starlette.requests import Request

from app.models.project import ProjectSession
from app.services.identity import Principal, get_current_principal
from app.services.quotas import QuotaExceededError

DEFAULT_SESSION_ID = "default"


@dataclass(frozen=True)
class ProjectCatalogEntry:
    project_id: str
    principal_id: str
    session_id: str
    name: str
    created_at: str
    updated_at: str


class SessionStore(Protocol):
    def get_or_create(self, principal: Principal) -> ProjectSession:
        """Return the current session for a principal, creating it if needed."""

    def load(self, session_id: str) -> ProjectSession:
        """Load a session by id."""

    def save(self, session: ProjectSession) -> None:
        """Persist a session."""

    def reset(self, session_id: str) -> ProjectSession:
        """Reset a session by id."""

    def list_projects(self, principal: Principal) -> list[ProjectCatalogEntry]:
        """List projects owned by a principal."""

    def get_project(self, principal: Principal, project_id: str) -> ProjectSession | None:
        """Load a persisted project by catalog id."""

    def save_project(
        self,
        principal: Principal,
        session: ProjectSession,
        *,
        project_id: str | None = None,
    ) -> ProjectCatalogEntry:
        """Persist a project entry for a principal."""

    def delete_project(self, principal: Principal, project_id: str) -> None:
        """Delete a persisted project entry."""

    def purge_expired_sessions(self, *, now_iso: str | None = None) -> int:
        """Purge idle sessions and return the number removed."""


_SQLITE_STORES: dict[str, SessionStore] = {}
_RETENTION_SWEEP_INTERVAL_SECONDS = 60.0
_RETENTION_SWEEP_LOCK = threading.RLock()
_LAST_RETENTION_SWEEP_MONOTONIC: float | None = None


def get_session_store() -> SessionStore:
    from app.services.settings import get_studio_settings
    from app.services.sqlite_session_store import SqliteSessionStore

    state_dir = get_studio_settings().state_dir
    cache_key = str(state_dir)
    if cache_key not in _SQLITE_STORES:
        _SQLITE_STORES[cache_key] = SqliteSessionStore(state_dir=state_dir)
    return _SQLITE_STORES[cache_key]


def get_current_session(request: Request) -> ProjectSession:
    session = getattr(request.state, "studio_session", None)
    if isinstance(session, ProjectSession):
        return session
    store = getattr(request.state, "session_store", None) or get_session_store()
    _maybe_purge_expired_sessions(store)
    principal = get_current_principal(request)
    session = store.get_or_create(principal)
    request.state.session_store = store
    request.state.studio_session = session
    return session


def save_current_session(request: Request, session: ProjectSession | None = None) -> None:
    store = getattr(request.state, "session_store", None) or get_session_store()
    active_session = session or get_current_session(request)
    store.save(active_session)
    request.state.session_store = store
    request.state.studio_session = active_session


def reset_current_session(request: Request) -> ProjectSession:
    store = getattr(request.state, "session_store", None) or get_session_store()
    session = get_current_session(request)
    session_id = session.session_id or DEFAULT_SESSION_ID
    reset = store.reset(session_id)
    request.state.session_store = store
    request.state.studio_session = reset
    return reset


def save_current_project(
    request: Request,
    session: ProjectSession | None = None,
    *,
    project_id: str | None = None,
) -> ProjectCatalogEntry:
    """Persist a project through the request principal and audit ownership denials."""

    store = getattr(request.state, "session_store", None) or get_session_store()
    principal = get_current_principal(request)
    active_session = session or get_current_session(request)
    try:
        return store.save_project(principal, active_session, project_id=project_id)
    except PermissionError:
        from app.services.audit import audit

        audit(request, "project.ownership", outcome="denied", project_id=project_id)
        raise
    except QuotaExceededError:
        from app.services.audit import audit

        audit(request, "project.save", outcome="blocked", project_id=project_id)
        raise


def workspace_session_marker(session: ProjectSession) -> tuple[str | None, str | None, bool]:
    """Return the workspace fields that KS helpers may mutate during a request."""

    return (session.project_id, session.ks_project_id, session.ks_active)


def save_current_session_if_workspace_changed(
    request: Request,
    session: ProjectSession,
    before: tuple[str | None, str | None, bool],
) -> None:
    """Persist first-use KS workspace changes without turning every GET into a write."""

    if workspace_session_marker(session) != before:
        save_current_session(request, session)


def _maybe_purge_expired_sessions(store: SessionStore) -> None:
    global _LAST_RETENTION_SWEEP_MONOTONIC
    now = time.monotonic()
    with _RETENTION_SWEEP_LOCK:
        if (
            _LAST_RETENTION_SWEEP_MONOTONIC is not None
            and now - _LAST_RETENTION_SWEEP_MONOTONIC < _RETENTION_SWEEP_INTERVAL_SECONDS
        ):
            return
        _LAST_RETENTION_SWEEP_MONOTONIC = now
    store.purge_expired_sessions()


def _reset_retention_sweeper_for_testing() -> None:
    global _LAST_RETENTION_SWEEP_MONOTONIC
    with _RETENTION_SWEEP_LOCK:
        _LAST_RETENTION_SWEEP_MONOTONIC = None
