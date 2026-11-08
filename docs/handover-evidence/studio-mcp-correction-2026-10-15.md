# MCP dependency correction and fresh-image proof - 2026-10-15

Candidate **EF-V5-M2-STUDIO-MCP-CORRECTION-S1**, revision **1**.
Observation date is America/Chicago; execution receipts record **2026-10-16 UTC**.
This corrects one dependency-advisory match, not overall M2 or release acceptance.

## Dependency and applicability

The [post-merge main audit](https://github.com/santosh-sh/EdgeForgeStudio/actions/runs/38847770849)
at `ab1274ca41441a8e8157e4423ff049ec3545d436` failed on MCP `1.28.1`.
[GHSA-84m7-p3x7-pcfv / CVE-2026-59951](https://github.com/modelcontextprotocol/python-sdk/security/advisories/GHSA-84m7-p3x7-pcfv)
identifies `1.30.0` as the patched 1.x release. It concerns unbounded stateful
Streamable HTTP server sessions; stdio-only servers are excluded.

Studio's [Engine adapter](../../app/integrations/appbuilder_integration.py)
constructs a FastMCP client with a local child command, not an HTTP endpoint.
Its [KS adapter](../../app/integrations/ks_integration.py) uses subprocess pipes
and a stdio handshake. Studio does not expose the affected MCP HTTP server.
This correction does not assert prior exploitability, add a transport, or change
the existing local CLI fallback/shared MCP-only policy. KA remains OFF by default.

Only `mcp==1.28.1` becomes `mcp==1.30.0` in the 95-pin reference graph.
`fastmcp==3.4.0` still selects `fastmcp-slim[client,server]==3.4.0`, whose SDK
range is `mcp>=1.24.0,<2.0`. [MCP 1.30.0 metadata](https://pypi.org/pypi/mcp/1.30.0/json)
requires Python >=3.10, compatible with supported host 3.11 and image 3.13.16.
No declaration, other reference pin or optional extra changes. Installed metadata,
entry points and imports were inspected. All **111 SDK code members** match the
official wheel in both environments; its SHA-256 is
`666edb5009503e1047c9d60346a756f94b261f05cc2625f23d41c728ffc484d0`.

The [reference SBOM](sbom.cdx.json), [licenses](dependency-licenses-transitive.csv)
and [audit](pip-audit.json) describe the clean macOS/Python 3.11 graph, not every
possible installation. The image's 94 standalone distributions omit conditional
`backports.tarfile`, `importlib_metadata` and its `zipp` dependency, and include
unchanged Linux-only keyring dependencies `SecretStorage==3.5.0` and
`jeepney==0.9.0`. Both full graphs pass `pip check` and separate complete strict
audits: **95 / 94 packages**, zero findings, zero skipped/omitted packages.
These two Linux packages also existed in the preceding image. The image SBOM and
scanner inventory include embedded records separately from standalone metadata.

## Actual image

| Identity | Value |
|---|---|
| Clean image-tested Studio | `a987a21f9cb78b6f598fbeb46049b5b0a5f56996` |
| Frozen clean merged Engine | `ba56abd1e0ff946260e96f3a3b715564fc0b740d` |
| Actual OCI index / local image | `sha256:af69209c3b195d1ac6547f6f7fd5d756682ffc821961ffa7a7010f828192b104` |
| AMD64 platform manifest | `sha256:fd494112428547f000e33f87f455afcd2d47cdcc3c9d707aca6abb9f147af61b` |
| Configuration | `sha256:ec452cf2a3bb7d80b61751105cf284a43ee8e1715476c3ae76d35a344f59c882` |

One fresh `--pull --no-cache` full build, **zero corrective image rebuilds**.
The [receipt](studio-mcp-correction-2026-10-15-receipt.json) records source archive,
recipe/tool hashes, verified base index/platform descriptors and actual OCI
compressed layers separately from filesystem diff IDs. Packaged Studio/Engine
files match their source archives. Later commits add evidence only; the PR body
names the independently reviewed head separately. This pairing is provisional.

The recipe, Python **3.13.16 / Bookworm**, pip **26.2.1**, setuptools **83.0.0**,
wheel **0.48.0**, Maven **3.9.16** and Temurin **21.0.12.1+1-LTS** are unchanged.
Host Python **3.11.15**, macOS **26.5 (25F71)**, arm64, Docker **29.6.1**;
linux/amd64 ran under emulation. APT used the recipe's official live repositories.
Resolved OS package versions happen to match the preceding image; this is not
an SDK remediation claim. Digest pins alone do not freeze APT resolution or
guarantee recovery of this digest from a later rebuild.

## Executed proof

| Check | Actual result |
|---|---|
| Clean host install, imports, toolchain, `pip check` | PASS |
| Host MCP/KA focused selection | **182 passed, 21 skipped** (17 KS availability; 4 Engine discovery) |
| Host non-smoke suite | **2498 passed, 43 skipped, 32 deselected** |
| Host L2 | **1 passed** |
| Evidence/OCI/bootstrap/proof-runner regressions | **76 passed** |
| Real host strict stdio | Public `/project/open` -> `/export/write` -> `/export/generate`; zero warnings; no CLI fallback |
| Mount-free non-root launch smoke | **1 passed**, UID 1000, loopback-only exposure |
| Offline bootstrap | Network disabled; ensurepip/venv, verified four-wheel installation, `pip check`, synthetic wheel build PASS |
| Actual image focused selection | **215 passed, 21 skipped** (17 KS availability; 4 Engine discovery) |
| Actual image L2 | **1 passed** |
| Actual image strict stdio generate/build/run/stop | Full maintained FS sample, legacy-compatible profile; zero export/generation warnings |
| Generated Maven verification | **1 executed, 0 failures/errors/skips**; retained Surefire XML hashes |
| Meaningful app HTTP | **201** create and **200** persisted read with all synthetic fields; **404** absent ID; health UP |

The route harness is service automation, not browser observation or full Suite
L5. It does not patch generated production code or strip handoffs. Tests and
fixtures were copied into the task container, never over packaged `app/` code;
the image scan targets the immutable image, not that test-modified container.
No KS process was used for this KA-OFF proof. Skips are not counted as passes.

Independent review additionally enabled the four Engine-discovery cases against
the frozen Engine: **3 passed, 1 failed**. The unchanged
`TestRunGenerate::test_real_engine_cached_url_generation_preserves_ingestion_and_source_label`
fixture selects `createAccount`, but supplies a cached contract containing only
`listAccounts`. Engine rejects that unresolved write on the first CLI iteration,
before reaching the MCP iteration. The XML/failure is retained, not counted as
a pass or silently fixed. This is an **OPEN Studio test-fixture reconciliation**,
not evidence of an SDK regression or a product defect in the supported sample
flow. The separate real strict-stdio and full-image proofs above use the valid
maintained FS contract and pass. No unrelated fixture change is included here.

Retained failures: an obsolete host proof runner stopped at its retired global
session API before interaction; the current public-route proof succeeded.
The first image regression collection had a one-level-deep script-fixture copy
error; a corrected copy passed the identical selection. Initial ledger invocation
needed the supported module entry point. A cross-round whole-ledger byte assertion
failed because raw report hashes legitimately differ; all other ledger content
matches, and same-input replay is byte-identical. An optional host command named
a nonexistent test file; its corrected existing-file selection passed. No product
guard was weakened and none of these failures required an image rebuild.

## Assessment and remaining boundaries

Checksum-verified **Syft 1.52.0 / Grype 0.119.0 / Trivy 0.74.0** use the retained
**2026-10-14 frozen databases**, unchanged before/after this campaign. Exact tool
hashes, database hashes/dates and scanner argv are retained. Fresh artifact scans
are not fresh advisory-database downloads; current Python audits were queried
separately on 2026-10-16 UTC. No private inventory was uploaded to a new service.

Two rounds produce the same [summary](studio-mcp-correction-2026-10-15-image-summary.json):
**166 Debian / 106 Python records / 52 Java archives**, copied JDK identified;
**1008 Grype active, 2471 ignored, 3520 Trivy Debian, 6 imported-Python unresolved**
observations. These overlapping sets must not be added as distinct vulnerabilities.
Ignored rules and unresolved embedded identities remain preserved, not accepted.
The lossless ledgers retain distinct raw-input hashes; all other content matches.

The [delta](studio-mcp-correction-2026-10-15-delta.json) shows MCP as the only
inventory version change and unchanged scanner observation streams. The frozen
image scanners did not match the SDK advisory on either image; **their silence
is not the basis for closing it**. That conclusion uses the official fixed range,
verified installed SDK bytes, complete current strict audit and compatibility proof.

JDK, private Python/vendor and seed-wheel bytes match the preceding observed
copies. All inherited OPEN findings, named-stage/transient/native/JDK coverage
limits and the [#315 owner queue](studio-image-residual-2026-10-14-queue.json)
remain. No pip-private urllib3 repair or whole-family re-investigation is claimed.
**Java font rendering remains unavailable by default.** No M2 clearance,
residual-risk acceptance or release approval follows from this dependency fix.

## Reproduction and retention

Use the clean image-tested Studio SHA above and frozen Engine archive, not moving
main. Follow [constrained setup](../../CONTRIBUTING.md#setup-build-test), regenerate
with `PYTHON=python3.11 scripts/generate-dependency-evidence.sh YYYY-MM-DD`, and run
the unchanged strict audit from [CI](../../.github/workflows/pytest-ci.yml).
The receipt's `proof` keys identify exact successful commands via retained
execution records; use the explicit test selections, not historical totals as
acceptance criteria. Repeat the image harness with strict MCP transport:

```bash
PYTHONPATH=/workspace/EdgeForgeStudio \
EDGEFORGE_STUDIO_ENGINE_TRANSPORT=mcp \
EDGEFORGE_STUDIO_ENGINE_MCP_COMMAND=/usr/local/bin/python \
python /tmp/maven_image_build_run_proof.py \
  --project /tmp/synthetic.edgeforge-project.json \
  --profile springboot-legacy-compatible \
  --proof-root /workspace/data/GeneratedApps/mcp-proof --run --exercise-account
```

Run as the image's normal user after copying the committed helper and maintained
FS project; allow public Maven dependency retrieval for build/run, but disable
network for `image_bootstrap_proof.py` with its verified local wheelhouse. Use
`EDGEFORGE_STUDIO_IMAGE_PREBUILT` only with this identified fresh-build receipt.
For scanner replay use `python -m scripts.image_findings_ledger` and
`scripts/image_assessment_report.py` with the retained matching triplets. A future
build is a new assessment artifact, not a promise to recover this digest.

Private retention set **Studio-MCP-Correction-2026-10-15** in the maintainer's
existing **EdgeForge Open-Source Artifacts** convention contains raw scans/SBOM,
frozen databases/tools, OCI/source archives, wheels, successful and failed logs,
execution records, retrieved executed helper copies and a checksum manifest.
Use its self-contained **review-correction-proof** packet for the corrected
skip/fixture disclosures; the initial seal and R0 report remain historical.
The retained `build_evidence.py --check --studio-checkout CHECKOUT` verifies this
sanitized projection against the matching PR checkout;
it requires those private inputs and is not a clean-clone-only replay claim.
Committed helper snapshots and retrieved post-execution copies match; that is
not in-process attestation. The initial scan orchestrator before its entry-point
correction was not separately retained; its exact scanner commands/logs and later
orchestrator are available. Historical #314/#315 records remain unchanged.

**Suite handoff:** MCP correction and bounded provisional-pair proof are delivered;
whole-image findings, coverage decisions and final selected-pair reassessment
remain open. No Engine/KS/tracker change, publication, merge, tag or follow-on task.
