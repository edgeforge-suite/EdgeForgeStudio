# PR-24 pre-flip evidence

Date: 2026-08-02 · maintainer sign-off added 2026-08-09

Studio base: `5624fe4` (`origin/main`)

Target: unreleased Studio `4.2.0`

This record executes the implementation design §4.2 gate before the refreshed UX becomes Studio's
only presentation. It does not authorize a `5.0.0` tag, a release, or a promoted demo baseline.

## Checklist

- [x] **Initiative prerequisites.** Git history at `5624fe4` contains every non-retired UX-refresh PR
  through PR-23, including PR-09a and PR-17a. PR-24a merged as PR #273 (`9c28c7b`); its governing
  A11y-01 amendment merged as PR #275 (`6dcdb50`). There were no open Studio PRs when this work began.
- [x] **Both rollout states before removal.** On the unmodified base, the default suite completed with
  `1850 passed, 40 skipped`; the refresh+split suite completed with
  `1849 passed, 40 skipped, 1 deselected`. The deselection was the expected test that asserted the old
  default-off deployment state.
- [x] **Round-trip, parity, and security.** Both full runs included the project round-trip, save-one
  no-op/parity, readiness/export parity, inspector/path safety, and stored-DOM-XSS sink inventory
  suites. The post-removal gate also fingerprints every remaining dynamic HTML sink.
- [x] **PR-24a accessibility.** The durable gate covers Steps 2/3/4/5/6/7, board keyboard contracts,
  both Step-5 presentations, live-region attributes, and every success/failure writer-to-region
  binding. The recorded keyboard-only and VoiceOver navigation walkthroughs are in
  `pr24a-a11y-walkthrough.md`.
- [x] **Action-2 DDA end to end.** A refreshed CRUD authoring session was completed with an explicit
  `Account.accountId` persistence identity, passed Studio readiness, and exported 14 package files.
  EdgeForge at `00998d2` generated 31 application files; the generated harness passed and
  `mvn -q -DskipTests package` exited 0. This validates authoring state through readiness, export,
  Engine generation, and generated-app compilation without changing the Engine contract.
- [x] **Old-project compatibility.** A project produced by the Studio `v4.1.0` `_crud_session` fixture
  loaded into current Studio in both pre-flip flag states with model-deep-equal state. Re-exported
  packages were identical across six durable files after excluding the intentionally timestamped
  Studio-project JSON and normalizing timestamp-only evidence fields. The August 2 review then found
  a second historical shape: interface-owned operations and mappings with an empty
  `classified_operations` inventory. The fix is regression-tested through Open Project → Step 3
  Save Selection → Export. A replay of the six-operation demo fixture preserved both interfaces,
  all samples and mappings, and emitted `upstream/account-mapping.yaml` plus
  `upstream/transaction-mapping.yaml`.
- [x] **Maintainer demo sign-off.** On August 9, 2026, the maintainer drove the actual PR #280 Docker
  build at `8a3c63c` using the pre-refresh `sample-account-project.json` fixture and the refreshed UI.
  The walkthrough reopened the historical project, re-ran Step 3 Save Selection without losing saved
  operations or mappings, exported and validated the package, generated and built the application,
  launched it through Studio, exercised persisted Account behavior, and successfully wrote the
  downstream XML output. The duplicate `GET /accounts` collision between an imported operation and
  baseline Engine CRUD was isolated as an Engine-generation issue with the existing Step 3 deselection
  workaround, not a PR-24 regression. **Demo verdict: passed.**
- [x] **Pinned baseline.** Studio tag `v4.1.0` resolves to `6537a75`. A detached checkout started
  successfully and returned HTTP 200 from `/`. No `v5` baseline was created.

## Accessibility release hold

> **Historical sequencing record.** This section records the PR-24 hold as approved in July 2026.
> The [proposed §7.3 amendment](implementation-design.md#a11y-01-v5-baseline-deferral) is non-operative
> until the Studio and Engine/Suite amendments are independently reviewed and merged. Once active,
> A11y-01 alone no longer blocks source publication, internal baselines/tags, public releases, or
> promoted demos. The issue remains an
> [open known limitation](https://github.com/santosh-sh/EdgeForgeStudio/issues/302), and the original
> evidence below is preserved rather than rewritten.

`A11y-01` remains mandatory before any tag, release, or promoted demo ships the refresh default-on.
PR-24a proved VoiceOver navigation and the structural announcement contract, but did not claim that
VoiceOver was observed speaking both success and validation-failure messages. This does not block the
PR-24 merge and must not be represented as completed release evidence.

## PR-24 implementation boundary

PR-24 removes the legacy browser render and handler paths, retires the two rollout environment
switches, and makes the desktop split responsive behavior standard. Existing whole-list HTTP routes
remain as compatibility APIs, but refreshed focused editors no longer call them. There is no manifest
or project-schema change, no `v5` tag, and no visual-polish work in this PR.

## Post-flip verification

- Default environment: `1857 passed, 40 skipped`.
- Retired settings explicitly false (`UX_REFRESH=false`, `UX_SPLIT=false`):
  `1857 passed, 40 skipped`.
- Retired settings explicitly true (`UX_REFRESH=true`, `UX_SPLIT=true`):
  `1857 passed, 40 skipped`.
- The focused PR-24 shell/legacy-removal, PR-24a accessibility, stored-DOM-XSS, and KA-off gates pass.
- `git diff --check`, Ruff, and rendered-script/Node syntax results are recorded in the PR description.
