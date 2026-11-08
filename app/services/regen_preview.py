"""Read-only regeneration preview view-models.

Studio renders the Engine Change Plan; it does not compute deltas or migration
classification.  This service resolves the Slice 1 managed baseline binding,
calls the Engine plan CLI, gates consumer compatibility, and shapes the payload
for templates.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.integrations.appbuilder_integration import run_apply, run_change_plan
from app.models.project import ProjectSession
from app.services.diagnostics import (
    diagnostic_id_for,
    project_engine_diagnostic,
    project_engine_result,
    sanitize_diagnostic_text,
)
from app.services.path_resolver import (
    PathResolutionError,
    contain_under_session_workspace,
    engine_repo_path,
    preflight_engine_package,
    session_export_dir,
    session_workspace_root,
)
from app.services.regen_apply_locks import acquire_regen_apply_lock
from app.services.regen_binding import (
    RegenBindingError,
    _current_manifest_path,
    _resolve_under_workspace,
    capture_generated_package,
    regen_status,
)
from app.services.settings import StudioSettings, get_studio_settings

CHANGE_PLAN_SUPPORTED_MAJOR = 1


def build_regen_preview(
    session: ProjectSession,
    settings: StudioSettings | None = None,
) -> dict[str, Any]:
    """Build the read-only regeneration preview state for the current session."""

    settings = settings or get_studio_settings()
    if not settings.regen_preview_enabled:
        return {
            "state": "disabled",
            "status": "none",
            "message": "Regeneration preview is disabled.",
        }

    # Check before status hashing as well as before plan/apply child invocation.
    try:
        _preflight_regen_packages(session, settings)
    except PathResolutionError as exc:
        return {"state": "error", "status": "none", "message": str(exc)}

    status = regen_status(session, settings=settings)
    if status == "none":
        return {
            "state": "empty",
            "status": status,
            "message": "Nothing to compare yet. Export and generate once to create a managed baseline.",
        }
    if status == "manifest-only":
        return {
            "state": "manifest-only",
            "status": status,
            "message": (
                "A previous generated package was captured without db/schema-baseline.json. "
                "Studio can show a manifest-only preview later, but DB migration deltas require "
                "a generated baseline. Export and generate with a baseline-capable Engine first."
            ),
        }

    try:
        manifest_path, package_dir, scratch_dir, roots = _resolve_plan_paths(session, settings)
    except RegenBindingError as exc:
        return {
            "state": "error",
            "status": status,
            "message": str(exc),
        }

    result = run_change_plan(
        manifest_path,
        package_dir,
        engine_repo_path(session, settings),
        allowed_roots=roots,
    )
    if not result.success or result.change_plan is None:
        projection = project_engine_diagnostic(
            result.error or result.subprocess.combined_output,
            success=False,
            diagnostic_id=diagnostic_id_for(result.subprocess),
        )
        return {
            "state": "error",
            "status": status,
            "message": projection.summary or "Engine Change Plan failed.",
            "engine_output": projection.message,
            "diagnostic_id": projection.diagnostic_id,
        }

    try:
        _assert_supported_change_plan(result.change_plan)
    except ValueError as exc:
        return {
            "state": "unsupported",
            "status": status,
            "message": str(exc),
        }

    return _view_model_from_plan(
        result.change_plan,
        status=status,
        manifest_path=manifest_path,
        package_dir=package_dir,
        scratch_dir=scratch_dir,
    )


def apply_regen_plan(
    session: ProjectSession,
    settings: StudioSettings | None = None,
    *,
    approved_plan_hash: str,
) -> dict[str, Any]:
    """Apply an approved additive Engine Change Plan and refresh the managed baseline."""

    settings = settings or get_studio_settings()
    if not settings.regen_preview_enabled:
        return {
            "state": "disabled",
            "message": "Regeneration preview is disabled.",
        }

    approved_hash = str(approved_plan_hash or "").strip()
    lock_target = _apply_lock_target(session, settings)
    with acquire_regen_apply_lock(lock_target) as acquired:
        if not acquired:
            return {
                "state": "busy",
                "message": "Regeneration apply is already in progress for this managed package.",
                "approved_plan_hash": approved_hash,
            }

        preview = build_regen_preview(session, settings)
        fresh_hash = str(preview.get("plan_hash") or "").strip()
        if preview.get("state") != "ready" or not approved_hash or fresh_hash != approved_hash:
            return {
                "state": "drift",
                "message": (
                    "The Change Plan changed or is no longer ready. "
                    "Review the latest plan before applying."
                ),
                "approved_plan_hash": approved_hash,
                "fresh_plan_hash": fresh_hash or None,
                "preview": preview,
            }

        blocked_items = _non_additive_items(preview.get("plan"))
        if blocked_items:
            return {
                "state": "blocked",
                "message": (
                    "Studio only applies additive Change Plans. "
                    "Resolve destructive, unsafe, or unclassified changes before applying."
                ),
                "approved_plan_hash": approved_hash,
                "plan_hash": fresh_hash,
                "blocked_items": blocked_items,
                "preview": preview,
            }

        try:
            manifest_path, package_dir, _scratch_dir, _roots = _resolve_plan_paths(session, settings)
        except RegenBindingError as exc:
            return {
                "state": "drift",
                "message": str(exc),
                "approved_plan_hash": approved_hash,
                "fresh_plan_hash": fresh_hash,
                "preview": preview,
            }

        apply_result = run_apply(
            manifest_path,
            package_dir,
            engine_repo_path(session, settings),
            approved_plan_hash=fresh_hash,
            allowed_roots=[str(manifest_path.parent), str(package_dir)],
        )
        if not apply_result.success:
            projection = project_engine_diagnostic(
                apply_result.error or apply_result.subprocess.combined_output,
                success=False,
                diagnostic_id=diagnostic_id_for(apply_result.subprocess),
            )
            return {
                "state": "error",
                "message": projection.summary or "Engine apply failed.",
                "engine_output": projection.message,
                "diagnostic_id": projection.diagnostic_id,
                "approved_plan_hash": approved_hash,
                "plan_hash": fresh_hash,
                "preview": preview,
            }

        try:
            capture_result = capture_generated_package(
                session,
                generated_package_path=package_dir,
                manifest_path=manifest_path,
                settings=settings,
            )
        except RegenBindingError as exc:
            projection = project_engine_result(apply_result.subprocess)
            return {
                "state": "error",
                "message": sanitize_diagnostic_text(
                    "Engine apply succeeded, but Studio could not refresh the managed baseline: "
                    f"{exc}"
                ),
                "engine_output": projection.message,
                "diagnostic_id": projection.diagnostic_id,
                "approved_plan_hash": approved_hash,
                "plan_hash": fresh_hash,
                "preview": preview,
            }

        projection = project_engine_result(apply_result.subprocess)
        return {
            "state": "applied",
            "message": "Additive Change Plan applied and managed baseline refreshed.",
            "approved_plan_hash": approved_hash,
            "plan_hash": fresh_hash,
            "engine_output": projection.message,
            "diagnostic_id": projection.diagnostic_id,
            "summary": {
                "generation_run_id": capture_result.generation_run_id,
                "managed_package_ref": capture_result.managed_package_ref,
                "manifest_hash": capture_result.manifest_hash,
                "baseline_hash": capture_result.baseline_hash,
                "baseline_present": capture_result.baseline_present,
                "status": capture_result.status,
            },
        }


def _resolve_plan_paths(
    session: ProjectSession,
    settings: StudioSettings,
) -> tuple[Path, Path, Path, list[str]]:
    try:
        _preflight_regen_packages(session, settings)
    except PathResolutionError as exc:
        raise RegenBindingError(str(exc)) from exc
    workspace_root = session_workspace_root(session, settings)
    manifest_path = _current_manifest_path(session)
    if manifest_path is None:
        raise RegenBindingError("Current manifest path is not available. Export the package first.")
    manifest = _resolve_under_workspace(
        workspace_root,
        manifest_path,
        "Current manifest path is outside the session workspace.",
    )
    package_dir = _resolve_under_workspace(
        workspace_root,
        workspace_root / str(session.last_generated_package_ref or ""),
        "Managed package reference is outside the session workspace.",
    )
    if not manifest.is_file():
        raise RegenBindingError("Current app-definition.yaml was not found. Export the package first.")
    if not package_dir.is_dir():
        raise RegenBindingError("Managed generated package was not found. Generate the app first.")

    scratch_dir = _resolve_under_workspace(
        workspace_root,
        workspace_root / "regen-preview",
        "Change Plan scratch path is outside the session workspace.",
    )
    scratch_dir.mkdir(parents=True, exist_ok=True)
    roots = [
        str(manifest.parent),
        str(package_dir),
        str(scratch_dir),
    ]
    return manifest, package_dir, scratch_dir, roots


def _preflight_regen_packages(session: ProjectSession, settings: StudioSettings) -> None:
    if not settings.shared_mode:
        return
    export = session_export_dir(session, settings)
    if export is not None:
        preflight_engine_package(export, settings)
    if session.last_generated_package_ref:
        package = session_workspace_root(session, settings) / session.last_generated_package_ref
        contain_under_session_workspace(session, package, settings)
        preflight_engine_package(package, settings)


def _apply_lock_target(session: ProjectSession, settings: StudioSettings) -> Path:
    workspace_root = session_workspace_root(session, settings)
    if session.last_generated_package_ref:
        try:
            return _resolve_under_workspace(
                workspace_root,
                workspace_root / session.last_generated_package_ref,
                "Managed package reference is outside the session workspace.",
            )
        except RegenBindingError:
            pass
    return workspace_root / f".regen-apply-{session.session_id or 'session'}"


def _assert_supported_change_plan(plan: dict[str, Any]) -> None:
    raw_version = str(plan.get("change_plan_schema_version") or "").strip()
    if not raw_version:
        raise ValueError("Unsupported Change Plan version: missing change_plan_schema_version.")
    try:
        major = int(raw_version.split(".", 1)[0])
    except ValueError as exc:
        raise ValueError(f"Unsupported Change Plan version: {raw_version}.") from exc
    if major != CHANGE_PLAN_SUPPORTED_MAJOR:
        raise ValueError(
            "Unsupported Change Plan version: "
            f"{raw_version}. Studio supports major version {CHANGE_PLAN_SUPPORTED_MAJOR}.x."
        )


def _view_model_from_plan(
    plan: dict[str, Any],
    *,
    status: str,
    manifest_path: Path,
    package_dir: Path,
    scratch_dir: Path,
) -> dict[str, Any]:
    groups = [
        *_manifest_delta_groups(plan.get("deltas")),
        _group("DB migration deltas", plan.get("db_migration_deltas")),
        _group(
            "Edge-contract impact",
            plan.get("edge_contract_impact"),
        ),
    ]
    return {
        "state": "ready",
        "status": status,
        "message": "Engine Change Plan loaded. Review only; apply is not available in this slice.",
        "plan": plan,
        "raw_plan_json": _plan_json(plan),
        "schema_version": plan.get("change_plan_schema_version"),
        "engine_version": plan.get("engine_version"),
        "plan_id": plan.get("plan_id"),
        "plan_hash": plan.get("plan_hash"),
        "package_state_hash": plan.get("package_state_hash"),
        "manifest_hash": plan.get("manifest_hash"),
        "baseline_hash": plan.get("baseline_hash"),
        "groups": [group for group in groups if group["items"]],
        "is_additive_only": not _non_additive_items(plan),
        "non_additive_items": _non_additive_items(plan),
        "required_manual_actions": _as_list(plan.get("required_manual_actions")),
        "warnings": _as_list(plan.get("warnings")),
        "manifest_path": str(manifest_path),
        "package_dir": str(package_dir),
        "scratch_dir": str(scratch_dir),
    }


def _manifest_delta_groups(raw_items: Any) -> list[dict[str, Any]]:
    grouped: dict[str, list[Any]] = {}
    for raw in _as_list(raw_items):
        kind = "manifest"
        if isinstance(raw, dict):
            kind = str(raw.get("kind") or "manifest").strip().lower() or "manifest"
        grouped.setdefault(kind, []).append(raw)
    return [
        _group(f"Manifest deltas - {_delta_kind_label(kind)}", items)
        for kind, items in grouped.items()
    ]


def _delta_kind_label(kind: str) -> str:
    return kind.replace("_", " ").replace("-", " ").title()


def _group(label: str, raw_items: Any) -> dict[str, Any]:
    items = [_item(raw) for raw in _as_list(raw_items)]
    return {"label": label, "items": items}


def _item(raw: Any) -> dict[str, Any]:
    payload = raw if isinstance(raw, dict) else {"value": raw}
    classification = _classification(payload)
    return {
        "title": _title(payload),
        "classification": classification,
        "payload": payload,
        "payload_json": _plan_json(payload),
        "is_gated": classification in {"unsafe", "destructive"},
    }


def _non_additive_items(plan: Any) -> list[dict[str, Any]]:
    if not isinstance(plan, dict):
        return [{"title": "Change Plan", "classification": "unclassified"}]
    blocked: list[dict[str, Any]] = []
    for raw in _plan_change_items(plan):
        item = _item(raw)
        if item["classification"] != "additive":
            blocked.append(
                {
                    "title": item["title"],
                    "classification": item["classification"],
                    "payload": item["payload"],
                }
            )
    return blocked


def _plan_change_items(plan: dict[str, Any]) -> list[Any]:
    items: list[Any] = []
    items.extend(_flatten_plan_items(plan.get("deltas")))
    items.extend(_as_list(plan.get("db_migration_deltas")))
    items.extend(_as_list(plan.get("edge_contract_impact")))
    return items


def _flatten_plan_items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        flattened: list[Any] = []
        for item in value.values():
            flattened.extend(_flatten_plan_items(item))
        return flattened
    return _as_list(value)


def _classification(payload: dict[str, Any]) -> str:
    for key in (
        "migration_classification",
        "classification",
        "safety",
        "change_type",
        "impact",
    ):
        value = str(payload.get(key) or "").strip().lower()
        if value in {"additive", "unsafe", "destructive"}:
            return value
    return "unclassified"


def _title(payload: dict[str, Any]) -> str:
    for key in (
        "title",
        "name",
        "entity",
        "field",
        "contract",
        "path",
        "target_path",
        "source_path",
        "operation",
        "id",
        "description",
        "summary",
    ):
        value = payload.get(key)
        if value:
            return str(value)
    return "Change"


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return [value]


def _plan_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True)
