"""The consolidated decision package cannot silently shrink or clear its baseline."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.image_consolidated_disposition import inventory, validate, verify_retained

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/handover-evidence"


@pytest.fixture
def package():
    candidate = json.loads((EVIDENCE / "studio-image-consolidated-ledger.json").read_text())
    baseline = deepcopy(candidate)
    baseline["components"] = [{k: v for k, v in c.items() if k not in {"decision", "inventory_indexes"}}
                              for c in candidate["components"]]
    baseline["groups"] = [{**{k: v for k, v in g.items()
                              if k not in {"decision", "rationale", "vendor_bookworm"}},
                           "classification": "open/unassessed"} for g in candidate["groups"]]
    syft = {"artifacts": [
        {"id": a["syft_artifact_id"], "type": a["type"], "name": a["name"],
         "version": a["version"], "metadata": {"source": a["source_family"],
                                               "sourceVersion": a["source_version"],
                                               "architecture": a["architecture"]},
         "locations": a["locations"], "purl": a["purl"]} for a in candidate["inventory"]
    ]}
    curl = json.loads((EVIDENCE / "studio-image-curl-ledger.json").read_text())
    return candidate, baseline, syft, curl


def test_committed_package_integrity(package):
    validate(*package)
    candidate = package[0]
    assert len(candidate["inventory"]) == 346
    assert candidate["source_observation_counts"] == {
        "grype_active": 1046, "grype_ignored": 2315, "trivy_debian": 3356, "trivy_python": 6,
    }
    assert candidate["classification_counts"] == {
        "open/unassessed": 3296, "open/applicability-unresolved": 60, "supported-not-affected": 18,
    }


@pytest.mark.parametrize("field", ["observations", "components", "groups", "inventory", "applied_rules"])
def test_dropped_record_rejected(package, field):
    candidate, *rest = package
    candidate[field].pop()
    with pytest.raises((ValueError, KeyError)):
        validate(candidate, *rest)


@pytest.mark.parametrize("field", ["advisory_id", "severity", "fix_state", "source_index", "aliases"])
def test_scanner_metadata_cannot_be_rewritten(package, field):
    candidate, *rest = package
    candidate["observations"][0][field] = "rewritten"
    with pytest.raises(ValueError, match="observations"):
        validate(candidate, *rest)


@pytest.mark.parametrize("field", ["name", "version", "type", "syft_artifact_ids", "inventory_status"])
def test_component_identity_cannot_be_rewritten(package, field):
    candidate, *rest = package
    candidate["components"][0][field] = "rewritten"
    with pytest.raises((ValueError, TypeError)):
        validate(candidate, *rest)


def test_unresolved_embedded_identity_stays_unresolved(package):
    candidate, *rest = package
    component = next(c for c in candidate["components"] if c["name"] == "urllib3")
    assert component["inventory_status"] == "inventory-unresolved"
    assert component["inventory_indexes"] == []
    component["inventory_status"] = "confirmed"
    with pytest.raises(ValueError, match="component identity"):
        validate(candidate, *rest)


@pytest.mark.parametrize("field", ["owner", "decision_needed", "sources", "review_trigger", "rationale"])
def test_incomplete_family_decision_rejected(package, field):
    candidate, *rest = package
    candidate["decisions"][0][field] = ""
    with pytest.raises(ValueError, match="incomplete"):
        validate(candidate, *rest)


def test_unowned_identity_rejected(package):
    candidate, *rest = package
    candidate["decisions"].clear()
    with pytest.raises(ValueError, match="unowned"):
        validate(candidate, *rest)


def test_risk_acceptance_is_not_generated(package):
    candidate, *rest = package
    candidate["decisions"][0]["state"] = "accepted"
    with pytest.raises(ValueError, match="accepted"):
        validate(candidate, *rest)


def test_new_non_curl_exclusion_rejected(package):
    candidate, *rest = package
    group = next(g for g in candidate["groups"] if g["decision"] != "os:curl")
    group["classification"] = "supported-not-affected"
    with pytest.raises(ValueError, match="unsupported new exclusion"):
        validate(candidate, *rest)


def test_curl_exclusion_cannot_expand(package):
    candidate, *rest = package
    group = next(g for g in candidate["groups"] if g["classification"] == "open/applicability-unresolved")
    group["classification"] = "supported-not-affected"
    with pytest.raises(ValueError, match="curl disposition"):
        validate(candidate, *rest)


def test_different_binary_locations_remain_distinct(package):
    inventory_records = package[0]["inventory"]
    launchers = [a for a in inventory_records if a["name"] == "Simple Launcher"]
    assert len(launchers) == 6
    assert len({a["syft_artifact_id"] for a in launchers}) == 6
    assert len({a["locations"][0]["path"] for a in launchers}) == 6


def test_inventory_rejects_assessor_host_path():
    with pytest.raises(ValueError, match="image-internal"):
        inventory({"artifacts": [{"id": "bad", "type": "binary", "name": "tool", "version": "1",
                                 "locations": [{"path": "/Users/example/private"}]}]})


def test_missing_retained_evidence_does_not_mean_clean(tmp_path):
    identity = {"retention": {"raw_files": {"syft.json": {"sha256": "missing"}}}}
    with pytest.raises(FileNotFoundError):
        verify_retained(tmp_path, identity)


def test_changed_retained_evidence_rejected(tmp_path):
    path = tmp_path / "syft.json"
    path.write_text("{}")
    identity = {"retention": {"raw_files": {"syft.json": {"sha256": "changed"}}}}
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_retained(tmp_path, identity)
