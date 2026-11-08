# Deferred Design Review — Staged Downstream Pipeline

> Captures the saved future requirement to support `Entity -> staging table -> downstream file`, plus the April 2026 design review and cross-review notes. Updated 2026-04-07.

## Status

- **Current decision:** still deferred
- **Implementation timeline:** none
- **Reason:** the active manifest 2.0 cut does not add this capability, and the requirement remains explicitly out of the current release-alignment scope
- **Revisit point:** only after an explicit future cross-repo product decision

This is no longer blocked on Build & Run or on the passthrough MVP. Those are
already part of the established baseline. Even so, staged downstream remains
deferred and is not scheduled into the current Phase 3 / 4 / 5 / 6 plan.

## Requirement Summary

The current Studio + Engine flow uses the canonical entity as the hub for both outbound lanes:

- `Upstream API -> canonical entity`
- `canonical entity -> staging table handoff`
- `canonical entity -> downstream file`

The future requirement under consideration is a staged pipeline that better matches common enterprise batch/EOD processing:

- `Upstream API -> canonical entity`
- `canonical entity -> staging table`
- `staging table -> downstream file`

Likely future extensions after that:

- one entity -> multiple staging tables
- each staging table -> different downstream file / downstream app
- later optional transform/business logic while populating staging or while emitting downstream outputs

## Why This Requirement Exists

This request comes from a realistic enterprise modernization pattern:

- core or canonical business data is materialized into staging tables
- different downstream consumers often require different staging shapes
- EOD file generation frequently reads from staging, not directly from core entity persistence
- staging tables act as an explicit integration boundary for external jobs, reconciliations, and file extracts

That production pattern is different from the current EdgeForge v1 baseline, which intentionally keeps handoffs and downstreams as parallel outputs from the canonical model.

## Current-State Truth

### Studio today

Current Studio authoring/export is explicitly canonical-as-hub:

- downstream mappings are authored as `source: Entity.field -> target: downstream_field`
- handoff mappings are authored as `source: Entity.field -> target: staging_column`
- downstream interfaces and data handoffs are exported as separate, unlinked manifest sections

Relevant current files:

- `app/services/mapping_generator.py`
- `app/services/manifest_generator.py`
- `app/routes/downstream.py`
- `app/routes/handoffs.py`
- `app/templates/step4_downstream.html`
- `app/templates/step5_handoffs.html`

### Engine today

Current Engine translation/generation is also canonical-as-hub:

- `MappingDirection` supports only:
  - `UPSTREAM_TO_CANONICAL`
  - `CANONICAL_TO_DOWNSTREAM`
  - `CANONICAL_TO_HANDOFF`
- the manifest has no field linking a downstream interface to a handoff contract
- downstream and handoff translation are independent peer ingest paths
- generated batch code reads entity records from the repository and writes staging rows and downstream files in the same loop

Relevant current files:

- `EdgeForge/appbuilder/contracts/manifest.py`
- `EdgeForge/appbuilder/mapping/models.py`
- `EdgeForge/appbuilder/metadata/translation.py`
- `EdgeForge/appbuilder/generation/java_emitter.py`
- `EdgeForge/appbuilder/harness/checks.py`

## What That Means

Today the product supports:

- `Entity -> staging table`
- `Entity -> downstream file`

It does **not** support:

- `staging table -> downstream file`
- a downstream file that explicitly declares a staging table as its source
- one entity fan-out into multiple staging-driven downstream pipelines

## Claude Review — Validated Summary

Claude's review was largely correct and grounded in the current code:

- the current architecture is correctly described as `canonical-as-hub`
- the staged downstream requirement is not a small UI tweak
- the current manifest has no downstream-to-handoff linkage
- the current generated batch job writes staging and file from the entity, not from staged rows
- an additive extension is preferable to replacing the current canonical-to-downstream path

Claude's recommended direction:

- keep canonical-to-downstream as the default path
- add an optional downstream `source_handoff`
- introduce a new Engine mapping direction for handoff-to-downstream
- prove the core architecture in Engine first
- add Studio authoring support later

## Codex Cross-Review

I agree with the main diagnosis and direction, with three important refinements.

### 1. This is larger than a simple mapping extension

The hardest part is not the extra mapping direction alone. The real design question is staging lifecycle:

- is the staging table append-only or snapshot-style?
- what happens on rerun?
- how does the downstream file step know which rows belong to the current batch?
- does the file read the full table or only the rows staged in this execution?

Those batch semantics must be frozen before implementation.

### 2. The first contract change should stay narrow

For the first increment, avoid a broad generic source/target-contract redesign.

Prefer:

