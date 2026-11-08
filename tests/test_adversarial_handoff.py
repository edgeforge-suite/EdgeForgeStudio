"""Request-driven regressions for the anonymous-session child boundary.

The marked tests additionally run installed Engine/KS children. They do not
select sibling pins: the operator supplies archived runtimes, as for L4 smoke.
"""

from __future__ import annotations

import asyncio
import builtins
import hashlib
import io
import json
import os
import re
import subprocess
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from app.integrations.ks_integration import KSCallError, KSClient
from app.models.project import KSManifestRevision
from app.services.csrf import CSRF_FORM_FIELD_NAME
from app.services.project_file_service import serialize_project, snapshot_session_for_save
from app.services.regen_binding import capture_generated_package
from app.services.request_resource_limits import reset_request_resource_limiter_for_testing
from app.services.session_context import _SQLITE_STORES
from app.services.settings import get_studio_settings
from tests.smoke._shared import (
    csrf_headers,
    export_package,
    make_exportable_smoke_session,
    new_shared_client,
    post_step1,
    save_session_for_client,
    session_for_client,
)


@pytest.fixture
def browsers(monkeypatch, tmp_path, request):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "synthetic-handoff-test-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED", "true")
    if request.node.get_closest_marker("smoke") is None:
        engine = tmp_path / "import-only-engine"
        engine.mkdir()
        monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_REPO", str(engine))

        def unexpected_child(*_args, **_kwargs):
            pytest.fail("Rejected request reached a child invocation")

        monkeypatch.setattr(
            "app.integrations.appbuilder_integration._run_subprocess", unexpected_child
        )
        monkeypatch.setattr(
            "app.integrations.appbuilder_integration._call_generate_app_mcp", unexpected_child
        )
        monkeypatch.setattr("app.integrations.ks_integration.KSClient.start", unexpected_child)
    # Undo the legacy suite's single deterministic ID, not the signed-cookie flow.
    monkeypatch.setattr("app.services.identity.secrets.token_urlsafe", lambda _n=24: uuid4().hex)
    _SQLITE_STORES.clear()
    pairs = [new_shared_client(), new_shared_client()]
    for index, (client, csrf) in enumerate(pairs):
        post_step1(
            client,
            csrf,
            app_name=f"Caller {index}",
            bounded_context=f"caller-{index}",
            output_path=tmp_path / "foreign-output",
        )
        session = session_for_client(client)
        make_exportable_smoke_session(
            session, entity_name=f"Record{index}", contract_name=f"record-{index}"
        )
        save_session_for_client(client, session)
    assert (
        session_for_client(pairs[0][0]).workspace_root
        != session_for_client(pairs[1][0]).workspace_root
    )
    yield pairs
    for client, _csrf in pairs:
        client.close()


def _import(client, csrf, session, **fields):
    project = json.loads(
        serialize_project(snapshot_session_for_save(session.model_copy(deep=True)))
    )
    project.update(fields)
    response = client.post(
        "/project/open",
        headers=csrf_headers(csrf),
        files={"project_file": ("synthetic.json", json.dumps(project), "application/json")},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text


@contextmanager
def _no_access(monkeypatch, forbidden):
    """Fail at the first attempted open, rather than merely checking no leakage."""
    forbidden = Path(forbidden).resolve()
    attempts = []
    real_io_open, real_open = io.open, builtins.open

    def guard(delegate):
        def opened(file, *args, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)):
                path = Path(os.fsdecode(file)).resolve()
                if path == forbidden or forbidden in path.parents:
                    attempts.append(str(path))
                    raise AssertionError("Unauthorized file open before boundary rejection")
            return delegate(file, *args, **kwargs)

        return opened

    with monkeypatch.context() as patch:
        patch.setattr(io, "open", guard(real_io_open))
        patch.setattr(builtins, "open", guard(real_open))
        yield attempts
    assert attempts == []


def _revision(path):
    return KSManifestRevision(
        revision_id="foreign-revision",
        exported_at="2026-10-02T00:00:00Z",
        manifest_hash="synthetic",
        archetype="crud",
        target_profile="springboot-standard-enterprise",
        export_path=str(path),
    )


