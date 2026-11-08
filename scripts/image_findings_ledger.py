"""Normalize retained image findings without copying private scanner inventories."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scripts.image_assessment_report import _ignore_rule, summarize


def _python_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _component(kind: str, name: str, version: str) -> tuple[str, str, str]:
    return kind, _python_name(name) if kind == "python" else name, version


def _advisory_identity(advisory_id: str, aliases: list[str]) -> str:
    # Only an explicit scanner-provided, unambiguous CVE alias is a merge key.
    cves = sorted({value for value in [advisory_id, *aliases] if value.startswith("CVE-")})
    return cves[0] if len(cves) == 1 else advisory_id


def normalize(syft: dict[str, Any], grype: dict[str, Any], trivy: dict[str, Any]) -> dict[str, Any]:
    """Return reversible source references; leave all applicability claims open."""
    assessment = summarize(syft, grype, trivy)
    syft_components: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    syft_by_id = {}
    for artifact in syft["artifacts"]:
        key = _component(artifact["type"], artifact["name"], artifact["version"])
        syft_components[key].add(artifact["id"])
        syft_by_id[artifact["id"]] = key

    records: list[dict[str, Any]] = []
    rules: dict[str, dict[str, Any]] = {}
    for status, matches in (("active", grype["matches"]), ("ignored", grype["ignoredMatches"])):
        for index, match in enumerate(matches):
            artifact = match["artifact"]
            key = _component(artifact["type"], artifact["name"], artifact["version"])
            if syft_by_id[artifact["id"]] != key:
                raise ValueError("Grype artifact identity disagrees with Syft")
            vulnerability = match["vulnerability"]
            aliases = sorted({item["id"] for item in match.get("relatedVulnerabilities", [])
                              if item["id"] != vulnerability["id"]})
            fix = vulnerability.get("fix") or {}
            rule_keys = []
            if status == "ignored":
                for rule in match["appliedIgnoreRules"]:
                    sanitized = _ignore_rule(rule)
                    rule_key = json.dumps(sanitized, sort_keys=True, separators=(",", ":"))
                    rules[rule_key] = sanitized
                    rule_keys.append(rule_key)
            records.append({
                "source": f"grype_{status}", "source_index": index,
                "component_key": key, "advisory_id": vulnerability["id"],
                "aliases": aliases, "severity": vulnerability.get("severity") or "Unknown",
                "fix_state": fix.get("state") or "unknown",
                "fixed_versions": sorted(fix.get("versions") or []),
                "rule_keys": sorted(set(rule_keys)),
            })

    for result_index, result in enumerate(trivy["Results"]):
        kind = result["Type"]
        if kind not in {"debian", "python-pkg"}:
            continue
        for index, vulnerability in enumerate(result.get("Vulnerabilities") or []):
            key = _component("deb" if kind == "debian" else "python",
                             vulnerability["PkgName"], vulnerability["InstalledVersion"])
            records.append({
                "source": "trivy_debian" if kind == "debian" else "trivy_python",
                "result_index": result_index, "source_index": index,
                "component_key": key, "advisory_id": vulnerability["VulnerabilityID"],
                "aliases": [], "severity": vulnerability.get("Severity") or "UNKNOWN",
                "fix_state": "listed" if vulnerability.get("FixedVersion") else "none listed",
                "fixed_versions": [vulnerability["FixedVersion"]] if vulnerability.get("FixedVersion") else [],
                "rule_keys": [],
            })

    component_keys = sorted({record["component_key"] for record in records})
    component_indexes = {key: index for index, key in enumerate(component_keys)}
    rule_keys = sorted(rules)
    rule_indexes = {key: index for index, key in enumerate(rule_keys)}
    grouped: dict[tuple[int, str], list[int]] = defaultdict(list)
    observations = []
    for record in records:
        component_index = component_indexes[record["component_key"]]
        identity = _advisory_identity(record["advisory_id"], record["aliases"])
        grouped[(component_index, identity)].append(len(observations))
        observation = {key: value for key, value in record.items()
                       if key not in {"component_key", "rule_keys"}}
        observation["component"] = component_index
        observation["applied_rules"] = [rule_indexes[key] for key in record["rule_keys"]]
        observations.append(observation)

    groups = []
    for (component_index, identity), refs in sorted(grouped.items()):
        groups.append({
            "component": component_index,
            "advisory_identity": identity,
            "observed_ids": sorted({observations[index]["advisory_id"] for index in refs}),
            "explicit_aliases": sorted({alias for index in refs
                                        for alias in observations[index]["aliases"]}),
            "observation_indexes": refs,
            "classification": "open/unassessed",
        })

    counts = Counter(record["source"] for record in records)
    for source in ("grype_active", "grype_ignored", "trivy_debian", "trivy_python"):
        counts.setdefault(source, 0)
    if (counts["grype_active"] != assessment["findings"]["total"]
            or counts["grype_ignored"] != assessment["ignored_findings"]["total"]
            or counts["trivy_debian"] != assessment["trivy_findings"]["by_category"].get("debian", 0)
            or counts["trivy_python"] != sum(value for key, value in
                                             assessment["trivy_findings"]["by_category"].items()
                                             if key.endswith("python"))):
        raise ValueError("ledger observations do not reconcile to the assessed reports")

    return {
        "schema_version": 1,
        "image_config_digest": assessment["image_config_digest"],
        "image_index_digest": assessment["image_index_digest"],
        "image_platform": "linux/" + syft["source"]["metadata"]["architecture"],
        "method": ("One observation per raw scanner finding; source_index is zero-based within the "
                   "named result array. Groups merge only the same component type/name/version and "
                   "an exact advisory ID or one explicit, unambiguous CVE alias. Different package "
                   "identities and unmatched aliases stay separate; groups are not risk dispositions."),
        "source_observation_counts": dict(sorted(counts.items())),
        "components": [
            {"type": kind, "name": name, "version": version,
             "syft_artifact_ids": sorted(syft_components.get((kind, name, version), [])),
             "inventory_status": "confirmed" if (kind, name, version) in syft_components
             else "inventory-unresolved"}
            for kind, name, version in component_keys
        ],
        "applied_rules": [rules[key] for key in rule_keys],
        "observations": observations,
        "groups": groups,
    }


def write_ledger(path: Path, ledger: dict[str, Any]) -> None:
    """Keep each indexed record reviewable without expanding the ledger into a raw report."""
    lines = ["{"]
    items = sorted(ledger.items())
    for position, (key, value) in enumerate(items):
        suffix = "," if position < len(items) - 1 else ""
        if key in {"components", "observations", "groups"}:
            lines.append(f'  "{key}": [')
            lines.extend(
                "    " + json.dumps(item, sort_keys=True, separators=(",", ":"))
                + ("," if index < len(value) - 1 else "")
                for index, item in enumerate(value)
            )
            lines.append("  ]" + suffix)
        else:
            lines.append(f'  "{key}": '
                         + json.dumps(value, sort_keys=True, separators=(",", ":")) + suffix)
    lines.append("}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--syft", type=Path, required=True)
    parser.add_argument("--grype", type=Path, required=True)
    parser.add_argument("--trivy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name) for name in ("syft", "grype", "trivy")}
    source_bytes = {name: path.read_bytes() for name, path in paths.items()}
    reports = {name: json.loads(content) for name, content in source_bytes.items()}
    ledger = normalize(reports["syft"], reports["grype"], reports["trivy"])
    ledger["source_sha256"] = {
        name: hashlib.sha256(content).hexdigest() for name, content in sorted(source_bytes.items())
    }
    write_ledger(args.output, ledger)


if __name__ == "__main__":
    main()
