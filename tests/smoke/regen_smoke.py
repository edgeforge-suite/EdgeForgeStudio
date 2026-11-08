from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from app.integrations.appbuilder_integration import _engine_subprocess_env
from app.services.regen_binding import regen_status
from app.services.regen_preview import apply_regen_plan, build_regen_preview
from app.services.retention import DURABLE_SUBDIR
from app.services.settings import get_studio_settings
from tests.smoke._shared import (
    assert_no_ka_noise,
    assert_path_under,
    export_package,
    make_exportable_smoke_session,
    new_shared_client,
    post_step1,
    save_session_for_client,
    session_for_client,
)
from tests.smoke.l4_driver import _ka_off_spy, _post_generate, _shared_mode_environment


def run_studio_regen_plan_smoke(*, root: Path) -> dict[str, Any]:
    """Capture a real Studio managed baseline, then run Engine ``appbuilder plan``.

    This intentionally exercises Slice-1's shared-mode generate/capture path
    through Studio, then invokes Slice-2's intended Engine surface as a direct
    CLI subprocess.  No MCP tool is used for ``plan``.
    """

    with _shared_mode_environment(root), _regen_preview_flag(), _ka_off_spy() as ks_calls:
        client, csrf = new_shared_client()
        post_step1(
            client,
            csrf,
            app_name="Regen Plan Smoke App",
            bounded_context="regen-plan-smoke",
            output_path=root / "ignored-user-output",
        )

        session = session_for_client(client)
        workspace_root = Path(session.workspace_root or "")
        make_exportable_smoke_session(
            session,
            entity_name="PlanRecord",
            contract_name="plan-record",
        )
        save_session_for_client(client, session)

        export_payload = export_package(client, csrf)
        manifest = Path(export_payload["output_dir"]) / "app-definition.yaml"
        assert manifest.is_file()
        assert_path_under(manifest, workspace_root)

        generate_payload = _post_generate(client, csrf)
        assert_no_ka_noise(generate_payload)
        assert generate_payload.get("regen_status") in {"none", "regenerate-ready"}

        session = session_for_client(client)
        assert session.generation_run_id
        assert session.last_generated_package_ref
        assert session.manifest_hash
        assert session.baseline_hash

        managed_package = workspace_root / session.last_generated_package_ref
        managed_run_root = workspace_root / DURABLE_SUBDIR / session.generation_run_id
        baseline = managed_package / "db" / "schema-baseline.json"
        assert managed_run_root.is_dir()
        assert managed_package.is_dir()
        assert baseline.is_file()
        assert_path_under(managed_package, workspace_root / DURABLE_SUBDIR)

        engine_repo = _engine_repo_from_env()
        plan_dir = workspace_root / "regen-plan"
        initial_plan_result = _run_appbuilder_plan(
            manifest=manifest,
            package=managed_package,
            out_dir=plan_dir,
            engine_repo=engine_repo,
        )
        initial_plan = _assert_contract_valid_change_plan(initial_plan_result["change_plan"])

        mutated_manifest = _add_optional_manifest_field(manifest)
        changed_plan_result = _run_appbuilder_plan(
            manifest=mutated_manifest,
            package=managed_package,
            out_dir=plan_dir,
            engine_repo=engine_repo,
        )
        changed_plan = _assert_contract_valid_change_plan(changed_plan_result["change_plan"])

        hash_sensitivity = {
            "plan_hash_changed": changed_plan["plan_hash"] != initial_plan["plan_hash"],
            "added_delta_present": _has_added_delta(changed_plan),
        }

        return {
            "ok": (
                ks_calls == []
                and initial_plan_result["returncode"] == 0
                and changed_plan_result["returncode"] == 0
                and hash_sensitivity["plan_hash_changed"]
                and hash_sensitivity["added_delta_present"]
            ),
            "ka_off_silent": ks_calls == [],
            "ks_calls": list(ks_calls),
            "workspace_root": str(workspace_root),
            "export_dir": export_payload["output_dir"],
            "manifest": str(manifest),
            "mutated_manifest": str(mutated_manifest),
            "generated_output": generate_payload["output_dir"],
            "managed_run_root": str(managed_run_root),
            "managed_package": str(managed_package),
            "schema_baseline": str(baseline),
            "regen_status": regen_status(session),
            "engine_repo": str(engine_repo),
            "initial_plan": _plan_summary(initial_plan),
            "changed_plan": _plan_summary(changed_plan),
            "hash_sensitivity": hash_sensitivity,
            "initial_command": initial_plan_result["command"],
            "changed_command": changed_plan_result["command"],
        }


