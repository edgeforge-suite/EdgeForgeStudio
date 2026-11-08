#!/usr/bin/env bash
# Regenerate the G4 dependency evidence artifacts:
#   - docs/handover-evidence/sbom.cdx.json                       (CycloneDX SBOM, resolved env)
#   - docs/handover-evidence/dependency-licenses.csv             (license inventory, declared deps)
#   - docs/handover-evidence/dependency-licenses-transitive.csv  (license inventory, resolved env)
#   - docs/handover-evidence/dependency-licenses.md              (same, + notable-licenses summary)
#   - docs/handover-evidence/pip-audit.json                      (pip-audit machine output)
#   - docs/handover-evidence/pip-audit.md                        (pip-audit readable summary)
#
# Named tools (pinned) are installed in an ISOLATED venv so they never pollute the
# project's own dependency surface. Studio's requirements.txt is installed into a
# project venv with constraints.txt; the SBOM is taken from that resolved
# environment, and the license inventory is filtered to the declared names in
# requirements.txt.
#
# Requires network access to the package index. Usage:
#   scripts/generate-dependency-evidence.sh [SNAPSHOT_DATE]
set -euo pipefail

CYCLONEDX_BOM_VERSION="7.3.0"
PIP_AUDIT_VERSION="2.9.0"
PIP_LICENSES_VERSION="5.5.5"
SNAPSHOT_DATE="${1:-$(date +%F)}"
PYTHON_BIN="${PYTHON:-python3.11}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT="docs/handover-evidence"
WORK="$(mktemp -d)"
TOOLS="$WORK/tools"
PROJ="$WORK/proj"

# Pinned SBOM/license tooling in an isolated venv.
"$PYTHON_BIN" -m venv "$TOOLS"
"$TOOLS/bin/pip" install --quiet --disable-pip-version-check \
  "cyclonedx-bom==${CYCLONEDX_BOM_VERSION}" \
  "pip-audit==${PIP_AUDIT_VERSION}" \
  "pip-licenses==${PIP_LICENSES_VERSION}"

# Studio's declared deps installed into a separate project venv -> resolved tree.
"$PYTHON_BIN" -m venv "$PROJ"
"$PROJ/bin/pip" install --quiet --disable-pip-version-check \
  -c constraints.txt pip setuptools wheel
"$PROJ/bin/python" scripts/verify-packaging-toolchain.py
"$PROJ/bin/pip" install --quiet --disable-pip-version-check -r requirements.txt -c constraints.txt

# 1. CycloneDX SBOM from the resolved project environment.
"$TOOLS/bin/cyclonedx-py" environment "$PROJ" \
  --of JSON --output-reproducible -o "$OUT/sbom.cdx.json"

# 2. License inventory, filtered to the names declared in requirements.txt.
"$TOOLS/bin/pip-licenses" --python "$PROJ/bin/python" --format json \
  --with-system > "$WORK/all.json"
SNAPSHOT_DATE="$SNAPSHOT_DATE" PIP_LICENSES_VERSION="$PIP_LICENSES_VERSION" \
  "$TOOLS/bin/python" - "$WORK/all.json" "$OUT" requirements.txt <<'PY'
import csv, json, os, re, sys
all_json, outdir, reqs = sys.argv[1], sys.argv[2], sys.argv[3]
TEST_DEPS = {"httpx2", "pytest", "pytestasyncio"}  # normalized names treated as test scope
norm = lambda n: n.lower().replace("-", "").replace("_", "")
declared = {}
for line in open(reqs, encoding="utf-8"):
    raw = line.split("#", 1)[0].strip()
    if not raw:
        continue
    requirement = raw.split(";", 1)[0].strip()
    name = re.split(r"[<>=!~;\[ ]", requirement, 1)[0]
    declared[norm(name)] = {"name": name, "requirement": requirement}
want = set(declared)
all_rows = sorted(json.load(open(all_json)), key=lambda r: r["Name"].lower())
rows = [r for r in all_rows if norm(r["Name"]) in want]

def scope_of(name: str) -> str:
    normalized = norm(name)
    if normalized in TEST_DEPS:
        return "test"
    if normalized in want:
        return "runtime"
    return "transitive"

with open(os.path.join(outdir, "dependency-licenses.csv"), "w", newline="") as f:
    w = csv.writer(f, lineterminator="\n")
    w.writerow(["Package", "Declared", "Resolved", "License", "Scope"])
    for r in rows:
        declared_req = declared[norm(r["Name"])]["requirement"]
        w.writerow([r["Name"], declared_req, r["Version"], r["License"], scope_of(r["Name"])])

with open(os.path.join(outdir, "dependency-licenses-transitive.csv"), "w", newline="") as f:
    w = csv.writer(f, lineterminator="\n")
    w.writerow(["Package", "Version", "License", "Scope"])
    for r in all_rows:
        w.writerow([r["Name"], r["Version"], r["License"], scope_of(r["Name"])])

