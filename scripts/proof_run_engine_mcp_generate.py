#!/usr/bin/env python3
"""Proof runner for Studio Phase 4 Engine MCP generation.

This exercises Studio's Step 8 backend route in three modes:
- strict MCP succeeds with a working Engine MCP Python
- auto mode falls back to CLI when MCP cannot start
- strict MCP fails visibly when MCP cannot start
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import yaml
from fastapi.testclient import TestClient

STUDIO_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(STUDIO_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(STUDIO_REPO_ROOT))

from app.main import app
from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    FieldMapping,
    OperationMapping,
    OperationSample,
    ProjectSession,
    UpstreamInterface,
)
from app.services.manifest_contract import STUDIO_MANIFEST_SCHEMA_VERSION
from app.services.project_file_service import serialize_project, snapshot_session
from app.services.runtime_defaults import default_edgeforge_repo_path


def _full_session(output_root: Path, engine_repo: Path) -> ProjectSession:
    """Independent tiny authoring input; no remote or external application spec."""
    session = ProjectSession(
        app_name="Synthetic Notes", bounded_context="notes",
        target_profile="springboot-legacy-compatible", output_path=str(output_root),
        appbuilder_repo_path=str(engine_repo), selected_entity_names=["Note"],
    )
    schema = {"type": "object", "properties": {
        "noteId": {"type": "string"}, "label": {"type": "string"},
        "state": {"type": "string"},
    }}
    content = json.dumps({
        "openapi": "3.0.3", "info": {"title": "Synthetic notes", "version": "1"},
        "paths": {"/notes": {"post": {
            "operationId": "createNote", "requestBody": {"required": True, "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/Note"}},
            }}, "responses": {"201": {"description": "Created", "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/Note"}},
            }}},
        }}}, "components": {"schemas": {"Note": schema}},
    })
    session.raw_spec_content = content
    session.raw_spec_filename = "notes.json"
    session.classified_entities = [ClassifiedEntity(name="Note", fields=[
        ClassifiedField(name="noteId", type="string", is_id=True),
        ClassifiedField(name="label", type="string"),
        ClassifiedField(name="state", type="string"),
    ])]
    session.upstream_interfaces = [UpstreamInterface(
        name="note-api", system="SyntheticNotes", type="rest-json", version="1",
        spec_content=content, entity_name="Note",
        operations=[OperationSample(
            name="createNote", request_sample_path="upstream/note-request.json",
            response_sample_path="upstream/note-response.json",
            request_sample_content='{"label":"SYNTHETIC NOTE","state":"NEW"}',
            response_sample_content='{"noteId":"SYNTH-NOTE-7","label":"SYNTHETIC NOTE","state":"NEW"}',
        )], operation_mappings=[OperationMapping(
            name="createNote",
            request_mappings=[FieldMapping(source=n, target=f"Note.{n}") for n in ("label", "state")],
            response_mappings=[FieldMapping(source=n, target=f"Note.{n}") for n in ("noteId", "label", "state")],
        )], mapping_path="upstream/note-mapping.yaml",
    )]
    return session


def _run_generate_case(
    *,
    name: str,
    transport: str,
    mcp_command: str,
    engine_repo: Path,
    expect_ok: bool,
    expected_message: str | None = None,
) -> dict:
    os.environ["EDGEFORGE_STUDIO_ENGINE_TRANSPORT"] = transport
    os.environ["EDGEFORGE_STUDIO_ENGINE_MCP_COMMAND"] = mcp_command

    output_root = Path(tempfile.mkdtemp(prefix=f"studio-{name}-"))
    os.environ["EDGEFORGE_STUDIO_STATE_DIR"] = str(output_root / "state")
    client = TestClient(app)
    opened = client.post(
        "/project/open",
        files={"project_file": (
            "synthetic-notes.edgeforge-project.json",
            serialize_project(snapshot_session(_full_session(output_root, engine_repo))),
            "application/json",
        )},
        follow_redirects=False,
    )
    if opened.status_code != 303:
        raise AssertionError(f"{name}: project/open failed: {opened.text}")
    write_response = client.post("/export/write")
    write_payload = write_response.json()
    if write_response.status_code != 200 or not write_payload.get("ok"):
        raise AssertionError(f"{name}: export/write failed: {write_payload}")
    manifest = yaml.safe_load((Path(write_payload["output_dir"]) / "app-definition.yaml").read_text())
    if manifest.get("schema_version") != STUDIO_MANIFEST_SCHEMA_VERSION:
        raise AssertionError(f"{name}: unexpected manifest version: {manifest}")

    validation = client.post("/export/validate").json()
    if not validation.get("ok"):
        raise AssertionError(f"{name}: schema validation failed: {validation}")

    commands = []
    real_popen = subprocess.Popen

    class ObservedPopen(real_popen):
        def __init__(self, command, *args, **kwargs):
            commands.append(list(command))
            super().__init__(command, *args, **kwargs)

    # Observe real children without replacing their execution or results.
    with patch("subprocess.Popen", ObservedPopen):
        generate_response = client.post("/export/generate")
    payload = generate_response.json()
    if payload.get("ok") is not expect_ok:
        raise AssertionError(f"{name}: expected ok={expect_ok}, got payload={payload}")

    if expected_message and expected_message not in payload.get("message", ""):
        raise AssertionError(f"{name}: expected message containing {expected_message!r}, got {payload}")

    if expect_ok:
        output_dir = Path(payload["output_dir"])
        if not output_dir.exists():
            raise AssertionError(f"{name}: generated output_dir does not exist: {output_dir}")
        source = next(output_dir.rglob("Note.java")).read_text()
        if not all(field in source for field in ("noteId", "label", "state")):
            raise AssertionError(f"{name}: missing canonical fields")
        if transport == "mcp" and not any("appbuilder.mcp_server" in command for command in commands):
            raise AssertionError(f"{name}: strict MCP did not execute: {payload}")
        if transport == "auto" and not any("appbuilder.cli" in command for command in commands):
            raise AssertionError(f"{name}: fallback evidence missing: {payload}")

    print(f"[OK] {name}: ok={payload.get('ok')} output_dir={payload.get('output_dir')}")
    if payload.get("warnings"):
        print(f"     warnings={len(payload['warnings'])}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Studio Engine MCP generate proof cases.")
    parser.add_argument(
        "--engine-repo",
        default=default_edgeforge_repo_path(),
        help="Local EdgeForge Engine repo path.",
    )
    parser.add_argument(
        "--engine-python",
        default=None,
        help="Python executable with Engine MCP/FastMCP installed. Defaults to <engine-repo>/.venv/bin/python.",
    )
    args = parser.parse_args()

    engine_repo = Path(args.engine_repo).expanduser().resolve()
    # Resolving a venv's interpreter symlink would discard that environment.
    engine_python = Path(args.engine_python or engine_repo / ".venv" / "bin" / "python").expanduser().absolute()
    if not engine_repo.exists():
        raise SystemExit(f"Engine repo not found: {engine_repo}")
    if not engine_python.exists():
        raise SystemExit(f"Engine MCP Python not found: {engine_python}")

    _run_generate_case(
        name="strict-mcp-success",
        transport="mcp",
        mcp_command=str(engine_python),
        engine_repo=engine_repo,
        expect_ok=True,
    )
    _run_generate_case(
        name="auto-fallback-success",
        transport="auto",
        mcp_command="/bad/python",
        engine_repo=engine_repo,
        expect_ok=True,
    )
    _run_generate_case(
        name="strict-mcp-failure",
        transport="mcp",
        mcp_command="/bad/python",
        engine_repo=engine_repo,
        expect_ok=False,
        expected_message="Engine MCP generate_app unavailable",
    )

    print("Studio Engine MCP generate proof completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
