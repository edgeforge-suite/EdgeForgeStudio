"""Safe projections for Engine diagnostics crossing Studio trust boundaries."""

from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any

DIAGNOSTIC_TEXT_LIMIT = 2000
DIAGNOSTIC_ITEM_LIMIT = 500
DIAGNOSTIC_LOG_LIMIT = 1200

_ANSI_ESCAPE_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_NETWORK_URL_RE = re.compile(
    r"(?:https?|postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis(?:s)?|"
    r"amqp(?:s)?|mssql|sqlserver|snowflake|jdbc:[a-z][a-z0-9+.-]*)"
    r"://[^\s<>'\"]+",
    re.IGNORECASE,
)
_QUOTED_ABSOLUTE_PATH_RE = re.compile(
    r'"(?:[a-z]:[\\/]|/)[^"\r\n]*"|\'(?:[a-z]:[\\/]|/)[^\'\r\n]*\'',
    re.IGNORECASE,
)
_ABSOLUTE_PATH_WITH_EXTENSION_RE = re.compile(
    r"(?i)(?<![\w.:])(?:[a-z]:[\\/]|/)"
    r"(?:[^\r\n\"'<>|,;:(){}\[\]\\/]+[\\/])*"
    r"[^\r\n\"'<>|,;:(){}\[\]\\/]+\."
    r"(?:csv|gradle|jar|java|json|kt|kts|log|md|properties|py|pyi|sql|toml|txt|"
    r"wsdl|xml|xsd|yaml|yml)",
)
_PATH_DETAIL_BOUNDARY_RE = re.compile(
    r"(?ix)"
    r"[ \t]+because[ \t]+(?:field|schema|property|operation|mapping|manifest|"
    r"output|file|directory|path|it|the)\b"
    r"|[ \t]+already[ \t]+(?:exists|present)\b"
    r"|[ \t]+(?:is|was)[ \t]+(?:required|missing|invalid|unsupported|unreadable|"
    r"unavailable|not[ \t]+found)\b"
    r"|[ \t]+(?:does[ \t]+not|cannot|could[ \t]+not|failed[ \t]+to)\b"
    r"|,[ \t]+(?=(?:field|schema|property|operation|mapping|manifest|output|file|"
    r"directory|path)\b)"
    r"|:[ \t]+(?=(?:field|schema|property|operation|mapping|manifest|output|file|"
    r"directory|path|error)\b)"
)
_TRACEBACK_FRAME_RE = re.compile(
    r"^\s*File\s+(?:['\"].*['\"]|<path>),\s+line\s+\d+",
    re.IGNORECASE,
)
_TRACEBACK_SEPARATOR_RE = re.compile(
    r"^(?:During handling of the above exception|The above exception was the direct cause)",
    re.IGNORECASE,
)
_COMMAND_LINE_RE = re.compile(
    r"^(?:command|cmd|argv|executing|running command|subprocess command)\s*[:=]",
    re.IGNORECASE,
)
_AUTHORIZATION_OPTION_RE = re.compile(
    r"(?i)(?P<prefix>--(?:proxy[-_])?authorization(?:=|\s+))"
    r"(?:(?:bearer|basic|digest|negotiate|token)\s+)?"
    r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s\r\n]+)",
)
_SENSITIVE_OPTION_RE = re.compile(
    r"(?i)(--(?:password|passwd|token|secret|api[-_]?key|credential|"
    r"access[-_]?token|client[-_]?secret|private[-_]?key)"
    r"(?:=|\s+))(?:\"[^\"]*\"|'[^']*'|\S+)",
)
_AUTHORIZATION_RE = re.compile(
    r"(?im)(?<![-\w])(?P<prefix>[\"']?[a-z0-9_.-]*(?:proxy[-_])?"
    r"authorization[\"']?\s*[:=]\s*)"
    r"(?:\[[^\]\r\n]*\]|\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\r\n,;}\]]+)",
)
_CONNECTION_SETTING_RE = re.compile(
    r"(?ix)(?P<prefix>[\"']?(?:"
    r"amqp_url|broker_url|connection_(?:string|url)|database_(?:dsn|uri|url)|"
    r"db_url|dsn|jdbc_url|mongodb_uri|redis_url|sqlalchemy_database_uri"
    r")[\"']?\s*[:=]\s*)"
    r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;}\]]+)",
)
_CREDENTIAL_RE = re.compile(
    r"(?i)(?P<key>[\"']?[A-Za-z0-9_.-]*"
    r"(?:password|passwd|token|secret|api[-_]?key|apikey|authorization|credential|cookie|"
    r"access[-_]?token|client[-_]?secret|private[-_]?key)"
    r"[A-Za-z0-9_.-]*[\"']?)\s*[:=]\s*"
    r"(?P<value>\[[^\]\r\n]*\]|\"[^\"]*\"|'[^']*'|[^\s,;}\]]+)",
)
_DIAGNOSTIC_ID_RE = re.compile(r"^diag-[0-9a-f]{32}$")


@dataclass(frozen=True)
class DiagnosticProjection:
    """Bounded UI/persistence-safe view of raw Engine diagnostic material."""

    diagnostic_id: str
    message: str
    warnings: list[str]
    errors: list[str]
    summary: str | None


