# Studio UX Refresh — Design Review Pass (Fable)

> **Status:** REVIEW PASS COMPLETE — verdict **adopt with changes** (all changes are execution-level;
> no concept-level objection). HALTED for the maintainer gate.
> **Subject:** [`proposal-final.md`](../proposal-final.md) (round-3 consolidation) + the four
> [`final-mockups/`](../final-mockups/).
> **Method:** full read of the proposal, all three Action-3 passes and all four cross-reviews, and —
> unlike the prior reviews — a **line-level read of the real Studio source** this proposal claims to
> change: `step2_upstream.html`, `step3_entities.html` (+ `step3_entities.js`, 1,881 lines),
> `step4_downstream.html` (displayed Step 5, 1,407 lines), `step5_handoffs.html` (displayed Step 4),
> `step6_rules.html` (1,167 lines), `step7_review.html`, `base.html`, `studio.js`, `studio.css`, plus
> the server-side readiness/completeness services. Everything below is grounded in that source.
> **Also delivered:** §11 resolutions — B1 (functional-zone tinting, applied to the Step-5 mock),
> B2/B3 scoping plans — and the two Action-4 gating decisions G1/G2, including a new Step-6 sketch
> ([`final-mockups/step6-rules-board-sketch.html`](../final-mockups/step6-rules-board-sketch.html)).
> **Date:** 2026-07-02. Design/docs only — no production code touched.

---

## Task A — Review of the consolidation

### A.1 Verdict per section

