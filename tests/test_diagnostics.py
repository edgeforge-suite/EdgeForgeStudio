from __future__ import annotations

import logging
import time
from types import SimpleNamespace

from app.services.diagnostics import (
    DIAGNOSTIC_LOG_LIMIT,
    log_engine_diagnostic,
    new_diagnostic_id,
    project_engine_result,
    sanitize_diagnostic_text,
)

HOSTILE_DIAGNOSTIC = (
    "Traceback (most recent call last):\n"
    '  File "/Users/example/private/engine.py", line 42, in <module>\n'
    "    subprocess.run(command)\n"
    "Command: /opt/private/python -m appbuilder.cli generate "
    "--manifest /Users/example/private/app-definition.yaml --token swordfish\n"
    "EDGEFORGE_SESSION_SECRET=local-secret-value\n"
    'PASSWORD: "hunter2"\n'
    "Authorization: Bearer super-secret-token\n"
    "--authorization Bearer option-secret-token\n"
    "--authorization=Basic dXNlcjpwYXNz\n"
    "HTTP_AUTHORIZATION=Bearer env-secret-token\n"
    "REDIRECT_HTTP_AUTHORIZATION=Bearer redirect-secret-token\n"
    "X_AUTHORIZATION=Basic eDpzZWNyZXQ=\n"
    "DATABASE_URL=postgresql://alice:db-password@db.internal/prod\n"
    "JDBC_URL=jdbc:postgresql://bob:jdbc-password@db.internal/prod\n"
    "Windows source C:\\Users\\Example\\private\\manifest.yaml\n"
    "Unquoted source /Users/alice/My Private Project/app-definition.yaml\n"
    "Extensionless POSIX /Users/alice/Hidden Workspace/generated-app\n"
    "Extensionless Windows C:\\Users\\Alice\\Sensitive Workspace\\generated-app\n"
    'Quoted source "/Users/Example/My Private Project/manifest.yaml"\n'
    "Quoted Windows source 'C:\\Users\\Example\\My Private Project\\manifest.yaml'\n"
    "$ python -m appbuilder.cli generate --manifest ./manifest.yaml --output ./generated\n"
    "Fetch https://alice:password@example.test/openapi.yaml?token=query-secret&mode=full\n"
    "ERROR: Field 'customerId' is required\x00\x1b[31m\u202e\n"
)


def test_sanitizer_removes_sensitive_process_detail_and_preserves_actionable_error():
    sanitized = sanitize_diagnostic_text(HOSTILE_DIAGNOSTIC)

    for sentinel in (
        "Traceback",
        "/Users/example",
        "/opt/private",
        "C:\\Users\\Example",
        "swordfish",
        "local-secret-value",
        "hunter2",
        "super-secret-token",
        "option-secret-token",
        "dXNlcjpwYXNz",
        "env-secret-token",
        "redirect-secret-token",
        "eDpzZWNyZXQ=",
        "db-password",
        "jdbc-password",
        "alice:password",
        "query-secret",
        "Hidden Workspace",
        "Sensitive Workspace",
        "appbuilder.cli",
        "--manifest",
        "\x00",
        "\x1b",
        "\u202e",
    ):
        assert sentinel not in sanitized
    assert "https://example.test/openapi.yaml?redacted" in sanitized
    assert "Authorization=[redacted]" in sanitized
    assert "--authorization [redacted]" in sanitized
    assert "--authorization=[redacted]" in sanitized
    assert "HTTP_AUTHORIZATION=[redacted]" in sanitized
    assert "REDIRECT_HTTP_AUTHORIZATION=[redacted]" in sanitized
    assert "X_AUTHORIZATION=[redacted]" in sanitized
    assert "[redacted]]" not in sanitized
    assert "DATABASE_URL=[redacted]" in sanitized
    assert "JDBC_URL=[redacted]" in sanitized
    assert "Private Project" not in sanitized
    assert "Field 'customerId' is required" in sanitized
    assert "<path>" in sanitized


def test_standalone_connection_uris_drop_userinfo_and_query_secrets():
    sanitized = sanitize_diagnostic_text(
        "Postgres postgresql://alice:db-password@db.internal/prod?sslkey=secret\n"
        "JDBC jdbc:postgresql://bob:jdbc-password@db.internal/prod?token=secret"
    )

    assert "postgresql://db.internal/prod?redacted" in sanitized
    assert "jdbc:postgresql://db.internal/prod?redacted" in sanitized
    for secret in ("alice", "db-password", "bob", "jdbc-password", "sslkey", "token"):
        assert secret not in sanitized