def run_studio_regen_apply_smoke(*, root: Path) -> dict[str, Any]:
    """Prove Engine ``appbuilder apply`` against Studio-managed baselines.

    The flow mirrors :func:`run_studio_regen_plan_smoke`: Studio captures a real
    shared-mode generated baseline first, then this driver invokes Engine's apply
    CLI directly.  No Studio apply UI/path is involved.
    """

    with _shared_mode_environment(root), _regen_preview_flag(), _ka_off_spy() as ks_calls:
        engine_repo = _engine_repo_from_env()
        additive = _run_additive_apply_scenario(
            root=root / "additive",
            engine_repo=engine_repo,
        )
        drift = _run_drift_apply_scenario(
            root=root / "drift",
            engine_repo=engine_repo,
        )
        destructive = _run_destructive_apply_scenario(
            root=root / "destructive",
            engine_repo=engine_repo,
        )
        studio_wrapper = _run_studio_wrapper_apply_scenario(
            root=root / "studio-wrapper",
        )

        ok = (
            ks_calls == []
            and additive["succeeded"]
            and drift["failed_closed"]
            and destructive["failed_closed"]
            and studio_wrapper["succeeded"]
            and studio_wrapper["drift"]["state"] == "drift"
            and studio_wrapper["destructive"]["state"] == "blocked"
        )
        return {
            "ok": ok,
            "ka_off_silent": ks_calls == [],
            "ks_calls": list(ks_calls),
            "engine_repo": str(engine_repo),
            "additive": additive,
            "drift": drift,
            "destructive": destructive,
            "studio_wrapper": studio_wrapper,
            "developer_file_preservation": {
                "skipped": True,
                "reason": "The core apply contract guarantees were covered; dev-owned file preservation is optional for this smoke.",
            },
        }


def _capture_studio_managed_baseline(
    *,
    root: Path,
    app_name: str,
    bounded_context: str,
) -> dict[str, Any]:
    client, csrf = new_shared_client()
    post_step1(
        client,
        csrf,
        app_name=app_name,
        bounded_context=bounded_context,
        output_path=root / "ignored-user-output",
    )

    session = session_for_client(client)
    workspace_root = Path(session.workspace_root or "")
    make_exportable_smoke_session(
        session,
        entity_name="PlanRecord",
        contract_name="plan-record",
    )
    save_session_for_client(client, session)

    export_payload = export_package(client, csrf)
    manifest = Path(export_payload["output_dir"]) / "app-definition.yaml"
    assert manifest.is_file()
    assert_path_under(manifest, workspace_root)

    generate_payload = _post_generate(client, csrf)
    assert_no_ka_noise(generate_payload)
    assert generate_payload.get("regen_status") in {"none", "regenerate-ready"}

    session = session_for_client(client)
    assert session.generation_run_id
    assert session.last_generated_package_ref
    assert session.manifest_hash
    assert session.baseline_hash

    managed_package = workspace_root / session.last_generated_package_ref
    managed_run_root = workspace_root / DURABLE_SUBDIR / session.generation_run_id
    baseline = managed_package / "db" / "schema-baseline.json"
    assert managed_run_root.is_dir()
    assert managed_package.is_dir()
    assert baseline.is_file()
    assert_path_under(managed_package, workspace_root / DURABLE_SUBDIR)

    return {
        "client": client,
        "csrf": csrf,
        "session": session,
        "workspace_root": workspace_root,
        "export_payload": export_payload,
        "manifest": manifest,
        "generate_payload": generate_payload,
        "managed_run_root": managed_run_root,
        "managed_package": managed_package,
        "schema_baseline": baseline,
        "regen_status": regen_status(session),
    }


