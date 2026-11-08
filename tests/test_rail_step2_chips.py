"""Wizard-rail and Step 2 readiness/capability presentation coverage.

Covers the §2 Phase-1 PR-11 acceptance bar: `build_nav_context()` gains
per-step `count`/`attention` sourced exclusively from
`readiness_view.step_counts()`; the wizard rail renders those as small,
shape+label chips (never colour-only). PR-22 moved Step 2's readiness and
capability projection from the legacy table into the triage board while
preserving the same single-producer and accessibility contracts.

Fixture note: reuses `tests.test_readiness_view`'s `_readiness_session` /
`_phase04_session` fixtures (already-verified upstream/entity/handoff/
downstream states) rather than redefining an equivalent fixture, mirroring
how `tests/test_shell_nav_frame.py` reuses `_full_session` from
`tests.test_package_writer`.

`draft` (and, independently, `metadata_only` capability) are not reachable
through any real `UpstreamInterface` field combination today --
`edge_contracts.py`'s `REFERENCE_ONLY` branch always appends a "no uploaded
artifact content" warning in the same branch that sets `status =
REFERENCE_ONLY` (edge_contracts.py ~L1397-1405), and `_state_for_edge_contract`
checks `if row.warnings` *before* `if row.status == REFERENCE_ONLY` -- so the
warning check always wins first. This is the identical finding already
documented for downstream in `tests/test_step5_triage_board.py`
(`test_draft_state_and_alt_capability_render_correctly`), which this file's
synthetic-item-injection test mirrors for Step 2's name-matched chip lookup.

WCAG tests independently RECOMPUTE contrast via the WCAG relative-luminance
formula against whatever hex/var() values are actually shipped in
studio.css (parsed from the file, not hardcoded), mirroring
`tests/test_family_zone_skin.py` and `tests/test_step5_triage_board.py`.
"""
from __future__ import annotations

import re as _re
from pathlib import Path as _Path

from fastapi.testclient import TestClient

import app.routes.upstream as upstream_route
from app.main import app
from app.models.project import FieldMapping, UpstreamInterface
from app.services import readiness_view
from app.services.nav_context import build_nav_context
from app.services.readiness_view import Cov, ReadinessItem
from tests.session_helpers import get_session, reset_session, save_session
from tests.test_readiness_view import _phase04_session, _readiness_session

client = TestClient(app)

_TEMPLATE_PATH = (
    _Path(__file__).resolve().parent.parent / "app" / "templates" / "step2_upstream.html"
)
_STUDIO_CSS = _Path(__file__).resolve().parent.parent / "app" / "static" / "css" / "studio.css"

_ROUTE_BY_POSITION = {
    2: "/upstream",
    3: "/entities",
    4: "/handoffs",
    5: "/downstream",
}

_STATE_CHIP_CLASS = {
    "ready": "badge-ready",
    "warning": "badge-warning",
    "draft": "badge-draft",
    "needs_action": "badge-warning",
    "blocks_export": "badge-warning",
}
_STATE_CHIP_LABEL = {
    "ready": "Ready",
    "warning": "Review",
    "needs_action": "Needs action",
    "blocks_export": "Blocked",
    "draft": "Draft",
}
_CAPABILITY_LABEL = {
    "manifest_reference": "MANIFEST REF",
    "populates_entities": "ENTITY-POPULATING",
    "metadata_only": "METADATA ONLY",
}


def _step2_board_row_window(html: str, name: str) -> str:
    marker = f'data-uxr-row-name="{name}"'
    marker_index = html.index(marker)
    row_marker = '<div class="uxr-board-row" '
    start = html.rindex(row_marker, 0, marker_index)
    next_row = html.find(row_marker, marker_index + len(marker))
    board_end = html.index('<div class="uxr-readiness-legend"', marker_index)
    end = min(position for position in (next_row, board_end) if position >= 0)
    return html[start:end]


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


# ---------------------------------------------------------------------------
# nav_context: count/attention is a pure projection of step_counts()
# ---------------------------------------------------------------------------


