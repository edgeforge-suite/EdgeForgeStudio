from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.integrations.ks_integration import _can_launch_ks, _ks_command, _ks_probe_env, _ks_repo
from app.services.session_context import _SQLITE_STORES
from tests.smoke._shared import require_mcp_transport
from tests.smoke.l5_driver import _ks_isolation_ok, run_studio_l5_acceptance

pytestmark = [pytest.mark.smoke, pytest.mark.l5]

SMOKE_PREFIX = "edgeforge-suite-smoke-studio-l5-"


def _valid_ks_isolation_report() -> dict:
    expected_roots = ["/tmp/session-a/ks", "/tmp/session-b/ks"]
    return {
        "distinct_workspaces": True,
        "distinct_ks_dbs": True,
        "db_a_under_workspace": True,
        "db_b_under_workspace": True,
        "alpha_result_has_alpha": True,
        "alpha_result_has_beta": False,
        "beta_result_has_beta": True,
        "beta_result_has_alpha": False,
        "ks_children_spawned": 2,
        "shared_mode_flag_per_child": ["1", "1"],
        "db_path_per_child": [
            "/tmp/session-a/ks/knowledge.sqlite3",
            "/tmp/session-b/ks/knowledge.sqlite3",
        ],
        "allowed_roots_per_child": expected_roots,
        "parsed_allowed_roots_per_child": [
            [expected_roots[0]],
            [expected_roots[1]],
        ],
        "expected_allowed_root_per_child": expected_roots,
        "child_db_paths_distinct": True,
        "child_roots_distinct": True,
        "child_roots_under_own_workspace": True,
        "child_roots_match_expected": True,
        "child_db_under_own_workspace": True,
    }


def test_l5_ks_isolation_accepts_complete_child_environment_evidence():
    assert _ks_isolation_ok(_valid_ks_isolation_report())["ok"] is True


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("ks_children_spawned", 1),
        ("shared_mode_flag_per_child", [None, None]),
        ("child_db_paths_distinct", False),
        ("child_db_under_own_workspace", False),
        ("child_roots_distinct", False),
        ("child_roots_under_own_workspace", False),
        ("child_roots_match_expected", False),
    ],
)
def test_l5_ks_isolation_rejects_invalid_child_environment_evidence(
    field: str,
    invalid_value: object,
):
    report = _valid_ks_isolation_report()
    report[field] = invalid_value

    assert _ks_isolation_ok(report)["ok"] is False


def test_l5_ks_isolation_rejects_an_appended_outside_root():
    report = _valid_ks_isolation_report()
    report["parsed_allowed_roots_per_child"][0].append("/tmp/outside-root")

    assert _ks_isolation_ok(report)["ok"] is False


def _prune_previous_smoke_roots() -> None:
    for candidate in Path("/tmp").glob(f"{SMOKE_PREFIX}*"):
        if candidate.is_dir():
            shutil.rmtree(candidate, ignore_errors=True)


def _require_l5_dependencies() -> None:
    require_mcp_transport()

    engine_repo_value = os.getenv("EDGEFORGE_STUDIO_ENGINE_REPO")
    if not engine_repo_value:
        pytest.skip("Studio L5 smoke requires EDGEFORGE_STUDIO_ENGINE_REPO")
    engine_repo = Path(engine_repo_value).expanduser()
    if not (engine_repo / "appbuilder").is_dir():
        pytest.skip(
            "Studio L5 smoke requires EDGEFORGE_STUDIO_ENGINE_REPO to point at an Engine checkout"
        )

    ks_repo = _ks_repo()
    if not ks_repo.exists():
        pytest.skip("Studio L5 smoke requires an EdgeForgeKnowledgeServer checkout")
    command = _ks_command(ks_repo)
    if not _can_launch_ks(command, _ks_probe_env(ks_repo)):
        pytest.skip("Studio L5 smoke requires an importable/runnable Knowledge Server")


@pytest.fixture(scope="module")
def l5_report() -> Iterator[dict]:
    _require_l5_dependencies()
    _prune_previous_smoke_roots()
    root = Path(tempfile.mkdtemp(prefix=SMOKE_PREFIX, dir="/tmp"))
    report = run_studio_l5_acceptance(root=root)
    yield report
    if all(scenario["ok"] for scenario in report["scenarios"]):
        shutil.rmtree(root, ignore_errors=True)
    else:
        print(f"Studio L5 smoke retained temp root for triage: {root}")
    _SQLITE_STORES.clear()


@pytest.mark.parametrize(
    "scenario_name",
    [
        "multi-session isolation",
        "shared-mode security",
        "Studio-to-Engine per-session outputs",
        "KS/KA per-session isolation",
        "Engine fail-closed out-of-root",
        "KA-OFF strict",
        "combined edge-contract author-generate",
        "regen-preview approve-apply",
    ],
)
def test_l5_studio_acceptance_scenario(l5_report: dict, scenario_name: str):
    scenarios = {scenario["scenario"]: scenario for scenario in l5_report["scenarios"]}
    assert scenario_name in scenarios
    assert scenarios[scenario_name]["ok"] is True, scenarios[scenario_name]
