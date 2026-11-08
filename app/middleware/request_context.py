"""Request-context middleware for the P1 identity/session seam."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.services.audit import get_audit_health_snapshot
from app.services.csrf import (
    SAFE_METHODS,
    CsrfValidationError,
    csrf_token_from_request,
    issue_csrf_token,
    validate_csrf_request,
)
from app.services.identity import (
    IdentityProviderUnavailable,
    SessionCookieUpdate,
    get_identity_provider,
)
from app.services.session_context import get_session_store
from app.services.settings import get_studio_settings


def _is_form_content_type(request: Request) -> bool:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    return content_type in {"application/x-www-form-urlencoded", "multipart/form-data"}


_ROUTE_FORM_CSRF_PATHS = {
    "/",
    "/project/save",
    "/project/open",
    "/knowledge/upload",
    "/knowledge/delete",
    "/regen/apply",
}


def _uses_route_form_csrf(request: Request) -> bool:
    return request.method.upper() == "POST" and request.url.path in _ROUTE_FORM_CSRF_PATHS


class StudioRequestContextMiddleware(BaseHTTPMiddleware):
    """Resolve principal/session context and apply seam-scoped CSRF checks."""

    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_studio_settings()
        request.state.audit_health = get_audit_health_snapshot()
        request.state.studio_shared_mode = settings.shared_mode
        provider = get_identity_provider(settings)
        try:
            principal = provider.resolve(request)
        except IdentityProviderUnavailable as exc:
            return JSONResponse(
                {
                    "ok": False,
                    "error": str(exc),
                },
                status_code=501,
            )
        request.state.principal = principal
        request.state.session_store = get_session_store()
        request.state.csrf_token = issue_csrf_token(principal, settings=settings)

        form_csrf_deferred = False
        if settings.csrf_enforced:
            try:
                if (
                    request.method.upper() not in SAFE_METHODS
                    and _is_form_content_type(request)
                    and not csrf_token_from_request(request)
                    and _uses_route_form_csrf(request)
                ):
                    form_csrf_deferred = True
                    request.state.csrf_form_validation_required = True
                else:
                    validate_csrf_request(request, principal, settings=settings)
                    if request.method.upper() not in SAFE_METHODS:
                        request.state.csrf_header_validated = True
            except CsrfValidationError as exc:
                return JSONResponse(
                    {
                        "ok": False,
                        "error": str(exc) or "Invalid CSRF token.",
                    },
                    status_code=403,
                )

        response = await call_next(request)
        if (
            form_csrf_deferred
            and not getattr(request.state, "csrf_form_validated", False)
            and not getattr(request.state, "csrf_pre_route_rejection", False)
            and response.status_code != 403
        ):
            return JSONResponse(
                {
                    "ok": False,
                    "error": "Missing CSRF token.",
                },
                status_code=403,
            )
        cookie_update = getattr(request.state, "studio_session_cookie_update", None)
        if isinstance(cookie_update, SessionCookieUpdate):
            expires = datetime.now(timezone.utc) + timedelta(
                seconds=cookie_update.max_age_seconds
            )
            response.set_cookie(
                settings.session_cookie_name,
                cookie_update.value,
                max_age=cookie_update.max_age_seconds,
                expires=expires,
                httponly=True,
                secure=settings.cookie_secure,
                samesite="lax",
            )
        return response
