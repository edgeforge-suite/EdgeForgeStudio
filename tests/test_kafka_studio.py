"""Focused tests for the Kafka integration Studio authoring flow."""

import io
import zipfile
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.main import app
from app.models.project import (
    KafkaConfig,
    KafkaRouteModel,
    KafkaRouterTargetTransform,
    KafkaRouterTransformRow,
    KafkaRouteTransform,
    KafkaTopicPair,
    KafkaTransformRow,
)
from app.services.completeness_service import build_completeness_report
from app.services.manifest_generator import build_manifest_dict
from app.services.project_file_service import serialize_project, snapshot_session
from app.wizard_registry import get_steps
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)


UPSTREAM_SCHEMA = '{"type":"object","properties":{"paymentId":{"type":"string"}}}'
DOWNSTREAM_SCHEMA = '{"type":"object","properties":{"ledgerId":{"type":"string"}}}'
UPSTREAM_REPLY_SCHEMA = '{"type":"object","properties":{"verified":{"type":"boolean"},"reason":{"type":"string"},"riskScore":{"type":"integer"}}}'
DOWNSTREAM_REPLY_SCHEMA = '{"type":"object","properties":{"approved":{"type":"boolean"},"declineReason":{"type":"string"},"score":{"type":"integer"}}}'


def _base_kafka_session() -> None:
    reset_session()
    session = get_session()
    session.app_name = "Payment Mediation"
    session.bounded_context = "payments"
    session.app_archetype = "kafka-integration"
    session.target_profile = "springboot-standard-enterprise"
    save_session(session)


def _seed_topic_pairs() -> None:
    _base_kafka_session()
    session = get_session()
    session.kafka_config = KafkaConfig(
        consumer_group="payment-mediation-group",
        concurrency=2,
        retry_max_attempts=3,
        retry_backoff_ms=1000,
        retry_backoff_multiplier=2.0,
        dlq_enabled=True,
        dlq_topic_suffix=".dlq",
    )
    session.kafka_topic_pairs = [
        KafkaTopicPair(
            route_name="payment-posted",
            upstream_topic="abc.payments.posted.v1",
            upstream_system="PaymentHub",
            upstream_schema_content=UPSTREAM_SCHEMA,
            downstream_topic="xyz.ledger.entries.v1",
            downstream_system="LedgerService",
            downstream_schema_content=DOWNSTREAM_SCHEMA,
        )
    ]
    save_session(session)


def _seed_route_models(pattern: str = "fire-and-forget") -> None:
    _seed_topic_pairs()
    session = get_session()
    session.kafka_route_models = [
        KafkaRouteModel(
            route_name="payment-posted",
            pattern=pattern,
            upstream_reply_topic="hub.reply.v1" if pattern == "request-reply" else "",
            upstream_reply_schema_content=UPSTREAM_REPLY_SCHEMA if pattern == "request-reply" else "",
            downstream_reply_topic="core.reply.v1" if pattern == "request-reply" else "",
            downstream_reply_schema_content=DOWNSTREAM_REPLY_SCHEMA if pattern == "request-reply" else "",
            correlation_source="header",
            correlation_field="X-Correlation-ID" if pattern == "request-reply" else "",
            reply_timeout_ms=5000,
        )
    ]
    save_session(session)


def _fully_populated_kafka_session(request_reply: bool = False):
    _seed_route_models("request-reply" if request_reply else "fire-and-forget")
    session = get_session()
    session.kafka_route_transforms = [
        KafkaRouteTransform(
            route_name="payment-posted",
            mappings=[
                KafkaTransformRow(source_field="paymentId", target_field="ledgerId"),
            ],
            response_mappings=[
                KafkaTransformRow(source_field="verified", target_field="approved"),
            ] if request_reply else [],
        )
    ]
    save_session(session)
    return session


def _valid_router_config() -> dict:
    return {
        "upstream_topics": [
            {
                "id": "u1_intake",
                "name": "abc.payments.posted.v1",
                "consumer_group": "payment-mediation-group",
                "source_system_extraction": {
                    "mode": "header",
                    "header_key": "X-Source-System",
                },
                "reply_destination_extraction": {
                    "mode": "header",
                    "header_key": "X-Reply-To",
                },
            }
        ],
        "inbound_schema": {
            "file": "schemas/payment-posted-upstream.json",
            "validation_policy": "strict",
            "failure_behavior": "nack",
        },
        "routing_rules": {
            "routing_fields": [{"name": "country", "json_path": "$.country"}],
            "rules": [
                {
                    "id": "uk-payments",
                    "conditions": [{"field": "country", "operator": "eq", "value": "UK"}],
                    "target": "ledger-core",
                }
            ],
            "default_target": "ledger-core",
        },
        "duplicate_correlation_policy": "reject-new",
        "targets": [
            {
                "id": "ledger-core",
                "request_topic": "xyz.ledger.entries.v1",
                "response_topic": "xyz.ledger.entries.reply.v1",
                "request_schema": {
                    "file": "schemas/payment-posted-downstream.json",
                    "validation_policy": "strict",
                    "failure_behavior": "nack",
                },
                "response_schema": {
                    "file": "schemas/payment-posted-target-response.json",
                    "validation_policy": "strict",
                    "failure_behavior": "nack",
                },
                "request_transform": {"file": "transforms/payment-posted-request.yaml"},
                "response_transform": {"file": "transforms/payment-posted-response.yaml"},
                "retry": {
                    "max_attempts": 3,
                    "backoff_ms": 1000,
                    "dlq_topic": "xyz.ledger.entries.v1.dlq",
                },
                "timeout_ms": 30000,
            }
        ],
        "outbound_schema": {
            "file": "schemas/payment-posted-outbound.json",
            "validation_policy": "strict",
            "failure_behavior": "nack",
        },
        "nack_routing": {
            "mode": "fixed",
            "fixed_topic": "payment-router-nack",
            "default_error_topic": "payment-router-error",
        },
        "timeout": {
            "behavior_with_known_reply": "nack",
            "behavior_without_reply": "error_topic",
        },
        "payload_logging": {
            "policy": "none",
            "capped_raw_bytes": 512,
        },
        "correlation_store": {
            "type": "in_memory",
            "timeout_ms": 30000,
            "eviction_interval_ms": 60000,
        },
    }


def _router_route_payload(router_config: dict | None = None) -> dict:
    return {
        "route_name": "payment-posted",
        "pattern": "router",
        "reply_timeout_ms": 5000,
        "router_config": router_config if router_config is not None else _valid_router_config(),
    }


def _router_manifest_for_nack_routing(nack_routing: dict) -> dict:
    _seed_topic_pairs()
    session = get_session()
    config = _valid_router_config()
    config["nack_routing"] = nack_routing
    session.kafka_route_models = [
        KafkaRouteModel(
            route_name="payment-posted",
            pattern="router",
            router_config=config,
        )
    ]
    session.kafka_route_models = [
        KafkaRouteModel.model_validate(session.kafka_route_models[0].model_dump())
    ]
    save_session(session)
    return build_manifest_dict(get_session())["async_routes"][0]["router_config"]["nack_routing"]