def _run_studio_wrapper_apply_scenario(*, root: Path) -> dict[str, Any]:
    captured = _capture_studio_managed_baseline(
        root=root / "additive",
        app_name="Regen Apply Studio Wrapper Smoke App",
        bounded_context="regen-apply-studio-wrapper-smoke",
    )
    session = captured["session"]
    workspace_root = captured["workspace_root"]
    manifest = captured["manifest"]
    old_run_id = session.generation_run_id
    old_package = captured["managed_package"]
    before_migrations = _migration_files(old_package)

    _add_response_only_optional_manifest_field(
        manifest,
        field_name="regenSmokeStudioApplyNote",
    )
    _mark_manifest_changed(manifest, marker="regen-smoke-studio-wrapper-additive")
    settings = get_studio_settings()
    preview = build_regen_preview(session, settings)
    assert preview["state"] == "ready", preview
    assert preview["is_additive_only"] is True, preview
    drift = apply_regen_plan(
        session,
        settings,
        approved_plan_hash="stale-studio-wrapper-hash",
    )
    apply_result = apply_regen_plan(
        session,
        settings,
        approved_plan_hash=preview["plan_hash"],
    )
    save_session_for_client(captured["client"], session)

    refreshed_package = workspace_root / session.last_generated_package_ref
    after_migrations = _migration_files(refreshed_package)
    old_migration_names = {path.name for path in before_migrations}
    new_migrations = [path for path in after_migrations if path.name not in old_migration_names]
    migration_contains_field = any(
        "regen_smoke_studio_apply_note" in path.read_text(encoding="utf-8").lower()
        for path in new_migrations
    )

    destructive_captured = _capture_studio_managed_baseline(
        root=root / "destructive",
        app_name="Regen Apply Studio Wrapper Blocked Smoke App",
        bounded_context="regen-apply-studio-wrapper-blocked-smoke",
    )
    destructive_session = destructive_captured["session"]
    _remove_manifest_field(destructive_captured["manifest"], field_name="status")
    _mark_manifest_changed(
        destructive_captured["manifest"],
        marker="regen-smoke-studio-wrapper-destructive",
    )
    destructive_preview = build_regen_preview(destructive_session, settings)
    assert destructive_preview["state"] == "ready", destructive_preview
    destructive = apply_regen_plan(
        destructive_session,
        settings,
        approved_plan_hash=destructive_preview["plan_hash"],
    )

    return {
        "succeeded": (
            drift["state"] == "drift"
            and apply_result["state"] == "applied"
            and session.generation_run_id != old_run_id
            and bool(new_migrations)
            and migration_contains_field
            and destructive["state"] == "blocked"
        ),
        "workspace_root": str(workspace_root),
        "manifest": str(manifest),
        "old_managed_package": str(old_package),
        "refreshed_package": str(refreshed_package),
        "old_generation_run_id": old_run_id,
        "new_generation_run_id": session.generation_run_id,
        "preview_plan_hash": preview["plan_hash"],
        "drift": {
            "state": drift["state"],
            "fresh_plan_hash": drift.get("fresh_plan_hash"),
        },
        "apply": {
            "state": apply_result["state"],
            "summary": apply_result.get("summary"),
            "engine_output": apply_result.get("engine_output"),
        },
        "new_migrations": [str(path) for path in new_migrations],
        "migration_contains_field": migration_contains_field,
        "destructive": {
            "state": destructive["state"],
            "blocked_count": len(destructive.get("blocked_items") or []),
            "plan_hash": destructive_preview["plan_hash"],
        },
    }


