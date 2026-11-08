from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.main import app
from app.models.project import ProjectSession
from app.services.package_writer import write_package_result
from app.services.regen_binding import (
    RegenBindingError,
    _generation_input_closure,
    _manifest_artifact_paths,
    _xml_include_targets,
    capture_generated_package,
    regen_status,
)
from app.services.retention import DURABLE_SUBDIR
from app.services.session_context import get_session_store
from tests.session_helpers import get_session, reset_session, save_session
from tests.test_package_writer import _full_session


def _xsd(body: str = "") -> str:
    """A minimal REAL XSD document. The `xs:` prefix has to be genuinely bound:
    include discovery parses the document, so an unbound prefix is simply invalid
    XML and yields no includes -- exactly as the Engine would treat it."""
    return f'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">{body}</xs:schema>'


def _xsd_including(location: str) -> str:
    return _xsd(f'<xs:include schemaLocation="{location}"/>')


class FakeGenerateResult:
    success = True
    combined_output = "generated"


def _future_now_iso() -> str:
    return datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat()


def _write_generated_app(output_dir: str, *, include_baseline: bool = True) -> None:
    generated = Path(output_dir)
    (generated / "src").mkdir(parents=True, exist_ok=True)
    (generated / "src" / "Demo.java").write_text("class Demo {}\n", encoding="utf-8")
    if include_baseline:
        (generated / "db").mkdir(parents=True, exist_ok=True)
        (generated / "db" / "schema-baseline.json").write_text(
            '{"entities":[]}\n',
            encoding="utf-8",
        )


def _prepare_exported_session(monkeypatch, *, include_baseline: bool = True):
    reset_session()
    session = _full_session()
    save_session(session)
    session = get_session()
    workspace_root = Path(session.workspace_root or "")
    session.output_path = str(workspace_root / "output")
    session.appbuilder_repo_path = str(Path.cwd())
    save_session(session)

    def fake_generate(
        _manifest_path: str,
        output_dir: str,
        _repo_path: str,
        **_kwargs,
    ):
        _write_generated_app(output_dir, include_baseline=include_baseline)
        return FakeGenerateResult()

    monkeypatch.setattr("app.routes.export.run_generate", fake_generate)
    client = TestClient(app)
    write_response = client.post("/export/write")
    assert write_response.status_code == 200
    assert write_response.json()["ok"] is True
    return client, workspace_root, Path(write_response.json()["output_dir"])


def test_regen_preview_flag_off_generate_leaves_binding_state_untouched(monkeypatch):
    monkeypatch.delenv("EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED", raising=False)
    client, workspace_root, _export_dir = _prepare_exported_session(monkeypatch)

    response = client.post("/export/generate")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert "regen_status" not in payload
    session = get_session()
    assert session.last_generated_package_ref is None
    assert session.generation_run_id is None
    assert session.manifest_hash is None
    assert session.baseline_hash is None
    assert regen_status(session) == "none"
    assert not (workspace_root / DURABLE_SUBDIR).exists()


def test_regen_preview_flag_on_captures_generated_package_and_survives_idle_purge(
    monkeypatch,
):
    monkeypatch.setenv("EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED", "true")

    def fail_ks_start(*_args, **_kwargs):
        raise AssertionError("regen-preview binding must not spawn Knowledge Server")

    monkeypatch.setattr("app.integrations.ks_integration.KSClient.start", fail_ks_start)
    client, workspace_root, _export_dir = _prepare_exported_session(monkeypatch)

    response = client.post("/export/generate")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["regen_status"] == "none"
    session = get_session()
    assert session.generation_run_id
    assert session.manifest_hash
    assert session.baseline_hash
    assert session.last_generated_package_ref
    managed_package = workspace_root / session.last_generated_package_ref
    assert managed_package.is_relative_to(workspace_root / DURABLE_SUBDIR)
    assert (managed_package / "src" / "Demo.java").exists()
    assert (managed_package / "db" / "schema-baseline.json").exists()

    purged = get_session_store().purge_expired_sessions(now_iso=_future_now_iso())

    assert purged == 0
    assert managed_package.exists()
    assert get_session_store().load(session.session_id or "").session_id == session.session_id


