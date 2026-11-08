# EdgeForge Studio — Phase 2 Backlog Closure

> Archived April 2026. Superseded by `studio-implementation-plan.md`
> and `EdgeForge/docs/EdgeForge Target State Features v1.md`.
>
> **Frozen record.** Updated 2026-04-10.

Phase 2 is now closed and frozen as **EdgeForge v1**. This file is no longer an active backlog for in-flight productization work. It is now the closure record for what Phase 2 delivered and what was intentionally carried forward or deferred.

## Phase 2 Closed Baseline

The frozen Studio v1 baseline includes:

- CRUD authoring flow across Steps 1-8
- Step 8 Build & Run support after generation
- Step 1 archetype selector
- constrained passthrough-router authoring and export
- Step 2 upload hardening
- prior Phase 2 polish and regression fixes already merged on `main`

The final Phase 2 freeze point for Studio is `main` through:

- PR `#41` Build & Run UI
- PR `#42` Step 2 upload hardening
- PR `#46` minimal Studio passthrough-router MVP
- PR `#47` Build & Run port/url/status polish

## Notable Phase 2 Items Closed on `main`

Earlier Phase 2 work that remains part of the v1 baseline includes:

- manifest-v1 export alignment
- Step 4/5 reorder to the canonical flow
- nested mapping validation fixes
- `field-comparison` rule authoring UI
- export error surfacing improvements
- Step 6 generated-ID warning heuristics
- Step 3 paginated-wrapper guidance
- Step 4/5 reload and serialization fixes
- Step 6 regex normalization

Those items are now baseline behavior, not open backlog entries.

## Carry-Forward Items After Phase 2 Close

Phase 2 is closed, but a small number of items carry forward into the next sequence.

### 1. Docs and release alignment

This is the active current PR track:

- sync living docs to the April 7, 2026 baseline
- document the `v1.0.0` freeze tag
- align phase numbering to 3 / 4 / 5 / 6

### 2. Planned Studio follow-up for Engine Phase 3

These are **planned, not started** Studio follow-ups that depend on Engine manifest/schema changes:

- entity type selector for `master record` vs `transaction/event`
- unique / idempotency key toggle on individual fields
- ID strategy panel for `UUID`, `sequence`, and `composite`

All three are additive `manifest-v1.1` ideas and must wait for Engine readiness.

### 3. Planned Studio-native save/open project support

This is a planned Studio UX follow-up, not current behavior:

- allow users to save in-progress Studio authoring work
- reopen it later without redoing Steps 1-6 from scratch
- keep the saved Studio project distinct from the exported Engine manifest package

The current Studio-local planning note is `docs/studio-save-load-project-plan.md`. It should stay aligned to the shared cross-repo design anchor in EdgeForge PR #93 (`docs/studio-save-load-design.md`).

This should remain:

- Studio-only in its first implementation
- file-based S1A save/open, not server-backed storage
- separate from Engine manifest contract changes
- separate from package re-import, which can be considered later as a distinct feature
- separate from S1B catalog/locking, SSO, LOB access, and RBAC, which should be revisited only after the Engine MCP phase clarifies the service boundary or real multi-user/shared-project needs appear

### 4. Later MCP-alignment work

After Phase 3 hardening stabilizes:

- Phase 4 = Engine MCP server alignment
- Phase 5 = Knowledge Server MCP alignment
- Phase 6 = LegacyExtractor MCP alignment

## Deferred With No Implementation Timeline

These items remain intentionally deferred:

- staged downstream (`Entity -> staging -> downstream`)
- passthrough-router scope beyond the current proven Engine contract
- breaking manifest redesign
- multi-session / multi-user support
- authentication
- long-term shared project storage
- direct Knowledge Server or LegacyExtractor product work before their MCP phases

## Current Passthrough Guardrail

The v1 passthrough Studio boundary remains:

- one upstream REST operation
- downstream systems and selected target operations
- one route field
- equality-match routing rows
- one default target
- flat transform mappings only
- no nested passthrough request modeling
- no per-target custom transform graphs

Studio should not broaden beyond this boundary until EdgeForge Engine explicitly extends the contract.
