"""Session workspace retention helpers.

This module is intentionally filesystem-only.  It must not import the KS client
or spawn subprocesses; callers coordinate lifecycle shutdown before cleanup.
"""

from __future__ import annotations

import shutil
from pathlib import Path

DURABLE_SUBDIR = "managed-artifacts"


def _assert_under(base: Path, target: Path) -> None:
    """Raise unless *target* resolves inside *base*."""
    resolved_base = base.expanduser().resolve(strict=False)
    resolved_target = target.expanduser().resolve(strict=False)
    if resolved_target == resolved_base:
        return
    try:
        resolved_target.relative_to(resolved_base)
    except ValueError as exc:
        raise ValueError("Retention cleanup target is outside the workspace base.") from exc


def remove_workspace_preserving_durable(
    workspace_root: Path,
    *,
    workspaces_base: Path,
) -> None:
    """Remove workspace contents while preserving ``managed-artifacts``."""
    _assert_under(workspaces_base, workspace_root)
    if not workspace_root.exists():
        return

    durable_dir = workspace_root / DURABLE_SUBDIR
    if durable_dir.exists():
        for child in workspace_root.iterdir():
            if child == durable_dir:
                continue
            _remove_path(child)
        return

    shutil.rmtree(workspace_root)


def clean_workspace_contents_preserving_durable(
    workspace_root: Path,
    *,
    workspaces_base: Path,
) -> None:
    """Clean a workspace in place while preserving ``managed-artifacts``."""
    _assert_under(workspaces_base, workspace_root)
    workspace_root.mkdir(parents=True, exist_ok=True)
    durable_dir = workspace_root / DURABLE_SUBDIR
    for child in workspace_root.iterdir():
        if child == durable_dir:
            continue
        _remove_path(child)


def has_durable_artifacts(workspace_root: Path) -> bool:
    return (workspace_root / DURABLE_SUBDIR).exists()


def remove_workspace_fully(
    workspace_root: Path,
    *,
    workspaces_base: Path,
) -> None:
    """Remove a workspace including durable artifacts for explicit deletion."""
    _assert_under(workspaces_base, workspace_root)
    if workspace_root.exists():
        shutil.rmtree(workspace_root)


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
