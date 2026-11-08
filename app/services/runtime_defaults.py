"""Runtime-configurable defaults for local Studio development."""

from __future__ import annotations

import json
import os
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from urllib.parse import unquote, urlparse

DEFAULT_EDGEFORGE_PATH_ENV = "EDGEFORGE_STUDIO_DEFAULT_ENGINE_REPO"
DEFAULT_OUTPUT_PATH_ENV = "EDGEFORGE_STUDIO_DEFAULT_OUTPUT_PATH"
DOCKER_MODE_ENV = "EDGEFORGE_STUDIO_DOCKER"
PUBLIC_BASE_URL_ENV = "EDGEFORGE_STUDIO_PUBLIC_BASE_URL"

_DOCKER_EDGEFORGE_PATH = "/workspace/EdgeForge"
_DOCKER_OUTPUT_PATH = "/workspace/data/GeneratedApps"
_DOCKER_PUBLIC_BASE_URL = "http://127.0.0.1:8083"
_PROJECT_DISTRIBUTION = "edgeforge-studio"


def is_docker_runtime() -> bool:
    """Return True when Studio is running in its Docker Compose runtime."""
    value = os.environ.get(DOCKER_MODE_ENV, "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return Path("/.dockerenv").exists()


def is_host_style_path(path: str | None) -> bool:
    """Detect paths that are host-only and unsafe inside Docker Studio."""
    raw = str(path or "").strip()
    lower = raw.lower()
    if not raw:
        return False
    if raw.startswith("~/") or raw == "~":
        return True
    if lower.startswith("/users/") or lower.startswith("/volumes/"):
        return True
    if len(raw) >= 3 and raw[1] == ":" and raw[2] in {"\\", "/"} and raw[0].isalpha():
        return True
    return False


def _is_studio_checkout(path: Path) -> bool:
    return (path / "pyproject.toml").is_file() and (path / "app" / "main.py").is_file()


def _source_checkout_root() -> Path | None:
    """Return the Studio checkout root when this package was installed locally."""
    module_root = Path(__file__).resolve().parents[2]
    if _is_studio_checkout(module_root):
        return module_root

    try:
        direct_url = distribution(_PROJECT_DISTRIBUTION).read_text("direct_url.json")
    except (PackageNotFoundError, FileNotFoundError):
        return None
    if not direct_url:
        return None

    try:
        url = json.loads(direct_url).get("url", "")
    except (TypeError, json.JSONDecodeError):
        return None
    parsed = urlparse(url)
    if parsed.scheme != "file":
        return None

    candidate = Path(unquote(parsed.path)).expanduser()
    if _is_studio_checkout(candidate):
        return candidate.resolve()
    return None


def _sibling_edgeforge_repo_path() -> str:
    """Return the conventional sibling Engine checkout path when discoverable."""
    studio_root = _source_checkout_root()
    if not studio_root:
        return ""
    return str(studio_root.parent / "EdgeForge")


def default_edgeforge_repo_path() -> str:
    """Return the default Engine checkout path for fresh Studio sessions."""
    configured = os.environ.get(DEFAULT_EDGEFORGE_PATH_ENV)
    if configured and not (is_docker_runtime() and is_host_style_path(configured)):
        return configured
    return _DOCKER_EDGEFORGE_PATH if is_docker_runtime() else _sibling_edgeforge_repo_path()


def default_output_path() -> str:
    """Return the default package/app output root for exports."""
    configured = os.environ.get(DEFAULT_OUTPUT_PATH_ENV)
    if configured and not (is_docker_runtime() and is_host_style_path(configured)):
        return configured
    return (
        _DOCKER_OUTPUT_PATH
        if is_docker_runtime()
        else str(Path.home() / "Documents" / "GitHub" / "AppBuilder" / "GeneratedApps")
    )


def docker_public_base_url() -> str:
    """Return the host-visible Studio base URL for Docker proxy links."""
    return os.environ.get(PUBLIC_BASE_URL_ENV, _DOCKER_PUBLIC_BASE_URL).rstrip("/")


def docker_output_path_error(output_path: str | None) -> str | None:
    """Return a user-facing Docker export path error, or None when allowed."""
    if not is_docker_runtime():
        return None
    configured = str(output_path or "").strip()
    if not configured:
        return None
    if is_host_style_path(configured):
        return (
            f"Docker Studio cannot export to host path {configured}. "
            f"Use {default_output_path()} or leave Output Path blank."
        )

    allowed_root = Path(default_output_path())
    try:
        resolved = Path(configured).expanduser().resolve()
        allowed = allowed_root.resolve()
    except OSError:
        return f"Docker Studio cannot export to {configured}. Use {default_output_path()}."
    if resolved == allowed or allowed in resolved.parents:
        return None
    return f"Docker Studio exports must stay under {allowed_root}."
