# Studio current-pair residual image proof - 2026-10-14

Candidate **EF-V5-M2-STUDIO-RESIDUAL-PROOF-S1**, revision **1**.
**Complete assessment with findings is the deliverable, not M2 clearance,
risk acceptance or selected-release acceptance.** No recipe, dependency, runtime,
Engine, KS or Suite tracker change is made. Historical campaigns remain intact.

## Artifact and campaign boundary

| Input/artifact | Exact identity |
|---|---|
| Clean image-tested Studio archive | `ae99f6d3924ba01429edbdb25712e7cfffb38583` |
| Clean frozen merged Engine archive | `ba56abd1e0ff946260e96f3a3b715564fc0b740d` |
| Actual final OCI index / local image | `sha256:c2f2faad2d2351991d55c055a870f9b1f41115ee29f4332c38946cccc6a1c0d8` |
| Actual final AMD64 platform manifest | `sha256:672e20cf8593f1eec912566deb577f4185861b6e107c044d99294ae07d7946cf` |
| Actual final configuration | `sha256:e3bfed1436ccb3d73b8a442262e2b0f98932eafac7a9d5aeb07c0426a2a9a9b9` |

This pair was current at entry, but is **provisional**, not the Suite's final
release selection. Later PR commits contain only tools/tests/evidence, not
packaged application changes. The PR body separately identifies its reviewed head.

The [receipt](studio-image-residual-2026-10-14-receipt.json) binds source archives,
all 107 packaged Studio and 74 Engine source files, recipe/constraints/installer
hashes, base index/platform/config identities, actual OCI compressed layers and
separate decompressed diff IDs. Scanner serialization is not an OCI manifest.
`verify_image_oci.py` verifies those bytes. Named-stage exports may reserialize
an upstream manifest; their actual identities are recorded separately.

One fresh full build, **zero corrective full rebuilds**, and two cached named-stage
exports were used. Python **3.13.16 / Bookworm**, pip **26.2.1**, setuptools
**83.0.0**, wheel **0.48.0**, Apache Maven **3.9.16**, Temurin
**21.0.12.1+1-LTS**, APP_UID/GID **1000** and existing FROM pins are unchanged.
Host: macOS **26.5 (25F71)**, arm64, Docker **29.6.1**; linux/amd64 ran under
Docker Desktop emulation. No other-platform clearance is claimed.

Official live APT repositories resolved the recorded package versions. The recipe
removes package lists; InRelease/index bytes were not retained. Base digest pins
alone do **not** guarantee recovery of this image or freeze later APT resolution.

Checksum-verified **Syft 1.52.0 / Grype 0.119.0 / Trivy 0.74.0** were reused
from the prior campaign, with new verification receipts. Public databases were
downloaded once, then frozen and hash-checked before/after scans. Grype DB built
**2026-10-14T06:30:34Z**; Trivy vulnerability DB updated
**2026-10-14T19:14:58.511503573Z**, Java DB updated
**2026-10-14T01:07:18.515664291Z**. Scanning ran **21:40-21:42 UTC** that day.
Public vendor research has individual retrieval timestamps/hashes in the receipt.
No private image, source, SBOM or inventory was uploaded. Network lookups during
scanning were disabled, including Java remote POM resolution.

## Coverage and preserved observations

| Surface | Syft inventory | Grype active / ignored | Trivy observations |
|---|---|---|---|
| Final image | 166 Debian, 106 Python, 52 Java archives, 19 binary | 1,008 / 2,471 | 3,520 Debian; 6 imported-Python unresolved; 0 JAR |
| Whole `jdk21` stage | 149 Ubuntu, 13 Go modules, 1 Java, 1 binary | 374 / 0 | 94 Ubuntu; 13 Go |
| Whole `maven` stage | 97 Debian, 1 Python, 51 Java, 10 binary | 250 / 0 | 254 Debian; 6 imported-Python unresolved; 0 JAR |

These overlapping observation sets **must not be added as distinct vulnerabilities**.
The [lossless final ledger](studio-image-residual-2026-10-14-ledger.json),
[stage inventory/ledger](studio-image-residual-2026-10-14-stages.json) and
[summary](studio-image-residual-2026-10-14-summary.json) preserve active, ignored,
imported/unresolved identities, severities, fixes, aliases, source positions and
ignore rules. Kernel-header exclusions remain observations, not accepted risk.
Go `go1.26.7` and `v1.26.7` spelling mismatches remain separate source identities.

