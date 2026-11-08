"""Studio's active EdgeForge manifest producer contract."""

from __future__ import annotations

import re

STUDIO_MANIFEST_SCHEMA_VERSION = "2.0"

_VERSION_MISMATCH_PATTERNS = (
    re.compile(
        r"\b(?:unknown|unsupported)\s+(?:manifest\s+)?schema_version\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bschema_version\b[^\n]*\bis not one of\b", re.IGNORECASE),
)

_REJECTED_VERSION_PATTERNS = (
    re.compile(
        r"\b(?:unknown|unsupported)\s+(?:manifest\s+)?schema_version\s*"
        r"(?:[:=]\s*)?['\"](?P<version>[^'\"]+)['\"]",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bschema_version\b[^\n'\"]*['\"](?P<version>[^'\"]+)['\"]"
        r"\s+is not one of\b",
        re.IGNORECASE,
    ),
)


def _rejected_manifest_version(child_output: str) -> str | None:
    for pattern in _REJECTED_VERSION_PATTERNS:
        match = pattern.search(child_output)
        if match:
            return match.group("version")
    return None


def manifest_version_mismatch_diagnostic(child_output: str) -> str | None:
    """Return a concise operator diagnostic for unmistakable version failures."""
    if not child_output or not any(
        pattern.search(child_output) for pattern in _VERSION_MISMATCH_PATTERNS
    ):
        return None
    rejected_version = _rejected_manifest_version(child_output)
    if rejected_version == STUDIO_MANIFEST_SCHEMA_VERSION:
        return (
            f"This package uses manifest schema_version '{STUDIO_MANIFEST_SCHEMA_VERSION}', but "
            "the configured EdgeForge Engine does not support it. Use the paired EdgeForge Engine "
            f"release that supports manifest {STUDIO_MANIFEST_SCHEMA_VERSION}, then retry."
        )
    if rejected_version:
        return (
            f"This package uses manifest schema_version '{rejected_version}', while this Studio "
            f"exports manifest {STUDIO_MANIFEST_SCHEMA_VERSION}. Reopen its saved Studio project "
            "and export it again, then use the paired EdgeForge Engine release that supports "
            f"manifest {STUDIO_MANIFEST_SCHEMA_VERSION}."
        )
    return (
        "The package and configured EdgeForge Engine use incompatible manifest schema versions. "
        f"This Studio exports manifest {STUDIO_MANIFEST_SCHEMA_VERSION}. Reopen the saved Studio "
        "project and export it again, and use the paired EdgeForge Engine release that supports "
        f"manifest {STUDIO_MANIFEST_SCHEMA_VERSION}."
    )
