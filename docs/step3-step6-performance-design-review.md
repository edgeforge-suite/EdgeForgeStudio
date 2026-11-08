# Performance Design Review — Step 3 / Step 6 Authoring & Review

> Captures the Studio Step 3 / Step 6 performance work: the completed KA-OFF render
> baseline (PR181/182), the deferred KA-OFF ideas, and the **now-implemented**
> request-level KA-ON suggestion batching (PR186/187/188). Authored by the Claude
> Studio design thread; cross-reviewed by Codex. Updated 2026-06-06.

## Status

- **KA-ON batching: IMPLEMENTED and merged** — the design in this doc is fully built
  (see [Implemented](#implemented) below). No further KA-ON batching work is planned.
- **Completed earlier (KA-OFF render baseline):** PR181 (Step 3 inline JS externalized)
  and PR182 (Step 6 no-op `GET /rules` no longer rewrites session) are merged to `main`.
- **Deferred (evidence-gated):** the remaining KA-OFF render ideas (see
  [Deferred KA-OFF Items](#deferred-ka-off-items)). Revisit **only** if manual testing
  shows KA-OFF slowness — no speculative optimization.
- **Guardrail:** Studio-only. No KS / Engine / TestBench / manifest / package /
  export / Evidence Trail behavior change. No UX v2 patterns. KA-OFF stays clean.

## Implemented

Request-level KA-ON batching shipped across three slices, each with its own
call-count + parity + KA-OFF tests. The original design (endpoint shape, grouped
transport-equivalent envelope, reuse-existing-normalizers, no durable cache) was
followed; the layered **Claude Review → Codex Cross-Review → Agreed Recommendation**
sections below remain the historical design record.

| Slice | PR | What shipped | Result |
|---|---|---|---|
| Step 3 full review | PR186 | `GET /entities/ks/full-review` (`app/routes/entities.py`) backed by `assist_service.batch_fetch_step3_full_review`; `loadKaFullReviewRows` calls it once | up to **3N → 1** KS context |
| Step 3 page badges | PR187 | `GET /entities` badge loop replaced with `assist_service.batch_fetch_step3_badge_counts` | **2N → 1** KS context |
| Step 6 rule badges | PR188 | `GET /rules` rule-badge loop replaced with `assist_service.get_rule_suggestion_badges_batch` | **2N → 1** KS context |

End-to-end on `main`:

- Step 3 full review = **1** `ks_client` context, independent of selected-entity count `N`.
- Step 3 page GET badges = **1** context.
- Step 6 GET = **2 bounded contexts** — `get_advisory_conflicts` (already batched, left
  unchanged) + the rule-badge batch — deliberately **not fused**, per the Agreed
  Recommendation.
- **KA-OFF = 0 spawns** across all three surfaces; review overlays, generated-impact
  labels, empty-state/warning copy, drawer behavior, evidence laziness, and export /
  Evidence Trail are unchanged. Single-entity endpoints/helpers retained for
  compatibility, direct drawers, and tests.

## Scope Of This Document

| In scope | Out of scope |
|---|---|
| Record completed Step 3/6 KA-OFF perf baseline as context | Re-litigating PR181/182 |
| Design request-level KA-ON suggestion batching | KS-side suggestion logic / Engine generation |
| Endpoint + response shape + helper refactor plan | Durable / session-level suggestion caches |
| Call-count test strategy | Wall-clock perf assertions |
| Risks to review overlays / Evidence Trail / KA-OFF | Manifest / export / package shape changes |

---

## Completed Baseline (Context Only)

These shipped and re-smoked green (focused + full suite, KA-OFF clean,
export/generate/build regression passed, durable all-runtime edge-contract demo
stable). They are **not** under review here; listed so the KA-ON design isn't
confused with KA-OFF render work.

- **PR181 — Step 3 render performance.** The large Step 3 inline `<script>` was
  externalized to `app/static/js/step3_entities.js` (now a cacheable static asset).
  Step 3 HTML size and browser parse cost dropped. (`main`: `0cdea80`, `3ba1818`,
  `6c8dad2`.)
- **PR182 — Step 6 GET purity.** A no-op `GET /rules` no longer rewrites persisted
  session state; first-time rule auto-population semantics preserved. (`main`:
  `b606544`, `5e94a7b`.)

### Deferred KA-OFF Items

Explicitly deferred and **must not** be mixed into the KA-ON batching PR. Revisit
only if new manual testing shows KA-OFF slowness:

- Step 3 bootstrap/sample payload lazy loading
- Step 3 inactive-DOM progressive rendering
- Step 6 broader view-model profiling
- Step 6 JS extraction
- General static-asset optimization

---

## Current-State Truth (KA-ON, verified against `main`)

### The actual cost unit: a KS subprocess spawn

`ks_client(...)` (`app/integrations/ks_integration.py:369`) is a `@contextmanager`
whose `start()` runs `subprocess.Popen(...)` plus an **MCP stdio handshake**, and
whose exit **terminates** the subprocess. So **every `with ks_client(...)` block is
one subprocess spawn + handshake + teardown** — not a cheap pooled connection.
Amplification is therefore measured in *context entries*, and the goal is to make
that count independent of the selected-entity count `N`.

### Where amplification happens today

| Surface | Path | Cost |
|---|---|---|
| Step 3 full review | `loadKaFullReviewRows` (`app/static/js/step3_entities.js:716`) fans out per entity to `/entities/ks/suggestions` + `/entities/ks/drawer?scope=validations` + `/entities/ks/drawer?scope=identity_role` | up to **3N** HTTP calls → up to **3N** spawns |
| Step 3 page GET badges | `GET /entities` loops entities calling `get_validation_hint_badge` + `get_identity_role_suggestion_badge` (`app/routes/entities.py:2091–2101`) | **2N** spawns |
| Step 6 rule badges | `get_rule_suggestion_badge` issues `_fetch_manifest_suggestions` for `rules` **and** `cross_entity_rules` per entity | **2N** spawns |

### Already-batched — leave unchanged

The good pattern already exists in-repo and should be the template for the fix
(open one context, loop inside it):

- `get_advisory_conflicts` (`app/services/assist_service.py:173`) opens **one**
  `ks_client` and loops `canonical_entities` inside it. **Already O(1) in N.**
- `_fetch_conflict_resolution_rows` (`app/services/assist_service.py:1067`) opens
  one context and loops queries inside.
- `fetch_field_suggestions` already does catalog + suggest in **one** context.

> **Correction to the original roadmap:** Step 6 "advisory conflicts loop per
> entity" is *already batched*. The only Step 6 amplifier is the rule badges.

---

## Claude Review — Recommended Design

**Verdict: ready to build.** Request-level batching (not caching) is correct, and
the codebase already contains the exact pattern. The amplification is in *context
creation*, so the fix is "share one `ks_client` across entities/scopes" while
**reusing the existing normalization / review-status overlay code verbatim**.

### 1. Endpoint shape

Add **`GET /entities/ks/full-review`**:

- Lives in the entities router beside `/ks/suggestions` and `/ks/drawer` (natural
  owner; Step 3 is the surface).
- Read-only **GET** (no state mutation — consistent with PR182 GET-purity).
- Entities derived server-side via the existing `_selected_canonical_entities(session)`.
  Optional `?entities=a,b` **debug/test override only**, defaulting to session-derived.

### 2. Response shape — "transport-equivalent grouped envelope"

Return the **same per-scope sub-payloads the single endpoints already return**,
grouped by entity, so `loadKaFullReviewRows` keeps 100% of its client-side
row-assembly / category / status / overlay logic and merely iterates instead of
awaiting 3N fetches.

```jsonc
{
  "ok": true,
  "selected_entities": ["Customer", "Account"],
  "identity_review_entities": ["Customer"],          // mirrors INITIAL_IDENTITY_REVIEW_ENTITIES gating
  "entities": [
    {
      "entity": "Customer",
      "field":         { "suggestions": [...], "warnings": [...], "empty": false, "empty_reason": null },  // == /ks/suggestions body
      "validations":   { "scopes": [...], "warnings": [...], "empty": false },                              // == /ks/drawer?scope=validations body
      "identity_role": { "scopes": [...], "warnings": [...], "empty": false }                               // == /ks/drawer?scope=identity_role; null when not eligible
    }
  ],
  "warnings": []                                       // global only; per-entity warnings stay inside each block
}
```

**Rejected alternative:** a server-pre-assembled `rows[]`. It would move client-side
overlay state (`kaFullInitialReviewStatus`, unsaved accept/edit/reject) to the
server and change behavior. Keep assembly on the client.

### 3. Helpers to add / refactor

- **Add** `assist_service.batch_fetch_suggestions(session, pairs, *, max_suggestions)`
  → opens **one** `ks_client`, loops `(entity, scope)`, returns raw
  `suggest_manifest_candidates` results keyed by pair; returns empty with **zero**
  spawns when KA is off. (Mirror `get_advisory_conflicts`.)
- **Add** route `GET /entities/ks/full-review` → calls the batch fetcher once, then
  applies the **existing** `_normalize_step3_field_suggestions`,
  `_normalize_*_drawer_payload`, `_apply_*_review_statuses` per entity, and assembles
  the grouped envelope.
- **Add** a Step 6 rule-badge batch helper (one context; `rules` + `cross_entity_rules`
  per entity → counts).
- **Refactor** the Step 3 page GET badge loop (`app/routes/entities.py:2091`) to use
  the shared batch fetcher (2N → 1).
- **Refactor** `loadKaFullReviewRows` (`app/static/js/step3_entities.js:716`) to one
  fetch + local iteration; keep all existing client logic.

### 4. What stays unchanged

Single-entity `/ks/suggestions` and `/ks/drawer` (compat / direct drawers / tests /
debug); all `*-review` submit endpoints; `get_advisory_conflicts` and
`_fetch_conflict_resolution_rows` (already batched); `/ks/evidence`; the
normalization / overlay / generated-impact logic; Evidence Trail; manifest / export /
package; KA-OFF behavior; the deferred KA-OFF roadmap items.

### 5. Call-count targets

O(1) `ks_client` contexts per page/action, **independent of N**:

| Surface | Before | Target |
|---|---|---|
| Step 3 full review | up to 3N | **1** |
| Step 3 page GET badges | 2N | **1** |
| Step 6 rule badges | 2N | **1** |
| Step 6 advisory conflicts | 1 | 1 (unchanged) |

Ideal = exactly 1 per action; acceptable = small constant. **Caveat:** keep evidence
chains lazy (`/ks/evidence` on row-expand). Eagerly fetching per-row evidence in the
batch would silently reintroduce per-row contexts and break the target.

### 6. Test strategy (call-count + behavior preservation, no wall-clock)

- **Call-count invariance:** spy/patch `ks_client` (or `KSClient.start`) and assert
  the enter-count for `/entities/ks/full-review` is the **same bounded constant for 1
  entity and for 5 entities** (target `== 1`), not `3N`. Same for the Step 3 GET and
  Step 6 rule-badge paths.
- **Behavior equivalence (golden):** for the same entity set, assert each batched
  per-entity sub-block is structurally equal to the corresponding single-endpoint
  response — suggestions, scopes/rows, per-entity warnings, **review-status
  overlays**, empty/empty_reason all identical.
- **KA-OFF:** `/ks/full-review` returns clean empty and the spy records **0** spawns.
- **Fault isolation:** simulate KS failure for one entity; other entities still
  return, the failed one carries a warning, no 500.
- **Regression:** `test_step3_ks_field_suggestions.py`, `test_rules_route.py`,
  `test_studio_ka_off.py`, `test_export_evidence_trail.py` unchanged and green.

### 7. Risks

- **Overlay drift (primary risk):** mitigate by reusing the existing
  normalization/overlay functions per entity — never reimplement them in the batch
  path. The batch endpoint = (1 shared fetch) + (existing per-entity normalization loop).
- **Per-entity warnings / empty-state copy:** must stay per-entity (the frontend
  prefixes `${entity}:`). Don't collapse into the global `warnings`.
- **Fault isolation:** today each entity is independently try/caught client-side;
  the batch must preserve that resilience server-side.
- **Deterministic order:** loop `selected_entities` in saved order so client filters
  render stably.
- **Evidence payloads:** keep lazy; `/ks/evidence` unchanged.

---

## Codex Cross-Review

Codex Studio review verified the load-bearing repo claims against the PR branch on
2026-06-05:

- `ks_client(...)` is a context manager that creates a new `KSClient`, calls
  `start()`, runs `subprocess.Popen(...)`, performs the MCP stdio initialize /
  initialized handshake, and calls `stop()` on context exit. Counting context entries
  is the right proxy for subprocess amplification.
- Step 3 full review currently fans out per selected entity to field suggestions,
  validation drawer, and identity-role drawer. Identity-role fetches are gated to
  identity-eligible entities, so **3N is an upper bound** rather than a guaranteed
  count for every project.
- Step 3 page badges are **2N** for validation + identity-role badge helpers.
- Step 6 rule badges are **2N** for `rules` + `cross_entity_rules`.
- `get_advisory_conflicts`, `_fetch_conflict_resolution_rows`, and
  `fetch_field_suggestions` already use one KS context and loop inside it, so they
  should be templates, not targets for broad rewrites.

Cross-review answers:

1. **Endpoint placement & method:** `GET /entities/ks/full-review` is the right owner
   and verb. It belongs beside the existing Step 3 KS field/drawer routes because the
   full-width Step 3 KA Review is the caller. Keep any optional entity override test-
   only or strictly validated against selected session entities.
2. **Response envelope:** grouped transport-equivalent payloads are the right shape,
   but the build PR should be precise: either include the complete single-endpoint
   bodies under each entity block or explicitly document that the block preserves the
   **frontend-consumed subshape** (`suggestions[]` / `warnings[]` for fields and
   `scopes[].rows[]` / `warnings[]` for drawers). Do not move row assembly or
   review-status overlays server-side.
3. **Helper boundary:** the seam is correct, with one caveat. A generic
   `batch_fetch_suggestions` helper must handle both manifest-scope suggestions and
   the field-suggestion path's catalog gate (`read_field_catalog` + `fields` scope
   suggestion). If that makes the helper muddy, split into a generic manifest batcher
   plus a small field-specific batch helper rather than weakening `/entities/ks/suggestions`
   parity.
4. **Step 6:** leave advisory conflicts unchanged. Batch only rule badges first. Keep
   advisory conflicts and rule badges as two bounded contexts for clarity; fusing them
   is optional later and not needed to remove the 2N amplifier.
5. **Call-count target:** literal `== 1` is realistic for Step 3 full review if the
   implementation loops all catalog/suggest/drawer tool calls inside one KS context.
   Tests should still phrase acceptance as a small constant independent of entity
   count, with `== 1` as the intended target for the first build slice.
6. **Evidence:** keep evidence lazy. Nothing in current full-review table assembly
   requires eager per-row evidence-chain fetches; row expansion can continue to call
   `/entities/ks/evidence`.
7. **Test seam:** patching `ks_client` is the best stable assertion point because the
   design target is context entry count. `KSClient.start` is useful for lower-level
   proof, but `ks_client` spies keep route/service tests simpler and independent of
   subprocess internals.

---

## Agreed Recommendation

Proceed to build, with wording/test clarifications above.

First build slice:

1. Add a request-scoped Step 3 full-review batch path:
   `GET /entities/ks/full-review`.
2. Return grouped per-entity field / validation / identity-role subpayloads that preserve
   the frontend-consumed shape of the existing single endpoints.
3. Repoint `loadKaFullReviewRows` to the batched endpoint while keeping all current
   client-side row assembly, generated-impact labels, review-status overlays, empty-state
   handling, and warning prefixing.
4. Keep existing `/entities/ks/suggestions`, `/entities/ks/drawer`,
   `/entities/ks/evidence`, and review-submit endpoints unchanged.
5. Add call-count, KA-OFF, warning/empty-state, and single-endpoint parity tests.

Then follow with Step 3 page badge batching and Step 6 rule-badge batching. Do not mix
the deferred KA-OFF render/payload optimizations into this KA-ON batching work.

---

## Open Questions To Resolve In The Build PR

1. **Eager vs lazy evidence in full review:** confirm rows need only a `has_evidence`
   flag (chain fetched on expand via `/ks/evidence`). If any row needs eager
   evidence, the O(1) target changes — flag it.
2. **`max_suggestions` for counts vs full rows:** can one batch helper serve both
   badge counts and full rows, or do badges need a cheaper count-only KS argument?
3. **Override param:** include `?entities=` test/debug override (default
   session-derived), or derive strictly from session?
4. **Cross-agent review:** the build PR's primary reviewer must not be its author —
   hand build ↔ review across agents.

---

## Recommended Build Slices

1. **Slice 1 (first):** `batch_fetch_suggestions` helper + `GET /entities/ks/full-review`
   returning the grouped envelope, reusing existing normalizers. Add call-count +
   golden-equivalence + KA-OFF + fault-isolation tests. *Backend-only; frontend still
   works via the old path.*
2. **Slice 2:** Repoint `loadKaFullReviewRows` to the batched endpoint (one fetch).
   Frontend behavior-parity test.
3. **Slice 3:** Step 3 page GET badges → shared batch helper (2N → 1).
4. **Slice 4:** Step 6 rule-badge batch helper (2N → 1). Leave advisory conflicts as-is.