def _seed_router_route_model() -> None:
    _seed_topic_pairs()
    session = get_session()
    session.kafka_route_models = [
        KafkaRouteModel(
            route_name="payment-posted",
            pattern="router",
            router_config=_valid_router_config(),
        )
    ]
    save_session(session)


def _seed_pure_router_route_model() -> None:
    _base_kafka_session()
    session = get_session()
    session.kafka_config = KafkaConfig(
        consumer_group="payment-mediation-group",
        concurrency=2,
        retry_max_attempts=3,
        retry_backoff_ms=1000,
        retry_backoff_multiplier=2.0,
        dlq_enabled=True,
        dlq_topic_suffix=".dlq",
    )
    session.kafka_topic_pairs = []
    session.kafka_route_models = [
        KafkaRouteModel(
            route_name="payment-posted",
            pattern="router",
            router_config=_valid_router_config(),
        )
    ]
    session.kafka_route_transforms = [
        KafkaRouteTransform(
            route_name="payment-posted",
            router_target_transforms=[
                KafkaRouterTargetTransform(
                    target_id="ledger-core",
                    request_transform_rows=[
                        KafkaRouterTransformRow(source="paymentId", target="transactionId")
                    ],
                    response_transform_rows=[
                        KafkaRouterTransformRow(source="ledgerId", target="paymentId")
                    ],
                )
            ],
        )
    ]
    save_session(session)


