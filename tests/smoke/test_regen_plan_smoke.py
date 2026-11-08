from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.services.session_context import _SQLITE_STORES
from tests.smoke._shared import require_mcp_transport
from tests.smoke.regen_smoke import run_studio_regen_plan_smoke

pytestmark = [pytest.mark.smoke, pytest.mark.regen]

SMOKE_PREFIX = "edgeforge-suite-smoke-studio-regen-"


def _prune_previous_smoke_roots() -> None:
    for candidate in Path("/tmp").glob(f"{SMOKE_PREFIX}*"):
        if candidate.is_dir():
            shutil.rmtree(candidate, ignore_errors=True)


def _require_regen_dependencies() -> None:
    require_mcp_transport()

    engine_repo_value = os.getenv("EDGEFORGE_STUDIO_ENGINE_REPO")
    if not engine_repo_value:
        pytest.skip("Studio regen smoke requires EDGEFORGE_STUDIO_ENGINE_REPO")
    engine_repo = Path(engine_repo_value).expanduser()
    if not (engine_repo / "appbuilder").is_dir():
        pytest.skip(
            "Studio regen smoke requires EDGEFORGE_STUDIO_ENGINE_REPO to point at an Engine checkout"
        )


@pytest.fixture(scope="module")
def regen_report() -> Iterator[dict]:
    _require_regen_dependencies()
    _prune_previous_smoke_roots()
    root = Path(tempfile.mkdtemp(prefix=SMOKE_PREFIX, dir="/tmp"))
    report = run_studio_regen_plan_smoke(root=root)
    yield report
    if report["ok"]:
        shutil.rmtree(root, ignore_errors=True)
    else:
        print(f"Studio regen smoke retained temp root for triage: {root}")
    _SQLITE_STORES.clear()


def test_regen_plan_smoke_produces_contract_valid_change_plan(regen_report: dict):
    assert regen_report["ka_off_silent"] is True, regen_report
    assert Path(regen_report["managed_package"]).is_dir(), regen_report
    assert Path(regen_report["schema_baseline"]).is_file(), regen_report
    assert regen_report["initial_plan"]["change_plan_schema_version"].split(".", 1)[0] == "1"
    assert regen_report["initial_plan"]["plan_hash"], regen_report
    assert regen_report["initial_plan"]["manifest_hash"], regen_report
    assert regen_report["initial_plan"]["baseline_hash"], regen_report
    assert regen_report["initial_plan"]["package_state_hash"], regen_report


def test_regen_plan_smoke_detects_added_manifest_field_change(regen_report: dict):
    assert regen_report["hash_sensitivity"]["plan_hash_changed"] is True, regen_report
    assert regen_report["hash_sensitivity"]["added_delta_present"] is True, regen_report
