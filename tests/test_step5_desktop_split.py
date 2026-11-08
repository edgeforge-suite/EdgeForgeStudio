"""PR-24 acceptance tests: Step 5 permanent responsive focus presentation.

A focused route always server-renders the board/editor wrapper. CSS displays
the split at 1200px and wider and hides the board for the supported narrow
full-page focus fallback. The retired refresh/split environment values are
inert; their unset/false/true combinations remain covered as compatibility
inputs rather than active rollout modes. Board-only and focused save behavior
remain covered by their dedicated suites.

Fixture note: 3 downstream interfaces spanning blocked/warning/ready --
verified directly against `readiness_view._downstream_interface_items` in the
same way as `test_step5_triage_board.py`'s own fixture (this file reuses that
file's `csv-blocked`/`fixed-warn` field shapes verbatim so the resulting
states are already known-correct, and adds one `xml-ready` item as the focus
target).
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models.project import DownstreamInterface, FieldMapping
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)
_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "app" / "templates" / "step5_downstream.html"
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
    """3 downstream interfaces: one blocked, one warning, one ready -- enough
    to populate every board section without duplicating the combinatorial
    breadth of test_step5_triage_board.py's own 8-item fixture."""
    session = get_session()
    session.app_name = "Desktop Split Fixture"
    session.bounded_context = "desktop-split-fixture"
    session.app_archetype = "crud"
    session.project_revision = 3
    session.downstream_interfaces = [
        DownstreamInterface(name="csv-blocked", type="file-csv"),
        DownstreamInterface(
            name="fixed-warn", type="file-fixed-width",
            spec="downstream/fixed-warn-layout.yaml",
            spec_content="format: fixed-width\nrecord_types:\n  data:\n    fields: []\n",
        ),
        DownstreamInterface(
            name="xml-ready", type="xml-xsd",
            xsd_path="contracts/out.xsd", xsd_content="<xs:schema/>", root_element="Msg",
            entity_name="Account",
            field_mappings=[FieldMapping(source="Account.accountId", target="msgId")],
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

    html = client.get("/downstream?focus=xml-ready").text

    assert 'data-uxr-focus-editor="xml-ready"' in html
    assert 'data-uxr-board="downstream"' in html
    assert 'data-uxr-split="true"' in html


def test_retired_split_env_unset_matches_explicit_false(monkeypatch):
    """Unset and false legacy values are equivalent compatibility inputs."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.delenv("EDGEFORGE_STUDIO_UX_SPLIT", raising=False)
    _split_session()
    unset_html = _normalize_csrf(client.get("/downstream?focus=xml-ready").text)

    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "false")
    explicit_off_html = _normalize_csrf(client.get("/downstream?focus=xml-ready").text)

    assert unset_html == explicit_off_html


def test_retired_refresh_flag_cannot_disable_split(monkeypatch):
    """A false retired refresh value cannot disable the focused presentation."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "true")
    _split_session()

    html = client.get("/downstream?focus=xml-ready").text
    assert 'data-uxr-split="true"' in html
    assert 'data-uxr-focus-editor="xml-ready"' in html
    assert 'data-uxr-board="downstream"' in html


# ---------------------------------------------------------------------------
# A focused route renders the board and editor in the responsive wrapper.
# ---------------------------------------------------------------------------

def test_focused_route_renders_board_and_editor_together(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "true")
    _split_session()

    html = client.get("/downstream?focus=xml-ready").text

    assert 'data-uxr-split="true"' in html
    assert 'data-uxr-board="downstream"' in html
    assert 'data-uxr-focus-editor="xml-ready"' in html
    for name in ("csv-blocked", "fixed-warn", "xml-ready"):
        assert html.count(f'data-uxr-row-name="{name}"') == 1
    # board's Edit links + filter chips are present alongside the editor
    assert 'data-uxr-edit-target="xml-ready"' in html
    assert 'data-uxr-filter="state:all"' in html
    assert 'data-uxr-filter="state:attention"' in html
    assert 'data-uxr-filter="state:review"' in html


def test_split_on_right_column_contains_editor_container_and_actions_in_order(monkeypatch):
    """Build packet §1: the <section data-uxr-focus-editor>, the
    #interfaces-container JS-populated form, and the Save/Cancel + Continue/
    Previous actions all belong in the right column -- assert the actual
    source order puts all three after the board column opens and closes."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "true")
    _split_session()

    html = client.get("/downstream?focus=xml-ready").text

    board_col = html.index('class="uxr-focus-split-board"')
    board_marker = html.index('data-uxr-board="downstream"')
    editor_col = html.index('class="uxr-focus-split-editor"')
    editor_marker = html.index('data-uxr-focus-editor="xml-ready"')
    container_marker = html.index('id="interfaces-container"')
    save_marker = html.index('data-uxr-save-one')
    step_actions_marker = html.index('data-uxr-step-actions')
    assert (
        board_col < board_marker < editor_col < editor_marker
        < container_marker < save_marker < step_actions_marker
    )


def test_split_on_renders_both_strips_and_css_picks_by_viewport(monkeypatch):
    """Both the board and the focus editor have their own ambient stat strip.
    Which one is VISIBLE is viewport-dependent, so Jinja cannot decide it:
    below the split breakpoint the board is hidden and the editor's strip is
    the only one (the supported single-column full-page fallback from the
    approved implementation-design §7.1 amendment); at >=1200px the board's
    richer strip takes over and CSS hides the editor's duplicate. Both must
    therefore be in the DOM, with the *stylesheet* choosing -- and PR-17a's
    querySelectorAll stat updaters keep them in sync so a resize is correct
    either way."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "true")
    _split_session()

    html = client.get("/downstream?focus=xml-ready").text

    assert html.count('class="uxr-stat-strip') == 2
    # "ready"/"blockers" stats only ever exist on the board's own strip -- the
    # editor's 2-stat (total/attention) strip never renders them.
    assert 'data-uxr-stat="ready">' in html
    assert 'data-uxr-stat="blockers">' in html

    css = _STUDIO_CSS.read_text(encoding="utf-8")
    split_block = css[css.index("PR-17 desktop split, folded into PR-24"):]
    # Narrow: board hidden outright (NOT stacked above the editor).
    assert "body.ux-refresh .uxr-focus-split-board {\n  display: none;\n}" in split_block
    # >=1200px: board returns and the editor's duplicate strip is suppressed.
    media = split_block[split_block.index("@media (min-width: 1200px)"):]
    assert "body.ux-refresh .uxr-focus-split-board {\n    display: block;\n  }" in media
    assert "body.ux-refresh .uxr-focus-split-editor .uxr-stat-strip {\n    display: none;\n  }" in media


def test_narrow_split_falls_back_to_single_column_focus_not_a_stacked_board(monkeypatch):
    """The approved implementation-design §7.1 amendment retires PR-18's modal
    because the full-page focus route is the supported accessible fallback. The
    board is server-rendered for every focused route, so below the breakpoint
    it must be HIDDEN -- leaving the pre-PR-17 single-column focus editor --
    rather than stacking above the editor. Regression guard for the original
    PR-17 build, which left it stacking."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "true")
    _split_session()

    html = client.get("/downstream?focus=xml-ready").text
    # The board IS in the DOM (Jinja can't know the viewport) ...
    assert 'class="uxr-focus-split-board"' in html

    css = _STUDIO_CSS.read_text(encoding="utf-8")
    split_block = css[css.index("PR-17 desktop split, folded into PR-24"):]
    board_default = split_block.index("body.ux-refresh .uxr-focus-split-board {\n  display: none;\n}")
    media_start = split_block.index("@media (min-width: 1200px)")
    # ... and its default (narrow) state is display:none, declared BEFORE the
    # min-width query that re-shows it -- so the cascade order actually works.
    assert board_default < media_start


def test_saved_row_is_regrouped_and_all_board_counters_recomputed(monkeypatch):
    """Regression for review finding 1 on #255 (P2): a save can CHANGE an
    item's state, so updating the row's attributes in place is not enough --
    the row must physically leave its old group, and the board-only counters
    (ready/review/blockers) plus the filter-chip counts must be recomputed.
    uxrUpdateAmbientAndRail() only ever touches total/attention, so without
    this the reviewer saw a row sit under 'Needs action' while its badge said
    Review, with blockers/review counts stale.

    No jsdom here, so this pins the wiring by source; the behaviour itself is
    live-driven in review."""
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")

    updater = template[template.index("function uxrUpdateBoardRowFromSaved"):]
    updater = updater[: updater.index("\n}\n")]
    assert "uxrRegroupBoardRow(row);" in updater
    assert "uxrRecomputeStatsAndFilterCounts();" in updater
    assert "uxrApplyBoardFilters();" in updater

    # The bucket mapping must agree with uxrApplyBoardFilters()'s, or a saved
    # row lands in a group its own filter chip then excludes.
    bucket = template[template.index("function uxrBoardGroupForState"):]
    bucket = bucket[: bucket.index("\n}\n")]
    assert "'blocks_export' || state === 'needs_action'" in bucket
    assert "'attention'" in bucket and "'review'" in bucket and "'ready'" in bucket


def test_saved_row_replaces_readiness_derived_facts_not_just_its_badge():
    """A live save must not leave a prior warning beside a fresh Ready badge.

    The server-rendered board macro derives coverage, capability, and the
    blocker/warning detail exclusively from ReadinessItem. Pin the live updater
    to that same response object so state transitions replace those facts rather
    than retaining DOM from the row's previous state.
    """
    for template_path in (_TEMPLATE_PATH, _TEMPLATE_PATH.parent / "step4_handoffs.html"):
        template = template_path.read_text(encoding="utf-8")

        helper_start = template.index("function uxrRenderBoardRowReadinessDetails")
        helper = template[helper_start:template.index("\n}\n", helper_start)]
        assert ".uxr-board-row-tags, .uxr-board-row-blocker, .uxr-board-row-warning" in helper
        assert "readiness.coverage" in helper
        assert "readiness.blockers" in helper
        assert "readiness.warnings" in helper
        assert "UXR_UPLOADED_ARTIFACT_COPY" in helper

        updater_start = template.index("function uxrUpdateBoardRowFromSaved")
        updater = template[updater_start:template.index("\n}\n", updater_start)]
        assert "uxrRenderBoardRowReadinessDetails(row, readiness);" in updater


def test_saved_row_replaces_server_derived_metadata_after_each_save():
    """The board's metadata is descriptive server output, not stale DOM state."""
    for template_path in (_TEMPLATE_PATH, _TEMPLATE_PATH.parent / "step4_handoffs.html"):
        template = template_path.read_text(encoding="utf-8")

        metadata_start = template.index("function uxrRenderBoardRowMetadata")
        metadata = template[metadata_start:template.index("\n}\n", metadata_start)]
        assert ".uxr-board-row-meta" in metadata
        assert "boardMetadata" in metadata

        updater_start = template.index("function uxrUpdateBoardRowFromSaved")
        updater = template[updater_start:template.index("\n}\n", updater_start)]
        assert "uxrRenderBoardRowMetadata(row, boardMetadata);" in updater

    step5_template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    step4_template = (_TEMPLATE_PATH.parent / "step4_handoffs.html").read_text(encoding="utf-8")
    assert "uxrUpdateBoardRowFromSaved(data.readiness, previousName, data.board_metadata);" in step5_template
    assert "uxrUpdateBoardRowFromSaved(data.readiness, previousName, data.board_metadata);" in step4_template


def test_board_group_headings_carry_a_stable_regroup_key(monkeypatch):
    """uxrRegroupBoardRow() moves rows between groups by data-uxr-group rather
    than by heading text. The server only renders a heading for a NON-empty
    group, so the JS must also be able to create a missing one -- pinned here
    so the key and the creation path stay in step."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "true")
    _split_session()

    html = client.get("/downstream").text
    assert 'data-uxr-group="attention"' in html
    assert 'data-uxr-group="review"' in html
    assert 'data-uxr-group="ready"' in html

    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "function uxrEnsureBoardGroup(board, key)" in template
    assert "board.insertBefore(heading, before || null);" in template


def test_conditional_chips_and_stats_are_created_and_removed_not_just_retexted():
    """Regression for review round 2 finding 1 on #255 (P2): the server renders
    the state chips and some stats ONLY when their count is non-zero, so
    re-texting whatever exists is not enough. A save that populates an empty
    bucket left the board with no filter chip to select the new group; a save
    that emptied one left an obsolete 'Needs review . 0'. Live counts must
    create/remove so the board matches a fresh server render for 0->N and N->0.
    """
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")

    recompute = template[template.index("function uxrRecomputeStatsAndFilterCounts"):]
    recompute = recompute[: recompute.index("\n}\n")]
    assert "uxrSyncConditionalStats(counts);" in recompute
    assert "uxrSyncConditionalChips(counts);" in recompute

    # Creation AND removal, both directions.
    chips = template[template.index("function uxrSyncConditionalChips"):]
    chips = chips[: chips.index("\n}\n")]
    assert "chip.remove();" in chips
    assert "document.createElement('button')" in chips
    # Removing the active filter must not strand the board showing nothing.
    assert "uxrResetStateFilterToAll();" in chips

    stats = template[template.index("function uxrSyncConditionalStats"):]
    stats = stats[: stats.index("\n}\n")]
    assert "existing.closest('span').remove();" in stats
    assert "document.createElement('span')" in stats

    # The conditional set must match what the template actually gates. On this
    # step the server renders total/ready/attention unconditionally and gates
    # review/blockers -- see the board strip markup.
    spec = template[template.index("const UXR_CONDITIONAL_STATS"):]
    spec = spec[: spec.index("];")]
    assert "'review'" in spec and "'blockers'" in spec
    assert "'total'" not in spec and "'attention'" not in spec


def test_created_chips_work_because_the_filter_handler_is_delegated():
    """uxrSyncConditionalChips() creates chips after init, so a per-chip
    listener bound at DOMContentLoaded would leave them dead -- the same
    replaced-node trap PR-16 hit with the tab badges. The handler must be
    delegated on the container."""
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "document.querySelector('.uxr-board-filters')?.addEventListener('click', event => {" in template
    assert "event.target.closest('[data-uxr-filter]')" in template
    # The old per-chip binding must be gone, or created chips silently do nothing.
    assert "document.querySelectorAll('[data-uxr-filter]').forEach(chip => {" not in template


def test_long_unbroken_names_are_contained_in_the_split(monkeypatch):
    """Regression for review finding 2 on #255 (P2): contract/handoff names are
    author-supplied identifiers with no length cap in the model or the save
    route. A valid long unbroken name measured 620px scroll width inside the
    fixed 320px board column and forced the page to scroll horizontally at
    1200px. The board row text and the focus heading/banner must wrap."""
    css = _STUDIO_CSS.read_text(encoding="utf-8")
    split_block = css[css.index("PR-17 desktop split, folded into PR-24"):]

    for selector in (
        "body.ux-refresh .uxr-focus-split .uxr-board-row-name",
        "body.ux-refresh .uxr-focus-split .uxr-board-row-meta",
        "body.ux-refresh .uxr-focus-split .uxr-board-row-blocker",
        "body.ux-refresh .uxr-focus-split .uxr-board-row-warning",
        "body.ux-refresh .uxr-focus-split [data-uxr-focus-title]",
        "body.ux-refresh .uxr-focus-split [data-uxr-editor-banner-copy]",
        # Review round 2 finding 2: the readiness badges are built client-side
        # from Ref.label, which embeds the item name -- same unbounded
        # identifier, and they overflowed the editor at the 1200px activation
        # breakpoint until they were included here.
        "body.ux-refresh .uxr-focus-split [data-uxr-tab-badges] .badge",
    ):
        assert selector in split_block, f"{selector} must be contained in the split"
    # .badge is inline-block, so wrapping alone is not enough -- without an
    # explicit max-width it still sets the editor column's min-content width.
    assert "max-width: 100%;" in split_block
    # `anywhere`, not `break-word`: these are identifiers, so a 320px column has
    # to be allowed to break mid-token.
    assert "overflow-wrap: anywhere;" in split_block
    # Both grid items must be able to shrink to their track rather than being
    # floored at max-content.
    assert "body.ux-refresh .uxr-focus-split-board,\nbody.ux-refresh .uxr-focus-split-editor {\n  min-width: 0;\n}" in split_block


def test_retired_split_off_value_keeps_both_responsive_strips(monkeypatch):
    """A false retired split value still renders both viewport-owned strips."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "false")
    _split_session()

    html = client.get("/downstream?focus=xml-ready").text

    assert html.count('class="uxr-stat-strip') == 2
    assert 'data-uxr-stat="ready"' in html
    assert 'data-uxr-stat="blockers"' in html


def test_retired_split_values_do_not_change_board_only_mode(monkeypatch):
    """Retired split values render the same board-only route."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "true")
    _split_session()
    split_on_html = _normalize_csrf(client.get("/downstream").text)

    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "false")
    split_off_html = _normalize_csrf(client.get("/downstream").text)

    assert split_on_html == split_off_html
    assert "uxr-focus-split" not in split_on_html


# ---------------------------------------------------------------------------
# Selected-row treatment applies only when a route has a focused item.
# ---------------------------------------------------------------------------

def test_focused_row_is_marked_is_editing_others_are_not(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "true")
    _split_session()

    html = client.get("/downstream?focus=xml-ready").text

    assert html.count("uxr-board-row is-editing") == 1
    focused_start = html.index('data-uxr-row-name="xml-ready"')
    row_open = html.rindex('<div class="uxr-board-row', 0, focused_start)
    assert html[row_open:focused_start].startswith('<div class="uxr-board-row is-editing"')
    for other in ("csv-blocked", "fixed-warn"):
        other_start = html.index(f'data-uxr-row-name="{other}"')
        other_open = html.rindex('<div class="uxr-board-row', 0, other_start)
        assert html[other_open:other_start].startswith('<div class="uxr-board-row"')


def test_board_only_mode_never_marks_any_row_is_editing(monkeypatch):
    """tests/test_step5_triage_board.py already pins 'uxr-board-row is-editing'
    not in html for board-only mode. This confirms the treatment is keyed to
    focus state, independent of the retired split setting."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "true")
    _split_session()

    html = client.get("/downstream").text
    assert "uxr-board-row is-editing" not in html


# ---------------------------------------------------------------------------
# CSS: the split grid is gated behind the (first, and only) min-width query.
# ---------------------------------------------------------------------------

def test_min_width_media_query_is_the_only_one_and_gates_the_split_grid():
    css = _STUDIO_CSS.read_text(encoding="utf-8")
    assert css.count("@media (min-width") == 1, (
        "PR-17's split breakpoint is the first min-width query in this "
        "codebase -- every pre-existing @media query is max-width "
        "(desktop-first); a second min-width query appearing would need "
        "its own conscious review, not silent duplication"
    )
    media_start = css.index("@media (min-width")
    window = css[media_start:media_start + 300]
    assert "min-width: 1200px" in window
    assert "body.ux-refresh .uxr-focus-split {" in window
    assert "display: grid;" in window
    assert "grid-template-columns: 320px minmax(0, 1fr);" in window


def test_split_wrapper_class_is_a_server_render_decision_not_js_driven():
    """Build packet: 'this is a template restructure, not a CSS-hidden
    toggle.' Confirm the .uxr-focus-split/data-uxr-split markers are never
    written or toggled from JS -- their only producer is server-side Jinja."""
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    script_start = template.index("{% block scripts %}")
    script_block = template[script_start:]
    assert "uxr-focus-split" not in script_block
    assert "data-uxr-split" not in script_block


def test_uxr_split_focus_depends_only_on_focus_route_state():
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "{% set uxr_split_focus = true if focus_name else false %}" in template
    assert "focus_name and ux_split" not in template