| Section | Verdict | Notes (detail in A.2/A.3) |
|---|---|---|
| §1–2 settled facts + final approach | **Adopt** | Faithful to all three passes; the two-speed model is right and Step 2 / Knowledge Workspace prove it in-app. |
| **§2.1 editor surface** (full-page `?focus=` → desktop split → narrow modal) | **Adopt** | Confirmed against source: Studio is server-rendered Jinja; a progressive same-template focus mode is cheap and honest. `studio.js` has the tab/drawer/modal *patterns* (not a component) — §5's reuse note is accurate. |
| **P1 triage board** | **Adopt with changes** | Missing: the **add-new-item flow** (see gap #4). Needs one stated rule: blocked-first *sections*, family grouping *within* sections (the mock does this; the spec text doesn't say it). |
| **P2 focused editor** | **Adopt with changes** | "Forms moved verbatim" is right in spirit, but today's markup is template-cloned, JS-driven cards — not `<form>`s. Tab error badges depend on P6 `section_ref` — fine, P6 is Phase 0. The SOAP card alone is ~20 fields + 2 dynamic mapping-row builders; budget it as DOM surgery, not a copy-paste. |
| **P3 Identity Role Lens** | **Adopt** | Server side is ready: `identity_role_review` + `role_behavior_rows` already exist (the Engine-behavior copy has a real data source). One warning: `step3_entities.js` is **1,881 lines** and the lens re-projects most of it — the single biggest Phase-1 JS item (gap #5). |
| **P4 family visual system** | **Adopt** | Hue set stays maintainer decision #2. B1 (below) adds the orthogonal **zone** axis with an explicit no-compete rule: family = element accents only (monogram, 3 px left border, ribbon); zone = container background only. |
| **P5 deterministic seeds** | **Adopt with changes — important** | The app **already parses pasted WSDL/XSD/file specs server-side** (`POST /downstream/edge-contract/inspect`, `/file-inspect`, with candidate pickers and seed actions in production today). Building a browser `DOMParser` path creates a second parser that can drift from the first. Change: the patch UI should consume the **existing inspect endpoints** as its only parsing source (details A.2-1). |
| **P6 readiness view-model** | **Adopt with changes — name the producers** | Not greenfield: `edge_contract_readiness` + `completeness_service.py` (+ `package_writer.py` as consumer, + Step 7's `report.ready()/warnings()/manual()`) already produce readiness for **contracts**. `ReadinessItem` must be an extension of `completeness_service` — one producer — or P6 accidentally creates a **fourth** source of truth (details A.2-2). |
| **P7 handoff editor** | **Adopt with changes** | Derived-vs-manual column split must be **recomputed**, never stored (rule in A.2-3). DDL before/after is trivially buildable (`/api/validate/staging-ddl/generate` + saved `ddl_content`). Seed-from-entity needs entity-fields plumbing the template doesn't receive today (gap #7). Note `getCardData` here is async (server DDL round-trip) — the editor Save needs a pending state. |
| **P8 Trace Lens** | **Adopt** | `entity_name` links exist on interfaces and handoffs — server-derivable. "Fix ↗" deep-links depend on Phase-2a routes; the phasing already orders this correctly. |
| **P9 Matrix Lite** | **Adopt the acceptance criteria; v1 call is OUT** (G2, below). |
| **§4 guardrails** | **Adopt with two additions** | (1) The XML security acceptance tests must **also cover the existing pasted-content inspect endpoints** — they parse user-supplied XML server-side *today*; §4 currently aims only at the new file-reading helper. (2) Add the P6 one-producer rule to the anti-drift guardrail. |
| **§6 phasing** | **Adopt with one precision** | Phase 1's board must keep **all cards present in the DOM** (visually collapsed, never removed). Then the existing wholesale `saveAll()` keeps working untouched and Phase 1 is genuinely no-backend. G1 only bites from Phase 2a. State it as a Phase-1 constraint. |

### A.2 The three findings the prior reviews missed (source-grounded)

**1. P5's parser already exists — server-side.** `step4_downstream.html` ships
`inspectDownstreamEdgeContract()` / `inspectDownstreamFileContract()` → `POST
/downstream/edge-contract/inspect` and `/file-inspect`, returning candidates (services / ports /
bindings / operations, XSD root + namespace + field candidates, file layout fields) with **Apply
selected metadata** and **Seed mapping rows** actions. The consolidation's "WSDL/XSD parsed via
browser `DOMParser`" would stand up a *second* parser with subtly different namespace/import/encoding
behavior. **Redline:** P5's patch UI consumes the existing endpoints; `DOMParser` is dropped (or
demoted to an explicitly optional preview nicety). Bonus: the deterministic-transform code and its
error reporting stay in one testable place, where the §4 acceptance tests can cover them.
Corollary: today's seed buttons are **confirm-then-replace-all** ("Seeding replaces existing
non-empty rows only after confirmation") — the opposite of P5's "never overwrites non-empty."
Action-4 must *migrate* the existing seed flows to the patch idiom, not add the patch beside them,
or one page will ship two contradictory seeding behaviors.

**2. P6 has three existing producers to unify — and two item kinds with none.**
`edge_contract_readiness` (contract-level), `completeness_service.py` (aggregates both directions;
already feeds `package_writer.py`, so **export truly is driven by the same rows** — P6's goal is
closer than the proposal knows), and Step 7's report are three parallel aggregations today.
`ReadinessItem` should be specified as a refactor of `completeness_service` outputs (single
producer; board rows / editor banners / Step 7 / trace lens / rail chips all consumers). Two item
kinds have **no producer today** and need new (read-only) logic in Phase 0: **handoffs** (staging
completeness — the mock's "Review DDL" state) and **entities** (missing persistence key — the
Step-3 mock's "Required before export"). Scope these honestly; they are small but they are new.
Rail chips are additive: `base.html`'s `nav_steps` already carries per-step `state` including
`warning` and `not-applicable`.

**3. Phase 1 is safer than the proposal claims — if one constraint is stated.** Because every heavy
page is DOM-as-truth with wholesale `saveAll()` (`/downstream/save`, `/handoffs/save`,
`/rules/save` — confirmed in all three templates), a Phase-1 board that merely *collapses* cards
(CSS visibility, cards stay in the DOM) changes **nothing** about the save model. The defensive
guard already in `step4_downstream.html` ("Save is blocked to avoid dropping restored interfaces")
is proof the codebase knows removal is the hazard. Write the constraint into Phase 1 and it ships
with zero save-model risk.

### A.3 Prioritized gap list

| # | Priority | Gap | Resolution |
|---|---|---|---|
| 1 | **P0** | G1 save/dirty-state unresolved | Recommendation below (G1) — decide at the gate. |
| 2 | **P0** | P6 producers unnamed → drift risk | Specify `completeness_service` as the single producer; add handoff + entity producers in Phase 0 (A.2-2). |
| 3 | **P1** | P5 dual-parser risk + legacy replace-seeding | Existing inspect endpoints as sole source; migrate old seed flows to the patch idiom (A.2-1). |
| 4 | **P1** | **Add-new-item flow absent** from P1/P2 spec and the Step-5 mock | Define: "+ Add" creates a *draft* item (P6 state `draft`) and opens it focused; the board shows it under Draft. |
| 5 | **P1** | Phase-1 effort under-scoped for Step 3 | `step3_entities.js` (1,881 lines) re-projection is the largest single Phase-1 JS item; schedule it as such. |
| 6 | **P1** | Step-6 right rail undefined in the new design | Today the right rail hosts the conflicts summary. G2 sketch keeps it (advisory summary only, reading the P6 model); the spec should say so. |
| 7 | **P2** | Handoffs template receives no entity-field data | P7 seed-from-entity needs added template context or a small read endpoint. |
| 8 | **P2** | Template↔step naming swap (`step4_downstream` = displayed Step 5) | Rename files during Action-4 (dev-facing only) — cheap insurance against wrong-file edits during build. |
| 9 | **P2** | Mock consistency nits | Fixed in this pass: Step-3 hidden-count arithmetic (41 → **39**: 10+8+21); Step-4 rail label `1!/3` → `1 to fix` (round-3 style); Step-7 "Audit XML" → `customer-audit-xml` (read as contradicting the Ready `account-audit-xml` row). PNGs re-rendered. |

**Harder-in-the-real-templates flags (for Action-4 estimation):**
- After one item saves, **five surfaces** must refresh consistently (board row, editor banner, tab
  badges, ambient stats, rail chip). Cheapest correct design: the save endpoint **returns the fresh
  `ReadinessItem` + step counts** in its response; anything else is N+1 fetches or a full reload.
- The SOAP canonical sections (up + down) are the heaviest "verbatim move" — dynamic
  request/response mapping-row builders with per-row listeners.
- Filters × sections × selection × zone tints need one precedence statement (B1 supplies it:
  **selection > zone > default**).

---

## Task B — §11 resolutions

### B1 — Functional-zone background tinting (extends P4) — DONE, applied

**Tokens** (added to the Step-5 mock and the new Step-6 sketch; for the real app they land in
`studio.css :root` in Phase 0 next to the family tokens):

```css
/* zone tints — tint by ROLE, never by family. Family stays an element accent
   (monogram, 3px left border, ribbon); zones are container backgrounds only. */
--zone-scan:    #f4f7fb;  /* scan/board surfaces — faint cool neutral            */
--zone-editor:  #ffffff;  /* focused editor — brightest panel = "act here"       */
--zone-derived: #f8f5fd;  /* derived/seed zones — faint lilac, ties to provenance */
--zone-derived-line: #e6ddf6;
--zone-attn:    #fdf8ee;  /* needs-action zones — faint amber wash               */
--zone-attn-line:    #f0e2c3;
--zone-ready:   #f4f6f9;  /* ambient readiness strips — faint neutral            */
```

**Application rules (as demonstrated in the updated Step-5 mock):**
- Board panel body → `--zone-scan`; the focused editor keeps pure white **plus a soft elevation
  shadow** — brightness + elevation together say "act here".
- Ambient stat cards → `--zone-ready` (the pre-existing amber warn-stat stays amber).
- Seed/derived boxes → `--zone-derived` with the lilac line; the DERIVED chips keep their existing
  provenance purple — the wash and the chip are the same story at two intensities.
- Needs-action group header + needs-action rows → `--zone-attn`; **selection (blue) always wins
  over zone** — the precedence rule is stated in the mock's legend.
- A zone legend row is added to the mock footer.

**A11y contract compliance (§4):** every tint is ≥ ~96% luminance, so body ink keeps ≥ 12:1
contrast on all zones; zones are never the only encoding — each tinted region carries its own
header/label ("Needs action", "Deterministic seeds…", stat labels); family hues never tint panels,
so the two axes cannot double-encode. Colour-blind safety: the amber/lilac/neutral washes remain
distinguishable by their labels alone, by design.

Deliverables: [`final-mockups/step5-downstream-contract-board.html`](../final-mockups/step5-downstream-contract-board.html)
(+ re-rendered PNG) and the tokens reused in the new Step-6 sketch.

### B2 — Kafka-router + REST-passthrough: capture → apply scoping plans

**Confirmed from source that the pattern language extends** — and where it genuinely doesn't:
`base.html` already defines per-archetype `nav_steps` with `not-applicable` states; Kafka runs
Topic Ingest (`/kafka/topics`) → Route Model (`/kafka/routes`) → Transform Mappings
(`/kafka/transforms`) with Downstream n/a; passthrough runs Upstream (`/upstream`, shared) → Route
& Transform (`/passthrough`: Inbound Operation · Downstream Targets · Routing · Transforms) with
Handoffs + Downstream n/a. `kafka_step2/3` render **per-route cards** — the same
always-expanded-card pattern that broke Steps 4/5 *will* reappear at scale. Both archetypes save
via their own `postJSON` endpoints; `/passthrough/describe-spec` already exists (a deterministic
seed source, in production).

**Kafka-router — capture pass then apply:**
1. *Capture* (reuse the initiative's Appendix-A prompt with the step list swapped): a rich sample
   with ≥ 6 topic pairs, ≥ 4 routes, transforms with several mappings each; capture `/kafka/topics`
   (consumer group, router summary, pairs), `/kafka/routes` and `/kafka/transforms` in grown-long
   state, plus Rules/Review/Export **in Kafka mode** (they render differently — `is_kafka_rules`).
2. *Apply mapping:* P1 board → **routes board** (row: in-topic → route kind → out-topic ·
   transform count · readiness) and a lighter topic-pairs table; P2 → focused editor per route /
   per transform-set; P4 → the family axis is **not contract families** — it becomes
   topic / route / transform kinds + direction, needing a small sub-palette decision; P6 → new
   `item_kind`s (`topic_pair`, `route`, `transform_set`) in the same `ReadinessItem` contract;
   P5 → deterministic seeds only from declared schema/sample inputs *if the capture shows such
   inputs exist* (no guessing); P8 → the Kafka trace is **topic-in → route → topic-out** (replaces
   the entity-centric lens).
3. *Genuinely different:* no entity model, no handoffs, shorter wizard — do not transplant the
   Step-3/4 patterns at all.

**REST-passthrough — capture pass then apply:**
1. *Capture:* a sample with several downstream targets + transforms; `/upstream` in passthrough
   mode, `/passthrough` (all four sections) grown as far as it realistically grows, Review/Export.
2. *Apply mapping:* this page is **section-shaped, not list-shaped** — the full board+editor
   machinery is likely overkill. Expected outcome: keep the single page; apply zone tints,
   family/type tokens on target rows, one readiness strip, and P5 seeds from the existing
   `/passthrough/describe-spec`. Only if the capture shows targets/transforms genuinely growing
   long does a targets board get built. Decide from capture data, not assumption.
3. *Item kinds:* `inbound_operation`, `target`, `transform` in the same readiness contract.

Both plans end with a pattern→applies/adapts/n-a table and only then any mockups. **No blind
mockups** — nothing is drawn until the capture exists.

### B3 — Knowledge Assist surfaces (Workspace + accept/edit/reject)

**Grounded:** the KA loop already exists in code — `initSuggestionDrawer()` (~700 lines of
`studio.js`), `/rules/ks/drawer` endpoints, Step-6 rules carrying
`suggestion_id / generated_by_ka / ka_review_status` datasets round-tripped through save, KA chip
tokens already in `studio.css` (`--ka-*`), and `knowledge_workspace.html`'s two-pane library. What
was never captured (Action-2 gap: needs an ingested evidence doc) is the *experienced* loop.

**Pattern reuse mapping:**
- The KA suggestion is a **stateful sibling of the P5 patch row**: same anatomy (Apply? · target ·
  proposed value · basis), two differences — the *basis* is evidence + confidence (deep-link into
  the Workspace detail pane) instead of an exact transform, and the lifecycle **persists**
  (proposed / accepted / edited / rejected — already modeled in the rule datasets) where P5 patches
  are ephemeral.
- **Provenance chips unify into one legend, two hue families:** DERIVED (deterministic, lilac) vs
  KA-APPLIED (AI-assisted, the existing `--ka-*` teal family) vs SPEC-DERIVED / MANUAL. Three of the
  four already render in Step 6 today; the system is additive, and the a11y contract (label + chip,
  never colour alone) already covers it.
- The KA review surface becomes a **suggestion queue board** (grouped by entity/type, sorted by
  impact) + **focused suggestion review** (before/after diff in patch-row anatomy) — the same
  two-speed law, no new interaction grammar.

**Scoping + gate:** a dedicated KA design pass, run **only after the KA production-readiness
decision** (PII/sanitization gate; KA defaults OFF and the KA-OFF-is-clean invariant is untouchable).
Nothing KA-related ships in Phases 0–3 of this refresh. The pass = capture (Workspace with a real
ingested doc; drawer flows on Steps 3/6/7; accept, edit, and reject each exercised end-to-end) →
apply the two mappings above → its own mockups.

---

## Task C — Action-4 gating decisions

### G1 — Save / dirty-state model: **two-stage; single-item upsert from Phase 2a**

**Recommendation.**
- **Phase 1:** keep wholesale `saveAll()` untouched — legal because collapsed cards stay in the DOM
  (A.2-3). No save-model work at all.
- **Phase 2a onward:** add **single-item upsert save routes** per step (e.g.
  `POST /downstream/save-one { interface, original_name }`), server-side upsert keyed by name —
  the exact semantics Step 2 already ships for upstream contracts, so this is an existing Studio
  idiom, not an invention. Wholesale save remains only behind explicit bulk operations (delete,
  future reorder). Rename = upsert under `original_name` atomically server-side (kills the silent
  duplicate-row hazard the current name-keyed model has).

**Why not keep save-all under the hood in Phase 2a** (the proposal's allowed fallback): it only
meets the criteria while resubmitted hidden rows are guaranteed byte-identical — true for a
single-user tool, but the **multi-session track (PR #200)** is actively landing; wholesale replace
is a built-in last-write-wins clobber across sessions. The defensive guard already in
`step4_downstream.html` is the codebase telling us DOM-as-truth wholesale replace is fragile.
Single-item save is the future-proof shape, and it is small (one route per step, reusing the
existing per-item validation).

**Acceptance-criteria mapping:**
1. *No hidden-row submits* — the request body contains exactly one item. ✓
2. *Cancel restores only the selected item* — the editor re-renders from its last-saved snapshot
   (the server-provided `existing[i]` payload); no other row is touched. ✓
3. *Dirty browser-back prompts* — snapshot-diff dirty flag + `beforeunload` + an in-app guard on
   rail/board navigation (small new `studio.js` utility; nothing exists today). ✓
4. *Board refreshes from saved state* — the save response **returns the fresh `ReadinessItem` +
   step counts**; board row, stats, and rail chip re-render from that server payload, never from an
   optimistic client summary. ✓ (This is also the cheap answer to the five-surfaces refresh flag.)
5. *Validation deep-links* — error responses carry P6 `blockers[]` with `section_ref`/`field_ref`;
   the editor maps them to tab badge + field focus. ✓

One naming consequence for Action-4: once items save individually, the step-level button becomes
**Continue** (validate step completeness + navigate) — item **Save** lives in the editor footer.
Don't leave one button doing both.

### G2 — Step 6 Rules & Mappings: board + focused editor, advisory kept visibly read-only

**Sketch:** [`final-mockups/step6-rules-board-sketch.html`](../final-mockups/step6-rules-board-sketch.html)
(+ PNG) — same visual language and B1 zones as the final mockups.

- **The item is the entity rule-set, not the individual rule.** Source-grounded reason:
  cross-entity derived rules (`cross-entity-field-check/compare/in`) take their FK-field options
  from same-entity `cross-entity-exists` **prerequisite rules** (`refreshCrossEntityRuleRow()`), so
  a per-rule editor would orphan the dependency. Board = one row per entity (rule count, fields
  covered, provenance chip counts, advisory count, state pill), needs-attention first; Legacy Notes
  stays a single quiet section — it never needed a board.
- **Editable vs advisory-only, visually:** editable rules are solid, **field-grouped** cards (fixes
  the flat-stack pain) with an Edit action and a provenance chip per row. Advisory conflicts are
  **one dashed-amber READ-ONLY strip** at the top of the editor with a deep-link "Review ↗" — never
  inline-editable, never a blocker (P6 state `warning`; export allowed — exactly today's
  advisory-only posture). Generated-ID cautions wash only the affected rule row (`--zone-attn`).
- **Provenance without a second review surface:** chips only (SPEC-DERIVED / MANUAL / KA-APPLIED /
  `prerequisite`), aggregated as counts on board rows. No provenance panel.
- **Cross-entity rules** get their own block per entity with the dependency made explicit:
  `via customerId ✓` when the prerequisite exists, an inline "add cross-entity-exists first" state
  when it doesn't — replacing today's silently-disabled dropdowns.
- **Right rail** keeps the advisory summary it hosts today, reading the same P6 model as the board
  counts (gap #6 resolved).
- **Bulk actions allowed in v1: exactly one** — paste a comma/newline list into *Allowed values*
  with preview-before-apply. Nothing else.

**Matrix Lite v1 call: OUT.** Rule shapes are heterogeneous — seven scalar types plus four
relational cross-entity types with dynamic dependent selects; only the scalar subset is
grid-shaped, and the observed bulk pain is *within-rule value lists*, not across-rule grids. P9's
own acceptance criteria (paste preview, undo, keyboard path, SR fallback) are a real build cost for
a surface only 1.5 of 3 passes wanted. **IN as Phase-3 optional**, scoped to single-field scalar
rule types only; cross-entity rules are permanently excluded from any grid. P9's acceptance
criteria remain binding if/when it builds.

---

## Mockup changes made by this pass

| File | Change |
|---|---|
| `final-mockups/step5-downstream-contract-board.html/.png` | B1 zone tokens + tints applied (board scan-tint, editor elevation, seed lilac, needs-action amber, readiness strips); zone legend + precedence note added. |
| `final-mockups/step6-rules-board-sketch.html/.png` | **New** — G2 sketch (entity rule-set board · field-grouped editor · read-only advisory strip · cross-entity prerequisites · Matrix-Lite-deferred note). |
| `final-mockups/step3-identity-role-lens.html/.png` | Hidden-count arithmetic fix (41 → 39). |
| `final-mockups/step4-handoff-board.html/.png` | Rail label `1!/3` → `1 to fix` (round-3 label style). |
| `final-mockups/step7-trace-lens.html/.png` | Unrelated-blocker renamed `customer-audit-xml` (disambiguation). |

All PNGs re-rendered (headless Chrome, 1480 px, device-scale 1).

## HALT

This review pass is complete: Task-A verdicts + gaps, B1 applied, B2/B3 scoped, G1/G2 recommended.
**Halting for the maintainer gate.** On sign-off (including the G1/G2 recommendations and the A.3
P0/P1 redlines), Action-4 — the phased implementation design doc — follows.
