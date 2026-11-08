# Studio curl-family image assessment and decision package

Date: **2026-10-01**. Candidate **EF-V5-M2-STUDIO-IMAGE-CURL-S1**, revision **1**.
Research cutoff: **2026-10-01T16:30:29Z**. Delivery **B: complete with open
findings; no compatible official Bookworm upgrade available at the cutoff**.
This is not risk acceptance, whole-image clearance, M2 completion, or release
approval. No image, Dockerfile, package, application, or test behavior changed.

## Artifact and coverage

| Input / identity | Recorded value |
|---|---|
| Tracked-clean Studio task base | `ce433e1e8a1fb6e6a28d58ff4bdfcefa7c0369e2` |
| Actual retained #306 image source | `f22f941d0981135e4f3fa24313266449418e59db` |
| Frozen read-only Engine archive | `584e4bf635ac12821496a52d20c3a03a6e73a92c` |
| Target | `linux/amd64` only; default image user `appuser` |
| Local Docker ID / OCI index | `sha256:ff97fb0ee901e2e759d2143fee83538ac1ffeb17248c745a8f3287e9ca264c89` |
| Actual image config digest | `sha256:1ffb911e7ac6a280378d2e1cebb3f6beea6df63c56fbb32fc693e7180675d32b` |
| Actual linux/amd64 OCI platform manifest | `sha256:abd1074c5ddc67a25ca3c41f365358d80805108d9ee2b20e443fd7a3be3019d5` |
| Scanner-serialized Docker-schema-2 manifest (not OCI platform identity) | `sha256:cf2a71fd08268fc993963cfd2dff2bb6c1ecd90ab857a2534989ff5117f4e5db` |

The supplied `ff97...` identity is an index/local ID, **not** the config digest.
The existing report validator reconciles scanner-native index/config identities
and filesystem DiffIDs; it does not independently establish the actual OCI
platform descriptor. A separate local Docker-save stream verified the hashed
OCI chain **index `ff97...` -> linux/amd64 manifest `abd107...` -> config
`1ffb...`**, including descriptor sizes/media types and all 16 compressed layer
blob hashes/sizes. No image tarball was retained or published. Syft/Grype's
`cf2a...` is the hash of the scanner's serialized Docker-schema-2 manifest,
not the OCI manifest selected by the index. The verified config's
`rootfs.diff_ids` match the scanner layer IDs. The first compressed layer blob
is `774043...`; its distinct uncompressed filesystem DiffID is `34467c...`.
The [identity summary](studio-image-curl-identities.json)
records actual OCI layer blob digests, filesystem DiffIDs and save blob paths
with separate explicit labels, recipe/lock hashes,
base materials, scanner/checksum/database provenance, raw hashes, inspection
timestamps, and coverage limits. These are local artifact identities, not
published registry references.

