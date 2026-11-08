"""Helpers for the passthrough-router Studio MVP."""

from __future__ import annotations

import re
from typing import Any

import yaml
from starlette.requests import Request

from app.models.project import (
    DownstreamInterface,
    PassthroughFlow,
    PassthroughRouteRow,
    PassthroughTransform,
    UpstreamInterface,
)
from app.services.openapi_service import (
    _derive_op_id,
    _extract_fields,
    _find_request_schema,
    _find_response_schema,
    _resolve_schema,
    fetch_openapi_from_url,
    parse_openapi_text,
)
from app.services.request_resource_limits import (
    RequestCostClass,
    ResourceLimitPermit,
    ResourceLimitPrincipalUnavailable,
    ResourceLimitRejection,
    get_request_resource_limiter,
    try_acquire_request_resource,
)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def load_openapi_spec(*, spec_url: str | None, spec_content: str | None) -> dict[str, Any]:
    if spec_content:
        return parse_openapi_text(spec_content)
    if spec_url:
        return fetch_openapi_from_url(spec_url)
    raise ValueError("Exactly one of spec_url or spec_content is required.")


class RemoteOpenAPIFetchRateLimitedError(Exception):
    """A guarded passthrough URL fetch exhausted Class B capacity."""

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds


class RemoteOpenAPIFetchUnavailableError(Exception):
    """A shared request lacks the principal context needed for Class B."""


async def fetch_openapi_spec_for_request(request: Request, *, spec_url: str | None) -> dict[str, Any]:
    """Fetch one passthrough URL spec under the shared Class B control seam.

    Text-backed specs stay on ``load_openapi_spec``. Every passthrough URL fetch
    must use this function so an otherwise-unthrottled save only consumes Class B
    for the remote work it actually performs.
    """

    if not spec_url:
        raise ValueError("Exactly one of spec_url or spec_content is required.")

    decision = await try_acquire_request_resource(request, cost_class=RequestCostClass.B)
    if isinstance(decision, ResourceLimitRejection):
        raise RemoteOpenAPIFetchRateLimitedError(decision.retry_after_seconds)
    if isinstance(decision, ResourceLimitPrincipalUnavailable):
        raise RemoteOpenAPIFetchUnavailableError
    if decision is None:
        return fetch_openapi_from_url(spec_url)

    permit: ResourceLimitPermit = decision
    try:
        return fetch_openapi_from_url(spec_url)
    finally:
        await get_request_resource_limiter().release(permit)


def dump_openapi_spec(spec: dict[str, Any]) -> str:
    return yaml.dump(spec, default_flow_style=False, sort_keys=False, allow_unicode=True)


def extract_operation_descriptors(spec: dict[str, Any]) -> list[dict[str, Any]]:
    paths = spec.get("paths", {})
    if not isinstance(paths, dict):
        return []

    operations: list[dict[str, Any]] = []
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method in ("get", "post", "put", "delete", "patch"):
            op_def = path_item.get(method)
            if not isinstance(op_def, dict):
                continue
            name = op_def.get("operationId") or _derive_op_id(method, path)
            request_schema_name = _find_request_schema(op_def, spec)
            response_schema_name = _find_response_schema(op_def, spec)
            request_schema = _resolve_schema(request_schema_name, spec) if request_schema_name else None
            response_schema = _resolve_schema(response_schema_name, spec) if response_schema_name else None
            request_fields = [
                field.name for field in _extract_fields(request_schema or {}, spec)
            ]
            response_fields = [
                field.name for field in _extract_fields(response_schema or {}, spec)
            ]
            operations.append({
                "name": name,
                "method": method.upper(),
                "path": path,
                "request_schema_name": request_schema_name,
                "response_schema_name": response_schema_name,
                "request_fields": request_fields,
                "response_fields": response_fields,
            })
    return operations


def filter_spec_to_operation(spec: dict[str, Any], operation_name: str) -> dict[str, Any]:
    filtered = dict(spec)
    filtered_paths: dict[str, Any] = {}
    paths = spec.get("paths", {})
    if not isinstance(paths, dict):
        raise ValueError("OpenAPI spec does not define any paths.")

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        kept_ops: dict[str, Any] = {}
        for method in ("get", "post", "put", "delete", "patch"):
            op_def = path_item.get(method)
            if not isinstance(op_def, dict):
                continue
            op_name = op_def.get("operationId") or _derive_op_id(method, path)
            if op_name == operation_name:
                kept_ops[method] = op_def
        if kept_ops:
            filtered_paths[path] = kept_ops

    if not filtered_paths:
        raise ValueError(f"Operation '{operation_name}' was not found in the supplied OpenAPI spec.")

    filtered["paths"] = filtered_paths
    return filtered


def serialize_passthrough_rules(flow: PassthroughFlow) -> str:
    payload: dict[str, Any] = {
        "routing_rules": {
            "route_field": flow.route_field,
            "routes": [
                {"match": route.match, "target": route.target}
                for route in flow.routes
            ],
            "default_target": flow.default_target,
        },
        "transforms": [
            {
                **{"source": transform.source, "target": transform.target},
                **({"default": transform.default} if transform.default is not None else {}),
            }
            for transform in flow.transforms
        ],
    }
    return yaml.dump(payload, default_flow_style=False, sort_keys=False, allow_unicode=True)


def build_passthrough_upstream_interface(
    *,
    bounded_context: str,
    spec_url: str | None,
    spec_content: str | None,
    spec_filename: str | None,
    upstream_operation_name: str,
) -> UpstreamInterface:
    iface_name = f"{_slug(bounded_context or 'app')}-router-upstream-api"
    spec_path = f"upstream/{spec_filename}" if spec_filename else f"upstream/{iface_name}-spec.yaml"
    return UpstreamInterface(
        name=iface_name,
        system="UPSTREAM",
        type="rest-json",
        spec=spec_path if spec_content else None,
        spec_url=spec_url if not spec_content else None,
        spec_content=spec_content,
        selected_operation_name=upstream_operation_name,
        is_draft=False,
    )


def build_passthrough_downstream_interface(
    *,
    name: str,
    system: str,
    spec_url: str | None,
    spec_content: str | None,
    selected_operation_name: str,
) -> DownstreamInterface:
    iface_slug = _slug(name)
    return DownstreamInterface(
        name=name,
        system=system,
        type="rest-json",
        spec=f"downstream/{iface_slug}-openapi.yaml" if spec_content else None,
        spec_url=spec_url if not spec_content else None,
        spec_content=spec_content,
        selected_operation_name=selected_operation_name,
    )


def build_passthrough_flow(
    *,
    upstream_operation_name: str,
    route_field: str,
    routes: list[dict[str, str]],
    default_target: str,
    transforms: list[dict[str, str | None]],
) -> PassthroughFlow:
    return PassthroughFlow(
        upstream_operation_name=upstream_operation_name,
        route_field=route_field,
        routes=[
            PassthroughRouteRow(match=route["match"], target=route["target"])
            for route in routes
        ],
        default_target=default_target,
        transforms=[
            PassthroughTransform(
                source=transform["source"],
                target=transform["target"],
                default=transform.get("default"),
            )
            for transform in transforms
        ],
    )
