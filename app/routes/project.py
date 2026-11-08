"""Step 1 — Project Setup."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.models.project_capabilities import ProjectCapabilities
from app.paths import TEMPLATE_DIR
from app.services.audit import audit
from app.services.build_run_service import stop_generated_app
from app.services.csrf import require_form_csrf
from app.services.ks_workspace_summary import build_workspace_summary
from app.services.nav_context import build_nav_context
from app.services.runtime_defaults import default_edgeforge_repo_path
from app.services.session_context import get_current_session, save_current_session
from app.services.settings import get_studio_settings

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATE_DIR)

TARGET_PROFILES = [
    {"id": "springboot-legacy-compatible", "label": "Spring Boot Legacy Compatible (Java 17 + H2)"},
    {
        "id": "springboot-enterprise-postgres-java17",
        "label": "Spring Boot Enterprise Postgres (Java 17 + PostgreSQL)",
    },
    {"id": "springboot-standard-enterprise", "label": "Spring Boot Standard Enterprise (Java 21 + PostgreSQL)"},
]

DEFAULT_EDGEFORGE_PATH = default_edgeforge_repo_path()
ASSIST_NOTICE_MESSAGES = {
    "knowledge-off": "Knowledge Assist is off. Enable it in Step 1 to use the Knowledge Workspace.",
}


def _project_notice_message(notice: str) -> str | None:
    if notice == "docker-paths-corrected":
        return "Project paths were adjusted for this runtime. Review Engine Path and Output Path before exporting."
    return None


APP_ARCHETYPES = [
    {"id": "crud", "label": "CRUD", "description": "Entity-centric bounded context with the current Studio wizard flow."},
    {"id": "passthrough-router", "label": "Passthrough Router", "description": "One inbound REST operation, simple routing, default target, and flat transforms."},
    {"id": "kafka-integration", "label": "Kafka Integration", "description": "Async Kafka mediation with fire-and-forget and request-reply route patterns."},
]


def _reset_flow_state(session) -> None:
    session.project_id = None
    session.ks_project_id = None
    session.ks_active = False
    session.capabilities = ProjectCapabilities()
    session.ks_workspace_state = session.ks_workspace_state.__class__()
    session.review_approved = False
    session.project_revision = 1
    session.created_at = None
    session.updated_at = None
    session.saved_at = None
    session.created_by = None
    session.modified_by = None
    session.is_brand_new = True
    session.raw_spec_content = None
    session.raw_spec_url = None
    session.raw_spec_filename = None
    session.classified_entities = []
    session.classified_operations = []
    session.selected_entity_names = []
    session.selected_operation_names = []
    session.upstream_interfaces = []
    session.downstream_interfaces = []
    session.data_handoffs = []
    session.entity_rules = []
    session.last_export_path = None
    session.build_run = session.build_run.__class__()
    session.passthrough_flow = session.passthrough_flow.__class__()
    session.kafka_config = session.kafka_config.__class__()
    session.kafka_topic_pairs = []
    session.kafka_route_models = []
    session.kafka_route_transforms = []


def _next_path_for_archetype(archetype: str) -> str:
    if archetype == "kafka-integration":
        return "/kafka/topics"
    return "/upstream"


def _next_step_label_for_archetype(archetype: str) -> str:
    if archetype == "kafka-integration":
        return "Topic Ingest"
    return "Upstream Contract"


def _next_step_hint_for_archetype(archetype: str) -> str:
    if archetype == "kafka-integration":
        return "After save, continue into consumer-group setup and your first topic pair."
    if archetype == "passthrough-router":
        return "After save, continue into the inbound contract before constrained route setup."
    return "After save, continue into the inbound contract before entity and operation modeling."


@router.get("/", response_class=HTMLResponse)
async def step1_get(request: Request):
    session = get_current_session(request)
    nav = build_nav_context(session, "/")
    assist_notice = request.query_params.get("assist_notice", "")
    project_notice = request.query_params.get("project_notice", "")
    knowledge_assist_enabled = session.capabilities.knowledge_assist_enabled
    workspace_summary = build_workspace_summary(session) if knowledge_assist_enabled else None
    return templates.TemplateResponse(request, "step1_project.html", {
        "request": request,
        "session": session,
        "profiles": TARGET_PROFILES,
        "app_archetypes": APP_ARCHETYPES,
        "knowledge_assist_enabled": knowledge_assist_enabled,
        "assist_notice_message": ASSIST_NOTICE_MESSAGES.get(assist_notice),
        "project_notice_message": _project_notice_message(project_notice),
        "workspace_summary": workspace_summary,
        "next_step_label": _next_step_label_for_archetype(session.app_archetype),
        "next_step_hint": _next_step_hint_for_archetype(session.app_archetype),
        "step": 1,
        **nav,
    })


@router.post("/", response_class=HTMLResponse)
async def step1_post(
    request: Request,
    _csrf: None = Depends(require_form_csrf),
    app_name: str = Form(""),
    bounded_context: str = Form(""),
    app_archetype: str = Form("crud"),
    target_profile: str = Form(""),
    output_path: str = Form(""),
    appbuilder_repo_path: str = Form(DEFAULT_EDGEFORGE_PATH),
    knowledge_assist_enabled: Optional[str] = Form(None),
):
    session = get_current_session(request)
    settings = get_studio_settings()
    previous_archetype = session.app_archetype
    session.app_name = app_name.strip()
    session.bounded_context = bounded_context.strip()
    session.app_archetype = app_archetype.strip() or "crud"
    session.target_profile = target_profile.strip()
    if settings.shared_mode:
        session.output_path = ""
        session.appbuilder_repo_path = ""
    else:
        session.output_path = output_path.strip()
        session.appbuilder_repo_path = appbuilder_repo_path.strip() or default_edgeforge_repo_path()
    if previous_archetype != session.app_archetype:
        stop_generated_app(session.build_run)
        _reset_flow_state(session)
    else:
        assist_enabled = knowledge_assist_enabled == "on"
        session.capabilities.knowledge_assist_enabled = assist_enabled
        if not assist_enabled:
            session.ks_active = False
    save_current_session(request, session)
    audit(request, "project.create", outcome="success")
    return RedirectResponse(_next_path_for_archetype(session.app_archetype), status_code=303)
