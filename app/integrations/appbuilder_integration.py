"""Integration with the local EdgeForge Engine checkout."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.services.diagnostics import (
    log_engine_diagnostic,
    new_diagnostic_id,
)
from app.services.manifest_contract import manifest_version_mismatch_diagnostic
from app.services.openapi_fetch_guard import (
    ENGINE_ALLOWED_HOSTS_ENV,
    normalized_openapi_allowed_hosts,
)
from app.services.path_resolver import PathResolutionError, preflight_engine_package
from app.services.settings import get_studio_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structured result
# ---------------------------------------------------------------------------

@dataclass
class SubprocessResult:
    """Structured result from every AppBuilder subprocess call.

    Separating stdout/stderr and capturing timing makes smoke-test failures
    immediately diagnosable without having to guess whether the process
    crashed, timed out, or returned a non-zero exit from a known error path.
    """
    success: bool
    returncode: int
    stdout: str
    stderr: str
    # Internal raw diagnostic material. Sanitize before presentation or persistence.
    combined_output: str
    duration_seconds: float
    command: list[str]          # exact argv that was executed
    cwd: str | None          # working directory, or None
    diagnostic_id: str = field(default_factory=new_diagnostic_id)


@dataclass
class ChangePlanResult:
    """Structured result for the Engine Change Plan CLI."""

    success: bool
    change_plan: dict[str, Any] | None
    error: str | None
    subprocess: SubprocessResult
    out_path: str | None = None


@dataclass
class ApplyResult:
    """Structured result for the Engine regeneration apply CLI."""

    success: bool
    error: str | None
    subprocess: SubprocessResult


# ---------------------------------------------------------------------------
# Internal subprocess helper
# ---------------------------------------------------------------------------

_MCP_ALLOWED_ROOTS_ENV = "EDGEFORGE_MCP_ALLOWED_ROOTS"
_STUDIO_ENGINE_TRANSPORT_ENV = "EDGEFORGE_STUDIO_ENGINE_TRANSPORT"
_STUDIO_ENGINE_MCP_COMMAND_ENV = "EDGEFORGE_STUDIO_ENGINE_MCP_COMMAND"
_STUDIO_ENGINE_VALIDATION_REPO_ENV = "EDGEFORGE_STUDIO_ENGINE_VALIDATION_REPO"
_STUDIO_ENGINE_OPENAPI_CACHE_ENV = "EDGEFORGE_STUDIO_ENGINE_OPENAPI_CACHE"
_MCP_SERVER_NAME = "edgeforge-engine"
# Engine branches on ``spec_url`` during translation, so satisfy that fetch seam
# from Studio-approved bytes rather than rewriting the invocation manifest.
_ENGINE_OPENAPI_CACHE_BOOTSTRAP = """
import json
import os
import runpy
import sys
from pathlib import Path

import yaml

from appbuilder.ingestion.openapi_fetcher import OpenAPIFetchPolicyError

try:
    cache_path = Path(os.environ["EDGEFORGE_STUDIO_ENGINE_OPENAPI_CACHE"]).resolve()
    cache_root = cache_path.parent
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
except (KeyError, OSError, UnicodeError, json.JSONDecodeError) as exc:
    raise OpenAPIFetchPolicyError("Studio OpenAPI cache is unavailable or invalid") from exc
if not isinstance(cache, dict):
    raise OpenAPIFetchPolicyError("Studio OpenAPI cache is unavailable or invalid")
sources = cache.get("sources")
if not isinstance(sources, dict):
    raise OpenAPIFetchPolicyError("Studio OpenAPI cache is unavailable or invalid")


def _studio_cached_openapi_fetch(url):
    relative_source = sources.get(url)
    if not isinstance(relative_source, str) or not relative_source:
        raise OpenAPIFetchPolicyError(
            "OpenAPI URL was not approved by Studio for this Engine invocation"
        )
    source_path = (cache_root / relative_source).resolve()
    try:
        source_path.relative_to(cache_root)
    except ValueError as exc:
        raise OpenAPIFetchPolicyError("Studio OpenAPI cache source is invalid") from exc
    try:
        raw = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise OpenAPIFetchPolicyError("Studio OpenAPI cache source is unavailable") from exc
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError:
        try:
            spec = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise ValueError(
                f"Failed to fetch OpenAPI spec from {url}: "
                "response was neither valid JSON nor YAML"
            ) from exc
    if not isinstance(spec, dict):
        raise ValueError(
            f"Failed to fetch OpenAPI spec from {url}: response did not contain a mapping"
        )
    return spec


