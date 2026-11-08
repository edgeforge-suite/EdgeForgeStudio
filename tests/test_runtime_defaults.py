"""Runtime-default path behavior."""

from __future__ import annotations

import json
from pathlib import Path

from app.services import runtime_defaults


def _make_studio_checkout(root: Path) -> Path:
    studio = root / "EdgeForgeStudio"
    (studio / "app").mkdir(parents=True)
    (studio / "pyproject.toml").write_text("[project]\nname='edgeforge-studio'\n", encoding="utf-8")
    (studio / "app" / "main.py").write_text("app = None\n", encoding="utf-8")
    return studio


def test_default_engine_path_uses_direct_url_when_installed(monkeypatch, tmp_path):
    studio = _make_studio_checkout(tmp_path)
    monkeypatch.setattr(
        runtime_defaults,
        "__file__",
        str(tmp_path / "venv" / "lib" / "python3.11" / "site-packages" / "app" / "services" / "runtime_defaults.py"),
    )

    class FakeDistribution:
        def read_text(self, name: str) -> str:
            assert name == "direct_url.json"
            return json.dumps({"url": studio.as_uri()})

    monkeypatch.setattr(runtime_defaults, "distribution", lambda _: FakeDistribution())

    assert runtime_defaults.default_edgeforge_repo_path() == str(tmp_path / "EdgeForge")


def test_default_engine_path_requires_override_when_checkout_is_not_discoverable(monkeypatch, tmp_path):
    installed_module = tmp_path / "venv" / "lib" / "python3.11" / "site-packages" / "app" / "services" / "runtime_defaults.py"
    monkeypatch.setattr(runtime_defaults, "__file__", str(installed_module))

    class FakeDistribution:
        def read_text(self, name: str) -> str | None:
            assert name == "direct_url.json"
            return None

    monkeypatch.setattr(runtime_defaults, "distribution", lambda _: FakeDistribution())

    assert runtime_defaults.default_edgeforge_repo_path() == ""
