"""Identity seam for Studio request context.

P1 wires the anonymous browser-session adapter only. Proxy/OIDC classes are
interface placeholders for later phases.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from starlette.requests import Request

from app.services.settings import StudioSettings, get_studio_settings
from app.services.signed_tokens import SignedTokenError, sign_payload, verify_payload

PrincipalSource = Literal["anonymous", "proxy", "oidc"]


@dataclass(frozen=True)
class Principal:
    user_id: str
    display_name: str | None = None
    source: PrincipalSource = "anonymous"
    claims: dict[str, Any] = field(default_factory=dict)


class IdentityProvider(Protocol):
    def resolve(self, request: Request) -> Principal:
        """Resolve a Principal for the current request."""


class IdentityProviderUnavailable(RuntimeError):
    """Raised when a configured identity provider is intentionally not wired yet."""


@dataclass(frozen=True)
class SessionCookieUpdate:
    value: str
    max_age_seconds: int


class AnonymousSessionIdentity:
    """Anonymous signed-cookie identity provider for local and P1 shared seams."""

    def __init__(self, settings: StudioSettings | None = None) -> None:
        self.settings = settings or get_studio_settings()

    def resolve(self, request: Request) -> Principal:
        now = int(time.time())
        token = request.cookies.get(self.settings.session_cookie_name)
        session_id: str | None = None
        issued_at = now
        should_rotate = False

        if token:
            try:
                payload = verify_payload(token, secret=self.settings.session_secret)
                session_id = str(payload.get("sid") or "")
                issued_at = int(payload.get("iat") or now)
                expires_at = int(payload.get("exp") or 0)
                if not session_id or expires_at <= now:
                    session_id = None
                elif now - issued_at >= self.settings.session_rotation_seconds:
                    should_rotate = True
            except (SignedTokenError, TypeError, ValueError):
                session_id = None

        if not session_id:
            session_id = secrets.token_urlsafe(24)
            issued_at = now
            should_rotate = True

        cookie_value = token
        if should_rotate or not cookie_value:
            cookie_value = self._make_cookie(session_id=session_id, issued_at=now)
            request.state.studio_session_cookie_update = SessionCookieUpdate(
                value=cookie_value,
                max_age_seconds=self.settings.session_max_age_seconds,
            )

        request.state.studio_anonymous_session_id = session_id
        return Principal(
            user_id=f"anonymous:{session_id}",
            display_name="Anonymous Studio Session",
            source="anonymous",
            claims={"anonymous_session_id": session_id, "issued_at": issued_at},
        )

    def _make_cookie(self, *, session_id: str, issued_at: int) -> str:
        return sign_payload(
            {
                "sid": session_id,
                "iat": issued_at,
                "exp": issued_at + self.settings.session_max_age_seconds,
            },
            secret=self.settings.session_secret,
        )


class ProxyHeaderIdentity:
    """Placeholder for a later trusted-proxy identity adapter."""

    def resolve(self, request: Request) -> Principal:  # pragma: no cover - stub only
        raise IdentityProviderUnavailable(
            "Proxy-header identity is deferred to a later phase."
        )


class OidcIdentity:
    """Placeholder for a later OIDC identity adapter."""

    def resolve(self, request: Request) -> Principal:  # pragma: no cover - stub only
        raise IdentityProviderUnavailable("OIDC identity is deferred to a later phase.")


def get_identity_provider(settings: StudioSettings | None = None) -> IdentityProvider:
    """Return the active P1 provider.

    Proxy/OIDC modes are represented by stubs but intentionally not implemented in P1.
    """

    settings = settings or get_studio_settings()
    if settings.auth_mode == "proxy":
        return ProxyHeaderIdentity()
    if settings.auth_mode == "oidc":
        return OidcIdentity()
    return AnonymousSessionIdentity(settings)


def get_current_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if isinstance(principal, Principal):
        return principal
    principal = get_identity_provider().resolve(request)
    request.state.principal = principal
    return principal
