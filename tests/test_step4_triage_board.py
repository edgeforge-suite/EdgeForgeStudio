"""PR-08 acceptance tests: Step 4 data handoff triage board (collapse-only).

Covers the build packet's §6 acceptance bar: one summary row per
`readiness_view.items_for_step(session, 4)` item (staging monogram, name,
table/column/mapping fact, coverage tag, top warning line, status pill, Edit
button), warning-state items grouped under "Needs review", ambient stats
strip, state-only filter chips (no family chips -- every handoff item's
family is always "staging"), collapse-only expand-one-at-a-time over the
untouched legacy `.handoff-card` editor. Board half only -- the split-panel
focus editor is PR-14.

Unlike PR-07's Step 5 board, `_handoff_items()` applies no type filter --
every handoff in `session.data_handoffs` gets exactly one row, so there is no
"unrepresented item" edge case to guard against here.

Fixture note (mirrors `tests/test_step5_triage_board.py`'s own convention):
every state/fact combination below was verified directly against
`readiness_view._handoff_item` / `handoffs_route._handoff_board_fact` (via a
throwaway probe script constructing each fixture handoff and printing its
resolved `ReadinessItem` and board fact) before writing these assertions --
not hand-predicted:
  warn-no-ddl=warning (missing-ddl only), warn-no-mappings=warning
  (missing-field-mappings only), ready-one=ready, ready-two=ready.

`blocks_export`/`needs_action`/`draft` are NOT reachable through any real
`DataHandoff` field combination today -- `_handoff_item` (readiness_view.py)
only ever returns `STATE_WARNING` or `STATE_READY`; it has no branch that
produces any other state. This is a pre-existing characteristic of
`readiness_view.py`, out of scope for this PR (which touches neither that
file's state logic). `test_synthetic_attention_and_draft_states_render_correctly`
below proves the *template* still handles the full state vocabulary
generically, by injecting synthetic items at the route's call site -- it does
not claim any of the three states are reachable via genuine session data
today.
"""
from __future__ import annotations

import json
import re as _re
from pathlib import Path as _Path

from fastapi.testclient import TestClient
from markupsafe import escape as _html_escape

import app.routes.handoffs as handoffs_route
from app.main import app
from app.models.project import DataHandoff, FieldMapping
from app.services.project_file_service import (
    deserialize_project,
    serialize_project,
    snapshot_session,
)
from app.services.readiness_view import Cov, ReadinessItem, Ref
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)

_TEMPLATE_PATH = (
    _Path(__file__).resolve().parent.parent / "app" / "templates" / "step4_handoffs.html"
)

BOARD_ITEM_NAMES = ["warn-no-ddl", "warn-no-mappings", "ready-one", "ready-two"]
WARNING_NAMES = ["warn-no-ddl", "warn-no-mappings"]
READY_NAMES = ["ready-one", "ready-two"]


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _triage_board_session():
    """4 data handoffs: one warning with no DDL at all, one warning with DDL
    but no field mappings, and 2 genuinely ready (DDL + mappings present, all
    mapping targets resolve to real DDL columns)."""
    session = get_session()
    session.app_name = "Handoff Triage Board Fixture"
    session.bounded_context = "handoff-triage-board-fixture"
    session.app_archetype = "crud"
    session.data_handoffs = [
        DataHandoff(
            name="warn-no-ddl",
            field_mappings=[FieldMapping(source="Entity.fieldA", target="col_a")],
        ),
        DataHandoff(
            name="warn-no-mappings",
            ddl_content="CREATE TABLE stage_b (col_b VARCHAR(20));",
        ),
        DataHandoff(
            name="ready-one",
            ddl_content="CREATE TABLE stage_c (col_c VARCHAR(10));",
            field_mappings=[FieldMapping(source="Entity.fieldC", target="col_c")],
        ),
        DataHandoff(
            name="ready-two",
            table_name="stage_d",
            ddl_content="CREATE TABLE stage_d (col_d1 VARCHAR(10), col_d2 INT);",
            field_mappings=[
                FieldMapping(source="Entity.fieldD1", target="col_d1"),
                FieldMapping(source="Entity.fieldD2", target="col_d2"),
            ],
        ),
    ]
    save_session(session)
    return session


# ---------------------------------------------------------------------------
# Flag-off: zero board markers; legacy cards/behavior unchanged.
# ---------------------------------------------------------------------------