def test_regen_preview_records_manifest_only_when_schema_baseline_is_absent(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED", "true")
    client, workspace_root, _export_dir = _prepare_exported_session(
        monkeypatch,
        include_baseline=False,
    )

    response = client.post("/export/generate")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["regen_status"] == "manifest-only"
    session = get_session()
    assert session.manifest_hash
    assert session.baseline_hash is None
    managed_package = workspace_root / (session.last_generated_package_ref or "")
    assert managed_package.exists()
    assert not (managed_package / "db" / "schema-baseline.json").exists()
    assert regen_status(session) == "manifest-only"


def test_repeated_regen_capture_prunes_previous_managed_run(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED", "true")
    client, workspace_root, _export_dir = _prepare_exported_session(monkeypatch)

    first_response = client.post("/export/generate")
    assert first_response.status_code == 200
    first_session = get_session()
    first_run_id = first_session.generation_run_id
    first_package = workspace_root / (first_session.last_generated_package_ref or "")
    assert first_run_id
    assert first_package.exists()

    second_response = client.post("/export/generate")
    assert second_response.status_code == 200
    second_session = get_session()
    second_run_id = second_session.generation_run_id
    second_package = workspace_root / (second_session.last_generated_package_ref or "")

    assert second_run_id
    assert second_run_id != first_run_id
    assert not (workspace_root / DURABLE_SUBDIR / first_run_id).exists()
    assert second_package.exists()
    assert sorted(child.name for child in (workspace_root / DURABLE_SUBDIR).iterdir()) == [
        second_run_id
    ]


def test_regen_status_reports_ready_only_when_baseline_exists_and_manifest_changes(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED", "true")
    session = ProjectSession(session_id="session-a", workspace_root=str(tmp_path / "workspace"))
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

    assert regen_status(session) == "none"

    manifest.write_text("app_name: demo\nentities: []\n", encoding="utf-8")

    assert regen_status(session) == "regenerate-ready"


def test_regen_status_detects_referenced_artifact_content_change(monkeypatch, tmp_path):
    """A layout/spec content edit under an UNCHANGED manifest path must still
    register as a regen delta. The manifest names artifacts by path only, so a
    manifest-only hash misses this -- the generation-input hash covers the
    referenced files too."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED", "true")
    session = ProjectSession(session_id="session-artifact", workspace_root=str(tmp_path / "workspace"))
    workspace_root = Path(session.workspace_root or "")
    export_dir = workspace_root / "output" / "demo"
    generated = export_dir / "generated-app"
    manifest = export_dir / "app-definition.yaml"
    layout = export_dir / "downstream" / "eod-layout.yaml"
    generated.mkdir(parents=True)
    (generated / "db").mkdir()
    (generated / "db" / "schema-baseline.json").write_text('{"entities":[]}\n', encoding="utf-8")
    layout.parent.mkdir(parents=True)
    layout.write_text("format: fixed-width\nrecord_types:\n  data:\n    fields: []\n", encoding="utf-8")
    # The manifest references the layout only by path -- the field a content
    # edit must NOT change.
    manifest.write_text(
        "app_name: demo\ndownstream_interfaces:\n  - name: eod\n    spec: downstream/eod-layout.yaml\n",
        encoding="utf-8",
    )
    session.last_export_path = str(export_dir)

    capture_generated_package(session, generated_package_path=generated, manifest_path=manifest)
    assert regen_status(session) == "none"

    # Edit the referenced layout's CONTENT; the manifest bytes are untouched.
    manifest_before = manifest.read_bytes()
    layout.write_text(
        "format: fixed-width\nrecord_types:\n  data:\n    fields:\n      - name: id\n        position: 1\n        length: 8\n",
        encoding="utf-8",
    )
    assert manifest.read_bytes() == manifest_before  # manifest path/text unchanged

    assert regen_status(session) == "regenerate-ready"


def _capture_package_with_layout(tmp_path, monkeypatch, session_id: str):
    """Seed an exported package (manifest + a downstream layout + generated-app)
    and capture it; returns (session, export_dir)."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED", "true")
    session = ProjectSession(session_id=session_id, workspace_root=str(tmp_path / "workspace"))
    workspace_root = Path(session.workspace_root or "")
    export_dir = workspace_root / "output" / "demo"
    generated = export_dir / "generated-app"
    manifest = export_dir / "app-definition.yaml"
    generated.mkdir(parents=True)
    (generated / "db").mkdir()
    (generated / "db" / "schema-baseline.json").write_text('{"entities":[]}\n', encoding="utf-8")
    manifest.write_text("app_name: demo\nspec: downstream/eod-layout.yaml\n", encoding="utf-8")
    (export_dir / "downstream").mkdir()
    (export_dir / "downstream" / "eod-layout.yaml").write_text("format: fixed-width\n", encoding="utf-8")
    session.last_export_path = str(export_dir)
    capture_generated_package(session, generated_package_path=generated, manifest_path=manifest)
    assert regen_status(session) == "none"
    return session, export_dir


def test_regen_status_ignores_metadata_sidecars_and_unreferenced_output(monkeypatch, tmp_path):
    """Studio-side metadata that changes every export (studio-project.json,
    reports, evidence-trail.json) and UNREFERENCED generated-app output must not
    affect the regen hash -- otherwise every re-export would be a false delta."""
    session, export_dir = _capture_package_with_layout(tmp_path, monkeypatch, "session-noise")

    (export_dir / "studio-project.json").write_text('{"revision": 9}\n', encoding="utf-8")
    (export_dir / "evidence-trail.json").write_text('{"exported_at": "later"}\n', encoding="utf-8")
    (export_dir / "generated-app" / "src").mkdir(parents=True)
    (export_dir / "generated-app" / "src" / "Demo.java").write_text("class Demo { int x; }\n", encoding="utf-8")
    assert regen_status(session) == "none"


def test_regen_status_ignores_arbitrary_unreferenced_package_files(monkeypatch, tmp_path):
    """Files nothing references -- editor/OS noise, stale artifacts left by an
    earlier export -- are not Engine inputs and must not trigger a false delta
    (review finding: hashing every package file was too broad)."""
    session, export_dir = _capture_package_with_layout(tmp_path, monkeypatch, "session-unref")

    (export_dir / "notes.txt").write_text("scratch notes\n", encoding="utf-8")
    (export_dir / ".DS_Store").write_bytes(b"\x00\x01")
    (export_dir / "downstream" / "stale-old-layout.yaml").write_text("format: fixed-width\n", encoding="utf-8")
    assert regen_status(session) == "none"


def test_regen_status_hashes_referenced_input_even_under_generated_app(monkeypatch, tmp_path):
    """Studio does not reserve generated-app/ as an artifact path, so a manifest
    can legitimately reference an input there. A content change to that input
    must be detected -- excluding the whole generated-app subtree was a false
    negative (review finding)."""
    session, export_dir = _capture_package_with_layout(tmp_path, monkeypatch, "session-under-output")
    manifest = export_dir / "app-definition.yaml"
    xsd = export_dir / "generated-app" / "schema.xsd"
    xsd.parent.mkdir(parents=True, exist_ok=True)
    xsd.write_text(_xsd("<!-- first -->"), encoding="utf-8")
    manifest.write_text(
        "app_name: demo\nupstream_interfaces:\n  - name: acct\n    xsd_path: generated-app/schema.xsd\n",
        encoding="utf-8",
    )
    capture_generated_package(session, generated_package_path=export_dir / "generated-app", manifest_path=manifest)
    assert regen_status(session) == "none"

    xsd.write_text(_xsd("<!-- second CHANGED -->"), encoding="utf-8")
    assert regen_status(session) == "regenerate-ready"


@pytest.mark.parametrize("source_key", ["xsd_path", "spec"])
def test_regen_status_detects_transitive_xsd_include_change(
    monkeypatch, tmp_path, source_key
):
    """A child artifact the manifest does NOT name (e.g. an XSD pulled in by an
    <xs:include> inside a manifest-referenced XSD) still changes Engine output,
    so a content edit to it must register as a delta -- hashing package contents
    (not just manifest-named paths) covers this."""
    session, export_dir = _capture_package_with_layout(tmp_path, monkeypatch, "session-xsd")
    contracts = export_dir / "contracts"
    contracts.mkdir()
    # A genuine reachability chain: manifest -> parent.xsd -> child.xsd.
    # child.xsd is named only INSIDE parent.xsd's <xs:include>, never by the
    # manifest -- so only following references reaches it.
    manifest = export_dir / "app-definition.yaml"
    manifest.write_text(
        "app_name: demo\n"
        "upstream_interfaces:\n"
        "  - name: acct\n"
        "    type: xml-xsd\n"
        f"    {source_key}: contracts/parent.xsd\n",
        encoding="utf-8",
    )
    (contracts / "parent.xsd").write_text(_xsd_including("child.xsd"), encoding="utf-8")
    (contracts / "child.xsd").write_text(_xsd("<!-- v1 -->"), encoding="utf-8")
    capture_generated_package(session, generated_package_path=export_dir / "generated-app", manifest_path=manifest)
    assert regen_status(session) == "none"

    (contracts / "child.xsd").write_text(_xsd("<!-- v2 CHANGED -->"), encoding="utf-8")
    assert regen_status(session) == "regenerate-ready"


def test_regen_status_does_not_follow_schema_markup_inside_xml_sample(monkeypatch, tmp_path):
    """Samples are Engine inputs, but the Engine never treats their nested XML as
    an XSD catalog. Include-shaped sample content must not pull in extra files."""
    session, export_dir = _capture_package_with_layout(tmp_path, monkeypatch, "session-sample")
    contracts = export_dir / "contracts"
    samples = export_dir / "samples"
    contracts.mkdir()
    samples.mkdir()
    manifest = export_dir / "app-definition.yaml"
    manifest.write_text(
        "app_name: demo\n"
        "upstream_interfaces:\n"
        "  - name: acct\n"
        "    type: xml-xsd\n"
        "    xsd_path: contracts/account.xsd\n"
        "    sample: samples/account.xml\n",
        encoding="utf-8",
    )
    (contracts / "account.xsd").write_text(_xsd(), encoding="utf-8")
    (samples / "account.xml").write_text(
        '<account xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        '<xs:schema><xs:include schemaLocation="noise.xsd"/></xs:schema>'
        "</account>",
        encoding="utf-8",
    )
    (samples / "noise.xsd").write_text(_xsd("<!-- v1 -->"), encoding="utf-8")
    capture_generated_package(
        session, generated_package_path=export_dir / "generated-app", manifest_path=manifest
    )
    assert regen_status(session) == "none"

    (samples / "noise.xsd").write_text(_xsd("<!-- v2 CHANGED -->"), encoding="utf-8")
    assert regen_status(session) == "none"


@pytest.mark.parametrize("source_key", ["wsdl_path", "spec"])
def test_regen_status_ignores_xsd_include_outside_wsdl_types(
    monkeypatch, tmp_path, source_key
):
    """The SOAP loader discovers schemas only under direct wsdl:types. An XSD
    fragment in documentation is content, not a transitive contract input."""
    session, export_dir = _capture_package_with_layout(tmp_path, monkeypatch, "session-wsdl-doc")
    contracts = export_dir / "contracts"
    contracts.mkdir()
    manifest = export_dir / "app-definition.yaml"
    manifest.write_text(
        "app_name: demo\n"
        "upstream_interfaces:\n"
        "  - name: acct\n"
        "    type: soap-wsdl\n"
        f"    {source_key}: contracts/account.wsdl\n",
        encoding="utf-8",
    )
    (contracts / "account.wsdl").write_text(
        '<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" '
        'xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        '<wsdl:types><xs:schema><xs:include schemaLocation="real.xsd"/>'
        "</xs:schema></wsdl:types>"
        "<wsdl:documentation>"
        '<xs:schema><xs:include schemaLocation="noise.xsd"/></xs:schema>'
        "</wsdl:documentation>"
        "</wsdl:definitions>",
        encoding="utf-8",
    )
    (contracts / "real.xsd").write_text(_xsd("<!-- v1 -->"), encoding="utf-8")
    (contracts / "noise.xsd").write_text(_xsd("<!-- v1 -->"), encoding="utf-8")
    capture_generated_package(
        session, generated_package_path=export_dir / "generated-app", manifest_path=manifest
    )
    assert regen_status(session) == "none"

    (contracts / "noise.xsd").write_text(_xsd("<!-- v2 CHANGED -->"), encoding="utf-8")
    assert regen_status(session) == "none"

    (contracts / "real.xsd").write_text(_xsd("<!-- v2 CHANGED -->"), encoding="utf-8")
    assert regen_status(session) == "regenerate-ready"


def test_regen_status_follows_non_utf8_xsd_include(monkeypatch, tmp_path):
    """ElementTree honors the XML declaration when parsing bytes, as the Engine
    does. Lossy UTF-8 decoding must not corrupt a non-ASCII include target."""
    session, export_dir = _capture_package_with_layout(tmp_path, monkeypatch, "session-latin1")
    contracts = export_dir / "contracts"
    contracts.mkdir()
    manifest = export_dir / "app-definition.yaml"
    manifest.write_text(
        "app_name: demo\n"
        "upstream_interfaces:\n"
        "  - name: acct\n"
        "    type: xml-xsd\n"
        "    xsd_path: contracts/parent.xsd\n",
        encoding="utf-8",
    )
    parent = '<?xml version="1.0" encoding="ISO-8859-1"?>' + _xsd_including(
        "common-é-types.xsd"
    )
    (contracts / "parent.xsd").write_bytes(parent.encode("iso-8859-1"))
    child = contracts / "common-é-types.xsd"
    child.write_text(_xsd("<!-- v1 -->"), encoding="utf-8")
    capture_generated_package(
        session, generated_package_path=export_dir / "generated-app", manifest_path=manifest
    )
    assert regen_status(session) == "none"

    child.write_text(_xsd("<!-- v2 CHANGED -->"), encoding="utf-8")
    assert regen_status(session) == "regenerate-ready"


@pytest.mark.parametrize(
    ("interface_type", "source_key", "parent_name", "root_kind", "parent_content"),
    [
        (
            "xml-xsd",
            "xsd_path",
            "parent.xsd",
            "xsd",
            "<!DOCTYPE xs:schema>" + _xsd_including("child.xsd"),
        ),
        (
            "soap-wsdl",
            "wsdl_path",
            "parent.wsdl",
            "wsdl",
            "<!DOCTYPE wsdl:definitions>"
            '<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" '
            'xmlns:xs="http://www.w3.org/2001/XMLSchema"><wsdl:types>'
            '<xs:schema><xs:include schemaLocation="child.xsd"/></xs:schema>'
            "</wsdl:types></wsdl:definitions>",
        ),
    ],
    ids=["xsd", "wsdl"],
)
def test_regen_status_does_not_follow_include_from_dtd_parent(
    monkeypatch,
    tmp_path,
    interface_type,
    source_key,
    parent_name,
    root_kind,
    parent_content,
):
    """A direct DTD-bearing input remains hashed, but its child is not traversed."""
    session, export_dir = _capture_package_with_layout(tmp_path, monkeypatch, "session-dtd")
    contracts = export_dir / "contracts"
    contracts.mkdir()
    manifest = export_dir / "app-definition.yaml"
    manifest.write_text(
        "app_name: demo\n"
        "upstream_interfaces:\n"
        "  - name: acct\n"
        f"    type: {interface_type}\n"
        f"    {source_key}: contracts/{parent_name}\n",
        encoding="utf-8",
    )
    parent = contracts / parent_name
    parent.write_text(parent_content, encoding="utf-8")
    child = contracts / "child.xsd"
    child.write_text(_xsd("<!-- v1 -->"), encoding="utf-8")

    assert _xml_include_targets(parent_content, root_kind=root_kind) == []
    closure = set(_generation_input_closure(manifest))
    assert parent.resolve() in closure
    assert child.resolve() not in closure

    capture_generated_package(
        session, generated_package_path=export_dir / "generated-app", manifest_path=manifest
    )
    assert regen_status(session) == "none"

    child.write_text(_xsd("<!-- v2 CHANGED -->"), encoding="utf-8")
    assert regen_status(session) == "none"

    parent.write_text(parent_content + "<!-- parent CHANGED -->", encoding="utf-8")
    assert regen_status(session) == "regenerate-ready"


@pytest.mark.parametrize(
    "decoy",
    [
        "<!-- <!DOCTYPE fake> -->",
        (
            "<xs:annotation><xs:documentation>"
            "<![CDATA[<!DOCTYPE fake>]]>"
            "</xs:documentation></xs:annotation>"
        ),
    ],
    ids=["comment", "cdata"],
)
def test_regen_status_ignores_declaration_syntax_outside_dtd(monkeypatch, tmp_path, decoy):
    """Declaration-shaped text in comments/CDATA remains ordinary XSD content."""
    session, export_dir = _capture_package_with_layout(tmp_path, monkeypatch, "session-decoy")
    contracts = export_dir / "contracts"
    contracts.mkdir()
    manifest = export_dir / "app-definition.yaml"
    manifest.write_text(
        "app_name: demo\n"
        "upstream_interfaces:\n"
        "  - name: acct\n"
        "    type: xml-xsd\n"
        "    xsd_path: contracts/parent.xsd\n",
        encoding="utf-8",
    )
    (contracts / "parent.xsd").write_text(
        _xsd(decoy + '<xs:include schemaLocation="child.xsd"/>'),
        encoding="utf-8",
    )
    child = contracts / "child.xsd"
    child.write_text(_xsd("<!-- v1 -->"), encoding="utf-8")
    capture_generated_package(
        session, generated_package_path=export_dir / "generated-app", manifest_path=manifest
    )
    assert regen_status(session) == "none"

    child.write_text(_xsd("<!-- v2 CHANGED -->"), encoding="utf-8")
    assert regen_status(session) == "regenerate-ready"


def test_regen_status_preserves_utf16be_trailing_whitespace(monkeypatch, tmp_path):
    """Raw byte trimming can remove only half of the final UTF-16BE whitespace
    code unit. Parse the unchanged bytes so the Engine-visible include survives."""
    session, export_dir = _capture_package_with_layout(tmp_path, monkeypatch, "session-utf16be")
    contracts = export_dir / "contracts"
    contracts.mkdir()
    manifest = export_dir / "app-definition.yaml"
    manifest.write_text(
        "app_name: demo\n"
        "upstream_interfaces:\n"
        "  - name: acct\n"
        "    type: xml-xsd\n"
        "    xsd_path: contracts/parent.xsd\n",
        encoding="utf-8",
    )
    parent = (
        '<?xml version="1.0" encoding="UTF-16BE"?>'
        + _xsd_including("child.xsd")
        + " \n"
    )
    (contracts / "parent.xsd").write_bytes(parent.encode("utf-16-be"))
    child = contracts / "child.xsd"
    child.write_text(_xsd("<!-- v1 -->"), encoding="utf-8")
    capture_generated_package(
        session, generated_package_path=export_dir / "generated-app", manifest_path=manifest
    )
    assert regen_status(session) == "none"

    child.write_text(_xsd("<!-- v2 CHANGED -->"), encoding="utf-8")
    assert regen_status(session) == "regenerate-ready"


def test_regen_status_ignores_non_path_manifest_scalars(monkeypatch, tmp_path):
    """A manifest scalar under a NON-path key that happens to equal a real
    filename (app_name: notes.txt) must not be treated as an artifact reference
    -- editing that unrelated file causes no delta (paths are taken from
    artifact keys structurally, not by scanning every string)."""
    session, export_dir = _capture_package_with_layout(tmp_path, monkeypatch, "session-scalar")
    (export_dir / "notes.txt").write_text("v1\n", encoding="utf-8")
    manifest = export_dir / "app-definition.yaml"
    manifest.write_text(
        "app_name: notes.txt\nversion: downstream/eod-layout.yaml\n"
        "downstream_interfaces:\n  - name: eod\n    spec: downstream/eod-layout.yaml\n",
        encoding="utf-8",
    )
    capture_generated_package(session, generated_package_path=export_dir / "generated-app", manifest_path=manifest)
    assert regen_status(session) == "none"

    # notes.txt is named only by app_name (a non-path key) -- not a reference.
    (export_dir / "notes.txt").write_text("v2 CHANGED\n", encoding="utf-8")
    assert regen_status(session) == "none"


def test_regen_status_follows_parent_relative_and_spaced_include_targets(monkeypatch, tmp_path):
    """Transitive includes with `../` parent-relative paths and spaces in the
    target must still be followed (they are valid Engine inputs). The include
    attribute value is honoured whole."""
    session, export_dir = _capture_package_with_layout(tmp_path, monkeypatch, "session-relpath")
    contracts = export_dir / "contracts"
    shared = export_dir / "shared dir"  # a directory name containing a space
    contracts.mkdir()
    shared.mkdir()
    manifest = export_dir / "app-definition.yaml"
    manifest.write_text(
        "app_name: demo\nupstream_interfaces:\n  - name: acct\n    xsd_path: contracts/parent.xsd\n",
        encoding="utf-8",
    )
    # parent -> ../shared dir/child.xsd  (parent-relative AND spaced)
    (contracts / "parent.xsd").write_text(
        _xsd_including("../shared dir/child.xsd"), encoding="utf-8"
    )
    (shared / "child.xsd").write_text(_xsd("<!-- v1 -->"), encoding="utf-8")
    capture_generated_package(session, generated_package_path=export_dir / "generated-app", manifest_path=manifest)
    assert regen_status(session) == "none"

    (shared / "child.xsd").write_text(_xsd("<!-- v2 CHANGED -->"), encoding="utf-8")
    assert regen_status(session) == "regenerate-ready"


def test_regen_status_decodes_entity_encoded_include_locations(monkeypatch, tmp_path):
    """`schemaLocation="../shared&#32;dir/child.xsd"` names the very same file as
    `../shared dir/child.xsd` -- an XML parser decodes the character reference,
    so the Engine follows the child and its content is a real generation input.
    A text scan takes the undecoded literal, fails to resolve it, and misses the
    dependency entirely (review finding: false negative)."""
    session, export_dir = _capture_package_with_layout(tmp_path, monkeypatch, "session-entity")
    contracts = export_dir / "contracts"
    shared = export_dir / "shared dir"
    contracts.mkdir()
    shared.mkdir()
    manifest = export_dir / "app-definition.yaml"
    manifest.write_text(
        "app_name: demo\nupstream_interfaces:\n  - name: acct\n    xsd_path: contracts/parent.xsd\n",
        encoding="utf-8",
    )
    (contracts / "parent.xsd").write_text(
        _xsd_including("../shared&#32;dir/child.xsd"), encoding="utf-8"
    )
    (shared / "child.xsd").write_text(_xsd("<!-- v1 -->"), encoding="utf-8")
    capture_generated_package(
        session, generated_package_path=export_dir / "generated-app", manifest_path=manifest
    )
    assert regen_status(session) == "none"

    (shared / "child.xsd").write_text(_xsd("<!-- v2 CHANGED -->"), encoding="utf-8")
    assert regen_status(session) == "regenerate-ready"


def test_regen_status_ignores_include_text_inside_an_xml_comment(monkeypatch, tmp_path):
    """A commented-out include is not an include. The Engine parses the document
    and never sees it, so the named file is not a generation input; treating the
    comment text as a reference makes an unrelated file able to invent a regen
    delta (review finding: false positive)."""
    session, export_dir = _capture_package_with_layout(tmp_path, monkeypatch, "session-comment")
    contracts = export_dir / "contracts"
    contracts.mkdir()
    manifest = export_dir / "app-definition.yaml"
    manifest.write_text(
        "app_name: demo\nupstream_interfaces:\n  - name: acct\n    xsd_path: contracts/parent.xsd\n",
        encoding="utf-8",
    )
    (contracts / "parent.xsd").write_text(
        _xsd('<!-- <xs:include schemaLocation="noise.xsd"/> -->'), encoding="utf-8"
    )
    (contracts / "noise.xsd").write_text(_xsd("<!-- v1 -->"), encoding="utf-8")
    capture_generated_package(
        session, generated_package_path=export_dir / "generated-app", manifest_path=manifest
    )
    assert regen_status(session) == "none"

    (contracts / "noise.xsd").write_text(_xsd("<!-- v2 CHANGED -->"), encoding="utf-8")
    assert regen_status(session) == "none"

    # ...while the genuinely referenced parent still registers.
    (contracts / "parent.xsd").write_text(_xsd("<!-- parent CHANGED -->"), encoding="utf-8")
    assert regen_status(session) == "regenerate-ready"


def test_xml_include_targets_parses_instead_of_scanning_text():
    """Unit-level statement of the include-discovery contract."""
    # Character references decode to the real filename.
    assert _xml_include_targets(
        _xsd_including("../shared&#32;dir/child.xsd"), root_kind="xsd"
    ) == [
        "../shared dir/child.xsd"
    ]
    # Comments are not markup.
    assert (
        _xml_include_targets(
            _xsd('<!-- <xs:include schemaLocation="noise.xsd"/> -->'),
            root_kind="xsd",
        )
        == []
    )
    # A DTD is refused outright rather than expanded (XXE / billion-laughs guard).
    assert (
        _xml_include_targets(
            '<!DOCTYPE schema [<!ENTITY x "y">]>'
            + _xsd_including("child.xsd"),
            root_kind="xsd",
        )
        == []
    )
    assert (
        _xml_include_targets(
            (
                '<?xml version="1.0" encoding="UTF-16"?>'
                '<!DOCTYPE schema [<!ENTITY x "y">]>'
                + _xsd_including("child.xsd")
            ).encode("utf-16"),
            root_kind="xsd",
        )
        == []
    )
    # A plain DTD is rejected just as decisively as one declaring an entity.
    assert (
        _xml_include_targets(
            "<!DOCTYPE xs:schema>" + _xsd_including("child.xsd"),
            root_kind="xsd",
        )
        == []
    )
    # Not XML, and XML whose xs: prefix is never bound, contribute nothing.
    assert _xml_include_targets("format: fixed-width\n", root_kind="xsd") == []
    assert (
        _xml_include_targets(
            '<xs:schema><xs:include schemaLocation="c.xsd"/></xs:schema>',
            root_kind="xsd",
        )
        == []
    )
    # A WSDL carries its schema under wsdl:types -- includes there still count.
    assert _xml_include_targets(
        '<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/"'
        ' xmlns:xs="http://www.w3.org/2001/XMLSchema"><wsdl:types>'
        '<xs:schema><xs:include schemaLocation="types/common.xsd"/></xs:schema>'
        "</wsdl:types></wsdl:definitions>",
        root_kind="wsdl",
    ) == ["types/common.xsd"]
    # Nested schemas in samples or WSDL documentation are not schema roots.
    assert (
        _xml_include_targets(
            '<sample xmlns:xs="http://www.w3.org/2001/XMLSchema">'
            '<xs:schema><xs:include schemaLocation="noise.xsd"/></xs:schema>'
            "</sample>",
            root_kind="xsd",
        )
        == []
    )


def test_manifest_paths_ignore_file_keys_outside_engine_path_positions(monkeypatch, tmp_path):
    """A router target's condition may carry an arbitrary value that happens to
    look like `{file: notes.txt}`. The Engine's typed referenced_paths() reads
    schema/transform `file` fields only, so notes.txt is NOT an input -- matching
    a key name at any depth seeded it and invented a delta (review finding)."""
    manifest_yaml = (
        "app_name: demo\n"
        "async_routes:\n"
        "  - name: route-x\n"
        "    pattern: router\n"
        "    router_config:\n"
        "      inbound_schema:\n"
        "        file: schemas/router-inbound.json\n"
        "      targets:\n"
        "        - name: t1\n"
        "          condition:\n"
        "            field: kind\n"
        "            value:\n"
        "              file: notes.txt\n"
        "          request_transform:\n"
        "            file: mappings/t1-request.yaml\n"
    )
    seeded = _manifest_artifact_paths(yaml.safe_load(manifest_yaml))
    assert "notes.txt" not in seeded
    assert seeded == {"schemas/router-inbound.json", "mappings/t1-request.yaml"}

    # ...and end to end: editing notes.txt is not a delta, editing a real
    # schema/transform position is.
    session, export_dir = _capture_package_with_layout(tmp_path, monkeypatch, "session-condition")
    (export_dir / "schemas").mkdir()
    (export_dir / "mappings").mkdir()
    manifest = export_dir / "app-definition.yaml"
    manifest.write_text(manifest_yaml, encoding="utf-8")
    (export_dir / "schemas" / "router-inbound.json").write_text('{"v": 1}\n', encoding="utf-8")
    (export_dir / "mappings" / "t1-request.yaml").write_text("mappings: []\n", encoding="utf-8")
    (export_dir / "notes.txt").write_text("v1\n", encoding="utf-8")
    capture_generated_package(
        session, generated_package_path=export_dir / "generated-app", manifest_path=manifest
    )
    assert regen_status(session) == "none"

    (export_dir / "notes.txt").write_text("v2 CHANGED\n", encoding="utf-8")
    assert regen_status(session) == "none"

    (export_dir / "mappings" / "t1-request.yaml").write_text("mappings: [changed]\n", encoding="utf-8")
    assert regen_status(session) == "regenerate-ready"


def test_regen_status_is_robust_to_dangling_symlinks(monkeypatch, tmp_path):
    """A dangling/loose symlink in the package must be skipped, not crash the
    status check (regen_status is on a request path)."""
    session, export_dir = _capture_package_with_layout(tmp_path, monkeypatch, "session-symlink")
    (export_dir / "downstream" / "dangling.yaml").symlink_to(export_dir / "downstream" / "nonexistent.yaml")
    # Must return a value, not raise.
    assert regen_status(session) in {"none", "regenerate-ready"}


def test_regen_status_detects_referenced_async_route_and_router_artifacts(monkeypatch, tmp_path):
    """kafka/router manifests reference topic message schemas, transform mappings
    and router_config schema files -- all generation inputs named by the Engine's
    referenced_paths(). A content edit to any of them must register as a regen
    delta; an UNreferenced sibling must not. A CRUD-only seed missed this whole
    surface, so router/kafka input changes escaped the hash silently."""
    session, export_dir = _capture_package_with_layout(tmp_path, monkeypatch, "session-async")
    (export_dir / "schemas").mkdir()
    (export_dir / "mappings").mkdir()
    manifest = export_dir / "app-definition.yaml"
    manifest.write_text(
        "app_name: demo\n"
        "async_routes:\n"
        "  - name: acct-route\n"
        "    pattern: fire-and-forget\n"
        "    upstream_topic:\n"
        "      name: acct.in\n"
        "      message_schema: schemas/acct-upstream.json\n"
        "    transform_mapping: mappings/acct-route.yaml\n"
        "  - name: route-x\n"
        "    pattern: router\n"
        "    router_config:\n"
        "      inbound_schema:\n"
        "        file: schemas/router-inbound.json\n",
        encoding="utf-8",
    )
    (export_dir / "schemas" / "acct-upstream.json").write_text('{"v": 1}\n', encoding="utf-8")
    (export_dir / "mappings" / "acct-route.yaml").write_text("mappings: []\n", encoding="utf-8")
    (export_dir / "schemas" / "router-inbound.json").write_text('{"v": 1}\n', encoding="utf-8")
    (export_dir / "schemas" / "unreferenced.json").write_text('{"noise": 1}\n', encoding="utf-8")
    capture_generated_package(
        session, generated_package_path=export_dir / "generated-app", manifest_path=manifest
    )
    assert regen_status(session) == "none"

    # A sibling nothing references is not an Engine input -> no delta.
    (export_dir / "schemas" / "unreferenced.json").write_text('{"noise": 2}\n', encoding="utf-8")
    assert regen_status(session) == "none"

    # Each referenced async-route input is independently load-bearing: edit it,
    # expect a delta, then re-capture to reset the baseline for the next one.
    for referenced in (
        "schemas/acct-upstream.json",
        "mappings/acct-route.yaml",
        "schemas/router-inbound.json",
    ):
        (export_dir / referenced).write_text('{"v": 2, "changed": true}\n', encoding="utf-8")
        assert regen_status(session) == "regenerate-ready", f"{referenced} was not hashed"
        capture_generated_package(
            session, generated_package_path=export_dir / "generated-app", manifest_path=manifest
        )
        assert regen_status(session) == "none"


def test_regen_status_detects_referenced_legacy_reference_change(monkeypatch, tmp_path):
    """legacy_references are manifest-referenced generation inputs per the
    Engine's referenced_paths(), so a content edit to one is a real regen delta."""
    session, export_dir = _capture_package_with_layout(tmp_path, monkeypatch, "session-legacy")
    (export_dir / "legacy").mkdir()
    manifest = export_dir / "app-definition.yaml"
    manifest.write_text(
        "app_name: demo\nlegacy_references:\n  - legacy/dda-notes.md\n",
        encoding="utf-8",
    )
    (export_dir / "legacy" / "dda-notes.md").write_text("# v1\n", encoding="utf-8")
    capture_generated_package(
        session, generated_package_path=export_dir / "generated-app", manifest_path=manifest
    )
    assert regen_status(session) == "none"

    (export_dir / "legacy" / "dda-notes.md").write_text("# v2 CHANGED\n", encoding="utf-8")
    assert regen_status(session) == "regenerate-ready"


def test_generation_input_closure_covers_every_referenced_file_in_a_full_package(tmp_path):
    """Anti-drift: for a real, fully-populated package the closure must reach
    every manifest-referenced file on disk. The oracle here -- 'any manifest
    string that resolves to a real package file' -- is deliberately independent
    of _MANIFEST_ARTIFACT_KEYS, so a path key added to manifest_generator but not
    mirrored in the key set shows up as a miss."""
    project_dir = write_package_result(_full_session(), tmp_path).project_dir.resolve()
    manifest = project_dir / "app-definition.yaml"

    def _strings(node):
        if isinstance(node, str):
            yield node
        elif isinstance(node, dict):
            for value in node.values():
                yield from _strings(value)
        elif isinstance(node, list):
            for value in node:
                yield from _strings(value)

    referenced = set()
    for text in _strings(yaml.safe_load(manifest.read_text(encoding="utf-8"))):
        try:
            resolved = (project_dir / text.strip()).resolve()
            resolved.relative_to(project_dir)
        except (ValueError, OSError):
            continue
        if resolved.is_file() and resolved != manifest.resolve():
            referenced.add(resolved)
    assert referenced, "full-package fixture wrote no artifacts -- the test would be vacuous"

    closure = set(_generation_input_closure(manifest))
    missing = sorted(str(path) for path in referenced if path not in closure)
    assert not missing, f"closure missed manifest-referenced files: {missing}"


def _engine_repo_for_manifest_contract() -> Path:
    candidates = [
        os.environ.get("EDGEFORGE_ENGINE_REPO"),
        os.environ.get("EDGEFORGE_STUDIO_ENGINE_REPO"),
        os.environ.get("EDGEFORGE_STUDIO_DEFAULT_ENGINE_REPO"),
        str(Path(__file__).resolve().parents[2] / "EdgeForge"),
    ]
    for value in candidates:
        if not value:
            continue
        candidate = Path(value).expanduser().resolve()
        if (candidate / "appbuilder" / "contracts" / "manifest.py").is_file():
            return candidate
    pytest.skip("referenced_paths parity requires a resolvable Engine checkout")


@pytest.mark.parametrize(
    "parent_content",
    [
        _xsd(
            "<!-- <!DOCTYPE fake> -->"
            "<xs:annotation><xs:documentation>"
            "<![CDATA[<!DOCTYPE fake>]]>"
            "</xs:documentation></xs:annotation>"
            '<xs:include schemaLocation="child.xsd"/>'
        ).encode(),
        (
            '<?xml version="1.0" encoding="UTF-16BE"?>'
            + _xsd_including("child.xsd")
            + " \n"
        ).encode("utf-16-be"),
    ],
    ids=["comment-and-cdata", "utf16be-trailing-whitespace"],
)
def test_xsd_include_edge_cases_match_real_engine_loader(tmp_path, parent_content):
    """Cross-repo guard for XML forms the real Engine accepts and traverses."""
    engine = _engine_repo_for_manifest_contract()
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    parent = contracts / "parent.xsd"
    child = contracts / "child.xsd"
    parent.write_bytes(parent_content)
    child.write_text(_xsd(), encoding="utf-8")
    script = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from appbuilder.contracts.xml_contracts import _load_schema_bundle\n"
        "root = Path(sys.argv[2])\n"
        "bundle = _load_schema_bundle(\n"
        "    xsd_path=root / 'parent.xsd',\n"
        "    interface_name='acct',\n"
        "    package_root=root,\n"
        ")\n"
        "print(json.dumps([path.name for path in bundle.paths]))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, str(engine), str(contracts)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == ["child.xsd", "parent.xsd"]


def test_plain_dtd_xsd_is_rejected_by_studio_and_real_engine_loader(tmp_path):
    """The paired loader and Studio discovery must refuse the same active DTD."""
    engine = _engine_repo_for_manifest_contract()
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    parent = contracts / "parent.xsd"
    parent_content = ("<!DOCTYPE xs:schema>" + _xsd_including("child.xsd")).encode()
    parent.write_bytes(parent_content)
    (contracts / "child.xsd").write_text(_xsd(), encoding="utf-8")

    assert _xml_include_targets(parent_content, root_kind="xsd") == []

    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from appbuilder.contracts.xml_contracts import _load_schema_bundle\n"
        "root = Path(sys.argv[2])\n"
        "_load_schema_bundle(\n"
        "    xsd_path=root / 'parent.xsd',\n"
        "    interface_name='acct',\n"
        "    package_root=root,\n"
        ")\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, str(engine), str(contracts)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    diagnostic = completed.stdout + completed.stderr
    assert "document type (DTD)" in diagnostic
    assert "not supported in design-time contract files" in diagnostic


def _collapse_relative(value: str) -> str:
    """Collapse '.'/'..' segments purely (no filesystem), matching how the Engine
    normalises rule/legacy paths, so parity compares target files not spelling."""
    parts: list[str] = []
    for part in value.strip().replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == ".." and parts:
            parts.pop()
        else:
            parts.append(part)
    return "/".join(parts)


def test_manifest_seed_matches_real_engine_referenced_paths():
    """Cross-repo parity: Studio's generation-input seed must cover every file the
    REAL Engine's ProjectDefinition.referenced_paths() expects, across the Engine's
    golden manifest corpus (CRUD, file, kafka, router). This is the durable guard
    against _MANIFEST_ARTIFACT_KEYS drifting from the Engine's manifest contract --
    a hand-derived mirror is exactly where blind spots hide. Skips when no Engine
    checkout is resolvable."""
    engine = _engine_repo_for_manifest_contract()
    manifests = sorted(
        {
            *(engine / "tests" / "fixtures").rglob("manifest.yaml"),
            *(engine / "examples").rglob("app-definition.yaml"),
        }
    )
    if len(manifests) < 3:
        pytest.skip("Engine manifest corpus too small for a meaningful parity check")

    script = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from appbuilder.contracts.manifest import load_project_definition\n"
        "out = {}\n"
        "for target in sys.argv[2:]:\n"
        "    try:\n"
        "        definition = load_project_definition(Path(target))\n"
        "        out[target] = [str(p) for p in definition.referenced_paths()]\n"
        "    except Exception:\n"
        "        out[target] = None\n"
        "print(json.dumps(out))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, str(engine), *[str(m) for m in manifests]],
        check=True,
        capture_output=True,
        text=True,
    )
    engine_refs = json.loads(completed.stdout)

    checked = 0
    for manifest_path in manifests:
        refs = engine_refs.get(str(manifest_path))
        if refs is None:
            continue  # fixture the Engine itself rejects -- nothing to compare
        data = yaml.safe_load(Path(manifest_path).read_text(encoding="utf-8"))
        seed = {_collapse_relative(value) for value in _manifest_artifact_paths(data)}
        engine_set = {_collapse_relative(ref) for ref in refs}
        # Both directions matter. Missing paths are false negatives (a real input
        # change goes undetected); extra paths are false positives (an unrelated
        # file invents a regen delta). Checking only one direction let a
        # broader-than-the-Engine extraction pass.
        missing = sorted(engine_set - seed)
        extra = sorted(seed - engine_set)
        assert not missing, (
            f"{manifest_path}: seed MISSES Engine-referenced paths {missing} -- "
            "extraction has drifted below referenced_paths()"
        )
        assert not extra, (
            f"{manifest_path}: seed invents paths the Engine never reads {extra} -- "
            "extraction is broader than referenced_paths() and would cause false deltas"
        )
        checked += 1
    assert checked >= 3, "parity validated too few manifests to be meaningful"


def test_regen_binding_rejects_generated_package_outside_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED", "true")
    session = ProjectSession(session_id="session-a", workspace_root=str(tmp_path / "workspace"))
    workspace_root = Path(session.workspace_root or "")
    manifest = workspace_root / "output" / "demo" / "app-definition.yaml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("app_name: demo\n", encoding="utf-8")
    outside_generated = tmp_path / "outside-generated"
    outside_generated.mkdir()

    with pytest.raises(RegenBindingError, match="outside the session workspace"):
        capture_generated_package(
            session,
            generated_package_path=outside_generated,
            manifest_path=manifest,
        )


def test_regen_binding_rejects_symlink_inside_generated_package(monkeypatch, tmp_path):
    monkeypatch.setenv("EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED", "true")
    session = ProjectSession(session_id="session-a", workspace_root=str(tmp_path / "workspace"))
    workspace_root = Path(session.workspace_root or "")
    export_dir = workspace_root / "output" / "demo"
    generated = export_dir / "generated-app"
    manifest = export_dir / "app-definition.yaml"
    generated.mkdir(parents=True)
    manifest.write_text("app_name: demo\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (generated / "escape").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation is not available in this environment: {exc}")

    with pytest.raises(RegenBindingError, match="contains a symlink"):
        capture_generated_package(
            session,
            generated_package_path=generated,
            manifest_path=manifest,
        )
