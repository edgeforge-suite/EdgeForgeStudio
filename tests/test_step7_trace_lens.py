"""PR-21 coverage for Step 7's Contract Trace Lens (Part A) and the flag-off
byte/marker guarantee.

Single-producer discipline: every pill/state/blocker the Trace Lens renders
must be the *same* readiness_view.ReadinessItem the Step 2/3/4/5 boards
already read (app/routes/review.py's _trace_lens_context and friends only
group those items -- readiness_view.py itself is untouched by this PR and is
never re-derived here). Every assertion below that touches a pill/state/
blocker/deep_link cross-checks against a live call to
readiness_view.items_for_step / item_by_display_name for the same fixture,
never a hand-typed expectation -- mirroring tests/test_step5_triage_board.py's
own documented convention (see that file's module docstring).

Fixture states were verified directly against edge_contracts.
edge_contract_readiness()/readiness_view._entity_item() before writing the
assertions below (not hand-predicted):
  account-rest-api: rest-json, outside EDGE_CONTRACT_TYPES -> no readiness
    item at all (plain provenance ref, no pill/Fix link).
  account-fixed-feed: file-fixed-width, spec + spec_content + field_mappings
    + entity_name -> ready.
  account-audit-xml: xml-xsd, xsd_path + xsd_content + root_element but NO
    field_mappings -> the upstream "no reviewed XML-to-canonical mappings"
    warning fires -> warning (state precedence checks warnings before the
    reference-only/draft branch, so this is genuinely reachable, unlike
    draft -- see the synthetic-injection test below for that one).
  account-xml-blocked: xml-xsd, nothing set -> missing xsd_path/content AND
    root element -> blocks_export.
  account-fixed-out: file-fixed-width downstream, spec + spec_content +
    field_mappings -> ready.
  ledger-soap-blocked: soap-wsdl downstream, nothing set -> missing
    wsdl_path/content -> blocks_export.
  account-staging handoff: ddl_content + field_mappings whose target matches
    the DDL columns -> ready.
  orphan-handoff: no ddl, no mappings, no entity_name -> warning (belongs to
    no entity's trace at all).
  Account entity: persistence_id decision + is_id field both resolve to
    "accountId" -> ready.
  Ledger entity: no identity_role_decisions, no is_id field -> needs_action.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app.routes.review as review_route
from app.main import app
from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    DataHandoff,
    DownstreamInterface,
    FieldMapping,
    IdentityRoleDecision,
    OperationSample,
    UpstreamInterface,
)
from app.services import readiness_view
from app.services.readiness_view import Cov, ReadinessItem
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)
TEMPLATE = Path(__file__).resolve().parent.parent / "app" / "templates" / "step7_review.html"


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _trace_lens_session():
    session = get_session()
    session.app_name = "Trace Lens Fixture"
    session.bounded_context = "trace-lens-fixture"
    session.app_archetype = "crud"
    session.classified_entities = [
        ClassifiedEntity(
            name="Account",
            fields=[
                ClassifiedField(name="accountId", type="string", is_id=True),
                ClassifiedField(name="status", type="string"),
            ],
        ),
        ClassifiedEntity(
            name="Ledger",
            fields=[
                ClassifiedField(name="ledgerId", type="string"),
                ClassifiedField(name="amount", type="decimal"),
            ],
        ),
    ]
    session.selected_entity_names = ["Account", "Ledger"]
    session.identity_role_decisions = [
        IdentityRoleDecision(entity="Account", field="accountId", role="persistence_id"),
        IdentityRoleDecision(entity="Account", field="status", role="business_key"),
    ]
    session.upstream_interfaces = [
        UpstreamInterface(
            name="account-rest-api", type="rest-json", entity_name="Account",
            operations=[OperationSample(name="getAccount"), OperationSample(name="listAccounts")],
        ),
        UpstreamInterface(
            name="account-fixed-feed", type="file-fixed-width", entity_name="Account",
            spec="upstream/account-fixed.yaml",
            spec_content="format: fixed-width\nrecord_types:\n  data:\n    fields: []\n",
            field_mappings=[FieldMapping(source="accountId", target="Account.accountId")],
        ),
        UpstreamInterface(
            name="account-audit-xml", type="xml-xsd", entity_name="Account",
            xsd_path="contracts/account-audit.xsd", xsd_content="<xs:schema/>", root_element="AuditMsg",
        ),
        UpstreamInterface(name="account-xml-blocked", type="xml-xsd", entity_name="Account"),
    ]
    session.downstream_interfaces = [
        DownstreamInterface(
            name="account-fixed-out", type="file-fixed-width", entity_name="Account",
            spec="downstream/account-fixed-out.yaml",
            spec_content="format: fixed-width\nrecord_types:\n  data:\n    fields: []\n",
            field_mappings=[FieldMapping(source="Account.accountId", target="accountId")],
        ),
        DownstreamInterface(name="ledger-soap-blocked", type="soap-wsdl", entity_name="Ledger"),
    ]
    session.data_handoffs = [
        DataHandoff(
            name="account-staging", entity_name="Account", table_name="ACCOUNT_STG",
            ddl_content="CREATE TABLE account_stage (account_id VARCHAR(36), status VARCHAR(20));",
            field_mappings=[FieldMapping(source="Account.accountId", target="account_id")],
        ),
        DataHandoff(name="orphan-handoff"),
    ]
    save_session(session)
    return session


# ---------------------------------------------------------------------------
# Flag-off: no Trace Lens markers leak; legacy Step 7 render is unaffected.
# ---------------------------------------------------------------------------


def test_retired_flag_off_value_keeps_trace_lens_markers(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    _trace_lens_session()

    response = client.get("/review")
    html = response.text

    assert response.status_code == 200
    for marker in (
        "data-trace-lens",
        "Contract Trace Lens",
        "rsummary",
        "tracelens",
        "tracepick",
        "otherblk",
        "entsel",
        "dirnote",
        "Trace by entity",
    ):
        assert marker in html, f"default-on render missed marker: {marker}"
    assert 'class="review-summary-strip"' not in html


# ---------------------------------------------------------------------------
# Flag-on: readiness summary strip, entity grouping, pills/blockers/deep
# links, unrelated-blockers strip, entity card -- all cross-checked against
# live readiness_view calls, never hand-predicted.
# ---------------------------------------------------------------------------


def test_readiness_summary_strip_buckets_match_live_readiness_states(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = _trace_lens_session()

    all_items = [
        *readiness_view.items_for_step(session, 2),
        *readiness_view.items_for_step(session, 3),
        *readiness_view.items_for_step(session, 4),
        *readiness_view.items_for_step(session, 5),
    ]
    expected_ready = sum(
        1 for i in all_items if i.state in (readiness_view.STATE_READY, readiness_view.STATE_DRAFT)
    )
    expected_warnings = sum(
        1 for i in all_items if i.state in (readiness_view.STATE_WARNING, readiness_view.STATE_NEEDS_ACTION)
    )
    expected_blocks_export = sum(1 for i in all_items if i.state == readiness_view.STATE_BLOCKS_EXPORT)
    # Sanity: every item lands in exactly one of the three buckets above --
    # confirms the fixture doesn't silently exercise a 4th state this test
    # forgot to bucket.
    assert expected_ready + expected_warnings + expected_blocks_export == len(all_items)

    html = client.get("/review").text
    strip_start = html.index('data-trace-lens-summary')
    strip_end = html.index("</div>\n\n", strip_start)
    strip = html[strip_start:strip_end]
    assert f'<span class="n">{expected_ready}</span><span class="l">Ready</span>' in strip
    assert f'<span class="n">{expected_warnings}</span><span class="l">Warnings</span>' in strip
    # PR-23 renamed this label "Blocks export" -> "Contract blockers". The
    # count is unchanged (still readiness_view's blocks_export bucket over
    # Steps 2-5); the old wording implied a package-wide scope it never had,
    # and once PR-23 made this the sole flag-on summary that read as a claim
    # the strip could not honour. The authoritative export gate now sits
    # beside it in the `data-export-gate` cell.
    assert f'<span class="n">{expected_blocks_export}</span><span class="l">Contract blockers</span>' in strip


def test_entity_picker_lists_both_entities_first_visible_second_hidden(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _trace_lens_session()

    html = client.get("/review").text

    assert '<option value="Account">Account</option>' in html
    assert '<option value="Ledger">Ledger</option>' in html
    account_pos = html.index('<option value="Account">')
    ledger_pos = html.index('<option value="Ledger">')
    assert account_pos < ledger_pos, "Account must be the first (default-visible) option"

    account_block_start = html.index('data-trace-lens-block="Account"')
    account_block_class_start = html.rindex('class="trace', 0, account_block_start)
    account_block_open_tag = html[account_block_class_start:account_block_start]
    assert "hidden" not in account_block_open_tag, "first entity's trace block must be visible by default"

    ledger_block_start = html.index('data-trace-lens-block="Ledger"')
    ledger_block_class_start = html.rindex('class="trace', 0, ledger_block_start)
    ledger_block_open_tag = html[ledger_block_class_start:ledger_block_start]
    assert "hidden" in ledger_block_open_tag, "non-first entity's trace block must start hidden"


def test_account_trace_groups_refs_by_entity_name_and_pills_match_readiness_view(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = _trace_lens_session()

    upstream_by_name = {i.display_name: i for i in readiness_view.items_for_step(session, 2)}
    downstream_by_name = {i.display_name: i for i in readiness_view.items_for_step(session, 5)}
    handoff_by_name = {i.display_name: i for i in readiness_view.items_for_step(session, 4)}

    assert upstream_by_name["account-fixed-feed"].state == readiness_view.STATE_READY
    assert upstream_by_name["account-audit-xml"].state == readiness_view.STATE_WARNING
    assert upstream_by_name["account-xml-blocked"].state == readiness_view.STATE_BLOCKS_EXPORT
    assert downstream_by_name["account-fixed-out"].state == readiness_view.STATE_READY
    assert handoff_by_name["account-staging"].state == readiness_view.STATE_READY

    html = client.get("/review").text
    block_start = html.index('data-trace-lens-block="Account"')
    block_end = html.index('data-trace-lens-unrelated="Account"', block_start)
    block = html[block_start:block_end]

    # account-rest-api: not itemized by readiness_view (REST/OpenAPI source),
    # but it populates Account, and Account IS itemized -> the row carries the
    # POPULATED ENTITY's readiness from the same P6 model (review finding 3,
    # round 2). Account has a persistence key here -> ready -> "Ready" pill,
    # tagged data-trace-ref-via="entity", no Fix (the entity owns that). The
    # pill MUST equal the live entity item's state -- never hand-predicted.
    assert "account-rest-api" not in upstream_by_name
    account_entity = readiness_view.item_by_display_name(
        session, "Account", item_kinds=(readiness_view.ITEM_KIND_ENTITY,)
    )
    assert account_entity is not None and account_entity.state == readiness_view.STATE_READY
    rest_ref_start = block.index('data-trace-ref="account-rest-api"')
    rest_ref = block[rest_ref_start : rest_ref_start + 600]
    assert 'data-trace-ref-via="entity"' in rest_ref
    assert f'data-trace-ref-state="{account_entity.state}"' in rest_ref
    assert '<span class="pill ok"' in rest_ref  # ready entity -> ok pill
    assert ">Ready</span>" in rest_ref
    assert "populates Account" in rest_ref       # provenance names the entity
    assert "jump" not in rest_ref                # no Fix on the source row
    assert "pill source" not in rest_ref

    # account-fixed-feed: ready -> .pill.ok "Ready", joined via the real item.
    fixed_ref_start = block.index('data-trace-ref="account-fixed-feed"')
    fixed_ref = block[fixed_ref_start : fixed_ref_start + 500]
    assert f'data-trace-ref-state="{upstream_by_name["account-fixed-feed"].state}"' in fixed_ref
    assert '<span class="pill ok">Ready</span>' in fixed_ref

    # account-audit-xml: warning -> .pill.attn "Review".
    warn_ref_start = block.index('data-trace-ref="account-audit-xml"')
    warn_ref = block[warn_ref_start : warn_ref_start + 500]
    assert f'data-trace-ref-state="{upstream_by_name["account-audit-xml"].state}"' in warn_ref
    assert '<span class="pill attn">Review</span>' in warn_ref

    # account-xml-blocked: blocks_export -> .ref.blocked carrying a TEXTUAL
    # state pill ("Blocks export"), the blocker reason line, and a Fix link
    # using the item's real deep_link + a contextual aria-label (review finding
    # 2: state is never colour/border alone, and Fix is never a bare repeat).
    real_blocked_item = upstream_by_name["account-xml-blocked"]
    assert real_blocked_item.blockers, "fixture must produce a genuine blocker to exercise the Fix link"
    expected_deep_link = real_blocked_item.blockers[0].deep_link
    blocked_ref_start = block.index('data-trace-ref="account-xml-blocked"')
    blocked_ref_container_start = block.rindex('<div class="ref', 0, blocked_ref_start)
    blocked_ref = block[blocked_ref_container_start : blocked_ref_container_start + 900]
    assert 'class="ref blocked"' in blocked_ref
    assert '<span class="pill attn">Blocks export</span>' in blocked_ref  # textual state
    assert 'class="rreason"' in blocked_ref                                # blocker reason line
    assert f'href="{expected_deep_link}"' in blocked_ref                   # real deep_link
    assert 'aria-label="Fix account-xml-blocked:' in blocked_ref           # contextual accessible name

    # Downstream/handoff columns: account-fixed-out (ready) and
    # account-staging (ready, listed before the downstream ref per the
    # handoffs-then-downstream ordering in the "-> EMITS" column).
    dn_col_start = block.index('class="col dn workflow-surface-detail"')
    dn_col = block[dn_col_start:]
    handoff_pos = dn_col.index('data-trace-ref="account-staging"')
    downstream_pos = dn_col.index('data-trace-ref="account-fixed-out"')
    assert handoff_pos < downstream_pos, "handoffs render before downstream refs in the EMITS column"
    assert '<span class="pill ok">Ready</span>' in dn_col[handoff_pos : handoff_pos + 500]
    assert '<span class="pill ok">Ready</span>' in dn_col[downstream_pos : downstream_pos + 500]

    # ledger-soap-blocked belongs to Ledger, not Account -- must never appear
    # inside Account's own trace block.
    assert "ledger-soap-blocked" not in block


def test_unrelated_blockers_strip_shows_the_other_entitys_blocker_not_your_own(monkeypatch):
    """The P1 cross-entity check: Account's own blocked upstream ref
    (account-xml-blocked) must NOT appear in Account's unrelated-blockers
    strip (it's already shown as .ref.blocked in Account's own column) --
    but Ledger's blocked downstream ref (ledger-soap-blocked) must, since
    it's connected to a different entity. And vice versa for Ledger's strip."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = _trace_lens_session()

    upstream_by_name = {i.display_name: i for i in readiness_view.items_for_step(session, 2)}
    downstream_by_name = {i.display_name: i for i in readiness_view.items_for_step(session, 5)}
    account_blocker = upstream_by_name["account-xml-blocked"]
    ledger_blocker = downstream_by_name["ledger-soap-blocked"]
    assert account_blocker.blockers and ledger_blocker.blockers

    html = client.get("/review").text

    account_strip_start = html.index('data-trace-lens-unrelated="Account"')
    account_strip_end = html.index("</div>\n    </div>", account_strip_start)
    account_strip = html[account_strip_start:account_strip_end]
    assert f'href="{ledger_blocker.blockers[0].deep_link}"' in account_strip
    assert ledger_blocker.blockers[0].label in account_strip
    assert f'href="{account_blocker.blockers[0].deep_link}"' not in account_strip

    ledger_strip_start = html.index('data-trace-lens-unrelated="Ledger"')
    ledger_strip_end = html.index("</div>\n    </div>", ledger_strip_start)
    ledger_strip = html[ledger_strip_start:ledger_strip_end]
    assert f'href="{account_blocker.blockers[0].deep_link}"' in ledger_strip
    assert account_blocker.blockers[0].label in ledger_strip
    assert f'href="{ledger_blocker.blockers[0].deep_link}"' not in ledger_strip


