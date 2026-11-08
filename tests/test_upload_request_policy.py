"""Adversarial coverage for Studio's pre-multipart upload boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from io import BytesIO

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient
from starlette.datastructures import Headers
from starlette.types import Message, Receive, Scope, Send

from app.main import app
from app.middleware.browser_security import (
    BROWSER_SECURITY_HEADERS,
    BrowserSecurityHeadersMiddleware,
)
from app.middleware.upload_request_policy import UploadRequestPolicyMiddleware
from app.services.upload_limits import (
    DEFAULT_MAX_UPLOAD_BYTES,
    KNOWLEDGE_UPLOAD_POLICY,
    MULTIPART_OVERHEAD_BYTES,
    OPENAPI_UPLOAD_POLICY,
    PROJECT_UPLOAD_POLICY,
    UploadFilePolicyError,
    multipart_request_limit_bytes,
    validate_upload_file,
)
from tests.session_helpers import get_session, save_session

_CLIENT = TestClient(app)
_ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def _scope(path: str, headers: list[tuple[bytes, bytes]]) -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }


def _run_asgi(
    app_to_call: _ASGIApp,
    scope: Scope,
    messages: list[Message],
) -> tuple[list[Message], int]:
    sent: list[Message] = []
    receive_calls = 0

    async def receive() -> Message:
        nonlocal receive_calls
        receive_calls += 1
        if messages:
            return messages.pop(0)
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        sent.append(message)

    asyncio.run(app_to_call(scope, receive, send))
    return sent, receive_calls


def _status(sent: list[Message]) -> int:
    return next(message["status"] for message in sent if message["type"] == "http.response.start")


def _headers(sent: list[Message]) -> Headers:
    start = next(message for message in sent if message["type"] == "http.response.start")
    return Headers(raw=start["headers"])


def _bounded_app(received: list[Message]) -> _ASGIApp:
    async def app_to_call(_scope: Scope, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            received.append(message)
            if message["type"] != "http.request" or not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    return app_to_call


def test_oversized_content_length_rejects_without_receive_or_inner_app(monkeypatch):
    monkeypatch.setattr(
        "app.middleware.upload_request_policy.multipart_request_limit_bytes",
        lambda: 10,
    )
    inner_calls: list[Message] = []
    protected = BrowserSecurityHeadersMiddleware(
        UploadRequestPolicyMiddleware(_bounded_app(inner_calls))
    )

    sent, receive_calls = _run_asgi(
        protected,
        _scope(
            "/upstream/ingest-file",
            [
                (b"content-type", b"multipart/form-data; boundary=unit"),
                (b"content-length", b"11"),
            ],
        ),
        [{"type": "http.request", "body": b"ignored", "more_body": False}],
    )

    assert _status(sent) == 413
    assert receive_calls == 0
    assert inner_calls == []
    for name, value in BROWSER_SECURITY_HEADERS.items():
        assert _headers(sent)[name] == value


@pytest.mark.parametrize("value", [b"not-a-number", b"-1", b"+1", b""])
def test_invalid_content_length_rejects_before_receive(value, monkeypatch):
    monkeypatch.setattr(
        "app.middleware.upload_request_policy.multipart_request_limit_bytes",
        lambda: 10,
    )
    inner_calls: list[Message] = []
    protected = UploadRequestPolicyMiddleware(_bounded_app(inner_calls))

    sent, receive_calls = _run_asgi(
        protected,
        _scope(
            "/upstream/ingest-file",
            [
                (b"content-type", b"multipart/form-data; boundary=unit"),
                (b"content-length", value),
            ],
        ),
        [{"type": "http.request", "body": b"ignored", "more_body": False}],
    )

    assert _status(sent) == 400
    assert receive_calls == 0
    assert inner_calls == []


def test_duplicate_content_length_rejects_before_receive(monkeypatch):
    monkeypatch.setattr(
        "app.middleware.upload_request_policy.multipart_request_limit_bytes",
        lambda: 10,
    )
    inner_calls: list[Message] = []
    protected = UploadRequestPolicyMiddleware(_bounded_app(inner_calls))

    sent, receive_calls = _run_asgi(
        protected,
        _scope(
            "/upstream/ingest-file",
            [
                (b"content-type", b"multipart/form-data; boundary=unit"),
                (b"content-length", b"1"),
                (b"content-length", b"1"),
            ],
        ),
        [{"type": "http.request", "body": b"ignored", "more_body": False}],
    )

    assert _status(sent) == 400
    assert receive_calls == 0
    assert inner_calls == []


@pytest.mark.parametrize(
    "content_type",
    [b"", b"application/json", b"multipart/form-data", b"multipart/form-data; boundary="],
)
def test_invalid_multipart_envelope_rejects_before_receive(content_type):
    inner_calls: list[Message] = []
    protected = UploadRequestPolicyMiddleware(_bounded_app(inner_calls))

    sent, receive_calls = _run_asgi(
        protected,
        _scope("/project/open", [(b"content-type", content_type)]),
        [{"type": "http.request", "body": b"ignored", "more_body": False}],
    )

    assert _status(sent) == 415
    assert receive_calls == 0
    assert inner_calls == []
    body = next(message["body"] for message in sent if message["type"] == "http.response.body")
    assert b"Upload not accepted" in body
    assert b"Return to Project Setup" in body


def test_chunked_overage_stops_inner_app_and_allows_cleanup(monkeypatch):
    monkeypatch.setattr(
        "app.middleware.upload_request_policy.multipart_request_limit_bytes",
        lambda: 4,
    )
    cleanup = {"ran": False}
    forwarded: list[Message] = []

    async def app_to_call(_scope: Scope, receive: Receive, _send: Send) -> None:
        try:
            while True:
                message = await receive()
                forwarded.append(message)
                if not message.get("more_body", False):
                    break
        finally:
            cleanup["ran"] = True

    sent, receive_calls = _run_asgi(
        UploadRequestPolicyMiddleware(app_to_call),
        _scope(
            "/knowledge/upload",
            [(b"content-type", b"multipart/form-data; boundary=unit")],
        ),
        [
            {"type": "http.request", "body": b"abc", "more_body": True},
            {"type": "http.request", "body": b"de", "more_body": False},
        ],
    )

    assert _status(sent) == 413
    assert receive_calls == 2
    assert [message["body"] for message in forwarded] == [b"abc"]
    assert cleanup["ran"] is True


def test_live_app_rejects_chunked_overage_with_browser_headers(monkeypatch):
    first_chunk = (
        b'--unit\r\nContent-Disposition: form-data; name="spec_file"; '
        b'filename="spec.yaml"\r\nContent-Type: application/yaml\r\n\r\nopenapi: 3.0.0\n'
    )
    monkeypatch.setattr(
        "app.middleware.upload_request_policy.multipart_request_limit_bytes",
        lambda: len(first_chunk) + 1,
    )

    sent, receive_calls = _run_asgi(
        app,
        _scope(
            "/upstream/ingest-file",
            [(b"content-type", b"multipart/form-data; boundary=unit")],
        ),
        [
            {"type": "http.request", "body": first_chunk, "more_body": True},
            {"type": "http.request", "body": b"xx", "more_body": False},
        ],
    )

    assert _status(sent) == 413
    assert receive_calls == 2
    for name, value in BROWSER_SECURITY_HEADERS.items():
        assert _headers(sent)[name] == value


def test_default_envelope_allows_50_mib_file_plus_small_overhead():
    assert multipart_request_limit_bytes() == DEFAULT_MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES
    inner_calls: list[Message] = []
    protected = UploadRequestPolicyMiddleware(_bounded_app(inner_calls))
    content_length = DEFAULT_MAX_UPLOAD_BYTES + 1024

    sent, receive_calls = _run_asgi(
        protected,
        _scope(
            "/upstream/ingest-file",
            [
                (b"content-type", b"multipart/form-data; boundary=unit"),
                (b"content-length", str(content_length).encode("ascii")),
            ],
        ),
        [{"type": "http.request", "body": b"", "more_body": False}],
    )

    assert _status(sent) == 204
    assert receive_calls == 1
    assert len(inner_calls) == 1


def test_unprotected_routes_pass_through_unchanged():
    received: list[Message] = []
    protected = UploadRequestPolicyMiddleware(_bounded_app(received))

    sent, receive_calls = _run_asgi(
        protected,
        _scope("/export/validate", [(b"content-type", b"application/json")]),
        [{"type": "http.request", "body": b"{}", "more_body": False}],
    )

    assert _status(sent) == 204
    assert receive_calls == 1
    assert received[0]["body"] == b"{}"


@pytest.mark.parametrize(
    ("policy", "filename", "content_type"),
    [
        (OPENAPI_UPLOAD_POLICY, "spec.json", "application/json"),
        (OPENAPI_UPLOAD_POLICY, "spec.json", "text/json"),
        (OPENAPI_UPLOAD_POLICY, "spec.json", "text/plain"),
        (OPENAPI_UPLOAD_POLICY, "spec.yaml", "application/yaml"),
        (OPENAPI_UPLOAD_POLICY, "spec.yaml", "application/x-yaml"),
        (OPENAPI_UPLOAD_POLICY, "spec.yaml", "text/yaml"),
        (OPENAPI_UPLOAD_POLICY, "spec.yaml", "text/x-yaml"),
        (OPENAPI_UPLOAD_POLICY, "spec.yml", "text/plain"),
        (OPENAPI_UPLOAD_POLICY, "spec.yml", "application/yaml"),
        (OPENAPI_UPLOAD_POLICY, "spec.yml", "application/x-yaml"),
        (OPENAPI_UPLOAD_POLICY, "spec.yml", "text/yaml"),
        (OPENAPI_UPLOAD_POLICY, "spec.yml", "text/x-yaml"),
        (PROJECT_UPLOAD_POLICY, "studio.json", "application/json"),
        (PROJECT_UPLOAD_POLICY, "studio.json", "text/json"),
        (PROJECT_UPLOAD_POLICY, "studio.json", "text/plain"),
        (KNOWLEDGE_UPLOAD_POLICY, "notes.md", "text/markdown"),
        (KNOWLEDGE_UPLOAD_POLICY, "notes.md", "text/plain"),
        (KNOWLEDGE_UPLOAD_POLICY, "notes.markdown", "text/markdown"),
        (KNOWLEDGE_UPLOAD_POLICY, "notes.markdown", "text/plain"),
        (KNOWLEDGE_UPLOAD_POLICY, "data.csv", "text/csv"),
        (KNOWLEDGE_UPLOAD_POLICY, "data.csv", "application/csv"),
        (KNOWLEDGE_UPLOAD_POLICY, "data.csv", "application/vnd.ms-excel"),
        (KNOWLEDGE_UPLOAD_POLICY, "data.csv", "text/plain"),
        (KNOWLEDGE_UPLOAD_POLICY, "schema.sql", "application/sql"),
        (KNOWLEDGE_UPLOAD_POLICY, "schema.sql", "application/x-sql"),
        (KNOWLEDGE_UPLOAD_POLICY, "schema.sql", "text/sql"),
        (KNOWLEDGE_UPLOAD_POLICY, "schema.sql", "text/plain"),
        (
            KNOWLEDGE_UPLOAD_POLICY,
            "worksheet.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        (KNOWLEDGE_UPLOAD_POLICY, "report.pdf", "application/pdf"),
        (
            KNOWLEDGE_UPLOAD_POLICY,
            "brief.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    ],
)
def test_each_permitted_extension_and_content_type_is_accepted(policy, filename, content_type):
    upload = UploadFile(
        file=BytesIO(b"content"),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )
    validate_upload_file(upload, policy=policy)


@pytest.mark.parametrize(
    ("policy", "filename"),
    [
        (OPENAPI_UPLOAD_POLICY, "spec.yaml"),
        (OPENAPI_UPLOAD_POLICY, "spec.yml"),
        (OPENAPI_UPLOAD_POLICY, "spec.json"),
        (PROJECT_UPLOAD_POLICY, "studio.json"),
        (KNOWLEDGE_UPLOAD_POLICY, "notes.md"),
        (KNOWLEDGE_UPLOAD_POLICY, "notes.markdown"),
        (KNOWLEDGE_UPLOAD_POLICY, "data.csv"),
        (KNOWLEDGE_UPLOAD_POLICY, "schema.sql"),
        (KNOWLEDGE_UPLOAD_POLICY, "worksheet.xlsx"),
        (KNOWLEDGE_UPLOAD_POLICY, "report.pdf"),
        (KNOWLEDGE_UPLOAD_POLICY, "brief.docx"),
    ],
)
def test_octet_stream_is_accepted_for_every_route_policy(policy, filename):
    upload = UploadFile(
        file=BytesIO(b"content"),
        filename=filename,
        headers=Headers({"content-type": "application/octet-stream"}),
    )
    validate_upload_file(upload, policy=policy)


@pytest.mark.parametrize(
    ("policy", "filename", "content_type"),
    [
        (OPENAPI_UPLOAD_POLICY, "spec.txt", "text/plain"),
        (PROJECT_UPLOAD_POLICY, "studio.yaml", "application/yaml"),
        (KNOWLEDGE_UPLOAD_POLICY, "notes.md", "application/pdf"),
    ],
)
def test_unsupported_extensions_and_mismatched_types_are_rejected(policy, filename, content_type):
    upload = UploadFile(
        file=BytesIO(b"content"),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )
    with pytest.raises(UploadFilePolicyError, match="Uploaded file type is not supported"):
        validate_upload_file(upload, policy=policy)


def test_upstream_file_policy_rejects_before_openapi_parsing(monkeypatch):
    def unexpected_parse(_content: str):
        raise AssertionError("OpenAPI parsing should not run for a rejected file type")

    monkeypatch.setattr("app.routes.upstream.parse_openapi_text", unexpected_parse)
    response = _CLIENT.post(
        "/upstream/ingest-file",
        files={"spec_file": ("spec.txt", b"not-openapi", "text/plain")},
    )

    assert response.status_code == 415
    assert response.json() == {"ok": False, "error": "Uploaded file type is not supported."}


def test_project_file_policy_rejects_before_project_deserialization(monkeypatch):
    def unexpected_deserialize(_text: str):
        raise AssertionError("Project deserialization should not run for a rejected file type")

    monkeypatch.setattr("app.routes.project_file.deserialize_project", unexpected_deserialize)
    response = _CLIENT.post(
        "/project/open",
        files={"project_file": ("project.yaml", b"not-json", "application/yaml")},
    )

    assert response.status_code == 415
    assert "Upload not accepted" in response.text


def test_knowledge_file_policy_rejects_before_workspace_or_ks_calls(monkeypatch):
    def unexpected_workspace(*_args, **_kwargs):
        raise AssertionError("Workspace storage should not run for a rejected file type")

    def unexpected_ks(*_args, **_kwargs):
        raise AssertionError("KS should not run for a rejected file type")

    monkeypatch.setattr("app.routes.knowledge.workspace_dir", unexpected_workspace)
    monkeypatch.setattr("app.routes.knowledge.ks_client", unexpected_ks)
    session = get_session()
    was_enabled = session.capabilities.knowledge_assist_enabled
    session.capabilities.knowledge_assist_enabled = True
    save_session(session)
    try:
        response = _CLIENT.post(
            "/knowledge/upload",
            files={"document_file": ("notes.md", b"not-markdown", "application/pdf")},
        )
    finally:
        session.capabilities.knowledge_assist_enabled = was_enabled
        save_session(session)

    assert response.status_code == 415
    assert "Upload not accepted" in response.text


@pytest.mark.parametrize(
    ("path", "expected_content_type"),
    [
        ("/upstream/ingest-file", "application/json"),
        ("/project/open", "text/html"),
        ("/knowledge/upload", "text/html"),
    ],
)
def test_early_rejections_keep_browser_headers(path, expected_content_type):
    response = _CLIENT.post(
        path,
        content=b"not-a-multipart-upload",
        headers={"content-type": "text/plain"},
    )

    assert response.status_code == 415
    assert response.headers["content-type"].startswith(expected_content_type)
    for name, value in BROWSER_SECURITY_HEADERS.items():
        assert response.headers[name] == value
    if path == "/upstream/ingest-file":
        assert response.json() == {
            "ok": False,
            "error": "Upload request must use multipart/form-data.",
        }
    else:
        assert "Upload not accepted" in response.text