copyleft = re.compile(r"GPL|LGPL|AGPL|MPL|EPL", re.I)
flagged_declared = [r for r in rows if copyleft.search(r["License"]) or r["License"].strip().upper() == "UNKNOWN"]
flagged_transitive = [r for r in all_rows if copyleft.search(r["License"]) or r["License"].strip().upper() == "UNKNOWN"]
summary = ("**Flagged declared licenses present:** " + ", ".join(f"`{r['Name']}` ({r['License']})" for r in flagged_declared)
           + ". Review before import.") if flagged_declared else (
           "**All declared dependencies are permissive (MIT / BSD / Apache-2.0). No copyleft "
           "(GPL / LGPL / AGPL / MPL / EPL) and no UNKNOWN-license packages are present among the "
           "declared surface.**")
declared_table = "| Package | Declared | Resolved | License | Scope |\n|---|---|---|---|---|\n" + "".join(
    f"| `{r['Name']}` | `{declared[norm(r['Name'])]['requirement']}` | {r['Version']} | {r['License']} | {scope_of(r['Name'])} |\n" for r in rows)
transitive_summary = ("**Flagged transitive licenses present:** " + ", ".join(
    f"`{r['Name']}` ({r['License']})" for r in flagged_transitive
) + ". Review before import.") if flagged_transitive else (
    "**Resolved transitive scan found no copyleft or UNKNOWN license strings.**"
)
md = f"""# Dependency License Inventory — EdgeForge Studio (declared deps)

> **Import-gate G4 evidence.** Resolved license inventory of Studio's declared
> dependencies plus a resolved transitive scan. See [`dependencies.md`](dependencies.md)
> for scope and tooling.
>
> **Generated:** {os.environ['SNAPSHOT_DATE']}, with **pip-licenses {os.environ['PIP_LICENSES_VERSION']}**.

## Notable licenses — summary

{summary}

## Declared dependencies

Machine-readable copy: [`dependency-licenses.csv`](dependency-licenses.csv).

{declared_table}
## Transitive scan

Machine-readable copy: [`dependency-licenses-transitive.csv`](dependency-licenses-transitive.csv).

{transitive_summary}

The transitive inventory covers the resolved project environment used for
[`sbom.cdx.json`](sbom.cdx.json). It is an automated scan, not a substitute for
the adopting organization's legal/license review.
"""
open(os.path.join(outdir, "dependency-licenses.md"), "w").write(md)
print(f"wrote {len(rows)} declared deps and {len(all_rows)} resolved packages; flagged declared: {len(flagged_declared)}; flagged transitive: {len(flagged_transitive)}")
PY

# 3. pip-audit from the locked project environment.
set +e
"$TOOLS/bin/pip-audit" -r constraints.txt --no-deps --disable-pip \
  --format json --output "$OUT/pip-audit.json" --progress-spinner off
AUDIT_EXIT=$?
set -e
if [ "$AUDIT_EXIT" -gt 1 ]; then
  echo "pip-audit failed with infrastructure/configuration exit code $AUDIT_EXIT" >&2
  exit "$AUDIT_EXIT"
fi
SNAPSHOT_DATE="$SNAPSHOT_DATE" PIP_AUDIT_VERSION="$PIP_AUDIT_VERSION" AUDIT_EXIT="$AUDIT_EXIT" \
  "$TOOLS/bin/python" - "$OUT/pip-audit.json" "$OUT/pip-audit.md" <<'PY'
import json, os, sys
src, dest = sys.argv[1], sys.argv[2]
data = json.load(open(src, encoding="utf-8"))
deps = data.get("dependencies", data if isinstance(data, list) else [])
vulns = []
for dep in deps:
    for vuln in dep.get("vulns", []) or []:
        vulns.append((dep.get("name", ""), dep.get("version", ""), vuln))
if vulns:
    summary = f"**Vulnerabilities found:** {len(vulns)} finding(s). Review before import."
    rows = "\n".join(
        f"| `{name}` | {version} | {v.get('id', '')} | {v.get('fix_versions') or v.get('fix_version') or ''} | {str(v.get('description', '')).replace('|', ' ')} |"
        for name, version, v in vulns
    )
    table = "\n| Package | Version | Advisory | Fix versions | Description |\n|---|---|---|---|---|\n" + rows
else:
    summary = "**No known vulnerabilities reported by pip-audit for the resolved environment.**"
    table = ""
status = "clean" if not vulns else "findings-present"
md = f"""# pip-audit Vulnerability Scan — EdgeForge Studio

> **Import-gate G4 evidence.** Vulnerability scan of the resolved Studio
> dependency environment.
>
> **Generated:** {os.environ['SNAPSHOT_DATE']}, with **pip-audit {os.environ['PIP_AUDIT_VERSION']}**.
> Machine-readable copy: [`pip-audit.json`](pip-audit.json).

## Status

{summary}

- Tool exit code: `{os.environ['AUDIT_EXIT']}`
- Status: `{status}`
{table}

## Scope

The scan is run against the locked dependency tree in `constraints.txt`, generated
from `requirements.txt`. It is an automated package-advisory check, not a
replacement for adopter-side supply-chain policy.
"""
open(dest, "w", encoding="utf-8").write(md)
PY

rm -rf "$WORK"
echo "dependency evidence regenerated under $OUT/"
