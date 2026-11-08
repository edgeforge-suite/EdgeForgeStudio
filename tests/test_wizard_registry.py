from app.models.project import (
    DownstreamInterface,
    KafkaRouteModel,
    KafkaRouteTransform,
    KafkaTopicPair,
    PassthroughFlow,
    ProjectSession,
)
from app.services.nav_context import build_nav_context
from app.wizard_registry import get_steps


def test_get_steps_crud_returns_expected_8_slot_order() -> None:
    steps = get_steps("crud")
    assert [step.step_id for step in steps] == [
        "project-setup",
        "upstream-ingest",
        "entity-model",
        "data-handoffs",
        "downstream-interfaces",
        "rules-mappings",
        "review",
        "export-build-run",
    ]
    assert [step.position for step in steps] == list(range(1, 9))
    assert all(step.applicable for step in steps)


def test_get_steps_passthrough_returns_expected_8_slot_order_and_real_routes() -> None:
    steps = get_steps("passthrough-router")
    assert [step.step_id for step in steps] == [
        "project-setup",
        "passthrough-upstream",
        "passthrough-route",
        "data-handoffs",
        "downstream-interfaces",
        "rules-mappings",
        "review",
        "export-build-run",
    ]
    assert steps[1].route == "/upstream"
    assert steps[2].route == "/passthrough"
    assert steps[3].applicable is False
    assert steps[4].applicable is False


def test_get_steps_kafka_returns_expected_8_slot_order() -> None:
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
    assert steps[4].applicable is False
    assert steps[4].route is None


def test_get_steps_unknown_archetype_falls_back_to_crud() -> None:
    assert get_steps("unknown-archetype") == get_steps("crud")


def test_crud_steps_have_non_empty_route_and_step_id() -> None:
    steps = get_steps("crud")
    assert all(step.step_id for step in steps)
    assert all(step.route for step in steps)


def test_build_nav_context_marks_project_active_for_crud() -> None:
    session = ProjectSession(app_archetype="crud")
    nav = build_nav_context(session, "/")
    active_steps = [step for step in nav["nav_steps"] if step["is_active"]]
    assert len(active_steps) == 1
    assert active_steps[0]["step_id"] == "project-setup"
    assert nav["shell_step_index"] == 1
    assert nav["total_steps"] == 8


def test_build_nav_context_marks_review_active_for_both_archetypes() -> None:
    crud_nav = build_nav_context(ProjectSession(app_archetype="crud"), "/review")
    passthrough_nav = build_nav_context(
        ProjectSession(app_archetype="passthrough-router"), "/review"
    )
    assert [step["step_id"] for step in crud_nav["nav_steps"] if step["is_active"]] == ["review"]
    assert [step["step_id"] for step in passthrough_nav["nav_steps"] if step["is_active"]] == [
        "review"
    ]


def test_nav_steps_positions_are_one_indexed_and_contiguous() -> None:
    nav = build_nav_context(ProjectSession(app_archetype="crud"), "/rules")
    assert [step["position"] for step in nav["nav_steps"]] == list(range(1, 9))


def test_nav_context_marks_not_applicable_slots_for_passthrough() -> None:
    nav = build_nav_context(ProjectSession(app_archetype="passthrough-router"), "/passthrough")
    assert nav["nav_steps"][3]["state"] == "not-applicable"
    assert nav["nav_steps"][4]["state"] == "not-applicable"
    assert nav["nav_steps"][3]["route"] is None
    assert nav["nav_steps"][4]["route"] is None


def test_nav_context_uses_conservative_completion_for_crud() -> None:
    session = ProjectSession(
        app_name="DDA App",
        bounded_context="dda",
        app_archetype="crud",
        target_profile="springboot-standard-enterprise",
        output_path="/tmp/out",
        raw_spec_content="openapi: 3.0.0",
        selected_entity_names=["Account"],
        selected_operation_names=["createAccount"],
    )
    nav = build_nav_context(session, "/entities")

    assert nav["nav_steps"][0]["state"] == "complete"
    assert nav["nav_steps"][1]["state"] == "complete"
    assert nav["nav_steps"][2]["state"] == "active"
    assert nav["nav_steps"][3]["state"] == "open"


def test_nav_context_uses_conservative_completion_for_passthrough() -> None:
    session = ProjectSession(
        app_name="Router",
        bounded_context="payments",
        app_archetype="passthrough-router",
        target_profile="springboot-legacy-compatible",
        output_path="/tmp/out",
        raw_spec_content="openapi: 3.0.0",
        downstream_interfaces=[DownstreamInterface(name="sct-api", type="rest-api")],
        passthrough_flow=PassthroughFlow(
            upstream_operation_name="routePayment",
            route_field="paymentType",
            routes=[{"match": "A", "target": "SCT"}],
            default_target="SCT",
            transforms=[{"source": "amount", "target": "settlementAmount"}],
        ),
    )
    nav = build_nav_context(session, "/passthrough")

    assert nav["nav_steps"][0]["state"] == "complete"
    assert nav["nav_steps"][1]["state"] == "complete"
    assert nav["nav_steps"][2]["state"] == "active"


def test_nav_context_uses_conservative_completion_for_kafka() -> None:
    session = ProjectSession(
        app_name="Payment Mediation",
        bounded_context="payments",
        app_archetype="kafka-integration",
        target_profile="springboot-standard-enterprise",
        output_path="/tmp/out",
        kafka_topic_pairs=[
            KafkaTopicPair(route_name="payment-posted", upstream_topic="a", downstream_topic="b")
        ],
        kafka_route_models=[KafkaRouteModel(route_name="payment-posted", pattern="fire-and-forget")],
        kafka_route_transforms=[KafkaRouteTransform(route_name="payment-posted")],
    )
    nav = build_nav_context(session, "/kafka/transforms")

    assert nav["nav_steps"][1]["state"] == "complete"
    assert nav["nav_steps"][2]["state"] == "complete"
    assert nav["nav_steps"][3]["state"] == "active"
    assert nav["nav_steps"][4]["state"] == "not-applicable"
