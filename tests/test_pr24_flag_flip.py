from pathlib import Path

from app.main import app

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "app" / "templates"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_refresh_rollout_environment_switches_are_retired_from_runtime() -> None:
    runtime_source = "\n".join(
        _source(path)
        for root in (ROOT / "app" / "routes", ROOT / "app" / "services")
        for path in root.glob("*.py")
    )

    assert "EDGEFORGE_STUDIO_UX_REFRESH" not in runtime_source
    assert "EDGEFORGE_STUDIO_UX_SPLIT" not in runtime_source


def test_step_templates_have_no_legacy_refresh_or_split_branches() -> None:
    for name in (
        "base.html",
        "step2_upstream.html",
        "step3_entities.html",
        "step4_handoffs.html",
        "step5_downstream.html",
        "step6_rules.html",
        "step7_review.html",
    ):
        source = _source(TEMPLATES / name)
        assert "{% if ux_refresh" not in source
        assert "{% if not ux_refresh" not in source
        assert "{% if ux_split" not in source


def test_focused_steps_no_longer_call_wholesale_browser_saves() -> None:
    handoffs = _source(TEMPLATES / "step4_handoffs.html")
    downstream = _source(TEMPLATES / "step5_downstream.html")

    assert "postJSON('/handoffs/save'" not in handoffs
    assert "function saveAll()" not in handoffs
    assert "postJSON('/downstream/save'" not in downstream
    assert "function saveAll()" not in downstream


def test_confirm_replace_seed_handlers_are_removed() -> None:
    upstream = _source(TEMPLATES / "step2_upstream.html")
    downstream = _source(TEMPLATES / "step5_downstream.html")

    assert "seedEdgeFieldMappings(" not in upstream
    assert "seedEdgeFieldMappingsFromNames(" not in upstream
    assert "seedDownstreamFileMappings(" not in downstream
    assert "seedDownstreamFileMappingsFromNames(" not in downstream
    assert "populateFixedWidthLayoutRowsFromInspection(" not in downstream


def test_pr24_bumps_only_the_unreleased_studio_minor_version() -> None:
    assert app.version == "4.2.0"
    assert 'version = "4.2.0"' in _source(ROOT / "pyproject.toml")
