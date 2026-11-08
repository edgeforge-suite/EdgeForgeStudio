# Studio image runtime S2: artifact-bound dispositions

Candidate **EF-V5-M2-STUDIO-IMAGE-RUNTIME-S2**, revision **1**. Observation date:
2026-10-08 UTC. This is a bounded decision/evidence package, **not M2 clearance,
risk acceptance, or a clean image claim**. No image recipe, dependency, runtime,
workflow, Engine, KS, tracker, onboarding or manual change is made.

## Sources, identity and frozen boundary

Entry Studio main: `e17eeaa317fb23147ff27dba553e7ee9c7ed867f` (merged #310).
Read-only archived Engine reference: `64f51d0bac92b4c70f26c8f5f067888717df7b14`.
The reused #310 artifact is **older**, not an image of either current main:

| Identity | Exact value |
|---|---|
| Image-tested Studio | `a333ab58433909f6ab224585be6471ed2c184aa2` |
| Actual embedded Engine | `ab41a02fc854f89681e0473d9914e9e16528c3c2` |
| OCI index / local Docker ID | `sha256:145acf7614b67f146959eb1b964c4f0a6eea5f996384025d4968d3a6dddfb62e` |
| Actual AMD64 OCI platform manifest | `sha256:07a6d9c444dee382aab67461f14987bee1aec0043784fcea640d96ffdfc849cc` |
| Actual image config | `sha256:1dac71e187a03e7f13468bd52feeb59328545959ee22bfe11f04a0be7970f8f9` |
| Assessed platform | `linux/amd64` only |

The [unchanged #310 identity receipt](studio-image-refresh-2026-10-04-identities.json)
retains base index/platform/config digests, compressed layer identities, distinct
filesystem DiffIDs, scanner serialization identity, tool checksums and database
provenance. Do not substitute the scanner-generated manifest for the OCI manifest.
S2 streamed the retained image through the existing OCI verifier again: actual
blob hashes/sizes, platform/config chain and decompressed layer DiffIDs match.
This slice verified the retained tool executables/archives, DB bytes and both raw
report rounds against that receipt. Existing normalizers reproduce both summaries
and raw ledgers; committed historical observations/rules agree. No new scanner or
database download was used. Historical owner projections were not rewritten.

The fixed list has **32 advisory identities**: A = seven current CPython groups,
six historical CPython groups no longer reported, and embedded Expat
`CVE-2026-102633`; B = all six imported/vendored Python observations; C = the nine
JDK21 entries in the July CPU and three in the August CSPU. The list, original
group/observation indexes, six historical indexes, aliases, **11 distinct code or
bootstrap copies**, per-copy evidence and decisions are in the
[sanitized inputs](studio-image-runtime-2026-10-08-inputs.json). License-only
directories are recorded separately, not counted as executable copies.

Scanner cutoff remains `2026-10-05T01:02:53.479177+00:00`. The inputs separately
record the actual October 8 vendor-research cutoff, retrieval timestamps and
SHA-256 hashes. Primary vendor pages can change; conclusions are dated. The
[deterministic results](studio-image-runtime-2026-10-08-results.json) retain every
identity and per-copy disposition: **11 OPEN, 21 supported-not-affected**. These
are scoped advisory conclusions, not a subtraction from the all-family scanner
totals or blanket clearance of any component.
The separate bootstrap disclosure below records **21 newly encountered advisory
associations**, outside those 32 dispositions; their applicability remains
**OPEN/unassessed**. They are not folded into the frozen counts or silently cleared.

## A. CPython and embedded Expat

The offline, mount-free probe ran as UID/GID 1000, with network disabled, on the
identified artifact. It recorded Python **3.11.17**, a 64-bit process, executable,
libpython and pyexpat hashes, linkage and code-copy searches. Eleven relevant
stdlib modules byte-match the checksum-verified
[official 3.11.17 source release](https://www.python.org/downloads/release/python-31117/).
The benign base64 probes retain the old accepting behavior. The safe tar-member
probe is confined to a disposable synthetic directory and verifies the backport.

| Identity | Disposition and basis |
|---|---|
| [CVE-2025-12781](https://www.cve.org/CVERecord?id=CVE-2025-12781) | **OPEN**: altchars alphabet behavior remains; PSF range includes 3.11.17. |
| [CVE-2025-15366](https://www.cve.org/CVERecord?id=CVE-2025-15366) | **OPEN**: exact imaplib command assembly lacks later newline rejection. |
| [CVE-2025-15367](https://www.cve.org/CVERecord?id=CVE-2025-15367) | **OPEN**: exact poplib line writer lacks later newline rejection. |
| [CVE-2026-3446](https://www.cve.org/CVERecord?id=CVE-2026-3446) | **OPEN**: benign padded base64 input still ignores trailing data. |
| [CVE-2026-3479](https://www.cve.org/CVERecord?id=CVE-2026-3479) | **Supported not affected under intended security model**: PSF disputes a code vulnerability; get_data is not a path-confinement boundary. |
| [CVE-2026-6019](https://www.cve.org/CVERecord?id=CVE-2026-6019) | **OPEN**: Morsel.js_output code remains; application exploitability is not established. |
| [CVE-2026-12345](https://www.cve.org/CVERecord?id=CVE-2026-12345) | **OPEN**: old TemporaryDirectory cleanup implementation remains in the affected PSF range. |
| CVE-2026-15310 | **Supported not affected**: PSF explicitly backported bounded bzip2/LZMA reads in 3.11.17; exact zipfile source matches. Arbitrary monkey-patched decompressors are not cleared. |
| CVE-2026-15806 | **Supported not affected**: explicit 3.11.17 credential-scheme fix and matching urllib.request source. |
| CVE-2026-17084 | **Supported not affected**: explicit 3.11.17 stringprep/IDNA fix and matching modules. |
| CVE-2026-19672 | **Supported not affected for this artifact**: release notes explicitly record the backport; matching tarfile source and regression prove no outside directory creation. The older CNA `<3.16` range conflicts; scanner disappearance alone was not used. |
| CVE-2026-82049 | **Supported not affected**: explicit 3.11.17 tar-filter backport and matching tarfile source. |
| CVE-2026-87910 | **Supported not affected**: explicit 3.11.17 filter-rejection backport and matching tarfile source. |
| [CVE-2026-102633](https://www.cve.org/CVERecord?id=CVE-2026-102633) | **OPEN**: pyexpat embeds **2.8.5**, separate from Debian libexpat1 u4. CNA describes 32-bit overflow; actual process is 64-bit, but sufficient artifact-specific allocation-path proof was not obtained. |

The six historical fixes above were **already present in #310**; S2 did not apply
them. Their PSF advisory references/ranges and release-source checksums remain in
the inputs. Newer Python **3 feature/minor lines**, not newer Python majors, carry
listed fixes for several remaining groups; the latest released 3.11 tag found at
the cutoff is 3.11.17. Do not upgrade the runtime line or patch stdlib without the
separate compatibility/provenance proof described in each OPEN record.

For embedded Expat, the [upstream overflow patch](https://github.com/libexpat/libexpat/commit/209801d7fbaf07ab74bae8cb32dd2ab9e5846118)
adds a check independently of the system library. Debian backports do not patch
this pyexpat copy; a future PSF embedded update or a separately authorized bounded
64-bit applicability investigation is required. No claim of exploitability is made.

## B. Pip/imported identities and duplicate copies

The search covers `/usr/local`, `/usr/lib`, `/opt` and `/workspace`, including wheel
members and the active import paths, with no access errors. It does not claim to
inventory future downloads, arbitrary archives or operator-mounted content.
Pip **26.2.1** is the latest stable release found at the cutoff. Installing a
standalone dependency does **not** update pip's private vendor copies.

| Copy | Actual content/use |
|---|---|
| Active pip | msgpack **1.1.2**, pkg_resources from setuptools **70.3.0**, urllib3 **2.7.0**; packaging/download/cache paths |
| `ensurepip/_bundled/pip-24.0-py3-none-any.whl` | msgpack **1.0.5**, pkg_resources from setuptools **68.0.0**, urllib3 **1.26.17**; dormant bootstrap bytes that venv/ensurepip can install |
| Active setuptools | Full **83.0.0** packaging distribution, distinct from pip's stripped subset |
| `ensurepip/_bundled/setuptools-79.0.1-py3-none-any.whl` | Full **79.0.1** bootstrap distribution, including FileList and PackageIndex |

| Identity | Artifact-specific disposition |
|---|---|
| [GHSA-6v7p-g79w-8964 / CVE-2026-57585](https://github.com/msgpack/msgpack-python/security/advisories/GHSA-6v7p-g79w-8964) | **Supported not affected**, both copies: advisory/patch target the native C/Cython unpacker; each copy contains only the Python fallback, without the native implementation. Live import confirms fallback. Not a blanket msgpack clearance. |
| [CVE-2025-47273](https://github.com/pypa/setuptools/security/advisories/GHSA-5rjg-fvgr-3xxf) | **Supported not affected**: both pip subsets lack the affected PackageIndex.download code; full 79.0.1/83.0.0 exceed the vendor 78.1.1 fix floor. Actual 83.0.0 also lacks package_index.py. |
| [CVE-2026-59890](https://github.com/pypa/setuptools/security/advisories/GHSA-h35f-9h28-mq5c) | **OPEN overall**: pip subsets lack affected sdist code and installed 83.0.0 has the upstream normalization fix (safe in-memory NFC/NFD exclusion regression passed). Full bootstrap 79.0.1 retains the old path. Linux narrows the stated APFS/HFS+ scenario, but is not blanket clearance for future supported build/mount contexts. |
| [CVE-2026-97687](https://github.com/urllib3/urllib3/security/advisories/GHSA-8988-9cw3-xx77) | **OPEN**, active 2.7.0 and bootstrap 1.26.17: HTTPS proxy TLS configuration; both in vendor range. |
| [CVE-2026-97689](https://github.com/urllib3/urllib3/security/advisories/GHSA-vxq7-64xx-v4gw) | **OPEN**, both copies: unbounded chunk-size line; both in vendor range. |
| [CVE-2026-97688](https://github.com/urllib3/urllib3/security/advisories/GHSA-gh4c-6fx4-qh6g) | **OPEN**, active 2.7.0: deflate chunk behavior. Bootstrap 1.26.17 is outside the vendor range beginning at 2.6.2, without clearing its other two alerts. |

The setuptools maintainer page still lists no patched version; the global advisory
lists 83.0.0 and an [upstream normalization patch](https://github.com/pypa/setuptools/commit/dd9f436a36486b4cb8a4c70a2321548b0be09b8f).
This disagreement is explicit, not silently resolved by package metadata. The
installed implementation/regression supports that copy; the bootstrap copy stays
OPEN. Pip's [documented vendoring policy](https://pip.pypa.io/en/stable/development/vendoring-policy/)
explains why pkg_resources is not the complete old setuptools distribution.

**Smallest next decisions:** await/use released pip and CPython bundles containing
the applicable fixes, or separately authorize and maintain a vendoring/bootstrap
replacement with toolchain, ensurepip/venv, offline/proxy and supported-filesystem
regressions. A one-line standalone urllib3 bump is ineffective. Removing bootstrap
capability, custom unvendoring or choosing a new runtime/distribution is not done
here. Code presence establishes identity, not exploitability; no risk is accepted.

### Newly encountered: bootstrap wheels (2026-10-08 America/Chicago)

[Claude's follow-up review](https://github.com/santosh-sh/EdgeForgeStudio/pull/311#issuecomment-6071211549)
identified a disclosure gap in dormant bootstrap archives. The retained probe's
`pip-24.0` wheel `vendor.txt` declares requests 2.31.0, certifi 2023.7.22, idna 3.4,
urllib3 1.26.17 and the stripped setuptools 68.0.0 identity. The setuptools 79.0.1
wheel contains wheel 0.45.1 metadata and `wheel/cli/unpack.py`. Archive, metadata,
declaration and unpack-member hashes are retained in the inputs' separate
`newly_encountered` record, bound to the existing image/probe receipt.

**M2 coverage exclusion: OPEN.** The retained #310 scanner reports did not
enumerate advisory coverage for these wheel-archive contents. Listing archives or
reading `vendor.txt` does not establish that coverage; scanner silence is not a
clean result or approved risk disposition. This describes this assessment campaign,
not a claim that every scanner/configuration can never inspect wheel archives.

The following **21 additional associations** were checked against public GitHub
advisory records; their source URLs, SHA-256 hashes, retrieval times, affected
ranges and reported fixed versions are recorded separately. Follow-up retrieval
cutoff: `2026-10-09T04:08:51.479963+00:00` (still October 8 in America/Chicago).
The original frozen-scope research/scanner cutoffs above are unchanged.

| Bootstrap component | Newly encountered advisory sources |
|---|---|
| pip 24.0 | [CVE-2026-13346](https://github.com/advisories/GHSA-qwm4-qh6w-59xr), [CVE-2026-8643](https://github.com/advisories/GHSA-wf93-45jw-7689), [CVE-2026-6357](https://github.com/advisories/GHSA-jp4c-xjxw-mgf9), [CVE-2026-3219](https://github.com/advisories/GHSA-58qw-9mgm-455v), [CVE-2026-1703](https://github.com/advisories/GHSA-6vgw-5pg2-w6jp), [CVE-2025-8869](https://github.com/advisories/GHSA-4xh5-x5gv-qwph) |
| urllib3 1.26.17 (beyond its two frozen OPEN items) | [CVE-2026-44431](https://github.com/advisories/GHSA-qccp-gfcp-xxvc), [CVE-2026-21441](https://github.com/advisories/GHSA-38jv-5279-wg99), [CVE-2025-66471](https://github.com/advisories/GHSA-2xpw-w6gg-jr37), [CVE-2025-66418](https://github.com/advisories/GHSA-gm62-xv2j-4w53), [CVE-2025-50181](https://github.com/advisories/GHSA-pq67-6m6q-mj2v), [CVE-2024-37891](https://github.com/advisories/GHSA-34jh-p97f-mpxf), [CVE-2023-45803](https://github.com/advisories/GHSA-g4mx-q9vg-27p4) |
| requests 2.31.0 | [CVE-2026-25645](https://github.com/advisories/GHSA-gc5v-m9x4-r6x2), [CVE-2024-47081](https://github.com/advisories/GHSA-9hjg-9r4m-mvj7), [CVE-2024-35195](https://github.com/advisories/GHSA-9wx4-h78v-vm56) |
| certifi 2023.7.22 | [CVE-2024-39689](https://github.com/advisories/GHSA-248v-346w-9cwc) |
| idna 3.4 | [CVE-2026-45409](https://github.com/advisories/GHSA-65pc-fj4g-8rjx), [CVE-2024-3651](https://github.com/advisories/GHSA-jjg7-2v4v-x38h) |
| pkg_resources 68.0.0 subset | [CVE-2024-6345](https://github.com/advisories/GHSA-cx63-2mw6-8hw5) |
| setuptools 79.0.1's vendored wheel 0.45.1 | [CVE-2026-24049](https://github.com/advisories/GHSA-8rrh-rw8j-w5fx) |

These are **not 21 confirmed exploitable vulnerabilities or new dispositions**.
The bootstrap code is dormant until ensurepip/venv or equivalent bootstrap use;
the reviewed Studio/Engine do not normally create those environments. Individual
conditions still matter: CVE-2025-8869 concerns a fallback without PEP 706 filters,
and CVE-2024-6345 targets `package_index`, not the stripped pkg_resources subset.
Their potential inapplicability is retained for follow-up, not silently upgraded
to a supported exclusion. The wheel unpack member's presence likewise does not
prove that normal Studio execution reaches it.

The existing smallest-next-decision applies to this whole bootstrap gap as well:
assess these associations, then use corrected released pip/CPython bundles where
available, or separately authorize a maintained bootstrap replacement and its
ensurepip/venv, constrained-toolchain, offline/proxy and filesystem proof. S2 does
not implement that replacement, remove bootstrap capability, accept risk or expand
its frozen 32-identity disposition scope. Overall M2 remains open.

## C. Copied Temurin JDK 21

Actual release: **Temurin 21.0.12.1+1-LTS**. The official
[Adoptium release](https://github.com/adoptium/temurin21-binaries/releases/tag/jdk-21.0.12.1%2B1)
archive SHA-256 is
`ce79869e1307ed8ee1e2baa86a412b1eb5b75d10a01006d788a6f968bcfaee94`.
**247 regular files match**, including `lib/modules`, `lib/server/libjvm.so` and
the JDK modules. The two exceptions are not hidden: `lib/src.zip` is removed and
`lib/server/classes.jsa` is regenerated by `java -Xshare:dump`, both explicit in
the [pinned official container recipe](https://github.com/adoptium/containers/blob/511f9356dc4d50932a0a5f8cfb0f87ed1aef4f07/21/jdk/ubuntu/resolute/Dockerfile).
Installed and official hashes for these differences are retained.

| Vendor matrix | Frozen JDK21 identities | Disposition |
|---|---|---|
| [2026-07-21 CPU](https://openjdk.org/groups/vulnerability/advisories/2026-07-21) | CVE-2026-41254, CVE-2026-47063, CVE-2026-60147, CVE-2026-46968, CVE-2026-47059, CVE-2026-47027, CVE-2026-47021, CVE-2026-46917, CVE-2026-47010 | **Supported not affected**: preceding 21.0.11 and earlier affected; exact installed vendor security release is later. |
| [2026-08-18 CSPU](https://openjdk.org/groups/vulnerability/advisories/2026-08-18) | CVE-2026-61308, CVE-2026-70907, CVE-2026-60589 | **Supported not affected**: preceding 21.0.12 and earlier affected; exact installed 21.0.12.1 release includes the security update. |

The matrices' 8/11-only and 25/26-only entries are outside this JDK21 list; OpenJFX
is separate and no JavaFX module is installed. This review of the latest CPU/CSPU
does not claim exhaustive historical JDK research or clear native libraries. The
font/metrics limitation remains unchanged. Scanner non-matches do not establish
JDK security; positive vendor release and installed-byte evidence support the
specific twelve conclusions above.

## Replay, proof and limitations

The [inputs](studio-image-runtime-2026-10-08-inputs.json) preserve sanitized artifact
hashes, all per-copy conclusions, primary-source URLs/hash/times, normalizer replay
receipts, the exact offline probe command and stdout/stderr/script hashes. The
new helper validates list/copy completeness, image identity, evidence references,
required OPEN states and deterministic aggregation. All eleven stdlib comparison
rows are mandatory; their well-formed official/installed hashes must match and
agree with the duplicate CPython source-match projection. A stale `equal` flag,
empty comparison or missing module cannot preserve a supported exclusion. JDK
file hashes use explicit `sha256` records without changing their values or adding
secret-scanner exceptions. It is a record-integrity
guard, not an automated exploitability oracle or permission to accept risk.
The matched-JDK-file map also reconciles to a digest/count in its archive receipt;
a substituted well-formed file hash is rejected. Because this slice changes no
image, relabeling an existing supported row as newly `remediated` is rejected.
The non-frozen bootstrap catalog must remain complete, sourced, archive-bound and
OPEN/unassessed, separately visible in results without changing frozen counts.

```sh
python -m scripts.image_runtime_dispositions --check
python -m pytest tests/test_image_runtime_dispositions.py -q
docker run --rm -i --network none --platform linux/amd64 --entrypoint python \
  "$IMAGE" - < scripts/image_runtime_probe.py > "$OUT/runtime-probe.json"
```

Use the exact local image identity above, never an arbitrary tag. To recheck the
official-byte comparison, download the public release inputs to a temporary
directory, verify the recorded hashes and call `compare_archives` with the probe,
Python source archive/release page, and JDK archive/checksum. No private image,
source, inventory or SBOM is uploaded. Public pages and floating base/APT inputs
can change: a new build is a **new artifact**, not recovery of this digest.

A clean clone can replay the new committed decision reduction. It cannot repeat
the old image campaign without the retained private image/raw reports, databases,
projection scripts and other inputs described by #310's unchanged
[retention limitation](studio-image-refresh-2026-10-04.md). They remain local with
no public download or retention SLA; ask the maintainer for controlled access.
Do not imply raw historical evidence became publicly reproducible.

No control or corrective image build and no fresh advisory scan was necessary:
the exact retained baseline and required bytes were available, and no substantiated
released compatible correction bundle for the remaining copies was selected.
The prebuilt image startup smoke was rerun without mounts, non-root and loopback
only. This does not test rebuilding today's Dockerfile. #310's historical real
Studio-to-Engine generate/build/run proof remains bound to its older Engine pin;
it was inspected, not rerun or relabeled as current-pair proof. A corrected image
would require fresh actual-image assessment and that proof before delivery.

The current [Engine external-review backlog](https://github.com/santosh-sh/EdgeForge/blob/64f51d0bac92b4c70f26c8f5f067888717df7b14/docs/external-review-backlog.md)
has adopted bounded ownership/scope; recommendations in the
[readiness procedure](https://github.com/santosh-sh/EdgeForge/blob/64f51d0bac92b4c70f26c8f5f067888717df7b14/docs/v5-release-readiness.md)
are not new signing, pinning or risk-acceptance authority. Newly encountered
PSF release-note items CVE-2026-19553 and CVE-2026-19445 are outside the frozen list:
PSF reports corrections in 3.11.17; no new broad clearance or scope expansion is
claimed. They remain a final-pair verification follow-up.

All other Debian, runtime and build families in the unchanged #310 ledger remain
separately tracked, including active and ignored matches. Final Studio/Engine
pairing, complete OS/native/build coverage and overall M2 decisions remain open.
KA remains OFF; manifest 2.0, authoring-only behavior, non-root execution, safe
Compose publication and supported functionality are unchanged.

### Validation record

Assessor Python: 3.11.15; assessed image Python: 3.11.17. Focused runtime-record,
existing image-report, ledger, packaging, proof-helper and KA-OFF checks:
**175 passed**, including 69 new S2 integrity/probe tests.
L2: **1 passed**. Existing prebuilt-image smoke: **1 passed**, not skipped. Changed
Python lint, decision replay, relative Markdown links and diff hygiene pass.
The final broad non-smoke run against the frozen read-only Engine reference:
**2,364 passed, 32 deselected**. Exact-head CI is reported on the PR.

An initial broad attempt was interrupted after a shared sibling Engine symlink
caused a timeout (1 failed, 72 passed). A second attempt's two runtime-default
assertions were invalidated by overly broad assessor environment overrides
(2 failed, 2,326 passed). The passing run used only `EDGEFORGE_ENGINE_REPO` for
optional cross-repo test discovery, leaving Studio's production defaults untouched.
The existing OCI verifier's first invocation used the host's generic Python 3.9
and failed at `zip(strict=True)`; its Python 3.11 rerun passed. No production/test
assertion was weakened and no failed attempt is counted as image proof.

Initial independent Astra extra-high review found two repairable blockers: the
required Secret Scan treated six bare filename-to-hash values as credentials,
and committed replay accepted incomplete/contradictory stdlib comparisons. The
repair preserves all 247 JDK hashes in explicit records, without allowlisting or
changing scanner rules, and rejects the reviewer's missing-row, stale-flag and
duplicate-projection mutations. The same pinned local secret scanner now reports
zero findings. Exact-head CI and independent re-review are recorded on the PR;
the initial head is not represented as approved. These corrections do not change
the image, underlying artifact facts, advisory dispositions or historical evidence.

Claude's subsequent review found the bootstrap-advisory disclosure gap. The added
21-item catalog is sourced and archive-bound, with mutation controls for dropping,
duplicating, clearing, mis-versioning or mis-binding entries. The JDK receipt check,
unchanged-image remediation-label restriction and frozen-image Engine diagnostic
also address the small reducer follow-ups. Local replay, targeted/full tests, L2,
lint, secret scan, documentation links and diff hygiene pass. Required CI and fresh
independent review of the resulting head are recorded on the PR; earlier approvals
are not carried forward to this correction.