def test_otherblk_still_renders_when_zero_unrelated_blockers_for_that_entity():
    """The strip must be always-present (never omitted just because it has
    nothing to show for the currently-traced entity) -- a session with only
    ONE entity and ONE genuinely unrelated blocker gives that single entity
    zero unrelated blockers of its own (its only blocker is its own)."""
    import os

    os.environ["EDGEFORGE_STUDIO_UX_REFRESH"] = "true"
    try:
        session = get_session()
        session.app_name = "Solo Entity Fixture"
        session.bounded_context = "solo-entity-fixture"
        session.app_archetype = "crud"
        session.classified_entities = [
            ClassifiedEntity(
                name="Widget",
                fields=[ClassifiedField(name="widgetId", type="string", is_id=True)],
            ),
        ]
        session.selected_entity_names = ["Widget"]
        session.upstream_interfaces = [
            UpstreamInterface(name="widget-xml-blocked", type="xml-xsd", entity_name="Widget"),
        ]
        save_session(session)

        html = client.get("/review").text
        strip_start = html.index('data-trace-lens-unrelated="Widget"')
        strip_end = html.index("</div>\n    </div>", strip_start)
        strip = html[strip_start:strip_end]
        assert "Other represented contract/handoff blockers not connected to Widget" in strip
        assert "None in this represented set." in strip
        assert "Package-wide export blockers are summarized above" in strip
        assert 'class="ob"' not in strip
    finally:
        os.environ.pop("EDGEFORGE_STUDIO_UX_REFRESH", None)


