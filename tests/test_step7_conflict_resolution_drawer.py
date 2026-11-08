"""Tests for Step 7 read-only conflict-resolution suggestions."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from app.integrations.ks_integration import KSUnavailableError
from app.main import app
from app.models.project import ClassifiedEntity, ClassifiedField, KSReviewHistoryEntry
from tests.session_helpers import get_session, reset_session, save_session
from tests.test_package_writer import _full_session

client = TestClient(app)


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def test_step7_conflict_drawer_js_uses_compact_expandable_evidence_cards() -> None:
    script = Path("app/static/js/studio.js").read_text()

    assert "compactText" in script
    assert "Advisory source alignment review" in script
    assert "What differs?" in script
    assert "collapsedList(row.payload.snippets" in script
    assert "View evidence" in script
    assert "Show conflict evidence details" not in script


def _seed_review_session(*, assist_enabled: bool = True) -> None:
    session = _full_session()
    session.capabilities.knowledge_assist_enabled = assist_enabled
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
    save_session(session)


def test_step7_conflict_badge_off_does_not_call_ks(monkeypatch) -> None:
    _seed_review_session(assist_enabled=False)

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when Knowledge Assist is off")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/review")

    assert response.status_code == 200
    assert "scope=conflict_resolution" not in response.text
    assert "Knowledge Assist Provenance" not in response.text


def test_step7_conflict_drawer_off_returns_empty_without_ks(monkeypatch) -> None:
    _seed_review_session(assist_enabled=False)

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when Knowledge Assist is off")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/review/ks/drawer?scope=conflict_resolution")

    assert response.status_code == 200
    assert response.json()["empty"] is True
    assert get_session().ks_active is False


def test_step7_conflict_badge_not_rendered_for_zero_suggestions(monkeypatch) -> None:
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
            calls.append(f"{scope}:{field_name_pattern}")
            return {"scope": scope, "suggestions": [], "suggestion_count": 0}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/review")

    assert response.status_code == 200
    assert calls
    assert any(call.startswith("conflict_resolution:") for call in calls)
    assert any(call.startswith("portfolio_reuse:") for call in calls)
    assert "scope=conflict_resolution" not in response.text


def test_step7_conflict_fetch_failure_is_silent(monkeypatch) -> None:
    _seed_review_session()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise KSUnavailableError("mock unavailable")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/review")

    assert response.status_code == 200
    assert "scope=conflict_resolution" not in response.text
    assert "unavailable" not in response.text.lower()


def test_step7_conflict_badge_renders_when_suggestions_exist(monkeypatch) -> None:
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
            return {
                "scope": scope,
                "suggestions": [
                    {
                        "suggestion_id": "conflict-1",
                        "suggestion_type": "conflict_resolution",
                        "title": "Status conflict",
                        "summary": "Two documents disagree about status.",
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
    assert "1 conflict" in response.text
    assert 'data-suggestion-drawer-url="/review/ks/drawer?scope=conflict_resolution"' in response.text


def test_step7_conflict_drawer_returns_read_only_conflict_rows(monkeypatch) -> None:
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
                        "suggestion_id": "conflict-1",
                        "suggestion_type": "conflict_resolution",
                        "conflict_signal": "Status conflict",
                        "summary": "Status differs between BRD and DDL.",
                        "document_names": ["BRD.pdf"],
                        "document_ids": ["brd-1"],
                        "citations": [{"snippet": "BRD says ACTIVE only."}],
                    },
                    {
                        "suggestion_id": "conflict-1",
                        "suggestion_type": "conflict_resolution",
                        "title": "Duplicate conflict",
                    },
                ],
            }

        def get_suggestion_evidence_chain(
            self,
            project_id: str,
            scope: str,
            suggestion_id: str,
        ):
            assert scope == "conflict_resolution"
            return {
                "evidence_chunks": [
                    {
                        "citation": {
                            "document_id": "ddl-1",
                            "document_name": "DDL.sql",
                            "snippet": "DDL allows PENDING.",
                        }
                    }
                ]
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/review/ks/drawer?scope=conflict_resolution")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["review_url"] == "/review/ks/review"
    assert payload["scope"] == "conflict_resolution"
    rows = payload["scopes"][0]["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["suggestion_id"] == "conflict-1"
    assert row["title"] == "Status conflict"
    assert row["payload"]["conflict_query"] == "Account"
    assert row["payload"]["document_labels"] == ["BRD.pdf", "brd-1", "DDL.sql"]
    assert row["payload"]["document_ids"] == ["brd-1", "ddl-1"]
    assert {"id": "brd-1", "label": "BRD.pdf"} in row["payload"]["document_options"]
    assert {"id": "ddl-1", "label": "DDL.sql"} in row["payload"]["document_options"]
    assert row["payload"]["conflict_summary"] == "Status conflict"
    assert row["payload"]["difference_category"] == "source alignment difference"
    assert "BRD says ACTIVE only." in row["payload"]["snippets"]
    assert "DDL allows PENDING." in row["payload"]["snippets"]
    assert calls[0] == ("conflict_resolution", "Account")


def test_step7_conflict_drawer_merges_saved_review_status(monkeypatch) -> None:
    _seed_review_session()
    session = get_session()
    session.ks_workspace_state.review_history.append(
        KSReviewHistoryEntry(
            suggestion_id="conflict-1",
            type="conflict_resolution",
            status="accepted",
            manifest_path="conflicts.conflict-1",
            reviewed_at="2026-05-01T00:00:00Z",
        )
    )
    save_session(session)

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            field_name_pattern: str | None = None,
            min_source_count: int = 1,
            max_suggestions: int = 10,
        ):
            return {
                "scope": scope,
                "suggestions": [
                    {
                        "suggestion_id": "conflict-1",
                        "suggestion_type": "conflict_resolution",
                        "title": "Saved conflict",
                    }
                ],
            }

        def get_suggestion_evidence_chain(self, project_id: str, scope: str, suggestion_id: str):
            return {}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/review/ks/drawer?scope=conflict_resolution")

    assert response.status_code == 200
    row = response.json()["scopes"][0]["rows"][0]
    assert row["status"] == "accepted"
    assert row["payload"]["studio_review_status"] == "accepted"
    assert row["payload"]["studio_reviewed_at"] == "2026-05-01T00:00:00Z"

def test_step7_conflict_review_accepts_and_records_history(monkeypatch) -> None:
    _seed_review_session()
    submitted: list[list[dict]] = []

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            submitted.append(decisions)
            return {"success": True, "outcomes": [{"suggestion_id": "conflict-1", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/review/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "conflict-1",
                    "suggestion_type": "conflict_resolution",
                    "status": "accepted",
                    "payload": {"conflict_query": "Account.status", "document_ids": ["brd-1"]},
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["saved_count"] == 1
    assert submitted == [[{"suggestion_id": "conflict-1", "status": "accepted"}]]
    session = get_session()
    assert session.ks_workspace_state.suggestion_review_state.accepted_ids == ["conflict-1"]
    assert session.ks_workspace_state.evidence_links == []
    entry = session.ks_workspace_state.review_history[-1]
    assert entry.type == "conflict_resolution"
    assert entry.status == "accepted"
    assert entry.manifest_path == "conflicts.conflict-1"
    assert entry.review_context["conflict_query"] == "Account.status"
    assert entry.review_context["document_ids"] == ["brd-1"]


def test_step7_conflict_review_rejects_without_generated_mutation(monkeypatch) -> None:
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
                    "suggestion_id": "conflict-reject",
                    "suggestion_type": "conflict_resolution",
                    "status": "rejected",
                    "payload": {"conflict_query": "Account"},
                }
            ]
        },
    )

    assert response.status_code == 200
    session = get_session()
    assert session.entity_rules == before_rules
    assert session.ks_workspace_state.suggestion_review_state.rejected_ids == ["conflict-reject"]
    assert session.ks_workspace_state.review_history[-1].type == "conflict_resolution"


def test_step7_conflict_review_edited_requires_resolution_note(monkeypatch) -> None:
    _seed_review_session()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("invalid conflict review should not call KS")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/review/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "conflict-edit",
                    "suggestion_type": "conflict_resolution",
                    "status": "edited",
                    "payload": {"document_ids": ["brd-1"]},
                    "edited_payload": {"preferred_document_id": "brd-1"},
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "resolution_note" in " ".join(response.json()["errors"])
    assert get_session().ks_workspace_state.review_history == []


def test_step7_conflict_review_validates_preferred_document_id(monkeypatch) -> None:
    _seed_review_session()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("invalid conflict review should not call KS")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/review/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "conflict-edit",
                    "suggestion_type": "conflict_resolution",
                    "status": "edited",
                    "payload": {"document_ids": ["brd-1"]},
                    "edited_payload": {
                        "resolution_note": "Prefer DDL for the enum values.",
                        "preferred_document_id": "ddl-2",
                    },
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "preferred_document_id" in " ".join(response.json()["errors"])
    assert get_session().ks_workspace_state.review_history == []


def test_step7_conflict_review_records_edited_payload(monkeypatch) -> None:
    _seed_review_session()
    submitted: list[list[dict]] = []

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            submitted.append(decisions)
            return {"success": True}

        def suggest_manifest_candidates(self, *args, **kwargs):
            return {"suggestions": []}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/review/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "conflict-edit",
                    "suggestion_type": "conflict_resolution",
                    "status": "edited",
                    "payload": {
                        "conflict_query": "Account.status",
                        "conflict_summary": "Account.status differs between BRD and DDL.",
                        "entity": "Account",
                        "field": "status",
                        "difference_category": "naming difference",
                        "normalized_field_mapping": "ACCOUNT_STATUS -> accountStatus",
                        "document_options": [{"id": "brd-1", "label": "Business Rules.pdf"}],
                    },
                    "edited_payload": {
                        "resolution_note": "BRD is newer than the DDL extract.",
                        "preferred_document_id": "brd-1",
                        "rationale": "Updated policy memo supersedes schema notes.",
                    },
                }
            ]
        },
    )

    assert response.status_code == 200
    assert submitted == [
        [
            {
                "suggestion_id": "conflict-edit",
                "status": "edited",
                "edited_payload": {
                    "resolution_note": "BRD is newer than the DDL extract.",
                    "preferred_document_id": "brd-1",
                    "rationale": "Updated policy memo supersedes schema notes.",
                },
            }
        ]
    ]
    session = get_session()
    assert session.ks_workspace_state.suggestion_review_state.edited_ids == ["conflict-edit"]
    entry = session.ks_workspace_state.review_history[-1]
    assert entry.edited_payload["resolution_note"] == "BRD is newer than the DDL extract."
    assert entry.review_context["preferred_document_id"] == "brd-1"
    assert entry.review_context["preferred_document_label"] == "Business Rules.pdf"
    assert entry.review_context["conflict_summary"] == "Account.status differs between BRD and DDL."
    assert entry.review_context["normalized_field_mapping"] == "ACCOUNT_STATUS -> accountStatus"

    page = client.get("/review")
    assert page.status_code == 200
    assert "Advisory Reviews" in page.text
    assert "Account.status differs between BRD and DDL." in page.text
    assert "Business Rules.pdf" in page.text


def test_step7_conflict_review_ks_failure_does_not_update_local_state(monkeypatch) -> None:
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
                    "suggestion_id": "conflict-1",
                    "suggestion_type": "conflict_resolution",
                    "status": "accepted",
                    "payload": {"conflict_query": "Account"},
                }
            ]
        },
    )

    assert response.status_code == 503
    assert get_session().ks_workspace_state.review_history == []


def test_step7_conflict_review_off_does_not_call_ks(monkeypatch) -> None:
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
                    "suggestion_id": "conflict-1",
                    "suggestion_type": "conflict_resolution",
                    "status": "accepted",
                    "payload": {"conflict_query": "Account"},
                }
            ]
        },
    )

    assert response.status_code == 400
    assert get_session().ks_workspace_state.review_history == []
