"""Kafka route inventory helpers shared by Studio flow services."""

from __future__ import annotations

from app.models.project import KafkaRouteModel, ProjectSession


def fixed_route_names(session: ProjectSession) -> list[str]:
    """Route names owned by fixed topic-pair authoring."""
    return [pair.route_name for pair in session.kafka_topic_pairs if pair.route_name]


def router_route_models(session: ProjectSession) -> list[KafkaRouteModel]:
    """Router route models that are complete enough to act as route anchors."""
    return [
        model
        for model in session.kafka_route_models
        if model.route_name and model.pattern == "router" and model.router_config is not None
    ]


def router_route_names(session: ProjectSession) -> list[str]:
    return [model.route_name for model in router_route_models(session)]


def all_kafka_route_names(session: ProjectSession) -> list[str]:
    """All route names, preserving fixed-route order before router-only routes."""
    names: list[str] = []
    seen: set[str] = set()
    for route_name in fixed_route_names(session) + router_route_names(session):
        if route_name in seen:
            continue
        seen.add(route_name)
        names.append(route_name)
    return names


def has_kafka_route_anchors(session: ProjectSession) -> bool:
    return bool(fixed_route_names(session) or router_route_names(session))
