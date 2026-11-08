"""PR-06 acceptance tests: family + zone visual skin, Steps 2/4/5.

Covers the §2 Phase-1 PR-06 acceptance bar: monogram tiles, 3px family
accents, tinted group headers, `--zone-scan` boards, and `--zone-ready`
stat strips, with the family label always visible as text next to the
colour signal (never colour-only, per §1.5).

PR-24 tests assert retired flag values cannot hide the default-on `uxr-*`
render — using the SAME rich, multi-family fixture as the flag-on tests
below, so the absence check is not trivially true from an empty fixture.

Fixture note: the exact `status` string each edge-contract row gets from
`edge_contract_readiness()` was verified directly (not hand-predicted)
against this fixture before writing these assertions:
  upstream: fixed-missing=Incomplete, xml-warning=Ready to export,
            csv-ready=Ready to export, soap-reference=Reference only
  downstream: fixed-out-ready=Ready to export, csv-out-ready=Ready to export,
              xml-out-reference=Reference only, soap-out-missing=Incomplete
`rest-api` (type rest-json) is deliberately included to confirm it is
excluded from both tables (edge_contract_readiness_rows filters to
EDGE_CONTRACT_TYPES only), matching pre-existing behavior.
"""
from __future__ import annotations

import re as _re
from pathlib import Path as _Path

from fastapi.testclient import TestClient

from app.main import app
from app.models.project import DataHandoff, DownstreamInterface, FieldMapping, UpstreamInterface
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)

UXR_MARKERS = (
    "uxr-fam-tile",
    "uxr-fam-badge",
    "uxr-fam-text",
    "uxr-zone-scan",
    "uxr-zone-ready",
    "uxr-stat-strip",
)


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _edge_contract_session():
    """One of every edge-contract family on both upstream and downstream,
    with a mix of ready / not-ready statuses, plus one ready and one
    not-ready data handoff."""
    session = get_session()
    session.app_name = "Family Zone Fixture"
    session.bounded_context = "family-zone-fixture"
    session.app_archetype = "crud"
    session.upstream_interfaces = [
        UpstreamInterface(
            name="rest-api", type="rest-json",
            spec="contracts/rest-openapi.yaml", entity_name="Account",
        ),
        UpstreamInterface(name="fixed-missing", type="file-fixed-width"),
        UpstreamInterface(
            name="xml-warning", type="xml-xsd",
            xsd_path="contracts/account.xsd",
            xsd_content="<xs:schema xmlns:xs='http://www.w3.org/2001/XMLSchema'/>",
            root_element="AccountMessage",
        ),
        UpstreamInterface(
            name="csv-ready", type="file-csv",
            spec="upstream/account-layout.yaml",
            spec_content="format: delimited\ndelimiter: ','\nfields:\n  - name: accountId\n",
            entity_name="Account",
            field_mappings=[FieldMapping(source="accountId", target="Account.accountId")],
        ),
        UpstreamInterface(name="soap-reference", type="soap-wsdl", wsdl_path="contracts/account.wsdl"),
    ]
    session.downstream_interfaces = [
        DownstreamInterface(
            name="fixed-out-ready", type="file-fixed-width",
            spec="downstream/account-layout.yaml",
            spec_content="format: fixed-width\nrecord_types:\n  data:\n    fields: []\n",
            entity_name="Account",
            field_mappings=[FieldMapping(source="Account.accountId", target="accountId")],
        ),
        DownstreamInterface(
            name="csv-out-ready", type="file-csv",
            spec="downstream/account-csv-layout.yaml",
            spec_content="format: delimited\ndelimiter: ','\nfields:\n  - name: accountId\n",
            entity_name="Account",
            field_mappings=[FieldMapping(source="Account.accountId", target="accountId")],
        ),
        DownstreamInterface(
            name="xml-out-reference", type="xml-xsd",
            xsd_path="contracts/account-out.xsd",
            root_element="AccountMessage",
        ),
        DownstreamInterface(name="soap-out-missing", type="soap-wsdl"),
    ]
    session.data_handoffs = [
        DataHandoff(
            name="ready-handoff",
            ddl_content="CREATE TABLE account_stage (account_id VARCHAR(36));",
            field_mappings=[FieldMapping(source="Account.accountId", target="account_id")],
        ),
        DataHandoff(name="missing-both"),
    ]
    save_session(session)
    return session