def test_retired_flag_off_value_keeps_default_on_triage_board(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    _triage_board_session()

    response = client.get("/handoffs")
    html = response.text

    assert response.status_code == 200
    assert 'data-uxr-board="handoffs"' in html
    assert "uxr-stat-strip" in html
    assert "uxrInitStep4TriageBoard" in html
    js_start = html.index("const existing = ") + len("const existing = ")
    # Not a naive index(";", ...) scan -- DDL content legitimately contains
    # its own semicolons (e.g. "CREATE TABLE ... );"), which would truncate
    # the JSON before its real end. raw_decode parses just the JSON value.
    existing_data, _ = json.JSONDecoder().raw_decode(html[js_start:])
    assert {d["name"] for d in existing_data} == set(BOARD_ITEM_NAMES)


# ---------------------------------------------------------------------------
# Flag-on: one row per item, warning-first grouping, correct pill/fact.
# ---------------------------------------------------------------------------

def test_flag_on_renders_exactly_one_row_per_item_grouped_correctly(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()

    response = client.get("/handoffs")
    html = response.text

    assert response.status_code == 200
    assert html.count('class="uxr-board-row"') == len(BOARD_ITEM_NAMES)
    for name in BOARD_ITEM_NAMES:
        assert html.count(f'data-uxr-row-name="{name}"') == 1

    needs_review_heading = html.index(">Needs review</div>")
    ready_heading = html.index(">Ready</div>")
    assert needs_review_heading < ready_heading, (
        "warning items must be grouped under 'Needs review', which must "
        "render before the 'Ready' group"
    )
    for name in WARNING_NAMES:
        row_pos = html.index(f'data-uxr-row-name="{name}"')
        assert needs_review_heading < row_pos < ready_heading, (
            f"{name}: warning-state row must render between the 'Needs "
            "review' and 'Ready' headings, not under 'Ready'"
        )
    for name in READY_NAMES:
        row_pos = html.index(f'data-uxr-row-name="{name}"')
        assert row_pos > ready_heading, f"{name}: ready-state row must render under 'Ready'"


def test_flag_on_needs_action_group_stat_and_filter_never_render(monkeypatch):
    """blocks_export/needs_action are structurally unreachable through any
    real DataHandoff field combination today (see module docstring). The
    "Needs action" group/stat/chip must simply never appear for genuine
    session data -- expected, not a bug."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/handoffs").text

    # Scoped to the rendered heading rather than a bare "Needs action" page
    # scan -- the same false-positive class described just below. PR-17's
    # uxrRegroupBoardRow() needs the group labels as JS constants
    # (UXR_BOARD_GROUPS), so that literal now ships inside the always-present
    # <script> on every flag-on page regardless of which groups render.
    # data-uxr-group is only ever emitted on a real server-rendered heading.
    assert 'data-uxr-group="attention"' not in html
    assert ">Needs action</div>" not in html
    # A bare 'data-uxr-stat="attention"' substring scan would also match
    # uxrUpdateAmbientAndRail's always-present JS selector
    # (document.querySelectorAll('[data-uxr-stat="attention"]')), which loads
    # on every flag-on page regardless of whether any handoff is actually in
    # an attention state (see PR-17a's fix to that function, which used to
    # dodge exactly this assertion with a string-concat instead of scoping
    # the check -- the same false-positive class the neighboring
    # test_flag_on_board_and_strip_omitted_entirely_when_no_handoffs already
    # warns about for 'uxr-board'). The fuller markup fragment isolates the
    # server-rendered stat span this test actually cares about.
    assert '<strong data-uxr-stat="attention">' not in html
    assert 'data-uxr-filter="state:attention"' not in html
    # Scoped for the same reason: "uxr-board-group-attn" is also the className
    # in PR-17's UXR_BOARD_GROUPS JS constant, so a bare scan matches the
    # script. The class only styles a real heading when applied to a rendered
    # <div>, which the data-uxr-group assertion above already excludes.
    assert '<div class="uxr-board-group uxr-board-group-attn"' not in html


def test_flag_on_pill_text_and_badge_class_match_state_mapping(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/handoffs").text

    ordered_names = WARNING_NAMES + READY_NAMES
    positions = [html.index(f'data-uxr-row-name="{n}"') for n in ordered_names]
    assert positions == sorted(positions)
    windows = {}
    for i, name in enumerate(ordered_names):
        start = positions[i]
        end = positions[i + 1] if i + 1 < len(positions) else len(html)
        windows[name] = html[start:end]

    expectations = {
        "warn-no-ddl": ("badge-warning", "Review DDL"),
        "warn-no-mappings": ("badge-warning", "Review DDL"),
        "ready-one": ("badge-ready", "Ready"),
        "ready-two": ("badge-ready", "Ready"),
    }
    for name, (badge_class, label) in expectations.items():
        window = windows[name]
        assert f'class="badge {badge_class}"' in window, f"{name}: expected badge class {badge_class}"
        assert f">{label}</span>" in window, f"{name}: expected pill text {label!r}"


def test_flag_on_warning_line_shows_top_warning_for_warning_state_items(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = _triage_board_session()
    html = client.get("/handoffs").text

    items_by_name = {i.display_name: i for i in handoffs_route.readiness_view.items_for_step(session, 4)}
    for name in WARNING_NAMES:
        # Jinja autoescapes the label's own quote marks (the label quotes the
        # handoff name, e.g. "'warn-no-ddl': no DDL provided") into &#39; --
        # compare against the same escaped form the template actually emits.
        expected_label = str(_html_escape(items_by_name[name].warnings[0].label))
        row_start = html.index(f'data-uxr-row-name="{name}"')
        window = html[row_start:row_start + 1200]
        assert f'<div class="uxr-board-row-warning">{expected_label}</div>' in window


def test_flag_on_ready_rows_show_no_warning_or_blocker_line(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/handoffs").text

    for name in READY_NAMES:
        row_start = html.index(f'data-uxr-row-name="{name}"')
        row_end = html.index(f'data-uxr-edit-target="{name}"', row_start)
        window = html[row_start:row_end]
        assert "uxr-board-row-warning" not in window
        assert "uxr-board-row-blocker" not in window


def test_flag_on_family_monogram_tile_is_staging_for_every_row(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/handoffs").text

    for name in BOARD_ITEM_NAMES:
        idx = html.index(f'data-uxr-row-name="{name}"')
        window = html[idx:idx + 400]
        assert "uxr-fam-staging" in window
        assert ">STG</span>" in window
        assert 'aria-label="Staging / Handoff"' in window


def test_flag_on_no_family_filter_chips_ever_render(monkeypatch):
    """Every handoff item's family is always 'staging' (build packet §1) --
    unlike Step 5's multi-family board, this board must never render a family
    filter chip or the chip separator."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/handoffs").text

    assert 'data-uxr-filter="family:' not in html
    assert "uxr-chip-sep" not in html


def test_flag_on_no_export_blockers_stat_ever_renders(monkeypatch):
    """export_blocking is always False for handoff items (build packet §1) --
    unlike Step 5's board, this board must never render a permanently-zero
    'export blocker(s)' stat."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/handoffs").text

    assert 'data-uxr-stat="blockers"' not in html
    assert "export blocker" not in html


def test_flag_on_ambient_stats_strip_shows_correct_counts(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/handoffs").text

    marker_idx = html.index("data-uxr-stat-strip")
    strip_start = html.rindex('<div class="uxr-stat-strip', 0, marker_idx)
    strip_end = html.index("</div>", strip_start)
    strip = html[strip_start:strip_end]
    assert "uxr-zone-ready" in strip, "no attention items -> ready tint, not attn tint"
    assert "uxr-zone-attn" not in strip
    assert 'data-uxr-stat="total">4</strong> data handoffs' in strip
    assert 'data-uxr-stat="ready">2</strong> ready' in strip
    assert 'data-uxr-stat="review">2</strong> need review' in strip
    assert 'data-uxr-stat="attention"' not in strip


def test_flag_on_filter_chips_render_with_correct_counts_and_default_state(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/handoffs").text

    assert (
        '<button type="button" class="uxr-chip is-on" aria-pressed="true" '
        'data-uxr-filter="state:all">All &middot; <span class="uxr-chip-count">4</span></button>' in html
    )
    assert (
        'aria-pressed="false" data-uxr-filter="state:review">Needs review &middot; '
        '<span class="uxr-chip-count">2</span></button>' in html
    )
    assert (
        'aria-pressed="false" data-uxr-filter="state:ready">Ready &middot; '
        '<span class="uxr-chip-count">2</span></button>' in html
    )
    assert 'data-uxr-filter="state:attention"' not in html


def test_flag_on_edit_button_target_matches_handoff_name_join_key(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/handoffs").text
    for name in BOARD_ITEM_NAMES:
        assert f'data-uxr-edit-target="{name}"' in html
        # PR-17a item 6: Edit must be a real <a href> link, not a
        # JS-navigated <button> -- so it is natively dirty-guardable and
        # keyboard-navigable (mirrors Step 2's already-correct precedent).
        assert (
            f'<a href="/handoffs?focus={name}" class="uxr-board-edit-btn" '
            f'data-uxr-edit-target="{name}">Edit</a>'
        ) in html


def test_edit_control_typography_is_pinned_not_inherited_from_the_tag():
    """PR-17a review (#254, P2): the rule set font-size/font-weight but never
    font-family or line-height, so the TAG supplied them -- a <button> took the
    UA form-control defaults (Arial / line-height:normal, 28px tall) while the
    <a> that replaced it inherits the page (system stack / line-height:1.5 =
    18px), rendering 32px. Pin both so the control's box is tag-independent and
    font-independent: line-height:14px + 12px padding + 2px border = the same
    28px border-box the button had. Guards against a silent re-regression if
    either declaration is dropped.
    """
    css = (
        _Path(__file__).resolve().parent.parent / "app" / "static" / "css" / "studio.css"
    ).read_text(encoding="utf-8")
    start = css.index("body.ux-refresh .uxr-board-edit-btn {")
    rule = css[start:css.index("}", start)]

    assert "font-family: inherit;" in rule
    assert "line-height: 14px;" in rule
    assert "text-decoration: none;" in rule
    # The box math the 28px parity depends on -- if any of these change, the
    # line-height above must be re-derived against the button it replaced.
    assert "padding: 6px 12px;" in rule
    assert "border: 1px solid var(--border-strong);" in rule
    assert "font-size: 12px;" in rule


def test_flag_on_all_rows_render_without_pagination_or_pre_expansion(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/handoffs").text

    assert html.count('class="uxr-board-row"') == len(BOARD_ITEM_NAMES)
    assert "uxr-board-row hidden" not in html
    assert "uxr-board-row is-editing" not in html
    assert "pagination" not in html.lower()


def test_flag_on_board_and_strip_omitted_entirely_when_no_handoffs(monkeypatch):
    """The board/strip markup itself must be absent with zero handoffs --
    the always-present page JS (e.g. the `.uxr-board-row` selector string
    inside uxrCollapseExpandedCard) legitimately still loads regardless, so
    this checks the specific markup markers, not a blanket "uxr-board"
    substring scan which would false-positive on that JS text."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = get_session()
    session.app_name = "No Handoffs"
    session.bounded_context = "no-handoffs"
    session.app_archetype = "crud"
    session.data_handoffs = []
    save_session(session)

    html = client.get("/handoffs").text
    assert 'data-uxr-board="handoffs"' not in html
    assert 'class="uxr-board-row"' not in html
    # Scoped to the rendered class attribute for exactly the reason in the
    # docstring above: PR-17's uxrBoardStatStrip() resolves the board's strip
    # via hasAttribute('data-uxr-stat-strip'), so that literal now ships in the
    # always-present JS and a bare attribute scan false-positives on it.
    assert 'class="uxr-stat-strip' not in html


# ---------------------------------------------------------------------------
# Table-name / column / mapping fact (`_handoff_board_fact`) -- display only.
# ---------------------------------------------------------------------------

def test_flag_on_row_shows_table_name_column_and_mapping_fact(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/handoffs").text

    expectations = {
        "warn-no-mappings": "1 col · 0/1 mapped",
        "ready-one": "1 col · 1/1 mapped",
        "ready-two": "stage_d · 2 cols · 2/2 mapped",
    }
    for name, fact in expectations.items():
        row_start = html.index(f'data-uxr-row-name="{name}"')
        window = html[row_start:row_start + 1000]
        assert 'class="uxr-board-row-meta"' in window, f"{name}: expected a meta line"
        assert f"<code>{fact}</code>" in window, f"{name}: expected fact {fact!r}"


def test_flag_on_row_omits_meta_line_when_no_ddl_to_derive_a_fact_from(monkeypatch):
    """warn-no-ddl has no ddl_content -- the meta line must be honestly
    absent, never a bogus '0 cols' line."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/handoffs").text

    row_start = html.index('data-uxr-row-name="warn-no-ddl"')
    row_end = html.index('data-uxr-edit-target="warn-no-ddl"', row_start)
    window = html[row_start:row_end]
    assert "uxr-board-row-meta" not in window
    assert "cols" not in window
    assert "mapped" not in window


def test_flag_on_row_shows_coverage_tag_and_manifest_ref_capability(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/handoffs").text

    expectations = {
        "warn-no-ddl": "1/2 handoff requirements",
        "warn-no-mappings": "1/2 handoff requirements",
        "ready-one": "2/2 handoff requirements",
        "ready-two": "2/2 handoff requirements",
    }
    for name, tag in expectations.items():
        row_start = html.index(f'data-uxr-row-name="{name}"')
        window = html[row_start:row_start + 1000]
        assert f'<span class="uxr-board-tag">{tag}</span>' in window
        assert '<span class="uxr-board-cap">MANIFEST REF</span>' in window


# ---------------------------------------------------------------------------
# Template-level coverage for states not reachable via genuine session
# fixtures today (see module docstring).
# ---------------------------------------------------------------------------

def test_synthetic_attention_and_draft_states_render_correctly(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()

    blocked_item = ReadinessItem(
        item_id="handoff:blocked-example",
        item_kind="handoff",
        family="staging",
        display_name="blocked-example",
        state="blocks_export",
        export_blocking=True,
        blockers=[Ref(code="synthetic-blocker", label="Synthetic export blocker")],
        coverage=[Cov(label="Handoff requirements", complete=0, total=2)],
    )
    needs_action_item = ReadinessItem(
        item_id="handoff:needs-action-example",
        item_kind="handoff",
        family="staging",
        display_name="needs-action-example",
        state="needs_action",
        export_blocking=False,
        blockers=[Ref(code="synthetic-needs-action", label="Synthetic needs-action blocker")],
        coverage=[Cov(label="Handoff requirements", complete=1, total=2)],
    )
    draft_item = ReadinessItem(
        item_id="handoff:draft-example",
        item_kind="handoff",
        family="staging",
        display_name="draft-example",
        state="draft",
        export_blocking=False,
        coverage=[Cov(label="Handoff requirements", complete=1, total=2)],
    )
    original = handoffs_route.readiness_view.items_for_step

    def _patched(session, step):
        return [*original(session, step), blocked_item, needs_action_item, draft_item]

    monkeypatch.setattr(handoffs_route.readiness_view, "items_for_step", _patched)

    html = client.get("/handoffs").text

    attn_heading = html.index(">Needs action</div>")
    review_heading = html.index(">Needs review</div>")
    ready_heading = html.index(">Ready</div>")
    assert attn_heading < review_heading < ready_heading

    blocked_start = html.index('data-uxr-row-name="blocked-example"')
    window = html[blocked_start:blocked_start + 700]
    assert 'data-uxr-row-state="blocks_export"' in window
    assert 'class="badge badge-warning"' in window
    assert ">Blocked</span>" in window
    assert '<div class="uxr-board-row-blocker">Synthetic export blocker</div>' in window
    assert attn_heading < blocked_start < review_heading

    needs_action_start = html.index('data-uxr-row-name="needs-action-example"')
    window = html[needs_action_start:needs_action_start + 700]
    assert 'data-uxr-row-state="needs_action"' in window
    assert ">Needs action</span>" in window
    assert '<div class="uxr-board-row-blocker">Synthetic needs-action blocker</div>' in window
    assert attn_heading < needs_action_start < review_heading

    draft_start = html.index('data-uxr-row-name="draft-example"')
    window = html[draft_start:draft_start + 700]
    assert 'data-uxr-row-state="draft"' in window
    assert 'class="badge badge-draft"' in window
    assert ">Draft</span>" in window
    assert draft_start > ready_heading


# ---------------------------------------------------------------------------
# Grep-guards: the new code never re-derives/recomputes readiness, and never
# invents bookkeeping this board doesn't need.
# ---------------------------------------------------------------------------

def test_new_js_never_hardcodes_readiness_status_strings():
    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    js_start = html.index("const uxrBoardItemNames")
    js_end = html.index("</script>", js_start)
    js_block = html[js_start:js_end]
    for banned in ("Ready to export", "Incomplete", "Reference only"):
        assert banned not in js_block, f"new JS must not hardcode readiness string {banned!r}"


def test_new_board_jinja_never_rederives_state_from_row_status():
    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    board_start = html.index("{% set uxr_h_items")
    board_end = html.index('<div id="handoffs-container"')
    board_block = html[board_start:board_end]
    assert "row.status" not in board_block
    assert "Ready to export" not in board_block
    assert "Reference only" not in board_block
    assert "item.state" in board_block


def test_no_intentionally_removed_count_bookkeeping_invented():
    """Build packet §5b: no `intentionallyRemovedCount`-equivalent mechanism
    exists for handoffs -- Step 5's version is specific to `saveAll()`'s
    guard, which has no Step-4 counterpart to preserve."""
    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "intentionallyRemovedCount" not in html


def test_new_board_js_never_calls_unrelated_existing_function_internals():
    """Build packet §5i: the new board JS may only touch addHandoff's dataset
    markers and the Remove button's onclick (both covered by dedicated tests
    below) -- it must never call into the DDL/column-builder machinery."""
    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    js_start = html.index("const uxrBoardItemNames")
    js_end = html.index("</script>", js_start)
    js_block = html[js_start:js_end]
    for banned in (
        "addColumnRow(", "onTypeChange(", "getColumnsFromCard(",
        "syncManualDdlAuthority(", "parseDdlToColumns(", "addMappingRowEl(", "saveAll(",
    ):
        assert banned not in js_block, f"new board JS must not call {banned!r}"


# ---------------------------------------------------------------------------
# Independent-review lesson from PR-07 (#243), applied proactively here:
# card lookup must use a stable identity, not the live (user-editable)
# .h-name input value -- renaming an expanded handoff must not break
# collapse/expand-one-at-a-time.
# ---------------------------------------------------------------------------

def test_add_handoff_captures_stable_original_name_at_restore_time():
    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    restore_block_start = html.index("if (data) {")
    restore_block_end = html.index("\n  }", restore_block_start)
    restore_block = html[restore_block_start:restore_block_end]
    assert "card.dataset.restoredHandoff = 'true'" in restore_block
    assert "card.dataset.uxrOriginalName = data.name" in restore_block, (
        "addHandoff() must capture the original name once, at restore time, "
        "into a stable attribute the board's own bookkeeping can rely on"
    )


def test_card_lookup_matches_stable_attribute_not_live_input_value():
    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    js_start = html.index("const uxrBoardItemNames")
    js_end = html.index("</script>", js_start)
    js_block = html[js_start:js_end]

    find_fn_start = js_block.index("function uxrFindHandoffCardByName")
    find_fn_end = js_block.index("\n}", find_fn_start)
    find_fn = js_block[find_fn_start:find_fn_end]
    assert "dataset.uxrOriginalName" in find_fn
    assert "querySelector('.h-name')" not in find_fn, (
        "uxrFindHandoffCardByName must not match on the live, user-editable "
        ".h-name input value -- that breaks the moment someone renames the "
        "handoff inside an expanded card (the exact bug PR-07 shipped and "
        "had to fix after review)"
    )

    init_fn_start = js_block.index("function uxrInitStep4TriageBoard")
    hide_loop_end = js_block.index("});", init_fn_start)
    hide_loop = js_block[init_fn_start:hide_loop_end]
    assert "dataset.uxrOriginalName" in hide_loop
    assert "querySelector('.h-name')" not in hide_loop, (
        "the initial collapse-by-default loop must also key off the stable "
        "attribute, consistent with uxrFindHandoffCardByName"
    )


def test_remove_handoff_card_captures_name_before_removal_and_delegates():
    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    fn_start = html.index("function removeHandoffCard")
    fn_end = html.index("\n}", fn_start)
    fn_body = html[fn_start:fn_end]
    assert "card.dataset.uxrOriginalName" in fn_body, (
        "must capture the stable identity BEFORE card.remove() detaches it"
    )
    assert _re.search(r"card\.remove\(\).*uxrHandleBoardTrackedCardRemoved", fn_body, _re.DOTALL), (
        "must call the board-reconciliation handler after removing the card, "
        "and only when this was a board-tracked (restored) card"
    )


def test_board_tracked_card_removed_handler_reconciles_expansion_row_and_counts():
    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    js_start = html.index("const uxrBoardItemNames")
    js_end = html.index("</script>", js_start)
    js_block = html[js_start:js_end]

    fn_start = js_block.index("function uxrHandleBoardTrackedCardRemoved")
    fn_end = js_block.index("\n}", fn_start)
    fn_body = js_block[fn_start:fn_end]
    assert "uxrExpandedName = null" in fn_body, (
        "must clear the expanded-name tracker when the removed card was the expanded one"
    )
    assert ".remove()" in fn_body, "must remove the now-orphaned board row from the DOM"
    assert "uxrRecomputeStatsAndFilterCounts()" in fn_body
    assert "uxrApplyBoardFilters()" in fn_body, (
        "must re-run filtering so a group left with zero rows hides itself"
    )


def test_recompute_stats_derives_counts_from_live_dom_not_a_running_counter():
    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    js_start = html.index("const uxrBoardItemNames")
    js_end = html.index("</script>", js_start)
    js_block = html[js_start:js_end]

    fn_start = js_block.index("function uxrRecomputeStatsAndFilterCounts")
    fn_end = js_block.index("\n}", fn_start)
    fn_body = js_block[fn_start:fn_end]
    assert "querySelectorAll('.uxr-board-row')" in fn_body
    for key in ("data-uxr-stat=", "uxr-chip-count"):
        assert key in fn_body

    # PR-17a hardening: today only one [data-uxr-stat] strip renders at a
    # time (focus-editor and board strips are mutually exclusive), so a
    # singular querySelector was safe -- PR-17 renders both together, and a
    # singular lookup would silently patch one strip and leave the other
    # stale. A no-op today; correct once PR-17 ships.
    assert "document.querySelectorAll(`[data-uxr-stat=\"${key}\"]`)" in fn_body
    assert "document.querySelector(`[data-uxr-stat=" not in fn_body


def test_ambient_updater_hardened_to_queryselectorall_with_no_concat_evasion():
    """PR-17a §3: uxrUpdateAmbientAndRail's total/attention stat lookups used
    a singular querySelector for the same reason as
    uxrRecomputeStatsAndFilterCounts above -- hardened to
    querySelectorAll + forEach (a no-op today, correct once PR-17 renders the
    board alongside the focus editor).

    The attention lookup specifically used to read
    `'[data-uxr-stat=' + '"attention"]'` -- a string concatenation that
    existed only to dodge test_flag_on_needs_action_group_stat_and_filter_
    never_render's (and test_flag_on_stat_strip_and_filter_chips_carry_
    stable_count_hooks's) whole-page substring scan for 'data-uxr-stat=
    "attention"', since this function's source is always present in flag-on
    markup regardless of whether any handoff is actually in an attention
    state. Those two tests now scope around the always-present JS instead
    (matching '<strong data-uxr-stat="attention">', the actual server-
    rendered fragment) -- this line is written plainly, honestly satisfying
    rather than evading the check."""
    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    fn_start = html.index("function uxrUpdateAmbientAndRail")
    fn_end = html.index("\n}", fn_start)
    fn_body = html[fn_start:fn_end]

    assert "'[data-uxr-stat=' + '\"attention\"]'" not in fn_body, (
        "no string-concat evasion of the source-grep assertion this line "
        "used to dodge -- write the selector plainly"
    )
    assert "document.querySelectorAll('[data-uxr-stat=\"total\"]')" in fn_body
    assert "document.querySelectorAll('[data-uxr-stat=\"attention\"]')" in fn_body
    assert "document.querySelector('[data-uxr-stat=" not in fn_body, (
        "a singular lookup would silently patch only one of the two "
        "simultaneously-rendered strips once PR-17 renders the board "
        "alongside the focus editor"
    )


# ---------------------------------------------------------------------------
# Independent-review lesson from PR-07 (#243): active filter state must not
# be color-only -- aria-pressed must be present initially and kept in sync.
# ---------------------------------------------------------------------------

def test_filter_chips_have_aria_pressed_matching_initial_on_state(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/handoffs").text

    assert 'class="uxr-chip is-on" aria-pressed="true"' in html
    filters_start = html.index('class="uxr-board-filters"')
    filters_end = html.index("</div>", html.index('class="uxr-board-group', filters_start))
    filters_block = html[filters_start:filters_end]
    assert filters_block.count('aria-pressed="true"') == 1, (
        "exactly the default-active 'All' chip should start pressed"
    )
    chip_button_count = filters_block.count('<button type="button" class="uxr-chip')
    assert chip_button_count == filters_block.count("aria-pressed"), (
        "every filter chip button must carry an aria-pressed attribute, not just some"
    )


def test_filter_click_handler_synchronizes_aria_pressed_with_is_on():
    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    js_start = html.index("const uxrBoardItemNames")
    js_end = html.index("</script>", js_start)
    js_block = html[js_start:js_end]

    filter_start = js_block.index("data-uxr-filter]'")
    filter_end = js_block.index("\n  });", filter_start)
    filter_handler = js_block[filter_start:filter_end]
    assert "familyOk" not in filter_handler and "uxrActiveFamilyFilter" not in filter_handler, (
        "no family branch should exist for this board (build packet §5g) -- "
        "there is only ever one family, so a family filter branch would be dead code"
    )
    assert filter_handler.count("setAttribute('aria-pressed'") == 2, (
        "the sole (state) branch must set aria-pressed on activate and clear "
        "it on every sibling chip it deactivates"
    )


# ---------------------------------------------------------------------------
# Stable hooks for live count recomputation must exist independent of
# whether any removal ever happens.
# ---------------------------------------------------------------------------

def test_flag_on_stat_strip_and_filter_chips_carry_stable_count_hooks(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/handoffs").text

    for stat_key, expected in (("total", "4"), ("ready", "2"), ("review", "2")):
        assert f'data-uxr-stat="{stat_key}">{expected}</strong>' in html, f"missing stat hook for {stat_key}"
    # See test_flag_on_needs_action_group_stat_and_filter_never_render for why
    # this must be the fuller markup fragment, not the bare attribute.
    assert '<strong data-uxr-stat="attention">' not in html
    assert 'data-uxr-stat="blockers"' not in html

    for filter_value in ("state:all", "state:review", "state:ready"):
        chip_start = html.index(f'data-uxr-filter="{filter_value}"')
        chip_end = html.index("</button>", chip_start)
        assert 'class="uxr-chip-count"' in html[chip_start:chip_end], (
            f"{filter_value} chip must wrap its count in .uxr-chip-count for live updates"
        )


# ---------------------------------------------------------------------------
# Independent-review fix (PR #245): a generated `spec` path with no real DDL
# content must not be treated as an available DDL artifact. Round-trips
# through the real /handoffs/save route rather than constructing a
# DataHandoff fixture directly, since the bug was specifically in the save
# route's own field-assignment logic -- an in-memory fixture would not have
# exercised it.
# ---------------------------------------------------------------------------

def test_save_route_does_not_fabricate_a_ddl_artifact_when_none_was_provided(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = get_session()
    session.app_name = "Save Route DDL Fix"
    session.bounded_context = "save-route-ddl-fix"
    session.app_archetype = "crud"
    save_session(session)

    save_response = client.post("/handoffs/save", json={
        "handoffs": [
            {
                "name": "no-ddl",
                "field_mappings": [{"source": "Entity.fieldA", "target": "col_a"}],
            },
        ],
    })
    assert save_response.status_code == 200
    assert save_response.json()["ok"] is True

    saved_session = get_session()
    saved_handoff = next(h for h in saved_session.data_handoffs if h.name == "no-ddl")
    assert saved_handoff.ddl_content is None
    assert saved_handoff.spec is None, (
        "a handoff saved with no DDL content must not get a fabricated spec "
        "path pointing at a .sql file that will never be written"
    )

    html = client.get("/handoffs").text
    row_start = html.index('data-uxr-row-name="no-ddl"')
    window = html[row_start:row_start + 900]
    assert 'data-uxr-row-state="warning"' in window, (
        "no DDL provided (and no fabricated spec) -> warning, not ready"
    )
    assert 'class="badge badge-warning"' in window
    assert ">Review DDL</span>" in window


def test_save_route_still_sets_spec_when_ddl_content_is_provided(monkeypatch):
    """Companion to the fix above: confirm the conditional assignment didn't
    regress the case where DDL genuinely was provided."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = get_session()
    session.app_name = "Save Route DDL Present"
    session.bounded_context = "save-route-ddl-present"
    session.app_archetype = "crud"
    save_session(session)

    save_response = client.post("/handoffs/save", json={
        "handoffs": [
            {
                "name": "with-ddl",
                "ddl_content": "CREATE TABLE stage_x (col_x VARCHAR(10));",
                "field_mappings": [{"source": "Entity.fieldX", "target": "col_x"}],
            },
        ],
    })
    assert save_response.status_code == 200
    assert save_response.json()["ok"] is True

    saved_session = get_session()
    saved_handoff = next(h for h in saved_session.data_handoffs if h.name == "with-ddl")
    assert saved_handoff.spec == "data-handoffs/with-ddl.sql"

    html = client.get("/handoffs").text
    row_start = html.index('data-uxr-row-name="with-ddl"')
    window = html[row_start:row_start + 400]
    assert 'data-uxr-row-state="ready"' in window


def test_project_open_then_step4_save_preserves_spec_only_handoff_on_rename(monkeypatch):
    """A restored package reference is server-owned state, not editable card data.

    The card sends only its stable original identity. Step 4 uses that identity
    to preserve the existing package-relative spec through an ordinary save,
    including when the handoff is renamed.
    """
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    source_session = get_session()
    source_session.app_name = "Spec Reference Round Trip"
    source_session.bounded_context = "spec-reference-round-trip"
    source_session.app_archetype = "crud"
    source_session.data_handoffs = [
        DataHandoff(
            name="ref-ddl",
            spec="data-handoffs/reviewed.sql",
            table_name="reviewed_stage",
            field_mappings=[FieldMapping(source="Entity.recordId", target="record_id")],
        )
    ]
    raw_project = serialize_project(snapshot_session(source_session)).encode("utf-8")

    reset_session()
    open_response = client.post(
        "/project/open",
        files={"project_file": ("spec-reference.project.json", raw_project, "application/json")},
        follow_redirects=False,
    )
    assert open_response.status_code == 303

    opened_html = client.get("/handoffs").text
    opened_row = opened_html[opened_html.index('data-uxr-row-name="ref-ddl"'):]
    assert 'data-uxr-row-state="ready"' in opened_row[:500]
    assert "data-handoffs/reviewed.sql" in opened_html
    assert "original_name: card.dataset.uxrOriginalName || null" in opened_html

    save_response = client.post("/handoffs/save", json={
        "handoffs": [
            {
                "original_name": "ref-ddl",
                "name": "renamed-ref-ddl",
                "table_name": "reviewed_stage",
                "field_mappings": [
                    {"source": "Entity.recordId", "target": "record_id"},
                ],
            },
        ],
    })
    assert save_response.status_code == 200
    assert save_response.json()["ok"] is True

    saved_handoff = get_session().data_handoffs[0]
    assert saved_handoff.name == "renamed-ref-ddl"
    assert saved_handoff.ddl_content is None
    assert saved_handoff.spec == "data-handoffs/reviewed.sql"

    reopened_html = client.get("/handoffs").text
    reopened_row = reopened_html[reopened_html.index('data-uxr-row-name="renamed-ref-ddl"'):]
    assert 'data-uxr-row-state="ready"' in reopened_row[:500]

    project_save_response = client.post("/project/save")
    assert project_save_response.status_code == 200
    saved_project = deserialize_project(project_save_response.text)
    assert saved_project.data_handoffs[0].name == "renamed-ref-ddl"
    assert saved_project.data_handoffs[0].spec == "data-handoffs/reviewed.sql"


# ---------------------------------------------------------------------------
# Independent-review fix (PR #245): exactly one authoritative stats summary
# must render -- the older PR-06 hand-summed strip was removed so the board
# is the single source of truth (it and the old strip could disagree, since
# the old strip used a different, ad-hoc predicate over session.data_handoffs
# directly instead of readiness_view.items_for_step()).
# ---------------------------------------------------------------------------

def test_flag_on_exactly_one_stats_strip_renders(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/handoffs").text

    assert html.count('class="uxr-stat-strip') == 1, (
        "only the board's own stats strip may render -- the older PR-06 "
        "hand-summed strip must not coexist with it"
    )
    assert "have both DDL and field mappings saved" not in html, (
        "the removed strip's literal copy must not still be present"
    )
