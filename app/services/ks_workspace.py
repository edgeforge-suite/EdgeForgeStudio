"""Request-scoped Knowledge Workspace identity and local storage helpers."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.integrations.ks_integration import KSUnavailableError
from app.models.project import ProjectSession
from app.services.path_resolver import (
    PathResolutionError,
    contain_under_session_workspace,
    session_workspace_root,
)


def current_workspace_identity(session: ProjectSession) -> str | None:
    """Return the current durable workspace ID without minting a new one."""
    return session.project_id or session.ks_project_id


def ensure_workspace_identity(session: ProjectSession) -> str:
    """Return the durable Studio-owned workspace ID, minting it once when needed."""
    if session.project_id:
        if session.ks_project_id != session.project_id:
            session.ks_project_id = session.project_id
    elif session.ks_project_id:
        session.project_id = session.ks_project_id
    else:
        workspace_id = f"studio-ks-{uuid4()}"
        session.project_id = workspace_id
        session.ks_project_id = workspace_id

    return session.project_id or session.ks_project_id or ""


def mark_workspace_active(session: ProjectSession) -> None:
    if not session.capabilities.knowledge_assist_enabled:
        return
    if not session.ks_active:
        session.ks_active = True
    return None


def workspace_dir(session: ProjectSession) -> Path:
    ensure_workspace_identity(session)
    root = _confined_path(session, session_workspace_root(session) / "ks")
    root.mkdir(parents=True, exist_ok=True)
    return root


def workspace_db_path(session: ProjectSession) -> str:
    return str(_confined_path(session, workspace_dir(session) / "knowledge.sqlite3"))


def workspace_allowed_roots(session: ProjectSession) -> list[str]:
    return [str(workspace_dir(session))]


def _confined_path(session: ProjectSession, path: Path) -> Path:
    try:
        return contain_under_session_workspace(session, path)
    except PathResolutionError as exc:
        raise KSUnavailableError("Knowledge Workspace path is outside this session's workspace.") from exc
