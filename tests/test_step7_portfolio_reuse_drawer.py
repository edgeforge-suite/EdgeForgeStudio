"""Tests for Step 7 read-only portfolio reuse suggestions."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from app.integrations.ks_integration import KSUnavailableError
from app.main import app
from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    EntityRules,
    KafkaRouteModel,
    KafkaTopicPair,
    RuleEntry,
)
from tests.session_helpers import get_session, reset_session, save_session
from tests.test_package_writer import _full_session

client = TestClient(app)


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _seed_review_session(*, assist_enabled: bool = True) -> None:
    session = _full_session()
    session.capabilities.knowledge_assist_enabled = assist_enabled
    session.app_name = "Account Hub"
    session.classified_entities = [
        ClassifiedEntity(
            name="Account",
            canonical_name="Account",
            classification="entity",
            fields=[
                ClassifiedField(name="status", type="string"),
                ClassifiedField(name="accountNumber", type="string"),
            ],
        )
    ]
    session.selected_entity_names = ["Account"]
    session.entity_rules = [
        EntityRules(entity_name="Account", rules=[RuleEntry(field="status", type="allowed-values")])
    ]
    save_session(session)


def test_step7_portfolio_badge_off_does_not_call_ks(monkeypatch) -> None:
    _seed_review_session(assist_enabled=False)

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when Knowledge Assist is off")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/review")

    assert response.status_code == 200
    assert "scope=portfolio_reuse" not in response.text
    assert get_session().ks_active is False


def test_step7_portfolio_badge_not_rendered_for_zero_suggestions(monkeypatch) -> None:
    _seed_review_session()
    calls: list[str] = []

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            field_name_pattern: str | None = None,
            min_source_count: int = 1,
            max_suggestions: int = 10,
        ):
            if scope == "portfolio_reuse":
                calls.append(field_name_pattern or "")
            return {"scope": scope, "suggestions": [], "suggestion_count": 0}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/review")

    assert response.status_code == 200
    assert calls
    assert "scope=portfolio_reuse" not in response.text


def test_step7_portfolio_fetch_failure_is_silent(monkeypatch) -> None:
    _seed_review_session()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise KSUnavailableError("mock unavailable")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/review")

    assert response.status_code == 200
    assert "scope=portfolio_reuse" not in response.text
    assert "unavailable" not in response.text.lower()


def test_step7_portfolio_badge_renders_when_suggestions_exist(monkeypatch) -> None:
    _seed_review_session()

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            field_name_pattern: str | None = None,
            min_source_count: int = 1,
            max_suggestions: int = 10,
        ):
            if scope == "conflict_resolution":
                return {"scope": scope, "suggestions": [], "suggestion_count": 0}
            return {
                "scope": scope,
                "suggestions": [
                    {
                        "suggestion_id": "portfolio-1",
                        "suggestion_type": "portfolio_reuse",
                        "title": "Reusable account onboarding pattern",
                        "matched_project_id": "portfolio-project-1",
                    }
                ],
                "suggestion_count": 1,
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/review")

    assert response.status_code == 200
    assert "1 portfolio pattern" in response.text
    assert 'data-suggestion-drawer-url="/review/ks/drawer?scope=portfolio_reuse"' in response.text


def test_step7_portfolio_drawer_returns_actionable_rows(monkeypatch) -> None:
    _seed_review_session()
    calls: list[tuple[str, str | None]] = []

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            field_name_pattern: str | None = None,
            min_source_count: int = 1,
            max_suggestions: int = 10,
        ):
            calls.append((scope, field_name_pattern))
            return {
                "scope": scope,
                "suggestions": [
                    {
                        "suggestion_id": "portfolio-1",
                        "suggestion_type": "portfolio_reuse",
                        "title": "Reusable account onboarding pattern",
                        "summary": "A prior project used a similar account activation flow.",
                        "matched_project_id": "portfolio-project-1",
                        "document_name": "Account Pattern BRD.pdf",
                        "document_id": "doc-portfolio",
                        "snippet": "Activation requires status validation.",
                        "reuse_kind": "Portfolio pattern",
                    },
                    {
                        "suggestion_id": "portfolio-1",
                        "title": "Duplicate portfolio pattern",
                    },
                ],
            }

        def get_suggestion_evidence_chain(
            self,
            project_id: str,
            scope: str,
            suggestion_id: str,
        ):
            assert scope == "portfolio_reuse"
            return {
                "evidence_chunks": [
                    {
                        "citation": {
                            "document_id": "doc-extra",
                            "document_name": "Reuse Notes.md",
                            "snippet": "Prior indexed project reused the account onboarding contract.",
                        }
                    }
                ]
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/review/ks/drawer?scope=portfolio_reuse")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["review_url"] == "/review/ks/review"
    assert payload["scope"] == "portfolio_reuse"
    rows = payload["scopes"][0]["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["suggestion_id"] == "portfolio-1"
    assert row["title"] == "Reusable account onboarding pattern"
    assert row["payload"]["portfolio_query"] == "Account Hub"
    assert row["payload"]["matched_project_id"] == "portfolio-project-1"
    assert row["payload"]["document_labels"] == [
        "Account Pattern BRD.pdf",
        "doc-portfolio",
        "Reuse Notes.md",
    ]
    assert row["payload"]["document_ids"] == ["doc-portfolio", "doc-extra"]
    assert "Activation requires status validation." in row["payload"]["snippets"]
    assert any(
        "Prior indexed project reused" in snippet
        for snippet in row["payload"]["snippets"]
    )
    assert calls[0] == ("portfolio_reuse", "Account Hub")


def test_step7_portfolio_review_accepts_and_records_history(monkeypatch) -> None:
    _seed_review_session()
    submitted: list[list[dict]] = []

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            submitted.append(decisions)
            return {"success": True, "outcomes": [{"suggestion_id": "portfolio-1", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/review/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "portfolio-1",
                    "suggestion_type": "portfolio_reuse",
                    "status": "accepted",
                    "payload": {
                        "portfolio_query": "Account Hub",
                        "matched_project_id": "portfolio-project-1",
                        "document_labels": ["Account Pattern BRD.pdf"],
                        "document_ids": ["doc-portfolio"],
                    },
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["saved_count"] == 1
    assert submitted == [[{"suggestion_id": "portfolio-1", "status": "accepted"}]]
    session = get_session()
    assert session.ks_workspace_state.suggestion_review_state.accepted_ids == ["portfolio-1"]
    assert session.ks_workspace_state.evidence_links == []
    entry = session.ks_workspace_state.review_history[-1]
    assert entry.type == "portfolio_reuse"
    assert entry.status == "accepted"
    assert entry.manifest_path == "portfolio_reuse.portfolio-1"
    assert entry.review_context["portfolio_query"] == "Account Hub"
    assert entry.review_context["matched_project_id"] == "portfolio-project-1"
    assert entry.review_context["document_labels"] == ["Account Pattern BRD.pdf"]


def test_step7_portfolio_review_rejects_without_generated_mutation(monkeypatch) -> None:
    _seed_review_session()

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {"success": True}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    before_rules = list(get_session().entity_rules)
    response = client.post(
        "/review/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "portfolio-reject",
                    "suggestion_type": "portfolio_reuse",
                    "status": "rejected",
                    "payload": {"portfolio_query": "Account Hub"},
                }
            ]
        },
    )

    assert response.status_code == 200
    session = get_session()
    assert session.entity_rules == before_rules
    assert session.ks_workspace_state.suggestion_review_state.rejected_ids == ["portfolio-reject"]
    assert session.ks_workspace_state.review_history[-1].type == "portfolio_reuse"


def test_step7_portfolio_review_edited_requires_note_or_rationale(monkeypatch) -> None:
    _seed_review_session()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("invalid portfolio review should not call KS")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/review/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "portfolio-edit",
                    "suggestion_type": "portfolio_reuse",
                    "status": "edited",
                    "payload": {"portfolio_query": "Account Hub"},
                    "edited_payload": {"target_step": "Step 6"},
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "reuse_note or rationale" in " ".join(response.json()["errors"])
    assert get_session().ks_workspace_state.review_history == []


def test_step7_portfolio_review_records_edited_payload(monkeypatch) -> None:
    _seed_review_session()
    submitted: list[list[dict]] = []

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            submitted.append(decisions)
            return {"success": True}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    edited_payload = {
        "reuse_note": "Useful pattern for account activation checks.",
        "rationale": "Matches the current Account Hub flow.",
        "target_step": "Step 6",
        "target_manifest_path": "rules.Account.status.allowed-values",
    }
    response = client.post(
        "/review/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "portfolio-edit",
                    "suggestion_type": "portfolio_reuse",
                    "status": "edited",
                    "payload": {
                        "portfolio_query": "Account Hub",
                        "matched_project_id": "portfolio-project-1",
                    },
                    "edited_payload": edited_payload,
                }
            ]
        },
    )

    assert response.status_code == 200
    assert submitted == [
        [
            {
                "suggestion_id": "portfolio-edit",
                "status": "edited",
                "edited_payload": edited_payload,
            }
        ]
    ]
    session = get_session()
    assert session.ks_workspace_state.suggestion_review_state.edited_ids == ["portfolio-edit"]
    entry = session.ks_workspace_state.review_history[-1]
    assert entry.edited_payload == edited_payload
    assert entry.review_context["matched_project_id"] == "portfolio-project-1"


def test_step7_portfolio_review_ks_failure_does_not_update_local_state(monkeypatch) -> None:
    _seed_review_session()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise KSUnavailableError("mock unavailable")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/review/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "portfolio-1",
                    "suggestion_type": "portfolio_reuse",
                    "status": "accepted",
                    "payload": {"portfolio_query": "Account Hub"},
                }
            ]
        },
    )

    assert response.status_code == 503
    assert get_session().ks_workspace_state.review_history == []


def test_step7_portfolio_review_off_does_not_call_ks(monkeypatch) -> None:
    _seed_review_session(assist_enabled=False)

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when Knowledge Assist is off")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/review/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "portfolio-1",
                    "suggestion_type": "portfolio_reuse",
                    "status": "accepted",
                    "payload": {"portfolio_query": "Account Hub"},
                }
            ]
        },
    )

    assert response.status_code == 400
    assert get_session().ks_workspace_state.review_history == []


def test_step7_portfolio_drawer_js_has_review_actions_without_import_controls() -> None:
    script = Path("app/static/js/studio.js").read_text(encoding="utf-8")

    assert "Acknowledge" in script
    assert "Record note" in script
    assert "Dismiss" in script
    assert "Advisory only" in script
    assert "portfolio_reuse" in script
    assert "Import portfolio" not in script
    assert "Apply portfolio" not in script
    assert "Copy portfolio" not in script


def test_step7_portfolio_query_candidates_include_kafka_routes(monkeypatch) -> None:
    session = _full_session()
    session.app_archetype = "kafka-integration"
    session.classified_entities = []
    session.selected_entity_names = []
    session.capabilities.knowledge_assist_enabled = True
    session.app_name = "Payment Events"
    session.kafka_route_models = [
        KafkaRouteModel(
            route_name="payment-posted",
            pattern="fire-and-forget",
        )
    ]
    session.kafka_topic_pairs = [
        KafkaTopicPair(
            route_name="payment-posted",
            upstream_topic="payments.in",
            downstream_topic="ledger.out",
        )
    ]
    save_session(session)
    calls: list[str] = []

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            field_name_pattern: str | None = None,
            min_source_count: int = 1,
            max_suggestions: int = 10,
        ):
            if scope == "portfolio_reuse":
                calls.append(field_name_pattern or "")
            return {"scope": scope, "suggestions": [], "suggestion_count": 0}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/review")

    assert response.status_code == 200
    assert calls[:4] == ["Payment Events", "kafka-integration", "payment-posted", "payments.in"]
