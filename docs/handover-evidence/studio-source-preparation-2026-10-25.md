# Private v5 source preparation - 2026-10-25

**EF-V5-SOURCE-PREP-STUDIO-S1 revision 1**; authority is the maintainer-approved
**EF-V5-RELEASE-SCOPE-RESET revision 3**. This is private preparation, not
publication, final-pair acceptance, residual-risk acceptance or M2 clearance.
The [compact receipt](studio-source-preparation-2026-10-25.json) records hashes,
actual timestamps, inventories, failed/recovered attempts and scanner provenance.
UTC execution crossed into October 26; the local observation date is October 25
(America/Chicago).

## Source and image identity

| Input/artifact | Identity |
|---|---|
| Starting Studio main | `74e065a95f0b129fcfd55fbea74412d6634cf17e` |
| Clean image-tested Studio source | `515435c351e9a203c9ddce30ee62281b54fbe092` |
| Clean archived Engine input | `d148ca50722a676359ec7c7296561f79f99e2b69` |
| OCI index | `sha256:872b4c81380a58e47ced7c70096f0ecb1133b52d8b1767b43deb9d847c9bdab8` |
| linux/amd64 manifest | `sha256:5fa784ef0a09557fe92b2b75fb40d1120bc6e14542f01144583ad58ad11c5e32` |
| Configuration | `sha256:861a79ba68b7540ec338adb45a4e9c60887159acc6eda60bec86e5dc74402bac` |

The existing OCI verifier checked saved index/platform/configuration bytes and
compressed layers separately from filesystem diff IDs. Later evidence/template
commits are not relabeled as the image's source. The assessed platform is only
linux/amd64, emulated on an arm64 macOS/Docker Desktop host. Base index pins,
resolved platform descriptors and recipe/input hashes are in the receipt.
Fresh official APT resolution was used; digest pins do not freeze repository
package resolution or promise bit-identical future rebuilds.

## Dependency correction and applicability

The fresh baseline strict audit covered all 95 reference pins and failed on
three observations. One coherent target set changes exactly four versions:

| Distribution | Before | Selected | Reason |
|---|---|---|---|
| fastmcp | 3.4.0 | 3.4.10 | [GHSA-7xgj-8392-5q4r](https://github.com/PrefectHQ/fastmcp/security/advisories/GHSA-7xgj-8392-5q4r) |
| fastmcp-slim | 3.4.0 | 3.4.10 | Exact associated distribution required by FastMCP |
| opentelemetry-api | 1.43.0 | 1.45.1 | [GHSA-xcq7-p3pf-p88h](https://github.com/open-telemetry/opentelemetry-python/security/advisories/GHSA-xcq7-p3pf-p88h) |
| setuptools | 83.0.0 | 84.1.0 | Fresh blocking audit: [GHSA-xmj3-9gf7-h52w](https://github.com/pypa/setuptools/security/advisories/GHSA-xmj3-9gf7-h52w) |

Alongside these four constraint-pin changes, the direct FastMCP requirement in
`requirements.txt` and `pyproject.toml` changed from `>=3.1,<4` to `==3.4.10`.

Official PyPI metadata/artifact hashes bind the selected versions and Python
requirements. The remaining 91 reference pins are unchanged, including MCP
1.30.0, certifi 2026.10.19 and Pillow 13.0.0. No alternative set was needed.
FastMCP's finding needs transformed component authorization; OTel's needs
untrusted propagation extraction; setuptools concerns a Windows legacy wheel
installation path. These dependency corrections do not establish that Studio
previously exposed those paths. Studio remains a local stdio client, not a new
authenticated HTTP server. Regression tests exercise transformed authorization
and oversized TraceState rejection while preserving valid input.

Actual clean Python 3.11.15 installation, constrained packaging verification and
`pip check` passed. The complete strict reference audit covered **95** packages;
the actual Python 3.13 image audit covered **94** installed distributions. Both
reported zero known findings and zero omissions. Existing environment markers,
including Linux-only packages, explain the different graphs. Current SBOM,
licenses and audit describe the 95-pin reference, not every embedded component.
License flags `caio` UNKNOWN and `certifi` MPL-2.0 remain factual review items.

## Executed compatibility proof

| Check | Actual result |
|---|---|
| Host focused KA/adapters/session/regeneration checks | 161 passed, 10 skipped (real sibling discovery unavailable in isolated host checkout) |
| Host complete non-smoke suite at image-tested source | 2,515 passed, 45 skipped, 32 deselected |
| Host L2 | 1 passed |
| Actual prebuilt-image smoke | 1 passed; non-root import/startup, no source mounts, loopback-only publication |
| Actual image SDK/document/TLS/KA-OFF tests | 34 passed; packaged `app/`, test inputs copied separately |
| Actual image `pip check` | Passed, complete 94-distribution graph |
| Network-disabled venv/bootstrap | Passed as UID 1000; upstream seed pip 26.2.1, explicit constrained setuptools 84.1.0/wheel 0.48.0, verified local wheelhouse, synthetic wheel build |
| Real Studio to frozen Engine | Project-open/export/strict MCP generate/build/run/stop passed, KA OFF, full FS sample, no generated-code edits |
| Generated test execution | `mvn clean verify`: 1 test, zero failures/errors/skips; Surefire XML retained |
| Meaningful generated-app requests | Create 201 and matching content, read 200 and matching content, missing ID 404; health UP |
| Package artifacts | Wheel/sdist built locally; SPDX Apache-2.0, LICENSE and NOTICE in both, Python >=3.11 |
| Final focused evidence/tooling regressions | 130 passed |
| Bounded content checks | 209 local links/anchors resolve; issue front matter/chooser valid; 95-pin SBOM/audit/license join exact; gitleaks 8.30.1 current-tree scan clean |

The content pass covered changed/directly relevant active files and tracked-tree
host-path/attribution searches, not old Git history. Existing synthetic path
fixtures remain synthetic. Selected new-organization/PVR destinations are
intentionally not asserted operational; historical private links are retained.
Required exact-head CI and independent review are recorded in the PR, not
inferred from these local results.

The public Build route deliberately uses `-DskipTests`; it receives **no** test
execution credit. The separate successful `mvn clean verify` supplies that proof.
Route/service automation is not browser or native accessibility observation.
No Node-dependent image matrix, full Suite L5 or final newcomer campaign ran.

Failures remain recorded: the first build stopped at a hung host credential
helper before building stages. One corrective build used task-local anonymous
public-registry configuration without changing global credentials/settings.
An initial proof destination outside the image's allowed output root was
correctly refused; the argument was corrected, not the guard. An image test
invocation omitted the existing asyncio configuration and used a forbidden
temporary export root; rerunning with `asyncio_mode=auto` and an allowed
`--basetemp` passed all 34 tests. No product repair or additional image build
was needed. The full image-build allowance is exhausted.

## Assessment and open owner queue

Checksum-verified Syft 1.52.0, Grype 0.119.0 and Trivy 0.74.0 ran locally with
frozen downloaded databases, external inventory lookup/telemetry disabled and
no private uploads. The Grype database was built October 25; Trivy's database
and Java metadata updated October 26 UTC. Exact database files, hashes, source
URLs/tool checksums, download/execution times and raw reports are retained.
Existing identity-checking summary/normalization tools replay the reports.

The final image contains 166 Debian packages, 106 scanner Python records
(including imported/private identities), 52 Java archives and Temurin
21.0.12.1+1-LTS. **Complete with findings**, not a clean image:

- Grype: 1,050 active and 1,883 separately retained ignored observations. The
  default kernel-header exclusion is not an approved disposition.
- Trivy: 2,938 Debian and eight unresolved Python observations; observed result
  types are Debian, Python and Java, with no Java matches. Silence is not JDK or
  nested-archive clearance.
- Existing normalization yields 2,948 groups / 5,879 observations. These are
  overlapping scanner identities, not a count of exploitable vulnerabilities.
  No new ledger framework or replacement historical ledger is introduced.
- Compared with #319's 3,840 groups / 7,663 observations: 1,057 exact identities
  persist, 1,891 are new/changed and 2,783 old identities are not observed now.
  Fresh APT packages and advisory databases both changed; scanner silence is
  **not** remediation, and no reduction is attributed solely to SDK updates.

| Remaining scope | Disposition, owner and trigger |
|---|---|
| Active pip-private and independent ensurepip seed certifi/urllib3 | OPEN; inspected old certifi bundle and urllib3 2.7.0 remain in both copies. Studio image/packaging owner; verified upstream containing-artifact correction or release selection. Standalone updates do not repair these copies. |
| Imported msgpack 1.1.2 and pkg_resources/setuptools 70.3.0 alerts | OPEN; eight total Python alerts also include three urllib3 identities, certifi and three old-setuptools associations. The newly observed setuptools advisory does not imply the complete old setuptools distribution or vulnerable caller is present. Copy/advisory-specific proof remains required. |
| OS/native/CPython/Expat and runtime TLS/parser families | OPEN known limitations; Studio image owner, next authoritative fix/applicability change or selected-pair assessment. System and embedded Expat are distinct. Historical supported outcomes remain bound to their artifacts, not renewed by this scan. |
| New Critical `linux-libc-dev` 6.1.190-1 / CVE-2026-98959 | Surfaced and OPEN. [Linux CNA record](https://cveawg.mitre.org/api/cve/CVE-2026-98959) identifies kernel `fs/btrfs/xattr.c`, not installed UAPI header implementation. Package file inventory is retained. No Docker-host-kernel clearance follows; Studio image owner and deployment kernel owner review on selection/advisory change. |
| Copied JDK/Maven, whole stages and transient build tools | Final copied runtime/archive inventory observed. No new whole-stage campaign or observation of every transient operation; unchanged pinned stages and historical #315/#318 findings/coverage stay separate and OPEN. Studio image owner; changed stage/copy or final-pair assessment triggers review. |
| Native wheel libraries and opaque embedded copies | Scanner extraction remains incomplete evidence, not non-applicability. Studio dependency/image owner; changed wheel/native bytes or relevant advisory triggers copy-specific assessment. |

Existing Critical/High OS families and private certifi remain visible in the
retained reports and earlier owner queue. No severity exemption, no-fix acceptance,
suppression or new release-risk decision is made. The Java font-rendering
limitation remains. A11y-01 remains one FAIL / three NOT RUN, with all four native
cases, automated checks and audience-accessible disclosure still required.

## Reproduction and retention

Use the image-tested source above for the recipe, or the final PR head for
evidence-only changes; retain the distinction. Archive the exact Engine commit,
then use the existing named `edgeforge_engine` context and `--platform linux/amd64`.
A later build is a **new artifact**, not guaranteed recovery of this digest.
Run the existing `tests/smoke/test_docker_image_launch_smoke.py` prebuilt mode and
`maven_image_build_run_proof.py` with `--run --exercise-account`, full FS sample,
legacy profile, strict MCP transport and a proof root under
`/workspace/data/GeneratedApps`. Use `image_bootstrap_proof.py --constraints`
with the four checksum-verified local wheels in a network-disabled container.
The historical helper default retains the earlier setuptools pin deliberately;
current runs must supply current constraints.

Raw image/OCI blobs, scanner/DB files, checksummed command receipts, inputs and
logs reside in task-private durable storage outside iCloud, packet identifier
`studio-source-prep-20261025`. The maintainer can provide authorized local access;
there is no public archive/download or retention SLA. A clean clone can inspect
committed source/projections and execute tests but cannot exactly replay private
raw inputs without that packet. Earlier #310 raw-input limitations remain.
Refresh after source/Engine/runtime/base/package/vendor/advisory changes or final
release selection; no recurring scan is created. Selected source terms, pending
ownership/route activation and one optional post-v5 list remain in the
[publication record](../publication-preparation.md).