def test_import_and_direct_requests_cannot_select_foreign_authoring(browsers, monkeypatch):
    (a, ca), (b, cb) = browsers
    victim = session_for_client(b)
    export_b = Path(export_package(b, cb)["output_dir"])
    before = (export_b / "app-definition.yaml").read_bytes()
    _import(
        a,
        ca,
        session_for_client(a),
        last_export_path=str(export_b),
        output_path=str(export_b),
        appbuilder_repo_path=str(export_b),
        workspace_root=victim.workspace_root,
        session_id=victim.session_id,
        manifest_revisions=[_revision(export_b).model_dump(mode="json")],
        last_generated_package_ref=str(export_b),
        manifest_hash="synthetic",
        baseline_hash="synthetic",
    )
    restored = session_for_client(a)
    assert restored.session_id != victim.session_id
    assert restored.workspace_root != victim.workspace_root
    assert restored.last_export_path is None
    with _no_access(monkeypatch, victim.workspace_root):
        query = f"?session_id={victim.session_id}&project_id={victim.project_id}"
        own = a.get("/review/manifest-preview" + query)
        assert own.status_code == 200 and "Record0" in own.json()["yaml"]
        assert "Record1" not in own.json()["yaml"]
        assert a.get("/review" + query).status_code == 200
        assert a.get("/regen/preview" + query).status_code == 200
        assert (
            a.post(
                "/regen/apply",
                headers=csrf_headers(ca),
                data={"approved_plan_hash": "foreign-plan"},
            ).status_code
            == 200
        )
        assert (
            a.post(
                "/entities/save" + query, headers=csrf_headers(cb), json={"entities": ["Record1"]}
            ).status_code
            == 403
        )
        assert (
            a.post(
                "/entities/save" + query,
                headers=csrf_headers(ca),
                json={"entities": ["Record0"], "operations": ["createRecord0"]},
            ).status_code
            == 200
        )
        own_export = Path(export_package(a, ca)["output_dir"])
        assert Path(restored.workspace_root) in own_export.parents
        assert a.get("/export/artifact/app-definition.yaml").status_code == 200
    assert (export_b / "app-definition.yaml").read_bytes() == before
    assert session_for_client(b).selected_entity_names == victim.selected_entity_names


@pytest.mark.parametrize("escape", ["absolute", "traversal", "symlink"])
def test_restored_export_is_rejected_before_read_or_child(browsers, monkeypatch, escape):
    (a, ca), (b, cb) = browsers
    victim = session_for_client(b)
    foreign = Path(export_package(b, cb)["output_dir"])
    current = session_for_client(a)
    workspace = Path(current.workspace_root)
    if escape == "absolute":
        target = foreign
    elif escape == "traversal":
        target = workspace / ".." / foreign.relative_to(workspace.parent)
    else:
        target = workspace / "escape"
        target.symlink_to(foreign, target_is_directory=True)
    # Persisted-state corruption is a defense-in-depth channel, not a user API.
    current.last_export_path = str(target)
    current.ks_workspace_state.manifest_revisions = [_revision(target)]
    save_session_for_client(a, current)
    with _no_access(monkeypatch, victim.workspace_root):
        for route in ("validate", "generate"):
            response = a.post(f"/export/{route}", headers=csrf_headers(ca))
            assert response.status_code == 400
            assert str(foreign) not in response.text
        assert a.get("/export/artifact/app-definition.yaml").status_code == 400
        assert a.get("/review").status_code == 200
        assert a.get("/regen/preview").status_code == 200


@pytest.mark.parametrize("route", ["artifact", "validate", "generate", "review"])
def test_manifest_symlink_is_rejected_before_foreign_read(browsers, monkeypatch, route):
    (a, ca), (b, cb) = browsers
    own = Path(export_package(a, ca)["output_dir"])
    foreign = Path(export_package(b, cb)["output_dir"])
    manifest = own / "app-definition.yaml"
    manifest.unlink()
    manifest.symlink_to(foreign / "app-definition.yaml")
    with _no_access(monkeypatch, session_for_client(b).workspace_root):
        if route == "artifact":
            response = a.get("/export/artifact/app-definition.yaml")
        elif route == "review":
            response = a.get("/review")
            assert response.status_code == 200
            assert "could not be read from disk" in response.text
            return
        else:
            response = a.post(f"/export/{route}", headers=csrf_headers(ca))
        assert response.status_code == 400


