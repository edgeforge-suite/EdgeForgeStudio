"""PR-24 acceptance tests: Step 4 permanent responsive focus presentation.

Mirrors tests/test_step5_desktop_split.py for the handoff board/editor pair.
A focused route always server-renders the board/editor wrapper. CSS displays
the split at 1200px and wider and hides the board for the supported narrow
full-page focus fallback. The retired refresh/split environment values are
inert; their unset/false/true combinations remain covered as compatibility
inputs rather than active rollout modes.

Fixture note: 2 data handoffs (one warning, one ready) -- the same
warn-no-ddl/ready-one field shapes as `test_step4_triage_board.py`'s own
fixture (already verified there against `readiness_view._handoff_item`), so
the resulting states are known-correct without re-deriving them here.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models.project import DataHandoff, FieldMapping
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)
_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "app" / "templates" / "step4_handoffs.html"
_STUDIO_CSS = Path(__file__).resolve().parent.parent / "app" / "static" / "css" / "studio.css"

_CSRF_META_RE = re.compile(r'(<meta\s+name="edgeforge-csrf-token"\s+content=")[^"]*(")')
_CSRF_FIELD_RE = re.compile(r'(<input type="hidden" name="_edgeforge_csrf_token" value=")[^"]*(")')


def _normalize_csrf(html: str) -> str:
    html = _CSRF_META_RE.sub(r"\1<CSRF>\2", html)
    return _CSRF_FIELD_RE.sub(r"\1<CSRF>\2", html)


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _split_session():
    """2 data handoffs: one warning (missing DDL), one ready -- enough to
    populate the Needs review + Ready board groups without duplicating
    test_step4_triage_board.py's own 4-item fixture."""
    session = get_session()
    session.app_name = "Handoff Desktop Split Fixture"
    session.bounded_context = "handoff-desktop-split-fixture"
    session.app_archetype = "crud"
    session.project_revision = 3
    session.data_handoffs = [
        DataHandoff(
            name="warn-no-ddl",
            field_mappings=[FieldMapping(source="Entity.fieldA", target="col_a")],
        ),
        DataHandoff(
            name="ready-one",
            ddl_content="CREATE TABLE stage_c (col_c VARCHAR(10));",
            field_mappings=[FieldMapping(source="Entity.fieldC", target="col_c")],
        ),
    ]
    save_session(session)
    return session


# ---------------------------------------------------------------------------
# Retired environment values cannot disable the permanent focus presentation.
# ---------------------------------------------------------------------------

def test_retired_split_off_value_still_renders_split_focus(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "false")
    _split_session()

    html = client.get("/handoffs?focus=ready-one").text

    assert 'data-uxr-focus-editor="ready-one"' in html
    assert 'data-uxr-board="handoffs"' in html
    assert 'data-uxr-split="true"' in html


def test_retired_split_env_unset_matches_explicit_false(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.delenv("EDGEFORGE_STUDIO_UX_SPLIT", raising=False)
    _split_session()
    unset_html = _normalize_csrf(client.get("/handoffs?focus=ready-one").text)

    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "false")
    explicit_off_html = _normalize_csrf(client.get("/handoffs?focus=ready-one").text)

    assert unset_html == explicit_off_html


def test_retired_refresh_flag_cannot_disable_split(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "true")
    _split_session()

    html = client.get("/handoffs?focus=ready-one").text
    assert 'data-uxr-split="true"' in html
    assert 'data-uxr-focus-editor="ready-one"' in html
    assert 'data-uxr-board="handoffs"' in html


# ---------------------------------------------------------------------------
# A focused route renders the board and editor in the responsive wrapper.
# ---------------------------------------------------------------------------

def test_focused_route_renders_board_and_editor_together(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "true")
    _split_session()

    html = client.get("/handoffs?focus=ready-one").text

    assert 'data-uxr-split="true"' in html
    assert 'data-uxr-board="handoffs"' in html
    assert 'data-uxr-focus-editor="ready-one"' in html
    for name in ("warn-no-ddl", "ready-one"):
        assert html.count(f'data-uxr-row-name="{name}"') == 1
    assert 'data-uxr-edit-target="ready-one"' in html
    assert 'data-uxr-filter="state:all"' in html
    assert 'data-uxr-filter="state:review"' in html


