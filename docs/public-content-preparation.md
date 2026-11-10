# Studio Public-Content Preparation

Candidate **EF-V5-PUBLIC-CONTENT-STUDIO-S1 revision 1**, observed 2026-11-02
America/Chicago (2026-11-03 UTC). Studio base:
`44ad01f30e4f43f326cfb4304bde704a90606faf`. Engine #338 is merged at
`89f1030b75b6d7c877861cbf8d0ed1556d8315a5`; the proof uses a task-owned clean
archive of exactly that commit, not another task's moving checkout.

This prepares one intended fresh-source tree. Original repositories/history stay
private. No import, publication, visibility change, rights/risk acceptance,
M2 clearance or final selected-release acceptance is performed.

## Content And Preserved Assertions

| Affected material | Independent replacement / preserved coverage |
|---|---|
| External-specific durable proof runner and copied payload/output detail | Runner retired; [neutral March summary](test-results/durable-crud-proof-2026-03-31.md) preserves date, original results and limits. Complete originals remain recoverable at the private base above, not in another archive. New synthetic inputs are never credited with that historical result. |
| Shared package fixture and its consumers | A newly authored tiny scalar Account model uses label/category/status, explicit request/response mappings, fixed-width ID layout, staging DDL and default/allowed-value rules. Generic Account naming is not an external contract. File-tree, mapping YAML, manifest 2.0, project save/open, explicit source/version, whitespace/missing-target refusals and export-side-effect assertions remain. Real CLI/MCP generation also checks the file writer, staging-table/column references and batch-job artifacts formerly checked by the retired runner. |
| MCP proof runner | Independent Notes contract: one supported required-JSON POST, three scalar fields and explicit mappings. Normal project-open/write/validate/generate routes replace stale global-session setup. A real-child observer proves strict MCP and automatic CLI fallback; strict unavailable-MCP failure remains required. Executable venv symlinks are not resolved out of their environment. No production adapter behavior changes. |
| Derived staging/file examples | Independently authored Workspace staging fields cover required/nullable text, decimal precision/scale and CHAR, plus four accepted mapping targets. Existing unknown-target, exact-case, partial-DDL warning, missing-path and XML/file guards remain. Three synthetic file interfaces retain save/restore cardinality, mapped fields and UUID-width guidance. |
| Small upload and inline response-reference payloads | Independent [Parcel fixture](../tests/fixtures/parcel-response-upload.yaml) replaces unverifiable upstream-derived content, rather than translating it. Component-response refs, parameterized JSON media types, nested Data, scalar enum refs, object/Links/Meta exclusion, canonical naming, mapping targets, upload, classification and actual Step 3 selection are asserted. |
| Identifying historical descriptions | Neutral summaries/illustrations and explicit public-tree amendments retain original dates, acceptance pins, result counts and limitations. The cached-URL record's original identifying diagnostic remains private; its command/result hashes are unchanged. SQL CASCADE, cadence and independent generic banking tests are not external application references. |

The [supported newcomer guide](newcomer-journey.md), all three canonical
[sample packs](sample-packs/README.md), their derivatives and historical journey
receipt are byte-unchanged. This task does not replace that journey or repeat its
regeneration/preservation campaign. Its final selected-pair applicability still
requires review/re-proof.

## Third-Party Treatment