@pytest.mark.parametrize("escape", ["output-root", "package-dir", "artifact", "zip"])
def test_export_symlink_is_rejected_before_foreign_write(browsers, monkeypatch, escape):
    (a, ca), (b, _cb) = browsers
    workspace = Path(session_for_client(a).workspace_root)
    foreign = Path(session_for_client(b).workspace_root)
    sentinel = foreign / "app-definition.yaml"
    sentinel.write_text("foreign-sentinel", encoding="utf-8")
    if escape == "output-root":
        (workspace / "output").symlink_to(foreign, target_is_directory=True)
    elif escape == "package-dir":
        (workspace / "output").mkdir()
        (workspace / "output" / "caller-0").symlink_to(foreign, target_is_directory=True)
    elif escape == "artifact":
        own = workspace / "output" / "caller-0"
        own.mkdir(parents=True)
        (own / "app-definition.yaml").symlink_to(sentinel)
    else:
        (workspace / "exports").symlink_to(foreign, target_is_directory=True)
    with _no_access(monkeypatch, foreign):
        response = (
            a.get("/export/download-zip")
            if escape == "zip"
            else a.post("/export/write", headers=csrf_headers(ca))
        )
        assert response.status_code == 400
    assert sentinel.read_text(encoding="utf-8") == "foreign-sentinel"


@pytest.mark.parametrize("escape", ["ks-root", "db", "uploads", "upload-file"])
def test_ks_symlink_is_rejected_before_read_write_or_spawn(browsers, monkeypatch, escape):
    (a, ca), (b, _cb) = browsers
    workspace = Path(session_for_client(a).workspace_root)
    foreign = Path(session_for_client(b).workspace_root)
    sentinel = foreign / "marker.md"
    sentinel.write_text("foreign-ks-sentinel", encoding="utf-8")
    assert (
        a.post(
            "/",
            headers=csrf_headers(ca),
            data={
                "app_name": "Caller 0",
                "bounded_context": "caller-0",
                "target_profile": "springboot-standard-enterprise",
                "knowledge_assist_enabled": "on",
            },
            follow_redirects=False,
        ).status_code
        == 303
    )
    if escape == "ks-root":
        (workspace / "ks").symlink_to(foreign, target_is_directory=True)
    else:
        (workspace / "ks").mkdir()
        if escape == "db":
            (workspace / "ks" / "knowledge.sqlite3").symlink_to(foreign / "database.sqlite3")
        elif escape == "uploads":
            (workspace / "ks" / "uploads").symlink_to(foreign, target_is_directory=True)
        else:
            (workspace / "ks" / "uploads").mkdir()
            (workspace / "ks" / "uploads" / "marker.md").symlink_to(sentinel)
    with _no_access(monkeypatch, foreign):
        response = a.post(
            "/knowledge/upload",
            headers=csrf_headers(ca),
            files={"document_file": ("marker.md", "own-marker", "text/markdown")},
        )
        assert response.status_code == 400
        assert str(foreign) not in response.text
    assert sentinel.read_text(encoding="utf-8") == "foreign-ks-sentinel"


def test_generation_output_symlink_does_not_widen_engine_roots(browsers, monkeypatch):
    (a, ca), (b, _cb) = browsers
    own = Path(export_package(a, ca)["output_dir"])
    foreign = Path(session_for_client(b).workspace_root)
    (own / "generated-app").symlink_to(foreign, target_is_directory=True)
    with _no_access(monkeypatch, foreign):
        response = a.post("/export/generate", headers=csrf_headers(ca))
        assert response.status_code == 400


def test_nested_package_symlink_never_reaches_child(browsers, monkeypatch):
    (a, ca), (b, cb) = browsers
    own = Path(export_package(a, ca)["output_dir"])
    foreign = Path(export_package(b, cb)["output_dir"])
    (own / "contracts" / "hidden-input.yaml").symlink_to(foreign / "app-definition.yaml")
    with _no_access(monkeypatch, session_for_client(b).workspace_root):
        for route in ("validate", "generate"):
            response = a.post(f"/export/{route}", headers=csrf_headers(ca))
            assert response.status_code == 400 and "symlink" in response.text


def _seed_regen_binding(client, export):
    generated = export / "generated-app"
    (generated / "db").mkdir(parents=True)
    (generated / "db" / "schema-baseline.json").write_text('{"entities":[]}\n')
    session = session_for_client(client)
    capture_generated_package(
        session, generated_package_path=generated,
        manifest_path=export / "app-definition.yaml",
    )
    save_session_for_client(client, session)
    manifest = export / "app-definition.yaml"
    manifest.write_text(manifest.read_text() + "\n# synthetic input change\n")
    return Path(session.workspace_root) / session.last_generated_package_ref


