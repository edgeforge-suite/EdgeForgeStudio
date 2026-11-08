"""Tests for the Knowledge Assist service guard."""

from __future__ import annotations

from contextlib import contextmanager

from app.integrations.ks_integration import KSCallError, KSUnavailableError
from app.models.project import ClassifiedEntity, ClassifiedField, ProjectSession
from app.services.assist_service import AssistService
from app.services.ks_workspace import ensure_workspace_identity, mark_workspace_active


def test_assist_service_off_returns_no_badge_and_does_not_call_ks(monkeypatch):
    session = ProjectSession()
    service = AssistService()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when Knowledge Assist is off")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    assert service.get_field_suggestion_badge(session, entity="Account") is None
    assert service.get_validation_hint_badge(session, entity="Account") is None
    assert service.get_identity_role_suggestion_badge(session, entity="Account") is None
    assert service.get_rule_suggestion_badge(session, entity="Account") is None
    assert service.get_mapping_suggestion_badge(session, route_name="routePayment") is None
    assert service.fetch_suggestion_drawer(session, scope="validations", entity="Account").empty is True
    assert session.project_id is None
    assert session.ks_project_id is None
    assert session.ks_active is False


def test_step3_field_review_context_requires_assist_crud_and_selection():
    session = ProjectSession()
    service = AssistService()

    off_context = service.get_step3_field_review_context(
        session,
        selected_entities=["Account"],
    )
    assert off_context.enabled is False
    assert off_context.rail_default == "collapsed"

    session.capabilities.knowledge_assist_enabled = True
    inactive_context = service.get_step3_field_review_context(
        session,
        selected_entities=["Account"],
    )
    assert inactive_context.enabled is False
    assert inactive_context.rail_default == "collapsed"

    ensure_workspace_identity(session)
    mark_workspace_active(session)
    on_context = service.get_step3_field_review_context(
        session,
        selected_entities=["Account"],
    )
    assert on_context.enabled is True
    assert on_context.rail_default == "expanded"

    no_selection_context = service.get_step3_field_review_context(
        session,
        selected_entities=[],
    )
    assert no_selection_context.enabled is False


