"""The image assessment must fail rather than silently lose a component class."""

import json
from copy import deepcopy

import pytest

from scripts.image_assessment_report import summarize
from scripts.image_findings_ledger import normalize, write_ledger


@pytest.fixture
def reports():
    name = "studio:test"
    config = "sha256:" + "a" * 64
    manifest = "sha256:" + "b" * 64
    index = "sha256:" + "c" * 64
    layer = "sha256:" + "d" * 64
    identity = {
        "userInput": name, "imageID": config, "manifestDigest": manifest,
        "repoDigests": ["studio@" + index], "layers": [{"digest": layer}],
        "os": "linux", "architecture": "amd64",
    }
    syft = {
        "source": {"type": "image", "metadata": {**identity, "host_path": "/private/example"}},
        "artifacts": [
            {"id": "deb-1", "type": "deb", "name": "bash", "version": "1"},
            {"id": "py-1", "type": "python", "name": "sample_pkg", "version": "2"},
            {"id": "jar-1", "type": "java-archive", "name": "maven-helper", "version": "3"},
            {
                "id": "jdk-1", "type": "binary", "name": "openjdk", "version": "21.0.12+8-LTS",
                "locations": [{"path": "/opt/java/openjdk/release"}],
            },
        ],
    }
    grype = {
        "source": {"type": "image", "target": identity},
        "descriptor": {"db": {"status": {"valid": True, "built": "2026-09-23T06:31:39Z"}}},
        "ignoredMatches": [],
        "matches": [{
            "artifact": {"id": "deb-1", "type": "deb", "name": "bash", "version": "1"},
            "vulnerability": {"id": "CVE-EXAMPLE", "severity": "High", "fix": {"state": "not-fixed"}},
        }],
    }
    trivy = {"ArtifactName": name, "Metadata": {
        "ImageID": index, "RepoDigests": ["studio@" + index], "DiffIDs": [layer],
    }, "Results": [
        {"Type": "debian", "Packages": [{"ID": "bash@1", "Name": "bash", "Version": "1"}],
         "Vulnerabilities": [{
             "VulnerabilityID": "CVE-TRIVY", "PkgName": "bash", "InstalledVersion": "1",
             "Severity": "HIGH",
         }]},
        {"Type": "python-pkg", "Packages": [
            {"Name": "sample-pkg", "Version": "2", "AnalyzedBy": "python-pkg"},
            {"Name": "stale", "Version": "0", "AnalyzedBy": "sbom"},
        ], "Vulnerabilities": [{
            "VulnerabilityID": "GHSA-STALE", "PkgName": "stale", "InstalledVersion": "0",
            "FixedVersion": "1", "Severity": "MEDIUM",
        }]},
    ]}
    return syft, grype, trivy


def test_summary_is_path_free_and_keeps_findings_open(reports):
    summary = summarize(*reports)
    assert summary["assessment_state"] == "complete-with-findings"
    assert summary["inventory"]["copied_jdk"]["version"] == "21.0.12+8-LTS"
    assert summary["inventory"]["trivy_imported_python_sbom_records"] == 1
    assert summary["findings"]["by_fix_state"] == {"not-fixed": 1}
    assert summary["findings"]["components"][0]["high_critical_ids"] == ["CVE-EXAMPLE"]
    assert summary["trivy_findings"]["by_category"] == {"debian": 1, "inventory_unresolved_python": 1}
    assert summary["trivy_findings"]["observed_result_types"] == ["debian", "python-pkg"]
    assert summary["trivy_findings"]["components"][0]["high_critical_ids"] == ["CVE-TRIVY"]
    assert summary["ignored_findings"]["total"] == 0
    assert "/private/example" not in str(summary)


@pytest.mark.parametrize("kind", ["deb", "python", "java-archive", "binary"])
def test_missing_required_inventory_fails(reports, kind):
    syft, grype, trivy = deepcopy(reports)
    syft["artifacts"] = [item for item in syft["artifacts"] if item["type"] != kind]
    with pytest.raises(ValueError, match="incomplete"):
        summarize(syft, grype, trivy)