@pytest.mark.parametrize("route", ["preview", "apply"])
@pytest.mark.parametrize("package", ["export", "managed"])
@pytest.mark.parametrize("kind", ["file", "directory"])
def test_regen_package_symlinks_reject_before_read_or_child(
    browsers, monkeypatch, route, package, kind,
):
    (a, ca), (b, cb) = browsers
    own = Path(export_package(a, ca)["output_dir"])
    foreign = Path(export_package(b, cb)["output_dir"])
    managed = _seed_regen_binding(a, own)
    root = own if package == "export" else managed
    link = root / "nested-input"
    target = foreign / "contracts" if kind == "directory" else foreign / "app-definition.yaml"
    link.symlink_to(target, target_is_directory=kind == "directory")
    before = _tree_hashes(Path(session_for_client(b).workspace_root))
    with _no_access(monkeypatch, session_for_client(b).workspace_root):
        response = (
            a.get("/regen/preview") if route == "preview" else a.post(
                "/regen/apply",
                data={CSRF_FORM_FIELD_NAME: ca, "approved_plan_hash": "synthetic-approved"},
            )
        )
        assert response.status_code == 200 and "symlink" in response.text
        assert str(target) not in response.text
    assert _tree_hashes(Path(session_for_client(b).workspace_root)) == before


@pytest.mark.parametrize("operation", ["plan", "apply"])
@pytest.mark.parametrize("package", ["export", "managed"])
@pytest.mark.parametrize("kind", ["file", "directory"])
def test_direct_regen_adapter_rejects_nested_symlinks(
    browsers, monkeypatch, operation, package, kind,
):
    from app.integrations import appbuilder_integration as integration

    (a, ca), (b, cb) = browsers
    own = Path(export_package(a, ca)["output_dir"])
    foreign = Path(export_package(b, cb)["output_dir"])
    managed = _seed_regen_binding(a, own)
    root = own if package == "export" else managed
    target = foreign if kind == "directory" else foreign / "app-definition.yaml"
    (root / "foreign-input").symlink_to(target, target_is_directory=kind == "directory")
    call = integration.run_change_plan if operation == "plan" else integration.run_apply
    kwargs = {} if operation == "plan" else {"approved_plan_hash": "synthetic-approved"}
    with _no_access(monkeypatch, session_for_client(b).workspace_root):
        result = call(
            own / "app-definition.yaml", managed, os.environ["EDGEFORGE_STUDIO_ENGINE_REPO"],
            allowed_roots=[str(own), str(managed)], **kwargs,
        )
        assert not result.success and "symlink" in result.error


@pytest.mark.parametrize("operation", ["plan", "apply"])
def test_local_regen_adapter_preserves_operator_symlinks(monkeypatch, tmp_path, operation):
    from app.integrations import appbuilder_integration as integration

    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "false")
    repo = tmp_path / "engine"
    repo.mkdir()
    export = tmp_path / "export"
    export.mkdir()
    manifest = export / "app-definition.yaml"
    manifest.write_text("schema_version: '2.0'\n")
    package = tmp_path / "package"
    package.mkdir()
    (package / "operator-link").symlink_to(manifest)
    calls = []

    def child(command, **kwargs):
        calls.append(command)
        return integration.SubprocessResult(
            success=True, returncode=0, stdout='{"plan_hash":"synthetic-own"}',
            stderr="", combined_output="own local control", duration_seconds=0,
            command=command, cwd=kwargs["cwd"],
        )

    monkeypatch.setattr(integration, "_run_subprocess", child)
    call = integration.run_change_plan if operation == "plan" else integration.run_apply
    kwargs = {} if operation == "plan" else {"approved_plan_hash": "synthetic-own"}
    result = call(manifest, package, str(repo), allowed_roots=[str(export), str(package)], **kwargs)
    assert result.success and len(calls) == 1


def test_invalid_cookie_and_foreign_ids_do_not_select_victim(browsers, monkeypatch):
    (a, _ca), (b, cb) = browsers
    victim = session_for_client(b)
    export_package(b, cb)
    cookie_name = get_studio_settings().session_cookie_name
    token = a.cookies.get(cookie_name)
    a.cookies.clear()
    a.cookies.set(cookie_name, token + "tampered", domain="testserver.local", path="/")
    with _no_access(monkeypatch, victim.workspace_root):
        page = a.get("/", params={"session_id": victim.session_id})
        assert page.status_code == 200
        assert session_for_client(a).session_id != victim.session_id
        assert a.get("/export/artifact/app-definition.yaml").status_code == 404


