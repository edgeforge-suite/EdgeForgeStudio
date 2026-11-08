"""Helpers for Kafka message schema authoring and compatibility fallbacks."""

from __future__ import annotations

import json

from app.models.project import KafkaRouteModel, KafkaRouteTransform


def infer_reply_schema_content(
    route_model: KafkaRouteModel,
    route_transform: KafkaRouteTransform | None,
    direction: str,
) -> str:
    """Return explicit reply schema content or infer a permissive JSON schema.

    Older Studio Kafka project files did not capture request-reply schema
    content. When response mappings exist we can still build a valid minimal
    schema from the mapped field names so review/export remains usable.
    """
    if direction == "upstream":
        if route_model.upstream_reply_schema_content:
            return route_model.upstream_reply_schema_content
        field_names = [row.target_field for row in (route_transform.response_mappings if route_transform else [])]
    else:
        if route_model.downstream_reply_schema_content:
            return route_model.downstream_reply_schema_content
        field_names = [row.source_field for row in (route_transform.response_mappings if route_transform else [])]

    if not field_names:
        return ""

    schema = {
        "type": "object",
        "properties": {
            field_name: {"type": "string"}
            for field_name in field_names
        },
    }
    return json.dumps(schema, indent=2)
