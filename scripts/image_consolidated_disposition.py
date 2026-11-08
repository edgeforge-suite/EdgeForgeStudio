"""Reconcile local frozen image evidence into a lossless, open decision package."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.image_findings_ledger import normalize, write_ledger

OWNER = "Studio maintainer; adopter security owner owns any exposure/risk decision"
CUTOFF = "2026-10-01T16:30:29Z"
RUNTIME_SOURCES = {
    "curl", "openssl", "expat", "sqlite3", "gnutls28", "libtasn1-6", "krb5",
    "openldap", "nghttp2", "zlib", "pcre2", "glibc", "pam", "libgcrypt20", "p11-kit",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_retained(root: Path, identity: dict[str, Any]) -> None:
    """Missing/changed reports, tools or DBs invalidate reuse, never mean clean."""
    for name, record in identity["retention"]["raw_files"].items():
        if sha256(root / name) != record["sha256"]:
            raise ValueError(f"retained hash mismatch: {name}")
    for name, record in identity["scanners"].items():
        for path, digest in (
            (record["archive"], record["archive_sha256"]),
            (name, record["executable_sha256"]),
        ):
            if sha256(root / "tools" / path) != digest:
                raise ValueError(f"retained tool mismatch: {path}")
        checksum_files = list((root / "tools").glob(f"{name}_*_checksums.txt"))
        if len(checksum_files) != 1 or sha256(checksum_files[0]) != record["checksums_sha256"]:
            raise ValueError(f"retained checksum list mismatch: {name}")
    for name, path in (
        ("grype", "grype-db/6/vulnerability.db"),
        ("trivy", "trivy-cache/db/trivy.db"),
        ("trivy_java", "trivy-cache/java-db/trivy-java.db"),
    ):
        if sha256(root / path) != identity["databases"][name]["sha256"]:
            raise ValueError(f"retained database mismatch: {name}")


def decision(kind: str, name: str, source: str = "") -> dict[str, Any]:
    """Family reasoning supplies an explicit open decision, not a suppression."""
    sources = ["studio-image-consolidated-disposition.md"]
    if kind == "deb":
        family = f"os:{source or name}"
        priority = 1 if source in RUNTIME_SOURCES else (2 if source == "linux" else 3)
        sources += [f"https://security-tracker.debian.org/tracker/source-package/{source or name}",
                    "retained:debian-tracker.json"]
        rationale = (
            "Installed final-image binary/source family; runtime libraries and tools remain shipped. "
            "Neither build orientation nor vendor no-dsa/postponed/wont-fix is non-applicability. "
            "Frozen Bookworm status is attached per matched advisory; missing entries remain unknown."
        )
        question = (
            f"For {source or name}, verify each open group against its exact binary and Bookworm "
            "backport, choose a verified same-Bookworm fix if available, or commission "
            "advisory-specific consumer proof. If only a distribution/removal transition suffices, "
            "approve the separately gated compatibility plan, not risk acceptance."
        )
        if source == "linux":
            rationale += (
                " linux-libc-dev is userspace build headers, not a container kernel. Grype's "
                "default exact-indirect-match rule does not clear header or compiled-product effects."
            )
            question = (
                "Review all retained linux-libc-dev groups for header/compiled-product applicability "
                "and decide whether a separately proved development-header removal preserves "
                "supported native builds; obtain host-kernel evidence separately."
            )
        if source == "expat":
            rationale += (
                " Ten frozen groups list Bookworm 2.5.0-1+deb12u4 as fixed, while the artifact "
                "has u3. This is an unapplied compatible-backport candidate, not a no-fix finding; "
                "CPython's separately embedded Expat is not the Debian library."
            )
            question = (
                "Verify the official AMD64 libexpat1 2.5.0-1+deb12u4 package and affected library "
                "replacement, then schedule one fresh same-recipe artifact (APT upgrade already "
                "exists) or a justified minimal pin. Compare under this frozen snapshot and rerun "
                "native/startup/Build & Run proof before closing the ten fixed-version groups. "
                "Five other Expat groups remain open independently."
            )
        trigger = "Changed Bookworm candidate/backport, affected-range correction, consumer/build use, or final release pair"
    elif kind == "python-unresolved":
        family, priority = f"embedded-python:{name}", 1
        sources += ["studio-image-triage.md", "retained:trivy.json", "retained:runtime-inspection.json"]
        rationale = (
            "Imported-SBOM identity is unresolved as a standalone distribution. Pip vendor code "
            "and alternate copies must be bound to the exact advisory surface; installed-version "
            "audit and absence of dist-info cannot clear embedded code. Historical fallback/subset "
            "leads are not supported-not-affected conclusions."
        )
        question = (
            f"For {name}, bind the imported version/advisories to every installed or vendored copy "
            "and affected function. Select a checksum-verified Python-3.11-compatible pip/vendor "
            "release only after its wheel actually replaces the affected content; otherwise retain "
            "unknown applicability and request focused reachability proof."
        )
        trigger = "New pip/vendor wheel, revised imported SBOM/advisory, alternative copy, or final release pair"
    elif kind == "binary" and name == "python":
        family, priority = "cpython", 1
        sources += ["studio-image-triage.md", "https://www.python.org/downloads/release/python-31116/",
                    "retained:grype.json", "retained:runtime-inspection.json"]
        rationale = (
            "CPython 3.11.16 and dynamically linked native libraries ship in runtime parsing/TLS/SQLite "
            "paths. Scanner fixes on newer feature lines are not a verified 3.11 correction; "
            "a missing 3.11 fix is not proof no backport can exist."
        )
        question = (
            "For all enumerated CPython groups, confirm a released PSF 3.11 backport and matching "
            "base artifact before a compatible correction. If unavailable, approve or reject "
            "a separately gated feature-line move with the compatibility costs in the decision table."
        )
        trigger = "PSF 3.11 release/backport, base-image change, affected parser use, or final release pair"
    elif kind == "binary" and name == "openjdk":
        family, priority = "copied-jdk", 2
        sources += ["studio-maven-image-remediation.md", "https://adoptium.net/support/",
                    "retained:syft.json"]
        rationale = "Copied Temurin JDK is detected; zero scanner matches is not complete vendor-JDK advisory coverage."
        question = (
            "Commission vendor-specific JDK-21 advisory mapping for the exact copied build; "
            "approve any JDK transition only after Java 17/21, TLS/native/font and Build & Run proof."
        )
        trigger = "Vendor CPU/security release, copied JDK/base change, new Java consumer, or final release pair"
    elif kind == "java-archive":
        family, priority = "maven-archives", 2
        sources += ["studio-maven-image-remediation.md", "retained:syft.json", "retained:grype.json", "retained:trivy.json"]
        rationale = (
            "All distinct Maven JAR identities/locations remain inventoried, including nested artifacts. "
            "Historical targeted Guava correction is preserved; zero current archive alerts is "
            "not whole-tooling clearance. Downloaded plugins/transitives are outside this filesystem."
        )
        question = "Retain whole-distribution Maven control; assess new plugins/transitives or any packaging transition separately."
        trigger = "Maven archive/plugin/extension or profile change, advisory correction, or final release pair"
    elif kind == "python":
        family, priority = "installed-python", 1
        sources += ["studio-pyjwt-audit-followup.md", "pip-audit.json", "retained:syft.json"]
        rationale = (
            "Installed distributions are reconciled across filesystem scanners, not conflated with "
            "the 95 reference constraints or imported-SBOM identities. PyJWT 2.15.0 control is "
            "retained, not new authentication; native/embedded code needs separate evidence."
        )
        question = "Keep strict constrained audit blocking; investigate any new installed/native finding before claiming a fix."
        trigger = "Lock/distribution/native wheel change, new advisory, or final release pair"
    else:
        family, priority = "embedded-native", 2
        sources += ["retained:syft.json", "retained:runtime-inspection.json"]
        rationale = (
            "PE launchers and platform-specific Maven native binaries are shipped distinct artifacts, "
            "not erased because this target is AMD64 Linux. Unrecognized native/embedded code is "
            "not exhaustively covered by package scanners."
        )
        question = "Map vendor native-library advisories and callable platform/use paths before any absence or removal conclusion."
        trigger = "Native artifact/platform/use or advisory change, or final release pair"
    return {"id": family, "priority": priority, "state": "open/decision-required",
            "owner": OWNER, "rationale": rationale, "decision_needed": question,
            "sources": sources, "review_trigger": trigger, "advisory_cutoff_utc": CUTOFF}


def inventory(syft: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for index, artifact in enumerate(syft["artifacts"]):
        source = artifact.get("metadata", {}).get("source") or artifact["name"]
        locations = [{k: loc[k] for k in ("path", "accessPath", "layerID") if k in loc}
                     for loc in artifact.get("locations", [])]
        if any(not loc["path"].startswith(("/usr/", "/opt/", "/var/", "/workspace/", "/home/"))
               for loc in locations):
            raise ValueError("inventory location is not an image-internal path")
        records.append({"syft_artifact_id": artifact["id"], "syft_source_index": index,
                        "type": artifact["type"], "name": artifact["name"],
                        "version": artifact["version"], "source_family": source,
                        "source_version": artifact.get("metadata", {}).get("sourceVersion") or artifact["version"],
                        "architecture": artifact.get("metadata", {}).get("architecture", ""),
                        "purl": artifact.get("purl", ""), "locations": locations,
                        "decision": decision(artifact["type"], artifact["name"], source)["id"]})
    return records


def consolidate(syft: dict, grype: dict, trivy: dict, curl: dict, tracker: dict) -> dict:
    baseline = normalize(syft, grype, trivy)
    result = copy.deepcopy(baseline)
    result["inventory"] = inventory(syft)
    by_id = {record["syft_artifact_id"]: record for record in result["inventory"]}
    decisions = {}
    for record in result["inventory"]:
        d = decision(record["type"], record["name"], record["source_family"])
        decisions[d["id"]] = d
    curl_groups = {(curl["components"][g["component"]]["name"],
                    curl["components"][g["component"]]["version"], g["advisory_identity"]): g
                   for g in curl["groups"]}
    for component in result["components"]:
        records = [by_id[i] for i in component["syft_artifact_ids"]]
        component["inventory_indexes"] = [r["syft_source_index"] for r in records]
        kind = component["type"] if records else "python-unresolved"
        source = records[0]["source_family"] if records else ""
        d = decision(kind, component["name"], source)
        component["decision"] = d["id"]
        decisions[d["id"]] = d
    for group in result["groups"]:
        component = result["components"][group["component"]]
        group["decision"] = component["decision"]
        if component["type"] == "deb":
            source = group["decision"].removeprefix("os:")
            entry = tracker.get(source, {}).get(group["advisory_identity"], {})
            group["vendor_bookworm"] = entry.get("releases", {}).get("bookworm", {"status": "unknown"})
        if component["decision"] == "os:curl":
            retained = curl_groups.get((component["name"], component["version"], group["advisory_identity"]))
            if retained is None:
                raise ValueError("curl identity missing from frozen family ledger")
            group["classification"] = retained["classification"]
            group["rationale"] = retained["rationale"]
    result["decisions"] = sorted(decisions.values(), key=lambda d: (d["priority"], d["id"]))
    result["candidate"] = "EF-V5-M2-STUDIO-CONSOLIDATED-S1"
    result["revision"] = 1
    result["advisory_cutoff_utc"] = CUTOFF
    result["classification_counts"] = dict(Counter(g["classification"] for g in result["groups"]))
    validate(result, baseline, syft, curl)
    return result


def validate(candidate: dict, baseline: dict, syft: dict, curl: dict) -> None:
    """Ensure dispositions cannot lose observations or expand retained exclusions."""
    for key in ("observations", "applied_rules", "source_observation_counts",
                "image_config_digest", "image_index_digest", "image_platform"):
        if candidate[key] != baseline[key]:
            raise ValueError(f"baseline changed: {key}")
    expected_inventory = inventory(syft)
    if candidate["inventory"] != expected_inventory:
        raise ValueError("inventory identity/position changed")
    if len(candidate["components"]) != len(baseline["components"]):
        raise ValueError("component lost")
    decisions = {d["id"]: d for d in candidate["decisions"]}
    if len(decisions) != len(candidate["decisions"]):
        raise ValueError("duplicate decision")
    for record in [*candidate["inventory"], *candidate["components"]]:
        if record["decision"] not in decisions:
            raise ValueError("unowned identity")
    for d in decisions.values():
        if d["state"] != "open/decision-required" or not all(
            d.get(k) for k in ("owner", "decision_needed", "sources", "review_trigger", "rationale")
        ):
            raise ValueError("incomplete or accepted decision")
    for actual, expected in zip(candidate["components"], baseline["components"], strict=True):
        if {k: actual[k] for k in expected} != expected:
            raise ValueError("component identity changed")
        expected_indexes = [r["syft_source_index"] for r in expected_inventory
                            if r["syft_artifact_id"] in expected["syft_artifact_ids"]]
        if sorted(actual["inventory_indexes"]) != sorted(expected_indexes):
            raise ValueError("component inventory references changed")
        records = [expected_inventory[i] for i in expected_indexes]
        expected_decision = decision(
            expected["type"] if records else "python-unresolved", expected["name"],
            records[0]["source_family"] if records else "",
        )["id"]
        if actual["decision"] != expected_decision:
            raise ValueError("component family changed")
    retained = {(curl["components"][g["component"]]["name"],
                 curl["components"][g["component"]]["version"], g["advisory_identity"]): g
                for g in curl["groups"]}
    for actual, expected in zip(candidate["groups"], baseline["groups"], strict=True):
        fields = {k: actual[k] for k in expected}
        fields["classification"] = "open/unassessed"
        if fields != expected:
            raise ValueError("group identity/reference changed")
        component = candidate["components"][actual["component"]]
        if actual["decision"] != component["decision"]:
            raise ValueError("group decision reference changed")
        family = retained.get((component["name"], component["version"], actual["advisory_identity"]))
        if component["type"] == "deb" and component["name"] in {"curl", "libcurl4", "libcurl3-gnutls"}:
            if not family or any(actual.get(k) != family[k] for k in ("classification", "rationale")):
                raise ValueError("curl disposition changed")
        elif actual["classification"] != "open/unassessed":
            raise ValueError("unsupported new exclusion")
    if candidate["classification_counts"] != dict(Counter(g["classification"] for g in candidate["groups"])):
        raise ValueError("classification counts changed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retained", type=Path, required=True)
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument("--curl-ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    identity = json.loads(args.identity.read_text())
    verify_retained(args.retained, identity)
    reports = {name: json.loads((args.retained / f"{name}.json").read_text())
               for name in ("syft", "grype", "trivy")}
    result = consolidate(**reports, curl=json.loads(args.curl_ledger.read_text()),
                         tracker=json.loads((args.retained / "debian-tracker.json").read_text()))
    result["source_sha256"] = {name: sha256(args.retained / f"{name}.json") for name in reports}
    result["frozen_inputs_sha256"] = {"identity": sha256(args.identity), "curl_ledger": sha256(args.curl_ledger),
                                      "debian_tracker": sha256(args.retained / "debian-tracker.json")}
    write_ledger(args.output, result)


if __name__ == "__main__":
    main()