@pytest.mark.parametrize("path", ["/foreign/marker.yaml", "../../marker.yaml"])
def test_imported_package_artifact_paths_are_not_writable(browsers, monkeypatch, path):
    (a, ca), (b, _cb) = browsers
    current = session_for_client(a)
    project = json.loads(serialize_project(snapshot_session_for_save(current)))
    project["upstream_interfaces"][0]["mapping_path"] = path
    _import(a, ca, current, upstream_interfaces=project["upstream_interfaces"])
    with _no_access(monkeypatch, session_for_client(b).workspace_root):
        response = a.post("/export/write", headers=csrf_headers(ca))
        assert response.status_code == 400


def _tree_hashes(root):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _require_runtime(variable, module):
    value = os.environ.get(variable)
    if not value:
        pytest.skip(f"Live handoff proof requires {variable}")
    repo = Path(value)
    assert (repo / module).is_dir()
    assert (repo / ".venv/bin/python").is_file()
    return repo


def _observe_children(monkeypatch):
    children = []
    real_popen = subprocess.Popen

    class ObservedPopen(real_popen):
        def __init__(self, command, *args, **kwargs):
            env = kwargs.get("env") or {}
            record = None
            if any(
                str(part) in {"appbuilder.mcp_server", "appbuilder.cli", "knowledge_server.server"}
                for part in command
            ):
                record = {
                    "command": list(command),
                    "cwd": str(kwargs.get("cwd")),
                    "env": {
                        key: env.get(key)
                        for key in (
                            "EDGEFORGE_SHARED_MODE",
                            "EDGEFORGE_MCP_ALLOWED_ROOTS",
                            "EDGEFORGE_KS_ALLOWED_ROOTS",
                            "EDGEFORGE_KS_DB_PATH",
                        )
                    },
                }
                children.append(record)
            try:
                super().__init__(command, *args, **kwargs)
            except OSError:
                if record is not None:
                    record["started"] = False
                raise
            if record is not None:
                record["started"] = True

    monkeypatch.setattr(subprocess, "Popen", ObservedPopen)
    return children


