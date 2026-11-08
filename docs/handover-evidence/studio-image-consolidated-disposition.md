# Consolidated Studio image disposition

**2026-10-02; EF-V5-M2-STUDIO-CONSOLIDATED-S1 revision 1, Phase 1 only.**
Complete bounded decision package with open findings, **not risk acceptance,
whole-image clearance, M2 completion, or release approval**. No recipe,
dependency, application, authentication, or trust-handoff behavior changed.
The advisory cutoff remains **2026-10-01T16:30:29Z**, not a fresh October 2 scan.
Phase 2 AC6-7 and caller-handoff proof are not delivered or credited here.

## Reconciled baseline

| Identity | Value |
|---|---|
| Consolidation base | `14a379fffaeeb8b3334b5f6c937714f3aa90e159` |
| Actual retained image Studio source | `f22f941d0981135e4f3fa24313266449418e59db` |
| Actual image Engine archive | `584e4bf635ac12821496a52d20c3a03a6e73a92c` |
| Platform / user | `linux/amd64` only / `appuser`, UID 1000 |
| Local Docker ID / OCI index | `sha256:ff97fb0ee901e2e759d2143fee83538ac1ffeb17248c745a8f3287e9ca264c89` |
| Actual OCI platform manifest | `sha256:abd1074c5ddc67a25ca3c41f365358d80805108d9ee2b20e443fd7a3be3019d5` |
| Actual config | `sha256:1ffb911e7ac6a280378d2e1cebb3f6beea6df63c56fbb32fc693e7180675d32b` |
| Scanner-serialized Docker-schema-2 manifest, **not OCI** | `sha256:cf2a71fd08268fc993963cfd2dff2bb6c1ecd90ab857a2534989ff5117f4e5db` |

The [identity receipt](studio-image-consolidated-identities.json) maps source,
Dockerfile/lock/install-script hashes, the unchanged `app` Git tree, resolved
Python/Temurin base materials, config, **16 compressed OCI layer blobs** and
their distinct uncompressed filesystem **DiffIDs**. A fresh local Docker-save
stream rehashed every blob and rechecked the index/platform/config bytes against
the retained receipt; no image tar was retained. `ff97` is not the config, `cf2a`
is not the OCI manifest, and DiffIDs are not compressed-layer digests.

All retained raw report/vendor/feature hashes, official scanner archives,
checksum lists/executables, three frozen databases, original #306 BuildKit
receipt, and Engine archive matched. The archive's embedded commit was checked.
Dockerfile, `.dockerignore`, locks, `app/`, Maven installer, and packaging verifier
have no diff from tested source to task base. The recipe copies no new
consolidation script/evidence into the image. No fresh artifact or advisory
database was needed to interpret this unchanged baseline.

Syft **1.52.0**, Grype **0.119.0**, and Trivy **0.74.0** are reused, not installed
anew or rescanned. Grype's report DB built `2026-10-01T06:33:48Z`; Trivy DB
updated `2026-10-01T13:01:27.395440834Z`, Java DB
`2026-10-01T00:59:54.094025329Z`. Original observations, full official tool/DB
provenance and raw SHA256s are preserved in the receipt. Checksum integrity is
not independent signature attestation. Scans were local/offline, automatic
updates/external inventory queries disabled, Trivy telemetry disabled. This
delivery performed no private inventory/source/image/SBOM upload.

Neither historical image Engine `584e4bf...` nor Maven-proof Engine
`127439a...` is Phase 2's Engine `5793cb...` or KS `d5cf...`. These are dated
image/tooling proofs, not a selected final Suite pair. The Engine M2 vocabulary
is a **proposal**, not an adopted release threshold.

## Complete identity coverage

The new [consolidated ledger](studio-image-consolidated-ledger.json) supersedes
no historical file: #303/#304/#305/#306/#307 records stay unchanged. It retains
every normalized source observation, alias, severity, fix version/state, ignore
rule, zero-based source/result position, and reversible group reference from
#307's full baseline. Every component and inventory record has an explicit
family-decision reference. All 346 distinct Syft artifact IDs and source
positions remain, including separate native launchers, nested Java archives,
binary libraries/backends and package versions. Sanitized paths are **inside
the image**, not host paths; full private inventories remain local.