def test_build_nav_context_flag_on_matches_step_counts_exactly(monkeypatch):
    """crud has no non-applicable steps, so step_counts() (which only skips
    non-applicable steps) returns an entry for every one of the 8 nav_steps --
    every nav_step's count/attention must equal that entry exactly, proving a
    pure passthrough rather than a re-derivation."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = _phase04_session()
    save_session(session)

    nav = build_nav_context(session, "/upstream")
    counts = readiness_view.step_counts(session)
    nav_by_position = {step["position"]: step for step in nav["nav_steps"]}

    assert set(nav_by_position) == set(counts)
    for position, bucket in counts.items():
        assert nav_by_position[position]["count"] == bucket["count"]
        assert nav_by_position[position]["attention"] == bucket["attention"]
    # sanity: this fixture actually exercises mixed states, not all-zero
    assert counts[2]["attention"] == 1
    assert counts[5]["attention"] == 1


def test_retired_flag_off_value_still_projects_step_counts(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    session = _phase04_session()
    save_session(session)

    nav = build_nav_context(session, "/upstream")

    counts = readiness_view.step_counts(session)
    for step in nav["nav_steps"]:
        if not step["is_applicable"]:
            assert "count" not in step
            continue
        assert step["count"] == counts[step["position"]]["count"]
        assert step["attention"] == counts[step["position"]]["attention"]


def test_build_nav_context_non_applicable_steps_get_no_count_key_even_when_flag_on(monkeypatch):
    """step_counts() only iterates applicable steps -- a non-applicable
    position (passthrough-router's Data Handoffs slot) must never gain a
    count/attention key at all, distinguishing "not represented" from
    "represented with zero items" (which DOES get the key, at 0)."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = get_session()
    session.app_name = "Router"
    session.bounded_context = "router"
    session.app_archetype = "passthrough-router"
    save_session(session)

    nav = build_nav_context(session, "/upstream")
    nav_by_position = {step["position"]: step for step in nav["nav_steps"]}

    assert nav_by_position[4]["is_applicable"] is False
    assert "count" not in nav_by_position[4]
    assert "attention" not in nav_by_position[4]
    assert nav_by_position[2]["is_applicable"] is True
    assert "count" in nav_by_position[2]


# ---------------------------------------------------------------------------
# Rail render: count/attention chips, aria-labels, flag-off, error-page guard
# ---------------------------------------------------------------------------


def _wizard_nav_html(html: str) -> str:
    start = html.index('<nav class="wizard-nav"')
    end = html.index("</nav>", start)
    return html[start:end]


def _nav_link_window(nav_html: str, route: str) -> str:
    start = nav_html.index(f'href="{route}"')
    end = nav_html.index("</a>", start)
    return nav_html[start:end]


def test_rail_flag_on_renders_single_chip_matching_step_counts_and_updater_format(monkeypatch):
    """One `badge uxr-rail-chip` per step, class + text byte-identical to what
    Step 5's save-one live updater writes. Per the locked five-surface rail
    payload ({step, count, attention} -- design doc §1.3), the chip always
    shows the total count; attention (when >0) is appended alongside it, never
    in place of it (`N` | `N · M need action`). Exactly one chip per link,
    since the updater targets it with a single `querySelector('.uxr-rail-chip')`."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = _phase04_session()
    save_session(session)

    html = client.get("/upstream").text
    nav_html = _wizard_nav_html(html)
    counts = readiness_view.step_counts(session)

    for position, route in _ROUTE_BY_POSITION.items():
        bucket = counts[position]
        window = _nav_link_window(nav_html, route)
        if bucket["count"] == 0:
            assert "uxr-rail-chip" not in window
            continue
        expected_text = (
            f"{bucket['count']} · {bucket['attention']} need action" if bucket["attention"] > 0
            else f"{bucket['count']} items"
        )
        assert f'<span class="badge uxr-rail-chip">{expected_text}</span>' in window, (
            f"step {position}: expected single chip with text {expected_text!r}"
        )
        assert window.count("uxr-rail-chip") == 1, f"step {position}: expected exactly one rail chip"

    # sanity: this fixture actually exercises both text branches
    # (step 2 has attention>0 -> combined "N · M need action"; step 4 has
    # attention==0 -> plain "N items")
    assert counts[2]["attention"] > 0 and counts[4]["attention"] == 0

    # Step 1 ("/") has count 0 -- the guard on `nav_step.count > 0` suppresses
    # the chip entirely, even though the key itself is present.
    root_window = _nav_link_window(nav_html, "/")
    assert "uxr-rail-chip" not in root_window


def test_rail_chip_markup_stays_byte_compatible_with_step5_save_one_updater():
    """Finding-2 regression guard: the rail chip this PR renders and the chip
    Step 5's save-one live updater owns after a save MUST use the same class and
    text format, or a save leaves incorrect/stale rail values. Pins both sides
    so they cannot silently drift apart again."""
    root = _Path(__file__).resolve().parent.parent / "app" / "templates"
    step5 = (root / "step5_downstream.html").read_text(encoding="utf-8")
    base = (root / "base.html").read_text(encoding="utf-8")
    # the updater creates `badge uxr-rail-chip` and writes these two exact texts
    assert "'badge uxr-rail-chip'" in step5
    assert "${entry.count} · ${entry.attention} need action" in step5
    assert "${entry.count} items" in step5
    # base.html server-renders the identical class + identical text templates
    assert 'class="badge uxr-rail-chip"' in base
    assert "{{ nav_step.count }}{% if nav_step.attention is defined and nav_step.attention > 0 %} · {{ nav_step.attention }} need action{% else %} items{% endif %}" in base


def test_rail_updater_removes_chip_when_count_drops_to_zero():
    """Re-review finding: the updater used to unconditionally create/update a
    chip for every rail entry, so a step whose count is (or becomes) 0 could
    show a stale/incorrect "0 items" chip after a live save even though the
    server-side guard hides it on initial render. The updater must mirror that
    guard: remove any existing chip (and never create one) when count is 0.
    Static source check since this repo has no jsdom to execute the JS."""
    step5 = (
        _Path(__file__).resolve().parent.parent / "app" / "templates" / "step5_downstream.html"
    ).read_text(encoding="utf-8")
    fn_start = step5.index("function uxrUpdateAmbientAndRail")
    fn_end = step5.index("\n}", fn_start)
    fn_body = step5[fn_start:fn_end]
    assert "if (!entry.count)" in fn_body or "!entry.count" in fn_body, (
        "updater must guard on entry.count before creating/keeping a chip"
    )
    assert "chip?.remove()" in fn_body or "chip.remove()" in fn_body, (
        "updater must remove an existing chip when the new count is 0"
    )


def test_ambient_stat_lookups_hardened_to_queryselectorall():
    """PR-17a §3: today only one [data-uxr-stat] strip renders at a time
    (focus-editor and board strips are mutually exclusive), so a singular
    querySelector was safe for the total/attention stat lookups above the
    rail-chip logic this file otherwise covers -- PR-17 renders both
    strips together, and a singular lookup would silently patch one and
    leave the other stale. Hardened to querySelectorAll + forEach (a no-op
    today, correct once PR-17 ships)."""
    step5 = (
        _Path(__file__).resolve().parent.parent / "app" / "templates" / "step5_downstream.html"
    ).read_text(encoding="utf-8")
    fn_start = step5.index("function uxrUpdateAmbientAndRail")
    fn_end = step5.index("\n}", fn_start)
    fn_body = step5[fn_start:fn_end]

    assert "document.querySelectorAll('[data-uxr-stat=\"total\"]')" in fn_body
    assert "document.querySelectorAll('[data-uxr-stat=\"attention\"]')" in fn_body
    assert "document.querySelector('[data-uxr-stat=" not in fn_body


def test_retired_flag_off_value_still_shows_default_on_rail_chips(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    session = _phase04_session()
    save_session(session)

    html = client.get("/upstream").text

    assert "uxr-rail-chip" in html


def test_rail_fallback_error_page_renders_without_chips_or_crash(monkeypatch):
    """base.html's `{% if nav_steps is not defined %}` fallback (used by
    project_open_error.html, which passes no session/nav context at all --
    see app/routes/project_file.py) must never crash and must never render a
    rail chip: both `ux_refresh` and `nav_step.count` are undefined there, and
    Jinja's default (non-strict) Undefined is falsy, so the `{% if ux_refresh
    and nav_step.count is defined and nav_step.count > 0 %}` guard
    short-circuits safely regardless."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_MAX_UPLOAD_BYTES", "1")

    response = client.post(
        "/project/open",
        files={"project_file": ("studio-project.json", b"{}", "application/json")},
    )

    assert response.status_code == 413
    assert "could not be opened" in response.text
    assert "uxr-rail-chip" not in response.text


# ---------------------------------------------------------------------------
# Step 2: readiness/capability chips sourced from the view-model, legend
# ---------------------------------------------------------------------------


def test_step2_flag_on_renders_readiness_and_capability_chips_from_view_model(monkeypatch):
    """Every chip must be sourced from readiness_view.items_for_step(session,
    2) -- proven by asserting the rendered chip for each row matches that
    row's own view-model item, not a hand-picked expectation. This fixture's
    real upstream edge contracts reach ready, warning, and blocks_export
    (draft/metadata_only are covered separately below via synthetic
    injection, since they are not reachable via genuine session state)."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = _readiness_session()
    save_session(session)

    html = client.get("/upstream").text
    items = readiness_view.items_for_step(session, 2)
    assert {item.state for item in items} == {"blocks_export", "warning", "ready"}  # fixture sanity

    for item in items:
        window = _step2_board_row_window(html, item.display_name)
        expected_class = _STATE_CHIP_CLASS[item.state]
        expected_label = _STATE_CHIP_LABEL[item.state]
        expected_cap = _CAPABILITY_LABEL[item.capability]
        assert f'class="badge {expected_class}">{expected_label}</span>' in window, (
            f"{item.display_name}: expected {expected_class}/{expected_label} chip"
        )
        assert f'class="uxr-board-cap">{expected_cap}</span>' in window, (
            f"{item.display_name}: expected capability chip {expected_cap!r}"
        )


def test_step2_flag_on_renders_draft_state_and_metadata_only_capability_via_synthetic_item(monkeypatch):
    """`draft` and `metadata_only` are not reachable through any real
    UpstreamInterface field combination today (see module docstring). This
    proves the template still renders both correctly via a synthetic
    ReadinessItem injected at the route's call site and matched by name to a
    real row -- it does not claim either is reachable via genuine session
    state today (mirrors test_step5_triage_board.py's identical technique)."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = _readiness_session()
    save_session(session)

    synthetic_item = ReadinessItem(
        item_id="usc:csv-ready",
        item_kind="upstream_contract",
        family="csv",
        display_name="csv-ready",
        state="draft",
        export_blocking=False,
        coverage=[Cov(label="Required fields", complete=1, total=1)],
        capability="metadata_only",
    )
    original = upstream_route.readiness_view.items_for_step

    def _patched(session, step):
        items = original(session, step)
        return [synthetic_item if it.display_name == "csv-ready" else it for it in items]

    monkeypatch.setattr(upstream_route.readiness_view, "items_for_step", _patched)

    html = client.get("/upstream").text
    window = _step2_board_row_window(html, "csv-ready")
    assert 'class="badge badge-draft">Draft</span>' in window
    assert 'class="uxr-board-cap">METADATA ONLY</span>' in window


def test_step2_flag_on_shows_single_readiness_verdict_not_legacy_badge(monkeypatch):
    """Finding-1 fix: under the flag the view-model chip is the sole readiness
    verdict; the legacy row.status `.badge` is suppressed so a row never shows
    two divergent verdicts (e.g. "Ready to export" beside "Review"). The
    fixture reaches ready/warning/blocks_export, so none of the three legacy
    status verdict labels may appear as a badge under the flag."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = _readiness_session()
    save_session(session)

    html = client.get("/upstream").text
    for legacy_status in ("Ready to export", "Reference only", "Incomplete"):
        for legacy_class in ("badge-confirmed", "badge-draft", "badge-warning"):
            assert f'<span class="badge {legacy_class}">{legacy_status}</span>' not in html, (
                f"legacy status badge {legacy_status!r} must be suppressed under the flag"
            )
    # the new readiness chip is present instead
    assert 'data-uxr-board="upstream"' in html
    assert 'class="uxr-board-row-right"' in html


def test_step2_flag_on_row_tint_agrees_with_its_own_readiness_chip(monkeypatch):
    """Re-review finding: the <tr> zone-ready tint keyed on the legacy
    row.status ("Ready to export"), which can be true at the same time the
    view-model state is "warning" (an XML contract with mappings saved but a
    blank entity_name fires an advisory warning that doesn't affect
    will_export/has_content) -- the row visually said "ready" (green tint)
    while its own chip said "Review". Verified this combination is genuinely
    reachable (not hypothetical) via edge_contract_readiness()/items_for_step()
    directly before writing this assertion. The tint must now key on the same
    view-model state the chip uses, so the two never disagree."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = get_session()
    session.app_name = "Tint Agreement"
    session.bounded_context = "tint-agreement"
    session.app_archetype = "crud"
    session.upstream_interfaces = [
        UpstreamInterface(
            name="xml-ready-warn", type="xml-xsd",
            xsd_path="contracts/acct.xsd", xsd_content="<xs:schema/>",
            root_element="AccountMessage",
            field_mappings=[FieldMapping(source="Account.accountId", target="AccountId")],
            entity_name=None,
        ),
    ]
    save_session(session)

    items = readiness_view.items_for_step(session, 2)
    item = next(i for i in items if i.display_name == "xml-ready-warn")
    assert item.state == "warning"  # fixture sanity -- proves this is reachable, not hypothetical

    html = client.get("/upstream").text
    window = _step2_board_row_window(html, "xml-ready-warn")
    assert 'data-uxr-row-state="warning"' in window
    assert 'class="badge badge-warning">Review</span>' in window


def test_retired_flag_off_value_keeps_step2_board_chips(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    session = _readiness_session()
    save_session(session)

    html = client.get("/upstream").text

    assert 'data-uxr-board="upstream"' in html
    assert 'class="uxr-board-cap"' in html
    assert 'class="badge badge-warning">Blocked</span>' in html


def test_step2_flag_on_renders_legend_with_every_state_and_capability_key(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = _readiness_session()
    save_session(session)

    html = client.get("/upstream").text
    legend_start = html.index('class="uxr-readiness-legend"')
    legend_end = html.index("</div>", legend_start)
    legend = html[legend_start:legend_end]

    assert 'badge-ready">Ready</span> Export allowed' in legend
    assert 'badge-warning">Review</span>' in legend
    assert 'badge-warning">Blocked</span>' in legend
    assert 'badge-draft">Draft</span>' in legend
    assert 'uxr-board-cap">MANIFEST REF</span>' in legend


# ---------------------------------------------------------------------------
# A11y: shape+label (no colour-only chip)
# ---------------------------------------------------------------------------

_CHIP_SPAN_RE = _re.compile(
    r'<span ([^>]*class="[^"]*\b(?:uxr-readiness-chip|uxr-board-cap|uxr-rail-chip)\b[^"]*"[^>]*)>([^<]*)</span>'
)


def test_every_readiness_capability_and_rail_chip_has_text_or_aria_label(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = _phase04_session()
    save_session(session)

    html = client.get("/upstream").text
    matches = _CHIP_SPAN_RE.findall(html)
    assert matches, "expected at least one chip span in this fixture"
    for attrs, text in matches:
        has_visible_text = text.strip() != ""
        has_aria_label = 'aria-label="' in attrs
        assert has_visible_text or has_aria_label, f"chip with attrs={attrs!r} has neither text nor aria-label"


# ---------------------------------------------------------------------------
# Grep-guards: single-producer rule + no redefinition of existing selectors
# ---------------------------------------------------------------------------


def test_step2_board_row_never_rederives_state_from_legacy_row_status():
    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    macro_start = html.index("{% macro uxr_us_row")
    macro_end = html.index("{% endmacro %}", macro_start)
    macro = html[macro_start:macro_end]
    assert "row.status" not in macro
    assert "row.required_missing" not in macro
    assert "item.state" in macro
    assert "item.capability" in macro


def test_new_selectors_do_not_redefine_pre_existing_uxr_chip_or_uxr_board_cap():
    css = _STUDIO_CSS.read_text(encoding="utf-8")
    assert css.count("body.ux-refresh .uxr-chip {") == 1, (
        "the pre-existing PR-07 board-filter .uxr-chip selector must not be redefined"
    )
    assert css.count("uxr-board-cap {") == 1, (
        "the pre-existing PR-06/07 .uxr-board-cap pairing must not be redefined -- "
        "PR-11 reuses it verbatim on the Step 2 capability chip instead of introducing a new neutral"
    )


# ---------------------------------------------------------------------------
# WCAG contrast: B1 finding (c) gate. Independently recomputed from whatever
# hex/var() values are actually shipped in studio.css (mirrors
# tests/test_family_zone_skin.py and tests/test_step5_triage_board.py).
# ---------------------------------------------------------------------------


def _css_var(name: str) -> str:
    css = _STUDIO_CSS.read_text(encoding="utf-8")
    match = _re.search(rf"--{_re.escape(name)}\s*:\s*(#[0-9a-fA-F]{{3,6}})", css)
    assert match, f"--{name} not found in studio.css"
    return match.group(1)


def _rule_body(selector: str) -> str:
    css = _STUDIO_CSS.read_text(encoding="utf-8")
    match = _re.search(_re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert match, f"{selector} rule not found in studio.css"
    return match.group(1)


def _declared_color(selector: str, prop: str) -> str:
    body = _rule_body(selector)
    match = _re.search(rf"{prop}\s*:\s*([^;]+);", body)
    assert match, f"{prop} not found in {selector} rule body"
    value = match.group(1).strip()
    var_match = _re.match(r"var\(--([a-zA-Z0-9-]+)\)$", value)
    return _css_var(var_match.group(1)) if var_match else value


def _srgb_to_linear(c: int) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(ch * 2 for ch in hex_color)
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    R, G, B = _srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b)
    return 0.2126 * R + 0.7152 * G + 0.0722 * B


def _contrast_ratio(hex1: str, hex2: str) -> float:
    l1, l2 = _relative_luminance(hex1), _relative_luminance(hex2)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _chip_contrast(selector: str) -> float:
    color = _declared_color(selector, "color")
    background = _declared_color(selector, "background")
    return _contrast_ratio(color, background)


def test_uxr_chip_ready_passes_aa():
    """#0f6a32 on #e7f5ec = 5.97:1 (old design-system value #15803d = 4.46:1,
    below AA -- B1 finding c)."""
    ratio = _chip_contrast("body.ux-refresh .uxr-chip-ready")
    assert ratio >= 4.5, f".uxr-chip-ready = {ratio:.2f}:1, below AA 4.5"


def test_uxr_chip_warning_passes_aa():
    """#96450a on #fdf7e8 = 6.23:1."""
    ratio = _chip_contrast("body.ux-refresh .uxr-chip-warning")
    assert ratio >= 4.5, f".uxr-chip-warning = {ratio:.2f}:1, below AA 4.5"


def test_uxr_chip_draft_passes_aa():
    """#4f6075 on #eef1f6 = 5.69:1 (old design-system value #68788c = 3.99:1,
    below AA -- B1 finding c)."""
    ratio = _chip_contrast("body.ux-refresh .uxr-chip-draft")
    assert ratio >= 4.5, f".uxr-chip-draft = {ratio:.2f}:1, below AA 4.5"


def test_uxr_chip_blocked_passes_aa():
    """Reuses the existing --danger/--danger-soft pair (same as
    .knowledge-status-dot.is-failed) = 4.94:1 -- not a new neutral."""
    ratio = _chip_contrast("body.ux-refresh .uxr-chip-blocked")
    assert ratio >= 4.5, f".uxr-chip-blocked = {ratio:.2f}:1, below AA 4.5"


def test_uxr_rail_chip_passes_aa():
    """Reuses the existing --muted-on-tint on --surface-muted pairing already
    established for .uxr-board-tag/.uxr-board-cap = 5.30:1. (The rail chip is
    intentionally text-only — see the CSS comment — so there is no separate
    attention-colour pairing to verify.)"""
    ratio = _chip_contrast("body.ux-refresh .uxr-rail-chip")
    assert ratio >= 4.5, f".uxr-rail-chip = {ratio:.2f}:1, below AA 4.5"


def test_old_failing_chip_baseline_would_not_pass_aa():
    """Documents why B1 finding (c) required darker chip text: these are the
    ORIGINAL design-system reference colors (edgeforge-studio-design-system.
    html's `.pill.ok` / `.pill.draft`), never shipped in studio.css, and both
    fail AA on the exact same soft fills the new, darker chip text now
    clears -- mirrors test_family_zone_skin.py's `--warn`-would-fail sanity
    check."""
    assert _contrast_ratio("#15803d", "#e7f5ec") < 4.5
    assert _contrast_ratio("#68788c", "#eef1f6") < 4.5
