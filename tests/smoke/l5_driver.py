from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from app.services.regen_preview import apply_regen_plan, build_regen_preview
from app.services.settings import get_studio_settings
from tests.smoke._shared import (
    assert_build_run_rejected_server_side,
    assert_csrf_enforced,
    assert_no_ka_noise,
    assert_openapi_url_policy,
    assert_path_under,
    assert_server_owned_paths,
    export_package,
    make_combined_edge_contract_session,
    make_exportable_smoke_session,
    new_shared_client,
    post_step1,
    save_session_for_client,
    session_for_client,
)
from tests.smoke.l4_driver import (
    _ka_off_spy,
    _post_generate,
    _shared_mode_environment,
    _tree_contains,
    run_author_generate_isolation,
    run_engine_fail_closed_isolation,
    run_ks_per_session_isolation,
)
from tests.smoke.regen_smoke import (
    _mark_manifest_changed,
    _migration_files,
    _regen_preview_flag,
)


def run_studio_l5_acceptance(*, root: Path) -> dict[str, Any]:
    """Run the Studio-owned acceptance scenarios for the suite orchestrator."""
    scenarios: list[dict[str, Any]] = []

    author_report = _capture("author_generate", lambda: run_author_generate_isolation(root=root / "author-generate"))
    if author_report["ok"]:
        detail = author_report["detail"]
        scenarios.append(
            _scenario(
                "multi-session isolation",
                detail["distinct_workspaces"]
                and detail["alpha_in_a"]
                and not detail["beta_in_a"]
                and detail["beta_in_b"]
                and not detail["alpha_in_b"],
                detail,
            )
        )
        scenarios.append(
            _scenario(
                "Studio-to-Engine per-session outputs",
                detail["distinct_generated_outputs"]
                and detail["output_a_under_workspace"]
                and detail["output_b_under_workspace"]
                and not detail["evil_a_exists"]
                and not detail["evil_b_exists"],
                detail,
            )
        )
    else:
        scenarios.append(_scenario("multi-session isolation", False, author_report["detail"]))
        scenarios.append(_scenario("Studio-to-Engine per-session outputs", False, author_report["detail"]))

    scenarios.append(_capture("shared-mode security", lambda: run_shared_mode_security(root=root / "security")))
    scenarios.append(
        _capture(
            "KS/KA per-session isolation",
            lambda: _ks_isolation_ok(run_ks_per_session_isolation(root=root / "ks-isolation")),
        )
    )
    scenarios.append(
        _capture(
            "Engine fail-closed out-of-root",
            lambda: _engine_fail_closed_ok(run_engine_fail_closed_isolation(root=root / "engine-fail-closed")),
        )
    )
    scenarios.append(_capture("KA-OFF strict", lambda: _ka_off_strict_ok(root=root / "ka-off-strict")))
    scenarios.append(
        _capture(
            "combined edge-contract author-generate",
            lambda: run_combined_edge_contract_generate(root=root / "combined-edge-contract"),
        )
    )
    scenarios.append(
        _capture(
            "regen-preview approve-apply",
            lambda: _regen_apply_isolation(root=root / "regen-apply"),
        )
    )
    return {"scenarios": scenarios}


def run_shared_mode_security(*, root: Path) -> dict[str, Any]:
    with _shared_mode_environment(root), _ka_off_spy() as ks_calls:
        client_a, csrf_a = new_shared_client()
        client_b, csrf_b = new_shared_client()
        assert_csrf_enforced(client_a)

        evil_a = root.parent / f"{root.name}-evil-a"
        evil_b = root.parent / f"{root.name}-evil-b"
        post_step1(
            client_a,
            csrf_a,
            app_name="Alpha Security Smoke App",
            bounded_context="alpha-security",
            output_path=evil_a,
        )
        post_step1(
            client_b,
            csrf_b,
            app_name="Beta Security Smoke App",
            bounded_context="beta-security",
            output_path=evil_b,
        )
        assert_openapi_url_policy(client_a, csrf_a)

        session_a = session_for_client(client_a)
        session_b = session_for_client(client_b)
        workspace_a = Path(session_a.workspace_root or "")
        workspace_b = Path(session_b.workspace_root or "")
        make_exportable_smoke_session(session_a, entity_name="AlphaSecure", contract_name="alpha-secure")
        make_exportable_smoke_session(session_b, entity_name="BetaSecure", contract_name="beta-secure")
        save_session_for_client(client_a, session_a)
        save_session_for_client(client_b, session_b)

        export_a = export_package(client_a, csrf_a)
        export_b = export_package(client_b, csrf_b)
        output_a = Path(export_a["output_dir"])
        output_b = Path(export_b["output_dir"])
        assert_server_owned_paths(
            output_a=output_a,
            output_b=output_b,
            workspace_a=workspace_a,
            workspace_b=workspace_b,
            evil_a=evil_a,
            evil_b=evil_b,
        )
        assert_build_run_rejected_server_side(client_a, csrf_a)

        import app.services.session_store as deprecated_session_store

        for accessor in ("get_session", "save_session", "reset_session"):
            try:
                getattr(deprecated_session_store, accessor)
            except RuntimeError:
                pass
            else:  # pragma: no cover - defensive
                raise AssertionError(f"deprecated session accessor still reachable: {accessor}")

        return {
            "ok": ks_calls == [],
            "ka_off_silent": ks_calls == [],
            "ks_calls": list(ks_calls),
            "workspace_a": str(workspace_a),
            "workspace_b": str(workspace_b),
            "output_a": str(output_a),
            "output_b": str(output_b),
        }


