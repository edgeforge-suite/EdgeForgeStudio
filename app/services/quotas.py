"""Non-destructive lifecycle quota guards for Studio sessions."""

from __future__ import annotations

from pathlib import Path

from app.models.project import ProjectSession
from app.services.ks_workspace import workspace_db_path
from app.services.path_resolver import session_workspace_root
from app.services.settings import StudioSettings, get_studio_settings
from app.services.upload_limits import human_readable_upload_limit


class QuotaExceededError(ValueError):
    """Raised when a Studio lifecycle quota would be exceeded."""


def human_readable_bytes(value: int) -> str:
    return human_readable_upload_limit(value)


def directory_size_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def ensure_session_disk_quota(
    session: ProjectSession,
    *,
    additional_bytes: int = 0,
    settings: StudioSettings | None = None,
) -> None:
    settings = settings or get_studio_settings()
    limit = settings.max_session_disk_bytes
    used = directory_size_bytes(session_workspace_root(session, settings))
    projected = used + max(0, additional_bytes)
    if projected > limit:
        raise QuotaExceededError(
            "Session workspace quota exceeded: "
            f"{human_readable_bytes(projected)} would exceed the "
            f"{human_readable_bytes(limit)} limit."
        )


def ensure_ks_db_quota(
    session: ProjectSession,
    *,
    settings: StudioSettings | None = None,
) -> None:
    settings = settings or get_studio_settings()
    limit = settings.max_ks_db_bytes
    db_path = Path(workspace_db_path(session))
    try:
        used = db_path.stat().st_size if db_path.exists() else 0
    except OSError:
        used = 0
    if used > limit:
        raise QuotaExceededError(
            "Knowledge Workspace database quota exceeded: "
            f"{human_readable_bytes(used)} exceeds the {human_readable_bytes(limit)} limit."
        )
