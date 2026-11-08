# OpenAPI Proof Selection Lessons — 2026-03-31

## Goal

Capture what the last two Studio proof runs taught us about selecting real-world OpenAPI specs, so future Phase 3 / 4 / 5 proof runs can reuse a stable selection method instead of restarting the search each time.

This document is based on:

- `docs/test-results/crud-proof-smoke-2026-03-31-post-pr50.md`
- `docs/test-results/stronger-realworld-crud-proof-2026-03-31-configcat.md`

## What The Last Two Runs Established

### 1. Keep one stable control proof

The Petstore rerun after EdgeForge PR #50 was the correct control check.

Why it worked:

- already proven Studio path
- already proven Engine CRUD lane
- fast end-to-end signal
- good fit for “did a shared Engine change regress the known green path?”

Reusable lesson:

- after shared Engine changes, rerun the existing green CRUD control before expanding to a harder spec

### 2. Use a separate stronger real-world proof for expansion

The ConfigCat permission-group run was the right next stronger candidate.

Why it was a good expansion target:

- real business-domain API
- direct CRUD-style resource shape
- multiple path-param flows
- richer object shape than Petstore
- direct request/response schemas for the selected resource

What it revealed:

- Studio export stayed clean
- Engine validate/generate stayed clean
- the stronger contract exposed an Engine compile blocker that Petstore did not cover

Reusable lesson:

- one stronger real-world spec can reveal gaps that a minimal control spec will never trigger

## Candidate Selection Pattern To Reuse

Use a two-lane selection model for future proofs.

### Lane A: Control Proof

Purpose:

- confirm that the already-proven CRUD path still works after shared changes

Selection rule:

- use the last known green control spec
- keep the same entity + operation scope
- do not broaden unless the goal is specifically broader coverage

Current recommended control:

- Petstore CRUD proof via `scripts/proof_run_petstore.py`

### Lane B: Expansion Proof

Purpose:

- push one step beyond the control lane and find the next real compatibility boundary

Selection rule:

- choose one real public OpenAPI spec that is stronger than the control but still inside the currently intended product lane

Current recommended expansion baseline:

- ConfigCat permission-group scope via `scripts/proof_run_configcat_permission_groups.py`

## What Makes A Good Candidate

Prefer specs with these traits:

- OpenAPI 3.x or another format that Studio currently ingests cleanly
- one resource with direct create/list/get/update style paths
- direct request/response schemas, not wrapper-heavy `data/meta/links` envelopes
- path params and optionally query params
- meaningful required fields or enum-backed fields
- richer but still practical nested shapes
- manageable size for one-entity proof scope

Good signs:

- list response resolves to array items of the same entity schema
- single-item response resolves to the same entity schema
- create/update requests use direct request bodies
- the selected entity can be isolated to one interface and a small operation set

## What Makes A Bad Candidate For The Current CRUD Lane

Avoid or defer specs with these traits unless the current phase is explicitly targeting them:

- heavy response envelopes or generic wrappers
- huge polymorphic `allOf` / `oneOf` contract surfaces
- callback/webhook-first or orchestration-first APIs
- auth flow as the main feature under test
- router/event/message/Kafka-first contracts
- older Swagger patterns that do not expose request/response schemas in the way current Studio extraction expects

## Candidate Notes From This Round

### Petstore

Role:

- control proof

Why it remains useful:

- fast green baseline
- already proven end to end
- ideal for shared-regression checks

Limitation:

- too forgiving to expose some real-world codegen gaps

### ConfigCat Permission Groups

Role:

- stronger real-world CRUD proof

Why it was selected:

- stronger than Petstore without leaving the CRUD lane
- real business-domain API
- direct create/list/get/update path set
- path params
- enums
- nested array/object field
- richer field count and request/response shape

What it exposed:

- Engine codegen currently emits invalid Java method names from hyphenated operation IDs

Why this still counts as a useful proof:

- it isolated a concrete compile blocker with clear ownership

### Apideck CRM

Why it was not selected:

- too wrapper-heavy for the current Studio/Engine CRUD proof lane
- many useful resources return envelope-style response schemas instead of direct entity schemas

Reusable lesson:

- wrapper-heavy APIs should wait until we explicitly want to test wrapper/unwrapping support

### Data2CRM

Why it was not selected:

- older Swagger/body-parameter style did not map cleanly into current Studio request/response schema extraction
- it was likely to fail for ingestion-shape reasons instead of giving a clean CRUD proof signal

Reusable lesson:

- do not spend a proof cycle on a spec whose transport/schema shape is already outside the current extraction assumptions

## Reusable Selection Checklist

Before locking a candidate, answer these questions:

1. Is this a control run or an expansion run?
2. Does the spec stay inside the current product lane?
3. Can I isolate one entity and 3-4 operations?
4. Do create/list/get/update responses point to direct entity schemas?
5. Will failure teach us something new, or just confirm a known unsupported shape?
6. Can I pin the spec locally for reproducibility?

If the answer to 4 or 5 is “no”, skip the candidate.

## Reusable Execution Pattern

For future phases, keep the proof structure consistent:

1. Pick the lane:
   - control or expansion
2. Pin the public spec locally when practical
3. Keep the scope to one entity and a small operation set
4. Run the same Studio -> Engine -> generated app sequence
5. Record ownership precisely:
   - Studio
   - Engine
   - generated app
   - spec shape / out-of-scope construct

## How To Reuse This In Future Phases

### Phase 3-style follow-ups

Use:

- the Petstore control as the first regression gate
- one stronger direct-schema real-world CRUD candidate second

Best focus:

- whichever next capability still fits direct CRUD semantics

### Phase 4-style follow-ups

Use:

- the same control
- an expansion candidate that adds one new complexity axis only

Examples:

- more query/filter coverage
- richer nested objects
- one multi-entity relation

Avoid:

- combining multiple new complexity axes in one proof

### Phase 5-style follow-ups

Only broaden beyond the current candidate pattern if the product lane has explicitly expanded.

Examples of “later, not earlier” proof categories:

- wrapper/unwrapping-heavy APIs
- polymorphic contracts
- router/passthrough-first APIs
- auth-centric APIs

## Practical Recommendation

For future proof cycles:

- always keep one green control proof alive
- add only one stronger expansion proof at a time
- prefer candidates that fail for meaningful product reasons, not for obviously out-of-lane transport quirks
- pin public specs locally when possible so the proof is safer and more reproducible

That gives us a reusable proof ladder:

1. control stays green
2. expansion finds the next real boundary
3. once fixed, expansion becomes the next stronger baseline
