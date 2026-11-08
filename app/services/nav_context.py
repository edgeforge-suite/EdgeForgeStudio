"""Wizard navigation context helpers."""

from __future__ import annotations

from typing import Any

from app.models.project import ProjectSession
from app.services import readiness_view
from app.services.kafka_route_inventory import has_kafka_route_anchors
from app.wizard_registry import get_archetype_label, get_steps


def _step1_complete(session: ProjectSession) -> bool:
    return all(
        [
            session.app_name.strip(),
            session.bounded_context.strip(),
            session.app_archetype.strip(),
            session.target_profile.strip(),
            session.output_path.strip(),
        ]
    )


def _step2_complete(session: ProjectSession) -> bool:
    if session.app_archetype == "kafka-integration":
        return has_kafka_route_anchors(session)
    return bool(
        session.raw_spec_content
        or session.raw_spec_url
        or session.raw_spec_filename
        or session.upstream_interfaces
    )


def _step3_complete(session: ProjectSession) -> bool:
    if session.app_archetype == "kafka-integration":
        return bool(session.kafka_route_models)
    if session.app_archetype == "passthrough-router":
        flow = session.passthrough_flow
        return bool(
            flow.upstream_operation_name
            and flow.route_field
            and flow.routes
            and flow.transforms
            and session.downstream_interfaces
        )
    return bool(session.selected_entity_names and session.selected_operation_names)


def _step4_complete(session: ProjectSession) -> bool:
    if session.app_archetype == "kafka-integration":
        return bool(session.kafka_route_transforms)
    if session.app_archetype == "crud":
        return bool(session.data_handoffs)
    return False


def _step5_complete(session: ProjectSession) -> bool:
    if session.app_archetype == "crud":
        return bool(session.downstream_interfaces)
    return False


def _step8_complete(session: ProjectSession) -> bool:
    return bool(session.last_export_path)


def _step_complete(session: ProjectSession, position: int) -> bool:
    if position == 1:
        return _step1_complete(session)
    if position == 2:
        return _step2_complete(session)
    if position == 3:
        return _step3_complete(session)
    if position == 4:
        return _step4_complete(session)
    if position == 5:
        return _step5_complete(session)
    if position == 8:
        return _step8_complete(session)
    return False


def _current_step_index(nav_steps: list[dict[str, Any]]) -> int:
    active = next((step for step in nav_steps if step["is_active"]), None)
    if active is not None:
        return active["position"]
    return 1


def build_nav_context(session: ProjectSession, current_route: str) -> dict[str, Any]:
    nav_steps: list[dict[str, Any]] = []
    for step in get_steps(session.app_archetype):
        is_active = current_route == step.route
        is_complete = False
        state = "open"
        if not step.applicable:
            state = "not-applicable"
        elif is_active:
            state = "active"
        else:
            is_complete = _step_complete(session, step.position)
            if is_complete:
                state = "complete"

        nav_steps.append(
            {
                "position": step.position,
                "step_id": step.step_id,
                "label": step.label,
                "route": step.route,
                "is_active": is_active,
                "is_complete": is_complete,
                "is_applicable": step.applicable,
                "state": state,
                "state_label": "Not applicable" if state == "not-applicable" else state.title(),
                "suggestion_scope": step.suggestion_scope,
            }
        )

    current_step = next((step for step in nav_steps if step["is_active"]), nav_steps[0])
    current_step_index = _current_step_index(nav_steps)
    # Rail count/attention chips are a pure projection of readiness_view.
    # PR-24 makes the refreshed shell the only presentation, so this projection
    # is no longer conditional on a deployment flag.
    counts = readiness_view.step_counts(session)
    for nav_step in nav_steps:
        bucket = counts.get(nav_step["position"])
        if bucket is not None:
            nav_step["count"] = bucket["count"]
            nav_step["attention"] = bucket["attention"]

    return {
        "nav_steps": nav_steps,
        "total_steps": 8,
        "shell_project_name": session.app_name or session.bounded_context or "Untitled project",
        "shell_project_context": session.bounded_context or "",
        "shell_archetype_label": get_archetype_label(session.app_archetype),
        "shell_current_step": current_step,
        "shell_step_index": current_step_index,
        # Compatibility keys remain while the refreshed templates are slimmed.
        # They are intentionally constant after PR-24: refresh is the sole UX,
        # and focused Steps 4/5/6 use the responsive split presentation.
        "ux_refresh": True,
        "ux_split": True,
    }
