"""Disposition/retention integrity without requiring private raw inputs in CI."""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.image_bundle_p_report import (
    ALWAYS_OPEN,
    HISTORY,
    PREFIX,
    STDLIB_PATHS,
    base_identities,
    dispositions,
    lineage,
    official_comparison,
    recorded_proof_tools,
    validate_proofs,
    validation_result,
)

EVIDENCE = Path(__file__).resolve().parents[1] / "docs/handover-evidence"


def test_committed_base_projection_preserves_identities_without_raw_config_text():
    record = {"repository": "python", "requested": "sha256:synthetic-index",
              "index_digest": "sha256:synthetic-index", "config_digest": "sha256:synthetic-config",
              "platform_descriptor": {"digest": "sha256:synthetic-platform"},
              "env": ["PUBLIC_BUILD_METADATA=synthetic"], "history": [{"created_by": "synthetic build"}]}
    result = base_identities([record])[0]
    assert set(result) == {"repository", "requested", "index_digest", "config_digest", "platform_descriptor"}
    assert all(result[key] == record[key] for key in result)
    assert record["env"] and record["history"]


def read(name):
    return json.loads((EVIDENCE / name).read_bytes())


@pytest.fixture
def receipt():
    return read(PREFIX + "-receipt.json")


def test_scoped_results_replay_without_clearing_historical_or_bootstrap_identities(receipt):
    old = read(HISTORY + "-inputs.json")
    result = read(PREFIX + "-delta.json")
    assert dispositions(receipt["runtime"], old, receipt["official_comparison"]) == result["scoped_findings"]
    assert {row["id"] for row in result["scoped_findings"]} == set(old["scope"])
    assert ALWAYS_OPEN <= {row["id"] for row in result["scoped_findings"] if row["state"] == "OPEN"}
    assert {row["id"] for row in result["additional_bootstrap_associations"]} == {row["id"] for row in old["newly_encountered"]["items"]}
    assert not result["risk_accepted"] and not result["m2_cleared"]


def test_recorded_proof_identity_does_not_hash_later_working_tree_edits(receipt, monkeypatch):
    original = Path.read_bytes
    def changed_source(path):
        return b"synthetic later tooling revision" if path.suffix == ".py" else original(path)
    monkeypatch.setattr(Path, "read_bytes", changed_source)
    assert recorded_proof_tools() == receipt["proof_tools_sha256"]
    altered = recorded_proof_tools()
    altered["verify_image_oci.py"] = "0" * 64
    assert recorded_proof_tools() == receipt["proof_tools_sha256"]


@pytest.mark.parametrize("name", sorted(STDLIB_PATHS))
def test_official_comparison_rejects_missing_source_before_reading_archive(receipt, tmp_path, name):
    probe = deepcopy(receipt["runtime"])
    probe["modules"].pop(name)
    with pytest.raises(ValueError, match="Incomplete required stdlib"):
        official_comparison(probe, tmp_path / "not-read.tar.xz", {})


@pytest.mark.parametrize("name", ["imaplib", "http.cookies"])
@pytest.mark.parametrize("mutation", ["import-error", "unsupported-path", "missing-hash", "bad-hash"])
def test_official_comparison_rejects_invalid_advisory_source_records(receipt, tmp_path, name, mutation):
    probe = deepcopy(receipt["runtime"])
    record = probe["modules"][name]
    if mutation == "import-error":
        record["import_error"] = "ImportError"
    elif mutation == "unsupported-path":
        record["path"] = "/usr/local/lib/python3.13/site-packages/synthetic.py"
    elif mutation == "missing-hash":
        record.pop("sha256")
    elif mutation == "bad-hash":
        record["sha256"] = "not-a-hash"
    with pytest.raises(ValueError, match="Invalid required stdlib"):
        official_comparison(probe, tmp_path / "not-read.tar.xz", {})


@pytest.mark.parametrize("name", ["imaplib", "http.cookies"])
@pytest.mark.parametrize("mutation", ["missing-record", "missing-comparison", "empty-comparison",
                                     "missing-comparison-module", "stale-probe-hash", "stale-comparison-hash", "wrong-source"])
