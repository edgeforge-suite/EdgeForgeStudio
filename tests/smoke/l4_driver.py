from __future__ import annotations

import itertools
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.integrations.appbuilder_integration import _engine_subprocess_env
from app.services.ks_lifecycle import (
    ks_client as lifecycle_ks_client,
)
from app.services.ks_lifecycle import (
    reset_ks_lifecycle_for_testing,
)
from app.services.request_resource_limits import reset_request_resource_limiter_for_testing
from app.services.session_context import _SQLITE_STORES
from tests.smoke._shared import (
    assert_no_ka_noise,
    assert_path_under,
    csrf_headers,
    export_package,
    make_exportable_smoke_session,
    new_shared_client,
    post_step1,
    save_session_for_client,
    session_for_client,
    upload_openapi,
)

SHARED_SECRET = "l4-shared-mode-smoke-secret"


def run_author_generate_isolation(*, root: Path) -> dict[str, Any]:
    with _shared_mode_environment(root), _ka_off_spy() as ks_calls:
        client_a, csrf_a = new_shared_client()
        client_b, csrf_b = new_shared_client()
        evil_a = root.parent / f"{root.name}-evil-a"
        evil_b = root.parent / f"{root.name}-evil-b"

        post_step1(
            client_a,
            csrf_a,
            app_name="Alpha Smoke App",
            bounded_context="alpha-smoke",
            output_path=evil_a,
        )
        post_step1(
            client_b,
            csrf_b,
            app_name="Beta Smoke App",
            bounded_context="beta-smoke",
            output_path=evil_b,
        )
        upload_openapi(client_a, csrf_a, filename="alpha-openapi.yaml", entity_name="Alpha")
        upload_openapi(client_b, csrf_b, filename="beta-openapi.yaml", entity_name="Beta")

        session_a = session_for_client(client_a)
        session_b = session_for_client(client_b)
        workspace_a = Path(session_a.workspace_root or "")
        workspace_b = Path(session_b.workspace_root or "")
        make_exportable_smoke_session(session_a, entity_name="Alpha", contract_name="alpha")
        make_exportable_smoke_session(session_b, entity_name="Beta", contract_name="beta")
        save_session_for_client(client_a, session_a)
        save_session_for_client(client_b, session_b)

        export_a = export_package(client_a, csrf_a)
        export_b = export_package(client_b, csrf_b)
        generate_a = _post_generate(client_a, csrf_a)
        generate_b = _post_generate(client_b, csrf_b)

        output_a = Path(generate_a["output_dir"])
        output_b = Path(generate_b["output_dir"])
        assert_path_under(output_a, workspace_a)
        assert_path_under(output_b, workspace_b)

        return {
            "ka_off_silent": ks_calls == [],
            "ks_calls": list(ks_calls),
            "workspace_a": str(workspace_a),
            "workspace_b": str(workspace_b),
            "export_a": export_a["output_dir"],
            "export_b": export_b["output_dir"],
            "generated_a": str(output_a),
            "generated_b": str(output_b),
            "distinct_workspaces": workspace_a != workspace_b,
            "distinct_generated_outputs": output_a != output_b,
            "output_a_under_workspace": _is_relative_to(output_a, workspace_a),
            "output_b_under_workspace": _is_relative_to(output_b, workspace_b),
            "evil_a_exists": evil_a.exists(),
            "evil_b_exists": evil_b.exists(),
            "alpha_in_a": _tree_contains(output_a, "Alpha"),
            "beta_in_a": _tree_contains(output_a, "Beta"),
            "beta_in_b": _tree_contains(output_b, "Beta"),
            "alpha_in_b": _tree_contains(output_b, "Alpha"),
        }