@pytest.mark.smoke
@pytest.mark.l4
def test_live_regen_request_package_preflight(browsers, monkeypatch):
    engine = _require_runtime("EDGEFORGE_STUDIO_ENGINE_REPO", "appbuilder")
    monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_MCP_COMMAND", str(engine / ".venv/bin/python"))
    monkeypatch.setenv("EDGEFORGE_SHARED_MODE", "0")
    monkeypatch.setenv("EDGEFORGE_MCP_ALLOWED_ROOTS", str(engine))
    children = _observe_children(monkeypatch)

    def forbidden_ks(_self):
        pytest.fail("KA OFF regeneration must never start KS")

    monkeypatch.setattr(KSClient, "start", forbidden_ks)
    exports = []
    for client, csrf in browsers:
        own = Path(export_package(client, csrf)["output_dir"])
        response = client.post("/export/generate", headers=csrf_headers(csrf))
        assert response.status_code == 200 and response.json()["ok"], response.text
        exports.append(own)
    (a, ca), (b, _cb) = browsers
    manifest = exports[0] / "app-definition.yaml"
    manifest.write_text(manifest.read_text() + "\n# synthetic regen control\n")
    preview = a.get("/regen/preview")
    match = re.search(r'name="approved_plan_hash" value="([^"]+)"', preview.text)
    assert preview.status_code == 200 and match, preview.text
    applied = a.post(
        "/regen/apply", data={CSRF_FORM_FIELD_NAME: ca, "approved_plan_hash": match[1]},
    )
    assert applied.status_code == 200 and "Additive Change Plan applied" in applied.text, applied.text
    # Regen CLI uses Studio's interpreter by contract; MCP generation uses the
    # isolated Engine interpreter. Observe both without rewriting either command.
    import sys

    cli_children = [child for child in children if "appbuilder.cli" in child["command"]]
    assert {child["command"][3] for child in cli_children} == {"plan", "apply"}
    for child in cli_children:
        assert child["started"] and child["command"][0] == sys.executable
        assert child["cwd"] == str(engine)
        assert child["env"]["EDGEFORGE_SHARED_MODE"] == "1"
        roots = child["env"]["EDGEFORGE_MCP_ALLOWED_ROOTS"].split(os.pathsep)
        assert str(engine) not in roots
        assert all(Path(session_for_client(a).workspace_root) in Path(root).parents for root in roots)

    manifest.write_text(manifest.read_text() + "\n# synthetic hostile-state probe\n")
    session = session_for_client(a)
    managed = Path(session.workspace_root) / session.last_generated_package_ref
    victim_root = Path(session_for_client(b).workspace_root)
    victim_spec = exports[1] / "contracts" / "record-1-openapi.yaml"
    victim_spec.write_text("private-regeneration-marker: [invalid synthetic YAML\n")
    victim_hashes = _tree_hashes(victim_root)
    for root in (exports[0], managed):
        for kind in ("file", "directory"):
            reset_request_resource_limiter_for_testing()
            backup = None
            original = None
            if root == exports[0]:
                link = root / "contracts"
                if kind == "file":
                    link = link / "record-0-openapi.yaml"
                    original = link.read_bytes()
                    link.unlink()
                else:
                    backup = root / "contracts-owned"
                    link.rename(backup)
            else:
                link = root / "foreign-input"
            target = exports[1] / "contracts" if kind == "directory" else victim_spec
            link.symlink_to(target, target_is_directory=kind == "directory")
            before_children = len(children)
            with _no_access(monkeypatch, victim_root):
                preview = a.get("/regen/preview")
                applied = a.post(
                    "/regen/apply", data={CSRF_FORM_FIELD_NAME: ca, "approved_plan_hash": match[1]},
                )
                for response in (preview, applied):
                    assert response.status_code == 200 and "symlink" in response.text
                    assert str(target) not in response.text
                    assert "private-regeneration-marker" not in response.text
                assert len(children) == before_children
            link.unlink()
            if original is not None:
                link.write_bytes(original)
            if backup is not None:
                backup.rename(link)
            assert _tree_hashes(victim_root) == victim_hashes
    reset_request_resource_limiter_for_testing()
    own_control = a.get("/regen/preview")
    assert own_control.status_code == 200 and "approved_plan_hash" in own_control.text
    print("HANDOFF_REGEN_CHILDREN=" + json.dumps(children, sort_keys=True))
    print("HANDOFF_REGEN_NEGATIVES=8 responses; zero child starts; zero foreign opens")


