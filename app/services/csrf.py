"""CSRF token utilities for Studio request-context middleware."""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import Form, HTTPException
from starlette.requests import Request

from app.services.identity import Principal, get_current_principal
from app.services.settings import StudioSettings, get_studio_settings
from app.services.signed_tokens import SignedTokenError, sign_payload, verify_payload

CSRF_HEADER_NAME = "x-edgeforge-csrf-token"
CSRF_FORM_FIELD_NAME = "_edgeforge_csrf_token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


class CsrfValidationError(ValueError):
    """Raised when a CSRF token is missing or invalid."""


def issue_csrf_token(
    principal: Principal,
    *,
    settings: StudioSettings | None = None,
    issued_at: int | None = None,
) -> str:
    settings = settings or get_studio_settings()
    now = int(issued_at or time.time())
    return sign_payload(
        {
            "sub": principal.user_id,
            "sid": principal.claims.get("anonymous_session_id") or principal.user_id,
            "iat": now,
            "exp": now + settings.session_max_age_seconds,
        },
        secret=settings.session_secret,
    )


def validate_csrf_token(
    token: str | None,
    principal: Principal,
    *,
    settings: StudioSettings | None = None,
) -> bool:
    if not token:
        raise CsrfValidationError("Missing CSRF token.")
    settings = settings or get_studio_settings()
    try:
        payload = verify_payload(token, secret=settings.session_secret)
        expires_at = int(payload.get("exp") or 0)
    except (SignedTokenError, TypeError, ValueError) as exc:
        raise CsrfValidationError("Invalid CSRF token.") from exc
    if expires_at <= int(time.time()):
        raise CsrfValidationError("Expired CSRF token.")
    expected_sid = principal.claims.get("anonymous_session_id") or principal.user_id
    if payload.get("sub") != principal.user_id or payload.get("sid") != expected_sid:
        raise CsrfValidationError("CSRF token does not match the current session.")
    return True


def csrf_token_from_request(request: Request) -> str | None:
    return request.headers.get(CSRF_HEADER_NAME) or request.headers.get("x-csrf-token")


def validate_csrf_request(
    request: Request,
    principal: Principal,
    *,
    settings: StudioSettings | None = None,
) -> bool:
    if request.method.upper() in SAFE_METHODS:
        return True
    return validate_csrf_token(
        csrf_token_from_request(request),
        principal,
        settings=settings or get_studio_settings(),
    )


async def require_form_csrf(
    request: Request,
    token: Annotated[str, Form(alias=CSRF_FORM_FIELD_NAME)] = "",
) -> None:
    """Validate a CSRF token carried by a native HTML form body.

    Middleware intentionally does not call ``request.form()`` because doing so
    would consume the request body before FastAPI can bind handler parameters.
    Native forms attach this dependency so FastAPI parses the form once and the
    dependency validates the token alongside the route's normal fields/files.
    """

    settings = get_studio_settings()
    if not settings.csrf_enforced:
        return
    if not token and getattr(request.state, "csrf_header_validated", False):
        request.state.csrf_form_validated = True
        return
    try:
        validate_csrf_token(
            token,
            get_current_principal(request),
            settings=settings,
        )
    except CsrfValidationError as exc:
        raise HTTPException(status_code=403, detail=str(exc) or "Invalid CSRF token.") from exc
    request.state.csrf_form_validated = True