def run_ks_per_session_isolation(*, root: Path) -> dict[str, Any]:
    with _shared_mode_environment(root), _ks_child_env_spy() as child_envs:
        client_a, csrf_a = new_shared_client()
        client_b, csrf_b = new_shared_client()

        post_step1(
            client_a,
            csrf_a,
            app_name="Alpha KS Smoke App",
            bounded_context="alpha-ks-smoke",
            output_path=root / "ignored-alpha-output",
        )
        post_step1(
            client_b,
            csrf_b,
            app_name="Beta KS Smoke App",
            bounded_context="beta-ks-smoke",
            output_path=root / "ignored-beta-output",
        )
        session_a = session_for_client(client_a)
        session_b = session_for_client(client_b)
        session_a.capabilities.knowledge_assist_enabled = True
        session_b.capabilities.knowledge_assist_enabled = True
        save_session_for_client(client_a, session_a)
        save_session_for_client(client_b, session_b)

        _upload_knowledge_doc(
            client_a,
            csrf_a,
            filename="alpha-marker.md",
            content="# Alpha\n\nalpha-marker is present only in browser A.\n",
        )
        _upload_knowledge_doc(
            client_b,
            csrf_b,
            filename="beta-marker.md",
            content="# Beta\n\nbeta-marker is present only in browser B.\n",
        )

        page_a = client_a.get("/knowledge?q=marker")
        page_b = client_b.get("/knowledge?q=marker")
        assert page_a.status_code == 200
        assert page_b.status_code == 200

        session_a = session_for_client(client_a)
        session_b = session_for_client(client_b)
        workspace_a = Path(session_a.workspace_root or "")
        workspace_b = Path(session_b.workspace_root or "")
        db_a = workspace_a / "ks" / "knowledge.sqlite3"
        db_b = workspace_b / "ks" / "knowledge.sqlite3"
        child_db_paths = [child["db_path"] for child in child_envs]
        child_roots = [child["allowed_roots"] for child in child_envs]
        expected_workspaces = [workspace_a, workspace_b]
        parsed_child_roots = [
            [
                str(Path(root.strip()).expanduser().resolve(strict=False))
                for root in (raw_roots or "").split(os.pathsep)
                if root.strip()
            ]
            for raw_roots in child_roots
        ]
        expected_child_roots = [
            str((workspace / "ks").resolve(strict=False))
            for workspace in expected_workspaces
        ]

        return {
            "workspace_a": str(workspace_a),
            "workspace_b": str(workspace_b),
            "ks_db_a": str(db_a),
            "ks_db_b": str(db_b),
            "distinct_workspaces": workspace_a != workspace_b,
            "distinct_ks_dbs": db_a != db_b,
            "db_a_under_workspace": _is_relative_to(db_a, workspace_a),
            "db_b_under_workspace": _is_relative_to(db_b, workspace_b),
            "alpha_result_has_alpha": "alpha-marker" in page_a.text,
            "alpha_result_has_beta": "beta-marker" in page_a.text,
            "beta_result_has_beta": "beta-marker" in page_b.text,
            "beta_result_has_alpha": "alpha-marker" in page_b.text,
            "ks_children_spawned": len(child_envs),
            "shared_mode_flag_per_child": [
                child["shared_mode"] for child in child_envs
            ],
            "db_path_per_child": child_db_paths,
            "allowed_roots_per_child": child_roots,
            "parsed_allowed_roots_per_child": parsed_child_roots,
            "expected_allowed_root_per_child": expected_child_roots,
            "child_db_paths_distinct": (
                len(child_db_paths) == 2 and len(set(child_db_paths)) == 2
            ),
            "child_roots_distinct": (
                len(child_roots) == 2 and len(set(child_roots)) == 2
            ),
            "child_roots_under_own_workspace": (
                len(parsed_child_roots) == 2
                and all(
                    roots
                    and all(
                        _is_relative_to(Path(root), workspace)
                        for root in roots
                    )
                    for roots, workspace in zip(
                        parsed_child_roots,
                        expected_workspaces,
                        strict=True,
                    )
                )
            ),
            "child_roots_match_expected": (
                len(parsed_child_roots) == 2
                and all(
                    roots == [expected]
                    for roots, expected in zip(
                        parsed_child_roots,
                        expected_child_roots,
                        strict=True,
                    )
                )
            ),
            "child_db_under_own_workspace": (
                len(child_db_paths) == 2
                and all(
                    db_path is not None
                    and _is_relative_to(Path(db_path), workspace)
                    for db_path, workspace in zip(
                        child_db_paths,
                        expected_workspaces,
                        strict=True,
                    )
                )
            ),
        }


