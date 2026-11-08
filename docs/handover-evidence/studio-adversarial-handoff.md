# Studio adversarial caller handoff

Build evidence, not independent approval, risk acceptance, M2 clearance, or a
final release-pair selection. Observation: **2026-10-02 America/Chicago**
(receipt capture **2026-10-03 UTC**). Scope: EF-V5-M2-STUDIO-CONSOLIDATED-S1
revision 1, AC6-7 and the handoff portion of AC8; image work is separate.

## Sources and runtimes

- Historical independent Studio base: `14a379fffaeeb8b3334b5f6c937714f3aa90e159`.
- Historical tested product/test head: `e621544d26c43296b1694e20f85bb4d24204755c`;
  first submitted head `01ef8600deb378f7ba7fe8da115921888a2cd5be`.
  The original JSON receipt remains a historical record, not current source hashes.
  The regeneration repair below has a separate tested source and receipt.
- Read-only Engine archive: `5793cb2f8779322ce13c5e758806b54e5e9d835a`.
- Read-only KS archive: `d5cf86b6f77ab4d12a898707f4048e04beb2702f`.
- Native host: macOS 26.5 arm64, CPython 3.11.15. Separate task-owned venvs:
  Studio FastMCP 3.4.0 / MCP 1.28.1 / Pydantic 2.11.7; Engine FastMCP 3.2.3 /
  MCP 1.30.0 / Pydantic 2.11.7; KS FastMCP 3.4.2 / MCP 1.28.1 /
  Pydantic 2.13.4. Bootstrap pip was 26.0.1. Complete local freezes are hashed
  in [the receipt](studio-adversarial-handoff-receipt.json), not uploaded.

The archives came from `git archive` of the exact commits, not mutable sibling
checkouts. Engine used its `requirements-lock.txt`; KS used `constraints.txt`;
Studio used `constraints.txt`. No sibling dependency/source changes, image build,
dependency-pin change, or package publication is part of this proof.

## Request boundary and controls

[`tests/test_adversarial_handoff.py`](../../tests/test_adversarial_handoff.py)
uses the real FastAPI request middleware, anonymous signed cookies, CSRF,
SQLite session store, and server-minted workspaces. Only synthetic cookie IDs
and authoring fixtures are supplied by existing L2/L4-style helpers; the
identity provider, signing/verification, store, routes, path resolution, and
live child calls are not substituted.

| Surface | Executed proof and disposition |
|---|---|
| Uploaded project / restored state | Real `/project/open` accepts a synthetic snapshot with hostile output/repo/export/revision/binding paths. Foreign workspace/session metadata cannot replace the store's stamps; last export is dropped. Separate persisted-state corruption probes test read-side defenses for absolute, `..`, and directory-symlink paths. |
| Direct authoring / review requests | Foreign session/project query IDs do not select another session's manifest; foreign CSRF cannot authorize an entity update. An own-CSRF update and own export/download succeed. The other session's selections and manifest remain unchanged. Foreign revision and managed-package references cannot make review/regen read another workspace; bogus apply does not write there. A tampered cookie creates a different anonymous session. |
| Before unauthorized access | Guards at both Python file-open seams fail on the first foreign content read/write attempt. Export artifacts, manifests, output roots, package dirs/files, ZIP destinations, generation output, KS roots/DB/uploads/files are exercised with symlinks and sentinels. Requests reject without opening the foreign files or invoking children. Imported absolute/traversal mapping paths cannot be written. |
| Own-session Engine control | Two actual `/export/generate` requests produce separate regular-file packages and `pom.xml` outputs through the pinned Engine stdio process. Popen observation delegates unchanged; actual commands, cwd, roots and shared flags are retained locally. |
| Hostile environment | Actual callers overwrite inherited broad/Engine-repo roots and shared flag `0`: generation has only its own export root; regen plan/apply has caller-derived export, managed-package and applicable scratch roots, all under its workspace. Shared flag is `1`. Each KS child has its own `ks` root/database and shared flag `1`. The Engine install tree is import-only, not an allowed data root. |
| Real Engine negatives | Absolute/traversal/import-only spec inputs are rejected by the frozen manifest contract. A nested symlink is now rejected by Studio before spawn. Auxiliary foreign manifest/output calls replay the complete configuration observed from the real HTTP caller, without selecting roots in the test; the frozen child's entrypoint checks reject them and create no foreign output. Victim and existing generated-output hashes remain unchanged. These auxiliary calls are distinguished from public request attacks. |
| No shared generation CLI fallback / KA OFF | A nonexistent configured MCP executable reaches the real integration failure path; browser errors redact its path and explicitly report generation fallback disabled. Generation-proof children are MCP only. Regen plan/apply intentionally uses CLI; this is not generation fallback. KA-OFF setup/import/export/generate/review/regen/knowledge requests never start KS. |
| Applicable KS | Real request uploads/search/read use two pinned children and separate databases. Foreign document ID read/delete attempts do not expose/delete the owner's document; its own read still succeeds. An auxiliary out-of-root ingest on the same route-created live client fails with a redacted error, leaving its sentinel unchanged. No test supplies new roots for that auxiliary probe. |

