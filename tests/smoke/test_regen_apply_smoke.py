from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.services.session_context import _SQLITE_STORES
from tests.smoke.regen_smoke import run_studio_regen_apply_smoke
from tests.smoke.test_regen_plan_smoke import (
    SMOKE_PREFIX,
    _prune_previous_smoke_roots,
    _require_regen_dependencies,
)

pytestmark = [pytest.mark.smoke, pytest.mark.regen]


@pytest.fixture(scope="module")
def regen_apply_report() -> Iterator[dict]:
    _require_regen_dependencies()
    _prune_previous_smoke_roots()
    root = Path(tempfile.mkdtemp(prefix=SMOKE_PREFIX, dir="/tmp"))
    report = run_studio_regen_apply_smoke(root=root)
    yield report
    if report["ok"]:
        shutil.rmtree(root, ignore_errors=True)
    else:
        print(f"Studio regen apply smoke retained temp root for triage: {root}")
    _SQLITE_STORES.clear()


def test_regen_apply_smoke_additive_apply_succeeds(regen_apply_report: dict):
    additive = regen_apply_report["additive"]
    assert regen_apply_report["ka_off_silent"] is True, regen_apply_report
    assert additive["apply_returncode"] == 0, additive
    assert additive["new_migrations"], additive
    assert additive["migration_contains_field"] is True, additive
    assert additive["summary_mentions_hash"] is True, additive
    assert additive["succeeded"] is True, additive


def test_regen_apply_smoke_drift_fails_closed(regen_apply_report: dict):
    drift = regen_apply_report["drift"]
    assert drift["apply_returncode"] != 0, drift
    assert drift["drift_message"] is True, drift
    assert drift["package_unchanged"] is True, drift
    assert drift["failed_closed"] is True, drift


def test_regen_apply_smoke_destructive_fails_closed(regen_apply_report: dict):
    destructive = regen_apply_report["destructive"]
    assert destructive["destructive_delta"] is True, destructive
    assert destructive["apply_returncode"] != 0, destructive
    assert destructive["refusal_message"] is True, destructive
    assert destructive["package_unchanged"] is True, destructive
    assert destructive["failed_closed"] is True, destructive


def test_regen_apply_smoke_studio_wrapper_applies_and_blocks(regen_apply_report: dict):
    wrapper = regen_apply_report["studio_wrapper"]
    assert wrapper["succeeded"] is True, wrapper
    assert wrapper["drift"]["state"] == "drift", wrapper
    assert wrapper["apply"]["state"] == "applied", wrapper
    assert wrapper["new_generation_run_id"] != wrapper["old_generation_run_id"], wrapper
    assert wrapper["new_migrations"], wrapper
    assert wrapper["migration_contains_field"] is True, wrapper
    assert wrapper["destructive"]["state"] == "blocked", wrapper
    assert wrapper["destructive"]["blocked_count"] > 0, wrapper