def test_split_on_right_column_contains_editor_container_and_actions_in_order(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "true")
    _split_session()

    html = client.get("/handoffs?focus=ready-one").text

    board_col = html.index('class="uxr-focus-split-board"')
    board_marker = html.index('data-uxr-board="handoffs"')
    editor_col = html.index('class="uxr-focus-split-editor"')
    editor_marker = html.index('data-uxr-focus-editor="ready-one"')
    container_marker = html.index('id="handoffs-container"')
    save_marker = html.index('data-uxr-save-one')
    step_actions_marker = html.index('data-uxr-step-actions')
    assert (
        board_col < board_marker < editor_col < editor_marker
        < container_marker < save_marker < step_actions_marker
    )


def test_split_on_renders_both_strips_and_css_picks_by_viewport(monkeypatch):
    """Which ambient strip is VISIBLE is viewport-dependent, so Jinja cannot
    decide it: below the split breakpoint the board is hidden and the editor's
    strip is the only one (the supported single-column full-page fallback from
    the approved implementation-design §7.1 amendment); at >=1200px the board's
    richer strip takes over and CSS hides the editor's duplicate. Both are
    therefore in the DOM, with the stylesheet choosing."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "true")
    _split_session()

    html = client.get("/handoffs?focus=ready-one").text

    assert html.count('class="uxr-stat-strip') == 2
    # "ready"/"review" stats only ever exist on the board's own strip -- the
    # editor's 2-stat (total/attention) strip never renders them.
    assert 'data-uxr-stat="ready">' in html
    assert 'data-uxr-stat="review">' in html


def test_saved_row_is_regrouped_and_all_board_counters_recomputed(monkeypatch):
    """Regression for review finding 1 on #255 (P2): the reviewer saved a
    handoff into `ready` and its row stayed under 'Needs review' with the
    board strip and chips still reading Ready=1/Needs review=1.
    uxrUpdateAmbientAndRail() only touches total/attention, so the save
    reconciliation must also regroup the row and recompute the board-only
    counters/chips from the live DOM."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "true")
    _split_session()

    html = client.get("/handoffs").text
    assert 'data-uxr-group="review"' in html
    assert 'data-uxr-group="ready"' in html

    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    updater = template[template.index("function uxrUpdateBoardRowFromSaved"):]
    updater = updater[: updater.index("\n}\n")]
    assert "uxrRegroupBoardRow(row);" in updater
    assert "uxrRecomputeStatsAndFilterCounts();" in updater
    assert "uxrApplyBoardFilters();" in updater
    assert "function uxrEnsureBoardGroup(board, key)" in template


def test_conditional_chips_and_stats_are_created_and_removed_not_just_retexted():
    """Regression for review round 2 finding 1 on #255 (P2): the reviewer moved
    the last warning handoff to Ready and the board kept showing
    'Needs review . 0'. The server gates these controls on a non-zero count, so
    live counts must create/remove them, not just re-text whatever exists."""
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")

    recompute = template[template.index("function uxrRecomputeStatsAndFilterCounts"):]
    recompute = recompute[: recompute.index("\n}\n")]
    assert "uxrSyncConditionalStats(counts);" in recompute
    assert "uxrSyncConditionalChips(counts);" in recompute

    chips = template[template.index("function uxrSyncConditionalChips"):]
    chips = chips[: chips.index("\n}\n")]
    assert "chip.remove();" in chips
    assert "document.createElement('button')" in chips
    assert "uxrResetStateFilterToAll();" in chips

    # Delegated, so chips created after init still respond (PR-16's trap).
    assert "document.querySelector('.uxr-board-filters')?.addEventListener('click', event => {" in template
    assert "document.querySelectorAll('[data-uxr-filter]').forEach(chip => {" not in template

    # On this step the server gates attention AND review (it renders
    # total/ready unconditionally) -- the spec must match that, not Step 5's.
    spec = template[template.index("const UXR_CONDITIONAL_STATS"):]
    spec = spec[: spec.index("];")]
    assert "'attention'" in spec and "'review'" in spec
    assert "'blockers'" not in spec


