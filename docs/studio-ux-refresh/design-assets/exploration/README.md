# B2 — Exploratory Mocks: Kafka-router · REST-passthrough · Knowledge Assist

> **Status: EXPLORATORY — not the current build contract.** Every mock carries the on-canvas badge.
> These are pre-capture design *options* applying the locked CRUD-refresh pattern language
> (implementation-design.md §1.5 tokens, board+focused-editor, reviewable seed patches, single
> readiness source). Produced by Fable (2026-07-06) from [`capture-digest.md`](capture-digest.md)
> (source-grounded) + the B2 brief. The eventual **blind capture pass still runs** (L16
> capture-first) and reconciles against these. **KA build stays gated** on the production-readiness /
> data-handling decision — the KA mock does not unblock it.

| Mock | Surface | The design idea |
|---|---|---|
| [`kafka-route-model-board`](kafka-route-model-board.html) (+ .png) | Kafka Route Model — **the densest page in the app** | Routes board (row = topic-in → pattern → targets, blocked-first) + focused route editor in **four blocks** (intake · routing rules · targets · NACK/runtime collapsed). Blocker granularity = rule → missing target, with a ghost "create target" card. Pattern is the family axis: **FNF / R·R / RTR** monograms (exploratory sub-palette cyan/violet/navy). |
| [`kafka-transforms-table`](kafka-transforms-table.html) (+ .png) | Kafka Transform Mappings | Routes list + **one native table per route** (source → target → coercion → value-map · origin chip). Deterministic seeds from the pasted schema pair as a keep/blank patch; KA suggestions a clearly opt-in, dashed strip. |
| [`passthrough-route-transform`](passthrough-route-transform.html) (+ .png) | Passthrough Route & Transform | **Deliberately NOT a board** — the section-shaped page stays one page. Tune: readiness strip (ops/targets/coverage/transforms), `describe-spec` operations surfaced as a **pick-to-seed patch**, compact target/route/transform rows, unrouted-operation as the needs-action wash. |
| [`ka-suggestion-review`](ka-suggestion-review.html) (+ .png) | Knowledge Assist suggestion review | Queue board (grouped by entity, applies-generated-change first) + **focused review = before/after diff + evidence citations** (deep-link to Workspace) + the real 3-way staged lifecycle (Apply / Apply edited / Reject → "Save suggestion review (N)"). Gate banner: opt-in, OFF by default, build gated. One provenance legend: DERIVED lilac vs KA-APPLIED teal. |

**Cross-cutting choices made (all flagged as assumptions to confirm in capture):** route-pattern
sub-palette hues · "Draft" state for incomplete routes · rule-level blocker granularity ·
schema-pair transform seeding as a deterministic helper · per-target transform tabs · passthrough
target-row fields · KA queue grouping/sort + standalone-queue framing vs today's per-step drawers.

**What stays true to source:** archetype rails with n/a steps (from `base.html` nav_steps) · the
Kafka nested config fields (from `defaultRouterConfig`) · transform row shapes incl. coercion enum ·
`describe-spec` as the existing deterministic seed · the KA 3-way staged batch lifecycle
(`data-suggestion-stage` accepted/edited/rejected → "Save suggestion review (N)") · step-number fix
(rail is the truth; the current templates mis-number their `<h2>`s — flagged in the digest).

PNGs rendered headless-Chrome @1480px. Everything lives outside the repos by policy.

---

## Codex review — folded in (2026-07-06)

**Verdict:** "Solid exploratory directions… keep them as B2 seed material for the later blind
capture→apply pass." All four mocks: **Keep.** No wrong-headed choices. Exploratory framing "unmissable."

**Source-accuracy corrections applied:**
- **Passthrough (substantive fix):** the **inbound operation picker** is populated from the **Step-2
  upstream OpenAPI already in session**, NOT `/passthrough/describe-spec` — `describe-spec` describes
  **downstream target** specs. → `passthrough-route-transform.{html,png}` re-worded + re-rendered;
  digest corrected.
- **Kafka coercion:** the UI's `none` option = blank/no-coercion, **not** a stored enum value (persisted
  enum is only `major_to_minor_units` / `minor_to_major_units`). → digest annotated.
- Kafka route model, KA lifecycle, step-number bug: **confirmed accurate** as captured.

**Per-assumption calls (Codex → recorded):**
| Assumption | Call |
|---|---|
| Route-pattern sub-palette (FNF/R·R/RTR) | **Keep** — as a *pattern accent* (not true contract family), always with readable labels. |
| Rule-level blocker granularity | **Keep** — better UX; needs a Kafka readiness producer later. |
| Schema-pair transform seeding | **Keep but prove** — not implemented today; must be exact/normalized, reviewable, no overwrite. |
| Passthrough stays section-shaped | **Keep strongly** — board would be over-design unless capture proves scale pain. |
| Readiness item-kinds | **Keep, refine names** → namespace: `kafka_topic_pair` / `kafka_route` / `kafka_transform_set`. |
| KA standalone queue vs per-step drawers | **Reconsider as horizon** — good north star, but capture should compare vs improving existing drawers first; KA stays gated. |
| Exploratory framing | **Keep** — good discipline. |

**Codex's build order for the eventual B2 track:** (1) Kafka step-number hygiene · (2) Kafka Route Model
board + focused editor · (3) Kafka Transform table + deterministic schema-pair seed *proof* · (4)
passthrough section polish · (5) **KA review redesign only after the KA readiness/data-handling gate.**