| Final filesystem coverage | Retention and limitation |
|---|---|
| 166 Debian packages | Every binary/version, source family/version, architecture and artifact ID; all 37 source families with findings mapped to open decisions |
| 109 installed Python distributions | Cross-scanner filesystem inventory; distinct from the 95 reference constraints and imported SBOM |
| 52 Java archive identities | Maven 3.9.16 distribution, including nested components; no new archive alerts, not full Java coverage |
| 19 binary identities | CPython 3.11.16, copied Temurin 21.0.12.1+1-LTS, 17 distinct PE/native tooling artifacts; other native code is not exhaustively detected |
| 18 pip vendor declarations | Exact names/versions in [native receipt](studio-image-consolidated-native.json); declarations are not a reachability or code-version verdict |
| 32 Python native extensions | Actual image-internal paths/SHA256s; statically linked or otherwise hidden code is not exhaustively assessed |
| Unassessed build stages | Temurin stage beyond the copied JDK, Maven install-stage Python/download/extraction environment, and transient compiler/package/bootstrap processes |
| Outside final filesystem | Newly downloaded Maven plugins/transitives/generated applications, host kernel, KS container, other platforms/custom adopter extensions |

The offline non-root, mount-free probe confirms CPython's `_ssl` links system
OpenSSL 3.0.22, `_sqlite3` system SQLite 3.40.1, and `zlib` system zlib 1.2.13.
`pyexpat` reports **Expat 2.8.3**, with no dynamic libexpat edge in its `ldd`
output. This embedded copy is distinct from Debian `libexpat1 2.5.0-1+deb12u3`;
neither version string alone establishes advisory clearance. Native extension
and vendor-file hashes are retained locally. The sanitized native receipt maps
these boundaries and gives an open owner/decision/review trigger.

| Overlapping observation stream | Count |
|---|---:|
| Grype active | 1,046 |
| Grype ignored | 2,315 |
| Trivy Debian | 3,356 |
| Trivy Python imported-SBOM | 6 |

There are **6,723 reversible observations, 93 affected component identities and
3,374 component/advisory groups**, not 6,723 vulnerabilities. Counts overlap;
do not add them to estimate distinct CVEs/exploits. Trivy's Java result is zero
findings, not a discarded unsupported finding. Copied JDK detection/zero
matches is not complete vendor-JDK assessment. Missing/malformed/changed raw
evidence fails reuse; it never means clean.

## Consolidated Decisions

The ledger has **103 explicit open family records**, covering affected and
inventory-only identities. Each includes responsible owner, exact question,
rationale, sources, priority and review trigger. Debian groups also carry the
frozen source-package Bookworm status/fixed version/repository metadata from
`debian-tracker.json`; unknown entries would stay unknown. A vendor `resolved`
status describes availability of a fix, **not this installed artifact**.

Decision owner throughout: **Studio maintainer**; the adopting deployment's
security/risk owner alone owns any later exposure/risk decision. No residual
risk is accepted here. Priority is investigation order, not exploitability.

