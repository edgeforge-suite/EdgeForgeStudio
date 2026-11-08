# Studio handover evidence

> **Evidence navigation, not acceptance.** This index links dated observations
> and their supporting artifacts. A merged report, current green CI or this
> wording update does not renew an old scan or approve release/deployment.
>
> **Honest by design.** Where an underlying doc says *pending / adopter-decides /
> post-import / by-design*, this index says the **same**. The consolidated open list
> is [below](#responsibilities-and-open-decisions).
>
> **Index checked:** 2026-10-25; current preparation starts at Studio `74e065a`. Studio is part of a multi-repo suite; this pack covers
> the **Studio** repository. What Studio does and how to run it: [`README.md`](../../README.md).

## What this pack is

This pack helps maintainers trace corrections and remaining decisions,
contributors reproduce bounded results, users understand supported behavior and
limitations, and enterprise adopters assess their chosen artifacts/deployment.
It is not restricted to an enterprise import checklist and does not transfer
project publication responsibilities to an adopter.

Studio ships local single-user mode and shared **anonymous session isolation**.
Real proxy/OIDC identity remains deferred. It authors/reviews manifest packages
and invokes Engine; generated applications are standalone. See the
[current scope](../../README.md#what-edgeforge-does-and-doesnt-do) and
[operator contract](../deployment-model.md).

For each record, read its observation date, tested source/Engine revisions,
artifact/platform identity, tool/checksum/database cutoff and stated exclusions.
The report's source SHA may precede later evidence-only commits: do not relabel
it as a run of the final merge or selected release. A package inventory, a
source-based assertion and executed runtime proof answer different questions.

## Concern → evidence

The [2026-11-02 public-content preparation](../public-content-preparation.md)
is the current 95-package dependency observation (joserfc 1.7.6 only), with
independent fixture replacements, real frozen-Engine generation and bounded
Java 17/H2 proof. It does not reassign earlier results to replacement inputs
or refresh historical images. Raw inputs/logs are private, not clone-local proof.

The preceding [2026-10-28 Authlib/dnspython correction](studio-audit-correction-2026-10-28.md)
and [compact receipt](studio-audit-correction-2026-10-28.json) record that dated
95-package reference-dependency observation. They preserve the project-intent
documentation and historical images, and add separate clean Python 3.11/3.13
host compatibility checks, not a new image campaign or release acceptance.

The [2026-10-25 private source preparation](studio-source-preparation-2026-10-25.md)
and [compact identity/proof receipt](studio-source-preparation-2026-10-25.json)
are the preceding dependency/image observation: four changed reference pins,
95-package reference and 94-package image strict audits, actual non-root image
and Engine proof, and a complete-with-findings assessment. The dated rows below
retain their original versions/counts; they are not current-graph claims.
Apache-2.0/DCO and selected-but-unverified reporting routes supersede earlier
unresolved terms/contact choices only as described in the
[publication record](../publication-preparation.md).

The [2026-10-17 cached-URL fixture correction](studio-cached-url-proof-2026-10-17.md)
records real CLI/strict-MCP ingestion and source-label proof plus absent-operation
refusal against a frozen Engine. It does not retroactively change #316's failed
fixture observation or establish image/release acceptance.

| Import-review concern | Evidence (authoritative — click through) | Honest status |
|---|---|---|
| **License & dependencies** | [`dependencies.md`](dependencies.md) (cover) · [MCP correction and fresh-image proof](studio-mcp-correction-2026-10-15.md) · [historical PyJWT follow-up](studio-pyjwt-audit-followup.md) · [`sbom.cdx.json`](sbom.cdx.json) (CycloneDX) · [`dependency-licenses.md`](dependency-licenses.md) / [`.csv`](dependency-licenses.csv) / [`dependency-licenses-transitive.csv`](dependency-licenses-transitive.csv) (G4) · [`pip-audit.md`](pip-audit.md) / [`.json`](pip-audit.json) | The 2026-10-15 reference SBOM, licenses and strict audit cover 95 pins with zero known findings at that observation; the fresh image's 94 distributions are separately audited. MCP alone changes to 1.30.0; FastMCP stays 3.4.0. Declared-license scope is permissive; transitive flags include `caio` UNKNOWN and `certifi` MPL-2.0. Strict audit remains blocking, not whole-image/application clearance. Terms and artifact-specific decisions remain in the publication record. |
| **Studio Docker image** | [`studio-image-assessment.md`](studio-image-assessment.md) · [sanitized findings summary](studio-image-assessment-summary.json) · [triage and ranked follow-ups](studio-image-triage.md) · [normalized findings ledger](studio-image-findings-ledger.json) | **Assessment and bounded triage complete with open findings, not M2 clearance.** One `linux/amd64` build from pinned Studio/Engine inputs was inventoried across Debian, Python, Maven archives and the copied JDK; a final-pair rebuild and risk decision remain separate. The Python-only audit above does not cover these image layers. |
| **Studio Maven image remediation** | [dated before/after proof and font/prebuilt limits](studio-maven-image-remediation.md) · [artifact identities](studio-maven-image-identities.json) · [control summary](studio-maven-image-control-summary.json) · [candidate summary](studio-maven-image-candidate-summary.json) | Verified Apache Maven 3.9.16 replaces Debian Maven; the identified candidate's two targeted Guava advisories are remediated. **Untargeted findings remain open; not M2 clearance.** The independent review observed unavailable Java font metrics in that lean candidate. Its historical frozen Engine input and Java 17/21, Boot 3/jobless Boot 4.1 Build & Run proof remain bound to that candidate; final release pairing still requires reassessment. |
| **Certifi/Pillow correction** | [2026-10-20 proof](studio-certifi-pillow-fix-2026-10-20.md) · [identity/reference/hash record](studio-certifi-pillow-fix-2026-10-20.json) | Supported host Python 3.11 and actual Python 3.13 image correction for standalone certifi/Pillow; complete strict graphs pass. Pip-private/ensurepip and other image residuals remain OPEN. No M2 or release clearance. |
| **Studio curl-family decision package** | [dated applicability and maintainer options](studio-image-curl-disposition.md) · [family ledger](studio-image-curl-ledger.json) · [artifact/database identities](studio-image-curl-identities.json) | **Delivery B: complete assessment with open findings, not M2 clearance or risk acceptance.** The retained #306 AMD64 image has no newer compatible official Bookworm curl candidate at the 2026-10-01 cutoff. All 156 cross-scanner observations remain: 18 package/advisory groups have supported inapplicability conclusions, 60 remain open. No package/image change or publication is claimed. |
| **Consolidated Studio image disposition** | [2026-10-02 decision package](studio-image-consolidated-disposition.md) · [lossless all-family ledger](studio-image-consolidated-ledger.json) · [verified identities](studio-image-consolidated-identities.json) · [embedded/native map](studio-image-consolidated-native.json) | **Phase 1 complete bounded decision package with open findings, not risk acceptance or M2 clearance.** Reuses the verified #306 image and frozen October 1 advisory cutoff; retains all active/ignored/unresolved identities and exactly #307's 18 exclusions/60 open curl groups. Expat has an unapplied Bookworm-backport candidate. No recipe change, fresh scan or Phase 2 caller-handoff proof is claimed. |
| **Fresh Studio image / Expat follow-up** | [2026-10-04 refresh proof](studio-image-refresh-2026-10-04.md) · [identities and commands](studio-image-refresh-2026-10-04-identities.json) · [reduced SBOM/findings summary](studio-image-refresh-2026-10-04-summary.json) · [lossless current ledger](studio-image-refresh-2026-10-04-ledger.json) · [historical/current delta](studio-image-refresh-2026-10-04-delta.json) | **Fresh AMD64 assessment with open findings; builder evidence, not approval or M2 clearance.** Actual Bookworm Expat u4 matches the official library bytes and fixes ten historical groups; five system groups and embedded-copy applicability remain open. Two frozen-database passes, non-root startup and real Boot 4.1.1 jobless H2 Build & Run passed. Historical records are preserved; no automatic carryforward of eighteen curl exclusions. Required final-head CI/review are separate gates. |
| **Bounded Studio runtime follow-up** | [2026-10-08 CPython/vendor/JDK investigation](studio-image-runtime-2026-10-08.md) · [artifact-bound inputs](studio-image-runtime-2026-10-08-inputs.json) · [replayable dispositions](studio-image-runtime-2026-10-08-results.json) | **32 frozen identities: 11 OPEN, 21 supported-not-affected; not M2 clearance.** Reuses the exact #310 AMD64 artifact, preserves history and accounts for 11 active/bootstrap code copies. No image or dependency change; released-bundle/backport and embedded-Expat decisions remain open. Current-pair reassessment remains separate. |
| **Bundle P image transition** | [2026-10-11 proof, retention and reproduction](studio-image-bundle-p-2026-10-11.md) · [receipt](studio-image-bundle-p-2026-10-11-receipt.json) · [summary](studio-image-bundle-p-2026-10-11-summary.json) · [lossless ledger](studio-image-bundle-p-2026-10-11-ledger.json) · [inherited-identity delta](studio-image-bundle-p-2026-10-11-delta.json) | **Python 3.13.16 / Bookworm partial correction, not M2 clearance.** Actual AMD64 build, offline bootstrap, non-root startup and Studio-to-Engine account create/read/build proof; host Python 3.11 retained. Three scoped corrections, fourteen supported dispositions and fifteen OPEN identities; 21 old bootstrap associations remain separately traceable with successor review outstanding. Private raw inputs are durably retained; final release pairing and remaining OS/native/build dispositions remain open. |
| **Current-pair residual proof** | [2026-10-14 campaign, coverage and next decisions](studio-image-residual-2026-10-14.md) · [identity/proof receipt](studio-image-residual-2026-10-14-receipt.json) · [final ledger](studio-image-residual-2026-10-14-ledger.json) · [whole-stage coverage](studio-image-residual-2026-10-14-stages.json) · [supported outcomes](studio-image-residual-2026-10-14-outcomes.json) · [owner queue](studio-image-residual-2026-10-14-queue.json) | **Fresh provisional AMD64 assessment, not M2 clearance.** Unchanged approved recipe; final image and complete JDK/Maven stage snapshots, native/vendor/seed evidence and full FS Build & Run. The inherited 32-identity set has three prior remediations, 21 supported conclusions and eight OPEN identities; tempfile remains OPEN after review correction. The 21 historical bootstrap associations are separately evaluated against successors. Other OS/native/build findings, opaque/transient coverage and final release-pair decisions remain open. Historical replay limitations are preserved. |
| **Residual decision proposal** | [2026-10-20 decisions and #319 resume](studio-image-residual-decisions-2026-10-20.md) · [compact historical/current identity projection](studio-image-residual-decisions-2026-10-20.json) | **Revision 2: six UNAPPROVED proposals; no new documentation-created closures or M2/risk acceptance.** Preserves the historical queue/outcomes and failed handoff; separately inherits #319 standalone corrections, maps all 313 new OPEN groups and changed Pillow native copies. Private/seed certifi remains OPEN; current mains are UNBUILT context, with final-pair proof and resume CI/review separate. |
| **Secrets & real data** | [`secret-and-data-scan.md`](secret-and-data-scan.md) · [`secret-scan` workflow](../../.github/workflows/secret-scan.yml) (G3) | Dated clean observations and synthetic-data policy; pinned gitleaks `8.30.1` runs on PRs/main pushes. No fresh unrestricted history scan is claimed by this prose update. Generated/session output stays out of Git. |
| **Compliance & portability** | [`compliance-and-portability.md`](../compliance-and-portability.md) (G7) | Source-based answers with dates/limits. Guarded user-directed fetch; optional KS and build/dependency tools have separate boundaries. Two runtime modes ship; audit identity is anonymous session-level. Upload/paste does not alone prove every downstream workflow offline. |
| **Security boundaries & attack surface** | [`security-boundary-map.md`](../security-boundary-map.md) (G8) | **Mapped + verified, two postures.** **Local single-user** (default): no auth (keep on `localhost`), Build & Run on, Engine CLI unconstrained. **Shared multi-session**: identity seam + CSRF, server-owned per-session paths, **every Engine call root-constrained fail-closed (F1)**, per-session KS DB, audit + ownership, quotas + retention, Build & Run **server-disabled**. Both: **no `shell=True`** (arg-list), data-only YAML loaders (PyYAML `safe_load`, plus ruamel round-trip mode for comment-preserving CSV edits), no CORS, upload-size cap, guarded OpenAPI fetch. Open: project-owned proxy/OIDC identity and RBAC integration; operators own gateway/IdP configuration and access policy. Single-replica contract. |
| **Deployment model** | [`deployment-model.md`](../deployment-model.md) | **Operator contract.** How to run each posture, the full flag matrix, the cross-repo Engine root-constraint contract (`EDGEFORGE_MCP_ALLOWED_ROOTS` + `EDGEFORGE_SHARED_MODE`), single-replica, and what's deferred (SSO/OIDC wiring, RBAC, multi-replica HA, regen-preview fast-follow). |
| **Governance files** | [`CONTRIBUTING.md`](../../CONTRIBUTING.md) · [`SECURITY.md`](../../SECURITY.md) · [issue chooser](../../.github/ISSUE_TEMPLATE/config.yml) · [PR template](../../.github/pull_request_template.md) | Apache-2.0/NOTICE and DCO 1.1 selected; no CLA. PVR/email routes selected but activation/reachability unverified. CODEOWNERS remains a commented template; maintainer publication authorization remains pending. |
| **CI evidence** | [`secret-scan.yml`](../../.github/workflows/secret-scan.yml) · [`pytest-ci.yml`](../../.github/workflows/pytest-ci.yml) | Inspect the actual target SHA/checks. Non-empty non-smoke and L2 tests plus strict constraints audit are required; Ruff remains advisory. Documentation CI does not rerun cross-repo runtime/image/native accessibility proof. |

### Dated caller-boundary proof

[Studio adversarial handoff](studio-adversarial-handoff.md) and its
[sanitized receipt](studio-adversarial-handoff-receipt.json) add request-driven
anonymous-session proof with archived Engine/KS children. The
[regen repair receipt](studio-adversarial-regen-repair-receipt.json) extends the
shared package preflight to preview/apply's export and managed-package inputs,
including direct adapter entrypoints; successful regen intentionally uses CLI,
while shared generation stays MCP-only. Package/KS symlink checks precede the
covered content access/child invocation. Static preflight and Engine nested-input
limits remain explicit; this is builder evidence, not independent approval or
final-pair release clearance.

## Responsibilities and open decisions

The [single publication decision list](../publication-preparation.md#remaining-maintainer-decisions)
owns current license/ownership/inbound terms, verified private reporting,
third-party artifact questions, image residual decisions and selected release
metadata. Earlier import-oriented tags in linked records do not assign public
project governance or security responsibilities to an adopter.

| Open item | Tag | Where it's authoritative |
|---|---|---|
| **Authentication** — local has none; shared identity is anonymous signed-cookie isolation. Real proxy/OIDC integration remains pending project work; gateway/IdP policy is operator-owned. | Implemented isolation / deferred identity | [deployment-model §3](../deployment-model.md#3-shared-multi-session-authoring-service) |
| **OpenAPI URL fetch guarded (mode-aware)** — each hop resolves once and connects only to validated, pinned addresses while retaining Host/SNI/certificate checks and verifying the peer; proxies are disabled, redirects are revalidated, and responses default to a 5 MiB cap plus one 10-second end-to-end deadline. Exact allowlisting can authorize private services but never metadata/special addresses; shared loopback stays forbidden and local loopback stays supported. Studio binds guarded responses into Engine's normal `spec_url` fetch seam through a root-confined, fail-closed cache, preventing child-policy drift without changing URL-origin ingestion or generated source labels. Use upload/paste for air-gap. | `[closed-now]` | [G8 §3b](../security-boundary-map.md#3-attack-surfaces-per-component) · [G7 §7](../compliance-and-portability.md#7-portability) |
| **Upload request bounds + type policy implemented** — Step 2 OpenAPI upload, project-open JSON upload, and `/knowledge/upload` have a 50 MiB default per-file reader plus a fixed 1 MiB multipart-envelope allowance (51 MiB total by default). Valid oversize `Content-Length` is refused before reading; chunked requests stop at the same total. These local/shared policies require multipart envelopes and allowlisted extensions/file-part MIME values, while parsers still validate actual content. | `[closed-now]` | [G8 §3b](../security-boundary-map.md#3-attack-surfaces-per-component) |
| **Local Build & Run code execution** — builds/runs a generated app locally at operator direction; non-prod, local-dev. | `[by-design]` | [G8 §5.5](../security-boundary-map.md#5-honest-open-items--recommendations) |
| **At-rest local files cleartext** — output/session unencrypted; use host filesystem encryption for sensitive content. | `[adopter-decides]` (host posture) | [G8 §5.6](../security-boundary-map.md#5-honest-open-items--recommendations) |
| **A11y-01** — one FAIL, three NOT RUN; four native exact-speech cases still required, automated checks binding and audience-accessible disclosure mandatory for an authorized release/demo. | Open known limitation / Studio-owned | [observation](../studio-ux-refresh/pr24a-a11y-walkthrough.md#a11y-01-v5-deferral-evidence) |
| **Font support and image coverage** — lean Java image lacks font rendering by default; scanner ignored matches and vendor/embedded-copy exclusions remain unresolved unless explicitly supported. #311 is a disposition package, not a corrected image. | Open limitations | [Maven/font record](studio-maven-image-remediation.md) · [runtime S2](studio-image-runtime-2026-10-08.md) |
| **Full threat model** | `[post-import]` | [G8 §5.7](../security-boundary-map.md#5-honest-open-items--recommendations) |

Adopters own their approved imports/data, host encryption, gateway, backups and
application authorization. Project-owned source/CI/terms/security decisions
are not discharged by an adopter performing a local assessment.

## Reproduce the evidence yourself

- **SBOM + license / vulnerability evidence (G4):** `make sbom` (pinned
  `cyclonedx-py`, `pip-licenses`, and `pip-audit` in an isolated venv)
  regenerates the resolved SBOM, declared/transitive license inventories, and
  vulnerability scan. It makes a **new dated observation** using current public
  feeds/resolution, not a byte-for-byte replay of September's historical result.
- **Studio image assessment:** follow the local-only, pinned-tool procedure in
  [`studio-image-assessment.md`](studio-image-assessment.md); do not treat its open
  findings as a clean scan or a release-image acceptance.
- **Secret scan (G3):** runs automatically in CI
  ([`secret-scan.yml`](../../.github/workflows/secret-scan.yml)); locally,
  `gitleaks dir . --redact --exit-code 1` with pinned `8.30.1`.
- **Tests:** `make test` / `pytest tests/` locally. CI runs the non-smoke suite
  and the in-process L2 smoke with explicit non-zero collection guards; cross-repo
  Engine/JDK smokes remain manual/skip-guarded.

### Replay availability and refresh triggers

- **#310 image refresh:** its identity/summary/ledger/delta are sanitized projections.
  Exact replay also needs the retained private image/OCI blobs, raw scanner
  reports, frozen databases, vendor/native inputs and task-local scripts including
  `build_evidence.py`. There is no public raw download or retention SLA. A clean
  clone alone cannot regenerate the owner projection; the
  [availability section](studio-image-refresh-2026-10-04.md#reproduction-and-retention)
  states the boundary. Missing inputs mean exact replay is unavailable, not a clean scan.
- **#311 runtime S2:** committed inputs and
  [`image_runtime_dispositions.py`](../../scripts/image_runtime_dispositions.py)
  replay the decision reduction under the
  [recorded procedure](studio-image-runtime-2026-10-08.md#replay-proof-and-limitations).
  They do not reconstruct the old image, scanners or retained raw campaign. No
  new corrected image/build/scan was delivered; frozen and newly encountered
  OPEN associations and JDK coverage exclusion stay visible.
- **#312 newcomer:** the [dated report](../test-results/newcomer-journey-2026-10-09.md)
  and receipts prove one supported reference route/terminal journey with
  designated developer-owned preservation. Reproduction needs clean compatible
  Studio/Engine sources and declared Python/JDK/Maven prerequisites. Final
  selected-release applicability/re-proof remains separate.

Preserve historical filenames/dates/results. Refresh applicable proof after
material source/Engine/profile/runtime changes, a changed image digest/base/
package/vendor copy, scanner/tool/database/advisory cutoff changes, or altered
deployment/security boundaries. New policy/terms/contact or target audience
also requires content review. Record new identities and dates rather than
silently replacing an old conclusion. Publish only necessary sanitized evidence;
do not upload private inventories, source archives, raw logs or credentials to
make reproduction appear complete.

## Where to go next

- **What Studio does / how to run it:** [`README.md`](../../README.md)
- **Compliance answer-sheet:** [`compliance-and-portability.md`](../compliance-and-portability.md) (G7)
- **Security boundary map:** [`security-boundary-map.md`](../security-boundary-map.md) (G8)
- **Authoritative rules:** [`CONTRIBUTING.md`](../../CONTRIBUTING.md)