## Narrow fixes and an important limit

The original directory containment did not guard the concrete manifest/artifact
file, writer target, ZIP target, KS subtree/DB/upload file, or generation output.
Those concrete targets now use the existing shared-mode containment helper.
Review confines the manifest itself before reading a restored revision.
The writer converts containment failures to its existing controlled error.

The frozen Engine accepted a package whose local OpenAPI spec was a symlink to
the other session (failed exploratory receipt retained). Its translator reads
that local spec without applying the entrypoint root helper. **Do not interpret
Engine entrypoint roots as a filesystem sandbox or universal nested-input check.**
Studio exports regular files. The initial shared preflight covered only
validate/assess/generate; independent review found regen preview/apply bypassed it.
The repair extends one shared preflight to the export and managed generated
package trees before regen status hashing and plan/apply, with adapter-entrypoint
checks also protecting direct Studio service calls. It rejects package symlinks
before the covered child invocation without Engine edits. Universal child nested-input confinement
remains an Engine-owner decision; this receipt does not accept that residual risk
or claim external/direct Engine clients receive the same Studio preflight.

The preflight is a static filesystem check, not atomic no-follow opens, protection
against a concurrent host filesystem writer, hardlinks/mounts, or a malicious
plugin. Anonymous signed-cookie isolation is not real authentication and does not
protect against theft of another browser's bearer cookie. Local mode remains
operator-directed; local paths and existing local-mode regressions are unchanged.

## Regeneration repair: 2026-10-03