@pytest.mark.smoke
@pytest.mark.l4
def test_live_engine_request_handoff(browsers, monkeypatch, tmp_path):
    engine = _require_runtime("EDGEFORGE_STUDIO_ENGINE_REPO", "appbuilder")
    monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_MCP_COMMAND", str(engine / ".venv/bin/python"))
    monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_TRANSPORT", "subprocess")
    monkeypatch.setenv("EDGEFORGE_SHARED_MODE", "0")
    monkeypatch.setenv("EDGEFORGE_MCP_ALLOWED_ROOTS", str(tmp_path) + os.pathsep + str(engine))
    children = _observe_children(monkeypatch)

    def forbidden_ks(_self):
        pytest.fail("KA OFF must never start KS")

    monkeypatch.setattr(KSClient, "start", forbidden_ks)
    from app.integrations import appbuilder_integration as integration

    payloads = []
    observed_envs = []
    real_format = integration._format_mcp_generation_output
    real_env = integration._mcp_env

    def produced_env(*args, **kwargs):
        env = real_env(*args, **kwargs)
        observed_envs.append(env.copy())
        return env

    def formatted(payload):
        payloads.append(payload)
        return real_format(payload)

    monkeypatch.setattr(integration, "_format_mcp_generation_output", formatted)
    monkeypatch.setattr(integration, "_mcp_env", produced_env)
    outputs = []
    for client, csrf in browsers:
        _import(client, csrf, session_for_client(client))
        own = Path(export_package(client, csrf)["output_dir"])
        response = client.post("/export/generate", headers=csrf_headers(csrf))
        assert response.status_code == 200 and response.json()["ok"], response.text
        output = own / "generated-app"
        assert (output / "pom.xml").is_file()
        outputs.append(output)
        assert client.get("/review").status_code == 200
        assert client.get("/knowledge", follow_redirects=False).status_code == 303
    assert len(children) == 2, children
    for child, output in zip(children, outputs, strict=True):
        assert "appbuilder.mcp_server" in child["command"]
        assert child["command"][0] == str(engine / ".venv/bin/python")
        assert child["env"]["EDGEFORGE_SHARED_MODE"] == "1"
        assert child["env"]["EDGEFORGE_MCP_ALLOWED_ROOTS"] == str(output.parent)
    # The route still chooses the roots. Only persisted package inputs are hostile.
    (a, ca), (b, _cb) = browsers
    victim = outputs[1].parent / "contracts" / "record-1-openapi.yaml"
    own_manifest = outputs[0].parent / "app-definition.yaml"
    assert victim.is_file()
    original = own_manifest.read_text(encoding="utf-8")
    victim_hashes = _tree_hashes(Path(session_for_client(b).workspace_root))
    own_output_hashes = _tree_hashes(outputs[0])
    link = own_manifest.parent / "foreign-spec.yaml"
    references = [
        str(victim),
        os.path.relpath(victim, own_manifest.parent),
        link.name,
        str(engine / "README.md"),
    ]
    for reference in references:
        if reference == link.name:
            link.symlink_to(victim)
        payload = yaml.safe_load(original)
        payload["upstream_interfaces"][0]["spec"] = reference
        own_manifest.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        previous_children = len(children)
        rejected = a.post("/export/generate", headers=csrf_headers(ca))
        if reference == link.name:
            assert rejected.status_code == 400 and "symlink" in rejected.text
            assert len(children) == previous_children
            link.unlink()
        else:
            assert rejected.status_code == 200 and rejected.json()["ok"] is False, rejected.text
            assert payloads[-1]["success"] is False
            assert "invalid manifest" in " ".join(payloads[-1]["errors"]).lower(), payloads[-1]
            print("HANDOFF_NEGATIVE_RESULT=" + json.dumps(payloads[-1], sort_keys=True))
        assert str(victim) not in rejected.text and str(engine) not in rejected.text
        assert children[-1]["env"]["EDGEFORGE_MCP_ALLOWED_ROOTS"] == str(outputs[0].parent)
        assert _tree_hashes(Path(session_for_client(b).workspace_root)) == victim_hashes
        assert _tree_hashes(outputs[0]) == own_output_hashes
    # Replay the config OBSERVED from the real HTTP caller, not preselected roots.
    # This auxiliary probe reaches the frozen child's entrypoint path checks.
    from fastmcp import Client
    from fastmcp.exceptions import ToolError

    child = children[0]
    config = {
        "mcpServers": {
            "observed-engine": {
                "command": child["command"][0],
                "args": child["command"][1:],
                "cwd": child["cwd"],
                "env": observed_envs[0],
            }
        }
    }
    foreign_output = Path(session_for_client(b).workspace_root) / "must-not-be-created"

    async def child_entrypoint_probes():
        async with Client(config) as client:
            for manifest, output in ((victim, outputs[0]), (own_manifest, foreign_output)):
                with pytest.raises(ToolError, match="inside an allowed root"):
                    await client.call_tool(
                        "generate_app", {"manifest_path": str(manifest), "output_dir": str(output)}
                    )

    own_manifest.write_text(original, encoding="utf-8")
    asyncio.run(child_entrypoint_probes())
    assert not foreign_output.exists()
    assert _tree_hashes(Path(session_for_client(b).workspace_root)) == victim_hashes
    assert _tree_hashes(outputs[0]) == own_output_hashes
    # A genuinely unavailable child must not turn into a shared CLI generation.
    # Separate cases must not exhaust the production six-request quota window.
    reset_request_resource_limiter_for_testing()
    monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_MCP_COMMAND", str(tmp_path / "missing-python"))
    before_unavailable = len(children)
    unavailable = a.post("/export/generate", headers=csrf_headers(ca))
    assert unavailable.json()["ok"] is False
    assert "subprocess fallback is disabled" in unavailable.text
    assert str(tmp_path / "missing-python") not in unavailable.text
    assert all("appbuilder.cli" not in child["command"] for child in children)
    assert before_unavailable == 6 and all(child["started"] for child in children[:6])
    assert len(children) in {6, 7}
    if len(children) == 7:
        assert children[-1]["started"] is False
    print("HANDOFF_UNAVAILABLE=" + json.dumps(unavailable.json(), sort_keys=True))
    print(
        "HANDOFF_ENGINE_RESULTS="
        + json.dumps(
            [
                {
                    "success": payload["success"],
                    "errors": payload.get("errors", []),
                    "files_written": len(payload.get("files_written", [])),
                }
                for payload in payloads
            ],
            sort_keys=True,
        )
    )
    print("HANDOFF_VICTIM_HASHES=" + json.dumps(victim_hashes, sort_keys=True))
    print("HANDOFF_ENGINE_CHILDREN=" + json.dumps(children, sort_keys=True))