def test_incomplete_or_stale_source_comparison_cannot_credit_remediation(receipt, name, mutation):
    probe = deepcopy(receipt["runtime"])
    comparison = deepcopy(receipt["official_comparison"])
    if mutation == "missing-record":
        probe["modules"].pop(name)
    elif mutation == "missing-comparison":
        comparison.pop("stdlib_module_sha256")
    elif mutation == "empty-comparison":
        comparison["stdlib_module_sha256"] = {}
    elif mutation == "missing-comparison-module":
        comparison["stdlib_module_sha256"].pop(name)
    elif mutation == "stale-probe-hash":
        probe["modules"][name]["sha256"] = "0" * 64
    elif mutation == "stale-comparison-hash":
        comparison["stdlib_module_sha256"][name] = "0" * 64
    elif mutation == "wrong-source":
        comparison["python_source_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        dispositions(probe, read(HISTORY + "-inputs.json"), comparison)


def test_all_historical_groups_and_zero_match_family_queue_remain_traceable():
    old = read("studio-image-refresh-2026-10-04-ledger.json")
    current = read(PREFIX + "-ledger.json")
    result = read(PREFIX + "-delta.json")
    assert result["lineage"] == lineage(old, current)
    assert [row["historical_group"] for row in result["lineage"]["mapping"]] == list(range(len(old["groups"])))
    assert result["lineage"]["family_owner_queue"] == old["decisions"]
    assert current["source_observation_counts"]["grype_ignored"] > 0
    assert current["applied_rules"]


@pytest.mark.parametrize("mutation", ["root", "version", "pip-check", "imap-send", "morsel", "jdk", "vendor"])
def test_incomplete_or_different_artifact_cannot_support_dispositions(receipt, mutation):
    probe = deepcopy(receipt["runtime"])
    comparison = deepcopy(receipt["official_comparison"])
    if mutation == "root":
        probe["uid"] = 0
    elif mutation == "version":
        probe["python"] = "3.11.17 different artifact"
    elif mutation == "pip-check":
        probe["pip_check"]["exit_code"] = 1
    elif mutation == "imap-send":
        probe["behavior_regressions"]["imap_sent_bytes_hex"] = ["0d0a"]
    elif mutation == "morsel":
        probe["behavior_regressions"]["morsel_rejects_control_characters"] = False
    elif mutation == "jdk":
        comparison["jdk_regular_files_equal_to_311"] = False
    elif mutation == "vendor":
        comparison["active_and_bootstrap_vendor_bytes_equal"] = False
    with pytest.raises(ValueError):
        dispositions(probe, read(HISTORY + "-inputs.json"), comparison)


@pytest.mark.parametrize("mutation", ["skipped", "no-tests", "request", "seed", "failed-install"])
def test_failed_bootstrap_or_application_execution_cannot_pass(receipt, mutation):
    bootstrap, run = deepcopy(receipt["bootstrap_proof"]), deepcopy(receipt["build_run"])
    if mutation == "skipped":
        run["maven_tests"]["skipped"] = 1
    elif mutation == "no-tests":
        run["maven_tests"]["tests"] = 0
    elif mutation == "request":
        run["application_requests"]["read_response"]["balance"] = 0
    elif mutation == "seed":
        bootstrap["seed"]["setuptools"] = "79.0.1"
    elif mutation == "failed-install":
        bootstrap["commands"][0]["exit_code"] = 1
    with pytest.raises(ValueError):
        validate_proofs(bootstrap, run)


def test_unexpected_image_test_failure_cannot_be_explained_as_missing_node():
    with pytest.raises(ValueError):
        validation_result("Stored-XSS markup tests require Node\nFAILED tests/test_browser_security.py::unexpected\n1 failed, 20 passed")
    with pytest.raises(ValueError):
        validation_result("Stored-XSS markup tests require Node\n495 errors in 18 seconds")