def _run_additive_apply_scenario(*, root: Path, engine_repo: Path) -> dict[str, Any]:
    captured = _capture_studio_managed_baseline(
        root=root,
        app_name="Regen Apply Additive Smoke App",
        bounded_context="regen-apply-additive-smoke",
    )
    manifest = captured["manifest"]
    managed_package = captured["managed_package"]
    plan_dir = captured["workspace_root"] / "regen-apply-plan"
    before_migrations = _migration_files(managed_package)

    _add_response_only_optional_manifest_field(manifest, field_name="regenSmokeApplyNote")
    plan_result = _run_appbuilder_plan(
        manifest=manifest,
        package=managed_package,
        out_dir=plan_dir,
        engine_repo=engine_repo,
    )
    plan = _assert_contract_valid_change_plan(plan_result["change_plan"])
    assert _has_field_delta(
        plan,
        field_name="regenSmokeApplyNote",
        change="added",
        classification="additive",
    ), _plan_summary(plan)

    apply_result = _run_appbuilder_apply(
        manifest=manifest,
        package=managed_package,
        approved_plan_hash=plan["plan_hash"],
        engine_repo=engine_repo,
    )
    after_migrations = _migration_files(managed_package)
    new_migrations = [
        path for path in after_migrations if path.name not in {item.name for item in before_migrations}
    ]
    migration_contains_field = any(
        "regen_smoke_apply_note" in path.read_text(encoding="utf-8").lower()
        for path in new_migrations
    )
    summary_mentions_hash = plan["plan_hash"] in apply_result["combined_output"]

    return {
        "succeeded": (
            apply_result["returncode"] == 0
            and bool(new_migrations)
            and migration_contains_field
            and summary_mentions_hash
        ),
        "workspace_root": str(captured["workspace_root"]),
        "manifest": str(manifest),
        "managed_package": str(managed_package),
        "schema_baseline": str(captured["schema_baseline"]),
        "plan": _plan_summary(plan),
        "plan_hash": plan["plan_hash"],
        "plan_command": plan_result["command"],
        "apply_command": apply_result["command"],
        "apply_returncode": apply_result["returncode"],
        "apply_output": apply_result["combined_output"],
        "new_migrations": [str(path) for path in new_migrations],
        "migration_contains_field": migration_contains_field,
        "summary_mentions_hash": summary_mentions_hash,
    }


def _run_drift_apply_scenario(*, root: Path, engine_repo: Path) -> dict[str, Any]:
    captured = _capture_studio_managed_baseline(
        root=root,
        app_name="Regen Apply Drift Smoke App",
        bounded_context="regen-apply-drift-smoke",
    )
    manifest = captured["manifest"]
    managed_package = captured["managed_package"]
    plan_dir = captured["workspace_root"] / "regen-apply-plan"

    _add_response_only_optional_manifest_field(manifest, field_name="regenSmokeApplyNote")
    approved_plan_result = _run_appbuilder_plan(
        manifest=manifest,
        package=managed_package,
        out_dir=plan_dir,
        engine_repo=engine_repo,
    )
    approved_plan = _assert_contract_valid_change_plan(approved_plan_result["change_plan"])
    before_fingerprint = _package_fingerprint(managed_package)

    _add_response_only_optional_manifest_field(manifest, field_name="regenSmokeDriftNote")
    apply_result = _run_appbuilder_apply(
        manifest=manifest,
        package=managed_package,
        approved_plan_hash=approved_plan["plan_hash"],
        engine_repo=engine_repo,
    )
    after_fingerprint = _package_fingerprint(managed_package)
    output = apply_result["combined_output"].lower()
    drift_message = (
        "hash" in output
        and (
            "mismatch" in output
            or "does not match" in output
            or "re-run appbuilder plan" in output
        )
    )

    return {
        "failed_closed": (
            apply_result["returncode"] != 0
            and drift_message
            and before_fingerprint == after_fingerprint
        ),
        "workspace_root": str(captured["workspace_root"]),
        "manifest": str(manifest),
        "managed_package": str(managed_package),
        "approved_plan": _plan_summary(approved_plan),
        "approved_plan_hash": approved_plan["plan_hash"],
        "apply_command": apply_result["command"],
        "apply_returncode": apply_result["returncode"],
        "apply_output": apply_result["combined_output"],
        "drift_message": drift_message,
        "package_unchanged": before_fingerprint == after_fingerprint,
    }


