"""PR-16 coverage for Step 7's completeness-drawer deep links.

CompletenessItem (app/services/completeness_service.py) carries only a
status/category/free-text message -- no structured reference. This PR joins
each message back to its readiness_view item via the verified "'{name}':"
message-prefix convention (see _COMPLETENESS_NAME_RE in app/routes/review.py)
to surface a deep_link into the corresponding focused editor. Every case here
reads the real CompletenessItem/ReadinessItem a fixture produces rather than
hand-constructing the expected message/link, per the build packet's
instruction.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.models.project import DataHandoff, DownstreamInterface, FieldMapping, UpstreamInterface
from app.routes.review import _completeness_deep_links
from app.services import readiness_view
from app.services.completeness_service import build_completeness_report
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _seed_downstream_blocker_session() -> str:
    """A genuine downstream-interface blocker (missing root element on an
    xml-xsd contract) reaching both build_completeness_report() and
    readiness_view.items_for_step() -- the fixture the build packet asks for."""
    session = get_session()
    session.app_name = "Deep Link Fixture"
    session.bounded_context = "deep-link-fixture"
    session.app_archetype = "crud"
    session.downstream_interfaces = [
        DownstreamInterface(name="account-status-soap-out", type="xml-xsd", xsd_path="contracts/account.xsd"),
    ]
    save_session(session)
    return "account-status-soap-out"


def test_item_by_display_name_resolves_the_real_downstream_blocker():
    name = _seed_downstream_blocker_session()
    session = get_session()

    resolved = readiness_view.item_by_display_name(session, name)

    assert resolved is not None
    assert resolved.item_id == f"dsi:{name}"
    assert resolved.blockers
    assert resolved.blockers[0].deep_link == f"/downstream?focus={name}#xsd"


def test_completeness_deep_links_joins_the_real_manual_follow_up_message():
    name = _seed_downstream_blocker_session()
    session = get_session()
    report = build_completeness_report(session)

    manual_messages = [item.message for item in report.manual() if name in item.message]
    assert manual_messages, "fixture did not produce the expected manual-follow-up item"
    message = manual_messages[0]
    assert message.startswith(f"'{name}':")  # the join convention this PR relies on

    links = _completeness_deep_links(session, report)

    assert links[("Downstream", message)] == f"/downstream?focus={name}#xsd"


def test_ready_row_for_a_downstream_interface_that_also_has_a_blocker_is_never_linked():
    """Regression for a re-review finding on PR #250: a single downstream
    interface can emit both a MANUAL_FOLLOW_UP row (missing root element) and
    a READY row ("field mappings defined") sharing the same name -- both
    resolve to the same ReadinessItem via item_by_display_name. Without an
    explicit READY skip, the READY row would inherit that item's blocker
    deep_link and a green row would point at someone else's problem section."""
    session = get_session()
    session.app_name = "Ready Skip Fixture"
    session.bounded_context = "ready-skip-fixture"
    session.app_archetype = "crud"
    session.downstream_interfaces = [
        DownstreamInterface(
            name="account-status-soap-out",
            type="xml-xsd",
            xsd_path="contracts/account.xsd",
            field_mappings=[FieldMapping(source="id", target="accountId")],
        ),
    ]
    save_session(session)
    report = build_completeness_report(session)

    name = "account-status-soap-out"
    matching = [item for item in report.items if item.category == "Downstream" and name in item.message]
    ready_messages = [item.message for item in matching if item.status == "READY"]
    blocker_messages = [item.message for item in matching if item.status == "MANUAL_FOLLOW_UP"]
    assert ready_messages, "fixture did not produce the expected READY row for this interface"
    assert blocker_messages, "fixture did not produce the expected blocker row for this interface"

    links = _completeness_deep_links(session, report)

    assert ("Downstream", blocker_messages[0]) in links
    assert ("Downstream", ready_messages[0]) not in links