def test_package_disagreement_fails(reports):
    syft, grype, trivy = deepcopy(reports)
    trivy["Results"][0]["Packages"][0]["ID"] = "bash@older"
    with pytest.raises(ValueError, match="Debian packages"):
        summarize(syft, grype, trivy)


def test_invalid_advisory_database_fails(reports):
    syft, grype, trivy = deepcopy(reports)
    grype["descriptor"]["db"]["status"]["valid"] = False
    with pytest.raises(ValueError, match="database"):
        summarize(syft, grype, trivy)


def test_uninventoried_advisory_component_fails(reports):
    syft, grype, trivy = deepcopy(reports)
    grype["matches"][0]["artifact"]["id"] = "missing"
    with pytest.raises(ValueError, match="not tied"):
        summarize(syft, grype, trivy)


@pytest.mark.parametrize("field", ["imageID", "manifestDigest", "repoDigests", "layers", "architecture"])
def test_grype_wrong_image_or_platform_fails_with_same_inventory(reports, field):
    syft, grype, trivy = deepcopy(reports)
    different = "sha256:" + "e" * 64
    grype["source"]["target"][field] = {
        "imageID": different, "manifestDigest": different,
        "repoDigests": ["studio@" + different], "layers": [{"digest": different}],
        "architecture": "arm64",
    }[field]
    with pytest.raises(ValueError, match="Grype report"):
        summarize(syft, grype, trivy)


@pytest.mark.parametrize("field", ["ImageID", "RepoDigests", "DiffIDs"])
def test_trivy_wrong_image_fails_with_same_inventory(reports, field):
    syft, grype, trivy = deepcopy(reports)
    different = "sha256:" + "e" * 64
    trivy["Metadata"][field] = {
        "ImageID": different, "RepoDigests": ["studio@" + different],
        "DiffIDs": [different],
    }[field]
    with pytest.raises(ValueError, match="Trivy report"):
        summarize(syft, grype, trivy)


@pytest.mark.parametrize("scanner", ["syft", "grype", "trivy"])
def test_missing_scanner_image_identity_fails(reports, scanner):
    syft, grype, trivy = deepcopy(reports)
    if scanner == "syft":
        del syft["source"]["metadata"]["imageID"]
    elif scanner == "grype":
        del grype["source"]["target"]["imageID"]
    else:
        del trivy["Metadata"]["ImageID"]
    with pytest.raises(ValueError, match="image|report"):
        summarize(syft, grype, trivy)


def test_grype_empty_cannot_hide_trivy_installed_findings(reports):
    syft, grype, trivy = deepcopy(reports)
    grype["matches"] = []
    summary = summarize(syft, grype, trivy)
    assert summary["findings"]["total"] == 0
    assert summary["assessment_state"] == "complete-with-findings"
    assert summary["trivy_findings"]["by_category"]["debian"] == 1


def test_trivy_installed_python_finding_prevents_clean_status(reports):
    syft, grype, trivy = deepcopy(reports)
    grype["matches"] = []
    trivy["Results"][0]["Vulnerabilities"] = []
    trivy["Results"][1]["Vulnerabilities"][0].update(
        {"PkgName": "sample-pkg", "InstalledVersion": "2"}
    )
    summary = summarize(syft, grype, trivy)
    assert summary["assessment_state"] == "complete-with-findings"
    assert summary["trivy_findings"]["by_category"] == {"installed_python": 1}


def test_changed_trivy_advisory_changes_summary(reports):
    syft, grype, trivy = deepcopy(reports)
    trivy["Results"][0]["Vulnerabilities"][0]["Severity"] = "LOW"
    first = summarize(syft, grype, trivy)
    trivy["Results"][0]["Vulnerabilities"][0]["VulnerabilityID"] = "CVE-NEW"
    second = summarize(syft, grype, trivy)
    assert first != second
    assert second["trivy_findings"]["components"][0]["high_critical_ids"] == []
    assert first["trivy_findings"]["components"][0]["advisory_fingerprint_sha256"] != (
        second["trivy_findings"]["components"][0]["advisory_fingerprint_sha256"]
    )


