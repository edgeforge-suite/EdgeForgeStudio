from __future__ import annotations

from pathlib import Path

from starlette.requests import Request

from app.models.project import ClassifiedEntity
from app.services.identity import Principal
from app.services.session_context import (
    get_current_session,
    get_session_store,
    reset_current_session,
    save_current_session,
)
from app.services.sqlite_session_store import SqliteSessionStore


def _principal(session_id: str, *, user_id: str | None = None) -> Principal:
    return Principal(
        user_id=user_id or f"anonymous:{session_id}",
        source="anonymous",
        claims={"anonymous_session_id": session_id},
    )


def _request(principal: Principal, store: SqliteSessionStore) -> Request:
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


def test_sqlite_store_creates_isolated_sessions_and_workspaces(tmp_path: Path):
    store = SqliteSessionStore(state_dir=tmp_path)
    alice = _principal("alice-browser")
    bob = _principal("bob-browser")

    alice_session = store.get_or_create(alice)
    bob_session = store.get_or_create(bob)

    assert alice_session.session_id == "alice-browser"
    assert bob_session.session_id == "bob-browser"
    assert alice_session.workspace_root != bob_session.workspace_root
    assert Path(alice_session.workspace_root or "").is_dir()
    assert Path(bob_session.workspace_root or "").is_dir()
    assert str(tmp_path / "workspaces") in (alice_session.workspace_root or "")
    assert str(tmp_path / "workspaces") in (bob_session.workspace_root or "")


def test_sqlite_store_persists_project_state_across_store_instances(tmp_path: Path):
    principal = _principal("persisted-browser")
    first_store = SqliteSessionStore(state_dir=tmp_path)
    session = first_store.get_or_create(principal)
    session.app_name = "Persisted App"
    session.bounded_context = "persisted"
    session.classified_entities = [ClassifiedEntity(name="Account")]
    first_store.save(session)

    second_store = SqliteSessionStore(state_dir=tmp_path)
    restored = second_store.get_or_create(principal)

    assert restored.session_id == "persisted-browser"
    assert restored.workspace_root == session.workspace_root
    assert restored.app_name == "Persisted App"
    assert restored.bounded_context == "persisted"
    assert restored.classified_entities[0].name == "Account"


def test_sqlite_store_persists_runtime_session_state_across_requests(tmp_path: Path):
    principal = _principal("runtime-browser")
    store = SqliteSessionStore(state_dir=tmp_path)
    session = store.get_or_create(principal)
    session.build_run.port = 18080
    session.build_run.pid = 12345
    session.build_run.run_status = "running"
    store.save(session)

    restored = SqliteSessionStore(state_dir=tmp_path).get_or_create(principal)

    assert restored.build_run.port == 18080
    assert restored.build_run.pid == 12345
    assert restored.build_run.run_status == "running"


def test_sqlite_store_reset_keeps_session_and_workspace_but_clears_project(tmp_path: Path):
    store = SqliteSessionStore(state_dir=tmp_path)
    principal = _principal("reset-browser")
    session = store.get_or_create(principal)
    session.app_name = "Before Reset"
    store.save(session)

    reset = store.reset("reset-browser")

    assert reset.session_id == "reset-browser"
    assert reset.workspace_root == session.workspace_root
    assert reset.is_brand_new is True
    assert reset.app_name == ""
    assert store.get_or_create(principal).app_name == ""


def test_sqlite_project_catalog_methods_round_trip_and_delete(tmp_path: Path):
    store = SqliteSessionStore(state_dir=tmp_path)
    principal = _principal("catalog-browser")
    session = store.get_or_create(principal)
    session.app_name = "Catalog App"
    entry = store.save_project(principal, session, project_id="catalog-project")

    projects = store.list_projects(principal)
    restored = store.get_project(principal, "catalog-project")
    store.delete_project(principal, "catalog-project")

    assert entry.project_id == "catalog-project"
    assert projects[0].project_id == "catalog-project"
    assert projects[0].name == "Catalog App"
    assert restored is not None
    assert restored.app_name == "Catalog App"
    assert store.get_project(principal, "catalog-project") is None


def test_sqlite_project_catalog_rejects_cross_principal_project_id_hijack(
    tmp_path: Path,
):
    store = SqliteSessionStore(state_dir=tmp_path)
    alice = _principal("alice-browser")
    bob = _principal("bob-browser")
    alice_session = store.get_or_create(alice)
    bob_session = store.get_or_create(bob)
    alice_session.app_name = "Alice App"
    bob_session.app_name = "Bob App"

    store.save_project(alice, alice_session, project_id="shared-id")

    try:
        store.save_project(bob, bob_session, project_id="shared-id")
    except PermissionError as exc:
        assert "different Studio principal" in str(exc)
    else:  # pragma: no cover - failure branch
        raise AssertionError("Cross-principal project id collision should be rejected")

    assert store.get_project(bob, "shared-id") is None
    store.delete_project(bob, "shared-id")
    alice_restored = store.get_project(alice, "shared-id")
    bob_projects = store.list_projects(bob)

    assert alice_restored is not None
    assert alice_restored.app_name == "Alice App"
    assert [project.project_id for project in bob_projects] == [
        "bob-browser:active"
    ]


def test_get_current_session_uses_sqlite_store_and_request_cache(tmp_path: Path):
    store = SqliteSessionStore(state_dir=tmp_path)
    principal = _principal("request-browser")
    request = _request(principal, store)

    first = get_current_session(request)
    first.app_name = "Request App"
    save_current_session(request, first)
    second = get_current_session(request)
    reloaded = store.get_or_create(principal)

    assert first is second
    assert reloaded.app_name == "Request App"


def test_reset_current_session_uses_request_scoped_store(tmp_path: Path):
    store = SqliteSessionStore(state_dir=tmp_path)
    principal = _principal("request-reset-browser")
    request = _request(principal, store)
    session = get_current_session(request)
    session.app_name = "Needs Reset"
    save_current_session(request, session)

    reset = reset_current_session(request)

    assert reset.session_id == "request-reset-browser"
    assert reset.app_name == ""
    assert get_current_session(request) is reset


def test_get_session_store_uses_configured_state_dir(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("EDGEFORGE_STUDIO_STATE_DIR", str(tmp_path))

    store = get_session_store()
    session = store.get_or_create(_principal("env-browser"))

    assert isinstance(store, SqliteSessionStore)
    assert session.workspace_root == str(tmp_path / "workspaces" / "env-browser")
