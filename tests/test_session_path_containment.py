"""Adversarial coverage for session-scoped export-path containment.

These tests deliberately assert *refused access attempts*, not merely that two
sessions resolve to different directories. The pre-existing isolation tests
established separation (session A and session B get distinct workspaces) but
never exercised session A **reaching for** session B's data, which is the
property that actually matters -- an isolation control that is enabled but
untested manufactures confidence rather than providing it.

The attacker-controlled channel is ``last_export_path``: it is restored from an
*uploaded* project file, so in shared mode it is caller input rather than
server-owned state. Two independent boundaries are covered here:

1. ``restore_session`` must not admit the value into session state at all.
2. ``session_export_dir`` -- the choke point every reader routes through -- must
   refuse it on read, including after ``..`` traversal (defence in depth).
"""

from __future__ import annotations

import pytest

from app.models.project import ProjectSession, StudioProject
from app.services.path_resolver import PathResolutionError, session_export_dir
from app.services.project_file_service import restore_session


def _shared_mode(monkeypatch) -> None:
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")


def _session_with_workspace(workspace) -> ProjectSession:
    session = ProjectSession()
    session.session_id = "session-under-test"
    session.workspace_root = str(workspace)
    return session


# ---------------------------------------------------------------------------
# session_export_dir -- read-side containment
# ---------------------------------------------------------------------------

def test_shared_mode_refuses_export_path_in_a_sibling_session(monkeypatch, tmp_path):
    """The core cross-session case: pointing at another session's workspace."""
    _shared_mode(monkeypatch)
    victim = tmp_path / "workspaces" / "victim-session"
    attacker = tmp_path / "workspaces" / "attacker-session"
    victim.mkdir(parents=True)
    attacker.mkdir(parents=True)

    session = _session_with_workspace(attacker)
    session.last_export_path = str(victim / "output" / "generated-app")

    with pytest.raises(PathResolutionError):
        session_export_dir(session)


def test_shared_mode_refuses_export_path_outside_the_state_dir(monkeypatch, tmp_path):
    """Absolute paths with no relationship to any session are refused too."""
    _shared_mode(monkeypatch)
    workspace = tmp_path / "workspaces" / "session-a"
    workspace.mkdir(parents=True)
    outside = tmp_path / "somewhere-else"
    outside.mkdir()

    session = _session_with_workspace(workspace)
    session.last_export_path = str(outside)

    with pytest.raises(PathResolutionError):
        session_export_dir(session)


def test_shared_mode_refuses_traversal_escape_from_the_workspace(monkeypatch, tmp_path):
    """``..`` must not escape: containment is tested *after* resolution."""
    _shared_mode(monkeypatch)
    workspace = tmp_path / "workspaces" / "session-a"
    workspace.mkdir(parents=True)

    session = _session_with_workspace(workspace)
    session.last_export_path = str(workspace / ".." / "victim-session")

    with pytest.raises(PathResolutionError):
        session_export_dir(session)


def test_shared_mode_allows_export_path_inside_the_session_workspace(monkeypatch, tmp_path):
    """The legitimate flow keeps working -- this must not be a blanket denial."""
    _shared_mode(monkeypatch)
    workspace = tmp_path / "workspaces" / "session-a"
    legitimate = workspace / "output" / "generated-app"
    legitimate.mkdir(parents=True)

    session = _session_with_workspace(workspace)
    session.last_export_path = str(legitimate)

    assert session_export_dir(session) == legitimate.resolve()


def test_no_export_path_still_returns_none(monkeypatch, tmp_path):
    _shared_mode(monkeypatch)
    workspace = tmp_path / "workspaces" / "session-a"
    workspace.mkdir(parents=True)

    assert session_export_dir(_session_with_workspace(workspace)) is None


# ---------------------------------------------------------------------------
# restore_session -- import-side rejection
# ---------------------------------------------------------------------------

