"""Tests for Step 7 current Step 6 rule review visibility."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.main import app
from app.models.project import KSEvidenceLink, KSReviewHistoryEntry, RuleEntry
from tests.session_helpers import get_session, reset_session, save_session
from tests.test_package_writer import _full_session

client = TestClient(app)


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _summary_count(text: str, label: str) -> int:
    match = re.search(rf">(\d+)</div>\s*<div[^>]*>{re.escape(label)}</div>", text)
    assert match is not None
    return int(match.group(1))


def _seed_review_session_with_step6_rules() -> None:
    session = _full_session()
    session.capabilities.knowledge_assist_enabled = True
    session.entity_rules[0].rules = [
        RuleEntry(
            field="balance",
            type="field-comparison",
            operator=">=",
            compare_to_field="minimumBalance",
        ),
        RuleEntry(
            field="customerId",
            type="cross-entity-field-check",
            target_entity="Customer",
            target_field="status",
            operator="eq",
            expected_value="ACTIVE",
            error_message="Customer must be ACTIVE.",
        ),
        RuleEntry(
            field="customerId",
            type="cross-entity-field-compare",
            target_entity="Customer",
            target_field="approvedLimit",
            source_field="requestedAmount",
            operator="lte",
            error_message="Requested amount exceeds approved limit.",
        ),
        RuleEntry(
            field="customerId",
            type="cross-entity-field-in",
            target_entity="Customer",
            target_field="status",
            values=["ACTIVE", "REVIEW"],
            error_message="Customer status must be eligible.",
        ),
    ]
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["s-1"]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="s-1",
            type="field",
            status="accepted",
            manifest_path="entities.Account.fields.account_id",
            reviewed_at="2026-04-22T12:00:00+00:00",
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


def test_step7_decision_history_surfaces_current_step6_rules_without_evidence_gap() -> None:
    _seed_review_session_with_step6_rules()

    response = client.get("/review")

    assert response.status_code == 200
    assert "Current Step 6 Rules" in response.text
    assert "Current Step 6 rules are surfaced here as the current Studio rule set for review before export." in response.text
    assert "untouched spec-derived rules and manually added rules" in response.text
    assert "rules.Account.balance.field-comparison" in response.text
    assert "rules.Account.customerId.cross-entity-field-check" in response.text
    assert "rules.Account.customerId.cross-entity-field-compare" in response.text
    assert "rules.Account.customerId.cross-entity-field-in" in response.text
    assert "current-rule-set" in response.text
    assert "Current Step 6 rule set" in response.text
    assert "human-authored" not in response.text
    assert "Manual authoring" not in response.text
    assert "No evidence linked" not in response.text
    assert _summary_count(response.text, "ACCEPTED CANDIDATES") == 1
    assert _summary_count(response.text, "EVIDENCE-BACKED") == 1


def test_step7_manifest_drawer_includes_generated_rule_yaml_preview() -> None:
    _seed_review_session_with_step6_rules()

    response = client.get("/review")

    assert response.status_code == 200
    assert "Generated Rule Files" in response.text
    assert "rules/account-business-rules.yaml" in response.text
    assert "type: field-comparison" in response.text
    assert "type: cross-entity-field-check" in response.text
    assert "type: cross-entity-field-compare" in response.text
    assert "type: cross-entity-field-in" in response.text
    assert "expected-value: ACTIVE" in response.text
    assert "allowed-values:" in response.text


def test_step7_separates_ka_rule_review_from_current_rule_set() -> None:
    _seed_review_session_with_step6_rules()
    session = get_session()
    session.ks_workspace_state.suggestion_review_state.accepted_ids.append("rule-s-1")
    session.ks_workspace_state.review_history.append(
        KSReviewHistoryEntry(
            suggestion_id="rule-s-1",
            type="rule",
            status="accepted",
            manifest_path="rules.Account.rule-s-1",
            reviewed_at="2026-04-28T12:00:00+00:00",
        )
    )
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert "Knowledge Assist Rule Review" in response.text
    assert "rules.Account.rule-s-1" in response.text
    assert "Accepted from KA" in response.text
    assert "KA-ACCEPTED" not in response.text
    assert "Current Step 6 Rules" in response.text
    assert "current-rule-set" in response.text
    assert "human-authored" not in response.text
