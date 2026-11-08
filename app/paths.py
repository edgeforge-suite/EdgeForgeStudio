"""Repository-independent filesystem anchors for packaged Studio assets."""

from __future__ import annotations

from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"