import appbuilder.ingestion as ingestion
import appbuilder.ingestion.openapi_fetcher as openapi_fetcher

ingestion.fetch_openapi_spec = _studio_cached_openapi_fetch
openapi_fetcher.fetch_openapi_spec = _studio_cached_openapi_fetch

module_name = sys.argv[1]
sys.argv = [module_name, *sys.argv[2:]]
runpy.run_module(module_name, run_name="__main__")
""".strip()


def _engine_module_args(
    module_name: str,
    *args: str,
    openapi_cache_path: str | None = None,
) -> list[str]:
    if openapi_cache_path:
        return ["-c", _ENGINE_OPENAPI_CACHE_BOOTSTRAP, module_name, *args]
    return ["-m", module_name, *args]


def _engine_module_command(
    module_name: str,
    *args: str,
    openapi_cache_path: str | None = None,
) -> list[str]:
    return [
        sys.executable,
        *_engine_module_args(
            module_name,
            *args,
            openapi_cache_path=openapi_cache_path,
        ),
    ]


def _openapi_cache_error(
    cache_path: str | None,
    *,
    expected_urls: list[str],
) -> str | None:
    """Validate the server-owned URL-to-file cache before an Engine child starts."""
    if not expected_urls:
        return None
    if not cache_path:
        return "the cache was not provided."
    try:
        resolved_cache = Path(cache_path).expanduser().resolve(strict=True)
        payload = json.loads(resolved_cache.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "the cache is unavailable or invalid."
    sources = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(sources, dict):
        return "the cache is unavailable or invalid."
    cache_root = resolved_cache.parent
    for url in dict.fromkeys(expected_urls):
        relative_source = sources.get(url)
        if not isinstance(relative_source, str) or not relative_source:
            return "the cache does not cover every manifest URL."
        source = (cache_root / relative_source).resolve(strict=False)
        try:
            source.relative_to(cache_root)
        except ValueError:
            return "the cache contains an invalid source."
        if not source.is_file():
            return "the cache contains an unavailable source."
    return None


def _decode_timeout_output(value: object) -> str:
    """Safely decode partial output from a TimeoutExpired exception.

    Python stores exc.output / exc.stderr as bytes on TimeoutExpired even when
    subprocess.run() was called with text=True.  Decode with errors='replace'
    so any partially-written binary output never raises a UnicodeDecodeError.
    Returns an empty string when the value is None (no output was captured).
    """
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


def _extract_child_os_error(output: str) -> str | None:
    """Return a concise OSError line from child-process output, if present."""
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if stripped.startswith("OSError:") or "Resource deadlock avoided" in stripped:
            return stripped
    return None


def _manifest_version_diagnostic_for_result(result: SubprocessResult) -> str | None:
    raw_output = "\n".join(
        part for part in (result.combined_output, result.stdout, result.stderr) if part
    )
    return manifest_version_mismatch_diagnostic(raw_output)


def _apply_manifest_version_diagnostic(
    result: SubprocessResult,
    *,
    label: str,
) -> SubprocessResult:
    """Replace unmistakable version failures with a concise UI-safe message."""
    if result.success:
        return result

    diagnostic = _manifest_version_diagnostic_for_result(result)
    if diagnostic is None:
        return result

    log_engine_diagnostic(
        logger,
        logging.ERROR,
        label=label,
        diagnostic_id=result.diagnostic_id,
        detail=diagnostic,
    )
    result.combined_output = diagnostic
    return result


def _engine_failure_result(
    message: str,
    *,
    label: str,
    command: list[str] | None = None,
    cwd: str | None = None,
) -> SubprocessResult:
    """Create and safely log a pre-spawn Engine failure."""

    result = SubprocessResult(
        success=False,
        returncode=-1,
        stdout="",
        stderr=message,
        combined_output=message,
        duration_seconds=0.0,
        command=command or [],
        cwd=cwd,
    )
    log_engine_diagnostic(
        logger,
        logging.ERROR,
        label=label,
        diagnostic_id=result.diagnostic_id,
        detail=message,
    )
    return result


def _run_subprocess(
    cmd: list[str],
    *,
    cwd: str | None = None,
    env: dict | None = None,
    timeout: int = 30,
    label: str = "subprocess",
) -> SubprocessResult:
    """Run *cmd* and return a fully-populated SubprocessResult.

    Handles the common failure modes so callers don't need to:
    - non-zero exit
    - TimeoutExpired
    - FileNotFoundError (missing executable / bad PATH)
    - OSError (process startup failures such as Docker/macOS deadlock errors)
    """
    diagnostic_id = new_diagnostic_id()
    logger.debug("[%s] diagnostic_id=%s Engine subprocess started", label, diagnostic_id)
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
        duration = round(time.monotonic() - t0, 3)
        combined = (proc.stdout + proc.stderr).strip()
        ok = proc.returncode == 0

        if ok:
            logger.debug(
                "[%s] diagnostic_id=%s exit=0 duration=%.3fs",
                label,
                diagnostic_id,
                duration,
            )
        else:
            log_engine_diagnostic(
                logger,
                logging.ERROR,
                label=label,
                diagnostic_id=diagnostic_id,
                detail=f"exit={proc.returncode} duration={duration:.3f}s\n{combined}",
            )

        return SubprocessResult(
            success=ok,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            combined_output=combined,
            duration_seconds=duration,
            command=cmd,
            cwd=cwd,
            diagnostic_id=diagnostic_id,
        )

    except subprocess.TimeoutExpired as exc:
        duration = round(time.monotonic() - t0, 3)
        # exc.output / exc.stderr hold whatever was captured before the process
        # was killed — often the most useful diagnostic signal for long-running
        # assess/generate runs.  Preserve them rather than replacing with a
        # generic message.
        # NOTE: Python always stores these as bytes on TimeoutExpired even when
        # subprocess.run() was called with text=True — decode defensively.
        partial_stdout = _decode_timeout_output(exc.output)
        partial_stderr = _decode_timeout_output(exc.stderr)
        timeout_msg = f"Timed out after {timeout}s"
        combined = "\n".join(filter(None, [timeout_msg, partial_stdout.strip(), partial_stderr.strip()]))
        log_engine_diagnostic(
            logger,
            logging.ERROR,
            label=label,
            diagnostic_id=diagnostic_id,
            detail=combined,
        )
        return SubprocessResult(
            success=False,
            returncode=-1,
            stdout=partial_stdout,
            stderr=partial_stderr or timeout_msg,
            combined_output=combined,
            duration_seconds=duration,
            command=cmd,
            cwd=cwd,
            diagnostic_id=diagnostic_id,
        )

    except FileNotFoundError as exc:
        duration = round(time.monotonic() - t0, 3)
        msg = f"Executable not found: {exc}"
        log_engine_diagnostic(
            logger,
            logging.ERROR,
            label=label,
            diagnostic_id=diagnostic_id,
            detail=msg,
        )
        return SubprocessResult(
            success=False,
            returncode=-1,
            stdout="",
            stderr=msg,
            combined_output=msg,
            duration_seconds=duration,
            command=cmd,
            cwd=cwd,
            diagnostic_id=diagnostic_id,
        )

    except OSError as exc:
        duration = round(time.monotonic() - t0, 3)
        msg = f"Failed to start subprocess: {exc}"
        log_engine_diagnostic(
            logger,
            logging.ERROR,
            label=label,
            diagnostic_id=diagnostic_id,
            detail=msg,
        )
        return SubprocessResult(
            success=False,
            returncode=-1,
            stdout="",
            stderr=msg,
            combined_output=msg,
            duration_seconds=duration,
            command=cmd,
            cwd=cwd,
            diagnostic_id=diagnostic_id,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _package_preflight_error(*packages: str | Path) -> str | None:
    try:
        for package in packages:
            preflight_engine_package(package)
    except PathResolutionError as exc:
        return str(exc)
    return None

def validate_manifest(
    manifest_path: Path,
    appbuilder_repo: str,
    *,
    allowed_roots: list[str] | None = None,
) -> SubprocessResult:
    """Validate app-definition.yaml using AppBuilder's load_project_definition.

    Runs an inline Python script in a subprocess so AppBuilder's own Pydantic
    models do the validation — the same path AppBuilder takes at generate time.
    """
    if error := _package_preflight_error(Path(manifest_path).parent, manifest_path):
        return _engine_failure_result(error, label="validate_manifest")
    repo = _validation_repo_for(Path(appbuilder_repo))
    if not repo.exists():
        msg = f"AppBuilder repo not found at: {repo}"
        return _engine_failure_result(msg, label="validate_manifest")

    # Use repr() for each path to avoid any injection via special characters.
    repo_repr = repr(str(repo))
    manifest_repr = repr(str(manifest_path))
    script = (
        f"import sys\n"
        f"sys.path.insert(0, {repo_repr})\n"
        f"from appbuilder.contracts.manifest import load_project_definition\n"
        f"load_project_definition({manifest_repr})\n"
        f"print('VALID')\n"
    )

    cmd = [sys.executable, "-B", "-c", script]
    settings = get_studio_settings()
    roots = allowed_roots or [str(Path(manifest_path).parent)]
    result = _run_subprocess(
        cmd,
        cwd=str(repo),
        env=_engine_subprocess_env(repo, allowed_roots=roots, settings=settings),
        timeout=settings.engine_validate_timeout_seconds,
        label="validate_manifest",
    )

    # Validate the sentinel: process may exit 0 but omit "VALID" if the script
    # printed nothing (should not happen, but be defensive).
    if result.success and "VALID" not in result.stdout:
        result.success = False
        result.stderr = result.stderr or "Validation script exited 0 but did not print VALID"
        result.combined_output = result.stderr
        log_engine_diagnostic(
            logger,
            logging.ERROR,
            label="validate_manifest",
            diagnostic_id=result.diagnostic_id,
            detail=result.stdout,
        )

    child_os_error = _extract_child_os_error(result.stderr or result.stdout)

    if result.success:
        result.combined_output = "Manifest is valid (passed AppBuilder validation)"
    elif child_os_error:
        result.stderr = (
            "Validation subprocess failed before manifest checks: "
            f"{child_os_error}"
        )
        result.combined_output = result.stderr
    elif _manifest_version_diagnostic_for_result(result):
        result = _apply_manifest_version_diagnostic(result, label="validate_manifest")
    else:
        result.combined_output = f"Manifest validation failed: {result.stderr or result.stdout}".strip()

    return result


def run_assess(
    spec_url: str,
    appbuilder_repo: str,
    output_path: str | None = None,
    *,
    allowed_roots: list[str] | None = None,
    openapi_cache_path: str | None = None,
) -> SubprocessResult:
    """Run Engine assessment with Studio-approved content for the original URL.

    The optional assessment JSON written to *output_path* is parsed and
    attached to ``result.combined_output`` as context when available.
    """
    inputs = [Path(value).parent for value in (openapi_cache_path, output_path) if value]
    if openapi_cache_path:
        inputs.append(Path(openapi_cache_path))
    if error := _package_preflight_error(*inputs):
        return _engine_failure_result(error, label="run_assess")
    repo = Path(appbuilder_repo)
    if not repo.exists():
        msg = f"AppBuilder repo not found at: {appbuilder_repo}"
        return _engine_failure_result(msg, label="run_assess")

    cache_error = _openapi_cache_error(openapi_cache_path, expected_urls=[spec_url])
    if cache_error:
        msg = (
            "Engine assessment requires a complete Studio-validated OpenAPI cache; "
            f"{cache_error}"
        )
        return _engine_failure_result(msg, label="run_assess")

    cmd = _engine_module_command(
        "appbuilder.cli",
        "assess",
        "--swagger",
        spec_url,
        openapi_cache_path=openapi_cache_path,
    )
    if output_path:
        cmd += ["--output", output_path]

    settings = get_studio_settings()
    roots = allowed_roots or []
    if settings.shared_mode and openapi_cache_path and not _path_is_under_any(
        openapi_cache_path,
        roots,
    ):
        msg = "Assessment OpenAPI cache is outside the configured Engine allowed roots."
        return _engine_failure_result(msg, label="run_assess")
    if settings.shared_mode and output_path and not _path_is_under_any(output_path, roots):
        msg = "Assessment output path is outside the configured Engine allowed roots."
        return _engine_failure_result(msg, label="run_assess")

    result = _run_subprocess(
        cmd,
        cwd=str(repo),
        env=_engine_subprocess_env(
            repo,
            allowed_roots=roots,
            settings=settings,
            openapi_cache_path=openapi_cache_path,
        ),
        timeout=settings.engine_assess_timeout_seconds,
        label="run_assess",
    )

    # Append parsed assessment JSON to combined_output for richer UI display.
    if output_path and Path(output_path).exists():
        try:
            assessment = json.loads(Path(output_path).read_text())
            result.combined_output = (
                result.combined_output + "\n" + json.dumps(assessment, indent=2)
            ).strip()
            logger.debug(
                "[run_assess] diagnostic_id=%s assessment JSON loaded",
                result.diagnostic_id,
            )
        except Exception as exc:
            log_engine_diagnostic(
                logger,
                logging.WARNING,
                label="run_assess",
                diagnostic_id=result.diagnostic_id,
                detail=f"Assessment JSON could not be parsed: {exc}",
            )

    return result


def run_change_plan(
    manifest_path: str | Path,
    package_dir: str | Path,
    appbuilder_repo: str,
    *,
    allowed_roots: list[str],
) -> ChangePlanResult:
    """Run Engine ``appbuilder plan`` and parse the emitted Change Plan JSON."""

    if error := _package_preflight_error(Path(manifest_path).parent, manifest_path, package_dir):
        return ChangePlanResult(
            success=False, change_plan=None, error=error,
            subprocess=_engine_failure_result(error, label="run_change_plan"),
        )

    repo = Path(appbuilder_repo)
    if not repo.exists():
        msg = f"AppBuilder repo not found at: {appbuilder_repo}"
        subprocess_result = _engine_failure_result(msg, label="run_change_plan")
        return ChangePlanResult(
            success=False,
            change_plan=None,
            error=msg,
            subprocess=subprocess_result,
        )

    manifest = Path(manifest_path)
    package = Path(package_dir)
    output_dir = _change_plan_output_dir(package, allowed_roots)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"change-plan-{uuid.uuid4().hex}.json"
    roots = list(dict.fromkeys([*allowed_roots, str(output_dir)]))
    settings = get_studio_settings()

    cmd = [
        sys.executable,
        "-m",
        "appbuilder.cli",
        "plan",
        "--manifest",
        str(manifest),
        "--package",
        str(package),
        "--out",
        str(out_path),
        "--validate-schema",
    ]
    result = _run_subprocess(
        cmd,
        cwd=str(repo),
        env=_engine_subprocess_env(repo, allowed_roots=roots, settings=settings),
        timeout=settings.engine_generate_timeout_seconds,
        label="run_change_plan",
    )
    result = _apply_manifest_version_diagnostic(result, label="run_change_plan")
    if not result.success:
        return ChangePlanResult(
            success=False,
            change_plan=None,
            error=result.combined_output or "Engine Change Plan failed.",
            subprocess=result,
            out_path=str(out_path),
        )

    try:
        if out_path.exists():
            raw = out_path.read_text(encoding="utf-8")
        else:
            raw = result.stdout
        parsed = json.loads(raw)
    except Exception as exc:
        msg = f"Engine Change Plan output could not be parsed as JSON: {exc}"
        return ChangePlanResult(
            success=False,
            change_plan=None,
            error=msg,
            subprocess=result,
            out_path=str(out_path),
        )
    finally:
        out_path.unlink(missing_ok=True)

    if not isinstance(parsed, dict):
        msg = "Engine Change Plan output was not a JSON object."
        return ChangePlanResult(
            success=False,
            change_plan=None,
            error=msg,
            subprocess=result,
            out_path=str(out_path),
        )
    return ChangePlanResult(
        success=True,
        change_plan=parsed,
        error=None,
        subprocess=result,
        out_path=str(out_path),
    )


def run_apply(
    manifest_path: str | Path,
    package_dir: str | Path,
    appbuilder_repo: str,
    *,
    approved_plan_hash: str,
    allowed_roots: list[str],
) -> ApplyResult:
    """Run Engine ``appbuilder apply`` for an approved regeneration Change Plan."""

    if error := _package_preflight_error(Path(manifest_path).parent, manifest_path, package_dir):
        return ApplyResult(
            success=False, error=error,
            subprocess=_engine_failure_result(error, label="run_apply"),
        )

    repo = Path(appbuilder_repo)
    if not repo.exists():
        msg = f"AppBuilder repo not found at: {appbuilder_repo}"
        subprocess_result = _engine_failure_result(msg, label="run_apply")
        return ApplyResult(
            success=False,
            error=msg,
            subprocess=subprocess_result,
        )

    manifest = Path(manifest_path)
    package = Path(package_dir)
    settings = get_studio_settings()
    cmd = [
        sys.executable,
        "-m",
        "appbuilder.cli",
        "apply",
        "--manifest",
        str(manifest),
        "--package",
        str(package),
        "--approved-plan-hash",
        approved_plan_hash,
    ]
    result = _run_subprocess(
        cmd,
        cwd=str(repo),
        env=_engine_subprocess_env(repo, allowed_roots=allowed_roots, settings=settings),
        timeout=settings.engine_generate_timeout_seconds,
        label="run_apply",
    )
    result = _apply_manifest_version_diagnostic(result, label="run_apply")
    return ApplyResult(
        success=result.success,
        error=None if result.success else (result.combined_output or "Engine apply failed."),
        subprocess=result,
    )


def run_generate(
    manifest_path: str,
    output_dir: str,
    appbuilder_repo: str,
    *,
    openapi_cache_path: str | None = None,
) -> SubprocessResult:
    """Generate an app, preferring Engine MCP with subprocess fallback."""
    if error := _package_preflight_error(Path(manifest_path).parent, manifest_path, output_dir):
        return _engine_failure_result(error, label="run_generate")
    repo = Path(appbuilder_repo)
    if not repo.exists():
        msg = f"AppBuilder repo not found at: {appbuilder_repo}"
        return _engine_failure_result(msg, label="run_generate")

    try:
        manifest_payload = yaml.safe_load(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        manifest_payload = None
    upstream_interfaces = (
        manifest_payload.get("upstream_interfaces")
        if isinstance(manifest_payload, dict)
        else None
    )
    remote_urls = [
        str(interface["spec_url"]).strip()
        for interface in upstream_interfaces or []
        if isinstance(interface, dict)
        and isinstance(interface.get("spec_url"), str)
        and str(interface["spec_url"]).strip()
    ]
    cache_error = _openapi_cache_error(
        openapi_cache_path,
        expected_urls=remote_urls,
    )
    if remote_urls and cache_error:
        msg = (
            "Engine generation requires a complete Studio-validated OpenAPI cache; "
            f"{cache_error}"
        )
        return _engine_failure_result(msg, label="run_generate")

    settings = get_studio_settings()
    engine_roots = [
        str(Path(manifest_path).expanduser().resolve(strict=False).parent),
        str(Path(output_dir).expanduser().resolve(strict=False).parent),
    ]
    if openapi_cache_path and not _path_is_under_any(openapi_cache_path, engine_roots):
        msg = "Generation OpenAPI cache is outside the configured Engine allowed roots."
        return _engine_failure_result(msg, label="run_generate")
    transport = os.environ.get(_STUDIO_ENGINE_TRANSPORT_ENV, "auto").strip().lower()
    if settings.shared_mode:
        mcp_result = (
            _run_generate_mcp(
                manifest_path,
                output_dir,
                repo,
                openapi_cache_path=openapi_cache_path,
            )
            if openapi_cache_path
            else _run_generate_mcp(manifest_path, output_dir, repo)
        )
        if (
            mcp_result.success
            or mcp_result.returncode != -1
            or _manifest_version_diagnostic_for_result(mcp_result)
        ):
            return mcp_result
        msg = (
            "Engine MCP generate is required in shared mode; "
            f"subprocess fallback is disabled. {mcp_result.combined_output}"
        )
        result = _engine_failure_result(
            msg,
            label="run_generate",
            command=mcp_result.command,
            cwd=mcp_result.cwd,
        )
        result.duration_seconds = mcp_result.duration_seconds
        return result

    if transport in {"mcp", "auto"}:
        mcp_result = (
            _run_generate_mcp(
                manifest_path,
                output_dir,
                repo,
                openapi_cache_path=openapi_cache_path,
            )
            if openapi_cache_path
            else _run_generate_mcp(manifest_path, output_dir, repo)
        )
        if mcp_result.success or transport == "mcp" or mcp_result.returncode != -1:
            return mcp_result
        log_engine_diagnostic(
            logger,
            logging.WARNING,
            label="run_generate",
            diagnostic_id=mcp_result.diagnostic_id,
            detail=(
                "Engine MCP unavailable; falling back to subprocess. "
                f"{mcp_result.combined_output}"
            ),
        )

    cmd = _engine_module_command(
        "appbuilder.cli",
        "generate",
        "--manifest", manifest_path,
        "--output", output_dir,
        openapi_cache_path=openapi_cache_path,
    )

    result = _run_subprocess(
        cmd,
        cwd=str(repo),
        env=_engine_subprocess_env(
            repo,
            allowed_roots=engine_roots,
            settings=settings,
            openapi_cache_path=openapi_cache_path,
        ),
        timeout=settings.engine_generate_timeout_seconds,
        label="run_generate",
    )
    result = _apply_manifest_version_diagnostic(result, label="run_generate")

    if result.success:
        logger.info(
            "[run_generate] diagnostic_id=%s completed in %.3fs",
            result.diagnostic_id,
            result.duration_seconds,
        )
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _change_plan_output_dir(package_dir: Path, allowed_roots: list[str]) -> Path:
    package = package_dir.expanduser().resolve(strict=False)
    for root in reversed(allowed_roots):
        candidate = Path(root).expanduser().resolve(strict=False)
        if candidate == package:
            continue
        try:
            candidate.relative_to(package)
            continue
        except ValueError:
            return candidate
    return package.parent


def _run_generate_mcp(
    manifest_path: str,
    output_dir: str,
    repo: Path,
    *,
    openapi_cache_path: str | None = None,
) -> SubprocessResult:
    """Call Engine MCP ``generate_app`` and adapt the response to SubprocessResult."""
    t0 = time.monotonic()
    command = ["mcp", _MCP_SERVER_NAME, "generate_app"]
    try:
        mcp_call = (
            _call_generate_app_mcp(
                manifest_path,
                output_dir,
                repo,
                openapi_cache_path=openapi_cache_path,
            )
            if openapi_cache_path
            else _call_generate_app_mcp(manifest_path, output_dir, repo)
        )
        payload = _run_async_blocking(mcp_call)
    except Exception as exc:
        duration = round(time.monotonic() - t0, 3)
        msg = f"Engine MCP generate_app unavailable: {exc}"
        result = SubprocessResult(
            success=False,
            returncode=-1,
            stdout="",
            stderr=msg,
            combined_output=msg,
            duration_seconds=duration,
            command=command,
            cwd=str(repo),
        )
        log_engine_diagnostic(
            logger,
            logging.WARNING,
            label="run_generate_mcp",
            diagnostic_id=result.diagnostic_id,
            detail=msg,
        )
        return _apply_manifest_version_diagnostic(result, label="run_generate_mcp")

    duration = round(time.monotonic() - t0, 3)
    success = bool(payload.get("success"))
    output = _format_mcp_generation_output(payload)
    result = SubprocessResult(
        success=success,
        returncode=0 if success else 1,
        stdout=output if success else "",
        stderr="" if success else output,
        combined_output=output,
        duration_seconds=duration,
        command=command,
        cwd=str(repo),
    )
    return _apply_manifest_version_diagnostic(result, label="run_generate_mcp")


async def _call_generate_app_mcp(
    manifest_path: str,
    output_dir: str,
    repo: Path,
    *,
    openapi_cache_path: str | None = None,
) -> dict[str, Any]:
    """Call FastMCP using the local stdio Engine server config."""
    try:
        from fastmcp import Client
    except ModuleNotFoundError as exc:
        raise RuntimeError("fastmcp is not installed in the Studio environment") from exc

    config = {
        "mcpServers": {
            _MCP_SERVER_NAME: {
                "command": _mcp_command(repo),
                "args": _engine_module_args(
                    "appbuilder.mcp_server",
                    openapi_cache_path=openapi_cache_path,
                ),
                "cwd": str(repo),
                "env": _mcp_env(
                    manifest_path,
                    output_dir,
                    repo,
                    openapi_cache_path=openapi_cache_path,
                ),
            }
        }
    }
    async with Client(config) as client:
        result = await client.call_tool(
            "generate_app",
            {"manifest_path": manifest_path, "output_dir": output_dir},
        )
    return _coerce_mcp_tool_result(result)


def _validation_repo_for(configured_repo: Path) -> Path:
    """Return the repo path used for Python manifest validation imports.

    Docker Compose keeps the editable Engine checkout mounted at
    /workspace/EdgeForge for user-facing paths, but Python imports from that
    macOS bind mount can fail with Errno 35.  When Compose provides an
    image-local validation runtime, use it only for imports; manifest file paths
    and generated output remain unchanged.
    """
    override = os.environ.get(_STUDIO_ENGINE_VALIDATION_REPO_ENV, "").strip()
    if override:
        override_path = Path(override).expanduser()
        if override_path.exists():
            return override_path
        logger.warning(
            "[validate_manifest] diagnostic_id=%s configured validation repo does not exist: <path>",
            new_diagnostic_id(),
        )
    return configured_repo


def _run_async_blocking(coro):
    """Run a coroutine from sync code, including inside an active event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result()


