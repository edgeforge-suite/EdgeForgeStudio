"""Small HMAC-signed token helpers for local Studio cookies."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any


class SignedTokenError(ValueError):
    """Raised when a signed token cannot be verified."""


def _b64_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def sign_payload(payload: dict[str, Any], *, secret: str) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    encoded = _b64_encode(raw)
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256)
    return f"{encoded}.{_b64_encode(signature.digest())}"


def verify_payload(token: str, *, secret: str) -> dict[str, Any]:
    try:
        encoded, supplied_signature = token.split(".", 1)
    except ValueError as exc:
        raise SignedTokenError("Malformed signed token.") from exc
    expected = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256)
    expected_signature = _b64_encode(expected.digest())
    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise SignedTokenError("Invalid signed token signature.")
    try:
        payload = json.loads(_b64_decode(encoded).decode("utf-8"))
    except Exception as exc:
        raise SignedTokenError("Invalid signed token payload.") from exc
    if not isinstance(payload, dict):
        raise SignedTokenError("Signed token payload must be an object.")
    return payload