def run_combined_edge_contract_generate(*, root: Path) -> dict[str, Any]:
    with _shared_mode_environment(root), _ka_off_spy() as ks_calls:
        client, csrf_token = new_shared_client()
        post_step1(
            client,
            csrf_token,
            app_name="Gamma Combined Edge App",
            bounded_context="gamma-combined",
            output_path=root / "ignored-output",
        )
        session = session_for_client(client)
        workspace = Path(session.workspace_root or "")
        make_combined_edge_contract_session(session, entity_name="Gamma", contract_name="gamma")
        save_session_for_client(client, session)

        export = export_package(client, csrf_token)
        package_dir = Path(export["output_dir"])
        assert_path_under(package_dir, workspace)
        package_checks = _combined_package_checks(package_dir)
        generate = _post_generate(client, csrf_token)
        generated_dir = Path(generate["output_dir"])
        assert_path_under(generated_dir, workspace)
        generated_checks = _combined_generated_checks(generated_dir, "Gamma")
        return {
            "ok": all(package_checks.values()) and all(generated_checks.values()) and ks_calls == [],
            "ka_off_silent": ks_calls == [],
            "ks_calls": list(ks_calls),
            "workspace": str(workspace),
            "package_dir": str(package_dir),
            "generated_dir": str(generated_dir),
            "package_checks": package_checks,
            "generated_checks": generated_checks,
        }


def _regen_apply_isolation(*, root: Path) -> dict[str, Any]:
    with _shared_mode_environment(root), _regen_preview_flag(), _ka_off_spy() as ks_calls:
        client_a, csrf_a = new_shared_client()
        client_b, csrf_b = new_shared_client()
        alpha = _regen_apply_one_session(
            client_a,
            csrf_a,
            root=root / "alpha",
            app_name="Alpha Regen Apply L5 App",
            bounded_context="alpha-regen-apply-l5",
            entity_name="Alpha",
            contract_name="alpha",
            field_name="alphaL5ApplyNote",
        )
        beta = _regen_apply_one_session(
            client_b,
            csrf_b,
            root=root / "beta",
            app_name="Beta Regen Apply L5 App",
            bounded_context="beta-regen-apply-l5",
            entity_name="Beta",
            contract_name="beta",
            field_name="betaL5ApplyNote",
        )
        distinct_workspaces = alpha["workspace_root"] != beta["workspace_root"]
        distinct_generated_outputs = alpha["generated_output"] != beta["generated_output"]
        distinct_managed_packages = alpha["refreshed_package"] != beta["refreshed_package"]
        alpha_workspace = Path(alpha["workspace_root"])
        beta_workspace = Path(beta["workspace_root"])
        alpha_package = Path(alpha["refreshed_package"])
        beta_package = Path(beta["refreshed_package"])
        alpha_under_workspace = alpha_package.resolve().is_relative_to(alpha_workspace.resolve())
        beta_under_workspace = beta_package.resolve().is_relative_to(beta_workspace.resolve())
        alpha_cross_bleed = _tree_contains(alpha_package, beta["migration_needle"])
        beta_cross_bleed = _tree_contains(beta_package, alpha["migration_needle"])

        return {
            "ok": (
                ks_calls == []
                and alpha["applied"]
                and beta["applied"]
                and alpha["new_migration_count"] > 0
                and beta["new_migration_count"] > 0
                and alpha["migration_contains_field"]
                and beta["migration_contains_field"]
                and distinct_workspaces
                and distinct_generated_outputs
                and distinct_managed_packages
                and alpha_under_workspace
                and beta_under_workspace
                and not alpha_cross_bleed
                and not beta_cross_bleed
            ),
            "ka_off_silent": ks_calls == [],
            "ks_calls": list(ks_calls),
            "distinct_workspaces": distinct_workspaces,
            "distinct_generated_outputs": distinct_generated_outputs,
            "distinct_managed_packages": distinct_managed_packages,
            "alpha_under_workspace": alpha_under_workspace,
            "beta_under_workspace": beta_under_workspace,
            "alpha_cross_bleed": alpha_cross_bleed,
            "beta_cross_bleed": beta_cross_bleed,
            "alpha": alpha,
            "beta": beta,
        }


