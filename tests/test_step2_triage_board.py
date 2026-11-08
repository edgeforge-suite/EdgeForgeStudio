"""PR-22 acceptance coverage for the Step 2 edge-contract triage board.

Step 2 deliberately represents only edge-contract upstream interfaces. The
REST/OpenAPI source and classification surfaces remain separate because they
do not yet have ``ReadinessItem`` rows.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models.project import ClassifiedEntity, ClassifiedField
from app.services import readiness_view
from tests.session_helpers import reset_session, save_session
from tests.test_readiness_view import _readiness_session

client = TestClient(app)
TEMPLATE = Path(__file__).resolve().parent.parent / "app" / "templates" / "step2_upstream.html"

BOARD_ITEM_NAMES = ["fixed-missing", "xml-warning", "csv-ready", "soap-reference"]
ATTENTION_NAMES = ["fixed-missing"]
WARNING_NAMES = ["xml-warning", "soap-reference"]
READY_NAMES = ["csv-ready"]


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _save_board_session(*, include_rest_sections: bool = False):
    session = _readiness_session()
    if include_rest_sections:
        session.raw_spec_url = "https://example.invalid/openapi.yaml"
        session.classified_entities = [
            ClassifiedEntity(
                name="Account",
                fields=[ClassifiedField(name="accountId", type="string", is_id=True)],
            )
        ]
    save_session(session)
    return session


def _row_window(html: str, name: str) -> str:
    marker = f'data-uxr-row-name="{name}"'
    marker_index = html.index(marker)
    row_marker = '<div class="uxr-board-row" '
    start = html.rindex(row_marker, 0, marker_index)
    next_row = html.find(row_marker, marker_index + len(marker))
    legend = html.index('<div class="uxr-readiness-legend"', marker_index)
    end = min(position for position in (next_row, legend) if position >= 0)
    return html[start:end]


def test_retired_flag_off_value_keeps_default_on_triage_board(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    _save_board_session()

    html = client.get("/upstream").text

    assert 'data-uxr-board="upstream"' in html
    assert 'class="uxr-board-row"' in html
    assert 'data-uxr-filter="state:all"' in html
    assert "uxrInitStep2TriageBoard" in html


def test_flag_on_renders_one_edge_contract_row_each_in_attention_first_order(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _save_board_session()

    html = client.get("/upstream").text

    assert html.count('class="uxr-board-row"') == len(BOARD_ITEM_NAMES)
    for name in BOARD_ITEM_NAMES:
        assert html.count(f'data-uxr-row-name="{name}"') == 1
    assert 'data-uxr-row-name="rest-api"' not in html
    ordered = ATTENTION_NAMES + WARNING_NAMES + READY_NAMES
    positions = [html.index(f'data-uxr-row-name="{name}"') for name in ordered]
    assert positions == sorted(positions)


def test_flag_on_rows_project_readiness_family_and_top_message(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = _save_board_session()
    items = {item.display_name: item for item in readiness_view.items_for_step(session, 2)}

    html = client.get("/upstream").text
    expectations = {
        "fixed-missing": ("FIX", "badge-warning", "Blocked"),
        "xml-warning": ("XML", "badge-warning", "Review"),
        "csv-ready": ("CSV", "badge-ready", "Ready"),
        "soap-reference": ("SOAP", "badge-warning", "Review"),
    }
    for name, (monogram, badge_class, label) in expectations.items():
        window = _row_window(html, name)
        assert f">{monogram}</span>" in window
        assert f'class="badge {badge_class}"' in window
        assert f">{label}</span>" in window
        item = items[name]
        if item.blockers:
            assert item.blockers[0].label in window
        elif item.warnings:
            assert item.warnings[0].label.replace(
                "uploaded artifact content", "pasted artifact content"
            ) in window


def test_flag_on_stats_filter_counts_and_family_chips_match_items(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _save_board_session()

    html = client.get("/upstream").text

    assert 'class="uxr-stat-strip uxr-zone-attn"' in html
    assert 'data-uxr-stat="total">4</strong> upstream contracts' in html
    assert 'data-uxr-stat="ready">1</strong> ready' in html
    assert 'data-uxr-stat="attention">1</strong> need action' in html
    assert 'data-uxr-stat="review">2</strong> need review' in html
    assert 'data-uxr-stat="blockers">1</strong> export blocker' in html
    assert 'class="uxr-chip is-on" aria-pressed="true" data-uxr-filter="state:all"' in html
    for state, count in (("attention", 1), ("review", 2), ("ready", 1)):
        marker = f'data-uxr-filter="state:{state}"'
        window = html[html.index(marker) : html.index(marker) + 140]
        assert f'class="uxr-chip-count">{count}</span>' in window
    for family in ("fixed", "csv", "xml", "soap"):
        assert f'data-uxr-filter="family:{family}"' in html


def test_single_ready_family_omits_review_group_and_family_filter(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = _readiness_session()
    session.upstream_interfaces = [
        interface for interface in session.upstream_interfaces if interface.name == "csv-ready"
    ]
    save_session(session)

    html = client.get("/upstream").text

    assert 'data-uxr-group="review"' not in html
    assert 'data-uxr-filter="state:review"' not in html
    assert 'data-uxr-filter="family:csv"' not in html
    assert '<span class="uxr-chip-sep"' not in html
    assert 'class="uxr-stat-strip uxr-zone-ready"' in html
    focus_html = client.get("/upstream?focus=csv-ready").text
    assert 'class="uxr-stat-strip uxr-zone-ready"' in focus_html


def test_focus_mode_renders_exactly_one_readiness_stat_strip(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _save_board_session()

    board_html = client.get("/upstream").text
    focus_html = client.get("/upstream?focus=csv-ready").text

    assert board_html.count('<div class="uxr-stat-strip') == 1
    assert focus_html.count('<div class="uxr-stat-strip') == 1
    assert 'class="uxr-stat-strip uxr-zone-attn"' in focus_html
    assert 'data-uxr-focus-editor="csv-ready"' in focus_html
    assert 'data-uxr-board="upstream"' in focus_html


def test_rows_join_edit_targets_and_server_metadata(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _save_board_session()

    html = client.get("/upstream").text

    for name in BOARD_ITEM_NAMES:
        assert (
            f'<a href="/upstream?focus={name}" class="uxr-board-edit-btn" '
            f'data-uxr-edit-target="{name}">Edit</a>'
        ) in html
    assert "<code>contracts/account.xsd</code>" in _row_window(html, "xml-warning")
    assert "root AccountMessage" in _row_window(html, "xml-warning")
    assert "<code>upstream/account-layout.yaml</code>" in _row_window(html, "csv-ready")
    assert "delimiter comma (,)" in _row_window(html, "csv-ready")
    assert "uxr-board-row-meta" not in _row_window(html, "fixed-missing")


def test_rest_source_and_classification_remain_separate_from_board(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _save_board_session(include_rest_sections=True)

    html = client.get("/upstream").text

    assert 'data-uxr-row-name="rest-api"' not in html
    assert "Current Contract Source" in html
    assert "https://example.invalid/openapi.yaml" in html
    assert "Classification Results" in html


def test_focus_editor_keeps_existing_deterministic_seed_actions_reachable(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _save_board_session()

    html = client.get("/upstream?focus=csv-ready").text

    assert 'id="edge-contract-inspect-panel"' in html
    assert "function renderUpstreamMappingSeedPatch(panel, names)" in html
    assert "window.EdgeForgeSeedPatch.buildRows" in html
    assert "renderDeterministicSeedPatch(panel" in html


def test_board_js_carries_shipped_regroup_and_conditional_reconciliation_contract():
    template = TEMPLATE.read_text(encoding="utf-8")

    assert "function uxrInitStep2TriageBoard()" in template
    assert "const UXR_CONDITIONAL_CHIPS = [" in template
    assert "const UXR_CONDITIONAL_STATS = [" in template
    assert "const UXR_UPSTREAM_FAMILY_ORDER = ['fixed', 'csv', 'xml', 'soap'];" in template
    assert "document.querySelectorAll('[data-uxr-stat=\"total\"]')" in template
    assert "function uxrSyncFamilyChips()" in template
    assert "if (families.size <= 1)" in template
    assert "familyChips.forEach(chip => chip.remove());" in template
    assert "separator?.remove();" in template
    assert "uxrActiveFamilyFilter = null;" in template
    assert "uxrSyncFamilyChips();" in template
    assert "document.querySelectorAll('[data-uxr-stat-strip]').forEach(strip => {" in template
    assert "strip.classList.toggle('uxr-zone-attn', counts.attention > 0);" in template
    assert "strip.classList.toggle('uxr-zone-ready', counts.attention === 0);" in template
    assert "uxrRegroupBoardRow(row);" in template
    assert "uxrRecomputeStatsAndFilterCounts();" in template
    assert "uxrApplyBoardFilters();" in template
    assert "if (!entry.count)" in template
    assert "chip?.remove();" in template
    assert (
        "uxrUpdateBoardRowFromSaved(data.readiness, previousName, data.board_metadata);"
        in template
    )
    assert "uxrUpdateAmbientAndRail(data);" in template
    assert "document.querySelector('.uxr-board-filters')?.addEventListener('click'" in template
