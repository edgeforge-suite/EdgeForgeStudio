"""Step 8 — Export Package."""

from __future__ import annotations

import json
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from app.integrations.appbuilder_integration import run_assess, run_generate, validate_manifest
from app.models.project import KSManifestRevision, ProjectSession
from app.paths import TEMPLATE_DIR
from app.services.audit import audit
from app.services.build_run_service import (
    build_generated_app,
    build_run_disabled_message,
    ensure_generated_app_path,
    start_generated_app,
    status_payload,
    stop_generated_app,
)
from app.services.completeness_service import build_completeness_report
from app.services.diagnostics import (
    actionable_diagnostic_summary,
    extract_diagnostic_messages,
    project_engine_diagnostic,
    project_engine_result,
    sanitize_diagnostic_text,
)
from app.services.evidence_trail import EvidenceTrailError
from app.services.generation_locks import acquire_generation_lock
from app.services.nav_context import build_nav_context
from app.services.openapi_fetch_guard import OpenAPIFetchPolicyError, fetch_url_with_policy
from app.services.package_writer import PackageWriteError, build_zip, write_package_result
from app.services.path_resolver import (
    PathResolutionError,
    contain_under_session_workspace,
    engine_repo_path,
    expand_user_path,
    export_zip_path,
    preflight_engine_package,
    session_export_dir,
    session_output_root,
    session_workspace_root,
)
from app.services.quotas import QuotaExceededError, ensure_session_disk_quota
from app.services.regen_binding import (
    RegenBindingError,
    capture_generated_package,
    regen_status,
)
from app.services.runtime_defaults import (
    default_edgeforge_repo_path,
    docker_output_path_error,
    is_docker_runtime,
)
from app.services.session_context import (
    get_current_session,
    reset_current_session,
    save_current_session,
)
from app.services.settings import StudioSettings, get_studio_settings

router = APIRouter(prefix="/export")
templates = Jinja2Templates(directory=TEMPLATE_DIR)

EXPORT_ARTIFACTS: list[dict[str, str]] = [
    {
        "name": "app-definition.yaml",
        "kind": "Manifest",
        "summary": "Primary Engine manifest package input.",
    },
    {
        "name": "evidence-trail.json",
        "kind": "Provenance",
        "summary": "Knowledge Assist provenance sidecar for supported suggestion types.",
    },
    {
        "name": "completeness-report.md",
        "kind": "Review",
        "summary": "Human-readable completeness checkpoint report.",
    },
    {
        "name": "assessment-report.json",
        "kind": "Assessment",
        "summary": "Source API assessment snapshot. Refreshed when Assess Source APIs runs.",
    },
    {
        "name": "studio-project.json",
        "kind": "Studio Project",
        "summary": "Openable Studio authoring snapshot that produced this package.",
    },
]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _manifest_openapi_urls(manifest_path: Path) -> list[str]:
    try:
        payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeError):
        return []
    interfaces = payload.get("upstream_interfaces") if isinstance(payload, dict) else None
    return [
        str(interface["spec_url"]).strip()
        for interface in interfaces or []
        if isinstance(interface, dict)
        and isinstance(interface.get("spec_url"), str)
        and str(interface["spec_url"]).strip()
    ]


@contextmanager
def _engine_openapi_response_cache(
    spec_urls: list[str],
    *,
    cache_parent: Path,
    settings: StudioSettings,
):
    """Cache pinned Studio responses while preserving Engine ``spec_url`` semantics."""
    unique_urls = list(dict.fromkeys(spec_urls))
    if not unique_urls:
        yield None
        return

    with tempfile.TemporaryDirectory(
        prefix=".studio-openapi-",
        dir=cache_parent,
    ) as source_dir_name:
        source_dir = Path(source_dir_name)
        sources: dict[str, str] = {}
        for index, spec_url in enumerate(unique_urls, start=1):
            response = fetch_url_with_policy(spec_url, settings=settings)
            source_path = source_dir / f"source-{index}.yaml"
            source_path.write_text(response.text, encoding="utf-8")
            sources[spec_url] = source_path.name
        cache_path = source_dir / "cache.json"
        cache_path.write_text(
            json.dumps({"version": 1, "sources": sources}, sort_keys=True),
            encoding="utf-8",
        )
        yield cache_path


