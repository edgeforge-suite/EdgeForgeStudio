"""Replay Bundle P evidence from private retained inputs; never scan or build.

Historical records remain immutable. A disappearing match is not a disposition.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
from collections import Counter, defaultdict
from pathlib import Path

from scripts.image_assessment_report import summarize
from scripts.image_findings_ledger import normalize, write_ledger
from scripts.verify_image_oci import verify

PREFIX = "studio-image-bundle-p-2026-10-11"
HISTORY = "studio-image-runtime-2026-10-08"
IMAGE = "sha256:1a2a15d0adb3437c9c12afc42022cc2ba560c541e65b0287eb3eef0100bfb567"
PYTHON_SOURCE = "f4b1bfb3c79b5bb11b8d228a12504163b4c0dab4d679828d8f5f26b6cb6ab35d"
PIP_WHEEL = "71138adf1f4ca900cdb7d289c21b7494329f2332b6d85f0e1c42108c0384ed3e"
STDLIB_PATHS = {name: name.replace(".", "/") + ".py" for name in (
    "base64", "encodings.idna", "http.cookies", "imaplib", "pkgutil", "poplib",
    "stringprep", "tarfile", "tempfile", "urllib.request")}
STDLIB_PATHS["zipfile"] = "zipfile/__init__.py"
ALWAYS_OPEN = {"CVE-2025-12781", "CVE-2025-15367", "CVE-2026-12345",
               "CVE-2026-3446", "CVE-2026-102633", "CVE-2026-97687",
               "CVE-2026-97688", "CVE-2026-97689"}
# Original recorded executor identities, verified against ae99f6d's source.
# Replaying with later tooling must not relabel the historical execution.
RECORDED_PROOF_TOOLS = {
    "image_bootstrap_proof.py": "7a247e004897a14ae47f60da59a780dcd6785c716f18ef00d23b386495b5df95",
    "image_bundle_p_probe.py": "00f3672983d4b92a63f1af5670ee54cca30da6b7ba85609b3073de4d5d3f2106",
    "maven_image_build_run_proof.py": "aaec27eb581cd307d8ef79950546e1ec6543b92abfb0f4d1441f159082526b0f",
    "verify_image_oci.py": "6c287b4bdb5b7f803e63b601190a407760b1d9f264a7361c4ee01b494493cdfc",
}


def recorded_proof_tools() -> dict[str, str]:
    return dict(RECORDED_PROOF_TOOLS)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def load(path: Path):
    return json.loads(path.read_bytes())


def base_identities(records: list[dict]) -> list[dict]:
    # Full config env/history remains in the hash-bound private inputs. Avoid
    # duplicating upstream build prose and public signing fingerprints here.
    fields = ("repository", "requested", "index_digest", "platform_descriptor", "config_digest")
    return [{key: record[key] for key in fields} for record in records]


def stdlib_records(probe: dict) -> dict:
    modules = probe.get("modules")
    if not isinstance(modules, dict) or not STDLIB_PATHS.keys() <= modules.keys():
        raise ValueError("Incomplete required stdlib source records")
    for name, relative in STDLIB_PATHS.items():
        row = modules[name]
        if (not isinstance(row, dict) or "import_error" in row
                or row.get("path") != "/usr/local/lib/python3.13/" + relative
                or not isinstance(row.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])):
            raise ValueError("Invalid required stdlib source record: " + name)
    return {name: modules[name] for name in STDLIB_PATHS}


def validate_source_comparison(probe: dict, comparison: dict) -> None:
    records = stdlib_records(probe)
    hashes = comparison.get("stdlib_module_sha256")
    if (comparison.get("python_source_sha256") != PYTHON_SOURCE
            or not isinstance(hashes, dict) or set(hashes) != set(STDLIB_PATHS)):
        raise ValueError("Incomplete official stdlib source comparison")
    if any(hashes[name] != row["sha256"] for name, row in records.items()):
        raise ValueError("Official/installed stdlib source hashes differ")


def official_comparison(probe: dict, source: Path, old: dict) -> dict:
    records = stdlib_records(probe)
    if digest(source.read_bytes()) != PYTHON_SOURCE:
        raise ValueError("Approved CPython source archive differs")
    modules = {}
    with tarfile.open(source) as archive:
        for name, record in records.items():
            data = archive.extractfile("Python-3.13.16/Lib/" + STDLIB_PATHS[name]).read()
            if digest(data) != record["sha256"]:
                raise ValueError("Installed CPython module differs: " + name)
            modules[name] = record["sha256"]
        news = "\n".join(archive.extractfile(m).read().decode(errors="replace")
                         for m in archive.getmembers()
                         if m.isfile() and ("/Misc/NEWS" in m.name or m.name.endswith("/Misc/HISTORY")))
    previous = old["official_comparison"]
    expected_jdk = {name: row["sha256"] for name, row in previous["jdk_matched_files"].items()}
    expected_jdk.update({name: row["installed"]["sha256"] for name, row in previous["jdk_different_files"].items()})
    actual_jdk = {name: row["sha256"] for name, row in probe["jdk_files"].items() if "sha256" in row}
    jdk_equal = actual_jdk == expected_jdk
    if not jdk_equal:
        raise ValueError("Copied JDK differs from advisory-bound historical bytes")
    copies = probe["copies"]
    prefix = "/usr/local/lib/python3.13/site-packages/"
    equal = {}
    for name, historical in (("msgpack", "pip-msgpack-1.1.2"),
                             ("pkg_resources", "pip-pkg-resources-70.3.0"),
                             ("urllib3", "pip-urllib3-2.7.0")):
        equal[name] = copies[prefix + "pip/_vendor/" + name] == old["copies"][historical]["evidence"]["file_inventory"]
        if not equal[name]:
            raise ValueError("Unexplained changed pip vendor bytes: " + name)
    bundles = probe["bundled_wheels"]
    expected = "/usr/local/lib/python3.13/ensurepip/_bundled/pip-26.2.1-py3-none-any.whl"
    if set(bundles) != {expected} or bundles[expected]["sha256"] != PIP_WHEEL:
        raise ValueError("Unexpected archived bootstrap copy")
    bootstrap = bundles[expected]
    if bootstrap["vendor_declarations"].get("pip/_vendor/vendor.txt") != probe["vendor_declarations"]:
        raise ValueError("Active and archived vendor declarations differ")
    for name in equal:
        for member, row in copies[prefix + "pip/_vendor/" + name].items():
            if bootstrap["members"].get("pip/_vendor/" + name + "/" + member) != row:
                raise ValueError("Active and archived vendor code differs")
    return {"python_source_sha256": PYTHON_SOURCE, "stdlib_module_sha256": modules,
            "release_news_mentions": sorted({row["id"] for row in old["findings"] if row["id"] in news}),
            "jdk_regular_files_equal_to_311": jdk_equal,
            "jdk_regular_file_count": len(actual_jdk),
            "jdk_file_records_sha256": digest(encoded(probe["jdk_files"])),
            "pip_vendor_bytes_equal_to_311_active": equal,
            "active_and_bootstrap_vendor_bytes_equal": True,
            "upstream_bootstrap_wheel_sha256": PIP_WHEEL}


def dispositions(probe: dict, old: dict, comparison: dict) -> list[dict]:
    validate_source_comparison(probe, comparison)
    if (not comparison["jdk_regular_files_equal_to_311"]
            or not comparison["active_and_bootstrap_vendor_bytes_equal"]
            or not all(comparison["pip_vendor_bytes_equal_to_311_active"].values())):
        raise ValueError("Unverified historical byte carryforward")
    behavior = probe["behavior_regressions"]
    if (not probe["python"].startswith("3.13.16 ") or probe["uid"] == 0
            or probe["copy_search_errors"] or probe["platform"] != "x86_64"
            or probe["distributions"] != {"pip": "26.2.1", "setuptools": "83.0.0", "wheel": "0.48.0"}
            or probe["pip_check"]["exit_code"]):
        raise ValueError("Incomplete or incompatible runtime proof")
    if (behavior["imap_sent_bytes_hex"] or not behavior["imap_newline_error"]
            or not behavior["morsel_rejects_control_characters"]
            or "synthetic%3D%3C%2Fscript%3E" not in behavior["morsel_js_output"]):
        raise ValueError("Required IMAP/Morsel behavior proof failed")
    rows = []
    for index, historical in enumerate(old["findings"]):
        advisory = historical["id"]
        state, reason = "OPEN", "Changed artifact needs advisory-specific evidence; scanner silence is insufficient."
        if advisory in ALWAYS_OPEN:
            reason = {
                "CVE-2025-12781": "Original alphabet characters still decode with an alternate alphabet; deprecation is not behavioral remediation. Caller integrity/applicability proof is missing.",
                "CVE-2025-15367": "POP3 remains in the PSF affected range; no supported correction in the approved bundle.",
                "CVE-2026-12345": "Target resists symlink deletion and preserves tested outside-file content/mode, but complete file-flags/path applicability is not established; current scanner still reports it.",
                "CVE-2026-3446": "Strict decoding rejects trailing data, but default decoding still accepts it and relevant callers' strict processing is unproven.",
                "CVE-2026-102633": "pyexpat still embeds Expat 2.8.5; system Expat updates do not replace these bytes. Native overflow applicability remains unproven.",
            }.get(advisory, "Active and new bootstrap pip both retain private urllib3 2.7.0; standalone updates do not change either copy. A supported upstream pip correction or scoped applicability decision is required.")
        elif advisory in {"CVE-2025-15366", "CVE-2026-6019"}:
            state = "remediated"
            reason = "Checksum-matched official 3.13.16 module plus actual IMAP no-send newline rejection." if advisory.endswith("15366") else "Checksum-matched official 3.13.16 module plus actual control-character rejection and encoded Morsel JavaScript output."
        elif advisory == "CVE-2026-59890":
            if probe["setuptools_normalization_regression"] != {"remaining_files": ["public.txt"]}:
                raise ValueError("Setuptools normalization proof failed")
            state, reason = "remediated", "The old full setuptools 79.0.1 bootstrap archive is absent; explicit full 83.0.0 passes normalization. Active and archived pip contain only the unchanged stripped pkg_resources subset."
        elif old["scope"][advisory]["component"] in {"temurin", "msgpack", "setuptools"}:
            state, reason = "supported-not-affected", "Inherited advisory-specific rationale retained with actual unchanged JDK/vendor bytes; archived pip vendors now match those same active bytes. No new fix credit."
        elif advisory in comparison["release_news_mentions"]:
            state, reason = "supported-not-affected", "Inherited correction remains named in the official 3.13.16 release NEWS and affected stdlib bytes match that archive. No new fix credit."
            if advisory == "CVE-2026-19672" and probe["tar_directory_regression"] != {"member_extracted_inside": True, "outside_directory_created": False}:
                raise ValueError("Historical tar backport behavior regressed")
        historical_state = "OPEN" if any(copy["state"] == "OPEN" for copy in historical["copies"].values()) else "supported-not-affected"
        rows.append({"id": advisory, "historical_index": index, "historical_state": historical_state,
                     "historical_copy_ids": sorted(historical["copies"]), "state": state,
                     "reason": reason, "sources": sorted({s for copy in historical["copies"].values() for s in copy["sources"]}),
                     "next_action": "Studio/security owner: obtain missing caller/native/vendor evidence or separately authorize supported correction; final-pair revalidation remains required." if state == "OPEN" else "Revalidate after runtime/vendor/base or selected release-pair changes."})
    return rows


def validate_proofs(bootstrap: dict, runtime: dict) -> None:
    if (bootstrap["result"] != "pass" or bootstrap["uid"] == 0
            or bootstrap["seed"] != {"pip": "26.2.1"}
            or bootstrap["explicit_toolchain"] != {"pip": "26.2.1", "setuptools": "83.0.0", "wheel": "0.48.0", "packaging": "26.2"}
            or bootstrap["wheelhouse_sha256"]["pip-26.2.1-py3-none-any.whl"] != PIP_WHEEL
            or any(row["exit_code"] for row in bootstrap["commands"])):
        raise ValueError("Incomplete offline bootstrap proof")
    counts = runtime["maven_tests"]
    requests = runtime["application_requests"]
    if (runtime["result"] != "pass" or runtime["uid"] == 0 or runtime["ka_enabled"]
            or not runtime["jar_built"] or counts["tests"] <= 0
            or any(counts[key] for key in ("failures", "errors", "skipped"))
            or requests["create_status"] != 201 or requests["read_status"] != 200
            or requests["missing_id_status"] != 404
            or requests["create_response"] != requests["request"]
            or requests["read_response"] != requests["request"]):
        raise ValueError("Incomplete executed-test/application proof")


def validation_result(text: str) -> dict:
    failures = [line.split(" - ", 1)[0].removeprefix("FAILED ")
                for line in text.splitlines() if line.startswith("FAILED ")]
    allowed = {
        "tests/test_dom_xss.py::test_one_audited_encoder_owns_text_and_quoted_attribute_encoding",
        "tests/test_dom_xss.py::test_hostile_saved_kafka_project_cannot_break_out_of_card_markup",
        "tests/test_dom_xss.py::test_hostile_openapi_descriptor_cannot_break_passthrough_markup",
        "tests/test_dom_xss.py::test_hostile_operation_name_completes_step3_sample_and_mapping_collection",
    }
    if set(failures) - allowed or " errors in " in text or "Stored-XSS markup tests require Node" not in text:
        raise ValueError("Unexpected image validation failure")
    passed = re.search(r"(\d+) passed", text)
    skipped = re.search(r"(\d+) skipped", text)
    if not passed:
        raise ValueError("Image regression tests did not execute")
    return {"state": "environment-limited, not all-green", "passed": int(passed[1]),
            "skipped": int(skipped[1]) if skipped else 0, "failed": failures,
            "limitation": "Node-dependent DOM tests require host/CI validation; Node is not an image runtime dependency. Original three path-guard failures passed with guard intact."}


def lineage(old: dict, new: dict) -> dict:
    current = defaultdict(list)
    for index, group in enumerate(new["groups"]):
        component = new["components"][group["component"]]
        current[(component["type"], component["name"], group["advisory_identity"])].append(index)
    mapped = []
    for index, group in enumerate(old["groups"]):
        component = old["components"][group["component"]]
        matches = current.get((component["type"], component["name"], group["advisory_identity"]), [])
        mapped.append({"historical_group": index, "current_groups": matches,
                       "state": "observed" if matches else "not-observed; not a disposition"})
    return {"historical_groups": len(old["groups"]), "current_groups": len(new["groups"]),
            "mapping": mapped, "family_owner_queue": old["decisions"],
            "qualification": "Different source versions and advisory databases: match/count changes are not attributed to remediation. All historical families, including zero-match coverage families, remain traceable and require current artifact applicability proof."}


def build(root: Path, evidence: Path) -> dict[str, dict]:
    old = load(evidence / (HISTORY + "-inputs.json"))
    historical = load(evidence / "studio-image-refresh-2026-10-04-ledger.json")
    oci = verify(root / "image.tar", IMAGE)
    rounds = []
    for number in (1, 2):
        reports = [load(root / f"{name}-{number}.json") for name in ("syft", "grype", "trivy")]
        summary = summarize(*reports)
        ledger = normalize(*reports)
        if summary["image_index_digest"] != IMAGE or summary["image_config_digest"] != oci["config_digest"]:
            raise ValueError("Wrong-image reports")
        rounds.append((reports, summary, ledger))
    if (rounds[0][1:] != rounds[1][1:] or rounds[0][0][0]["artifacts"] != rounds[1][0][0]["artifacts"]):
        raise ValueError("Repeated observations differ; retain and investigate, do not discard")
    probe = load(root / "runtime-probe-resume.json")
    container = load(root / "proof-container-before-stop.json")[0]
    if container["Image"] != IMAGE or container["Mounts"] or container["NetworkSettings"]["Networks"]:
        raise ValueError("Probe container identity/mount/network differs")
    comparison = official_comparison(probe, root / "artifacts/Python-3.13.16.tar.xz", old)
    rows = dispositions(probe, old, comparison)
    summary, ledger = rounds[0][1:]
    ledger["source_sha256"] = {name: digest((root / f"{name}-1.json").read_bytes()) for name in ("syft", "grype", "trivy")}
    delta = lineage(historical, ledger)
    # Keep every additional old-bootstrap association separate from scoped IDs.
    bootstrap = [{"id": row["id"], "component": row["component"], "historical_index": index,
                  "historical_archive": row["archive"], "historical_version": row["recorded_version"],
                  "state": "old-bootstrap-copy-replaced; successor applicability requires range reconciliation",
                  "source": row["advisory_url"], "next_action": "Studio/security owner: retain the association and reconcile replacement vendor ranges before final M2 disposition; no blanket clearance."}
                 for index, row in enumerate(old["newly_encountered"]["items"])]
    runtime = {key: probe[key] for key in ("python", "uid", "gid", "platform", "pointer_bits", "python_optimization", "copy_search_errors",
               "distributions", "distribution_copies", "embedded_expat", "expat_ldd", "system_expat", "modules",
               "functions", "vendor_declarations", "msgpack_implementation", "behavior_regressions", "pip_check",
               "tar_directory_regression", "setuptools_normalization_regression", "jdk_release", "java_version")}
    runtime["copies"] = {name: {"file_records_sha256": digest(encoded(records)), "file_count": len(records),
                                "native_files": [f for f in records if f.endswith((".so", ".c", ".pyx", ".pyd"))]}
                         for name, records in probe["copies"].items()}
    runtime["bootstrap_wheels"] = {name: {"sha256": row["sha256"], "vendor_declarations": row["vendor_declarations"]}
                                    for name, row in probe["bundled_wheels"].items()}
    retained = [f"{name}-{n}.json" for n in (1, 2) for name in ("syft", "grype", "trivy")]
    retained += ["image.tar", "engine.tar", "sbom.cdx.json", "runtime-probe-resume.json", "bootstrap-proof.json",
                 "buildrun/result.json", "image-regressions-resume.log", "image-regressions-resume-executed.log",
                 "image-regressions.log", "image-regressions-retry.log", "runtime-probe-final.stderr",
                 "runtime-probe-final-retry.stderr", "build-1.log", "build-metadata.json", "dpkg-packages.txt",
                 "apt-sources.txt", "image-launch-smoke.log", "proof-container-before-stop.json",
                 "entry/selected-bases.json"]
    bootstrap_proof, build_run = load(root / "bootstrap-proof.json"), load(root / "buildrun/result.json")
    validate_proofs(bootstrap_proof, build_run)
    receipt = {"candidate": "EF-V5-M2-STUDIO-IMAGE-BUNDLE-P", "revision": 1,
               "studio_base": "260af2983eb74c8f0eb38fe757120086a3228528",
               "image_tested_studio": "98a50bf0204976043f1d69580113a30c390e1b31",
               "engine": "30d25d055c48001e6478493c8993d1e029d4df8f", "pairing": "provisional, not final release selection",
               "image": oci, "bases": base_identities(load(root / "entry/selected-bases.json")),
               "tools": load(root / "tools/verified.json"), "databases_sha256": load(root / "frozen-db-sha256.json"),
               "grype_database": summary["advisory_db"],
               "trivy_database": load(root / "trivy-cache/db/metadata.json"),
               "trivy_java_database": load(root / "trivy-cache/java-db/metadata.json"),
               "official_downloads": load(root / "artifacts/verified.json"), "entry_sources": load(root / "entry/receipts.json"),
               "raw_sha256": {name: digest((root / name).read_bytes()) for name in retained},
               "historical_sha256": {name: digest((evidence / name).read_bytes()) for name in (
                   HISTORY + "-inputs.json", HISTORY + "-results.json", "studio-image-refresh-2026-10-04-ledger.json")},
               "runtime": runtime, "official_comparison": comparison,
               "bootstrap_proof": bootstrap_proof, "build_run": build_run,
               "image_regressions": validation_result((root / "image-regressions-resume-executed.log").read_text()),
               "proof_tools_sha256": recorded_proof_tools(),
               "apt_sources": (root / "apt-sources.txt").read_text(),
               "installed_debian_packages": sorted((root / "dpkg-packages.txt").read_text().splitlines()),
               "repeat": load(root / "repeat-result.json"),
               "raw_retention": "Private EdgeForge Open-Source Artifacts / Studio-Bundle-P-2026-10-11",
               "local_full_builds_used": 1, "risk_accepted": False, "m2_cleared": False}
    result = {"candidate": receipt["candidate"], "scoped_findings": rows,
              "scoped_counts": dict(Counter(row["state"] for row in rows)), "additional_bootstrap_associations": bootstrap,
              "lineage": delta, "newly_encountered": [
                  {"id": "CVE-2026-77214", "scope": "system/embedded Expat XML_ParseBuffer", "state": "OPEN",
                   "next_action": "Studio/security owner: reconcile vendor/backport and native call preconditions; system and embedded copies are separate."}],
              "risk_accepted": False, "m2_cleared": False}
    return {"summary": summary, "ledger": ledger, "receipt": receipt, "delta": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retained", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, default=Path("docs/handover-evidence"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = build(args.retained, args.evidence_dir)
    for name, value in outputs.items():
        path = args.evidence_dir / (PREFIX + "-" + name + ".json")
        if args.check:
            if load(path) != value:
                raise ValueError("Evidence differs: " + name)
        elif name == "ledger":
            write_ledger(path, value)
        else:
            path.write_bytes(encoded(value))


if __name__ == "__main__":
    main()
