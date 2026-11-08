"""Public integrity controls; complete raw campaign replay remains private."""
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.image_residual_inventory import archive_components, inventory
from scripts.image_residual_report import (
    PREFIX,
    bootstrap_conclusions,
    copied_tree,
    cpython_conclusion,
    history_mapping,
    image_test_selection,
    recorded_proof_tools,
    required_inputs,
    single_test_pass,
    stage_ledger,
    tar_backport_evidence,
    validation_receipt,
)

EVIDENCE = Path(__file__).resolve().parents[1] / "docs/handover-evidence"


@pytest.fixture
def stage_reports():
    identity = {"userInput": "synthetic:test", "imageID": "sha256:" + "a" * 64,
                "manifestDigest": "sha256:" + "b" * 64, "repoDigests": ["synthetic@sha256:" + "c" * 64],
                "layers": [{"digest": "sha256:" + "d" * 64}], "os": "linux", "architecture": "amd64"}
    syft = {"source": {"type": "image", "metadata": deepcopy(identity)}, "artifacts": [
        {"id": "os", "type": "deb", "name": "synthetic-os", "version": "1", "locations": [{"path": "/var/lib/dpkg/status"}]},
        {"id": "go", "type": "go-module", "name": "stdlib", "version": "go1.26.7", "locations": [{"path": "/usr/bin/synthetic"}]},
    ]}
    grype = {"source": {"type": "image", "target": deepcopy(identity)}, "matches": [],
             "descriptor": {"db": {"status": {"valid": True, "built": "2026-10-14T00:00:00Z"}}}}
    trivy = {"ArtifactName": identity["userInput"], "Metadata": {"ImageID": "sha256:" + "c" * 64,
             "RepoDigests": identity["repoDigests"], "DiffIDs": ["sha256:" + "d" * 64]}, "Results": [
        {"Type": "ubuntu", "Packages": [{"ID": "synthetic-os@1", "Name": "synthetic-os", "Version": "1"}]},
        {"Type": "gobinary", "Target": "usr/bin/synthetic", "Packages": [{"Name": "stdlib", "Version": "v1.26.7"}], "Vulnerabilities": [
            {"VulnerabilityID": "CVE-SYNTHETIC", "PkgName": "stdlib", "InstalledVersion": "v1.26.7",
             "VendorIDs": ["GO-SYNTHETIC"], "Severity": "CRITICAL", "FixedVersion": "1.26.9"}]},
    ]}
    return syft, grype, trivy


def test_ubuntu_go_observation_is_retained_without_false_clean_or_version_merge(stage_reports):
    result = stage_ledger(*stage_reports, "jdk21")
    assert result["stream_counts"] == {"trivy_gobinary": 1}
    assert result["observations"][0]["vendor_ids"] == ["GO-SYNTHETIC"]
    assert result["observations"][0]["severity"] == "CRITICAL"
    assert result["groups"][0]["state"].startswith("OPEN")
    assert result["inventory"][1]["version"] == "go1.26.7"
    assert result["observations"][0]["component"][2] == "v1.26.7"


@pytest.mark.parametrize("mutation", ["wrong-image", "empty-inventory", "duplicate", "missing-location",
                                     "wrong-os", "unknown-critical", "missing-os", "missing-python", "unbound-grype", "invalid-db", "missing-stream"])
def test_stage_missing_or_malformed_required_coverage_fails(stage_reports, mutation):
    s, g, t = deepcopy(stage_reports)
    if mutation == "wrong-image":
        t["Metadata"]["ImageID"] = "sha256:" + "e" * 64
    elif mutation == "empty-inventory":
        s["artifacts"] = []
    elif mutation == "duplicate":
        s["artifacts"].append(deepcopy(s["artifacts"][0]))
    elif mutation == "missing-location":
        s["artifacts"][0].pop("locations")
    elif mutation == "wrong-os":
        t["Results"][0]["Packages"][0]["ID"] = "synthetic-os@older"
    elif mutation == "unknown-critical":
        t["Results"][1]["Type"] = "unhandled"
    elif mutation == "missing-os":
        t["Results"].pop(0)
    elif mutation == "missing-python":
        s["artifacts"].append({"id": "py", "type": "python", "name": "synthetic", "version": "1", "locations": [{"path": "/python"}]})
    elif mutation == "unbound-grype":
        g["matches"] = [{"artifact": {"id": "missing", "type": "deb", "name": "missing", "version": "1"},
                         "vulnerability": {"id": "CVE-SYNTHETIC"}}]
    elif mutation == "invalid-db":
        g["descriptor"]["db"]["status"]["valid"] = False
    elif mutation == "missing-stream":
        g.pop("matches")
    with pytest.raises(ValueError):
        stage_ledger(s, g, t, "jdk21")