- optional downstream `source_handoff`
- new Engine mapping direction `handoff-to-downstream`
- keep current `canonical-to-downstream` unchanged

That gives backward compatibility and a focused proof surface.

### 3. Do Engine proof first, Studio second

The first implementation increment should not start in Studio.

Recommended order:

1. Engine contract + translation + generation proof
2. one hand-authored fixture proving staged downstream works
3. then Studio authoring/export support on the now-proven contract

That keeps the product change smaller and avoids building Studio UI against an unproven Engine topology.

## Agreed Recommendation

Treat this as a **future optional extension**, not a replacement for the current canonical-as-hub design.

Why that still fits after the v1 freeze:

- current canonical-to-downstream is already proven and useful
- many current packages do not need staging-driven downstream
- a staged pipeline is realistic and valuable for enterprise, but it should not
  expand the paired manifest 2.0 baseline without a separate cross-repo decision

## Challenge Points For The Future Revisit

These are the places most likely to matter when implementation eventually starts.

### 1. Batch lifecycle semantics

This remains the most important unresolved design area.

Questions:

- is the staging table cleared each run?
- are only current-run rows exported?
- is a run marker needed?
- if the batch fails after staging but before file output, what is the recovery model?

Until those are decided, the rest of the design stays underspecified.

### 2. Manifest contract shape

The first contract change should stay as small as possible.

Recommended first-step question:

- is `source_handoff` enough for V1?

Current answer: yes, unless the first Engine proof immediately exposes a stronger need.

### 3. Mapping source format

A broader source/target-contract abstraction may become useful later, but it should not be the first move.

For the first increment:

- downstream declares `source_handoff`
- downstream mapping source values use handoff-column context rather than a generalized graph model

### 4. Current one-contract-per-entity assumptions

The current Engine still has places where generation assumes one downstream file and one handoff contract per entity.

That is acceptable for the first staged proof, but it must be revisited before any fanout phase.

### 5. Studio UX complexity

The current wizard is already dense.

If staged downstream is added too early or too broadly, it will create confusion for authors who only need the simpler canonical-as-hub path.

That is why the recommendation remains:

- Engine proof first
- Studio support second
- advanced option, not default

## Revised Phased Revisit Plan

If this work is ever reactivated, the recommended order is still:

### Phase 0 — Requirement Freeze

Before code changes, explicitly decide:

- canonical-to-downstream remains default
- staged downstream is optional
- V1 of the staged feature supports only `staging-table -> fixed-width file`
- one downstream interface may reference at most one handoff
- no fanout in the first increment
- no outbound transform DSL in the first increment
- staging lifecycle semantics

### Phase A — Engine-Only Proof

Goal:

- prove `entity -> staging -> downstream` in Engine without any Studio UI change

Likely Engine changes:

- optional `source_handoff` on downstream contract
- new `HANDOFF_TO_DOWNSTREAM` mapping direction
- translation support for staged downstream linkage
- generated two-step batch flow:
  - stage canonical rows
  - read staged rows and emit downstream file
- focused harness checks for the new direction
- one hand-authored example fixture / proof lane

### Phase B — Studio Support

Goal:

- author/export the new staged downstream contract from the wizard

Likely Studio changes:

- downstream authoring adds optional data-source selection
- default remains `Canonical Entity`
- advanced option allows choosing a saved handoff table
- downstream mapping source hints switch from `Entity.field` to handoff columns when staging is selected
- manifest/mapping export supports the new contract shape

### Phase C — Integrated Studio-Led Proof

Goal:

- one Studio-authored enterprise proof for:
  - one entity
  - one staging table
  - one downstream file sourced from staging

### Phase D — Fanout Expansion

Only after the above is stable:

- one entity -> multiple staging tables
- one staging table -> multiple downstream outputs

### Phase E — Optional Outbound Transforms

Only after topology is proven:

- value/code translation
- formatting during staging or file emission
- conditional outbound field behavior

## Open Questions To Resolve When Revisited

These questions should be answered before implementation begins:

1. Should the first staged increment use snapshot semantics or append/history semantics?
2. Should the downstream file read the whole staging table or only current-run rows?
3. Does the first increment need a batch execution key or run marker?
4. Should handoff-to-downstream mappings reference handoff column names only, or fully qualified `table.column` paths?
5. Should Engine metadata store an explicit normalized downstream-to-handoff link in addition to the mappings?
6. For later fanout, what execution order is desired: stage once and emit many files, or stage separately per downstream lane?

## Deferred Decision

For now, this requirement is intentionally **saved, not started**.

The current working decision is:

- keep the design review
- do not start implementation
- do not add a timeline
- revisit only if a later explicit cross-repo decision makes it active
