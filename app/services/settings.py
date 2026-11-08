"""Runtime settings for Studio request-context seams."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

LOCAL_DEV_SESSION_SECRET = "edgeforge-studio-local-dev-session-secret"


class StudioSettingsError(RuntimeError):
    """Raised when Studio settings would create an unsafe shared-mode posture."""


@dataclass(frozen=True)
class ResourceLimitClassSettings:
    """Rate and concurrency settings for one bounded request cost class."""

    rate_max: int
    rate_window_seconds: int
    principal_concurrency: int
    process_concurrency: int


@dataclass(frozen=True)
class RequestResourceLimits:
    """Immutable grouped settings for the five shared-mode request classes."""

    a: ResourceLimitClassSettings
    b: ResourceLimitClassSettings
    c: ResourceLimitClassSettings
    c2: ResourceLimitClassSettings
    d: ResourceLimitClassSettings

    def for_class(self, class_identifier: str) -> ResourceLimitClassSettings:
        if class_identifier == "A":
            return self.a
        if class_identifier == "B":
            return self.b
        if class_identifier == "C":
            return self.c
        if class_identifier == "C2":
            return self.c2
        if class_identifier == "D":
            return self.d
        raise ValueError(f"Unknown Studio request resource class: {class_identifier}")


def _env_bool(name: str, *, alias: str | None = None, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None and alias:
        raw = os.getenv(alias)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_choice(
    name: str,
    *,
    alias: str | None = None,
    default: str,
    allowed: set[str],
) -> str:
    raw = os.getenv(name)
    if raw is None and alias:
        raw = os.getenv(alias)
    if raw is None:
        return default
    value = raw.strip().lower()
    return value if value in allowed else default


def _env_int(name: str, *, default: int, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value >= minimum else default


def _strict_env_choice(name: str, *, default: str, allowed: set[str]) -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value not in allowed:
        choices = ", ".join(sorted(allowed))
        raise StudioSettingsError(f"{name} must be one of: {choices}.")
    return value


def _strict_env_int(name: str, *, default: int, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise StudioSettingsError(
            f"{name} must be an integer of at least {minimum}."
        ) from None
    if value < minimum:
        raise StudioSettingsError(f"{name} must be an integer of at least {minimum}.")
    return value


def _resource_limit_class_settings(
    class_identifier: str,
    *,
    rate_max: int,
    rate_window_seconds: int,
    principal_concurrency: int,
    process_concurrency: int,
) -> ResourceLimitClassSettings:
    """Read all dimensions for one cost class from the explicit operator surface."""

    prefix = f"EDGEFORGE_STUDIO_RATE_{class_identifier}_"
    return ResourceLimitClassSettings(
        rate_max=_strict_env_int(
            f"{prefix}MAX",
            default=rate_max,
            minimum=0,
        ),
        rate_window_seconds=_strict_env_int(
            f"{prefix}WINDOW_S",
            default=rate_window_seconds,
            minimum=0,
        ),
        principal_concurrency=_strict_env_int(
            f"{prefix}CONCURRENCY_PRINCIPAL",
            default=principal_concurrency,
            minimum=0,
        ),
        process_concurrency=_strict_env_int(
            f"{prefix}CONCURRENCY_PROCESS",
            default=process_concurrency,
            minimum=0,
        ),
    )


def _paths_refer_to_same_file(first: Path, second: Path) -> bool:
    first_resolved = first.expanduser().resolve(strict=False)
    second_resolved = second.expanduser().resolve(strict=False)
    if first_resolved == second_resolved:
        return True
    try:
        return first.exists() and second.exists() and first.samefile(second)
    except OSError:
        return False


@dataclass(frozen=True)
class StudioSettings:
    """Small P1 settings surface for identity/session request context."""

    shared_mode: bool
    auth_mode: str
    enable_api_docs: bool
    build_run_enabled: bool
    openapi_fetch_mode: str
    openapi_fetch_max_bytes: int
    openapi_fetch_timeout_seconds: int
    audit_sink: str
    audit_db_path: Path
    audit_retention_days: int
    max_session_disk_bytes: int
    max_projects_per_principal: int
    max_ks_db_bytes: int
    max_ks_subprocesses: int
    ks_idle_ttl_seconds: int
    session_idle_ttl_seconds: int
    engine_validate_timeout_seconds: int
    engine_assess_timeout_seconds: int
    engine_generate_timeout_seconds: int
    build_timeout_seconds: int
    regen_preview_enabled: bool
    request_resource_limits: RequestResourceLimits
    session_cookie_name: str
    session_secret: str
    session_max_age_seconds: int
    session_rotation_seconds: int
    state_dir: Path

    @property
    def cookie_secure(self) -> bool:
        return self.shared_mode

    @property
    def csrf_enforced(self) -> bool:
        return self.shared_mode


def get_studio_settings() -> StudioSettings:
    """Read settings from env with safe local defaults.

    This intentionally avoids process-wide caching so tests and local runs can toggle
    P1 flags without restarting the app.
    """

    shared_mode = _env_bool(
        "EDGEFORGE_STUDIO_SHARED_MODE",
        alias="STUDIO_SHARED_MODE",
        default=False,
    )
    auth_mode = _env_choice(
        "EDGEFORGE_STUDIO_AUTH_MODE",
        alias="STUDIO_AUTH_MODE",
        default="anonymous",
        allowed={"anonymous", "proxy", "oidc"},
    )
    enable_api_docs = _env_bool(
        "EDGEFORGE_STUDIO_ENABLE_API_DOCS",
        default=False,
    )
    if shared_mode and enable_api_docs:
        raise StudioSettingsError(
            "EDGEFORGE_STUDIO_ENABLE_API_DOCS cannot be enabled when "
            "EDGEFORGE_STUDIO_SHARED_MODE=true."
        )
    # (not shared_mode) or _env_bool(...) short-circuits in local mode: the left
    # operand is already True, so the env var is never read and an operator
    # setting EDGEFORGE_STUDIO_BUILD_RUN_ENABLED=false has no effect. Folding
    # the mode into the flag's own default keeps today's defaults (on in
    # local, off in shared) while honouring an explicit value in both modes.
    build_run_enabled = _env_bool(
        "EDGEFORGE_STUDIO_BUILD_RUN_ENABLED",
        default=not shared_mode,
    )
    openapi_fetch_mode = _env_choice(
        "EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE",
        default="allowlist" if shared_mode else "open",
        allowed={"disabled", "allowlist", "open"},
    )
    openapi_fetch_max_bytes = _env_int(
        "EDGEFORGE_STUDIO_OPENAPI_FETCH_MAX_BYTES",
        default=5 * 1024 * 1024,
        minimum=1,
    )
    openapi_fetch_timeout_seconds = _env_int(
        "EDGEFORGE_STUDIO_OPENAPI_FETCH_TIMEOUT_SECONDS",
        default=10,
        minimum=1,
    )
    state_dir = Path(
        os.getenv(
            "EDGEFORGE_STUDIO_STATE_DIR",
            str(Path(tempfile.gettempdir()) / "edgeforge-studio-state"),
        )
    ).expanduser()
    audit_sink = _strict_env_choice(
        "EDGEFORGE_STUDIO_AUDIT_SINK",
        default="sqlite" if shared_mode else "noop",
        allowed={"noop", "sqlite"},
    )
    audit_db_path_raw = os.getenv("EDGEFORGE_STUDIO_AUDIT_DB_PATH")
    if audit_db_path_raw is None:
        audit_db_path = state_dir / "studio-audit.sqlite3"
    else:
        audit_db_path = Path(audit_db_path_raw.strip()).expanduser()
        if not audit_db_path_raw.strip() or not audit_db_path.is_absolute():
            raise StudioSettingsError(
                "EDGEFORGE_STUDIO_AUDIT_DB_PATH must be an absolute operator-owned path."
            )
    session_db_path = state_dir / "studio-sessions.sqlite3"
    if _paths_refer_to_same_file(audit_db_path, session_db_path):
        raise StudioSettingsError(
            "EDGEFORGE_STUDIO_AUDIT_DB_PATH must not refer to the Studio session database."
        )
    audit_retention_days = _strict_env_int(
        "EDGEFORGE_STUDIO_AUDIT_RETENTION_DAYS",
        default=90,
        minimum=1,
    )
    max_session_disk_bytes = _env_int(
        "EDGEFORGE_STUDIO_MAX_SESSION_DISK_BYTES",
        default=5 * 1024 * 1024 * 1024,
        minimum=1,
    )
    max_projects_per_principal = _env_int(
        "EDGEFORGE_STUDIO_MAX_PROJECTS_PER_PRINCIPAL",
        default=100,
        minimum=1,
    )
    max_ks_db_bytes = _env_int(
        "EDGEFORGE_STUDIO_MAX_KS_DB_BYTES",
        default=1024 * 1024 * 1024,
        minimum=1,
    )
    max_ks_subprocesses = _env_int(
        "EDGEFORGE_STUDIO_MAX_KS_SUBPROCESSES",
        default=8,
        minimum=1,
    )
    ks_idle_ttl_seconds = _env_int(
        "EDGEFORGE_STUDIO_KS_IDLE_TTL_SECONDS",
        default=30 * 60,
        minimum=1,
    )
    session_idle_ttl_seconds = _env_int(
        "EDGEFORGE_STUDIO_SESSION_IDLE_TTL_SECONDS",
        default=24 * 60 * 60,
        minimum=60,
    )
    engine_validate_timeout_seconds = _env_int(
        "EDGEFORGE_STUDIO_ENGINE_VALIDATE_TIMEOUT_SECONDS",
        default=15,
        minimum=1,
    )
    engine_assess_timeout_seconds = _env_int(
        "EDGEFORGE_STUDIO_ENGINE_ASSESS_TIMEOUT_SECONDS",
        default=30,
        minimum=1,
    )
    engine_generate_timeout_seconds = _env_int(
        "EDGEFORGE_STUDIO_ENGINE_GENERATE_TIMEOUT_SECONDS",
        default=120,
        minimum=1,
    )
    build_timeout_seconds = _env_int(
        "EDGEFORGE_STUDIO_BUILD_TIMEOUT_SECONDS",
        default=600,
        minimum=1,
    )
    regen_preview_enabled = _env_bool(
        "EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED",
        default=False,
    )
    request_resource_limits = RequestResourceLimits(
        a=_resource_limit_class_settings(
            "A",
            rate_max=6,
            rate_window_seconds=300,
            principal_concurrency=1,
            process_concurrency=2,
        ),
        b=_resource_limit_class_settings(
            "B",
            rate_max=20,
            rate_window_seconds=300,
            principal_concurrency=2,
            process_concurrency=6,
        ),
        c=_resource_limit_class_settings(
            "C",
            rate_max=30,
            rate_window_seconds=300,
            principal_concurrency=2,
            process_concurrency=6,
        ),
        c2=_resource_limit_class_settings(
            "C2",
            rate_max=120,
            rate_window_seconds=300,
            principal_concurrency=4,
            process_concurrency=12,
        ),
        d=_resource_limit_class_settings(
            "D",
            rate_max=60,
            rate_window_seconds=300,
            principal_concurrency=4,
            process_concurrency=12,
        ),
    )
    max_age = _env_int(
        "EDGEFORGE_STUDIO_SESSION_MAX_AGE_SECONDS",
        default=8 * 60 * 60,
        minimum=60,
    )
    rotation = _env_int(
        "EDGEFORGE_STUDIO_SESSION_ROTATION_SECONDS",
        default=max_age // 2,
        minimum=30,
    )
    rotation = min(rotation, max_age)
    session_secret = os.getenv(
        "EDGEFORGE_STUDIO_SESSION_SECRET",
        LOCAL_DEV_SESSION_SECRET,
    )
    if shared_mode and session_secret == LOCAL_DEV_SESSION_SECRET:
        raise StudioSettingsError(
            "EDGEFORGE_STUDIO_SESSION_SECRET must be set to a non-default value "
            "when EDGEFORGE_STUDIO_SHARED_MODE=true."
        )

    return StudioSettings(
        shared_mode=shared_mode,
        auth_mode=auth_mode,
        enable_api_docs=enable_api_docs,
        build_run_enabled=build_run_enabled,
        openapi_fetch_mode=openapi_fetch_mode,
        openapi_fetch_max_bytes=openapi_fetch_max_bytes,
        openapi_fetch_timeout_seconds=openapi_fetch_timeout_seconds,
        audit_sink=audit_sink,
        audit_db_path=audit_db_path,
        audit_retention_days=audit_retention_days,
        max_session_disk_bytes=max_session_disk_bytes,
        max_projects_per_principal=max_projects_per_principal,
        max_ks_db_bytes=max_ks_db_bytes,
        max_ks_subprocesses=max_ks_subprocesses,
        ks_idle_ttl_seconds=ks_idle_ttl_seconds,
        session_idle_ttl_seconds=session_idle_ttl_seconds,
        engine_validate_timeout_seconds=engine_validate_timeout_seconds,
        engine_assess_timeout_seconds=engine_assess_timeout_seconds,
        engine_generate_timeout_seconds=engine_generate_timeout_seconds,
        build_timeout_seconds=build_timeout_seconds,
        regen_preview_enabled=regen_preview_enabled,
        request_resource_limits=request_resource_limits,
        session_cookie_name=os.getenv(
            "EDGEFORGE_STUDIO_SESSION_COOKIE_NAME",
            "edgeforge_studio_session",
        ),
        session_secret=session_secret,
        session_max_age_seconds=max_age,
        session_rotation_seconds=rotation,
        # expanduser() keeps state and session-supplied workspace roots aligned.
        state_dir=state_dir,
    )
