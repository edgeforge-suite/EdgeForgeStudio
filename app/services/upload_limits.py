"""Shared bounded upload readers for Studio upload endpoints."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import UploadFile

DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_UPLOAD_BYTES_ENV = "EDGEFORGE_STUDIO_MAX_UPLOAD_BYTES"
MULTIPART_OVERHEAD_BYTES = 1 * 1024 * 1024

OPENAPI_UPLOAD_POLICY = "openapi"
PROJECT_UPLOAD_POLICY = "project"
KNOWLEDGE_UPLOAD_POLICY = "knowledge"

_UPLOAD_FILE_POLICIES: dict[str, dict[str, frozenset[str]]] = {
    OPENAPI_UPLOAD_POLICY: {
        ".json": frozenset({
            "application/json",
            "text/json",
            "text/plain",
            "application/octet-stream",
        }),
        ".yaml": frozenset({
            "application/yaml",
            "application/x-yaml",
            "text/yaml",
            "text/x-yaml",
            "text/plain",
            "application/octet-stream",
        }),
        ".yml": frozenset({
            "application/yaml",
            "application/x-yaml",
            "text/yaml",
            "text/x-yaml",
            "text/plain",
            "application/octet-stream",
        }),
    },
    PROJECT_UPLOAD_POLICY: {
        ".json": frozenset({
            "application/json",
            "text/json",
            "text/plain",
            "application/octet-stream",
        }),
    },
    KNOWLEDGE_UPLOAD_POLICY: {
        ".md": frozenset({"text/markdown", "text/plain", "application/octet-stream"}),
        ".markdown": frozenset({"text/markdown", "text/plain", "application/octet-stream"}),
        ".csv": frozenset({
            "text/csv",
            "application/csv",
            "application/vnd.ms-excel",
            "text/plain",
            "application/octet-stream",
        }),
        ".sql": frozenset({
            "application/sql",
            "application/x-sql",
            "text/sql",
            "text/plain",
            "application/octet-stream",
        }),
        ".xlsx": frozenset({
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/octet-stream",
        }),
        ".pdf": frozenset({"application/pdf", "application/octet-stream"}),
        ".docx": frozenset({
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/octet-stream",
        }),
    },
}


class UploadTooLargeError(ValueError):
    """Raised when an uploaded file exceeds Studio's configured upload cap."""


class UploadFilePolicyError(ValueError):
    """Raised when an uploaded file's extension or declared type is not permitted."""


def max_upload_bytes() -> int:
    raw = os.getenv(MAX_UPLOAD_BYTES_ENV)
    if raw is None:
        return DEFAULT_MAX_UPLOAD_BYTES
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_UPLOAD_BYTES
    return parsed if parsed > 0 else DEFAULT_MAX_UPLOAD_BYTES


def multipart_request_limit_bytes(file_limit: int | None = None) -> int:
    """Return the complete multipart-envelope cap for a configured file limit."""
    return (max_upload_bytes() if file_limit is None else file_limit) + MULTIPART_OVERHEAD_BYTES


def human_readable_upload_limit(limit: int | None = None) -> str:
    value = max_upload_bytes() if limit is None else limit
    if value % (1024 * 1024) == 0:
        return f"{value // (1024 * 1024)} MiB"
    if value % 1024 == 0:
        return f"{value // 1024} KiB"
    return f"{value} bytes"


def upload_too_large_message(limit: int | None = None) -> str:
    return f"Uploaded file exceeds the {human_readable_upload_limit(limit)} limit."


def upload_request_too_large_message(limit: int | None = None) -> str:
    value = multipart_request_limit_bytes() if limit is None else limit
    return f"Upload request exceeds the {human_readable_upload_limit(value)} limit."


def validate_upload_file(upload: UploadFile, *, policy: str) -> None:
    """Enforce the route-owned extension and client-declared MIME allowlist."""
    policy_map = _UPLOAD_FILE_POLICIES.get(policy)
    if policy_map is None:
        raise ValueError(f"Unknown upload policy: {policy}")

    extension = Path(upload.filename or "").suffix.lower()
    accepted_types = policy_map.get(extension)
    content_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
    if accepted_types is None or content_type not in accepted_types:
        raise UploadFilePolicyError("Uploaded file type is not supported.")


async def read_upload_limited(upload: UploadFile, *, limit: int | None = None) -> bytes:
    """Read an UploadFile in chunks and reject once the configured cap is exceeded."""
    max_bytes = max_upload_bytes() if limit is None else limit
    if max_bytes <= 0:
        max_bytes = DEFAULT_MAX_UPLOAD_BYTES

    size = getattr(upload, "size", None)
    if isinstance(size, int) and size > max_bytes:
        raise UploadTooLargeError(upload_too_large_message(max_bytes))

    chunks: list[bytes] = []
    total = 0
    while True:
        read_size = min(1024 * 1024, max_bytes - total + 1)
        chunk = await upload.read(read_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise UploadTooLargeError(upload_too_large_message(max_bytes))
        chunks.append(chunk)
    return b"".join(chunks)