Mount-free stopped-container filesystem exports inventory all regular/hardlink
bytes, native ELF/PE paths and nested ZIP/JAR/wheel components. Final/stage native
path counts are **1,124 / 975 / 801**; these are paths, not distinct components.
All copied `/opt/java/openjdk` and `/opt/maven` regular bytes match their stage
snapshots. The complete Ubuntu stage includes `/usr/bin/pebble` and Go **1.26.7**
findings; those are not copied with the JDK subtree. Stage-only exposure remains
OPEN for the image owner, rather than being hidden by final-image coverage.

The non-root native probe binds **110 Python extension files** to exported bytes
and records linkage and supported runtime APIs. System/stdlib OpenSSL **3.0.22**
is separate from cryptography's private **4.0.1**. Lxml's private libxml2
**2.14.6** / libxslt **1.1.43**, Pillow's native features and PDFium
**151.0.7891.0** have explicit separate OPEN advisory-mapping work. Their versions
and artifact hashes are observed; OS/PyPI scanner silence does not clear them.
System Expat **2.5.0-1+deb12u4** and pyexpat's embedded **2.8.5** are separate.
`_elementtree` consumes pyexpat's C API; it is not asserted to be an independent
second embedded Expat library.

Complete stage/final snapshots do not observe every removed upstream build,
installation extraction or transient compiler process. Build/installer logs,
verified archives and signed-repository configuration provide bounded evidence,
not full transient instrumentation. Opaque/static/shaded identities, offline
Java dependency resolution, other platforms, host kernel and later Maven plugin
downloads have explicit limitations/owner decisions in the receipt and queue.

## Supported reconciliation and next decisions

The [outcomes](studio-image-residual-2026-10-14-outcomes.json) retain every
historical identity and source link; the [owner queue](studio-image-residual-2026-10-14-queue.json)
maps all 41 current final-image families, historical rationale and stage findings.
The following groups overlap; they are not interchangeable vulnerability totals.