def _extract_messages(output: str) -> tuple[list[str], list[str]]:
    """Compatibility wrapper around the centralized safe projection helper."""

    return extract_diagnostic_messages(sanitize_diagnostic_text(output))


def _extract_actionable_summary(output: str, errors: list[str] | None = None) -> str | None:
    """Compatibility wrapper returning a sanitized actionable summary."""

    safe_output = sanitize_diagnostic_text(output)
    safe_errors = [sanitize_diagnostic_text(error) for error in errors or []]
    return actionable_diagnostic_summary(safe_output, safe_errors)


def _build_export_artifact_summary(session) -> dict[str, Any] | None:
    if not session.last_export_path:
        return None

    try:
        export_dir = session_export_dir(session)
    except PathResolutionError:
        return None
    if export_dir is None:
        return None
    items: list[dict[str, str | bool]] = []
    for artifact in EXPORT_ARTIFACTS:
        artifact_path = export_dir / artifact["name"]
        if not artifact_path.exists():
            continue
        items.append({
            "name": artifact["name"],
            "kind": artifact["kind"],
            "summary": artifact["summary"],
            "path": str(artifact_path),
            "download_url": f"/export/artifact/{artifact['name']}",
            "is_evidence": artifact["name"] == "evidence-trail.json",
        })

    return {
        "output_dir": str(export_dir),
        "artifacts": items,
    }


def _latest_revision_checkpoint(session) -> dict[str, str] | None:
    revisions = session.ks_workspace_state.manifest_revisions
    if not revisions:
        return None

    latest = revisions[-1]
    try:
        # Revisions recorded before output-path expansion carry a raw '~/...'.
        # Display the resolved location Studio actually reads/writes rather
        # than the literal stored string; suppress it if it cannot be resolved
        # instead of showing an unusable path. Contained the same as every other
        # reader of a restored path -- this is display-only and never touches
        # disk, but leaving it uncontained meant Step 8 could show a revision
        # path that review.py's own baseline lookup refuses (PR #276 review, F5).
        export_path_display = str(
            contain_under_session_workspace(session, expand_user_path(latest.export_path))
        )
    except PathResolutionError:
        export_path_display = ""
    return {
        "revision_id": latest.revision_id,
        "exported_at": latest.exported_at,
        "manifest_hash": latest.manifest_hash,
        "export_path": export_path_display,
    }


def _engine_repo_path_warning(session, settings: StudioSettings | None = None) -> str | None:
    settings = settings or get_studio_settings()
    if settings.shared_mode:
        return None

    configured_path = str(session.appbuilder_repo_path or "").strip()
    if not configured_path:
        return None
    if Path(configured_path).expanduser().exists():
        return None

    default_path = default_edgeforge_repo_path()
    if default_path and default_path != configured_path:
        return (
            "This project was saved with an Engine path that does not exist here. "
            f"In Docker, set EdgeForge Local Repo Path to `{default_path}` in Step 1."
        )
    return (
        "This project was saved with an Engine path that does not exist here. "
        "Update EdgeForge Local Repo Path in Step 1 before validating or generating."
    )


def _engine_repo_path_error(session, settings: StudioSettings | None = None) -> str | None:
    warning = _engine_repo_path_warning(session, settings)
    return warning.replace("`", "") if warning else None


def _docker_output_path_response(session, settings: StudioSettings | None = None) -> JSONResponse | None:
    settings = settings or get_studio_settings()
    if settings.shared_mode:
        return None
    output_root = str(session_output_root(session, settings))
    if error := docker_output_path_error(output_root):
        return JSONResponse({"ok": False, "error": error, "summary": error}, status_code=400)
    return None


