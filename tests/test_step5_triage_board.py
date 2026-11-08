"""PR-07 acceptance tests: Step 5 downstream triage board (collapse-only).

Covers the §2 Phase-1 PR-07 acceptance bar: one summary row per represented
downstream contract, rendered server-side from `readiness_view.items_for_step`
(never re-derived); attention-state items (`blocks_export`/`needs_action`)
grouped before the rest; ambient stats strip; state/family filter chips;
collapse-only expand-one-at-a-time over the untouched legacy `.iface-card`
editor. Board half only -- the split-panel focus editor is PR-12.

Fixture note (mirrors `tests/test_family_zone_skin.py`'s own convention): every
state->field combination below was verified directly against
`readiness_view._downstream_interface_items` / `edge_contracts.
edge_contract_readiness` before writing these assertions (not hand-predicted):
  fixed-ready=ready, fixed-warn=warning, csv-ready=ready,
  csv-blocked=blocks_export, xml-ready=ready, xml-warn=warning,
  soap-blocked=blocks_export, soap-ready=ready.

`draft` is NOT reachable through any real `DownstreamInterface` field
combination today. `edge_contract_readiness()`'s `REFERENCE_ONLY` branch
always appends a "no uploaded artifact content" warning in the same branch
that sets `status = REFERENCE_ONLY` (edge_contracts.py ~L1401-1405), and
`_state_for_edge_contract` checks `if row.warnings: return STATE_WARNING`
*before* `if row.status == REFERENCE_ONLY: return STATE_DRAFT` -- so the
warning check always wins first. Confirmed by direct probing across every
field combination tried (fixed/csv/xml/soap, all directions), and by the
pre-existing `tests/test_readiness_view.py`, which never imports or exercises
`STATE_DRAFT` either -- this is a pre-existing characteristic of
`readiness_view.py`/`edge_contracts.py`, out of scope for this PR (which
touches neither file). `test_draft_state_and_alt_capability_render_correctly`
below proves the *template* still renders a draft-state / non-default-
capability row correctly, by injecting synthetic items at the route's call
site -- it does not claim either is reachable via genuine session state today.
"""
from __future__ import annotations

import json
import re as _re
from pathlib import Path as _Path

from fastapi.testclient import TestClient

import app.routes.downstream as downstream_route
from app.main import app
from app.models.project import DownstreamInterface, FieldMapping, LayoutField
from app.services.readiness_view import Cov, ReadinessItem
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)

_TEMPLATE_PATH = (
    _Path(__file__).resolve().parent.parent / "app" / "templates" / "step5_downstream.html"
)
_STUDIO_CSS = _Path(__file__).resolve().parent.parent / "app" / "static" / "css" / "studio.css"

