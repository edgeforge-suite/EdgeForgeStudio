"""PR-16 coverage for Step 5's tab-badge click behavior.

Closes the PR-12 gap: the focus editor's blocker/warning badges already carry
data-section-ref/data-field-ref (server-rendered), but nothing made them
clickable. This file verifies (a) the field_ref -> CSS selector map against
the real edge_contracts.py code path rather than a hand-written table, (b)
the new #wsdl/#xsd/#layout section anchors render, once per card, correctly
scoped for a multi-interface fixture, and (c) the click-handling JS itself via
static source inspection -- this repo has no jsdom, so JS behavior is verified
by source assertions, mirroring PR-07/08's precedent (see
test_step5_save_one.py::test_static_client_contract_preserves_cancel_dirty_and_single_payload_paths).
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models.project import DownstreamInterface
from app.services.edge_contracts import edge_contract_readiness, slug
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)
ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "app" / "templates" / "step5_downstream.html"


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


# ---------------------------------------------------------------------------
# field_ref -> CSS selector map, each verified against the real
# edge_contract_readiness()/slug() code path (not a hand-asserted table) --
# catches drift if either the required-field label wording or the slug
# function ever changes.
# ---------------------------------------------------------------------------


def test_xsd_path_or_content_slug_matches_real_missing_artifact_label():
    iface = DownstreamInterface(name="no-xsd", type="xml-xsd", root_element="Foo")

    readiness = edge_contract_readiness(iface, direction="downstream")

    assert readiness.required_missing == ["xsd_path or uploaded XSD content"]
    produced_slug = slug(readiness.required_missing[0])
    assert produced_slug == "xsd-path-or-uploaded-xsd-content"
    assert f"'{produced_slug}'" in TEMPLATE.read_text(encoding="utf-8")


def test_wsdl_path_or_content_slug_matches_real_missing_artifact_label():
    iface = DownstreamInterface(name="no-wsdl", type="soap-wsdl")

    readiness = edge_contract_readiness(iface, direction="downstream")

    assert readiness.required_missing == ["wsdl_path or uploaded WSDL content"]
    produced_slug = slug(readiness.required_missing[0])
    assert produced_slug == "wsdl-path-or-uploaded-wsdl-content"
    assert f"'{produced_slug}'" in TEMPLATE.read_text(encoding="utf-8")


def test_layout_spec_path_or_content_slug_matches_real_missing_artifact_label():
    iface = DownstreamInterface(name="no-layout", type="file-csv")

    readiness = edge_contract_readiness(iface, direction="downstream")

    assert readiness.required_missing == ["layout/spec path or uploaded layout/spec content"]
    produced_slug = slug(readiness.required_missing[0])
    assert produced_slug == "layout-spec-path-or-uploaded-layout-spec-content"
    assert f"'{produced_slug}'" in TEMPLATE.read_text(encoding="utf-8")


def test_root_element_slug_matches_real_missing_field_label():
    iface = DownstreamInterface(name="no-root", type="xml-xsd", xsd_path="contracts/x.xsd")

    readiness = edge_contract_readiness(iface, direction="downstream")

    assert readiness.required_missing == ["root element"]
    produced_slug = slug(readiness.required_missing[0])
    assert produced_slug == "root-element"
    assert f"'{produced_slug}'" in TEMPLATE.read_text(encoding="utf-8")


def test_selected_soap_operation_slug_matches_real_missing_field_label():
    """Only reachable as a *blocker* for a downstream canonical-mode contract
    with no operation selected -- upstream only ever warns on this (never
    populates required_missing), so it never reaches Step 5's badges."""
    iface = DownstreamInterface(
        name="no-op",
        type="soap-wsdl",
        wsdl_path="contracts/x.wsdl",
        soap_operation_mode="canonical",
    )

    readiness = edge_contract_readiness(iface, direction="downstream")

    assert "selected SOAP operation" in readiness.required_missing
    produced_slug = slug("selected SOAP operation")
    assert produced_slug == "selected-soap-operation"
    assert f"'{produced_slug}'" in TEMPLATE.read_text(encoding="utf-8")