def test_entity_card_fields_match_live_identity_roles_and_edge_contracts_calls(monkeypatch):
    """Card metadata is descriptive (not a pill/state/blocker), so it is
    sourced from identity_roles/edge_contracts directly rather than a
    ReadinessItem -- this test cross-checks against those same production
    helpers called independently, rather than hand-typing expected numbers."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = _trace_lens_session()

    from app.services import identity_roles
    from app.services.edge_contracts import EDGE_CONTRACT_TYPES, _safe_persistence_fields

    account_entity = identity_roles.authoritative_entity(session, "Account")
    expected_account_field_count = len(account_entity.fields)
    expected_account_key = min(_safe_persistence_fields(session, "Account"))
    expected_account_role_count = len(identity_roles.active_identity_decisions_by_field(session).get("Account", {}))
    expected_account_contracts = sum(
        1
        for iface in (*session.upstream_interfaces, *session.downstream_interfaces)
        if iface.entity_name == "Account" and iface.type in EDGE_CONTRACT_TYPES
    )
    assert expected_account_field_count == 2
    assert expected_account_key == "accountId"
    assert expected_account_role_count == 2
    # account-fixed-feed + account-audit-xml + account-xml-blocked (upstream,
    # all EDGE_CONTRACT_TYPES) + account-fixed-out (downstream) = 4.
    # account-rest-api is excluded (rest-json is outside EDGE_CONTRACT_TYPES).
    assert expected_account_contracts == 4

    ledger_entity = identity_roles.authoritative_entity(session, "Ledger")
    expected_ledger_field_count = len(ledger_entity.fields)
    assert _safe_persistence_fields(session, "Ledger") == set()
    expected_ledger_role_count = len(identity_roles.active_identity_decisions_by_field(session).get("Ledger", {}))
    expected_ledger_contracts = sum(
        1
        for iface in (*session.upstream_interfaces, *session.downstream_interfaces)
        if iface.entity_name == "Ledger" and iface.type in EDGE_CONTRACT_TYPES
    )
    assert expected_ledger_field_count == 2
    assert expected_ledger_role_count == 0
    assert expected_ledger_contracts == 1

    html = client.get("/review").text
    account_card_start = html.index('<div class="en">Account</div>')
    account_card = html[account_card_start : account_card_start + 400]
    assert f'<div class="ek">&#128273; {expected_account_key}</div>' in account_card
    assert (
        f"{expected_account_field_count} fields &middot; {expected_account_role_count} roles "
        f"&middot; {expected_account_contracts} contracts" in account_card
    )

    ledger_card_start = html.index('<div class="en">Ledger</div>')
    ledger_card = html[ledger_card_start : ledger_card_start + 400]
    assert '<div class="ek">' not in ledger_card, "Ledger has no persistence key -- no key row at all"
    # 0 pluralizes as "roles" (only the exact count 1 is singular) -- 1
    # contract stays singular.
    assert (
        f"{expected_ledger_field_count} fields &middot; {expected_ledger_role_count} roles "
        f"&middot; {expected_ledger_contracts} contract" in ledger_card
    )


def test_entity_with_no_upstream_refs_shows_empty_state_copy_but_keeps_its_downstream_ref(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _trace_lens_session()

    html = client.get("/review").text
    block_start = html.index('data-trace-lens-block="Ledger"')
    block_end = html.index('data-trace-lens-unrelated="Ledger"', block_start)
    block = html[block_start:block_end]
    assert "No upstream references for this entity." in block
    # Ledger has a downstream ref (ledger-soap-blocked), so the downstream
    # empty-state copy must NOT render for it.
    assert "No downstream references for this entity." not in block


# ---------------------------------------------------------------------------
# Synthetic-injection coverage for a state genuinely unreachable via real
# session fixtures today, mirroring test_step5_triage_board.py::
# test_draft_state_and_alt_capability_render_correctly's own precedent and
# documented justification (edge_contract_readiness()'s REFERENCE_ONLY branch
# always also appends a warning in the same branch, so the warnings-checked-
# first state precedence in _state_for_edge_contract means STATE_DRAFT can
# never actually be produced by a real DownstreamInterface/UpstreamInterface
# -- confirmed by that file's own module docstring, which this PR's fixtures
# do not change or route around).
# ---------------------------------------------------------------------------


def test_draft_state_ref_renders_pill_ok_draft_via_synthetic_injection(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _trace_lens_session()

    draft_item = ReadinessItem(
        item_id="usc:account-fixed-feed",
        item_kind=readiness_view.ITEM_KIND_UPSTREAM_CONTRACT,
        family="fixed",
        display_name="account-fixed-feed",
        state="draft",
        export_blocking=False,
        coverage=[Cov(label="Required fields", complete=1, total=1)],
    )
    original = review_route.readiness_view.item_by_display_name

    def _patched(session, display_name, *, item_kinds=None):
        if display_name == "account-fixed-feed" and item_kinds == (readiness_view.ITEM_KIND_UPSTREAM_CONTRACT,):
            return draft_item
        return original(session, display_name, item_kinds=item_kinds)

    monkeypatch.setattr(review_route.readiness_view, "item_by_display_name", _patched)

    html = client.get("/review").text
    ref_start = html.index('data-trace-ref="account-fixed-feed"')
    ref = html[ref_start : ref_start + 500]
    assert 'data-trace-ref-state="draft"' in ref
    assert '<span class="pill ok">Draft</span>' in ref


# ---------------------------------------------------------------------------
# Static JS-source check for the entity-picker toggle (no jsdom in this
# repo -- mirrors tests/test_step5_tab_badge_focus.py's precedent).
# ---------------------------------------------------------------------------


def test_picker_toggle_js_uses_hidden_class_not_native_hidden_attribute():
    """`.trace` needs `display: grid` when shown, so a plain `hidden`
    attribute/property would lose the specificity fight against that rule
    (the pre-existing global `.hidden { display: none !important }` utility,
    studio.css:84, is what every other show/hide script in this app already
    uses for exactly this reason -- see step2/4/5's own classList.add/remove
    ('hidden') calls)."""
    template = TEMPLATE.read_text(encoding="utf-8")

    fn_start = template.index("function initTraceLensPicker()")
    fn_end = template.index("</script>", fn_start)
    fn_body = template[fn_start:fn_end]

    assert "classList.toggle('hidden'" in fn_body
    assert ".hidden = " not in fn_body
    assert "setAttribute('hidden'" not in fn_body
    assert "removeAttribute('hidden'" not in fn_body


def test_picker_toggle_js_is_always_present_and_guards_missing_picker():
    template = TEMPLATE.read_text(encoding="utf-8")

    guard_start = template.index("// PR-21 Trace Lens entity picker")
    guarded_block = template[guard_start:template.index("</script>", guard_start)]

    assert "function initTraceLensPicker()" in guarded_block
    assert "if (!picker) return;" in guarded_block
    assert "addEventListener('change'" in guarded_block
    # Progressive enhancement only: every block is already server-rendered,
    # so the handler must never fetch or otherwise hit the network.
    assert "fetch(" not in guarded_block
    assert "XMLHttpRequest" not in guarded_block


def test_unrelated_blockers_strip_shows_every_blocker_of_an_item_not_just_the_first(monkeypatch):
    """Review finding 2 (#258): the unrelated-blockers builder took only
    blockers[0], so an item with two blockers dropped the second when tracing
    another entity -- the exact thing the strip exists to prevent. An xml-xsd
    upstream with neither xsd_path nor root element yields TWO blockers; both
    must appear in a different entity's unrelated strip."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = get_session()
    session.app_name = "Two Blocker Fixture"
    session.bounded_context = "two-blocker-fixture"
    session.app_archetype = "crud"
    session.classified_entities = [
        ClassifiedEntity(name="Account", fields=[]),
        ClassifiedEntity(name="Widget", fields=[]),
    ]
    session.selected_entity_names = ["Account", "Widget"]
    # Two genuine blockers on one Account interface; Widget has its own ref so
    # its trace exists and the Account item is "unrelated" to it.
    session.upstream_interfaces = [
        UpstreamInterface(name="acct-xml-2blk", type="xml-xsd", entity_name="Account"),
        UpstreamInterface(name="widget-fixed", type="file-fixed-width", spec="w.yaml", entity_name="Widget"),
    ]
    save_session(session)

    item = readiness_view.item_by_display_name(
        get_session(), "acct-xml-2blk", item_kinds=(readiness_view.ITEM_KIND_UPSTREAM_CONTRACT,)
    )
    assert len(item.blockers) == 2, "fixture must produce a genuine two-blocker item"
    labels = [b.label for b in item.blockers]

    html = client.get("/review").text
    widget_strip_start = html.index('data-trace-lens-unrelated="Widget"')
    widget_strip = html[widget_strip_start : widget_strip_start + 1500]
    # BOTH blocker labels present -- not just blockers[0].
    for label in labels:
        assert label in widget_strip, f"unrelated strip dropped blocker: {label!r}"


def test_narrow_layout_hides_shared_header_and_uses_per_column_headings():
    """Review finding 4 (#258): at <=900px the shared 3-column .tracehd
    collapsed to one column but only the middle heading was hidden, stacking
    'Downstream references' above the upstream rows. The shared header must be
    hidden entirely narrow and each column carry its own .colhd heading."""
    template = TEMPLATE.read_text(encoding="utf-8")
    # Per-column headings exist in each column.
    assert template.count('<div class="colhd">') == 3
    assert '<div class="colhd">Upstream references</div>' in template
    assert '<div class="colhd">Canonical entity</div>' in template
    assert '<div class="colhd">Downstream references</div>' in template

    css = (Path(__file__).resolve().parent.parent / "app" / "static" / "css" / "studio.css").read_text(encoding="utf-8")
    # Anchor on THIS PR's trace media query -- studio.css already has an
    # unrelated @media (max-width: 900px) for .app-shell, so search from the
    # trace-specific comment, not the first 900px block.
    trace_media_anchor = css.index("Read-only lens, not the split-editor")
    media_block = css[trace_media_anchor : trace_media_anchor + 1200]
    # Narrow: the shared header is hidden outright (NOT just its .mid), and the
    # per-column headings are shown.
    assert "body.ux-refresh .tracehd {\n    display: none;\n  }" in media_block
    assert "body.ux-refresh .colhd {\n    display: block;\n  }" in media_block
    # The old ".mid only" hide (which caused the bug) is gone from this block.
    assert "body.ux-refresh .tracehd .mid {" not in media_block
    # Wide: .colhd is display:none so the shared header labels the columns.
    assert "body.ux-refresh .colhd {\n  display: none;" in css


def test_rest_row_reflects_its_populated_entitys_state_when_the_entity_is_not_ready(monkeypatch):
    """Review finding 3, round 2: the REST row's pill is the populated entity's
    readiness FROM the P6 model -- so a non-ready entity must show through. An
    entity with no persistence key is needs_action; its REST source row must
    show that state, not a blanket "Ready" or "Source"."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = get_session()
    session.app_name = "Rest Entity State Fixture"
    session.bounded_context = "rest-entity-state-fixture"
    session.app_archetype = "crud"
    # No is_id field and no persistence_id decision -> entity is needs_action.
    session.classified_entities = [
        ClassifiedEntity(name="Order", fields=[ClassifiedField(name="orderRef", type="string")]),
    ]
    session.selected_entity_names = ["Order"]
    session.upstream_interfaces = [
        UpstreamInterface(name="order-rest-api", type="rest-json", entity_name="Order",
                          operations=[OperationSample(name="getOrder")]),
    ]
    save_session(session)

    order_entity = readiness_view.item_by_display_name(
        get_session(), "Order", item_kinds=(readiness_view.ITEM_KIND_ENTITY,)
    )
    assert order_entity.state == readiness_view.STATE_NEEDS_ACTION, "fixture must make the entity non-ready"

    html = client.get("/review").text
    ref_start = html.index('data-trace-ref="order-rest-api"')
    ref = html[ref_start : ref_start + 600]
    assert 'data-trace-ref-via="entity"' in ref
    assert f'data-trace-ref-state="{order_entity.state}"' in ref  # pill == live entity state
    assert '<span class="pill attn"' in ref
    assert ">Needs action</span>" in ref
    # The entity owns the Fix affordance, not the source row.
    assert "jump" not in ref


def test_source_fallback_branch_is_retained_for_entity_less_refs():
    """Refs are grouped BY selected entity, so a rendered REST ref's
    entity_name always resolves to an itemized entity and takes the
    entity-sourced pill -- the "Source" fallback is now unreachable for
    rendered rows. It is kept as a defensive branch so an entity-less ref
    would still be labeled (never silently unlabeled) rather than render
    nothing; pin that the branch survives in the template."""
    template = TEMPLATE.read_text(encoding="utf-8")
    assert '<span class="pill source"' in template
    assert "{% elif ref.entity_readiness %}" in template
