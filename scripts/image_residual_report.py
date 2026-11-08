"""Reduce a fixed local residual campaign; no builds, downloads or scanner calls."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import tarfile
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from scripts.image_assessment_report import _ignore_rule, _image_identity, summarize
from scripts.image_bundle_p_report import official_comparison, validate_proofs
from scripts.image_findings_ledger import _advisory_identity, normalize, write_ledger
from scripts.image_residual_inventory import inventory
from scripts.verify_image_oci import verify

PREFIX = "studio-image-residual-2026-10-14"
STUDIO = "ae99f6d3924ba01429edbdb25712e7cfffb38583"
ENGINE = "ba56abd1e0ff946260e96f3a3b715564fc0b740d"
SURFACES = ("final", "jdk21", "maven")
TOOLS = {"syft": ("1.52.0", "014d561b6d13059124155f74a6c5a9a99501f5e209313638dd884f39eb418ee6"),
         "grype": ("0.119.0", "500c9b2b6c089d21481815f57a553fabbd441ec7d1e79d95e3aaf40c3bfc7e36"),
         "trivy": ("0.74.0", "1caada5e0e2091909357c7525d3aa76f4b660b13821bc143b190c7483e31cc11")}
TYPES = {"debian": "deb", "ubuntu": "deb", "python-pkg": "python", "jar": "java-archive", "gobinary": "go-module"}
HISTORY = "studio-image-bundle-p-2026-10-11"
RECORDED_PROOF_SOURCE = "ed9ddcff74a6ba83685aec07b35695e8bb4ad820"
# These are the original campaign producers, not the current replay reducers.
RECORDED_PROOF_TOOLS = {
    "image_bootstrap_proof.py": "7a247e004897a14ae47f60da59a780dcd6785c716f18ef00d23b386495b5df95",
    "image_bundle_p_probe.py": "00f3672983d4b92a63f1af5670ee54cca30da6b7ba85609b3073de4d5d3f2106",
    "image_residual_inventory.py": "7630ea1f0698d934cec82dd23efadf160def4cef4eec4ef1657e0232a4e5bec5",
    "image_residual_native_probe.py": "86ec0da11bfefcb189e05af7512f5caba78381e573336341ce962d02ba834a60",
    "image_residual_report.py": "be52337b3018d4614c9130e8c0bcbaea2cc505102d85e4794c6aa4681a484179",
    "maven_image_build_run_proof.py": "aaec27eb581cd307d8ef79950546e1ec6543b92abfb0f4d1441f159082526b0f",
    "verify_image_oci.py": "e72a0fa47a28719dd548133643b6fd631b0211cd300ebd91a08d692b5275bc17",
}


def recorded_proof_tools() -> dict[str, str]:
    return dict(RECORDED_PROOF_TOOLS)


def sha(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def load(path: Path):
    return json.loads(path.read_bytes())


def encoded(value) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def stage_ledger(syft: dict, grype: dict, trivy: dict, surface: str) -> dict:
    config, index = _image_identity(syft, grype, trivy)
    database = grype.get("descriptor", {}).get("db", {}).get("status", {})
    if database.get("valid") is not True or not isinstance(database.get("built"), str):
        raise ValueError("Stage advisory database is invalid or unidentified")
    artifacts = syft.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("Missing complete stage inventory")
    by_id, catalog = {}, []
    for item in artifacts:
        if (not all(isinstance(item.get(key), str) and item[key] for key in ("id", "type", "name", "version"))
                or item["id"] in by_id or not item.get("locations")):
            raise ValueError("Malformed or duplicate inventory identity")
        key = (item["type"], item["name"], item["version"])
        by_id[item["id"]] = key
        metadata = item.get("metadata") or {}
        catalog.append({"id": item["id"], "type": key[0], "name": key[1], "version": key[2],
                        "paths": sorted({row["path"] for row in item["locations"]}),
                        "source_package": metadata.get("source") or item["name"],
                        "source_version": metadata.get("sourceVersion") or item["version"]})
    observations = []
    for status in ("active", "ignored"):
        field = "matches" if status == "active" else "ignoredMatches"
        matches = grype.get(field, [])
        if not isinstance(matches, list) or ((surface == "final" or field == "matches") and field not in grype):
            raise ValueError("Missing finding stream")
        for position, row in enumerate(matches):
            artifact, advisory = row["artifact"], row["vulnerability"]
            key = (artifact["type"], artifact["name"], artifact["version"])
            if by_id.get(artifact["id"]) != key:
                raise ValueError("Finding artifact differs from inventory")
            aliases = sorted({r["id"] for r in row.get("relatedVulnerabilities", [])})
            rules = [_ignore_rule(r) for r in row.get("appliedIgnoreRules", [])]
            if status == "ignored" and not rules:
                raise ValueError("Ignored observation lacks applied rules")
            observations.append({"stream": "grype_" + status, "source_index": position,
                                 "component": list(key), "advisory": advisory["id"], "aliases": aliases,
                                 "severity": advisory.get("severity") or "Unknown",
                                 "fix": advisory.get("fix") or {}, "rules": rules})
    results = trivy.get("Results")
    if not isinstance(results, list) or not results:
        raise ValueError("Missing stage Trivy results")
    for result_index, result in enumerate(results):
        kind = result.get("Type")
        packages, findings = result.get("Packages"), result.get("Vulnerabilities")
        packages = [] if packages is None else packages
        findings = [] if findings is None else findings
        if not isinstance(packages, list) or not isinstance(findings, list):
            raise ValueError("Malformed stage package/findings arrays")
        if kind not in TYPES and (packages or findings):
            raise ValueError("Unsupported result with inventory/findings: " + str(kind))
        if kind in {"debian", "ubuntu"}:
            actual = {(r["Name"], r["ID"].split("@", 1)[1]) for r in packages}
            expected = {(r["name"], r["version"]) for r in catalog if r["type"] == "deb"}
            if not expected or actual != expected:
                raise ValueError("Stage OS inventories disagree")
        if kind == "python-pkg":
            def canonical(name):
                return re.sub(r"[-_.]+", "-", name).lower()
            actual = {(canonical(r["Name"]), r["Version"]) for r in packages if r.get("AnalyzedBy") == "python-pkg"}
            expected = {(canonical(r["name"]), r["version"]) for r in catalog if r["type"] == "python"}
            if actual != expected:
                raise ValueError("Installed Python stage inventories disagree")
        if kind == "gobinary":
            target = result.get("Target")
            if not isinstance(target, str) or not target:
                raise ValueError("Missing Go binary target")
            def go_key(name, version):
                # Compare the two documented stdlib spellings without merging
                # their original source observations in the ledger.
                if name == "stdlib":
                    version = version.removeprefix("go").removeprefix("v")
                return name, version
            actual = {go_key(r["Name"], r["Version"]) for r in packages}
            expected = {go_key(r["name"], r["version"]) for r in catalog if r["type"] == "go-module"
                        and target.lstrip("/") in {p.lstrip("/") for p in r["paths"]}}
            if not expected or actual != expected:
                raise ValueError("Go binary inventories disagree")
        for position, row in enumerate(findings):
            key = [TYPES[kind], row["PkgName"], row["InstalledVersion"]]
            observations.append({"stream": "trivy_" + kind, "result_index": result_index, "source_index": position,
                                 "component": key, "advisory": row["VulnerabilityID"], "aliases": [],
                                 "vendor_ids": sorted(row.get("VendorIDs") or []),
                                 "severity": row.get("Severity") or "UNKNOWN",
                                 "fix": {"versions": [row["FixedVersion"]] if row.get("FixedVersion") else [],
                                         "state": row.get("Status") or "unknown"}, "rules": []})
    observed_types = {r["Type"] for r in results}
    if not observed_types & {"debian", "ubuntu"} or (any(r["type"] == "python" for r in catalog) and "python-pkg" not in observed_types):
        raise ValueError("Required inventory result missing")
    if surface in {"final", "maven"} and "jar" not in observed_types:
        raise ValueError("Required Maven/archive scanner result missing")
    go_targets = {path.lstrip("/") for row in catalog if row["type"] == "go-module" for path in row["paths"]}
    reported_go = {row["Target"].lstrip("/") for row in results if row.get("Type") == "gobinary"}
    if go_targets != reported_go:
        raise ValueError("Required Go binary coverage missing or unexpected")
    grouped = defaultdict(list)
    for position, row in enumerate(observations):
        grouped[(*row["component"], _advisory_identity(row["advisory"], row["aliases"]))].append(position)
    groups = [{"component": list(key[:3]), "advisory": key[3], "observation_indexes": positions,
               "state": "OPEN; artifact applicability not established"} for key, positions in sorted(grouped.items())]
    return {"surface": surface, "config_digest": config, "index_digest": index,
            "inventory": catalog, "observations": observations, "groups": groups,
            "stream_counts": dict(Counter(row["stream"] for row in observations)),
            "observed_result_types": sorted(observed_types),
            "qualification": "Exact source positions preserve observations. Go go/v version spellings and unmatched component identities remain separate; stages overlap and counts are not additive vulnerabilities."}


def stage_projection(ledgers: dict) -> dict:
    result = {"surface_identities": {}, "inventory": [], "observations": [], "groups": [],
              "final_observation_source": PREFIX + "-ledger.json"}
    for surface, ledger in ledgers.items():
        result["surface_identities"][surface] = {key: ledger[key] for key in (
            "index_digest", "config_digest", "stream_counts", "observed_result_types", "qualification")}
        for key in ("inventory", "observations", "groups"):
            if surface == "final" and key != "inventory":
                continue
            result[key].extend({"surface": surface, "local_index": index, **row} for index, row in enumerate(ledger[key]))
    return result


def copied_tree(stage: dict, final: dict, prefix: str) -> dict:
    expected = {p: row["sha256"] for p, row in stage["files"].items() if p.startswith(prefix + "/")}
    actual = {p: row["sha256"] for p, row in final["files"].items() if p.startswith(prefix + "/")}
    if not expected or expected != actual:
        raise ValueError("Copied stage bytes do not match final image: " + prefix)
    return {"prefix": prefix, "regular_files": len(expected),
            "file_map_sha256": hashlib.sha256(encoded(expected)).hexdigest(), "byte_equal": True}


def vendor_binding(filesystem: dict, wheel_path: Path, expected: str) -> dict:
    if sha(wheel_path) != expected:
        raise ValueError("Official pip wheel identity differs")
    root = "/usr/local/lib/python3.13/site-packages/"
    with zipfile.ZipFile(wheel_path) as wheel:
        members = {name: hashlib.sha256(wheel.read(name)).hexdigest() for name in wheel.namelist()
                   if name.startswith("pip/_vendor/") and not name.endswith("/")}
        actual = {name[len(root):]: row["sha256"] for name, row in filesystem["files"].items()
                  if name.startswith(root + "pip/_vendor/") and not name.endswith(".pyc")}
        if not members or members != actual:
            raise ValueError("Installed pip vendor tree differs from verified official wheel")
        declarations = wheel.read("pip/_vendor/vendor.txt").decode()
    seed = "/usr/local/lib/python3.13/ensurepip/_bundled/pip-26.2.1-py3-none-any.whl"
    wheels = {p for p in filesystem["archives"] if p.startswith("/usr/local/lib/python3.13/ensurepip/_bundled/")}
    if wheels != {seed} or filesystem["files"][seed]["sha256"] != expected:
        raise ValueError("Bootstrap archive differs or obsolete copies remain")
    versions = {match[1].lower(): match[2] for match in re.finditer(r"^\s*([\w-]+)==([^\s]+)", declarations, re.M)}
    return {"wheel_sha256": expected, "vendor_members": len(members), "active_and_seed_match_official": True,
            "vendor_map_sha256": hashlib.sha256(encoded(members)).hexdigest(), "versions": versions}


def version_affected(version: str, entry: dict) -> bool:
    candidate = Version(version)
    lower = Version(entry["version"])
    if candidate < lower:
        return False
    if "lessThan" in entry:
        return candidate < Version(entry["lessThan"])
    if "lessThanOrEqual" in entry:
        return candidate <= Version(entry["lessThanOrEqual"])
    return candidate == lower


def cpython_conclusion(cna: dict) -> str:
    rows = cna["affected"]
    if not rows or any(row.get("product") != "CPython" or row.get("defaultStatus") != "unaffected" for row in rows):
        raise ValueError("Unsupported CPython advisory range")
    versions = [r for row in rows for r in row["versions"]]
    if any(r.get("status") not in {"affected", "unaffected"} or r.get("changes") for r in versions):
        raise ValueError("Unsupported explicit CPython version status")
    affected = [r for r in versions if r["status"] == "affected"]
    if not affected:
        raise ValueError("Missing explicit affected ranges")
    candidate = Version("3.13.16")
    if any(version_affected(str(candidate), row) for row in affected):
        return "OPEN"
    explicit_unaffected = any(r["status"] == "unaffected" and version_affected(str(candidate), r) for r in versions)
    explicit_fix = any("lessThan" in r and Version(r["lessThan"]).release[:2] == candidate.release[:2]
                       and Version(r["version"]) < Version(r["lessThan"]) <= candidate for r in affected)
    return "supported-not-affected" if explicit_unaffected or explicit_fix else "OPEN"


def tempfile_review_evidence(root: Path, comparison: dict) -> dict:
    directory = root / "claude-followup/research"
    record = load(directory / "tempfile-upstream.json")
    source = (directory / "tempfile-v3.13.16.py").read_bytes()
    expected = comparison["stdlib_module_sha256"]["tempfile"]
    references = {r["url"].rsplit("/", 1)[1] for r in load(root / "research/CVE-2026-12345.json")["containers"]["cna"]["references"] if "/commit/" in r["url"]}
    if (record["advisory"] != "CVE-2026-12345" or record["release"]["sha"] != "cbc944f4bc59639a444dd971c737788ba2283a91"
            or record["source_sha256"] != expected or hashlib.sha256(source).hexdigest() != expected
            or any(marker in source for marker in (b"_rmtree_use_dir_fd", b"_resetperms_at"))
            or {r["reference_commit"] for r in record["comparisons"]} != references
            or any(r["base_commit"] != r["reference_commit"] or r["status"] not in {"behind", "diverged"}
                   or r["contained_in_release"] is not False for r in record["comparisons"])):
        raise ValueError("Tempfile release/source/patch evidence incomplete")
    for receipt in record["receipts"]:
        if sha(directory / receipt["file"]) != receipt["retained_projection_sha256"]:
            raise ValueError("Tempfile upstream projection changed")
    return record


def image_test_selection(root: Path, validation: dict) -> dict:
    nodes = load(root / "claude-followup/image-regression-nodeids.json")
    record = load(root / "claude-followup/image-regression-selection.json")
    counts = dict(sorted(Counter(node.split("::", 1)[0] for node in nodes).items()))
    executed = validation["full_retry"]
    if (not nodes or len(nodes) != len(set(nodes)) or any(not node.startswith("tests/") for node in nodes)
            or len(nodes) != executed["passed"] + executed["skipped"] + len(executed["failed"])
            or record["file_counts"] != counts or record["count"] != len(nodes)
            or record["nodeids_sha256"] != sha(root / "claude-followup/image-regression-nodeids.json")):
        raise ValueError("Image test selection does not reconcile with execution")
    return record


def tar_backport_evidence(root: Path, probe: dict, comparison: dict) -> dict:
    record = load(root / "research/cpython-156042.json")
    if (record["base"]["ref"] != "3.13" or record["number"] != 156042 or not record.get("merged_at")
            or record.get("merge_commit_sha") != "c7979f3a819011a3222bd16e671264b1e34282cb"):
        raise ValueError("Missing official 3.13 tar backport")
    with tarfile.open(root / "artifacts/Python-3.13.16.tar.xz") as archive:
        news = archive.extractfile("Python-3.13.16/Misc/NEWS").read()
        module = archive.extractfile("Python-3.13.16/Lib/tarfile.py").read()
    if (b"gh-155999" not in news or b"normalized = os.path.normpath(name)" not in module
            or hashlib.sha256(module).hexdigest() != comparison["stdlib_module_sha256"]["tarfile"]
            or probe["tar_directory_regression"] != {"member_extracted_inside": True, "outside_directory_created": False}):
        raise ValueError("Tar backport source/behavior proof incomplete")
    return {"advisory": "CVE-2026-19672", "issue": "gh-155999", "backport": record["html_url"],
            "merge_commit": record["merge_commit_sha"], "news_sha256": hashlib.sha256(news).hexdigest(),
            "module_sha256": hashlib.sha256(module).hexdigest(), "behavior": probe["tar_directory_regression"],
            "qualification": "Explicit PSF 3.13 backport, release NEWS, actual module bytes and regression override the retained broad CNA <3.16 range, not scanner silence."}


def bootstrap_conclusions(old: dict, root: Path, bound: dict, copies: dict) -> list[dict]:
    if not bound["active_and_seed_match_official"] or bound["vendor_members"] <= 0:
        raise ValueError("Unbound successor bootstrap code")
    versions = {name: [version] for name, version in bound["versions"].items()}
    versions.update(copies)
    result = []
    for index, inherited in enumerate(old["newly_encountered"]["items"]):
        ghsa = inherited["advisory_url"].rsplit("/", 1)[1]
        advisory = load(root / "research" / (ghsa + ".json"))
        identities = {row["value"] for row in advisory["identifiers"]}
        if inherited["id"] not in identities or advisory.get("withdrawn_at"):
            raise ValueError("Advisory identity changed/withdrawn; investigate")
        package = inherited["component"]
        ranges = [row["vulnerable_version_range"] for row in advisory["vulnerabilities"]
                  if row["package"]["ecosystem"] == "pip" and row["package"]["name"].lower() == package]
        if not ranges or package not in versions:
            raise ValueError("Missing successor/range evidence")
        affected = any(Version(version) in SpecifierSet(value) for value in ranges for version in versions[package])
        result.append({"historical_index": index, "id": inherited["id"], "component": package,
                       "historical_version": inherited["recorded_version"], "successor_versions": versions[package],
                       "ranges": ranges, "source": inherited["advisory_url"],
                       "state": "OPEN" if affected else "supported-not-affected",
                       "reason": "Successor active and seed vendor bytes match the verified official wheel; explicit advisory ranges evaluated. Old archive absence is not the sole evidence.",
                       "next_action": "Revalidate on seed/vendor/constraint changes; other advisories remain separate."})
    return result


def history_mapping(old: dict, new: dict) -> list[dict]:
    by_key = defaultdict(list)
    for index, group in enumerate(new["groups"]):
        c = new["components"][group["component"]]
        by_key[(c["type"], c["name"], group["advisory_identity"])].append(index)
    return [{"historical_group": index, "current_groups": by_key.get((
        old["components"][row["component"]]["type"], old["components"][row["component"]]["name"], row["advisory_identity"]), []),
        "qualification": "Version/count changes or absent observations are not remediation dispositions."}
        for index, row in enumerate(old["groups"])]


def family_queue(ledger: dict, catalog: list[dict], vendor: dict) -> list[dict]:
    indexed = {(row["type"], row["name"].lower(), row["version"]): row for row in catalog}
    families = {}
    for index, group in enumerate(ledger["groups"]):
        component = ledger["components"][group["component"]]
        artifact = indexed.get((component["type"], component["name"].lower(), component["version"]), {})
        source = artifact.get("source_package") or component["name"]
        family = "debian:" + source if component["type"] == "deb" else component["type"] + ":" + component["name"]
        row = families.setdefault(family, {"id": family, "components": {}, "groups": [], "vendor_status_counts": Counter(),
            "reported_fixed_versions": set(), "state": "OPEN; individual supported outcomes are recorded separately",
            "owner": "Studio image/security maintainer", "next_action": "Bind exact advisory functions/backports to installed/native/vendor copies and supported consumers; no scanner-ignore/no-fix acceptance."})
        row["components"][group["component"]] = {"name": component["name"], "version": component["version"],
                                                "inventory_status": component["inventory_status"]}
        row["groups"].append(index)
        if component["type"] == "deb":
            status = vendor.get(source, {}).get(group["advisory_identity"], {}).get("releases", {}).get("bookworm", {})
            row["vendor_status_counts"][status.get("status", "unknown")] += 1
            fixed = status.get("fixed_version")
            if fixed and fixed != "0":
                row["reported_fixed_versions"].add(fixed)
        if source in {"curl", "openssl", "gnutls28", "expat", "glibc", "sqlite3", "openldap", "krb5", "zlib"}:
            row["priority"] = 1
        elif source in {"linux", "gcc-12", "binutils"}:
            row["priority"] = 2
            row["next_action"] = "Separate installed user-space headers/compiler paths from absent host-kernel implementation; compile proof preserves capability but does not clear advisory applicability."
        else:
            row["priority"] = 2
    for row in families.values():
        row["components"] = [{"ledger_component": index, **component} for index, component in sorted(row["components"].items())]
        row["vendor_status_counts"] = dict(row["vendor_status_counts"])
        row["reported_fixed_versions"] = sorted(row["reported_fixed_versions"])
        row["qualification"] = "Bookworm status/fix metadata is current vendor evidence, not proof of installed-byte remediation or risk acceptance."
    return sorted(families.values(), key=lambda row: (row["priority"], row["id"]))


def pytest_summary(text: str) -> dict[str, int]:
    clean = re.sub(r"\x1b\[[0-9;]*m", "", text)
    summaries = []
    labels = r"passed|failed|skipped|error|errors|xfailed|xpassed|deselected|warning|warnings"
    for line in clean.splitlines():
        match = re.fullmatch(r"(\d+ (?:" + labels + r")(?:, \d+ (?:" + labels + r"))*) in \d+(?:\.\d+)?s(?: \([^\n]*\))?",
                             line.strip().strip("=").strip())
        if match:
            pairs = re.findall(r"(\d+) (" + labels + r")", match[1])
            if len({label for _, label in pairs}) != len(pairs):
                raise ValueError("Duplicate pytest summary counts")
            summaries.append({label: int(count) for count, label in pairs})
    if len(summaries) != 1:
        raise ValueError("Missing or ambiguous pytest execution summary")
    return summaries[0]


def single_test_pass(text: str, exit_code: int | None = None) -> bool:
    if type(exit_code) is not int or exit_code != 0:
        return False
    clean = re.sub(r"\x1b\[[0-9;]*m", "", text)
    if re.search(r"^(?:FAILED|ERROR|INTERNALERROR|INTERRUPTED)\b|KeyboardInterrupt|no tests ran|Traceback \(most recent call last\):", clean, re.M):
        return False
    return pytest_summary(clean) == {"passed": 1}


def validation_receipt(root: Path) -> dict:
    execution = load(root / "validation-commands-r2.json")
    commands = execution.get("commands")
    if (not isinstance(commands, list) or len(commands) != 2
            or {r.get("name") for r in commands} != {"launch-smoke", "fixture-policy"}
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", execution.get("image_index", ""))):
        raise ValueError("Required proof execution records missing/malformed")
    logs, status = {}, {}
    for record in commands:
        expected_log = {"launch-smoke": "image-launch-smoke-r2.log", "fixture-policy": "image-policy-fixture-r2.log"}[record["name"]]
        argv = record.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) and arg for arg in argv):
            raise ValueError("Malformed proof command arguments")
        try:
            started, finished = (datetime.fromisoformat(record[key]) for key in ("started_utc", "finished_utc"))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Malformed proof command timestamps") from error
        if started.tzinfo is None or finished.tzinfo is None or finished < started:
            raise ValueError("Unbound or reversed proof command timestamps")
        if (record.get("log") != expected_log or sha(root / expected_log) != record.get("log_sha256")
                or type(record.get("exit_code")) is not int or record["exit_code"] != 0
                ):
            raise ValueError("Required proof command failed or its log is unbound")
        logs[record["name"]] = (root / expected_log).read_text()
        status[record["name"]] = record["exit_code"]
    smoke, policy = logs["launch-smoke"], logs["fixture-policy"]
    regression = (root / "image-regressions-retry.log").read_text()
    expected = {"tests/test_dependency_audit_policy.py::test_supported_bootstrap_paths_pin_and_verify_the_packaging_toolchain",
        "tests/test_dom_xss.py::test_one_audited_encoder_owns_text_and_quoted_attribute_encoding",
        "tests/test_dom_xss.py::test_hostile_saved_kafka_project_cannot_break_out_of_card_markup",
        "tests/test_dom_xss.py::test_hostile_openapi_descriptor_cannot_break_passthrough_markup",
        "tests/test_dom_xss.py::test_hostile_operation_name_completes_step3_sample_and_mapping_collection"}
    failures = {line.removeprefix("FAILED ").split(" - ", 1)[0] for line in regression.splitlines() if line.startswith("FAILED ")}
    if (not single_test_pass(smoke, status["launch-smoke"]) or not single_test_pass(policy, status["fixture-policy"])
            or failures != expected or "Stored-XSS markup tests require Node" not in regression
            or "CONTRIBUTING.md" not in regression or "FileNotFoundError" not in regression):
        raise ValueError("Required image proof failed or unexpected regression was hidden")
    counts = pytest_summary(regression)
    if (counts.get("passed", 0) <= 0 or counts.get("skipped", 0) <= 0
            or counts.get("failed") != len(expected) or set(counts) != {"passed", "skipped", "failed"}):
        raise ValueError("Image regressions did not execute")
    return {"image_index": execution["image_index"],
            "proof_commands": [{key: r[key] for key in ("name", "exit_code", "log", "log_sha256", "started_utc", "finished_utc")} for r in commands],
            "launch_smoke": "1 passed", "full_retry": {"passed": counts["passed"], "skipped": counts["skipped"],
             "failed": sorted(failures)}, "affected_documentation_fixture_test": "1 passed after copying available CONTRIBUTING fixture",
            "qualification": "Full retry was not all-green. The affected policy assertion separately passed; four Node-dependent cases require host/CI and are not image passes. All failed attempts retained."}


def historical_native_conclusions(evidence: Path, root: Path, filesystem: dict, ledger: dict) -> dict:
    files = filesystem["files"]
    curl_identity = load(evidence / "studio-image-curl-identities.json")
    curl_ledger = load(evidence / "studio-image-curl-ledger.json")
    equal = all(files.get(path, {}).get("sha256") == value for path, value in curl_identity["feature_proof"]["artifact_sha256"].items())
    feed = {row["id"]: row for row in load(root / "research/curl-vuln.json")}
    historical_advisories = {row["id"]: row for row in curl_ledger["advisories"]}
    curl = []
    for position, group in enumerate(curl_ledger["groups"]):
        if group["classification"] != "supported-not-affected":
            continue
        old = historical_advisories[group["advisory_identity"]]
        current = feed.get(old["upstream_id"], {})
        ranges = [item for row in current.get("affected", []) for item in row.get("ranges", []) if item["type"] == "SEMVER"]
        supported = equal and ranges == old["upstream_semver_ranges"]
        component = curl_ledger["components"][group["component"]]
        curl.append({"historical_group": position, "component": component, "id": group["advisory_identity"],
                     "state": "supported-not-affected" if supported else "OPEN",
                     "reason": group["rationale"] if supported else "Artifact or vendor ranges changed; prior exclusion cannot be carried without review.",
                     "source": old["upstream_reference"]})
    prior_identity = load(evidence / "studio-image-refresh-2026-10-04-identities.json")
    prior_delta = load(evidence / "studio-image-refresh-2026-10-04-delta.json")
    library = prior_identity["expat_official_binary_comparison"]["libraries"][0]
    package = (root / "research/libexpat1-u4-amd64.deb").read_bytes()
    if hashlib.sha256(package).hexdigest() != "ed010cc41577d75ab01cccc6afa93496d9a99f1e16bd469caf58e1b81fddae80" or not package.startswith(b"!<arch>\n"):
        raise ValueError("Official Expat package identity differs")
    position, payload = 8, None
    while position < len(package):
        header = package[position:position + 60]
        if len(header) != 60 or header[58:] != b"`\n":
            raise ValueError("Malformed Debian archive")
        size = int(header[48:58].strip())
        name = header[:16].strip().rstrip(b"/")
        if name == b"data.tar.xz":
            if payload is not None:
                raise ValueError("Duplicate package data archive")
            payload = package[position + 60:position + 60 + size]
        position += 60 + size + size % 2
    if payload is None:
        raise ValueError("Missing package data archive")
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:xz") as archive:
        members = [m for m in archive.getmembers() if m.isfile() and m.name.endswith("/libexpat.so.1.8.10")]
        if len(members) != 1 or hashlib.sha256(archive.extractfile(members[0]).read()).hexdigest() != library["official_package_library_sha256"]:
            raise ValueError("Official Expat library bytes differ")
    actual = files.get(library["image_path"], files.get(library["image_path"].replace("/lib/", "/usr/lib/", 1), {}))
    binary_equal = actual.get("sha256") == library["official_package_library_sha256"]
    vendor = load(root / "research/debian-tracker.json")
    expat = []
    for old in prior_delta["expat_reconciliation"]:
        current = vendor.get("expat", {}).get(old["advisory_id"], {}).get("releases", {}).get("bookworm", {})
        supported = (binary_equal and old["classification"] == "supported-fixed"
                     and current.get("status") == "resolved" and current.get("fixed_version") == "2.5.0-1+deb12u4")
        expat.append({"id": old["advisory_id"], "component": "system libexpat1 2.5.0-1+deb12u4",
                      "state": "remediated (prior official backport, unchanged bytes)" if supported else "OPEN",
                      "vendor_bookworm": current, "reason": "Actual library matches previously verified official package bytes and current exact vendor backport identity." if supported else
                      "No automatic no-DSA/postponed/scanner-silence exclusion; affected function/compile option needs proof.",
                      "source": "https://security-tracker.debian.org/tracker/" + old["advisory_id"]})
    return {"curl_prior_exclusions": curl, "curl_artifact_bytes_equal": equal,
            "system_expat": expat, "system_expat_official_bytes_equal": binary_equal,
            "qualification": "Prior supported evidence is preserved only at matching artifact/vendor identities; no new correction credit or embedded Expat clearance. All scanner observations remain present."}


def required_inputs(previous: dict) -> set[str]:
    names = {"studio-source.tar", "engine.tar", "build-metadata.json", "runtime-probe.json",
             "offline-proof-container.json", "bootstrap-offline-verified.json", "buildrun/result.json",
             "scanner-reuse-verified.json", "frozen-db-sha256.json", "campaign-scan-result.json",
             "artifacts/Python-3.13.16.tar.xz", "wheelhouse/pip-26.2.1-py3-none-any.whl",
             "research/receipts.json", "research/debian-tracker.json", "research/curl-vuln.json",
             "research/pip-candidate-inspection.json", "image-regressions.log", "image-regressions-retry.log",
             "image-launch-smoke.log", "image-policy-fixture-final.log", "buildrun-attempt-1/verify.log",
             "wheelhouse/setuptools-83.0.0-py3-none-any.whl", "wheelhouse/wheel-0.48.0-py3-none-any.whl",
             "research/cpython-156042.json", "native-probe.json", "research/libexpat1-u4-amd64.deb"}
    names.update({"validation-commands-r2.json", "image-launch-smoke-r2.log", "image-policy-fixture-r2.log", "repair_r2_execute.py"})
    names.update({"claude-followup/research/tempfile-upstream.json", "claude-followup/research/tempfile-v3.13.16.py",
                  "claude-followup/image-regression-nodeids.json", "claude-followup/image-regression-selection.json"})
    names.update(f"claude-followup/research/upstream-{number:02d}.json" for number in range(1, 10))
    names.update({"campaign-commands.json", "trivy-cache/db/metadata.json", "trivy-cache/java-db/metadata.json",
                  "bases/selected.json", "bases/receipts.json", "jdk21-build-metadata.json", "maven-build-metadata.json"})
    for surface in SURFACES:
        names.update({surface + suffix for suffix in ("-image.tar", "-filesystem.tar", "-filesystem.json", "-inspect.json", "-export-container.json")})
        names.update(f"{surface}-1-{name}.json" for name in ("syft", "grype", "trivy"))
    names.update(f"final-2-{name}.json" for name in ("syft", "grype", "trivy"))
    names.update({"grype-db/6/vulnerability.db", "trivy-cache/db/trivy.db", "trivy-cache/java-db/trivy-java.db"})
    names.update("research/" + key + ".json" for key in previous["scope"] if key.startswith("CVE-"))
    names.update("research/" + row["advisory_url"].rsplit("/", 1)[1] + ".json" for row in previous["newly_encountered"]["items"])
    return names


def installed_tool_copies(filesystem: dict, root: Path) -> dict:
    names = {"pip": {"26.2.1"}, "setuptools": {"70.3.0"}, "wheel": set()}
    for name, version, expected in (
        ("setuptools", "83.0.0", "29b23c360f22f414dc7336bb39178cc7bcbf6021ed2733cde173f09dba19abb3"),
        ("wheel", "0.48.0", "3217dcc807155e45db462d7ef2431f5ddda0d7273b700d05a67b271ceb1287ab"),
    ):
        path = root / "wheelhouse" / f"{name}-{version}-py3-none-any.whl"
        if sha(path) != expected:
            raise ValueError("Approved installed tool artifact hash differs")
        with zipfile.ZipFile(path) as archive:
            matched = 0
            for member in archive.namelist():
                if member.startswith(name + "/") and not member.endswith("/"):
                    target = "/usr/local/lib/python3.13/site-packages/" + member
                    if filesystem["files"].get(target, {}).get("sha256") != hashlib.sha256(archive.read(member)).hexdigest():
                        raise ValueError("Installed tool/vendor bytes differ: " + member)
                    matched += 1
            if not matched:
                raise ValueError("Empty official tool copy comparison")
        names[name].add(version)
    # This private wheel is inspected inside the verified full setuptools wheel,
    # not silently replaced by the active wheel distribution's version.
    private = "/usr/local/lib/python3.13/site-packages/setuptools/_vendor/wheel-0.46.3.dist-info/METADATA"
    if private not in filesystem["files"]:
        raise ValueError("Missing expected private wheel copy")
    names["wheel"].add("0.46.3")
    return {name: sorted(versions) for name, versions in names.items()}


def verified_scanners(root: Path) -> dict:
    receipt = load(root / "scanner-reuse-verified.json")
    rows = receipt.get("tools")
    if not isinstance(rows, list) or {row["name"] for row in rows} != set(TOOLS) or len(rows) != len(TOOLS):
        raise ValueError("Missing or substituted scanner/tool provenance")
    for row in rows:
        version, expected = TOOLS[row["name"]]
        archive = root / "tools" / row["archive"]
        if row["version"] != version or row["archive_sha256"] != expected or sha(archive) != expected:
            raise ValueError("Approved scanner archive differs")
        with tarfile.open(archive) as package:
            executable = hashlib.sha256(package.extractfile(row["name"]).read()).hexdigest()
        if executable != row["executable_sha256"] or executable != sha(root / "tools" / row["name"]):
            raise ValueError("Scanner executable differs from verified archive")
    return receipt


def source_binding(path: Path, expected_commit: str, prefix: str, installed: dict, destination: str) -> dict:
    with tarfile.open(path) as archive:
        if archive.pax_headers.get("comment") != expected_commit:
            raise ValueError("Source archive commit differs")
        hashes = {}
        for member in archive.getmembers():
            if member.isfile() and member.name.startswith(prefix + "/"):
                data = archive.extractfile(member).read()
                target = destination + "/" + member.name
                if installed["files"].get(target, {}).get("sha256") != hashlib.sha256(data).hexdigest():
                    raise ValueError("Packaged source differs: " + member.name)
                hashes[member.name] = hashlib.sha256(data).hexdigest()
    if not hashes:
        raise ValueError("Empty packaged source comparison")
    return {"commit": expected_commit, "archive_sha256": sha(path), "matched_files": len(hashes),
            "file_map_sha256": hashlib.sha256(encoded(hashes)).hexdigest()}


def recipe_inputs(root: Path) -> dict:
    names = ("Dockerfile", "constraints.txt", "requirements.txt", "scripts/install_apache_maven.py",
             "scripts/verify-packaging-toolchain.py")
    with tarfile.open(root / "studio-source.tar") as archive:
        hashes = {name: hashlib.sha256(archive.extractfile(name).read()).hexdigest() for name in names}
    with tarfile.open(root / "final-filesystem.tar") as archive:
        sources = archive.extractfile("etc/apt/sources.list.d/debian.sources").read().decode()
    return {"source_file_sha256": hashes, "build_arguments": {"APP_UID": 1000, "APP_GID": 1000},
            "apt_sources": sources,
            "apt_resolution_limit": "Official live repositories; recipe removes package lists. InRelease/index bytes were not retained, so digest pins do not freeze APT resolution."}


def build(root: Path, evidence: Path, replay_filesystems: bool = False) -> dict:
    previous = load(evidence / "studio-image-runtime-2026-10-08-inputs.json")
    inputs = load(root / "campaign-inputs.json")
    if inputs["studio"] != STUDIO or inputs["engine"] != ENGINE or set(inputs["images"]) != set(SURFACES):
        raise ValueError("Unexpected campaign source/stage scope")
    if not required_inputs(previous) <= inputs["sha256"].keys():
        raise ValueError("Required campaign hash coverage incomplete")
    for name, expected in inputs["sha256"].items():
        if sha(root / name) != expected:
            raise ValueError("Missing or changed required input: " + name)
    surfaces, filesystems, ledgers = {}, {}, {}
    for surface in SURFACES:
        oci = verify(root / (surface + "-image.tar"), inputs["images"][surface])
        if surface == "final" and oci["config_user"] != "appuser":
            raise ValueError("Final image must retain its non-root appuser default")
        s, g, t = [load(root / f"{surface}-1-{name}.json") for name in ("syft", "grype", "trivy")]
        stage = stage_ledger(s, g, t, surface)
        if stage["config_digest"] != oci["config_digest"] or stage["index_digest"] != oci["index_digest"]:
            raise ValueError("Scanner and actual OCI identity differ")
        fs = load(root / (surface + "-filesystem.json"))
        exported = load(root / (surface + "-export-container.json"))[0]
        if exported["Image"] != oci["index_digest"] or exported["Mounts"] or exported["State"]["Running"]:
            raise ValueError("Filesystem export container image/mount/state differs")
        if replay_filesystems and inventory(root / (surface + "-filesystem.tar")) != fs:
            raise ValueError("Filesystem projection differs from exported bytes")
        if not fs["files"] or not fs["native"] or not fs["archives"]:
            raise ValueError("Missing required native/archive coverage")
        filesystems[surface] = fs
        ledgers[surface] = stage
        surfaces[surface] = {"image": oci, "stream_counts": stage["stream_counts"],
            "inventory_counts": dict(Counter(row["type"] for row in stage["inventory"])),
            "regular_file_count": len(fs["files"]), "native_files": fs["native"], "archives": fs["archives"],
            "scope": "shipped final image" if surface == "final" else "whole named build-stage snapshot, not all transient processes"}
    first = [load(root / f"final-1-{name}.json") for name in ("syft", "grype", "trivy")]
    second = [load(root / f"final-2-{name}.json") for name in ("syft", "grype", "trivy")]
    summary, final_ledger = summarize(*first), normalize(*first)
    if summary != summarize(*second) or final_ledger != normalize(*second) or first[0]["artifacts"] != second[0]["artifacts"]:
        raise ValueError("Repeated final-image inventory/findings differ")
    copied = {"jdk": copied_tree(filesystems["jdk21"], filesystems["final"], "/opt/java/openjdk"),
              "maven": copied_tree(filesystems["maven"], filesystems["final"], "/opt/maven")}
    for row in final_ledger["observations"]:
        if row["source"].startswith("trivy_"):
            original = first[2]["Results"][row["result_index"]]["Vulnerabilities"][row["source_index"]]
            row["vendor_ids"] = sorted(original.get("VendorIDs") or [])
    wheel = root / "wheelhouse/pip-26.2.1-py3-none-any.whl"
    pip_sha = "71138adf1f4ca900cdb7d289c21b7494329f2332b6d85f0e1c42108c0384ed3e"
    bindings = {surface: vendor_binding(filesystems[surface], wheel, pip_sha) for surface in ("final", "maven")}
    probe = load(root / "runtime-probe.json")
    if (not probe["python"].startswith("3.13.16 ") or probe["copy_search_errors"]
            or probe["distributions"] != {"pip": "26.2.1", "setuptools": "83.0.0", "wheel": "0.48.0"}):
        raise ValueError("Runtime/toolchain proof differs from approved artifact")
    for row in probe["modules"].values():
        if "path" in row and filesystems["final"]["files"].get(row["path"], {}).get("sha256") != row["sha256"]:
            raise ValueError("Runtime probe module differs from exported image bytes")
    comparison = official_comparison(probe, root / "artifacts/Python-3.13.16.tar.xz", previous)
    observed_jdk = {"/opt/java/openjdk/" + name: row["sha256"] for name, row in probe["jdk_files"].items() if "sha256" in row}
    exported_jdk = {name: row["sha256"] for name, row in filesystems["final"]["files"].items() if name.startswith("/opt/java/openjdk/")}
    if observed_jdk != exported_jdk or probe["pip_check"].get("exit_code") != 0:
        raise ValueError("JDK/runtime installation proof differs from actual exported bytes")
    tar_backport = tar_backport_evidence(root, probe, comparison)
    tempfile_review = tempfile_review_evidence(root, comparison)
    bootstrap, run = load(root / "bootstrap-offline-verified.json"), load(root / "buildrun/result.json")
    validate_proofs(bootstrap, run)
    if run["jobless"] or probe["uid"] != 1000 or probe["pointer_bits"] != 64:
        raise ValueError("Declared full-fixture/non-root/AMD64 proof differs")
    offline = load(root / "offline-proof-container.json")[0]
    if offline["Image"] != inputs["images"]["final"] or offline["Mounts"] or offline["NetworkSettings"]["Networks"]:
        raise ValueError("Offline mount-free proof identity differs")
    dbs = load(root / "frozen-db-sha256.json")
    scan_receipt = load(root / "campaign-scan-result.json")
    if scan_receipt.get("result") != "pass" or scan_receipt.get("db_hashes_unchanged") != dbs:
        raise ValueError("Advisory database freeze proof incomplete")
    if any(inputs["sha256"].get(name) != value for name, value in dbs.items()):
        raise ValueError("Advisory database hashes differ")
    sources = {"studio": source_binding(root / "studio-source.tar", STUDIO, "app", filesystems["final"], "/workspace/EdgeForgeStudio"),
               "engine": source_binding(root / "engine.tar", ENGINE, "appbuilder", filesystems["final"], "/opt/EdgeForgeRuntime")}
    for row in load(root / "research/receipts.json"):
        if "error" not in row and inputs["sha256"].get("research/" + row["file"]) != row["sha256"]:
            raise ValueError("Vendor receipt bytes differ")
    prior_delta = load(evidence / (HISTORY + "-delta.json"))
    rows = []
    carry = {"CVE-2026-3479", "CVE-2026-15310", "CVE-2026-15806", "CVE-2026-17084",
             "CVE-2026-19672", "CVE-2026-82049", "CVE-2026-87910", "CVE-2026-12345"}
    for old in prior_delta["scoped_findings"]:
        row = {"id": old["id"], "historical_state": old["state"], "state": old["state"], "reason": old["reason"],
               "next_action": old["next_action"], "sources": old["sources"]}
        if row["id"] in carry:
            cna = load(root / "research" / (row["id"] + ".json"))["containers"]["cna"]
            row["state"] = cpython_conclusion(cna)
            row["reason"] = ("PSF explicit current affected ranges evaluated against 3.13.16; all eleven installed stdlib modules match the approved source archive. "
                             + ("Explicit 3.13 correction boundary excludes the candidate; no new artifact-change credit." if row["state"] != "OPEN" else
                                "Candidate is affected or the record omits an explicit 3.13 correction; omission/default status is not clearance."))
            row["sources"] = ["https://cveawg.mitre.org/api/cve/" + row["id"]]
            if row["id"] == "CVE-2026-19672":
                row["state"] = "supported-not-affected"
                row["reason"] = tar_backport["qualification"]
                row["sources"].append(tar_backport["backport"])
            if row["id"] == "CVE-2026-12345":
                row["state"] = "OPEN"
                row["reason"] = "The CNA omits 3.13. None of its five patch/revert references is contained in the exact v3.13.16 release; installed tempfile.py matches that unpatched source and lacks _rmtree_use_dir_fd/_resetperms_at. The 3.12 backport was reverted. Bounded symlink-probe success is context, not clearance."
                row["sources"] += [tempfile_review["source_url"], "https://github.com/python/cpython/pull/158528"]
                row["next_action"] = "Studio/security owner: obtain a supported 3.13 correction or complete caller/cleanup applicability evidence; no omitted-branch or bounded-probe clearance."
            if row["state"] == "supported-not-affected":
                row["next_action"] = "Revalidate exact runtime/module bytes and advisory/backport evidence on any material change or final release pairing."
        rows.append(row)
    tool_copies = installed_tool_copies(filesystems["final"], root)
    for item in ledgers["final"]["inventory"]:
        if item["type"] == "python" and item["name"].lower() in bindings["final"]["versions"]:
            name = item["name"].lower()
            tool_copies[name] = sorted(set(tool_copies.get(name, []) + [item["version"], bindings["final"]["versions"][name]]))
    successor = bootstrap_conclusions(previous, root, bindings["final"], tool_copies)
    old_ledger = load(evidence / (HISTORY + "-ledger.json"))
    outcome = {"scoped": rows, "scoped_counts": dict(Counter(row["state"] for row in rows)),
               "successor_bootstrap": successor, "bootstrap_counts": dict(Counter(row["state"] for row in successor)),
               "historical_to_current": history_mapping(old_ledger, final_ledger),
               "qualification": "Overlapping sets, not additive vulnerabilities. No risk accepted; historical evidence unchanged.",
               "new_expat": {"id": "CVE-2026-77214", "state": "OPEN", "scope": "system and embedded copies",
                             "next_action": "Bind each XML_ParseBuffer consumer and buffer-length guarantee or verify a compatible vendor correction; wrapper checks are not whole-image clearance."}}
    outcome["historical_native"] = historical_native_conclusions(evidence, root, filesystems["final"], final_ledger)
    native = load(root / "native-probe.json")
    validation = validation_receipt(root)
    validation["selection"] = image_test_selection(root, validation)
    if validation["image_index"] != inputs["images"]["final"]:
        raise ValueError("Required proof execution targets a different image")
    if native["uid"] != 1000 or not native["native_extensions"] or "pointer=8" not in native["compiler_header_proof"]:
        raise ValueError("Native/compiler proof incomplete")
    for path, row in native["native_extensions"].items():
        if filesystems["final"]["files"].get(path, {}).get("sha256") != row["sha256"]:
            raise ValueError("Native probe differs from image bytes")
        row["ldd"] = re.sub(r"0x[0-9a-f]+", "<address>", row["ldd"])
    native["git_https_linkage"] = re.sub(r"0x[0-9a-f]+", "<address>", native["git_https_linkage"])
    queue = {"current_families": family_queue(final_ledger, ledgers["final"]["inventory"], load(root / "research/debian-tracker.json")),
             "inherited_family_decisions": load(evidence / "studio-image-refresh-2026-10-04-ledger.json")["decisions"],
             "historical_qualification": "Original 103 family decisions are immutable historical rationale, not current 3.13 claims; current artifacts/questions above govern this campaign.",
             "stage_followups": {surface: {"state": "OPEN", "groups": len(ledgers[surface]["groups"]),
                  "next_action": "Image owner: evaluate exact stage OS/native/bootstrap and JDK-stage pebble/Go identities; distinguish stage-only bytes from the verified copied subsets. No stage risk accepted."} for surface in ("jdk21", "maven")}}
    queue["identified_embedded_native"] = [
        {"component": component, "observed_version": version, "state": "OPEN; separate native advisory coverage not established",
         "owner": "Studio image/security maintainer", "next_action": "Bind exact embedded library/build options to vendor advisories; standalone OS/Python package absence or a zero scanner match is not clearance."}
        for component, version in (("cryptography private OpenSSL", native["cryptography_private_openssl"]),
                                   ("lxml private libxml2", native["lxml_private_libxml"]),
                                   ("lxml private libxslt", native["lxml_private_libxslt"]),
                                   ("Pillow native features", native["pillow_native_features"]),
                                   ("PDFium", native["pdfium_runtime"]))]
    receipt = {"candidate": "EF-V5-M2-STUDIO-RESIDUAL-PROOF-S1", "revision": 1, "studio": STUDIO, "engine": ENGINE,
               "pairing": "provisional assessment input; final Suite selection/rebuild remains required",
               "input_sha256": inputs["sha256"], "packaged_sources": sources, "tools": verified_scanners(root),
               "base_materials": load(root / "bases/selected.json"), "recipe_inputs": recipe_inputs(root),
               "build_base_provenance": load(root / "build-metadata.json")["buildx.build.provenance"]["materials"],
               "database_metadata": {"grype": {key: value for key, value in first[1]["descriptor"]["db"]["status"].items() if key != "path"},
                                     "trivy": load(root / "trivy-cache/db/metadata.json"),
                                     "java": load(root / "trivy-cache/java-db/metadata.json")},
               "observation_times": [{key: row[key] for key in ("name", "started_utc", "finished_utc", "exit_code")}
                                     for row in load(root / "campaign-commands.json")],
               "campaign_manifest_sha256": sha(root / "campaign-inputs.json"),
               "proof_tool_sha256": recorded_proof_tools(),
               "recorded_proof_tool_source": RECORDED_PROOF_SOURCE,
               "proof_tool_identity_scope": "Original campaign producer snapshots, not the current replay reducer. Current correction/replay implementation is identified by the exact reviewed PR head.",
               "reduction_policy_revision": 2,
               "observed_versions": {"python": probe["python"], "packaging": probe["distributions"],
                                      "embedded_expat": probe["embedded_expat"], "system_expat": probe["system_expat"]["stdout"],
                                      "java": probe["jdk_release"]},
               "databases": load(root / "frozen-db-sha256.json"), "scan_receipt": load(root / "campaign-scan-result.json"),
               "surfaces": surfaces, "copied_subsets": copied, "pip_bindings": bindings, "tool_copies": tool_copies,
               "official_comparison": comparison, "tar_backport": tar_backport, "tempfile_review": tempfile_review,
               "runtime_probe_sha256": sha(root / "runtime-probe.json"), "native_consumers": native,
               "bootstrap": bootstrap, "build_run": run, "research": load(root / "research/receipts.json"),
               "image_validation": validation,
               "repeat": "Both final rounds have identical complete inventory, reduced summary and normalized ledger",
               "coverage_exclusions": [
                   {"surface": "transient upstream/native builds", "reason": "Final/stage snapshots cannot observe every removed compiler, APT/PyPI extraction or upstream build process",
                    "next_decision": "Image owner: retain signed-repository/checksum/build logs and installer source; separately authorize transient instrumentation if required by selected-release policy."},
                   {"surface": "opaque/static/shaded native identities", "reason": "All ELF/PE and nested archive paths/hashes retained; not every statically embedded code version is detectable",
                    "next_decision": "Image/security owner: investigate exact unmatched native/component families before clearance; no scanner-silence exclusion."},
                   {"surface": "other platforms, host kernel, later downloaded Maven plugins/generated-app images", "reason": "Outside this declared AMD64 Studio/stage campaign",
                    "next_decision": "Owning release/Engine/operator lane: assess applicable selected-pair artifacts; no full L5 or generated-image claim."}],
               "font_rendering": "Unavailable by default; no restoration or compatibility waiver",
               "risk_accepted": False, "m2_cleared": False}
    return {"receipt": receipt, "summary": summary, "ledger": final_ledger, "stages": stage_projection(ledgers), "outcomes": outcome, "queue": queue}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retained", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, default=Path("docs/handover-evidence"))
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--replay-filesystems", action="store_true")
    args = parser.parse_args()
    outputs = build(args.retained, args.evidence_dir, args.replay_filesystems)
    for name, value in outputs.items():
        path = args.evidence_dir / (PREFIX + "-" + name + ".json")
        if args.check:
            if load(path) != value:
                raise ValueError("Committed output differs: " + name)
        elif name in {"ledger", "stages", "queue"}:
            write_ledger(path, value)
        else:
            path.write_bytes(encoded(value))


if __name__ == "__main__":
    main()