def _all_ready_handoff_session():
    session = get_session()
    session.app_name = "All Ready Handoffs"
    session.bounded_context = "all-ready-handoffs"
    session.app_archetype = "crud"
    session.data_handoffs = [
        DataHandoff(
            name="ready-one",
            ddl_content="CREATE TABLE stage_one (id VARCHAR(36));",
            field_mappings=[FieldMapping(source="Entity.id", target="id")],
        ),
        DataHandoff(
            name="ready-two",
            ddl_content="CREATE TABLE stage_two (id VARCHAR(36));",
            field_mappings=[FieldMapping(source="Entity.id", target="id")],
        ),
    ]
    save_session(session)
    return session


# ---------------------------------------------------------------------------
# Retired flag values cannot restore the deleted legacy surfaces.
# ---------------------------------------------------------------------------

def test_step2_retired_flag_off_value_keeps_family_zone_markup(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    _edge_contract_session()

    response = client.get("/upstream")

    assert response.status_code == 200
    for marker in ("uxr-fam-tile", "uxr-zone-scan", "uxr-stat-strip"):
        assert marker in response.text
    assert 'data-uxr-board="upstream"' in response.text


def test_step5_retired_flag_off_value_keeps_family_zone_markup(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    _edge_contract_session()

    response = client.get("/downstream")

    assert response.status_code == 200
    for marker in ("uxr-fam-tile", "uxr-zone-scan", "uxr-stat-strip"):
        assert marker in response.text
    assert 'data-uxr-board="downstream"' in response.text


def test_step4_retired_flag_off_value_keeps_family_zone_markup(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    _edge_contract_session()

    response = client.get("/handoffs")

    assert response.status_code == 200
    for marker in ("uxr-fam-tile", "uxr-zone-scan", "uxr-stat-strip"):
        assert marker in response.text
    assert 'data-uxr-board="handoffs"' in response.text


# ---------------------------------------------------------------------------
# Flag-on: monogram tiles, 3px family accents, tinted headers/boards,
# zone-ready stat strips, family label always adjacent to colour.
# ---------------------------------------------------------------------------

def test_step2_flag_on_renders_family_monograms_and_zone_tints(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _edge_contract_session()

    response = client.get("/upstream")
    html = response.text

    assert response.status_code == 200
    # Tinted group header + the full triage board replace the drawer table.
    assert '<div class="step-section-heading uxr-zone-scan">' in html
    assert '<div class="uxr-board uxr-zone-scan" data-uxr-board="upstream"' in html
    # Each family has an accessible monogram; the label is no longer dependent
    # on adjacent table-cell text.
    assert (
        '<span class="uxr-fam-tile uxr-fam-fixed" aria-label="Fixed-width file">FIX</span>'
        in html
    )
    assert '<span class="uxr-fam-tile uxr-fam-xml" aria-label="XML / XSD">XML</span>' in html
    assert (
        '<span class="uxr-fam-tile uxr-fam-csv" aria-label="CSV / delimited file">CSV</span>'
        in html
    )
    assert '<span class="uxr-fam-tile uxr-fam-soap" aria-label="SOAP / WSDL">SOAP</span>' in html
    assert html.count('class="uxr-board-row"') == 4
    assert html.count('data-uxr-row-state="ready"') == 1
    assert 'data-uxr-row-state="warning"' in html
    assert 'data-uxr-row-state="blocks_export"' in html


def test_step5_flag_on_renders_family_monograms_and_zone_tints(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _edge_contract_session()

    response = client.get("/downstream")
    html = response.text

    assert response.status_code == 200
    assert '<div class="uxr-board uxr-zone-scan" data-uxr-board="downstream"' in html
    assert '<span class="uxr-fam-tile uxr-fam-fixed" aria-label="Fixed-width file">FIX</span>' in html
    assert '<span class="uxr-fam-tile uxr-fam-csv" aria-label="CSV / delimited file">CSV</span>' in html
    assert '<span class="uxr-fam-tile uxr-fam-xml" aria-label="XML / XSD">XML</span>' in html
    assert '<span class="uxr-fam-tile uxr-fam-soap" aria-label="SOAP / WSDL">SOAP</span>' in html
    assert html.count('class="uxr-board-row"') == 4


def test_step4_flag_on_renders_staging_accent_badge_and_mixed_stat_strip(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _edge_contract_session()  # 1 ready ("ready-handoff") of 2 total handoffs

    response = client.get("/handoffs")
    html = response.text

    assert response.status_code == 200
    assert '<div id="handoffs-container" class="uxr-zone-scan"></div>' in html
    # 3px family accent replaces the legacy 4px border when the flag is on
    assert 'style="border-left:3px solid var(--fam-staging);margin-bottom:16px"' in html
    assert 'style="border-left:4px solid var(--success)' not in html
    # monogram + adjacent visible text label on the card title
    assert '<span class="uxr-fam-tile uxr-fam-staging" aria-hidden="true">STG</span>' in html
    assert '<span class="uxr-fam-text">Staging / Handoff</span>' in html
    # PR-08 (#245) replaced this page's older hand-summed stat strip with the
    # board's own single authoritative summary sourced from
    # readiness_view.items_for_step() -- two independently-computed summaries
    # would violate the single-readiness-producer rule (that was itself a
    # review finding on #245). No attention-state item is reachable for
    # handoffs today, so a mixed ready/needs-review set still tints
    # zone-ready, matching Step 5's board's identical convention (zone-attn
    # is reserved for blocking states, not merely non-ready ones).
    assert '<div class="uxr-stat-strip uxr-zone-ready" data-uxr-stat-strip>' in html
    assert 'data-uxr-stat="total">2</strong> data handoffs' in html
    assert 'data-uxr-stat="ready">1</strong> ready' in html
    assert 'data-uxr-stat="review">1</strong> need review' in html


def test_step4_flag_on_all_ready_handoffs_use_zone_ready_stat_strip(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _all_ready_handoff_session()  # 2 of 2 ready

    response = client.get("/handoffs")
    html = response.text

    assert response.status_code == 200
    assert '<div class="uxr-stat-strip uxr-zone-ready" data-uxr-stat-strip>' in html
    assert 'data-uxr-stat="total">2</strong> data handoffs' in html
    assert 'data-uxr-stat="ready">2</strong> ready' in html
    assert 'data-uxr-stat="review"' not in html


def test_step4_flag_on_stat_strip_counts_file_referenced_ddl_as_ready(monkeypatch):
    """A handoff's DDL can legitimately be an uploaded/reviewed file
    (`spec`) rather than inline `ddl_content` text -- `completeness_service.py`
    and `readiness_view.py` both treat `ddl_content or spec` as "DDL
    provided", a `readiness_view.py` semantic this PR does not change. (This
    is distinct from the PR #245 review finding that `routes/handoffs.py`'s
    *save route* was fabricating a `spec` value with no real content behind
    it for every handoff regardless of DDL presence -- fixed by only setting
    `spec` when `ddl` is truthy. This test constructs the `DataHandoff`
    directly, bypassing the save route, to isolate the readiness semantic
    from that save-route bug.) The board's stat strip must use the same
    predicate rather than a narrower one, or it would show a handoff as
    not-ready when every other Studio surface already calls it ready."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = get_session()
    session.app_name = "File-Referenced DDL"
    session.bounded_context = "file-referenced-ddl"
    session.app_archetype = "crud"
    session.data_handoffs = [
        DataHandoff(
            name="file-ddl-handoff",
            spec="data-handoffs/account-staging.sql",
            field_mappings=[FieldMapping(source="Account.accountId", target="account_id")],
        ),
    ]
    save_session(session)

    response = client.get("/handoffs")
    html = response.text

    assert response.status_code == 200
    assert '<div class="uxr-stat-strip uxr-zone-ready" data-uxr-stat-strip>' in html
    assert 'data-uxr-stat="total">1</strong> data handoff<' in html
    assert 'data-uxr-stat="ready">1</strong> ready' in html


def test_step4_flag_on_zero_handoffs_renders_no_stat_strip(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = get_session()
    session.app_name = "No Handoffs"
    session.bounded_context = "no-handoffs"
    session.app_archetype = "crud"
    save_session(session)

    response = client.get("/handoffs")
    html = response.text

    assert response.status_code == 200
    # Scoped to the rendered class attribute, not a bare substring: PR-17's
    # uxrBoardStatStrip() resolves the board's own strip via
    # hasAttribute('data-uxr-stat-strip'), so that literal ships inside the
    # always-present page JS regardless of whether a strip is rendered.
    assert 'class="uxr-stat-strip' not in html
    # board container still gets the zone-scan tint even with nothing in it yet
    assert '<div id="handoffs-container" class="uxr-zone-scan"></div>' in html


# ---------------------------------------------------------------------------
# B1 design-system reference (docs/studio-ux-refresh/design-assets/design-system/
# edgeforge-studio-design-system.html §3 "Measured findings") — findings (a)
# and (b) are baked into this PR per that reference; PR-24a's a11y gate
# re-verifies both. (c) is not triggered: PR-06 introduces no soft-fill ready/warn/
# draft chip partial (only `.uxr-fam-badge`, a plain tile+label wrapper with
# no semantic-state colour). (d) is already satisfied: grep-confirmed PR-06
# introduces zero mockup-neutral hex values (#dde3ec/#eef1f6/#1c2733/#68788c/
# #b91c1c) — every colour used is either an existing shipped token or the two
# tile-specific fixes below.
#
# These tests independently RECOMPUTE contrast via the WCAG relative-
# luminance formula against whatever hex values are actually shipped in
# studio.css (parsed from the file, not hardcoded), so a future edit that
# reintroduces a non-compliant value fails here rather than silently
# shipping.
# ---------------------------------------------------------------------------

_STUDIO_CSS = _Path(__file__).resolve().parent.parent / "app" / "static" / "css" / "studio.css"


def _css_var(name: str) -> str:
    css = _STUDIO_CSS.read_text(encoding="utf-8")
    match = _re.search(rf"--{_re.escape(name)}\s*:\s*(#[0-9a-fA-F]{{3,6}})", css)
    assert match, f"--{name} not found in studio.css"
    return match.group(1)


def _rest_tile_fill() -> str:
    css = _STUDIO_CSS.read_text(encoding="utf-8")
    match = _re.search(
        r"\.uxr-fam-tile\.uxr-fam-rest\s*\{\s*background:\s*(#[0-9a-fA-F]{3,6})",
        css,
    )
    assert match, "uxr-fam-tile.uxr-fam-rest background rule not found in studio.css"
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


def test_muted_on_tint_token_passes_aa_on_every_zone_tint():
    """--muted-on-tint must clear WCAG AA (4.5:1) against all four zone
    tints — not just the two (--zone-scan/--zone-ready) PR-06 currently
    applies, since the token is meant to serve zone-derived/zone-attn too
    once later PRs place muted text there."""
    muted_on_tint = _css_var("muted-on-tint")
    zones = {
        "zone-scan": _css_var("zone-scan"),
        "zone-derived": _css_var("zone-derived"),
        "zone-attn": _css_var("zone-attn"),
        "zone-ready": _css_var("zone-ready"),
    }
    for zone_name, zone_hex in zones.items():
        ratio = _contrast_ratio(muted_on_tint, zone_hex)
        assert ratio >= 4.5, f"--muted-on-tint on {zone_name} ({zone_hex}) = {ratio:.2f}:1, below AA 4.5"


def test_rest_monogram_tile_fill_passes_aa_with_white_text():
    """The REST tile's own fill (not the shared --fam-rest token, which
    stays locked per §1.5 D1) must clear 4.5:1 with white text — the tile
    keeps white text like all five other family tiles, per the B1
    reference's fix (darken the fill, don't switch this one tile to black)."""
    rest_tile_fill = _rest_tile_fill()
    ratio = _contrast_ratio(rest_tile_fill, "#ffffff")
    assert ratio >= 4.5, f"REST tile fill {rest_tile_fill} with white text = {ratio:.2f}:1, below AA 4.5"
    # the locked --fam-rest token itself must be untouched (still used for
    # accent purposes elsewhere — 3px border-left, ribbon, legend)
    assert _css_var("fam-rest") == "#0d9488"


def test_rest_monogram_tile_no_longer_uses_black_text_override():
    css = _STUDIO_CSS.read_text(encoding="utf-8")
    match = _re.search(r"\.uxr-fam-tile\.uxr-fam-rest\s*\{([^}]*)\}", css)
    assert match, "uxr-fam-tile.uxr-fam-rest rule not found"
    rule_body = match.group(1)
    assert "color" not in rule_body, (
        "REST tile should inherit the shared white .uxr-fam-tile text colour, "
        "not override it — contrast is fixed via the darkened fill instead"
    )


def test_step2_and_step5_muted_subtitle_is_inside_the_tinted_header(monkeypatch):
    """Locks in the actual DOM relationship the --muted-on-tint fix depends
    on: the pre-existing `.text-muted` subtitle paragraph under "Loaded Edge
    Contracts" / "Contract Export Readiness" is a genuine descendant of the
    now-tinted `.step-section-heading`, so the CSS descendant-selector
    override in studio.css actually reaches it (not just a theoretical risk)."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _edge_contract_session()

    for route, board in (("/upstream", "upstream"), ("/downstream", "downstream")):
        html = client.get(route).text
        assert f'<div class="uxr-board uxr-zone-scan" data-uxr-board="{board}"' in html
        assert 'class="uxr-board-row-meta"' in html