1. **Supported conclusions:** the inherited 32-identity runtime set now has
   **3 prior remediations, 21 supported-not-affected and 8 OPEN**. Seven prior
   questions close using explicit current-minor PSF correction boundaries or backport/source/behavior
   proof, not new product changes. All eleven selected stdlib modules match the
   verified official 3.13.16 source. For CVE-2026-19672, the broad CNA range is
   retained alongside the explicit [3.13 backport](https://github.com/python/cpython/pull/156042),
   release NEWS, actual tarfile bytes and bounded no-outside-directory probe.
   The 21 old-bootstrap associations are separately evaluated against **every
   successor copy**, including setuptools' private wheel **0.46.3**. The official
   pip wheel matches active and seed vendor trees; absent old archives alone do
   not establish these conclusions. The existing 18 curl exclusions carry only
   because the four relevant binaries and upstream ranges match. Ten historical
   system-Expat backports match a freshly retrieved official u4 binary and current
   Debian fixed-version evidence. Five system groups remain OPEN. All 248 JDK
   regular files match the prior advisory-bound image; no blanket JDK clearance.
2. **Compatible-fix candidates:** no additional installable correction bundle
   is substantiated within the approved pins. One current official pip wheel was
   inspected: **26.2.1 still vendors urllib3 2.7.0**. A newer standalone urllib3
   cannot repair active/seed pip copies. Scanner-listed Go **1.26.9 / 1.27.2**
   are stage-binary rebuild leads, not a verified compatible Temurin replacement.
   Current Debian fix metadata is retained; no no-fix/no-DSA/postponed state is
   automatically cleared. A proposed replacement needs archive/copy inspection,
   non-root/bootstrap/build proof and fresh artifact assessment before remediation.
3. **OPEN applicability/compatibility decisions:** CVE-2025-12781 alternate
   base64 alphabets, CVE-2025-15367 POP3, CVE-2026-12345 tempfile cleanup,
   CVE-2026-3446 padded base64 callers,
   CVE-2026-102633 embedded Expat, and pip-private CVE-2026-97687/97688/97689
   remain the eight scoped OPEN identities. Deprecation is not behavioral repair;
   strict decoding is not proof about every caller. Expat's 32-bit advisory
   qualification does not alone clear this 64-bit artifact's allocation paths.
   Newly encountered **CVE-2026-77214** remains OPEN for system and embedded
   Expat: every applicable XML_ParseBuffer length guarantee is not established.
   TLS/parser consumers, native wheel copies, libc, headers/compiler and other
   ranked OS/build families remain visible. A successful synthetic header compile
   preserves functionality, not advisory applicability or host-kernel clearance.
4. **Coverage decisions:** the image/security owner must determine what additional
   native/static and transient-build evidence is required for final clearance.
   The release owner must reassess the selected final Studio/Engine pair. No
   accepted-residual disposition, font restoration or policy exemption is claimed.

**Smallest recommended next action:** authorize one copy-specific investigation
of the three pip-private urllib3 identities in active and ensurepip seed copies,
including actual pip caller paths and upstream bundle availability. It should end
with a verified upstream-fix proposal or explicit maintainer decision, not custom
unvendoring or an automatic standalone dependency bump. Other owner-queue work
remains separate; no follow-on task is started here.

## Executed proof and retained failures

- Non-root UID 1000 imports/tool versions/`pip check` pass; source mounts absent.
- Existing prebuilt-image startup smoke: **1 passed**, loopback-only publication;
  affected R2 repeat: **1 passed, process exit 0**, same immutable image.
- Network-disabled ensurepip/venv, explicit verified local toolchain installation,
  `pip check` and synthetic wheel build pass. Both seed and active vendors checked.
- Full maintained synthetic FS fixture, **springboot-legacy-compatible / H2**,
  goes through normal Studio project-open/export/generate/build/run/stop. It is
  **not jobless**: handoffs and downstream interfaces were not deleted. Export
  and generation warnings are empty. Separate `mvn clean verify` executes
  **1 test, 0 failures/errors/skips**. Studio's later `-DskipTests` packaging
  receives no test-execution credit. Account create **201**, persisted read
  **200** with all synthetic fields, missing ID **404**, health UP and stop pass.
- Initial Maven proof failed DNS while the container was still network-disabled.
  Failed logs/cache were retained. After disconnecting Docker's exclusive `none`
  network and enabling the proof's normal dependency-download network, the one
  justified retry passed. The task container was disconnected afterward.
- Image regression retry: **331 passed, 4 skipped, 5 failed**. Four failures need
  Node, intentionally absent from the image; they are **not image passes**. The
  fifth required a missing copied CONTRIBUTING fixture; after supplying it, that
  single policy test passed. The earlier **330/4/6** attempt and all failure logs
  remain retained. Four skips need a full external Engine checkout in those tests;
  packaged-Engine generate/build/run is proved separately. Host/CI DOM checks
  remain required. No image runtime capability or test assertion was weakened.

KA remains OFF, shared-mode guards and regeneration safeguards are unchanged.
The Java font-rendering limitation remains visible: no fonts were restored.
Manifest 2.0 and independently versioned project snapshots are unchanged. This
campaign does not establish A11y-01 speech, browser proof or full Suite L5.

### Image regression selection

The image regression selection was **340 tests**, not Bundle P's separate
495-test selection. The dedicated stopped task container's pytest node-ID cache
retains those 340 unique IDs; no cache was copied in the setup archive. Its
per-file counts reconcile with the actual **331 passed / 4 skipped / 5 failed**
retry. The receipt records the selection and hash-bound private node-ID list.
The original full argv was not captured; this is recovered selection evidence,
not an invented command transcript.

| Selected file under `tests/` | Tests |
|---|---:|
| `test_audit_persistence.py` | 26 |
| `test_browser_security.py` | 6 |
| `test_dependency_audit_policy.py` | 4 |
| `test_docker_compose_defaults.py` | 5 |
| `test_dom_xss.py` | 11 |
| `test_edge_contract_inspector_security.py` | 34 |
| `test_export_build_run.py` | 13 |
| `test_maven_image_build_run_proof.py` | 15 |
| `test_package_writer.py` | 51 |
| `test_project_file_service.py` | 75 |
| `test_regen_binding.py` | 36 |
| `test_session_path_containment.py` | 13 |
| `test_sqlite_session_store.py` | 9 |
| `test_studio_ka_off.py` | 21 |
| `test_studio_settings.py` | 21 |

### Independent review correction - 2026-10-14

The later review found the tempfile clearance unsupported. Its retained CNA
omits 3.13/3.14; `defaultStatus: unaffected` cannot clear an omitted minor line.
Official upstream comparisons show that none of the five patch/revert references
is contained in exact release `v3.13.16` (`cbc944f4bc59639a444dd971c737788ba2283a91`).
The image's `tempfile.py` matches that source, SHA-256
`7350d7f75ca8d6e4752c377777a315dc26eb4ecd3b6c9c0951bffddc576f030f`,
and lacks `_rmtree_use_dir_fd` and `_resetperms_at`. The
[3.12 backport was reverted](https://github.com/python/cpython/pull/158528).
CVE-2026-12345 is restored to **OPEN**. The bounded symlink probe is retained
as context, not clearance or complete applicability proof. No custom fix or
runtime upgrade was made; upstream receipts are retained with their UTC dates.

Both reducers now use **per-record pinned producer identities**, rather than
hashing whatever scripts happen to be in the replay working tree. Bundle P's four
recorded tool hashes match source `ae99f6d`; this campaign's seven match source
`ed9ddcf`. These identify the recorded producers, not the corrected replay code.
The current correction is identified separately by reduction-policy revision 2
and the exact PR head. A later tooling-only edit does not relabel historical
execution; a changed computed result still fails `--check`. Bundle P's committed
receipt/results are unchanged and its retained replay is explicitly checked.

Final host Python 3.11 validation after the Claude review correction: focused
residual/OCI/Bundle P/report integrity checks **161 passed**; non-smoke suite **2,498 passed, 43
skipped, 32 deselected**; L2 **1
passed**. Skips are not passes. Changed-file Ruff, diff hygiene, 87 relative
documentation links/anchors and the local secret scan pass. Required CI and
independent exact-head review are separate, recorded in the PR handoff.
Both the corrected residual replay and historical Bundle P `--check` passed
against the retained inputs. This new head requires independent re-review;
earlier-head approvals are not transferred.

## Replay, retention and refresh

Private retention: task-specific **Studio-Residual-Proof-2026-10-14** package in
the maintainer's existing **EdgeForge Open-Source Artifacts** convention. It holds
source/OCI/filesystem archives, CycloneDX SBOMs, raw scanner rounds, frozen DBs,
verified tools/wheels/vendor receipts, logs and failed observations. Its checksum
manifest and the receipt's input manifest identify what can be replayed. Private
host paths and raw reports are not committed. No upload/publication is implied.
The original 381-file sealed packet and **`final-proof/`** overlay remain unchanged.
Use **`review-correction-proof/`** for the corrected reducer: all 145 previous
input hashes remain unchanged, with fourteen added upstream-research/selection
inputs (159 total). Relative links reuse the sealed raw campaign; additional
evidence does not relabel or rescan the image.

With authorized access to that package's `review-correction-proof/` overlay as `RETAINED`
and this PR's tooling revision:

```bash
python -m scripts.image_residual_report --retained "$RETAINED" --check --replay-filesystems
python -m pytest tests/test_image_residual_report.py tests/test_verify_image_oci.py -q
```

The reducer performs no builds/downloads/scans. It rejects missing/changed inputs,
wrong images, incomplete OS/Python/archive streams, unsupported finding types,
unbound vendor copies, invalid DBs and non-executed tests. Negative controls cover
ignored-only findings, CRITICAL Go/JAR results, private-wheel drift, malformed
exports and unsupported tar-backport exclusions. Review R0 also identified three
validator gaps, corrected without changing any assessed input: inventoried Go
targets now require matching scan inventories; falsey non-list finding fields
fail; startup/policy proof requires one unambiguous executed pytest pass, not a
substring that could coexist with failures/errors/skips. The reviewer's actual
report-mutation controls now reject all three cases, including a complete reducer
overlay with a removed Go result and updated input hash. R1 then demonstrated a
real pytest finalizer exception with a passing-test summary but process exit 1.
The final validator additionally requires exit 0 in a timestamped execution
record bound to each exact proof log and the assessed image. Both affected checks
were rerun: startup and the isolated fixture policy each pass with exit 0.
Missing/nonzero/bool exits, log drift, ANSI error markers and the real finalizer
control are rejected; a test summary alone is never process-success proof.
Both final rounds replay to the
same summary, complete inventory and normalized ledger.

A clean public clone can run synthetic integrity tests, **not** replay private raw
inputs. Missing #310 historical raw materials remain unavailable; this campaign
does not reconstruct them or silently reclassify history. A new recipe build uses
live APT and produces a **new artifact**, not guaranteed recovery of this digest.
Use the named Engine context and existing [local scanner procedure](studio-image-assessment.md#reproduce-locally)
for a new authorized campaign; assess final plus both named stages.

Refresh after source/Engine selection, recipe/base/toolchain/vendor changes,
material advisories/DB changes or changed coverage policy. Selected-release
rebuild, current-pair applicability and remaining M2 decisions are still required.
No risk, merge, release, image publication or Suite acceptance is authorized here.