def test_sanitizer_strictly_bounds_output():
    assert len(sanitize_diagnostic_text("x" * 500, max_chars=80)) <= 80
    assert len(sanitize_diagnostic_text("x" * 500, max_chars=8)) <= 8


def test_extensionless_absolute_path_is_sanitized_without_backtracking():
    raw = "/" + ("segment/" * 24) + "tail_without_extension"

    started = time.perf_counter()
    sanitized = sanitize_diagnostic_text(raw)
    elapsed = time.perf_counter() - started

    assert sanitized == "<path>"
    assert elapsed < 0.5


def test_prefixed_authorization_and_spaced_extensionless_paths_are_fully_redacted():
    sanitized = sanitize_diagnostic_text(
        "HTTP_AUTHORIZATION=Bearer env-secret-token\n"
        "REDIRECT_HTTP_AUTHORIZATION=Bearer redirect-secret-token\n"
        "X_AUTHORIZATION=Basic eDpzZWNyZXQ=\n"
        "Manifest /Users/alice/My Private Project/generated-app\n"
        "Manifest C:\\Users\\Alice\\My Private Project\\generated-app"
    )

    assert sanitized.splitlines() == [
        "HTTP_AUTHORIZATION=[redacted]",
        "REDIRECT_HTTP_AUTHORIZATION=[redacted]",
        "X_AUTHORIZATION=[redacted]",
        "Manifest <path>",
        "Manifest <path>",
    ]


def test_path_redaction_preserves_actionable_detail_and_contains_legal_punctuation():
    sanitized = sanitize_diagnostic_text(
        "ERROR: Invalid schema at /tmp/generated-app because field customerId is required\n"
        "ERROR: Output /tmp/generated-app already exists\n"
        "Manifest /Users/alice/Project,Secret/generated-app\n"
        "Manifest /Users/alice/Project (Secret)/generated-app\n"
        "Manifest C:\\Users\\Alice\\Project,Secret\\generated-app\n"
        "Manifest C:\\Users\\Alice\\Project (Secret)\\generated-app"
    )

    assert sanitized.splitlines() == [
        "ERROR: Invalid schema at <path> because field customerId is required",
        "ERROR: Output <path> already exists",
        "Manifest <path>",
        "Manifest <path>",
        "Manifest <path>",
        "Manifest <path>",
    ]


def test_colon_labels_and_path_shaped_boundaries_do_not_bypass_redaction():
    sanitized = sanitize_diagnostic_text(
        "path:/Users/alice/Secret/generated-app\n"
        "manifest:C:\\Users\\Alice\\Secret\\generated-app\n"
        "FileNotFoundError:/Users/alice/Secret/app-definition\n"
        "Manifest /Users/alice/Project, file SECRET/generated-app\n"
        "Manifest /Users/alice/Project because field SECRET/generated-app\n"
        "Manifest C:\\Users\\Alice\\Project, file SECRET\\generated-app"
    )

    assert sanitized.splitlines() == [
        "path:<path>",
        "manifest:<path>",
        "FileNotFoundError:<path>",
        "Manifest <path>",
        "Manifest <path>",
        "Manifest <path>",
    ]


def test_projection_keeps_raw_result_unchanged_and_adds_opaque_id():
    result = SimpleNamespace(success=False, combined_output=HOSTILE_DIAGNOSTIC)

    projection = project_engine_result(result)

    assert result.combined_output == HOSTILE_DIAGNOSTIC
    assert projection.diagnostic_id == result.diagnostic_id
    assert projection.diagnostic_id.startswith("diag-")
    assert projection.summary == "Field 'customerId' is required"
    assert projection.errors == ["Field 'customerId' is required"]
    assert projection.diagnostic_id in projection.message
    assert "local-secret-value" not in projection.message


def test_default_log_projection_is_bounded_sanitized_and_correlated(caplog):
    diagnostic_id = new_diagnostic_id()

    with caplog.at_level(logging.ERROR):
        log_engine_diagnostic(
            logging.getLogger("tests.diagnostics"),
            logging.ERROR,
            label="run_generate",
            diagnostic_id=diagnostic_id,
            detail=HOSTILE_DIAGNOSTIC + ("x" * 5000),
        )

    logged = caplog.text
    assert diagnostic_id in logged
    assert "Field 'customerId' is required" in logged
    assert "local-secret-value" not in logged
    assert "/Users/example" not in logged
    assert len(caplog.records[-1].getMessage()) <= DIAGNOSTIC_LOG_LIMIT + 100
