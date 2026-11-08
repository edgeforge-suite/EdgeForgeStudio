# EdgeForge Studio — Historical Implementation Plan

> **Historical snapshot.** Captured 2026-04-21 and retained for decision and sequencing
> history. It is not current implementation or planning authority. Use
> [`studio-context.md`](studio-context.md) and [`studio-architecture.md`](studio-architecture.md)
> for current Studio truth. Current suite planning lives in the Engine
> [enterprise readiness roadmap](https://github.com/santosh-sh/EdgeForge/blob/main/docs/enterprise-readiness-roadmap.md)
> and [generated tracker](https://github.com/santosh-sh/EdgeForge/tree/main/docs/tracker).
>
> **2026-08-22 reconciliation:** shared multi-session isolation has shipped;
> passthrough navigation now uses `/upstream` and `/passthrough` and is regression-tested;
> manifest 2.0 and Studio project snapshot 1.4 are separate current contracts. Studio
> `4.2.0` remains unreleased, and A11y-01 remains open.

## Historical State At Capture

Studio v1 is already a frozen product baseline, not an open proving track.

The baseline recorded by this April 2026 plan was:

- Studio `main` included merged work through PR `#70`
- CRUD wizard path working end to end
- Step 8 Build & Run included in baseline
- Step 1 archetype selector included in baseline
- constrained passthrough-router authoring/export included in the baseline; the
  then-stale registry mapping was later corrected to the already-working
  `/upstream` -> `/passthrough` route flow
- step registry foundation included via PR `#61`
- Kafka wizard authoring included via PRs `#62` / `#63`
- S1A save/open project included via PR `#54`
- Step 1 Knowledge Workspace foundation included via PR `#67`
- durable KS save/open linkage (`studio_project_schema_version: "1.1"`) included via PR `#68`
- CRUD Step 3 field suggestion review with batched KS write-back included via PR `#69`
- Step 7 KS provenance review, Step 8 `evidence-trail.json` export, and manifest revision tracking included via PR `#70`
- Phase 4 Engine MCP `generate_app` adapter included with subprocess fallback and reusable proof runner
- Design gates B1-B4 completed in the Engine repo via PR `#114`
- Knowledge Server backend baseline complete with stable `suggestion_id`, persisted suggestion `status`, and `submit_suggestion_decisions(...)`
- staged downstream explicitly deferred

The bounded Studio `generate_app` MCP slice was part of the historical `v1.5.0`
baseline. At the time of this plan, the named Studio baseline was `v2.0.0`, which
added the bounded field-suggestion-only KS MVP on top of that Engine MCP foundation.

The former backlog pointer in this plan has been superseded. Current planning uses:

- [Engine enterprise readiness roadmap](https://github.com/santosh-sh/EdgeForge/blob/main/docs/enterprise-readiness-roadmap.md)
- [Generated suite tracker](https://github.com/santosh-sh/EdgeForge/tree/main/docs/tracker)

## Historical Immediate Sequence

### Status recorded in April 2026

- Phase 4 Kafka authoring: COMPLETE
  - step registry foundation (PR `#61`)
  - Kafka wizard topics, routes, transforms (PRs `#62` / `#63`)
- S1A save/open project: COMPLETE (PR `#54`)
- Design gates B1-B4: COMPLETE (Engine PR `#114`)
- KS backend baseline: COMPLETE
  - all 12 tools implemented
  - wire protocol verified
- bounded field-suggestion-only Studio KS MVP: COMPLETE
  - Step 1 Knowledge Workspace foundation (PR `#67`)
  - durable save/open linkage and workspace state (PR `#68`)
  - CRUD Step 3 field suggestion review with batched write-back (PR `#69`)
  - Step 7 provenance review and Step 8 `evidence-trail.json` export (PR `#70`)
- The then-current Engine backlog has since been replaced by the roadmap/tracker
  pointers at the top of this document.

### Phase 5 status recorded in April 2026

The bounded field-suggestion-only Studio KS MVP is now implemented on `main`.

Current delivered coverage is:

- Step 1 Knowledge Workspace
  - upload / ingest
  - document list / refresh
  - search
  - document read / viewer
  - field catalog browse
  - degraded-mode handling when KS is unavailable
- save/open schema evolution to `studio_project_schema_version: "1.1"`
  - durable `project_id`
  - durable `ks_project_id`
  - `ks_active`
  - workspace review / evidence / revision placeholders
- CRUD Step 3 field suggestion review only
  - accept / edit / reject
  - batched `submit_suggestion_decisions(...)` write-back
  - current Studio-owned review history and evidence links
- Step 7 provenance review for current KS-backed field review history
- Step 8 `evidence-trail.json` sidecar export plus manifest revision tracking

Manual smoke / proof of the shipped KS MVP is now complete and is captured in
the committed Studio smoke-proof artifact. The next work is follow-on UX
polish and broader future KS scope, not MVP acceptance proof.

### Follow-on KS work after the shipped MVP

- broader non-field suggestion flows
  - rules
  - mappings
  - route/config scopes
- broader step attachment beyond the current CRUD Step 3 field review surface
- manifest prefill from accepted suggestions
- Step 1 / Step 3 UX scale-up beyond the current bounded panels
- richer reconnect automation on reopen
- LegacyExtractor design-first work in Phase 6

## Historical Phase Map

- Phase 2 = EdgeForge v1 closed baseline
- Phase 3 = production quality hardening — complete
- Phase 4 = Engine MCP + Kafka Studio authoring — complete
- Phase 5 = Knowledge Server MCP / Studio field-suggestion-only MVP — implemented on `main`; manual smoke/proof completed, with follow-on UX/scope work remaining
- Phase 6 = LegacyExtractor MCP

## Current Planning Alignment

Studio work should use the current suite-level planning anchors:

- [Engine enterprise readiness roadmap](https://github.com/santosh-sh/EdgeForge/blob/main/docs/enterprise-readiness-roadmap.md)
- [Generated suite tracker](https://github.com/santosh-sh/EdgeForge/tree/main/docs/tracker)

What that means in practice:

- Studio should reference the suite-level roadmap and sequencing docs, not restate them as Studio-owned work
- Studio should treat the design gates as prerequisites, not parallel implementation work
- Studio should preserve the paired manifest-2.0 semantic and topology boundary,
  including constrained passthrough, until any broader redesign is approved with
  matching Engine support

## Guardrails

- Keep PRs tightly scoped to the selected slice
- No staged downstream implementation work
- No passthrough scope broadening
- No breaking manifest redesign
- No Studio-first implementation of planned Phase 3 concepts before Engine readiness
- No coupling of Studio save/open project files to the Engine manifest contract

## Historical Deferred Scope

At the time of this snapshot, the following work was deferred. Shared multi-session
isolation and durable project/session storage have since shipped; real authentication,
SSO, and RBAC remain deferred.

- staged downstream (`Entity -> staging -> downstream`)
- broader passthrough-router modeling than the then-proven contract
- real proxy/OIDC authentication, SSO, and RBAC
- cross-replica shared storage beyond the shipped process/filesystem posture
- package re-import as a substitute for Studio-native save/open
- React/SPA rewrite
- LegacyExtractor Studio integration before a design doc exists
- SSO / LOB / RBAC (S2-S4)
- any change that breaks S1A save/open compatibility
- any manifest addition beyond 2.0 before the paired Engine schema exists

## Historical Acceptance Orientation

Phase 3 and Kafka Studio authoring were closed, and the field-suggestion-only KS
Studio MVP acceptance proof was completed. The committed
[smoke-proof record](test-results/studio-ks-mvp-smoke-proof-2026-04-20.md) covers
document ingest, CRUD Step 3 field review, Step 7 provenance visibility, and
Step 8 `evidence-trail.json` export working together. Only the follow-on UX and
broader KS scope described above remained after this historical checkpoint.
