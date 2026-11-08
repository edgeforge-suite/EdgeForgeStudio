"""Validate local image-scan coverage and write a path-free findings summary.

Raw Syft/Grype/Trivy reports stay outside the repository. In particular, Syft's
raw descriptor may contain host cache paths and must not be committed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _packages(report: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [item for item in report.get("artifacts", []) if item.get("type") == kind]


def _installed_trivy_packages(report: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    results = report.get("Results", [])
    selected = [result for result in results if result.get("Type") == kind]
    if len(selected) != 1:
        raise ValueError(f"expected one Trivy {kind} result, found {len(selected)}")
    packages = selected[0].get("Packages", [])
    if kind == "python-pkg":
        return [package for package in packages if package.get("AnalyzedBy") == "python-pkg"]
    return packages


def _name_versions(packages: list[dict[str, Any]], *, syft: bool, python: bool) -> set[tuple[str, str]]:
    if syft:
        pairs = [(package["name"], package["version"]) for package in packages]
    elif python:
        pairs = [(package["Name"], package["Version"]) for package in packages]
    else:
        # Trivy splits the Debian version into Version and Release; ID retains both.
        pairs = [tuple(package["ID"].split("@", 1)) for package in packages]
    if python:
        return {(re.sub(r"[-_.]+", "-", name).lower(), version) for name, version in pairs}
    return set(pairs)


def _scope(kind: str, name: str) -> str:
    if kind == "python" or (kind == "binary" and name == "python"):
        return "Studio Python runtime"
    if kind == "binary" and name == "openjdk":
        return "Engine invocation and local build capability"
    if kind == "java-archive" or name.startswith(("maven", "libmaven", "openjdk-17", "default-jre")):
        return "build tooling retained in final image"
    return "final-image OS/tooling; runtime applicability unproven"


def _fingerprint(records: list[tuple[str, ...]]) -> str:
    return hashlib.sha256(json.dumps(sorted(records), separators=(",", ":")).encode()).hexdigest()


def _image_identity(syft: dict[str, Any], grype: dict[str, Any], trivy: dict[str, Any]) -> tuple[str, str]:
    source = syft.get("source", {})
    syft_image = source.get("metadata", {})
    grype_source = grype.get("source", {})
    grype_image = grype_source.get("target", {})
    trivy_image = trivy.get("Metadata", {})

    config = syft_image.get("imageID")
    manifest = syft_image.get("manifestDigest")
    name = syft_image.get("userInput")
    index_digests = syft_image.get("repoDigests")
    syft_layers = syft_image.get("layers")
    layers = ([layer.get("digest") for layer in syft_layers]
              if isinstance(syft_layers, list) else [])
    grype_layers = grype_image.get("layers")
    if (source.get("type") != "image" or not isinstance(config, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", config)
            or not isinstance(manifest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", manifest)
            or not isinstance(name, str) or not name
            or not isinstance(index_digests, list) or not index_digests
            or not layers or any(not isinstance(layer, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", layer)
                                 for layer in layers)
            or syft_image.get("os") != "linux" or not syft_image.get("architecture")):
        raise ValueError("Syft report is missing identified image and platform metadata")

    # Docker's OCI index, platform manifest, image config and layer IDs are distinct.
    # Trivy reports the index and layers; Grype/Syft additionally report the config.
    if (grype_source.get("type") != "image"
            or grype_image.get("imageID") != config
            or grype_image.get("manifestDigest") != manifest
            or grype_image.get("repoDigests") != index_digests
            or grype_image.get("userInput") != name
            or grype_image.get("os") != syft_image["os"]
            or grype_image.get("architecture") != syft_image["architecture"]
            or not isinstance(grype_layers, list)
            or [layer.get("digest") for layer in grype_layers] != layers):
        raise ValueError("Grype report is not for the Syft image and platform")

    index = trivy_image.get("ImageID")
    if (not isinstance(index, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", index)
            or not any(digest.endswith("@" + index) for digest in index_digests)
            or trivy_image.get("RepoDigests") != index_digests
            or trivy.get("ArtifactName") != name
            or trivy_image.get("DiffIDs") != layers):
        raise ValueError("Trivy report is not for the Syft image and platform")
    return config, index


def _trivy_findings(trivy: dict[str, Any], os_packages: list[dict[str, Any]],
                    python_packages: list[dict[str, Any]]) -> dict[str, Any]:
    installed_os = _name_versions(os_packages, syft=True, python=False)
    installed_python = _name_versions(python_packages, syft=True, python=True)
    totals: Counter[str] = Counter()
    severities: dict[str, Counter[str]] = defaultdict(Counter)
    by_component: dict[tuple[str, str, str, str], dict[str, Any]] = defaultdict(
        lambda: {"advisories": 0, "severities": Counter(), "high_critical_ids": set(),
                 "available_fixes": {}, "advisory_records": []}
    )
    for result in trivy["Results"]:
        kind = result.get("Type")
        if not isinstance(kind, str) or not kind:
            raise ValueError("Trivy result is missing a type")
        vulnerabilities = result.get("Vulnerabilities", [])
        if vulnerabilities is None:
            vulnerabilities = []
        if not isinstance(vulnerabilities, list):
            raise ValueError("Trivy advisory results are invalid")
        if kind not in {"debian", "python-pkg"}:
            if vulnerabilities:
                raise ValueError(f"unsupported Trivy result type with vulnerabilities: {kind}")
            continue
        for vulnerability in vulnerabilities:
            name = vulnerability["PkgName"]
            version = vulnerability["InstalledVersion"]
            severity = vulnerability.get("Severity") or "UNKNOWN"
            if kind == "debian":
                if (name, version) not in installed_os:
                    raise ValueError("Trivy Debian finding is not tied to the inventoried image")
                disposition = "open; applicability not yet established"
                category = "debian"
            else:
                normalized = _name_versions([{"name": name, "version": version}], syft=True, python=True)
                installed = normalized <= installed_python
                disposition = ("open; applicability not yet established" if installed else
                               "open; standalone distribution absent, embedded-code applicability unresolved")
                category = "installed_python" if installed else "inventory_unresolved_python"
            totals[category] += 1
            severities[category][severity] += 1
            component = by_component[(category, name, version, disposition)]
            component["advisories"] += 1
            component["severities"][severity] += 1
            advisory_id = vulnerability["VulnerabilityID"]
            component["advisory_records"].append(
                (advisory_id, severity, vulnerability.get("FixedVersion") or "")
            )
            if severity.upper() in {"HIGH", "CRITICAL"}:
                component["high_critical_ids"].add(advisory_id)
            if vulnerability.get("FixedVersion"):
                component["available_fixes"][advisory_id] = vulnerability["FixedVersion"]

    components = [
        {
            "category": category, "name": name, "version": version,
            "scope": _scope("python" if category.endswith("python") else "deb", name),
            "advisories": values["advisories"],
            "severities": dict(sorted(values["severities"].items())),
            "high_critical_ids": sorted(values["high_critical_ids"]),
            "available_fixes": dict(sorted(values["available_fixes"].items())),
            "advisory_fingerprint_sha256": _fingerprint(values["advisory_records"]),
            "disposition": disposition,
        }
        for (category, name, version, disposition), values in sorted(by_component.items())
    ]
    return {
        "by_category": dict(sorted(totals.items())),
        "by_severity": {kind: dict(sorted(counts.items())) for kind, counts in sorted(severities.items())},
        "observed_result_types": sorted({result.get("Type") for result in trivy["Results"]}),
        "components": components,
    }


def _ignore_rule(rule: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(rule, dict):
        raise ValueError("Grype ignored finding has an unsupported or incomplete rule")
    package = rule.get("package")
    if (set(rule) != {"namespace", "package", "match-type"}
            or not isinstance(package, dict)
            or set(package) != {"name", "type", "language", "upstream-name"}
            or not package.get("name") or not package.get("type") or not rule.get("match-type")):
        raise ValueError("Grype ignored finding has an unsupported or incomplete rule")
    return {
        "namespace": rule["namespace"],
        "package": {key: package[key] for key in ("name", "type", "language", "upstream-name")},
        "match-type": rule["match-type"],
    }


def _ignored_grype_findings(matches: list[dict[str, Any]]) -> dict[str, Any]:
    severities: Counter[str] = Counter()
    fix_states: Counter[str] = Counter()
    by_component: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
        lambda: {"advisories": 0, "severities": Counter(), "fix_states": Counter(),
                 "high_critical_ids": set(), "available_fixes": {}, "advisory_records": [], "rules": set()}
    )
    by_rule: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"ignored_matches": 0, "advisory_records": []}
    )
    for match in matches:
        artifact = match["artifact"]
        vulnerability = match["vulnerability"]
        rules = match.get("appliedIgnoreRules")
        if not isinstance(rules, list) or not rules:
            raise ValueError("Grype ignored finding has no applied rule")
        rule_keys = {
            json.dumps(_ignore_rule(rule), sort_keys=True, separators=(",", ":"))
            for rule in rules
        }
        severity = vulnerability.get("severity") or "Unknown"
        fix = vulnerability.get("fix") or {}
        fix_state = fix.get("state") or "unknown"
        record = (vulnerability["id"], severity, fix_state,
                  json.dumps(sorted(fix.get("versions") or [])))
        key = (artifact["type"], artifact["name"], artifact["version"])
        component = by_component[key]
        component["advisories"] += 1
        component["severities"][severity] += 1
        component["fix_states"][fix_state] += 1
        component["advisory_records"].append(record)
        component["rules"].update(rule_keys)
        if severity.lower() in {"high", "critical"}:
            component["high_critical_ids"].add(vulnerability["id"])
        if fix_state == "fixed":
            component["available_fixes"][vulnerability["id"]] = fix.get("versions") or []
        severities[severity] += 1
        fix_states[fix_state] += 1
        for rule_key in rule_keys:
            by_rule[rule_key]["ignored_matches"] += 1
            by_rule[rule_key]["advisory_records"].append(record)

    return {
        "total": len(matches),
        "by_severity": dict(sorted(severities.items())),
        "by_fix_state": dict(sorted(fix_states.items())),
        "components": [
            {
                "type": kind, "name": name, "version": version,
                "scope": _scope(kind, name),
                "advisories": values["advisories"],
                "severities": dict(sorted(values["severities"].items())),
                "fix_states": dict(sorted(values["fix_states"].items())),
                "high_critical_ids": sorted(values["high_critical_ids"]),
                "available_fixes": dict(sorted(values["available_fixes"].items())),
                "advisory_fingerprint_sha256": _fingerprint(values["advisory_records"]),
                "applied_rules": [json.loads(rule) for rule in sorted(values["rules"])],
                "disposition": "open; scanner-excluded, applicability not yet established",
            }
            for (kind, name, version), values in sorted(by_component.items())
        ],
        "rules": [
            {
                "rule": json.loads(rule),
                "ignored_matches": values["ignored_matches"],
                "advisory_fingerprint_sha256": _fingerprint(values["advisory_records"]),
            }
            for rule, values in sorted(by_rule.items())
        ],
    }


def summarize(
    syft: dict[str, Any], grype: dict[str, Any], trivy: dict[str, Any]
) -> dict[str, Any]:
    """Fail closed if the scanners disagree on installed packages or miss the JDK."""
    image_id, index_digest = _image_identity(syft, grype, trivy)

    artifacts = syft.get("artifacts", [])
    os_packages = _packages(syft, "deb")
    python_packages = _packages(syft, "python")
    java_archives = _packages(syft, "java-archive")
    jdks = [
        item for item in _packages(syft, "binary")
        if item.get("name") == "openjdk"
        and any(location.get("path") == "/opt/java/openjdk/release"
                for location in item.get("locations", []))
    ]
    if not os_packages or not python_packages or not java_archives or len(jdks) != 1:
        raise ValueError("OS, Python, Java archives, or copied JDK inventory is incomplete")

    results = trivy.get("Results")
    if (not isinstance(results, list) or any(
            not isinstance(result, dict) or not isinstance(result.get("Type"), str)
            or not result["Type"] for result in results)):
        raise ValueError("Trivy result is missing a type")
    trivy_os = _installed_trivy_packages(trivy, "debian")
    trivy_python = _installed_trivy_packages(trivy, "python-pkg")
    if _name_versions(os_packages, syft=True, python=False) != _name_versions(trivy_os, syft=False, python=False):
        raise ValueError("Syft and Trivy disagree on installed Debian packages")
    if _name_versions(python_packages, syft=True, python=True) != _name_versions(trivy_python, syft=False, python=True):
        raise ValueError("Syft and Trivy disagree on installed Python packages")

    db = grype.get("descriptor", {}).get("db", {}).get("status", {})
    if db.get("valid") is not True or not db.get("built"):
        raise ValueError("Grype advisory database is missing or invalid")
    matches = grype.get("matches")
    ignored_matches = grype.get("ignoredMatches")
    if not isinstance(matches, list) or not isinstance(ignored_matches, list):
        raise ValueError("Grype report lacks active or ignored advisory results")
    artifact_ids = {item.get("id") for item in artifacts}
    if any(match.get("artifact", {}).get("id") not in artifact_ids
           for match in matches + ignored_matches):
        raise ValueError("Grype finding is not tied to the inventoried image")

    ignored_findings = _ignored_grype_findings(ignored_matches)
    trivy_findings = _trivy_findings(trivy, os_packages, python_packages)

    by_type: Counter[str] = Counter()
    by_severity: Counter[str] = Counter()
    by_fix_state: Counter[str] = Counter()
    by_component: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "advisories": 0, "severities": Counter(), "fix_states": Counter(),
            "high_critical_ids": set(), "available_fixes": {},
        }
    )
    for match in matches:
        artifact = match["artifact"]
        vulnerability = match["vulnerability"]
        kind = artifact["type"]
        severity = vulnerability.get("severity") or "Unknown"
        fix_state = vulnerability.get("fix", {}).get("state") or "unknown"
        key = (kind, artifact["name"], artifact["version"])
        by_type[kind] += 1
        by_severity[severity] += 1
        by_fix_state[fix_state] += 1
        component = by_component[key]
        component["advisories"] += 1
        component["severities"][severity] += 1
        component["fix_states"][fix_state] += 1
        if severity.lower() in {"high", "critical"}:
            component["high_critical_ids"].add(vulnerability["id"])
        if fix_state == "fixed":
            component["available_fixes"][vulnerability["id"]] = vulnerability.get("fix", {}).get("versions", [])

    components = [
        {
            "type": kind,
            "name": name,
            "version": version,
            "scope": _scope(kind, name),
            "advisories": values["advisories"],
            "severities": dict(sorted(values["severities"].items())),
            "fix_states": dict(sorted(values["fix_states"].items())),
            "high_critical_ids": sorted(values["high_critical_ids"]),
            "available_fixes": values["available_fixes"],
            "disposition": "open; applicability not yet established",
        }
        for (kind, name, version), values in sorted(by_component.items())
    ]
    imported_python = [
        package for result in trivy.get("Results", [])
        if result.get("Type") == "python-pkg"
        for package in result.get("Packages", [])
        if package.get("AnalyzedBy") == "sbom"
    ]
    return {
        "schema_version": 2,
        "assessment_state": ("complete-with-findings" if matches or ignored_matches
                             or any(trivy_findings["by_category"].values()) else "clean"),
        "image_config_digest": image_id,
        "image_index_digest": index_digest,
        "inventory": {
            "debian_packages": len(os_packages),
            "python_packages": len(python_packages),
            "java_archives": len(java_archives),
            "copied_jdk": {"name": jdks[0]["name"], "version": jdks[0]["version"]},
            "trivy_imported_python_sbom_records": len(imported_python),
        },
        "advisory_db": {"schema": db.get("schemaVersion"), "built_utc": db["built"]},
        "findings": {
            "total": len(matches),
            "by_component_type": dict(sorted(by_type.items())),
            "by_severity": dict(sorted(by_severity.items())),
            "by_fix_state": dict(sorted(by_fix_state.items())),
            "components": components,
        },
        "ignored_findings": ignored_findings,
        "trivy_findings": trivy_findings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--syft", type=Path, required=True)
    parser.add_argument("--grype", type=Path, required=True)
    parser.add_argument("--trivy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in (args.syft, args.grype, args.trivy)]
    result = summarize(*reports)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
