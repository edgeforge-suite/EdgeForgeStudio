"""``get_studio_settings()`` flag-derivation regressions.

Distinct from ``tests/test_export_build_run.py``, which drives Build & Run
through the real ``/export/build`` and ``/export/run`` routes. These tests
target the pure derivation in ``get_studio_settings()`` itself, where a
short-circuit bug can hide: every route-level test that only exercises the
"enabled" path passes whether or not the env var was ever actually read.
"""

from __future__ import annotations

import pytest

from app.services.settings import StudioSettingsError, get_studio_settings


def _shared_mode(monkeypatch) -> None:
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")


def test_build_run_disabled_by_explicit_false_in_local_mode(monkeypatch) -> None:
    """The bug: ``(not shared_mode) or _env_bool(...)`` short-circuits to True
    in local mode before the env var is ever read, so an operator's explicit
    ``false`` had no effect.
    """
    monkeypatch.delenv("EDGEFORGE_STUDIO_SHARED_MODE", raising=False)
    monkeypatch.setenv("EDGEFORGE_STUDIO_BUILD_RUN_ENABLED", "false")

    assert get_studio_settings().build_run_enabled is False


def test_build_run_still_defaults_on_in_local_mode(monkeypatch) -> None:
    """Non-regression: local mode's today's-default (enabled) must survive."""
    monkeypatch.delenv("EDGEFORGE_STUDIO_SHARED_MODE", raising=False)
    monkeypatch.delenv("EDGEFORGE_STUDIO_BUILD_RUN_ENABLED", raising=False)

    assert get_studio_settings().build_run_enabled is True


def test_build_run_enabled_by_explicit_true_in_shared_mode(monkeypatch) -> None:
    _shared_mode(monkeypatch)
    monkeypatch.setenv("EDGEFORGE_STUDIO_BUILD_RUN_ENABLED", "true")

    assert get_studio_settings().build_run_enabled is True


def test_build_run_still_defaults_off_in_shared_mode(monkeypatch) -> None:
    """Non-regression: shared mode's today's-default (disabled) must survive."""
    _shared_mode(monkeypatch)
    monkeypatch.delenv("EDGEFORGE_STUDIO_BUILD_RUN_ENABLED", raising=False)

    assert get_studio_settings().build_run_enabled is False


def test_api_docs_default_off_and_local_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("EDGEFORGE_STUDIO_SHARED_MODE", raising=False)
    monkeypatch.delenv("EDGEFORGE_STUDIO_ENABLE_API_DOCS", raising=False)
    assert get_studio_settings().enable_api_docs is False

    monkeypatch.setenv("EDGEFORGE_STUDIO_ENABLE_API_DOCS", "true")
    assert get_studio_settings().enable_api_docs is True


def test_api_docs_opt_in_is_refused_in_shared_mode(monkeypatch) -> None:
    _shared_mode(monkeypatch)
    monkeypatch.setenv("EDGEFORGE_STUDIO_ENABLE_API_DOCS", "true")

    with pytest.raises(StudioSettingsError, match="ENABLE_API_DOCS cannot be enabled"):
        get_studio_settings()


def test_openapi_fetch_bounds_use_safe_defaults(monkeypatch) -> None:
    monkeypatch.delenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_MAX_BYTES", raising=False)
    monkeypatch.delenv(
        "EDGEFORGE_STUDIO_OPENAPI_FETCH_TIMEOUT_SECONDS",
        raising=False,
    )

    settings = get_studio_settings()

    assert settings.openapi_fetch_max_bytes == 5 * 1024 * 1024
    assert settings.openapi_fetch_timeout_seconds == 10


def test_invalid_openapi_fetch_bounds_fall_back_safely(monkeypatch) -> None:
    for invalid in ("", "not-an-integer", "0", "-1"):
        monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_MAX_BYTES", invalid)
        monkeypatch.setenv(
            "EDGEFORGE_STUDIO_OPENAPI_FETCH_TIMEOUT_SECONDS",
            invalid,
        )

        settings = get_studio_settings()

        assert settings.openapi_fetch_max_bytes == 5 * 1024 * 1024
        assert settings.openapi_fetch_timeout_seconds == 10


def test_audit_defaults_follow_runtime_mode(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EDGEFORGE_STUDIO_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("EDGEFORGE_STUDIO_AUDIT_SINK", raising=False)
    monkeypatch.delenv("EDGEFORGE_STUDIO_AUDIT_DB_PATH", raising=False)
    monkeypatch.delenv("EDGEFORGE_STUDIO_AUDIT_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("EDGEFORGE_STUDIO_SHARED_MODE", raising=False)

    local = get_studio_settings()

    assert local.audit_sink == "noop"
    assert local.audit_db_path == tmp_path / "studio-audit.sqlite3"
    assert local.audit_retention_days == 90

    _shared_mode(monkeypatch)
    shared = get_studio_settings()

    assert shared.audit_sink == "sqlite"
    assert shared.audit_db_path == tmp_path / "studio-audit.sqlite3"


@pytest.mark.parametrize("value", ["", "file", "postgres"])
def test_invalid_explicit_audit_sink_is_rejected(monkeypatch, value) -> None:
    monkeypatch.setenv("EDGEFORGE_STUDIO_AUDIT_SINK", value)

    with pytest.raises(StudioSettingsError, match="AUDIT_SINK must be one of"):
        get_studio_settings()


@pytest.mark.parametrize("value", ["", "relative/audit.sqlite3"])
def test_relative_or_blank_audit_db_path_is_rejected(monkeypatch, value) -> None:
    monkeypatch.setenv("EDGEFORGE_STUDIO_AUDIT_DB_PATH", value)

    with pytest.raises(StudioSettingsError, match="AUDIT_DB_PATH must be an absolute"):
        get_studio_settings()


@pytest.mark.parametrize("alias_kind", ["direct", "symlink", "hardlink"])
def test_audit_db_path_must_not_alias_session_database(
    monkeypatch,
    tmp_path,
    alias_kind,
) -> None:
    session_db = tmp_path / "studio-sessions.sqlite3"
    session_db.touch()
    audit_db = session_db
    if alias_kind == "symlink":
        audit_db = tmp_path / "audit-symlink.sqlite3"
        audit_db.symlink_to(session_db)
    elif alias_kind == "hardlink":
        audit_db = tmp_path / "audit-hardlink.sqlite3"
        audit_db.hardlink_to(session_db)
    monkeypatch.setenv("EDGEFORGE_STUDIO_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("EDGEFORGE_STUDIO_AUDIT_DB_PATH", str(audit_db))

    with pytest.raises(StudioSettingsError, match="must not refer to the Studio session"):
        get_studio_settings()


@pytest.mark.parametrize("value", ["", "ninety", "0", "-1"])
def test_invalid_audit_retention_is_rejected(monkeypatch, value) -> None:
    monkeypatch.setenv("EDGEFORGE_STUDIO_AUDIT_RETENTION_DAYS", value)

    with pytest.raises(StudioSettingsError, match="AUDIT_RETENTION_DAYS"):
        get_studio_settings()