@pytest.mark.parametrize("mutation", ["missing-go", "wrong-target", "wrong-version", "empty-go-packages"])
def test_inventoried_go_binary_requires_its_matching_scan_inventory(stage_reports, mutation):
    s, g, t = deepcopy(stage_reports)
    if mutation == "missing-go":
        t["Results"].pop(1)
    elif mutation == "wrong-target":
        t["Results"][1]["Target"] = "usr/bin/other"
    elif mutation == "wrong-version":
        t["Results"][1]["Packages"][0]["Version"] = "v1.26.6"
    else:
        t["Results"][1]["Packages"] = []
    with pytest.raises(ValueError):
        stage_ledger(s, g, t, "jdk21")


@pytest.mark.parametrize("field", ["Packages", "Vulnerabilities"])
@pytest.mark.parametrize("malformed", [{}, "", 0, False])
def test_falsey_malformed_scanner_fields_do_not_become_empty_arrays(stage_reports, field, malformed):
    s, g, t = deepcopy(stage_reports)
    t["Results"][1][field] = malformed
    with pytest.raises(ValueError):
        stage_ledger(s, g, t, "jdk21")


@pytest.mark.parametrize("omitted", [None, "absent"])
def test_scanner_optional_null_or_absent_empty_findings_remain_legal(stage_reports, omitted):
    s, g, t = deepcopy(stage_reports)
    if omitted is None:
        t["Results"][1]["Vulnerabilities"] = None
    else:
        t["Results"][1].pop("Vulnerabilities")
    assert stage_ledger(s, g, t, "jdk21")["stream_counts"] == {}


@pytest.mark.parametrize("summary", ["1 passed in 1.00s", "1 failed, 1 passed in 1.00s",
    "1 passed, 1 error in 1.00s", "1 skipped in 1.00s", "no tests ran in 1.00s",
    "1 passed in 1.00s\n1 failed in 2.00s", "ERROR collecting smoke\n1 passed in 1.00s",
    "KeyboardInterrupt\n1 passed in 1.00s", "1 passed, 1 skipped in 1.00s"])
def test_launch_proof_requires_one_unambiguous_executed_pass(tmp_path, summary):
    failures = ["tests/test_dependency_audit_policy.py::test_supported_bootstrap_paths_pin_and_verify_the_packaging_toolchain",
        "tests/test_dom_xss.py::test_one_audited_encoder_owns_text_and_quoted_attribute_encoding",
        "tests/test_dom_xss.py::test_hostile_saved_kafka_project_cannot_break_out_of_card_markup",
        "tests/test_dom_xss.py::test_hostile_openapi_descriptor_cannot_break_passthrough_markup",
        "tests/test_dom_xss.py::test_hostile_operation_name_completes_step3_sample_and_mapping_collection"]
    (tmp_path / "image-launch-smoke-r2.log").write_text(summary + "\n")
    (tmp_path / "image-policy-fixture-r2.log").write_text("1 passed in 1.00s\n")
    proof_records(tmp_path)
    regression = "Stored-XSS markup tests require Node\nCONTRIBUTING.md FileNotFoundError\n"
    regression += "\n".join("FAILED " + name for name in failures)
    (tmp_path / "image-regressions-retry.log").write_text(regression + "\n5 failed, 331 passed, 4 skipped in 14.53s\n")
    if summary == "1 passed in 1.00s":
        assert validation_receipt(tmp_path)["launch_smoke"] == "1 passed"
    else:
        with pytest.raises(ValueError):
            validation_receipt(tmp_path)


def proof_records(root, exit_code=0):
    commands = []
    for name, log in (("launch-smoke", "image-launch-smoke-r2.log"), ("fixture-policy", "image-policy-fixture-r2.log")):
        commands.append({"name": name, "log": log, "log_sha256": hashlib.sha256((root / log).read_bytes()).hexdigest(),
                         "argv": ["python", "-m", "pytest"], "exit_code": exit_code,
                         "started_utc": "2026-10-14T00:00:00Z", "finished_utc": "2026-10-14T00:00:01Z"})
    (root / "validation-commands-r2.json").write_text(json.dumps({"image_index": "sha256:" + "a" * 64, "commands": commands}))