def _mcp_env(
    manifest_path: str,
    output_dir: str,
    repo: Path,
    *,
    openapi_cache_path: str | None = None,
) -> dict[str, str]:
    settings = get_studio_settings()
    allowed = []
    if not settings.shared_mode:
        allowed.append(str(repo.expanduser().resolve(strict=False)))
    allowed.extend(
        [
            str(Path(manifest_path).expanduser().resolve(strict=False).parent),
            str(Path(output_dir).expanduser().resolve(strict=False).parent),
        ]
    )
    existing = os.environ.get(_MCP_ALLOWED_ROOTS_ENV)
    if existing and not settings.shared_mode:
        allowed.extend(part for part in existing.split(os.pathsep) if part.strip())
    if settings.shared_mode:
        return _engine_subprocess_env(
            repo,
            allowed_roots=allowed,
            settings=settings,
            openapi_cache_path=openapi_cache_path,
        )
    env = _env_with_repo(repo, openapi_cache_path=openapi_cache_path)
    env.pop("EDGEFORGE_SHARED_MODE", None)
    env[_MCP_ALLOWED_ROOTS_ENV] = os.pathsep.join(dict.fromkeys(allowed))
    return env


def _mcp_command(repo: Path) -> str:
    configured = os.environ.get(_STUDIO_ENGINE_MCP_COMMAND_ENV)
    if configured and configured.strip():
        return configured.strip()

    repo_venv_python = repo / ".venv" / "bin" / "python"
    if repo_venv_python.exists():
        return str(repo_venv_python)

    return sys.executable