def test_standalone_inventory_absence_does_not_clear_embedded_alert(reports):
    syft, grype, trivy = deepcopy(reports)
    grype["matches"] = []
    trivy["Results"][0]["Vulnerabilities"] = []
    summary = summarize(syft, grype, trivy)
    assert summary["assessment_state"] == "complete-with-findings"
    assert summary["trivy_findings"]["by_category"] == {"inventory_unresolved_python": 1}
    assert summary["trivy_findings"]["components"][0]["disposition"].startswith("open;")


def _ignored_match() -> dict:
    return {
        "artifact": {"id": "deb-1", "type": "deb", "name": "bash", "version": "1"},
        "vulnerability": {"id": "CVE-IGNORED", "severity": "Critical", "fix": {"state": "not-fixed"}},
        "appliedIgnoreRules": [{
            "namespace": "", "match-type": "exact-indirect-match",
            "package": {"name": "bash", "type": "deb", "language": "", "upstream-name": "bash"},
        }],
    }


def test_ignored_only_findings_remain_open_with_rules_and_fingerprint(reports):
    syft, grype, trivy = deepcopy(reports)
    grype["matches"] = []
    grype["ignoredMatches"] = [_ignored_match()]
    grype["ignoredMatches"][0]["vulnerability"]["severity"] = "Low"
    trivy["Results"][0]["Vulnerabilities"] = []
    trivy["Results"][1]["Vulnerabilities"] = []
    summary = summarize(syft, grype, trivy)
    assert summary["assessment_state"] == "complete-with-findings"
    assert summary["findings"]["total"] == 0
    assert summary["ignored_findings"]["total"] == 1
    assert summary["ignored_findings"]["by_fix_state"] == {"not-fixed": 1}
    assert summary["ignored_findings"]["rules"][0]["ignored_matches"] == 1
    assert summary["ignored_findings"]["components"][0]["high_critical_ids"] == []
    grype["ignoredMatches"][0]["vulnerability"]["id"] = "CVE-CHANGED"
    changed = summarize(syft, grype, trivy)
    assert summary["ignored_findings"]["components"][0]["advisory_fingerprint_sha256"] != (
        changed["ignored_findings"]["components"][0]["advisory_fingerprint_sha256"]
    )


def test_ignored_finding_must_match_image_inventory(reports):
    syft, grype, trivy = deepcopy(reports)
    grype["ignoredMatches"] = [_ignored_match()]
    grype["ignoredMatches"][0]["artifact"]["id"] = "other-image"
    with pytest.raises(ValueError, match="not tied"):
        summarize(syft, grype, trivy)


def test_ignored_finding_without_rule_fails(reports):
    syft, grype, trivy = deepcopy(reports)
    grype["ignoredMatches"] = [_ignored_match()]
    grype["ignoredMatches"][0]["appliedIgnoreRules"] = []
    with pytest.raises(ValueError, match="no applied rule"):
        summarize(syft, grype, trivy)


def test_missing_ignored_results_fails(reports):
    syft, grype, trivy = deepcopy(reports)
    del grype["ignoredMatches"]
    with pytest.raises(ValueError, match="active or ignored"):
        summarize(syft, grype, trivy)


def test_unsupported_trivy_critical_finding_fails(reports):
    syft, grype, trivy = deepcopy(reports)
    grype["matches"] = []
    trivy["Results"][0]["Vulnerabilities"] = []
    trivy["Results"][1]["Vulnerabilities"] = []
    trivy["Results"].append({
        "Type": "jar", "Vulnerabilities": [{
            "VulnerabilityID": "CVE-UNHANDLED", "Severity": "CRITICAL",
            "PkgName": "library", "InstalledVersion": "1",
        }],
    })
    with pytest.raises(ValueError, match="unsupported Trivy result type.*jar"):
        summarize(syft, grype, trivy)


