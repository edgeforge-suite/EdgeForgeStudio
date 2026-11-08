"""PR-23 coverage for Step 7's summary-strip reconciliation (Part A) and
Step 8's CSS-only export artifact list restyle (Part B).

Part A -- Step 7. Flag-on Step 7 previously rendered TWO summary strips with
two different count vocabularies: the legacy `.review-summary-strip`
(completeness_service list-filter `|length` counts, ungated -- rendered in
both flag states) and PR-21's `.rsummary` (readiness_view state buckets,
gated on ux_refresh). PR-23 makes `.rsummary` THE flag-on summary and
suppresses the legacy strip flag-on, via a same-line-glued
`{% if not ux_refresh %}...{% endif %}` -- the technique this repo already
uses and tests (tests/test_step6_allowed_values_paste.py's byte-identity
test; step6_rules.html's `{% if not ux_refresh %}<div class="card ...">`
gate) -- so flag-off stays byte-identical. The two strips' numbers are
EXPECTED to differ: `.rsummary` counts readiness_view items over Steps 2-5
only, the legacy strip counted every completeness_service category
(Project/Kafka/Rules included). Every count assertion below cross-checks a
LIVE call to review._trace_lens_summary()/build_completeness_report(),
never a hand-typed expectation -- mirroring tests/test_step7_trace_lens.py's
own documented single-producer-discipline convention.

Part B -- Step 8. PR-23's visual change was CSS-only (build packet §B.1):
step8_export.html's server-rendered artifact rows (:108-125) are reproduced
by renderArtifactRows() in the same file's own script for the
post-/export/write re-render. Tests confirm the real
GET /export -> POST /export/write -> GET /export flow still renders
`.s8-artifact-row` in both flag states, plus that the new CSS is scoped
under `body.ux-refresh` with no `--fam-*` tokens (Scope Reality #3: export.py's
EXPORT_ARTIFACTS `kind` is Manifest/Provenance/Review/Assessment/Studio
Project -- an artifact-TYPE vocabulary unrelated to readiness_view's
contract families, and export.py never imports readiness_view -- so no
family mapping is invented here, only the shared zone/role vocabulary).
"""

from __future__ import annotations

import re
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
from app.services.completeness_service import build_completeness_report
from tests.session_helpers import get_session, reset_session, save_session
from tests.test_package_writer import _full_session

client = TestClient(app)
REPO_ROOT = Path(__file__).resolve().parent.parent
STEP7_TEMPLATE = REPO_ROOT / "app" / "templates" / "step7_review.html"
STEP8_TEMPLATE = REPO_ROOT / "app" / "templates" / "step8_export.html"
STUDIO_CSS = REPO_ROOT / "app" / "static" / "css" / "studio.css"


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mixed_readiness_session():
    """A session whose trace_lens_summary (readiness_view, Steps 2-5 only)
    and completeness report (every category) are both non-trivial AND
    guaranteed to disagree numerically:
      - Account entity has a persistence_id decision -> ready.
      - Ledger entity has none -> needs_action -> buckets into "warnings"
        (readiness_view._trace_lens_summary's own documented rule).
      - account-fixed-feed (file-fixed-width upstream, fully specified,
        same recipe verified ready by test_step7_trace_lens.py) -> ready.
      - account-xml-blocked (xml-xsd upstream, nothing set) -> blocks_export.
      - account-rest-api (rest-json, outside EDGE_CONTRACT_TYPES) is not
        itemized by readiness_view AT ALL (zero contribution to
        trace_lens_summary -- readiness_view does not model plain REST
        upstream sources), but completeness_service DOES evaluate it: its
        bare OperationSample has no sample path/content, so
        OperationSample.has_sample() is False and
        completeness_service.build_completeness_report adds a
        MANUAL_FOLLOW_UP item for it that trace_lens_summary never counts.
        That is the guaranteed-divergence lever -- confirmed empirically
        below (test_flag_on_summary_counts_come_from_trace_lens_summary_
        not_completeness_report), not assumed.
    """
    session = get_session()
    session.app_name = "Package Story Fixture"
    session.bounded_context = "package-story-fixture"
    session.app_archetype = "crud"
    session.classified_entities = [
        ClassifiedEntity(name="Account", fields=[ClassifiedField(name="accountId", type="string", is_id=True)]),
        ClassifiedEntity(name="Ledger", fields=[ClassifiedField(name="ledgerId", type="string")]),
    ]
    session.selected_entity_names = ["Account", "Ledger"]
    session.identity_role_decisions = [
        IdentityRoleDecision(entity="Account", field="accountId", role="persistence_id"),
    ]
    session.upstream_interfaces = [
        UpstreamInterface(
            name="account-rest-api", type="rest-json", entity_name="Account",
            operations=[OperationSample(name="getAccount")],
        ),
        UpstreamInterface(
            name="account-fixed-feed", type="file-fixed-width", entity_name="Account",
            spec="upstream/account-fixed.yaml",
            spec_content="format: fixed-width\nrecord_types:\n  data:\n    fields: []\n",
            field_mappings=[FieldMapping(source="accountId", target="Account.accountId")],
        ),
        UpstreamInterface(name="account-xml-blocked", type="xml-xsd", entity_name="Account"),
    ]
    save_session(session)
    return session