One focused source check used Engine's merged
[attribution account](https://github.com/santosh-sh/EdgeForge/blob/89f1030b75b6d7c877861cbf8d0ed1556d8315a5/docs/third-party-attribution.md#open-banking-specification)
and the official
[Open Banking v4.0.1 artifact](https://github.com/OpenBankingUK/read-write-api-specs/blob/v4.0.1/dist/openapi/payment-initiation-openapi.yaml).
Engine's full-spec identity/notice does not establish Studio's small excerpt's
source revision or modification history. Studio's former declared version was
not treated as proof. Instead of inventing provenance or a byte-identity claim,
the fixture and related inline payloads were replaced from the parser requirements
above. No Open Banking contract extract remains in those replacement files;
no third-party notice is invented for independently authored material.
[Contributor rules](../CONTRIBUTING.md) now narrowly allow accurate attribution
for permitted specifications without authorizing private customer material.
This does not settle unrelated advisory-feed or dependency redistribution rights.

## Single-Package Correction

Only `joserfc==1.7.1` changes to `joserfc==1.7.6`; all other 94 reference
versions, direct requirements, FastMCP/MCP/OTel and packaging pins are unchanged.
Both actual clean host environments pass constrained installation, toolchain
verification and `pip check`: Python 3.11.15 has 95 distributions; Python 3.13.16
has 92 (existing version-conditional backports differ). The image remains on
its approved Python 3.13 line; this is host compatibility, not a new image build.

[GHSA-9pg5-8c7x-5hfx](https://github.com/advisories/GHSA-9pg5-8c7x-5hfx)
(CVE-2026-119284) lists `<1.7.6` / patched 1.7.6. The
[repository advisory](https://github.com/authlib/joserfc/security/advisories/GHSA-9pg5-8c7x-5hfx)
still describes `<=1.7.4` / 1.7.5. Both claims are retained privately; no blanket
prior-exploitability conclusion follows. The selected
[released source](https://github.com/authlib/joserfc/blob/1.7.6/src/joserfc/_rfc7797/compact.py)
checks compact-input length before splitting. A 38-byte bytes-subclass canary
with a 24-byte total configured limit reaches split on old 1.7.1 and is rejected
first on 1.7.6. Valid HMAC verification and wrong-key rejection also pass; this
is not a memory-exhaustion benchmark or a new authentication implementation.

The official 1.7.6 wheel SHA-256 is
`e2d72e3fa937ed8ddd42ad8c1cc337a43e7ffd02efa572a2aa15e2764a05b506`.
All 55 Python members match both installations, and the relevant wheel source
matches the released tag. Requires-Python `>=3.10` and cryptography `>=45.0.1`
are satisfied by Studio's existing Python floor and cryptography 50.0.0.
Authlib 1.9.1 and fastmcp-slim's server extra both introduce joserfc; no new direct
dependency is added. Existing tools regenerate the current SBOM, audit and
licenses; the complete strict audit covers all 95 exact pins with zero findings,
omissions or skipped packages at this observation. Historical clean audits remain
point-in-time results, not current or whole-image clearance.

## Executed Proof And Limits

The Notes route/runtime proof used Studio
`af30ac4a9bfdeaa35bc31e833234db3c69d5f038` and the frozen Engine above.
Later test-only, documentation and evidence commits do not change that fixture,
its recipe or production behavior. Reference host: macOS 26.7.1 build 25G241,
arm64, Java 17.0.18 Homebrew, Maven 3.9.12. No generated code was patched.

- Normal project open, package write, Engine schema validation, strict MCP
  generation and Studio Build & Run build endpoint succeeded. One separately
  executed `mvn -B -q clean verify` ran **1 test, 0 skipped/failures/errors**;
  Studio's packaging-only build receives no test-execution credit.
- Loopback-only Java/H2 startup and POST `/notes` (201), GET detail (200) and
  GET collection (200) preserve the submitted label/state and generated identity.
  The app is stopped afterward. This is HTTP/backend automation, not browser
  observation or a claim of authenticated deployment readiness.
- Separate MCP proof passes strict MCP success, deliberate broken-command
  automatic CLI fallback, and strict MCP refusal. Real child modules are observed;
  fallback cannot satisfy strict success.
- Normal Python 3.11 non-smoke suite with Engine discovery: **2549 passed,
  17 skipped, 32 deselected**, one existing Authlib legacy-JOSE warning. All 17
  skips are unavailable optional KS subprocess cases; none is real-Engine proof.
  Required L2: **1 passed**. Python 3.13 focused checks: **357 passed, no skips**.
  The local suite used the `af30ac4` working tree plus the new self-contained
  contract test; subsequent focused real-Engine/manifest/newcomer checks passed
  **108 tests, no skips**, including the retained file/staging/batch assertions.
  Final automatic CI identifies the committed candidate separately.
- Initial failures are retained: a form-vs-JSON test setup error; five fixture
  consumers requiring path/canonical-field alignment; stale global-session and
  interpreter-symlink harness setup; and a missing required-body flag in the new
  synthetic proof. These were fixture/harness repairs, not relaxed Engine guards.

Reproduction uses the existing constrained setup, then runs the affected tests,
normal non-smoke/L2 selections and
`scripts/proof_run_engine_mcp_generate.py --engine-repo "$ENGINE" --engine-python "$ENGINE_PYTHON"`
against the frozen clean Engine. The dependency record documents existing
[regeneration tooling](handover-evidence/dependencies.md). Exact final-head CI
and required external Claude review are recorded in the draft PR, not inferred
from local results. Private logs, verified public artifacts, helper snapshots,
runtime receipt and checksums are retained outside the public tree; a clone
cannot recreate those historical observations from committed prose alone.

| Retained proof input/result | SHA-256 |
|---|---|
| Frozen Engine archive | `5bc59f4486ac32e20d28db87b9e088162e1010fb56720df46b73ff786ed5730a` |
| Notes runtime receipt | `d352110824a075d4d1cb36991ff13a483bd8c3e9126bc6f23c223d31ed70fbcd` |
| Full local non-smoke log | `2d8705f7fab6f98d55f41b54a7f2b1cd3e6d2af629028cf4ab13c2f531be24f6` |
| Complete strict audit execution log | `79d30422388543b2563e1dde76bb7e7857d7ef0c6fdf05c8c71598633ca07e1e` |

## Initial Claude Review And Repair Round 1

Claude's initial independent review at
`5efaf59cfb16c23538d52140ea4e0323ffff0216` requested changes. This is repair/
re-review round **1 of 2**. **Dated clarification (2026-11-07):** independent
re-review approved `47d4aab5f50e39eb6e4bdc683fbb794fa2646254`;
[original PR #323](https://github.com/santosh-sh/EdgeForgeStudio/pull/323) was
subsequently merged. That review covers the bounded cleanup, not release acceptance.

- `ParcelResponse` now uses `/parcel-notes` and its detail route, yielding
  path-derived `ParcelNote`, not schema-normalized `Parcel`. Parser/display,
  operation candidates, canonical mapping targets and Step 3 ownership are
  asserted; raw browser selection remains `ParcelResponse`. Component-response
  references, parameterized media, nested Data, enum and wrapper/object guards
  remain intact. Production naming code is unchanged.
- The three-file parser/upload/selection set passed **122 tests, no skips**, on
  Python 3.11.15 and 3.13.16. The builder's M1/M2 mutation runs used a two-file,
  **106-test** subset: each produced **4 failures / 102 passes**. Independent
  three-file mutation selections produced **4 failures / 118 passes**. M1
  ignored both path-derived canonical overrides; M2 disabled hyphen splitting.
  In those main M1/M2 runs, Step 3 stopped at an earlier page-text assertion;
  separate reviewer controls established the later canonical-selection assertion.
  These are distinct selections and observations, not one 122-test result.
  Controls used disposable tracked-tree copies, leaving the worktree unmutated.
- The [March summary](test-results/durable-crud-proof-2026-03-31.md) again records
  Studio's merged-through-PR20 baseline and Engine `c37d4d2`, advanced from
  `e4baebe` through merged Engine PR #54. The later private recovery revision is
  explicitly not a March execution baseline; no Studio SHA is invented.
- The JWS citation above now points to released `_rfc7797/compact.py`, verified
  byte-identical to that member of the retained checksum-verified 1.7.6 wheel.
  Dependency pins and audit/SBOM/license evidence are unchanged by this repair.
- The affected real-Engine adapter suite passes **49 tests, no skips**, against
  the same frozen Engine `89f1030`. Both CLI and strict MCP retain ingestion,
  source-label and failure checks, now also asserting `BatchTriggerController.java`
  alongside the file writer, staging writer and batch job.

The initial full-suite difference is environmental, not new test credit: both
runs collected 2,566 non-smoke cases; local execution passed 2,549 and skipped 17,
whereas CI passed 2,521 and skipped 45. The extra 28 CI skips are 15 fixed-width
contiguity parity, 6 Engine generate/assess, 4 regeneration-reference parity,
2 file-layout contract and 1 Engine-schema case. The other 17 are optional KS
subprocess cases skipped in both environments. CI does not execute the affected
real-Engine proof; the explicit local run above does. Skips are not passes.

Notes inputs/helpers and production/dependency bytes remain applicable to the
recorded runtime Studio `af30ac4` and frozen Engine, independently checked by
source/archive comparison. No manual Java/Maven/HTTP, image, dependency-scan or
full Suite campaign was repeated. New-head automatic CI and focused Claude
re-review are recorded in the PR; earlier evidence and initial review remain
dated, not transferred approvals.

## Remaining Gates

Current tracked-tree and changed-document/link/secret checks exclude unrelated
untracked checkout files; no original history scan or public import is performed.
No Engine advisory-file exclusion is copied into Studio. Inherited private
pip/ensurepip, OS/native/JDK/Maven/stage findings, source-specific rights questions,
font limitation and A11y-01 (one FAIL, three NOT RUN) remain unchanged and OPEN.
KA remains OFF by default; manifest 2.0, independently versioned Studio snapshots,
local/shared anonymous isolation, gateway/direct-port and adopter authorization
boundaries are not altered. Apache-2.0/DCO and the
[pending ownership, security-route activation and publication gates](publication-preparation.md#remaining-maintainer-decisions)
remain binding. Final selected Studio/Engine image proof and coordinated
acceptance are later work. Human merge and external exact-head review remain
separate; no approval or risk acceptance is implied here.
