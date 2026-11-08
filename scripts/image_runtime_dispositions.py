"""Validate and replay the bounded runtime S2 evidence, not general image clearance."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import tarfile
from collections import Counter
from pathlib import Path

PREFIX = "studio-image-runtime-2026-10-08"
JDK_IDS = {
    "CVE-2026-41254", "CVE-2026-47063", "CVE-2026-60147", "CVE-2026-46968",
    "CVE-2026-47059", "CVE-2026-47027", "CVE-2026-47021", "CVE-2026-46917",
    "CVE-2026-47010", "CVE-2026-61308", "CVE-2026-70907", "CVE-2026-60589",
}
COPIES = {
    "python": {"cpython-3.11.17"},
    "embedded-expat": {"embedded-expat-2.8.5"},
    "msgpack": {"pip-msgpack-1.1.2", "bootstrap-msgpack-1.0.5"},
    "setuptools": {"pip-pkg-resources-70.3.0", "bootstrap-pkg-resources-68.0.0",
                   "installed-setuptools-83.0.0", "bootstrap-setuptools-79.0.1"},
    "urllib3": {"pip-urllib3-2.7.0", "bootstrap-urllib3-1.26.17"},
    "temurin": {"temurin-21.0.12.1+1"},
}
STATES = {"OPEN", "supported-not-affected"}
STDLIB_MODULES = {
    "base64", "encodings.idna", "http.cookies", "imaplib", "pkgutil", "poplib",
    "stringprep", "tarfile", "tempfile", "urllib.request", "zipfile",
}
BOOTSTRAP_FOLLOWUP_IDS = {
    "pip": {"CVE-2026-13346", "CVE-2026-8643", "CVE-2026-6357", "CVE-2026-3219", "CVE-2026-1703", "CVE-2025-8869"},
    "urllib3": {"CVE-2026-44431", "CVE-2026-21441", "CVE-2025-66471", "CVE-2025-66418", "CVE-2025-50181", "CVE-2024-37891", "CVE-2023-45803"},
    "requests": {"CVE-2026-25645", "CVE-2024-47081", "CVE-2024-35195"},
    "certifi": {"CVE-2024-39689"},
    "idna": {"CVE-2026-45409", "CVE-2024-3651"},
    "setuptools": {"CVE-2024-6345"},
    "wheel": {"CVE-2026-24049"},
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def validate_bootstrap_disclosure(disclosure: dict, inputs: dict) -> None:
    """Keep newly encountered associations separate from frozen dispositions."""
    expected = {advisory: component for component, ids in BOOTSTRAP_FOLLOWUP_IDS.items() for advisory in ids}
    items = disclosure["items"]
    if len(items) != len(expected) or {row["id"]: row["component"] for row in items} != expected:
        raise ValueError("Incomplete bootstrap advisory disclosure")
    if (disclosure["status"] != "OPEN-unassessed" or not disclosure["coverage_limit"]
            or not disclosure["next_action"] or expected.keys() & inputs["scope"].keys()):
        raise ValueError("Bootstrap coverage exclusion is not a frozen disposition")
    archives = disclosure["archives"]
    for name, copy_id in (("pip-24.0", "bootstrap-urllib3-1.26.17"),
                          ("setuptools-79.0.1", "bootstrap-setuptools-79.0.1")):
        if archives[name]["sha256"] != inputs["copies"][copy_id]["evidence"]["wheel_sha256"]:
            raise ValueError("Bootstrap disclosure archive differs from assessed copy")
    for row in items:
        receipt = row["source_receipt"]
        if (row["status"] != "OPEN-unassessed" or row["archive"] not in archives
                or not row["recorded_version"] or not row["affected_ranges"] or not row["applicability_note"]
                or not row["advisory_url"].startswith("https://github.com/advisories/")
                or receipt["url"] != "https://api.github.com/advisories?cve_id=" + row["id"]
                or not re.fullmatch(r"[a-f0-9]{64}", receipt["sha256"])):
            raise ValueError("Invalid unassessed bootstrap association/source")
        component, version = row["component"], row["recorded_version"]
        expected_archive = "setuptools-79.0.1" if component == "wheel" else "pip-24.0"
        if row["archive"] != expected_archive:
            raise ValueError("Bootstrap association targets wrong archive")
        if component == "pip":
            version_matches = "pip-" + version == expected_archive
        elif component == "wheel":
            version_matches = ("setuptools/_vendor/wheel-" + version + ".dist-info/METADATA"
                               in archives[expected_archive]["nested_wheel_members"])
        else:
            declarations = archives[expected_archive]["vendor_declarations"]["pip/_vendor/vendor.txt"]
            version_matches = any(line.split("#", 1)[0].strip() == component + "==" + version
                                  for line in declarations.splitlines())
        if not version_matches:
            raise ValueError("Bootstrap association version differs from archive inventory")
    if max(row["source_receipt"]["retrieved_utc"] for row in items) != disclosure["research_cutoff_utc"]:
        raise ValueError("Bootstrap disclosure research cutoff differs")


def frozen_scope(ledger: dict, delta: dict) -> dict:
    scope = {}
    for index, group in enumerate(ledger["groups"]):
        component = ledger["components"][group["component"]]
        if component["decision"] == "cpython" or component["decision"].startswith("embedded-python:"):
            scope[group["advisory_identity"]] = {
                "component": component["name"], "current_group_index": index,
                "observation_indexes": group["observation_indexes"],
                "recorded_version": component["version"],
            }
    for entry in delta["catalog_delta"]:
        if entry["name"] == "python" and not entry["new_group_indexes"]:
            scope[entry["advisory_identity"]] = {
                "component": "python", "historical_group_indexes": entry["old_group_indexes"],
                "observation_indexes": [], "recorded_version": "3.11.16",
            }
    scope["CVE-2026-102633"] = {"component": "embedded-expat", "observation_indexes": [],
                                 "recorded_version": delta["embedded_expat"]["version"]}
    for advisory in sorted(JDK_IDS):
        scope[advisory] = {"component": "temurin", "observation_indexes": [],
                           "recorded_version": "21.0.12.1+1", "origin": "vendor-matrix-JDK21"}
    return dict(sorted(scope.items()))


def compare_archives(probe: dict, python_tar: Path, release_page: Path,
                     jdk_tar: Path, jdk_checksum: Path) -> dict:
    """Compare actual bytes, not just installed distribution version strings."""
    page = release_page.read_bytes()
    if page.startswith(b"\x1f\x8b"):
        page = gzip.decompress(page)
    python_hash = digest(python_tar.read_bytes())
    if python_hash not in re.sub(r"<[^>]+>", "", page.decode()):
        raise ValueError("Python source checksum not in official release page")
    jdk_hash = digest(jdk_tar.read_bytes())
    if jdk_hash != jdk_checksum.read_text().split()[0]:
        raise ValueError("JDK official checksum mismatch")
    matched, different, missing = {}, {}, {}
    with tarfile.open(jdk_tar) as archive:
        for member in archive:
            if not member.isfile():
                continue
            name = member.name.split("/", 1)[-1]
            source_hash = digest(archive.extractfile(member).read())
            actual = probe["jdk_files"].get(name)
            if actual is None:
                missing[name] = source_hash
            elif actual.get("sha256") == source_hash:
                matched[name] = {"sha256": source_hash}
            else:
                different[name] = {"official": source_hash, "installed": actual}
    modules = {}
    with tarfile.open(python_tar) as archive:
        prefix = "/usr/local/lib/python3.11/"
        for name, module in probe["modules"].items():
            path = module.get("path", "")
            if not path.startswith(prefix) or "site-packages" in path or "lib-dynload" in path:
                continue
            source = archive.extractfile("Python-3.11.17/Lib/" + path[len(prefix):]).read()
            modules[name] = {"official_sha256": digest(source), "installed_sha256": module["sha256"],
                             "equal": digest(source) == module["sha256"]}
            if not modules[name]["equal"]:
                raise ValueError("Installed stdlib differs: " + name)
    return {"jdk_archive_sha256": jdk_hash, "jdk_matched_files": matched,
            "jdk_different_files": different, "jdk_missing_files": missing,
            "python_source_sha256": python_hash, "python_modules": modules}


def compile_result(inputs: dict, ledger: dict, delta: dict, identity: dict) -> dict:
    if inputs["scope"] != frozen_scope(ledger, delta):
        raise ValueError("Frozen scope differs; historical or vendor identities cannot disappear")
    for key, value in inputs["image"].items():
        if value != identity["image"][key]:
            raise ValueError("Image identity mismatch: " + key)
    if set(inputs["image"]) != {"index_digest", "platform_descriptor", "config_descriptor"}:
        raise ValueError("Incomplete image identity")
    oci = inputs["oci_reverification"]
    if (not oci["all_manifest_layer_blob_hashes_sizes_and_decompressed_diff_ids_verified"]
            or any(oci[key] != value for key, value in inputs["image"].items())):
        raise ValueError("OCI byte reverification mismatch")
    if inputs["image_engine_sha"] != identity["frozen_engine_sha"]:
        raise ValueError("Assessed Engine differs from frozen image Engine")
    if inputs["image_studio_sha"] != identity["image_tested_studio_sha"]:
        raise ValueError("Assessed Studio identity mismatch")
    receipt = inputs["probe_receipt"]
    if (receipt["exit_code"] != 0 or receipt["mounts"] or receipt["network"] != "none"
            or receipt["docker_image_inspect"]["Id"] != inputs["image"]["index_digest"]
            or receipt["stdout_sha256"] != inputs["new_raw_sha256"]["runtime-probe.json"]
            or receipt["stdin_sha256"] != inputs["new_raw_sha256"]["probe_script"]):
        raise ValueError("Unbound or incomplete retained-image probe")
    probe = inputs["artifact"]
    if (probe["copy_search_errors"] or probe["uid"] == 0 or probe["pointer_bits"] != 64
            or probe["platform"] != "x86_64"):
        raise ValueError("Incomplete or different artifact probe")
    if not probe["python"].startswith("3.11.17") or "21.0.12.1" not in probe["jdk_release"]:
        raise ValueError("Runtime version mismatch")
    if probe["tar_directory_regression"] != {"member_extracted_inside": True, "outside_directory_created": False}:
        raise ValueError("Tar-directory backport regression failed")
    if probe["setuptools_normalization_regression"] != {"remaining_files": ["public.txt"]}:
        raise ValueError("Installed setuptools normalization fix not established")
    if probe["pip_check"]["exit_code"] or probe["java_version"]["exit_code"]:
        raise ValueError("Runtime inspection failed")
    comparison = inputs["official_comparison"]
    modules = comparison["python_modules"]
    if not isinstance(modules, dict) or set(modules) != STDLIB_MODULES:
        raise ValueError("Incomplete stdlib source comparison")
    for name, row in modules.items():
        if (not isinstance(row, dict) or set(row) != {"official_sha256", "installed_sha256", "equal"}
                or any(not isinstance(row[key], str) or not re.fullmatch(r"[a-f0-9]{64}", row[key])
                       for key in ("official_sha256", "installed_sha256"))
                or row["official_sha256"] != row["installed_sha256"] or row["equal"] is not True):
            raise ValueError("Contradictory stdlib source comparison: " + name)
    if inputs["copies"]["cpython-3.11.17"]["evidence"]["source_match"] != modules:
        raise ValueError("CPython copy source-match projection differs")
    if (set(comparison["jdk_different_files"]) != {"lib/server/classes.jsa"}
            or set(comparison["jdk_missing_files"]) != {"lib/src.zip"}
            or not {"lib/modules", "lib/server/libjvm.so"} <= comparison["jdk_matched_files"].keys()):
        raise ValueError("Unexplained official artifact difference")
    for row in comparison["jdk_matched_files"].values():
        if (not isinstance(row, dict) or set(row) != {"sha256"}
                or not isinstance(row["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", row["sha256"])):
            raise ValueError("Invalid explicit JDK SHA-256 record")
    jdk_receipt = inputs["copies"]["temurin-21.0.12.1+1"]["evidence"]["official_archive"]
    if (digest(encoded(comparison["jdk_matched_files"])) != jdk_receipt["matched_file_map_sha256"]
            or len(comparison["jdk_matched_files"]) != jdk_receipt["matched_regular_files"]
            or comparison["jdk_archive_sha256"] != jdk_receipt["sha256"]):
        raise ValueError("JDK matched-file projection differs from archive receipt")
    sources = {source["id"]: source for source in inputs["sources"]}
    if len(sources) != len(inputs["sources"]):
        raise ValueError("Duplicate source provenance")
    for source in sources.values():
        if not source["url"].startswith("https://") or not re.fullmatch(r"[a-f0-9]{64}", source["sha256"]):
            raise ValueError("Invalid source provenance")
    artifacts = inputs["copies"]
    if set(artifacts) != set().union(*COPIES.values()):
        raise ValueError("Missing or added artifact copy")
    findings = inputs["findings"]
    if len(findings) != len(inputs["scope"]) or {f["id"] for f in findings} != set(inputs["scope"]):
        raise ValueError("Missing, duplicate or added finding")
    rows = []
    for finding in sorted(findings, key=lambda row: row["id"]):
        component = inputs["scope"][finding["id"]]["component"]
        dispositions = finding["copies"]
        if set(dispositions) != COPIES[component]:
            raise ValueError("Finding omits a duplicate/vendor copy: " + finding["id"])
        for copy_id, disposition in dispositions.items():
            if disposition["state"] not in STATES:
                raise ValueError("Unsupported disposition/risk acceptance")
            if not all(disposition.get(key) for key in ("reason", "sources", "artifact_evidence", "next_action")):
                raise ValueError("Incomplete evidence-backed disposition")
            if set(disposition["sources"]) - sources.keys():
                raise ValueError("Missing advisory/vendor source")
            if set(disposition["artifact_evidence"]) - artifacts[copy_id]["evidence"].keys():
                raise ValueError("Missing artifact-bound evidence")
            if not all(artifacts[copy_id]["evidence"][key] for key in disposition["artifact_evidence"]):
                raise ValueError("Empty artifact-bound evidence")
            if not disposition.get("advisory_specific"):
                raise ValueError("Inventory absence or scanner silence is not clearance")
            if component == "msgpack" and disposition["state"] != "OPEN":
                files = artifacts[copy_id]["evidence"]["file_inventory"]
                if (not {"__init__.py", "fallback.py"} <= files.keys()
                        or any(name.endswith((".so", ".pyd", ".pyx", ".c")) for name in files)
                        or probe["msgpack_implementation"] != "pip._vendor.msgpack.fallback"):
                    raise ValueError("Native msgpack exclusion unsupported by actual copy")
            # These exact unresolved prerequisites must not be cleared by changing a label.
            required_open = (
                finding["id"] in {"CVE-2025-12781", "CVE-2025-15366", "CVE-2025-15367",
                                  "CVE-2026-12345", "CVE-2026-3446", "CVE-2026-6019", "CVE-2026-102633"}
                or component == "urllib3" and (copy_id.startswith("pip-") or finding["id"] != "CVE-2026-97688")
                or finding["id"] == "CVE-2026-59890" and copy_id == "bootstrap-setuptools-79.0.1"
            )
            if required_open and disposition["state"] != "OPEN":
                raise ValueError("Unsupported new exclusion; unresolved exact copy must remain OPEN")
        states = {d["state"] for d in dispositions.values()}
        state = "OPEN" if "OPEN" in states else "supported-not-affected"
        rows.append({**finding, "state": state, "lineage": inputs["scope"][finding["id"]]})
    validate_bootstrap_disclosure(inputs["newly_encountered"], inputs)
    return {
        "candidate": "EF-V5-M2-STUDIO-IMAGE-RUNTIME-S2", "revision": 1,
        "schema_version": 1, "image": inputs["image"],
        "scanner_advisory_cutoff_utc": ledger["advisory_cutoff_utc"],
        "vendor_research_cutoff_utc": inputs["vendor_research_cutoff_utc"],
        "input_sha256": digest(encoded(inputs)), "findings": rows,
        "counts": dict(sorted(Counter(row["state"] for row in rows).items())),
        "newly_encountered": inputs["newly_encountered"],
        "interpretation": "Bounded artifact/advisory dispositions only; unresolved findings and overall M2 remain open.",
        "image_changed": False, "risk_accepted": False, "m2_cleared": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, default=Path("docs/handover-evidence"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    directory = args.evidence_dir
    paths = [directory / name for name in (
        PREFIX + "-inputs.json", "studio-image-refresh-2026-10-04-ledger.json",
        "studio-image-refresh-2026-10-04-delta.json", "studio-image-refresh-2026-10-04-identities.json")]
    inputs, ledger, delta, identity = [json.loads(path.read_bytes()) for path in paths]
    for path in paths[1:]:
        if digest(path.read_bytes()) != inputs["historical_file_sha256"][path.name]:
            raise ValueError("Historical evidence changed: " + path.name)
    script = directory.parents[1] / "scripts/image_runtime_probe.py"
    if digest(script.read_bytes()) != inputs["new_raw_sha256"]["probe_script"]:
        raise ValueError("Executed probe script changed; recapture evidence before replay")
    output = encoded(compile_result(inputs, ledger, delta, identity))
    target = directory / (PREFIX + "-results.json")
    if args.check:
        if target.read_bytes() != output:
            raise ValueError("Committed runtime dispositions do not replay")
    else:
        target.write_bytes(output)


if __name__ == "__main__":
    main()