def _run_destructive_apply_scenario(*, root: Path, engine_repo: Path) -> dict[str, Any]:
    captured = _capture_studio_managed_baseline(
        root=root,
        app_name="Regen Apply Destructive Smoke App",
        bounded_context="regen-apply-destructive-smoke",
    )
    manifest = captured["manifest"]
    managed_package = captured["managed_package"]
    plan_dir = captured["workspace_root"] / "regen-apply-plan"

    _remove_manifest_field(manifest, field_name="status")
    plan_result = _run_appbuilder_plan(
        manifest=manifest,
        package=managed_package,
        out_dir=plan_dir,
        engine_repo=engine_repo,
    )
    plan = _assert_contract_valid_change_plan(plan_result["change_plan"])
    destructive_delta = _has_field_delta(
        plan,
        field_name="status",
        change="removed",
        classification="destructive",
    )
    before_fingerprint = _package_fingerprint(managed_package)
    apply_result = _run_appbuilder_apply(
        manifest=manifest,
        package=managed_package,
        approved_plan_hash=plan["plan_hash"],
        engine_repo=engine_repo,
    )
    after_fingerprint = _package_fingerprint(managed_package)
    output = apply_result["combined_output"].lower()
    refusal_message = (
        "additive-only" in output
        or "destructive" in output
        or "unsafe" in output
    )

    return {
        "failed_closed": (
            destructive_delta
            and apply_result["returncode"] != 0
            and refusal_message
            and before_fingerprint == after_fingerprint
        ),
        "workspace_root": str(captured["workspace_root"]),
        "manifest": str(manifest),
        "managed_package": str(managed_package),
        "plan": _plan_summary(plan),
        "plan_hash": plan["plan_hash"],
        "destructive_delta": destructive_delta,
        "apply_command": apply_result["command"],
        "apply_returncode": apply_result["returncode"],
        "apply_output": apply_result["combined_output"],
        "refusal_message": refusal_message,
        "package_unchanged": before_fingerprint == after_fingerprint,
    }


class _regen_preview_flag:
    def __enter__(self) -> None:
        self._original = os.environ.get("EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED")
        os.environ["EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED"] = "true"

    def __exit__(self, *_exc_info) -> None:
        if self._original is None:
            os.environ.pop("EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED", None)
        else:
            os.environ["EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED"] = self._original


def _engine_repo_from_env() -> Path:
    value = os.environ.get("EDGEFORGE_STUDIO_ENGINE_REPO", "").strip()
    assert value, "EDGEFORGE_STUDIO_ENGINE_REPO is required for the regen smoke"
    repo = Path(value).expanduser().resolve(strict=False)
    assert (repo / "appbuilder").is_dir(), f"Engine repo is not valid: {repo}"
    return repo


def _run_appbuilder_plan(
    *,
    manifest: Path,
    package: Path,
    out_dir: Path,
    engine_repo: Path,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{manifest.stem}-{len(list(out_dir.glob('*.json'))) + 1}.json"
    allowed_roots = [
        str(manifest.parent),
        str(package),
        str(out_dir),
    ]
    command = [
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
    ]
    proc = subprocess.run(
        command,
        cwd=str(engine_repo),
        env=_engine_subprocess_env(engine_repo, allowed_roots=allowed_roots),
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined_output = (proc.stdout + proc.stderr).strip()
    assert proc.returncode == 0, combined_output
    assert out_path.is_file(), combined_output
    raw = out_path.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "combined_output": combined_output,
        "command": command,
        "out_path": str(out_path),
        "change_plan": parsed,
    }


def _run_appbuilder_apply(
    *,
    manifest: Path,
    package: Path,
    approved_plan_hash: str,
    engine_repo: Path,
) -> dict[str, Any]:
    allowed_roots = [
        str(manifest.parent),
        str(package),
    ]
    command = [
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
        "--generation-run-id",
        "studio-regen-apply-smoke",
    ]
    proc = subprocess.run(
        command,
        cwd=str(engine_repo),
        env=_engine_subprocess_env(engine_repo, allowed_roots=allowed_roots),
        capture_output=True,
        text=True,
        timeout=180,
    )
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "combined_output": (proc.stdout + proc.stderr).strip(),
        "command": command,
    }


def _assert_contract_valid_change_plan(plan: object) -> dict[str, Any]:
    assert isinstance(plan, dict)
    version = str(plan.get("change_plan_schema_version", ""))
    major = version.split(".", 1)[0]
    assert major == "1", plan
    for key in ("plan_hash", "manifest_hash", "baseline_hash", "package_state_hash"):
        assert isinstance(plan.get(key), str) and plan[key].strip(), plan
    assert "deltas" in plan
    assert isinstance(plan["deltas"], (list, dict))
    assert "edge_contract_impact" in plan
    assert "warnings" in plan
    _assert_delta_classifications(plan["deltas"])
    return plan


def _assert_delta_classifications(deltas: object) -> None:
    if isinstance(deltas, list):
        for delta in deltas:
            assert isinstance(delta, dict)
            assert "migration_classification" in delta or "classification" in delta
        return
    assert isinstance(deltas, dict)
    for value in deltas.values():
        if isinstance(value, list):
            _assert_delta_classifications(value)


