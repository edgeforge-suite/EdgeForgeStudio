"""S2 keeps historical findings, duplicate code copies and open decisions visible."""

import hashlib
import io
import json
import subprocess
import sys
import tarfile
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.image_runtime_dispositions import (
    BOOTSTRAP_FOLLOWUP_IDS,
    PREFIX,
    STDLIB_MODULES,
    compare_archives,
    compile_result,
    encoded,
    frozen_scope,
)
from scripts.image_runtime_probe import tar_directory_regression, wheel_records

EVIDENCE = Path(__file__).resolve().parents[1] / "docs/handover-evidence"


@pytest.fixture
def inputs():
    return json.loads((EVIDENCE / (PREFIX + "-inputs.json")).read_bytes())


@pytest.fixture
def historical():
    return [json.loads((EVIDENCE / ("studio-image-refresh-2026-10-04-" + name + ".json")).read_bytes())
            for name in ("ledger", "delta", "identities")]


def test_committed_result_replays(inputs, historical):
    result = compile_result(inputs, *historical)
    assert encoded(result) == (EVIDENCE / (PREFIX + "-results.json")).read_bytes()
    assert len(result["findings"]) == 32
    assert result["counts"] == {"OPEN": 11, "supported-not-affected": 21}
    assert not result["risk_accepted"] and not result["m2_cleared"] and not result["image_changed"]


def test_scope_includes_nonreported_history_and_vendor_matrix(inputs, historical):
    scope = frozen_scope(*historical[:2])
    assert scope == inputs["scope"]
    assert len([v for v in scope.values() if "historical_group_indexes" in v]) == 6
    assert len([v for v in scope.values() if v["component"] == "temurin"]) == 12
    assert scope["CVE-2026-102633"]["recorded_version"] == "expat_2.8.5"


@pytest.mark.parametrize("key", ["index_digest", "platform_descriptor", "config_descriptor"])
def test_wrong_or_missing_image_identity_rejected(inputs, historical, key):
    inputs["image"].pop(key)
    with pytest.raises(ValueError, match="identity"):
        compile_result(inputs, *historical)


def test_reference_engine_cannot_relabel_assessed_engine(inputs, historical):
    inputs["image_engine_sha"] = inputs["engine_reference_sha"]
    with pytest.raises(ValueError, match="frozen image Engine"):
        compile_result(inputs, *historical)


def test_reference_studio_cannot_relabel_assessed_studio(inputs, historical):
    inputs["image_studio_sha"] = inputs["entry_studio_sha"]
    with pytest.raises(ValueError, match="Studio identity"):
        compile_result(inputs, *historical)


def test_probe_platform_must_match_assessed_amd64(inputs, historical):
    inputs["artifact"]["platform"] = "aarch64"
    with pytest.raises(ValueError, match="artifact probe"):
        compile_result(inputs, *historical)


def test_failed_oci_byte_verification_cannot_be_reused(inputs, historical):
    inputs["oci_reverification"]["all_manifest_layer_blob_hashes_sizes_and_decompressed_diff_ids_verified"] = False
    with pytest.raises(ValueError, match="OCI byte"):
        compile_result(inputs, *historical)


@pytest.mark.parametrize("field,value", [("exit_code", 1), ("mounts", ["source"]), ("network", "external")])
def test_unbound_or_incomplete_probe_rejected(inputs, historical, field, value):
    inputs["probe_receipt"][field] = value
    with pytest.raises(ValueError, match="probe"):
        compile_result(inputs, *historical)


@pytest.mark.parametrize("advisory", ["CVE-2026-19672", "CVE-2026-102633", "CVE-2026-61308", "CVE-2026-97687"])
def test_dropped_identity_rejected(inputs, historical, advisory):
    inputs["findings"] = [row for row in inputs["findings"] if row["id"] != advisory]
    with pytest.raises(ValueError, match="finding"):
        compile_result(inputs, *historical)


def test_dropped_historical_scope_rejected(inputs, historical):
    inputs["scope"].pop("CVE-2026-19672")
    with pytest.raises(ValueError, match="Frozen scope"):
        compile_result(inputs, *historical)


def test_duplicate_vendor_copy_cannot_disappear(inputs, historical):
    finding = next(f for f in inputs["findings"] if f["id"] == "CVE-2026-97687")
    finding["copies"].pop("bootstrap-urllib3-1.26.17")
    with pytest.raises(ValueError, match="copy"):
        compile_result(inputs, *historical)


@pytest.mark.parametrize("advisory", ["CVE-2026-102633", "CVE-2025-15366", "CVE-2026-97687", "CVE-2026-59890"])
def test_unresolved_copies_cannot_be_cleared_by_inventory_or_silence(inputs, historical, advisory):
    finding = next(f for f in inputs["findings"] if f["id"] == advisory)
    next(d for d in finding["copies"].values() if d["state"] == "OPEN")["state"] = "supported-not-affected"
    with pytest.raises(ValueError, match="unresolved exact copy"):
        compile_result(inputs, *historical)


