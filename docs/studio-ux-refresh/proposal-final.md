# EdgeForge Studio — UX Refresh: Consolidated Proposal (Action 3 → final)

> **Status:** APPROVED CONSOLIDATED PROPOSAL (round-3 — Codex + ChatGPT review redlines folded in) —
> the Action-3 design baseline that informed the now-active
> [`implementation-design.md`](implementation-design.md) build contract.
> **Inputs:** [`action-3-passes/`](archive/action-3-passes/) — [Fable](archive/action-3-passes/fable/proposal.md) ·
> [ChatGPT](archive/action-3-passes/chatgpt/proposal.html) + [its review of Fable](archive/action-3-passes/chatgpt/review-of-fable-pass.md) ·
> [Codex](archive/action-3-passes/codex/proposal.md) + [Fable's review of Codex](archive/action-3-passes/fable/review-of-codex-pass.md);
> the [Action-2 baseline](baseline/current-state-walkthrough.html); the [initiative guardrails](initiative.md).
> **Method:** three *blind* passes (none read another) → two adversarial cross-reviews → this synthesis
> takes the best *expression* of each converged idea and resolves the few genuine divergences.
> **Deliverables:** this document + final target-state mockups in [`final-mockups/`](final-mockups/).
> **Date:** 2026-07-02.
>
> **Implementation amendment (2026-07-22):** the full-page focus route and desktop split have shipped.
> The narrow-screen modal is retired; the supported sub-1200px presentation is the single-column
> full-page focus route. PR-24a owns the cross-surface a11y acceptance gate — **except** the
> vocalization half of §1.5 item 7, which the §7.2 amendment scopes to **A11y-01**, a mandatory
> pre-release gate. PR-24a is therefore **not** the final a11y verification. See
> [`implementation-design.md` §7.1 + §7.2](implementation-design.md).
>
> **Sequencing supersession (revised 2026-09-21):** the statement above remains the historical
> Action-3 rule. The [proposed §7.3 amendment](implementation-design.md#a11y-01-v5-baseline-deferral)
> becomes operative only after the Studio and Engine/Suite amendments are independently reviewed and
> merged. Once active, A11y-01 alone no longer blocks source publication, internal baselines/tags,
> public releases, or promoted demos. It remains an
> [open known limitation](https://github.com/santosh-sh/EdgeForgeStudio/issues/302), and all four
> native observations remain required for completion.

---

## 1. What the three passes settled

Three independent senior passes, working the same baseline without seeing each other, converged on one
architecture. That means the *direction* is no longer the question — only the best expression of each
shared idea is. Settled design facts (all three reached each independently):

- **Two-speed authoring.** Every heavy page becomes a **compact scan surface** (a board/registry, one
  short row per item) **plus a focused editor** for one contract / handoff / entity at a time. This is
  not a foreign pattern — Step 2 already ships a weaker version of it, and the Knowledge Workspace ships
  a stronger one.
- **Entity model goes exceptions-first.** Stop rendering an identity-role dropdown per field × entity
  (mostly "No role"); each entity gets one persistence-identity decision, and only *assigned* roles
  render.
- **Generation impact is shown at the identity decision** (not hidden, not a per-field column).
- **Contract families need silhouettes** — colour **plus a type label** (never colour alone), with
  family-specific "shape" metadata chips, so a SOAP row can never read as a CSV row.
- **Deterministic seeds, never assumptions** — exact transforms surfaced as *reviewable* candidates,
  chip-marked, editable, never auto-applied; KA stays opt-in review/accept.
- **Same guardrails, same scope boundary** — frontend-first, manifest-compatible, Engine/KS-protective;
  and no pass tries to fake entity derivation for file/XML/SOAP (that's a product boundary, made
  *legible*, not papered over).

The cross-reviews then hardened this from "looks good" to "survives enterprise scale." Their net effect:
**lead with the boring-robust surface, add the clever ones as enhancements**, and make every readiness
number come from one place.

## 2. The final design approach

**Two speeds, one truth, families you can see.**

1. **Scan** — a triage board: grouped by contract family, **sorted blocked-first**, with status + type
   filters and each row's **exact blocker inline**. Ambient readiness (counts, an explicit *Export
   Blockers* number) sits on top.
2. **Edit** — a focused single-item editor (see the resolved surface below), forms moved verbatim, with
   deterministic seeds offered as a reviewable patch and a one-line guardrail-legible reassurance.
3. **One truth** — every readiness signal (row pills, editor banners, Step 7, the trace lens) reads from
   **one read-only readiness view-model per item**. No surface computes "complete" on its own.
4. **Families you can see** — a cross-cutting visual token system: type = monogram + label + accent +
   (secondary) hue; state = pill + icon + text; provenance = chip + source.

### 2.1 The resolved editor surface (the one real divergence)

The three passes offered three editor surfaces — Fable's **drawer**, ChatGPT's **full-page-first**, and
Codex's **in-page side panel**. They reconcile into one responsive answer:

> **A full-page `?focus=<id>` route is the baseline** — accessible, deep-linkable from Step 7, cheap to
> build in Jinja, and it kills the scroll pain on its own. **On wide desktop that same route renders as a
> persistent split** (board on the left stays visible, editor on the right — Codex's win: you never lose
> context). **Below the split breakpoint, it remains the single-column full-page route.** The overlay
> drawer and narrow modal are not part of the shipped surface.

This captures ChatGPT's accessibility/deep-link argument *and* Codex's board-stays-visible argument,
while keeping the more accessible narrow presentation: standard page semantics, native browser-back,
and no focus-trap/scroll-containment surface.

### 2.2 Round-3 — post-consolidation review incorporation (Codex + ChatGPT)
Both post-consolidation reviews returned **"adopt with redlines"** (verbatim:
[`action-3-passes/codex/review-of-final.md`](archive/action-3-passes/codex/review-of-final.md),
[`action-3-passes/chatgpt/review-of-final.md`](archive/action-3-passes/chatgpt/review-of-final.md)). Both
confirmed their passes were captured fairly; there is **no residual concept-level disagreement** — every
redline is execution-risk tightening, folded in as:

| Redline | Where addressed |
|---|---|
| Specify the readiness view-model shape + state precedence | **P6** — `ReadinessItem` contract + precedence |
| Save / dirty-state is a P0 risk (desktop split = two views of one item), not a mere option | **§8 gating decision G1** |
| Full-page first; split second (flagged); supported narrow full-page fallback; a11y acceptance gate (spoken-announcement verification = A11y-01, pre-release) | **§6 Phase 2a / 2b + PR-24a + §7.2** |
| Every board actually blocked-first (the Step-4 mock violated it) | **Step-4 mockup fixed** — Needs-action section first |
| Deterministic seed **collision + normalization** rules | **P5** |
| Unrelated-blockers strip in the Trace Lens | **P8 + Step-7 mockup** |
| Restore the Kafka + KA + non-CRUD "not validated" caveat | **§9** |
| Matrix Lite acceptance criteria now (even with mock deferred) | **P9** |
| `studio.js` = patterns/utilities, **not** a ready generic editor component | **§5** |
| Provenance: recompute-vs-store lifecycle | **§4** |
| Backend-helper acceptance tests | **§4** |
| Step 2 family-tokens + readiness chips earlier | **§6 Phase 1** |
| Step 6 Rules & Mappings is the thinnest surface | **§8 gating decision G2** |
| Mockup labels (`1 blocker · 5 contracts`; tab badges by severity; `Derived DDL preview`; `Knowledge Assist: Off`) | **mockups updated** |

**Two decisions are promoted to Action-4 gating (must be resolved before any build):** **G1 (save /
dirty-state)** and **G2 (Step 6 rules surface)** — both detailed in §8.

## 3. Pattern spec (final)

Each pattern names the **best-expression source**, its **guardrail check**, and the **real Studio source**
to change (grounded by the Codex pass).

### P1 — Triage board (Steps 5, 4, 2)
Compact rows grouped by contract **family**, **sorted blocked-first**. Above the list: an *ambient
readiness* strip (Contracts / Ready / Mapped entities / **Export blockers**) and two filter groups —
**status** (Needs action · Ready · Draft) and **type** (File · XML/XSD · SOAP · …). Each row: family
monogram + accent + label · name · artifact path (mono) · one family "shape" chip (`delimiter |`,
`root AccountMessage`, `operation syncCustomer`) · mapped-entity chip · mapping coverage · a **capability
icon** (`POPULATES ENTITIES` on REST vs `MANIFEST REFERENCE` on the rest — pain-5 made legible, compressed
to an icon + legend, not a full column) · **the exact blocker inline** when not ready · status pill · Edit.
*Best expression:* Fable's typed registry + ChatGPT's blocked-first triage + Codex's board silhouettes &
ambient stats. *Guardrail:* frontend-only; readiness from the P6 view-model. *Source:* `step2_upstream.html`
(already close), `step4_downstream.html` (= displayed Step 5), `step5_handoffs.html` (= displayed Step 4);
`studio.css` (`step-section-card`, `review-summary-strip`, `badge`); vanilla JS.

### P2 — Focused editor (full-page baseline · desktop split)
Header: monogram, name, family ribbon, status, a one-line **readiness banner** naming exactly what
unblocks export. **Section anchor tabs carry error badges** so a required blocker can't hide on an
inactive tab. Body = today's form fields moved **verbatim** (same names, same save endpoints). A pinned
footer with the validation summary + Cancel/Save, and a guardrail-legible note ("this edits the same
fields Studio exports today; it does not change Engine behavior"). *Best expression:* the §2.1
reconciliation. *Guardrail:* frontend-first; same persisted payload; §4 a11y contract. *Source:* the
per-step templates + `studio.js` interaction utilities + `?focus=` route handling.

### P3 — Identity Role Lens (Step 3, exceptions-first)
Left: entity cards (name, field/rule counts, scope, assigned-role chips or a red "no key chosen"). Top:
a summary strip including a **"N No Role Hidden" trust counter** (so users trust the compression). Right,
for the selected entity: one **Persistence identity** picker, then an **assigned-roles-only** table whose
**"Current Engine Behavior"** column shows generation impact *for assigned roles only* (Java `@Id` / DB
PK / repo lookup / `identity_overrides` — no per-field boilerplate); explicit **decision-state** language
(required / metadata-only / out-of-scope / reference-only); deterministic **filter cards** (ID-looking ·
required · metadata-only — *filters, not assignments*); a **"Show all fields"** reveal for edge cases.
*Best expression:* Fable's inversion + Codex's trust counter / Engine-behavior column / filter cards +
ChatGPT's decision-state language & impact insistence. *Round-3:* an entity with **no persistence key**
shows an explicit **"Required before export / generation"** state in the detail panel (not only red text on
the left card); entities with **>50 fields** default the table to *assigned + required* fields with a
search box. *Guardrail:* frontend-first; writes the same project state. *Source:* `step3_entities.html`,
`step3_entities.js`.

### P4 — Contract-family visual system (accessibility-first)
CSS custom properties in `studio.css`, three orthogonal axes: **type = monogram + label + left accent +
(secondary) hue**; **state = pill + icon + text**; **provenance = chip + source-on-demand**. Redundant
encoding is mandatory — no meaning in colour alone; dots carry labels; error is never red-only. One
palette, run through a contrast + colour-blind pass in Phase 0 (family hues to be finalized — Fable and
Codex proposed near-identical sets differing only on SOAP/REST/CSV hue assignment). *Guardrail:*
presentation only; no generated-output change. *Source:* `studio.css`.

### P5 — Deterministic seeds as a reviewable patch
Every prefill is an **exact transform** of a user-supplied artifact — **no fuzzy/similarity "candidate"
tier at all** — chip-marked, editable, and it **never overwrites a non-empty value**. Surfaced as a
review patch (Apply? · target · source · transform) or Codex's per-row **"Keep"** control; **nothing is
applied silently.** **Collision rules (round-3):** an exact *raw-name* match always wins; an exact
*normalized* match (case / snake↔camel) applies only when exactly one source and one target remain; if
several normalized matches exist the row is left blank and the collision is shown (never pre-selected);
every applied row shows its transform basis. WSDL/XSD parsed via browser `DOMParser` for pasted content (Service/Port/Binding/
Operation → pickers; XSD root/namespace; exact-name mapping seeds; handoff columns from the linked entity
via a documented type map). *Guardrail:* deterministic; the one optional backend helper only under §4's
security scoping. *Source:* existing inspectors/seed buttons made visible; `DOMParser` in vanilla JS.

### P6 — Single readiness view-model (P0) + wayfinding
**One read-only readiness object per item** is the single source every surface reads — board rows, editor
banners, Step 7, the trace lens. No duplicated client-side "n/4 complete" math, ever.

Its shape, to pin before Action-4:
```
ReadinessItem { item_id · item_kind · family · display_name
  state: ready | warning | needs_action | blocks_export | draft
  export_blocking: bool
  blockers: [{ code, label, field_ref, section_ref, deep_link }]
  warnings:  [{ code, label, deep_link }]
  coverage:  [{ label, complete, total }]
  capability: populates_entities | manifest_reference | metadata_only
  source_of_truth_version }
```
State **precedence**: `blocks_export > needs_action > warning > draft > ready`. State **policy**:
*warning* = export allowed · *needs_action* = continue allowed, export may/may not · *blocks_export* =
export disabled until fixed · *draft* = intentionally incomplete (export disabled only if in the active
package). Every pill on every surface maps to exactly one state.

Left-rail steps
carry count chips ("Downstream · 6 · 1!"); Step-7 advisories deep-link to the owning item's editor.
*Guardrail:* the anti-drift rule that makes every other pattern safe. *Source:* a server-rendered
readiness helper feeding the templates.

### P7 — Handoff editor, three blocks (Step 4)
Board rows (handoff · table · entity · columns · mappings · DDL mode · readiness) + a focused editor split
into three explicit blocks: **(1) identity**, **(2) staging columns** — *derived-from-entity separated
from manual operational columns* (never mixed with mapping rows), **(3) entity→staging mappings** with
deterministic seed-from-entity. DDL preview is secondary, with a **before/after diff before save**. A
"this is staging, not a Step-5 artifact transform" banner when edge contracts also exist. *Best
expression:* Codex's handoff board + ChatGPT's three-block split & DDL diff. *Guardrail:* `data_handoffs[]`
shape unchanged. *Source:* `step5_handoffs.html`.

### P8 — Review Trace Lens (Step 7, comprehension)
Inside Step 7 (the best-organized page): **"Trace by entity ▼"** → upstream references → canonical entity
→ downstream references, each carrying readiness **from the same P6 view-model** (no map-specific
summaries; never dims away unrelated blockers). This is the comprehension surface all passes wanted, in
the form that avoids two-views-of-one-state drift. The standalone spatial Contract Map (Fable's mock-5)
is **deferred** — optional, later, and if built it reads the same view-model. When tracing one entity, an
**"other export blockers not connected to \<entity\>"** strip stays visible, so focusing on one entity can
never hide unrelated blockers. *Source:* `step7_review.html`.

### P9 — Matrix Lite (Step 6 Rules & Mappings) — optional, Phase 3
For genuinely grid-shaped work: a **native HTML table** with paste-into-column and fill-down, but
**preview-before-save + undo-last-bulk-action**, row-level validation, and a "switch to card editor"
fallback. No full-spreadsheet interaction model in v1. Marked optional because only 1.5/3 passes reached
it (ChatGPT originated, Fable adopted, Codex silent). **Acceptance criteria (binding even though the mockup
is deferred to Action-4):** paste preview before commit · undo-last-bulk-action · per-cell validation before
save · row-level error summary · documented keyboard-only path · screen-reader fallback to the card editor.
*Guardrail:* destructive ops must be previewable + reversible. *Source:* `step6_rules.html` (or equivalent), vanilla JS.

## 4. Hard guardrails (cross-cutting)

Originals (initiative §3): **frontend-first · manifest-compatible · protect Engine/KS core · deterministic-
not-assumptive · phased/safe/reversible.** Plus the round-2 hardening, now binding on the whole design:

- **Single readiness view-model (P0)** — one read-only object per item feeds every readiness signal; no
  surface recomputes it, or the summaries eventually contradict export.
- **Security-scoped backend helper** — the one optional read-only artifact helper ships only if:
  read-only · project-root-confined · **no network fetch by default** · import-depth-limited · **XXE-safe**
  · deterministic error reporting · **no manifest writes** · fully behind a flag. (Bank-auditable.)
  **Acceptance tests:** `../` traversal rejected · external entity (XXE) rejected · recursive import depth
  exceeded → deterministic error · unresolved import → deterministic warning · with the helper disabled the
  manual-path workflow still works.
- **Provenance stays out of the manifest** — `DERIVED`/`MANUAL` is UI/project-side only (or recomputed
  fresh); it must never become new Engine-manifest state. **Lifecycle:** recompute where possible; UI-only
  project metadata is allowed but is never exported to the Engine manifest.
- **Accessibility contract** — redundant (non-colour) encoding, contrast + colour-blind checked, focus
  management, error semantics beyond colour. Defined in Phase 0 before any visual redesign ships.
- **Per-surface failure-state acceptance criteria** — before a surface ships, specify empty / overflow
  (50+ items) / long-path / nested-XML / unresolved-import / duplicate-name / parser-failure /
  stale-after-back / paste-conflict / keyboard-only states.

## 5. Source-grounded implementation map (from the Codex pass)

| Surface | Real file(s) to change | Reuse |
|---|---|---|
| Downstream board + editor (Step 5) | `app/templates/step4_downstream.html` | `step-section-card`, `review-summary-strip`, `badge`; `studio.js` interaction utilities |
| Handoff board + editor (Step 4) | `app/templates/step5_handoffs.html` | same tokens; existing DDL generation |
| Identity Role Lens (Step 3) | `app/templates/step3_entities.html`, `app/static/js/step3_entities.js` | existing entity filter/render JS |
| Upstream parity (Step 2) | `app/templates/step2_upstream.html` | already the strongest page |
| Family tokens (cross-cutting) | `app/static/css/studio.css` | existing token/badge system |
| Trace lens (Step 7) | `app/templates/step7_review.html` | `review-summary-strip`, summary cards |

> Naming note (confirmed from source by Codex, not a guess): `step4_downstream.html` renders the
> *displayed* Step 5, and `step5_handoffs.html` renders the *displayed* Step 4 — the file names are
> swapped vs the step order. Fix or leave during Action-4 (cosmetic, dev-facing).

> Reuse note (round-3, per Codex): `studio.js` ships tabs, a shell drawer, a suggestion drawer, and
> modal-like helpers — **interaction patterns and utilities to reuse, not a ready generic editor
> component**. Build the focused editor as a **progressive same-template focus mode** (`?focus=<id>`
> re-renders the existing step template in edit-one mode), not separate routes per contract.

## 6. Phasing (each phase independently shippable + revertable)

- **Phase 0 — foundations.** The **single readiness view-model** + the **accessibility token contract**
  + page-local family-token / board-row / editor-panel utility classes. No visible behavior change.
- **Phase 1 — low-risk compression.** Family tokens across Steps 2–5 (hue secondary); Step 3 Identity
  Role Lens (inversion + trust counter + impact + filter cards); the **triage board** for Steps 5 & 4
  (blocked-first + filters, expand-one-at-a-time — no split editor yet); rail count chips; **Step 2 gets
  family tokens + readiness chips now** (full editor parity waits for Phase 4 — it is already compact). No
  backend, no routes.
- **Phase 2 — focused authoring (sequenced by accessibility risk).**
  **2a** — full-page `?focus=` route only, rolled 5 → 4 → 2, forms verbatim; deterministic **seed
  patches**; WSDL/XSD `DOMParser`; the security-scoped helper only if approved; deep links from Step 7.
  **2b** — the wide-desktop split (board + editor) behind a flag.
  **2c retired** — no narrow-screen modal. Below the split breakpoint, the supported full-page focus
  route remains route-addressable + browser-back-restorable, with normal page focus and dirty-state
  protection. PR-24a records the keyboard-only + screen-reader *navigation* acceptance walkthroughs and
  test-enforces the structural save-announcement contract; observing announcements **spoken** is
  **A11y-01**, a mandatory pre-release gate (§7.2 of `implementation-design.md`).
- **Phase 3 — power & review.** **Matrix Lite** (Step 6) and the **Review Trace Lens** (Step 7); then,
  only if proven needed, the standalone spatial Contract Map (same view-model, additive, deletable).
- **Phase 4 — Step 2 parity + deterministic-seed visibility.** Bring Step 2 to full parity; surface the
  seed actions already present.
- **Phase 5 — package-story polish.** Tune Step 7/8 summaries so the story is coherent from board rows to
  export artifacts to Evidence Trail.

Rollback: Phase 0 is internal; Phases 1–2 keep the old template blocks behind a flag until sign-off; every
Phase-3+ surface is additive and deletable.

## 7. Pain → resolution (final)

| # | Pain (Action-2 baseline) | Resolution | Patterns |
|---|---|---|---|
| 1 | Steps 4/5 never collapse (~85 scroll-ticks; ~8× Step 2) | Triage board + focused editor; one law on all heavy pages | P1, P2 |
| 2 | Identity-role row per field × entity, mostly "No role" | Exceptions-first lens; one picker/entity; "N No Role Hidden" counter | P3 |
| 3 | SOAP row ≙ CSV row; visual monotony | Family silhouettes (monogram + label + accent), a11y-safe | P4 |
| 4 | XML/XSD + SOAP mapping fully manual | Deterministic seed patches (WSDL/XSD pickers, exact-name seeds) | P5, P7 |
| 5 | Only REST populates entities (structural) | Made legible: capability icon + `ENTITY SOURCE` note + trace lens | P1, P3, P8 |
| — | *(round-2) summaries could silently lie* | Single readiness view-model feeds every signal | P6 |

## 8. Decision status and remaining maintainer calls

1. **Editor surface — resolved and shipped.** Full-page baseline + desktop split; sub-1200px stays on
   the supported full-page fallback. The narrow modal is retired by the approved §7.1 amendment.
2. **Family palette** — pick the hue set (Fable vs Codex differ only on SOAP/REST/CSV) and run the a11y pass.
3. **Matrix Lite (P9)** — include in Phase 3, or defer entirely (only 1.5/3 passes reached it).
4. **Spatial Contract Map** — keep on the roadmap after the trace lens, or park it.
5. **Completeness soft-block** — should "Needs action" soft-block Continue (today it doesn't)? Now framed by
   the P6 state policy; this is the remaining workflow-policy call.

**Action-4 gating decisions (must be resolved before any build — promoted from the round-3 reviews):**
- **G1 — Save / dirty-state model.** Editing one focused item must not submit hidden rows; Cancel restores
  only the selected item; browser-back with a dirty editor prompts; the board row refreshes from *saved*
  state (not an optimistic local summary); validation deep-links to the exact section + field. (Keeping
  save-all under the hood is acceptable for the first slice **only if** these hold; otherwise a single-item
  save route.)
- **G2 — Step 6 Rules & Mappings.** The one surface no pass covered well. Decide: is Matrix Lite in scope or
  deferred; how editable rules read differently from advisory-only conflicts; how rule provenance
  (generated / spec-derived / manual / KA-applied) shows without becoming a second review surface; how
  cross-entity rules group without a giant row stack; which bulk actions are allowed (with preview/undo).

## 9. What this does not attempt (unchanged scope — all three passes agreed)

No generated-app changes · no manifest schema changes · no Engine/KS behavior changes · no hidden parsing
or AI inference · no change to KA-OFF cleanliness · no attempt to make file/XML/SOAP magically create
entity models (a product/backend boundary, made legible, not papered over in the UI).

**Not validated in this pass** (patterns are intended to extend to them, but each needs a capture pass
before implementation — restored per the round-3 review): the **Kafka archetype-specific flow**; the
**KA accept / edit / reject loop**; **non-CRUD archetype navigation**. Do not treat the mockups as
covering these.

## 10. Final mockups

| File | Surface | Shows |
|---|---|---|
| [`final-mockups/step5-downstream-contract-board.html`](final-mockups/step5-downstream-contract-board.html) | Step 5 | Triage board (blocked-first + filters + inline blockers) · desktop split editor · deterministic seed patch · guardrail-legible copy |
| [`final-mockups/step3-identity-role-lens.html`](final-mockups/step3-identity-role-lens.html) | Step 3 | Exceptions-first lens · "N No Role Hidden" counter · Engine-behavior column · deterministic filter cards |
| [`final-mockups/step4-handoff-board.html`](final-mockups/step4-handoff-board.html) | Step 4 | Handoff board · three-block editor (identity · columns · mappings) · DDL before/after |
| [`final-mockups/step6-rules-board.html`](final-mockups/step6-rules-board.html) | Step 6 | Entity rule-set board (locked L9) · field-grouped editor · dashed read-only advisory strip (warning, never blocking) · explicit cross-entity prerequisites · quiet Legacy Notes · save-one vs Continue. **Matrix Lite remains OUT (locked L10).** |
| [`final-mockups/step7-trace-lens.html`](final-mockups/step7-trace-lens.html) | Step 7 | Review Trace Lens — trace one entity upstream → canonical → downstream, one readiness source |

PNG screenshots sit alongside each HTML. These reflect the **final** approach (they supersede the
round-1 per-pass mockups) and include the **round-3 fixes** (Step-4 board now blocked-first; rail reads
`1 blocker · 5 contracts`; editor tab badges by severity; `Derived DDL preview`; `Knowledge Assist: Off`;
Trace-Lens unrelated-blockers strip). Matrix Lite (P9) is specced but its mockup is deferred to Action-4,
since it is optional/Phase-3.

## 11. Open design questions carried into the review pass

Three questions raised after round-3, to be resolved **inside this design theme** by the review pass:

1. **Functional-zone background tinting (extends P4).** The mockups lean on white cards — flat, and a
   missed differentiation cue. Introduce a small **light palette that tints by *role*, not by family**:
   scan/board on a faint cool neutral · the focused editor kept **brightest** (= "act here") · derived /
   seed zones a faint lilac (ties to provenance) · needs-action zones a faint amber wash · readiness
   strips a faint neutral. **Family stays an accent, never a full-panel tint** — tinting panels by
   contract family would double-encode with the accents and breach the §4 a11y contract. *In-theme; the
   review pass proposes the palette + applies it to one mock.* **✅ Decided (D1):** shared palette at
   moderate/Codex intensity, applied to the canonical Step-5 mock — see `review-reconciliation.md`.
2. **Non-CRUD archetypes — Kafka-router + REST-passthrough.** Out of scope here (CRUD-only; §9). The
   pattern language (board + focused editor · family silhouettes · deterministic seeds · single readiness
   model) is archetype-agnostic and should carry, but each archetype's *actual* steps differ (Kafka router
   = topic-in → route → topic-out; REST passthrough = a thin proxy — neither has the entity-model /
   downstream-file emphasis). *Recommendation: a light dedicated **capture → apply** pass per archetype
   that reuses this template — not a blind extend, not a from-scratch redo.*
3. **Knowledge Assist surfaces — Workspace + accept/edit/reject review.** Out of scope here (§9). A
   different workflow (AI suggestion → review → apply), but a close cousin of P5's **reviewable derivation
   patch** + the provenance-chip system. *Recommendation: a dedicated KA design pass reusing those
   patterns, **gated on the KA production-readiness decision** (KA defaults OFF; not production-bound until
   the PII/sanitization gate is designed).*

**Sequencing of #2 and #3:** both are **parallel follow-on tracks whose only hard prerequisite is that this
proposal is *frozen* (maintainer gate)** — they reuse its then-stable pattern language, so they must not
start on a moving template, but they do **not** wait behind CRUD Action-4/5. Once frozen: Kafka-router runs
unblocked; the KA pass may *design* in parallel but its *build* is additionally gated on the KA
production-readiness decision. The Fable/Codex B2/B3 scoping outputs are the ready-to-fire briefs.

## 12. Scope freeze — surface coverage, compatibility & rollout

### 12.1 Surface coverage map (every step + sub-surface → disposition)
**"Un-mocked" ≠ "unchanged."** Three buckets: **A** = inherits the cross-cutting refresh (tokens, zone
tints, single readiness model, wayfinding) automatically — nothing looks stale next to the new work; **B**
= in-scope, redesigned in its phase (just not a headline mock); **C** = structurally as-is (not a pain
point) — cosmetic refresh only.

| Surface | Bucket | Disposition |
|---|---|---|
| Step 1 · Project Setup (kickoff) | **C** | Short form; not an Action-2 pain. Structure unchanged; picks up tokens/tints only. |
| Step 2 · Upstream Contract | **B** | Already the strongest page. Phase 1 tokens+readiness; Phase 4 full board parity. |
| Step 3 · Entity Model | **A+B** | Redesigned — Identity Role Lens (mock). |
| Step 4 · Data Handoffs | **A+B** | Redesigned — Handoff Board (mock). |
| Step 5 · Downstream Interfaces | **A+B** | Redesigned — Contract Board (mock). |
| Step 6 · Rules & Mappings | **B** | Rules board + editor (G2). Advisory conflicts → read-only strip; **Legacy Notes → read-only / collapsed** (exact treatment = G2 / Action-4). |
| Step 7 · Review | **A+B** | The existing review-summary-strip + **Review drawer STAY and are reused**; P8 adds the Trace Lens + deep-links on top. Phase 5 polishes summaries. |
| Step 8 · Export & Build | **B** | Phase 5 package-story polish; no structural redesign. |
| Knowledge Workspace (KA) | — | Separate follow-on pass (§11.3), gated. |
| Global chrome (rail / shell / drawer) | **A** | Inherits tokens/tints/chips; structure unchanged. |

Action-4 owns the exhaustive template-by-template version of this table.

### 12.2 Project-file compatibility (a guarantee)
**Existing Studio project files load on the refreshed UX as-is.** The refresh is manifest-compatible, moves
forms **verbatim** (same fields, same persisted values), and keeps readiness + provenance **derived, not
stored** — P6 is a *refactor of existing producers* (confirmed by both source-grounded reviews), so **no
new persisted fields**. Rule for Action-4: **no new *required* persisted field**; any new field is optional
+ back-fillable; ship a **round-trip test** (load an old project → new UX → save → the diff is empty or
additive-only).

### 12.3 Rollout safety & versioning
The refresh must never take the working suite off the table for demos.
- **Pinned demo baseline.** The current **4.1.x** Engine + Studio release stays tagged and available for
  demos throughout — pin demos to it (Engine is at v4.1.1).
- **Flag-gated + revertable through the build.** Each phase shipped independently behind a default-off
  rollout flag until the §4.2 gate passed. PR-24 retires that in-repo flag and leaves the pinned 4.1.x
  tag plus a clean PR revert as the two fallback mechanisms.
- **Flip on completion.** PR-24 is the completion boundary: the refreshed UX becomes the only
  presentation and Studio receives an unreleased minor version bump. No release tag is created here.

### 12.4 Rough scale (Action-4 produces the exact slicing)
Planning-grade estimate for the CRUD refresh — all small, flagged, revertable PRs: **~18–24 PRs across
Phases 0–5** (≈ 2 foundations · 5–6 Phase 1 · 5–7 Phase 2 · 3–4 Phase 3 · 2–4 polish). Follow-on tracks
add their own: **Kafka-router ≈ 5–8**, **KA ≈ 6–10** (build-gated). Many small PRs is deliberate — it *is*
the rollout-safety mechanism.

## 13. HALT — for review

Both parallel review passes are in — **Fable** ([`review-pass-fable.md`](archive/review-pass-fable.md)) and **Codex**
([`review-pass-codex.md`](archive/review-pass-codex.md)) — plus the earlier Codex/ChatGPT cross-checks. Both
independently returned **adopt-with-changes** and **converged on the same two P0 redlines** — P5 → consume
the existing inspect endpoints + a reviewable-patch migration; P6 → refactor to one readiness producer —
which are therefore treated as **locked**. The two open calls are now **decided** (see
[`review-reconciliation.md`](review-reconciliation.md) §B): **D1** tint = shared palette at moderate/Codex
intensity on the canonical mock; **D2** save-model = single-item upsert from Phase 2a (no interim). Remaining
for the **maintainer gate**: formal sign-off of the locked set (§A of the reconciliation sheet — P5, P6, G1
target, G2 shape / Matrix-Lite-out). **✅ Signed off 2026-07-03.** **Action-4 delivered:**
[`implementation-design.md`](implementation-design.md) — the phased build contract (24 PRs, Phases 0–5).