def test_shared_mode_import_does_not_admit_a_foreign_export_path(monkeypatch, tmp_path):
    """A hostile project file must not seed session state with its own path."""
    _shared_mode(monkeypatch)
    workspace = tmp_path / "workspaces" / "attacker-session"
    workspace.mkdir(parents=True)
    session = _session_with_workspace(workspace)

    project = StudioProject(app_name="imported")
    project.last_export_path = str(tmp_path / "workspaces" / "victim-session")

    restore_session(project, session)

    assert session.last_export_path is None


def test_local_mode_import_preserves_the_operator_export_path(monkeypatch, tmp_path):
    """Local mode is unchanged: the path is the operator's own machine."""
    monkeypatch.delenv("EDGEFORGE_STUDIO_SHARED_MODE", raising=False)
    own_export = tmp_path / "Documents" / "my-export"
    session = ProjectSession()

    project = StudioProject(app_name="imported")
    project.last_export_path = str(own_export)

    restore_session(project, session)

    assert session.last_export_path == str(own_export)


# ---------------------------------------------------------------------------
# The shared helper -- used by BOTH readers
# ---------------------------------------------------------------------------

def test_shared_helper_refuses_foreign_path_for_any_reader(monkeypatch, tmp_path):
    """The Step-7 review diff reads a *different* restored field.

    ``manifest_revisions[].export_path`` is restored from the same uploaded
    project file as ``last_export_path`` but is read by ``routes/review.py``,
    which previously applied only ``expand_user_path``. Both readers now route
    through one containment helper so a future reader cannot re-derive -- and
    forget -- the check.
    """
    from app.services.path_resolver import contain_under_session_workspace

    _shared_mode(monkeypatch)
    workspace = tmp_path / "workspaces" / "attacker-session"
    workspace.mkdir(parents=True)
    victim = tmp_path / "workspaces" / "victim-session"
    victim.mkdir(parents=True)

    session = _session_with_workspace(workspace)

    with pytest.raises(PathResolutionError):
        contain_under_session_workspace(session, victim)

    inside = workspace / "output"
    inside.mkdir()
    assert contain_under_session_workspace(session, inside) == inside.resolve()


def test_shared_mode_refuses_a_symlink_that_points_outside_the_workspace(monkeypatch, tmp_path):
    """The one escape class the caller can plausibly *create* themselves (F3).

    ``..`` segments and absolute paths are pure input; a symlink is something the
    caller controls the contents of their own workspace to place. Resolution runs
    before containment (``Path.resolve()`` follows symlinks), so this must be
    refused exactly like any other escape -- verified here rather than only
    asserted in the docstrings at ``path_resolver.py:64-66``/``:97-98``.
    """
    _shared_mode(monkeypatch)
    workspace = tmp_path / "workspaces" / "session-a"
    workspace.mkdir(parents=True)
    outside = tmp_path / "somewhere-else"
    outside.mkdir()

    escape_link = workspace / "escape"
    escape_link.symlink_to(outside)

    session = _session_with_workspace(workspace)
    session.last_export_path = str(escape_link)

    with pytest.raises(PathResolutionError):
        session_export_dir(session)


# ---------------------------------------------------------------------------
# The review-diff reader itself, not just the shared helper (F1)
# ---------------------------------------------------------------------------
#
# ``test_shared_helper_refuses_foreign_path_for_any_reader`` above proves
# ``contain_under_session_workspace`` works; it calls the helper directly and so
# never proves ``review.py`` actually calls it. Reverting ``review.py``'s fix
# back to a bare ``expand_user_path`` left every existing test green, including
# that one -- these two drive the real reader, in shared mode, the way a
# restored revision actually reaches it.