def test_upstream_and_handoff_categories_now_have_shipped_focus_editors_and_render_linked(monkeypatch):
    """PR-21 (#36) flip: distinct from
    test_project_category_has_no_readiness_view_coverage_... below, where
    Project has NO readiness_view item to find at all. Upstream and
    DataHandoff items DO resolve via readiness_view (item_by_display_name can
    find them unfiltered). PR-16 (#250) originally withheld a link for them
    because, at that time, neither /upstream nor /handoffs consumed `?focus=`
    yet. That premise is now stale: PR-15 shipped /upstream's focus editor
    (`id="xsd"`/`id="wsdl"`/`id="layout"` anchors) and PR-14 shipped
    /handoffs' (`id="ddl"`/`id="mappings"`/`id="identity"` anchors), both
    ux_refresh-gated same as Downstream's -- so _completeness_deep_links must
    now resolve a link for both, same as it already does for Downstream."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = get_session()
    session.app_name = "Upstream Handoff Coverage Fixture"
    session.bounded_context = "upstream-handoff-coverage-fixture"
    session.app_archetype = "crud"
    session.upstream_interfaces = [UpstreamInterface(name="orders-in", type="xml-xsd", xsd_path="contracts/orders.xsd")]
    session.data_handoffs = [DataHandoff(name="orders-staging")]
    save_session(session)

    resolved_upstream = readiness_view.item_by_display_name(
        get_session(), "orders-in", item_kinds=(readiness_view.ITEM_KIND_UPSTREAM_CONTRACT,)
    )
    assert resolved_upstream is not None, "fixture did not produce a resolvable upstream readiness_view item"
    assert resolved_upstream.blockers

    resolved_handoff = readiness_view.item_by_display_name(
        get_session(), "orders-staging", item_kinds=(readiness_view.ITEM_KIND_HANDOFF,)
    )
    assert resolved_handoff is not None, "fixture did not produce a resolvable handoff readiness_view item"
    assert resolved_handoff.warnings

    report = build_completeness_report(get_session())
    upstream_messages = [item.message for item in report.items if item.category == "Upstream" and "orders-in" in item.message]
    handoff_messages = [item.message for item in report.items if item.category == "DataHandoff" and "orders-staging" in item.message]
    assert upstream_messages, "fixture did not produce the expected Upstream completeness message"
    assert handoff_messages, "fixture did not produce the expected DataHandoff completeness message"

    links = _completeness_deep_links(get_session(), report)
    expected_upstream_link = resolved_upstream.blockers[0].deep_link
    expected_handoff_link = resolved_handoff.warnings[0].deep_link
    assert links[("Upstream", upstream_messages[0])] == expected_upstream_link == "/upstream?focus=orders-in#xsd"
    assert links[("DataHandoff", handoff_messages[0])] == expected_handoff_link == "/handoffs?focus=orders-staging#ddl"

    html = client.get("/review").text
    assert f'href="{expected_upstream_link}"' in html
    assert f'href="{expected_handoff_link}"' in html
    # Jinja2 autoescapes the message's leading quote (`'orders-in':` ->
    # `&#39;orders-in&#39;:`), so search on the unescaped tail of the message
    # rather than the raw string from the report.
    upstream_marker = upstream_messages[0].split(": ", 1)[1]
    handoff_marker = handoff_messages[0].split(": ", 1)[1]
    assert upstream_marker in html
    assert handoff_marker in html
    assert response_has_link_after(html, upstream_marker, expected_upstream_link)
    assert response_has_link_after(html, handoff_marker, expected_handoff_link)


def test_review_page_renders_deep_link_for_the_real_blocker_when_flag_on(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _seed_downstream_blocker_session()
    session = get_session()
    report = build_completeness_report(session)
    links = _completeness_deep_links(session, report)
    expected_link = next(iter(links.values()))

    html = client.get("/review").text

    assert f'href="{expected_link}"' in html
    assert "data-completeness-deep-link" in html


def test_retired_flag_off_value_keeps_deep_link_markup(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    name = _seed_downstream_blocker_session()

    html = client.get("/review").text

    assert name in html  # the plain message itself still renders
    assert "data-completeness-deep-link" in html
    assert "?focus=" in html


def test_project_category_has_no_readiness_view_coverage_and_renders_unlinked(monkeypatch):
    """Project/Kafka/Rules categories aren't itemized by readiness_view yet
    (design doc §1.2): their completeness messages must render exactly as
    today -- plain "[category] message", no link, no crash -- in both flag
    states."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = get_session()
    session.app_name = ""
    session.bounded_context = ""
    session.app_archetype = "crud"
    save_session(session)
    report = build_completeness_report(session)
    assert any(item.category == "Project" for item in report.manual()), (
        "fixture did not produce the expected Project category item"
    )

    links = _completeness_deep_links(session, report)
    assert not any(category == "Project" for category, _ in links)

    html = client.get("/review").text
    assert "app_name is required" in html
    assert response_has_no_link_after(html, "app_name is required")


def response_has_no_link_after(html: str, marker: str) -> bool:
    start = html.index(marker)
    end = html.index("</div>", start)
    return "data-completeness-deep-link" not in html[start:end]


def response_has_link_after(html: str, marker: str, expected_href: str) -> bool:
    start = html.index(marker)
    end = html.index("</div>", start)
    window = html[start:end]
    return "data-completeness-deep-link" in window and f'href="{expected_href}"' in window


def test_flag_on_and_off_both_survive_a_report_with_no_resolvable_items_without_crash(monkeypatch):
    """A session with nothing but Project/Entities/Upstream aggregate-level
    advisories (no per-name interface/handoff items at all) must not crash
    the join in either flag state."""
    session = get_session()
    session.app_name = ""
    session.bounded_context = ""
    session.app_archetype = "crud"
    save_session(session)

    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    assert client.get("/review").status_code == 200

    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    assert client.get("/review").status_code == 200