def _unresolvable_export_path_response(session) -> JSONResponse | None:
    """400 when the stored last_export_path cannot be resolved.

    A project saved with an unusable '~unknownuser/...' path must not turn every
    subsequent validate/generate/download into an HTTP 500.
    """
    try:
        export_dir = session_export_dir(session)
        if export_dir is not None:
            contain_under_session_workspace(session, export_dir / "app-definition.yaml")
            preflight_engine_package(export_dir)
    except PathResolutionError as exc:
        message = f"The recorded export location is not usable. {exc} Re-export the package."
        return JSONResponse(
            {"ok": False, "error": message, "summary": message}, status_code=400
        )
    return None


def _unresolvable_output_path_response(
    session, settings: StudioSettings | None = None
) -> JSONResponse | None:
    """400 when the configured Output Path cannot be resolved to a real location.

    ``~unknownuser/...`` (and a bare ``~`` with no HOME) cannot be expanded. That is
    user input, so it is reported rather than raised -- and it must never fall back
    to the unexpanded value, which would write under the server's CWD.
    """
    try:
        session_output_root(session, settings or get_studio_settings())
    except PathResolutionError as exc:
        message = f"Output Path is not usable. {exc}"
        return JSONResponse(
            {"ok": False, "error": message, "summary": message}, status_code=400
        )
    return None


def _build_run_disabled_response(settings: StudioSettings) -> JSONResponse | None:
    if settings.build_run_enabled:
        return None
    message = build_run_disabled_message(settings.shared_mode)
    return JSONResponse(
        {
            "ok": False,
            "error": message,
            "summary": message,
        },
        status_code=403,
    )


def _is_html_response(headers: dict[str, str]) -> bool:
    content_type = str(headers.get("content-type") or headers.get("Content-Type") or "").lower()
    return "text/html" in content_type


def _generated_app_fetch_proxy_script(port: int) -> str:
    proxy_base = f"/export/generated-app/{port}"
    return f"""
<script data-edgeforge-generated-app-proxy>
(() => {{
  const proxyBase = "{proxy_base}";
  const originalFetch = window.fetch;
  if (!originalFetch || window.__edgeforgeGeneratedAppProxyFetch) return;
  window.__edgeforgeGeneratedAppProxyFetch = true;
  function rewriteUrl(value) {{
    if (typeof value !== "string") return value;
    if (!value.startsWith("/") || value.startsWith(proxyBase + "/") || value === proxyBase) return value;
    if (value.startsWith("/export/generated-app/")) return value;
    return proxyBase + value;
  }}
  window.fetch = function(input, init) {{
    if (typeof input === "string") {{
      return originalFetch.call(this, rewriteUrl(input), init);
    }}
    if (input instanceof Request) {{
      const url = new URL(input.url, window.location.href);
      if (url.origin === window.location.origin) {{
        const rewritten = rewriteUrl(url.pathname + url.search + url.hash);
        if (rewritten !== url.pathname + url.search + url.hash) {{
          return originalFetch.call(this, new Request(rewritten, input), init);
        }}
      }}
    }}
    return originalFetch.call(this, input, init);
  }};
}})();
</script>
""".strip()


def _inject_generated_app_proxy_script(content: bytes, port: int) -> bytes:
    """Inject a fetch base-path shim into generated-app HTML served via Docker proxy."""
    script = _generated_app_fetch_proxy_script(port)
    html = content.decode("utf-8", errors="replace")
    lower = html.lower()
    head_index = lower.find("<head")
    if head_index >= 0:
        head_close = lower.find(">", head_index)
        if head_close >= 0:
            html = f"{html[:head_close + 1]}\n{script}\n{html[head_close + 1:]}"
            return html.encode("utf-8")
    html_index = lower.find("<html")
    if html_index >= 0:
        html_close = lower.find(">", html_index)
        if html_close >= 0:
            html = f"{html[:html_close + 1]}\n<head>{script}</head>\n{html[html_close + 1:]}"
            return html.encode("utf-8")
    return f"{script}\n{html}".encode()


