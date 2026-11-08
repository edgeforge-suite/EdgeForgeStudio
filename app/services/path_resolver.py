"""Request/session scoped filesystem path resolution for Studio."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from app.models.project import ProjectSession
from app.services.runtime_defaults import default_edgeforge_repo_path, default_output_path
from app.services.settings import StudioSettings, get_studio_settings

ENGINE_REPO_ENV = "EDGEFORGE_STUDIO_ENGINE_REPO"


class PathResolutionError(ValueError):
    """A configured path could not be resolved to a real filesystem location."""


def preflight_engine_package(
    package: str | Path,
    settings: StudioSettings | None = None,
) -> None:
    """Reject links in shared child inputs without opening their contents.

    Child entrypoint roots do not cover every nested input. This static check
    supplements caller containment; it is not an atomic filesystem sandbox.
    Local mode retains operator-owned symlink compatibility.
    """
    settings = settings or get_studio_settings()
    if not settings.shared_mode:
        return
    root = Path(package)
    try:
        if root.is_symlink() or any(path.is_symlink() for path in root.rglob("*")):
            raise PathResolutionError(
                "The Engine input package contains a symlink and was refused. "
                "Re-export or regenerate the package in this session."
            )
    except OSError as exc:
        raise PathResolutionError("The Engine input package could not be safely inspected.") from exc


def expand_user_path(value: str | Path) -> Path:
    """``Path.expanduser()`` that fails loudly instead of crashing a request.

    ``expanduser()`` raises ``RuntimeError`` when it cannot determine the home
    directory -- notably for ``~unknownuser/...`` and for a bare ``~`` with no
    ``HOME`` set. Letting that escape turns bad Step-1 input into an HTTP 500, so
    it is converted into a typed error the routes render as a 400. Returning the
    path unexpanded is deliberately *not* an option: that is the original bug, a
    relative path whose first segment is literally ``~`` written under the CWD.
    """
    path = Path(value)
    try:
        return path.expanduser()
    except RuntimeError as exc:
        raise PathResolutionError(
            f"'{path}' could not be resolved: the home directory it names does not "
            "exist. Use an absolute path, or a '~/' path for the current user."
        ) from exc


def session_export_dir(
    session: ProjectSession,
    settings: StudioSettings | None = None,
) -> Path | None:
    """The last exported package directory: home-expanded, and confined in shared mode.

    ``last_export_path`` is persisted in project files and session snapshots, so a
    project saved *before* output-path expansion carries a raw ``~/...`` value.
    Reopening it must not keep assess, artifact download, regen binding, or
    build/run operating under a literal ``~`` directory in the server's CWD, so
    every reader resolves through here rather than ``Path(session.last_export_path)``.

    **Containment (shared mode).** ``last_export_path`` is *restored from an uploaded
    project file*, so in shared mode it is untrusted input, not server-owned state.
    Expansion alone is not a boundary: every reader of this value -- artifact
    download, the Step-7 review diff, regen binding, and build/run -- would otherwise
    operate on a caller-chosen absolute path, and the Engine's allowed-root is itself
    derived from it, so the Engine would validate that path against a root derived
    from the same path. This function is the choke point every reader already routes
    through (enforced by ``tests/test_output_path_expansion.py``), so the boundary
    belongs here: the resolved path must lie under the *server-minted*
    ``session_workspace_root``, which is re-stamped from the sessions table and is
    never restorable from an uploaded file.

    Resolution happens *before* the containment test so that ``..`` segments and
    symlinks cannot escape -- the same resolve-then-contain order used by
    ``retention._assert_under`` and ``appbuilder_integration._path_is_under_any``.

    Local mode keeps the historical behaviour: the path is the operator's own, on
    their own machine, exactly as ``session_output_root`` treats ``output_path``.
    """
    if not session.last_export_path:
        return None
    candidate = expand_user_path(session.last_export_path)
    return contain_under_session_workspace(session, candidate, settings)


def contain_under_session_workspace(
    session: ProjectSession,
    candidate: Path,
    settings: StudioSettings | None = None,
) -> Path:
    """Confine *candidate* to the session's server-owned workspace in shared mode.

    Shared by every reader of a path that was restored from an uploaded project
    file. It exists as one function on purpose: the original defect was that the
    containment invariant lived in a single reader's head rather than in shared
    code, so a *second* reader of a *different* restored field
    (``manifest_revisions[].export_path``, read by the Step-7 review diff) applied
    only ``expand_user_path`` and silently bypassed the boundary. Any future reader
    of restored path state must call this rather than re-deriving the check.

    Resolution precedes the containment test so ``..`` segments and symlinks cannot
    escape. Local mode is a pass-through: those paths are the operator's own.
    """
    settings = settings or get_studio_settings()
    if not settings.shared_mode:
        return candidate

    root = session_workspace_root(session, settings).resolve(strict=False)
    resolved = candidate.resolve(strict=False)
    if resolved != root and root not in resolved.parents:
        raise PathResolutionError(
            "The stored path is outside this session's workspace and was refused. "
            "Re-export the package in this session."
        )
    return resolved


def session_workspace_root(
    session: ProjectSession,
    settings: StudioSettings | None = None,
) -> Path:
    """Return the server-owned workspace root for a session.

    P2-created sessions carry ``workspace_root`` from the SQLite store.  The
    fallback stays under ``state_dir`` so shared-mode callers never fall back to a
    user-controlled path if older tests or snapshots lack that metadata.
    """

    settings = settings or get_studio_settings()
    if session.workspace_root:
        root = expand_user_path(session.workspace_root)
    else:
        session_id = session.session_id or "unscoped"
        # settings.state_dir is expanded at construction, so both branches agree:
        # expanding only one of them would split shared-mode state between
        # <state_dir>/workspaces/<id> and a literal '~' directory under the CWD.
        state_dir = settings.state_dir.resolve(strict=False)
        root = (state_dir / "workspaces" / session_id).resolve(strict=False)
        # session_id is server-issued today (identity.py), but this keeps the
        # fallback self-contained rather than resting on that provenance alone:
        # a traversal segment -- or an absolute session_id, which would make the
        # '/' join above discard state_dir entirely -- must not move the
        # containment root itself outside state_dir (PR #276 review, F4).
        if root != state_dir and state_dir not in root.parents:
            raise PathResolutionError(
                "The session workspace could not be resolved under the server's "
                "state directory."
            )
    root.mkdir(parents=True, exist_ok=True)
    return root


def session_output_root(
    session: ProjectSession,
    settings: StudioSettings | None = None,
) -> Path:
    """Resolve the package output root for the current mode.

    The local-mode value is user-supplied (Step 1 "Output Path"), and that field's
    own placeholder and help text offer ``~/Documents/...`` as the example, so a
    leading ``~`` has to be expanded here. Without expansion the value stays a
    *relative* path whose first segment is literally ``~``, and every consumer
    resolves it against the server process CWD -- an export then wrote a complete
    package into ``<cwd>/~/Documents/...`` (inside the Studio checkout) while
    reporting success and echoing the unexpanded path back, so nothing signalled
    the real location.

    Expansion belongs at this choke point rather than at Step-1 save because all
    three consumers already route through here (the Docker output guard, the
    package write, and the ZIP download), so a previously-saved session or an
    imported project file carrying a ``~`` path is healed on read instead of only
    on re-save. ``expanduser()`` matches the idiom already applied to this same
    value in ``routes/export.py``. Relative-path semantics are otherwise unchanged.
    """

    settings = settings or get_studio_settings()
    if settings.shared_mode:
        root = contain_under_session_workspace(
            session, session_workspace_root(session, settings) / "output", settings
        )
        root.mkdir(parents=True, exist_ok=True)
        return root
    return expand_user_path(session.output_path or default_output_path())


def export_zip_path(
    session: ProjectSession,
    slug: str,
    settings: StudioSettings | None = None,
) -> Path:
    """Resolve where Studio stores the transient package ZIP."""

    settings = settings or get_studio_settings()
    filename = f"{slug}-appbuilder-package.zip"
    if settings.shared_mode:
        root = contain_under_session_workspace(
            session, session_workspace_root(session, settings) / "exports", settings
        )
        root.mkdir(parents=True, exist_ok=True)
        return contain_under_session_workspace(session, root / filename, settings)
    return Path(tempfile.gettempdir()) / filename


def engine_repo_path(
    session: ProjectSession,
    settings: StudioSettings | None = None,
) -> str:
    """Resolve the Engine repository path for invocation.

    Local mode intentionally preserves the user-supplied Step 1 path.  Shared
    mode uses operator configuration only; per-request project values are ignored.
    """

    settings = settings or get_studio_settings()
    if settings.shared_mode:
        configured = os.getenv(ENGINE_REPO_ENV, "").strip()
        return configured or default_edgeforge_repo_path()
    return session.appbuilder_repo_path