@pytest.mark.parametrize("mutation", ["nonzero", "missing", "log-drift", "bool-exit"])
def test_single_pass_text_cannot_override_failed_or_unbound_command(tmp_path, mutation):
    (tmp_path / "image-launch-smoke-r2.log").write_text("1 passed in 1.00s\n")
    (tmp_path / "image-policy-fixture-r2.log").write_text("1 passed in 1.00s\n")
    proof_records(tmp_path, exit_code=1 if mutation == "nonzero" else (False if mutation == "bool-exit" else 0))
    if mutation == "missing":
        (tmp_path / "validation-commands-r2.json").unlink()
    if mutation == "log-drift":
        (tmp_path / "image-launch-smoke-r2.log").write_text("changed\n1 passed in 1.00s\n")
    with pytest.raises((ValueError, FileNotFoundError)):
        validation_receipt(tmp_path)


def test_real_pytest_finalizer_failure_with_passed_test_is_not_success(tmp_path):
    (tmp_path / "test_probe.py").write_text("def test_probe():\n    assert True\n")
    (tmp_path / "conftest.py").write_text(
        "import pytest\n@pytest.hookimpl(hookwrapper=True, tryfirst=True)\ndef pytest_sessionfinish(session, exitstatus):\n"
        "    yield\n    raise RuntimeError('synthetic finalizer failure')\n")
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "--color=no", "--rootdir=" + str(tmp_path), str(tmp_path)],
                            capture_output=True, text=True, cwd=tmp_path, timeout=30)
    output = result.stdout + result.stderr
    assert result.returncode != 0 and "1 passed" in output
    assert not single_test_pass(output, result.returncode)
    assert not single_test_pass("1 passed in 1.00s\n", result.returncode)
    (tmp_path / "image-launch-smoke-r2.log").write_text(output)
    (tmp_path / "image-policy-fixture-r2.log").write_text("1 passed in 1.00s\n")
    proof_records(tmp_path, exit_code=result.returncode)
    with pytest.raises(ValueError, match="command failed"):
        validation_receipt(tmp_path)


def test_ansi_error_marker_does_not_escape_validation():
    assert not single_test_pass("\x1b[31mERROR\x1b[0m collecting smoke\n1 passed in 1.00s\n", 0)


def test_ignored_only_stage_finding_keeps_rule_and_is_open(stage_reports):
    s, g, t = deepcopy(stage_reports)
    g["ignoredMatches"] = [{"artifact": {"id": "os", "type": "deb", "name": "synthetic-os", "version": "1"},
        "vulnerability": {"id": "CVE-IGNORED", "severity": "High", "fix": {"state": "not-fixed"}},
        "appliedIgnoreRules": [{"namespace": "nvd:cpe", "match-type": "exact-indirect-match",
            "package": {"name": "synthetic-os", "type": "deb", "language": "", "upstream-name": "linux"}}]}]
    result = stage_ledger(s, g, t, "jdk21")
    assert result["stream_counts"]["grype_ignored"] == 1
    assert result["observations"][0]["rules"]
    g["ignoredMatches"][0]["appliedIgnoreRules"] = []
    with pytest.raises(ValueError):
        stage_ledger(s, g, t, "jdk21")


def test_critical_java_stage_finding_is_retained(stage_reports):
    s, g, t = deepcopy(stage_reports)
    s["artifacts"].append({"id": "jar", "type": "java-archive", "name": "synthetic-jar", "version": "1", "locations": [{"path": "/opt/maven/synthetic.jar"}]})
    t["Results"].append({"Type": "jar", "Packages": [], "Vulnerabilities": [
        {"VulnerabilityID": "CVE-JAR", "PkgName": "synthetic-jar", "InstalledVersion": "1", "Severity": "CRITICAL"}]})
    result = stage_ledger(s, g, t, "maven")
    assert result["stream_counts"]["trivy_jar"] == 1
    assert any(row["advisory"] == "CVE-JAR" and row["severity"] == "CRITICAL" for row in result["observations"])


@pytest.mark.parametrize("version,expected", [("3.13.16", "supported-not-affected"), ("3.13.17", "OPEN")])
def test_explicit_psf_range_not_scanner_silence_controls_current_disposition(version, expected):
    cna = {"affected": [{"product": "CPython", "defaultStatus": "unaffected", "versions": [
        {"version": "3.13.0", "lessThan": version, "status": "affected"}]}]}
    assert cpython_conclusion(cna) == expected
    cna["affected"][0]["defaultStatus"] = "unknown"
    with pytest.raises(ValueError):
        cpython_conclusion(cna)