def test_assist_service_on_lazily_mints_workspace_and_marks_active(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()

    calls: list[tuple[str, str]] = []

    class FakeClient:
        def read_field_catalog(self, project_id: str, entity: str):
            return {"fields": [{"field_name": "account_id"}], "warnings": []}

        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            calls.append(("suggest_manifest_candidates", scope))
            return {
                "tool_name": "suggest_manifest_candidates",
                "scope": scope,
                "suggestions": [{"suggestion_id": "s-1", "field_name": "account_id"}],
                "suggestion_count": 1,
                "warnings": [],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    badge = service.get_field_suggestion_badge(session, entity="Account")

    assert badge is not None
    assert badge.entity == "Account"
    assert badge.suggestion_count == 1
    assert calls == [("suggest_manifest_candidates", "fields")]
    assert session.project_id == session.ks_project_id
    assert session.ks_active is True


def test_assist_service_wizard_failures_return_none(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()

    @contextmanager
    def unavailable_ks_client(**kwargs):
        raise KSUnavailableError("mock unavailable")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", unavailable_ks_client)

    assert service.get_field_suggestion_badge(session, entity="Account") is None

    @contextmanager
    def failing_ks_client(**kwargs):
        class FakeClient:
            def read_field_catalog(self, project_id: str, entity: str):
                raise KSCallError("read_field_catalog", "mock failure")

        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", failing_ks_client)

    assert service.fetch_field_suggestions(session, entity="Account") is None


def test_s8_badges_return_none_for_zero_suggestions(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()
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
            return {"scope": scope, "suggestions": [], "suggestion_count": 0}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    assert service.get_validation_hint_badge(session, entity="Account") is None
    assert service.get_identity_role_suggestion_badge(session, entity="Account") is None
    assert service.get_rule_suggestion_badge(session, entity="Account") is None
    assert calls == ["validations", "identity_role", "rules", "cross_entity_rules"]


def test_mapping_badge_returns_none_for_zero_suggestions(monkeypatch):
    session = ProjectSession()
    session.app_archetype = "passthrough-router"
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()
    calls: list[tuple[str, str | None, str | None, str | None, str | None, str | None]] = []

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            route_name: str | None = None,
            target_id: str | None = None,
            direction: str | None = None,
            source_entity: str | None = None,
            target_entity: str | None = None,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            calls.append((scope, route_name, target_id, direction, source_entity, target_entity))
            return {"scope": scope, "suggestions": [], "suggestion_count": 0}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    assert service.get_mapping_suggestion_badge(
        session,
        route_name="routePayment",
        direction="request",
        source_entity="InternalPaymentRequest",
        target_entity="SctPaymentRequest",
    ) is None
    assert calls == [
        (
            "mappings",
            "routePayment",
            None,
            "request",
            "InternalPaymentRequest",
            "SctPaymentRequest",
        )
    ]


def test_s8_badges_call_generic_scopes_when_enabled(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()
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
            return {
                "scope": scope,
                "suggestions": [{"suggestion_id": f"{scope}-1", "field_name": "status"}],
                "suggestion_count": 1,
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    validation_badge = service.get_validation_hint_badge(session, entity="Account")
    identity_badge = service.get_identity_role_suggestion_badge(session, entity="Account")
    rule_badge = service.get_rule_suggestion_badge(session, entity="Account")

    assert validation_badge is not None
    assert validation_badge.scope == "validations"
    assert validation_badge.label == "1 validation hint"
    assert identity_badge is not None
    assert identity_badge.scope == "identity_role"
    assert identity_badge.label == "1 identity role suggestion"
    assert rule_badge is not None
    assert rule_badge.scope == "rules"
    assert rule_badge.count == 2
    assert rule_badge.label == "2 rule suggestions"
    assert calls == ["validations", "identity_role", "rules", "cross_entity_rules"]


def test_identity_role_drawer_normalizes_role_payload(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()

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
                "scope": scope,
                "suggestions": [
                    {
                        "suggestion_id": "id-1",
                        "suggestion_type": "identity_role",
                        "entity": "Account",
                        "field": "accountId",
                        "suggested_role": "persistence_id",
                        "summary": "Account id is the persistence row identity.",
                        "confidence": 0.91,
                        "source_document_names": ["field-catalog.csv"],
                        "citation_count": 1,
                    }
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    drawer = service.fetch_suggestion_drawer(session, scope="identity_role", entity="Account")

    assert drawer is not None
    assert drawer.title == "Identity Role Suggestions"
    assert drawer.empty is False
    row = drawer.scopes[0].rows[0]
    assert row.suggestion_type == "identity_role"
    assert row.title == "Account id is the persistence row identity."
    assert row.payload["entity"] == "Account"
    assert row.payload["field"] == "accountId"
    assert row.payload["suggested_role"] == "persistence_id"
    assert row.payload["suggestion_semantics"]["category"] == "Applies generated change"
    assert row.has_evidence is True


def test_s8_drawer_fetch_normalizes_validation_rows(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()

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
            return {
                "scope": scope,
                "suggestions": [
                    {
                        "suggestion_id": "v-1",
                        "suggestion_type": "validation",
                        "field_name": "status",
                        "summary": "Status should be constrained.",
                        "confidence": 0.82,
                        "manifest_path": "entities.Account.fields.status.validations",
                        "citation_count": 2,
                    }
                ],
            }

        def get_suggestion_evidence_chain(
            self,
            project_id: str,
            scope: str,
            suggestion_id: str,
        ):
            return {"evidence_chunks": []}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    drawer = service.fetch_suggestion_drawer(session, scope="validations", entity="Account")

    assert drawer is not None
    assert drawer.empty is False
    row = drawer.scopes[0].rows[0]
    assert row.suggestion_id == "v-1"
    assert row.title == "Status should be constrained."
    assert row.confidence == 0.82
    assert row.citation_count == 2
    assert row.has_evidence is True


def test_s8_drawer_row_id_alone_does_not_imply_evidence(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()

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
                "scope": scope,
                "suggestions": [
                    {
                        "suggestion_id": "v-without-evidence",
                        "suggestion_type": "validation",
                        "field_name": "status",
                        "summary": "Status should be constrained.",
                    }
                ],
            }

        def get_suggestion_evidence_chain(
            self,
            project_id: str,
            scope: str,
            suggestion_id: str,
        ):
            return {"evidence_chunks": []}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    drawer = service.fetch_suggestion_drawer(session, scope="validations", entity="Account")

    assert drawer is not None
    row = drawer.scopes[0].rows[0]
    assert row.suggestion_id == "v-without-evidence"
    assert row.citation_count == 0
    assert row.has_evidence is False


def test_s8_drawer_row_has_evidence_when_snippets_exist(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()

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
                "scope": scope,
                "suggestions": [
                    {
                        "suggestion_id": "v-with-snippet",
                        "suggestion_type": "validation",
                        "field_name": "status",
                        "summary": "Status should be constrained.",
                        "snippet": "Status is ACTIVE or DORMANT.",
                    }
                ],
            }

        def get_suggestion_evidence_chain(
            self,
            project_id: str,
            scope: str,
            suggestion_id: str,
        ):
            return {"evidence_chunks": []}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    drawer = service.fetch_suggestion_drawer(session, scope="validations", entity="Account")

    assert drawer is not None
    assert drawer.scopes[0].rows[0].has_evidence is True


def test_s8_drawer_fetch_normalizes_rule_rows(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            assert scope == "cross_entity_rules"
            return {
                "scope": scope,
                "suggestions": [
                    {
                        "suggestion_id": "x-1",
                        "rule_type": "cross-entity-field-check",
                        "field": "customerId",
                        "rationale": "Customer status gates account creation.",
                        "source_count": 3,
                    }
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    drawer = service.fetch_suggestion_drawer(
        session,
        scope="cross_entity_rules",
        entity="Account",
    )

    assert drawer is not None
    assert drawer.title == "Cross-Entity Rule Suggestions"
    row = drawer.scopes[0].rows[0]
    assert row.title == "cross-entity-field-check on customerId"
    assert row.summary == "Customer status gates account creation."
    assert row.citation_count == 3


def test_s8_drawer_fetch_normalizes_mapping_rows(monkeypatch):
    session = ProjectSession()
    session.app_archetype = "kafka-integration"
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()
    calls: list[tuple[str, str | None, str | None, str | None, str | None, str | None]] = []

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            route_name: str | None = None,
            target_id: str | None = None,
            direction: str | None = None,
            source_entity: str | None = None,
            target_entity: str | None = None,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            calls.append((scope, route_name, target_id, direction, source_entity, target_entity))
            return {
                "scope": scope,
                "suggestions": [
                    {
                        "suggestion_id": "m-1",
                        "suggestion_type": "mapping",
                        "payload": {
                            "source_field": "paymentId",
                            "target_field": "ledgerId",
                        },
                        "summary": "Payment id maps to ledger id.",
                        "confidence_basis": "Matched by field catalog name and compatible type.",
                        "confidence": 0.77,
                        "manifest_path": "async_routes.payment-posted.transform_mapping",
                        "citation_count": 1,
                    }
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    mapping_context = {
        "route_name": "payment-posted",
        "direction": "request",
        "source_entity": "PaymentPosted",
        "target_entity": "LedgerEntry",
    }
    badge = service.get_mapping_suggestion_badge(
        session,
        route_name="payment-posted",
        contexts=[mapping_context],
    )
    drawer = service.fetch_mapping_suggestion_drawer(
        session,
        route_name="payment-posted",
        contexts=[mapping_context],
    )

    assert badge is not None
    assert badge.label == "1 mapping suggestion"
    assert drawer is not None
    assert drawer.title == "Mapping Suggestions"
    row = drawer.scopes[0].rows[0]
    assert row.suggestion_type == "mapping"
    assert row.title == "paymentId → ledgerId"
    assert row.confidence == 0.77
    assert row.payload["confidence_basis"] == "Matched by field catalog name and compatible type."
    assert row.payload["route_name"] == "payment-posted"
    assert row.payload["direction"] == "request"
    assert row.payload["source_entity"] == "PaymentPosted"
    assert row.payload["target_entity"] == "LedgerEntry"
    assert calls == [
        ("mappings", "payment-posted", None, "request", "PaymentPosted", "LedgerEntry"),
        ("mappings", "payment-posted", None, "request", "PaymentPosted", "LedgerEntry"),
    ]


def test_s8_transform_badge_and_drawer_use_router_context(monkeypatch):
    session = ProjectSession()
    session.app_archetype = "kafka-integration"
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()
    calls: list[tuple[str, str | None, str | None, str | None, str | None, str | None]] = []
    evidence_calls: list[tuple[str, str]] = []

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            route_name: str | None = None,
            target_id: str | None = None,
            direction: str | None = None,
            source_entity: str | None = None,
            target_entity: str | None = None,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            calls.append((scope, route_name, target_id, direction, source_entity, target_entity))
            return {
                "scope": scope,
                "suggestions": [
                    {
                        "suggestion_id": "t-1",
                        "suggestion_type": "transform",
                        "payload": {
                            "source": "paymentId",
                            "target": "transactionId",
                            "type_coercion": "major_to_minor_units",
                        },
                        "summary": "Router request should map payment id to transaction id.",
                        "confidence": 0.82,
                        "manifest_path": "async_routes.payment-posted.router_config.targets.ledger-core.request_transform",
                    },
                    {
                        "suggestion_id": "t-1",
                        "suggestion_type": "transform",
                        "payload": {"source": "paymentId", "target": "transactionId"},
                    },
                ],
            }

        def get_suggestion_evidence_chain(
            self,
            project_id: str,
            scope: str,
            suggestion_id: str,
        ):
            evidence_calls.append((scope, suggestion_id))
            return {
                "evidence_chunks": [
                    {
                        "citation": {"document_id": "doc-1"},
                        "snippet": "Payment id is the downstream transaction id.",
                    }
                ]
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    transform_context = {
        "route_name": "payment-posted",
        "target_id": "ledger-core",
        "direction": "request",
        "source_entity": "payment-posted-upstream",
        "target_entity": "payment-posted-downstream",
    }
    badge = service.get_transform_suggestion_badge(
        session,
        route_name="payment-posted",
        target_id="ledger-core",
        direction="request",
        contexts=[transform_context],
    )
    drawer = service.fetch_transform_suggestion_drawer(
        session,
        route_name="payment-posted",
        target_id="ledger-core",
        direction="request",
        contexts=[transform_context],
    )

    assert badge is not None
    assert badge.label == "1 request transform suggestion"
    assert drawer is not None
    assert drawer.title == "Transform Suggestions"
    assert drawer.empty is False
    assert len(drawer.scopes[0].rows) == 1
    row = drawer.scopes[0].rows[0]
    assert row.suggestion_type == "transform"
    assert row.title == "paymentId → transactionId"
    assert row.payload["route_name"] == "payment-posted"
    assert row.payload["target_id"] == "ledger-core"
    assert row.payload["direction"] == "request"
    assert row.payload["source_entity"] == "payment-posted-upstream"
    assert row.payload["target_entity"] == "payment-posted-downstream"
    assert row.citation_count == 1
    assert "Payment id is the downstream transaction id." in row.payload["snippets"]
    assert calls == [
        ("transforms", "payment-posted", "ledger-core", "request", "payment-posted-upstream", "payment-posted-downstream"),
        ("transforms", "payment-posted", "ledger-core", "request", "payment-posted-upstream", "payment-posted-downstream"),
    ]
    assert evidence_calls == [("transforms", "t-1")]


def test_rule_empty_diagnostic_uses_user_facing_copy():
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    session.selected_entity_names = ["AccountResponse"]
    session.classified_entities = [
        ClassifiedEntity(
            name="AccountResponse",
            canonical_name="Account",
            classification="entity",
            fields=[ClassifiedField(name="status", type="string")],
        )
    ]
    service = AssistService()

    message = service._rule_empty_diagnostic(session, "Account", ("rules", "cross_entity_rules"))

    assert "No rule suggestions are currently available for Account." in message
    assert "Knowledge Workspace" in message
    assert "Scopes:" not in message
    assert "Knowledge Assist enabled:" not in message


def test_transform_summary_copy_does_not_mention_later_pr(monkeypatch):
    session = ProjectSession()
    session.app_archetype = "kafka-integration"
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            route_name: str | None = None,
            target_id: str | None = None,
            direction: str | None = None,
            source_entity: str | None = None,
            target_entity: str | None = None,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            return {
                "scope": scope,
                "suggestions": [
                    {
                        "suggestion_id": "t-copy",
                        "suggestion_type": "transform",
                        "payload": {"source": "amount", "target": "amountMinor"},
                    }
                ],
            }

        def get_suggestion_evidence_chain(
            self,
            project_id: str,
            scope: str,
            suggestion_id: str,
        ):
            return {"evidence_chunks": []}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    drawer = service.fetch_transform_suggestion_drawer(
        session,
        route_name="payments",
        target_id="core",
        direction="request",
        source_entity="PaymentRequest",
        target_entity="CorePaymentRequest",
    )

    assert drawer is not None
    summary = drawer.scopes[0].rows[0].summary or ""
    assert "no changes are applied until you accept or edit this suggestion" in summary
    assert "later action PR" not in summary


def test_transform_empty_diagnostics_use_user_facing_context_label():
    service = AssistService()

    warnings = service._transform_empty_diagnostics(
        [
            {
                "route_name": "payment-posted",
                "target_id": "ledger-core",
                "direction": "request",
                "source_entity": "PaymentPosted",
                "target_entity": "LedgerEntry",
            }
        ]
    )

    assert warnings == [
        "No actionable Kafka transform suggestions are currently available for "
        "payment-posted target ledger-core request transform (PaymentPosted -> LedgerEntry)."
    ]
    assert "route=" not in warnings[0]
    assert "target_id=" not in warnings[0]
    assert "source_entity=" not in warnings[0]
    assert "target_entity=" not in warnings[0]


def test_s8_transform_context_failure_is_quiet(monkeypatch):
    session = ProjectSession()
    session.app_archetype = "kafka-integration"
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("incomplete router transform context should not call KS")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    assert service.get_transform_suggestion_badge(
        session,
        route_name="payment-posted",
        target_id="ledger-core",
        direction="request",
        contexts=[
            {
                "route_name": "payment-posted",
                "target_id": "ledger-core",
                "direction": "request",
                "source_entity": "",
                "target_entity": "payment-posted-downstream",
            }
        ],
    ) is None
    drawer = service.fetch_transform_suggestion_drawer(
        session,
        route_name="payment-posted",
        target_id="ledger-core",
        direction="request",
        contexts=[],
    )
    assert drawer is not None
    assert drawer.empty is True
    assert session.ks_active is False


def test_s8_combined_rule_drawer_includes_cross_entity_only_rows(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()
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
            if scope == "rules":
                return {"scope": scope, "suggestions": [], "suggestion_count": 0}
            return {
                "scope": scope,
                "suggestions": [
                    {
                        "suggestion_id": "x-1",
                        "rule_type": "cross-entity-field-check",
                        "field": "customerId",
                    }
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    drawer = service.fetch_rule_suggestion_drawer(session, entity="Account")

    assert drawer is not None
    assert drawer.empty is False
    assert calls == ["rules", "cross_entity_rules"]
    assert len(drawer.scopes) == 1
    assert drawer.scopes[0].scope == "cross_entity_rules"
    assert drawer.scopes[0].rows[0].title == "cross-entity-field-check on customerId"


def test_assist_service_evidence_off_returns_none_and_does_not_mint(monkeypatch):
    session = ProjectSession()
    service = AssistService()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when Knowledge Assist is off")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    assert service.get_field_evidence_chain(session, entity="Account", field_name="account_id") is None
    assert session.project_id is None
    assert session.ks_active is False


def test_rule_suggestion_decision_submit_off_returns_none_without_ks_call(monkeypatch):
    session = ProjectSession()
    service = AssistService()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when Knowledge Assist is off")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    result = service.submit_rule_suggestion_decisions(
        session,
        decisions=[{"suggestion_id": "r-1", "status": "accepted"}],
    )

    assert result is None
    assert session.project_id is None
    assert session.ks_active is False


def test_rule_suggestion_decision_submit_on_uses_service_guard(monkeypatch):
    session = ProjectSession()
    session.app_archetype = "crud"
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()
    submitted: list[tuple[str, list[dict]]] = []

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            submitted.append((project_id, decisions))
            return {"success": True, "outcomes": [{"suggestion_id": "r-1", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    result = service.submit_rule_suggestion_decisions(
        session,
        decisions=[{"suggestion_id": "r-1", "status": "accepted"}],
    )

    assert result == {"success": True, "outcomes": [{"suggestion_id": "r-1", "success": True}]}
    assert submitted == [(session.project_id, [{"suggestion_id": "r-1", "status": "accepted"}])]
    assert session.project_id
    assert session.ks_project_id == session.project_id
    assert session.ks_active is True


def test_rule_suggestion_decision_submit_failure_is_quiet(monkeypatch):
    session = ProjectSession()
    session.app_archetype = "crud"
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise KSCallError("submit_suggestion_decisions", "mock failure")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    result = service.submit_rule_suggestion_decisions(
        session,
        decisions=[{"suggestion_id": "r-1", "status": "accepted"}],
    )

    assert result is None
    assert session.ks_active is False


def test_validation_suggestion_decision_submit_uses_service_guard(monkeypatch):
    session = ProjectSession()
    session.app_archetype = "crud"
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()
    submitted: list[tuple[str, list[dict]]] = []

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            submitted.append((project_id, decisions))
            return {"success": True, "outcomes": [{"suggestion_id": "v-1", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    result = service.submit_validation_suggestion_decisions(
        session,
        decisions=[{"suggestion_id": "v-1", "status": "accepted"}],
    )

    assert result == {"success": True, "outcomes": [{"suggestion_id": "v-1", "success": True}]}
    assert submitted == [(session.project_id, [{"suggestion_id": "v-1", "status": "accepted"}])]
    assert session.project_id
    assert session.ks_active is True


def test_validation_suggestion_decision_submit_off_returns_none_without_ks_call(monkeypatch):
    session = ProjectSession()
    service = AssistService()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when Knowledge Assist is off")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    result = service.submit_validation_suggestion_decisions(
        session,
        decisions=[{"suggestion_id": "v-1", "status": "accepted"}],
    )

    assert result is None
    assert session.project_id is None
    assert session.ks_active is False


def test_mapping_suggestion_decision_submit_uses_service_guard(monkeypatch):
    session = ProjectSession()
    session.app_archetype = "passthrough-router"
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()
    submitted: list[tuple[str, list[dict]]] = []

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            submitted.append((project_id, decisions))
            return {"success": True, "outcomes": [{"suggestion_id": "m-1", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    result = service.submit_mapping_suggestion_decisions(
        session,
        decisions=[{"suggestion_id": "m-1", "status": "accepted"}],
    )

    assert result == {"success": True, "outcomes": [{"suggestion_id": "m-1", "success": True}]}
    assert submitted == [(session.project_id, [{"suggestion_id": "m-1", "status": "accepted"}])]
    assert session.project_id
    assert session.ks_active is True


def test_mapping_suggestion_decision_submit_off_returns_none_without_ks_call(monkeypatch):
    session = ProjectSession()
    session.app_archetype = "passthrough-router"
    service = AssistService()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when Knowledge Assist is off")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    result = service.submit_mapping_suggestion_decisions(
        session,
        decisions=[{"suggestion_id": "m-1", "status": "accepted"}],
    )

    assert result is None
    assert session.project_id is None
    assert session.ks_active is False


def test_mapping_suggestion_decision_submit_failure_is_quiet(monkeypatch):
    session = ProjectSession()
    session.app_archetype = "kafka-integration"
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise KSCallError("submit_suggestion_decisions", "mock failure")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    result = service.submit_mapping_suggestion_decisions(
        session,
        decisions=[{"suggestion_id": "m-1", "status": "accepted"}],
    )

    assert result is None
    assert session.ks_active is False


def test_transform_suggestion_decision_submit_uses_generic_path(monkeypatch):
    session = ProjectSession()
    session.app_archetype = "kafka-integration"
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()
    submitted: list[tuple[str, list[dict]]] = []

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            submitted.append((project_id, decisions))
            return {"success": True, "outcomes": [{"suggestion_id": "t-1", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    result = service.submit_transform_suggestion_decisions(
        session,
        decisions=[
            {
                "suggestion_id": "t-1",
                "status": "edited",
                "edited_payload": {"source": "amount", "target": "amountMinor"},
            }
        ],
    )

    assert result == {"success": True, "outcomes": [{"suggestion_id": "t-1", "success": True}]}
    assert submitted == [
        (
            session.project_id,
            [
                {
                    "suggestion_id": "t-1",
                    "status": "edited",
                    "edited_payload": {"source": "amount", "target": "amountMinor"},
                }
            ],
        )
    ]
    assert session.project_id
    assert session.ks_active is True


def test_transform_suggestion_decision_submit_off_returns_none_without_ks_call(monkeypatch):
    session = ProjectSession()
    session.app_archetype = "kafka-integration"
    service = AssistService()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when Knowledge Assist is off")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    result = service.submit_transform_suggestion_decisions(
        session,
        decisions=[{"suggestion_id": "t-1", "status": "accepted"}],
    )

    assert result is None
    assert session.project_id is None
    assert session.ks_active is False


def test_transform_suggestion_decision_submit_failure_is_quiet(monkeypatch):
    session = ProjectSession()
    session.app_archetype = "kafka-integration"
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise KSCallError("submit_suggestion_decisions", "mock failure")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    result = service.submit_transform_suggestion_decisions(
        session,
        decisions=[{"suggestion_id": "t-1", "status": "accepted"}],
    )

    assert result is None
    assert session.ks_active is False


def test_conflict_resolution_decisions_submit_through_generic_path(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()
    submitted: list[tuple[str, list[dict]]] = []

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            submitted.append((project_id, decisions))
            return {"success": True, "outcomes": [{"suggestion_id": "c-1", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    result = service.submit_conflict_resolution_decisions(
        session,
        decisions=[
            {
                "suggestion_id": "c-1",
                "status": "edited",
                "edited_payload": {
                    "resolution_note": "Prefer the BRD statement.",
                    "preferred_document_id": "brd-1",
                },
            }
        ],
    )

    assert result == {"success": True, "outcomes": [{"suggestion_id": "c-1", "success": True}]}
    assert submitted == [
        (
            session.project_id,
            [
                {
                    "suggestion_id": "c-1",
                    "status": "edited",
                    "edited_payload": {
                        "resolution_note": "Prefer the BRD statement.",
                        "preferred_document_id": "brd-1",
                    },
                }
            ],
        )
    ]
    assert session.ks_active is True


def test_conflict_resolution_decision_submit_failure_is_quiet(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise KSCallError("submit_suggestion_decisions", "mock failure")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    result = service.submit_conflict_resolution_decisions(
        session,
        decisions=[{"suggestion_id": "c-1", "status": "accepted"}],
    )

    assert result is None
    assert session.ks_active is False


def test_conflict_resolution_badge_uses_canonical_scope_and_field_query(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()
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
                        "suggestion_id": "c-1",
                        "suggestion_type": "conflict_resolution",
                        "title": "Status conflict",
                        "summary": "Two documents disagree about status values.",
                    }
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    badge = service.get_conflict_resolution_badge(
        session,
        query_candidates=["Account.status"],
        drawer_url="/review/ks/drawer?scope=conflict_resolution",
    )

    assert badge is not None
    assert badge.scope == "conflict_resolution"
    assert badge.label == "1 conflict"
    assert calls == [("conflict_resolution", "Account.status")]
    assert session.ks_active is True


def test_conflict_resolution_badge_dedupes_suggestions(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()
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
            calls.append(field_name_pattern or "")
            return {
                "scope": scope,
                "suggestions": [
                    {"suggestion_id": "c-1", "title": f"Conflict for {field_name_pattern}"}
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    badge = service.get_conflict_resolution_badge(
        session,
        query_candidates=["Account", "Account.status", "account"],
        drawer_url="/review/ks/drawer?scope=conflict_resolution",
    )

    assert badge is not None
    assert badge.count == 1
    assert calls == ["Account", "Account.status"]


def test_conflict_resolution_drawer_includes_query_and_evidence(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()

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
                        "suggestion_id": "c-1",
                        "suggestion_type": "conflict_resolution",
                        "conflict_signal": "Status value conflict",
                        "summary": "Status differs across source documents.",
                        "document_names": ["BRD.pdf"],
                        "citations": [{"snippet": "Status must be ACTIVE."}],
                    }
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
                            "document_name": "Rules.xlsx",
                            "snippet": "Status may also be PENDING.",
                        }
                    }
                ]
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    drawer = service.fetch_conflict_resolution_drawer(
        session,
        query_candidates=["Account.status"],
    )

    assert drawer is not None
    assert drawer.empty is False
    row = drawer.scopes[0].rows[0]
    assert row.suggestion_id == "c-1"
    assert row.title == "Status value conflict"
    assert row.summary == "Status value conflict"
    assert "Status must be ACTIVE." not in row.summary
    assert row.payload["conflict_query"] == "Account.status"
    assert row.payload["document_labels"] == ["BRD.pdf", "Rules.xlsx"]
    assert row.payload["conflict_summary"] == "Status value conflict"
    assert row.payload["difference_category"] == "source alignment difference"
    assert "Status must be ACTIVE." in row.payload["snippets"]
    assert row.citation_count == 1


def test_conflict_resolution_failure_is_quiet(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise KSUnavailableError("mock unavailable")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    assert service.get_conflict_resolution_badge(
        session,
        query_candidates=["Account.status"],
        drawer_url="/review/ks/drawer?scope=conflict_resolution",
    ) is None
    drawer = service.fetch_conflict_resolution_drawer(
        session,
        query_candidates=["Account.status"],
    )
    assert drawer is not None
    assert drawer.empty is True
    assert session.ks_active is False


def test_portfolio_reuse_badge_uses_canonical_scope_and_query(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()
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
                        "suggestion_id": "p-1",
                        "suggestion_type": "portfolio_reuse",
                        "title": "Reusable account pattern",
                        "summary": "Another project modeled a similar Account flow.",
                    }
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    badge = service.get_portfolio_reuse_badge(
        session,
        query_candidates=["Account"],
        drawer_url="/review/ks/drawer?scope=portfolio_reuse",
    )

    assert badge is not None
    assert badge.scope == "portfolio_reuse"
    assert badge.label == "1 portfolio pattern"
    assert calls == [("portfolio_reuse", "Account")]
    assert session.ks_active is True


def test_portfolio_reuse_badge_dedupes_suggestions(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()
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
            calls.append(field_name_pattern or "")
            return {
                "scope": scope,
                "suggestions": [
                    {"suggestion_id": "p-1", "title": f"Pattern for {field_name_pattern}"}
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    badge = service.get_portfolio_reuse_badge(
        session,
        query_candidates=["Account", "account", "status"],
        drawer_url="/review/ks/drawer?scope=portfolio_reuse",
    )

    assert badge is not None
    assert badge.count == 1
    assert calls == ["Account", "status"]


def test_portfolio_reuse_drawer_includes_query_project_and_evidence(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()

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
                        "suggestion_id": "p-1",
                        "suggestion_type": "portfolio_reuse",
                        "title": "Reusable account pattern",
                        "summary": "Another indexed project has a similar Account pattern.",
                        "matched_project_id": "portfolio-project-1",
                        "document_name": "Account Pattern BRD.pdf",
                        "document_id": "doc-portfolio",
                        "snippet": "Account onboarding validates status before activation.",
                        "reuse_kind": "Portfolio pattern",
                    }
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
                            "snippet": "A prior payments app reused the same onboarding contract.",
                        }
                    }
                ]
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    drawer = service.fetch_portfolio_reuse_drawer(
        session,
        query_candidates=["Account"],
    )

    assert drawer is not None
    assert drawer.empty is False
    row = drawer.scopes[0].rows[0]
    assert row.suggestion_id == "p-1"
    assert row.title == "Reusable account pattern"
    assert row.payload["portfolio_query"] == "Account"
    assert row.payload["matched_project_id"] == "portfolio-project-1"
    assert "Account Pattern BRD.pdf" in row.payload["document_labels"]
    assert "doc-extra" in row.payload["document_ids"]
    assert "A prior payments app reused" in row.payload["snippets"][1]
    assert row.citation_count == 1


def test_portfolio_reuse_failure_is_quiet(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise KSUnavailableError("mock unavailable")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    assert service.get_portfolio_reuse_badge(
        session,
        query_candidates=["Account"],
        drawer_url="/review/ks/drawer?scope=portfolio_reuse",
    ) is None
    drawer = service.fetch_portfolio_reuse_drawer(
        session,
        query_candidates=["Account"],
    )
    assert drawer is not None
    assert drawer.empty is True
    assert session.ks_active is False


def test_portfolio_reuse_decisions_submit_through_generic_path(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()
    submitted: list[tuple[str, list[dict]]] = []

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            submitted.append((project_id, decisions))
            return {"success": True, "outcomes": [{"suggestion_id": "p-1", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    result = service.submit_portfolio_reuse_decisions(
        session,
        decisions=[
            {
                "suggestion_id": "p-1",
                "status": "edited",
                "edited_payload": {
                    "reuse_note": "Useful account onboarding pattern.",
                    "target_step": "Step 6",
                },
            }
        ],
    )

    assert result == {"success": True, "outcomes": [{"suggestion_id": "p-1", "success": True}]}
    assert submitted == [
        (
            session.project_id,
            [
                {
                    "suggestion_id": "p-1",
                    "status": "edited",
                    "edited_payload": {
                        "reuse_note": "Useful account onboarding pattern.",
                        "target_step": "Step 6",
                    },
                }
            ],
        )
    ]
    assert session.ks_active is True


def test_portfolio_reuse_decision_submit_failure_is_quiet(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise KSCallError("submit_suggestion_decisions", "mock failure")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    result = service.submit_portfolio_reuse_decisions(
        session,
        decisions=[{"suggestion_id": "p-1", "status": "accepted"}],
    )

    assert result is None
    assert session.ks_active is False


def test_advisory_conflicts_off_returns_empty_without_ks_call(monkeypatch):
    session = ProjectSession()
    session.ks_active = True
    service = AssistService()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when Knowledge Assist is off")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    view = service.get_advisory_conflicts(session, canonical_entities=["Account"])

    assert view["enabled"] is False
    assert view["has_items"] is False
    assert view["show_empty_state"] is False


def test_advisory_conflicts_on_returns_grouped_items(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    session.ks_active = True
    session.project_id = "workspace-123"
    session.ks_project_id = "workspace-123"
    session.selected_entity_names = ["Account"]
    session.classified_entities = [
        ClassifiedEntity(
            name="Account",
            canonical_name="Account",
            classification="entity",
            fields=[ClassifiedField(name="creditLimit", type="decimal")],
        )
    ]
    service = AssistService()

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            assert scope == "fields"
            return {
                "suggestions": [
                    {
                        "suggestion_id": "s-1",
                        "field_name": "CREDIT_LIMIT",
                        "conflict_hint": "Spec says integer, guidance says decimal.",
                    }
                ]
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    view = service.get_advisory_conflicts(session, canonical_entities=["Account"])

    assert view["enabled"] is True
    assert view["has_items"] is True
    assert view["count"] == 1
    assert view["groups"][0]["items"][0]["field_name"] == "creditLimit"


def test_assist_service_evidence_uses_generic_field_scope(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    service = AssistService()
    calls: list[tuple[str, str]] = []

    class FakeClient:
        def get_suggestion_evidence_chain(
            self,
            project_id: str,
            scope: str,
            suggestion_id: str,
        ):
            calls.append(("get_suggestion_evidence_chain", scope))
            return {
                "tool_name": "get_suggestion_evidence_chain",
                "scope": scope,
                "project_id": project_id,
                "suggestion_id": suggestion_id,
                "entity": "Account",
                "field_name": "account_id",
                "suggestion": None,
                "definitions": [],
                "evidence_chunks": [],
                "warnings": [],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    result = service.get_field_evidence_chain(
        session,
        entity="Account",
        field_name="account_id",
        suggestion_id="s-1",
    )

    assert result is not None
    assert result["tool_name"] == "get_suggestion_evidence_chain"
    assert result["scope"] == "fields"
    assert result["suggestion_id"] == "s-1"
    assert calls == [("get_suggestion_evidence_chain", "fields")]


def test_advisory_conflicts_failure_is_quiet(monkeypatch):
    session = ProjectSession()
    session.capabilities.knowledge_assist_enabled = True
    session.ks_active = True
    session.project_id = "workspace-123"
    session.ks_project_id = "workspace-123"
    service = AssistService()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise KSUnavailableError("mock unavailable")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    view = service.get_advisory_conflicts(session, canonical_entities=["Account"])

    assert view["enabled"] is True
    assert view["degraded"] is False
    assert view["has_items"] is False


def test_ensure_workspace_identity_no_longer_sets_ks_active():
    session = ProjectSession()

    workspace_id = ensure_workspace_identity(session)

    assert workspace_id
    assert session.project_id == workspace_id
    assert session.ks_project_id == workspace_id
    assert session.ks_active is False


def test_mark_workspace_active_respects_capability_flag():
    session = ProjectSession()

    mark_workspace_active(session)

    assert session.ks_active is False
    assert session.capabilities.knowledge_assist_enabled is False

    session.capabilities.knowledge_assist_enabled = True
    mark_workspace_active(session)

    assert session.ks_active is True