BOARD_ITEM_NAMES = [
    "fixed-ready",
    "fixed-warn",
    "csv-ready",
    "csv-blocked",
    "xml-ready",
    "xml-warn",
    "soap-blocked",
    "soap-ready",
]
ATTENTION_NAMES = ["csv-blocked", "soap-blocked"]
WARNING_NAMES = ["fixed-warn", "xml-warn"]
READY_NAMES = ["fixed-ready", "csv-ready", "xml-ready", "soap-ready"]


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _triage_board_session():
    """8 board-represented downstream interfaces spanning ready/warning/
    blocks_export across all 4 edge-contract families, plus one rest-json
    interface (outside EDGE_CONTRACT_TYPES, but genuinely constructible --
    SUPPORTED_INTERFACE_TYPES = {REST_OPENAPI_TYPE, *EDGE_CONTRACT_TYPES}, and
    validate_edge_contract_payload's real /downstream/save route accepts it
    too, checked directly) to prove non-represented interfaces are never
    auto-hidden."""
    session = get_session()
    session.app_name = "Triage Board Fixture"
    session.bounded_context = "triage-board-fixture"
    session.app_archetype = "crud"
    session.downstream_interfaces = [
        DownstreamInterface(
            name="fixed-ready", type="file-fixed-width",
            spec="downstream/fixed-ready-layout.yaml",
            spec_content="format: fixed-width\nrecord_types:\n  data:\n    fields: []\n",
            entity_name="Account",
            layout_fields=[LayoutField(name="accountId", start=1, length=20)],
            field_mappings=[FieldMapping(source="Account.accountId", target="accountId")],
        ),
        DownstreamInterface(
            name="fixed-warn", type="file-fixed-width",
            spec="downstream/fixed-warn-layout.yaml",
            spec_content="format: fixed-width\nrecord_types:\n  data:\n    fields: []\n",
        ),
        DownstreamInterface(
            name="csv-ready", type="file-csv",
            spec="downstream/csv-ready.yaml",
            spec_content=(
                "format: csv\n"
                "delimiter: ','\n"
                "record_types:\n"
                "  data:\n"
                "    fields:\n"
                "      - name: accountId\n"
                "        column: 1\n"
            ),
            entity_name="Account",
            field_mappings=[FieldMapping(source="Account.accountId", target="accountId")],
        ),
        DownstreamInterface(name="csv-blocked", type="file-csv"),
        DownstreamInterface(
            name="xml-ready", type="xml-xsd",
            xsd_path="contracts/out.xsd", xsd_content="<xs:schema/>", root_element="Msg",
            entity_name="Account",
            field_mappings=[FieldMapping(source="Account.accountId", target="msgId")],
        ),
        DownstreamInterface(
            name="xml-warn", type="xml-xsd",
            xsd_path="contracts/out2.xsd", xsd_content="<xs:schema/>", root_element="Msg2",
        ),
        DownstreamInterface(name="soap-blocked", type="soap-wsdl"),
        DownstreamInterface(
            name="soap-ready", type="soap-wsdl",
            wsdl_path="contracts/svc.wsdl", wsdl_content="<definitions/>",
            selected_operation_name="DoThing",
        ),
        DownstreamInterface(
            name="rest-out", type="rest-json",
            spec="contracts/rest.yaml", entity_name="Account",
        ),
    ]
    save_session(session)
    return session


# ---------------------------------------------------------------------------
# Flag-off: zero board markers; legacy table/cards unchanged.
# ---------------------------------------------------------------------------