def test_structurally_unreachable_attention_chip_is_never_created(monkeypatch):
    """_handoff_item only ever yields warning|ready, so the attention count is
    always 0 and the create/remove logic must therefore never bring the
    'Needs action' chip/stat into being -- preserving the triage-board
    needs-action invariant. This is
    exactly why the fix creates on demand rather than rendering stable hidden
    controls: a hidden attention chip here would be permanent dead markup."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "true")
    _split_session()

    html = client.get("/handoffs").text
    assert 'data-uxr-filter="state:attention"' not in html
    assert '<strong data-uxr-stat="attention">' not in html


def test_narrow_split_falls_back_to_single_column_focus_not_a_stacked_board(monkeypatch):
    """The approved implementation-design §7.1 amendment retires PR-18's modal
    because the full-page focus route is the supported accessible fallback. The
    board is server-rendered for every focused route, so below the breakpoint
    it must be HIDDEN -- leaving the pre-PR-17 single-column focus editor --
    rather than stacking above the editor. The shared rule lives in studio.css
    and is asserted in full by the Step-5 companion; here we only pin that Step
    4 routes through the same wrapper class."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "true")
    _split_session()

    html = client.get("/handoffs?focus=ready-one").text

    assert 'class="uxr-focus-split-board"' in html


def test_retired_split_off_value_keeps_both_responsive_strips(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "false")
    _split_session()

    html = client.get("/handoffs?focus=ready-one").text

    assert html.count('class="uxr-stat-strip') == 2
    assert 'data-uxr-stat="ready"' in html
    assert 'data-uxr-stat="review"' in html


def test_split_on_no_focus_is_unchanged_board_mode(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "true")
    _split_session()
    split_on_html = _normalize_csrf(client.get("/handoffs").text)

    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "false")
    split_off_html = _normalize_csrf(client.get("/handoffs").text)

    assert split_on_html == split_off_html
    assert "uxr-focus-split" not in split_on_html


# ---------------------------------------------------------------------------
# Selected-row treatment: is-editing reclaimed only in split+focus mode.
# ---------------------------------------------------------------------------

def test_split_on_focused_row_is_marked_is_editing_others_are_not(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "true")
    _split_session()

    html = client.get("/handoffs?focus=ready-one").text

    assert html.count("uxr-board-row is-editing") == 1
    focused_start = html.index('data-uxr-row-name="ready-one"')
    row_open = html.rindex('<div class="uxr-board-row', 0, focused_start)
    assert html[row_open:focused_start].startswith('<div class="uxr-board-row is-editing"')
    other_start = html.index('data-uxr-row-name="warn-no-ddl"')
    other_open = html.rindex('<div class="uxr-board-row', 0, other_start)
    assert html[other_open:other_start].startswith('<div class="uxr-board-row"')


def test_board_only_mode_never_marks_any_row_is_editing_even_with_split_on(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "true")
    _split_session()

    html = client.get("/handoffs").text
    assert "uxr-board-row is-editing" not in html


# ---------------------------------------------------------------------------
# CSS + static-source guards (shared stylesheet/behavior with Step 5).
# ---------------------------------------------------------------------------

def test_min_width_media_query_is_the_only_one_and_gates_the_split_grid():
    css = _STUDIO_CSS.read_text(encoding="utf-8")
    assert css.count("@media (min-width") == 1
    media_start = css.index("@media (min-width")
    window = css[media_start:media_start + 300]
    assert "min-width: 1200px" in window
    assert "body.ux-refresh .uxr-focus-split {" in window
    assert "display: grid;" in window
    assert "grid-template-columns: 320px minmax(0, 1fr);" in window


def test_split_wrapper_class_is_a_server_render_decision_not_js_driven():
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    script_start = template.index("{% block scripts %}")
    script_block = template[script_start:]
    assert "uxr-focus-split" not in script_block
    assert "data-uxr-split" not in script_block


def test_uxr_split_focus_depends_only_on_focus_route_state():
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "{% set uxr_split_focus = true if focus_name else false %}" in template
    assert "focus_name and ux_split" not in template