def test_step1_can_select_kafka_integration_archetype() -> None:
    reset_session()
    response = client.post(
        "/",
        data={
            "app_name": "Kafka Hub",
            "bounded_context": "payments",
            "app_archetype": "kafka-integration",
            "target_profile": "springboot-standard-enterprise",
            "output_path": "",
            "appbuilder_repo_path": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/kafka/topics"
    assert get_session().app_archetype == "kafka-integration"
    reset_session()


def test_get_steps_kafka_integration_returns_expected_order() -> None:
    steps = get_steps("kafka-integration")
    assert [step.step_id for step in steps] == [
        "project-setup",
        "kafka-topic-ingest",
        "kafka-route-model",
        "kafka-transform-mappings",
        "downstream-interfaces",
        "rules-mappings",
        "review",
        "export-build-run",
    ]


def test_kafka_topics_redirects_for_non_kafka_session() -> None:
    reset_session()
    response = client.get("/kafka/topics", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_kafka_topics_get_returns_200_for_kafka_session() -> None:
    _base_kafka_session()
    response = client.get("/kafka/topics")
    assert response.status_code == 200
    assert "Kafka Integration" in response.text
    assert "Topic Ingest" in response.text
    assert "Advanced consumer settings" in response.text
    assert "Schema payloads" in response.text


def test_kafka_topics_get_renders_router_summary_without_topic_pairs() -> None:
    _seed_pure_router_route_model()

    response = client.get("/kafka/topics")

    assert response.status_code == 200
    assert "Router Topic Summary" in response.text
    assert "Fixed topic pairs are not required for router pattern routes." in response.text
    assert "payment-posted" in response.text
    assert "abc.payments.posted.v1" in response.text
    assert "ledger-core" in response.text
    assert "const hasRouterTopicSummary = true;" in response.text
    reset_session()


def test_kafka_topics_save_valid_payload_persists_config_and_pairs() -> None:
    _base_kafka_session()
    response = client.post(
        "/kafka/topics/save",
        json={
            "consumer_group": "payment-mediation-group",
            "concurrency": 2,
            "retry_max_attempts": 3,
            "retry_backoff_ms": 1000,
            "retry_backoff_multiplier": 2.0,
            "dlq_enabled": True,
            "dlq_topic_suffix": ".dlq",
            "topic_pairs": [
                {
                    "route_name": "payment-posted",
                    "upstream_topic": "abc.payments.posted.v1",
                    "upstream_system": "PaymentHub",
                    "upstream_schema_content": UPSTREAM_SCHEMA,
                    "downstream_topic": "xyz.ledger.entries.v1",
                    "downstream_system": "LedgerService",
                    "downstream_schema_content": DOWNSTREAM_SCHEMA,
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    session = get_session()
    assert session.kafka_config.consumer_group == "payment-mediation-group"
    assert session.kafka_config.concurrency == 2
    assert len(session.kafka_topic_pairs) == 1
    assert session.kafka_topic_pairs[0].route_name == "payment-posted"


def test_kafka_topics_save_requires_consumer_group() -> None:
    _base_kafka_session()
    response = client.post(
        "/kafka/topics/save",
        json={
            "consumer_group": "",
            "concurrency": 2,
            "topic_pairs": [
                {
                    "route_name": "payment-posted",
                    "upstream_topic": "abc.payments.posted.v1",
                    "downstream_topic": "xyz.ledger.entries.v1",
                }
            ],
        },
    )

    assert response.status_code == 400
    assert response.json()["ok"] is False


def test_kafka_topics_save_rejects_duplicate_route_names() -> None:
    _base_kafka_session()
    response = client.post(
        "/kafka/topics/save",
        json={
            "consumer_group": "payment-mediation-group",
            "concurrency": 2,
            "topic_pairs": [
                {
                    "route_name": "payment-posted",
                    "upstream_topic": "abc.payments.posted.v1",
                    "downstream_topic": "xyz.ledger.entries.v1",
                },
                {
                    "route_name": "payment-posted",
                    "upstream_topic": "abc.payments.reversed.v1",
                    "downstream_topic": "xyz.ledger.reversals.v1",
                },
            ],
        },
    )

    assert response.status_code == 400
    assert response.json()["ok"] is False


def test_kafka_routes_get_redirects_when_topic_pairs_missing() -> None:
    _base_kafka_session()
    response = client.get("/kafka/routes", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/kafka/topics"


def test_kafka_routes_get_allows_pure_router_route_model() -> None:
    _seed_pure_router_route_model()

    response = client.get("/kafka/routes", follow_redirects=False)

    assert response.status_code == 200
    assert "Route Model" in response.text
    assert "payment-posted" in response.text
    assert "ledger-core" in response.text
    reset_session()


def test_kafka_routes_save_allows_router_without_fixed_topic_pair() -> None:
    _seed_pure_router_route_model()

    response = client.post("/kafka/routes/save", json={"routes": [_router_route_payload()]})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    session = get_session()
    assert session.kafka_topic_pairs == []
    assert len(session.kafka_route_models) == 1
    assert session.kafka_route_models[0].pattern == "router"
    assert session.kafka_route_models[0].router_config is not None
    reset_session()


def test_kafka_routes_get_shows_route_model_and_reply_details() -> None:
    _seed_topic_pairs()
    response = client.get("/kafka/routes")

    assert response.status_code == 200
    assert "Route Model" in response.text
    assert "Reply channel details" in response.text
    assert 'value="router"' in response.text
    assert "Router request-path configuration is supported here" in response.text
    assert "Starter router config" in response.text
    assert "These values are not imported or restored data." in response.text
    assert "const usesStarterRouterConfig = !model.router_config;" in response.text
    assert "routerPanel(routeName, routerConfig, usesStarterRouterConfig)" in response.text
    assert "const savedRouterConfig = !usesStarterConfig;" in response.text
    assert "Routing fields and rules (${countLabel(routingFieldCount, 'field')}, ${countLabel(routingRuleCount, 'rule')})" in response.text
    assert "Targets and transform file references (${countLabel(targetCount, 'target')})" in response.text
    assert (
        '<details class="disclosure-card workflow-surface-subsection" '
        "${savedDetailState}>"
    ) in response.text


def test_kafka_routes_save_request_reply_requires_correlation_field() -> None:
    _seed_topic_pairs()
    response = client.post(
        "/kafka/routes/save",
        json={
            "routes": [
                {
                    "route_name": "payment-posted",
                    "pattern": "request-reply",
                    "upstream_reply_topic": "hub.reply.v1",
                    "upstream_reply_schema_content": UPSTREAM_REPLY_SCHEMA,
                    "downstream_reply_topic": "core.reply.v1",
                    "downstream_reply_schema_content": DOWNSTREAM_REPLY_SCHEMA,
                    "correlation_source": "header",
                    "correlation_field": "",
                    "reply_timeout_ms": 5000,
                }
            ]
        },
    )

    assert response.status_code == 400
    assert response.json()["ok"] is False


def test_kafka_routes_save_valid_fire_and_forget_payload() -> None:
    _seed_topic_pairs()
    response = client.post(
        "/kafka/routes/save",
        json={
            "routes": [
                {
                    "route_name": "payment-posted",
                    "pattern": "fire-and-forget",
                    "upstream_reply_topic": "",
                    "downstream_reply_topic": "",
                    "correlation_source": "header",
                    "correlation_field": "",
                    "reply_timeout_ms": 5000,
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert get_session().kafka_route_models[0].pattern == "fire-and-forget"


def test_kafka_routes_save_valid_router_payload_persists_config() -> None:
    _seed_topic_pairs()
    response = client.post(
        "/kafka/routes/save",
        json={"routes": [_router_route_payload()]},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    model = get_session().kafka_route_models[0]
    assert model.pattern == "router"
    assert model.router_config is not None
    assert model.router_config.upstream_topics[0].name == "abc.payments.posted.v1"
    assert model.router_config.targets[0].id == "ledger-core"
    assert model.router_config.nack_routing.fixed_topic == "payment-router-nack"


def test_kafka_routes_save_router_does_not_require_request_reply_fields() -> None:
    _seed_topic_pairs()
    payload = _router_route_payload()
    payload.update(
        {
            "upstream_reply_topic": "",
            "downstream_reply_topic": "",
            "correlation_source": "header",
            "correlation_field": "",
            "reply_timeout_ms": 0,
        }
    )

    response = client.post("/kafka/routes/save", json={"routes": [payload]})

    assert response.status_code == 200
    assert get_session().kafka_route_models[0].pattern == "router"


def test_kafka_routes_save_router_rejects_bad_target_references() -> None:
    _seed_topic_pairs()
    config = _valid_router_config()
    config["routing_rules"]["rules"][0]["target"] = "missing-target"

    response = client.post(
        "/kafka/routes/save",
        json={"routes": [_router_route_payload(config)]},
    )

    assert response.status_code == 400
    assert "target must reference an existing target id" in response.json()["error"]


def test_kafka_routes_save_router_rejects_bad_default_target() -> None:
    _seed_topic_pairs()
    config = _valid_router_config()
    config["routing_rules"]["default_target"] = "missing-target"

    response = client.post(
        "/kafka/routes/save",
        json={"routes": [_router_route_payload(config)]},
    )

    assert response.status_code == 400
    assert "Default target must reference an existing target id" in response.json()["error"]


def test_kafka_routes_save_router_rejects_bad_condition_field() -> None:
    _seed_topic_pairs()
    config = _valid_router_config()
    config["routing_rules"]["rules"][0]["conditions"][0]["field"] = "missing-field"

    response = client.post(
        "/kafka/routes/save",
        json={"routes": [_router_route_payload(config)]},
    )

    assert response.status_code == 400
    assert "condition field must reference a declared routing field" in response.json()["error"]


def test_kafka_routes_save_router_rejects_bad_extraction_mode_payloads() -> None:
    _seed_topic_pairs()
    config = _valid_router_config()
    config["upstream_topics"][0]["source_system_extraction"] = {
        "mode": "header",
        "header_key": "",
    }

    response = client.post(
        "/kafka/routes/save",
        json={"routes": [_router_route_payload(config)]},
    )

    assert response.status_code == 400
    assert "header extraction requires header_key" in response.json()["error"]


def test_kafka_routes_save_router_rejects_bad_nack_payloads() -> None:
    _seed_topic_pairs()
    config = _valid_router_config()
    config["nack_routing"]["mode"] = "per_source_system"
    config["nack_routing"]["per_source_system"] = {}

    response = client.post(
        "/kafka/routes/save",
        json={"routes": [_router_route_payload(config)]},
    )

    assert response.status_code == 400
    assert "per_source_system NACK mode requires" in response.json()["error"]


def test_kafka_routes_save_router_rejects_capped_raw_without_positive_bytes() -> None:
    _seed_topic_pairs()
    config = _valid_router_config()
    config["payload_logging"] = {"policy": "capped_raw", "capped_raw_bytes": 0}

    response = client.post(
        "/kafka/routes/save",
        json={"routes": [_router_route_payload(config)]},
    )

    assert response.status_code == 400
    assert "positive capped_raw_bytes" in response.json()["error"]


def test_kafka_topics_save_preserves_existing_route_state_when_topic_pairs_unchanged() -> None:
    _fully_populated_kafka_session(request_reply=True)

    response = client.post(
        "/kafka/topics/save",
        json={
            "consumer_group": "payment-mediation-group",
            "concurrency": 2,
            "retry_max_attempts": 3,
            "retry_backoff_ms": 1000,
            "retry_backoff_multiplier": 2.0,
            "dlq_enabled": True,
            "dlq_topic_suffix": ".dlq",
            "topic_pairs": [
                {
                    "route_name": "payment-posted",
                    "upstream_topic": "abc.payments.posted.v1",
                    "upstream_system": "PaymentHub",
                    "upstream_schema_content": UPSTREAM_SCHEMA,
                    "downstream_topic": "xyz.ledger.entries.v1",
                    "downstream_system": "LedgerService",
                    "downstream_schema_content": DOWNSTREAM_SCHEMA,
                }
            ],
        },
    )

    assert response.status_code == 200
    session = get_session()
    assert len(session.kafka_route_models) == 1
    assert session.kafka_route_models[0].pattern == "request-reply"
    assert session.kafka_route_models[0].upstream_reply_topic == "hub.reply.v1"
    assert len(session.kafka_route_transforms) == 1
    assert session.kafka_route_transforms[0].response_mappings[0].target_field == "approved"


def test_kafka_topics_save_preserves_router_state_when_route_name_unchanged() -> None:
    _seed_router_route_model()
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

    response = client.post(
        "/kafka/topics/save",
        json={
            "consumer_group": "payment-mediation-group",
            "concurrency": 2,
            "retry_max_attempts": 3,
            "retry_backoff_ms": 1000,
            "retry_backoff_multiplier": 2.0,
            "dlq_enabled": True,
            "dlq_topic_suffix": ".dlq",
            "topic_pairs": [
                {
                    "route_name": "payment-posted",
                    "upstream_topic": "abc.payments.posted.v1",
                    "upstream_system": "PaymentHub",
                    "upstream_schema_path": "schemas/payment-posted-upstream.json",
                    "downstream_topic": "xyz.ledger.entries.v1",
                    "downstream_system": "LedgerService",
                    "downstream_schema_path": "schemas/payment-posted-downstream.json",
                }
            ],
        },
    )

    assert response.status_code == 200
    session = get_session()
    assert len(session.kafka_route_models) == 1
    assert session.kafka_route_models[0].pattern == "router"
    assert session.kafka_route_models[0].router_config is not None
    assert session.kafka_route_models[0].router_config.targets[0].id == "ledger-core"
    assert len(session.kafka_route_transforms) == 1
    assert session.kafka_route_transforms[0].router_target_transforms[0].target_id == "ledger-core"
    assert (
        session.kafka_route_transforms[0]
        .router_target_transforms[0]
        .request_transform_rows[0]
        .target
        == "transactionId"
    )


def test_kafka_topics_save_allows_zero_pairs_when_router_route_exists() -> None:
    _seed_pure_router_route_model()

    response = client.post(
        "/kafka/topics/save",
        json={
            "consumer_group": "payment-mediation-group",
            "concurrency": 2,
            "retry_max_attempts": 3,
            "retry_backoff_ms": 1000,
            "retry_backoff_multiplier": 2.0,
            "dlq_enabled": True,
            "dlq_topic_suffix": ".dlq",
            "topic_pairs": [],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    session = get_session()
    assert session.kafka_topic_pairs == []
    assert len(session.kafka_route_models) == 1
    assert session.kafka_route_models[0].pattern == "router"
    assert session.kafka_route_models[0].router_config is not None
    assert len(session.kafka_route_transforms) == 1
    assert session.kafka_route_transforms[0].router_target_transforms[0].target_id == "ledger-core"
    reset_session()


def test_kafka_topics_save_reconciles_route_state_for_renamed_routes() -> None:
    _seed_router_route_model()
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

    response = client.post(
        "/kafka/topics/save",
        json={
            "consumer_group": "payment-mediation-group",
            "concurrency": 2,
            "retry_max_attempts": 3,
            "retry_backoff_ms": 1000,
            "retry_backoff_multiplier": 2.0,
            "dlq_enabled": True,
            "dlq_topic_suffix": ".dlq",
            "topic_pairs": [
                {
                    "route_name": "payment-posted-v2",
                    "upstream_topic": "abc.payments.posted.v1",
                    "upstream_system": "PaymentHub",
                    "upstream_schema_content": UPSTREAM_SCHEMA,
                    "downstream_topic": "xyz.ledger.entries.v1",
                    "downstream_system": "LedgerService",
                    "downstream_schema_content": DOWNSTREAM_SCHEMA,
                }
            ],
        },
    )

    assert response.status_code == 200
    session = get_session()
    assert [pair.route_name for pair in session.kafka_topic_pairs] == ["payment-posted-v2"]
    assert session.kafka_route_models == []
    assert session.kafka_route_transforms == []


def test_kafka_transforms_get_redirects_when_route_models_missing() -> None:
    _seed_topic_pairs()
    response = client.get("/kafka/transforms", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/kafka/routes"


def test_kafka_transforms_save_valid_payload() -> None:
    _seed_route_models("fire-and-forget")
    response = client.post(
        "/kafka/transforms/save",
        json={
            "transforms": [
                {
                    "route_name": "payment-posted",
                    "mappings": [
                        {"source_field": "paymentId", "target_field": "ledgerId"},
                    ],
                    "response_mappings": [],
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert get_session().kafka_route_transforms[0].mappings[0].target_field == "ledgerId"


def test_kafka_transforms_renders_mapping_badge_for_fire_and_forget(monkeypatch) -> None:
    _seed_route_models("fire-and-forget")
    session = get_session()
    session.capabilities.knowledge_assist_enabled = True
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
            assert scope == "mappings"
            assert route_name == "payment-posted"
            assert direction == "request"
            assert source_entity == "payment-posted-upstream"
            assert target_entity == "payment-posted-downstream"
            return {
                "scope": scope,
                "suggestions": [{"suggestion_id": "m-1", "source_field": "paymentId", "target_field": "ledgerId"}],
                "suggestion_count": 1,
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/kafka/transforms")

    assert response.status_code == 200
    assert "1 mapping suggestion" in response.text
    assert "/kafka/ks/drawer?scope=mappings\\u0026route_name=payment-posted" in response.text


def test_kafka_transforms_renders_mapping_badge_for_request_reply(monkeypatch) -> None:
    _seed_route_models("request-reply")
    session = get_session()
    session.capabilities.knowledge_assist_enabled = True
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
            assert scope == "mappings"
            assert route_name == "payment-posted"
            assert direction in {"request", "response"}
            assert source_entity
            assert target_entity
            return {
                "scope": scope,
                "suggestions": [{"suggestion_id": "m-1", "source_field": "verified", "target_field": "approved"}],
                "suggestion_count": 1,
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/kafka/transforms")

    assert response.status_code == 200
    assert "2 mapping suggestions" in response.text
    assert "Response Mappings" in response.text


def test_kafka_mapping_drawer_route_returns_rows_for_fixed_route(monkeypatch) -> None:
    _seed_route_models("fire-and-forget")
    session = get_session()
    session.capabilities.knowledge_assist_enabled = True
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
            assert scope == "mappings"
            assert route_name == "payment-posted"
            assert direction == "request"
            assert source_entity == "payment-posted-upstream"
            assert target_entity == "payment-posted-downstream"
            return {
                "scope": scope,
                "suggestions": [
                    {
                        "suggestion_id": "m-1",
                        "suggestion_type": "mapping",
                        "payload": {"source_field": "paymentId", "target_field": "ledgerId"},
                    }
                ],
                "suggestion_count": 1,
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/kafka/ks/drawer?scope=mappings&route_name=payment-posted")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["scope"] == "mappings"
    assert payload["scopes"][0]["rows"][0]["suggestion_type"] == "mapping"
    assert payload["scopes"][0]["rows"][0]["title"] == "paymentId → ledgerId"


def _kafka_mapping_decision(
    suggestion_id: str,
    status: str,
    *,
    direction: str = "request",
    source: str = "paymentId",
    target: str = "ledgerId",
    source_entity: str | None = None,
    target_entity: str | None = None,
    edited_payload: dict | None = None,
    route_name: str = "payment-posted",
    mapping_type: str = "copy",
) -> dict:
    source_entity = source_entity or (
        "payment-posted-downstream-reply" if direction == "response" else "payment-posted-upstream"
    )
    target_entity = target_entity or (
        "payment-posted-upstream-reply" if direction == "response" else "payment-posted-downstream"
    )
    decision = {
        "suggestion_id": suggestion_id,
        "suggestion_type": "mapping",
        "status": status,
        "manifest_path": f"async_routes.{route_name}.transform_mapping.{direction}.{target}",
    }
    decision["payload"] = {
        "route_name": route_name,
        "direction": direction,
        "source_entity": source_entity,
        "target_entity": target_entity,
        "source_field": source,
        "target_field": target,
        "mapping_type": mapping_type,
    }
    if edited_payload is not None:
        decision["edited_payload"] = edited_payload
    return decision


def _enable_kafka_mapping_reviews(pattern: str, monkeypatch):
    _seed_route_models(pattern)
    session = get_session()
    session.capabilities.knowledge_assist_enabled = True
    save_session(session)
    submitted: list[list[dict]] = []

    def fake_submit(session, *, decisions: list[dict]):
        submitted.append(decisions)
        return {
            "success": True,
            "outcomes": [
                {"suggestion_id": decision["suggestion_id"], "success": True}
                for decision in decisions
            ],
        }

    monkeypatch.setattr(
        "app.routes.kafka.assist_service.submit_mapping_suggestion_decisions",
        fake_submit,
    )
    return submitted


def test_kafka_mapping_review_accept_applies_fire_and_forget_request_mapping(monkeypatch) -> None:
    submitted = _enable_kafka_mapping_reviews("fire-and-forget", monkeypatch)

    response = client.post(
        "/kafka/ks/review",
        json={"decisions": [_kafka_mapping_decision("m-kafka-request", "accepted")]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["applied_count"] == 1
    session = get_session()
    assert session.kafka_route_transforms[0].mappings == [
        KafkaTransformRow(source_field="paymentId", target_field="ledgerId")
    ]
    assert session.ks_workspace_state.suggestion_review_state.accepted_ids == ["m-kafka-request"]
    assert session.ks_workspace_state.review_history[-1].type == "mapping"
    assert session.ks_workspace_state.evidence_links == []
    assert submitted == [[{"suggestion_id": "m-kafka-request", "status": "accepted"}]]


def test_kafka_mapping_review_accept_applies_request_reply_request_mapping(monkeypatch) -> None:
    _enable_kafka_mapping_reviews("request-reply", monkeypatch)

    response = client.post(
        "/kafka/ks/review",
        json={"decisions": [_kafka_mapping_decision("m-rr-request", "accepted")]},
    )

    assert response.status_code == 200
    transform = get_session().kafka_route_transforms[0]
    assert transform.mappings == [KafkaTransformRow(source_field="paymentId", target_field="ledgerId")]
    assert transform.response_mappings == []


def test_kafka_mapping_review_accept_applies_request_reply_response_mapping(monkeypatch) -> None:
    _enable_kafka_mapping_reviews("request-reply", monkeypatch)

    response = client.post(
        "/kafka/ks/review",
        json={
            "decisions": [
                _kafka_mapping_decision(
                    "m-rr-response",
                    "accepted",
                    direction="response",
                    source="approved",
                    target="verified",
                )
            ]
        },
    )

    assert response.status_code == 200
    transform = get_session().kafka_route_transforms[0]
    assert transform.mappings == []
    assert transform.response_mappings == [
        KafkaTransformRow(source_field="approved", target_field="verified")
    ]


def test_kafka_mapping_review_edit_applies_edited_payload(monkeypatch) -> None:
    submitted = _enable_kafka_mapping_reviews("fire-and-forget", monkeypatch)
    edited = {"source_field": "alternatePaymentId", "target_field": "ledgerReference"}

    response = client.post(
        "/kafka/ks/review",
        json={"decisions": [_kafka_mapping_decision("m-kafka-edit", "edited", edited_payload=edited)]},
    )

    assert response.status_code == 200
    transform = get_session().kafka_route_transforms[0]
    assert transform.mappings == [
        KafkaTransformRow(source_field="alternatePaymentId", target_field="ledgerReference")
    ]
    assert get_session().ks_workspace_state.suggestion_review_state.edited_ids == ["m-kafka-edit"]
    assert get_session().ks_workspace_state.review_history[-1].review_context == {
        "mapping_context": "kafka",
        "route_name": "payment-posted",
        "direction": "request",
        "source_entity": "payment-posted-upstream",
        "target_entity": "payment-posted-downstream",
        "source_field": "alternatePaymentId",
        "target_field": "ledgerReference",
    }
    assert get_session().ks_workspace_state.review_history[-1].manifest_path == (
        "async_routes.payment-posted.transform_mapping.request.alternatePaymentId.ledgerReference"
    )
    assert "ledgerId" not in get_session().ks_workspace_state.review_history[-1].manifest_path
    assert submitted == [[{"suggestion_id": "m-kafka-edit", "status": "edited", "edited_payload": edited}]]


def test_kafka_mapping_review_reject_records_without_mutating_transforms(monkeypatch) -> None:
    _enable_kafka_mapping_reviews("fire-and-forget", monkeypatch)

    response = client.post(
        "/kafka/ks/review",
        json={"decisions": [_kafka_mapping_decision("m-kafka-reject", "rejected")]},
    )

    assert response.status_code == 200
    session = get_session()
    assert session.kafka_route_transforms == []
    assert session.ks_workspace_state.suggestion_review_state.rejected_ids == ["m-kafka-reject"]
    assert session.ks_workspace_state.review_history[-1].type == "mapping"
    assert session.ks_workspace_state.review_history[-1].review_context == {
        "mapping_context": "kafka",
        "route_name": "payment-posted",
        "direction": "request",
        "source_entity": "payment-posted-upstream",
        "target_entity": "payment-posted-downstream",
        "source_field": "paymentId",
        "target_field": "ledgerId",
    }


def test_kafka_mapping_review_does_not_apply_router_route(monkeypatch) -> None:
    _seed_router_route_model()
    session = get_session()
    session.capabilities.knowledge_assist_enabled = True
    save_session(session)

    def fail_submit(session, *, decisions: list[dict]):
        raise AssertionError("router mapping suggestions should fail before KS review submission")

    monkeypatch.setattr(
        "app.routes.kafka.assist_service.submit_mapping_suggestion_decisions",
        fail_submit,
    )

    response = client.post(
        "/kafka/ks/review",
        json={"decisions": [_kafka_mapping_decision("m-router", "accepted")]},
    )

    assert response.status_code == 400
    assert "Kafka router transform suggestions are out of scope" in response.json()["errors"][0]
    assert get_session().kafka_route_transforms == []


def test_kafka_mapping_review_rejects_unsupported_payload(monkeypatch) -> None:
    _enable_kafka_mapping_reviews("fire-and-forget", monkeypatch)

    def fail_submit(session, *, decisions: list[dict]):
        raise AssertionError("invalid mapping payloads should not be submitted to KS")

    monkeypatch.setattr(
        "app.routes.kafka.assist_service.submit_mapping_suggestion_decisions",
        fail_submit,
    )

    response = client.post(
        "/kafka/ks/review",
        json={
            "decisions": [
                _kafka_mapping_decision(
                    "m-value-map",
                    "accepted",
                    mapping_type="value_map",
                )
            ]
        },
    )

    assert response.status_code == 400
    assert "copy mappings only" in response.json()["errors"][0]


def test_kafka_mapping_review_off_rejects_without_ks_call(monkeypatch) -> None:
    _seed_route_models("fire-and-forget")

    def fail_submit(session, *, decisions: list[dict]):
        raise AssertionError("Knowledge Assist OFF should not submit mapping decisions")

    monkeypatch.setattr(
        "app.routes.kafka.assist_service.submit_mapping_suggestion_decisions",
        fail_submit,
    )

    response = client.post(
        "/kafka/ks/review",
        json={"decisions": [_kafka_mapping_decision("m-off", "accepted")]},
    )

    assert response.status_code == 400
    assert "Knowledge Assist is off" in response.json()["errors"][0]


def test_kafka_transforms_does_not_render_mapping_badge_for_router_route(monkeypatch) -> None:
    _seed_router_route_model()
    session = get_session()
    session.capabilities.knowledge_assist_enabled = True
    save_session(session)

    calls: list[str] = []

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
            calls.append(scope)
            return {"scope": scope, "suggestions": [], "suggestion_count": 0}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/kafka/transforms")
    drawer = client.get("/kafka/ks/drawer?scope=mappings&route_name=payment-posted")

    assert response.status_code == 200
    assert "mapping suggestion" not in response.text
    assert "mappings" not in calls
    assert "transforms" in calls
    assert drawer.status_code == 200
    assert drawer.json()["empty"] is True


def test_kafka_transforms_get_renders_router_target_transform_sections() -> None:
    _seed_router_route_model()

    response = client.get("/kafka/transforms")

    assert response.status_code == 200
    assert "ledger-core" in response.text
    assert "transforms/payment-posted-request.yaml" in response.text
    assert "transforms/payment-posted-response.yaml" in response.text
    assert "This page writes the transform YAML files referenced by router_config" in response.text


def test_kafka_transforms_get_renders_pure_router_target_transform_sections() -> None:
    _seed_pure_router_route_model()

    response = client.get("/kafka/transforms")

    assert response.status_code == 200
    assert "payment-posted" in response.text
    assert "ledger-core" in response.text
    assert "transforms/payment-posted-request.yaml" in response.text
    assert "transactionId" in response.text
    reset_session()


def test_kafka_transforms_save_router_request_and_response_rows() -> None:
    _seed_router_route_model()

    response = client.post(
        "/kafka/transforms/save",
        json={
            "transforms": [
                {
                    "route_name": "payment-posted",
                    "router_target_transforms": [
                        {
                            "target_id": "ledger-core",
                            "request_transform_rows": [
                                {
                                    "source": "paymentId",
                                    "target": "transactionId",
                                },
                                {
                                    "source": "status",
                                    "target": "decisionCode",
                                    "value_map": '{"APPROVED":"A","DECLINED":"D"}',
                                    "type_coercion": "",
                                },
                            ],
                            "response_transform_rows": [
                                {
                                    "source": "processorStatus",
                                    "target": "status",
                                    "value_map": {"ACCEPTED": "APPROVED"},
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    )

    assert response.status_code == 200
    transform = get_session().kafka_route_transforms[0]
    target_transform = transform.router_target_transforms[0]
    assert target_transform.target_id == "ledger-core"
    assert target_transform.request_transform_rows[1].value_map == {
        "APPROVED": "A",
        "DECLINED": "D",
    }
    assert target_transform.response_transform_rows[0].target == "status"


def test_kafka_transforms_save_router_rejects_blank_target_field() -> None:
    _seed_router_route_model()

    response = client.post(
        "/kafka/transforms/save",
        json={
            "transforms": [
                {
                    "route_name": "payment-posted",
                    "router_target_transforms": [
                        {
                            "target_id": "ledger-core",
                            "request_transform_rows": [{"source": "paymentId", "target": ""}],
                            "response_transform_rows": [],
                        }
                    ],
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "target is required" in response.json()["error"]


def test_kafka_transforms_save_router_rejects_row_without_source_constant_or_default() -> None:
    _seed_router_route_model()

    response = client.post(
        "/kafka/transforms/save",
        json={
            "transforms": [
                {
                    "route_name": "payment-posted",
                    "router_target_transforms": [
                        {
                            "target_id": "ledger-core",
                            "request_transform_rows": [{"source": "", "target": "transactionId"}],
                            "response_transform_rows": [],
                        }
                    ],
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "requires source, constant, or default" in response.json()["error"]


def test_kafka_transforms_save_router_accepts_default_only_row() -> None:
    _seed_router_route_model()

    response = client.post(
        "/kafka/transforms/save",
        json={
            "transforms": [
                {
                    "route_name": "payment-posted",
                    "router_target_transforms": [
                        {
                            "target_id": "ledger-core",
                            "request_transform_rows": [
                                {
                                    "source": "",
                                    "target": "currency",
                                    "default_value": "USD",
                                }
                            ],
                            "response_transform_rows": [],
                        }
                    ],
                }
            ]
        },
    )

    assert response.status_code == 200
    session = get_session()
    saved = session.kafka_route_transforms[0].router_target_transforms[0].request_transform_rows[0]
    assert saved.source == ""
    assert saved.target == "currency"
    assert saved.default_value == "USD"


def test_kafka_transforms_save_router_rejects_invalid_value_map() -> None:
    _seed_router_route_model()

    response = client.post(
        "/kafka/transforms/save",
        json={
            "transforms": [
                {
                    "route_name": "payment-posted",
                    "router_target_transforms": [
                        {
                            "target_id": "ledger-core",
                            "request_transform_rows": [
                                {
                                    "source": "status",
                                    "target": "decisionCode",
                                    "value_map": "[\"not\", \"an\", \"object\"]",
                                }
                            ],
                            "response_transform_rows": [],
                        }
                    ],
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "value_map must be a JSON object" in response.json()["error"]


def test_kafka_transforms_save_router_rejects_invalid_type_coercion() -> None:
    _seed_router_route_model()

    response = client.post(
        "/kafka/transforms/save",
        json={
            "transforms": [
                {
                    "route_name": "payment-posted",
                    "router_target_transforms": [
                        {
                            "target_id": "ledger-core",
                            "request_transform_rows": [
                                {
                                    "source": "amount",
                                    "target": "amountMinor",
                                    "type_coercion": "decimal_to_money",
                                }
                            ],
                            "response_transform_rows": [],
                        }
                    ],
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "type_coercion must be" in response.json()["error"]


def test_kafka_transforms_save_router_accepts_type_coercion_and_constant() -> None:
    _seed_router_route_model()

    response = client.post(
        "/kafka/transforms/save",
        json={
            "transforms": [
                {
                    "route_name": "payment-posted",
                    "router_target_transforms": [
                        {
                            "target_id": "ledger-core",
                            "request_transform_rows": [
                                {
                                    "source": "amount",
                                    "target": "amountMinor",
                                    "type_coercion": "major_to_minor_units",
                                },
                                {
                                    "source": "",
                                    "target": "channel",
                                    "constant": "STUDIO",
                                },
                            ],
                            "response_transform_rows": [],
                        }
                    ],
                }
            ]
        },
    )

    assert response.status_code == 200
    rows = get_session().kafka_route_transforms[0].router_target_transforms[0].request_transform_rows
    assert rows[0].type_coercion == "major_to_minor_units"
    assert rows[1].constant == "STUDIO"


def test_kafka_transforms_save_router_only_empty_payload_preserves_existing_router_rows() -> None:
    _seed_router_route_model()
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

    response = client.post("/kafka/transforms/save", json={"transforms": []})

    assert response.status_code == 200
    preserved = get_session().kafka_route_transforms[0]
    assert preserved.router_target_transforms[0].request_transform_rows[0].target == "transactionId"


def test_open_project_restores_request_reply_route_and_transform_values() -> None:
    session = _fully_populated_kafka_session(request_reply=True)
    project_bytes = serialize_project(snapshot_session(session)).encode("utf-8")

    open_response = client.post(
        "/project/open",
        files={"project_file": ("kafka-project.json", io.BytesIO(project_bytes), "application/json")},
        follow_redirects=False,
    )
    assert open_response.status_code == 303

    routes_response = client.get("/kafka/routes")
    assert routes_response.status_code == 200
    assert "request-reply" in routes_response.text
    assert "hub.reply.v1" in routes_response.text
    assert "core.reply.v1" in routes_response.text
    assert "X-Correlation-ID" in routes_response.text
    assert "upstream_reply_schema_content" in routes_response.text
    assert "verified" in routes_response.text
    assert "approved" in routes_response.text

    transforms_response = client.get("/kafka/transforms")
    assert transforms_response.status_code == 200
    assert "ledgerId" in transforms_response.text
    assert "approved" in transforms_response.text
    assert "declineReason" in transforms_response.text


def test_rules_get_for_kafka_shows_shared_navigation_without_entity_blocker() -> None:
    _fully_populated_kafka_session(request_reply=True)

    response = client.get("/rules")

    assert response.status_code == 200
    assert "No entity selection is required for Kafka integration" in response.text
    assert "Save &amp; Continue" in response.text
    assert 'href="/kafka/transforms"' in response.text
    assert "No entities selected yet" not in response.text


def test_request_reply_without_saved_reply_schema_content_uses_inferred_schema_from_response_mappings() -> None:
    session = _fully_populated_kafka_session(request_reply=True)
    session.kafka_route_models[0].upstream_reply_schema_content = ""
    session.kafka_route_models[0].downstream_reply_schema_content = ""
    save_session(session)

    report = build_completeness_report(session)
    blocker_messages = [item.message for item in report.manual()]

    assert all("reply schema content" not in message for message in blocker_messages)


def test_build_manifest_dict_for_kafka_contains_kafka_config_and_async_routes() -> None:
    session = _fully_populated_kafka_session(request_reply=False)
    manifest = build_manifest_dict(session)

    assert manifest["app_archetype"] == "kafka-integration"
    assert manifest["kafka_config"]["consumer_group"] == "payment-mediation-group"
    assert manifest["kafka_config"]["retry"]["max_attempts"] == 3
    assert len(manifest["async_routes"]) == 1
    assert manifest["async_routes"][0]["transform_mapping"] == "mappings/payment-posted.yaml"


def test_build_manifest_dict_request_reply_includes_reply_and_correlation_fields() -> None:
    session = _fully_populated_kafka_session(request_reply=True)
    manifest = build_manifest_dict(session)
    route = manifest["async_routes"][0]

    assert route["pattern"] == "request-reply"
    assert route["upstream_reply_topic"]["name"] == "hub.reply.v1"
    assert route["upstream_reply_topic"]["message_schema"] == "schemas/payment-posted-upstream-reply.json"
    assert route["downstream_reply_topic"]["name"] == "core.reply.v1"
    assert route["downstream_reply_topic"]["message_schema"] == "schemas/payment-posted-downstream-reply.json"
    assert route["correlation_id"] == {
        "source": "header",
        "field_name": "X-Correlation-ID",
    }
    assert route["reply_timeout_ms"] == 5000
    assert route["response_transform_mapping"] == "mappings/payment-posted-response.yaml"


def test_build_manifest_dict_fire_and_forget_omits_reply_and_correlation_fields() -> None:
    session = _fully_populated_kafka_session(request_reply=False)
    manifest = build_manifest_dict(session)
    route = manifest["async_routes"][0]

    assert route["pattern"] == "fire-and-forget"
    assert "upstream_reply_topic" not in route
    assert "downstream_reply_topic" not in route
    assert "correlation_id" not in route
    assert "reply_timeout_ms" not in route


def test_build_manifest_dict_router_includes_router_config_and_omits_fixed_route_fields() -> None:
    _seed_topic_pairs()
    session = get_session()
    session.kafka_route_models = [
        KafkaRouteModel(
            route_name="payment-posted",
            pattern="router",
            router_config=_router_route_payload()["router_config"],
        )
    ]
    # Re-validate through Pydantic because route helpers use dict payloads.
    session.kafka_route_models = [
        KafkaRouteModel.model_validate(session.kafka_route_models[0].model_dump())
    ]
    save_session(session)

    manifest = build_manifest_dict(get_session())
    route = manifest["async_routes"][0]

    assert route["pattern"] == "router"
    assert route["router_config"]["upstream_topics"][0]["id"] == "u1_intake"
    assert "body_field_path" not in route["router_config"]["upstream_topics"][0]["source_system_extraction"]
    assert route["router_config"]["outbound_schema"]["file"] == "schemas/payment-posted-outbound.json"
    assert route["router_config"]["targets"][0]["request_transform"]["file"] == "transforms/payment-posted-request.yaml"
    assert "upstream_topic" not in route
    assert "downstream_topic" not in route
    assert "transform_mapping" not in route
    assert "upstream_reply_topic" not in route
    assert "downstream_reply_topic" not in route
    assert "response_transform_mapping" not in route


def test_build_manifest_dict_pure_router_includes_router_config_without_topic_pairs() -> None:
    _seed_pure_router_route_model()

    manifest = build_manifest_dict(get_session())
    route = manifest["async_routes"][0]

    assert len(manifest["async_routes"]) == 1
    assert route["name"] == "payment-posted"
    assert route["pattern"] == "router"
    assert route["router_config"]["upstream_topics"][0]["name"] == "abc.payments.posted.v1"
    assert "upstream_topic" not in route
    assert "downstream_topic" not in route
    assert "transform_mapping" not in route
    reset_session()


def test_build_manifest_dict_router_fixed_nack_omits_inactive_per_source_system() -> None:
    nack_routing = _router_manifest_for_nack_routing(
        {
            "mode": "fixed",
            "per_source_system": {},
            "fixed_topic": "payments.router.nack.v1",
            "default_error_topic": "payments.router.error.v1",
        }
    )

    assert nack_routing["mode"] == "fixed"
    assert nack_routing["fixed_topic"] == "payments.router.nack.v1"
    assert nack_routing["default_error_topic"] == "payments.router.error.v1"
    assert "per_source_system" not in nack_routing


def test_build_manifest_dict_router_default_error_nack_omits_inactive_mode_fields() -> None:
    nack_routing = _router_manifest_for_nack_routing(
        {
            "mode": "default_error",
            "per_source_system": {"CRM": "payments.crm.errors.v1"},
            "fixed_topic": "payments.router.nack.v1",
            "default_error_topic": "payments.router.error.v1",
        }
    )

    assert nack_routing == {
        "mode": "default_error",
        "default_error_topic": "payments.router.error.v1",
    }


def test_build_manifest_dict_router_same_as_reply_nack_omits_inactive_per_source_system() -> None:
    nack_routing = _router_manifest_for_nack_routing(
        {
            "mode": "same_as_reply",
            "per_source_system": {"CRM": "payments.crm.errors.v1"},
            "default_error_topic": "payments.router.error.v1",
        }
    )

    assert nack_routing == {
        "mode": "same_as_reply",
        "default_error_topic": "payments.router.error.v1",
    }


def test_build_manifest_dict_router_per_source_system_nack_keeps_valid_entries() -> None:
    nack_routing = _router_manifest_for_nack_routing(
        {
            "mode": "per_source_system",
            "per_source_system": {
                "CRM": "payments.crm.errors.v1",
                "CORE": "payments.core.errors.v1",
            },
            "fixed_topic": "payments.router.nack.v1",
            "default_error_topic": "payments.router.error.v1",
        }
    )

    assert nack_routing == {
        "mode": "per_source_system",
        "per_source_system": {
            "CRM": "payments.crm.errors.v1",
            "CORE": "payments.core.errors.v1",
        },
        "default_error_topic": "payments.router.error.v1",
    }


def test_completeness_treats_valid_router_config_as_ready_without_transform_rows() -> None:
    _seed_topic_pairs()
    session = get_session()
    session.kafka_route_models = [
        KafkaRouteModel(
            route_name="payment-posted",
            pattern="router",
            router_config=_router_route_payload()["router_config"],
        )
    ]
    session.kafka_route_models = [
        KafkaRouteModel.model_validate(session.kafka_route_models[0].model_dump())
    ]
    session.kafka_route_transforms = []
    save_session(session)

    report = build_completeness_report(get_session())
    blocker_messages = [item.message for item in report.manual()]

    assert all("request transform mapping" not in message for message in blocker_messages)
    assert all("response transform mapping" not in message for message in blocker_messages)


def test_kafka_transforms_save_allows_router_only_routes_without_mapping_rows() -> None:
    _seed_topic_pairs()
    session = get_session()
    session.kafka_route_models = [
        KafkaRouteModel(
            route_name="payment-posted",
            pattern="router",
            router_config=_router_route_payload()["router_config"],
        )
    ]
    save_session(session)

    response = client.post("/kafka/transforms/save", json={"transforms": []})

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_export_write_kafka_package_writes_manifest_schemas_and_mappings(tmp_path) -> None:
    session = _fully_populated_kafka_session(request_reply=True)
    session.output_path = str(tmp_path)
    save_session(session)

    response = client.post("/export/write")
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert "app-definition.yaml" in payload["files"]
    assert "schemas/payment-posted-upstream.json" in payload["files"]
    assert "schemas/payment-posted-downstream.json" in payload["files"]
    assert "schemas/payment-posted-upstream-reply.json" in payload["files"]
    assert "schemas/payment-posted-downstream-reply.json" in payload["files"]
    assert "mappings/payment-posted.yaml" in payload["files"]
    assert "mappings/payment-posted-response.yaml" in payload["files"]

    reset_session()


def test_export_write_router_blocks_when_referenced_artifacts_are_missing(tmp_path) -> None:
    _seed_topic_pairs()
    session = get_session()
    session.output_path = str(tmp_path)
    session.kafka_route_models = [
        KafkaRouteModel(
            route_name="payment-posted",
            pattern="router",
            router_config=_valid_router_config(),
        )
    ]
    session.kafka_route_transforms = []
    save_session(session)

    response = client.post("/export/write")
    payload = response.json()

    assert response.status_code == 400
    assert payload["ok"] is False
    assert "references package file(s) that Studio did not write" in payload["error"]
    assert "schemas/payment-posted-target-response.json" in payload["error"]
    assert "transforms/payment-posted-request.yaml" in payload["error"]

    reset_session()


def test_export_write_router_includes_preexisting_referenced_artifacts(tmp_path) -> None:
    _seed_topic_pairs()
    session = get_session()
    session.output_path = str(tmp_path)
    session.kafka_route_models = [
        KafkaRouteModel(
            route_name="payment-posted",
            pattern="router",
            router_config=_valid_router_config(),
        )
    ]
    session.kafka_route_transforms = []
    project_dir = tmp_path / "payments"
    (project_dir / "schemas").mkdir(parents=True)
    (project_dir / "transforms").mkdir(parents=True)
    (project_dir / "schemas/payment-posted-target-response.json").write_text(
        '{"type":"object","properties":{"status":{"type":"string"}}}',
        encoding="utf-8",
    )
    (project_dir / "schemas/payment-posted-outbound.json").write_text(
        '{"type":"object","properties":{"status":{"type":"string"}}}',
        encoding="utf-8",
    )
    (project_dir / "transforms/payment-posted-request.yaml").write_text(
        "transforms: []\n",
        encoding="utf-8",
    )
    (project_dir / "transforms/payment-posted-response.yaml").write_text(
        "transforms: []\n",
        encoding="utf-8",
    )
    save_session(session)

    response = client.post("/export/write")
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert "schemas/payment-posted-upstream.json" in payload["files"]
    assert "schemas/payment-posted-downstream.json" in payload["files"]
    assert "schemas/payment-posted-target-response.json" in payload["files"]
    assert "schemas/payment-posted-outbound.json" in payload["files"]
    assert "transforms/payment-posted-request.yaml" in payload["files"]
    assert "transforms/payment-posted-response.yaml" in payload["files"]

    reset_session()


def test_export_download_zip_router_includes_preexisting_referenced_artifacts(tmp_path) -> None:
    _seed_topic_pairs()
    session = get_session()
    session.output_path = str(tmp_path)
    session.kafka_route_models = [
        KafkaRouteModel(
            route_name="payment-posted",
            pattern="router",
            router_config=_valid_router_config(),
        )
    ]
    session.kafka_route_transforms = []
    project_dir = tmp_path / "payments"
    (project_dir / "schemas").mkdir(parents=True)
    (project_dir / "transforms").mkdir(parents=True)
    (project_dir / "schemas/payment-posted-target-response.json").write_text(
        '{"type":"object","properties":{"status":{"type":"string"}}}',
        encoding="utf-8",
    )
    (project_dir / "schemas/payment-posted-outbound.json").write_text(
        '{"type":"object","properties":{"status":{"type":"string"}}}',
        encoding="utf-8",
    )
    (project_dir / "transforms/payment-posted-request.yaml").write_text(
        "transforms: []\n",
        encoding="utf-8",
    )
    (project_dir / "transforms/payment-posted-response.yaml").write_text(
        "transforms: []\n",
        encoding="utf-8",
    )
    save_session(session)

    response = client.get("/export/download-zip")

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        names = set(zf.namelist())
    assert "payments/schemas/payment-posted-upstream.json" in names
    assert "payments/schemas/payment-posted-downstream.json" in names
    assert "payments/schemas/payment-posted-target-response.json" in names
    assert "payments/schemas/payment-posted-outbound.json" in names
    assert "payments/transforms/payment-posted-request.yaml" in names
    assert "payments/transforms/payment-posted-response.yaml" in names

    reset_session()


def test_request_reply_timeout_below_1000ms_is_a_completeness_blocker() -> None:
    session = _fully_populated_kafka_session(request_reply=True)
    session.kafka_route_models[0].reply_timeout_ms = 500
    save_session(session)

    report = build_completeness_report(session)
    blocker_messages = [item.message for item in report.manual()]

    assert any("reply_timeout_ms must be at least 1000" in message for message in blocker_messages)