def run_ks_solo_child_environment(*, root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    allowed_root = root / "docs"
    allowed_root.mkdir()
    db_path = root / "knowledge.sqlite3"

    with _solo_mode_parent_shared_flag(), _ks_child_env_spy() as child_envs:
        with lifecycle_ks_client(
            allowed_roots=[str(allowed_root)],
            db_path=str(db_path),
        ) as client:
            result = client.list_documents(project_id="solo-mode-propagation-smoke")

        return {
            "ks_children_spawned": len(child_envs),
            "shared_mode_flag_per_child": [
                child["shared_mode"] for child in child_envs
            ],
            "db_path_per_child": [child["db_path"] for child in child_envs],
            "allowed_roots_per_child": [
                child["allowed_roots"] for child in child_envs
            ],
            "list_documents_succeeded": isinstance(result.get("documents"), list),
        }


def run_studio_l4_smoke(*, root: Path) -> dict[str, Any]:
    return {
        "author_generate": run_author_generate_isolation(root=root / "author-generate"),
        "ks_isolation": run_ks_per_session_isolation(root=root / "ks-isolation"),
        "engine_fail_closed": run_engine_fail_closed_isolation(root=root / "engine-fail-closed"),
    }


def run_engine_fail_closed_isolation(*, root: Path) -> dict[str, Any]:
    """Drive Engine CLI fail-closed checks with controlled allowed roots.

    Studio's normal shared-mode generate path derives roots from the manifest
    and output path, so this smoke intentionally calls the Engine CLI directly
    with A's session root pinned as the only allowed root.
    """
    with _shared_mode_environment(root), _ka_off_spy() as ks_calls:
        client_a, csrf_a = new_shared_client()
        client_b, csrf_b = new_shared_client()

        post_step1(
            client_a,
            csrf_a,
            app_name="Alpha Fail Closed App",
            bounded_context="alpha-fail-closed",
            output_path=root / "ignored-alpha-output",
        )
        post_step1(
            client_b,
            csrf_b,
            app_name="Beta Fail Closed App",
            bounded_context="beta-fail-closed",
            output_path=root / "ignored-beta-output",
        )

        session_a = session_for_client(client_a)
        session_b = session_for_client(client_b)
        workspace_a = Path(session_a.workspace_root or "")
        workspace_b = Path(session_b.workspace_root or "")
        make_exportable_smoke_session(session_a, entity_name="Alpha", contract_name="alpha")
        save_session_for_client(client_a, session_a)

        export_a = export_package(client_a, csrf_a)
        manifest = Path(export_a["output_dir"]) / "app-definition.yaml"
        assert manifest.exists()
        assert_path_under(manifest, workspace_a)

        engine_repo = _engine_repo_from_env()
        symlink_outside = root / "symlink-outside-target"
        symlink_outside.mkdir(parents=True, exist_ok=True)
        symlink_path = workspace_a / "escape-link"
        if symlink_path.exists() or symlink_path.is_symlink():
            symlink_path.unlink()
        symlink_path.symlink_to(symlink_outside, target_is_directory=True)

        negative_specs = [
            ("engine_repo_output", engine_repo / f"_studio_l4_escape_{root.name}"),
            ("traversal_output", workspace_a / ".." / f"_studio_l4_escape_{root.name}"),
            ("symlink_escape_output", symlink_path / "generated-app"),
            ("sibling_session_output", workspace_b / "_cross-write"),
        ]
        negatives = [
            _run_fail_closed_case(
                name=name,
                manifest=manifest,
                output=output,
                engine_repo=engine_repo,
                allowed_roots=[workspace_a],
                expected_message="must resolve inside an allowed root",
            )
            for name, output in negative_specs
        ]
        missing_roots = _run_fail_closed_case(
            name="missing_roots",
            manifest=manifest,
            output=workspace_a / "missing-roots-generated-app",
            engine_repo=engine_repo,
            allowed_roots=[],
            expected_message="must be set to per-session",
        )
        positive = _engine_cli_generate(
            manifest=manifest,
            output=workspace_a / "generated-app",
            engine_repo=engine_repo,
            allowed_roots=[workspace_a],
            shared_mode=True,
        )

        return {
            "ka_off_silent": ks_calls == [],
            "ks_calls": list(ks_calls),
            "workspace_a": str(workspace_a),
            "workspace_b": str(workspace_b),
            "engine_repo": str(engine_repo),
            "distinct_workspaces": workspace_a != workspace_b,
            "negative_cases": negatives,
            "missing_roots": missing_roots,
            "positive_control": {
                "returncode": positive["returncode"],
                "succeeded": positive["returncode"] == 0,
                "output_exists": Path(positive["target"]).exists(),
                "target": positive["target"],
                "combined_output": positive["combined_output"],
            },
        }


@contextmanager
def _shared_mode_environment(root: Path) -> Iterator[None]:
    keys = (
        "EDGEFORGE_STUDIO_SHARED_MODE",
        "EDGEFORGE_STUDIO_SESSION_SECRET",
        "EDGEFORGE_STUDIO_STATE_DIR",
        "EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE",
        "EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS",
        "EDGEFORGE_STUDIO_BUILD_RUN_ENABLED",
    )
    original = {key: os.environ.get(key) for key in keys}
    import app.services.identity as identity

    original_token_urlsafe = identity.secrets.token_urlsafe
    session_counter = itertools.count(1)
    try:
        _configure_shared_mode(root)
        identity.secrets.token_urlsafe = (
            lambda _n=24: f"l4-session-{next(session_counter)}"
        )
        yield
    finally:
        identity.secrets.token_urlsafe = original_token_urlsafe
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        _SQLITE_STORES.clear()
        reset_ks_lifecycle_for_testing()
        reset_request_resource_limiter_for_testing()


def _configure_shared_mode(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    os.environ["EDGEFORGE_STUDIO_SHARED_MODE"] = "true"
    os.environ["EDGEFORGE_STUDIO_SESSION_SECRET"] = SHARED_SECRET
    os.environ["EDGEFORGE_STUDIO_STATE_DIR"] = str(root / "studio-state")
    os.environ["EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE"] = "allowlist"
    os.environ.pop("EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS", None)
    os.environ.pop("EDGEFORGE_STUDIO_BUILD_RUN_ENABLED", None)
    _SQLITE_STORES.clear()
    reset_ks_lifecycle_for_testing()
    reset_request_resource_limiter_for_testing()


@contextmanager
def _solo_mode_parent_shared_flag() -> Iterator[None]:
    keys = (
        "EDGEFORGE_STUDIO_SHARED_MODE",
        "STUDIO_SHARED_MODE",
        "EDGEFORGE_SHARED_MODE",
    )
    original = {key: os.environ.get(key) for key in keys}
    try:
        os.environ.pop("EDGEFORGE_STUDIO_SHARED_MODE", None)
        os.environ.pop("STUDIO_SHARED_MODE", None)
        os.environ["EDGEFORGE_SHARED_MODE"] = "1"
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def _ks_child_env_spy() -> Iterator[list[dict[str, str | None]]]:
    import app.integrations.ks_integration as ks_integration

    child_envs: list[dict[str, str | None]] = []
    original_popen = ks_integration.subprocess.Popen

    def recording_popen(*args, **kwargs):
        env = kwargs.get("env")
        command = args[0] if args else kwargs.get("args")
        is_ks_child = (
            isinstance(command, (list, tuple))
            and "-m" in command
            and "knowledge_server.server" in command
        )
        if is_ks_child:
            if not isinstance(env, dict):
                raise AssertionError("KS subprocess must receive an explicit environment")
            child_envs.append(
                {
                    "shared_mode": env.get("EDGEFORGE_SHARED_MODE"),
                    "db_path": env.get("EDGEFORGE_KS_DB_PATH"),
                    "allowed_roots": env.get("EDGEFORGE_KS_ALLOWED_ROOTS"),
                }
            )
        return original_popen(*args, **kwargs)

    reset_ks_lifecycle_for_testing()
    try:
        ks_integration.subprocess.Popen = recording_popen
        yield child_envs
    finally:
        reset_ks_lifecycle_for_testing()
        ks_integration.subprocess.Popen = original_popen


@contextmanager
def _ka_off_spy() -> Iterator[list[str]]:
    calls: list[str] = []

    def fail_ks_client(*_args, **_kwargs):
        calls.append("ks_client")
        raise AssertionError("KS must not be called in the KA-OFF L4 author/generate smoke")

    def fail_ks_start(*_args, **_kwargs):
        calls.append("KSClient.start")
        raise AssertionError("KSClient.start must not be called in the KA-OFF L4 author/generate smoke")

    import app.integrations.ks_integration as ks_integration
    import app.routes.entities as entities
    import app.routes.knowledge as knowledge
    import app.services.assist_service as assist_service
    import app.services.evidence_trail as evidence_trail

    originals = {
        (ks_integration, "ks_client"): ks_integration.ks_client,
        (ks_integration.KSClient, "start"): ks_integration.KSClient.start,
        (assist_service, "ks_client"): assist_service.ks_client,
        (knowledge, "ks_client"): knowledge.ks_client,
        (entities, "ks_client"): entities.ks_client,
        (evidence_trail, "ks_client"): evidence_trail.ks_client,
    }
    try:
        ks_integration.ks_client = fail_ks_client
        ks_integration.KSClient.start = fail_ks_start
        assist_service.ks_client = fail_ks_client
        knowledge.ks_client = fail_ks_client
        entities.ks_client = fail_ks_client
        evidence_trail.ks_client = fail_ks_client
        yield calls
    finally:
        for (target, name), value in originals.items():
            setattr(target, name, value)


def _post_generate(client, csrf_token: str) -> dict:
    response = client.post("/export/generate", headers=csrf_headers(csrf_token))
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True, payload
    assert_no_ka_noise(payload)
    return payload


def _upload_knowledge_doc(client, csrf_token: str, *, filename: str, content: str) -> None:
    response = client.post(
        "/knowledge/upload",
        files={"document_file": (filename, content.encode("utf-8"), "text/markdown")},
        data={"_edgeforge_csrf_token": csrf_token, "description": "L4 synthetic marker document"},
    )
    assert response.status_code == 200
    assert "Ingested" in response.text


def _engine_repo_from_env() -> Path:
    value = os.environ.get("EDGEFORGE_STUDIO_ENGINE_REPO", "").strip()
    assert value, "EDGEFORGE_STUDIO_ENGINE_REPO is required for the L4 Engine fail-closed smoke"
    repo = Path(value).expanduser().resolve(strict=False)
    assert (repo / "appbuilder").is_dir(), f"Engine repo is not valid: {repo}"
    return repo


def _engine_cli_generate(
    *,
    manifest: Path,
    output: Path,
    engine_repo: Path,
    allowed_roots: list[Path],
    shared_mode: bool,
) -> dict[str, Any]:
    env = _engine_subprocess_env(engine_repo, allowed_roots=allowed_roots)
    if not allowed_roots:
        # The missing-roots negative intentionally bypasses Studio's normal
        # root population to prove Engine's EDGEFORGE_SHARED_MODE fail-closed
        # behavior when roots are unset.
        env.pop("EDGEFORGE_MCP_ALLOWED_ROOTS", None)
    if shared_mode:
        env["EDGEFORGE_SHARED_MODE"] = "1"
    else:
        env.pop("EDGEFORGE_SHARED_MODE", None)

    command = [
        sys.executable,
        "-m",
        "appbuilder.cli",
        "generate",
        "--manifest",
        str(manifest),
        "--output",
        str(output),
    ]
    proc = subprocess.run(
        command,
        cwd=str(engine_repo),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "combined_output": (proc.stdout + proc.stderr).strip(),
        "target": str(output),
        "resolved_target": str(output.expanduser().resolve(strict=False)),
        "command": command,
    }


def _run_fail_closed_case(
    *,
    name: str,
    manifest: Path,
    output: Path,
    engine_repo: Path,
    allowed_roots: list[Path],
    expected_message: str,
) -> dict[str, Any]:
    result = _engine_cli_generate(
        manifest=manifest,
        output=output,
        engine_repo=engine_repo,
        allowed_roots=allowed_roots,
        shared_mode=True,
    )
    resolved_target = Path(result["resolved_target"])
    return {
        "name": name,
        "returncode": result["returncode"],
        "rejected": result["returncode"] != 0,
        "message_matched": expected_message in result["combined_output"],
        "target": result["target"],
        "resolved_target": str(resolved_target),
        "target_exists": resolved_target.exists(),
        "combined_output": result["combined_output"],
    }


def _tree_contains(root: Path, needle: str) -> bool:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            if needle in path.read_text(encoding="utf-8", errors="ignore"):
                return True
        except OSError:
            continue
    return False


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True
