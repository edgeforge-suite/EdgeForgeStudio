"""Lifecycle and drift-control tests for the maintained synthetic sample packs."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from app.main import app
from app.models.project import STUDIO_PROJECT_SCHEMA_VERSION, ProjectSession, StudioProject
from app.services.completeness_service import build_completeness_report
from app.services.package_writer import write_package_result
from app.services.project_file_service import (
    deserialize_project,
    restore_session,
    serialize_project,
    snapshot_session_for_save,
)
from scripts.sample_pack_derivatives import (
    DERIVATIVE_MAP,
    SamplePackDerivativeError,
    compare_pack_derivatives,
    extract_pack_derivatives,
    write_pack_derivatives,
)
from tests.session_helpers import get_session, reset_session, save_session

ROOT = Path(__file__).resolve().parents[1]
PACK_ROOT = ROOT / "docs" / "sample-packs"
PACK_IDS = tuple(DERIVATIVE_MAP)
PROOF_KEYS = {
    "pack_id",
    "archetype",
    "target_profile",
    "expected_entities",
    "expected_manifest_schema_version",
    "expected_export_warnings",
    "expected_generation_warnings",
    "expected_harness_warnings",
    "harness_applies",
    "min_studio_project_schema_version",
    "expected_export_dir",
    "expected_exported_artifacts",
}
_SAVE_METADATA_FIELDS = {
    "project_revision",
    "updated_at",
    "saved_at",
    "modified_by",
}
_PACKAGE_PATH_FIELDS = {
    "spec",
    "mapping_path",
    "xsd_path",
    "wsdl_path",
    "sample_path",
    "request_sample_path",
    "response_sample_path",
    "file_path",
    "rule_path",
    "raw_spec_filename",
}
_WRITER_DERIVED_PATH_FIELDS = _PACKAGE_PATH_FIELDS - {
    "request_sample_path",
    "response_sample_path",
    "raw_spec_filename",
}

client = TestClient(app)


def _pack_dir(pack_id: str) -> Path:
    return PACK_ROOT / pack_id


def _project_path(pack_id: str) -> Path:
    return _pack_dir(pack_id) / "project" / f"{pack_id}.edgeforge-project.json"


def _load_raw_project(pack_id: str) -> dict[str, Any]:
    return json.loads(_project_path(pack_id).read_text(encoding="utf-8"))


def _load_pack(pack_id: str) -> tuple[StudioProject, dict[str, Any]]:
    project = deserialize_project(_project_path(pack_id).read_text(encoding="utf-8"))
    proof = json.loads((_pack_dir(pack_id) / "expected-proof.json").read_text(encoding="utf-8"))
    return project, proof


def _authored_state(project: StudioProject) -> dict[str, Any]:
    state = project.model_dump(mode="json")
    for field in _SAVE_METADATA_FIELDS:
        state.pop(field, None)
    return state


def _filesystem_field_values(value: Any, *, parent_key: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _PACKAGE_PATH_FIELDS and isinstance(child, str) and child:
                yield key, child
            yield from _filesystem_field_values(child, parent_key=key)
    elif isinstance(value, list):
        for child in value:
            yield from _filesystem_field_values(child, parent_key=parent_key)


def _assert_safe_package_path(field: str, value: str) -> None:
    normalized = value.replace("\\", "/")
    assert not PurePosixPath(normalized).is_absolute(), f"{field} must be package-relative: {value}"
    assert ".." not in PurePosixPath(normalized).parts, f"{field} contains parent traversal: {value}"
    assert re.match(r"^[A-Za-z]:/", normalized) is None, f"{field} contains a drive path: {value}"
    home = str(Path.home())
    assert not value.startswith(home), f"{field} contains a local home path"


def _assert_exact_tree(actual: list[str], expected: list[str]) -> None:
    assert sorted(actual) == expected


def _schema_version_parts(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def _selected_canonical_entity_names(project: StudioProject | ProjectSession) -> list[str]:
    entities_by_source = {entity.name: entity for entity in project.classified_entities}
    return [entities_by_source[name].display_name() for name in project.selected_entity_names]


def _entity_operation_map(session: ProjectSession) -> dict[str, list[str]]:
    interfaces_by_entity = {
        interface.entity_name: interface for interface in session.upstream_interfaces
    }
    entities_by_source = {entity.name: entity for entity in session.classified_entities}
    return {
        source_name: [
            operation.name
            for operation in interfaces_by_entity[
                entities_by_source[source_name].display_name()
            ].operations
        ]
        for source_name in session.selected_entity_names
    }


def _json_values_for_key(value: Any, key: str) -> list[Any]:
    values: list[Any] = []
    if isinstance(value, dict):
        for child_key, child in value.items():
            if child_key == key:
                values.append(child)
            values.extend(_json_values_for_key(child, key))
    elif isinstance(value, list):
        for child in value:
            values.extend(_json_values_for_key(child, key))
    return values


def test_sample_pack_root_and_pack_structures_are_exact():
    assert {path.name for path in PACK_ROOT.iterdir()} == {"README.md", *PACK_IDS}

    for pack_id in PACK_IDS:
        pack_dir = _pack_dir(pack_id)
        expected_files = {
            "README.md",
            "expected-proof.json",
            f"project/{pack_id}.edgeforge-project.json",
            *DERIVATIVE_MAP[pack_id],
        }
        actual_files = {
            path.relative_to(pack_dir).as_posix()
            for path in pack_dir.rglob("*")
            if path.is_file()
        }
        assert actual_files == expected_files

    forbidden_names = {
        "app-definition.yaml",
        "pom.xml",
        "target",
    }
    assert not [
        path
        for path in PACK_ROOT.rglob("*")
        if path.name in forbidden_names or path.suffix == ".java"
    ]


@pytest.mark.parametrize("pack_id", PACK_IDS)
def test_sample_pack_lifecycle_round_trip_and_export(
    pack_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    def forbid_process_spawn(*_args, **_kwargs):
        pytest.fail("sample-pack lifecycle attempted to spawn a subprocess")

    monkeypatch.setattr(subprocess, "Popen", forbid_process_spawn)
    raw = _load_raw_project(pack_id)
    project, proof = _load_pack(pack_id)

    minimum_schema = proof["min_studio_project_schema_version"]
    assert _schema_version_parts(raw["studio_project_schema_version"]) >= _schema_version_parts(
        minimum_schema
    )
    assert project.studio_project_schema_version == STUDIO_PROJECT_SCHEMA_VERSION
    assert _schema_version_parts(project.studio_project_schema_version) >= _schema_version_parts(
        minimum_schema
    )
    assert project.app_archetype == proof["archetype"]
    assert project.target_profile == proof["target_profile"]
    assert _selected_canonical_entity_names(project) == proof["expected_entities"]
    assert project.capabilities.knowledge_assist_enabled is False
    assert project.ks_active is False

    session = ProjectSession(appbuilder_repo_path="")
    restore_session(project, session)
    assert session.capabilities.knowledge_assist_enabled is False
    assert session.ks_active is False

    saved = snapshot_session_for_save(session)
    reopened = deserialize_project(serialize_project(saved))
    assert reopened == saved
    assert _authored_state(reopened) == _authored_state(project)

    report = build_completeness_report(session)
    assert report.is_exportable(), [item.message for item in report.manual()]
    result = write_package_result(session, tmp_path)
    manifest = yaml.safe_load((result.project_dir / "app-definition.yaml").read_text(encoding="utf-8"))

    assert result.project_dir.name == proof["expected_export_dir"]
    assert result.warnings == proof["expected_export_warnings"]
    _assert_exact_tree(result.written, proof["expected_exported_artifacts"])
    assert manifest["schema_version"] == proof["expected_manifest_schema_version"]
    assert manifest["app_archetype"] == proof["archetype"]
    assert manifest["target_profile"] == proof["target_profile"]


@pytest.mark.parametrize("pack_id", PACK_IDS)
def test_sample_pack_public_open_save_export_workflow(pack_id: str, tmp_path: Path):
    reset_session()
    try:
        _, proof = _load_pack(pack_id)
        project_path = _project_path(pack_id)
        opened = client.post(
            "/project/open",
            files={
                "project_file": (
                    project_path.name,
                    project_path.read_bytes(),
                    "application/json",
                )
            },
            follow_redirects=False,
        )
        assert opened.status_code == 303

        session = get_session()
        original_selected_entity_names = list(session.selected_entity_names)
        original_iface = session.upstream_interfaces[0].model_copy(deep=True)
        original_mappings = [
            mapping.model_dump(mode="json") for mapping in original_iface.operation_mappings
        ]
        assert original_iface.spec is None

        if session.app_archetype == "crud":
            entity_op_map = _entity_operation_map(session)
            saved = client.post(
                "/entities/save",
                json={
                    "entities": list(session.selected_entity_names),
                    "operations": list(session.selected_operation_names),
                    "entity_op_map": entity_op_map,
                },
            )
            assert saved.status_code == 200

        persisted = get_session()
        persisted_iface = persisted.upstream_interfaces[0]
        assert persisted.selected_entity_names == original_selected_entity_names
        assert _selected_canonical_entity_names(persisted) == proof["expected_entities"]
        assert persisted_iface.spec is None
        assert persisted_iface.spec_content == original_iface.spec_content
        assert persisted.raw_spec_content == original_iface.spec_content
        assert [
            mapping.model_dump(mode="json") for mapping in persisted_iface.operation_mappings
        ] == original_mappings

        persisted.output_path = str(tmp_path)
        save_session(persisted)
        exported = client.post("/export/write")
        assert exported.status_code == 200, exported.text
        payload = exported.json()
        assert payload["warnings"] == proof["expected_export_warnings"]
        _assert_exact_tree(payload["files"], proof["expected_exported_artifacts"])

        manifest = yaml.safe_load(
            (tmp_path / proof["expected_export_dir"] / "app-definition.yaml").read_text(
                encoding="utf-8"
            )
        )
        assert manifest["schema_version"] == proof["expected_manifest_schema_version"]
        assert manifest["app_archetype"] == proof["archetype"]
        assert manifest["target_profile"] == proof["target_profile"]
    finally:
        reset_session()


@pytest.mark.parametrize("pack_id", PACK_IDS)
def test_sample_pack_proof_metadata_is_static_and_matches_project(pack_id: str):
    raw = _load_raw_project(pack_id)
    _, proof = _load_pack(pack_id)

    assert set(proof) == PROOF_KEYS
    assert proof["pack_id"] == pack_id
    assert proof["archetype"] == raw["app_archetype"]
    assert proof["target_profile"] == raw["target_profile"]
    project, _ = _load_pack(pack_id)
    assert proof["expected_entities"] == _selected_canonical_entity_names(project)
    assert proof["expected_manifest_schema_version"] == "2.0"
    assert proof["expected_export_warnings"] == []
    assert proof["expected_generation_warnings"] == []
    assert proof["expected_harness_warnings"] == []
    assert proof["expected_exported_artifacts"] == sorted(proof["expected_exported_artifacts"])

    serialized = json.dumps(proof)
    assert "last_verified" not in proof
    assert "repository_sha" not in proof
    assert "timestamp" not in serialized.lower()
    assert str(Path.home()) not in serialized


@pytest.mark.parametrize("pack_id", PACK_IDS)
def test_sample_pack_paths_are_clean_and_export_state_is_absent(pack_id: str):
    raw = _load_raw_project(pack_id)

    assert raw["output_path"] == ""
    assert raw["appbuilder_repo_path"] == ""
    assert "last_export_path" not in raw
    assert "last_export_timestamp" not in raw
    assert "last_generated_app_path" not in raw
    assert raw.get("manifest_revisions", []) == []
    assert raw.get("ks_workspace_state", {}).get("manifest_revisions", []) == []

    path_values = list(_filesystem_field_values(raw))
    assert path_values
    assert [
        (field, value)
        for field, value in path_values
        if field in _WRITER_DERIVED_PATH_FIELDS
    ] == []
    for field, value in path_values:
        _assert_safe_package_path(field, value)


@pytest.mark.parametrize("pack_id", PACK_IDS)
def test_sample_pack_review_derivatives_match_canonical_project(pack_id: str):
    pack_dir = _pack_dir(pack_id)

    assert compare_pack_derivatives(pack_dir) == []
    expected = extract_pack_derivatives(pack_dir)
    assert set(expected) == set(DERIVATIVE_MAP[pack_id])
    for relative_path, content in expected.items():
        assert (_pack_dir(pack_id) / relative_path).read_bytes() == content


def test_crud_sample_paths_match_studio_camel_case_slug_convention():
    expected = {
        "fs-account-servicing": (
            "upstream/sample-createaccount-request.json",
            "upstream/sample-createaccount-response.json",
        ),
        "hc-authorization-status": (
            "upstream/sample-createauthorization-request.json",
            "upstream/sample-createauthorization-response.json",
        ),
    }
    for pack_id, paths in expected.items():
        operation = _load_raw_project(pack_id)["upstream_interfaces"][0]["operations"][0]
        assert (operation["request_sample_path"], operation["response_sample_path"]) == paths


@pytest.mark.parametrize(
    ("pack_id", "field_name", "expected_spec_values", "expected_sample_value"),
    [
        (
            "fs-account-servicing",
            "balance",
            [0.0, 640.25, 875.5, 875.5, 1250.0, 3200.75],
            1250.0,
        ),
        (
            "hc-authorization-status",
            "serviceUnits",
            [2.0, 3.0, 4.0, 6.0, 6.0, 8.0],
            4.0,
        ),
    ],
)
def test_decimal_examples_use_decimal_shaped_json_numbers(
    pack_id: str,
    field_name: str,
    expected_spec_values: list[float],
    expected_sample_value: float,
):
    project, _ = _load_pack(pack_id)
    interface = project.upstream_interfaces[0]

    embedded_spec = json.loads(interface.spec_content or "{}")
    raw_spec = json.loads(project.raw_spec_content or "{}")
    assert embedded_spec == raw_spec
    spec_values = sorted(
        value
        for value in _json_values_for_key(embedded_spec, field_name)
        if isinstance(value, (int, float))
    )
    assert spec_values == expected_spec_values
    assert all(type(value) is float for value in spec_values)

    operation = interface.operations[0]
    for content in (operation.request_sample_content, operation.response_sample_content):
        value = json.loads(content or "{}")[field_name]
        assert value == expected_sample_value
        assert type(value) is float


def test_hc_authorization_alias_preserves_external_contract_and_canonical_ownership(
    tmp_path: Path,
):
    project, proof = _load_pack("hc-authorization-status")
    entity = project.classified_entities[0]

    assert project.selected_entity_names == ["Authorization"]
    assert entity.name == entity.source_schema == "Authorization"
    assert entity.display_name() == "AuthorizationRecord"
    assert proof["expected_entities"] == ["AuthorizationRecord"]
    assert all(
        operation.entity_candidates == ["AuthorizationRecord"]
        for operation in project.classified_operations
    )
    assert all(operation.resource == "Authorization" for operation in project.classified_operations)
    assert all(
        operation.request_schema in {None, "Authorization"}
        and operation.response_schema == "Authorization"
        and operation.path.startswith("/authorizations")
        for operation in project.classified_operations
    )
    assert [decision.entity for decision in project.identity_role_decisions] == [
        "AuthorizationRecord"
    ]

    upstream = project.upstream_interfaces[0]
    assert upstream.entity_name == "AuthorizationRecord"
    assert all(
        mapping.target.startswith("AuthorizationRecord.")
        for operation in upstream.operation_mappings
        for mapping in (*operation.request_mappings, *operation.response_mappings)
    )
    external_spec = json.loads(upstream.spec_content or "{}")
    assert set(external_spec["components"]["schemas"]) == {"Authorization"}
    assert set(external_spec["paths"]) == {
        "/authorizations",
        "/authorizations/{authorizationId}",
    }

    downstream = project.downstream_interfaces[0]
    assert downstream.entity_name == "AuthorizationRecord"
    assert downstream.root_element == "Authorization"
    assert 'name="Authorization"' in (downstream.xsd_content or "")
    assert all(
        mapping.source.startswith("AuthorizationRecord.")
        for mapping in downstream.field_mappings
    )

    handoff = project.data_handoffs[0]
    assert handoff.entity_name == "AuthorizationRecord"
    assert handoff.table_name == "authorization_staging"
    assert all(
        mapping.source.startswith("AuthorizationRecord.")
        for mapping in handoff.field_mappings
    )
    assert [rule_set.entity_name for rule_set in project.entity_rules] == [
        "AuthorizationRecord"
    ]

    session = ProjectSession()
    restore_session(project, session)
    result = write_package_result(session, tmp_path)
    assert result.warnings == []
    manifest = yaml.safe_load(
        (result.project_dir / "app-definition.yaml").read_text(encoding="utf-8")
    )
    assert manifest["identity_overrides"][0]["entity"] == "AuthorizationRecord"
    assert manifest["downstream_interfaces"][0]["root_element"] == "Authorization"

    for relative_path, path_key in (
        ("upstream/authorization-api-mapping.yaml", "target"),
        ("downstream/authorization-mapping.yaml", "source"),
        ("data-handoffs/authorization-staging-table-mapping.yaml", "source"),
    ):
        mapping_text = (result.project_dir / relative_path).read_text(encoding="utf-8")
        mapping = yaml.safe_load(mapping_text)
        assert mapping["entity"] == "AuthorizationRecord"
        assert "AuthorizationRecord." in mapping_text
        assert f"{path_key}: Authorization." not in mapping_text

    rule_path = result.project_dir / "rules/authorizationrecord-business-rules.yaml"
    assert yaml.safe_load(rule_path.read_text(encoding="utf-8"))["entity"] == (
        "AuthorizationRecord"
    )


def test_review_derivative_guard_detects_mutation(tmp_path: Path):
    source = _pack_dir("fs-account-servicing")
    mutated = tmp_path / source.name
    shutil.copytree(source, mutated)
    relative_path = next(iter(DERIVATIVE_MAP[source.name]))
    derivative = mutated / relative_path
    derivative.write_bytes(derivative.read_bytes() + b"\n")

    assert compare_pack_derivatives(mutated) == [
        f"{relative_path}: differs from the canonical project JSON"
    ]


@pytest.mark.parametrize("mutation", ["missing", "wrong-type"])
def test_derivative_extractor_rejects_invalid_source_fields(tmp_path: Path, mutation: str):
    source = _pack_dir("ins-claims-intake-router")
    mutated = tmp_path / source.name
    shutil.copytree(source, mutated)
    project_path = mutated / "project" / f"{source.name}.edgeforge-project.json"
    raw = json.loads(project_path.read_text(encoding="utf-8"))
    if mutation == "missing":
        del raw["upstream_interfaces"][0]["spec_content"]
    else:
        raw["upstream_interfaces"][0]["spec_content"] = {"not": "text"}
    project_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(SamplePackDerivativeError, match="spec_content"):
        extract_pack_derivatives(mutated)


def test_derivative_regeneration_is_byte_stable(tmp_path: Path):
    source = _pack_dir("hc-authorization-status")
    regenerated = tmp_path / source.name
    shutil.copytree(source, regenerated)
    write_pack_derivatives(regenerated)
    first = {
        relative_path: (regenerated / relative_path).read_bytes()
        for relative_path in DERIVATIVE_MAP[source.name]
    }
    write_pack_derivatives(regenerated)
    second = {
        relative_path: (regenerated / relative_path).read_bytes()
        for relative_path in DERIVATIVE_MAP[source.name]
    }

    assert second == first
    assert compare_pack_derivatives(regenerated) == []


@pytest.mark.parametrize("mutation", ["extra", "missing"])
def test_exact_export_tree_guard_detects_mutation(mutation: str):
    expected = json.loads(
        (_pack_dir("ins-claims-intake-router") / "expected-proof.json").read_text(
            encoding="utf-8"
        )
    )["expected_exported_artifacts"]
    actual = list(expected)
    if mutation == "extra":
        actual.append("unexpected-artifact.txt")
    else:
        actual.pop()

    with pytest.raises(AssertionError):
        _assert_exact_tree(actual, expected)


def test_committed_contract_hosts_and_identifiers_are_synthetic():
    review_text = "\n".join(
        path.read_text(encoding="utf-8")
        for pack_id in PACK_IDS
        for path in (_pack_dir(pack_id) / "contracts").glob("*.json")
    )
    urls = re.findall(r"https://[^\"\\s]+", review_text)

    assert urls
    assert set(urls) == {"https://api.example.com"}
    for prefix in ("ACCT-", "CUST-", "AUTH-", "MBR-", "CLM-", "POL-"):
        assert prefix in review_text