def _coerce_mcp_tool_result(result: object) -> dict[str, Any]:
    """Handle FastMCP result variants without coupling Studio to one version."""
    for attr in ("data", "structured_content", "structuredContent"):
        value = getattr(result, attr, None)
        if isinstance(value, dict):
            return value

    if isinstance(result, dict):
        return result

    content = getattr(result, "content", None)
    if isinstance(content, list) and content:
        text = "\n".join(
            str(getattr(item, "text", ""))
            for item in content
            if getattr(item, "text", "")
        ).strip()
        if text:
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                return {"success": False, "errors": [text], "warnings": [], "files_written": []}

    raise RuntimeError(f"Unexpected MCP generate_app result shape: {type(result).__name__}")


def _format_mcp_generation_output(payload: dict[str, Any]) -> str:
    output_dir = payload.get("output_dir") or ""
    files = payload.get("files_written") or []
    warnings = payload.get("warnings") or []
    errors = payload.get("errors") or []

    lines: list[str] = []
    if payload.get("success"):
        lines.append(f"Generated application at: {output_dir}")
        lines.append(f"Files written: {len(files)}")
    else:
        lines.append("Generation failed via Engine MCP.")

    for warning in warnings:
        lines.append(f"WARNING: {warning}")
    for error in errors:
        lines.append(f"ERROR: {error}")
    return "\n".join(lines).strip()


