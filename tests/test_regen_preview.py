from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.integrations.appbuilder_integration as engine_integration
from app.integrations.appbuilder_integration import (
    ApplyResult,
    ChangePlanResult,
    SubprocessResult,
    run_apply,
    run_change_plan,
)
from app.main import app
from app.services.audit import AuditEvent, set_audit_sink_for_testing
from app.services.regen_apply_locks import acquire_regen_apply_lock
from app.services.regen_binding import capture_generated_package
from app.services.regen_preview import apply_regen_plan, build_regen_preview
from tests.session_helpers import get_session, reset_session, save_session
from tests.smoke._shared import csrf_from_html, save_session_for_client, session_for_client


def _subprocess_result(stdout: str = "") -> SubprocessResult:
    return SubprocessResult(
        success=True,
        returncode=0,
        stdout=stdout,
        stderr="",
        combined_output=stdout,
        duration_seconds=0.0,
        command=["stubbed"],
        cwd=None,
    )


def _change_plan_result(plan: dict) -> ChangePlanResult:
    return ChangePlanResult(
        success=True,
        change_plan=plan,
        error=None,
        subprocess=_subprocess_result(json.dumps(plan)),
        out_path=None,
    )


def _failed_change_plan_result(output: str) -> ChangePlanResult:
    subprocess = _subprocess_result(output)
    subprocess.success = False
    subprocess.returncode = 1
    subprocess.stderr = output
    return ChangePlanResult(
        success=False,
        change_plan=None,
        error=output,
        subprocess=subprocess,
        out_path=None,
    )


class _CapturingAuditSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> None:
        self.events.append(event)


@pytest.fixture(autouse=True)
def _reset_audit_sink():
    set_audit_sink_for_testing(None)
    yield
    set_audit_sink_for_testing(None)


def _install_audit_sink() -> _CapturingAuditSink:
    sink = _CapturingAuditSink()
    set_audit_sink_for_testing(sink)
    return sink


def _apply_result(*, success: bool = True, output: str = "apply ok") -> ApplyResult:
    subprocess = _subprocess_result(output)
    subprocess.success = success
    subprocess.returncode = 0 if success else 1
    subprocess.stderr = "" if success else output
    subprocess.combined_output = output
    return ApplyResult(
        success=success,
        error=None if success else output,
        subprocess=subprocess,
    )


def _sample_change_plan(**overrides) -> dict:
    plan = {
        "change_plan_schema_version": "1.0",
        "engine_version": "engine-test",
        "manifest_hash": "manifest-new",
        "baseline_hash": "baseline-old",
        "package_state_hash": "package-state-1",
        "plan_id": "plan-1",
        "plan_hash": "plan-hash-1",
        "deltas": [
            {
                "kind": "entity",
                "path": "/entities/Account",
                "entity": "Account",
                "change": "added",
                "migration_classification": "additive",
            },
            {
                "kind": "field",
                "path": "/entities/Account/fields/legacyCode",
                "field": "Account.legacyCode",
                "change": "removed",
                "migration_classification": "destructive",
            },
        ],
        "edge_contract_impact": [
            {
                "contract": "account-fixed-out",
                "field": "legacy_code",
                "classification": "unsafe",
                "reason": "mapped field removed",
            }
        ],
        "db_migration_deltas": [
            {
                "name": "V2__add_account.sql",
                "path": "/db/migrations/V2__add_account.sql",
                "migration_classification": "additive",
            }
        ],
        "required_manual_actions": ["Review removed field mapping."],
        "warnings": ["SOAP response mapping changed."],
    }
    plan.update(overrides)
    return plan


def _sample_additive_change_plan(**overrides) -> dict:
    return _sample_change_plan(
        deltas=[
            {
                "kind": "field",
                "path": "/entities/Account/fields/note",
                "field": "Account.note",
                "change": "added",
                "migration_classification": "additive",
            }
        ],
        edge_contract_impact=[],
        db_migration_deltas=[
            {
                "name": "V2__add_account_note.sql",
                "path": "/db/migrations/V2__add_account_note.sql",
                "migration_classification": "additive",
            }
        ],
        required_manual_actions=[],
        warnings=[],
        **overrides,
    )


