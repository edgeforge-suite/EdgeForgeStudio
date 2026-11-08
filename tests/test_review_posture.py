"""Tests for Step 7 review posture and drawer restructure."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    EntityRules,
    KSManifestRevision,
    KSReviewHistoryEntry,
    RuleEntry,
)
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


def test_step7_main_pane_renders_review_posture_and_drawer_tabs() -> None:
    _seed_review_session()

    response = client.get("/review")

    assert response.status_code == 200
    assert "Step 7: Review Checkpoint" in response.text
    assert "Mark reviewed" in response.text
    assert "Marked reviewed records your review checkpoint. Export is still allowed during Studio preview mode." in response.text
    assert "Proceed to Export" in response.text
    assert "Manifest Diff" in response.text
    assert "Decision History" in response.text
    assert "Completeness" in response.text
    assert "Evidence Trail Links / Exported Evidence" in response.text
    assert "Generated Rule Files" in response.text
    assert 'data-shell-drawer-default="expanded"' in response.text
    assert 'data-shell-rail-default="collapsed"' in response.text
    assert "Decision Context" in response.text
    assert "No step-specific context has moved into the rail in this slice." not in response.text
    assert "Evidence detail remains in the main workflow pages for now." not in response.text
    assert "Conflict guidance appears here only when this step has active advisory context." not in response.text


def test_step7_decision_history_uses_single_ka_empty_state() -> None:
    _seed_review_session()

    response = client.get("/review")

    assert response.status_code == 200
    assert "No Knowledge Assist decisions have been saved yet." in response.text
    assert "No Knowledge Assist field review history has been saved yet." not in response.text
    assert "No Knowledge Assist rule suggestion decisions have been saved yet." not in response.text
    assert "No Knowledge Assist mapping suggestion decisions have been saved yet." not in response.text
    assert "Current Step 6 Rules" in response.text


def test_step7_decision_history_renders_only_populated_ka_sections() -> None:
    _seed_review_session()
    session = get_session()
    session.ks_workspace_state.review_history.append(
        KSReviewHistoryEntry(
            suggestion_id="m-1",
            type="mapping",
            status="accepted",
            manifest_path="passthrough.routePayment.transforms.currency.settlementCurrency",
            reviewed_at="2026-05-02T12:00:00+00:00",
        )
    )
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert "No Knowledge Assist decisions have been saved yet." not in response.text
    assert "Knowledge Assist Mapping Review" in response.text
    assert "Knowledge Assist Rule Review" not in response.text
    assert "Knowledge Assist Transform Review" not in response.text
    assert "Current Step 6 Rules" in response.text


def test_step7_decision_history_filters_cover_entities_types_and_groups() -> None:
    _seed_review_session()
    session = get_session()
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="v-account",
            type="validation",
            status="accepted",
            manifest_path="entities.Account.fields.status.validations.allowed-values",
            reviewed_at="2026-05-03T12:00:00+00:00",
            review_context={
                "entity": "Account",
                "field": "status",
                "suggestion_semantics": {"category": "Already satisfied"},
            },
        ),
        KSReviewHistoryEntry(
            suggestion_id="r-customer",
            type="rule",
            status="edited",
            manifest_path="rules.Customer.customerId.pattern",
            reviewed_at="2026-05-03T12:05:00+00:00",
        ),
        KSReviewHistoryEntry(
            suggestion_id="c-transaction",
            type="conflict_resolution",
            status="accepted",
            manifest_path="conflicts.c-transaction",
            reviewed_at="2026-05-03T12:10:00+00:00",
            review_context={
                "entity": "Transaction",
                "field": "amount",
                "conflict_summary": "Transaction amount differs across source documents.",
            },
        ),
        KSReviewHistoryEntry(
            suggestion_id="m-account-customer",
            type="mapping",
            status="accepted",
            manifest_path="passthrough.routePayment.transforms.accountId.customerId",
            reviewed_at="2026-05-03T12:15:00+00:00",
            review_context={
                "source_entity": "Account",
                "target_entity": "Customer",
                "source_field": "accountId",
                "target_field": "customerId",
            },
        ),
        KSReviewHistoryEntry(
            suggestion_id="t-account-transaction",
            type="transform",
            status="edited",
            manifest_path=(
                "async_routes.payment-router.router_config.targets.ledger."
                "request_transform.accountId.transactionAccountId"
            ),
            reviewed_at="2026-05-03T12:20:00+00:00",
            edited_payload={
                "source_entity": "Account",
                "target_entity": "Transaction",
                "source": "accountId",
                "target": "transactionAccountId",
            },
        ),
    ]
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert 'data-decision-history-filter="all"' in response.text
    assert 'data-decision-history-filter="group:generated"' in response.text
    assert 'data-decision-history-filter="group:advisory"' in response.text
    assert 'data-decision-history-filter="semantic:noop"' in response.text
    assert 'data-decision-history-filter="entity:Account"' in response.text
    assert 'data-decision-history-filter="entity:Customer"' in response.text
    assert 'data-decision-history-filter="entity:Transaction"' in response.text
    assert 'data-decision-history-filter="type:validation"' in response.text
    assert 'data-decision-history-filter="type:rule"' in response.text
    assert 'data-decision-history-filter="type:mapping"' in response.text
    assert 'data-decision-history-filter="type:transform"' in response.text
    assert 'data-decision-history-filter="type:conflict"' in response.text
    assert 'data-decision-type="validation"' in response.text
    assert 'data-decision-type="rule"' in response.text
    assert 'data-decision-type="mapping"' in response.text
    assert 'data-decision-type="transform"' in response.text
    assert 'data-decision-type="conflict"' in response.text
    assert 'data-decision-entities="Account||Customer"' in response.text
    assert 'data-decision-entities="Account||Transaction"' in response.text
    assert "Generated Artifact Decisions" in response.text
    assert "Advisory Reviews" in response.text


def test_step7_current_rules_filter_and_provenance_badges_include_ka_metadata() -> None:
    _seed_review_session()
    session = get_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(
                    field="status",
                    type="allowed-values",
                    values=["ACTIVE"],
                    suggestion_id="v-status",
                    suggestion_type="validation",
                    applied_by="knowledge_assist",
                    applied_at="2026-05-03T12:00:00+00:00",
                    generated_by_ka=True,
                    ka_review_status="accepted",
                ),
                RuleEntry(field="accountNumber", type="max-length", value="12"),
            ],
        )
    ]
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert 'data-decision-history-filter="group:current_rules"' in response.text
    assert 'data-decision-history-filter="entity:Account"' in response.text
    assert 'data-decision-group="current_rules"' in response.text
    assert "KA-applied rule" in response.text
    assert "ka-category-generated ka-taxonomy-change" in response.text
    assert "Manual/imported/spec-derived rule" in response.text
    assert "ka-category-satisfied ka-taxonomy-satisfied" in response.text
    assert "Suggestion: <code>v-status</code>" in response.text


def test_step7_decision_history_has_scrollable_drawer_containers() -> None:
    css = Path("app/static/css/studio.css").read_text(encoding="utf-8")

    assert ".shell-bottom-drawer .shell-drawer-panel.active" in css
    assert "overflow-y: auto;" in css
    assert ".drawer-table-shell" in css


def test_ka_visual_taxonomy_css_defines_all_categories() -> None:
    css = Path("app/static/css/studio.css").read_text(encoding="utf-8")

    for token in [
        "--ka-change-bg",
        "--ka-satisfied-bg",
        "--ka-advisory-bg",
        "--ka-evidence-bg",
        "--ka-attention-bg",
        ".ka-taxonomy-change",
        ".ka-taxonomy-satisfied",
        ".ka-taxonomy-advisory",
        ".ka-taxonomy-evidence",
        ".ka-taxonomy-attention",
    ]:
        assert token in css


def test_review_posture_toggle_is_soft_and_session_local() -> None:
    _seed_review_session()

    response = client.post("/review/approve", json={"approved": True})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["review_approved"] is True
    assert get_session().review_approved is True

    response = client.post("/review/approve", json={"approved": False})

    assert response.status_code == 200
    assert response.json()["review_approved"] is False
    assert get_session().review_approved is False


def test_step7_manifest_drawer_falls_back_when_no_prior_baseline() -> None:
    _seed_review_session()

    response = client.get("/review")

    assert response.status_code == 200
    assert "No prior baseline available — showing current manifest." in response.text
    assert 'id="manifest-preview"' in response.text


def test_step7_manifest_drawer_handles_missing_prior_manifest_file() -> None:
    _seed_review_session()
    session = get_session()
    session.ks_workspace_state.manifest_revisions = [
        KSManifestRevision(
            revision_id="rev-missing",
            exported_at="2026-04-20T12:00:00+00:00",
            manifest_hash="sha256:abc",
            archetype=session.app_archetype,
            target_profile=session.target_profile,
            export_path="/tmp/edgeforge-studio-missing-review-baseline",
        )
    ]
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert "Prior manifest revision was recorded but could not be read from disk — showing current manifest." in response.text


def test_step7_advisory_summary_does_not_query_ks_when_assist_off(monkeypatch) -> None:
    _seed_review_session()
    session = get_session()
    session.capabilities.knowledge_assist_enabled = False
    session.ks_active = True
    session.project_id = "workspace-123"
    session.ks_project_id = "workspace-123"
    save_session(session)

    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when Knowledge Assist is off")

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/review")

    assert response.status_code == 200
    assert "Advisory issues" not in response.text
    assert "Current advisory conflict summary" not in response.text
    assert "Knowledge Assist is off" not in response.text
    assert "Dormant workspace history" not in response.text
    assert "Knowledge Assist Provenance" not in response.text
    assert "Knowledge Assist Field Review" not in response.text
    assert "Completeness" in response.text
    assert "Evidence Coverage" not in response.text
    assert response.text.count('class="tab-panel shell-drawer-panel review-drawer-panel"') == 3


def test_step7_advisory_summary_uses_assist_view_model_when_on(monkeypatch) -> None:
    _seed_review_session()
    session = get_session()
    session.capabilities.knowledge_assist_enabled = True
    session.ks_active = True
    session.project_id = "workspace-123"
    session.ks_project_id = "workspace-123"
    session.classified_entities = [
        ClassifiedEntity(
            name="Account",
            canonical_name="Account",
            classification="entity",
            fields=[ClassifiedField(name="creditLimit", type="decimal")],
        )
    ]
    session.selected_entity_names = ["Account"]
    save_session(session)

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str | None = None,
            field_name_pattern: str | None = None,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            if scope in {"conflict_resolution", "portfolio_reuse"}:
                return {"suggestions": [], "suggestion_count": 0}
            assert scope == "fields"
            return {
                "suggestions": [
                    {
                        "field_name": "CREDIT_LIMIT",
                        "conflict_hint": "Current field guidance disagrees with the spec.",
                    }
                ]
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/review")

    assert response.status_code == 200
    assert "Advisory issues" in response.text
    assert "Non-blocking CRUD advisory signal" in response.text
    assert "Review in Step 6" in response.text
