"""Tests for shared proof-runner helper utilities."""

import json

import pytest

from scripts.proof_runner_helpers import (
    assert_json_array,
    discover_collection_path,
    resolve_generated_jar,
)


def test_discover_collection_path_ignores_demo_and_batch_controllers(tmp_path):
    generated_dir = tmp_path / "generated"
    controller_dir = generated_dir / "src" / "main" / "java"
    controller_dir.mkdir(parents=True)

    (controller_dir / "DemoController.java").write_text('@RequestMapping("/demo")\nclass DemoController {}')
    (controller_dir / "BatchTriggerController.java").write_text('@RequestMapping("/batch")\nclass BatchTriggerController {}')
    (controller_dir / "CustomerController.java").write_text('@RequestMapping("/customers")\nclass CustomerController {}')

    assert discover_collection_path(generated_dir) == "/customers"


def test_discover_collection_path_allows_custom_exclusion_set(tmp_path):
    generated_dir = tmp_path / "generated"
    controller_dir = generated_dir / "src" / "main" / "java"
    controller_dir.mkdir(parents=True)

    (controller_dir / "DemoController.java").write_text('@RequestMapping("/demo")\nclass DemoController {}')
    (controller_dir / "PermissionGroupsController.java").write_text(
        '@RequestMapping("/permission-groups")\nclass PermissionGroupsController {}'
    )

    assert discover_collection_path(generated_dir, excluded={"DemoController.java"}) == "/permission-groups"


def test_discover_collection_path_value_equals_form(tmp_path):
    """@RequestMapping(value = "/foo") must be parsed correctly."""
    controller_dir = tmp_path / "generated" / "src"
    controller_dir.mkdir(parents=True)
    (controller_dir / "PetController.java").write_text(
        '@RequestMapping(value = "/pet")\nclass PetController {}'
    )
    assert discover_collection_path(tmp_path / "generated") == "/pet"


def test_discover_collection_path_path_equals_form(tmp_path):
    """@RequestMapping(path = "/foo") must be parsed correctly."""
    controller_dir = tmp_path / "generated" / "src"
    controller_dir.mkdir(parents=True)
    (controller_dir / "PetController.java").write_text(
        '@RequestMapping(path = "/pet")\nclass PetController {}'
    )
    assert discover_collection_path(tmp_path / "generated") == "/pet"


def test_discover_collection_path_singular_petstore_route(tmp_path):
    """Engine may emit /pet (singular) — discover_collection_path must accept it."""
    controller_dir = tmp_path / "generated" / "src"
    controller_dir.mkdir(parents=True)
    (controller_dir / "DemoController.java").write_text('@RequestMapping("/demo")\nclass DemoController {}')
    (controller_dir / "PetController.java").write_text('@RequestMapping("/pet")\nclass PetController {}')
    assert discover_collection_path(tmp_path / "generated") == "/pet"


def test_resolve_generated_jar_prefers_named_then_falls_back(tmp_path):
    generated_dir = tmp_path / "generated"
    target_dir = generated_dir / "target"
    target_dir.mkdir(parents=True)

    fallback = target_dir / "service-0.0.1-SNAPSHOT.jar"
    fallback.write_text("jar")
    (target_dir / "service-0.0.1-SNAPSHOT-sources.jar").write_text("sources")
    (target_dir / "original-service-0.0.1-SNAPSHOT.jar").write_text("original")

    assert resolve_generated_jar(generated_dir, "missing.jar") == fallback


def test_assert_json_array_accepts_arrays_and_rejects_other_shapes():
    assert assert_json_array(json.dumps([{"id": 1}]), "GET /items") == [{"id": 1}]

    with pytest.raises(RuntimeError, match="expected array"):
        assert_json_array(json.dumps({"id": 1}), "GET /items")