| Priority / identities | Evidence and exact open decision |
|---|---|
| 1: curl/OpenSSL and GnuTLS backends; authentication/proxy/cookie and HTTP/2 memory-safety groups | Preserve [#307's full applicability record](studio-image-curl-disposition.md): **18 supported exclusions and 60 open groups**, exactly unchanged. Exclusions remain advisory/backend/component-specific; map Git/operator credentials, handles and supported protocol use before a broader claim. |
| 1: native crypto/parsing/auth source families `openssl`, `expat`, `sqlite3`, `gnutls28`, `libtasn1-6`, `krb5`, `openldap`, `nghttp2`, `zlib`, `pcre2`, `glibc`, `pam`, `libgcrypt20`, `p11-kit` | All binaries/versions and groups are enumerated. Shipped libraries may be callable even when pulled by tooling. Validate exact binary/backport and affected consumer paths; neither safe application YAML loaders nor disabled shared Build & Run clear native libraries. |
| 1: **Expat compatible-backport candidate** | Frozen tracker and both scanners list **2.5.0-1+deb12u4** for ten groups, while this image has u3. IDs: CVE-2024-28757, CVE-2025-59375, CVE-2026-24515, -25210, -32776, -32777, -32778, -45186, -66046, -93990. Verify the official AMD64 package/replacement before a new artifact. Five other groups remain open. Do not confuse embedded CPython Expat with this package. |
| 1: pip-vendored `msgpack 1.1.2`, `setuptools 70.3.0`, `urllib3 2.7.0` | Six imported-SBOM alerts stay inventory-unresolved/open. Actual pip vendor declarations/files are present, including urllib3. Historical pure-Python msgpack/native-fault and pkg_resources-subset leads are not exclusions. Match affected functions and alternate copies; a standalone setuptools/urllib3 update does not replace pip's copy. Verify an actual compatible pip wheel before proposing a vendor update. |
| 1: CPython 3.11.16 and installed Python/native wheels | All 12 interpreter groups remain open: ten list only newer feature-line fixes, two no listed version. No released 3.11 fix was established by these scanner records. Confirm PSF advisory/backport and base artifact; do not infer that no future backport exists. Preserve strict reference audit/PyJWT 2.15.0 control separately. |
| 2: Linux userspace headers | All 2,315 Grype ignored observations retained; Trivy also retains its extra identity. The host kernel is not inside the image. Decide header/compiled-product applicability and whether a proved header/toolchain removal preserves native builds; scanner default ignore rules are not acceptance. |
| 2: copied JDK, 52 Maven archive identities and embedded native tooling | Historical Guava whole-distribution correction retained, not a new image-wide conclusion. Vendor-specific JDK/native advisory mapping and downloaded plugin graphs remain open. The Linux target does not erase bundled Windows launchers/Jansi identities. |
| 3: remaining OS source families | `acl`, `apt`, `attr`, `bash`, `binutils`, `bzip2`, `coreutils`, `dash`, `diffutils`, `gcc-12`, `git`, `gnupg2`, `gzip`, `ncurses`, `patch`, `perl`, `shadow`, `systemd`, `sysvinit`, `tar`, `util-linux`: every binary/group maps to its source-family decision and exact frozen vendor status. Verify backports, executable/library use and supported build dependencies before update/removal. Build orientation is not absence. |

### Completed change/compatibility decision package

**Chosen bounded delivery: unchanged artifact plus complete open decision
package.** This does not claim every investigation exhausted or every compatible
fix unavailable. In particular the Expat backport is a concrete unapplied fix
candidate, not a no-fix excuse. The Dockerfile already upgrades APT; a redundant
recipe edit would not prove library replacement. No new image is built merely
to chase zero findings. Family-specific unknowns and next proof are explicit.

| Alternative, not implemented | Cost / responsible owner's precise question |
|---|---|
| Same-Bookworm native refresh, beginning with Expat u4 | **Studio maintainer:** verify the official package, then authorize a bounded fresh artifact from the same recipe or justify a minimal version pin. Prove installed/native delta, frozen-snapshot comparison, non-root startup/caches, strict audit, affected tests and representative Build & Run. This is not a broad migration gate or an applied fix. |
| Python-3.11-compatible pip/vendor wheel | **Studio maintainer:** after advisory-to-code binding, select the actual wheel whose vendor tree corrects the affected copies, not merely a higher version. Cost: resolver/bootstrap policy, constrained install/audit and native/Studio/Engine compatibility proof. Until verified, no pin change or exclusion. |
| Python feature-line transition | **Studio maintainer:** approve or reject moving beyond 3.11 only after enumerating ABI/wheel/parser/tarfile differences, supported Engine/FastMCP installs and full relevant Studio/image tests. Ten scanner fix strings alone are not approval or a stable-release recommendation. |
| Distribution or toolchain removal transition | **Studio maintainer:** select a supported distribution versus continued Bookworm backports, or remove named development packages only after ABI/glibc/OpenSSL/Git/UID/native-build/JDK costs and supported workflows are proved. No mixed repos, custom curl library swap, unsupported capability loss, or broad OS change here. |
| JDK or Maven transition | **Studio maintainer:** preserve JDK 21 and verified complete Maven 3.9.16 unless an actual vendor mapping justifies a reviewed change; assess Java 17/21 outputs/runtime, plugins, TLS/native and font support. No arbitrary JAR substitution or major transition. |
| Base tags: pin versus float | **Studio maintainer:** approve a separate reproducibility policy for the two recorded base materials. Current tags still float; digest pinning alone does not freeze APT/PyPI/download/timestamps. Chosen here: disclose and retain exact resolved identities, no unapproved pinning/settings change. Trigger: final pair/build, base movement or provenance-policy selection. |
| Interim deployment controls/residual risk | **Adopter security owner:** define scope, accountable owner, mitigations and review date for exact open identities if deployment is proposed. These potential controls are not tested fixes, approved exposure or acceptance. |

General review triggers: a released compatible vendor/backport/wheel; changed
affected range or consumer/protocol/native features; new plugin/profile; changed
advisory snapshot; or selected final Studio/Engine release pair. A trigger calls
for a bounded reassessment, not an automation or another automatic family PR.
No-fix, no-dsa, postponed, wont-fix, suppression and unknowns remain open.

## Compatibility and Validation

Freshly executed on this retained artifact: existing mount-free/non-root image
launch smoke **1 passed**, actual UID 1000 vendor/native probe and writable
`/home/appuser/.m2` and `/workspace/data`, and full OCI blob/descriptor recheck.
The prebuilt smoke checks **this image only**; it does not prove a changed recipe
or the current/future Engine pair. No changed native/tooling content exists.

Reused as **historical compatibility**, not relabeled as a run on `ff97`:
[#305's Java 17/21 and representative Build & Run proof](studio-maven-image-remediation.md).
Maven/JDK/APT content is byte-identical through the first nine compressed layers;
the installer/runner inputs are unchanged. The two corrected historical
Boot 3/jobless Boot 4.1 result/verify-log hashes were rechecked. Each executed
one Maven test, zero skips/errors/failures, package and HTTP 200/health UP.
Java-21/PostgreSQL and host-JDK observations remain the original dated receipts,
not rerun against the changed Engine context. No full Suite L5 or Batch/Kafka
proof is claimed. Preserve the lean-image **font-rendering limitation** and
prebuilt-artifact disclosure; adopter font/text-rendering extensions need their
own assessment. #306's startup/PyJWT controls remain dated proof as recorded.

The existing report and full-ledger replays are byte-identical to frozen raw
outputs. The new generator delegates identity/coverage to those validators,
then preserves every observation and component/group reference while adding
inventory and owner decisions. Focused integrity suite: **66 passed** (36
existing plus 30 consolidated regressions). Negative controls reject dropped
active/ignored/group/inventory records, rewritten advisory/fix/severity/source
fields, changed unresolved identity, missing owner/question/source/trigger,
new exclusions, expanded curl conclusions and missing/changed retained files.
Changed Python lint and diff hygiene pass. Fresh local non-smoke suite:
**2,234 passed, 18 skipped, 29 deselected**; skips are not executed proof.
Fresh L2: **1 passed**. Established strict constrained `pip-audit 2.9.0`:
exit 0, **no known vulnerabilities found**. Its public package-name/version
queries are separate from the frozen image snapshot and do not assess embedded
pip/native/JDK/OS code. The retained audit executable lacked its module; a new
task-owned isolated audit environment succeeded without product changes.
Commands and raw log hashes are in the identity receipt.

Exact-head CI and fresh independent review are required handoff gates. This
builder does not self-approve. Human merge, overall goal state, Phase 2 and
M2/release clearance remain separately owned.

## Replay and Retention

Set `RETAINED` to local `edgeforge-studio-curl-s1-proof` and `OUT` to task-local
`edgeforge-studio-consolidated-image-proof`, outside Git. Retention has no SLA;
preserve hash-identified raw files/DBs before temporary cleanup. New raw OCI
recheck/runtime probe receipts and their hashes are in the identity receipt.
No raw reports, DBs, full SBOMs, private inventory or source archive is committed.

```sh
python3.11 -m scripts.image_consolidated_disposition \
  --retained "$RETAINED" \
  --identity docs/handover-evidence/studio-image-curl-identities.json \
  --curl-ledger docs/handover-evidence/studio-image-curl-ledger.json \
  --output "$OUT/replayed-consolidated-ledger.json"
cmp "$OUT/replayed-consolidated-ledger.json" \
  docs/handover-evidence/studio-image-consolidated-ledger.json
python3.11 scripts/image_assessment_report.py \
  --syft "$RETAINED/syft.json" --grype "$RETAINED/grype.json" \
  --trivy "$RETAINED/trivy.json" --output "$OUT/replayed-summary.json"
python3.11 -m scripts.image_findings_ledger \
  --syft "$RETAINED/syft.json" --grype "$RETAINED/grype.json" \
  --trivy "$RETAINED/trivy.json" --output "$OUT/replayed-full-ledger.json"
cmp "$OUT/replayed-summary.json" "$RETAINED/summary.json"
cmp "$OUT/replayed-full-ledger.json" "$RETAINED/full-ledger.json"
python -m pytest tests/test_image_assessment_report.py \
  tests/test_image_consolidated_disposition.py -q
EDGEFORGE_STUDIO_IMAGE_PREBUILT=sha256:ff97fb0ee901e2e759d2143fee83538ac1ffeb17248c745a8f3287e9ca264c89 \
  python -m pytest tests/smoke/test_docker_image_launch_smoke.py -q -m smoke
```

The ledger checksum is an evidence-integrity receipt, not an independent
advisory judgment. Reproduction uses the actual retained image/frozen databases;
floating rebuilds and fresh database downloads cannot recover this baseline.
Fresh package/feature changes require a separately identified artifact and
appropriate proof under the authorized finite bounds.