def _add_optional_manifest_field(manifest: Path) -> Path:
    """Mutate package artifacts referenced by the current manifest to add a field.

    The Studio-exported manifest stores source truth in package-relative
    OpenAPI/mapping/layout artifacts.  Changing those artifacts while keeping
    the manifest path stable mirrors a user re-exporting a richer current
    package without manually altering the managed generated-app baseline.
    """

    package_root = manifest.parent
    openapi_path = package_root / "contracts" / "plan-record-openapi.yaml"
    openapi_doc = yaml.safe_load(openapi_path.read_text(encoding="utf-8"))
    for schema_name in ("PlanRecord", "CreatePlanRecordRequest"):
        properties = openapi_doc["components"]["schemas"][schema_name]["properties"]
        properties["regenSmokeNote"] = {"type": "string", "nullable": True}
    openapi_path.write_text(yaml.safe_dump(openapi_doc, sort_keys=False), encoding="utf-8")

    for sample_name in ("plan-record-request.json", "plan-record-response.json"):
        sample_path = package_root / "upstream" / sample_name
        sample = json.loads(sample_path.read_text(encoding="utf-8"))
        sample["regenSmokeNote"] = "note"
        sample_path.write_text(json.dumps(sample, indent=2), encoding="utf-8")

    upstream_mapping_path = package_root / "upstream" / "plan-record-mapping.yaml"
    upstream_mapping = yaml.safe_load(upstream_mapping_path.read_text(encoding="utf-8"))
    operation = upstream_mapping["operations"][0]
    operation["request_mappings"].append(
        {"source": "regenSmokeNote", "target": "PlanRecord.regenSmokeNote"}
    )
    operation["response_mappings"].append(
        {"source": "regenSmokeNote", "target": "PlanRecord.regenSmokeNote"}
    )
    upstream_mapping_path.write_text(
        yaml.safe_dump(upstream_mapping, sort_keys=False),
        encoding="utf-8",
    )

    return manifest


def _mark_manifest_changed(manifest: Path, *, marker: str) -> Path:
    """Touch app-definition.yaml without changing parsed manifest semantics."""

    text = manifest.read_text(encoding="utf-8")
    comment = f"# {marker}"
    if comment not in text:
        manifest.write_text(f"{text.rstrip()}\n{comment}\n", encoding="utf-8")
    return manifest


def _add_response_only_optional_manifest_field(manifest: Path, *, field_name: str) -> Path:
    """Add an optional response-only field so Engine can apply it additively."""

    package_root = manifest.parent
    openapi_path = package_root / "contracts" / "plan-record-openapi.yaml"
    openapi_doc = yaml.safe_load(openapi_path.read_text(encoding="utf-8"))
    properties = openapi_doc["components"]["schemas"]["PlanRecord"]["properties"]
    properties[field_name] = {"type": "string", "nullable": True}
    openapi_path.write_text(yaml.safe_dump(openapi_doc, sort_keys=False), encoding="utf-8")

    response_path = package_root / "upstream" / "plan-record-response.json"
    response_sample = json.loads(response_path.read_text(encoding="utf-8"))
    response_sample[field_name] = "note"
    response_path.write_text(json.dumps(response_sample, indent=2), encoding="utf-8")

    upstream_mapping_path = package_root / "upstream" / "plan-record-mapping.yaml"
    upstream_mapping = yaml.safe_load(upstream_mapping_path.read_text(encoding="utf-8"))
    operation = upstream_mapping["operations"][0]
    operation["response_mappings"].append(
        {"source": field_name, "target": f"PlanRecord.{field_name}"}
    )
    upstream_mapping_path.write_text(
        yaml.safe_dump(upstream_mapping, sort_keys=False),
        encoding="utf-8",
    )

    return manifest


