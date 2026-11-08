"""Browser-response containment headers for every Studio HTTP surface."""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

BROWSER_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "frame-ancestors 'none'",
}


async def browser_safe_internal_server_error(
    _request: Request,
    _exc: Exception,
) -> PlainTextResponse:
    """Keep Starlette's outer emergency response contained and non-diagnostic."""

    return PlainTextResponse(
        "Internal Server Error",
        status_code=500,
        headers=BROWSER_SECURITY_HEADERS,
    )


class BrowserSecurityHeadersMiddleware:
    """Attach the scoped baseline headers without constraining inline assets."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in BROWSER_SECURITY_HEADERS.items():
                    headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)
