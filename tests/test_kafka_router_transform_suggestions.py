"""Tests for read-only Kafka router transform suggestions."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from app.integrations.ks_integration import KSUnavailableError
from app.main import app
from app.models.project import (
    KafkaRouterTargetTransform,
    KafkaRouterTransformRow,
    KafkaRouteTransform,
)
from tests.session_helpers import get_session, reset_session, save_session
from tests.test_kafka_studio import _seed_route_models, _seed_router_route_model

client = TestClient(app)


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def test_router_transform_drawer_uses_generated_change_taxonomy() -> None:
    js = Path("app/static/js/studio.js").read_text(encoding="utf-8")

    assert "Applies generated change" in js
    assert "ka-category-generated ka-taxonomy-change" in js
    assert "'transforms'" in js


def _enable_assist() -> None:
    session = get_session()
    session.capabilities.knowledge_assist_enabled = True
    save_session(session)


def test_router_transform_badges_off_do_not_call_ks(monkeypatch) -> None:
    _seed_router_route_model()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when Knowledge Assist is off")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/kafka/transforms")

    assert response.status_code == 200
    assert "transform suggestion" not in response.text
    assert get_session().ks_active is False


def test_router_transform_badges_not_rendered_for_zero_suggestions(monkeypatch) -> None:
    _seed_router_route_model()
    _enable_assist()
    calls: list[tuple[str, str, str | None]] = []

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
            calls.append((scope, direction or "", target_id))
            return {"scope": scope, "suggestions": [], "suggestion_count": 0}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/kafka/transforms")

    assert response.status_code == 200
    assert ("transforms", "request", "ledger-core") in calls
    assert ("transforms", "response", "ledger-core") in calls
    assert "transform suggestion" not in response.text


def test_router_transform_fetch_failure_is_silent(monkeypatch) -> None:
    _seed_router_route_model()
    _enable_assist()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise KSUnavailableError("mock unavailable")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/kafka/transforms")

    assert response.status_code == 200
    assert "transform suggestion" not in response.text
    assert "unavailable" not in response.text.lower()


def test_router_request_and_response_transform_badges_render(monkeypatch) -> None:
    _seed_router_route_model()
    _enable_assist()

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
                        "suggestion_id": f"t-{direction}",
                        "suggestion_type": "transform",
                        "payload": {
                            "route_name": route_name,
                            "target_id": target_id,
                            "direction": direction,
                            "source": "paymentId" if direction == "request" else "approved",
                            "target": "transactionId" if direction == "request" else "verified",
                        },
                    }
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/kafka/transforms")

    assert response.status_code == 200
    assert "1 request transform suggestion" in response.text
    assert "1 response transform suggestion" in response.text
    assert "scope=transforms\\u0026route_name=payment-posted" in response.text
    assert "target_id=ledger-core" in response.text


def _transform_decision(
    suggestion_id: str,
    status: str,
    *,
    route_name: str = "payment-posted",
    target_id: str = "ledger-core",
    direction: str = "request",
    source: str = "paymentId",
    target: str = "transactionId",
    edited_payload: dict | None = None,
    value_map=None,
    type_coercion: str | None = None,
    constant: str | None = None,
    default_value: str | None = None,
) -> dict:
    payload = {
        "route_name": route_name,
        "target_id": target_id,
        "direction": direction,
        "source_entity": "payment-posted-upstream" if direction == "request" else "payment-posted-target-response",
        "target_entity": "payment-posted-downstream" if direction == "request" else "payment-posted-outbound",
        "source": source,
        "target": target,
    }
    if value_map is not None:
        payload["value_map"] = value_map
    if type_coercion is not None:
        payload["type_coercion"] = type_coercion
    if default_value is not None:
        payload["default_value"] = default_value
    if constant is not None:
        payload["constant"] = constant
        payload["source"] = source
    decision = {
        "suggestion_id": suggestion_id,
        "suggestion_type": "transform",
        "status": status,
        "manifest_path": f"async_routes.{route_name}.router_config.targets.{target_id}.{direction}_transform",
        "payload": payload,
    }
    if edited_payload is not None:
        decision["edited_payload"] = edited_payload
    return decision


def _submit_success(monkeypatch, failed_ids: set[str] | None = None) -> list[list[dict]]:
    calls: list[list[dict]] = []
    failed_ids = failed_ids or set()

    def fake_submit(session, *, decisions: list[dict]):
        calls.append(decisions)
        return {
            "success": True,
            "outcomes": [
                {
                    "suggestion_id": decision["suggestion_id"],
                    "success": decision["suggestion_id"] not in failed_ids,
                }
                for decision in decisions
            ],
        }

    monkeypatch.setattr(
        "app.routes.kafka.assist_service.submit_transform_suggestion_decisions",
        fake_submit,
    )
    return calls


def test_router_transform_drawer_returns_actionable_rows_with_evidence(monkeypatch) -> None:
    _seed_router_route_model()
    _enable_assist()
    session = get_session()
    session.kafka_route_transforms = [
        KafkaRouteTransform(
            route_name="payment-posted",
            router_target_transforms=[
                KafkaRouterTargetTransform(
                    target_id="ledger-core",
                    request_transform_rows=[
                        KafkaRouterTransformRow(source="existing", target="existingTarget")
                    ],
                )
            ],
        )
    ]
    save_session(session)

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
                        "suggestion_id": "t-1",
                        "suggestion_type": "transform",
                        "payload": {
                            "target_id": target_id,
                            "source": "paymentId",
                            "target": "transactionId",
                            "default_value": "UNKNOWN",
                            "value_map": {"APPROVED": "A"},
                        },
                        "manifest_path": "async_routes.payment-posted.router_config.targets.ledger-core.request_transform",
                        "citation_count": 1,
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
            assert scope == "transforms"
            return {"evidence_chunks": [{"snippet": "Router request maps paymentId."}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get(
        "/kafka/ks/drawer",
        params={
            "scope": "transforms",
            "route_name": "payment-posted",
            "target_id": "ledger-core",
            "direction": "request",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["scope"] == "transforms"
    assert payload["review_url"] == "/kafka/ks/transform-review"
    assert payload["route_name"] == "payment-posted"
    assert payload["target_id"] == "ledger-core"
    assert payload["direction"] == "request"
    rows = payload["scopes"][0]["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["suggestion_id"] == "t-1"
    assert row["title"] == "paymentId → transactionId"
    assert row["payload"]["route_name"] == "payment-posted"
    assert row["payload"]["target_id"] == "ledger-core"
    assert row["payload"]["direction"] == "request"
    assert row["payload"]["source"] == "paymentId"
    assert row["payload"]["target"] == "transactionId"
    assert row["payload"]["default_value"] == "UNKNOWN"
    assert row["payload"]["value_map"] == {"APPROVED": "A"}
    assert row["manifest_path"].endswith("request_transform")
    assert row["citation_count"] == 1
    assert "Router request maps paymentId." in row["payload"]["snippets"]
    assert get_session().kafka_route_transforms == session.kafka_route_transforms


def test_router_transform_empty_drawer_surfaces_context_warnings(monkeypatch) -> None:
    _seed_router_route_model()
    _enable_assist()

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
                "suggestions": [],
                "suggestion_count": 0,
                "warnings": ["No persisted transform candidates matched this context."],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get(
        "/kafka/ks/drawer",
        params={
            "scope": "transforms",
            "route_name": "payment-posted",
            "target_id": "ledger-core",
            "direction": "request",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["empty"] is True
    assert payload["scopes"] == []
    assert len(payload["warnings"]) == 1
    warning = payload["warnings"][0]
    assert "No persisted transform candidates matched this context." in warning
    assert "payment-posted target ledger-core request transform" in warning
    assert "payment-posted-upstream -> payment-posted-downstream" in warning
    assert "route=" not in warning
    assert "target_id=" not in warning
    assert "direction=" not in warning
    assert get_session().kafka_route_transforms == []


def test_router_transform_review_accepts_request_row(monkeypatch) -> None:
    _seed_router_route_model()
    _enable_assist()
    calls = _submit_success(monkeypatch)

    response = client.post(
        "/kafka/ks/transform-review",
        json={"decisions": [_transform_decision("t-request", "accepted")]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["applied_count"] == 1
    assert payload["refresh"] is True
    assert calls[0] == [{"suggestion_id": "t-request", "status": "accepted"}]
    session = get_session()
    target = session.kafka_route_transforms[0].router_target_transforms[0]
    assert target.request_transform_rows[0] == KafkaRouterTransformRow(
        source="paymentId",
        target="transactionId",
    )
    assert session.ks_workspace_state.suggestion_review_state.accepted_ids == ["t-request"]
    assert session.ks_workspace_state.review_history[-1].type == "transform"
    assert session.ks_workspace_state.review_history[-1].manifest_path.endswith("request_transform.paymentId.transactionId")
    assert session.ks_workspace_state.evidence_links == []


def test_router_transform_review_accepts_response_row(monkeypatch) -> None:
    _seed_router_route_model()
    _enable_assist()
    _submit_success(monkeypatch)

    response = client.post(
        "/kafka/ks/transform-review",
        json={
            "decisions": [
                _transform_decision(
                    "t-response",
                    "accepted",
                    direction="response",
                    source="approved",
                    target="verified",
                )
            ]
        },
    )

    assert response.status_code == 200
    target = get_session().kafka_route_transforms[0].router_target_transforms[0]
    assert target.response_transform_rows[0] == KafkaRouterTransformRow(
        source="approved",
        target="verified",
    )


def test_router_transform_review_edit_applies_edited_fields(monkeypatch) -> None:
    _seed_router_route_model()
    _enable_assist()
    calls = _submit_success(monkeypatch)

    response = client.post(
        "/kafka/ks/transform-review",
        json={
            "decisions": [
                _transform_decision(
                    "t-edit",
                    "edited",
                    edited_payload={
                        "route_name": "payment-posted",
                        "target_id": "ledger-core",
                        "direction": "request",
                        "source_entity": "payment-posted-upstream",
                        "target_entity": "payment-posted-downstream",
                        "source": "amount",
                        "target": "amountMinor",
                        "type_coercion": "major_to_minor_units",
                        "value_map": {"USD": "840"},
                        "snippets": ["display-only metadata from drawer"],
                    },
                )
            ]
        },
    )

    assert response.status_code == 200
    target = get_session().kafka_route_transforms[0].router_target_transforms[0]
    assert target.request_transform_rows[0] == KafkaRouterTransformRow(
        source="amount",
        target="amountMinor",
        value_map={"USD": "840"},
        type_coercion="major_to_minor_units",
    )
    assert calls[0][0]["edited_payload"] == {
        "target": "amountMinor",
        "source": "amount",
        "value_map": {"USD": "840"},
        "type_coercion": "major_to_minor_units",
    }
    history = get_session().ks_workspace_state.review_history[-1]
    assert history.status == "edited"
    assert history.edited_payload["target"] == "amountMinor"
    assert history.review_context["type_coercion"] == "major_to_minor_units"


def test_router_transform_review_reject_records_without_mutating_rows(monkeypatch) -> None:
    _seed_router_route_model()
    _enable_assist()
    _submit_success(monkeypatch)

    response = client.post(
        "/kafka/ks/transform-review",
        json={"decisions": [_transform_decision("t-reject", "rejected")]},
    )

    assert response.status_code == 200
    session = get_session()
    assert session.kafka_route_transforms == []
    assert session.ks_workspace_state.suggestion_review_state.rejected_ids == ["t-reject"]
    assert session.ks_workspace_state.review_history[-1].type == "transform"
    assert session.ks_workspace_state.review_history[-1].review_context["source_entity"] == "payment-posted-upstream"
    assert session.ks_workspace_state.review_history[-1].review_context["target_entity"] == "payment-posted-downstream"
    assert session.ks_workspace_state.review_history[-1].review_context["source"] == "paymentId"
    assert session.ks_workspace_state.review_history[-1].review_context["target"] == "transactionId"


def test_router_transform_review_duplicate_does_not_create_duplicate_row(monkeypatch) -> None:
    _seed_router_route_model()
    _enable_assist()
    session = get_session()
    session.kafka_route_transforms = [
        KafkaRouteTransform(
            route_name="payment-posted",
            router_target_transforms=[
                KafkaRouterTargetTransform(
                    target_id="ledger-core",
                    request_transform_rows=[
                        KafkaRouterTransformRow(source="paymentId", target="transactionId")
                    ],
                )
            ],
        )
    ]
    save_session(session)
    _submit_success(monkeypatch)

    response = client.post(
        "/kafka/ks/transform-review",
        json={"decisions": [_transform_decision("t-dupe", "accepted")]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["applied_count"] == 0
    assert "already exists" in payload["warnings"][0]
    rows = get_session().kafka_route_transforms[0].router_target_transforms[0].request_transform_rows
    assert rows == [KafkaRouterTransformRow(source="paymentId", target="transactionId")]


def test_router_transform_review_updates_same_source_target_details(monkeypatch) -> None:
    _seed_router_route_model()
    _enable_assist()
    session = get_session()
    session.kafka_route_transforms = [
        KafkaRouteTransform(
            route_name="payment-posted",
            router_target_transforms=[
                KafkaRouterTargetTransform(
                    target_id="ledger-core",
                    request_transform_rows=[
                        KafkaRouterTransformRow(source="amount", target="amountMinor")
                    ],
                )
            ],
        )
    ]
    save_session(session)
    _submit_success(monkeypatch)

    response = client.post(
        "/kafka/ks/transform-review",
        json={
            "decisions": [
                _transform_decision(
                    "t-update",
                    "accepted",
                    source="amount",
                    target="amountMinor",
                    value_map={"USD": "840"},
                    type_coercion="major_to_minor_units",
                )
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["applied_count"] == 1
    rows = get_session().kafka_route_transforms[0].router_target_transforms[0].request_transform_rows
    assert rows == [
        KafkaRouterTransformRow(
            source="amount",
            target="amountMinor",
            value_map={"USD": "840"},
            type_coercion="major_to_minor_units",
        )
    ]


def test_router_transform_review_accepts_default_only_row(monkeypatch) -> None:
    _seed_router_route_model()
    _enable_assist()
    _submit_success(monkeypatch)

    response = client.post(
        "/kafka/ks/transform-review",
        json={
            "decisions": [
                _transform_decision(
                    "t-default",
                    "accepted",
                    source="",
                    target="status",
                    default_value="UNKNOWN",
                )
            ]
        },
    )

    assert response.status_code == 200
    target = get_session().kafka_route_transforms[0].router_target_transforms[0]
    assert target.request_transform_rows == [
        KafkaRouterTransformRow(source="", target="status", default_value="UNKNOWN")
    ]
    assert response.json()["outcomes"][0]["manifest_path"].endswith("request_transform.default.status")


def test_router_transform_review_rejects_stale_target_before_ks(monkeypatch) -> None:
    _seed_router_route_model()
    _enable_assist()

    def fail_submit(session, *, decisions: list[dict]):
        raise AssertionError("stale transform context should not be submitted to KS")

    monkeypatch.setattr(
        "app.routes.kafka.assist_service.submit_transform_suggestion_decisions",
        fail_submit,
    )

    response = client.post(
        "/kafka/ks/transform-review",
        json={"decisions": [_transform_decision("t-stale", "accepted", target_id="missing-target")]},
    )

    assert response.status_code == 400
    assert "no longer matches" in response.json()["errors"][0]


def test_router_transform_review_rejects_non_router_route_before_ks(monkeypatch) -> None:
    _seed_route_models("fire-and-forget")
    _enable_assist()

    def fail_submit(session, *, decisions: list[dict]):
        raise AssertionError("non-router transform suggestion should not be submitted to KS")

    monkeypatch.setattr(
        "app.routes.kafka.assist_service.submit_transform_suggestion_decisions",
        fail_submit,
    )

    response = client.post(
        "/kafka/ks/transform-review",
        json={"decisions": [_transform_decision("t-non-router", "accepted")]},
    )

    assert response.status_code == 400
    assert "Kafka router routes" in response.json()["errors"][0]


def test_router_transform_review_rejects_invalid_value_map(monkeypatch) -> None:
    _seed_router_route_model()
    _enable_assist()

    def fail_submit(session, *, decisions: list[dict]):
        raise AssertionError("invalid transform payload should not be submitted to KS")

    monkeypatch.setattr(
        "app.routes.kafka.assist_service.submit_transform_suggestion_decisions",
        fail_submit,
    )

    response = client.post(
        "/kafka/ks/transform-review",
        json={"decisions": [_transform_decision("t-map", "accepted", value_map="[1, 2]")]},
    )

    assert response.status_code == 400
    assert "value_map must be a JSON object" in response.json()["errors"][0]


def test_router_transform_review_rejects_invalid_type_coercion(monkeypatch) -> None:
    _seed_router_route_model()
    _enable_assist()

    def fail_submit(session, *, decisions: list[dict]):
        raise AssertionError("invalid transform payload should not be submitted to KS")

    monkeypatch.setattr(
        "app.routes.kafka.assist_service.submit_transform_suggestion_decisions",
        fail_submit,
    )

    response = client.post(
        "/kafka/ks/transform-review",
        json={"decisions": [_transform_decision("t-coerce", "accepted", type_coercion="stringify")]},
    )

    assert response.status_code == 400
    assert "type_coercion" in response.json()["errors"][0]


def test_router_transform_review_ks_failure_does_not_mutate(monkeypatch) -> None:
    _seed_router_route_model()
    _enable_assist()

    def fail_submit(session, *, decisions: list[dict]):
        return None

    monkeypatch.setattr(
        "app.routes.kafka.assist_service.submit_transform_suggestion_decisions",
        fail_submit,
    )

    response = client.post(
        "/kafka/ks/transform-review",
        json={"decisions": [_transform_decision("t-fail", "accepted")]},
    )

    assert response.status_code == 502
    assert get_session().kafka_route_transforms == []
    assert get_session().ks_workspace_state.review_history == []


def test_router_transform_drawer_empty_for_non_router_route(monkeypatch) -> None:
    _seed_router_route_model()
    _enable_assist()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("non-router transform drawer should not call KS")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get(
        "/kafka/ks/drawer",
        params={
            "scope": "transforms",
            "route_name": "unknown-route",
            "target_id": "ledger-core",
            "direction": "request",
        },
    )

    assert response.status_code == 200
    assert response.json()["empty"] is True