@pytest.mark.parametrize("entries", [
    [{"version": "0", "lessThan": "3.12.15", "status": "affected"},
     {"version": "3.15.0a1", "lessThan": "3.15.0rc3", "status": "affected"}],
    [{"version": "3.14.0", "lessThan": "3.14.8", "status": "affected"}],
    [{"version": "3.13.0", "status": "affected"}],
])
def test_omitted_minor_or_unbounded_entry_cannot_clear_cpython(entries):
    cna = {"affected": [{"product": "CPython", "defaultStatus": "unaffected", "versions": entries}]}
    assert cpython_conclusion(cna) == "OPEN"


def test_explicit_current_minor_fix_boundary_can_support_cpython():
    cna = {"affected": [{"product": "CPython", "defaultStatus": "unaffected", "versions": [
        {"version": "0", "lessThan": "3.13.13", "status": "affected"}]}]}
    assert cpython_conclusion(cna) == "supported-not-affected"


def test_residual_proof_provenance_is_frozen_not_current_reducer_identity(monkeypatch):
    def changed_source(path):
        raise AssertionError("Recorded provenance must not inspect current source")
    monkeypatch.setattr(Path, "read_bytes", changed_source)
    first = recorded_proof_tools()
    assert first["image_residual_report.py"] == "be52337b3018d4614c9130e8c0bcbaea2cc505102d85e4794c6aa4681a484179"
    first["image_residual_report.py"] = "0" * 64
    assert recorded_proof_tools()["image_residual_report.py"] != first["image_residual_report.py"]