def _write_assessment_report(session, results: list[dict[str, Any]]) -> None:
    if not session.last_export_path:
        return

    try:
        export_dir = session_export_dir(session)
    except PathResolutionError:
        return
    if export_dir is None:
        return
    report_path = export_dir / "assessment-report.json"
    payload = {
        "generated_by": "EdgeForge Studio",
        "app_name": session.app_name,
        "bounded_context": session.bounded_context,
        "assessed_at": datetime.now(timezone.utc).isoformat(),
        "source": "export/assess",
        "results": results,
    }
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


@router.get("", response_class=HTMLResponse)
async def step8_get(request: Request):
    session = get_current_session(request)
    settings = get_studio_settings()
    nav = build_nav_context(session, "/export")
    build_run = ensure_generated_app_path(session)
    build_run_data = status_payload(build_run) if build_run.generated_app_path else None
    save_current_session(request, session)
    report = build_completeness_report(session)
    display_session = _with_resolved_export_path_display(session)
    return templates.TemplateResponse(request, "step8_export.html", {
        "request": request,
        "session": display_session,
        "step": 8,
        "export_disabled": not report.is_exportable(),
        "export_blockers": [item.message for item in report.manual()],
        "build_run_enabled": settings.build_run_enabled and bool(build_run.generated_app_path),
        "build_run_data": build_run_data,
        "export_artifacts": _build_export_artifact_summary(session),
        "latest_revision": _latest_revision_checkpoint(session),
        "engine_repo_path": engine_repo_path(session, settings),
        "engine_repo_path_warning": _engine_repo_path_warning(session, settings),
        **nav,
    })


def _with_resolved_export_path_display(session: ProjectSession) -> ProjectSession:
    """A render-only view of *session* with last_export_path safe to display.

    step8_export.html renders ``session.last_export_path`` directly and is
    locked byte-identical to its PR-23 base (renderArtifactRows() in that
    file's own <script> mirrors the server-rendered markup character-for-
    character with no flag branch to gate a change with -- see build packet
    §B.1), so the fix cannot touch the template. A project restored from
    before output-path expansion carries a raw '~/...' there; displaying that
    literal tells the author nothing about where Studio actually reads/writes.

    Returns a SHALLOW COPY so this is purely a render-time view: the mutation
    never reaches the persisted session (the real save already happened, above,
    before this is called) or any other consumer of the original object.
    """
    if not session.last_export_path:
        return session
    try:
        export_dir = session_export_dir(session)
    except PathResolutionError:
        export_dir = None
    display = session.model_copy()
    display.last_export_path = str(export_dir) if export_dir else ""
    return display


def _exportability_error(session) -> JSONResponse | None:
    """Return a 400 JSONResponse listing blockers, or None if export is allowed."""
    report = build_completeness_report(session)
    if not report.is_exportable():
        blockers = [item.message for item in report.manual()]
        return JSONResponse(
            {
                "ok": False,
                "error": "Package has unresolved blockers and cannot be exported.",
                "blockers": blockers,
            },
            status_code=400,
        )
    return None


