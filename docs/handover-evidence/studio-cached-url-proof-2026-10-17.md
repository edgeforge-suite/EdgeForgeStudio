# Cached-URL real-Engine fixture correction

Candidate `EF-V5-STUDIO-CACHED-URL-PROOF-FIX-S1`, revision 1. Observed
2026-10-17 America/Chicago (execution continued into 2026-10-18 UTC).
This repairs test evidence, not production behavior, M2 or release acceptance.

## Source and environment

- Studio base: `f46e61cbb90a93e1dfe48b685cb6aad2abe75156` (merged #316).
- Tested correction: `e0ef176d117d566faf426d1fcc2e4e5afb6d80ba`.
  Later evidence-only commits do not change this tested implementation.
- Frozen merged Engine: `ba56abd1e0ff946260e96f3a3b715564fc0b740d`.
  A task-owned committed-source archive, not the moving sibling worktree, was
  used unchanged. Engine archive SHA-256:
  `59830a166fc5bd4e00548223ab8f3356a04af4d5b8abf081ac095702e7669f54`.
- macOS 26.5 build 25F71, arm64; Python 3.11.15 in a fresh task-owned venv;
  constrained MCP 1.30.0 and FastMCP 3.4.0. Packaging verification and `pip check`
  passed. Studio's unchanged constraints supply the test environment; this is
  not a separate Engine dependency-refresh campaign.
- The primary Studio/Engine checkouts had no tracked changes at entry. Their
  unrelated untracked files and environments were left untouched.

## Original failure and bounded correction

The [#316 record](studio-mcp-correction-2026-10-15.md) retains the historical
failed observation. Reproduction on the base above returned pytest exit 1:

The diagnostic identified an unresolved selected write operation on the
historical interface. Identifying external labels are omitted from this public
summary; the unchanged original failure log remains in private development history.

The shared `_full_session()` selects/maps `createAccount`, while the former
cached OpenAPI defined only `GET /accounts`, `listAccounts`. The corrected
test-local contract defines `POST /accounts`, `createAccount`, a JSON Account
request and a 201 Account response. The existing fields and request/response
mappings agree; the shared fixture is unchanged.

The [integration tests](../../tests/test_appbuilder_integration.py) still assert
the cached-only `serverOnly` field reaches generated `Account.java`, both cache
locations preserve identical `Source manifest:` labels referring to
`app-definition.yaml`, and no `.studio-openapi-` label leaks. A delegating
`Popen` subclass observes the real child without substituting execution/results.
Each transport must start exactly one correct CLI/MCP child; strict MCP must
return the `generate_app` command identity. A CLI fallback cannot satisfy this.

Two negative controls change only the cached operation ID, retaining the
selected `createAccount`. Both CLI and strict MCP must refuse it with the
selected-operation diagnostic, no sample fallback and no generated Account.
No strict validation or cache confinement was relaxed.

## Reproduction and validation

Set `ENGINE` to a clean archive/checkout of the frozen Engine above and `PY` to
the isolated Studio Python environment. From the identified Studio source:

```bash
export EDGEFORGE_ENGINE_REPO="$ENGINE"
export EDGEFORGE_STUDIO_ENGINE_MCP_COMMAND="$PY"
"$PY" -m pytest tests/test_appbuilder_integration.py tests/test_package_writer.py -q -rs
"$PY" -m pytest tests/ -q -m "not smoke" -rs
"$PY" -m pytest tests/smoke/test_l2_two_session_smoke.py -q -m "smoke and l2" -rs
git diff --check
```

For the original reproduction, run
`TestRunGenerate::test_real_engine_cached_url_generation_preserves_ingestion_and_source_label`
in `tests/test_appbuilder_integration.py` at the base SHA with the same Engine and
environment. That original failure occurs in CLI before MCP. The corrected
positive test and both new negative controls execute real MCP, not just a client
mock or fallback.

- Original reproduction: **1 failed**, expected, exit 1.
- Corrected integration plus package-writer consumers: **100 passed, no skips**.
  This includes all four pre-existing real-Engine cases and both new negative
  controls, with Engine discovery enabled.
- L2 two-session smoke: **1 passed, no skips**.
- Complete non-smoke suite: **2526 passed, 17 skipped, 32 deselected** in
  79.78 seconds. All 17 skips are `tests/test_ks_integration.py` subprocess cases:
  `knowledge_server` is not installed in this task-owned environment. No
  real-Engine case skipped. The 32 smoke cases are deselected by the normal CI
  selection; the required L2 entry above is executed separately.

The per-case skip inventory is retained in JUnit XML and the source/environment
receipt. Normal CI does not provision the Engine; its availability skips do not
establish this real-Engine proof.

Retained evidence SHA-256:

| Record | SHA-256 |
|---|---|
| Original-failure JUnit XML | `9ad7b656a607018551379fa623e0787bd06c3dcfc0903c369882804190bbe8ac` |
| Focused JUnit XML | `e03811ccb6a1624eca9eacfa00e947f37b02bd999d5c493e789a450ddeb5bb66` |
| Non-smoke JUnit XML | `c3d18c61aa7da4ec26df9876c8004cf6567202e255ff8bf5a4cdd701055d2bac` |
| Source/environment and per-case receipt | `0b11b9c13213b771d941830ff97fe77d4d4ead3028ebb9390598128bed544485` |

## Retention and boundaries

The task's private retained packet, `Studio-Cached-URL-Proof-2026-10-17`, holds
base/tested Studio archives, the frozen Engine archive, original failure,
corrected/focused/full/L2 logs and JUnit XML, environment/source receipt and
checksums. These private diagnostic inputs are not a public download or retention
SLA. A fresh clone can rerun the test with the frozen Engine; it cannot reconstruct
the historical execution's diagnostics without that packet. Final CI and
independent exact-head review are separate from local test observations.

Only tests, this evidence/index and the changelog change. No application,
dependency, transport, shared fixture, Engine or KS source changes; no image
build/scan, Maven campaign, native accessibility or full Suite L5. Unavailable KS
or other optional proofs are not represented as passes. The selected release pair
still needs its own applicable verification; whole-image findings and M2 remain
open. Human merge is separate.

Public-tree amendment (2026-11-02): neutralized the original diagnostic only; historical SHAs, results and receipt hashes are unchanged. Current synthetic fixtures are not credited with the old result.