@pytest.mark.parametrize("field", ["reason", "sources", "artifact_evidence", "next_action", "advisory_specific"])
def test_incomplete_disposition_rejected(inputs, historical, field):
    next(iter(inputs["findings"][0]["copies"].values()))[field] = None
    with pytest.raises(ValueError):
        compile_result(inputs, *historical)


def test_native_msgpack_invalidates_fallback_exclusion(inputs, historical):
    inputs["copies"]["bootstrap-msgpack-1.0.5"]["evidence"]["file_inventory"]["_cmsgpack.so"] = {"sha256": "0" * 64}
    with pytest.raises(ValueError, match="Native msgpack"):
        compile_result(inputs, *historical)


def test_jdk_unexplained_binary_change_rejected(inputs, historical):
    inputs["official_comparison"]["jdk_different_files"]["lib/modules"] = {}
    with pytest.raises(ValueError, match="artifact difference"):
        compile_result(inputs, *historical)


@pytest.mark.parametrize("module", sorted(STDLIB_MODULES))
def test_required_stdlib_source_comparison_cannot_disappear(inputs, historical, module):
    inputs["official_comparison"]["python_modules"].pop(module)
    with pytest.raises(ValueError, match="Incomplete stdlib"):
        compile_result(inputs, *historical)


def test_empty_stdlib_source_comparison_rejected(inputs, historical):
    inputs["official_comparison"]["python_modules"] = {}
    with pytest.raises(ValueError, match="Incomplete stdlib"):
        compile_result(inputs, *historical)


@pytest.mark.parametrize("field,value", [
    ("installed_sha256", "0" * 64), ("official_sha256", "0" * 64),
    ("installed_sha256", "not a digest"), ("official_sha256", None),
    ("installed_sha256", "g" * 64), ("equal", False), ("equal", 1),
])
def test_stdlib_hash_pairs_not_stale_equal_flag_establish_match(inputs, historical, field, value):
    inputs["official_comparison"]["python_modules"]["tarfile"][field] = value
    with pytest.raises(ValueError, match="Contradictory stdlib"):
        compile_result(inputs, *historical)