@router.post("/write", response_class=JSONResponse)
async def export_write(request: Request):
    """Write package to disk — blocked if completeness report has MANUAL_FOLLOW_UP items."""
    session = get_current_session(request)
    settings = get_studio_settings()

    # Guard: refuse to write a package EdgeForge Engine would reject
    if (err := _exportability_error(session)) is not None:
        audit(request, "export.write", outcome="blocked")
        return err
    # Resolve the output root before anything else consumes it: an unresolvable
    # '~unknownuser/...' Output Path is bad user input, not a server fault, so it
    # must render as a 400 rather than escaping as an HTTP 500.
    if (err := _unresolvable_output_path_response(session, settings)) is not None:
        audit(request, "export.write", outcome="blocked")
        return err
    if (err := _docker_output_path_response(session, settings)) is not None:
        audit(request, "export.write", outcome="blocked")
        return err
    try:
        ensure_session_disk_quota(session, settings=settings)
    except QuotaExceededError as exc:
        audit(request, "export.write", outcome="blocked")
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=413)

    root = session_output_root(session, settings)
    try:
        result = write_package_result(session, root)
        # Keep last_export_path aligned with package_writer's bounded-context-first
        # project folder resolution so validate/generate look in the right place.
        project_dir = result.project_dir
        session.last_export_path = str(project_dir)
        session.ks_workspace_state.manifest_revisions.append(
            KSManifestRevision(
                revision_id=result.evidence_trail.revision_id,
                exported_at=result.evidence_trail.exported_at,
                manifest_hash=result.evidence_trail.manifest_hash,
                archetype=session.app_archetype,
                target_profile=session.target_profile,
                export_path=str(project_dir),
            )
        )
        save_current_session(request, session)
        artifact_summary = _build_export_artifact_summary(session)
        latest_revision = _latest_revision_checkpoint(session)
        audit(request, "export.write", outcome="success")
        return JSONResponse({
            "ok": True,
            "output_dir": str(project_dir),
            "files": result.written,
            "revision_id": result.evidence_trail.revision_id,
            "manifest_hash": result.evidence_trail.manifest_hash,
            "warnings": result.warnings,
            "export_artifacts": artifact_summary,
            "latest_revision": latest_revision,
        })
    except EvidenceTrailError as exc:
        audit(request, "export.write", outcome="blocked")
        return JSONResponse(
            {
                "ok": False,
                "error": str(exc),
                "evidence_export_failed": True,
            },
            status_code=400,
        )
    except PackageWriteError as exc:
        audit(request, "export.write", outcome="blocked")
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    except Exception as exc:
        audit(request, "export.write", outcome="blocked")
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@router.get("/download-zip")
async def export_zip(request: Request):
    """Build package and stream as ZIP — blocked if completeness report has MANUAL_FOLLOW_UP items."""
    session = get_current_session(request)
    settings = get_studio_settings()
    if (err := _unresolvable_output_path_response(session, settings)) is not None:
        return err

    # Guard: refuse to produce a ZIP EdgeForge Engine would reject
    if (err := _exportability_error(session)) is not None:
        return err
    if (err := _docker_output_path_response(session, settings)) is not None:
        return err
    try:
        ensure_session_disk_quota(session, settings=settings)
    except QuotaExceededError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=413)

    root = session_output_root(session, settings)
    try:
        slug = _slug(session.bounded_context or session.app_name or "project")
        zip_path = export_zip_path(session, slug, settings)
        zip_bytes = build_zip(session, root)
    except EvidenceTrailError as exc:
        return JSONResponse(
            {
                "ok": False,
                "error": str(exc),
                "evidence_export_failed": True,
            },
            status_code=400,
        )
    except (PackageWriteError, PathResolutionError) as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    zip_path.write_bytes(zip_bytes)
    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename=f"{slug}-appbuilder-package.zip",
    )


@router.get("/artifact/{artifact_name}")
async def export_download_artifact(request: Request, artifact_name: str):
    session = get_current_session(request)
    if not session.last_export_path:
        raise HTTPException(status_code=404, detail="No exported package is available yet.")

    safe_name = Path(artifact_name).name
    allowed_names = {artifact["name"] for artifact in EXPORT_ARTIFACTS}
    if safe_name not in allowed_names:
        raise HTTPException(status_code=404, detail="Artifact not available.")

    try:
        export_dir = session_export_dir(session)
        artifact_path = contain_under_session_workspace(session, (export_dir or Path()) / safe_name)
    except PathResolutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not artifact_path.exists():
        raise HTTPException(status_code=404, detail="Artifact not available.")

    return FileResponse(
        path=str(artifact_path),
        filename=safe_name,
        media_type="application/octet-stream",
    )