def _regen_apply_one_session(
    client,
    csrf_token: str,
    *,
    root: Path,
    app_name: str,
    bounded_context: str,
    entity_name: str,
    contract_name: str,
    field_name: str,
) -> dict[str, Any]:
    post_step1(
        client,
        csrf_token,
        app_name=app_name,
        bounded_context=bounded_context,
        output_path=root / "ignored-output",
    )
    session = session_for_client(client)
    workspace = Path(session.workspace_root or "")
    make_exportable_smoke_session(session, entity_name=entity_name, contract_name=contract_name)
    save_session_for_client(client, session)

    export = export_package(client, csrf_token)
    package_dir = Path(export["output_dir"])
    assert_path_under(package_dir, workspace)
    manifest = package_dir / "app-definition.yaml"
    generate = _post_generate(client, csrf_token)
    generated_output = Path(generate["output_dir"])
    assert_path_under(generated_output, workspace)

    session = session_for_client(client)
    managed_package = workspace / str(session.last_generated_package_ref)
    before_migrations = _migration_files(managed_package)
    _add_l5_response_only_field(
        manifest,
        entity_name=entity_name,
        contract_name=contract_name,
        field_name=field_name,
    )
    _mark_manifest_changed(
        manifest,
        marker=f"l5-regen-apply-{contract_name}",
    )
    settings = get_studio_settings()
    preview = build_regen_preview(session, settings)
    assert preview["state"] == "ready", preview
    assert preview["is_additive_only"] is True, preview
    apply_result = apply_regen_plan(
        session,
        settings,
        approved_plan_hash=preview["plan_hash"],
    )
    save_session_for_client(client, session)

    refreshed_package = workspace / str(session.last_generated_package_ref)
    after_migrations = _migration_files(refreshed_package)
    old_migration_names = {path.name for path in before_migrations}
    new_migrations = [path for path in after_migrations if path.name not in old_migration_names]
    migration_needle = _snake_case(field_name)
    migration_contains_field = any(
        migration_needle in path.read_text(encoding="utf-8").lower()
        for path in new_migrations
    )
    return {
        "applied": apply_result["state"] == "applied",
        "workspace_root": str(workspace),
        "export_package": str(package_dir),
        "generated_output": str(generated_output),
        "initial_managed_package": str(managed_package),
        "refreshed_package": str(refreshed_package),
        "plan_hash": preview["plan_hash"],
        "apply_summary": apply_result.get("summary"),
        "new_migration_count": len(new_migrations),
        "new_migrations": [str(path) for path in new_migrations],
        "migration_contains_field": migration_contains_field,
        "migration_needle": migration_needle,
    }


def _add_l5_response_only_field(
    manifest: Path,
    *,
    entity_name: str,
    contract_name: str,
    field_name: str,
) -> None:
    package_root = manifest.parent
    openapi_path = package_root / "contracts" / f"{contract_name}-openapi.yaml"
    openapi_doc = yaml.safe_load(openapi_path.read_text(encoding="utf-8"))
    openapi_doc["components"]["schemas"][entity_name]["properties"][field_name] = {
        "type": "string",
        "nullable": True,
    }
    openapi_path.write_text(yaml.safe_dump(openapi_doc, sort_keys=False), encoding="utf-8")

    response_path = package_root / "upstream" / f"{contract_name}-response.json"
    response_sample = json.loads(response_path.read_text(encoding="utf-8"))
    response_sample[field_name] = "note"
    response_path.write_text(json.dumps(response_sample, indent=2), encoding="utf-8")

    mapping_path = package_root / "upstream" / f"{contract_name}-mapping.yaml"
    mapping = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
    mapping["operations"][0]["response_mappings"].append(
        {"source": field_name, "target": f"{entity_name}.{field_name}"}
    )
    mapping_path.write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8")