@pytest.mark.parametrize("mutation", ["missing", "different"])
def test_cpython_source_match_projection_must_reconcile(inputs, historical, mutation):
    projection = inputs["copies"]["cpython-3.11.17"]["evidence"]["source_match"]
    if mutation == "missing":
        projection.pop("tarfile")
    else:
        projection["tarfile"]["installed_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="projection differs"):
        compile_result(inputs, *historical)


def test_jdk_file_hashes_are_explicit_records(inputs, historical):
    rows = inputs["official_comparison"]["jdk_matched_files"]
    assert len(rows) == 247
    assert all(set(row) == {"sha256"} for row in rows.values())
    rows["bin/keytool"] = rows["bin/keytool"]["sha256"]
    with pytest.raises(ValueError, match="explicit JDK SHA-256"):
        compile_result(inputs, *historical)


def test_well_formed_jdk_hash_substitution_rejected(inputs, historical):
    inputs["official_comparison"]["jdk_matched_files"]["lib/modules"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="JDK matched-file projection"):
        compile_result(inputs, *historical)


def test_unchanged_image_cannot_claim_new_remediation(inputs, historical):
    finding = next(row for row in inputs["findings"] if row["id"] == "CVE-2026-19672")
    finding["copies"]["cpython-3.11.17"]["state"] = "remediated"
    with pytest.raises(ValueError, match="Unsupported disposition"):
        compile_result(inputs, *historical)


def test_bootstrap_followups_visible_but_do_not_expand_frozen_dispositions(inputs, historical):
    result = compile_result(inputs, *historical)
    disclosure = result["newly_encountered"]
    assert len(disclosure["items"]) == 21
    assert {row["component"] for row in disclosure["items"]} == BOOTSTRAP_FOLLOWUP_IDS.keys()
    assert {row["status"] for row in disclosure["items"]} == {"OPEN-unassessed"}
    assert not {row["id"] for row in disclosure["items"]} & inputs["scope"].keys()
    assert result["counts"] == {"OPEN": 11, "supported-not-affected": 21}
    report = (EVIDENCE / (PREFIX + ".md")).read_text()
    assert all(row["id"] in report and row["advisory_url"] in report for row in disclosure["items"])


@pytest.mark.parametrize("mutation", [
    "drop", "duplicate", "clear", "wrong-archive", "wrong-existing-archive", "wrong-version", "missing-source", "cutoff",
])
def test_bootstrap_followup_disclosure_mutations_rejected(inputs, historical, mutation):
    disclosure = inputs["newly_encountered"]
    if mutation == "drop":
        disclosure["items"].pop()
    elif mutation == "duplicate":
        disclosure["items"][-1] = deepcopy(disclosure["items"][0])
    elif mutation == "clear":
        disclosure["items"][0]["status"] = "supported-not-affected"
    elif mutation == "wrong-archive":
        disclosure["archives"]["pip-24.0"]["sha256"] = "0" * 64
    elif mutation == "wrong-existing-archive":
        disclosure["items"][0]["archive"] = "setuptools-79.0.1"
    elif mutation == "wrong-version":
        disclosure["items"][0]["recorded_version"] = "999.0"
    elif mutation == "missing-source":
        disclosure["items"][0]["source_receipt"]["sha256"] = ""
    else:
        disclosure["research_cutoff_utc"] = ""
    with pytest.raises(ValueError, match="[Bb]ootstrap"):
        compile_result(inputs, *historical)


@pytest.mark.parametrize("field", ["tar_directory_regression", "setuptools_normalization_regression"])
def test_required_backport_regression_cannot_be_missing(inputs, historical, field):
    inputs["artifact"][field] = {}
    with pytest.raises(ValueError, match="regression|normalization"):
        compile_result(inputs, *historical)


def test_aggregation_keeps_one_open_copy_visible(inputs, historical):
    result = compile_result(inputs, *historical)
    row = next(f for f in result["findings"] if f["id"] == "CVE-2026-59890")
    assert row["state"] == "OPEN"
    assert [name for name, value in row["copies"].items() if value["state"] == "OPEN"] == ["bootstrap-setuptools-79.0.1"]


def test_probe_tar_regression_is_wholly_temporary():
    try:
        result = tar_directory_regression()
    except FileExistsError as error:
        # An older assessor interpreter may expose the bug; only the image probe is acceptance evidence.
        assert "/destination/../outside/../destination" in error.filename
        return
    assert set(result) == {"member_extracted_inside", "outside_directory_created"}
    assert all(isinstance(value, bool) for value in result.values())


def test_wheel_inventory_retains_native_and_all_vendor_copies(tmp_path):
    import zipfile
    path = tmp_path / "synthetic.whl"
    with zipfile.ZipFile(path, "w") as wheel:
        wheel.writestr("pip/_vendor/msgpack/_cmsgpack.so", b"synthetic native marker")
        wheel.writestr("pip/_vendor/urllib3/response.py", b"synthetic")
        wheel.writestr("pip/_vendor/vendor.txt", "urllib3==2.7.0\n")
    result = wheel_records(path)
    assert len(result["members"]) == 3
    assert result["vendor_declarations"] == {"pip/_vendor/vendor.txt": "urllib3==2.7.0\n"}


def tar_bytes(path, files):
    with tarfile.open(path, "w") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


def test_official_comparison_checks_bytes_not_version_only(tmp_path):
    python = tmp_path / "python.tar"
    jdk = tmp_path / "jdk.tar"
    page = tmp_path / "release.html"
    checksum = tmp_path / "jdk.sha256"
    tar_bytes(python, {"Python-3.11.17/Lib/pkgutil.py": b"official"})
    tar_bytes(jdk, {"jdk/lib/modules": b"official jdk"})
    page.write_text(hashlib.sha256(python.read_bytes()).hexdigest())
    checksum.write_text(hashlib.sha256(jdk.read_bytes()).hexdigest())
    probe = {"modules": {"pkgutil": {"path": "/usr/local/lib/python3.11/pkgutil.py", "sha256": "0" * 64}},
             "jdk_files": {"lib/modules": {"sha256": "0" * 64}}}
    with pytest.raises(ValueError, match="stdlib differs"):
        compare_archives(probe, python, page, jdk, checksum)
    probe["modules"] = {}
    result = compare_archives(probe, python, page, jdk, checksum)
    assert "lib/modules" in result["jdk_different_files"]
    official_digest = hashlib.sha256(b"official jdk").hexdigest()
    probe["jdk_files"]["lib/modules"]["sha256"] = official_digest
    result = compare_archives(probe, python, page, jdk, checksum)
    assert result["jdk_matched_files"] == {"lib/modules": {"sha256": official_digest}}
    checksum.write_text("0" * 64)
    with pytest.raises(ValueError, match="checksum"):
        compare_archives(probe, python, page, jdk, checksum)


def test_cli_check_rejects_changed_historical_bytes(tmp_path, inputs, historical):
    for name, value in zip(("ledger", "delta", "identities"), historical, strict=True):
        # Reformatting also changes the historical source receipt; never silently overwrite it.
        (tmp_path / ("studio-image-refresh-2026-10-04-" + name + ".json")).write_bytes(encoded(deepcopy(value)))
    (tmp_path / (PREFIX + "-inputs.json")).write_bytes(encoded(inputs))
    result = subprocess.run([sys.executable, "-m", "scripts.image_runtime_dispositions", "--check",
                             "--evidence-dir", str(tmp_path)], capture_output=True, text=True)
    assert result.returncode != 0
    assert "Historical evidence changed" in result.stderr