def test_missing_trivy_result_type_fails(reports):
    syft, grype, trivy = deepcopy(reports)
    del trivy["Results"][0]["Type"]
    with pytest.raises(ValueError, match="missing a type"):
        summarize(syft, grype, trivy)


def test_malformed_trivy_vulnerabilities_fail(reports):
    syft, grype, trivy = deepcopy(reports)
    trivy["Results"].append({"Type": "jar", "Vulnerabilities": {}})
    with pytest.raises(ValueError, match="advisory results are invalid"):
        summarize(syft, grype, trivy)


def test_ledger_reconciles_every_source_and_drops_private_paths(reports):
    ledger = normalize(*reports)
    assert ledger["source_observation_counts"] == {
        "grype_active": 1, "grype_ignored": 0, "trivy_debian": 1, "trivy_python": 1,
    }
    assert len(ledger["observations"]) == 3
    assert len(ledger["groups"]) == 3
    assert ledger["observations"][1]["source_index"] == 0
    assert ledger["observations"][1]["result_index"] == 0
    assert any(item["inventory_status"] == "inventory-unresolved" for item in ledger["components"])
    assert "/private/example" not in str(ledger)


def test_ledger_merges_only_explicit_alias_on_same_artifact(reports):
    syft, grype, trivy = deepcopy(reports)
    grype["matches"][0]["vulnerability"]["id"] = "GHSA-EXAMPLE"
    grype["matches"][0]["relatedVulnerabilities"] = [{"id": "CVE-TRIVY"}]
    ledger = normalize(syft, grype, trivy)
    merged = next(group for group in ledger["groups"] if group["advisory_identity"] == "CVE-TRIVY")
    assert merged["observed_ids"] == ["CVE-TRIVY", "GHSA-EXAMPLE"]
    assert merged["explicit_aliases"] == ["CVE-TRIVY"]
    assert len(merged["observation_indexes"]) == 2
    assert len(ledger["groups"]) == 2


def test_ledger_keeps_different_artifacts_separate_despite_shared_advisory(reports):
    syft, grype, trivy = deepcopy(reports)
    trivy["Results"][1]["Vulnerabilities"][0]["VulnerabilityID"] = "CVE-EXAMPLE"
    ledger = normalize(syft, grype, trivy)
    same_advisory = [group for group in ledger["groups"]
                     if group["advisory_identity"] == "CVE-EXAMPLE"]
    assert len(same_advisory) == 2
    assert len({group["component"] for group in same_advisory}) == 2


def test_ledger_retains_ignored_rules_and_source_index(reports):
    syft, grype, trivy = deepcopy(reports)
    grype["ignoredMatches"] = [_ignored_match()]
    ledger = normalize(syft, grype, trivy)
    ignored = next(item for item in ledger["observations"] if item["source"] == "grype_ignored")
    assert ignored["source_index"] == 0
    assert ignored["applied_rules"] == [0]
    assert ledger["applied_rules"][0]["match-type"] == "exact-indirect-match"
    assert len(ledger["observations"]) == 4


def test_ledger_rejects_same_id_with_changed_artifact_identity(reports):
    syft, grype, trivy = deepcopy(reports)
    grype["matches"][0]["artifact"]["version"] = "older"
    with pytest.raises(ValueError, match="artifact identity disagrees"):
        normalize(syft, grype, trivy)


def test_ledger_compact_output_is_stable_and_round_trips(reports, tmp_path):
    ledger = normalize(*reports)
    output = tmp_path / "ledger.json"
    write_ledger(output, ledger)
    first = output.read_bytes()
    assert json.loads(first) == ledger
    assert first.count(b"\n") < 30
    write_ledger(output, ledger)
    assert output.read_bytes() == first