def _all_ready_session():
    """A session whose trace_lens_summary is non-trivially all-ready
    (ready > 0, warnings == 0, blocks_export == 0) -- the `uxr-zone-ready`
    branch, proven with real ready items rather than an empty/degenerate
    session (which would also read as "no attention items" but would not
    demonstrate the branch firing for a genuine populated board). Same
    proven-ready recipe as tests/test_step7_trace_lens.py's fixture
    (account-fixed-feed / account-fixed-out / account-staging / an Account
    entity with a persistence_id decision)."""
    session = get_session()
    session.app_name = "All Ready Fixture"
    session.bounded_context = "all-ready-fixture"
    session.app_archetype = "crud"
    session.classified_entities = [
        ClassifiedEntity(name="Account", fields=[ClassifiedField(name="accountId", type="string", is_id=True)]),
    ]
    session.selected_entity_names = ["Account"]
    session.identity_role_decisions = [
        IdentityRoleDecision(entity="Account", field="accountId", role="persistence_id"),
    ]
    session.upstream_interfaces = [
        UpstreamInterface(
            name="account-fixed-feed", type="file-fixed-width", entity_name="Account",
            spec="upstream/account-fixed.yaml",
            spec_content="format: fixed-width\nrecord_types:\n  data:\n    fields: []\n",
            field_mappings=[FieldMapping(source="accountId", target="Account.accountId")],
        ),
    ]
    session.downstream_interfaces = [
        DownstreamInterface(
            name="account-fixed-out", type="file-fixed-width", entity_name="Account",
            spec="downstream/account-fixed-out.yaml",
            spec_content="format: fixed-width\nrecord_types:\n  data:\n    fields: []\n",
            field_mappings=[FieldMapping(source="Account.accountId", target="accountId")],
        ),
    ]
    session.data_handoffs = [
        DataHandoff(
            name="account-staging", entity_name="Account", table_name="ACCOUNT_STG",
            ddl_content="CREATE TABLE account_stage (account_id VARCHAR(36), status VARCHAR(20));",
            field_mappings=[FieldMapping(source="Account.accountId", target="account_id")],
        ),
    ]
    save_session(session)
    return session


def _exportable_all_ready_session():
    """`_all_ready_session()` plus the one field that separates "readiness is
    clean" from "export is actually allowed".

    Worth stating plainly, because it is the whole point of the PR-23 review
    finding: the bare all-ready fixture is NOT exportable -- its readiness
    board is spotless, yet `build_completeness_report().manual()` returns
    `['target_profile is required']`, which is exactly the class of
    project-level blocker readiness_view never sees. Any test asserting the
    green branch must use this variant, or it asserts a green strip on a
    session Step 8 would refuse to export."""
    session = _all_ready_session()
    session.target_profile = "springboot-legacy-compatible"
    save_session(session)
    return session