def test_upstream_downstream_name_collision_resolves_each_message_to_its_own_direction():
    """Regression for a real join-ambiguity bug found while building PR-16:
    upstream and downstream interfaces are independent lists with no
    cross-list name-uniqueness guarantee -- item_by_display_name is called
    with an item_kinds filter scoped to the category's own kind specifically
    so an Upstream message can never resolve to the Downstream item of the
    same name, or vice versa
    (test_item_by_display_name_item_kinds_filter_excludes_other_kinds covers
    that resolution directly). Now that both categories have shipped focus
    editors (PR-21 #36), this also still guards the original join-ambiguity
    concern: the two completeness messages are byte-identical apart from
    category (same shared name + contract type), so the result dict must be
    keyed by (category, message), not message alone -- otherwise the
    Downstream entry would collide with the same-keyed Upstream one and the
    two directions would not resolve to their own distinct deep_link."""
    session = get_session()
    session.app_name = "Collision Fixture"
    session.bounded_context = "collision-fixture"
    session.app_archetype = "crud"
    session.upstream_interfaces = [UpstreamInterface(name="shared-name", type="file-csv")]
    session.downstream_interfaces = [DownstreamInterface(name="shared-name", type="file-csv")]
    save_session(session)
    report = build_completeness_report(session)

    links = _completeness_deep_links(session, report)

    upstream_links = {link for (category, _message), link in links.items() if category == "Upstream"}
    downstream_links = {link for (category, _message), link in links.items() if category == "Downstream"}
    assert upstream_links == {"/upstream?focus=shared-name#layout"}
    assert downstream_links == {"/downstream?focus=shared-name#layout"}


def test_item_by_display_name_item_kinds_filter_excludes_other_kinds():
    session = get_session()
    session.app_name = "Collision Fixture"
    session.bounded_context = "collision-fixture"
    session.app_archetype = "crud"
    session.upstream_interfaces = [UpstreamInterface(name="shared-name", type="file-csv")]
    session.downstream_interfaces = [DownstreamInterface(name="shared-name", type="file-csv")]
    save_session(session)

    upstream_only = readiness_view.item_by_display_name(
        session, "shared-name", item_kinds=(readiness_view.ITEM_KIND_UPSTREAM_CONTRACT,)
    )
    downstream_only = readiness_view.item_by_display_name(
        session, "shared-name", item_kinds=(readiness_view.ITEM_KIND_DOWNSTREAM_INTERFACE,)
    )
    unfiltered = readiness_view.item_by_display_name(session, "shared-name")
    missing_kind = readiness_view.item_by_display_name(
        session, "shared-name", item_kinds=(readiness_view.ITEM_KIND_HANDOFF,)
    )

    assert upstream_only.item_kind == readiness_view.ITEM_KIND_UPSTREAM_CONTRACT
    assert downstream_only.item_kind == readiness_view.ITEM_KIND_DOWNSTREAM_INTERFACE
    # Unfiltered keeps the packet's original (kind-agnostic) behavior: first
    # match wins, in step order -- upstream (step 2) before downstream (step 5).
    assert unfiltered.item_kind == readiness_view.ITEM_KIND_UPSTREAM_CONTRACT
    assert missing_kind is None


def test_item_by_display_name_returns_none_for_unknown_name():
    _seed_downstream_blocker_session()
    session = get_session()

    assert readiness_view.item_by_display_name(session, "no-such-interface") is None


def test_handoff_ddl_and_mapping_warnings_link_to_their_own_sections():
    """Review finding 1 (#258): a resolved item can carry refs pointing at
    DIFFERENT sections. A handoff missing both DDL and mappings emits
    "no DDL provided" (#ddl) and "no field mappings supplied" (#mappings) --
    _completeness_deep_links must match each completeness message to ITS OWN
    ref, not always refs[0], or the mapping warning wrongly links to #ddl."""
    session = get_session()
    session.app_name = "Handoff Link Fixture"
    session.bounded_context = "handoff-link-fixture"
    session.app_archetype = "crud"
    session.data_handoffs = [DataHandoff(name="orders-staging", type="staging-table")]
    save_session(session)
    report = build_completeness_report(session)

    ddl_msg = "'orders-staging': no DDL provided"
    map_msg = "'orders-staging': no field mappings supplied"
    handoff_msgs = [item.message for item in report.items if item.category == "DataHandoff"]
    assert ddl_msg in handoff_msgs and map_msg in handoff_msgs, "fixture did not produce both warnings"

    links = _completeness_deep_links(session, report)

    assert links[("DataHandoff", ddl_msg)] == "/handoffs?focus=orders-staging#ddl"
    assert links[("DataHandoff", map_msg)] == "/handoffs?focus=orders-staging#mappings"
