# Studio image residual decisions - 2026-10-20

**EF-V5-M2-STUDIO-RESIDUAL-DISPOSITIONS-S1, revision 2. Additive PR318 resume
after #319; six decision packages remain UNAPPROVED proposals.** This document
creates no new technical closures: `new_closed_dispositions` stays empty.
The separate `inherited_319` record recognizes only #319's bounded standalone
corrections. No risk acceptance, M2 clearance or selected-release acceptance.

## Resume After #319

The [#319 correction record](studio-certifi-pillow-fix-2026-10-20.md) and its
[machine evidence](studio-certifi-pillow-fix-2026-10-20.json) supply the existing
verified proof, not new proof run by this resume. The projection's `resume`
overlay and scoped `resume.source_catalog` bind that committed record and private
`final-ledger.json`, `delta.json`, `new-observations.json`, `native-delta.json`,
scanner streams and baseline audit. New private catalog hashes are checked against
#319's committed `private_sha256`; raw reports are not copied into this document.
Original family/native vectors and all sections under **Preserved Revision 1
Record** below retain their historical artifacts, dates and bounded conclusions.

### Identity And Dated Handoff

Original parked head **`a6f8cc80d048065f74073bcd474b9aeac55711f5`**, entry Studio
`8f416a80a0ab30f0998b0abceec3accb152b94a7` / Engine
`ca53afb40ac9ba67d74f9d27c2d52e63b909970c`, and the sealed private packet
**Studio-Residual-Dispositions-2026-10-20** remain unchanged. The historical
[required audit failure](https://github.com/santosh-sh/EdgeForgeStudio/actions/runs/39498938191)
and incomplete/not-merge-ready handoff are preserved, not rewritten as passes.
The dated October 20 Astra content APPROVE applied only to `a6f8cc8`, retained the
CI blocker, and is **not final approval** of this resume or a later head. Hash-bound
private `incomplete-handoff.md` and `review-r0.md` remain in the original packet.

Current Studio main **`112b229a1a586d833265a09d850b2f72f12a044d`** and Engine
main **`417e224e18fa6069b48a77e89cbd574c73f21538`** are separate **UNBUILT
context**, not a tested/selected pair. Local merge
`15f0cedb46750cb52ebf62c6c661a0afbe4e580d` preserves the parked record.
Entry main CI runs `39533664477` / `39533664416` passed; they do not approve the
resume head or replace its exact-head CI and independent review.

| #319 tested identity only | Exact value |
|---|---|
| Studio code | `529ec2d113fb619b2db94dacd0a541809c3818ce` |
| Engine snapshot | `ca53afb40ac9ba67d74f9d27c2d52e63b909970c` |
| OCI index/local artifact | `sha256:ade363aed9b85edc8e493bf1f62745fe501c95116ecb7569571a4c1a4022206c` |
| Linux/AMD64 platform manifest | `sha256:29db810e476c3e0aac31b5fcf5583e59555f3cbbc0ed7142b670d624d34d2ca3` |
| Configuration | `sha256:73d2cdd1cdf7b47cc9c27f4c4511e3c7fdbbc038fec776771a1e0232a4d0794b` |

Do not relabel that image as delivery `b1d0503`, merge `112b229`, local merge
`15f0ced`, or current Engine `417e224`. D6 still requires separately
selected-pair proof and authority; source drift is not runtime equivalence.

### Bounded Corrections And Accounting

#319 corrects the **nine original standalone audit observations** using
**certifi 2026.10.19 / Pillow 13.0.0**. The baseline certifi audit identity is
**PYSEC-2026-4320**, alias **GHSA-6q48-6c7w-9gw2**; the projection preserves the
baseline IDs/aliases separately from the advisory and image-scanner identities.
Actual supported host **Python 3.11** and image **Python 3.13** proof, including
complete **95-reference / 94-image strict audits with zero findings and zero
omissions**, belongs to #319. Its synthetic compatibility/caller checks are not
an exploit corpus, all-native clearance or a renewed whole-image acceptance.

| Retained ledger accounting | Groups / observations |
|---|---|
| Historical October 14 | **3,528 / 7,005** |
| #319 current artifact/database | **3,840 / 7,663** |
| Group identity join | **3,527 persist + 313 new; one old group silent** |
| Current observation streams | **1,050 active + 2,775 ignored Grype; 3,831 Debian + seven unresolved Python Trivy** |

These are overlapping groups/observations, **not unique vulnerability totals**.
`resume.accounting.persisting_runs` maps every retained old group index to its
#319 group index without renumbering the old queue. `new_groups` enumerates every
one of the **313 OPEN** groups with component/version, advisory ID, current group
index, private new-observations row, ledger observation index and raw source/result
indexes. The hash-bound ledger retains aliases, fixes, severities and ignore rules.

| New OPEN membership | Package / count | Proposed route |
|---|---|---|
| Headers | linux-libc-dev 6.1.187-1 / **305** | D4, extending historical `debian:linux` only by overlay |
| RPC | libtirpc3, libtirpc-dev, libtirpc-common 1.3.3+ds-1 / **two each, six total** | D4 overlay; caller applicability unproved |
| OS trust store | ca-certificates 20250419~deb12u1 / **one, DLA-4845-1** | D4 overlay; separate from standalone certifi |
| Imported embedded certifi match | certifi 2026.6.17 / **one, GHSA-6q48-6c7w-9gw2** | D1 overlay; still OPEN |

The **312 OS groups are new database matches on unchanged versions, package-file
manifests and original payload layers**, not introduced/worsened component content.
#319's `assessment.scope_analysis` binds that comparison; it does not prove
applicability or correction. Header metadata is not host-kernel evidence.
Old group **2285**, linux-libc-dev / **CVE-2026-89603**, is silent in #319 but
**remains OPEN**. Silence is not remediation or acceptance.

### Selective Package Overlay

**D1:** #319 confirms active pip26.2.1 private certifi and the independent
ensurepip pip26.2.1 seed both retain **2026.06.17** (normalized **2026.6.17**),
G3 and bundle SHA-256
`bbc7e9c01d7551bb8a159b5dedd989b8ee3ce105aff522b68eb1b01bf854cab0`:
**OPEN**. Private urllib3's three findings remain OPEN. Imported certifi group
**3833**, component **95**, is **inventory-unresolved** in the ledger; the two
actual copies are separately confirmed by #319 copy inspection, not inferred from
that one group or counted as two new groups. The prior **21 bootstrap** conclusions
do **not** dispose of the new certifi advisory. Historical pip26.2.2 inspection
established unchanged **urllib3** bytes only, not its private certifi outcome:
certifi containing-artifact suitability remains **UNKNOWN**, with no fresh
research in this resume. The old ineffective-bump conclusion is urllib3-specific.

**D3:** Pillow's **eight changed native extensions** and **18 bundled libraries**
remain separate applicability obligations. #319's `native-delta.json` binds every
extension's old/new hashes and every bundled-library path/hash, with linkage in its
native evidence. libjpeg-turbo changes **3.1.4.1 -> 3.2.0**, libtiff
**4.7.1 -> 4.7.2**. Unchanged feature-version strings do not establish byte identity
or clearance. The eight package-level Pillow corrections do not settle all native
advisories/callers; other TLS/private-native gaps remain OPEN.

**D4** adds only the explicit OS-match overlay above; the old header candidate is
still a dated lead, not re-researched or installed. **D2/D5** keep their original
CPython/Expat questions, **423 JDK + 262 Maven = 685 OPEN stage groups**, and
native/transient/static/shaded/opaque gaps. No new whole-stage proof is claimed.
**D6** retains final selected-pair proof, retention/replay and authority gates.

All six existing packages, old queue memberships, IDs and scoped **32 runtime /
21 bootstrap / 18 curl / 12 JDK / Expat** conclusions remain intact at their
original artifacts and cutoffs. Missing #310 raw-history limitations remain.
Proposed owner `santosh-sh` and **2026-10-27** review date remain **UNAPPROVED**,
not accepted assignments or residual waivers. Host3.11/image3.13, KA default OFF,
manifest2.0 / snapshot1.4, font limitations, runtime modes and A11y-01
**one FAIL / three NOT RUN** are unchanged; no all-embedded or accessibility
clearance, publication, release or new implementation is authorized.

## Revision 2 Validation Status

The resume method is retained-file/static delta inspection and narrow JSON
projection/hash joins only. **No new build, installation, runtime, scan, audit or
upstream research.** The historical **161 tests / 95 links / eight negative
controls** below belong to revision 1 and are not claimed as new resume checks.
Final resume validation, CI and review are recorded in the separate exact-head
handoff, not this self-referential record. No final pass or approval is asserted
here. Resume receipts are separate from the original sealed
packet; neither that packet nor its original generator is modified.

## Preserved Revision 1 Record

The following original proposal and validation/retention account are historical,
not a current-image vector or final resume approval. Read them with the bounded
#319 correction and current overlay above; no original outcome is rewritten.

**EF-V5-M2-STUDIO-RESIDUAL-DISPOSITIONS-S1, revision 1. Decision proposal,
UNAPPROVED. No new closed dispositions, implementation authorization, risk
acceptance, M2 clearance or selected-release acceptance.** Existing OPEN findings
remain OPEN. This documentation slice changes no product, recipe, dependency,
Engine/KS, generated application or historical evidence.

## Evidence And Identity

The [compact decision projection](studio-image-residual-decisions-2026-10-20.json)
is the exhaustive membership index, not a replacement scanner report. Its source
catalog hashes the [owner queue](studio-image-residual-2026-10-14-queue.json),
[final ledger](studio-image-residual-2026-10-14-ledger.json),
[whole-stage ledger](studio-image-residual-2026-10-14-stages.json),
[corrected outcomes](studio-image-residual-2026-10-14-outcomes.json) and
[receipt](studio-image-residual-2026-10-14-receipt.json). Existing family IDs,
ledger group indexes and `(surface, local_index)` stage identities are preserved.
Stage tuples name every source-array position; the bound source retains exact
components, advisories and observation links. Observations retain aliases,
active/ignored/unresolved states, source positions, severity, fixes and rules.

| Preserved set | Coverage in the projection |
|---|---|
| Current final image | All **41 families / 3,528 groups / 7,005 observations**, including **2,471 ignored** Grype observations; each family has a concrete missing question and proposed action. |
| Whole stages | All **423 jdk21 / 262 Maven groups**, still OPEN; overlapping with final-image observations, not extra vulnerability totals. |
| Historical rationale | All **103 family IDs** and exact rationale pointers; not silently promoted into current 3.13 dispositions. All **3,494 historical-to-current** mappings remain bound to the original outcomes. |
| Scoped outcomes | All **32 runtime identities**, **21 bootstrap associations**, **18 curl exclusions**, **12 advisory-specific JDK conclusions**, and **15 prior system-Expat outcomes** plus new Expat identity. These sets overlap. |
| Native and gaps | All five identified private-native questions, **110 extension-file bindings**, **1,124 / 975 / 801** final/JDK/Maven native paths, copied-subtree identities and every explicit transient/opaque/out-of-scope exclusion. Counts are paths, not components. |

Entry Studio **`8f416a80a0ab30f0998b0abceec3accb152b94a7`** and Engine
**`ca53afb40ac9ba67d74f9d27c2d52e63b909970c`** are **provisional, not selected**.
No image was built or assessed for that pair here. Historical image-tested pairs
stay frozen; all OCI index/platform/config digests are in `historical_identities`:

| Record | Image-tested Studio | Image-tested Engine |
|---|---|---|
| [#311 runtime S2](studio-image-runtime-2026-10-08.md), reusing #310 | `a333ab58433909f6ab224585be6471ed2c184aa2` | `ab41a02fc854f89681e0473d9914e9e16528c3c2` |
| [#314 Bundle P](studio-image-bundle-p-2026-10-11.md) | `98a50bf0204976043f1d69580113a30c390e1b31` | `30d25d055c48001e6478493c8993d1e029d4df8f` |
| [#315 corrected residual proof](studio-image-residual-2026-10-14.md) | `ae99f6d3924ba01429edbdb25712e7cfffb38583` | `ba56abd1e0ff946260e96f3a3b715564fc0b740d` |
| [#316 MCP correction](studio-mcp-correction-2026-10-15.md) | `a987a21f9cb78b6f598fbeb46049b5b0a5f56996` | `ba56abd1e0ff946260e96f3a3b715564fc0b740d` |

Static tree comparison from #316 to entry finds no changes to Studio's
`Dockerfile`, constraints, requirements, `app/` or `scripts/`: changes are evidence,
changelog and the integration fixture test. Engine changes four `appbuilder`
generation build/container-policy files; its declared dependency graph is unchanged.
That is source-drift context, **not current-pair runtime/image equivalence**.
Generated-container policy assessment belongs to the separate Engine lane.
#316's unchanged private/seed/JDK bytes and frozen scanner streams support only
its documented bounded carryforward, not fresh whole-stage/native coverage.

## Recheck And Carryforward

The coordinator performed **one** primary-source recheck on 2026-10-20; the
document builder performed static reads only. The projection preserves **36
retrieval receipts: 35 HTTP 200 and one OpenJDK HTTP 404**, with original UTC times,
URLs, hashes or failure. Response headers/cookies and raw inventories are not
committed. `source_catalog` binds private `upstream-result.json` and
`upstream/receipts.json`; all **37 Debian families** have current Bookworm status
buckets mapped to existing group indexes. The other four families require
PSF/vendor/copy evidence, not forced Debian source-package matches. Missing tracker
entries remain unknown/not-listed. No metadata state becomes an artifact closure.

| Surface | Dated result and decision |
|---|---|
| Pip active and seed | **26.2.2**, released **2026-10-20 16:36:27 UTC**, requires Python >=3.10; wheel SHA-256 `fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70`. All **39** private urllib3 members are byte-identical to 26.2.1, still **2.7.0**. It is **not a fix** for CVE-2026-97687/97688/97689; no bump proposed. Standalone urllib3 2.8.0 does not replace either private copy. |
| CPython | Latest 3.13 source observed is **3.13.16**; branch ensurepip still selects **26.2.1** and bundled Expat is **2.8.5**. Branch base64/POP3/tempfile source matches the retained modules. Four stdlib questions remain OPEN, including the reviewed tempfile correction. Branch/release metadata is not behavioral proof. |
| Expat | Official **2.9.0** source archive, released October 5, SHA-256 `1e6371862cc31999b368c3b89b49994f0677e1bab5f1b2b85ae3741f5d803051`, matches the official asset digest and contains both CVE-2026-102633/77214 fixes in `xmlparse.c`. No supported containing CPython/Debian replacement is selected or proved. Security-index `libexpat1` remains **2.5.0-1+deb12u4**. System and embedded copies stay separate and OPEN as applicable. |
| Headers and other Debian families | Official security-subset candidate **linux-libc-dev 6.1.190-1**, SHA-256 `a88a129991cbb7db1715bed232c9808b91ac0fb7149660558b9df0d074348f05`, has statically verified version-header content and index/release hash linkage. **904 source-package fixed-version metadata associations are not 904 header fixes.** Reconcile actual header membership; the host kernel is unchanged. The security index is not a complete APT candidate index or proof of globally highest versions. |
| JDK, Go and Maven | Temurin API still lists **21.0.12.1+1-LTS**. The October 20 OpenJDK advisory URL returned **404: current event review UNKNOWN/not completed**, not no-new-advisories. Go **1.27.3 / 1.26.10** are release leads, not corrected Temurin `/usr/bin/pebble` binaries. Maven metadata lists **3.10.0**, but no matching finding rationale or containing distribution was inspected; no upgrade proposed. |

For CVE-2026-77214, the CNA is **PUBLISHED October 7, updated October 10**;
the exact released 2.9.0 source establishes an upstream fix lead. Expat issue
1160 is a generic pending/checklist source with reserved/rejected/TBA language,
not an advisory-specific clearing record. Prefer the published CNA and exact
released source for that identity, not a pending-status inference or simple
last-retrieved ordering. Neither establishes correction of retained image bytes.
Debian's CVE-2026-102633 OPEN/no-DSA note about compiled-out `XML_GE` is a
system-backport qualification, not proof about pyexpat or universal non-applicability;
77214 also remains OPEN. Archive hashes were linked via HTTPS; this recheck did
not independently verify OpenPGP signatures or execute the candidates.

No historical outcome is rewritten: #311 remains **11 OPEN / 21 supported**;
#314 remains **3 remediated / 14 supported / 15 OPEN**; corrected #315 remains
**3 prior remediations / 21 supported / 8 OPEN**. The eight are alternate base64
CVE-2025-12781, POP3 CVE-2025-15367, padded base64 CVE-2026-3446, tempfile
CVE-2026-12345, embedded Expat CVE-2026-102633 and private-pip
CVE-2026-97687/97688/97689. New Expat CVE-2026-77214 stays OPEN for both copies.
The **21 bootstrap successor conclusions**, **18 byte/range-bound curl exclusions**,
**12 JDK advisory-specific conclusions** and **10 prior system-Expat backports /
five OPEN** are preserved individually, not credited as new fixes. All scanner
observations remain, including ignored rules and unresolved imported identities.

The private, previously reviewed pip proposal revision 1 remains a separate dated
record: manifest SHA-256
`7e102cab22e9c61cec855686ee9f0fbf740153b1d24134188e899a725962ce61`.
Its input manifest hashes were statically verified; selected report/plan/scanner
subset hashes and exact copy/advisory pointers are bound in this projection.
Active/seed final and Maven copies are independent lifecycle obligations;
Maven's Python tree is not copied into final `/opt/maven`. Replacing active pip
does not repair ensurepip or descendant venv seeding, and an initial network
upgrade can still use the old vendor. Host-context 3.11 copies are not an all-host
assessment. Prior benign pip index/download observations establish some caller
prerequisites, not malformed-response exploits or universal TLS safety. Redirect
decoding, actual CLI HTTPS-proxy policy and chunk-line buffering gaps stay explicit.

## Proposed Decisions

**One proposed accountable owner for D1-D6: `santosh-sh` (Studio maintainer).
Proposed review date: 2026-10-27. Ownership, date and every route below are
UNAPPROVED; no assignee acceptance, residual acceptance or execution is implied.**
Each family, stage group, scoped outcome and coverage gap maps to one of these
packages; shared dependencies do not make their counts additive.

| Package | Concrete bounded action / decision route | Earlier trigger |
|---|---|---|
| **D1 Pip and bootstrap** | Prefer released containing-artifact follow-up for all active/seed copies. Preserve stripped pkg_resources vs full setuptools and private wheel 0.46.3 vs active 0.48.0. Require supported host-3.11/image-3.13 bootstrap and initial-upgrade proof before a separately authorized implementation. Do not implement unvendoring, custom seeds, seed deletion or the ineffective 26.2.2 bump. | Pip/vendor/seed release, revised advisory, new caller/copy or setup policy. |
| **D2 CPython and Expat** | Review base64 strict callers/integrity vs deprecation, POP3 command arguments, tempfile cleanup/callback/symlink paths; separately bind all XML_ParseBuffer length guarantees and expat_realloc 64-bit allocation paths. Separate system XML_GE/backports from pyexpat 2.8.5; `_elementtree` uses pyexpat C API, not a proven second embedded library. Choose later compatible containing-artifact work only with actual provenance. | PSF/backport/base/embedded Expat release, advisory/compile-option revision or new XML/cleanup/decoder caller. |
| **D3 TLS and native copies** | Prioritize exact Python `_ssl`/curl OpenSSL, Git GnuTLS and private cryptography OpenSSL **4.0.1** consumers. Map lxml libxml2 **2.14.6** / libxslt **1.1.43**, Pillow's separately recorded native feature versions and PDFium **151.0.7891.0** to advisories, options and callable paths. Include LDAP/Kerberos/SASL/ASN.1/HTTP2/trust-store prerequisites; do not substitute speculative package jumps. | TLS/native advisory, wheel/options/configuration/consumer change or newly identified opaque copy. |
| **D4 OS, build tools and headers** | Scope the **6.1.190-1 candidate plus header/advisory membership reconciliation** first. Then use each remaining family's concrete question for libc/loader/NSS, SQLite/zlib, compiler/sanitizer, archive/file utilities and privileged/session tools. Require installed-member, backport and input/privilege proof; compile success or non-root launch does not settle applicability. | Bookworm candidate/backport/range change; changed build inputs, privileges, header/tool membership or host-kernel policy. |
| **D5 Full stages and coverage gaps** | Keep all stage groups OPEN; copied **248 JDK / 96 Maven regular files** match historical subtree bytes, not the full stages. Ubuntu `/usr/bin/pebble`/Go and Maven Python/seed/build tools remain distinct. Recheck missing JDK event evidence; determine whether separately authorized transient/static/shaded investigation is needed. No Go install or Maven minor jump proposed. | JDK CPU/advisory/API event, containing stage-binary/base/archive release, changed extraction policy or missing source. |
| **D6 Selected pair and authority** | Obtain explicit ownership/date approval and separately authorize any implementation or time-bounded artifact/advisory-specific residual decision. Select and reassess the final pair; do not reuse historical runtime/build approval on changed Engine code. Font, private retention/replay and external coverage decisions stay visible. | Final pair/source/Engine/recipe/vendor selection, scanner/database/cutoff, coverage/security/retention/publication-policy change. |

**All packages also reopen on selected-release pairing or material artifact/source
change.** Earliest useful next scope is bounded TLS/native and Expat consumer proof,
alongside the header candidate/membership reconciliation, rather than an unverified
dependency jump. A later risk decision, if needed, must name exact artifacts,
copies/advisories, use assumptions, rationale, accountable owner, expiry/review date
and reopening triggers. OPEN tracking itself is not acceptance. No automation,
follow-up execution, risk waiver or release action is created here.

Final/stage snapshots do not capture all removed installation/extraction/compiler
processes. Opaque/static/shaded code, offline Java resolution, other platforms,
host kernel and later Maven plugins/generated images remain explicit gaps. Java
font rendering is still unavailable by default. Private raw inputs are needed for
exact replay; missing #310 history remains unavailable, and live APT prevents
guaranteed reconstruction from FROM pins. No no-fix/no-DSA/postponed state, stage
role, low severity, ignore rule, green audit/CI or scanner silence grants clearance.
This static documentation work ran no runtime/build/scan/install/probe; required
exact-head review/CI and any future selected-pair proof remain separate gates.

Unchanged invariants: supported host Python **3.11** and image Python **3.13**;
Knowledge Assist default **OFF**, with no new KS calls; Engine manifest **2.0**
and independently versioned Studio snapshot **1.4**; local single-user/no-auth
and shared anonymous-session isolation, with real authentication still deferred.
Studio authors/reviews; Engine generates. Fonts remain unavailable by default.
A11y-01 remains **one FAIL / three NOT RUN**; no native-speech completion or
broader accessibility clearance is claimed. Existing automated accessibility
checks remain binding; the audience-accessible limitation disclosure is unchanged.

## Validation And Retention

Existing residual/Bundle P/report/OCI integrity tests: **161 passed**. The retained
residual reducer and historical runtime reducer both pass `--check`; these are
static replays, not new runtime or scanner observations. The task-private coverage
check accounts for all final/stage membership and inherited outcomes, verifies
source hashes and current vendor buckets, and checks **95 relative links**.
Eight negative controls reject missing families/groups/bootstrap associations or
coverage gaps, a hidden ignored stream, stale input hashes and a new unsupported
closure. Diff hygiene passes. Required CI and independent review identify their
exact head in the PR handoff, not in this self-referential document.

Private supporting set **Studio-Residual-Dispositions-2026-10-20** follows the
existing EdgeForge Open-Source Artifacts convention: public vendor responses,
official inspected archives, timestamped/hash-bound receipts, static projection
and validation scripts, source/CI snapshots and review are retained locally with
checksums. Original scanner/OCI inputs remain in their unchanged dated sets.
Clean-clone readers can inspect this compact record and run existing synthetic
integrity tests, but cannot replay private raw inputs without authorized access.
No private archive, image, source tree or inventory was uploaded.
