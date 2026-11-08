# S8 newcomer journey: dated reference proof

Candidate `EF-V5-STUDIO-S8-NEWCOMER-JOURNEY`, revision 1. Authority:
[adopted XR-4/S8 and parallel ownership](https://github.com/santosh-sh/EdgeForge/blob/64f51d0bac92b4c70f26c8f5f067888717df7b14/docs/external-review-backlog.md#xr-4-one-newcomer-journey).
This is bounded builder evidence; independent exact-head review and CI are
recorded on the PR, not inferred from this report. No merge or release is authorized.

## Identity and method

- Studio base: `fa64cdbfbb1fccc5638a919df24e03def281faf8`.
- Tested implementation: `6900db9d05f719cf8b66c6946a46792721d4338a`.
- Engine: clean, detached merged `64f51d0bac92b4c70f26c8f5f067888717df7b14`;
  no Engine #327 code or moving sibling environment was used.
- macOS 26.5 ARM64, Python 3.11.15, Homebrew OpenJDK 17.0.18+0,
  Apache Maven 3.9.12. Fresh separate Studio/Engine virtual environments;
  Studio's packaging verification passed with pip 26.2.1, setuptools 83.0.0,
  wheel 0.48.0, followed by its constrained requirements installation.
- Maintained `fs-account-servicing` project opened unchanged through
  `/project/open`. Step 1 explicitly selected `springboot-legacy-compatible`
  (Java 17/H2) for this local exercise; the committed enterprise sample is unchanged.
- Separate fresh state and Maven cache. Preview flag enabled, local single-user
  mode, KA OFF, no KS install. All application exposure was loopback-only.

The [sanitized receipt](newcomer-journey-2026-10-09.json) is the runner's actual
output, including timestamps, source/sample identity, ordered routes, request and
response content, executed test counts and artifact hashes. Evidence-only commits
after the tested implementation do not claim a new runtime observation.

The [task guide](../newcomer-journey.md) and
[runner](../../scripts/newcomer_journey.py) describe the same route/terminal flow.
Run from a clean Studio checkout using its installed Python environment:

```sh
.venv/bin/python scripts/newcomer_journey.py \
  --engine-repo /path/to/clean/pinned/EdgeForge \
  --work-dir /tmp/studio-newcomer-proof-UNIQUE
```

This is **real HTTP route automation**, not browser observation. No session was
injected and no direct Engine invocation replaced a Studio authoring/generation/
preview/apply action. The developer-owned Java edit and terminal Maven/Java steps
are explicit fixture/operator actions. Generated output, HTML, raw logs, Maven
cache and source environments remain outside the repository. Raw logs/HTML may
include local paths or session tokens and must not be published unredacted.

## What passed

| Step | Observed proof |
|---|---|
| Install/start/open/review | Clean-source installations; loopback Studio start; normal project upload and Step 1/3 saves; Steps 2-8 pages returned 200. |
| Export/validate/generate | Public Studio routes called the frozen real Engine; manifest 2.0; no export/generation warnings. |
| Studio Build & Run | Actual `/export/build` and `/export/run`; create 201 and read-by-ID 200 with expected synthetic values, missing ID 404. The button skips tests and is not credited as test execution. |
| Developer seam before apply | `AccountService.beforeCreate` set `customerId` to `CUST-S8-HOOK`; Maven verify executed 1 generated test, zero failures/errors/skips; real create/read returned the hook value. |
| Supported change | Step 2 upload, Step 3 selection/samples/mappings and Step 6 default rule added `nickname` with `UNNAMED` default. Existing rules/contracts retained. |
| Approval safety | Real preview hash became stale after a temporary developer-file edit; Studio refused apply and generated base remained unchanged. The file was restored and a newly displayed plan reviewed; no hash was forged or bypassed. |
| Apply | Public preview/apply accepted the additive plan and emitted `V4__alter_account_add_nickname.sql`. |
| Preservation and rebuild | Entire developer service byte-identical, generated base refreshed; Maven verify again executed 1 test with zero failures/errors/skips. Create/read returned both the hook value and `SYNTHETIC-NICKNAME`; missing ID remained 404. |
| Cleanup | Generated apps and the isolated Studio server stopped. |

## Automated validation

- Focused journey, sample-pack, Build & Run, regeneration and KA-OFF suite:
  **124 passed**. New proof controls reject missing success envelopes, missing or
  escaping baselines, wrong customization ownership, changed developer bytes,
  missing approvals, wrong application content and skipped-only Maven results.
- Full non-smoke suite: **2,377 passed, 17 skipped, 32 deselected** in 84.30s.
  All 17 skips were optional KS subprocess cases because `knowledge_server` was
  not installed. They are not required journey steps; KS was intentionally absent.
- L2 two-session smoke: **1 passed**.
- Changed-file Ruff and `git diff --check`: passed.
- Existing destructive/unsafe refusal tests remain unchanged and binding.
  Feasibility also observed refusal of a new non-null column without a default;
  the positive flow declares a default through Studio instead of weakening that gate.

Required exact-head CI and independent review are separate from these local
results. No workflow, dependency lock, production module or sample-pack source
was changed. Engine, KS, Dockerfiles, image evidence and Suite tracker were untouched.

## Limits and refresh triggers

Studio currently keeps Step 8 Build & Run on the original output while
preview/apply targets a managed copy. The guide names this boundary: customization
and post-regeneration Maven/Java execution use the current managed reference from
Save Project. This proof does not claim the UI automatically switches build paths.

H2 starts fresh for each process. This proves the emitted migrations execute, not
continuity of production data across upgrades. Flyway emits its existing H2
version-range warning; passing verification is not universal database compatibility.
The generated test is the shipped context-start test; the additional HTTP assertions
provide the meaningful behavior evidence, not an invented broader generated test suite.

No filtered-list, computed-read, EOD delivery, arbitrary generated-file edit,
production authorization, image, full Maven matrix, full L5 or native accessibility
claim is made. A11y-01 remains open with its existing disclosed observation limits.
KA remained OFF; focused no-KS-call controls remain binding. This is not overall
Suite acceptance. The final selected Studio/Engine pair needs applicability review
and relevant journey re-proof, particularly after route, mapping, ownership,
preview/apply, build/runtime or target-profile changes.

## Review follow-up: 2026-10-10 UTC

The original receipt above is retained unchanged. The
[follow-up receipt](newcomer-journey-2026-10-10.json) records a fresh complete run
at implementation `54ef0391ce89ca76225e828ebeae0371bd4eda78`, with the same frozen
Engine and reference tool versions. Subsequent evidence-only changes do not
claim another runtime observation. These corrections address Claude's
[nonblocking review](https://github.com/santosh-sh/EdgeForgeStudio/pull/312#issuecomment-6092980410).

- Corrected the guide: the actual migration adds a **nullable** `VARCHAR(255)`
  column with SQL default `UNNAMED`; the generated Java field has an initializer.
- Added an omitted-field create/read case. The request contains no `nickname`;
  create returns 201 and read returns 200, both with `nickname: UNNAMED` and the
  preserved `customerId: CUST-S8-HOOK`. Explicit-null behavior is not claimed.
- Recorded both successful `GET /regen/preview` observations in route order,
  before the stale refusal and the fresh approved apply respectively.
- Clarified how a second terminal obtains the isolated state path and how to
  inspect the downloaded project JSON for the current managed reference.
- Engine installation guidance remains unchanged; constraining that graph is
  a separate cross-repository documentation/validation follow-up.

The complete journey passed, including whole-file and executable preservation,
stale-approval refusal, explicit nickname responses and both Maven verifications
(1 actual test each; zero failures/errors/skips). The same method and limitations
above apply: this is not a new browser or native accessibility observation.

Follow-up validation: **132 focused tests passed**; full non-smoke **2,385 passed,
17 optional KS skips, 32 deselected** in 91.36s; L2 **1 passed**. Changed-file Ruff
and diff hygiene passed. New failure controls reject a missing or incorrect
default on create/read, a lost hook, failed reads and failed preview responses.
Exact-head CI and independent re-review are recorded separately on PR #312.