def test_shared_mode_review_diff_reader_refuses_a_foreign_revision_path(monkeypatch, tmp_path):
    """A revision ``export_path`` restored from an uploaded project, pointing at
    another session's workspace, must not be read by the Step-7 baseline lookup.
    """
    from app.models.project import KSManifestRevision
    from app.routes.review import _build_manifest_drawer_state

    _shared_mode(monkeypatch)
    workspace = tmp_path / "workspaces" / "attacker-session"
    workspace.mkdir(parents=True)
    victim_export = tmp_path / "workspaces" / "victim-session" / "output"
    victim_export.mkdir(parents=True)
    (victim_export / "app-definition.yaml").write_text("app_name: victim\n", encoding="utf-8")

    session = _session_with_workspace(workspace)
    session.ks_workspace_state.manifest_revisions.append(
        KSManifestRevision(
            revision_id="rev-1",
            exported_at="2026-07-26T00:00:00Z",
            manifest_hash="abc",
            archetype="crud",
            target_profile="springboot-legacy-compatible",
            export_path=str(victim_export),
        )
    )

    context = _build_manifest_drawer_state(session, "app_name: attacker\n")

    assert context["mode"] == "current-only"
    assert "could not be read from disk" in context.get("note", ""), (
        "the review diff read a revision export_path outside its own session "
        f"workspace: {context}"
    )


def test_shared_mode_review_diff_reader_reads_its_own_session_revision(monkeypatch, tmp_path):
    """The legitimate flow must keep working -- this is not a blanket denial."""
    from app.models.project import KSManifestRevision
    from app.routes.review import _build_manifest_drawer_state

    _shared_mode(monkeypatch)
    workspace = tmp_path / "workspaces" / "session-a"
    own_export = workspace / "output"
    own_export.mkdir(parents=True)
    (own_export / "app-definition.yaml").write_text("app_name: demo\n", encoding="utf-8")

    session = _session_with_workspace(workspace)
    session.ks_workspace_state.manifest_revisions.append(
        KSManifestRevision(
            revision_id="rev-1",
            exported_at="2026-07-26T00:00:00Z",
            manifest_hash="abc",
            archetype="crud",
            target_profile="springboot-legacy-compatible",
            export_path=str(own_export),
        )
    )

    context = _build_manifest_drawer_state(session, "app_name: demo\n")

    assert "could not be read from disk" not in context.get("note", ""), (
        f"a legitimate in-workspace revision path was refused: {context}"
    )


# ---------------------------------------------------------------------------
# session_workspace_root -- the trusted root's own fallback (F4)
# ---------------------------------------------------------------------------

def test_shared_mode_workspace_root_fallback_refuses_a_traversal_session_id(monkeypatch, tmp_path):
    """``session_id`` is server-issued today, but the fallback must not simply
    trust it -- a traversal-bearing value must not move the containment root
    itself outside ``state_dir`` (F4: latent, not reachable today, hardened anyway).
    """
    from app.services.path_resolver import session_workspace_root

    _shared_mode(monkeypatch)
    monkeypatch.setenv("EDGEFORGE_STUDIO_STATE_DIR", str(tmp_path / "state"))

    session = ProjectSession()
    session.session_id = "../../escaped"

    with pytest.raises(PathResolutionError):
        session_workspace_root(session)


# ---------------------------------------------------------------------------
# The Step-8 "latest revision" checkpoint display (F5)
# ---------------------------------------------------------------------------

def test_shared_mode_export_page_checkpoint_blanks_a_foreign_revision_path(monkeypatch, tmp_path):
    """Display-only, but it should agree with the boundary the review-diff reader
    enforces rather than disagree with it -- otherwise Step 8 can show a revision
    path that review.py's own baseline lookup refuses to read (F5).
    """
    from app.models.project import KSManifestRevision
    from app.routes.export import _latest_revision_checkpoint

    _shared_mode(monkeypatch)
    workspace = tmp_path / "workspaces" / "attacker-session"
    workspace.mkdir(parents=True)
    victim = tmp_path / "workspaces" / "victim-session" / "output"
    victim.mkdir(parents=True)

    session = _session_with_workspace(workspace)
    session.ks_workspace_state.manifest_revisions.append(
        KSManifestRevision(
            revision_id="rev-1",
            exported_at="2026-07-26T00:00:00Z",
            manifest_hash="abc",
            archetype="crud",
            target_profile="springboot-legacy-compatible",
            export_path=str(victim),
        )
    )

    checkpoint = _latest_revision_checkpoint(session)

    assert checkpoint["export_path"] == "", (
        "the Step-8 checkpoint display showed a path outside its own session "
        f"workspace: {checkpoint}"
    )