def _engine_subprocess_env(
    repo: Path,
    *,
    allowed_roots: list[str],
    settings=None,
    openapi_cache_path: str | None = None,
) -> dict:
    """Build an Engine subprocess env with shared-mode allowed roots."""
    settings = settings or get_studio_settings()
    env = _env_with_repo(repo, openapi_cache_path=openapi_cache_path)
    if not settings.shared_mode:
        env.pop(_MCP_ALLOWED_ROOTS_ENV, None)
        env.pop("EDGEFORGE_SHARED_MODE", None)
        return env

    resolved_roots = [
        str(Path(root).expanduser().resolve(strict=False))
        for root in allowed_roots
        if str(root).strip()
    ]
    env[_MCP_ALLOWED_ROOTS_ENV] = os.pathsep.join(dict.fromkeys(resolved_roots))
    env["EDGEFORGE_SHARED_MODE"] = "1"
    return env


def _path_is_under_any(path: str | Path, roots: list[str]) -> bool:
    candidate = Path(path).expanduser().resolve(strict=False)
    for root in roots:
        resolved_root = Path(root).expanduser().resolve(strict=False)
        if candidate == resolved_root:
            return True
        try:
            candidate.relative_to(resolved_root)
            return True
        except ValueError:
            continue
    return False


def _env_with_repo(
    repo: Path,
    *,
    openapi_cache_path: str | None = None,
) -> dict:
    env = os.environ.copy()
    env[ENGINE_ALLOWED_HOSTS_ENV] = ",".join(normalized_openapi_allowed_hosts())
    if openapi_cache_path:
        env[_STUDIO_ENGINE_OPENAPI_CACHE_ENV] = str(
            Path(openapi_cache_path).expanduser().resolve(strict=False)
        )
    else:
        env.pop(_STUDIO_ENGINE_OPENAPI_CACHE_ENV, None)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{repo}{':' if existing else ''}{existing}"
    return env
