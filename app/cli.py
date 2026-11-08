"""Console entry points for EdgeForge Studio."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    """Launch the Studio FastAPI app with uvicorn."""
    os.chdir(Path(__file__).resolve().parents[1])
    host = os.environ.get("EDGEFORGE_STUDIO_HOST", "127.0.0.1")
    port = int(os.environ.get("EDGEFORGE_STUDIO_PORT", "8080"))
    reload = _truthy(os.environ.get("EDGEFORGE_STUDIO_RELOAD"))
    uvicorn.run("app.main:app", host=host, port=port, reload=reload)