def _remove_manifest_field(manifest: Path, *, field_name: str) -> Path:
    """Remove a canonical field from all package artifacts that currently author it."""

    package_root = manifest.parent
    openapi_path = package_root / "contracts" / "plan-record-openapi.yaml"
    openapi_doc = yaml.safe_load(openapi_path.read_text(encoding="utf-8"))
    schemas = openapi_doc["components"]["schemas"]
    for schema_name in ("PlanRecord", "CreatePlanRecordRequest"):
        schema = schemas[schema_name]
        schema.get("properties", {}).pop(field_name, None)
        required = schema.get("required")
        if isinstance(required, list):
            schema["required"] = [item for item in required if item != field_name]
    openapi_path.write_text(yaml.safe_dump(openapi_doc, sort_keys=False), encoding="utf-8")

    for sample_name in ("plan-record-request.json", "plan-record-response.json"):
        sample_path = package_root / "upstream" / sample_name
        sample = json.loads(sample_path.read_text(encoding="utf-8"))
        sample.pop(field_name, None)
        sample_path.write_text(json.dumps(sample, indent=2), encoding="utf-8")

    upstream_mapping_path = package_root / "upstream" / "plan-record-mapping.yaml"
    upstream_mapping = yaml.safe_load(upstream_mapping_path.read_text(encoding="utf-8"))
    operation = upstream_mapping["operations"][0]
    for mapping_key in ("request_mappings", "response_mappings"):
        operation[mapping_key] = [
            row
            for row in operation.get(mapping_key, [])
            if row.get("source") != field_name and row.get("target") != f"PlanRecord.{field_name}"
        ]
    upstream_mapping_path.write_text(
        yaml.safe_dump(upstream_mapping, sort_keys=False),
        encoding="utf-8",
    )

    downstream_mapping_path = package_root / "downstream" / "plan-record-mapping.yaml"
    downstream_mapping = yaml.safe_load(downstream_mapping_path.read_text(encoding="utf-8"))
    downstream_mapping["field_mappings"] = [
        row
        for row in downstream_mapping.get("field_mappings", [])
        if row.get("source") != f"PlanRecord.{field_name}" and row.get("target") != field_name
    ]
    downstream_mapping_path.write_text(
        yaml.safe_dump(downstream_mapping, sort_keys=False),
        encoding="utf-8",
    )

    downstream_layout_path = package_root / "downstream" / "plan-record-layout.yaml"
    downstream_layout = yaml.safe_load(downstream_layout_path.read_text(encoding="utf-8"))
    record_types = downstream_layout.get("record_types") or {}
    data_record = record_types.get("data") or {}
    data_record["fields"] = [
        row for row in data_record.get("fields", []) if row.get("name") != field_name
    ]
    downstream_layout_path.write_text(
        yaml.safe_dump(downstream_layout, sort_keys=False),
        encoding="utf-8",
    )

    return manifest


def _has_added_delta(plan: dict[str, Any]) -> bool:
    for delta in _iter_deltas(plan.get("deltas")):
        if str(delta.get("change", "")).lower() == "added":
            return True
    return False


def _has_field_delta(
    plan: dict[str, Any],
    *,
    field_name: str,
    change: str,
    classification: str,
) -> bool:
    for delta in _iter_deltas(plan.get("deltas")):
        if (
            delta.get("kind") == "field"
            and delta.get("field") == field_name
            and str(delta.get("change", "")).lower() == change
            and str(delta.get("classification", "")).lower() == classification
        ):
            return True
    return False


def _iter_deltas(deltas: object):
    if isinstance(deltas, list):
        for delta in deltas:
            if isinstance(delta, dict):
                yield delta
        return
    if isinstance(deltas, dict):
        for value in deltas.values():
            yield from _iter_deltas(value)


def _migration_files(package: Path) -> list[Path]:
    migration_dir = package / "src" / "main" / "resources" / "db" / "migration"
    return sorted(path for path in migration_dir.glob("V*.sql") if path.is_file())


def _package_fingerprint(package: Path) -> str:
    entries: list[str] = []
    for path in sorted(path for path in package.rglob("*") if path.is_file()):
        rel = path.relative_to(package).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append(f"{rel}:{digest}")
    return hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()


def _plan_summary(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "change_plan_schema_version": plan.get("change_plan_schema_version"),
        "plan_hash": plan.get("plan_hash"),
        "manifest_hash": plan.get("manifest_hash"),
        "baseline_hash": plan.get("baseline_hash"),
        "package_state_hash": plan.get("package_state_hash"),
        "delta_count": sum(1 for _ in _iter_deltas(plan.get("deltas"))),
        "edge_contract_impact_count": len(plan.get("edge_contract_impact") or []),
        "warning_count": len(plan.get("warnings") or []),
    }