def test_retired_flag_off_value_keeps_default_on_triage_board(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    _triage_board_session()

    response = client.get("/downstream")
    html = response.text

    assert response.status_code == 200
    assert 'data-uxr-board="downstream"' in html
    assert "uxr-stat-strip" in html
    assert "uxrInitStep5TriageBoard" in html
    js_start = html.index("const existing = ")
    js_end = html.index(";", js_start)
    existing_data = json.loads(html[js_start + len("const existing = "):js_end])
    assert {d["name"] for d in existing_data} == {*BOARD_ITEM_NAMES, "rest-out"}


# ---------------------------------------------------------------------------
# Flag-on: one row per represented item, attention-first, correct pill/
# family/blocker/warning per row.
# ---------------------------------------------------------------------------

def test_flag_on_renders_exactly_one_row_per_represented_item_attention_first(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()

    response = client.get("/downstream")
    html = response.text

    assert response.status_code == 200
    assert html.count('class="uxr-board-row"') == len(BOARD_ITEM_NAMES)
    for name in BOARD_ITEM_NAMES:
        assert html.count(f'data-uxr-row-name="{name}"') == 1
    assert 'data-uxr-row-name="rest-out"' not in html

    ordered_names = ATTENTION_NAMES + WARNING_NAMES + READY_NAMES
    positions = [html.index(f'data-uxr-row-name="{n}"') for n in ordered_names]
    assert positions == sorted(positions), (
        "attention-state rows (csv-blocked, soap-blocked) must render before "
        "every non-attention row, in document order"
    )


def test_flag_on_pill_text_and_class_match_state_mapping(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/downstream").text

    ordered_names = ATTENTION_NAMES + WARNING_NAMES + READY_NAMES
    positions = [html.index(f'data-uxr-row-name="{n}"') for n in ordered_names]
    windows = {}
    for i, name in enumerate(ordered_names):
        start = positions[i]
        end = positions[i + 1] if i + 1 < len(positions) else len(html)
        windows[name] = html[start:end]

    expectations = {
        "fixed-ready": ("badge-ready", "Ready"),
        "csv-ready": ("badge-ready", "Ready"),
        "xml-ready": ("badge-ready", "Ready"),
        "soap-ready": ("badge-ready", "Ready"),
        "fixed-warn": ("badge-warning", "Review"),
        "xml-warn": ("badge-warning", "Review"),
        "csv-blocked": ("badge-warning", "Blocked"),
        "soap-blocked": ("badge-warning", "Blocked"),
    }
    for name, (badge_class, label) in expectations.items():
        window = windows[name]
        assert f'class="badge {badge_class}"' in window, f"{name}: expected badge class {badge_class}"
        assert f">{label}</span>" in window, f"{name}: expected pill text {label}"


def test_flag_on_warning_line_reuses_pasted_artifact_content_copy_fix(monkeypatch):
    """`edge_contract_readiness()` emits the same literal "...no uploaded
    artifact content..." warning for every reference-only contract type. The
    pre-existing legacy readiness table (a few lines below the board)
    rewrites this to "pasted artifact content" for display, since Studio's
    actual flow is paste-not-upload -- confirmed as a real, load-bearing
    rewrite by `tests/test_studio_ka_off.py::
    test_crud_wizard_routes_render_without_ks_calls_when_assist_off`, which
    asserts "uploaded artifact content" never appears anywhere on the
    rendered page. The new board's warning line must apply the identical
    rewrite for the same reason (a fixed-width interface with field
    mappings but no spec/spec_content -- entity_name + mappings present so
    only the reference-only warning fires, no mapping warning)."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = get_session()
    session.app_name = "Reference Only Fixture"
    session.bounded_context = "reference-only-fixture"
    session.app_archetype = "crud"
    session.downstream_interfaces = [
        DownstreamInterface(
            name="ledger-file", type="file-fixed-width",
            entity_name="Account",
            field_mappings=[FieldMapping(source="Account.accountId", target="account_id")],
        ),
    ]
    save_session(session)

    html = client.get("/downstream").text
    assert "uploaded artifact content" not in html
    row_start = html.index('data-uxr-row-name="ledger-file"')
    window = html[row_start:row_start + 1200]
    assert 'class="uxr-board-row-warning"' in window
    assert "pasted artifact content" in window


def test_flag_on_family_monogram_tile_matches_contract_type(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/downstream").text

    expectations = {
        "fixed-ready": "FIX", "fixed-warn": "FIX",
        "csv-ready": "CSV", "csv-blocked": "CSV",
        "xml-ready": "XML", "xml-warn": "XML",
        "soap-blocked": "SOAP", "soap-ready": "SOAP",
    }
    for name, mono in expectations.items():
        idx = html.index(f'data-uxr-row-name="{name}"')
        window = html[idx:idx + 400]
        assert f'uxr-fam-{mono.lower() if mono != "FIX" else "fixed"}' in window
        assert f">{mono}</span>" in window


def test_flag_on_blocker_line_shows_top_blocker_for_attention_items(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = _triage_board_session()
    html = client.get("/downstream").text

    items_by_name = {i.display_name: i for i in downstream_route.readiness_view.items_for_step(session, 5)}
    for name in ATTENTION_NAMES:
        expected_label = items_by_name[name].blockers[0].label
        row_start = html.index(f'data-uxr-row-name="{name}"')
        window = html[row_start:row_start + 1200]
        assert f'<div class="uxr-board-row-blocker">{expected_label}</div>' in window


def test_flag_on_warning_line_shows_top_warning_for_warning_state_items(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = _triage_board_session()
    html = client.get("/downstream").text

    items_by_name = {i.display_name: i for i in downstream_route.readiness_view.items_for_step(session, 5)}
    for name in ("fixed-warn", "xml-warn"):
        expected_label = items_by_name[name].warnings[0].label
        row_start = html.index(f'data-uxr-row-name="{name}"')
        window = html[row_start:row_start + 1200]
        assert f'<div class="uxr-board-row-warning">{expected_label}</div>' in window


def test_flag_on_all_represented_rows_render_without_pagination_or_pre_expansion(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/downstream").text

    assert html.count('class="uxr-board-row"') == len(BOARD_ITEM_NAMES)
    assert "uxr-board-row hidden" not in html
    assert "uxr-board-row is-editing" not in html
    assert "pagination" not in html.lower()


def test_flag_on_ambient_stats_strip_shows_correct_counts(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/downstream").text

    strip_start = html.index('class="uxr-stat-strip')
    strip_end = html.index("</div>", strip_start)
    strip = html[strip_start:strip_end]
    assert "uxr-zone-attn" in strip, "attention items present -> attn tint, not ready tint"
    assert 'data-uxr-stat="total">8</strong> downstream contracts' in strip
    assert 'data-uxr-stat="ready">4</strong> ready' in strip
    assert 'data-uxr-stat="attention">2</strong> need action' in strip
    assert 'data-uxr-stat="review">2</strong> need review' in strip
    assert 'data-uxr-stat="blockers">2</strong> export blockers' in strip


def test_flag_on_filter_chips_render_with_correct_counts_and_default_state(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/downstream").text

    assert (
        '<button type="button" class="uxr-chip is-on" aria-pressed="true" '
        'data-uxr-filter="state:all">All &middot; <span class="uxr-chip-count">8</span></button>' in html
    )
    assert (
        'aria-pressed="false" data-uxr-filter="state:attention">Needs action &middot; '
        '<span class="uxr-chip-count">2</span></button>' in html
    )
    assert (
        'aria-pressed="false" data-uxr-filter="state:review">Needs review &middot; '
        '<span class="uxr-chip-count">2</span></button>' in html
    )
    assert (
        'aria-pressed="false" data-uxr-filter="state:ready">Ready &middot; '
        '<span class="uxr-chip-count">4</span></button>' in html
    )
    for fam, mono in (("fixed", "FIX"), ("csv", "CSV"), ("xml", "XML"), ("soap", "SOAP")):
        assert f'aria-pressed="false" data-uxr-filter="family:{fam}">{mono}</button>' in html


def test_flag_on_no_needs_review_group_or_filter_when_no_warning_items(monkeypatch):
    """Guards against the opposite failure mode of the mislabeling bug: the
    'Needs review' group/filter chip must not leak in when there genuinely
    are no warning-state items (single ready-only fixture)."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = get_session()
    session.app_name = "Ready Only"
    session.bounded_context = "ready-only"
    session.app_archetype = "crud"
    session.downstream_interfaces = [
        DownstreamInterface(
            name="only-ready", type="file-csv",
            spec="downstream/only-ready.yaml",
            spec_content="format: delimited\ndelimiter: ','\n",
            entity_name="Account",
            field_mappings=[FieldMapping(source="Account.accountId", target="accountId")],
        ),
    ]
    save_session(session)

    html = client.get("/downstream").text
    # Scoped to the rendered heading rather than a bare "Needs review" page
    # scan: PR-17's uxrRegroupBoardRow() needs the group labels as JS constants
    # (UXR_BOARD_GROUPS), so that literal now ships inside the always-present
    # <script> on every flag-on page regardless of which groups actually
    # render. data-uxr-group is only ever emitted on a real server-rendered
    # heading, so it isolates what this test means. (Same false-positive class
    # PR-17a fixed for 'data-uxr-stat="attention"'.)
    assert 'data-uxr-group="review"' not in html
    assert ">Needs review</div>" not in html
    assert 'data-uxr-filter="state:review"' not in html


def test_family_filter_chips_hidden_when_only_one_family_present(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = get_session()
    session.app_name = "Single Family"
    session.bounded_context = "single-family"
    session.app_archetype = "crud"
    session.downstream_interfaces = [
        DownstreamInterface(
            name="only-fixed", type="file-fixed-width",
            spec="downstream/only-fixed.yaml",
            spec_content="format: fixed-width\nrecord_types:\n  data:\n    fields: []\n",
            entity_name="Account",
            field_mappings=[FieldMapping(source="Account.accountId", target="accountId")],
        ),
    ]
    save_session(session)

    html = client.get("/downstream").text
    assert 'data-uxr-filter="family:fixed"' not in html
    assert "uxr-chip-sep" not in html


def test_flag_on_edit_button_target_matches_iface_name_join_key(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/downstream").text
    for name in BOARD_ITEM_NAMES:
        assert f'data-uxr-edit-target="{name}"' in html
        # PR-17a item 6: Edit must be a real <a href> link, not a
        # JS-navigated <button> -- so it is natively dirty-guardable and
        # keyboard-navigable (mirrors Step 2's already-correct precedent).
        assert (
            f'<a href="/downstream?focus={name}" class="uxr-board-edit-btn" '
            f'data-uxr-edit-target="{name}">Edit</a>'
        ) in html


# ---------------------------------------------------------------------------
# Independent-review fix: rows must surface the artifact path AND a
# type-specific family fact (both were previously missing entirely).
# ---------------------------------------------------------------------------

def test_flag_on_row_shows_artifact_path_and_family_specific_fact(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/downstream").text

    expectations = {
        "fixed-ready": ("downstream/fixed-ready-layout.yaml", "1 col · 1/1 mapped"),
        "csv-ready": ("downstream/csv-ready.yaml", "delimiter comma (,)"),
        "xml-ready": ("contracts/out.xsd", "root Msg"),
        "soap-ready": ("contracts/svc.wsdl", "operation DoThing · adapter-only"),
    }
    for name, (path, fact) in expectations.items():
        row_start = html.index(f'data-uxr-row-name="{name}"')
        window = html[row_start:row_start + 1000]
        assert 'class="uxr-board-row-meta"' in window, f"{name}: expected a meta line"
        assert f"<code>{path}</code>" in window, f"{name}: expected artifact path {path}"
        if fact:
            assert fact in window, f"{name}: expected family fact {fact!r}"


def test_flag_on_row_omits_meta_line_when_neither_path_nor_fact_available(monkeypatch):
    """`csv-blocked`/`soap-blocked` in the shared fixture have no spec path
    and no operation selected yet -- the meta line must not render an empty
    or broken div for them."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/downstream").text

    for name in ("csv-blocked", "soap-blocked"):
        row_start = html.index(f'data-uxr-row-name="{name}"')
        row_end = html.index(f'data-uxr-edit-target="{name}"', row_start)
        window = html[row_start:row_end]
        assert "uxr-board-row-meta" not in window, f"{name}: unexpected meta line with nothing to show"


def test_flag_on_fixed_width_fact_shows_column_count_and_mapping_coverage(monkeypatch):
    """Independent-review follow-up: fixed-width previously always returned
    no fact at all. Covers both the honest-absence case (no layout_fields)
    and partial mapping coverage (2 columns, only 1 mapped), not just the
    trivial 1/1 case already exercised by the shared fixture."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = get_session()
    session.app_name = "Fixed Width Fact"
    session.bounded_context = "fixed-width-fact"
    session.app_archetype = "crud"
    session.downstream_interfaces = [
        DownstreamInterface(
            name="fixed-no-layout", type="file-fixed-width",
            spec="downstream/fixed-no-layout.yaml",
            spec_content="format: fixed-width\nrecord_types:\n  data:\n    fields: []\n",
        ),
        DownstreamInterface(
            name="fixed-partial-mapped", type="file-fixed-width",
            spec="downstream/fixed-partial.yaml",
            spec_content="format: fixed-width\nrecord_types:\n  data:\n    fields: []\n",
            entity_name="Account",
            layout_fields=[
                LayoutField(name="accountId", start=1, length=20),
                LayoutField(name="status", start=21, length=10),
            ],
            field_mappings=[FieldMapping(source="Account.accountId", target="accountId")],
        ),
    ]
    save_session(session)

    html = client.get("/downstream").text

    row_start = html.index('data-uxr-row-name="fixed-no-layout"')
    row_end = html.index('data-uxr-edit-target="fixed-no-layout"', row_start)
    window = html[row_start:row_end]
    assert "<code>downstream/fixed-no-layout.yaml</code>" in window, "path alone still renders"
    assert "cols" not in window and "mapped" not in window, (
        "no layout_fields -> no fixed-width fact appended, not a bogus '0 cols' line"
    )

    row_start = html.index('data-uxr-row-name="fixed-partial-mapped"')
    window = html[row_start:row_start + 1000]
    assert "2 cols · 1/2 mapped" in window


# ---------------------------------------------------------------------------
# Defensive coverage: interface types outside EDGE_CONTRACT_TYPES are never
# auto-hidden (never added to the client-side hide-set).
# ---------------------------------------------------------------------------

def test_flag_on_type_outside_edge_contract_types_is_never_in_board_item_names(monkeypatch):
    """rest-json is outside EDGE_CONTRACT_TYPES but genuinely constructible
    (checked directly: SUPPORTED_INTERFACE_TYPES includes it, and
    validate_edge_contract_payload's real save-route path accepts it too --
    see edge_contracts.py L1021-1022). It must never appear in the server-
    rendered `uxrBoardItemNames` JS set: the client-side JS (only hides a
    `.iface-card` whose name IS in that set, so excluding it here is exactly
    what keeps its legacy card visible/unhidden -- never hide a card the
    board has no row to reveal it from."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/downstream").text

    js_start = html.index("const uxrBoardItemNames = new Set(")
    js_end = html.index(");", js_start)
    names = json.loads(html[js_start + len("const uxrBoardItemNames = new Set("):js_end])
    assert "rest-out" not in names
    assert set(names) == set(BOARD_ITEM_NAMES)
    assert 'data-uxr-row-name="rest-out"' not in html


# ---------------------------------------------------------------------------
# Template-level coverage for states/capabilities that are not reachable via
# genuine session fixtures today (see module docstring).
# ---------------------------------------------------------------------------

def test_draft_state_and_alt_capability_render_correctly(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()

    draft_item = ReadinessItem(
        item_id="dsi:draft-example",
        item_kind="downstream_interface",
        family="xml",
        display_name="draft-example",
        state="draft",
        export_blocking=False,
        coverage=[Cov(label="Required fields", complete=1, total=1)],
        capability="populates_entities",
    )
    original = downstream_route.readiness_view.items_for_step

    def _patched(session, step):
        return [*original(session, step), draft_item]

    monkeypatch.setattr(downstream_route.readiness_view, "items_for_step", _patched)

    html = client.get("/downstream").text
    row_start = html.index('data-uxr-row-name="draft-example"')
    window = html[row_start:row_start + 700]
    assert 'data-uxr-row-state="draft"' in window
    assert 'class="badge badge-draft"' in window
    assert ">Draft</span>" in window
    assert "ENTITY-POPULATING" in window

    # draft is not an attention state -- it renders in the "Ready" group,
    # after the "Ready" heading, never under "Needs action"
    ready_heading = html.index(">Ready</div>")
    assert ready_heading < row_start


# ---------------------------------------------------------------------------
# Grep-guards: the new code never re-derives/recomputes readiness.
# ---------------------------------------------------------------------------

def test_new_js_never_hardcodes_readiness_status_strings():
    """The new page JS is pure DOM show/hide over already-server-rendered
    state -- it must never recompute or re-derive readiness. It only
    branches on dataset.uxrRowState / dataset.uxrRowFamily."""
    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    js_start = html.index("const uxrBoardItemNames")
    js_end = html.index("</script>", js_start)
    js_block = html[js_start:js_end]
    for banned in ("Ready to export", "Incomplete", "Reference only"):
        assert banned not in js_block, f"new JS must not hardcode readiness string {banned!r}"


def test_new_board_jinja_never_rederives_state_from_row_status():
    """The new board block must key exclusively off `item.state` (the
    readiness_view.ReadinessItem contract) -- never off `row.status` or a
    hardcoded EdgeContractReadiness status string, which is what the
    pre-existing legacy readiness table (a few lines below) legitimately
    does instead."""
    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    board_start = html.index("{% set uxr_ds_items")
    board_end = html.index(
        '{% if uxr_split_focus %}</div><div class="uxr-focus-split-editor">{% endif %}',
        board_start,
    )
    board_block = html[board_start:board_end]
    assert "row.status" not in board_block
    assert "Ready to export" not in board_block
    assert "Reference only" not in board_block
    assert "item.state" in board_block


def test_family_dicts_defined_exactly_once_in_template_source():
    """§3 note: `uxr_family_by_type`/`uxr_family_mono` were hoisted earlier
    in the template so the new board (which renders before the legacy
    readiness table) can use them too -- there must still be exactly one
    definition of each, shared by both the legacy table and the new board."""
    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    assert html.count("{% set uxr_family_by_type") == 1
    assert html.count("{% set uxr_family_mono") == 1


# ---------------------------------------------------------------------------
# Independent-review fix: card lookup must use a stable identity, not the
# live (user-editable) .iface-name input value -- renaming an expanded
# interface must not break collapse/expand-one-at-a-time. This repo has no
# jsdom/Playwright harness (confirmed elsewhere in this initiative), so these
# are static source-text regression guards, mirroring PR-09a's precedent of
# documented static invariants in place of a live DOM-interaction test.
# ---------------------------------------------------------------------------

def test_add_interface_captures_stable_original_name_at_restore_time():
    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    restore_block_start = html.index("if (data) {")
    restore_block_end = html.index("\n  }", restore_block_start)
    restore_block = html[restore_block_start:restore_block_end]
    assert "card.dataset.uxrOriginalName = data.name" in restore_block, (
        "addInterface() must capture the original name once, at restore time, "
        "into a stable attribute the board's own bookkeeping can rely on"
    )


def test_card_lookup_matches_stable_attribute_not_live_input_value():
    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    js_start = html.index("const uxrBoardItemNames")
    js_end = html.index("</script>", js_start)
    js_block = html[js_start:js_end]

    find_fn_start = js_block.index("function uxrFindIfaceCardByName")
    find_fn_end = js_block.index("\n}", find_fn_start)
    find_fn = js_block[find_fn_start:find_fn_end]
    assert "dataset.uxrOriginalName" in find_fn
    assert "querySelector('.iface-name')" not in find_fn, (
        "uxrFindIfaceCardByName must not match on the live, user-editable "
        ".iface-name input value -- that breaks the moment someone renames "
        "the interface inside an expanded card"
    )

    init_fn_start = js_block.index("function uxrInitStep5TriageBoard")
    hide_loop_end = js_block.index("});", init_fn_start)
    hide_loop = js_block[init_fn_start:hide_loop_end]
    assert "dataset.uxrOriginalName" in hide_loop
    assert "querySelector('.iface-name')" not in hide_loop, (
        "the initial collapse-by-default loop must also key off the stable "
        "attribute, consistent with uxrFindIfaceCardByName"
    )


# ---------------------------------------------------------------------------
# Independent-review fix: active filter state must not be color-only --
# aria-pressed must be present initially and kept in sync on click.
# ---------------------------------------------------------------------------

def test_filter_chips_have_aria_pressed_matching_initial_on_state(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/downstream").text

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
    assert filter_handler.count("setAttribute('aria-pressed'") >= 4, (
        "state and family branches must both set aria-pressed on activate "
        "and clear it on every sibling chip they deactivate"
    )


# ---------------------------------------------------------------------------
# WCAG contrast: every new text-on-tint pairing this PR introduces, computed
# live from the actual shipped hex (mirrors tests/test_family_zone_skin.py).
# ---------------------------------------------------------------------------

def _css_var(name: str) -> str:
    css = _STUDIO_CSS.read_text(encoding="utf-8")
    match = _re.search(rf"--{_re.escape(name)}\s*:\s*(#[0-9a-fA-F]{{3,6}})", css)
    assert match, f"--{name} not found in studio.css"
    return match.group(1)


def _board_row_warning_color() -> str:
    css = _STUDIO_CSS.read_text(encoding="utf-8")
    match = _re.search(
        r"\.uxr-board-row-warning\s*\{[^}]*color:\s*(#[0-9a-fA-F]{3,6})", css, _re.DOTALL
    )
    assert match, "uxr-board-row-warning color rule not found in studio.css"
    return match.group(1)


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


def test_board_group_attn_heading_and_blocker_text_pass_aa_on_zone_attn():
    """`.uxr-board-group-attn`'s heading AND `.uxr-board-row-blocker` both
    use --danger as their text colour, and both only ever sit on --zone-attn
    (only blocks_export/needs_action rows get that background) -- one
    shared, live-recomputed check covers both usages."""
    danger = _css_var("danger")
    zone_attn = _css_var("zone-attn")
    ratio = _contrast_ratio(danger, zone_attn)
    assert ratio >= 4.5, f"--danger on --zone-attn = {ratio:.2f}:1, below AA 4.5"


def test_board_row_warning_text_passes_aa_on_zone_scan():
    """Warning-state rows do NOT get the --zone-attn background (only
    blocks_export/needs_action rows do) -- they sit on the board's own
    --zone-scan tint. Plain --warn measures only ~3.2-3.6:1 there (fails AA
    4.5:1), so `.uxr-board-row-warning` uses a darker amber instead (the
    mock's own inline-warning-text colour). This recomputes contrast against
    whatever hex is actually shipped, so a future edit reintroducing --warn
    (or any other non-compliant value) fails here rather than shipping."""
    warning_color = _board_row_warning_color()
    zone_scan = _css_var("zone-scan")
    ratio = _contrast_ratio(warning_color, zone_scan)
    assert ratio >= 4.5, f"{warning_color} on --zone-scan = {ratio:.2f}:1, below AA 4.5"

    warn_token = _css_var("warn")
    warn_ratio = _contrast_ratio(warn_token, zone_scan)
    assert warn_ratio < 4.5, (
        "sanity check: this test's premise is that plain --warn fails AA here; "
        "if --warn itself changed and now passes, .uxr-board-row-warning "
        "could safely switch back to var(--warn)"
    )


def test_board_tag_and_cap_text_passes_aa_on_surface_muted():
    """.uxr-board-tag / .uxr-board-cap render inside every row regardless of
    the row's own background (attention rows are on --zone-attn, the rest on
    --zone-scan), on their own opaque --surface-muted chip fill."""
    muted_on_tint = _css_var("muted-on-tint")
    surface_muted = _css_var("surface-muted")
    ratio = _contrast_ratio(muted_on_tint, surface_muted)
    assert ratio >= 4.5, f"--muted-on-tint on --surface-muted = {ratio:.2f}:1, below AA 4.5"


# ---------------------------------------------------------------------------
# Independent-review fix: removing a *restored* card (which has a board row)
# must reconcile the board -- not just delete the legacy card and leave a
# dead row/stale counts behind.
# ---------------------------------------------------------------------------

def test_flag_on_stat_strip_and_filter_chips_carry_stable_count_hooks(monkeypatch):
    """Live count recomputation after a client-side removal needs stable
    DOM hooks to target -- these must exist on initial render, independent
    of whether any removal ever happens."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _triage_board_session()
    html = client.get("/downstream").text

    for stat_key, expected in (("total", "8"), ("ready", "4"), ("attention", "2"), ("review", "2"), ("blockers", "2")):
        assert f'data-uxr-stat="{stat_key}">{expected}</strong>' in html, f"missing stat hook for {stat_key}"

    for filter_value in ("state:all", "state:attention", "state:review", "state:ready"):
        chip_start = html.index(f'data-uxr-filter="{filter_value}"')
        chip_end = html.index("</button>", chip_start)
        assert 'class="uxr-chip-count"' in html[chip_start:chip_end], (
            f"{filter_value} chip must wrap its count in .uxr-chip-count for live updates"
        )


def test_remove_interface_card_captures_name_before_removal_and_delegates():
    html = _TEMPLATE_PATH.read_text(encoding="utf-8")
    fn_start = html.index("function removeInterfaceCard")
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
        "must re-run filtering so a group left with zero rows hides itself "
        "(reuses the existing filter machinery rather than duplicating it)"
    )


def test_recompute_stats_derives_counts_from_live_dom_not_a_running_counter():
    """The recompute must re-derive every count from the current
    .uxr-board-row elements in the DOM (so it's correct after any number of
    removals in any order), not decrement a server-rendered starting number."""
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