The [independent review's identity-labeling correction](https://github.com/santosh-sh/EdgeForgeStudio/pull/307#pullrequestreview-5384746925)
was verified on 2026-10-01 at `20:08:24Z`. This corrects provenance labels, not
the scanned artifact or any findings. The research cutoff, frozen raw scanner
reports, family ledger and all 156 observations remain unchanged. No rebuild
or advisory rescan was performed for this correction.

The Dockerfile, locks, `app/` tree, Apache Maven installer and toolchain verifier
have no diff between the tested image source and task base. Later #306 evidence
and merge commits are not mislabeled as tested image source. The Engine archive
commit ID was rechecked; Engine #320 and moving Engine main were not used.
No fresh build was necessary. A rebuild from floating base tags and live APT
repositories would create a new artifact, not recover this digest; even pinning
base digests would not freeze subsequent package resolution.

One baseline inventory/scan used checksum-verified official **Syft 1.52.0**,
**Grype 0.119.0**, and **Trivy 0.74.0**, running on Darwin ARM64 against the
local AMD64 image. Official release/checksum URLs and actual archive/executable
hashes are in the identity summary. Checksum verification does not claim an
independent signature attestation. Public advisory databases were downloaded
once, then frozen; scans were local, external inventory queries disabled, and
Trivy telemetry disabled. No image, SBOM, source, or private inventory was
uploaded.

The final filesystem inventory includes **166 Debian packages, 109 Python
distributions, 52 Java archives**, and copied **JDK 21.0.12.1+1-LTS**. The
validated full baseline retains **1,046 active Grype**, **2,315 ignored Grype**,
**3,356 Trivy Debian**, and **6 Trivy Python** observations. These overlap; do
not add them. Trivy's Java result contains zero findings, not an unsupported
vulnerable result silently discarded. Copied-JDK inventory is not complete
vendor-JDK advisory coverage. Build stages, other platforms, and exploitability
are not cleared. The full baseline and historical findings outside curl remain
open under their own records.

## Family ledger and installed consumers

The [family ledger](studio-image-curl-ledger.json) preserves **78 Grype active,
0 Grype ignored, and 78 Trivy Debian** observations for the three installed
binary packages from source package `curl`, all **7.88.1-10+deb12u15**. There
are **26 advisory identities** and **78 package/advisory groups**, not 78 unique
vulnerabilities. Both scanners identify the same 26 CVEs at this cutoff; no
unmatched or ambiguous family alias remains. Zero ignored family findings is
verified by filtering the full ignored array, not assumed. The rest of the
image's ignored findings remain retained and unresolved.

Every observation has its scanner, active/ignored status, zero-based source
index (and Trivy result index), package index, aliases, original severity and
fix metadata. Groups merge only an identical package type/name/version and an
exact ID or explicit unambiguous CVE alias. Different binaries and TLS backends
remain separate. Scanner severity disagreements remain visible: for example
CVE-2026-8924 is Critical in Grype and Medium in Trivy. Debian status and
upstream affected/fixed ranges are preserved separately from researched
dispositions; none is silently replaced by a scanner suppression.

Offline synthetic `curl_version_info(3)` inspection of **both installed
libraries**, package file lists, `curl --version`, and `ldd` on Git's HTTP
helper establish:

| Binary package | Actual artifact / consumer | Installed features |
|---|---|---|
| `curl` | `/usr/bin/curl` loads `libcurl4` | OpenSSL 3.0.22 |
| `libcurl4` | `libcurl.so.4.8.0`; CLI and potential operator consumers | OpenSSL 3.0.22 |
| `libcurl3-gnutls` | `libcurl-gnutls.so.4.8.0`; Git 2.39.5 HTTP helper | GnuTLS 3.7.9 |

Both libraries report **libssh2 1.10.0**, **zlib 1.2.13**, HTTP/2 and PSL
support, LDAP/LDAPS and SCP/SFTP protocols, and **no HTTP/3**. Neither reports
wolfSSL, wolfSSH, or libssh. Artifact SHA256s and the complete protocol/file
lists are preserved in the identity summary. Loading a library to read its
feature table performs no network transfer or exploit probe.

Source inspection at the task base finds Studio's guarded OpenAPI fetch uses
Python `http.client`/`urllib`, generated-app proxying uses `httpx`, local health
checks use `urllib`, Build & Run launches Maven, and Engine integration uses
local CLI/stdio. These paths do not directly invoke curl. A bounded search of
the frozen Engine core/metadata/generation paths likewise found no direct
curl/libcurl invocation. This does **not** clear operator curl, Git transports,
Maven wrappers, unknown consumers, or every callable library API. HTTP/2,
GSSAPI/Negotiate, cookies, LDAP and SSH remain supported capabilities. Runtime
use of the advisory-specific sequences is unresolved, not proved absent.

## Advisory-specific applicability

The ledger records affected preconditions, Debian Bookworm status and available
upstream fixed ranges for **every** family advisory. Primary sources are the
[Debian curl tracker](https://security-tracker.debian.org/tracker/source-package/curl)
and [curl upstream advisory feed](https://curl.se/docs/vuln.json). The retained
vendor JSON and supporting HTML are hashed; live pages may change after cutoff.

The following narrowly supported conclusions account for **18**
package/advisory groups; all original scanner observations are still present:

| Advisory | Supported conclusion for this exact artifact |
|---|---|
| [CVE-2024-2379](https://curl.se/docs/CVE-2024-2379.html) | All three: requires wolfSSL QUIC (upstream affected release 8.6.0); neither installed library has that backend or HTTP/3. |
| [CVE-2025-0725](https://curl.se/docs/CVE-2025-0725.html) | All three: requires zlib 1.2.0.3 or older; actual libraries report 1.2.13. |
| [CVE-2025-10966](https://curl.se/docs/CVE-2025-10966.html) | All three: requires wolfSSH; actual SSH backend is libssh2. |
| [CVE-2025-15079](https://curl.se/docs/CVE-2025-15079.html), [CVE-2025-15224](https://curl.se/docs/CVE-2025-15224.html) | All three for each: upstream explicitly excludes libssh2; actual libraries use libssh2, not libssh. |
| [CVE-2026-12064](https://curl.se/docs/CVE-2026-12064.html) | Only the two library packages: upstream marks the defect tool-only; neither owns the affected CLI. **The installed curl tool remains open**, so this is not image-level clearance. |
| [CVE-2026-80230](https://curl.se/docs/CVE-2026-80230.html) | Only `libcurl3-gnutls`: upstream limits the affected backend to OpenSSL. OpenSSL CLI/library findings remain open. |

The other **60 package/advisory groups remain open/applicability-unresolved**,
covering **21 advisory identities with at least one open binary package**.
They are not labeled demonstrated exploits or remediated. Exposure could be
lower in particular operator workflows, but the triggering APIs/features were
not ruled out across all image consumers. In particular, PSL is a prerequisite
for CVE-2026-82209, not blanket cookie protection. Debian's PSL mitigation note
for [CVE-2026-8924](https://security-tracker.debian.org/tracker/CVE-2026-8924)
does not establish non-applicability; that issue stays open.

## Maintainer decision package

A disposable container refreshed official Bookworm APT metadata and read
`apt-cache policy` without installing/upgrading any package. All three installed
and candidate versions are **7.88.1-10+deb12u15**; security repository u5 is
older. All 26 Bookworm advisory entries in the retained tracker remain open
with no Bookworm fixed version. Upstream fixed releases/ranges are not a
released compatible Bookworm binary upgrade. The existing Dockerfile already
runs APT upgrade. A redundant recipe edit would not remediate anything.

**Responsible decision owner:** Studio maintainer, with the adopting deployment's
security/risk owner for any exposure/risk decision. No acceptance is delegated
to this report. Ranked next investigations, retaining all High/Critical groups:

| Priority / family | Open identities | Proposed next proof or control, not implemented/accepted |
|---|---|---|
| 1: authentication, proxy and cookie cross-boundary reuse | 11856, 19931, 8927, 8924, 6276, 82209, 8458, 1965, 5545, 6253, 6429 (all CVE-2026) | Map actual Git/operator libcurl credentials, cookies, redirects and pooled handles; segregate identities/proxies, avoid shared credentials/netrc across redirects, and use fresh connections where the vendor recommends them. Cookie restrictions are incomplete mitigations, not a fix. |
| 1: HTTP/2 memory safety | CVE-2026-10536, CVE-2026-18924 | Determine use of stream-dependency/reset/cleanup and shared server-push APIs; require a vendor backport or separately approved targeted control. No absence-of-use claim was proved. |
| 2: TLS/SSH/LDAP integrity | CVE-2026-80230 (OpenSSL), CVE-2026-12064 (CLI), CVE-2026-13608, CVE-2026-8932, CVE-2026-8286 | Keep peer/hostname verification enabled; use explicit SSH schemes and known-host configuration; investigate SASL/mTLS/STARTTLS reuse. These do not resolve every identity. |
| 3: remaining protocol/SSH behavior | CVE-2026-4873, CVE-2026-9547, CVE-2025-14017 | Check mixed clear/TLS protocol pools, SSH callbacks and multithreaded LDAPS TLS-option changes. Keep findings visible pending evidence. |

Smallest follow-up options, requiring a separate assignment/decision:

1. **Preferred compatible path:** wait for an official Bookworm backport, then
   rebuild and verify exact package/vendor deltas with the same DB snapshot and
   representative curl/Git TLS transports plus image launch/Build & Run proof.
   Waiting is not acceptance of current risk or authorization to publish.
2. **If cadence is insufficient:** evaluate a supported distribution or vendor
   package transition under a new design. Repository, ABI/dependency, Python
   3.11, JDK/Maven, Git/TLS and deployment compatibility costs must be assessed.
   No mixed repositories, private curl build, manual library swap or feature
   removal is approved here; a newer distribution alone may still have findings.
3. **Interim operator restrictions:** propose verified workflow-specific controls
   above and a bounded exposure decision to the responsible owner. Do not turn
   untested mitigations, Debian `no-dsa`/`postponed`, or scanner `wont-fix` into
   a supported-not-affected conclusion or accepted residual risk.

Review triggers: a newer official Bookworm candidate/backport; an upstream
affected-range correction; changed TLS/SSH/protocol build features; a new
Git/operator credential, cookie, proxy or libcurl use; a materially changed
advisory snapshot; or selection of the final Studio/Engine release pair. That
pair still requires rebuild/reassessment. No recurring scan is created here.

## Out-of-scope changes observed

Trivy reports imported-SBOM `urllib3 2.7.0` alerts **CVE-2026-97687,
CVE-2026-97688, CVE-2026-97689** in this dated baseline, alongside imported
`msgpack 1.1.2` / `setuptools 70.3.0` alerts. All six Python observations,
source indices, fix metadata and unresolved inventory identities are retained
in the identity summary. Their artifact presence/applicability was not
investigated in this curl slice. Absence from standalone inventories is not
proof of absence; they remain **open/unassessed**, not accepted or cleared.
Prior dated evidence and all other families are unchanged.

## Reproduction and retention

Raw reports, SBOM, frozen DBs, official scanner archives/checksum lists, vendor
snapshots and inspection outputs are retained locally under the task-owned
directory basename `edgeforge-studio-curl-s1-proof`. Request the hash-identified
files from the maintainer/build observer before temporary storage cleanup.
The small `oci-identity-proof.json` retains the original index, platform-manifest
and config JSON bytes in base64 plus verified descriptor/layer metadata;
`verify_oci_archive.py` is the retained streaming reader. Their hashes are in
the identity summary. They contain no layer payload or image tar. To repeat
the local identity inspection, stream the exact local ID into that reader:

```bash
docker image save sha256:ff97fb0ee901e2e759d2143fee83538ac1ffeb17248c745a8f3287e9ca264c89 \
  | python3.11 "$CURL_EVIDENCE_ROOT/verify_oci_archive.py" > oci-identity-proof.json
```

Verify SHA256 of the retained index bytes equals `ff97...`, follow its sole
linux/amd64 descriptor, and verify the selected manifest bytes hash to
`abd107...` and reference config `1ffb...`. Compare ordered OCI layer blob
digests/sizes with the archive blobs, and config `rootfs.diff_ids` with scanner
layer IDs. Independently decode/hash Syft `source.metadata.manifest` to verify
the separately labeled `cf2a...` representation and Docker-schema-2 media type.
The reader's capture timestamp can change; descriptor identities must not.

The original #306 build receipt and frozen Engine archive are retained with
that task's inputs; their hashes are in the identity summary. There is no
public raw download or guaranteed retention SLA. No raw inventory, DB, cache,
source tree, image tar, credential or host-specific path is committed.

Use the [existing local assessment procedure](studio-image-assessment.md#reproduce-locally)
to obtain the official scanner artifacts, verifying the recorded checksums.
For exact replay, use the **recorded local artifact and frozen DB files**, not
new builds or freshly downloaded databases. Set `CURL_EVIDENCE_ROOT` to the
retained directory and run from this PR's checkout. Scan commands used once:

```bash
SYFT_CHECK_FOR_APP_UPDATE=false "$CURL_EVIDENCE_ROOT/tools/syft" scan \
  docker:edgeforge-studio-pyjwt-s1:candidate --platform linux/amd64 \
  --output "syft-json=$CURL_EVIDENCE_ROOT/syft.json"
GRYPE_DB_CACHE_DIR="$CURL_EVIDENCE_ROOT/grype-db" GRYPE_DB_AUTO_UPDATE=false \
  GRYPE_CHECK_FOR_APP_UPDATE=false GRYPE_EXTERNAL_SOURCES_ENABLE=false \
  "$CURL_EVIDENCE_ROOT/tools/grype" "sbom:$CURL_EVIDENCE_ROOT/syft.json" \
  --output json --file "$CURL_EVIDENCE_ROOT/grype.json"
"$CURL_EVIDENCE_ROOT/tools/trivy" image --cache-dir "$CURL_EVIDENCE_ROOT/trivy-cache" \
  --image-src docker --platform linux/amd64 --offline-scan --skip-db-update \
  --skip-java-db-update --skip-check-update --skip-version-check --disable-telemetry \
  --scanners vuln --format json --output "$CURL_EVIDENCE_ROOT/trivy.json" \
  edgeforge-studio-pyjwt-s1:candidate
```

No repeat advisory scan is needed for evidence review. Replay retained inputs:

```bash
python3.11 scripts/image_assessment_report.py --syft "$CURL_EVIDENCE_ROOT/syft.json" \
  --grype "$CURL_EVIDENCE_ROOT/grype.json" --trivy "$CURL_EVIDENCE_ROOT/trivy.json" \
  --output "$CURL_EVIDENCE_ROOT/replayed-summary.json"
python3.11 -m scripts.image_findings_ledger --syft "$CURL_EVIDENCE_ROOT/syft.json" \
  --grype "$CURL_EVIDENCE_ROOT/grype.json" --trivy "$CURL_EVIDENCE_ROOT/trivy.json" \
  --output "$CURL_EVIDENCE_ROOT/replayed-full-ledger.json"
```

Compare the replayed summary/full ledger byte-for-byte with the hash-recorded
retained outputs. For the committed family projection, select components where
Syft's Debian `metadata.source` (or package name when empty) is `curl`; filter
every active/ignored/Trivy observation and reindex component and group references.
Compare all observation fields and group identity/reference fields, not only
counts. Authored vendor research/dispositions are reviewed against the retained
primary snapshots and feature proof, not regenerated as automatic clean results.

Offline feature probe used:
`docker run --rm -i --network none --platform linux/amd64 edgeforge-studio-pyjwt-s1:candidate python - < inspect_curl.py`.
The retained probe reads `curl_version_info(3)` through ctypes, package file
lists and artifact hashes; it does not alter packages. The separate disposable
APT metadata container was root only for metadata refresh, then removed; the
assessed image/non-root deployment was unchanged.

## Validation and handoff

Executed here: report/ledger identity and coverage validation, full-to-family
observation reconciliation, frozen vendor/feature checks, deterministic evidence
regeneration and replay, a dropped-observation negative control, documentation
links and diff hygiene. Existing report/ledger integrity tests: **36 passed**.
No tests added merely to mirror document wording or package pins.

For the identity-label correction, the local archive inspection verified the
OCI index/platform/config descriptor chain and every compressed layer blob
hash/size. Two additional temporary evidence-integrity negative controls reject
the scanner-serialized manifest substituted for the OCI platform manifest and
filesystem DiffIDs substituted for layer blob digests. The **36 existing tests
passed again**; raw report/full-ledger replay and family ledger are byte-identical
to the reviewed inputs. No production/test changes or fresh scans were needed.

Reused, not rerun: [#306's dated functional proof](studio-pyjwt-audit-followup.md)
at source `f22f941...`: **2,205 passed, 17 skipped, 29 deselected** non-smoke;
**72 passed** focused; **1 passed** L2; **1 passed** actual non-root Docker
launch/import smoke without source mounts; real frozen-Engine stdio returned
six profiles. The 17 environment skips are not new executed proof. No fresh
Maven matrix, exploit transfer, font experiment, full L5, generated-image scan,
or final-pair certification is claimed for this evidence-only delivery. The
disclosed lean-image font limitation and PyJWT/Maven controls are unchanged.

Required exact-head PR CI and independent review are subsequent handoff gates;
their actual outcome belongs to the PR, not an invented result in this dated
report. The 60 open curl groups, other families and broader maintainer decisions
remain open after completion of this investigation. Human merge is separate.
