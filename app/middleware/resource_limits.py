"""Shared-mode request rate and concurrency controls."""

from __future__ import annotations

from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.paths import TEMPLATE_DIR
from app.services.request_resource_limits import (
    HTML_RATE_LIMITED_PATHS,
    ResourceLimitPermit,
    ResourceLimitPrincipalUnavailable,
    ResourceLimitRejection,
    get_request_resource_limiter,
    request_cost_class,
    try_acquire_request_resource,
)

_TEMPLATES = Jinja2Templates(directory=TEMPLATE_DIR)
_LIMIT_MESSAGE = "Request limit reached. Please retry later."
_UNAVAILABLE_MESSAGE = "Request processing is temporarily unavailable."


def resource_limit_rejection_response(*, path: str, retry_after_seconds: int) -> Response:
    """Return the fixed JSON or standalone HTML response for a 429 rejection."""

    html_context = HTML_RATE_LIMITED_PATHS.get(path)
    headers = {"Retry-After": str(retry_after_seconds)}
    if html_context is None:
        return JSONResponse(
            {
                "ok": False,
                "error": _LIMIT_MESSAGE,
                "retry_after": retry_after_seconds,
            },
            status_code=429,
            headers=headers,
        )

    back_href, back_label = html_context
    content = _TEMPLATES.get_template("errors/rate_limited.html").render(
        status_code=429,
        message=_LIMIT_MESSAGE,
        retry_after_seconds=retry_after_seconds,
        back_href=back_href,
        back_label=back_label,
    )
    return HTMLResponse(content, status_code=429, headers=headers)


def resource_limit_unavailable_response(*, path: str) -> Response:
    """Fail closed without exposing request-state or identity internals."""

    html_context = HTML_RATE_LIMITED_PATHS.get(path)
    if html_context is None:
        return JSONResponse(
            {"ok": False, "error": _UNAVAILABLE_MESSAGE},
            status_code=503,
        )
    back_href, back_label = html_context
    content = _TEMPLATES.get_template("errors/rate_limited.html").render(
        status_code=503,
        message=_UNAVAILABLE_MESSAGE,
        retry_after_seconds=None,
        back_href=back_href,
        back_label=back_label,
    )
    return HTMLResponse(content, status_code=503)


class ResourceControlMiddleware(BaseHTTPMiddleware):
    """Apply only the approved shared-mode controls after request context exists."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # This must remain the first resource-control action: local mode does not
        # classify, derive an identity key, or touch limiter state.
        if not getattr(request.state, "studio_shared_mode", False):
            return await call_next(request)

        cost_class = request_cost_class(request.method, request.url.path)
        if cost_class is None:
            return await call_next(request)

        decision = await try_acquire_request_resource(request, cost_class=cost_class)
        if isinstance(decision, ResourceLimitPrincipalUnavailable):
            request.state.csrf_pre_route_rejection = True
            return resource_limit_unavailable_response(path=request.url.path)
        if isinstance(decision, ResourceLimitRejection):
            # Native-form CSRF is validated by the route after multipart parsing.
            # Tell request context this deliberate pre-route rejection must retain
            # its bounded 429 response rather than be rewritten to a false 403.
            request.state.csrf_pre_route_rejection = True
            return resource_limit_rejection_response(
                path=request.url.path,
                retry_after_seconds=decision.retry_after_seconds,
            )

        assert decision is not None
        permit: ResourceLimitPermit = decision
        try:
            return await call_next(request)
        finally:
            # Routes may reject deferred multipart CSRF, raise, disconnect, or be
            # cancelled. None of those paths may leave capacity wedged.
            await get_request_resource_limiter().release(permit)