def _snake_case(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def _capture(name: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        result = fn()
        if "scenario" in result and "ok" in result:
            return result
        return _scenario(name, bool(result.get("ok", True)), result)
    except Exception as exc:  # pragma: no cover - assertion detail for smoke failures
        return _scenario(name, False, {"error": f"{type(exc).__name__}: {exc}"})


def _scenario(name: str, ok: bool, detail: dict[str, Any]) -> dict[str, Any]:
    return {"scenario": name, "ok": ok, "detail": detail}


def _ks_isolation_ok(report: dict[str, Any]) -> dict[str, Any]:
    expected_roots = report["expected_allowed_root_per_child"]
    parsed_roots = report["parsed_allowed_roots_per_child"]
    ok = (
        report["distinct_workspaces"]
        and report["distinct_ks_dbs"]
        and report["db_a_under_workspace"]
        and report["db_b_under_workspace"]
        and report["alpha_result_has_alpha"]
        and not report["alpha_result_has_beta"]
        and report["beta_result_has_beta"]
        and not report["beta_result_has_alpha"]
        and report["ks_children_spawned"] == 2
        and report["shared_mode_flag_per_child"] == ["1", "1"]
        and len(report["db_path_per_child"]) == 2
        and all(report["db_path_per_child"])
        and len(report["allowed_roots_per_child"]) == 2
        and all(report["allowed_roots_per_child"])
        and report["child_db_paths_distinct"]
        and report["child_db_under_own_workspace"]
        and report["child_roots_distinct"]
        and report["child_roots_under_own_workspace"]
        and report["child_roots_match_expected"]
        and len(expected_roots) == 2
        and parsed_roots == [[expected_roots[0]], [expected_roots[1]]]
    )
    return {"ok": ok, **report}


def _engine_fail_closed_ok(report: dict[str, Any]) -> dict[str, Any]:
    negatives_ok = all(
        case["rejected"] and case["message_matched"] and not case["target_exists"]
        for case in report["negative_cases"]
    )
    missing = report["missing_roots"]
    missing_ok = missing["rejected"] and missing["message_matched"] and not missing["target_exists"]
    positive = report["positive_control"]
    ok = (
        report["ka_off_silent"]
        and report["distinct_workspaces"]
        and negatives_ok
        and missing_ok
        and positive["succeeded"]
        and positive["output_exists"]
    )
    return {"ok": ok, **report}


def _ka_off_strict_ok(*, root: Path) -> dict[str, Any]:
    with _shared_mode_environment(root), _ka_off_spy() as ks_calls:
        client, csrf_token = new_shared_client()
        post_step1(
            client,
            csrf_token,
            app_name="KA Off Strict Smoke App",
            bounded_context="ka-off-strict",
            output_path=root / "ignored-output",
        )
        session = session_for_client(client)
        make_exportable_smoke_session(session, entity_name="Silent", contract_name="silent")
        save_session_for_client(client, session)
        payload = export_package(client, csrf_token)
        assert_no_ka_noise(payload)
        return {"ok": ks_calls == [], "ka_off_silent": ks_calls == [], "ks_calls": list(ks_calls)}


def _combined_package_checks(package_dir: Path) -> dict[str, bool]:
    expected_paths = {
        "manifest": package_dir / "app-definition.yaml",
        "evidence_trail": package_dir / "evidence-trail.json",
        "rest_spec": package_dir / "contracts/gamma-openapi.yaml",
        "fixed_width": package_dir / "downstream/gamma-layout.yaml",
        "csv_in": package_dir / "upstream/gamma-csv-layout.yaml",
        "csv_out": package_dir / "downstream/gamma-csv-layout.yaml",
        "xml_in": package_dir / "contracts/gamma-in.xsd",
        "xml_out": package_dir / "contracts/gamma-out.xsd",
        "soap_in": package_dir / "contracts/gamma-soap-service.wsdl",
        "soap_out": package_dir / "contracts/gamma-soap-client.wsdl",
        "staging_ddl": package_dir / "data-handoffs/gamma-staging-table.sql",
        "staging_mapping": package_dir / "data-handoffs/gamma-staging-mapping.yaml",
    }
    checks = {name: path.exists() for name, path in expected_paths.items()}
    if expected_paths["evidence_trail"].exists():
        sidecar = json.loads(expected_paths["evidence_trail"].read_text(encoding="utf-8"))
        serialized = json.dumps(sidecar)
        checks["evidence_has_file"] = "file-fixed-width" in serialized and "file-csv" in serialized
        checks["evidence_has_xml"] = "xml-xsd" in serialized
        checks["evidence_has_soap"] = "soap-wsdl" in serialized
    else:
        checks["evidence_has_file"] = False
        checks["evidence_has_xml"] = False
        checks["evidence_has_soap"] = False
    return checks


def _combined_generated_checks(generated_dir: Path, entity_name: str) -> dict[str, bool]:
    file_names = {path.name for path in generated_dir.rglob("*") if path.is_file()}
    return {
        "rest_controller": f"{entity_name}Controller.java" in file_names,
        "fixed_width_writer": any("Fixed" in name and "Writer" in name for name in file_names),
        "csv_writer": any("Csv" in name and "Writer" in name for name in file_names),
        "xml_handler": any("Xml" in name for name in file_names),
        "soap_artifact": any("Soap" in name for name in file_names),
        "staging_artifact": _tree_contains(generated_dir, "gamma_staging"),
    }