def test_valid_artifact_path_slug_matches_real_invalid_path_label():
    """Fires on an invalid (not missing) artifact path -- constructed by
    setting an absolute xsd_path directly on the model (bypassing the
    payload-parsing layer, which would reject it earlier); mirrors
    package_path_error's own "must be relative" case."""
    iface = DownstreamInterface(name="bad-path", type="xml-xsd", xsd_path="/etc/passwd", root_element="Foo")

    readiness = edge_contract_readiness(iface, direction="downstream")

    assert readiness.required_missing == ["valid artifact path"]
    produced_slug = slug(readiness.required_missing[0])
    assert produced_slug == "valid-artifact-path"
    assert f"'{produced_slug}'" in TEMPLATE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Section anchors: present, and (per multi-card fixture) the click-handling
# JS is scoped per-card rather than relying on a bare document.getElementById.
# ---------------------------------------------------------------------------


def _multi_interface_session():
    session = get_session()
    session.app_name = "Tab Badge Fixture"
    session.bounded_context = "tab-badge-fixture"
    session.app_archetype = "crud"
    session.downstream_interfaces = [
        DownstreamInterface(name="account-xml", type="xml-xsd", root_element="AccountMessage", xsd_path="contracts/account.xsd"),
        DownstreamInterface(name="audit-fixed", type="file-fixed-width", spec="downstream/audit-layout.yaml", spec_content="format: fixed-width\n"),
        DownstreamInterface(name="billing-soap", type="soap-wsdl", wsdl_path="contracts/billing.wsdl"),
    ]
    save_session(session)


