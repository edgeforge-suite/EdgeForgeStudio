from __future__ import annotations

from app.models.project import ProjectSession
from app.services.identity import Principal
from app.services.session_context import get_session_store

TEST_PRINCIPAL = Principal(
    user_id="anonymous:test-session",
    display_name="Anonymous Studio Session",
    source="anonymous",
    claims={"anonymous_session_id": "test-session"},
)


def get_session() -> ProjectSession:
    return get_session_store().get_or_create(TEST_PRINCIPAL)


def save_session(session: ProjectSession) -> None:
    store = get_session_store()
    if not session.session_id or not session.workspace_root:
        active_session = store.get_or_create(TEST_PRINCIPAL)
        session.session_id = session.session_id or active_session.session_id
        session.workspace_root = session.workspace_root or active_session.workspace_root
    store.save(session)


def reset_session() -> ProjectSession:
    store = get_session_store()
    session = store.get_or_create(TEST_PRINCIPAL)
    return store.reset(session.session_id or "default")
