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
from tests.smoke.l4_driver import (
    run_author_generate_isolation,
    run_engine_fail_closed_isolation,
    run_ks_per_session_isolation,
    run_ks_solo_child_environment,
)

pytestmark = [pytest.mark.smoke, pytest.mark.l4]

SMOKE_PREFIX = "edgeforge-suite-smoke-studio-l4-"


def _prune_previous_smoke_roots() -> None:
    for candidate in Path("/tmp").glob(f"{SMOKE_PREFIX}*"):
        if candidate.is_dir():
            shutil.rmtree(candidate, ignore_errors=True)


def _require_engine_dependency() -> None:
    engine_repo_value = os.getenv("EDGEFORGE_STUDIO_ENGINE_REPO")
    if not engine_repo_value:
        pytest.skip("Studio L4 smoke requires EDGEFORGE_STUDIO_ENGINE_REPO")

    engine_repo = Path(engine_repo_value).expanduser()
    if not (engine_repo / "appbuilder").is_dir():
        pytest.skip(
            "Studio L4 smoke requires EDGEFORGE_STUDIO_ENGINE_REPO to point at an Engine checkout"
        )


def _require_ks_dependency() -> None:
    ks_repo = _ks_repo()
    if not ks_repo.exists():
        pytest.skip("Studio L4 smoke requires an EdgeForgeKnowledgeServer checkout")

    command = _ks_command(ks_repo)
    if not _can_launch_ks(command, _ks_probe_env(ks_repo)):
        pytest.skip("Studio L4 smoke requires an importable/runnable Knowledge Server")


@pytest.fixture
def engine_smoke_root(
    request: pytest.FixtureRequest,
) -> Iterator[Path]:
    _require_engine_dependency()
    yield from _smoke_root(request)


@pytest.fixture
def ks_smoke_root(
    request: pytest.FixtureRequest,
) -> Iterator[Path]:
    _require_ks_dependency()
    yield from _smoke_root(request)


def _smoke_root(request: pytest.FixtureRequest) -> Iterator[Path]:
    _prune_previous_smoke_roots()
    root = Path(tempfile.mkdtemp(prefix=SMOKE_PREFIX, dir="/tmp"))
    yield root
    call_report = getattr(request.node, "rep_call", None)
    if call_report is not None and call_report.passed:
        shutil.rmtree(root, ignore_errors=True)
    else:
        print(f"Studio L4 smoke retained temp root for triage: {root}")
    _SQLITE_STORES.clear()


def test_l4_author_generate_two_session_isolation(engine_smoke_root: Path):
    require_mcp_transport()
    report = run_author_generate_isolation(root=engine_smoke_root / "author-generate")

    assert report["ka_off_silent"] is True
    assert report["ks_calls"] == []
    assert report["distinct_workspaces"] is True
    assert report["distinct_generated_outputs"] is True
    assert report["output_a_under_workspace"] is True
    assert report["output_b_under_workspace"] is True
    assert report["evil_a_exists"] is False
    assert report["evil_b_exists"] is False
    assert report["alpha_in_a"] is True
    assert report["beta_in_a"] is False
    assert report["beta_in_b"] is True
    assert report["alpha_in_b"] is False


def test_l4_ks_per_session_isolation_when_enabled(ks_smoke_root: Path):
    report = run_ks_per_session_isolation(root=ks_smoke_root / "ks-isolation")

    assert report["distinct_workspaces"] is True
    assert report["distinct_ks_dbs"] is True
    assert report["db_a_under_workspace"] is True
    assert report["db_b_under_workspace"] is True
    assert Path(report["ks_db_a"]).exists()
    assert Path(report["ks_db_b"]).exists()
    assert report["alpha_result_has_alpha"] is True
    assert report["alpha_result_has_beta"] is False
    assert report["beta_result_has_beta"] is True
    assert report["beta_result_has_alpha"] is False
    assert report["ks_children_spawned"] == 2
    assert report["shared_mode_flag_per_child"] == ["1", "1"]
    assert all(report["db_path_per_child"])
    assert all(report["allowed_roots_per_child"])
    assert report["child_db_paths_distinct"] is True
    assert report["child_roots_distinct"] is True
    assert report["child_roots_under_own_workspace"] is True
    assert report["child_roots_match_expected"] is True
    assert report["parsed_allowed_roots_per_child"] == [
        [report["expected_allowed_root_per_child"][0]],
        [report["expected_allowed_root_per_child"][1]],
    ]
    assert report["child_db_under_own_workspace"] is True


def test_l4_ks_solo_mode_strips_inherited_shared_flag(ks_smoke_root: Path):
    report = run_ks_solo_child_environment(root=ks_smoke_root / "ks-solo-mode")

    assert report["ks_children_spawned"] == 1
    assert report["shared_mode_flag_per_child"] == [None]
    assert all(report["db_path_per_child"])
    assert all(report["allowed_roots_per_child"])
    assert report["list_documents_succeeded"] is True


def test_l4_engine_fail_closed_rejection(engine_smoke_root: Path):
    report = run_engine_fail_closed_isolation(root=engine_smoke_root / "engine-fail-closed")

    assert report["ka_off_silent"] is True
    assert report["ks_calls"] == []
    assert report["distinct_workspaces"] is True

    for case in report["negative_cases"]:
        assert case["rejected"] is True, case
        assert case["message_matched"] is True, case
        assert case["target_exists"] is False, case

    missing_roots = report["missing_roots"]
    assert missing_roots["rejected"] is True, missing_roots
    assert missing_roots["message_matched"] is True, missing_roots
    assert missing_roots["target_exists"] is False, missing_roots

    positive = report["positive_control"]
    assert positive["succeeded"] is True, positive
    assert positive["output_exists"] is True, positive
