"""E2E-F6 regression: a ``~`` Output Path must never resolve against the CWD.

Step 1's Output Path field offers ``~/Documents/...`` as its own placeholder and
help-text example, so a leading ``~`` is expected input. Before the fix
``session_output_root()`` returned it unexpanded, which is a *relative* path whose
first segment is literally ``~`` -- so ``/export/write`` wrote a full package into
``<cwd>/~/Documents/...`` (inside the Studio checkout) and still reported success.

Every test here redirects ``HOME`` into ``tmp_path`` before touching a resolver,
because the resolvers ``mkdir()`` what they return: without the redirect a passing
run would create real directories in the developer's home, and a deliberately
mutated run would leave a literal ``~`` directory inside the checkout.
"""

from __future__ import annotations

import ast
import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.project import KSManifestRevision, ProjectSession
from app.routes.export import _unresolvable_output_path_response
from app.services.path_resolver import (
    PathResolutionError,
    session_export_dir,
    session_output_root,
    session_workspace_root,
)
from app.services.settings import get_studio_settings
from tests.session_helpers import get_session, reset_session, save_session
from tests.test_package_writer import _full_session

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _sandboxed_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Point ``~`` at a disposable directory for the whole module.

    Teardown removes a literal ``~`` directory under the CWD **only when this test
    created it**. Deleting one unconditionally would recursively destroy a
    pre-existing ``~`` directory in the developer's checkout — including the very
    evidence someone might be inspecting after hitting this bug — so existence is
    recorded before the test runs and anything pre-existing is left untouched.
    """
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # harmless on POSIX

    stray = Path.cwd() / "~"
    pre_existing = stray.exists() or stray.is_symlink()

    yield home

    # A regression (or a deliberate mutation) resolves the path against the CWD.
    # Clean that up so a failing run cannot pollute the checkout — but never touch
    # a directory that was already there, and never follow a symlink.
    if pre_existing or stray.is_symlink() or not stray.is_dir():
        return
    shutil.rmtree(stray)


def test_tilde_output_path_expands_to_an_absolute_home_path(_sandboxed_home: Path) -> None:
    session = ProjectSession(
        app_name="Tilde Demo",
        output_path="~/Documents/EdgeForgeGeneratedApps/tilde-demo",
    )

    root = session_output_root(session)

    assert root.is_absolute(), f"output root must be absolute, got {root}"
    assert "~" not in root.parts, f"a literal '~' segment survived: {root}"
    assert root == _sandboxed_home / "Documents/EdgeForgeGeneratedApps/tilde-demo"


def test_tilde_output_path_is_not_resolved_against_the_process_cwd() -> None:
    """The specific failure: the write root landing under the server's CWD.

    Compares the *effective* filesystem location, because an unexpanded ``~/...``
    is a relative path -- its raw string never matches the CWD prefix, so a naive
    string check here would pass even while the package lands under the CWD.
    """
    session = ProjectSession(app_name="X", output_path="~/some-export-root")

    root = session_output_root(session)
    effective = root if root.is_absolute() else Path.cwd() / root

    assert not str(effective.resolve()).startswith(str(Path.cwd().resolve())), (
        f"output root {root} effectively resolves to {effective} under the CWD "
        f"{Path.cwd()} -- a package would be written into whatever directory the "
        "server happened to be started from"
    )


def test_tilde_workspace_root_expands_too(_sandboxed_home: Path) -> None:
    session = ProjectSession(
        app_name="X",
        session_id="s-tilde",
        workspace_root="~/Documents/EdgeForgeGeneratedApps/tilde-workspace",
    )

    root = session_workspace_root(session)

    assert root.is_absolute()
    assert "~" not in root.parts
    assert str(root).startswith(str(_sandboxed_home))


def test_reopened_pre_fix_project_resolves_its_stored_export_path(
    _sandboxed_home: Path,
) -> None:
    """A project saved BEFORE the fix carries a raw ``~/...`` last_export_path.

    Reopening it must not leave assess, artifact download, regen binding, or
    build/run operating under a literal ``~`` directory in the server's CWD.
    """
    session = ProjectSession(
        app_name="X",
        last_export_path="~/Documents/EdgeForgeGeneratedApps/pre-fix/proj",
    )

    export_dir = session_export_dir(session)

    assert export_dir is not None
    assert export_dir.is_absolute()
    assert "~" not in export_dir.parts
    assert str(export_dir).startswith(str(_sandboxed_home))
    assert session_export_dir(ProjectSession(app_name="X")) is None


def test_unresolvable_output_path_is_a_400_not_a_500() -> None:
    """``~unknownuser/...`` is bad user input, not a server fault.

    It must also never silently fall back to the unexpanded value, which is the
    original bug (a relative path whose first segment is literally ``~``).
    """
    session = ProjectSession(app_name="X", output_path="~missinguser/exports")

    with pytest.raises(PathResolutionError):
        session_output_root(session)

    response = _unresolvable_output_path_response(session)
    assert response is not None
    assert response.status_code == 400
    assert b"Output Path is not usable" in response.body

    # A resolvable path is not blocked.
    assert _unresolvable_output_path_response(
        ProjectSession(app_name="X", output_path="~/exports")
    ) is None


def test_state_dir_and_workspace_root_expand_consistently(
    monkeypatch: pytest.MonkeyPatch, _sandboxed_home: Path
) -> None:
    """Expanding only one of them splits shared-mode state.

    The workspace fallback is ``settings.state_dir / "workspaces" / <id>``; if
    state_dir kept a literal ``~`` while a session-supplied workspace_root was
    expanded, the two would resolve to different trees.
    """
    monkeypatch.setenv("EDGEFORGE_STUDIO_STATE_DIR", "~/studio-state")

    state_dir = get_studio_settings().state_dir
    assert state_dir.is_absolute()
    assert "~" not in state_dir.parts
    assert str(state_dir).startswith(str(_sandboxed_home))

    fallback = session_workspace_root(ProjectSession(app_name="X", session_id="s-1"))
    assert "~" not in fallback.parts
    assert str(fallback).startswith(str(state_dir))


def test_fixture_teardown_never_deletes_a_pre_existing_tilde_directory(
    tmp_path: Path,
) -> None:
    """The cleanup must only remove what a test created.

    Recursively deleting any ``~`` directory found in the checkout would destroy a
    developer's pre-existing one — including evidence left by this very bug.
    """
    import shutil as _shutil

    from _pytest.monkeypatch import MonkeyPatch

    sandbox = tmp_path / "cwd"
    (sandbox / "~" / "keep").mkdir(parents=True)
    (sandbox / "~" / "keep" / "evidence.txt").write_text("do not delete", encoding="utf-8")

    mp = MonkeyPatch()
    mp.chdir(sandbox)
    try:
        gen = _sandboxed_home.__wrapped__(mp, tmp_path / "fixture-home")
        next(gen)          # setup: records the pre-existing '~'
        next(gen, None)    # teardown
    finally:
        mp.undo()

    survivor = sandbox / "~" / "keep" / "evidence.txt"
    assert survivor.is_file(), "teardown deleted a pre-existing '~' directory"
    assert survivor.read_text(encoding="utf-8") == "do not delete"
    _shutil.rmtree(sandbox, ignore_errors=True)


def test_no_route_reads_last_export_path_without_expanding_it() -> None:
    """Structural guard: every consumer must go through ``session_export_dir``.

    Patching only the sites a grep happened to surface is how ``/export/validate``
    and ``/export/generate`` were missed — ``str(Path(session.last_export_path) /
    ...)`` did not match the filter used. This asserts the raw construction is gone
    from the whole app, so a new consumer written the old way fails here.
    """
    offenders: list[str] = []
    for source in (ROOT / "app").rglob("*.py"):
        if source.name == "path_resolver.py":
            continue  # the expansion helper documents the old shape
        text = source.read_text(encoding="utf-8")
        if "Path(session.last_export_path)" in text:
            offenders.append(str(source.relative_to(ROOT)))
    assert not offenders, (
        "these read last_export_path without home-expansion, so a reopened pre-fix "
        f"project keeps operating under a literal '~': {offenders}"
    )


def test_every_expand_user_path_call_is_contained_or_explicitly_allowlisted() -> None:
    """Structural guard for containment (PR #276 review, F1).

    The guard above enforces *expansion* for one literal construction pattern.
    It does not enforce *containment*: ``review.py`` expanded a different
    restored field (``manifest_revisions[].export_path``) through
    ``expand_user_path`` and satisfied that guard completely while bypassing the
    session-workspace boundary. Nothing structural caught it -- only a reviewer
    manually re-deriving the test evidence did.

    This asserts every function that calls ``expand_user_path`` also calls
    ``contain_under_session_workspace`` in the same function body, unless it is
    on the small explicit allowlist below with a stated reason. A new reader of
    restored path state written the ``review.py``-before-this-PR way fails here.
    """
    ALLOWLIST: dict[tuple[str, str], str] = {
        ("app/services/path_resolver.py", "session_workspace_root"): (
            "this function builds the trusted root itself; it cannot contain "
            "itself, and its own fallback branch is separately self-contained "
            "under state_dir (F4)"
        ),
    }

    offenders: list[str] = []
    seen_allowlist_entries: set[tuple[str, str]] = set()

    for source in (ROOT / "app").rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        if "expand_user_path(" not in text:
            continue
        rel = str(source.relative_to(ROOT))
        tree = ast.parse(text, filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            called: set[str] = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(
                    sub.func, (ast.Name, ast.Attribute)
                ):
                    called.add(
                        sub.func.id if isinstance(sub.func, ast.Name) else sub.func.attr
                    )
            if "expand_user_path" not in called:
                continue
            if "contain_under_session_workspace" in called:
                continue
            key = (rel, node.name)
            if key in ALLOWLIST:
                seen_allowlist_entries.add(key)
                continue
            offenders.append(f"{rel}:{node.name}")

    assert not offenders, (
        "these functions call expand_user_path() without routing the result "
        "through contain_under_session_workspace() and are not on the explicit "
        f"allowlist -- either contain them or state why not: {offenders}"
    )

    stale = set(ALLOWLIST) - seen_allowlist_entries
    assert not stale, (
        "these allowlist entries no longer call expand_user_path() without "
        f"containment -- remove them so the allowlist stays accurate: {stale}"
    )


def test_validate_and_generate_reject_an_unresolvable_export_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A stored '~unknownuser/...' must 400 on every consumer, never 500.

    ``appbuilder_repo_path`` is pointed at a real (but otherwise empty) directory
    so the routes' Engine-repo-path guard is satisfied regardless of whether a
    sibling Engine checkout happens to exist next to wherever this test runs.
    Without that, this test's pass/fail depended on incidental directory layout:
    it passed locally next to a real EdgeForge checkout and failed in CI, which
    has no sibling checkout -- ``appbuilder_repo_path`` defaults via
    ``Field(default_factory=default_edgeforge_repo_path)``, which falls back to
    that sibling path when unset.
    """
    reset_session()
    session = _full_session()
    engine_stub = tmp_path / "engine-stub"
    engine_stub.mkdir()
    session.appbuilder_repo_path = str(engine_stub)
    session.last_export_path = "~missinguser/exports/proj"
    save_session(session)

    client = TestClient(app)
    for route in ("/export/validate", "/export/generate"):
        response = client.post(route)
        assert response.status_code == 400, (
            f"{route} returned {response.status_code}, expected 400"
        )
        assert "not usable" in response.json().get("error", "")


def test_assess_rejects_an_unresolvable_export_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """'~unknownuser/...' must 400 assess too, never 500.

    The guard runs before the per-interface loop, so it fires ahead of both the
    Engine-repo check and any network I/O -- no engine stub or run_assess mock
    needed for this specific path to be reached.
    """
    from app.models.project import OperationSample, UpstreamInterface

    reset_session()
    session = _full_session()
    session.upstream_interfaces = [
        UpstreamInterface(
            name="url-iface",
            type="rest-json",
            spec_url="https://example.invalid/openapi.json",
            entity_name="Account",
            operations=[OperationSample(name="op")],
        )
    ]
    session.last_export_path = "~missinguser/exports/proj"
    save_session(session)

    response = TestClient(app).post("/export/assess")

    assert response.status_code == 400, (
        f"/export/assess returned {response.status_code}, expected 400"
    )
    assert "not usable" in response.json().get("error", "")


def test_step8_never_displays_a_raw_restored_tilde_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _sandboxed_home: Path,
) -> None:
    """Step 8 must show the resolved path, or nothing -- never the literal '~/...'.

    A restored ``last_export_path`` and a restored revision ``export_path`` are
    both set to the same raw value: the resolvable one must render as its
    resolved, absolute form; both must never appear as the raw literal string.
    """
    reset_session()
    session = _full_session()
    session.last_export_path = "~/exports/proj"
    session.ks_workspace_state.manifest_revisions.append(
        KSManifestRevision(
            revision_id="rev-1",
            exported_at="2026-07-25T00:00:00Z",
            manifest_hash="abc",
            archetype="crud",
            target_profile="springboot-legacy-compatible",
            export_path="~/exports/proj",
        )
    )
    save_session(session)

    html = TestClient(app).get("/export").text

    assert "~/exports/proj" not in html, "the raw restored path leaked into Step 8"
    assert str(_sandboxed_home / "exports/proj") in html, (
        "Step 8 did not display the resolved path anywhere"
    )