@pytest.mark.parametrize("mutation", [None, "missing-node", "duplicate", "wrong-file-count"])
def test_image_test_selection_reconciles_the_actual_executed_count(tmp_path, mutation):
    directory = tmp_path / "claude-followup"
    directory.mkdir()
    nodes = ["tests/test_synthetic.py::test_a", "tests/test_synthetic.py::test_b", "tests/test_synthetic.py::test_c"]
    if mutation == "missing-node":
        nodes.pop()
    if mutation == "duplicate":
        nodes[-1] = nodes[0]
    path = directory / "image-regression-nodeids.json"
    path.write_text(json.dumps(nodes))
    record = {"file_counts": {"tests/test_synthetic.py": 3 if mutation != "wrong-file-count" else 4},
              "count": 3, "nodeids_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (directory / "image-regression-selection.json").write_text(json.dumps(record))
    execution = {"full_retry": {"passed": 1, "skipped": 1, "failed": ["synthetic"]}}
    if mutation:
        with pytest.raises(ValueError):
            image_test_selection(tmp_path, execution)
    else:
        assert image_test_selection(tmp_path, execution)["count"] == 3


def test_every_successor_copy_is_checked_including_private_wheel(tmp_path):
    root = tmp_path / "research"
    root.mkdir()
    (root / "GHSA-SYNTHETIC.json").write_text(json.dumps({"identifiers": [{"value": "CVE-SYNTHETIC"}],
        "vulnerabilities": [{"package": {"ecosystem": "pip", "name": "wheel"}, "vulnerable_version_range": "<=0.46.1"}]}))
    old = {"newly_encountered": {"items": [{"id": "CVE-SYNTHETIC", "component": "wheel", "recorded_version": "0.45.1",
                                           "advisory_url": "https://github.com/advisories/GHSA-SYNTHETIC"}]}}
    bound = {"active_and_seed_match_official": True, "vendor_members": 1, "versions": {}}
    assert bootstrap_conclusions(old, tmp_path, bound, {"wheel": ["0.48.0", "0.46.3"]})[0]["state"] == "supported-not-affected"
    assert bootstrap_conclusions(old, tmp_path, bound, {"wheel": ["0.48.0", "0.45.1"]})[0]["state"] == "OPEN"
    bound["active_and_seed_match_official"] = False
    with pytest.raises(ValueError):
        bootstrap_conclusions(old, tmp_path, bound, {"wheel": ["0.48.0"]})


@pytest.mark.parametrize("mutation", [None, "wrong-branch", "unmerged", "wrong-bytes", "outside-created"])
def test_tar_range_override_requires_backport_actual_bytes_and_behavior(tmp_path, mutation):
    (tmp_path / "research").mkdir()
    (tmp_path / "artifacts").mkdir()
    record = {"base": {"ref": "3.13"}, "number": 156042, "merged_at": "2026-08-19",
              "merge_commit_sha": "c7979f3a819011a3222bd16e671264b1e34282cb",
              "html_url": "https://github.com/python/cpython/pull/156042"}
    if mutation == "wrong-branch":
        record["base"]["ref"] = "3.14"
    if mutation == "unmerged":
        record["merged_at"] = None
    (tmp_path / "research/cpython-156042.json").write_text(json.dumps(record))
    module = b"normalized = os.path.normpath(name)"
    with tarfile.open(tmp_path / "artifacts/Python-3.13.16.tar.xz", "w:xz") as archive:
        for path, data in (("Misc/NEWS", b"gh-155999"), ("Lib/tarfile.py", module)):
            member = tarfile.TarInfo("Python-3.13.16/" + path)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    comparison = {"stdlib_module_sha256": {"tarfile": hashlib.sha256(module).hexdigest()}}
    probe = {"tar_directory_regression": {"member_extracted_inside": True, "outside_directory_created": False}}
    if mutation == "wrong-bytes":
        comparison["stdlib_module_sha256"]["tarfile"] = "0" * 64
    if mutation == "outside-created":
        probe["tar_directory_regression"]["outside_directory_created"] = True
    if mutation:
        with pytest.raises(ValueError):
            tar_backport_evidence(tmp_path, probe, comparison)
    else:
        assert tar_backport_evidence(tmp_path, probe, comparison)["advisory"] == "CVE-2026-19672"


def test_changed_copied_stage_file_cannot_be_claimed_equal():
    stage = {"files": {"/opt/maven/tool": {"sha256": "a"}}}
    assert copied_tree(stage, stage, "/opt/maven")["byte_equal"]
    with pytest.raises(ValueError):
        copied_tree(stage, {"files": {}}, "/opt/maven")


def zip_bytes(members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members:
            archive.writestr(name, data)
    return buffer.getvalue()


def test_nested_archive_keeps_native_bytes_and_identifiable_components():
    nested = zip_bytes([("META-INF/maven/synthetic/tool/pom.properties", b"groupId=synthetic\nartifactId=tool\nversion=1\n"),
                        ("native/synthetic.dll", b"MZsynthetic")])
    rows = archive_components(zip_bytes([("nested.jar", nested)]), "/opt/maven/tool.jar")
    assert any(row.get("native_format") == "PE/MS-DOS" for row in rows)
    assert any(row.get("artifactId") == "tool" for row in rows)
    with pytest.raises((ValueError, zipfile.BadZipFile)):
        archive_components(b"not a ZIP archive", "broken.jar")


@pytest.mark.parametrize("mutation", [None, "traversal", "duplicate", "missing-status", "bad-elf"])
def test_filesystem_inventory_hashes_hardlinks_and_rejects_incomplete_or_ambiguous_exports(tmp_path, mutation):
    path = tmp_path / "filesystem.tar"
    with tarfile.open(path, "w") as archive:
        files = {"var/lib/dpkg/status": b"synthetic", "usr/lib/tool": b"\x7fELF\x02\x01" + b"\0" * 60}
        if mutation == "traversal":
            files["../outside"] = b"synthetic"
        if mutation == "missing-status":
            files.pop("var/lib/dpkg/status")
        if mutation == "bad-elf":
            files["usr/lib/tool"] = b"\x7fELF"
        for name, data in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
        if mutation == "duplicate":
            archive.addfile(member, io.BytesIO(data))
        link = tarfile.TarInfo("usr/lib/tool-alias")
        link.type, link.linkname = tarfile.LNKTYPE, "usr/lib/tool"
        archive.addfile(link)
    if mutation:
        with pytest.raises(ValueError):
            inventory(path)
    else:
        result = inventory(path)
        assert result["files"]["/usr/lib/tool"]["sha256"] == result["files"]["/usr/lib/tool-alias"]["sha256"]
        assert result["files"]["/usr/lib/tool-alias"]["bytes"] == 66


def test_committed_reconciliation_retains_every_inherited_identity_and_required_input():
    old = json.loads((EVIDENCE / "studio-image-bundle-p-2026-10-11-ledger.json").read_bytes())
    new = json.loads((EVIDENCE / (PREFIX + "-ledger.json")).read_bytes())
    results = json.loads((EVIDENCE / (PREFIX + "-outcomes.json")).read_bytes())
    assert results["historical_to_current"] == history_mapping(old, new)
    prior = json.loads((EVIDENCE / "studio-image-runtime-2026-10-08-inputs.json").read_bytes())
    assert {row["id"] for row in results["scoped"]} == set(prior["scope"])
    assert len(results["successor_bootstrap"]) == len(prior["newly_encountered"]["items"])
    receipt = json.loads((EVIDENCE / (PREFIX + "-receipt.json")).read_bytes())
    assert required_inputs(prior) <= receipt["input_sha256"].keys()
    assert not receipt["risk_accepted"] and not receipt["m2_cleared"]
