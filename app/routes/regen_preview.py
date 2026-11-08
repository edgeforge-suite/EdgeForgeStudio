"""Read-only regeneration preview routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.paths import TEMPLATE_DIR
from app.services.audit import audit
from app.services.csrf import CSRF_FORM_FIELD_NAME, require_form_csrf
from app.services.nav_context import build_nav_context
from app.services.regen_preview import apply_regen_plan, build_regen_preview
from app.services.session_context import get_current_session, save_current_session
from app.services.settings import get_studio_settings

router = APIRouter(prefix="/regen")
templates = Jinja2Templates(directory=TEMPLATE_DIR)


async def require_regen_apply_form_csrf(
    request: Request,
    token: Annotated[str, Form(alias=CSRF_FORM_FIELD_NAME)] = "",
) -> None:
    """Validate regen apply form CSRF after preserving flag-off 404 behavior."""

    if not get_studio_settings().regen_preview_enabled:
        raise HTTPException(status_code=404, detail="Regeneration preview is disabled.")
    await require_form_csrf(request, token)


@router.get("/preview", response_class=HTMLResponse)
async def regen_preview_get(request: Request):
    session = get_current_session(request)
    settings = get_studio_settings()
    preview = build_regen_preview(session, settings)
    if preview["state"] == "disabled":
        raise HTTPException(status_code=404, detail="Regeneration preview is disabled.")

    request.state.regen_plan_hash = preview.get("plan_hash")
    request.state.regen_package_state_hash = preview.get("package_state_hash")
    nav = build_nav_context(session, "/export")
    return templates.TemplateResponse(
        request,
        "regen_preview.html",
        {
            "request": request,
            "session": session,
            "step": 8,
            "preview": preview,
            **nav,
        },
    )


@router.post("/apply", response_class=HTMLResponse)
async def regen_apply_post(
    request: Request,
    approved_plan_hash: str = Form(""),
    _csrf: None = Depends(require_regen_apply_form_csrf),
):
    session = get_current_session(request)
    settings = get_studio_settings()
    if not settings.regen_preview_enabled:
        raise HTTPException(status_code=404, detail="Regeneration preview is disabled.")

    apply_result = apply_regen_plan(
        session,
        settings,
        approved_plan_hash=approved_plan_hash,
    )
    if apply_result["state"] == "applied":
        save_current_session(request, session)
        preview = build_regen_preview(session, settings)
    elif apply_result["state"] == "busy":
        preview = {
            "state": "empty",
            "status": "regenerate-ready",
            "message": apply_result["message"],
        }
    else:
        preview = apply_result.get("preview") or build_regen_preview(session, settings)
    audit(
        request,
        "regen.apply",
        outcome="success" if apply_result["state"] == "applied" else "blocked",
    )

    request.state.regen_plan_hash = preview.get("plan_hash")
    request.state.regen_package_state_hash = preview.get("package_state_hash")
    nav = build_nav_context(session, "/export")
    return templates.TemplateResponse(
        request,
        "regen_preview.html",
        {
            "request": request,
            "session": session,
            "step": 8,
            "preview": preview,
            "apply_result": apply_result,
            **nav,
        },
        status_code=409 if apply_result["state"] == "busy" else 200,
    )
