"""Kafka-integration authoring flow."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.models.project import (
    KafkaConfig,
    KafkaRouteModel,
    KafkaRouterCondition,
    KafkaRouterConfig,
    KafkaRouterCorrelationStore,
    KafkaRouterExtraction,
    KafkaRouterNackRouting,
    KafkaRouterPayloadLogging,
    KafkaRouterRetry,
    KafkaRouterRoutingField,
    KafkaRouterRoutingRules,
    KafkaRouterRule,
    KafkaRouterSchemaRef,
    KafkaRouterTarget,
    KafkaRouterTargetTransform,
    KafkaRouterTimeout,
    KafkaRouterTransformRef,
    KafkaRouterTransformRow,
    KafkaRouterUpstreamTopic,
    KafkaRouteTransform,
    KafkaTopicPair,
    KafkaTransformRow,
)
from app.paths import TEMPLATE_DIR
from app.services.assist_service import AssistService
from app.services.kafka_route_inventory import (
    all_kafka_route_names,
    fixed_route_names,
    has_kafka_route_anchors,
    router_route_models,
    router_route_names,
)
from app.services.kafka_schema_service import infer_reply_schema_content
from app.services.nav_context import build_nav_context
from app.services.session_context import (
    get_current_session,
    save_current_session,
    save_current_session_if_workspace_changed,
    workspace_session_marker,
)
from app.services.suggestion_review_state import record_review_history_without_evidence

router = APIRouter(prefix="/kafka")
templates = Jinja2Templates(directory=TEMPLATE_DIR)
assist_service = AssistService()

ROUTER_CONDITION_OPERATORS = {"eq", "in", "lt", "lte", "gt", "gte", "not_null"}
ROUTER_TYPE_COERCIONS = {"major_to_minor_units", "minor_to_major_units"}
MAPPING_REVIEW_STATUSES = {"accepted", "edited", "rejected"}


def _kafka_guard(request: Request):
    session = get_current_session(request)
    if session.app_archetype != "kafka-integration":
        return session, RedirectResponse("/", status_code=303)
    return session, None


def _text(value) -> str:
    return str(value or "").strip()


def _int_value(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _schema_entity_name(schema_content: str, schema_path: str, fallback: str) -> str:
    candidate = ""
    if schema_content:
        try:
            schema = json.loads(schema_content)
        except json.JSONDecodeError:
            schema = {}
        if isinstance(schema, dict):
            candidate = _text(schema.get("title")) or _text(schema.get("$id"))
    if not candidate and schema_path:
        candidate = schema_path.rsplit("/", 1)[-1]
    if candidate.endswith(".json"):
        candidate = candidate[:-5]
    return _text(candidate) or fallback


def _schema_ref_entity_name(schema_ref: KafkaRouterSchemaRef, fallback: str) -> str:
    return _schema_entity_name("", schema_ref.file, fallback)


def _router_topic_summary(session) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for model in router_route_models(session):
        router_config = model.router_config
        if router_config is None:
            continue
        summaries.append(
            {
                "route_name": model.route_name,
                "upstream_topics": [
                    {"id": topic.id, "name": topic.name}
                    for topic in router_config.upstream_topics
                ],
                "targets": [
                    {
                        "id": target.id,
                        "request_schema": target.request_schema.file,
                        "response_schema": target.response_schema.file,
                    }
                    for target in router_config.targets
                ],
                "inbound_schema": router_config.inbound_schema.file,
                "outbound_schema": router_config.outbound_schema.file,
            }
        )
    return summaries


def _kafka_mapping_contexts(
    session,
    route_model: KafkaRouteModel,
) -> list[dict[str, str]]:
    if route_model.pattern == "router":
        return []

    topic_pair = next(
        (pair for pair in session.kafka_topic_pairs if pair.route_name == route_model.route_name),
        None,
    )
    if topic_pair is None:
        return []

    route_name = route_model.route_name
    contexts = [
        {
            "route_name": route_name,
            "direction": "request",
            "source_entity": _schema_entity_name(
                topic_pair.upstream_schema_content,
                topic_pair.upstream_schema_path,
                f"{route_name}-upstream",
            ),
            "target_entity": _schema_entity_name(
                topic_pair.downstream_schema_content,
                topic_pair.downstream_schema_path,
                f"{route_name}-downstream",
            ),
        }
    ]
    if route_model.pattern == "request-reply":
        contexts.append(
            {
                "route_name": route_name,
                "direction": "response",
                "source_entity": _schema_entity_name(
                    route_model.downstream_reply_schema_content,
                    route_model.downstream_reply_schema_path,
                    f"{route_name}-downstream-reply",
                ),
                "target_entity": _schema_entity_name(
                    route_model.upstream_reply_schema_content,
                    route_model.upstream_reply_schema_path,
                    f"{route_name}-upstream-reply",
                ),
            }
        )
    return contexts


def _kafka_router_transform_contexts(
    route_model: KafkaRouteModel | None,
    *,
    target_id: str = "",
    direction: str = "",
) -> list[dict[str, str]]:
    if route_model is None or route_model.pattern != "router" or route_model.router_config is None:
        return []

    router_config = route_model.router_config
    normalized_target_id = _text(target_id)
    normalized_direction = _text(direction)
    contexts: list[dict[str, str]] = []
    for target in router_config.targets:
        if normalized_target_id and target.id != normalized_target_id:
            continue
        directions = [normalized_direction] if normalized_direction else ["request", "response"]
        for current_direction in directions:
            if current_direction == "request":
                if not router_config.inbound_schema.file or not target.request_schema.file:
                    continue
                source_entity = _schema_ref_entity_name(
                    router_config.inbound_schema,
                    f"{route_model.route_name}-inbound",
                )
                target_entity = _schema_ref_entity_name(
                    target.request_schema,
                    f"{target.id}-request",
                )
            elif current_direction == "response":
                if not target.response_schema.file or not router_config.outbound_schema.file:
                    continue
                source_entity = _schema_ref_entity_name(
                    target.response_schema,
                    f"{target.id}-response",
                )
                target_entity = _schema_ref_entity_name(
                    router_config.outbound_schema,
                    f"{route_model.route_name}-outbound",
                )
            else:
                continue

            contexts.append(
                {
                    "route_name": route_model.route_name,
                    "target_id": target.id,
                    "direction": current_direction,
                    "source_entity": source_entity,
                    "target_entity": target_entity,
                }
            )
    return contexts


def _badge_dict(badge) -> dict[str, Any]:
    return badge.model_dump() if hasattr(badge, "model_dump") else {
        "scope": badge.scope,
        "label": badge.label,
        "count": badge.count,
        "entity": badge.entity,
        "context": badge.context,
        "drawer_url": badge.drawer_url,
    }


def _successful_outcome_ids(ks_result: dict[str, Any], decisions: list[dict[str, Any]]) -> set[str]:
    outcomes = ks_result.get("outcomes", [])
    if isinstance(outcomes, list) and outcomes:
        return {
            str(outcome.get("suggestion_id"))
            for outcome in outcomes
            if isinstance(outcome, dict)
            and outcome.get("success", True)
            and outcome.get("suggestion_id") is not None
        }
    return {decision["suggestion_id"] for decision in decisions} if ks_result.get("success", True) else set()


def _ks_review_payload(decision: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "suggestion_id": decision["suggestion_id"],
        "status": decision["status"],
    }
    if decision["status"] == "edited":
        payload["edited_payload"] = decision["edited_payload"]
    return payload


def _mapping_payload(decision: dict[str, Any]) -> dict[str, Any]:
    payload = dict(decision["payload"])
    if decision["status"] == "edited" and decision.get("edited_payload"):
        payload.update(decision["edited_payload"])
    return payload


def _transform_payload(decision: dict[str, Any]) -> dict[str, Any]:
    payload = dict(decision["payload"])
    if decision["status"] == "edited" and decision.get("edited_payload"):
        edited_payload = decision["edited_payload"]
        payload.update(edited_payload)
        if "source" in edited_payload:
            payload.pop("source_field", None)
        if "target" in edited_payload:
            payload.pop("target_field", None)
    return payload


def _payload_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _normalize_mapping_decisions(raw_decisions: Any) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(raw_decisions, list):
        return [], ["Review decisions must be a list."]
    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, item in enumerate(raw_decisions):
        if not isinstance(item, dict):
            errors.append(f"Decision {index + 1} must be an object.")
            continue
        suggestion_id = _text(item.get("suggestion_id"))
        suggestion_type = _text(item.get("suggestion_type"))
        status = _text(item.get("status"))
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        edited_payload = item.get("edited_payload") if isinstance(item.get("edited_payload"), dict) else None
        manifest_path = _text(item.get("manifest_path"))
        if not suggestion_id:
            errors.append(f"Decision {index + 1} must include suggestion_id.")
            continue
        if suggestion_type != "mapping":
            errors.append(f"Decision {index + 1} has unsupported suggestion_type '{suggestion_type}'.")
            continue
        if status not in MAPPING_REVIEW_STATUSES:
            errors.append(f"Decision {index + 1} has unsupported status '{status}'.")
            continue
        if status in {"accepted", "edited"} and not payload:
            errors.append(f"Decision {index + 1} requires a mapping payload for {status} review.")
            continue
        if status == "edited" and not edited_payload:
            errors.append(f"Decision {index + 1} requires edited_payload for edited review.")
            continue
        normalized.append(
            {
                "suggestion_id": suggestion_id,
                "suggestion_type": suggestion_type,
                "status": status,
                "payload": payload,
                "edited_payload": edited_payload,
                "manifest_path": manifest_path,
            }
        )
    return normalized, errors


def _normalize_transform_decisions(raw_decisions: Any) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(raw_decisions, list):
        return [], ["Review decisions must be a list."]
    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, item in enumerate(raw_decisions):
        if not isinstance(item, dict):
            errors.append(f"Decision {index + 1} must be an object.")
            continue
        suggestion_id = _text(item.get("suggestion_id"))
        suggestion_type = _text(item.get("suggestion_type"))
        status = _text(item.get("status"))
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        edited_payload = item.get("edited_payload") if isinstance(item.get("edited_payload"), dict) else None
        manifest_path = _text(item.get("manifest_path"))
        if not suggestion_id:
            errors.append(f"Decision {index + 1} must include suggestion_id.")
            continue
        if suggestion_type not in {"transform", "transforms"}:
            errors.append(f"Decision {index + 1} has unsupported suggestion_type '{suggestion_type}'.")
            continue
        if status not in MAPPING_REVIEW_STATUSES:
            errors.append(f"Decision {index + 1} has unsupported status '{status}'.")
            continue
        if status in {"accepted", "edited"} and not payload:
            errors.append(f"Decision {index + 1} requires a transform payload for {status} review.")
            continue
        if status == "edited" and not edited_payload:
            errors.append(f"Decision {index + 1} requires edited_payload for edited review.")
            continue
        normalized.append(
            {
                "suggestion_id": suggestion_id,
                "suggestion_type": "transform",
                "status": status,
                "payload": payload,
                "edited_payload": edited_payload,
                "manifest_path": manifest_path,
            }
        )
    return normalized, errors


def _validate_kafka_mapping_payload(
    session,
    payload: dict[str, Any],
) -> tuple[str, str, str, str | None]:
    route_name = _payload_text(payload, "route_name")
    direction = _payload_text(payload, "direction") or "request"
    source_entity = _payload_text(payload, "source_entity")
    target_entity = _payload_text(payload, "target_entity")
    source = _payload_text(payload, "source_field", "source")
    target = _payload_text(payload, "target_field", "target")
    mapping_type = (_payload_text(payload, "mapping_type", "type") or "copy").lower()

    if mapping_type != "copy":
        return "", "", "", f"Unsupported mapping_type '{mapping_type}'. Studio can apply copy mappings only in this PR."
    if not route_name:
        return "", "", "", "Mapping suggestion payload requires route_name."
    if direction not in {"request", "response"}:
        return "", "", "", "Kafka mapping suggestion direction must be request or response."
    if not source or not target:
        return "", "", "", "Mapping suggestions require source_field and target_field."

    route_model = next((model for model in session.kafka_route_models if model.route_name == route_name), None)
    if route_model is None:
        return "", "", "", f"Mapping suggestion references unknown route '{route_name}'."
    if route_model.pattern == "router":
        return "", "", "", "Kafka router transform suggestions are out of scope for this PR."
    if direction == "response" and route_model.pattern != "request-reply":
        return "", "", "", f"Route '{route_name}' does not support response mappings."
    if not any(
        context["route_name"] == route_name
        and context["direction"] == direction
        and context["source_entity"] == source_entity
        and context["target_entity"] == target_entity
        for context in _kafka_mapping_contexts(session, route_model)
    ):
        return "", "", "", "Mapping suggestion no longer matches the current Kafka route context."
    return source, target, route_name, None


def _parse_transform_value_map(
    raw_value_map: Any,
    *,
    route_name: str,
    target_id: str,
    direction: str,
) -> tuple[dict[str, str], str | None]:
    if raw_value_map is None or raw_value_map == "":
        return {}, None
    if isinstance(raw_value_map, dict):
        return {str(key): str(value) for key, value in raw_value_map.items()}, None
    raw_text = _text(raw_value_map)
    if not raw_text:
        return {}, None
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return {}, f"Route '{route_name}' target '{target_id}' {direction} value_map must be a JSON object."
    if not isinstance(parsed, dict):
        return {}, f"Route '{route_name}' target '{target_id}' {direction} value_map must be a JSON object."
    return {str(key): str(value) for key, value in parsed.items()}, None


def _validate_kafka_transform_payload(
    session,
    payload: dict[str, Any],
) -> tuple[KafkaRouterTransformRow | None, str, str, str, str | None]:
    route_name = _payload_text(payload, "route_name")
    target_id = _payload_text(payload, "target_id")
    direction = _payload_text(payload, "direction")
    source = _payload_text(payload, "source", "source_field")
    target = _payload_text(payload, "target", "target_field")
    default_value = _payload_text(payload, "default_value", "default") or None
    constant = _payload_text(payload, "constant") or None
    type_coercion = _payload_text(payload, "type_coercion") or None

    if not route_name:
        return None, "", "", "", "Transform suggestion payload requires route_name."
    if not target_id:
        return None, "", "", "", "Transform suggestion payload requires target_id."
    if direction not in {"request", "response"}:
        return None, "", "", "", "Transform suggestion direction must be request or response."
    if not target:
        return None, "", "", "", "Transform suggestions require target."
    if not source and constant is None and default_value is None:
        return None, "", "", "", "Transform suggestions require source, constant, or default_value."
    if type_coercion and type_coercion not in ROUTER_TYPE_COERCIONS:
        return None, "", "", "", "Transform suggestion type_coercion must be major_to_minor_units or minor_to_major_units."

    route_model = next((model for model in session.kafka_route_models if model.route_name == route_name), None)
    if route_model is None:
        return None, "", "", "", f"Transform suggestion references unknown route '{route_name}'."
    if route_model.pattern != "router" or route_model.router_config is None:
        return None, "", "", "", "Transform suggestions can only apply to Kafka router routes."

    contexts = _kafka_router_transform_contexts(route_model, target_id=target_id, direction=direction)
    if not contexts:
        return None, "", "", "", "Transform suggestion no longer matches the current Kafka router target context."

    source_entity = _payload_text(payload, "source_entity")
    target_entity = _payload_text(payload, "target_entity")
    if source_entity or target_entity:
        if not any(
            (not source_entity or context["source_entity"] == source_entity)
            and (not target_entity or context["target_entity"] == target_entity)
            for context in contexts
        ):
            return None, "", "", "", "Transform suggestion no longer matches the current Kafka router schema context."

    value_map, value_map_error = _parse_transform_value_map(
        payload.get("value_map"),
        route_name=route_name,
        target_id=target_id,
        direction=direction,
    )
    if value_map_error:
        return None, "", "", "", value_map_error

    return (
        KafkaRouterTransformRow(
            source=source,
            target=target,
            default_value=default_value,
            constant=constant,
            value_map=value_map,
            type_coercion=type_coercion,
        ),
        route_name,
        target_id,
        direction,
        None,
    )


def _route_transform_for(session, route_name: str) -> KafkaRouteTransform:
    for transform in session.kafka_route_transforms:
        if transform.route_name == route_name:
            return transform
    transform = KafkaRouteTransform(route_name=route_name)
    session.kafka_route_transforms.append(transform)
    return transform


def _append_kafka_mapping_if_missing(
    session,
    *,
    route_name: str,
    direction: str,
    source: str,
    target: str,
) -> bool:
    transform = _route_transform_for(session, route_name)
    rows = transform.response_mappings if direction == "response" else transform.mappings
    for row in rows:
        if row.source_field == source and row.target_field == target:
            return False
    rows.append(KafkaTransformRow(source_field=source, target_field=target))
    return True


def _router_target_transform_for(
    transform: KafkaRouteTransform,
    target_id: str,
) -> KafkaRouterTargetTransform:
    for target_transform in transform.router_target_transforms:
        if target_transform.target_id == target_id:
            return target_transform
    target_transform = KafkaRouterTargetTransform(target_id=target_id)
    transform.router_target_transforms.append(target_transform)
    return target_transform


def _append_kafka_router_transform_if_missing(
    session,
    *,
    route_name: str,
    target_id: str,
    direction: str,
    row: KafkaRouterTransformRow,
) -> bool:
    transform = _route_transform_for(session, route_name)
    target_transform = _router_target_transform_for(transform, target_id)
    rows = (
        target_transform.response_transform_rows
        if direction == "response"
        else target_transform.request_transform_rows
    )
    for existing in rows:
        if existing.source == row.source and existing.target == row.target:
            if existing == row:
                return False
            existing.default_value = row.default_value
            existing.constant = row.constant
            existing.value_map = dict(row.value_map)
            existing.type_coercion = row.type_coercion
            return True
    rows.append(row)
    return True


def _sanitized_transform_edit_payload(row: KafkaRouterTransformRow) -> dict[str, Any]:
    payload: dict[str, Any] = {"target": row.target}
    if row.source:
        payload["source"] = row.source
    if row.default_value is not None:
        payload["default_value"] = row.default_value
    if row.constant is not None:
        payload["constant"] = row.constant
    if row.value_map:
        payload["value_map"] = dict(row.value_map)
    if row.type_coercion:
        payload["type_coercion"] = row.type_coercion
    return payload


def _kafka_mapping_manifest_path(route_name: str, direction: str, source: str, target: str) -> str:
    return f"async_routes.{route_name}.transform_mapping.{direction}.{source}.{target}"


def _kafka_router_transform_manifest_path(
    route_name: str,
    target_id: str,
    direction: str,
    row: KafkaRouterTransformRow,
) -> str:
    source = row.source or ("constant" if row.constant is not None else "default")
    return f"async_routes.{route_name}.router_config.targets.{target_id}.{direction}_transform.{source}.{row.target}"


def _kafka_mapping_review_context(
    route_name: str,
    direction: str,
    source: str,
    target: str,
    *,
    source_entity: str = "",
    target_entity: str = "",
) -> dict[str, str]:
    context = {
        "mapping_context": "kafka",
        "route_name": route_name,
        "direction": direction,
        "source_field": source,
        "target_field": target,
    }
    if source_entity:
        context["source_entity"] = source_entity
    if target_entity:
        context["target_entity"] = target_entity
    return context


def _kafka_mapping_review_context_from_decision(decision: dict[str, Any]) -> dict[str, str] | None:
    payload = decision["payload"] if isinstance(decision.get("payload"), dict) else {}
    edited_payload = decision["edited_payload"] if isinstance(decision.get("edited_payload"), dict) else {}
    route_name = _payload_text(edited_payload, "route_name") or _payload_text(payload, "route_name")
    direction = _payload_text(edited_payload, "direction") or _payload_text(payload, "direction") or "request"
    source = (
        _payload_text(edited_payload, "source_field", "source")
        or _payload_text(payload, "source_field", "source")
    )
    target = (
        _payload_text(edited_payload, "target_field", "target")
        or _payload_text(payload, "target_field", "target")
    )
    source_entity = (
        _payload_text(edited_payload, "source_entity")
        or _payload_text(payload, "source_entity")
    )
    target_entity = (
        _payload_text(edited_payload, "target_entity")
        or _payload_text(payload, "target_entity")
    )
    if not any((route_name, direction, source, target, source_entity, target_entity)):
        return None
    return _kafka_mapping_review_context(
        route_name,
        direction,
        source,
        target,
        source_entity=source_entity,
        target_entity=target_entity,
    )


def _kafka_router_transform_review_context(
    route_name: str,
    target_id: str,
    direction: str,
    row: KafkaRouterTransformRow,
    *,
    source_entity: str = "",
    target_entity: str = "",
) -> dict[str, Any]:
    context = {
        "mapping_context": "kafka_router_transform",
        "route_name": route_name,
        "target_id": target_id,
        "direction": direction,
        "source": row.source,
        "target": row.target,
        "default_value": row.default_value,
        "constant": row.constant,
        "value_map": row.value_map,
        "type_coercion": row.type_coercion,
    }
    if source_entity:
        context["source_entity"] = source_entity
    if target_entity:
        context["target_entity"] = target_entity
    return context


def _kafka_router_transform_review_context_from_decision(decision: dict[str, Any]) -> dict[str, Any] | None:
    payload = decision["payload"] if isinstance(decision.get("payload"), dict) else {}
    edited_payload = decision["edited_payload"] if isinstance(decision.get("edited_payload"), dict) else {}
    route_name = _payload_text(edited_payload, "route_name") or _payload_text(payload, "route_name")
    target_id = _payload_text(edited_payload, "target_id") or _payload_text(payload, "target_id")
    direction = _payload_text(edited_payload, "direction") or _payload_text(payload, "direction")
    source = _payload_text(edited_payload, "source", "source_field") or _payload_text(payload, "source", "source_field")
    target = _payload_text(edited_payload, "target", "target_field") or _payload_text(payload, "target", "target_field")
    source_entity = (
        _payload_text(edited_payload, "source_entity")
        or _payload_text(payload, "source_entity")
    )
    target_entity = (
        _payload_text(edited_payload, "target_entity")
        or _payload_text(payload, "target_entity")
    )
    if not any((route_name, target_id, direction, source, target, source_entity, target_entity)):
        return None
    context: dict[str, Any] = {
        "mapping_context": "kafka_router_transform",
        "route_name": route_name,
        "target_id": target_id,
        "direction": direction,
        "source": source,
        "target": target,
        "default_value": _payload_text(edited_payload, "default_value", "default")
        or _payload_text(payload, "default_value", "default"),
        "constant": _payload_text(edited_payload, "constant") or _payload_text(payload, "constant"),
        "value_map": edited_payload.get("value_map") if "value_map" in edited_payload else payload.get("value_map"),
        "type_coercion": _payload_text(edited_payload, "type_coercion") or _payload_text(payload, "type_coercion"),
    }
    if source_entity:
        context["source_entity"] = source_entity
    if target_entity:
        context["target_entity"] = target_entity
    return {key: value for key, value in context.items() if value not in ("", None, {}, [])}


def _schema_ref(raw: dict | None, default_file: str = "") -> KafkaRouterSchemaRef:
    raw = raw or {}
    return KafkaRouterSchemaRef(
        file=_text(raw.get("file")) or default_file,
        validation_policy=_text(raw.get("validation_policy")) or "strict",
        failure_behavior=_text(raw.get("failure_behavior")) or "nack",
    )


def _transform_ref(raw: dict | None) -> KafkaRouterTransformRef:
    raw = raw or {}
    return KafkaRouterTransformRef(file=_text(raw.get("file")))


def _parse_per_source_system(raw_value) -> dict[str, str]:
    if isinstance(raw_value, dict):
        return {
            _text(source): _text(topic)
            for source, topic in raw_value.items()
            if _text(source) or _text(topic)
        }
    if isinstance(raw_value, list):
        mappings: dict[str, str] = {}
        for row in raw_value:
            if not isinstance(row, dict):
                continue
            source = _text(row.get("source_system"))
            topic = _text(row.get("topic"))
            if source or topic:
                mappings[source] = topic
        return mappings
    return {}


def _validate_schema_ref(ref: KafkaRouterSchemaRef, label: str, errors: list[str]) -> None:
    if not ref.file:
        errors.append(f"{label} file is required.")
    if ref.validation_policy not in {"strict", "lenient"}:
        errors.append(f"{label} validation_policy must be strict or lenient.")
    if ref.failure_behavior != "nack":
        errors.append(f"{label} failure_behavior must be nack.")


def _validate_extraction(extraction: KafkaRouterExtraction, label: str, errors: list[str]) -> None:
    if extraction.mode not in {"header", "body_field"}:
        errors.append(f"{label} mode must be header or body_field.")
    if extraction.mode == "header" and not extraction.header_key:
        errors.append(f"{label} header extraction requires header_key.")
    if extraction.mode == "body_field" and not extraction.body_field_path:
        errors.append(f"{label} body-field extraction requires body_field_path.")


def _parse_router_config(
    raw_config: dict | None,
    route_name: str,
    topic_pair: KafkaTopicPair | None,
    kafka_config: KafkaConfig,
) -> tuple[KafkaRouterConfig, list[str]]:
    raw_config = raw_config or {}
    errors: list[str] = []

    upstream_topics: list[KafkaRouterUpstreamTopic] = []
    for index, raw_topic in enumerate(raw_config.get("upstream_topics") or []):
        source_extraction = raw_topic.get("source_system_extraction") or {}
        reply_extraction = raw_topic.get("reply_destination_extraction") or {}
        upstream = KafkaRouterUpstreamTopic(
            id=_text(raw_topic.get("id")) or f"{route_name}-upstream-{index + 1}",
            name=_text(raw_topic.get("name")) or (topic_pair.upstream_topic if topic_pair else ""),
            consumer_group=_text(raw_topic.get("consumer_group")) or kafka_config.consumer_group,
            source_system_extraction=KafkaRouterExtraction(
                mode=_text(source_extraction.get("mode")) or "header",
                header_key=_text(source_extraction.get("header_key")),
                body_field_path=_text(source_extraction.get("body_field_path")),
            ),
            reply_destination_extraction=KafkaRouterExtraction(
                mode=_text(reply_extraction.get("mode")) or "header",
                header_key=_text(reply_extraction.get("header_key")),
                body_field_path=_text(reply_extraction.get("body_field_path")),
            ),
        )
        if not upstream.id:
            errors.append("Router upstream topic id is required.")
        if not upstream.name:
            errors.append("Router upstream topic name is required.")
        if not upstream.consumer_group:
            errors.append("Router upstream topic consumer_group is required.")
        _validate_extraction(upstream.source_system_extraction, "source_system_extraction", errors)
        _validate_extraction(upstream.reply_destination_extraction, "reply_destination_extraction", errors)
        upstream_topics.append(upstream)

    inbound_schema = _schema_ref(
        raw_config.get("inbound_schema"),
        (topic_pair.upstream_schema_path if topic_pair else "") or f"schemas/{route_name}-upstream.json",
    )
    outbound_schema = _schema_ref(raw_config.get("outbound_schema"))
    _validate_schema_ref(inbound_schema, "inbound_schema", errors)
    _validate_schema_ref(outbound_schema, "outbound_schema", errors)

    raw_routing = raw_config.get("routing_rules") or {}
    routing_fields = [
        KafkaRouterRoutingField(name=_text(row.get("name")), json_path=_text(row.get("json_path")))
        for row in raw_routing.get("routing_fields") or []
        if _text(row.get("name")) or _text(row.get("json_path"))
    ]
    declared_fields = {field.name for field in routing_fields if field.name}
    for field in routing_fields:
        if not field.name or not field.json_path:
            errors.append("Each routing field requires name and json_path.")

    rules: list[KafkaRouterRule] = []
    for raw_rule in raw_routing.get("rules") or []:
        conditions: list[KafkaRouterCondition] = []
        for raw_condition in raw_rule.get("conditions") or []:
            condition = KafkaRouterCondition(
                field=_text(raw_condition.get("field")),
                operator=_text(raw_condition.get("operator")) or "eq",
                value=_text(raw_condition.get("value")),
            )
            if condition.operator not in ROUTER_CONDITION_OPERATORS:
                errors.append(
                    f"Routing rule '{_text(raw_rule.get('id')) or '<unnamed>'}' uses unsupported operator '{condition.operator}'."
                )
            if condition.field not in declared_fields:
                errors.append(
                    f"Routing rule '{_text(raw_rule.get('id')) or '<unnamed>'}' condition field must reference a declared routing field."
                )
            if condition.operator != "not_null" and not condition.value:
                errors.append(
                    f"Routing rule '{_text(raw_rule.get('id')) or '<unnamed>'}' condition value is required."
                )
            conditions.append(condition)
        rule = KafkaRouterRule(
            id=_text(raw_rule.get("id")),
            conditions=conditions,
            target=_text(raw_rule.get("target")),
        )
        if not rule.id:
            errors.append("Each routing rule requires id.")
        if not rule.target:
            errors.append(f"Routing rule '{rule.id or '<unnamed>'}' target is required.")
        if not rule.conditions:
            errors.append(f"Routing rule '{rule.id or '<unnamed>'}' requires at least one condition.")
        rules.append(rule)

    default_target = _text(raw_routing.get("default_target")) or None
    routing_rules = KafkaRouterRoutingRules(
        routing_fields=routing_fields,
        rules=rules,
        default_target=default_target,
    )

    targets: list[KafkaRouterTarget] = []
    for raw_target in raw_config.get("targets") or []:
        request_topic = _text(raw_target.get("request_topic")) or (
            topic_pair.downstream_topic if topic_pair else ""
        )
        target = KafkaRouterTarget(
            id=_text(raw_target.get("id")),
            request_topic=request_topic,
            response_topic=_text(raw_target.get("response_topic")),
            request_schema=_schema_ref(raw_target.get("request_schema")),
            response_schema=_schema_ref(raw_target.get("response_schema")),
            request_transform=_transform_ref(raw_target.get("request_transform")),
            response_transform=_transform_ref(raw_target.get("response_transform")),
            retry=KafkaRouterRetry(
                max_attempts=_int_value((raw_target.get("retry") or {}).get("max_attempts"), 3),
                backoff_ms=_int_value((raw_target.get("retry") or {}).get("backoff_ms"), 1000),
                dlq_topic=_text((raw_target.get("retry") or {}).get("dlq_topic")),
            ),
            timeout_ms=_int_value(raw_target.get("timeout_ms"), 30000),
        )
        if not target.id:
            errors.append("Each router target requires id.")
        if not target.request_topic:
            errors.append(f"Router target '{target.id or '<unnamed>'}' request_topic is required.")
        if not target.response_topic:
            errors.append(f"Router target '{target.id or '<unnamed>'}' response_topic is required.")
        _validate_schema_ref(target.request_schema, f"Router target '{target.id or '<unnamed>'}' request_schema", errors)
        _validate_schema_ref(target.response_schema, f"Router target '{target.id or '<unnamed>'}' response_schema", errors)
        if not target.request_transform.file:
            errors.append(f"Router target '{target.id or '<unnamed>'}' request_transform.file is required.")
        if not target.response_transform.file:
            errors.append(f"Router target '{target.id or '<unnamed>'}' response_transform.file is required.")
        if not target.retry.dlq_topic:
            errors.append(f"Router target '{target.id or '<unnamed>'}' retry.dlq_topic is required.")
        if target.timeout_ms < 1000:
            errors.append(f"Router target '{target.id or '<unnamed>'}' timeout_ms must be at least 1000.")
        targets.append(target)

    target_ids = {target.id for target in targets if target.id}
    for rule in rules:
        if rule.target and rule.target not in target_ids:
            errors.append(f"Routing rule '{rule.id}' target must reference an existing target id.")
    if default_target and default_target not in target_ids:
        errors.append("Default target must reference an existing target id.")

    raw_nack = raw_config.get("nack_routing") or {}
    nack_routing = KafkaRouterNackRouting(
        mode=_text(raw_nack.get("mode")) or "default_error",
        per_source_system=_parse_per_source_system(raw_nack.get("per_source_system")),
        fixed_topic=_text(raw_nack.get("fixed_topic")) or None,
        default_error_topic=_text(raw_nack.get("default_error_topic")),
    )
    if nack_routing.mode not in {"same_as_reply", "per_source_system", "fixed", "default_error"}:
        errors.append("nack_routing mode must be same_as_reply, per_source_system, fixed, or default_error.")
    if not nack_routing.default_error_topic:
        errors.append("nack_routing default_error_topic is required.")
    if nack_routing.mode == "fixed" and not nack_routing.fixed_topic:
        errors.append("fixed NACK mode requires fixed_topic.")
    if nack_routing.mode == "per_source_system" and not nack_routing.per_source_system:
        errors.append("per_source_system NACK mode requires at least one source-system mapping.")
    for source, topic in nack_routing.per_source_system.items():
        if not source or not topic:
            errors.append("per_source_system NACK mappings require source_system and topic.")

    raw_timeout = raw_config.get("timeout") or {}
    timeout = KafkaRouterTimeout(
        behavior_with_known_reply=_text(raw_timeout.get("behavior_with_known_reply")) or "nack",
        behavior_without_reply=_text(raw_timeout.get("behavior_without_reply")) or "error_topic",
    )
    if timeout.behavior_with_known_reply not in {"nack", "error_topic"}:
        errors.append("timeout behavior_with_known_reply must be nack or error_topic.")
    if timeout.behavior_without_reply != "error_topic":
        errors.append("timeout behavior_without_reply must be error_topic.")

    raw_logging = raw_config.get("payload_logging") or {}
    payload_logging = KafkaRouterPayloadLogging(
        policy=_text(raw_logging.get("policy")) or "none",
        capped_raw_bytes=_int_value(raw_logging.get("capped_raw_bytes"), 512),
    )
    if payload_logging.policy not in {"none", "hash", "redacted", "capped_raw"}:
        errors.append("payload_logging policy must be none, hash, redacted, or capped_raw.")
    if payload_logging.policy == "capped_raw" and payload_logging.capped_raw_bytes <= 0:
        errors.append("capped_raw payload logging requires positive capped_raw_bytes.")

    raw_store = raw_config.get("correlation_store") or {}
    correlation_store = KafkaRouterCorrelationStore(
        type=_text(raw_store.get("type")) or "in_memory",
        timeout_ms=_int_value(raw_store.get("timeout_ms"), 30000),
        eviction_interval_ms=_int_value(raw_store.get("eviction_interval_ms"), 60000),
    )
    if correlation_store.type != "in_memory":
        errors.append("correlation_store.type must be in_memory.")
    if correlation_store.timeout_ms < 1000:
        errors.append("correlation_store.timeout_ms must be at least 1000.")
    if correlation_store.eviction_interval_ms < 1000:
        errors.append("correlation_store.eviction_interval_ms must be at least 1000.")

    duplicate_policy = _text(raw_config.get("duplicate_correlation_policy")) or "reject-new"
    if duplicate_policy not in {"reject-new", "accept-last"}:
        errors.append("duplicate_correlation_policy must be reject-new or accept-last.")

    router_config = KafkaRouterConfig(
        upstream_topics=upstream_topics,
        inbound_schema=inbound_schema,
        routing_rules=routing_rules,
        duplicate_correlation_policy=duplicate_policy,
        targets=targets,
        outbound_schema=outbound_schema,
        nack_routing=nack_routing,
        timeout=timeout,
        payload_logging=payload_logging,
        correlation_store=correlation_store,
    )
    if not router_config.upstream_topics:
        errors.append("Router route requires at least one upstream topic.")
    if not router_config.targets:
        errors.append("Router route requires at least one target.")

    return router_config, errors


def _parse_router_transform_rows(
    raw_rows,
    route_name: str,
    target_id: str,
    direction: str,
) -> tuple[list[KafkaRouterTransformRow], list[str]]:
    errors: list[str] = []
    rows: list[KafkaRouterTransformRow] = []
    for index, raw_row in enumerate(raw_rows or [], start=1):
        source = _text(raw_row.get("source"))
        target = _text(raw_row.get("target"))
        default_value = _text(raw_row.get("default_value") or raw_row.get("default")) or None
        constant = _text(raw_row.get("constant")) or None
        type_coercion = _text(raw_row.get("type_coercion")) or None
        raw_value_map = raw_row.get("value_map")
        if raw_value_map is None:
            value_map: dict[str, str] = {}
        elif isinstance(raw_value_map, dict):
            value_map = {str(key): str(value) for key, value in raw_value_map.items()}
        else:
            raw_value_map_text = _text(raw_value_map)
            if raw_value_map_text:
                try:
                    parsed = json.loads(raw_value_map_text)
                except json.JSONDecodeError:
                    errors.append(
                        f"Route '{route_name}' target '{target_id}' {direction} row {index} value_map must be a JSON object."
                    )
                    parsed = {}
                if isinstance(parsed, dict):
                    value_map = {str(key): str(value) for key, value in parsed.items()}
                else:
                    errors.append(
                        f"Route '{route_name}' target '{target_id}' {direction} row {index} value_map must be a JSON object."
                    )
                    value_map = {}
            else:
                value_map = {}

        has_any_field = any(
            [
                source,
                target,
                default_value,
                constant,
                value_map,
                type_coercion,
            ]
        )
        if not has_any_field:
            continue
        if not target:
            errors.append(
                f"Route '{route_name}' target '{target_id}' {direction} row {index} target is required."
            )
        if not source and constant is None and default_value is None:
            errors.append(
                f"Route '{route_name}' target '{target_id}' {direction} row {index} requires source, constant, or default."
            )
        if type_coercion and type_coercion not in ROUTER_TYPE_COERCIONS:
            errors.append(
                f"Route '{route_name}' target '{target_id}' {direction} row {index} type_coercion must be major_to_minor_units or minor_to_major_units."
            )
        rows.append(
            KafkaRouterTransformRow(
                source=source,
                target=target,
                default_value=default_value,
                constant=constant,
                value_map=value_map,
                type_coercion=type_coercion,
            )
        )
    return rows, errors


@router.get("/topics", response_class=HTMLResponse)
async def kafka_topics_get(request: Request):
    session, redirect = _kafka_guard(request)
    if redirect is not None:
        return redirect
    nav = build_nav_context(session, "/kafka/topics")
    return templates.TemplateResponse(
        request,
        "kafka_step1_topics.html",
        {
            "request": request,
            "session": session,
            "existing_topic_pairs": [pair.model_dump() for pair in session.kafka_topic_pairs],
            "router_topic_summary": _router_topic_summary(session),
            **nav,
        },
    )


@router.post("/topics/save", response_class=JSONResponse)
async def kafka_topics_save(request: Request):
    session = get_current_session(request)
    if session.app_archetype != "kafka-integration":
        return JSONResponse(
            {"ok": False, "error": "Current project archetype is not kafka-integration."},
            status_code=400,
        )

    body = await request.json()
    consumer_group = (body.get("consumer_group") or "").strip()
    concurrency = int(body.get("concurrency") or 0)
    retry_max_attempts = int(body.get("retry_max_attempts") or 0)
    retry_backoff_ms = int(body.get("retry_backoff_ms") or 0)
    retry_backoff_multiplier = float(body.get("retry_backoff_multiplier") or 0)
    dlq_enabled = bool(body.get("dlq_enabled"))
    dlq_topic_suffix = (body.get("dlq_topic_suffix") or "").strip() or ".dlq"
    topic_pairs_payload = body.get("topic_pairs") or []

    previous_fixed_route_names = set(fixed_route_names(session))
    if not consumer_group:
        return JSONResponse({"ok": False, "error": "consumer_group is required."}, status_code=400)
    if concurrency < 1 or concurrency > 10:
        return JSONResponse({"ok": False, "error": "concurrency must be between 1 and 10."}, status_code=400)
    existing_router_route_names = set(router_route_names(session))
    if not topic_pairs_payload and not existing_router_route_names:
        return JSONResponse({"ok": False, "error": "Add at least one topic pair."}, status_code=400)
    if dlq_enabled and not dlq_topic_suffix.startswith("."):
        return JSONResponse(
            {"ok": False, "error": "dlq_topic_suffix must start with '.' when DLQ is enabled."},
            status_code=400,
        )

    topic_pairs: list[KafkaTopicPair] = []
    seen_route_names: set[str] = set()
    for raw_pair in topic_pairs_payload:
        pair = KafkaTopicPair(
            route_name=(raw_pair.get("route_name") or "").strip(),
            upstream_topic=(raw_pair.get("upstream_topic") or "").strip(),
            upstream_system=(raw_pair.get("upstream_system") or "").strip(),
            upstream_schema_path=(raw_pair.get("upstream_schema_path") or "").strip(),
            upstream_schema_content=(raw_pair.get("upstream_schema_content") or "").strip(),
            downstream_topic=(raw_pair.get("downstream_topic") or "").strip(),
            downstream_system=(raw_pair.get("downstream_system") or "").strip(),
            downstream_schema_path=(raw_pair.get("downstream_schema_path") or "").strip(),
            downstream_schema_content=(raw_pair.get("downstream_schema_content") or "").strip(),
        )
        if not pair.route_name or not pair.upstream_topic or not pair.downstream_topic:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "Each topic pair requires route_name, upstream_topic, and downstream_topic.",
                },
                status_code=400,
            )
        if pair.route_name in seen_route_names:
            return JSONResponse(
                {"ok": False, "error": f"Duplicate route_name '{pair.route_name}' is not allowed."},
                status_code=400,
            )
        seen_route_names.add(pair.route_name)
        topic_pairs.append(pair)

    valid_fixed_route_names = {pair.route_name for pair in topic_pairs}
    preserve_router_route_names = {
        route_name
        for route_name in existing_router_route_names
        if not topic_pairs_payload
        or route_name in valid_fixed_route_names
        or route_name not in previous_fixed_route_names
    }
    valid_route_names = valid_fixed_route_names | preserve_router_route_names

    session.kafka_config = KafkaConfig(
        consumer_group=consumer_group,
        concurrency=concurrency,
        retry_max_attempts=retry_max_attempts,
        retry_backoff_ms=retry_backoff_ms,
        retry_backoff_multiplier=retry_backoff_multiplier,
        dlq_enabled=dlq_enabled,
        dlq_topic_suffix=dlq_topic_suffix,
    )
    session.kafka_topic_pairs = topic_pairs
    session.kafka_route_models = [
        model
        for model in session.kafka_route_models
        if model.route_name in valid_route_names
        and (model.pattern == "router" or model.route_name in valid_fixed_route_names)
    ]
    session.kafka_route_transforms = [
        transform
        for transform in session.kafka_route_transforms
        if transform.route_name in valid_route_names
    ]
    save_current_session(request, session)
    return JSONResponse({"ok": True})


@router.get("/routes", response_class=HTMLResponse)
async def kafka_routes_get(request: Request):
    session, redirect = _kafka_guard(request)
    if redirect is not None:
        return redirect
    if not has_kafka_route_anchors(session):
        return RedirectResponse("/kafka/topics", status_code=303)
    nav = build_nav_context(session, "/kafka/routes")
    transforms_by_name = {transform.route_name: transform for transform in session.kafka_route_transforms}
    existing_route_models = []
    for model in session.kafka_route_models:
        model_data = model.model_dump()
        if model.pattern == "request-reply":
            transform = transforms_by_name.get(model.route_name)
            model_data["upstream_reply_schema_content"] = infer_reply_schema_content(model, transform, "upstream")
            model_data["downstream_reply_schema_content"] = infer_reply_schema_content(model, transform, "downstream")
        existing_route_models.append(model_data)
    return templates.TemplateResponse(
        request,
        "kafka_step2_routes.html",
        {
            "request": request,
            "session": session,
            "route_names": all_kafka_route_names(session),
            "topic_pairs": [pair.model_dump() for pair in session.kafka_topic_pairs],
            "existing_route_models": existing_route_models,
            **nav,
        },
    )


@router.post("/routes/save", response_class=JSONResponse)
async def kafka_routes_save(request: Request):
    session = get_current_session(request)
    if session.app_archetype != "kafka-integration":
        return JSONResponse(
            {"ok": False, "error": "Current project archetype is not kafka-integration."},
            status_code=400,
        )

    valid_fixed_route_names = set(fixed_route_names(session))
    valid_router_route_names = set(router_route_names(session))
    valid_route_names = valid_fixed_route_names | valid_router_route_names
    if not valid_route_names:
        return JSONResponse({"ok": False, "error": "Complete topic ingest first."}, status_code=400)

    body = await request.json()
    routes_payload = body.get("routes") or []
    if not routes_payload:
        return JSONResponse({"ok": False, "error": "Add at least one route model."}, status_code=400)

    route_models: list[KafkaRouteModel] = []
    seen_route_names: set[str] = set()
    topic_pairs = {pair.route_name: pair for pair in session.kafka_topic_pairs}
    for raw_route in routes_payload:
        route_name = (raw_route.get("route_name") or "").strip()
        pattern = (raw_route.get("pattern") or "fire-and-forget").strip() or "fire-and-forget"
        if route_name not in valid_route_names:
            return JSONResponse(
                {"ok": False, "error": f"Unknown route_name '{route_name}'."},
                status_code=400,
            )
        if route_name in seen_route_names:
            return JSONResponse(
                {"ok": False, "error": f"Duplicate route_name '{route_name}' is not allowed."},
                status_code=400,
            )

        if pattern not in {"fire-and-forget", "request-reply", "router"}:
            return JSONResponse(
                {
                    "ok": False,
                    "error": (
                        f"Route '{route_name}' pattern must be fire-and-forget, "
                        "request-reply, or router."
                    ),
                },
                status_code=400,
            )
        if pattern != "router" and route_name not in valid_fixed_route_names:
            return JSONResponse(
                {
                    "ok": False,
                    "error": f"Route '{route_name}' requires a fixed topic pair for pattern '{pattern}'.",
                },
                status_code=400,
            )

        router_config = None
        if pattern == "router":
            router_config, router_errors = _parse_router_config(
                raw_route.get("router_config"),
                route_name,
                topic_pairs.get(route_name),
                session.kafka_config,
            )
            if router_errors:
                return JSONResponse(
                    {
                        "ok": False,
                        "error": f"Route '{route_name}' router_config is invalid: " + "; ".join(router_errors),
                    },
                    status_code=400,
                )

        model = KafkaRouteModel(
            route_name=route_name,
            pattern=pattern,
            upstream_reply_topic=(raw_route.get("upstream_reply_topic") or "").strip(),
            upstream_reply_schema_path=(raw_route.get("upstream_reply_schema_path") or "").strip(),
            upstream_reply_schema_content=(raw_route.get("upstream_reply_schema_content") or "").strip(),
            downstream_reply_topic=(raw_route.get("downstream_reply_topic") or "").strip(),
            downstream_reply_schema_path=(raw_route.get("downstream_reply_schema_path") or "").strip(),
            downstream_reply_schema_content=(raw_route.get("downstream_reply_schema_content") or "").strip(),
            correlation_source=(raw_route.get("correlation_source") or "header").strip() or "header",
            correlation_field=(raw_route.get("correlation_field") or "").strip(),
            reply_timeout_ms=int(raw_route.get("reply_timeout_ms") or 5000),
            router_config=router_config,
        )
        if model.correlation_source not in {"header", "payload"}:
            return JSONResponse(
                {
                    "ok": False,
                    "error": f"Route '{route_name}' correlation_source must be header or payload.",
                },
                status_code=400,
            )
        if model.pattern != "router" and model.reply_timeout_ms < 1000:
            return JSONResponse(
                {"ok": False, "error": f"Route '{route_name}' reply_timeout_ms must be at least 1000."},
                status_code=400,
            )
        if model.pattern == "request-reply":
            if (
                not model.upstream_reply_topic
                or not model.downstream_reply_topic
                or not model.correlation_field
                or not model.upstream_reply_schema_content
                or not model.downstream_reply_schema_content
            ):
                return JSONResponse(
                    {
                        "ok": False,
                        "error": (
                            f"Route '{route_name}' requires upstream_reply_topic, "
                            "downstream_reply_topic, reply schema content, and correlation_field "
                            "for request-reply."
                        ),
                    },
                    status_code=400,
                )
        route_models.append(model)
        seen_route_names.add(route_name)

    if seen_route_names != valid_route_names:
        missing = ", ".join(sorted(valid_route_names - seen_route_names))
        return JSONResponse(
            {"ok": False, "error": f"Route models are missing for: {missing}."},
            status_code=400,
        )

    session.kafka_route_models = route_models
    save_current_session(request, session)
    return JSONResponse({"ok": True})


@router.get("/transforms", response_class=HTMLResponse)
async def kafka_transforms_get(request: Request):
    session, redirect = _kafka_guard(request)
    if redirect is not None:
        return redirect
    if not session.kafka_route_models:
        return RedirectResponse("/kafka/routes", status_code=303)
    nav = build_nav_context(session, "/kafka/transforms")
    route_models_by_name = {model.route_name: model for model in session.kafka_route_models}
    transform_route_names = [
        route_name
        for route_name in all_kafka_route_names(session)
        if route_models_by_name.get(route_name)
    ]
    mapping_suggestion_badges = {}
    router_transform_suggestion_badges = {}
    workspace_before = workspace_session_marker(session)
    for route_name in transform_route_names:
        route_model = route_models_by_name[route_name]
        if route_model.pattern == "router":
            target_badges: dict[str, dict[str, Any]] = {}
            for context in _kafka_router_transform_contexts(route_model):
                badge = assist_service.get_transform_suggestion_badge(
                    session,
                    route_name=route_name,
                    target_id=context["target_id"],
                    direction=context["direction"],
                    contexts=[context],
                    drawer_url=f"/kafka/ks/drawer?{urlencode({'scope': 'transforms', 'route_name': route_name, 'target_id': context['target_id'], 'direction': context['direction']})}",
                )
                if badge:
                    target_badges.setdefault(context["target_id"], {})[context["direction"]] = _badge_dict(badge)
            if target_badges:
                router_transform_suggestion_badges[route_name] = target_badges
            continue
        mapping_contexts = _kafka_mapping_contexts(session, route_model)
        badge = assist_service.get_mapping_suggestion_badge(
            session,
            route_name=route_name,
            contexts=mapping_contexts,
            drawer_url=f"/kafka/ks/drawer?{urlencode({'scope': 'mappings', 'route_name': route_name})}",
        )
        if badge:
            mapping_suggestion_badges[route_name] = _badge_dict(badge)
    save_current_session_if_workspace_changed(request, session, workspace_before)
    return templates.TemplateResponse(
        request,
        "kafka_step3_transforms.html",
        {
            "request": request,
            "session": session,
            "route_names": transform_route_names,
            "existing_route_models": [model.model_dump() for model in session.kafka_route_models],
            "existing_route_transforms": [
                transform.model_dump() for transform in session.kafka_route_transforms
            ],
            "mapping_suggestion_badges": mapping_suggestion_badges,
            "router_transform_suggestion_badges": router_transform_suggestion_badges,
            **nav,
        },
    )


@router.get("/ks/drawer", response_class=JSONResponse)
async def kafka_ks_drawer(
    request: Request,
    scope: str = Query("mappings"),
    route_name: str = Query(""),
    target_id: str = Query(""),
    direction: str = Query(""),
):
    session, redirect = _kafka_guard(request)
    if redirect is not None:
        return JSONResponse(
            {
                "ok": False,
                "warning": "Kafka mapping suggestion drawers are available for Kafka Integration projects only.",
            },
            status_code=400,
        )
    if scope not in {"mappings", "transforms"}:
        return JSONResponse(
            {
                "ok": False,
                "warning": f"Unsupported Kafka Knowledge Assist drawer scope '{scope}'.",
            },
            status_code=400,
        )

    normalized_route_name = route_name.strip()
    route_model = next(
        (model for model in session.kafka_route_models if model.route_name == normalized_route_name),
        None,
    )
    if scope == "transforms":
        contexts = _kafka_router_transform_contexts(
            route_model,
            target_id=target_id,
            direction=direction,
        )
        if route_model is None or route_model.pattern != "router" or not contexts:
            return JSONResponse(
                {
                    "ok": True,
                    "scope": "transforms",
                    "title": "Transform Suggestions",
                    "entity": None,
                    "route_name": normalized_route_name,
                    "target_id": target_id.strip(),
                    "direction": direction.strip(),
                    "scopes": [],
                    "warnings": [],
                    "empty": True,
                }
            )

        workspace_before = workspace_session_marker(session)
        drawer = assist_service.fetch_transform_suggestion_drawer(
            session,
            route_name=normalized_route_name,
            target_id=target_id,
            direction=direction,
            contexts=contexts,
        )
        save_current_session_if_workspace_changed(request, session, workspace_before)
        payload = drawer.to_dict() if drawer else {
            "ok": True,
            "scope": "transforms",
            "title": "Transform Suggestions",
            "entity": None,
            "scopes": [],
            "warnings": [],
            "empty": True,
        }
        payload["route_name"] = normalized_route_name
        payload["target_id"] = target_id.strip()
        payload["direction"] = direction.strip()
        payload["review_url"] = "/kafka/ks/transform-review"
        return JSONResponse(payload)

    mapping_contexts = _kafka_mapping_contexts(session, route_model) if route_model else []
    if route_model is None or route_model.pattern == "router" or not mapping_contexts:
        return JSONResponse(
            {
                "ok": True,
                "scope": "mappings",
                "title": "Mapping Suggestions",
                "entity": None,
                "route_name": normalized_route_name,
                "scopes": [],
                "warnings": [],
                "empty": True,
            }
        )

    workspace_before = workspace_session_marker(session)
    drawer = assist_service.fetch_mapping_suggestion_drawer(
        session,
        route_name=normalized_route_name,
        contexts=mapping_contexts,
    )
    save_current_session_if_workspace_changed(request, session, workspace_before)
    payload = drawer.to_dict() if drawer else {
        "ok": True,
        "scope": "mappings",
        "title": "Mapping Suggestions",
        "entity": None,
        "scopes": [],
        "warnings": [],
        "empty": True,
    }
    payload["route_name"] = normalized_route_name
    payload["review_url"] = "/kafka/ks/review"
    return JSONResponse(payload)


@router.post("/ks/transform-review", response_class=JSONResponse)
async def kafka_ks_transform_review(request: Request):
    session, redirect = _kafka_guard(request)
    if redirect is not None:
        return JSONResponse(
            {"ok": False, "errors": ["Kafka transform suggestion review is available for Kafka Integration projects only."]},
            status_code=400,
        )
    if not session.capabilities.knowledge_assist_enabled:
        return JSONResponse(
            {"ok": False, "errors": ["Knowledge Assist is off; no transform suggestion decisions were submitted."]},
            status_code=400,
        )

    body = await request.json()
    decisions, errors = _normalize_transform_decisions(body.get("decisions"))
    if errors:
        return JSONResponse({"ok": False, "errors": errors}, status_code=400)
    if not decisions:
        return JSONResponse(
            {
                "ok": True,
                "skipped": True,
                "message": "No staged transform suggestion decisions to save.",
                "outcomes": [],
                "saved_count": 0,
                "failed_count": 0,
                "applied_count": 0,
                "warnings": [],
            }
        )

    candidate_rows: dict[str, tuple[KafkaRouterTransformRow, str, str, str] | None] = {}
    ks_decisions: list[dict[str, Any]] = []
    preflight_errors: list[str] = []
    for decision in decisions:
        if decision["status"] in {"accepted", "edited"}:
            row, route_name, target_id, direction, warning = _validate_kafka_transform_payload(
                session,
                _transform_payload(decision),
            )
            if warning or row is None:
                preflight_errors.append(f"{decision['suggestion_id']}: {warning or 'Invalid transform suggestion payload.'}")
                continue
            candidate_rows[decision["suggestion_id"]] = (row, route_name, target_id, direction)
            ks_decision = {
                "suggestion_id": decision["suggestion_id"],
                "status": decision["status"],
            }
            if decision["status"] == "edited":
                ks_decision["edited_payload"] = _sanitized_transform_edit_payload(row)
            ks_decisions.append(ks_decision)
        else:
            candidate_rows[decision["suggestion_id"]] = None
            ks_decisions.append(_ks_review_payload(decision))
    if preflight_errors:
        return JSONResponse({"ok": False, "errors": preflight_errors}, status_code=400)

    ks_result = assist_service.submit_transform_suggestion_decisions(
        session,
        decisions=ks_decisions,
    )
    if ks_result is None:
        return JSONResponse(
            {
                "ok": False,
                "errors": ["Transform suggestion review could not be saved. Manual transform authoring remains available."],
                "outcomes": [],
                "saved_count": 0,
                "failed_count": len(decisions),
                "applied_count": 0,
                "warnings": [],
            },
            status_code=502,
        )

    successful_ids = _successful_outcome_ids(ks_result, decisions)
    outcomes: list[dict[str, Any]] = []
    warnings: list[str] = []
    applied_count = 0
    for decision in decisions:
        suggestion_id = decision["suggestion_id"]
        success = suggestion_id in successful_ids
        applied = False
        manifest_path = decision["manifest_path"] or f"async_routes.transform_reviews.{suggestion_id}"
        review_context: dict[str, Any] | None = None
        if success:
            candidate = candidate_rows.get(suggestion_id)
            if candidate is not None:
                row, route_name, target_id, direction = candidate
                applied = _append_kafka_router_transform_if_missing(
                    session,
                    route_name=route_name,
                    target_id=target_id,
                    direction=direction,
                    row=row,
                )
                if applied:
                    applied_count += 1
                else:
                    warnings.append(
                        f"{suggestion_id}: matching router transform row already exists; review was recorded without duplicating it."
                    )
                manifest_path = _kafka_router_transform_manifest_path(
                    route_name,
                    target_id,
                    direction,
                    row,
                )
                review_context = _kafka_router_transform_review_context(
                    route_name,
                    target_id,
                    direction,
                    row,
                    source_entity=(
                        _payload_text(decision["edited_payload"] or {}, "source_entity")
                        if isinstance(decision.get("edited_payload"), dict)
                        else ""
                    )
                    or _payload_text(decision["payload"], "source_entity"),
                    target_entity=(
                        _payload_text(decision["edited_payload"] or {}, "target_entity")
                        if isinstance(decision.get("edited_payload"), dict)
                        else ""
                    )
                    or _payload_text(decision["payload"], "target_entity"),
                )
            else:
                review_context = _kafka_router_transform_review_context_from_decision(decision)
            record_review_history_without_evidence(
                session,
                suggestion_id=suggestion_id,
                suggestion_type="transform",
                status=decision["status"],
                manifest_path=manifest_path,
                edited_payload=decision["edited_payload"],
                review_context=review_context,
            )
        outcomes.append(
            {
                "suggestion_id": suggestion_id,
                "status": decision["status"],
                "success": success,
                "applied": applied,
                "manifest_path": manifest_path,
            }
        )

    save_current_session(request, session)
    saved_count = sum(1 for outcome in outcomes if outcome["success"])
    failed_count = len(outcomes) - saved_count
    return JSONResponse(
        {
            "ok": failed_count == 0,
            "partial_failure": failed_count > 0,
            "message": f"Saved {saved_count} transform suggestion decision(s); applied {applied_count} transform row(s).",
            "outcomes": outcomes,
            "saved_count": saved_count,
            "failed_count": failed_count,
            "applied_count": applied_count,
            "warnings": warnings,
            "refresh": applied_count > 0,
        }
    )


@router.post("/ks/review", response_class=JSONResponse)
async def kafka_ks_review(request: Request):
    session, redirect = _kafka_guard(request)
    if redirect is not None:
        return JSONResponse(
            {"ok": False, "errors": ["Kafka mapping suggestion review is available for Kafka Integration projects only."]},
            status_code=400,
        )
    if not session.capabilities.knowledge_assist_enabled:
        return JSONResponse(
            {"ok": False, "errors": ["Knowledge Assist is off; no mapping suggestion decisions were submitted."]},
            status_code=400,
        )

    body = await request.json()
    decisions, errors = _normalize_mapping_decisions(body.get("decisions"))
    if errors:
        return JSONResponse({"ok": False, "errors": errors}, status_code=400)
    if not decisions:
        return JSONResponse(
            {
                "ok": True,
                "skipped": True,
                "message": "No staged mapping suggestion decisions to save.",
                "outcomes": [],
                "saved_count": 0,
                "failed_count": 0,
                "applied_count": 0,
                "warnings": [],
            }
        )

    candidate_mappings: dict[str, tuple[str, str, str, str] | None] = {}
    preflight_errors: list[str] = []
    for decision in decisions:
        if decision["status"] in {"accepted", "edited"}:
            source, target, route_name, warning = _validate_kafka_mapping_payload(
                session,
                _mapping_payload(decision),
            )
            if warning:
                preflight_errors.append(f"{decision['suggestion_id']}: {warning}")
                continue
            direction = _payload_text(_mapping_payload(decision), "direction") or "request"
            candidate_mappings[decision["suggestion_id"]] = (source, target, route_name, direction)
        else:
            candidate_mappings[decision["suggestion_id"]] = None
    if preflight_errors:
        return JSONResponse({"ok": False, "errors": preflight_errors}, status_code=400)

    ks_result = assist_service.submit_mapping_suggestion_decisions(
        session,
        decisions=[_ks_review_payload(decision) for decision in decisions],
    )
    if ks_result is None:
        return JSONResponse(
            {
                "ok": True,
                "degraded": True,
                "message": "Mapping suggestion review could not be saved. Manual transform authoring remains available.",
                "outcomes": [],
                "saved_count": 0,
                "failed_count": len(decisions),
                "applied_count": 0,
                "warnings": [],
            }
        )

    successful_ids = _successful_outcome_ids(ks_result, decisions)
    outcomes: list[dict[str, Any]] = []
    warnings: list[str] = []
    applied_count = 0
    for decision in decisions:
        suggestion_id = decision["suggestion_id"]
        success = suggestion_id in successful_ids
        applied = False
        manifest_path = decision["manifest_path"]
        review_context: dict[str, str] | None = None
        if success:
            candidate = candidate_mappings.get(suggestion_id)
            if candidate is not None:
                source, target, route_name, direction = candidate
                applied = _append_kafka_mapping_if_missing(
                    session,
                    route_name=route_name,
                    direction=direction,
                    source=source,
                    target=target,
                )
                if applied:
                    applied_count += 1
                else:
                    warnings.append(f"{suggestion_id}: matching Kafka mapping already exists; review was recorded without duplicating it.")
                manifest_path = _kafka_mapping_manifest_path(route_name, direction, source, target)
                payload = decision["payload"] if isinstance(decision.get("payload"), dict) else {}
                edited_payload = (
                    decision["edited_payload"] if isinstance(decision.get("edited_payload"), dict) else {}
                )
                review_context = _kafka_mapping_review_context(
                    route_name,
                    direction,
                    source,
                    target,
                    source_entity=(
                        _payload_text(edited_payload, "source_entity")
                        or _payload_text(payload, "source_entity")
                    ),
                    target_entity=(
                        _payload_text(edited_payload, "target_entity")
                        or _payload_text(payload, "target_entity")
                    ),
                )
            else:
                manifest_path = manifest_path or f"async_routes.mapping_reviews.{suggestion_id}"
                review_context = _kafka_mapping_review_context_from_decision(decision)
            record_review_history_without_evidence(
                session,
                suggestion_id=suggestion_id,
                suggestion_type="mapping",
                status=decision["status"],
                manifest_path=manifest_path,
                edited_payload=decision["edited_payload"],
                review_context=review_context,
            )
        outcomes.append(
            {
                "suggestion_id": suggestion_id,
                "status": decision["status"],
                "success": success,
                "applied": applied,
                "manifest_path": manifest_path,
            }
        )

    save_current_session(request, session)
    saved_count = sum(1 for outcome in outcomes if outcome["success"])
    failed_count = len(outcomes) - saved_count
    return JSONResponse(
        {
            "ok": failed_count == 0,
            "partial_failure": failed_count > 0,
            "message": f"Saved {saved_count} mapping suggestion decision(s); applied {applied_count} mapping(s).",
            "outcomes": outcomes,
            "saved_count": saved_count,
            "failed_count": failed_count,
            "applied_count": applied_count,
            "warnings": warnings,
        }
    )


@router.post("/transforms/save", response_class=JSONResponse)
async def kafka_transforms_save(request: Request):
    session = get_current_session(request)
    if session.app_archetype != "kafka-integration":
        return JSONResponse(
            {"ok": False, "error": "Current project archetype is not kafka-integration."},
            status_code=400,
        )

    valid_route_names = set(all_kafka_route_names(session))
    route_models = {route.route_name: route for route in session.kafka_route_models}
    if not route_models:
        return JSONResponse({"ok": False, "error": "Complete route modeling first."}, status_code=400)
    required_transform_route_names = {
        route_name
        for route_name in valid_route_names
        if route_models.get(route_name) and route_models[route_name].pattern != "router"
    }

    body = await request.json()
    transforms_payload = body.get("transforms") or []
    if not transforms_payload and required_transform_route_names:
        return JSONResponse({"ok": False, "error": "Add at least one route transform."}, status_code=400)

    transforms: list[KafkaRouteTransform] = []
    seen_route_names: set[str] = set()
    seen_non_router_route_names: set[str] = set()
    for raw_transform in transforms_payload:
        route_name = (raw_transform.get("route_name") or "").strip()
        if route_name not in valid_route_names:
            return JSONResponse(
                {"ok": False, "error": f"Unknown route_name '{route_name}'."},
                status_code=400,
            )
        route_model = route_models.get(route_name)
        if route_model is None:
            return JSONResponse(
                {"ok": False, "error": f"Route '{route_name}' has no saved route model."},
                status_code=400,
            )

        if route_model.pattern == "router":
            target_ids = {
                target.id
                for target in (route_model.router_config.targets if route_model.router_config else [])
            }
            router_target_transforms: list[KafkaRouterTargetTransform] = []
            for raw_target_transform in raw_transform.get("router_target_transforms") or []:
                target_id = _text(raw_target_transform.get("target_id"))
                if target_id not in target_ids:
                    return JSONResponse(
                        {
                            "ok": False,
                            "error": f"Route '{route_name}' router transform target_id '{target_id}' is not defined in Route Model.",
                        },
                        status_code=400,
                    )
                request_rows, request_errors = _parse_router_transform_rows(
                    raw_target_transform.get("request_transform_rows"),
                    route_name,
                    target_id,
                    "request",
                )
                response_rows, response_errors = _parse_router_transform_rows(
                    raw_target_transform.get("response_transform_rows"),
                    route_name,
                    target_id,
                    "response",
                )
                errors = request_errors + response_errors
                if errors:
                    return JSONResponse(
                        {"ok": False, "error": "; ".join(errors)},
                        status_code=400,
                    )
                router_target_transforms.append(
                    KafkaRouterTargetTransform(
                        target_id=target_id,
                        request_transform_rows=request_rows,
                        response_transform_rows=response_rows,
                    )
                )
            transforms.append(
                KafkaRouteTransform(
                    route_name=route_name,
                    router_target_transforms=router_target_transforms,
                )
            )
            seen_route_names.add(route_name)
            continue

        mappings = []
        for raw_row in raw_transform.get("mappings") or []:
            source_field = (raw_row.get("source_field") or "").strip()
            target_field = (raw_row.get("target_field") or "").strip()
            if not source_field or not target_field:
                return JSONResponse(
                    {"ok": False, "error": f"Route '{route_name}' has a request mapping with blank fields."},
                    status_code=400,
                )
            mappings.append(KafkaTransformRow(source_field=source_field, target_field=target_field))

        response_mappings = []
        for raw_row in raw_transform.get("response_mappings") or []:
            source_field = (raw_row.get("source_field") or "").strip()
            target_field = (raw_row.get("target_field") or "").strip()
            if not source_field or not target_field:
                return JSONResponse(
                    {"ok": False, "error": f"Route '{route_name}' has a response mapping with blank fields."},
                    status_code=400,
                )
            response_mappings.append(
                KafkaTransformRow(source_field=source_field, target_field=target_field)
            )

        if not mappings:
            return JSONResponse(
                {"ok": False, "error": f"Route '{route_name}' requires at least one request mapping."},
                status_code=400,
            )
        if (
            route_model.pattern == "request-reply"
            and not response_mappings
        ):
            return JSONResponse(
                {"ok": False, "error": f"Route '{route_name}' requires at least one response mapping."},
                status_code=400,
            )

        transforms.append(
            KafkaRouteTransform(
                route_name=route_name,
                mappings=mappings,
                response_mappings=response_mappings,
            )
        )
        seen_route_names.add(route_name)
        seen_non_router_route_names.add(route_name)

    if seen_non_router_route_names != required_transform_route_names:
        missing = ", ".join(sorted(required_transform_route_names - seen_non_router_route_names))
        return JSONResponse(
            {"ok": False, "error": f"Transforms are missing for: {missing}."},
            status_code=400,
        )

    existing_by_name = {transform.route_name: transform for transform in session.kafka_route_transforms}
    for route_name, route_model in route_models.items():
        if route_model.pattern == "router" and route_name not in seen_route_names:
            existing = existing_by_name.get(route_name)
            if existing is not None:
                transforms.append(existing)

    session.kafka_route_transforms = transforms
    save_current_session(request, session)
    return JSONResponse({"ok": True})


@router.get("/next")
async def kafka_next():
    return RedirectResponse("/rules", status_code=303)