@router.post("/validate", response_class=JSONResponse)
async def export_validate(request: Request):
    """Validate generated manifest against EdgeForge Engine."""
    session = get_current_session(request)
    settings = get_studio_settings()
    if not session.last_export_path:
        return JSONResponse({"ok": False, "error": "Export the package first."})
    if (err := _unresolvable_export_path_response(session)) is not None:
        return err
    manifest_path = session_export_dir(session) / "app-definition.yaml"
    if not manifest_path.exists():
        return JSONResponse({"ok": False, "error": "app-definition.yaml not found. Export first."})
    if engine_error := _engine_repo_path_error(session, settings):
        return JSONResponse({"ok": False, "errors": [engine_error], "summary": engine_error})
    repo_path = engine_repo_path(session, settings)
    try:
        result = validate_manifest(
            manifest_path,
            repo_path,
            allowed_roots=[str(manifest_path.parent)],
        )
    except OSError as exc:
        projection = project_engine_diagnostic(
            f"Manifest validation could not start: {exc}",
            success=False,
        )
        return JSONResponse({
            "ok": False,
            "message": projection.message,
            "warnings": projection.warnings,
            "errors": projection.errors,
            "summary": projection.summary,
            "diagnostic_id": projection.diagnostic_id,
        })
    projection = project_engine_result(result)
    return JSONResponse({
        "ok": result.success,
        "message": projection.message,
        "warnings": projection.warnings,
        "errors": projection.errors,
        "summary": projection.summary,
        "diagnostic_id": projection.diagnostic_id,
    })


@router.post("/assess", response_class=JSONResponse)
async def export_assess(request: Request):
    """Run appbuilder assess for OpenAPI-backed upstreams."""
    session = get_current_session(request)
    settings = get_studio_settings()
    url_ifaces = [i for i in session.upstream_interfaces if i.spec_url]
    if not url_ifaces:
        return JSONResponse({"ok": False, "error": "No spec_url upstreams to assess."})
    if (err := _unresolvable_export_path_response(session)) is not None:
        return err

    if engine_error := _engine_repo_path_error(session, settings):
        return JSONResponse({"ok": False, "error": engine_error, "errors": [engine_error]})

    results = []
    workspace_root = session_workspace_root(session, settings)
    workspace_root.mkdir(parents=True, exist_ok=True)
    try:
        with _engine_openapi_response_cache(
            [iface.spec_url for iface in url_ifaces],
            cache_parent=workspace_root,
            settings=settings,
        ) as cache_path:
            for iface in url_ifaces:
                res = run_assess(
                    iface.spec_url,
                    engine_repo_path(session, settings),
                    allowed_roots=[str(workspace_root)],
                    openapi_cache_path=str(cache_path),
                )
                projection = project_engine_result(res)
                results.append(
                    {
                        "interface": iface.name,
                        "ok": res.success,
                        "output": projection.message,
                        "warnings": projection.warnings,
                        "errors": projection.errors,
                        "summary": projection.summary,
                        "diagnostic_id": projection.diagnostic_id,
                    }
                )
    except OpenAPIFetchPolicyError as exc:
        return JSONResponse(
            {"ok": False, "error": str(exc), "errors": [str(exc)]},
            status_code=400,
        )
    _write_assessment_report(session, results)
    return JSONResponse({"ok": True, "results": results})