@pytest.mark.smoke
@pytest.mark.l4
def test_live_ks_request_handoff(browsers, monkeypatch, tmp_path):
    ks = _require_runtime("EDGEFORGE_STUDIO_KS_REPO", "knowledge_server")
    monkeypatch.setenv("EDGEFORGE_STUDIO_KS_COMMAND", str(ks / ".venv/bin/python"))
    monkeypatch.setenv("EDGEFORGE_SHARED_MODE", "0")
    monkeypatch.setenv("EDGEFORGE_KS_ALLOWED_ROOTS", str(tmp_path))
    monkeypatch.setenv("EDGEFORGE_KS_DB_PATH", str(tmp_path / "hostile.sqlite3"))
    children = _observe_children(monkeypatch)
    route_clients = []
    real_call = KSClient.call

    def call(client, tool, arguments):
        if client not in route_clients:
            route_clients.append(client)
        return real_call(client, tool, arguments)

    monkeypatch.setattr(KSClient, "call", call)
    document_ids = []
    for index, (client, csrf) in enumerate(browsers):
        response = client.post(
            "/",
            headers=csrf_headers(csrf),
            data={
                "app_name": f"Caller {index}",
                "bounded_context": f"caller-{index}",
                "target_profile": "springboot-standard-enterprise",
                "knowledge_assist_enabled": "on",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        upload = client.post(
            "/knowledge/upload",
            headers=csrf_headers(csrf),
            files={
                "document_file": (
                    f"marker-{index}.md",
                    f"# Marker\n\nprivate-marker-{index}",
                    "text/markdown",
                )
            },
        )
        assert upload.status_code == 200, upload.text
        assert upload.context["status_type"] == "success", upload.context["status_message"]
        page = client.get("/knowledge?q=marker")
        plain = page.text.replace("[", "").replace("]", "")
        assert f"private-marker-{index}" in plain, page.context["ks_warning"]
        assert f"private-marker-{1 - index}" not in plain
        document_ids.append(page.context["documents"][0]["document_id"])
    assert len(children) == 2, children
    for child, (client, _csrf) in zip(children, browsers, strict=True):
        root = Path(session_for_client(client).workspace_root) / "ks"
        assert child["env"]["EDGEFORGE_SHARED_MODE"] == "1"
        assert child["env"]["EDGEFORGE_KS_ALLOWED_ROOTS"] == str(root)
        assert child["env"]["EDGEFORGE_KS_DB_PATH"] == str(root / "knowledge.sqlite3")
        assert (root / "knowledge.sqlite3").is_file()
    assert not (tmp_path / "hostile.sqlite3").exists()
    (a, ca), (b, _cb) = browsers
    foreign_read = a.get(
        "/knowledge",
        params={"document_id": document_ids[1], "project_id": session_for_client(b).project_id},
    )
    assert "private-marker-1" not in foreign_read.text
    deleted = a.post(
        "/knowledge/delete",
        headers=csrf_headers(ca),
        data={"document_id": document_ids[1], "document_name": "foreign"},
    )
    assert deleted.status_code == 400
    own_read = b.get("/knowledge", params={"document_id": document_ids[1]})
    assert "private-marker-1" in own_read.text
    # Auxiliary child probe on the SAME client instantiated by the real route;
    # roots/DB are not supplied by the test. There is no public file-path API.
    sentinel = Path(session_for_client(b).workspace_root) / "foreign-probe.md"
    sentinel.write_text("foreign-child-sentinel", encoding="utf-8")
    with pytest.raises(KSCallError) as rejected:
        route_clients[0].ingest_document(
            project_id=session_for_client(a).project_id,
            file_path=str(sentinel),
            doc_type="markdown",
        )
    assert str(sentinel) not in str(rejected.value)
    assert "foreign-child-sentinel" not in str(rejected.value)
    assert sentinel.read_text(encoding="utf-8") == "foreign-child-sentinel"
    print("HANDOFF_KS_CHILDREN=" + json.dumps(children, sort_keys=True))
