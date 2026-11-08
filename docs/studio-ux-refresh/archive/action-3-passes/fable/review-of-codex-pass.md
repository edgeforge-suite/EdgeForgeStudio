# Fable — Review of the Codex Action-3 pass

> **Provenance:** Fable's review of the Codex independent Action-3 pass
> ([`../codex/proposal.md`](../codex/proposal.md) + 3 mockups), 2026-07-02. Codex produced a *fresh*
> design (not a critique of this pass), grounded in the real Studio source. This review reads it on its
> merits, maps convergence vs divergence across all three passes, and flags what should feed the
> consolidated `proposal-final.md`.

## Verdict
**Strong, and independently confirming.** Working only from the source + the Action-2 baseline (it did
not read the Fable or ChatGPT passes), Codex reached the *same core architecture* as the other two:
a compact **board for scan** + a **focused editor for one item**, an **exceptions-first entity lens**,
**contract-family silhouettes**, and **deterministic seeds that are never auto-applied** — under the
same guardrails and the same "don't fake entity derivation for file/XML/SOAP" scope. Three independent
senior passes landing on one design is the strongest validation signal we have. Codex's distinctive
value is that it is **source-grounded**: every move cites the real template/CSS/JS to change.

## Convergence map — what all three passes agree on (treat as settled design facts)
| Design fact | Fable | ChatGPT | Codex |
|---|---|---|---|
| Two-speed: compact registry/board + focused single-item editor | ✅ P1/P2 | ✅ | ✅ Contract/Handoff Board |
| Entity model **exceptions-first** — hide "No role", one persistence-identity decision | ✅ P3 | ✅ | ✅ Identity Role Lens |
| **Generation impact visible at the identity decision** | ✅ (r2 strip) | ✅ strip | ✅ per-role "Engine behavior" column |
| Contract-**family visual silhouettes** (colour **+ type label**, metadata chips) | ✅ P4 | ✅ | ✅ family accents + labels |
| **Deterministic seeds** shown as reviewable candidates, never silently applied | ✅ P5 | ✅ patch | ✅ "Keep" seeds panel |
| Handoff split into **identity · staging columns · mappings** | ✅ (r2) | ✅ | ✅ |
| Same guardrails + same "does-not-attempt" scope; tokens/CSS-first phasing | ✅ | ✅ | ✅ |

When three blind passes converge this completely, the direction is no longer the question — only the
implementation details are.

## What Codex does better than my pass (graft into the consolidation)
1. **Source-grounded implementation map.** It names the actual files (`step4_downstream.html` = Step 5,
   `step5_handoffs.html` = Step 4 — it *confirms the template-naming swap from source*, which my pass
   only flagged as a guess) and the reusable existing tokens (`step-section-card`,
   `review-summary-strip`, `disclosure-card`, drawer/modal). This turns "design" into "here is the file
   and the token" — the lowest-friction path to Action-4.
2. **In-page side-panel editor (board stays visible while editing).** Directly answers ChatGPT's
   complaint that my drawer *blurs the board*. Its responsive answer — side-panel on desktop, modal on
   narrow — is thoughtful. This is a genuinely strong third option for the editor-surface decision.
3. **"41 No Role Hidden" trust counter.** Elegantly solves the exact risk ChatGPT flagged for the
   exceptions-first lens (users must trust that hidden fields still mean "No role"). Show the count.
4. **Per-assigned-role "Current Engine Behavior" column** — impact shown only for the 2 assigned roles,
   not every field, so it avoids the boilerplate ChatGPT's per-entity strip risked. A cleaner placement.
5. **Guardrail-legible UI copy** — "this editor changes the same fields Studio exports today; it does
   not change Engine behavior", the "KA OFF clean" badge, the "staging ≠ Step-5 transform" banner.
   Baking the guardrails into the UI is smart for enterprise trust.
6. **Deterministic filter cards** (ID-looking / required / metadata-only) as *filters, not assignments*
   — a nice authoring aid to find fields needing roles without auto-assigning.