@router.post("/generate", response_class=JSONResponse)
async def export_generate(request: Request):
    """Run appbuilder generate (optional advanced action)."""
    session = get_current_session(request)
    settings = get_studio_settings()
    if not session.last_export_path:
        audit(request, "export.generate", outcome="blocked")
        return JSONResponse({"ok": False, "error": "Export the package first."})
    if (err := _unresolvable_export_path_response(session)) is not None:
        audit(request, "export.generate", outcome="blocked")
        return err
    if engine_error := _engine_repo_path_error(session, settings):
        audit(request, "export.generate", outcome="blocked")
        return JSONResponse({"ok": False, "errors": [engine_error], "summary": engine_error})
    export_dir = session_export_dir(session)
    manifest_path = contain_under_session_workspace(session, export_dir / "app-definition.yaml")
    try:
        gen_output = str(contain_under_session_workspace(session, export_dir / "generated-app"))
    except PathResolutionError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    try:
        with _engine_openapi_response_cache(
            _manifest_openapi_urls(manifest_path),
            cache_parent=manifest_path.parent,
            settings=settings,
        ) as cache_path:
            with acquire_generation_lock(gen_output) as acquired:
                if not acquired:
                    message = "Generation is already in progress for this output path."
                    audit(request, "export.generate", outcome="blocked")
                    return JSONResponse(
                        {
                            "ok": False,
                            "error": message,
                            "errors": [message],
                            "summary": message,
                            "output_dir": gen_output,
                        },
                        status_code=409,
                    )
                res = run_generate(
                    str(manifest_path),
                    gen_output,
                    engine_repo_path(session, settings),
                    openapi_cache_path=str(cache_path) if cache_path else None,
                )
    except OpenAPIFetchPolicyError as exc:
        audit(request, "export.generate", outcome="blocked")
        return JSONResponse(
            {"ok": False, "error": str(exc), "errors": [str(exc)], "summary": str(exc)},
            status_code=400,
        )
    projection = project_engine_result(res)
    warnings = list(projection.warnings)
    regen_preview_status = None
    if res.success:
        stop_generated_app(session.build_run)
        session.build_run.generated_app_path = gen_output
        session.build_run.build_status = "idle"
        session.build_run.run_status = "idle"
        session.build_run.build_log_path = None
        session.build_run.run_log_path = None
        session.build_run.build_summary = None
        session.build_run.run_summary = None
        session.build_run.jar_path = None
        session.build_run.pid = None
        session.build_run.app_url = None
        session.build_run.health_url = None
        session.build_run.route_summary = []
        if settings.regen_preview_enabled:
            try:
                capture_result = capture_generated_package(
                    session,
                    generated_package_path=gen_output,
                    manifest_path=manifest_path,
                    settings=settings,
                )
                regen_preview_status = capture_result.status
            except RegenBindingError as exc:
                warnings.append(f"Regen-preview binding was not captured: {exc}")
                regen_preview_status = regen_status(session, settings=settings)
        save_current_session(request, session)
    audit(request, "export.generate", outcome="success" if res.success else "blocked")
    payload = {
        "ok": res.success,
        "message": projection.message,
        "warnings": warnings,
        "errors": projection.errors,
        "summary": projection.summary,
        "diagnostic_id": projection.diagnostic_id,
        "output_dir": gen_output,
    }
    if settings.regen_preview_enabled:
        payload["regen_status"] = regen_preview_status or regen_status(session, settings=settings)
    return JSONResponse(payload)


@router.post("/build", response_class=JSONResponse)
async def export_build(request: Request):
    session = get_current_session(request)
    settings = get_studio_settings()
    if (err := _build_run_disabled_response(settings)) is not None:
        audit(request, "export.build", outcome="blocked")
        return err

    build_run = ensure_generated_app_path(session)
    if not build_run.generated_app_path:
        audit(request, "export.build", outcome="blocked")
        return JSONResponse({"ok": False, "error": "Generate the app first."}, status_code=400)

    build_run.build_status = "building"
    build_run.build_summary = "Build in progress."
    save_current_session(request, session)

    result = build_generated_app(build_run.generated_app_path)
    build_run.build_log_path = result.log_path or None
    build_run.build_summary = result.summary
    build_run.build_status = "build_succeeded" if result.success else "build_failed"
    build_run.jar_path = result.jar_path
    build_run.route_summary = result.route_summary or []
    save_current_session(request, session)

    status = status_payload(build_run)
    status.update({
        "ok": result.success,
        "message": result.output,
        "summary": result.summary,
        "command": result.command,
    })
    audit(request, "export.build", outcome="success" if result.success else "blocked")
    return JSONResponse(status, status_code=200 if result.success else 500)


