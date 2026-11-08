"""Tests for CRUD Step 3 KS field suggestion review."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.integrations.ks_integration import KSCallError, KSUnavailableError
from app.main import app
from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    ClassifiedOperation,
    EntityRules,
    KSEvidenceLink,
    KSReviewHistoryEntry,
    RuleEntry,
)
from app.routes.entities import assist_service
from app.services.manifest_generator import build_manifest_dict
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)


def _step3_js() -> str:
    return Path("app/static/js/step3_entities.js").read_text(encoding="utf-8")


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _seed_crud_step3_session(
    *,
    app_archetype: str = "crud",
    selected_entity_names: list[str] | None = None,
    classified_entities: list[ClassifiedEntity] | None = None,
    knowledge_assist_enabled: bool = True,
    active_workspace: bool = False,
) -> None:
    session = get_session()
    session.app_name = "TestApp"
    session.bounded_context = "accounts"
    session.target_profile = "springboot-legacy-compatible"
    session.app_archetype = app_archetype
    session.capabilities.knowledge_assist_enabled = knowledge_assist_enabled
    session.classified_entities = classified_entities or [
        ClassifiedEntity(
            name="AccountResponse",
            canonical_name="Account",
            classification="entity",
        )
    ]
    session.classified_operations = [
        ClassifiedOperation(
            name="createAccount",
            method="POST",
            path="/accounts",
            resource="accounts",
            entity_candidates=["Account"],
        )
    ]
    session.selected_entity_names = (
        selected_entity_names if selected_entity_names is not None else ["AccountResponse"]
    )
    if active_workspace:
        session.project_id = "studio-ks-step3"
        session.ks_project_id = "studio-ks-step3"
        session.ks_active = True
    save_session(session)


def _seed_validation_step3_session(*, knowledge_assist_enabled: bool = True) -> None:
    _seed_crud_step3_session(
        knowledge_assist_enabled=knowledge_assist_enabled,
        classified_entities=[
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
                fields=[
                    ClassifiedField(name="status", type="string"),
                    ClassifiedField(name="accountNumber", type="string"),
                    ClassifiedField(name="routingNumber", type="string"),
                    ClassifiedField(name="balance", type="decimal"),
                ],
            )
        ],
    )


def _seed_multi_entity_step3_session(count: int = 5) -> list[str]:
    entities = [
        ClassifiedEntity(
            name=f"Entity{index}Response",
            canonical_name=f"Entity{index}",
            classification="entity",
            fields=[
                ClassifiedField(name="id", type="string"),
                ClassifiedField(name="status", type="string"),
            ],
        )
        for index in range(1, count + 1)
    ]
    _seed_crud_step3_session(
        active_workspace=True,
        selected_entity_names=[entity.name for entity in entities],
        classified_entities=entities,
    )
    return [entity.display_name() for entity in entities]


def test_step3_renders_ks_surface_only_for_saved_crud_selection():
    _seed_crud_step3_session(active_workspace=True)

    response = client.get("/entities")

    assert response.status_code == 200
    assert "Knowledge Assist Summary" in response.text
    assert "Open Knowledge Assist Review" in response.text
    assert "function renderExpandableEvidenceText" in _step3_js()
    assert "Show full conflict detail" in _step3_js()
    assert 'data-shell-rail-default="expanded"' in response.text
    assert 'id="rail-ka-summary-panel"' in response.text
    assert 'id="ks-evidence-viewer"' not in response.text

    reset_session()
    _seed_crud_step3_session()

    response = client.get("/entities")

    assert response.status_code == 200
    assert "Knowledge Assist Summary" not in response.text
    assert "Fetching suggestions" not in response.text
    assert "Open Knowledge Assist workspace" not in response.text
    assert "ka-suggestion-drawer" not in response.text

    reset_session()
    _seed_crud_step3_session(app_archetype="passthrough-router")

    response = client.get("/entities")

    assert response.status_code == 200
    assert "Knowledge Assist Summary" not in response.text

    reset_session()
    _seed_crud_step3_session(selected_entity_names=[])

    response = client.get("/entities")

    assert response.status_code == 200
    assert "Knowledge Assist Summary" not in response.text
    assert "Step 3 Context" in response.text
    assert "Fetching suggestions" not in response.text

    reset_session()
    _seed_crud_step3_session(knowledge_assist_enabled=False)

    response = client.get("/entities")

    assert response.status_code == 200
    assert "Knowledge Assist Summary" not in response.text
    assert "Open Knowledge Workspace" not in response.text
    assert "Fetching suggestions" not in response.text
    assert ">Suggestions</h4>" not in response.text
    assert 'data-shell-rail-default="collapsed"' in response.text


def test_step3_ks_suggestions_returns_empty_state_when_no_field_catalog(monkeypatch):
    _seed_crud_step3_session()

    class FakeClient:
        def read_field_catalog(self, project_id: str, source=None, entity=None):
            assert entity == "Account"
            return {"fields": [], "warnings": []}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities/ks/suggestions?entity=Account")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["empty"] is True
    assert payload["knowledge_url"] == "/knowledge"
    assert "field catalog" in payload["empty_reason"].lower()


def test_step3_full_review_batch_uses_one_ks_context_for_one_or_many_entities(monkeypatch):
    entities = _seed_multi_entity_step3_session(count=5)
    context_entries = 0

    class FakeClient:
        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {"fields": [{"name": "status"}], "warnings": []}

        def suggest_manifest_candidates(self, project_id: str, scope: str, entity: str, **kwargs):
            return {"suggestions": [], "suggestion_count": 0, "warnings": []}

    @contextmanager
    def fake_ks_client(**kwargs):
        nonlocal context_entries
        context_entries += 1
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get(f"/entities/ks/full-review?entities={entities[0]}")
    assert response.status_code == 200
    assert response.json()["selected_entities"] == [entities[0]]
    assert context_entries == 1

    context_entries = 0
    response = client.get("/entities/ks/full-review")
    assert response.status_code == 200
    payload = response.json()
    assert payload["selected_entities"] == entities
    assert [block["entity"] for block in payload["entities"]] == entities
    assert context_entries == 1


def test_step3_full_review_batch_matches_single_endpoint_payloads(monkeypatch):
    _seed_crud_step3_session(
        active_workspace=True,
        classified_entities=[
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
                fields=[
                    ClassifiedField(name="accountId", type="string"),
                    ClassifiedField(name="status", type="string"),
                ],
            )
        ],
    )

    class FakeClient:
        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {"fields": [{"name": "openedDate"}], "warnings": []}

        def suggest_manifest_candidates(self, project_id: str, scope: str, entity: str, **kwargs):
            if scope == "fields":
                return {
                    "suggestions": [
                        {
                            "suggestion_id": "field-1",
                            "field_name": "openedDate",
                            "suggested_type": "date",
                            "suggested_nullable": False,
                            "suggested_description": "Date account opened.",
                            "manifest_path": "entities.Account.fields.openedDate",
                        }
                    ],
                    "suggestion_count": 1,
                    "warnings": ["field warning"],
                }
            if scope == "validations":
                return {
                    "suggestions": [
                        {
                            "suggestion_id": "validation-1",
                            "field_name": "status",
                            "summary": "Require status.",
                            "manifest_path": "entities.Account.fields.status.validations.not-null",
                            "payload": {"field": "status", "validation_type": "not_null"},
                        }
                    ],
                    "warnings": ["validation warning"],
                }
            if scope == "identity_role":
                return {
                    "suggestions": [
                        {
                            "suggestion_id": "identity-1",
                            "entity": "Account",
                            "field": "accountId",
                            "suggested_role": "persistence_id",
                            "manifest_path": "entities.Account.fields.accountId.identity_role",
                        }
                    ],
                    "warnings": ["identity warning"],
                }
            return {"suggestions": []}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    single_field = client.get("/entities/ks/suggestions?entity=Account").json()
    single_validations = client.get("/entities/ks/drawer?scope=validations&entity=Account").json()
    single_identity = client.get("/entities/ks/drawer?scope=identity_role&entity=Account").json()
    batch = client.get("/entities/ks/full-review").json()

    assert batch["ok"] is True
    assert batch["identity_review_entities"] == ["Account"]
    block = batch["entities"][0]
    assert block["entity"] == "Account"
    assert block["field"] == single_field
    assert block["validations"] == single_validations
    assert block["identity_role"] == single_identity
    assert batch["warnings"] == []


def test_step3_full_review_batch_preserves_field_catalog_gate(monkeypatch):
    _seed_crud_step3_session(active_workspace=True)
    suggest_calls: list[str] = []

    class FakeClient:
        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {"fields": [], "warnings": ["catalog is empty"]}

        def suggest_manifest_candidates(self, project_id: str, scope: str, entity: str, **kwargs):
            suggest_calls.append(scope)
            return {"suggestions": [], "suggestion_count": 0, "warnings": []}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    single_field = client.get("/entities/ks/suggestions?entity=Account").json()
    batch = client.get("/entities/ks/full-review").json()

    assert batch["entities"][0]["field"] == single_field
    assert "field catalog" in batch["entities"][0]["field"]["empty_reason"].lower()
    assert "catalog is empty" in batch["entities"][0]["field"]["warnings"]
    assert suggest_calls == ["validations"]


def test_step3_full_review_batch_isolates_per_scope_tool_errors(monkeypatch):
    _seed_crud_step3_session(
        active_workspace=True,
        selected_entity_names=["AccountResponse", "CustomerResponse"],
        classified_entities=[
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
                fields=[ClassifiedField(name="status", type="string")],
            ),
            ClassifiedEntity(
                name="CustomerResponse",
                canonical_name="Customer",
                classification="entity",
                fields=[ClassifiedField(name="status", type="string")],
            ),
        ],
    )

    class FakeClient:
        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {"fields": [{"name": "status"}], "warnings": []}

        def suggest_manifest_candidates(self, project_id: str, scope: str, entity: str, **kwargs):
            if scope == "validations" and entity == "Account":
                raise KSCallError("suggest_manifest_candidates", "validation boom")
            if scope == "validations" and entity == "Customer":
                return {
                    "suggestions": [
                        {
                            "suggestion_id": "customer-validation",
                            "field_name": "status",
                            "payload": {"field": "status", "validation_type": "not_null"},
                        }
                    ]
                }
            return {"suggestions": [], "suggestion_count": 0, "warnings": []}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities/ks/full-review")

    assert response.status_code == 200
    payload = response.json()
    assert payload["warnings"] == []
    by_entity = {block["entity"]: block for block in payload["entities"]}
    assert by_entity["Account"]["validations"]["empty"] is True
    assert any("validation boom" in warning for warning in by_entity["Account"]["validations"]["warnings"])
    customer_rows = by_entity["Customer"]["validations"]["scopes"][0]["rows"]
    assert customer_rows[0]["suggestion_id"] == "customer-validation"


def test_step3_identity_role_suggestion_badge_calls_ks_only_when_ka_on(monkeypatch):
    _seed_crud_step3_session(
        active_workspace=True,
        classified_entities=[
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
                fields=[ClassifiedField(name="accountId", type="string")],
            )
        ],
    )
    calls: list[str] = []

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            calls.append(scope)
            if scope == "identity_role":
                return {
                    "suggestions": [
                        {
                            "suggestion_id": "id-role-1",
                            "entity": "Account",
                            "field": "accountId",
                            "suggested_role": "persistence_id",
                        }
                    ],
                    "suggestion_count": 1,
                }
            return {"suggestions": [], "suggestion_count": 0}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities")

    assert response.status_code == 200
    assert "Account · 1 identity role suggestion" not in response.text
    assert "Identity roles" in response.text
    assert "Open review to inspect" in response.text
    assert "Open Knowledge Assist Review" in response.text
    assert "identity_role" in calls

    reset_session()
    _seed_crud_step3_session(
        knowledge_assist_enabled=False,
        active_workspace=True,
        classified_entities=[
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
                fields=[ClassifiedField(name="accountId", type="string")],
            )
        ],
    )
    calls.clear()

    response = client.get("/entities")

    assert response.status_code == 200
    assert "identity role suggestion" not in response.text
    assert calls == []


def test_step3_page_badge_batch_uses_one_ks_context_for_one_or_many_entities(monkeypatch):
    context_entries = 0

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            return {
                "suggestions": [{"suggestion_id": f"{scope}-{entity}"}],
                "suggestion_count": 1,
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        nonlocal context_entries
        context_entries += 1
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    _seed_multi_entity_step3_session(count=1)
    response = client.get("/entities")
    assert response.status_code == 200
    assert context_entries == 1

    context_entries = 0
    _seed_multi_entity_step3_session(count=5)
    response = client.get("/entities")
    assert response.status_code == 200
    assert context_entries == 1


def test_step3_page_badge_batch_matches_single_badge_helpers(monkeypatch):
    _seed_crud_step3_session(
        active_workspace=True,
        selected_entity_names=["AccountResponse", "CustomerResponse"],
        classified_entities=[
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
                fields=[ClassifiedField(name="accountId", type="string")],
            ),
            ClassifiedEntity(
                name="CustomerResponse",
                canonical_name="Customer",
                classification="entity",
                fields=[ClassifiedField(name="customerId", type="string")],
            ),
        ],
    )

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            counts = {
                ("validations", "Account"): 1,
                ("validations", "Customer"): 0,
                ("identity_role", "Account"): 2,
            }
            count = counts.get((scope, entity), 0)
            return {
                "suggestions": [{"suggestion_id": f"{scope}-{entity}-{index}"} for index in range(count)],
                "suggestion_count": count,
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)
    session = get_session()
    validation_entities = ["Account", "Customer"]
    identity_entities = ["Account"]

    single_validation_badges = [
        badge
        for entity in validation_entities
        if (badge := assist_service.get_validation_hint_badge(session, entity=entity))
    ]
    single_identity_badges = [
        badge
        for entity in identity_entities
        if (badge := assist_service.get_identity_role_suggestion_badge(session, entity=entity))
    ]
    batch_validation_badges, batch_identity_badges = assist_service.batch_fetch_step3_badge_counts(
        session,
        validation_entities=validation_entities,
        identity_entities=identity_entities,
    )

    assert batch_validation_badges == single_validation_badges
    assert batch_identity_badges == single_identity_badges
    assert [badge.entity for badge in batch_validation_badges] == ["Account"]
    assert batch_validation_badges[0].label == "1 validation hint"
    assert batch_identity_badges[0].label == "2 identity role suggestions"
    assert batch_identity_badges[0].drawer_url == "/entities/ks/drawer?scope=identity_role&entity=Account"


def test_step3_page_badge_batch_keeps_identity_badges_identity_eligible_only(monkeypatch):
    _seed_crud_step3_session(
        active_workspace=True,
        selected_entity_names=["AccountResponse", "AuditResponse"],
        classified_entities=[
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
                fields=[ClassifiedField(name="accountId", type="string")],
            ),
            ClassifiedEntity(
                name="AuditResponse",
                canonical_name="Audit",
                classification="entity",
                fields=[],
            ),
        ],
    )
    calls: list[tuple[str, str]] = []

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            calls.append((scope, entity))
            return {"suggestions": [], "suggestion_count": 0}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities")

    assert response.status_code == 200
    assert ("validations", "Account") in calls
    assert ("validations", "Audit") in calls
    assert ("identity_role", "Account") in calls
    assert ("identity_role", "Audit") not in calls


def test_step3_page_badge_batch_isolates_per_entity_validation_errors(monkeypatch):
    _seed_crud_step3_session(
        active_workspace=True,
        selected_entity_names=["AccountResponse", "CustomerResponse"],
        classified_entities=[
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
                fields=[],
            ),
            ClassifiedEntity(
                name="CustomerResponse",
                canonical_name="Customer",
                classification="entity",
                fields=[],
            ),
        ],
    )

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            if scope == "validations" and entity == "Account":
                raise KSCallError("suggest_manifest_candidates", "validation boom")
            return {
                "suggestions": [{"suggestion_id": f"{scope}-{entity}"}],
                "suggestion_count": 1,
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities")

    assert response.status_code == 200
    validation_badges, identity_badges = assist_service.batch_fetch_step3_badge_counts(
        get_session(),
        validation_entities=["Account", "Customer"],
        identity_entities=[],
    )
    assert [badge.entity for badge in validation_badges] == ["Customer"]
    assert identity_badges == []


def test_identity_role_suggestion_drawer_normalizes_and_rehydrates(monkeypatch):
    _seed_crud_step3_session(
        classified_entities=[
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
                fields=[ClassifiedField(name="accountId", type="string")],
            )
        ],
    )
    session = get_session()
    session.ks_workspace_state.review_history.append(
        KSReviewHistoryEntry(
            suggestion_id="id-role-1",
            type="identity_role",
            status="accepted",
            manifest_path="entities.Account.fields.accountId",
            reviewed_at="2026-05-07T10:00:00+00:00",
            review_context={"entity": "Account", "field": "accountId", "role": "persistence_id"},
        )
    )
    save_session(session)

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            assert scope == "identity_role"
            return {
                "suggestions": [
                    {
                        "suggestion_id": "id-role-1",
                        "entity": "Account",
                        "field": "ACCOUNT_ID",
                        "suggested_role": "persistence_id",
                        "summary": "Account id is the persistence identity.",
                        "confidence": 0.9,
                        "source_document_names": ["identity-ddl.sql"],
                        "citation_count": 1,
                    }
                ],
                "suggestion_count": 1,
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities/ks/drawer?scope=identity_role&entity=Account")

    assert response.status_code == 200
    payload = response.json()
    assert payload["review_url"] == "/entities/ks/identity-role-review"
    row = payload["scopes"][0]["rows"][0]
    assert row["suggestion_type"] == "identity_role"
    assert row["status"] == "accepted"
    assert row["manifest_path"] == "entities.Account.fields.accountId"
    assert row["payload"]["field"] == "accountId"
    assert row["payload"]["source_field_name"] == "ACCOUNT_ID"
    assert row["payload"]["suggested_role"] == "persistence_id"
    assert row["payload"]["suggestion_semantics"]["category"] == "Applies generated change"


def test_identity_role_suggestion_review_accepts_edits_and_rejects_without_evidence(monkeypatch):
    _seed_crud_step3_session(
        classified_entities=[
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
                fields=[
                    ClassifiedField(name="accountId", type="string"),
                    ClassifiedField(name="externalRef", type="string"),
                ],
            )
        ],
    )
    submitted: list[list[dict[str, str]]] = []
    unsupported_ks_keys = {
        "confidence",
        "signals",
        "summary",
        "confidence_basis",
        "source_document_ids",
        "source_document_names",
        "review_needed",
        "conflicting_roles",
        "field_name",
        "citations",
        "snippets",
    }

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict[str, str]]):
            for decision in decisions:
                if "edited_payload" not in decision:
                    assert set(decision) == {"suggestion_id", "status"}
                    continue
                edited_payload = decision["edited_payload"]
                assert set(edited_payload) <= {"entity", "field", "role", "suggested_role", "rationale"}
                assert not (set(edited_payload) & unsupported_ks_keys)
            submitted.append(decisions)
            return {
                "success": True,
                "outcomes": [
                    {"suggestion_id": decision["suggestion_id"], "success": True}
                    for decision in decisions
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    accepted = client.post(
        "/entities/ks/identity-role-review",
        json={
            "decisions": [
                {
                    "suggestion_id": "id-role-1",
                    "suggestion_type": "identity_role",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {
                        "entity": "Account",
                        "field": "accountId",
                        "suggested_role": "persistence_id",
                    },
                }
            ]
        },
    )

    assert accepted.status_code == 200
    accepted_payload = accepted.json()
    assert accepted_payload["applied_count"] == 1
    assert accepted_payload["stats"]["persistence_ids"] == 1
    assert accepted_payload["entities"][0]["assigned_count"] == 1
    accepted_field = accepted_payload["entities"][0]["fields"][0]
    assert accepted_field["current_role"] == "persistence_id"
    assert accepted_field["reviewed_at"]
    session = get_session()
    assert [(decision.field, decision.role, decision.provenance) for decision in session.identity_role_decisions] == [
        ("accountId", "persistence_id", "knowledge-assist")
    ]
    assert session.ks_workspace_state.review_history[-1].type == "identity_role"
    assert session.ks_workspace_state.evidence_links == []
    assert build_manifest_dict(session)["identity_overrides"] == [
        {"entity": "Account", "persistence_id": "accountId"}
    ]

    edited = client.post(
        "/entities/ks/identity-role-review",
        json={
            "decisions": [
                {
                    "suggestion_id": "id-role-2",
                    "suggestion_type": "identity_role",
                    "status": "edited",
                    "entity": "Account",
                    "payload": {
                        "entity": "Account",
                        "field": "externalRef",
                        "suggested_role": "external_reference",
                        "confidence": 0.81,
                        "signals": ["external-reference-name"],
                        "summary": "External reference is not persistence identity.",
                        "confidence_basis": "Matched field catalog names.",
                        "source_document_ids": ["doc-1"],
                        "source_document_names": ["identity-catalog.csv"],
                        "review_needed": False,
                        "conflicting_roles": ["business_key"],
                        "field_name": "externalRef",
                        "snippets": ["externalRef is supplied by provider."],
                    },
                    "edited_payload": {
                        "role": "business_key",
                        "confidence": 0.4,
                        "signals": ["ui-noise"],
                        "rationale": "Manual review selected this as the business key.",
                    },
                }
            ]
        },
    )

    assert edited.status_code == 200
    assert ("externalRef", "business_key", "knowledge-assist") in [
        (decision.field, decision.role, decision.provenance)
        for decision in get_session().identity_role_decisions
    ]
    assert build_manifest_dict(get_session())["identity_roles"] == [
        {
            "entity": "Account",
            "field": "externalRef",
            "role": "business_key",
            "mode": "metadata_only",
        }
    ]

    rejected = client.post(
        "/entities/ks/identity-role-review",
        json={
            "decisions": [
                {
                    "suggestion_id": "id-role-3",
                    "suggestion_type": "identity_role",
                    "status": "rejected",
                    "entity": "Account",
                    "payload": {
                        "entity": "Account",
                        "field": "externalRef",
                        "suggested_role": "persistence_id",
                    },
                }
            ]
        },
    )

    assert rejected.status_code == 200
    assert rejected.json()["applied_count"] == 0
    assert len(get_session().identity_role_decisions) == 2
    assert submitted[0] == [{"suggestion_id": "id-role-1", "status": "accepted"}]
    assert submitted[1][0]["suggestion_id"] == "id-role-2"
    assert submitted[1][0]["status"] == "edited"
    assert submitted[1][0]["edited_payload"]["entity"] == "Account"
    assert submitted[1][0]["edited_payload"]["field"] == "externalRef"
    assert submitted[1][0]["edited_payload"]["role"] == "business_key"
    assert submitted[1][0]["edited_payload"]["suggested_role"] == "business_key"
    assert submitted[1][0]["edited_payload"]["rationale"] == "Manual review selected this as the business key."


def test_edited_identity_role_persistence_id_replaces_existing_override(monkeypatch):
    _seed_crud_step3_session(
        classified_entities=[
            ClassifiedEntity(
                name="TransactionPostingResponse",
                canonical_name="TransactionPosting",
                classification="entity",
                fields=[
                    ClassifiedField(name="legacyPostingId", type="string"),
                    ClassifiedField(name="postingRowId", type="string"),
                ],
            )
        ],
        selected_entity_names=["TransactionPostingResponse"],
    )
    submitted: list[list[dict[str, object]]] = []

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict[str, object]]):
            submitted.append(decisions)
            return {
                "success": True,
                "outcomes": [
                    {"suggestion_id": decision["suggestion_id"], "success": True}
                    for decision in decisions
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    first = client.post(
        "/entities/ks/identity-role-review",
        json={
            "decisions": [
                {
                    "suggestion_id": "posting-role-1",
                    "suggestion_type": "identity_role",
                    "status": "accepted",
                    "entity": "TransactionPosting",
                    "payload": {
                        "entity": "TransactionPosting",
                        "field": "legacyPostingId",
                        "suggested_role": "persistence_id",
                    },
                }
            ]
        },
    )
    assert first.status_code == 200

    edited = client.post(
        "/entities/ks/identity-role-review",
        json={
            "decisions": [
                {
                    "suggestion_id": "posting-role-2",
                    "suggestion_type": "identity_role",
                    "status": "edited",
                    "entity": "TransactionPosting",
                    "payload": {
                        "entity": "TransactionPosting",
                        "field": "postingRowId",
                        "suggested_role": "event_id",
                        "source_document_names": ["posting-catalog.csv"],
                    },
                    "edited_payload": {"role": "persistence_id"},
                }
            ]
        },
    )

    assert edited.status_code == 200
    session = get_session()
    assert [(decision.entity, decision.field, decision.role) for decision in session.identity_role_decisions] == [
        ("TransactionPosting", "postingRowId", "persistence_id")
    ]
    assert build_manifest_dict(session)["identity_overrides"] == [
        {"entity": "TransactionPosting", "persistence_id": "postingRowId"}
    ]
    assert submitted[1][0]["edited_payload"] == {
        "entity": "TransactionPosting",
        "field": "postingRowId",
        "role": "persistence_id",
        "suggested_role": "persistence_id",
    }


def test_identity_role_suggestion_review_rejects_conflicting_batch_before_ks(monkeypatch):
    _seed_crud_step3_session(
        classified_entities=[
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
                fields=[
                    ClassifiedField(name="accountId", type="string"),
                    ClassifiedField(name="externalId", type="string"),
                ],
            )
        ],
    )

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("conflicting identity batches should fail before KS submit")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/entities/ks/identity-role-review",
        json={
            "decisions": [
                {
                    "suggestion_id": "id-role-1",
                    "suggestion_type": "identity_role",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {
                        "entity": "Account",
                        "field": "accountId",
                        "suggested_role": "persistence_id",
                    },
                },
                {
                    "suggestion_id": "id-role-2",
                    "suggestion_type": "identity_role",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {
                        "entity": "Account",
                        "field": "externalId",
                        "suggested_role": "persistence_id",
                    },
                },
            ]
        },
    )

    assert response.status_code == 400
    assert "can have only one active persistence_id in this review batch" in response.json()["errors"][0]
    assert get_session().identity_role_decisions == []

    response = client.post(
        "/entities/ks/identity-role-review",
        json={
            "decisions": [
                {
                    "suggestion_id": "id-role-3",
                    "suggestion_type": "identity_role",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {
                        "entity": "Account",
                        "field": "accountId",
                        "suggested_role": "persistence_id",
                    },
                },
                {
                    "suggestion_id": "id-role-4",
                    "suggestion_type": "identity_role",
                    "status": "edited",
                    "entity": "Account",
                    "payload": {
                        "entity": "Account",
                        "field": "accountId",
                        "suggested_role": "external_reference",
                    },
                    "edited_payload": {"role": "business_key"},
                },
            ]
        },
    )

    assert response.status_code == 400
    assert "can have only one active identity role in this review batch" in response.json()["errors"][0]
    assert get_session().identity_role_decisions == []


@pytest.mark.parametrize(
    ("suggestion", "expected_field_name"),
    [
        ({"suggestion_id": "s-top", "field_name": "account_id"}, "account_id"),
        (
            {"suggestion_id": "s-payload-name", "payload": {"field_name": "routingNumber"}},
            "routingNumber",
        ),
        ({"suggestion_id": "s-payload-field", "payload": {"field": "status"}}, "status"),
        (
            {"suggestion_id": "s-payload-target", "payload": {"target_field": "creditLimit"}},
            "creditLimit",
        ),
    ],
)
def test_step3_ks_suggestions_resolve_field_name_aliases(
    monkeypatch,
    suggestion,
    expected_field_name,
):
    _seed_crud_step3_session()

    class FakeClient:
        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {"fields": [{"field_name": expected_field_name}], "warnings": []}

        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            assert scope == "fields"
            return {"suggestions": [suggestion], "suggestion_count": 1, "warnings": []}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities/ks/suggestions?entity=Account")

    assert response.status_code == 200
    payload = response.json()
    assert payload["suggestions"][0]["field_name"] == expected_field_name
    if isinstance(payload["suggestions"][0].get("payload"), dict):
        assert payload["suggestions"][0]["payload"]["field_name"] == expected_field_name


def test_step3_ks_suggestions_skip_malformed_field_name_and_surface_warning(monkeypatch):
    _seed_crud_step3_session()

    class FakeClient:
        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {"fields": [{"field_name": "account_id"}], "warnings": []}

        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            return {
                "suggestions": [{"suggestion_id": "s-missing", "payload": {"title": "No field"}}],
                "suggestion_count": 1,
                "warnings": [],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities/ks/suggestions?entity=Account")

    assert response.status_code == 200
    payload = response.json()
    assert payload["empty"] is True
    assert payload["suggestions"] == []
    assert payload["suggestion_count"] == 0
    assert payload["raw_suggestion_count"] == 1
    assert "Skipped 1 malformed Knowledge Assist field suggestion" in payload["warnings"][0]


def test_step3_ks_suggestions_resolve_legacy_catalog_field_to_current_model(monkeypatch):
    _seed_crud_step3_session(
        classified_entities=[
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
                fields=[ClassifiedField(name="accountStatus", type="string")],
            )
        ]
    )

    class FakeClient:
        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {"fields": [{"field_name": "ACCOUNT_STATUS"}], "warnings": []}

        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            return {
                "suggestions": [
                    {
                        "suggestion_id": "s-status",
                        "field_name": "ACCOUNT_STATUS",
                        "conflict_hint": "DORMANT appears in catalog evidence.",
                    }
                ],
                "suggestion_count": 1,
                "warnings": [],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities/ks/suggestions?entity=Account")

    assert response.status_code == 200
    payload = response.json()
    assert payload["empty"] is False
    suggestion = payload["suggestions"][0]
    assert suggestion["field_name"] == "accountStatus"
    assert suggestion["source_field_name"] == "ACCOUNT_STATUS"
    assert "DORMANT" in suggestion["conflict_hint"]


def test_step3_field_suggestion_marks_current_match_already_satisfied(monkeypatch):
    _seed_crud_step3_session(
        classified_entities=[
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
                fields=[ClassifiedField(name="accountStatus", type="string", required=False)],
            )
        ]
    )

    class FakeClient:
        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {"fields": [{"field_name": "ACCOUNT_STATUS", "field_type": "string", "nullable": True}], "warnings": []}

        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            return {
                "suggestions": [
                    {
                        "suggestion_id": "s-status",
                        "field_name": "ACCOUNT_STATUS",
                        "field_type": "string",
                        "nullable": True,
                    }
                ],
                "suggestion_count": 1,
                "warnings": [],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities/ks/suggestions?entity=Account")

    assert response.status_code == 200
    suggestion = response.json()["suggestions"][0]
    semantics = suggestion["suggestion_semantics"]
    assert suggestion["field_name"] == "accountStatus"
    assert semantics["category"] == "Already satisfied"
    assert semantics["already_satisfied"] is True
    assert semantics["impact"] == [
        "No change. Existing model already matches Knowledge Assist evidence."
    ]
    assert semantics["current"]["type"] == "string"
    assert semantics["suggested"]["type"] == "string"
    assert semantics["current"]["nullable"] is True
    assert semantics["suggested"]["nullable"] is True
    assert semantics["changed_count"] == 0
    assert semantics["compared_count"] == 4
    assert all(delta["changed"] is False for delta in semantics["deltas"])


def test_step3_field_suggestion_shows_generated_app_deltas(monkeypatch):
    _seed_crud_step3_session(
        classified_entities=[
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
                fields=[ClassifiedField(name="creditLimit", type="integer", required=True)],
            )
        ]
    )

    class FakeClient:
        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {
                "fields": [
                    {
                        "field_name": "creditLimit",
                        "field_type": "decimal",
                        "nullable": True,
                        "description": "Approved credit line.",
                    }
                ],
                "warnings": [],
            }

        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            return {
                "suggestions": [
                    {
                        "suggestion_id": "s-credit",
                        "field_name": "creditLimit",
                        "field_type": "decimal",
                        "nullable": True,
                        "description": "Approved credit line.",
                    }
                ],
                "suggestion_count": 1,
                "warnings": [],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities/ks/suggestions?entity=Account")

    assert response.status_code == 200
    semantics = response.json()["suggestions"][0]["suggestion_semantics"]
    assert semantics["category"] == "Applies generated change"
    assert semantics["already_satisfied"] is False
    assert semantics["impact"] == [
        "Will update type",
        "Will update nullable",
        "Description differs; Studio records the suggested description in review history only.",
    ]
    assert semantics["changed_count"] == 3
    assert semantics["compared_count"] == 4
    delta_labels = {delta["label"] for delta in semantics["deltas"]}
    assert {"Field name", "Type", "Nullable", "Description"} <= delta_labels
    changed_labels = {delta["label"] for delta in semantics["deltas"] if delta["changed"]}
    assert changed_labels == {"Type", "Nullable", "Description"}


def test_step3_field_suggestion_description_only_is_review_needed(monkeypatch):
    _seed_crud_step3_session(
        classified_entities=[
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
                fields=[ClassifiedField(name="accountStatus", type="string", required=False)],
            )
        ]
    )

    class FakeClient:
        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {"fields": [{"field_name": "accountStatus", "field_type": "string", "nullable": True}], "warnings": []}

        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            return {
                "suggestions": [
                    {
                        "suggestion_id": "s-status-description",
                        "field_name": "accountStatus",
                        "field_type": "string",
                        "nullable": True,
                        "description": "Lifecycle status from the source catalog.",
                    }
                ],
                "suggestion_count": 1,
                "warnings": [],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities/ks/suggestions?entity=Account")

    assert response.status_code == 200
    semantics = response.json()["suggestions"][0]["suggestion_semantics"]
    assert semantics["category"] == "Review needed"
    assert semantics["impact"] == [
        "Description differs; Studio records the suggested description in review history only."
    ]
    assert semantics["changed_count"] == 1
    assert semantics["compared_count"] == 4
    changed_labels = [delta["label"] for delta in semantics["deltas"] if delta["changed"]]
    assert changed_labels == ["Description"]


def test_step3_field_suggestion_preserves_evidence_detail_fields(monkeypatch):
    _seed_crud_step3_session(
        classified_entities=[
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
                fields=[ClassifiedField(name="openedDate", type="date", required=False)],
            )
        ]
    )

    class FakeClient:
        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {"fields": [{"field_name": "openedDate", "field_type": "date", "nullable": True}], "warnings": []}

        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            return {
                "suggestions": [
                    {
                        "suggestion_id": "s-opened-date",
                        "field_name": "openedDate",
                        "field_type": "date",
                        "nullable": True,
                        "summary": "Source DDA evidence describes the account opening date.",
                        "rationale": "Use the account open date from the source file.",
                        "confidence": 0.91,
                        "source_document_names": ["dda-fields.csv"],
                        "citations": [
                            {
                                "document_name": "dda-fields.csv",
                                "section": "Account",
                                "snippet": "OPENED_DATE is the account open date.",
                            }
                        ],
                        "snippets": ["OPENED_DATE is the account open date."],
                    }
                ],
                "suggestion_count": 1,
                "warnings": [],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities/ks/suggestions?entity=Account")

    assert response.status_code == 200
    suggestion = response.json()["suggestions"][0]
    assert suggestion["summary"] == "Source DDA evidence describes the account opening date."
    assert suggestion["rationale"] == "Use the account open date from the source file."
    assert suggestion["source_document_names"] == ["dda-fields.csv"]
    assert suggestion["citations"][0]["snippet"] == "OPENED_DATE is the account open date."
    assert suggestion["snippets"] == ["OPENED_DATE is the account open date."]


def test_step3_field_suggestion_parses_string_nullable_values(monkeypatch):
    _seed_crud_step3_session(
        classified_entities=[
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
                fields=[ClassifiedField(name="accountStatus", type="string", required=True)],
            )
        ]
    )

    class FakeClient:
        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {"fields": [{"field_name": "accountStatus", "nullable": "false"}], "warnings": []}

        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            return {
                "suggestions": [
                    {
                        "suggestion_id": "s-status",
                        "field_name": "accountStatus",
                        "nullable": "false",
                    }
                ],
                "suggestion_count": 1,
                "warnings": [],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities/ks/suggestions?entity=Account")

    assert response.status_code == 200
    semantics = response.json()["suggestions"][0]["suggestion_semantics"]
    assert semantics["category"] == "Already satisfied"
    assert semantics["current"]["nullable"] is False
    assert semantics["suggested"]["nullable"] is False
    assert semantics["changed_count"] == 0
    assert semantics["compared_count"] == 4


def test_step3_field_suggestion_new_field_shows_add_impact(monkeypatch):
    _seed_crud_step3_session(
        classified_entities=[
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
                fields=[ClassifiedField(name="accountStatus", type="string")],
            )
        ]
    )

    class FakeClient:
        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {"fields": [{"field_name": "openedAt", "field_type": "datetime"}], "warnings": []}

        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            return {
                "suggestions": [
                    {
                        "suggestion_id": "s-opened",
                        "field_name": "openedAt",
                        "field_type": "datetime",
                    }
                ],
                "suggestion_count": 1,
                "warnings": [],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities/ks/suggestions?entity=Account")

    assert response.status_code == 200
    semantics = response.json()["suggestions"][0]["suggestion_semantics"]
    assert semantics["category"] == "Applies generated change"
    assert semantics["impact"] == ["Will add field"]


def test_step3_type_less_new_field_suggestion_is_not_actionable(monkeypatch):
    _seed_crud_step3_session(
        classified_entities=[
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
                fields=[ClassifiedField(name="accountStatus", type="string")],
            )
        ]
    )

    class FakeClient:
        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {"fields": [{"field_name": "openedAt"}], "warnings": []}

        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            return {
                "suggestions": [
                    {
                        "suggestion_id": "s-opened",
                        "field_name": "openedAt",
                    }
                ],
                "suggestion_count": 1,
                "warnings": [],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities/ks/suggestions?entity=Account")

    assert response.status_code == 200
    suggestion = response.json()["suggestions"][0]
    semantics = suggestion["suggestion_semantics"]
    assert suggestion["actionable"] is False
    assert "did not provide a type" in suggestion["catalog_only_reason"]
    assert semantics["category"] == "Review needed"
    assert semantics["impact"] == [
        "Review needed. Knowledge Assist did not provide a field type, so Studio cannot add this field yet."
    ]


def test_step3_ks_suggestions_mark_unknown_conflict_hints_catalog_only(monkeypatch):
    _seed_crud_step3_session(
        classified_entities=[
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
                fields=[ClassifiedField(name="accountStatus", type="string")],
            )
        ]
    )

    class FakeClient:
        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {"fields": [{"field_name": "LEGACY_STATUS"}], "warnings": []}

        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            return {
                "suggestions": [
                    {
                        "suggestion_id": "s-unknown",
                        "field_name": "LEGACY_STATUS",
                        "conflict_hint": "Catalog field does not match the current CRUD model.",
                    },
                    {
                        "suggestion_id": "s-current",
                        "field_name": "ACCOUNT_STATUS",
                        "conflict_hint": "DORMANT appears in catalog evidence.",
                    },
                ],
                "suggestion_count": 2,
                "warnings": [],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities/ks/suggestions?entity=Account")

    assert response.status_code == 200
    suggestions = {item["suggestion_id"]: item for item in response.json()["suggestions"]}
    assert suggestions["s-unknown"]["actionable"] is False
    assert suggestions["s-current"]["field_name"] == "accountStatus"
    assert "actionable" not in suggestions["s-current"]


def test_step3_field_suggestion_template_uses_resolved_field_for_evidence():
    _seed_crud_step3_session(active_workspace=True)

    response = client.get("/entities")

    assert response.status_code == 200
    js = _step3_js()
    assert "function resolveKsSuggestionFieldName" in js
    assert 'data-field-name="${escapeHtml(resolvedFieldName)}"' in js
    assert "loadSuggestionEvidence(${escapeInlineJsArg(suggestion.suggestion_id)}, ${escapeInlineJsArg(entity)}, ${escapeInlineJsArg(resolvedFieldName)})" in js
    assert "Field name missing; evidence lookup is unavailable for this suggestion." not in response.text
    assert "Evidence lookup requires a resolved current field name." in js


def test_step3_field_suggestion_template_uses_semantic_copy_and_textarea():
    _seed_crud_step3_session(active_workspace=True)

    response = client.get("/entities")

    assert response.status_code == 200
    js = _step3_js()
    assert "No change. Existing model already matches Knowledge Assist evidence." in js
    assert "const impacts = Array.isArray(semantics.impact)" in js
    assert "const deltas = Array.isArray(semantics.deltas)" in js
    assert "function fieldChangeSummary" in js
    assert "fields compared" in js
    assert "Already matches" in js
    assert "Mark reviewed" in js
    assert ">Hide</button>" in js
    assert ">Apply</button>" in js
    assert "Apply edited" in js
    assert "ks-suggestion-card-noop" in js
    assert '<textarea class="ks-edit-description"' in js
    assert 'class="ks-edit-description" value=' not in js


def test_step3_full_review_details_renderer_shows_evidence_and_empty_state():
    _seed_crud_step3_session(active_workspace=True)

    response = client.get("/entities")

    assert response.status_code == 200
    js = _step3_js()
    assert "function renderSuggestionDetailsPanel" in js
    assert "Evidence summary" in js
    assert "Sources and snippets" in js
    assert "Normalized suggestion payload" in js
    assert "Raw KS JSON" in js
    assert "No raw evidence detail was returned for this suggestion." in js
    assert "renderSuggestionDetailsPanel(suggestion, { normalizedPayload: normalizedDetails })" in js
    assert "renderSuggestionDetailsPanel(row.row || {}, {" in js
    assert "JSON.stringify(suggestion, null, 2)" not in js


def test_step3_renders_full_width_ka_review_surface():
    _seed_crud_step3_session(active_workspace=True)

    response = client.get("/entities")

    assert response.status_code == 200
    assert "Open Knowledge Assist Review" in response.text
    assert "data-step3-ka-full-review" in response.text
    assert 'data-ka-full-filter="entity"' in response.text
    assert 'data-ka-full-filter="type"' in response.text
    assert 'data-ka-full-filter="category"' in response.text
    assert 'data-ka-full-filter="status"' in response.text
    assert 'data-ka-full-review-save' in response.text
    assert 'data-ka-full-review-count' in response.text
    js = _step3_js()
    assert "step3-ka-review-table" in js
    assert "<th>Type</th>" in js
    assert "<th>Target</th>" in js
    assert "<th>Current</th>" in js
    assert "<th>Suggested</th>" in js
    assert "<th>Impact</th>" in js
    assert "<th>Evidence</th>" in js
    assert "<th>Actions</th>" in js
    assert "Entity / field / rule / transform" not in response.text
    assert "Generated impact" not in response.text
    assert "data-ka-full-details-for" in js
    assert "data-ka-full-toggle-details" in js
    assert "hidden>" in js
    assert "function kaFullImpactDisplay" in js
    assert "label: 'Applies'" in js
    assert "label: 'Metadata'" in js
    assert "label: 'Advisory'" in js
    assert "label: 'Satisfied'" in js
    assert "label: 'Review'" in js
    assert "function kaFullEvidenceDisplay" in js
    assert "label: 'Backed'" in js
    assert "label: 'None'" in js
    assert "label: 'Unavailable'" in js
    assert "label: 'Stale'" in js
    assert "aria-label=\"${escapeHtml(impact.title)}\"" in js
    assert "aria-label=\"${escapeHtml(evidence.title)}\"" in js
    assert "step3-ka-review-value" in js
    assert "Field / Validation / Identity role" in response.text
    assert "Studio metadata only" in js
    assert "Applies generated change" in js
    assert "Already satisfied" in js
    assert "ka-category-generated ka-taxonomy-change" in js
    assert "ka-category-satisfied ka-taxonomy-satisfied" in js
    assert "const stagedKaFullFieldDecisions = new Map();" in js
    assert "const stagedKaFullValidationDecisions = new Map();" in js
    assert "const stagedKaFullIdentityDecisions = new Map();" in js
    assert "INITIAL_IDENTITY_REVIEW_ENTITIES" in js
    assert "function identityRoleImpactText(value)" in js
    assert "data-ka-full-identity-impact" in js
    assert "event.target.matches('[data-ka-full-identity-role]')" in js
    assert "/entities/ks/validation-review" in js
    assert "/entities/ks/identity-role-review" in js


def test_step3_right_rail_is_read_only_ka_summary():
    _seed_crud_step3_session(active_workspace=True)

    response = client.get("/entities")

    assert response.status_code == 200
    assert "Knowledge Assist Summary" in response.text
    assert "Snapshot of Step 3 review state for the selected CRUD entities." in response.text
    assert "Field suggestions" in response.text
    assert "Validation hints" in response.text
    assert "Identity roles" in response.text
    assert "Open review to inspect" in response.text
    assert "Field suggestions update Studio field/schema metadata." in response.text
    assert "Validation hints materialize Step 6 validation rules." in response.text
    assert "These are reviewed independently. Rejecting one does not undo a previously accepted change from the other." in response.text
    assert 'id="rail-ka-summary-panel"' in response.text
    assert 'data-ka-summary-type="field"' in response.text
    assert 'data-ka-summary-type="validation"' in response.text
    assert 'data-ka-summary-type="identity_role"' in response.text
    assert 'data-ka-summary-status="accepted"' in response.text
    assert 'data-ka-summary-status="edited"' in response.text
    assert 'data-ka-summary-status="rejected"' in response.text
    assert 'id="ks-evidence-viewer"' not in response.text


def test_step3_ka_summary_uses_latest_selected_entity_review_state():
    _seed_crud_step3_session(
        active_workspace=True,
        classified_entities=[
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
            ),
            ClassifiedEntity(
                name="CustomerResponse",
                canonical_name="Customer",
                classification="entity",
            ),
        ],
        selected_entity_names=["AccountResponse"],
    )
    session = get_session()
    session.ks_workspace_state.review_history.extend(
        [
            KSReviewHistoryEntry(
                suggestion_id="validation-1",
                type="validation",
                status="accepted",
                manifest_path="entities.Account.fields.status.validations.not-null",
                reviewed_at="2026-05-17T10:00:00Z",
                review_context={
                    "entity": "Account",
                    "field": "status",
                    "validation_fallback_key": "account|status|not-null|entities.account.fields.status.validations.not-null|not_null=true",
                },
            ),
            KSReviewHistoryEntry(
                suggestion_id="validation-2",
                type="validation",
                status="rejected",
                manifest_path="entities.Account.fields.status.validations.not-null",
                reviewed_at="2026-05-17T10:05:00Z",
                review_context={
                    "entity": "Account",
                    "field": "status",
                    "validation_fallback_key": "account|status|not-null|entities.account.fields.status.validations.not-null|not_null=true",
                },
            ),
            KSReviewHistoryEntry(
                suggestion_id="identity-customer",
                type="identity_role",
                status="accepted",
                manifest_path="entities.Customer.fields.customerId",
                reviewed_at="2026-05-17T10:10:00Z",
                review_context={"entity": "Customer", "field": "customerId"},
            ),
            KSReviewHistoryEntry(
                suggestion_id="field-1",
                type="field",
                status="edited",
                manifest_path="entities.Account.fields.accountName",
                reviewed_at="2026-05-17T10:15:00Z",
            ),
        ]
    )
    save_session(session)

    response = client.get("/entities")

    assert response.status_code == 200
    assert "Knowledge Assist Summary" in response.text
    assert 'Edited: <strong data-ka-summary-status="edited">1</strong>' in response.text
    assert 'Rejected: <strong data-ka-summary-status="rejected">1</strong>' in response.text
    assert 'Accepted: <strong data-ka-summary-status="accepted">1</strong>' not in response.text
    js = _step3_js()
    assert "initialKaSummaryReviewStatuses" in response.text
    assert "INITIAL_KA_SUMMARY_REVIEW_STATUSES" in js
    assert "const kaSummaryReviewStatuses = { ...INITIAL_KA_SUMMARY_REVIEW_STATUSES };" in js
    assert "field:suggestion:field-1" in response.text
    assert "const status = kaFullInitialReviewStatus('field', suggestion.suggestion_id, suggestion.manifest_path)" in js
    assert "|| suggestion.status" in js


def test_step3_full_review_batch_save_keeps_only_failed_staged_decisions():
    _seed_crud_step3_session(active_workspace=True)

    response = client.get("/entities")

    assert response.status_code == 200
    js = _step3_js()
    assert "function clearSuccessfulKaFullDecisions" in js
    assert "function kaFullSuccessfulRowKeys" in js
    assert "function applyKaSummaryReviewUpdates" in js
    assert "function updateKaSummaryCount" in js
    assert "function kaFullInitialReviewStatus" in js
    assert 'kaSummaryReviewStatuses[`${row.type}:suggestion:${decision.suggestion_id}`] = nextStatus;' in js
    assert 'kaSummaryReviewStatuses[`${row.type}:path:${manifestPath}`] = nextStatus;' in js
    assert ".filter(outcome => outcome.success)" in js
    assert ".filter(([, decision]) => successfulIds.has(decision.suggestion_id))" in js
    assert "stagedMap.delete(rowKey);" in js
    assert "result.partial_failure" in js
    assert "applyKaSummaryReviewUpdates(stagedKaFullFieldDecisions, kaFullSuccessfulRowKeys(stagedKaFullFieldDecisions, result));" in js
    assert "applyKaSummaryReviewUpdates(stagedKaFullValidationDecisions, kaFullSuccessfulRowKeys(stagedKaFullValidationDecisions, result));" in js
    assert "applyKaSummaryReviewUpdates(stagedKaFullIdentityDecisions, kaFullSuccessfulRowKeys(stagedKaFullIdentityDecisions, result));" in js
    identity_save = js[
        js.index("if (stagedKaFullIdentityDecisions.size)") : js.index(
            "\n  }\n\n  updateKaFullReviewCount();",
            js.index("if (stagedKaFullIdentityDecisions.size)"),
        )
    ]
    assert "applyIdentityRoleLensProjection(lens, result);" in identity_save
    assert "result.stats && Array.isArray(result.entities)" in identity_save


def test_step3_full_review_batch_save_surfaces_errors_before_success_copy():
    _seed_crud_step3_session(active_workspace=True)

    response = client.get("/entities")

    assert response.status_code == 200
    js = _step3_js()
    assert "function kaFullReviewResultMessage" in js
    assert "Array.isArray(result.errors) && result.errors.length > 0" in js
    assert "return result.errors.join(' ');" in js
    assert "kaFullReviewResultMessage(result, 'Field suggestion review saved.')" in js
    assert "kaFullReviewResultMessage(result, 'Validation hint review saved.')" in js


def test_step3_ks_degraded_mode_is_non_blocking(monkeypatch):
    _seed_crud_step3_session()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise KSUnavailableError("mock KS unavailable")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    page = client.get("/entities")
    response = client.get("/entities/ks/suggestions?entity=Account")

    assert page.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["empty"] is True
    assert payload["suggestions"] == []
    assert "Knowledge Assist is off or unavailable" in payload["empty_reason"]


def test_step3_ks_suggestions_are_quiet_when_knowledge_assist_off(monkeypatch):
    _seed_crud_step3_session(knowledge_assist_enabled=False)

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when Knowledge Assist is off")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities/ks/suggestions?entity=Account")
    session = get_session()

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["empty"] is True
    assert payload["suggestions"] == []
    assert session.project_id is None
    assert session.ks_active is False


def test_step3_validation_badge_hidden_when_knowledge_assist_off(monkeypatch):
    _seed_crud_step3_session(knowledge_assist_enabled=False)

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when Knowledge Assist is off")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities")

    assert response.status_code == 200
    assert "validation hints" not in response.text
    assert "data-suggestion-drawer-open" not in response.text
    assert "data-step3-ka-full-review" not in response.text
    assert "Open Knowledge Assist Review" not in response.text


def test_step3_renders_validation_badge_when_suggestions_exist(monkeypatch):
    _seed_crud_step3_session(active_workspace=True)

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            assert scope == "validations"
            assert entity == "Account"
            return {
                "suggestions": [{"suggestion_id": "v-1", "field_name": "status"}],
                "suggestion_count": 1,
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities")

    assert response.status_code == 200
    assert "Validation hints" in response.text
    assert "Open review to inspect" in response.text
    assert "ka-suggestion-badge-row" not in response.text
    assert 'data-suggestion-drawer-url="/entities/ks/drawer?scope=validations&amp;entity=Account"' not in response.text


def test_step3_renders_validation_badges_for_all_selected_entities(monkeypatch):
    _seed_crud_step3_session(
        active_workspace=True,
        selected_entity_names=["AccountResponse", "CustomerResponse"],
        classified_entities=[
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
            ),
            ClassifiedEntity(
                name="CustomerResponse",
                canonical_name="Customer",
                classification="entity",
            ),
        ],
    )
    calls: list[str] = []

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            assert scope == "validations"
            calls.append(entity)
            return {
                "suggestions": [{"suggestion_id": f"v-{entity}", "field_name": "status"}],
                "suggestion_count": 1,
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities")

    assert response.status_code == 200
    assert calls == ["Account", "Customer"]
    assert "Selected entities:" in response.text
    assert "Account, Customer" in response.text
    assert "Validation hints" in response.text
    assert "Open review to inspect" in response.text
    assert "Account · 1 validation hint" not in response.text
    assert "Customer · 1 validation hint" not in response.text
    assert 'data-suggestion-drawer-url="/entities/ks/drawer?scope=validations&amp;entity=Account"' not in response.text
    assert 'data-suggestion-drawer-url="/entities/ks/drawer?scope=validations&amp;entity=Customer"' not in response.text


def test_step3_validation_drawer_route_returns_rows(monkeypatch):
    _seed_crud_step3_session()

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            assert scope == "validations"
            assert entity == "Account"
            return {
                "suggestions": [
                    {
                        "suggestion_id": "v-1",
                        "field_name": "status",
                        "summary": "Add allowed-values validation.",
                        "manifest_path": "entities.Account.fields.status.validations",
                        "payload": {"validation_type": "not_null"},
                    }
                ]
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities/ks/drawer?scope=validations&entity=Account")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["scope"] == "validations"
    assert payload["empty"] is False
    assert payload["scopes"][0]["rows"][0]["suggestion_id"] == "v-1"
    assert payload["scopes"][0]["rows"][0]["manifest_path"] == "entities.Account.fields.status.validations"
    assert payload["scopes"][0]["rows"][0]["payload"]["field_name"] == "status"
    assert payload["scopes"][0]["rows"][0]["payload"]["validation_type"] == "not_null"
    assert payload["review_url"] == "/entities/ks/validation-review"


def test_step3_validation_drawer_rehydrates_saved_status_by_suggestion_id(monkeypatch):
    _seed_validation_step3_session()
    session = get_session()
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="v-1",
            type="validation",
            status="accepted",
            manifest_path="entities.Account.fields.status.validations.not-null",
            reviewed_at="2026-05-02T12:00:00+00:00",
            review_context={
                "entity": "Account",
                "field": "status",
                "validation_type": "not-null",
                "validation_fallback_key": (
                    "account|status|not-null|"
                    "entities.account.fields.status.validations.not-null"
                ),
            },
        )
    ]
    save_session(session)

    class FakeClient:
        def suggest_manifest_candidates(self, project_id: str, scope: str, entity: str, **kwargs):
            return {
                "suggestions": [
                    {
                        "suggestion_id": "v-1",
                        "field_name": "status",
                        "payload": {"field": "status", "validation_type": "not_null"},
                    }
                ]
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities/ks/drawer?scope=validations&entity=Account")

    assert response.status_code == 200
    row = response.json()["scopes"][0]["rows"][0]
    assert row["status"] == "accepted"
    assert row["payload"]["studio_review_status"] == "accepted"
    assert row["payload"]["studio_review_match"] == "suggestion_id"


def test_step3_validation_drawer_rehydrates_saved_status_by_validation_context(monkeypatch):
    _seed_validation_step3_session()
    session = get_session()
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="old-suggestion-id",
            type="validation",
            status="edited",
            manifest_path="entities.Account.fields.accountNumber.validations.max-length",
            reviewed_at="2026-05-02T12:05:00+00:00",
            edited_payload={"entity": "Account", "field": "accountNumber", "validation_type": "max-length", "max": 12},
            review_context={
                "entity": "Account",
                "field": "accountNumber",
                "validation_type": "max-length",
                "constraint_fingerprint": "max=12",
                "validation_fallback_key": (
                    "account|accountnumber|max-length|"
                    "entities.account.fields.accountnumber.validations.max-length|max=12"
                ),
            },
        )
    ]
    save_session(session)

    class FakeClient:
        def suggest_manifest_candidates(self, project_id: str, scope: str, entity: str, **kwargs):
            return {
                "suggestions": [
                    {
                        "suggestion_id": "new-suggestion-id",
                        "field_name": "accountNumber",
                        "payload": {"field": "accountNumber", "validation_type": "max_length", "max": 12},
                    }
                ]
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities/ks/drawer?scope=validations&entity=Account")

    assert response.status_code == 200
    row = response.json()["scopes"][0]["rows"][0]
    assert row["status"] == "edited"
    assert row["payload"]["studio_review_status"] == "edited"
    assert row["payload"]["studio_review_match"] == "validation_context"
    assert row["payload"]["studio_edited_payload"]["max"] == 12


def test_step3_validation_drawer_does_not_rehydrate_changed_constraint_value(monkeypatch):
    _seed_validation_step3_session()
    session = get_session()
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="old-suggestion-id",
            type="validation",
            status="accepted",
            manifest_path="entities.Account.fields.accountNumber.validations.max-length",
            reviewed_at="2026-05-02T12:05:00+00:00",
            review_context={
                "entity": "Account",
                "field": "accountNumber",
                "validation_type": "max-length",
                "constraint_fingerprint": "max=12",
                "validation_fallback_key": (
                    "account|accountnumber|max-length|"
                    "entities.account.fields.accountnumber.validations.max-length|max=12"
                ),
            },
        )
    ]
    save_session(session)

    class FakeClient:
        def suggest_manifest_candidates(self, project_id: str, scope: str, entity: str, **kwargs):
            return {
                "suggestions": [
                    {
                        "suggestion_id": "new-suggestion-id",
                        "field_name": "accountNumber",
                        "payload": {"field": "accountNumber", "validation_type": "max_length", "max": 14},
                    }
                ]
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities/ks/drawer?scope=validations&entity=Account")

    assert response.status_code == 200
    row = response.json()["scopes"][0]["rows"][0]
    assert row["status"] == "pending"
    assert "studio_review_status" not in row["payload"]


def test_step3_validation_drawer_maps_legacy_field_names_to_current_crud_fields(monkeypatch):
    _seed_crud_step3_session(
        classified_entities=[
            ClassifiedEntity(
                name="CustomerResponse",
                canonical_name="Customer",
                classification="entity",
                fields=[ClassifiedField(name="customerId", type="string")],
            )
        ],
        selected_entity_names=["CustomerResponse"],
    )

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            assert scope == "validations"
            assert entity == "Customer"
            return {
                "suggestions": [
                    {
                        "suggestion_id": "v-customer-id",
                        "field_name": "CUSTOMER_ID",
                        "payload": {"field": "CUSTOMER_ID", "validation_type": "not_null"},
                    }
                ]
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities/ks/drawer?scope=validations&entity=Customer")

    assert response.status_code == 200
    row = response.json()["scopes"][0]["rows"][0]
    assert row["title"] == "Validation hint for customerId"
    assert row["manifest_path"] == "entities.Customer.fields.customerId.validations.not-null"
    assert row["payload"]["field"] == "customerId"
    assert row["payload"]["field_name"] == "customerId"
    assert row["payload"]["source_field_name"] == "CUSTOMER_ID"


def test_step3_validation_drawer_marks_unknown_fields_catalog_only(monkeypatch):
    _seed_validation_step3_session()

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            return {
                "suggestions": [
                    {
                        "suggestion_id": "v-ghost",
                        "field_name": "GHOST_FIELD",
                        "payload": {"field": "GHOST_FIELD", "validation_type": "not_null"},
                    }
                ]
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities/ks/drawer?scope=validations&entity=Account")

    assert response.status_code == 200
    row = response.json()["scopes"][0]["rows"][0]
    assert row["payload"]["actionable"] is False
    assert "not available in the current CRUD model" in row["payload"]["catalog_only_reason"]


def test_step3_validation_review_rejects_ka_off_without_ks_call(monkeypatch):
    _seed_validation_step3_session(knowledge_assist_enabled=False)

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when Knowledge Assist is off")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/entities/ks/validation-review",
        json={
            "decisions": [
                {
                    "suggestion_id": "v-1",
                    "suggestion_type": "validation",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {"field": "status", "validation_type": "not_null"},
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "Knowledge Assist is off" in response.json()["errors"][0]


def test_step3_validation_review_rejects_unsupported_suggestion_type(monkeypatch):
    _seed_validation_step3_session()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called for invalid validation decisions")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/entities/ks/validation-review",
        json={
            "decisions": [
                {
                    "suggestion_id": "m-1",
                    "suggestion_type": "mapping",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {"field": "status", "validation_type": "not_null"},
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "unsupported suggestion_type" in response.json()["errors"][0]


def test_step3_validation_review_rejects_missing_target_field_without_provenance(monkeypatch):
    _seed_validation_step3_session()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when validation target field is missing")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/entities/ks/validation-review",
        json={
            "decisions": [
                {
                    "suggestion_id": "v-ghost",
                    "suggestion_type": "validation",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {"field": "ghostField", "validation_type": "not_null"},
                }
            ]
        },
    )
    session = get_session()

    assert response.status_code == 400
    assert "Field 'Account.ghostField' is not available" in response.json()["errors"][0]
    assert session.entity_rules == []
    assert session.ks_workspace_state.review_history == []
    assert session.ks_workspace_state.evidence_links == []
    assert session.ks_workspace_state.suggestion_review_state.accepted_ids == []


def test_step3_validation_review_applies_not_null_and_max_length(monkeypatch):
    _seed_validation_step3_session()
    submitted: list[list[dict]] = []

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            submitted.append(decisions)
            return {
                "success": True,
                "outcomes": [
                    {"suggestion_id": "v-not-null", "success": True},
                    {"suggestion_id": "v-max", "success": True},
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/entities/ks/validation-review",
        json={
            "decisions": [
                {
                    "suggestion_id": "v-not-null",
                    "suggestion_type": "validation",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {"field": "status", "validation_type": "not_null", "nullable": False},
                },
                {
                    "suggestion_id": "v-max",
                    "suggestion_type": "validation",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {"field": "accountNumber", "validation_type": "max_length", "max": 12},
                },
            ]
        },
    )
    session = get_session()

    assert response.status_code == 200
    assert response.json()["applied_count"] == 2
    assert submitted == [[
        {"suggestion_id": "v-not-null", "status": "accepted"},
        {"suggestion_id": "v-max", "status": "accepted"},
    ]]
    fields = {field.name: field for field in session.classified_entities[0].fields}
    assert fields["status"].required is True
    assert fields["accountNumber"].max_length == 12
    rules = session.entity_rules[0].rules
    assert [(rule.field, rule.type, rule.value) for rule in rules] == [
        ("status", "not-null", None),
        ("accountNumber", "max-length", "12"),
    ]
    assert [
        (
            rule.suggestion_id,
            rule.suggestion_type,
            rule.generated_by_ka,
            rule.applied_by,
            rule.ka_review_status,
        )
        for rule in rules
    ] == [
        ("v-not-null", "validation", True, "knowledge_assist", "accepted"),
        ("v-max", "validation", True, "knowledge_assist", "accepted"),
    ]
    assert rules[0].applied_at
    assert session.ks_workspace_state.suggestion_review_state.accepted_ids == ["v-not-null", "v-max"]
    assert session.ks_workspace_state.review_history[0].type == "validation"
    assert session.ks_workspace_state.review_history[0].review_context["constraint_fingerprint"] == "nullable=False"
    assert session.ks_workspace_state.evidence_links[0] == KSEvidenceLink(
        manifest_path="entities.Account.fields.status.validations.not-null",
        suggestion_id="v-not-null",
        provenance="ai-accepted",
    )


def test_step3_validation_reject_marks_existing_ka_rule_but_does_not_remove(monkeypatch):
    _seed_validation_step3_session()

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {
                "success": True,
                "outcomes": [{"suggestion_id": decisions[0]["suggestion_id"], "success": True}],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    assert client.post(
        "/entities/ks/validation-review",
        json={
            "decisions": [
                {
                    "suggestion_id": "v-status",
                    "suggestion_type": "validation",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {"field": "status", "validation_type": "not_null"},
                }
            ]
        },
    ).status_code == 200

    response = client.post(
        "/entities/ks/validation-review",
        json={
            "decisions": [
                {
                    "suggestion_id": "v-status",
                    "suggestion_type": "validation",
                    "status": "rejected",
                    "entity": "Account",
                    "payload": {"field": "status", "validation_type": "not_null"},
                }
            ]
        },
    )
    session = get_session()

    assert response.status_code == 200
    payload = response.json()
    assert payload["applied_count"] == 0
    assert (
        "v-status: Reject recorded. The KA-applied rule remains until removed in Step 6."
        in payload["warnings"]
    )
    assert len(session.entity_rules[0].rules) == 1
    rule = session.entity_rules[0].rules[0]
    assert rule.field == "status"
    assert rule.type == "not-null"
    assert rule.generated_by_ka is True
    assert rule.suggestion_id == "v-status"
    assert rule.ka_review_status == "rejected"
    assert session.ks_workspace_state.suggestion_review_state.rejected_ids == ["v-status"]


def test_step3_validation_reject_marks_changed_ka_rule_as_edited(monkeypatch):
    _seed_validation_step3_session()

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {"success": True, "outcomes": [{"suggestion_id": decisions[0]["suggestion_id"], "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    accepted = client.post(
        "/entities/ks/validation-review",
        json={
            "decisions": [
                {
                    "suggestion_id": "v-max",
                    "suggestion_type": "validation",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {"field": "accountNumber", "validation_type": "max_length", "value": 12},
                }
            ]
        },
    )
    assert accepted.status_code == 200
    session = get_session()
    session.entity_rules[0].rules[0].value = "14"
    save_session(session)

    response = client.post(
        "/entities/ks/validation-review",
        json={
            "decisions": [
                {
                    "suggestion_id": "v-max",
                    "suggestion_type": "validation",
                    "status": "rejected",
                    "entity": "Account",
                    "payload": {"field": "accountNumber", "validation_type": "max_length", "value": 12},
                }
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert (
        "v-max: Reject recorded. A KA-applied rule was changed after application and remains as KA-applied, edited."
        in payload["warnings"]
    )
    rule = get_session().entity_rules[0].rules[0]
    assert rule.value == "14"
    assert rule.ka_review_status == "edited"


def test_step3_validation_review_applies_legacy_uppercase_field_to_current_field(monkeypatch):
    _seed_crud_step3_session(
        classified_entities=[
            ClassifiedEntity(
                name="CustomerResponse",
                canonical_name="Customer",
                classification="entity",
                fields=[ClassifiedField(name="customerId", type="string")],
            )
        ],
        selected_entity_names=["CustomerResponse"],
    )

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {"success": True, "outcomes": [{"suggestion_id": "v-customer-id", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/entities/ks/validation-review",
        json={
            "decisions": [
                {
                    "suggestion_id": "v-customer-id",
                    "suggestion_type": "validation",
                    "status": "accepted",
                    "entity": "Customer",
                    "payload": {"field": "CUSTOMER_ID", "validation_type": "not_null"},
                }
            ]
        },
    )

    assert response.status_code == 200
    session = get_session()
    assert session.classified_entities[0].fields[0].required is True
    assert session.entity_rules[0].rules[0].field == "customerId"
    assert (
        session.ks_workspace_state.review_history[0].manifest_path
        == "entities.Customer.fields.customerId.validations.not-null"
    )


def test_step3_validation_review_applies_min_length_pattern_and_range(monkeypatch):
    _seed_validation_step3_session()

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {
                "success": True,
                "outcomes": [
                    {"suggestion_id": "v-min", "success": True},
                    {"suggestion_id": "v-pattern", "success": True},
                    {"suggestion_id": "v-range", "success": True},
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/entities/ks/validation-review",
        json={
            "decisions": [
                {
                    "suggestion_id": "v-min",
                    "suggestion_type": "validation",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {"field": "accountNumber", "validation_type": "min_length", "min": 8},
                },
                {
                    "suggestion_id": "v-pattern",
                    "suggestion_type": "validation",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {"field": "accountNumber", "validation_type": "pattern", "pattern": "^[0-9]+$"},
                },
                {
                    "suggestion_id": "v-range",
                    "suggestion_type": "validation",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {"field": "balance", "validation_type": "range", "min": 0, "max": 999},
                },
            ]
        },
    )
    session = get_session()

    assert response.status_code == 200
    fields = {field.name: field for field in session.classified_entities[0].fields}
    assert fields["accountNumber"].min_length == 8
    assert fields["accountNumber"].pattern == "^[0-9]+$"
    assert fields["balance"].minimum == 0
    assert fields["balance"].maximum == 999
    assert [(rule.field, rule.type, rule.value, rule.values) for rule in session.entity_rules[0].rules] == [
        ("accountNumber", "min-length", "8", []),
        ("accountNumber", "pattern", "^[0-9]+$", []),
        ("balance", "range", "0.0", ["999.0"]),
    ]


def test_step3_validation_review_reject_records_without_mutation(monkeypatch):
    _seed_validation_step3_session()

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {"success": True, "outcomes": [{"suggestion_id": "v-reject", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/entities/ks/validation-review",
        json={
            "decisions": [
                {
                    "suggestion_id": "v-reject",
                    "suggestion_type": "validation",
                    "status": "rejected",
                    "entity": "Account",
                    "payload": {"field": "status", "validation_type": "not_null"},
                }
            ]
        },
    )
    session = get_session()

    assert response.status_code == 200
    assert response.json()["applied_count"] == 0
    assert session.classified_entities[0].fields[0].required is False
    assert session.entity_rules == []
    assert session.ks_workspace_state.suggestion_review_state.rejected_ids == ["v-reject"]
    assert session.ks_workspace_state.evidence_links == []


def test_step3_validation_review_sends_and_applies_edited_payload(monkeypatch):
    _seed_validation_step3_session()
    submitted: list[list[dict]] = []

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            submitted.append(decisions)
            return {"success": True, "outcomes": [{"suggestion_id": "v-edit", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/entities/ks/validation-review",
        json={
            "decisions": [
                {
                    "suggestion_id": "v-edit",
                    "suggestion_type": "validation",
                    "status": "edited",
                    "entity": "Account",
                    "payload": {"field": "accountNumber", "validation_type": "max_length", "max": 10},
                    "manifest_path": "entities.Account.fields.accountNumber.validations.max-length",
                    "edited_payload": {
                        "target_field": "routingNumber",
                        "rule_type": "min_length",
                        "value": 8,
                        "title": "Display only",
                        "summary": "Drawer summary should not go to KS.",
                        "confidence": 0.91,
                        "citations": [{"document_id": "doc-1"}],
                        "snippets": ["routing number evidence"],
                        "document_labels": ["BRD.pdf"],
                    },
                }
            ]
        },
    )
    session = get_session()

    assert response.status_code == 200
    assert submitted[0][0]["edited_payload"] == {
        "entity": "Account",
        "field": "routingNumber",
        "validation_type": "min-length",
        "min": 8,
        "min_length": 8,
    }
    assert session.classified_entities[0].fields[1].max_length is None
    assert session.classified_entities[0].fields[2].min_length == 8
    assert session.entity_rules[0].rules[0].field == "routingNumber"
    assert session.entity_rules[0].rules[0].type == "min-length"
    assert session.entity_rules[0].rules[0].value == "8"
    assert session.ks_workspace_state.suggestion_review_state.edited_ids == ["v-edit"]
    assert (
        session.ks_workspace_state.review_history[0].manifest_path
        == "entities.Account.fields.routingNumber.validations.min-length"
    )
    assert (
        session.ks_workspace_state.evidence_links[0].manifest_path
        == "entities.Account.fields.routingNumber.validations.min-length"
    )
    assert session.ks_workspace_state.evidence_links[0].provenance == "ai-edited"


def test_step3_validation_review_applies_combined_length_bounds(monkeypatch):
    _seed_validation_step3_session()

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {"success": True, "outcomes": [{"suggestion_id": "v-length", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/entities/ks/validation-review",
        json={
            "decisions": [
                {
                    "suggestion_id": "v-length",
                    "suggestion_type": "validation",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {
                        "field": "accountNumber",
                        "validation_type": "length",
                        "constraint": {"min": 8, "max": 14},
                    },
                }
            ]
        },
    )
    session = get_session()

    assert response.status_code == 200
    assert response.json()["applied_count"] == 2
    assert session.classified_entities[0].fields[1].min_length == 8
    assert session.classified_entities[0].fields[1].max_length == 14
    applied_rules = {(rule.field, rule.type, rule.value) for rule in session.entity_rules[0].rules}
    assert ("accountNumber", "min-length", "8") in applied_rules
    assert ("accountNumber", "max-length", "14") in applied_rules


def test_step3_validation_review_avoids_duplicate_rules(monkeypatch):
    _seed_validation_step3_session()

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {"success": True, "outcomes": [{"suggestion_id": "v-dup", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    payload = {
        "decisions": [
            {
                "suggestion_id": "v-dup",
                "suggestion_type": "validation",
                "status": "accepted",
                "entity": "Account",
                "payload": {"field": "status", "validation_type": "not_null"},
            }
        ]
    }

    assert client.post("/entities/ks/validation-review", json=payload).status_code == 200
    assert client.post("/entities/ks/validation-review", json=payload).status_code == 200

    session = get_session()
    assert len(session.entity_rules[0].rules) == 1
    assert session.entity_rules[0].rules[0].type == "not-null"
    assert session.entity_rules[0].rules[0].generated_by_ka is True
    assert session.entity_rules[0].rules[0].suggestion_id == "v-dup"


def test_step3_validation_duplicate_accept_does_not_relabel_manual_rule(monkeypatch):
    _seed_validation_step3_session()
    session = get_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[RuleEntry(field="status", type="not-null", applied_by="manual")],
            file_path="rules/account-business-rules.yaml",
        )
    ]
    save_session(session)

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {"success": True, "outcomes": [{"suggestion_id": "v-manual-dup", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/entities/ks/validation-review",
        json={
            "decisions": [
                {
                    "suggestion_id": "v-manual-dup",
                    "suggestion_type": "validation",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {"field": "status", "validation_type": "not_null"},
                }
            ]
        },
    )
    rule = get_session().entity_rules[0].rules[0]

    assert response.status_code == 200
    assert response.json()["applied_count"] == 0
    assert rule.generated_by_ka is False
    assert rule.suggestion_id is None
    assert rule.applied_by == "manual"


def test_step3_validation_review_partial_failure_applies_successful_only(monkeypatch):
    _seed_validation_step3_session()

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {
                "success": False,
                "outcomes": [
                    {"suggestion_id": "v-ok", "success": True},
                    {
                        "suggestion_id": "v-fail",
                        "success": False,
                        "error": "edited_payload.field is required.",
                        "warnings": ["Validation suggestion was not stored."],
                    },
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/entities/ks/validation-review",
        json={
            "decisions": [
                {
                    "suggestion_id": "v-ok",
                    "suggestion_type": "validation",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {"field": "status", "validation_type": "not_null"},
                },
                {
                    "suggestion_id": "v-fail",
                    "suggestion_type": "validation",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {"field": "accountNumber", "validation_type": "max_length", "max": 12},
                },
            ]
        },
    )
    session = get_session()

    assert response.status_code == 200
    payload = response.json()
    assert payload["partial_failure"] is True
    assert payload["saved_count"] == 1
    assert payload["failed_count"] == 1
    assert payload["errors"] == ["v-fail: edited_payload.field is required."]
    assert "v-fail: Validation suggestion was not stored." in payload["warnings"]
    assert payload["outcomes"][1]["error"] == "edited_payload.field is required."
    assert payload["outcomes"][1]["warnings"] == ["Validation suggestion was not stored."]
    assert session.classified_entities[0].fields[0].required is True
    assert session.classified_entities[0].fields[1].max_length is None


def test_step3_ks_evidence_is_quiet_when_knowledge_assist_off(monkeypatch):
    _seed_crud_step3_session(knowledge_assist_enabled=False)

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when Knowledge Assist is off")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/entities/ks/evidence?entity=Account&field_name=account_id")
    session = get_session()

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["definitions"] == []
    assert payload["evidence_chunks"] == []
    assert payload["source_count"] == 0
    assert session.project_id is None
    assert session.ks_active is False


def test_step3_ks_evidence_uses_generic_suggestion_chain(monkeypatch):
    _seed_crud_step3_session()

    class FakeClient:
        def get_suggestion_evidence_chain(
            self,
            project_id: str,
            scope: str,
            suggestion_id: str,
        ):
            assert scope == "fields"
            assert suggestion_id == "s-1"
            return {
                "tool_name": "get_suggestion_evidence_chain",
                "scope": scope,
                "suggestion_id": suggestion_id,
                "suggestion": {"field_name": "account_id", "entity": "Account"},
                "definitions": [{"field_name": "account_id"}],
                "evidence_chunks": [{"citation": {"document_name": "fields.csv"}}],
                "source_count": 1,
                "warnings": [],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get(
        "/entities/ks/evidence?entity=Account&field_name=account_id&suggestion_id=s-1"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["suggestion"]["field_name"] == "account_id"
    assert payload["definitions"] == [{"field_name": "account_id"}]
    assert payload["evidence_chunks"] == [{"citation": {"document_name": "fields.csv"}}]
    assert payload["source_count"] == 1


def test_step3_ks_evidence_uses_resolved_current_field_name(monkeypatch):
    _seed_crud_step3_session(
        classified_entities=[
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
                fields=[ClassifiedField(name="accountStatus", type="string")],
            )
        ]
    )

    class FakeClient:
        def get_suggestion_evidence_chain(
            self,
            project_id: str,
            scope: str,
            suggestion_id: str,
        ):
            return {
                "suggestion": {"field_name": "ACCOUNT_STATUS", "entity": "Account"},
                "definitions": [{"field_name": "ACCOUNT_STATUS"}],
                "evidence_chunks": [],
                "source_count": 1,
                "warnings": [],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get(
        "/entities/ks/evidence?entity=Account&field_name=ACCOUNT_STATUS&suggestion_id=s-status"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["field_name"] == "accountStatus"


def test_step3_review_accept_updates_workspace_state_and_applies_field(monkeypatch):
    _seed_crud_step3_session()

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            assert project_id.startswith("studio-ks-")
            assert decisions == [
                {
                    "suggestion_id": "s-1",
                    "status": "accepted",
                }
            ]
            return {
                "success": True,
                "outcomes": [
                    {"suggestion_id": "s-1", "status": "accepted", "success": True, "warnings": []}
                ],
                "warnings": [],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.routes.entities.ks_client", fake_ks_client)

    response = client.post(
        "/entities/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "s-1",
                    "entity": "Account",
                    "field_name": "account_id",
                    "status": "accepted",
                    "suggested_type": "string",
                    "suggested_nullable": False,
                    "suggested_description": "Primary key",
                }
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    session = get_session()
    assert session.project_id == session.ks_project_id
    assert session.ks_workspace_state.suggestion_review_state.accepted_ids == ["s-1"]
    assert session.ks_workspace_state.suggestion_review_state.edited_ids == []
    assert session.ks_workspace_state.suggestion_review_state.rejected_ids == []
    assert session.ks_workspace_state.review_history[-1].status == "accepted"
    assert session.ks_workspace_state.review_history[-1].manifest_path == "entities.Account.fields.account_id"
    assert session.ks_workspace_state.evidence_links == [
        KSEvidenceLink(
            manifest_path="entities.Account.fields.account_id",
            suggestion_id="s-1",
            provenance="ai-accepted",
        )
    ]
    assert session.classified_entities[0].fields == [
        ClassifiedField(name="account_id", type="string", required=True)
    ]


def test_step3_review_rejects_type_less_new_field_without_ks_call(monkeypatch):
    _seed_crud_step3_session(
        classified_entities=[
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
                fields=[],
            )
        ]
    )

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called for type-less new field decisions")
        yield

    monkeypatch.setattr("app.routes.entities.ks_client", fake_ks_client)

    response = client.post(
        "/entities/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "s-no-type",
                    "entity": "Account",
                    "field_name": "openedAt",
                    "status": "accepted",
                }
            ]
        },
    )
    session = get_session()

    assert response.status_code == 400
    assert response.json()["errors"] == [
        "Suggestion 's-no-type' cannot add Account.openedAt because no field type was provided."
    ]
    assert session.classified_entities[0].fields == []
    assert session.ks_workspace_state.review_history == []
    assert session.ks_workspace_state.evidence_links == []


def test_step3_review_edit_updates_history_evidence_and_single_owner(monkeypatch):
    _seed_crud_step3_session(
        classified_entities=[
            ClassifiedEntity(
                name="CustomerResponse",
                canonical_name="Customer",
                classification="entity",
            ),
            ClassifiedEntity(
                name="GetCustomerResponse",
                canonical_name="Customer",
                classification="entity",
            ),
        ],
        selected_entity_names=["CustomerResponse", "GetCustomerResponse"],
    )

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            assert decisions[0]["edited_payload"]["manifest_path"] == "entities.Customer.fields.customer_status"
            return {
                "success": True,
                "outcomes": [
                    {"suggestion_id": "s-2", "status": "edited", "success": True, "warnings": []}
                ],
                "warnings": [],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.routes.entities.ks_client", fake_ks_client)

    response = client.post(
        "/entities/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "s-2",
                    "entity": "Customer",
                    "field_name": "customer_status",
                    "status": "edited",
                    "suggested_type": "string",
                    "suggested_nullable": True,
                    "suggested_description": "Lifecycle status",
                    "edited_payload": {
                        "field_name": "customer_status",
                        "suggested_type": "string",
                        "suggested_nullable": False,
                        "suggested_description": "Reviewed lifecycle status",
                    },
                }
            ]
        },
    )

    assert response.status_code == 200
    session = get_session()
    assert session.ks_workspace_state.suggestion_review_state.accepted_ids == []
    assert session.ks_workspace_state.suggestion_review_state.edited_ids == ["s-2"]
    assert session.ks_workspace_state.review_history[-1].status == "edited"
    assert session.ks_workspace_state.review_history[-1].edited_payload == {
        "field_name": "customer_status",
        "suggested_type": "string",
        "suggested_nullable": False,
        "suggested_description": "Reviewed lifecycle status",
        "manifest_path": "entities.Customer.fields.customer_status",
    }
    assert session.ks_workspace_state.evidence_links[0].manifest_path == "entities.Customer.fields.customer_status"
    assert session.ks_workspace_state.evidence_links[0].provenance == "ai-edited"
    assert [field.name for field in session.classified_entities[0].fields] == ["customer_status"]
    assert session.classified_entities[0].fields[0].required is True
    assert session.classified_entities[1].fields == []


def test_step3_review_reject_removes_stale_evidence_and_skips_new_links(monkeypatch):
    _seed_crud_step3_session()
    session = get_session()
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["s-3"]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="entities.Account.fields.account_id",
            suggestion_id="s-3",
            provenance="ai-accepted",
        )
    ]
    save_session(session)

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {
                "success": True,
                "outcomes": [
                    {"suggestion_id": "s-3", "status": "rejected", "success": True, "warnings": []}
                ],
                "warnings": [],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.routes.entities.ks_client", fake_ks_client)

    response = client.post(
        "/entities/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "s-3",
                    "entity": "Account",
                    "field_name": "account_id",
                    "status": "rejected",
                    "suggested_type": "string",
                }
            ]
        },
    )

    assert response.status_code == 200
    session = get_session()
    assert session.ks_workspace_state.suggestion_review_state.accepted_ids == []
    assert session.ks_workspace_state.suggestion_review_state.rejected_ids == ["s-3"]
    assert session.ks_workspace_state.evidence_links == []


def test_step3_review_reject_preserves_other_accepted_evidence_on_same_manifest_path(monkeypatch):
    _seed_crud_step3_session()
    session = get_session()
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["s-old"]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="entities.Account.fields.account_id",
            suggestion_id="s-old",
            provenance="ai-accepted",
        )
    ]
    save_session(session)

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {
                "success": True,
                "outcomes": [
                    {"suggestion_id": "s-new", "status": "rejected", "success": True, "warnings": []}
                ],
                "warnings": [],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.routes.entities.ks_client", fake_ks_client)

    response = client.post(
        "/entities/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "s-new",
                    "entity": "Account",
                    "field_name": "account_id",
                    "status": "rejected",
                    "suggested_type": "string",
                }
            ]
        },
    )

    assert response.status_code == 200
    session = get_session()
    assert session.ks_workspace_state.suggestion_review_state.accepted_ids == ["s-old"]
    assert session.ks_workspace_state.suggestion_review_state.rejected_ids == ["s-new"]
    assert session.ks_workspace_state.evidence_links == [
        KSEvidenceLink(
            manifest_path="entities.Account.fields.account_id",
            suggestion_id="s-old",
            provenance="ai-accepted",
        )
    ]


def test_step3_review_partial_failure_is_surfaced_honestly(monkeypatch):
    _seed_crud_step3_session()

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {
                "success": False,
                "outcomes": [
                    {"suggestion_id": "s-4", "status": "accepted", "success": True, "warnings": []},
                    {
                        "suggestion_id": "s-5",
                        "status": "rejected",
                        "success": False,
                        "warnings": [],
                        "error": "Suggestion not found: s-5",
                    },
                ],
                "warnings": [],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.routes.entities.ks_client", fake_ks_client)

    response = client.post(
        "/entities/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "s-4",
                    "entity": "Account",
                    "field_name": "account_id",
                    "status": "accepted",
                    "suggested_type": "string",
                },
                {
                    "suggestion_id": "s-5",
                    "entity": "Account",
                    "field_name": "account_status",
                    "status": "rejected",
                    "suggested_type": "string",
                },
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["partial_failure"] is True
    assert payload["saved_count"] == 1
    assert payload["failed_count"] == 1
    session = get_session()
    assert session.ks_workspace_state.suggestion_review_state.accepted_ids == ["s-4"]
    assert session.ks_workspace_state.suggestion_review_state.rejected_ids == []