def _trace_lens_summary_for(session) -> dict[str, int]:
    return review_route._trace_lens_summary(
        readiness_view.items_for_step(session, 2),
        readiness_view.items_for_step(session, 3),
        readiness_view.items_for_step(session, 4),
        readiness_view.items_for_step(session, 5),
    )


def _rsummary_strip(html: str) -> str:
    """Extract the `.rsummary` strip's rendered markup, from its opening
    <div (found via the stable data-trace-lens-summary hook) through its
    closing </div> -- same `</div>\\n\\n` boundary idiom already proven by
    tests/test_step7_trace_lens.py::
    test_readiness_summary_strip_buckets_match_live_readiness_states (the
    outer wrapper's close is followed by a blank line; the three inner
    `.rs` divs are not, so this does not stop early on a nested </div>)."""
    idx = html.index("data-trace-lens-summary")
    start = html.rindex("<div", 0, idx)
    end = html.index("</div>\n\n", idx)
    return html[start:end]


# ---------------------------------------------------------------------------
# Part A -- Step 7: exactly one summary strip
# ---------------------------------------------------------------------------


def test_flag_on_review_has_exactly_one_summary_strip(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _mixed_readiness_session()

    html = client.get("/review").text
    assert html.count('class="review-summary-strip"') == 0
    assert html.count("data-trace-lens-summary") == 1


def test_retired_flag_off_value_keeps_only_trace_lens_strip(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    _mixed_readiness_session()

    html = client.get("/review").text
    assert html.count('class="review-summary-strip"') == 0
    assert html.count("data-trace-lens-summary") == 1


def test_legacy_summary_strip_and_flag_gate_are_removed():
    template = STEP7_TEMPLATE.read_text(encoding="utf-8")

    assert 'class="review-summary-strip"' not in template
    assert "{% if not ux_refresh %}" not in template


def test_flag_on_summary_counts_come_from_trace_lens_summary_not_completeness_report(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = _mixed_readiness_session()

    expected = _trace_lens_summary_for(session)
    report = build_completeness_report(session)
    report_counts = (len(report.ready()), len(report.warnings()), len(report.manual()))
    trace_counts = (expected["ready"], expected["warnings"], expected["blocks_export"])

    # A fixture where the two coincide would prove nothing (build packet's
    # own warning) -- assert they genuinely differ before trusting the
    # render assertions below to distinguish the two sources.
    assert report_counts != trace_counts, (
        f"fixture does not discriminate: completeness report {report_counts} "
        f"== trace_lens_summary {trace_counts}"
    )
    # And every bucket in trace_counts is non-zero, so this exercises a real
    # mix rather than a single all-or-nothing bucket.
    assert all(n > 0 for n in trace_counts), trace_counts

    strip = _rsummary_strip(client.get("/review").text)
    assert f'<span class="n">{expected["ready"]}</span><span class="l">Ready</span>' in strip
    assert f'<span class="n">{expected["warnings"]}</span><span class="l">Warnings</span>' in strip
    assert f'<span class="n">{expected["blocks_export"]}</span><span class="l">Contract blockers</span>' in strip


def test_sole_summary_cannot_be_green_while_export_is_blocked(monkeypatch):
    """Regression for the PR-23 review finding (#261).

    `trace_lens_summary` only sees readiness_view items for Steps 2-5, but
    `/export` gates on `build_completeness_report().is_exportable()`.
    Project-level blockers never become readiness items, so an all-ready
    board with (say) `target_profile` missing left the SOLE flag-on summary
    rendering `uxr-zone-ready` with three zeroes while Step 8 refused to
    export -- a false green. The legacy strip used to mask this by showing
    the manual-follow-up count alongside; PR-23 removed it.

    Uses the all-ready fixture and breaks ONLY target_profile, so readiness
    genuinely stays clean and the export gate is the only thing objecting --
    which is precisely the condition the readiness counts cannot see."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = _all_ready_session()
    session.target_profile = ""
    save_session(session)

    # Fixture discriminates: readiness sees nothing wrong, export is blocked.
    readiness = _trace_lens_summary_for(session)
    assert readiness["warnings"] == 0 and readiness["blocks_export"] == 0, readiness
    assert readiness["ready"] > 0, readiness
    report = build_completeness_report(session)
    assert report.is_exportable() is False
    blocker_count = len(report.manual())
    assert blocker_count > 0

    html = client.get("/review").text
    strip = _rsummary_strip(html)

    # The strip must NOT claim all-clear.
    assert "uxr-zone-attn" in strip, "summary stayed green while export was blocked"
    assert "uxr-zone-ready" not in strip
    # And it must carry the authoritative gate, not just a tint.
    assert (
        f'<span class="n">{blocker_count}</span><span class="l">Export blockers</span>' in strip
    )
    assert "data-export-gate" in strip

    # Trace Lens deliberately itemizes represented Step 2/4/5 contracts and
    # handoffs only. Its empty unrelated-blocker result must say so rather
    # than contradicting the package-wide export gate above.
    unrelated_start = html.index('data-trace-lens-unrelated="Account"')
    unrelated_end = html.index("</div>\n    </div>", unrelated_start)
    unrelated = html[unrelated_start:unrelated_end]
    assert "Other represented contract/handoff blockers not connected to Account" in unrelated
    assert "None in this represented set." in unrelated
    assert "Package-wide export blockers are summarized above" in unrelated
    assert "Other export blockers not connected" not in unrelated
    assert "None right now." not in unrelated


def test_export_gate_cell_reads_clean_when_nothing_blocks_export(monkeypatch):
    """The other branch: a genuinely exportable session shows a zeroed,
    non-attention export-gate cell and a green strip -- so the new cell is a
    real signal rather than something permanently stuck on `attn`."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = _exportable_all_ready_session()

    report = build_completeness_report(session)
    assert report.is_exportable() is True, [item.message for item in report.manual()]

    strip = _rsummary_strip(client.get("/review").text)

    assert '<span class="n">0</span><span class="l">Export blockers</span>' in strip
    assert "uxr-zone-ready" in strip
    assert "uxr-zone-attn" not in strip


def test_export_gate_is_precomputed_in_the_route_not_counted_in_jinja():
    """The gate must come from review.py's _export_gate, keeping the
    template free of arithmetic (the same rule that removed the legacy
    strip's `report.manual()|length`)."""
    template = STEP7_TEMPLATE.read_text(encoding="utf-8")
    strip_src = template[
        template.index('<div class="rsummary') : template.index("data-export-gate") + 400
    ]
    assert "export_gate.blocker_count" in strip_src
    assert "export_gate.exportable" in strip_src
    assert "|length" not in strip_src
    assert "report.manual()" not in strip_src


def test_flag_on_summary_source_has_no_length_filter():
    """Static-source guard: the flag-on `.rsummary` block must never use a
    `|length` filter for its counts (that would silently reintroduce a
    completeness-report-shaped count into the readiness_view-sourced
    strip). All three numbers must come from the pre-computed
    trace_lens_summary dict, as plain ints."""
    template = STEP7_TEMPLATE.read_text(encoding="utf-8")
    start = template.index('<div class="rsummary')
    end = template.index("</div>", start) + len("</div>")
    block = template[start:end]

    assert "|length" not in block
    assert "trace_lens_summary.ready" in block
    assert "trace_lens_summary.warnings" in block
    assert "trace_lens_summary.blocks_export" in block


def test_flag_on_zone_class_is_attn_when_blocking_or_warning_items_exist(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = _mixed_readiness_session()
    expected = _trace_lens_summary_for(session)
    assert expected["blocks_export"] > 0 or expected["warnings"] > 0

    strip = _rsummary_strip(client.get("/review").text)
    open_tag = strip[: strip.index(">") + 1]
    assert "uxr-zone-attn" in open_tag
    assert "uxr-zone-ready" not in open_tag
    assert "uxr-stat-strip" in open_tag
    assert "data-trace-lens-summary" in open_tag


def test_flag_on_zone_class_is_ready_when_no_blocking_or_warning_items(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    session = _exportable_all_ready_session()
    expected = _trace_lens_summary_for(session)
    assert expected["ready"] > 0
    assert expected["warnings"] == 0
    assert expected["blocks_export"] == 0
    # Green now requires BOTH: clean readiness AND a clear export gate. The
    # bare _all_ready_session() is NOT exportable (target_profile is unset),
    # so asserting the ready branch on it would be asserting the very
    # false-green this PR's review found -- hence the exportable variant.
    assert build_completeness_report(session).is_exportable() is True

    strip = _rsummary_strip(client.get("/review").text)
    open_tag = strip[: strip.index(">") + 1]
    assert "uxr-zone-ready" in open_tag
    assert "uxr-zone-attn" not in open_tag
    assert "uxr-stat-strip" in open_tag


# ---------------------------------------------------------------------------
# Part B -- Step 8: CSS-only zone-token artifact list
# ---------------------------------------------------------------------------

def test_step8_dynamic_links_use_the_shared_html_encoder():
    source = STEP8_TEMPLATE.read_text(encoding="utf-8")

    assert "function escapeHtml(" not in source
    assert 'href="${escapeHtml(artifact.download_url)}"' in source
    assert 'href="${escapeHtml(data.app_url)}"' in source
    assert 'href="${escapeHtml(data.health_url)}"' in source


def _seed_written_export(tmp_path) -> None:
    session = _full_session()
    session.output_path = str(tmp_path)
    save_session(session)
    write_resp = client.post("/export/write")
    assert write_resp.status_code == 200, write_resp.text


def test_flag_on_export_still_renders_artifact_rows_after_real_write(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _seed_written_export(tmp_path)

    html = client.get("/export").text
    assert html.count("s8-artifact-row") >= 1
    assert 'class="s8-artifact-row workflow-surface-row is-provenance"' in html
    assert "s8-artifact-kind" in html
    assert "s8-artifact-summary" in html


def test_flag_off_export_still_renders_artifact_rows_after_real_write(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    _seed_written_export(tmp_path)

    html = client.get("/export").text
    assert html.count("s8-artifact-row") >= 1
    assert 'class="s8-artifact-row workflow-surface-row is-provenance"' in html


def test_step8_css_block_is_scoped_under_ux_refresh_and_has_no_fam_tokens():
    css = STUDIO_CSS.read_text(encoding="utf-8")
    # Anchor on the first real rule, not the banner comment's own prose --
    # the comment text a few lines above this explains IN PROSE that no
    # --fam-* tokens are used (Scope Reality #3), which would false-positive
    # a substring scan starting mid-comment. Slicing from the first actual
    # selector sidesteps that instead of trying to comment-strip a slice
    # that starts inside an unterminated comment.
    start = css.index("body.ux-refresh .s8-artifact-list {")
    block = css[start:]  # this PR's block runs to the end of the file

    code_only = re.sub(r"/\*.*?\*/", "", block, flags=re.DOTALL)
    assert "--fam-" not in code_only, "Step 8 must use zone tokens only, never family tokens (Scope Reality #3)"

    selector_lines = [
        line.strip()
        for line in block.splitlines()
        if line.strip().endswith("{") and "s8-artifact" in line
    ]
    assert selector_lines, "expected at least one .s8-artifact-* selector in the PR-23 CSS block"
    for line in selector_lines:
        assert line.startswith("body.ux-refresh "), f"unscoped selector leaks outside the flag: {line}"

    # The two contrast-bearing token swaps this PR makes are present (guards
    # against silently falling back to the old bespoke hexes).
    assert "var(--zone-derived)" in block
    assert "var(--muted-on-tint)" in block
    assert "var(--surface-muted)" in block
