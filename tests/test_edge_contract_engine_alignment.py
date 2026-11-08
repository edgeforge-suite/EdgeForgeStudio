"""Proof tests that Studio edge-contract exports align with Engine manifest shape."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest
import yaml

from app.models.project import (
    DataHandoff,
    DownstreamInterface,
    FieldMapping,
    LayoutField,
    ProjectSession,
    UpstreamInterface,
)
from app.services.edge_contracts import INCOMPLETE, REFERENCE_ONLY, edge_contract_readiness
from app.services.manifest_generator import build_manifest_dict
from app.services.package_writer import PackageWriteError, write_package_result
from tests.test_package_writer import _full_session


def _edge_contract_session() -> ProjectSession:
    session = ProjectSession()
    session.app_name = "Edge Contract Proof"
    session.bounded_context = "edge-contract-proof"
    session.target_profile = "springboot-legacy-compatible"
    session.upstream_interfaces = [
        UpstreamInterface(
            name="fixed-in",
            type="file-fixed-width",
            spec="upstream/fixed-in-layout.yaml",
            spec_content=(
                "format: fixed-width\n"
                "record_types:\n"
                "  data:\n"
                "    fields: []\n"
            ),
            entity_name="Account",
            field_mappings=[
                FieldMapping(source="account_id", target="Account.accountId"),
            ],
            mapping_path="upstream/fixed-in-mapping.yaml",
        ),
        UpstreamInterface(
            name="csv-in",
            type="file-csv",
            spec="upstream/csv-in-layout.yaml",
            spec_content=(
                "format: csv\n"
                "record_types:\n"
                "  data:\n"
                "    fields:\n"
                "      - name: account_id\n"
                "        column: 1\n"
            ),
            sample_path="upstream/csv-in-sample.csv",
            sample_content="accountId,status\nA1,ACTIVE\n",
        ),
        UpstreamInterface(
            name="xml-in",
            type="xml-xsd",
            xsd_path="contracts/xml-in.xsd",
            xsd_content="<xs:schema xmlns:xs=\"http://www.w3.org/2001/XMLSchema\"/>",
            root_element="acct:Account",
            namespace="urn:accounts:v1",
            namespace_alias="acct",
        ),
        UpstreamInterface(
            name="soap-in",
            type="soap-wsdl",
            wsdl_path="contracts/soap-in.wsdl",
            wsdl_content="<definitions/>",
            service="AccountService",
            port="AccountPort",
            binding="AccountBinding",
            selected_operation_name="getAccount",
        ),
    ]
    session.downstream_interfaces = [
        DownstreamInterface(
            name="fixed-out",
            type="file-fixed-width",
            spec="downstream/fixed-out-layout.yaml",
            layout_fields=[LayoutField(name="account_id", start=1, length=12)],
            field_mappings=[FieldMapping(source="Account.accountId", target="account_id")],
            mapping_path="downstream/fixed-out-mapping.yaml",
        ),
        DownstreamInterface(
            name="csv-out",
            type="file-csv",
            spec="downstream/csv-out-layout.yaml",
            spec_content=(
                "format: csv\n"
                "record_types:\n"
                "  data:\n"
                "    fields:\n"
                "      - name: account_id\n"
                "        column: 1\n"
            ),
            sample_path="downstream/csv-out-sample.csv",
            sample_content="accountId,status\nA1,ACTIVE\n",
        ),
        DownstreamInterface(
            name="xml-out",
            type="xml-xsd",
            xsd_path="contracts/xml-out.xsd",
            xsd_content="<xs:schema xmlns:xs=\"http://www.w3.org/2001/XMLSchema\"/>",
            root_element="acct:AccountOut",
        ),
        DownstreamInterface(
            name="soap-out",
            type="soap-wsdl",
            wsdl_path="contracts/soap-out.wsdl",
            wsdl_content="<definitions/>",
        ),
    ]
    session.data_handoffs = [
        DataHandoff(
            name="account-staging",
            type="staging-table",
            spec="data-handoffs/account-staging.sql",
            ddl_content="CREATE TABLE account_staging (account_id VARCHAR(36));",
        )
    ]
    return session


def _by_name(entries: list[dict]) -> dict[str, dict]:
    return {entry["name"]: entry for entry in entries}


def _assert_package_relative(path: str) -> None:
    parsed = PurePosixPath(path)
    assert not parsed.is_absolute()
    assert ".." not in parsed.parts
    assert "://" not in path


def test_edge_contract_manifest_uses_only_engine_supported_interface_arrays():
    manifest = build_manifest_dict(_edge_contract_session())

    assert "upstream_interfaces" in manifest
    assert "downstream_interfaces" in manifest
    assert "edge_contracts" not in manifest
    assert "upstream_contracts" not in manifest
    assert "downstream_contracts" not in manifest

    upstream_types = {entry["type"] for entry in manifest["upstream_interfaces"]}
    downstream_types = {entry["type"] for entry in manifest["downstream_interfaces"]}
    edge_types = {"file-fixed-width", "file-csv", "xml-xsd", "soap-wsdl"}

    assert upstream_types == edge_types
    assert downstream_types == edge_types
    assert all(entry["type"] != "soap" for entry in manifest["upstream_interfaces"])
    assert all(entry["type"] != "soap" for entry in manifest["downstream_interfaces"])
    assert all(item["type"] not in edge_types for item in manifest.get("data_handoffs", []))


def test_upstream_edge_contract_manifest_entries_match_engine_shape():
    entries = _by_name(build_manifest_dict(_edge_contract_session())["upstream_interfaces"])

    assert entries["fixed-in"] == {
        "name": "fixed-in",
        "type": "file-fixed-width",
        "spec": "upstream/fixed-in-layout.yaml",
        "mapping": "upstream/fixed-in-mapping.yaml",
    }
    assert entries["csv-in"] == {
        "name": "csv-in",
        "type": "file-csv",
        "spec": "upstream/csv-in-layout.yaml",
        "samples": ["upstream/csv-in-sample.csv"],
    }
    assert entries["xml-in"] == {
        "name": "xml-in",
        "type": "xml-xsd",
        "xsd_path": "contracts/xml-in.xsd",
        "root_element": "acct:Account",
        "namespace": "urn:accounts:v1",
        "namespace_alias": "acct",
    }
    assert entries["soap-in"] == {
        "name": "soap-in",
        "type": "soap-wsdl",
        "wsdl_path": "contracts/soap-in.wsdl",
        "service": "AccountService",
        "port": "AccountPort",
        "binding": "AccountBinding",
        "mapping": "mappings/soap-in-operation-mapping.yaml",
    }
    assert all("spec_url" not in entry for entry in entries.values())


def test_downstream_edge_contract_manifest_entries_match_engine_shape():
    entries = _by_name(build_manifest_dict(_edge_contract_session())["downstream_interfaces"])

    assert entries["fixed-out"]["type"] == "file-fixed-width"
    assert entries["fixed-out"]["spec"] == "downstream/fixed-out-layout.yaml"
    assert entries["fixed-out"]["mapping"] == "downstream/fixed-out-mapping.yaml"
    assert entries["csv-out"] == {
        "name": "csv-out",
        "type": "file-csv",
        "spec": "downstream/csv-out-layout.yaml",
        "samples": ["downstream/csv-out-sample.csv"],
    }
    assert entries["xml-out"] == {
        "name": "xml-out",
        "type": "xml-xsd",
        "xsd_path": "contracts/xml-out.xsd",
        "root_element": "acct:AccountOut",
    }
    assert entries["soap-out"] == {
        "name": "soap-out",
        "type": "soap-wsdl",
        "wsdl_path": "contracts/soap-out.wsdl",
    }
    assert all("spec_url" not in entry for entry in entries.values())


def test_package_writer_outputs_manifest_paths_and_artifacts_that_align(tmp_path):
    result = write_package_result(_edge_contract_session(), tmp_path)
    project_dir = result.project_dir
    manifest = yaml.safe_load((project_dir / "app-definition.yaml").read_text(encoding="utf-8"))

    path_fields: list[tuple[str, str]] = []
    for entry in manifest["upstream_interfaces"] + manifest["downstream_interfaces"]:
        for key in ("spec", "xsd_path", "wsdl_path", "mapping", "sample"):
            if entry.get(key):
                path_fields.append((entry["name"], entry[key]))
        for sample in entry.get("samples", []):
            path_fields.append((entry["name"], sample))

    for _, rel_path in path_fields:
        _assert_package_relative(rel_path)
        assert rel_path in result.written
        assert (project_dir / rel_path).exists()

    for expected in [
        "upstream/fixed-in-layout.yaml",
        "upstream/fixed-in-mapping.yaml",
        "upstream/csv-in-layout.yaml",
        "upstream/csv-in-sample.csv",
        "contracts/xml-in.xsd",
        "contracts/soap-in.wsdl",
        "mappings/soap-in-operation-mapping.yaml",
        "downstream/fixed-out-layout.yaml",
        "downstream/fixed-out-mapping.yaml",
        "downstream/csv-out-layout.yaml",
        "downstream/csv-out-sample.csv",
        "contracts/xml-out.xsd",
        "contracts/soap-out.wsdl",
    ]:
        assert expected in result.written
        assert (project_dir / expected).exists()

    fixed_mapping = yaml.safe_load((project_dir / "upstream/fixed-in-mapping.yaml").read_text(encoding="utf-8"))
    assert fixed_mapping == {
        "entity": "Account",
        "direction": "inbound",
        "field_mappings": [
            {"source": "account_id", "target": "Account.accountId"},
        ],
    }


def test_reference_only_readiness_matches_manifest_and_package_warning(tmp_path):
    session = ProjectSession(
        app_name="Reference Only",
        bounded_context="reference-only",
        target_profile="springboot-legacy-compatible",
        upstream_interfaces=[
            UpstreamInterface(
                name="xml-ref",
                type="xml-xsd",
                xsd_path="contracts/xml-ref.xsd",
                root_element="Root",
            )
        ],
    )
    readiness = edge_contract_readiness(session.upstream_interfaces[0], direction="upstream")

    manifest = build_manifest_dict(session)
    result = write_package_result(session, tmp_path)

    assert readiness.status == REFERENCE_ONLY
    assert readiness.will_export is True
    assert manifest["upstream_interfaces"][0]["xsd_path"] == "contracts/xml-ref.xsd"
    assert any("no uploaded artifact content" in warning for warning in result.warnings)
    assert not (result.project_dir / "contracts/xml-ref.xsd").exists()


def test_incomplete_readiness_matches_manifest_omit_and_package_block(tmp_path):
    session = ProjectSession(
        app_name="Incomplete",
        bounded_context="incomplete",
        target_profile="springboot-legacy-compatible",
        downstream_interfaces=[DownstreamInterface(name="csv-out", type="file-csv")],
    )
    readiness = edge_contract_readiness(session.downstream_interfaces[0], direction="downstream")

    manifest = build_manifest_dict(session)

    assert readiness.status == INCOMPLETE
    assert readiness.will_export is False
    assert "downstream_interfaces" not in manifest
    with pytest.raises(PackageWriteError):
        write_package_result(session, tmp_path)


def test_duplicate_artifact_paths_with_different_content_fail_deterministically(tmp_path):
    session = ProjectSession(
        app_name="Duplicate Artifacts",
        bounded_context="duplicate-artifacts",
        target_profile="springboot-legacy-compatible",
        upstream_interfaces=[
            UpstreamInterface(
                name="xml-a",
                type="xml-xsd",
                xsd_path="contracts/shared.xsd",
                xsd_content="<xs:schema id=\"a\"/>",
                root_element="A",
            ),
            UpstreamInterface(
                name="xml-b",
                type="xml-xsd",
                xsd_path="contracts/shared.xsd",
                xsd_content="<xs:schema id=\"b\"/>",
                root_element="B",
            ),
        ],
    )

    with pytest.raises(PackageWriteError) as exc:
        write_package_result(session, tmp_path)

    assert "Duplicate package artifact path 'contracts/shared.xsd'" in str(exc.value)


def test_openapi_and_existing_fixed_width_package_behavior_remain_unchanged(tmp_path):
    session = _full_session()

    result = write_package_result(session, tmp_path)
    manifest = yaml.safe_load((result.project_dir / "app-definition.yaml").read_text(encoding="utf-8"))

    assert manifest["upstream_interfaces"][0]["type"] == "rest-json"
    assert manifest["upstream_interfaces"][0]["spec_url"] == "https://example.com/synthetic-account.json"
    assert manifest["downstream_interfaces"][0]["type"] == "file-fixed-width"
    assert manifest["downstream_interfaces"][0]["spec"] == "downstream/eod-handoff-file-layout.yaml"
    assert "edge_contracts" not in manifest
    assert (result.project_dir / "downstream/eod-handoff-file-layout.yaml").exists()


@pytest.mark.skipif(
    not os.environ.get("EDGEFORGE_ENGINE_REPO"),
    reason="Optional Engine schema smoke requires EDGEFORGE_ENGINE_REPO.",
)
def test_optional_engine_manifest_v2_contract_accepts_studio_edge_contract_export(tmp_path):
    engine_repo = Path(os.environ["EDGEFORGE_ENGINE_REPO"]).expanduser().resolve()
    schema_path = engine_repo / "appbuilder/schema/manifest-v2.schema.json"
    if not schema_path.exists():
        pytest.fail(f"Configured Engine checkout is missing manifest-v2 schema: {schema_path}")

    result = write_package_result(_edge_contract_session(), tmp_path)
    manifest_path = result.project_dir / "app-definition.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == "2.0"
    assert schema["properties"]["schema_version"]["enum"] == ["2.0"]

    script = (
        "import json, pathlib, sys, yaml\n"
        "from jsonschema import Draft202012Validator\n"
        "engine_repo = pathlib.Path(sys.argv[1])\n"
        "schema = json.loads(pathlib.Path(sys.argv[2]).read_text())\n"
        "manifest_path = pathlib.Path(sys.argv[3])\n"
        "manifest = yaml.safe_load(manifest_path.read_text())\n"
        "Draft202012Validator(schema).validate(manifest)\n"
        "sys.path.insert(0, str(engine_repo))\n"
        "from appbuilder.contracts.manifest import load_project_definition\n"
        "definition = load_project_definition(manifest_path)\n"
        "assert definition.schema_version == '2.0'\n"
    )
    subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(engine_repo),
            str(schema_path),
            str(manifest_path),
        ],
        check=True,
    )
