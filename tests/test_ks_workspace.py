from __future__ import annotations

from pathlib import Path

from app.services.identity import Principal
from app.services.ks_workspace import workspace_allowed_roots, workspace_db_path, workspace_dir
from app.services.session_context import get_session_store


def _principal(session_id: str) -> Principal:
    return Principal(
        user_id=f"anonymous:{session_id}",
        display_name="Anonymous Studio Session",
        source="anonymous",
        claims={"anonymous_session_id": session_id},
    )


def test_ks_workspace_paths_are_session_scoped_even_for_same_project_id():
    store = get_session_store()
    session_a = store.get_or_create(_principal("browser-a"))
    session_b = store.get_or_create(_principal("browser-b"))
    session_a.project_id = "shared-project-id"
    session_a.ks_project_id = "shared-project-id"
    session_b.project_id = "shared-project-id"
    session_b.ks_project_id = "shared-project-id"

    dir_a = workspace_dir(session_a)
    dir_b = workspace_dir(session_b)
    db_a = Path(workspace_db_path(session_a))
    db_b = Path(workspace_db_path(session_b))
    roots_a = [Path(root) for root in workspace_allowed_roots(session_a)]
    roots_b = [Path(root) for root in workspace_allowed_roots(session_b)]
    workspace_a = Path(session_a.workspace_root or "")
    workspace_b = Path(session_b.workspace_root or "")

    assert workspace_a != workspace_b
    assert dir_a != dir_b
    assert db_a != db_b
    assert dir_a.is_relative_to(workspace_a)
    assert dir_b.is_relative_to(workspace_b)
    assert db_a.is_relative_to(workspace_a)
    assert db_b.is_relative_to(workspace_b)
    assert all(root.is_relative_to(workspace_a) for root in roots_a)
    assert all(root.is_relative_to(workspace_b) for root in roots_b)
