"""Tests for Step 7 KS provenance review."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.main import app
from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    DownstreamInterface,
    EntityRules,
    IdentityRoleDecision,
    KafkaRouterTargetTransform,
    KafkaRouterTransformRow,
    KafkaRouteTransform,
    KSEvidenceLink,
    KSReviewHistoryEntry,
    PassthroughTransform,
    RuleEntry,
    UpstreamInterface,
)
from app.routes.review import _build_identity_role_history
from app.services.identity_roles import identity_role_decision_entries
from tests.session_helpers import get_session, reset_session, save_session
from tests.test_package_writer import _full_session

client = TestClient(app)


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _seed_review_session() -> None:
    session = _full_session()
    session.capabilities.knowledge_assist_enabled = True
    save_session(session)


def _summary_count(text: str, label: str) -> int:
    match = re.search(rf">(\d+)</div>\s*<div[^>]*>{re.escape(label)}</div>", text)
    assert match is not None
    return int(match.group(1))


def _coverage_count(text: str, label: str) -> int:
    match = re.search(
        rf'<span class="review-kv-label">{re.escape(label)}</span>\s*<strong>(\d+)</strong>',
        text,
    )
    assert match is not None
    return int(match.group(1))


def test_step7_ks_provenance_empty_state():
    _seed_review_session()

    response = client.get("/review")

    assert response.status_code == 200
    assert "Evidence Trail Links / Exported Evidence" in response.text
    assert "Exported evidence links" in response.text
    assert "Evidence-backed counts are export evidence counts" in response.text
    assert "Decision History shows a mix of current/latest collapsed sections" in response.text
    assert "Generated Artifact Evidence Coverage" not in response.text
    assert "No Knowledge Assist decisions have been saved yet." in response.text
    assert "No Knowledge Assist field review history has been saved yet." not in response.text


def test_step7_project_snapshot_shows_edge_contract_counts():
    session = reset_session()
    session.app_name = "Edge Contract Review"
    session.bounded_context = "edge-contracts"
    session.app_archetype = "crud"
    session.upstream_interfaces = [
        UpstreamInterface(name="fixed-in", type="file-fixed-width", spec="upstream/fixed-layout.yaml"),
        UpstreamInterface(name="csv-in", type="file-csv", spec="upstream/csv-layout.yaml"),
        UpstreamInterface(name="xml-in", type="xml-xsd", xsd_path="contracts/in.xsd", root_element="acct:In"),
        UpstreamInterface(name="soap-in", type="soap-wsdl", wsdl_path="contracts/in.wsdl"),
    ]
    session.downstream_interfaces = [
        DownstreamInterface(name="fixed-out", type="file-fixed-width", spec="downstream/fixed-layout.yaml"),
        DownstreamInterface(name="csv-out", type="file-csv", spec="downstream/csv-layout.yaml"),
        DownstreamInterface(name="xml-out", type="xml-xsd", xsd_path="contracts/out.xsd", root_element="acct:Out"),
        DownstreamInterface(name="soap-out", type="soap-wsdl", wsdl_path="contracts/out.wsdl"),
    ]
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert "Upstream Contracts" in response.text
    assert "4 (2 file, 1 XML, 1 SOAP)" in response.text
    assert "Downstream Contracts" in response.text
    assert "Knowledge Assist" not in response.text


def test_step7_rejected_only_reviews_are_not_framed_as_exported_evidence():
    _seed_review_session()
    session = get_session()
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="rule-rejected",
            type="rule",
            status="rejected",
            manifest_path="rules.Account.status.allowed-values",
            reviewed_at="2026-05-11T12:00:00+00:00",
        )
    ]
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert _summary_count(response.text, "EVIDENCE-BACKED") == 0
    assert 'review-summary-label">REJECTED<' not in response.text
    assert _coverage_count(response.text, "Rejected (review only)") == 1
    assert "Rejected suggestions are review history only" in response.text


def test_step7_shows_manual_identity_role_decisions_without_ka_labels():
    session = _full_session()
    session.capabilities.knowledge_assist_enabled = False
    session.classified_entities = [
        ClassifiedEntity(
            name="Account",
            fields=[
                ClassifiedField(name="accountId", type="string"),
                ClassifiedField(name="accountNumber", type="string"),
            ],
        )
    ]
    session.selected_entity_names = ["Account"]
    session.identity_role_decisions = [
        IdentityRoleDecision(
            entity="Account",
            field="accountId",
            role="persistence_id",
            reviewed_at="2026-05-06T12:00:00+00:00",
        ),
        IdentityRoleDecision(
            entity="Account",
            field="accountNumber",
            role="business_key",
            reviewed_at="2026-05-06T12:30:00+00:00",
        ),
    ]
    save_session(session)
    entries = identity_role_decision_entries(session)

    response = client.get("/review")

    assert entries[0]["manifest_path"] == "entities.Account.fields.accountId"
    assert response.status_code == 200
    assert "Identity Role Decisions" in response.text
    assert "human-authored" in response.text
    assert "Exports to identity_overrides" in response.text
    assert "Affects generated persistence identity: Java @Id, DB primary key, and repository identity." in response.text
    assert "Exports to identity_roles as metadata_only; no generated app behavior yet" in response.text
    assert "Does not change Java, DDL, rules, APIs, or runtime behavior." in response.text
    assert "Not an Evidence Trail v1.1 entry." in response.text
    assert "2026-05-06" in response.text
    assert "2026-05-06T12:00:00+00:00" not in response.text
    assert "KA-ACCEPTED" not in response.text
    assert "Accepted from KA" not in response.text


def test_step7_shows_ka_identity_role_reviews_separate_from_evidence():
    session = _full_session()
    session.capabilities.knowledge_assist_enabled = True
    session.classified_entities = [
        ClassifiedEntity(
            name="Account",
            fields=[ClassifiedField(name="accountId", type="string")],
        )
    ]
    session.selected_entity_names = ["Account"]
    session.identity_role_decisions = [
        IdentityRoleDecision(
            entity="Account",
            field="accountId",
            role="persistence_id",
            provenance="knowledge-assist",
            reviewed_at="2026-05-07T12:00:00+00:00",
        )
    ]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="id-role-1",
            type="identity_role",
            status="accepted",
            manifest_path="entities.Account.fields.accountId",
            reviewed_at="2026-05-07T12:00:00+00:00",
            review_context={"entity": "Account", "field": "accountId", "role": "persistence_id"},
        ),
        KSReviewHistoryEntry(
            suggestion_id="id-role-2",
            type="identity_role",
            status="rejected",
            manifest_path="entities.Account.fields.accountId",
            reviewed_at="2026-05-07T13:00:00+00:00",
            review_context={"entity": "Account", "field": "accountId", "role": "business_key"},
        ),
    ]
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert "Identity Role Decisions" in response.text
    assert "Knowledge Assist" in response.text
    assert "accepted" in response.text
    assert "rejected" in response.text
    assert "Identity-role reviews are excluded from evidence-trail.json" in response.text


def test_step7_rejected_persistence_identity_review_does_not_show_active_engine_behavior():
    session = _full_session()
    session.capabilities.knowledge_assist_enabled = True
    session.classified_entities = [
        ClassifiedEntity(
            name="Account",
            fields=[ClassifiedField(name="accountId", type="string")],
        )
    ]
    session.selected_entity_names = ["Account"]
    session.identity_role_decisions = []
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="id-role-rejected",
            type="identity_role",
            status="rejected",
            manifest_path="entities.Account.fields.accountId",
            reviewed_at="2026-05-07T13:00:00+00:00",
            review_context={"entity": "Account", "field": "accountId", "role": "persistence_id"},
        )
    ]
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert "Review only" in response.text
    assert "Rejected review only; no generated app behavior." in response.text
    assert "Rejected review only; no generated API behavior." in response.text
    assert "Affects generated persistence identity: Java @Id" not in response.text
    assert "May affect generated API ID behavior" not in response.text


def test_step7_rejected_identity_review_does_not_relabel_active_accepted_decision():
    session = _full_session()
    session.capabilities.knowledge_assist_enabled = True
    session.classified_entities = [
        ClassifiedEntity(
            name="Account",
            fields=[ClassifiedField(name="accountId", type="string")],
        )
    ]
    session.selected_entity_names = ["Account"]
    session.identity_role_decisions = [
        IdentityRoleDecision(
            entity="Account",
            field="accountId",
            role="persistence_id",
            provenance="knowledge-assist",
            reviewed_at="2026-05-07T12:00:00+00:00",
        )
    ]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="id-role-accepted",
            type="identity_role",
            status="accepted",
            manifest_path="entities.Account.fields.accountId",
            reviewed_at="2026-05-07T12:00:00+00:00",
            review_context={"entity": "Account", "field": "accountId", "role": "persistence_id"},
        ),
        KSReviewHistoryEntry(
            suggestion_id="id-role-rejected",
            type="identity_role",
            status="rejected",
            manifest_path="entities.Account.fields.accountId",
            reviewed_at="2026-05-07T13:00:00+00:00",
            review_context={"entity": "Account", "field": "accountId", "role": "persistence_id"},
        ),
    ]
    save_session(session)

    history = _build_identity_role_history(session)

    assert history["entries"][0]["status"] == "accepted"
    assert history["entries"][0]["suggestion_id"] == "id-role-accepted"


def test_step7_human_authored_identity_does_not_inherit_old_ka_status():
    session = _full_session()
    session.capabilities.knowledge_assist_enabled = True
    session.classified_entities = [
        ClassifiedEntity(
            name="Account",
            fields=[ClassifiedField(name="accountId", type="string")],
        )
    ]
    session.selected_entity_names = ["Account"]
    session.identity_role_decisions = [
        IdentityRoleDecision(
            entity="Account",
            field="accountId",
            role="persistence_id",
            provenance="human-authored",
            reviewed_at="2026-05-07T14:00:00+00:00",
        )
    ]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="id-role-accepted",
            type="identity_role",
            status="accepted",
            manifest_path="entities.Account.fields.accountId",
            reviewed_at="2026-05-07T12:00:00+00:00",
            review_context={"entity": "Account", "field": "accountId", "role": "persistence_id"},
        )
    ]
    save_session(session)

    history = _build_identity_role_history(session)

    assert history["entries"][0]["provenance"] == "human-authored"
    assert history["entries"][0]["status"] == "active"
    assert history["entries"][0]["suggestion_id"] == ""


def test_step7_hides_dormant_ks_provenance_when_assist_off():
    session = _full_session()
    session.capabilities.knowledge_assist_enabled = False
    session.ks_active = False
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="s-1",
            type="field",
            status="accepted",
            manifest_path="entities.Account.fields.account_id",
            reviewed_at="2026-04-20T12:00:00+00:00",
        )
    ]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="entities.Account.fields.account_id",
            suggestion_id="s-1",
            provenance="ai-accepted",
        )
    ]
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert "Knowledge Assist Provenance" not in response.text
    assert "Knowledge Assist Field Review" not in response.text
    assert "Evidence Coverage" not in response.text
    assert "1 evidence-backed field decisions" not in response.text
    assert "entities.Account.fields.account_id" not in response.text
    assert "Knowledge Assist is off" not in response.text
    assert "Current Step 6 Rules" in response.text


def test_step7_ks_provenance_summary_and_classes():
    _seed_review_session()
    session = get_session()
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["s-1"]
    session.ks_workspace_state.suggestion_review_state.edited_ids = ["s-2"]
    session.ks_workspace_state.suggestion_review_state.rejected_ids = ["s-3"]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="s-1",
            type="field",
            status="accepted",
            manifest_path="entities.Account.fields.account_id",
            reviewed_at="2026-04-20T12:00:00+00:00",
        ),
        KSReviewHistoryEntry(
            suggestion_id="s-2",
            type="field",
            status="edited",
            manifest_path="entities.Account.fields.account_status",
            reviewed_at="2026-04-20T12:05:00+00:00",
            edited_payload={"field_name": "account_status"},
        ),
        KSReviewHistoryEntry(
            suggestion_id="s-3",
            type="field",
            status="rejected",
            manifest_path="entities.Account.fields.account_type",
            reviewed_at="2026-04-20T12:10:00+00:00",
        ),
    ]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="entities.Account.fields.account_id",
            suggestion_id="s-1",
            provenance="ai-accepted",
        ),
        KSEvidenceLink(
            manifest_path="entities.Account.fields.account_status",
            suggestion_id="s-2",
            provenance="ai-edited",
        ),
    ]
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert _summary_count(response.text, "ACCEPTED CANDIDATES") == 1
    assert _summary_count(response.text, "EDITED CANDIDATES") == 1
    assert _summary_count(response.text, "EVIDENCE-BACKED") == 2
    assert 'review-summary-label">REJECTED<' not in response.text
    assert "entities.Account.fields.account_id" in response.text
    assert "entities.Account.fields.account_status" in response.text
    assert "entities.Account.fields.account_type" in response.text
    assert "Accepted from KA" in response.text
    assert "Edited from KA" in response.text
    assert "ka-category-generated ka-taxonomy-change" in response.text
    assert "ka-category-evidence ka-taxonomy-evidence" in response.text
    assert "ka-category-review ka-taxonomy-attention" in response.text
    assert "KA-ACCEPTED" not in response.text
    assert "KA-EDITED" not in response.text
    assert "Review only, not exported" in response.text


def test_step7_field_provenance_summary_ignores_rule_review_buckets():
    _seed_review_session()
    session = get_session()
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["rule-s-1"]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="rule-s-1",
            type="rule",
            status="accepted",
            manifest_path="rules.Account.status.allowed-values",
            reviewed_at="2026-04-28T12:00:00+00:00",
        )
    ]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="rules.Account.status.allowed-values",
            suggestion_id="rule-s-1",
            provenance="ai-accepted",
        )
    ]
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert _summary_count(response.text, "ACCEPTED CANDIDATES") == 1
    assert _summary_count(response.text, "EDITED CANDIDATES") == 0
    assert _summary_count(response.text, "EVIDENCE-BACKED") == 0
    assert "No Knowledge Assist field review history has been saved yet." not in response.text
    assert "Knowledge Assist Rule Review" in response.text
    assert "rules.Account.status.allowed-values" in response.text


def test_step7_field_provenance_summary_ignores_validation_reviews():
    _seed_review_session()
    session = get_session()
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["v-1"]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="v-1",
            type="validation",
            status="accepted",
            manifest_path="entities.Account.fields.status.validations.not-null",
            reviewed_at="2026-04-28T12:00:00+00:00",
        )
    ]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="entities.Account.fields.status.validations.not-null",
            suggestion_id="v-1",
            provenance="ai-accepted",
        )
    ]
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert _summary_count(response.text, "ACCEPTED CANDIDATES") == 1
    assert _summary_count(response.text, "EVIDENCE-BACKED") == 0
    assert "No Knowledge Assist field review history has been saved yet." not in response.text
    assert "Generated Artifact Decisions" in response.text
    assert "Knowledge Assist Validation Review" in response.text
    assert "entities.Account.fields.status.validations.not-null" in response.text


def test_step7_mapping_review_history_is_visible_without_labeling_manual_mappings():
    _seed_review_session()
    session = get_session()
    session.passthrough_flow.upstream_operation_name = "routePayment"
    session.passthrough_flow.transforms = [
        PassthroughTransform(source="amount", target="settlementAmount"),
    ]
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["m-1"]
    session.ks_workspace_state.suggestion_review_state.rejected_ids = ["m-2"]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="m-1",
            type="mapping",
            status="accepted",
            manifest_path="passthrough.routePayment.transforms.amount.settlementAmount",
            reviewed_at="2026-04-28T12:00:00+00:00",
        ),
        KSReviewHistoryEntry(
            suggestion_id="m-2",
            type="mapping",
            status="rejected",
            manifest_path="passthrough.routePayment.transforms.currency.settlementCurrency",
            reviewed_at="2026-04-28T12:01:00+00:00",
        ),
    ]
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert _summary_count(response.text, "ACCEPTED CANDIDATES") == 1
    assert _summary_count(response.text, "EVIDENCE-BACKED") == 1
    assert "Knowledge Assist Mapping Review" in response.text
    assert "passthrough.routePayment.transforms.amount.settlementAmount" in response.text
    assert "passthrough.routePayment.transforms.currency.settlementCurrency" in response.text
    assert "Evidence Trail Links / Exported Evidence" in response.text
    assert "Only the Evidence-backed count represents links" in response.text


def test_step7_transform_review_history_is_visible_and_current_rows_count_as_linked():
    _seed_review_session()
    session = get_session()
    session.kafka_route_transforms = [
        KafkaRouteTransform(
            route_name="payment-router",
            router_target_transforms=[
                KafkaRouterTargetTransform(
                    target_id="ledger-core",
                    request_transform_rows=[
                        KafkaRouterTransformRow(source="payment.id", target="transactionId")
                    ],
                )
            ],
        )
    ]
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["t-1"]
    session.ks_workspace_state.suggestion_review_state.edited_ids = ["t-2"]
    session.ks_workspace_state.suggestion_review_state.rejected_ids = ["t-3"]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="t-1",
            type="transform",
            status="accepted",
            manifest_path=(
                "async_routes.payment-router.router_config.targets.ledger-core."
                "request_transform.payment.id.transactionId"
            ),
            reviewed_at="2026-04-29T14:00:00+00:00",
            review_context={
                "route_name": "payment-router",
                "target_id": "ledger-core",
                "direction": "request",
                "source": "payment.id",
                "target": "transactionId",
            },
        ),
        KSReviewHistoryEntry(
            suggestion_id="t-2",
            type="transform",
            status="edited",
            manifest_path=(
                "async_routes.payment-router.router_config.targets.ledger-core."
                "response_transform.status.status"
            ),
            reviewed_at="2026-04-29T14:05:00+00:00",
            review_context={
                "route_name": "payment-router",
                "target_id": "ledger-core",
                "direction": "response",
                "source": "status",
                "target": "status",
            },
        ),
        KSReviewHistoryEntry(
            suggestion_id="t-3",
            type="transform",
            status="rejected",
            manifest_path=(
                "async_routes.payment-router.router_config.targets.ledger-core."
                "request_transform.ignored.ignored"
            ),
            reviewed_at="2026-04-29T14:10:00+00:00",
        ),
    ]
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert "Knowledge Assist Transform Review" in response.text
    assert "async_routes.payment-router.router_config.targets.ledger-core.request_transform.payment.id.transactionId" in response.text
    assert "async_routes.payment-router.router_config.targets.ledger-core.response_transform.status.status" in response.text
    assert "Applied row is no longer present." in response.text
    assert _coverage_count(response.text, "Evidence-backed") == 1
    assert _coverage_count(response.text, "Without evidence") == 0
    assert _coverage_count(response.text, "Accepted") == 1
    assert _coverage_count(response.text, "Edited") == 1
    assert _coverage_count(response.text, "Rejected (review only)") == 1


def test_step7_conflict_review_history_is_visible_without_evidence_claim():
    _seed_review_session()
    session = get_session()
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["c-1"]
    session.ks_workspace_state.suggestion_review_state.edited_ids = ["c-2"]
    session.ks_workspace_state.suggestion_review_state.rejected_ids = ["c-3"]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="c-1",
            type="conflict_resolution",
            status="accepted",
            manifest_path="conflicts.c-1",
            reviewed_at="2026-04-29T12:00:00+00:00",
        ),
        KSReviewHistoryEntry(
            suggestion_id="c-2",
            type="conflict_resolution",
            status="edited",
            manifest_path="conflicts.c-2",
            reviewed_at="2026-04-29T12:05:00+00:00",
            edited_payload={
                "resolution_note": "Prefer the BRD because it is newer.",
                "preferred_document_id": "brd-1",
            },
        ),
        KSReviewHistoryEntry(
            suggestion_id="c-3",
            type="conflict_resolution",
            status="rejected",
            manifest_path="conflicts.c-3",
            reviewed_at="2026-04-29T12:10:00+00:00",
        ),
    ]
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert _summary_count(response.text, "ACCEPTED CANDIDATES") == 0
    assert _summary_count(response.text, "EVIDENCE-BACKED") == 0
    assert "Advisory Reviews" in response.text
    assert "Advisory Conflict Reviews" in response.text
    assert "conflicts.c-1" in response.text
    assert "conflicts.c-2" in response.text
    assert "conflicts.c-3" in response.text
    assert "ka-category-advisory ka-taxonomy-advisory" in response.text
    assert "ka-category-generated ka-taxonomy-change" not in response.text
    assert "resolution-note" in response.text
    assert "Prefer the BRD because it is newer." in response.text
    assert "Preferred source:" in response.text


def test_step7_portfolio_review_history_is_visible_without_evidence_claim():
    _seed_review_session()
    session = get_session()
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["p-1"]
    session.ks_workspace_state.suggestion_review_state.edited_ids = ["p-2"]
    session.ks_workspace_state.suggestion_review_state.rejected_ids = ["p-3"]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="p-1",
            type="portfolio_reuse",
            status="accepted",
            manifest_path="portfolio_reuse.p-1",
            reviewed_at="2026-04-29T13:00:00+00:00",
            review_context={
                "matched_project_id": "portfolio-project-1",
                "document_labels": ["Account Pattern BRD.pdf"],
            },
        ),
        KSReviewHistoryEntry(
            suggestion_id="p-2",
            type="portfolio_reuse",
            status="edited",
            manifest_path="portfolio_reuse.p-2",
            reviewed_at="2026-04-29T13:05:00+00:00",
            edited_payload={
                "reuse_note": "Useful pattern for Step 6 rule checks.",
                "target_step": "Step 6",
                "target_manifest_path": "rules.Account.status.allowed-values",
            },
            review_context={"matched_project_id": "portfolio-project-2"},
        ),
        KSReviewHistoryEntry(
            suggestion_id="p-3",
            type="portfolio_reuse",
            status="rejected",
            manifest_path="portfolio_reuse.p-3",
            reviewed_at="2026-04-29T13:10:00+00:00",
        ),
    ]
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert _summary_count(response.text, "ACCEPTED CANDIDATES") == 0
    assert _summary_count(response.text, "EVIDENCE-BACKED") == 0
    assert "Knowledge Assist Portfolio Review" in response.text
    assert "portfolio_reuse.p-1" in response.text
    assert "portfolio_reuse.p-2" in response.text
    assert "portfolio_reuse.p-3" in response.text
    assert "portfolio-project-1" in response.text
    assert "Account Pattern BRD.pdf" in response.text
    assert "reuse-note" in response.text
    assert "Useful pattern for Step 6 rule checks." in response.text
    assert "rules.Account.status.allowed-values" in response.text


def test_step7_mapping_coverage_ignores_deleted_transform_rows():
    _seed_review_session()
    session = get_session()
    session.passthrough_flow.upstream_operation_name = "routePayment"
    session.passthrough_flow.transforms = [
        PassthroughTransform(source="amount", target="settlementAmount"),
    ]
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["m-present", "m-deleted"]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="m-present",
            type="mapping",
            status="accepted",
            manifest_path="passthrough.routePayment.transforms.amount.settlementAmount",
            reviewed_at="2026-04-28T12:00:00+00:00",
        ),
        KSReviewHistoryEntry(
            suggestion_id="m-deleted",
            type="mapping",
            status="accepted",
            manifest_path="passthrough.routePayment.transforms.currency.settlementCurrency",
            reviewed_at="2026-04-28T12:01:00+00:00",
        ),
    ]
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert _coverage_count(response.text, "Evidence-backed") == 1
    assert _coverage_count(response.text, "Without evidence") == 0
    assert _coverage_count(response.text, "Accepted") == 2
    assert "passthrough.routePayment.transforms.currency.settlementCurrency" in response.text


def test_step7_mapping_coverage_ignores_colliding_dotted_review_context():
    _seed_review_session()
    session = get_session()
    session.passthrough_flow.upstream_operation_name = "routePayment"
    session.passthrough_flow.transforms = [
        PassthroughTransform(source="customer", target="id.accountCustomerId"),
    ]
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["m-old"]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="m-old",
            type="mapping",
            status="accepted",
            manifest_path="passthrough.routePayment.transforms.customer.id.accountCustomerId",
            reviewed_at="2026-04-28T12:00:00+00:00",
            review_context={
                "mapping_context": "passthrough",
                "route_name": "routePayment",
                "direction": "request",
                "source_field": "customer.id",
                "target_field": "accountCustomerId",
            },
        ),
    ]
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert _coverage_count(response.text, "Evidence-backed") == 0
    assert _coverage_count(response.text, "Without evidence") == 0
    assert _coverage_count(response.text, "Accepted") == 1
    assert "passthrough.routePayment.transforms.customer.id.accountCustomerId" in response.text


def test_step7_accepted_or_edited_without_matching_link_shows_no_evidence_indicator():
    _seed_review_session()
    session = get_session()
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["s-1"]
    session.ks_workspace_state.suggestion_review_state.edited_ids = ["s-2"]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="s-1",
            type="field",
            status="accepted",
            manifest_path="entities.Account.fields.account_id",
            reviewed_at="2026-04-20T12:00:00+00:00",
        ),
        KSReviewHistoryEntry(
            suggestion_id="s-2",
            type="field",
            status="edited",
            manifest_path="entities.Account.fields.account_status",
            reviewed_at="2026-04-20T12:05:00+00:00",
            edited_payload={"field_name": "account_status"},
        ),
    ]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="entities.Account.fields.account_id",
            suggestion_id="s-1",
            provenance="ai-accepted",
        )
    ]
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert "Evidence stale or missing" in response.text
    assert "1 current/latest accepted or edited field review entries have evidence stale or missing." in response.text


def test_step7_validation_history_keeps_latest_decision_for_same_manifest_path():
    _seed_review_session()
    session = get_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Customer",
            rules=[
                RuleEntry(
                    field="kycStatus",
                    type="not-null",
                    suggestion_id="v-old",
                    suggestion_type="validation",
                    applied_by="knowledge_assist",
                    generated_by_ka=True,
                    ka_review_status="accepted",
                )
            ],
        )
    ]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="v-old",
            type="validation",
            status="accepted",
            manifest_path="entities.Customer.fields.kycStatus.validations.not-null",
            reviewed_at="2026-05-03T12:00:00+00:00",
        ),
        KSReviewHistoryEntry(
            suggestion_id="v-new",
            type="validation",
            status="rejected",
            manifest_path="entities.Customer.fields.kycStatus.validations.not-null",
            reviewed_at="2026-05-03T12:05:00+00:00",
        ),
    ]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="entities.Customer.fields.kycStatus.validations.not-null",
            suggestion_id="v-old",
            provenance="ai-accepted",
        )
    ]
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert response.text.count("entities.Customer.fields.kycStatus.validations.not-null") == 1
    assert "Rejected KA suggestion" in response.text
    assert "Accepted from KA" not in response.text
    assert _coverage_count(response.text, "Evidence-backed") == 0


def test_step7_validation_history_counts_not_null_boolean_fingerprint():
    _seed_review_session()
    session = get_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Customer",
            rules=[
                RuleEntry(
                    field="kycStatus",
                    type="not-null",
                    suggestion_id="v-required",
                    suggestion_type="validation",
                    applied_by="knowledge_assist",
                    generated_by_ka=True,
                    ka_review_status="accepted",
                )
            ],
        )
    ]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="v-required",
            type="validation",
            status="accepted",
            manifest_path="entities.Customer.fields.kycStatus.validations.not-null",
            reviewed_at="2026-05-03T12:00:00+00:00",
            review_context={"constraint_fingerprint": "required=True"},
        )
    ]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="entities.Customer.fields.kycStatus.validations.not-null",
            suggestion_id="v-required",
            provenance="ai-accepted",
        )
    ]
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert _coverage_count(response.text, "Evidence-backed") == 1
    assert "entities.Customer.fields.kycStatus.validations.not-null" in response.text


def test_step7_coverage_ignores_stale_ka_rule_identity_after_user_edit():
    _seed_review_session()
    session = get_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(
                    field="statusCode",
                    type="pattern",
                    value="^[A-Z]+$",
                    suggestion_id="r-stale",
                    suggestion_type="rule",
                    applied_by="knowledge_assist",
                    generated_by_ka=True,
                    ka_review_status="accepted",
                )
            ],
        )
    ]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="r-stale",
            type="rule",
            status="accepted",
            manifest_path="rules.Account.status.allowed-values",
            reviewed_at="2026-05-03T12:00:00+00:00",
        )
    ]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="rules.Account.status.allowed-values",
            suggestion_id="r-stale",
            provenance="ai-accepted",
        )
    ]
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert _coverage_count(response.text, "Evidence-backed") == 0
    assert _coverage_count(response.text, "Without evidence") == 0


def test_step7_coverage_keeps_same_path_cross_entity_rule_reviews():
    _seed_review_session()
    session = get_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(
                    field="customerId",
                    type="cross-entity-field-check",
                    target_entity="Customer",
                    expected_value="ACTIVE",
                    suggestion_id="x-old",
                    suggestion_type="cross_entity_rule",
                    applied_by="knowledge_assist",
                    generated_by_ka=True,
                    ka_review_status="accepted",
                ),
                RuleEntry(
                    field="customerId",
                    type="cross-entity-field-check",
                    target_entity="Customer",
                    expected_value="VERIFIED",
                    suggestion_id="x-new",
                    suggestion_type="cross_entity_rule",
                    applied_by="knowledge_assist",
                    generated_by_ka=True,
                    ka_review_status="accepted",
                ),
            ],
        )
    ]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="x-old",
            type="cross_entity_rule",
            status="accepted",
            manifest_path="rules.Account.customerId.cross-entity-field-check",
            reviewed_at="2026-05-03T12:00:00+00:00",
        ),
        KSReviewHistoryEntry(
            suggestion_id="x-new",
            type="cross_entity_rule",
            status="accepted",
            manifest_path="rules.Account.customerId.cross-entity-field-check",
            reviewed_at="2026-05-03T12:05:00+00:00",
        ),
    ]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="rules.Account.customerId.cross-entity-field-check",
            suggestion_id="x-new",
            provenance="ai-accepted",
        )
    ]
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert _coverage_count(response.text, "Evidence-backed") == 1
    assert _coverage_count(response.text, "Without evidence") == 1
    assert _coverage_count(response.text, "Accepted") == 2


def test_step7_superseded_same_field_review_is_not_counted_as_no_evidence():
    _seed_review_session()
    session = get_session()
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["s-old"]
    session.ks_workspace_state.suggestion_review_state.edited_ids = ["s-new"]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="s-old",
            type="field",
            status="accepted",
            manifest_path="entities.Account.fields.account_id",
            reviewed_at="2026-04-20T12:00:00+00:00",
        ),
        KSReviewHistoryEntry(
            suggestion_id="s-new",
            type="field",
            status="edited",
            manifest_path="entities.Account.fields.account_id",
            reviewed_at="2026-04-20T12:05:00+00:00",
            edited_payload={"field_name": "account_id"},
        ),
    ]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="entities.Account.fields.account_id",
            suggestion_id="s-new",
            provenance="ai-edited",
        )
    ]
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert "Superseded by newer linked review" in response.text
    assert "0 current/latest accepted or edited field review entries have evidence stale or missing." not in response.text
