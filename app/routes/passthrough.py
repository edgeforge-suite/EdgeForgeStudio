"""Minimal passthrough-router authoring flow."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.middleware.resource_limits import (
    resource_limit_rejection_response,
    resource_limit_unavailable_response,
)
from app.models.project import PassthroughTransform
from app.paths import TEMPLATE_DIR
from app.services.assist_service import AssistService
from app.services.nav_context import build_nav_context
from app.services.passthrough_service import (
    RemoteOpenAPIFetchRateLimitedError,
    RemoteOpenAPIFetchUnavailableError,
    build_passthrough_downstream_interface,
    build_passthrough_flow,
    build_passthrough_upstream_interface,
    dump_openapi_spec,
    extract_operation_descriptors,
    fetch_openapi_spec_for_request,
    load_openapi_spec,
)
from app.services.session_context import (
    get_current_session,
    save_current_session,
    save_current_session_if_workspace_changed,
    workspace_session_marker,
)
from app.services.suggestion_review_state import record_review_history_without_evidence

router = APIRouter(prefix="/passthrough")
templates = Jinja2Templates(directory=TEMPLATE_DIR)
assist_service = AssistService()
_MAPPING_REVIEW_STATUSES = {"accepted", "edited", "rejected"}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _upstream_operation_context(session) -> tuple[list[dict], dict | None]:
    if not session.raw_spec_content:
        return [], None
    spec = load_openapi_spec(spec_content=session.raw_spec_content, spec_url=None)
    operations = extract_operation_descriptors(spec)
    selected_name = session.passthrough_flow.upstream_operation_name
    selected = next((op for op in operations if op["name"] == selected_name), None)
    return operations, selected


def _downstream_context(session) -> list[dict]:
    targets: list[dict] = []
    for iface in session.downstream_interfaces:
        operations: list[dict] = []
        if iface.spec_content:
            operations = extract_operation_descriptors(
                load_openapi_spec(spec_content=iface.spec_content, spec_url=None)
            )
        selected = next((op for op in operations if op["name"] == iface.selected_operation_name), None)
        targets.append({
            "name": iface.name,
            "system": iface.system or "",
            "source_mode": "url" if iface.spec_url and not iface.spec_content else "text",
            "spec_url": iface.spec_url or "",
            "spec_content": iface.spec_content or "",
            "selected_operation_name": iface.selected_operation_name or "",
            "operations": operations,
            "selected_operation": selected,
        })
    return targets


def _mapping_contexts(
    *,
    route_name: str,
    selected_upstream: dict | None,
    downstream_targets: list[dict],
) -> list[dict[str, str]]:
    if not route_name or not selected_upstream:
        return []

    source_entity = (
        selected_upstream.get("request_schema_name")
        or selected_upstream.get("name")
        or route_name
    )
    contexts: list[dict[str, str]] = []
    for target in downstream_targets:
        selected_operation = target.get("selected_operation") or {}
        target_entity = (
            selected_operation.get("request_schema_name")
            or target.get("selected_operation_name")
            or target.get("name")
        )
        if not source_entity or not target_entity:
            continue
        contexts.append(
            {
                "route_name": route_name,
                "direction": "request",
                "source_entity": source_entity,
                "target_entity": target_entity,
            }
        )
    return contexts


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
        payload["edited_payload"] = _ks_mapping_edited_payload(decision)
    return payload


def _merged_mapping_payload(decision: dict[str, Any]) -> dict[str, Any]:
    payload = dict(decision["payload"])
    if decision["status"] == "edited" and decision.get("edited_payload"):
        edited_payload = decision["edited_payload"]
        payload.update(edited_payload)
        if "source" in edited_payload:
            payload.pop("source_field", None)
        if "target" in edited_payload:
            payload.pop("target_field", None)
    return payload


def _ks_mapping_edited_payload(decision: dict[str, Any]) -> dict[str, Any]:
    """Return the KS-compatible edited payload for mapping suggestions.

    The drawer only asks humans to edit the visible source/target fields.  KS
    still validates edited mapping decisions against the full persisted mapping
    suggestion contract, so Studio needs to merge the hidden route/context fields
    from the original suggestion before submitting the decision.
    """
    payload = _merged_mapping_payload(decision)
    result = {
        "route_name": _payload_text(payload, "route_name"),
        "direction": _payload_text(payload, "direction") or "request",
        "source_entity": _payload_text(payload, "source_entity"),
        "target_entity": _payload_text(payload, "target_entity"),
        "source_field": _payload_text(payload, "source_field", "source"),
        "target_field": _payload_text(payload, "target_field", "target"),
        "mapping_type": (_payload_text(payload, "mapping_type", "type") or "copy").lower(),
        "confidence_basis": _payload_text(payload, "confidence_basis", "confidence_reason", "basis"),
    }
    return {key: value for key, value in result.items() if value}


def _ks_outcome_details(ks_result: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    details: dict[str, dict[str, list[str]]] = {}
    outcomes = ks_result.get("outcomes", [])
    if not isinstance(outcomes, list):
        return details
    for outcome in outcomes:
        if not isinstance(outcome, dict) or outcome.get("suggestion_id") is None:
            continue
        suggestion_id = str(outcome.get("suggestion_id"))
        entry = details.setdefault(suggestion_id, {"errors": [], "warnings": []})
        for key in ("error", "message", "reason"):
            value = outcome.get(key)
            if value and not outcome.get("success", True):
                entry["errors"].append(str(value))
        raw_warnings = outcome.get("warnings") or outcome.get("warning")
        if isinstance(raw_warnings, list):
            entry["warnings"].extend(str(item) for item in raw_warnings if str(item).strip())
        elif raw_warnings:
            entry["warnings"].append(str(raw_warnings))
    return details


def _payload_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _validate_mapping_payload(
    payload: dict[str, Any],
    *,
    contexts: list[dict[str, str]],
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
    if direction != "request":
        return "", "", "", "Passthrough mapping suggestions support request direction only."
    if not source or not target:
        return "", "", "", "Mapping suggestions require source_field and target_field."
    if not any(
        context["route_name"] == route_name
        and context["direction"] == direction
        and context["source_entity"] == source_entity
        and context["target_entity"] == target_entity
        for context in contexts
    ):
        return "", "", "", "Mapping suggestion no longer matches the current passthrough route context."
    return source, target, route_name, None


def _normalize_mapping_decisions(raw_decisions: Any) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(raw_decisions, list):
        return [], ["Review decisions must be a list."]

    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, item in enumerate(raw_decisions):
        if not isinstance(item, dict):
            errors.append(f"Decision {index + 1} must be an object.")
            continue
        suggestion_id = str(item.get("suggestion_id") or "").strip()
        suggestion_type = str(item.get("suggestion_type") or "").strip()
        status = str(item.get("status") or "").strip()
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        edited_payload = item.get("edited_payload") if isinstance(item.get("edited_payload"), dict) else None
        manifest_path = str(item.get("manifest_path") or "").strip()

        if not suggestion_id:
            errors.append(f"Decision {index + 1} must include suggestion_id.")
            continue
        if suggestion_type != "mapping":
            errors.append(f"Decision {index + 1} has unsupported suggestion_type '{suggestion_type}'.")
            continue
        if status not in _MAPPING_REVIEW_STATUSES:
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


def _append_passthrough_transform_if_missing(session, source: str, target: str) -> bool:
    for transform in session.passthrough_flow.transforms:
        if transform.source == source and transform.target == target:
            return False
    session.passthrough_flow.transforms.append(PassthroughTransform(source=source, target=target))
    return True


def _passthrough_mapping_manifest_path(route_name: str, source: str, target: str) -> str:
    return f"passthrough.{route_name}.transforms.{source}.{target}"


def _passthrough_mapping_review_context(
    route_name: str,
    source: str,
    target: str,
    *,
    source_entity: str = "",
    target_entity: str = "",
) -> dict[str, str]:
    context = {
        "mapping_context": "passthrough",
        "route_name": route_name,
        "direction": "request",
        "source_field": source,
        "target_field": target,
    }
    if source_entity:
        context["source_entity"] = source_entity
    if target_entity:
        context["target_entity"] = target_entity
    return context


def _passthrough_mapping_review_context_from_decision(session, decision: dict[str, Any]) -> dict[str, str] | None:
    payload = decision["payload"] if isinstance(decision.get("payload"), dict) else {}
    edited_payload = decision["edited_payload"] if isinstance(decision.get("edited_payload"), dict) else {}
    route_name = (
        _payload_text(edited_payload, "route_name")
        or _payload_text(payload, "route_name")
        or session.passthrough_flow.upstream_operation_name
        or "route"
    )
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
    if not any((route_name, source, target, source_entity, target_entity)):
        return None
    return _passthrough_mapping_review_context(
        route_name,
        source,
        target,
        source_entity=source_entity,
        target_entity=target_entity,
    )


@router.get("", response_class=HTMLResponse)
async def passthrough_get(request: Request):
    session = get_current_session(request)
    if session.app_archetype != "passthrough-router":
        return RedirectResponse("/entities", status_code=303)
    nav = build_nav_context(session, "/passthrough")

    upstream_operations, selected_upstream = _upstream_operation_context(session)
    downstream_targets = _downstream_context(session)
    downstream_request_fields = sorted({
        field
        for target in downstream_targets
        for op in target["operations"]
        if op["name"] == target["selected_operation_name"]
        for field in op["request_fields"]
    })
    route_name = session.passthrough_flow.upstream_operation_name or ""
    mapping_contexts = _mapping_contexts(
        route_name=route_name,
        selected_upstream=selected_upstream,
        downstream_targets=downstream_targets,
    )
    mapping_suggestion_badge = None
    if mapping_contexts:
        workspace_before = workspace_session_marker(session)
        mapping_suggestion_badge = assist_service.get_mapping_suggestion_badge(
            session,
            route_name=route_name,
            contexts=mapping_contexts,
            drawer_url=f"/passthrough/ks/drawer?{urlencode({'scope': 'mappings', 'route_name': route_name})}",
        )
        save_current_session_if_workspace_changed(request, session, workspace_before)

    return templates.TemplateResponse(request, "step3_passthrough.html", {
        "request": request,
        "session": session,
        "step": 3,
        **nav,
        "upstream_operations": upstream_operations,
        "selected_upstream": selected_upstream,
        "downstream_targets": downstream_targets,
        "downstream_request_fields": downstream_request_fields,
        "existing_routes": [route.model_dump() for route in session.passthrough_flow.routes],
        "existing_transforms": [transform.model_dump() for transform in session.passthrough_flow.transforms],
        "mapping_suggestion_badge": mapping_suggestion_badge,
    })


@router.get("/ks/drawer", response_class=JSONResponse)
async def passthrough_ks_drawer(
    request: Request,
    scope: str = Query("mappings"),
    route_name: str = Query(""),
):
    session = get_current_session(request)
    if session.app_archetype != "passthrough-router":
        return JSONResponse(
            {
                "ok": False,
                "warning": "Passthrough mapping suggestion drawers are available for passthrough-router projects only.",
            },
            status_code=400,
        )
    if scope != "mappings":
        return JSONResponse(
            {
                "ok": False,
                "warning": f"Unsupported passthrough Knowledge Assist drawer scope '{scope}'.",
            },
            status_code=400,
        )

    normalized_route_name = route_name.strip()
    selected_route_name = session.passthrough_flow.upstream_operation_name
    upstream_operations, selected_upstream = _upstream_operation_context(session)
    downstream_targets = _downstream_context(session)
    mapping_contexts = _mapping_contexts(
        route_name=normalized_route_name,
        selected_upstream=selected_upstream,
        downstream_targets=downstream_targets,
    )
    if (
        not normalized_route_name
        or normalized_route_name != selected_route_name
        or not mapping_contexts
    ):
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
    payload["review_url"] = "/passthrough/ks/review"
    return JSONResponse(payload)


@router.post("/ks/review", response_class=JSONResponse)
async def passthrough_ks_review(request: Request):
    session = get_current_session(request)
    if session.app_archetype != "passthrough-router":
        return JSONResponse(
            {"ok": False, "errors": ["Passthrough mapping suggestion review is available for passthrough-router projects only."]},
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

    _, selected_upstream = _upstream_operation_context(session)
    mapping_contexts = _mapping_contexts(
        route_name=session.passthrough_flow.upstream_operation_name or "",
        selected_upstream=selected_upstream,
        downstream_targets=_downstream_context(session),
    )
    candidate_mappings: dict[str, tuple[str, str, str] | None] = {}
    preflight_errors: list[str] = []
    for decision in decisions:
        if decision["status"] in {"accepted", "edited"}:
            source, target, route_name, warning = _validate_mapping_payload(
                _merged_mapping_payload(decision),
                contexts=mapping_contexts,
            )
            if warning:
                preflight_errors.append(f"{decision['suggestion_id']}: {warning}")
                continue
            candidate_mappings[decision["suggestion_id"]] = (source, target, route_name)
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
    ks_details = _ks_outcome_details(ks_result)
    outcomes: list[dict[str, Any]] = []
    warnings: list[str] = []
    response_errors: list[str] = []
    result_warnings = ks_result.get("warnings", [])
    for warning in (result_warnings if isinstance(result_warnings, list) else []):
        if str(warning).strip():
            warnings.append(str(warning))
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
                source, target, route_name = candidate
                applied = _append_passthrough_transform_if_missing(session, source, target)
                if applied:
                    applied_count += 1
                else:
                    warnings.append(f"{suggestion_id}: matching passthrough transform already exists; review was recorded without duplicating it.")
                manifest_path = _passthrough_mapping_manifest_path(route_name, source, target)
                payload = decision["payload"] if isinstance(decision.get("payload"), dict) else {}
                edited_payload = (
                    decision["edited_payload"] if isinstance(decision.get("edited_payload"), dict) else {}
                )
                review_context = _passthrough_mapping_review_context(
                    route_name,
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
                manifest_path = manifest_path or f"passthrough.{session.passthrough_flow.upstream_operation_name or 'route'}.transforms.{suggestion_id}"
                review_context = _passthrough_mapping_review_context_from_decision(session, decision)
            record_review_history_without_evidence(
                session,
                suggestion_id=suggestion_id,
                suggestion_type="mapping",
                status=decision["status"],
                manifest_path=manifest_path,
                edited_payload=(
                    _ks_mapping_edited_payload(decision)
                    if decision["status"] == "edited"
                    else decision["edited_payload"]
                ),
                review_context=review_context,
            )
        else:
            detail = ks_details.get(suggestion_id, {})
            for message in detail.get("errors", []):
                response_errors.append(f"{suggestion_id}: {message}")
            for message in detail.get("warnings", []):
                warnings.append(f"{suggestion_id}: {message}")
        outcomes.append(
            {
                "suggestion_id": suggestion_id,
                "status": decision["status"],
                "success": success,
                "applied": applied,
                "manifest_path": manifest_path,
                "errors": ks_details.get(suggestion_id, {}).get("errors", []),
                "warnings": ks_details.get(suggestion_id, {}).get("warnings", []),
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
            "errors": response_errors,
        }
    )


@router.post("/describe-spec", response_class=JSONResponse)
async def describe_spec(request: Request):
    body = await request.json()
    try:
        source_mode = (body.get("source_mode") or "text").strip()
        spec_url = (body.get("spec_url") or "").strip() or None
        spec_content = (body.get("spec_content") or "").strip() or None
        if source_mode == "url":
            spec = await fetch_openapi_spec_for_request(request, spec_url=spec_url)
            normalized_content = dump_openapi_spec(spec)
        else:
            spec = load_openapi_spec(spec_url=None, spec_content=spec_content)
            normalized_content = spec_content or dump_openapi_spec(spec)
        return JSONResponse({
            "ok": True,
            "operations": extract_operation_descriptors(spec),
            "normalized_spec_content": normalized_content,
        })
    except RemoteOpenAPIFetchRateLimitedError as exc:
        return resource_limit_rejection_response(
            path=request.url.path,
            retry_after_seconds=exc.retry_after_seconds,
        )
    except RemoteOpenAPIFetchUnavailableError:
        return resource_limit_unavailable_response(path=request.url.path)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@router.post("/save", response_class=JSONResponse)
async def passthrough_save(request: Request):
    body = await request.json()
    session = get_current_session(request)

    if session.app_archetype != "passthrough-router":
        return JSONResponse({"ok": False, "error": "Current project archetype is not passthrough-router."}, status_code=400)
    if not session.raw_spec_content:
        return JSONResponse({"ok": False, "error": "Ingest the upstream OpenAPI spec first."}, status_code=400)

    upstream_spec = load_openapi_spec(spec_content=session.raw_spec_content, spec_url=None)
    upstream_operations = extract_operation_descriptors(upstream_spec)
    upstream_operation_name = (body.get("upstream_operation_name") or "").strip()
    selected_upstream = next((op for op in upstream_operations if op["name"] == upstream_operation_name), None)
    if selected_upstream is None:
        return JSONResponse({"ok": False, "error": "Select one upstream operation for the passthrough flow."}, status_code=400)

    downstream_interfaces = []
    downstream_request_fields: set[str] = set()
    downstream_systems: set[str] = set()

    for raw in body.get("downstream_targets", []):
        name = (raw.get("name") or "").strip()
        system = (raw.get("system") or "").strip()
        source_mode = (raw.get("source_mode") or "text").strip()
        spec_url = (raw.get("spec_url") or "").strip() or None
        spec_content = (raw.get("spec_content") or "").strip() or None
        selected_operation_name = (raw.get("selected_operation_name") or "").strip()

        if not name or not system:
            continue
        if system in downstream_systems:
            return JSONResponse({"ok": False, "error": f"Downstream system '{system}' is duplicated. Use unique target system names."}, status_code=400)

        try:
            if source_mode == "url":
                spec = await fetch_openapi_spec_for_request(request, spec_url=spec_url)
                spec_content = dump_openapi_spec(spec)
            else:
                spec = load_openapi_spec(spec_url=None, spec_content=spec_content)
                spec_content = spec_content or dump_openapi_spec(spec)
        except RemoteOpenAPIFetchRateLimitedError as exc:
            return resource_limit_rejection_response(
                path=request.url.path,
                retry_after_seconds=exc.retry_after_seconds,
            )
        except RemoteOpenAPIFetchUnavailableError:
            return resource_limit_unavailable_response(path=request.url.path)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"[{name}] {exc}"}, status_code=400)

        operations = extract_operation_descriptors(spec)
        selected_operation = next((op for op in operations if op["name"] == selected_operation_name), None)
        if selected_operation is None:
            return JSONResponse({"ok": False, "error": f"[{name}] Select one downstream target operation."}, status_code=400)

        downstream_request_fields.update(selected_operation["request_fields"])
        downstream_systems.add(system)
        downstream_interfaces.append(
            build_passthrough_downstream_interface(
                name=name,
                system=system,
                spec_url=spec_url,
                spec_content=spec_content,
                selected_operation_name=selected_operation_name,
            )
        )

    if not downstream_interfaces:
        return JSONResponse({"ok": False, "error": "Add at least one downstream target."}, status_code=400)

    route_field = (body.get("route_field") or "").strip()
    default_target = (body.get("default_target") or "").strip()
    routes = [
        {"match": (row.get("match") or "").strip(), "target": (row.get("target") or "").strip()}
        for row in body.get("routes", [])
        if (row.get("match") or "").strip() and (row.get("target") or "").strip()
    ]
    transforms = [
        {
            "source": (row.get("source") or "").strip(),
            "target": (row.get("target") or "").strip(),
            "default": (row.get("default") or "").strip() or None,
        }
        for row in body.get("transforms", [])
        if (row.get("source") or "").strip() and (row.get("target") or "").strip()
    ]

    upstream_request_fields = set(selected_upstream["request_fields"])
    if route_field not in upstream_request_fields:
        return JSONResponse({"ok": False, "error": f"Routing field '{route_field}' is not present in the passthrough upstream request contract."}, status_code=400)
    if default_target not in downstream_systems:
        return JSONResponse({"ok": False, "error": f"Default routing target '{default_target}' does not match any downstream interface system."}, status_code=400)
    for route in routes:
        if route["target"] not in downstream_systems:
            return JSONResponse({"ok": False, "error": f"Routing target '{route['target']}' does not match any downstream interface system."}, status_code=400)
    if not routes:
        return JSONResponse({"ok": False, "error": "Add at least one equality-match routing row."}, status_code=400)
    if not transforms:
        return JSONResponse({"ok": False, "error": "Add at least one flat transform mapping."}, status_code=400)
    for transform in transforms:
        if transform["source"] not in upstream_request_fields:
            return JSONResponse({"ok": False, "error": f"Transform source '{transform['source']}' is not present in the passthrough upstream request contract."}, status_code=400)
        if transform["target"] not in downstream_request_fields:
            return JSONResponse({"ok": False, "error": f"Transform target '{transform['target']}' is not present in the passthrough downstream request contracts."}, status_code=400)

    upstream_filename = session.raw_spec_filename or f"{_slug(session.bounded_context or 'app')}-passthrough-upstream.yaml"
    session.upstream_interfaces = [
        build_passthrough_upstream_interface(
            bounded_context=session.bounded_context,
            spec_url=session.raw_spec_url,
            spec_content=session.raw_spec_content,
            spec_filename=upstream_filename,
            upstream_operation_name=upstream_operation_name,
        )
    ]
    session.downstream_interfaces = downstream_interfaces
    session.data_handoffs = []
    session.entity_rules = []
    session.selected_entity_names = []
    session.selected_operation_names = []
    session.passthrough_flow = build_passthrough_flow(
        upstream_operation_name=upstream_operation_name,
        route_field=route_field,
        routes=routes,
        default_target=default_target,
        transforms=transforms,
    )
    save_current_session(request, session)
    return JSONResponse({
        "ok": True,
        "upstream_request_fields": sorted(upstream_request_fields),
        "downstream_request_fields": sorted(downstream_request_fields),
        "downstream_count": len(downstream_interfaces),
    })


@router.get("/next")
async def passthrough_next():
    return RedirectResponse("/review", status_code=303)