def test_section_anchors_render_in_the_shared_card_template(monkeypatch):
    """The three .iface-card sections (and their anchor ids) live only inside
    the single shared <template id="iface-template">; per-interface cards are
    cloned from it client-side (addInterface()'s tpl.content.cloneNode) on
    DOMContentLoaded, which a TestClient response never executes. So the
    anchor ids appear exactly once each in server-rendered HTML regardless of
    how many interfaces are in the session -- multiple cards (and the
    resulting *repeated* ids across clones, by design, see
    _SECTION_REF_BY_FAMILY) are a client-side-only property, covered instead
    by the static per-card-scoping source check below."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _multi_interface_session()

    html = client.get("/downstream?focus=account-xml").text

    assert html.count('id="wsdl"') == 1
    assert html.count('id="xsd"') == 1
    assert html.count('id="layout"') == 1
    assert (
        'class="edge-contract-section edge-file-section workflow-surface-detail" '
        'id="layout"'
    ) in html
    assert (
        'class="edge-contract-section edge-xml-section workflow-surface-detail hidden" '
        'id="xsd"'
    ) in html
    assert (
        'class="edge-contract-section edge-soap-section workflow-surface-detail hidden" '
        'id="wsdl"'
    ) in html


def test_click_handling_js_scopes_section_lookup_to_the_focused_card_not_globally():
    template = TEMPLATE.read_text(encoding="utf-8")

    scroll_start = template.index("function uxrScrollToSectionInCard(card, sectionRef)")
    scroll_end = template.index("\n}\n", scroll_start)
    scroll_body = template[scroll_start:scroll_end]

    # Scoped: card.querySelector(...), never a bare global lookup by this id.
    assert "card.querySelector(`[id=\"${sectionRef}\"]`)" in scroll_body
    assert "document.getElementById(sectionRef)" not in scroll_body
    assert "document.getElementById('wsdl')" not in template
    assert "document.getElementById('xsd')" not in template
    assert "document.getElementById('layout')" not in template

    # Both the badge-click path and the on-load hash path (finding 4, PR-16
    # #250) go through this one scoped helper rather than each re-implementing
    # their own (potentially unscoped) lookup.
    activate_start = template.index("function uxrActivateTabBadge(badge)")
    activate_end = template.index("\n}\n", activate_start)
    activate_body = template[activate_start:activate_end]
    assert "uxrScrollToSectionInCard(card, badge.dataset.sectionRef" in activate_body

    init_start = template.index("function uxrInitFocusedEditor()")
    init_end = template.index("\n}\n", init_start)
    init_body = template[init_start:init_end]
    assert "uxrScrollToSectionInCard(card, window.location.hash.slice(1))" in init_body


# ---------------------------------------------------------------------------
# Badge click handler: static JS-source checks (no jsdom in this repo).
# ---------------------------------------------------------------------------


def test_badges_are_real_buttons_not_inert_spans():
    template = TEMPLATE.read_text(encoding="utf-8")

    assert '<button type="button" class="badge badge-warning" data-section-ref=' in template
    assert "<span class=\"badge badge-warning\" data-section-ref=" not in template
    # The dynamic re-render path (after a save-one response) must match, or
    # badges revert to inert spans the moment the editor re-renders.
    assert "const badge = document.createElement('button');" in template
    assert "const badge = document.createElement('span');" not in template


def test_tab_badges_click_handler_is_delegated_on_the_container():
    template = TEMPLATE.read_text(encoding="utf-8")

    # Delegated on the container (not bound per-badge): uxrRenderEditorReadiness
    # calls badges.replaceChildren() on every save-one response, which would
    # silently drop any listener bound directly to an individual badge node.
    assert (
        "document.querySelector('[data-uxr-tab-badges]')?.addEventListener('click', event => {"
        in template
    )
    wiring_start = template.index("document.querySelector('[data-uxr-tab-badges]')?.addEventListener")
    wiring_end = template.index("});", wiring_start)
    wiring_body = template[wiring_start:wiring_end]
    assert "event.target.closest('.badge')" in wiring_body
    assert "uxrActivateTabBadge(badge)" in wiring_body

    # Wired inside uxrInitFocusedEditor, which only runs when a focus editor
    # is present -- guarded the same way every other focus-only listener in
    # this file already is (data-uxr-save-one, data-uxr-cancel-focus, ...).
    init_start = template.index("function uxrInitFocusedEditor()")
    init_end = template.index("\nfunction uxrInitStep5TriageBoard", init_start)
    assert "data-uxr-tab-badges" in template[init_start:init_end]


def test_activate_tab_badge_reads_section_and_field_ref_and_never_throws_on_unmapped_slug():
    template = TEMPLATE.read_text(encoding="utf-8")

    activate_start = template.index("function uxrActivateTabBadge(badge)")
    activate_end = template.index("\n}\n", activate_start)
    activate_body = template[activate_start:activate_end]

    assert "badge.dataset.sectionRef" in activate_body
    assert "badge.dataset.fieldRef" in activate_body
    # Scrolling is delegated to uxrScrollToSectionInCard (shared with the
    # on-load hash path below) rather than reimplemented inline here.
    assert "uxrScrollToSectionInCard(card, badge.dataset.sectionRef || '')" in activate_body
    assert ".focus()" in activate_body

    scroll_start = template.index("function uxrScrollToSectionInCard(card, sectionRef)")
    scroll_end = template.index("\n}\n", scroll_start)
    scroll_body = template[scroll_start:scroll_end]
    assert "scrollIntoView" in scroll_body

    # uxrFieldRefSelector returns null (not a throw) for an unmapped or empty
    # field_ref -- the caller's `if (selector)` guard means no match is a
    # silent no-op, never an exception. It consults two tables (readiness_view
    # slugs, then save-one's raw field names) since they're two different
    # vocabularies -- see UXR_SAVE_BLOCKER_FIELD_SELECTORS's own comment.
    selector_start = template.index("function uxrFieldRefSelector(card, fieldRef)")
    selector_end = template.index("\n}\n", selector_start)
    selector_body = template[selector_start:selector_end]
    assert "if (!fieldRef) return null;" in selector_body
    assert "UXR_FIELD_REF_SELECTORS[fieldRef] || UXR_SAVE_BLOCKER_FIELD_SELECTORS[fieldRef] || null" in selector_body


def test_on_load_hash_scroll_is_scoped_to_the_focused_card_not_native_fragment_nav():
    """Regression for a re-review finding on PR #250: a deep_link's
    #section_ref arrives as the page's own location.hash on load. Native
    browser fragment navigation runs before any script and resolves against
    whichever duplicate #wsdl/#xsd/#layout anchor is first in the DOM (often a
    hidden, wrong card) -- so uxrInitFocusedEditor must re-do the scroll
    itself, scoped to the now-focused card, rather than rely on the browser's
    own resolution."""
    template = TEMPLATE.read_text(encoding="utf-8")

    init_start = template.index("function uxrInitFocusedEditor()")
    init_end = template.index("\n}\n", init_start)
    init_body = template[init_start:init_end]

    assert "const card = uxrShowFocusedCard();" in init_body
    assert "if (window.location.hash) {" in init_body
    assert "uxrScrollToSectionInCard(card, window.location.hash.slice(1));" in init_body

    # The hash check must come after the card is resolved (so it can be
    # scoped to it) and before any dirty-tracker/listener wiring below it.
    card_pos = init_body.index("const card = uxrShowFocusedCard();")
    hash_pos = init_body.index("if (window.location.hash) {")
    dirty_pos = init_body.index("uxrDirtyTracker = window.createDirtyTracker(")
    assert card_pos < hash_pos < dirty_pos


def test_field_ref_selector_map_covers_all_six_verified_slugs():
    template = TEMPLATE.read_text(encoding="utf-8")
    map_start = template.index("const UXR_FIELD_REF_SELECTORS = {")
    map_end = template.index("};", map_start)
    map_body = template[map_start:map_end]

    assert "'xsd-path-or-uploaded-xsd-content': '.iface-xsd-path'" in map_body
    assert "'wsdl-path-or-uploaded-wsdl-content': '.iface-wsdl-path'" in map_body
    assert "'layout-spec-path-or-uploaded-layout-spec-content': '.iface-spec'" in map_body
    assert "'root-element': '.iface-root-element'" in map_body
    assert "'selected-soap-operation': '.iface-operation'" in map_body

    # valid-artifact-path is type-dependent (handled by its own branch, not a
    # static map entry) -- confirm the branch exists and covers all three
    # edge-contract artifact-path fields.
    selector_start = template.index("function uxrFieldRefSelector(card, fieldRef)")
    selector_end = template.index("\n}\n", selector_start)
    selector_body = template[selector_start:selector_end]
    assert "fieldRef === 'valid-artifact-path'" in selector_body
    assert "return '.iface-xsd-path';" in selector_body
    assert "return '.iface-wsdl-path';" in selector_body
    assert "return '.iface-spec';" in selector_body


def test_save_blocker_selector_map_covers_canonical_soap_authoring_controls():
    template = TEMPLATE.read_text(encoding="utf-8")
    map_start = template.index("const UXR_SAVE_BLOCKER_FIELD_SELECTORS = {")
    map_end = template.index("};", map_start)
    map_body = template[map_start:map_end]

    expected = {
        "soap_operation_mode": ".iface-soap-mode",
        "selected_operation_name": ".iface-operation",
        "soap_canonical_entity": ".soap-canonical-entity",
        "soap_lookup_field": ".soap-lookup-field",
        "soap_request_field": ".soap-request-field",
        "soap_response_mode": ".soap-response-mode",
    }
    for field_ref, selector in expected.items():
        assert f"{field_ref}: '{selector}'" in map_body
        assert f'class="{selector.removeprefix(".")}"' in template

    assert (
        "soap_request_mappings: '.soap-request-mapping-row .soap-request-source, "
        ".soap-request-mappings-container + button'"
    ) in map_body
    assert (
        "soap_response_mappings: '.soap-response-mapping-row .soap-response-source-path, "
        ".soap-response-mappings-container + button'"
    ) in map_body