@router.post("/run", response_class=JSONResponse)
async def export_run(request: Request):
    session = get_current_session(request)
    settings = get_studio_settings()
    if (err := _build_run_disabled_response(settings)) is not None:
        audit(request, "export.run", outcome="blocked")
        return err

    build_run = ensure_generated_app_path(session)
    if not build_run.generated_app_path:
        audit(request, "export.run", outcome="blocked")
        return JSONResponse({"ok": False, "error": "Generate the app first."}, status_code=400)
    if build_run.build_status != "build_succeeded" or not build_run.jar_path:
        audit(request, "export.run", outcome="blocked")
        return JSONResponse({"ok": False, "error": "Build the app successfully first."}, status_code=400)

    result = start_generated_app(build_run)
    save_current_session(request, session)
    status = status_payload(build_run)
    status.update({"ok": result.success, "summary": result.summary})
    audit(request, "export.run", outcome="success" if result.success else "blocked")
    return JSONResponse(status, status_code=200 if result.success else 400)


@router.get("/run-status", response_class=JSONResponse)
async def export_run_status(request: Request):
    session = get_current_session(request)
    build_run = ensure_generated_app_path(session)
    save_current_session(request, session)
    return JSONResponse({
        "ok": bool(build_run.generated_app_path),
        **(status_payload(build_run) if build_run.generated_app_path else {}),
    })


@router.post("/stop", response_class=JSONResponse)
async def export_stop(request: Request):
    session = get_current_session(request)
    build_run = session.build_run
    stop_generated_app(build_run)
    save_current_session(request, session)
    return JSONResponse({"ok": True, **status_payload(build_run)})


@router.api_route(
    "/generated-app/{port}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
@router.api_route(
    "/generated-app/{port}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def generated_app_proxy(request: Request, port: int, path: str = ""):
    """Proxy the Studio-managed generated app through the published Studio port in Docker."""
    if not is_docker_runtime():
        raise HTTPException(status_code=404, detail="Generated app proxy is only available in Docker Studio.")

    session = get_current_session(request)
    build_run = session.build_run
    if (
        build_run.port != port
        or build_run.run_status not in {"starting", "running"}
        or not build_run.pid
    ):
        raise HTTPException(status_code=404, detail="No managed generated app is running on this port.")

    target_path = f"/{path.lstrip('/')}" if path else "/"
    target_url = f"http://127.0.0.1:{port}{target_path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    excluded_headers = {"host", "connection", "content-length", "accept-encoding"}
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in excluded_headers
    }
    headers["accept-encoding"] = "identity"
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            proxied = await client.request(
                request.method,
                target_url,
                content=await request.body(),
                headers=headers,
            )
    except httpx.HTTPError as exc:
        return JSONResponse(
            {"ok": False, "error": f"Generated app is not reachable inside Docker Studio: {exc}"},
            status_code=502,
        )

    proxied_content = proxied.content
    proxied_headers = dict(proxied.headers)
    if _is_html_response(proxied_headers):
        proxied_content = _inject_generated_app_proxy_script(proxied_content, port)

    response_headers = {
        key: value
        for key, value in proxied_headers.items()
        if key.lower() not in {"content-encoding", "content-length", "transfer-encoding", "connection"}
    }
    return Response(
        content=proxied_content,
        status_code=proxied.status_code,
        headers=response_headers,
        media_type=proxied_headers.get("content-type"),
    )


@router.post("/reset", response_class=JSONResponse)
async def reset(request: Request):
    session = get_current_session(request)
    stop_generated_app(session.build_run)
    reset_current_session(request)
    return JSONResponse({"ok": True})