def new_diagnostic_id() -> str:
    """Return an opaque correlation identifier with no user-derived content."""

    return f"diag-{uuid.uuid4().hex}"


def normalized_diagnostic_id(value: object | None) -> str:
    """Keep a valid existing ID or create one for older/fake result objects."""

    if isinstance(value, str) and _DIAGNOSTIC_ID_RE.fullmatch(value):
        return value
    return new_diagnostic_id()


def diagnostic_id_for(result: object) -> str:
    """Return and, where possible, attach one stable ID to a result object."""

    diagnostic_id = normalized_diagnostic_id(getattr(result, "diagnostic_id", None))
    try:
        result.diagnostic_id = diagnostic_id
    except (AttributeError, TypeError):
        pass
    return diagnostic_id


def _sanitize_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    trailing = ""
    while raw and raw[-1] in ".,;)]}":
        trailing = raw[-1] + trailing
        raw = raw[:-1]
    scheme_separator = raw.find("://")
    if scheme_separator < 1:
        return "<url>" + trailing
    prefix = raw[: scheme_separator + 3]
    remainder = raw[scheme_separator + 3 :]
    authority_end = min(
        (index for marker in "/?#" if (index := remainder.find(marker)) >= 0),
        default=len(remainder),
    )
    authority = remainder[:authority_end]
    if not authority:
        return "<url>" + trailing
    safe_authority = authority.rsplit("@", 1)[-1]
    suffix = remainder[authority_end:]
    query_index = suffix.find("?")
    fragment_index = suffix.find("#")
    detail_indexes = [index for index in (query_index, fragment_index) if index >= 0]
    path_end = min(detail_indexes, default=len(suffix))
    safe_suffix = suffix[:path_end]
    if query_index >= 0:
        safe_suffix += "?redacted"
    if fragment_index >= 0:
        safe_suffix += "#redacted"
    safe = f"{prefix}{safe_authority}{safe_suffix}"
    return safe + trailing


def _absolute_path_prefix_length(value: str, index: int) -> int:
    if index > 0 and (value[index - 1].isalnum() or value[index - 1] in "_."):
        return 0
    if value[index] == "/":
        if index + 1 < len(value) and not value[index + 1].isspace():
            return 1
        return 0
    if (
        index + 2 < len(value)
        and "a" <= value[index].lower() <= "z"
        and value[index + 1] == ":"
        and value[index + 2] in "\\/"
    ):
        return 3
    return 0


def _redact_unquoted_absolute_paths(value: str) -> str:
    """Redact paths while retaining recognizable trailing diagnostic clauses."""

    output: list[str] = []
    cursor = 0
    scan = 0
    while scan < len(value):
        prefix_length = _absolute_path_prefix_length(value, scan)
        if not prefix_length:
            scan += 1
            continue

        line_end = len(value)
        for separator in ("\r", "\n"):
            found = value.find(separator, scan + prefix_length)
            if found >= 0:
                line_end = min(line_end, found)
        last_separator = max(
            value.rfind("/", scan + prefix_length, line_end),
            value.rfind("\\", scan + prefix_length, line_end),
        )
        detail = _PATH_DETAIL_BOUNDARY_RE.search(
            value,
            max(scan + prefix_length, last_separator + 1),
            line_end,
        )
        path_end = detail.start() if detail else line_end

        output.append(value[cursor:scan])
        output.append("<path>")
        cursor = path_end
        scan = path_end

    output.append(value[cursor:])
    return "".join(output)


def _strip_control_characters(value: str) -> str:
    return "".join(
        character
        if character in {"\n", "\t"}
        or not unicodedata.category(character).startswith("C")
        else " "
        for character in value
    )


