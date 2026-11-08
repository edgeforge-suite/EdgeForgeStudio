"""S1A Save/Open Project routes.

POST /project/save  — snapshot current session → return .json file download
POST /project/open  — upload .json file → restore session → redirect to Step 1
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.middleware.upload_request_policy import upload_rejected_response
from app.paths import TEMPLATE_DIR
from app.services.audit import audit
from app.services.build_run_service import stop_generated_app
from app.services.csrf import require_form_csrf
from app.services.project_file_service import (
    deserialize_project,
    restore_session,
    serialize_project,
    snapshot_session_for_save,
)
from app.services.runtime_defaults import (
    default_edgeforge_repo_path,
    default_output_path,
    is_docker_runtime,
    is_host_style_path,
)
from app.services.session_context import get_current_session, save_current_session
from app.services.upload_limits import (
    PROJECT_UPLOAD_POLICY,
    UploadFilePolicyError,
    UploadTooLargeError,
    read_upload_limited,
    validate_upload_file,
)

router = APIRouter(prefix="/project")
templates = Jinja2Templates(directory=TEMPLATE_DIR)


def _safe_slug(text: str) -> str:
    """Convert arbitrary text to a filename-safe slug."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "project"


def _normalize_docker_loaded_paths(session) -> bool:
    """Rewrite host-only saved paths to Docker-visible defaults when needed."""
    if not is_docker_runtime():
        return False

    changed = False
    if is_host_style_path(session.appbuilder_repo_path):
        session.appbuilder_repo_path = default_edgeforge_repo_path()
        changed = True
    if is_host_style_path(session.output_path):
        session.output_path = default_output_path()
        changed = True
    if is_host_style_path(session.last_export_path):
        session.last_export_path = None
        changed = True
    return changed


# ---------------------------------------------------------------------------
# Save Project
# ---------------------------------------------------------------------------


@router.post("/save")
async def save_project(request: Request, _csrf: None = Depends(require_form_csrf)) -> Response:
    """Snapshot the current session and return it as a downloadable JSON file."""
    session = get_current_session(request)
    project = snapshot_session_for_save(session)
    save_current_session(request, session)
    content = serialize_project(project)
    audit(request, "project.save", outcome="success")

    slug = _safe_slug(session.bounded_context or session.app_name)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"edgeforge-studio-{slug}-{timestamp}.json"

    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


# ---------------------------------------------------------------------------
# Open Project
# ---------------------------------------------------------------------------


@router.post("/open", response_class=HTMLResponse)
async def open_project(
    request: Request,
    _csrf: None = Depends(require_form_csrf),
    project_file: UploadFile = File(...),
) -> HTMLResponse:
    """Accept an uploaded Studio project JSON file and restore the session."""
    try:
        validate_upload_file(project_file, policy=PROJECT_UPLOAD_POLICY)
    except UploadFilePolicyError as exc:
        return upload_rejected_response(
            path="/project/open",
            status_code=415,
            message=str(exc),
        )

    session = get_current_session(request)
    try:
        raw = await read_upload_limited(project_file)
    except UploadTooLargeError as exc:
        audit(request, "project.open", outcome="blocked")
        return templates.TemplateResponse(
            request,
            "project_open_error.html",
            {
                "request": request,
                "error": str(exc),
                "step": 1,
            },
            status_code=413,
        )

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        audit(request, "project.open", outcome="blocked")
        return templates.TemplateResponse(
            request,
            "project_open_error.html",
            {
                "request": request,
                "error": f"Project file is not valid UTF-8: {exc}",
                "step": 1,
            },
            status_code=400,
        )

    try:
        project = deserialize_project(text)
    except ValueError as exc:
        audit(request, "project.open", outcome="blocked")
        return templates.TemplateResponse(
            request,
            "project_open_error.html",
            {
                "request": request,
                "error": str(exc),
                "step": 1,
            },
            status_code=400,
        )

    # Stop any previously running generated app before the session is replaced.
    # This must happen before restore_session() resets build_run, because
    # restore_session() clears the PID — if we stop after, the handle is gone
    # and the Java process would be left running in the background.
    stop_generated_app(session.build_run)
    restore_session(project, session)
    paths_corrected = _normalize_docker_loaded_paths(session)
    save_current_session(request, session)
    audit(request, "project.open", outcome="success")

    redirect_url = "/?project_notice=docker-paths-corrected" if paths_corrected else "/"
    return RedirectResponse(redirect_url, status_code=303)