## Where Codex is weaker / what I'd challenge (apply the same round-2 hardening)
Codex sits at "round-1 maturity" — the same gaps my pass had *before* ChatGPT's review. The round-2
guardrails apply to it equally:
1. **No single readiness view-model.** It shows readiness inline (Ready pills, an "Export Blockers"
   count) but never states the P0 rule that every readiness signal derive from **one** source. Same
   biggest-risk gap ChatGPT caught in mine.
2. **Boards are typed, not yet triage.** Rows group by family with status pills, but they don't surface
   the *exact blocker inline* and the only filters are type (All/File/XML/SOAP) — no "Needs action"
   status filter, no blocked-first sort. ChatGPT's triage critique applies here too. (Family grouping +
   blocked-first + status filters are *not* mutually exclusive — combine them.)
3. **Rules & Mappings (Step 6) essentially uncovered**, and **no Bulk/Matrix mode.** Codex redesigns
   Steps 2/3/4/5 but leaves Step 6 to inherit the board pattern by analogy. Notably it did **not**
   independently reach the matrix idea — so Bulk/Matrix is now 1.5/3 (ChatGPT originated, I adopted,
   Codex silent), which *confirms* treating Matrix Lite as an optional Phase-3, not core.
4. **No comprehension/overview surface.** Codex is boards-per-step only — there is no Contract Map or
   cross-contract Trace Lens. The "trace one entity across upstream→canonical→downstream" need is
   unmet. (Restraint that aligns with ChatGPT's caution, but the Step-7 Trace Lens is still worth having.)
5. **DDL preview, but no before/after diff before save** (ChatGPT wanted the diff). Minor.
6. **The side-panel narrows the board (~50%).** The flip side of "board stays visible": at 4 items it's
   fine, but with many columns per row + 20+ contracts the half-width board will truncate (the Ready
   pill/action already clip at the panel edge in the mock). A real tradeoff vs a full-width board.

## The genuine divergences = the real decisions for `proposal-final`
1. **Editor surface — the one big open question, now with three answers:** drawer (my round-1) ·
   full-page-first (ChatGPT / my round-2) · in-page side-panel + modal (Codex). *My synthesis:* these
   reconcile — a **full-page `?focus=` route as the robust, accessible, deep-linkable baseline, which on
   wide desktop renders as Codex's persistent board+editor split**, and as a modal on narrow screens.
   That captures ChatGPT's a11y/deep-link win *and* Codex's board-stays-visible win.
2. **Family hue assignments differ** (Codex SOAP=navy/CSV=teal/REST=blue vs Fable SOAP=violet/CSV=green/
   REST=teal). Cosmetic — pick one palette in Phase 0 under the accessibility pass. *Note Codex pairs
   every accent with a text family label already — that redundant encoding is the a11y-safe thing to do.*
3. **Blocked-first triage vs family-grouped board** — combine (group by family, sort blocked-first,
   add status filters).
4. **Matrix/Bulk mode** — optional Phase-3 Matrix Lite (settled by 1.5/3 + ChatGPT's own "don't block on
   it").

## Bottom line for the consolidation
The three passes agree on the architecture; the consolidation is now mostly **picking the best
*expression* of each shared idea, not choosing between directions.** Concretely, `proposal-final` should:
- Take the **shared board + focused-editor + exceptions-lens + family-silhouettes + deterministic-seeds**
  as the settled spine.
- Adopt **Codex's source-grounded file/token map** as the Action-4 implementation substrate.
- Resolve the **editor surface** via the full-page-baseline / desktop-split / narrow-modal reconciliation.
- Keep the **round-2 hardening** (single readiness view-model P0, security-scoped helper,
  provenance-out-of-manifest, a11y contract, failure-state criteria) as cross-cutting requirements on
  *all* of it.
- Fold in Codex's **trust-counter, guardrail-legible copy, and deterministic filter cards**; keep the
  **Step-7 Trace Lens** (Codex's gap) and **Matrix Lite** (Codex's gap) as scoped later phases.