def _bound(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    suffix = "\n[diagnostic truncated]"
    if limit <= len(suffix):
        return suffix[-limit:]
    return value[: max(0, limit - len(suffix))].rstrip() + suffix


def sanitize_diagnostic_text(
    value: object,
    *,
    max_chars: int = DIAGNOSTIC_TEXT_LIMIT,
) -> str:
    """Remove sensitive process detail while retaining actionable validation text."""

    text = _strip_control_characters(_ANSI_ESCAPE_RE.sub("", str(value or "")))
    url_tokens: dict[str, str] = {}

    def hold_url(match: re.Match[str]) -> str:
        token = f"SAFEURLTOKEN{len(url_tokens)}END"
        url_tokens[token] = _sanitize_url(match)
        return token

    text = _NETWORK_URL_RE.sub(hold_url, text)
    text = _AUTHORIZATION_OPTION_RE.sub(
        lambda match: f"{match.group('prefix')}[redacted]",
        text,
    )
    text = _SENSITIVE_OPTION_RE.sub(r"\1[redacted]", text)
    text = _AUTHORIZATION_RE.sub(lambda match: f"{match.group('prefix')}[redacted]", text)
    text = _CONNECTION_SETTING_RE.sub(
        lambda match: f"{match.group('prefix')}[redacted]",
        text,
    )
    text = _CREDENTIAL_RE.sub(lambda match: f"{match.group('key')}=[redacted]", text)
    text = _QUOTED_ABSOLUTE_PATH_RE.sub("<path>", text)
    text = _ABSOLUTE_PATH_WITH_EXTENSION_RE.sub("<path>", text)
    text = _redact_unquoted_absolute_paths(text)

    kept_lines: list[str] = []
    skip_frame_source = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower().startswith("traceback ("):
            skip_frame_source = False
            continue
        if _TRACEBACK_FRAME_RE.match(line):
            skip_frame_source = True
            continue
        if skip_frame_source and line[:1].isspace():
            skip_frame_source = False
            continue
        skip_frame_source = False
        if _TRACEBACK_SEPARATOR_RE.match(stripped):
            continue
        command_echo = stripped.startswith(("$ ", "+ ")) or (
            any(name in stripped.lower() for name in ("appbuilder", "edgeforge", "python"))
            and any(
                option in stripped
                for option in ("--manifest", "--output", "--package", "--approved-plan-hash")
            )
        )
        if _COMMAND_LINE_RE.match(stripped) or command_echo:
            kept_lines.append("Command details redacted.")
            continue
        kept_lines.append(stripped)

    safe = "\n".join(kept_lines)
    for token, url in url_tokens.items():
        safe = safe.replace(token, url)
    return _bound(safe, max(1, max_chars))


def extract_diagnostic_messages(output: str) -> tuple[list[str], list[str]]:
    """Extract bounded warning/error entries from already-sanitized output."""

    warnings: list[str] = []
    errors: list[str] = []
    in_warning_block = False
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("generation warnings:"):
            in_warning_block = True
            continue
        if in_warning_block:
            if stripped.startswith("- "):
                warnings.append(_bound(stripped[2:].strip(), DIAGNOSTIC_ITEM_LIMIT))
            elif stripped == "" or stripped.startswith("-"):
                continue
            else:
                in_warning_block = False
        if stripped.startswith("WARNING:"):
            warnings.append(_bound(stripped[len("WARNING:") :].strip(), DIAGNOSTIC_ITEM_LIMIT))
        elif stripped.startswith("ERROR:"):
            errors.append(_bound(stripped[len("ERROR:") :].strip(), DIAGNOSTIC_ITEM_LIMIT))
    return warnings, errors


def actionable_diagnostic_summary(
    output: str,
    errors: list[str] | None = None,
) -> str | None:
    """Return the highest-signal bounded summary from sanitized output."""

    if errors:
        return _bound(errors[0].strip(), DIAGNOSTIC_ITEM_LIMIT) if errors[0].strip() else None
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return None
    exception_re = re.compile(r"^[A-Za-z_][\w.]*?(?:Error|Exception|Warning):\s+.+$")
    for line in reversed(lines):
        if exception_re.match(line):
            return _bound(line, DIAGNOSTIC_ITEM_LIMIT)
    signal_markers = (
        " is not present ",
        " does not match ",
        " field required",
        " missing",
        " invalid",
        " not found",
        " unable to ",
        " failed",
        " unsupported",
    )
    for line in lines:
        if any(marker in line.lower() for marker in signal_markers):
            return _bound(line, DIAGNOSTIC_ITEM_LIMIT)
    return _bound(lines[0], DIAGNOSTIC_ITEM_LIMIT)


def project_engine_diagnostic(
    raw_output: object,
    *,
    success: bool,
    diagnostic_id: str | None = None,
) -> DiagnosticProjection:
    """Build a complete safe response/persistence projection from raw material."""

    resolved_id = normalized_diagnostic_id(diagnostic_id)
    safe_output = sanitize_diagnostic_text(raw_output)
    warnings, errors = extract_diagnostic_messages(safe_output)
    summary = None if success else actionable_diagnostic_summary(safe_output, errors)
    if success:
        message = safe_output or "Engine operation completed."
    else:
        summary = summary or "Engine operation failed."
        if not errors:
            errors = [summary]
        detail = safe_output or summary
        message = f"{detail}\nDiagnostic ID: {resolved_id}"
    return DiagnosticProjection(
        diagnostic_id=resolved_id,
        message=message,
        warnings=warnings,
        errors=errors,
        summary=summary,
    )


def project_engine_result(result: Any) -> DiagnosticProjection:
    """Project a result without changing any of its raw diagnostic fields."""

    return project_engine_diagnostic(
        getattr(result, "combined_output", ""),
        success=bool(getattr(result, "success", False)),
        diagnostic_id=diagnostic_id_for(result),
    )


def log_engine_diagnostic(
    target_logger: logging.Logger,
    level: int,
    *,
    label: str,
    diagnostic_id: str,
    detail: object,
) -> None:
    """Write one bounded, sanitized, correlation-friendly default log entry."""

    safe_detail = sanitize_diagnostic_text(detail, max_chars=DIAGNOSTIC_LOG_LIMIT)
    target_logger.log(
        level,
        "[%s] diagnostic_id=%s %s",
        label,
        normalized_diagnostic_id(diagnostic_id),
        safe_detail or "Engine operation produced no diagnostic detail.",
    )
