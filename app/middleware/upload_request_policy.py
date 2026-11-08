"""Early multipart request bounds for the three Studio upload endpoints."""

from __future__ import annotations

import json

from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.paths import TEMPLATE_DIR
from app.services.upload_limits import (
    multipart_request_limit_bytes,
    upload_request_too_large_message,
)

_PROTECTED_UPLOAD_PATHS = {
    "/upstream/ingest-file": {"format": "json"},
    "/project/open": {"format": "html", "back_href": "/", "back_label": "Project Setup"},
    "/knowledge/upload": {"format": "html", "back_href": "/knowledge", "back_label": "Knowledge Workspace"},
}
_TEMPLATES = Jinja2Templates(directory=TEMPLATE_DIR)


class _RequestLimitExceeded(Exception):
    """Private signal used only to stop a chunked request before route handling."""


def _is_valid_multipart(content_type: str | None) -> bool:
    if not content_type:
        return False
    parts = [part.strip() for part in content_type.split(";")]
    if not parts or parts[0].lower() != "multipart/form-data":
        return False
    for part in parts[1:]:
        name, separator, value = part.partition("=")
        if separator and name.strip().lower() == "boundary" and value.strip().strip('"'):
            return True
    return False


def _parse_content_length(value: str | None) -> int | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw or not raw.isascii() or not raw.isdecimal():
        raise ValueError
    return int(raw)


def upload_rejected_response(
    *,
    path: str,
    status_code: int,
    message: str,
) -> HTMLResponse:
    """Build a session-free HTML rejection page for form upload routes."""
    endpoint = _PROTECTED_UPLOAD_PATHS[path]
    content = _TEMPLATES.get_template("errors/upload_rejected.html").render(
        status_code=status_code,
        message=message,
        back_href=endpoint["back_href"],
        back_label=endpoint["back_label"],
    )
    return HTMLResponse(content, status_code=status_code)


async def _send_rejection(
    *,
    path: str,
    status_code: int,
    message: str,
    send: Send,
) -> None:
    endpoint = _PROTECTED_UPLOAD_PATHS[path]
    if endpoint["format"] == "json":
        body = json.dumps({"ok": False, "error": message}, separators=(",", ":")).encode("utf-8")
        content_type = b"application/json; charset=utf-8"
    else:
        body = upload_rejected_response(
            path=path,
            status_code=status_code,
            message=message,
        ).body
        content_type = b"text/html; charset=utf-8"

    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", content_type),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class UploadRequestPolicyMiddleware:
    """Bound protected multipart envelopes before request context or route parsing."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"].upper() != "POST":
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        if path not in _PROTECTED_UPLOAD_PATHS:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        if not _is_valid_multipart(headers.get("content-type")):
            await _send_rejection(
                path=path,
                status_code=415,
                message="Upload request must use multipart/form-data.",
                send=send,
            )
            return

        request_limit = multipart_request_limit_bytes()
        content_lengths = headers.getlist("content-length")
        try:
            content_length = (
                _parse_content_length(content_lengths[0])
                if len(content_lengths) == 1
                else None
            )
            if len(content_lengths) > 1:
                raise ValueError
        except ValueError:
            await _send_rejection(
                path=path,
                status_code=400,
                message="Upload request has an invalid Content-Length header.",
                send=send,
            )
            return

        if content_length is not None and content_length > request_limit:
            await _send_rejection(
                path=path,
                status_code=413,
                message=upload_request_too_large_message(request_limit),
                send=send,
            )
            return

        received = 0
        limit_exceeded = False
        buffered_response: list[Message] = []

        async def limited_receive() -> Message:
            nonlocal limit_exceeded, received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > request_limit:
                    limit_exceeded = True
                    raise _RequestLimitExceeded
            return message

        async def buffered_send(message: Message) -> None:
            buffered_response.append(message)

        try:
            await self.app(scope, limited_receive, buffered_send)
        except _RequestLimitExceeded:
            limit_exceeded = True

        if limit_exceeded:
            await _send_rejection(
                path=path,
                status_code=413,
                message=upload_request_too_large_message(request_limit),
                send=send,
            )
            return

        for message in buffered_response:
            await send(message)