def test_zip_and_artifact_routes_do_not_500_on_unresolvable_paths() -> None:
    reset_session()
    session = _full_session()
    session.output_path = "~missinguser/exports"
    session.last_export_path = "~missinguser/exports/proj"
    save_session(session)

    client = TestClient(app)
    assert client.get("/export/download-zip").status_code < 500
    assert client.get("/export/artifact/app-definition.yaml").status_code < 500
    # Page render must survive it too — the artifact summary is built on load.
    assert client.get("/export").status_code < 500


def test_persisted_manifest_revision_path_is_expanded_for_baseline_lookup(
    _sandboxed_home: Path,
) -> None:
    """Step-7 baseline lookup reads a persisted revision export_path.

    Revisions written before output-path expansion carry a raw '~/...'; without
    expanding on read the baseline silently misses and Step 8 shows a stale path.
    """
    from app.routes.review import _build_manifest_drawer_state

    package = _sandboxed_home / "revisions" / "proj"
    package.mkdir(parents=True)
    (package / "app-definition.yaml").write_text("app_name: demo\n", encoding="utf-8")

    reset_session()
    session = _full_session()
    session.ks_workspace_state.manifest_revisions.append(
        KSManifestRevision(
            revision_id="rev-1",
            exported_at="2026-07-25T00:00:00Z",
            manifest_hash="abc",
            archetype="crud",
            target_profile="springboot-legacy-compatible",
            export_path="~/revisions/proj",  # raw, as a pre-fix export recorded it
        )
    )
    save_session(session)

    context = _build_manifest_drawer_state(get_session(), "app_name: demo\n")

    # "current-only" covers both "baseline missing" and "baseline found, no diff",
    # so assert on the note that distinguishes them.
    assert "could not be read from disk" not in context.get("note", ""), (
        "the persisted '~/...' revision path was not expanded, so the Step-7 "
        f"baseline lookup missed a manifest that exists on disk: {context}"
    )


def test_export_write_with_tilde_output_path_creates_no_tilde_dir_under_cwd() -> None:
    """End-to-end guard through the real export route."""
    reset_session()
    session = _full_session()
    session.output_path = "~/exports/e2e-f6"
    save_session(session)

    stray = Path.cwd() / "~"
    existed_before = stray.exists()

    client = TestClient(app)
    response = client.post("/export/write")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True

    # The echoed location must be the real one, not the unexpanded string.
    assert not payload["output_dir"].startswith("~"), (
        f"output_dir echoed an unexpanded path: {payload['output_dir']}"
    )

    if not existed_before:
        assert not stray.exists(), (
            f"export created a literal '~' directory under the CWD: {stray}"
        )

    written_root = Path(payload["output_dir"])
    assert written_root.is_absolute()
    assert (written_root / "app-definition.yaml").is_file()
    assert str(written_root).startswith(os.environ["HOME"])