def _seed_regenerate_ready_project(session):
    workspace_root = Path(session.workspace_root or "")
    export_dir = workspace_root / "output" / "demo"
    generated = export_dir / "generated-app"
    manifest = export_dir / "app-definition.yaml"
    generated.mkdir(parents=True)
    (generated / "db").mkdir()
    (generated / "db" / "schema-baseline.json").write_text('{"entities":[]}\n', encoding="utf-8")
    manifest.write_text("app_name: demo\n", encoding="utf-8")
    session.last_export_path = str(export_dir)
    capture_generated_package(
        session,
        generated_package_path=generated,
        manifest_path=manifest,
    )
    manifest.write_text("app_name: demo\nentities: []\n", encoding="utf-8")
    return session


def _seed_regenerate_ready_session(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED", "true")
    session = reset_session()
    session = get_session()
    _seed_regenerate_ready_project(session)
    save_session(session)
    return get_session()


def test_regen_preview_flag_off_route_404_and_no_engine_plan_call(monkeypatch):
    monkeypatch.delenv("EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED", raising=False)
    calls = []

    def fail_plan(*_args, **_kwargs):
        calls.append("called")
        raise AssertionError("flag-off regen preview must not call Engine plan")

    monkeypatch.setattr("app.services.regen_preview.run_change_plan", fail_plan)

    assert build_regen_preview(get_session())["state"] == "disabled"
    response = TestClient(app).get("/regen/preview")

    assert response.status_code == 404
    assert calls == []


def test_regen_preview_renders_engine_change_plan_verbatim(monkeypatch):
    _seed_regenerate_ready_session(monkeypatch)
    plan = _sample_change_plan()
    calls = []

    def fake_plan(manifest_path, package_dir, appbuilder_repo, *, allowed_roots):
        calls.append(
            {
                "manifest_path": Path(manifest_path),
                "package_dir": Path(package_dir),
                "allowed_roots": [Path(root) for root in allowed_roots],
            }
        )
        return _change_plan_result(plan)

    monkeypatch.setattr("app.services.regen_preview.run_change_plan", fake_plan)
    response = TestClient(app).get("/regen/preview")

    assert response.status_code == 200
    assert calls
    html = response.text
    assert "plan-hash-1" in html
    assert "package-state-1" in html
    assert "engine-test" in html
    assert "Manifest deltas - Entity" in html
    assert "Manifest deltas - Field" in html
    assert "DB migration deltas" in html
    assert "Account.legacyCode" in html
    assert "V2__add_account.sql" in html
    assert "account-fixed-out" in html
    assert "SOAP response mapping changed." in html
    assert "Review removed field mapping." in html
    assert "regen-destructive" in html
    assert "regen-unsafe" in html
    assert "Apply blocked for this change" in html


def test_regen_preview_sanitizes_engine_failure_output(monkeypatch):
    _seed_regenerate_ready_session(monkeypatch)
    hostile = (
        'Traceback (most recent call last):\n  File "/Users/alice/private/plan.py", '
        "line 7, in build\n    run_plan()\n"
        "ValueError: field customer_id is missing\n"
        "Command: edgeforge plan --token topsecret --manifest /Users/alice/app.yaml\n"
        "PASSWORD=hunter2\n"
        "https://alice:secret@example.test/spec.yaml?token=secret"
    )

    def fake_plan(*_args, **_kwargs):
        return _failed_change_plan_result(hostile)

    monkeypatch.setattr("app.services.regen_preview.run_change_plan", fake_plan)

    preview = build_regen_preview(get_session())

    assert preview["state"] == "error"
    assert preview["message"] == "ValueError: field customer_id is missing"
    assert preview["diagnostic_id"].startswith("diag-")
    rendered = json.dumps(preview)
    for secret in (
        "Traceback",
        "/Users/alice",
        "topsecret",
        "hunter2",
        "alice:secret",
        "token=secret",
    ):
        assert secret not in rendered


def test_regen_preview_groups_real_engine_deltas_by_kind(monkeypatch):
    _seed_regenerate_ready_session(monkeypatch)

    def fake_plan(*_args, **_kwargs):
        return _change_plan_result(
            _sample_change_plan(
                edge_contract_impact=[],
                required_manual_actions=[],
                warnings=[],
            )
        )

    monkeypatch.setattr("app.services.regen_preview.run_change_plan", fake_plan)

    preview = build_regen_preview(get_session())

    assert preview["state"] == "ready"
    groups = {group["label"]: group for group in preview["groups"]}
    assert set(groups) == {
        "Manifest deltas - Entity",
        "Manifest deltas - Field",
        "DB migration deltas",
    }
    assert groups["Manifest deltas - Entity"]["items"][0]["payload"]["path"] == "/entities/Account"
    assert (
        groups["Manifest deltas - Field"]["items"][0]["payload"]["path"]
        == "/entities/Account/fields/legacyCode"
    )
    assert (
        groups["DB migration deltas"]["items"][0]["payload"]["path"]
        == "/db/migrations/V2__add_account.sql"
    )


def test_change_plan_unknown_major_is_rejected(monkeypatch):
    _seed_regenerate_ready_session(monkeypatch)

    def fake_plan(*_args, **_kwargs):
        return _change_plan_result(_sample_change_plan(change_plan_schema_version="2.0"))

    monkeypatch.setattr("app.services.regen_preview.run_change_plan", fake_plan)

    preview = build_regen_preview(get_session())

    assert preview["state"] == "unsupported"
    assert "Unsupported Change Plan version: 2.0" in preview["message"]
    assert "raw_plan_json" not in preview


def test_change_plan_minor_version_is_tolerated(monkeypatch):
    _seed_regenerate_ready_session(monkeypatch)

    def fake_plan(*_args, **_kwargs):
        return _change_plan_result(
            _sample_change_plan(
                change_plan_schema_version="1.1",
                future_minor_field={"ok": True},
            )
        )

    monkeypatch.setattr("app.services.regen_preview.run_change_plan", fake_plan)

    preview = build_regen_preview(get_session())

    assert preview["state"] == "ready"
    assert preview["schema_version"] == "1.1"
    assert "future_minor_field" in preview["raw_plan_json"]


def test_regen_preview_none_and_manifest_only_do_not_call_engine_plan(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED", "true")
    calls = []

    def fail_plan(*_args, **_kwargs):
        calls.append("called")
        raise AssertionError("friendly regen states must not call Engine plan")

    monkeypatch.setattr("app.services.regen_preview.run_change_plan", fail_plan)
    session = reset_session()

    empty = build_regen_preview(session)

    workspace_root = Path(session.workspace_root or "")
    package = workspace_root / "managed-artifacts" / "run-1" / "generated-app"
    package.mkdir(parents=True)
    session.last_generated_package_ref = "managed-artifacts/run-1/generated-app"
    session.generation_run_id = "run-1"
    session.manifest_hash = "manifest-hash"
    session.baseline_hash = None

    manifest_only = build_regen_preview(session)

    assert empty["state"] == "empty"
    assert manifest_only["state"] == "manifest-only"
    assert calls == []


def test_run_change_plan_sets_shared_roots_and_reads_out_json(monkeypatch, tmp_path):
    repo = tmp_path / "engine"
    repo.mkdir()
    manifest = tmp_path / "workspace" / "export" / "app-definition.yaml"
    package = tmp_path / "workspace" / "managed-artifacts" / "run-1" / "generated-app"
    scratch = tmp_path / "workspace" / "regen-preview"
    manifest.parent.mkdir(parents=True)
    package.mkdir(parents=True)
    scratch.mkdir(parents=True)
    manifest.write_text("app_name: demo\n", encoding="utf-8")
    captured: dict[str, object] = {}
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "plan-shared-secret")

    def fake_run_subprocess(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["env"] = dict(kwargs["env"])
        out_path = Path(cmd[cmd.index("--out") + 1])
        assert out_path.parent == scratch.resolve()
        out_path.write_text(json.dumps(_sample_change_plan()), encoding="utf-8")
        return _subprocess_result("plan ok")

    monkeypatch.setattr(engine_integration, "_run_subprocess", fake_run_subprocess)

    result = run_change_plan(
        manifest,
        package,
        str(repo),
        allowed_roots=[str(manifest.parent), str(package), str(scratch)],
    )

    assert result.success is True
    assert result.change_plan and result.change_plan["plan_hash"] == "plan-hash-1"
    cmd = captured["cmd"]
    assert cmd[:4] == [sys.executable, "-m", "appbuilder.cli", "plan"]
    assert "--validate-schema" in cmd
    env = captured["env"]
    roots = env["EDGEFORGE_MCP_ALLOWED_ROOTS"].split(os.pathsep)
    assert env["EDGEFORGE_SHARED_MODE"] == "1"
    assert str(manifest.parent.resolve()) in roots
    assert str(package.resolve()) in roots
    assert str(scratch.resolve()) in roots
    assert str(repo.resolve()) not in roots


def test_run_apply_sets_shared_roots_and_approved_hash(monkeypatch, tmp_path):
    repo = tmp_path / "engine"
    repo.mkdir()
    manifest = tmp_path / "workspace" / "export" / "app-definition.yaml"
    package = tmp_path / "workspace" / "managed-artifacts" / "run-1" / "generated-app"
    manifest.parent.mkdir(parents=True)
    package.mkdir(parents=True)
    manifest.write_text("app_name: demo\n", encoding="utf-8")
    captured: dict[str, object] = {}
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "apply-shared-secret")

    def fake_run_subprocess(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["env"] = dict(kwargs["env"])
        return _subprocess_result("apply ok")

    monkeypatch.setattr(engine_integration, "_run_subprocess", fake_run_subprocess)

    result = run_apply(
        manifest,
        package,
        str(repo),
        approved_plan_hash="approved-hash",
        allowed_roots=[str(manifest.parent), str(package)],
    )

    assert result.success is True
    cmd = captured["cmd"]
    assert cmd[:4] == [sys.executable, "-m", "appbuilder.cli", "apply"]
    assert cmd[cmd.index("--approved-plan-hash") + 1] == "approved-hash"
    assert "--manifest" in cmd
    assert "--package" in cmd
    env = captured["env"]
    roots = env["EDGEFORGE_MCP_ALLOWED_ROOTS"].split(os.pathsep)
    assert env["EDGEFORGE_SHARED_MODE"] == "1"
    assert str(manifest.parent.resolve()) in roots
    assert str(package.resolve()) in roots
    assert str(repo.resolve()) not in roots


def test_apply_regen_plan_flag_off_returns_disabled_and_skips_engine(monkeypatch):
    monkeypatch.delenv("EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED", raising=False)
    session = get_session()

    def fail_apply(*_args, **_kwargs):
        raise AssertionError("flag-off apply must not call Engine")

    monkeypatch.setattr("app.services.regen_preview.run_apply", fail_apply)

    result = apply_regen_plan(session, approved_plan_hash="any")

    assert result["state"] == "disabled"


def test_apply_regen_plan_detects_drift_before_engine_apply(monkeypatch):
    session = _seed_regenerate_ready_session(monkeypatch)

    def fake_plan(*_args, **_kwargs):
        return _change_plan_result(_sample_additive_change_plan(plan_hash="fresh-hash"))

    def fail_apply(*_args, **_kwargs):
        raise AssertionError("drifted apply must not call Engine")

    monkeypatch.setattr("app.services.regen_preview.run_change_plan", fake_plan)
    monkeypatch.setattr("app.services.regen_preview.run_apply", fail_apply)

    result = apply_regen_plan(session, approved_plan_hash="stale-hash")

    assert result["state"] == "drift"
    assert result["fresh_plan_hash"] == "fresh-hash"


def test_apply_regen_plan_returns_busy_when_package_lock_is_held(monkeypatch):
    session = _seed_regenerate_ready_session(monkeypatch)
    package = Path(session.workspace_root or "") / str(session.last_generated_package_ref)

    def fail_plan(*_args, **_kwargs):
        raise AssertionError("busy apply must not recompute the Change Plan")

    def fail_apply(*_args, **_kwargs):
        raise AssertionError("busy apply must not call Engine")

    monkeypatch.setattr("app.services.regen_preview.run_change_plan", fail_plan)
    monkeypatch.setattr("app.services.regen_preview.run_apply", fail_apply)

    with acquire_regen_apply_lock(package) as acquired:
        assert acquired is True
        result = apply_regen_plan(session, approved_plan_hash="apply-hash")

    assert result["state"] == "busy"
    assert "already in progress" in result["message"]


def test_apply_regen_plan_blocks_non_additive_change(monkeypatch):
    session = _seed_regenerate_ready_session(monkeypatch)

    def fake_plan(*_args, **_kwargs):
        return _change_plan_result(_sample_change_plan(plan_hash="blocked-hash"))

    def fail_apply(*_args, **_kwargs):
        raise AssertionError("blocked apply must not call Engine")

    monkeypatch.setattr("app.services.regen_preview.run_change_plan", fake_plan)
    monkeypatch.setattr("app.services.regen_preview.run_apply", fail_apply)

    result = apply_regen_plan(session, approved_plan_hash="blocked-hash")

    assert result["state"] == "blocked"
    assert {item["classification"] for item in result["blocked_items"]} >= {
        "destructive",
        "unsafe",
    }


def test_apply_regen_plan_additive_runs_engine_and_refreshes_baseline(monkeypatch):
    session = _seed_regenerate_ready_session(monkeypatch)
    original_run_id = session.generation_run_id
    calls = []

    def fake_plan(*_args, **_kwargs):
        return _change_plan_result(_sample_additive_change_plan(plan_hash="apply-hash"))

    def fake_apply(manifest_path, package_dir, appbuilder_repo, *, approved_plan_hash, allowed_roots):
        calls.append(
            {
                "manifest_path": Path(manifest_path),
                "package_dir": Path(package_dir),
                "approved_plan_hash": approved_plan_hash,
                "allowed_roots": [Path(root) for root in allowed_roots],
            }
        )
        return _apply_result(output="applied apply-hash")

    monkeypatch.setattr("app.services.regen_preview.run_change_plan", fake_plan)
    monkeypatch.setattr("app.services.regen_preview.run_apply", fake_apply)

    result = apply_regen_plan(session, approved_plan_hash="apply-hash")

    assert result["state"] == "applied"
    assert calls
    assert calls[0]["approved_plan_hash"] == "apply-hash"
    assert calls[0]["manifest_path"].parent in calls[0]["allowed_roots"]
    assert calls[0]["package_dir"] in calls[0]["allowed_roots"]
    assert session.generation_run_id
    assert session.generation_run_id != original_run_id
    assert result["summary"]["managed_package_ref"] == session.last_generated_package_ref
    assert result["summary"]["baseline_present"] is True


def test_apply_regen_plan_engine_failure_returns_error_without_refresh(monkeypatch):
    session = _seed_regenerate_ready_session(monkeypatch)
    original_run_id = session.generation_run_id

    def fake_plan(*_args, **_kwargs):
        return _change_plan_result(_sample_additive_change_plan(plan_hash="apply-hash"))

    def fake_apply(*_args, **_kwargs):
        return _apply_result(success=False, output="engine refused apply")

    monkeypatch.setattr("app.services.regen_preview.run_change_plan", fake_plan)
    monkeypatch.setattr("app.services.regen_preview.run_apply", fake_apply)

    result = apply_regen_plan(session, approved_plan_hash="apply-hash")

    assert result["state"] == "error"
    assert "engine refused apply" in result["engine_output"]
    assert session.generation_run_id == original_run_id


@pytest.mark.parametrize("success", [False, True])
def test_apply_regen_plan_sanitizes_engine_output_in_all_states(monkeypatch, success):
    session = _seed_regenerate_ready_session(monkeypatch)
    hostile = (
        'Traceback (most recent call last):\n  File "C:\\Users\\Alice\\private\\apply.py", '
        "line 9, in apply\n    run_apply()\n"
        "Applied additive migration.\n"
        "Command: edgeforge apply --password supersecret C:\\Users\\Alice\\app.yaml\n"
        "API_TOKEN=token-value\n"
        "https://alice:secret@example.test/apply?api_key=secret"
    )

    def fake_plan(*_args, **_kwargs):
        return _change_plan_result(_sample_additive_change_plan(plan_hash="apply-hash"))

    def fake_apply(*_args, **_kwargs):
        return _apply_result(success=success, output=hostile)

    monkeypatch.setattr("app.services.regen_preview.run_change_plan", fake_plan)
    monkeypatch.setattr("app.services.regen_preview.run_apply", fake_apply)

    result = apply_regen_plan(session, approved_plan_hash="apply-hash")

    assert result["state"] == ("applied" if success else "error")
    assert result["diagnostic_id"].startswith("diag-")
    rendered = json.dumps(result)
    assert "Applied additive migration." in rendered
    for secret in (
        "Traceback",
        "C:\\Users\\Alice",
        "supersecret",
        "token-value",
        "alice:secret",
        "api_key=secret",
    ):
        assert secret not in rendered


def test_regen_apply_route_404_when_flag_off(monkeypatch):
    monkeypatch.delenv("EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED", raising=False)

    response = TestClient(app).post("/regen/apply", data={"approved_plan_hash": "hash"})

    assert response.status_code == 404


def test_regen_apply_route_requires_form_csrf_in_shared_mode(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "regen-apply-shared-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED", "true")
    client = TestClient(app, base_url="https://testserver")
    token = csrf_from_html(client.get("/").text)
    session = session_for_client(client)
    _seed_regenerate_ready_project(session)
    save_session_for_client(client, session)

    def fake_plan(*_args, **_kwargs):
        return _change_plan_result(_sample_additive_change_plan(plan_hash="route-hash"))

    def fake_apply(*_args, **_kwargs):
        return _apply_result(output="route applied")

    monkeypatch.setattr("app.services.regen_preview.run_change_plan", fake_plan)
    monkeypatch.setattr("app.services.regen_preview.run_apply", fake_apply)

    missing = client.post("/regen/apply", data={"approved_plan_hash": "route-hash"})
    valid = client.post(
        "/regen/apply",
        data={
            "_edgeforge_csrf_token": token,
            "approved_plan_hash": "route-hash",
        },
    )

    assert missing.status_code == 403
    assert valid.status_code == 200
    assert "Additive Change Plan applied" in valid.text


def test_regen_apply_route_returns_409_and_audits_when_package_lock_is_held(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "regen-apply-busy-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED", "true")
    sink = _install_audit_sink()
    client = TestClient(app, base_url="https://testserver")
    token = csrf_from_html(client.get("/").text)
    session = session_for_client(client)
    _seed_regenerate_ready_project(session)
    save_session_for_client(client, session)
    package = Path(session.workspace_root or "") / str(session.last_generated_package_ref)

    def fail_plan(*_args, **_kwargs):
        raise AssertionError("busy route must not recompute the Change Plan")

    monkeypatch.setattr("app.services.regen_preview.run_change_plan", fail_plan)

    with acquire_regen_apply_lock(package) as acquired:
        assert acquired is True
        response = client.post(
            "/regen/apply",
            data={
                "_edgeforge_csrf_token": token,
                "approved_plan_hash": "apply-hash",
            },
        )

    assert response.status_code == 409
    assert "already in progress" in response.text
    assert ("regen.apply", "blocked") in [
        (event.event_type, event.outcome) for event in sink.events
    ]


def test_regen_apply_route_surfaces_drift_and_blocked(monkeypatch):
    session = _seed_regenerate_ready_session(monkeypatch)

    def fake_additive_plan(*_args, **_kwargs):
        return _change_plan_result(_sample_additive_change_plan(plan_hash="fresh-hash"))

    def fail_apply(*_args, **_kwargs):
        raise AssertionError("drift/blocked route cases must not call Engine apply")

    monkeypatch.setattr("app.services.regen_preview.run_change_plan", fake_additive_plan)
    monkeypatch.setattr("app.services.regen_preview.run_apply", fail_apply)
    drift = TestClient(app).post("/regen/apply", data={"approved_plan_hash": "stale-hash"})

    def fake_blocked_plan(*_args, **_kwargs):
        return _change_plan_result(_sample_change_plan(plan_hash="blocked-hash"))

    monkeypatch.setattr("app.services.regen_preview.run_change_plan", fake_blocked_plan)
    save_session(session)
    blocked = TestClient(app).post("/regen/apply", data={"approved_plan_hash": "blocked-hash"})

    assert drift.status_code == 200
    assert "The Change Plan changed or is no longer ready" in drift.text
    assert blocked.status_code == 200
    assert "Studio only applies additive Change Plans" in blocked.text


def test_regen_apply_route_audits_success_and_blocked_outcomes(monkeypatch):
    sink = _install_audit_sink()
    _seed_regenerate_ready_session(monkeypatch)

    def fake_additive_plan(*_args, **_kwargs):
        return _change_plan_result(_sample_additive_change_plan(plan_hash="route-hash"))

    def fake_apply(*_args, **_kwargs):
        return _apply_result(output="route applied")

    monkeypatch.setattr("app.services.regen_preview.run_change_plan", fake_additive_plan)
    monkeypatch.setattr("app.services.regen_preview.run_apply", fake_apply)
    success = TestClient(app).post("/regen/apply", data={"approved_plan_hash": "route-hash"})

    _seed_regenerate_ready_session(monkeypatch)

    def fake_blocked_plan(*_args, **_kwargs):
        return _change_plan_result(_sample_change_plan(plan_hash="blocked-hash"))

    monkeypatch.setattr("app.services.regen_preview.run_change_plan", fake_blocked_plan)
    blocked = TestClient(app).post("/regen/apply", data={"approved_plan_hash": "blocked-hash"})

    assert success.status_code == 200
    assert blocked.status_code == 200
    observed = [(event.event_type, event.outcome) for event in sink.events]
    assert ("regen.apply", "success") in observed
    assert ("regen.apply", "blocked") in observed


def test_regen_preview_ka_off_spawns_no_ks(monkeypatch):
    _seed_regenerate_ready_session(monkeypatch)

    def fail_ks_start(*_args, **_kwargs):
        raise AssertionError("regen preview must not spawn Knowledge Server")

    def fake_plan(*_args, **_kwargs):
        return _change_plan_result(_sample_change_plan())

    monkeypatch.setattr("app.integrations.ks_integration.KSClient.start", fail_ks_start)
    monkeypatch.setattr("app.services.regen_preview.run_change_plan", fake_plan)

    response = TestClient(app).get("/regen/preview")

    assert response.status_code == 200
    assert "Engine Change Plan" in response.text