P2-1 from the independent PR review is addressed by builder changes; **new-head
independent review remains pending**, and old-head approval is not carried forward.
The branch was updated by a non-rewriting merge of main
`baa73a495ae3a45e7d74e0b1fcf33e66dca6a757` (merged image #308), merge commit
`70f39b079b313665a4bf06492985975eb217f339`. Repair product/test commit:
`d28162ce3075eb5475fb50a354502714f662c632`.

- `preflight_engine_package` is shared by export, regen preview/apply and all
  public Engine adapter entrypoints: validate, assess, generate, plan and apply.
  The regen check runs before status hashing and is repeated before child calls.
- Eighteen new ordinary non-smoke cases cover preview/apply, file/directory
  symlinks, export/managed trees, direct adapters and local operator controls.
  Shared rejection asserts no attempted Engine call and no foreign file opens.
- The additional real-child case uses two shipped anonymous sessions and real
  generation, then successful own-session CLI plan/apply. A referenced export
  spec file/directory link and managed-tree links target the other session's
  deliberately invalid synthetic YAML. Eight hostile responses reject before
  any child starts/content opens, with no marker leakage and stable victim hashes.
  Own preview succeeds after removing the links; KA OFF starts zero KS children.
- Actual commands are observed without replacing transport or root derivation.
  Generation runs Engine FastMCP 3.2.3 in the isolated Engine interpreter. Regen
  CLI uses Studio Python 3.11.15/Pydantic 2.11.7/PyYAML 6.0.2 by the existing
  adapter contract; it does not run an Engine MCP server in Studio's FastMCP 3.4.0.
  KS retains its isolated FastMCP 3.4.2 environment. No runtime pins were changed.
- Product-head handoff: **42 passed, zero skipped**, 13.26s (39 ordinary cases,
  three marked live cases). Focused invocation/containment/isolation/regen/
  adapter suites: **189 passed, zero skipped**, 16.63s. L2: **one passed**.
  Strict constraints audit: no known vulnerabilities. Changed-file Ruff and
  directory gitleaks passed. Whole-repository Ruff remains advisory.

[Repair receipt](studio-adversarial-regen-repair-receipt.json) preserves new
source/raw identities separately. Full commands, final-head CI checkout/tree
verification, complete tests/skips and review instructions are outside Git at
`/private/tmp/edgeforge-studio-pr309-regen-fix-proof/review-packet.md`.
No image build/fix, auth change, Engine/KS edit, risk acceptance or release is
part of this repair. Regen remains disabled by default; local mode is unchanged.

## Historical results and reproduction

Local product-head command (with archived dependencies installed separately):

```bash
EDGEFORGE_STUDIO_ENGINE_REPO="$PROOF/engine" \
EDGEFORGE_STUDIO_KS_REPO="$PROOF/ks" \
FASTMCP_SHOW_SERVER_BANNER=0 \
"$PROOF/studio-venv/bin/python" -m pytest tests/test_adversarial_handoff.py -v -s \
  --basetemp="$PROOF/reproduction-unique"
```

Here `PROOF` is a fresh operator-owned temporary root. Archive each frozen commit
there, create `.venv` inside each archive, install the Engine and KS requirements
with their respective constraints, and install Studio requirements with Studio
constraints in `studio-venv`. Do not change sibling checkouts. The three marked
live tests skip only when the corresponding repository variable is absent;
invalid explicitly configured runtimes fail. Use a new basetemp, never another
task's temporary directory.

| Check | Actual result |
|---|---|
| Focused request + archived children | **23 passed**, zero skipped, 7.68 seconds at product head. Two marked `smoke/l4` cases; 21 durable non-smoke request regressions run in ordinary CI. |
| Full `pytest tests -q -m 'not smoke'` | **2,225 passed, 18 skipped, 31 deselected**, 72.47 seconds. This run preceded the final smoke-only limiter-reset import/line; product behavior and non-smoke assertions were unchanged. Exact submitted-head CI must be checked separately. |
| L2 in-process smoke | **1 passed**, zero skipped. |
| Changed-file Ruff | Passed. Whole-repository Ruff remains advisory. |
| Gitleaks 8.30.1 directory scan | Exit 0, no leaks; local report is `[]`. |

The full suite's 17 optional direct-KS tests and one optional Engine-schema test
were skipped and are not credited as
executed live proof. Full L5, Java Build & Run, final image/release-pair assessment,
SSO/OIDC, atomic filesystem race proof, and all Engine tools/contracts were not
rerun or claimed. The request tests reuse existing smoke helpers, not another
orchestrator, pin system, CI framework, port, or persistent service.

Raw receipts, prior failing runs, hashes, actual commands, final-head CI/source
verification and fresh-review instructions are retained outside Git at
`/private/tmp/edgeforge-studio-consolidated-handoff-proof/review-packet.md`.
The initial exploratory baseline used the default Engine lookup through an
existing sibling symlink once; it is excluded from pinned-child claims. Subsequent
credited live runs explicitly use the archives. Sibling tracked/untracked status
matched the saved baseline; ignored interpreter bytecode is not asserted immutable.
Historical legacy unit tests can also auto-discover a sibling Engine; those runs
are not frozen-child claims. Repair unit/real proofs explicitly select the archives.
No independent verdict is embedded in this commit.
