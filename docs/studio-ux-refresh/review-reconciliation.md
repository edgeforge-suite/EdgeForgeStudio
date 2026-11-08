# Studio UX Refresh — Review Reconciliation & Maintainer Decision Sheet

> Reconciles the two independent source-grounded review passes — **Fable**
> ([`review-pass-fable.md`](archive/review-pass-fable.md)) and **Codex** ([`review-pass-codex.md`](archive/review-pass-codex.md))
> — into one sign-off sheet for the maintainer gate. Both ran blind (Codex read Fable only for its closing
> reconciliation section); both did a line-level read of the real Studio source. Date: 2026-07-03.
> Design/docs only — no production code touched.

## Bottom line
Two independent senior passes, both grounded in the actual templates/services, returned **adopt with
changes** and converged on **~95% of the redlines** — including both P0s, both gating decisions, and the
Matrix-Lite call. **Neither raised a concept-level objection.** **Both open calls (§B) are now decided
(2026-07-03).** What's left for the gate: **sign off the locked set (§A)**. Then Action-4.

---

## A. LOCKED — converged; sign-off only (no debate)

| # | Item | What both agree | Source anchor |
|---|---|---|---|
| L1 | Verdict | Adopt with changes; direction sound + implementable in Jinja + vanilla JS | — |
| L2 | **P5 parser** | Consume the **existing** server-side inspect endpoints (`/{up,down}stream/edge-contract/inspect` + `/file-inspect`); drop browser `DOMParser` as the primary path (optional preview at most) | `edge_contract_inspector.py`, `edge_contract_file_inspector.py`, upstream/downstream routes |
| L3 | **P5 seeding** | Migrate today's *confirm-then-replace-all* seed flow to the never-overwrite **reviewable patch**; don't ship both behaviours on one page | seed helpers in `step2_upstream.html` / `step4_downstream.html` |
| L4 | **P6 producer** | Refactor `completeness_service` + `edge_contract_readiness` into **one** item-shaped producer feeding board / editor / Step 7 / trace / rail — not a 4th source (export already reads these) | `completeness_service.py`, `edge_contract_readiness`, `package_writer.py`, `manifest_generator.py` |
| L5 | **P6 new producers** | Add small read-only producers for item-kinds with none today (CRUD Phase 0: **handoffs + entities**; more kinds arrive with their own tracks) | — |
| L6 | Phase 1 safety | Collapse-only, cards **stay in the DOM** → wholesale `saveAll()` untouched → zero save-risk. State it as a Phase-1 constraint | the `saveAll` model + the "save blocked to avoid dropping restored interfaces" guard |
| L7 | **G1 target** | Single-item **upsert** save is the target shape (Step 2 already ships this idiom); resolve before the desktop split | Step 2 upstream save |
| L8 | G1 acceptance | one item per request · Cancel restores only the selected item · dirty browser-back prompts · board refreshes from **saved** state (save response returns the fresh `ReadinessItem` + counts) · validation deep-links via `section_ref`/`field_ref` | — |
| L9 | **G2 Step 6 shape** | Item = the **entity rule-set** (cross-entity rules depend on same-entity prerequisites); field-grouped editable cards; advisory conflicts = **read-only dashed-amber strip, never blockers**; Legacy Notes stay quiet/separate; right rail = read-only advisory summary on the P6 model | `step6_rules.html`, `refreshCrossEntityRuleRow()` |
| L10 | **Matrix Lite** | **OUT of v1**; IN later only for homogeneous scalar rules; cross-entity + advisory permanently excluded | — |
| L11 | P2 effort | "Forms moved verbatim" **understates** it — SOAP/file mapping sections are heavy template/JS (budget DOM surgery) | `step4_downstream.html` SOAP + mapping-row builders |
| L12 | P3 effort | Adopt; `step3_entities.js` (**1,881 lines**) re-projection is the single biggest Phase-1 JS item | `step3_entities.js` |
| L13 | P4 axes | Family = element accent only; zone tint = page function; **never** a family-coloured panel background | — |
| L14 | Add-new-item | Under-specified: "+ Add" creates a `draft` item, opens it focused, shows it under Draft | — |
| L15 | Naming swap | `step4_downstream` = displayed Step 5 / `step5_handoffs` = displayed Step 4 — rename during Action-4 (cheap insurance) | — |
| L16 | Follow-on tracks | Kafka + REST-passthrough = **capture-first** (no blind transplant); KA reuses the patch grammar but is **gated on the KA production-readiness decision** | `base.html` per-archetype `nav_steps` |

---

## B. MAINTAINER DECISIONS — the short list

### Sign-offs (approve the locked P0s / gates)
**P5** (L2 + L3) · **P6** (L4 + L5) · **G1 target** (L7 + L8) · **G2 shape + Matrix-Lite-out** (L9 + L10).

### D1 — Tint palette — ✅ DECIDED
Both passes agreed on the *palette system*; the real variable was **intensity** — Fable's whispered (barely
distinguishable from white), Codex's was assertively cool. **Decision: the shared palette at Codex's
intensity, applied to the real canonical layout** (not Codex's demo chrome). Merged target rendered into
[`final-mockups/step5-downstream-contract-board.html`](final-mockups/step5-downstream-contract-board.html):
cool scan board (`--zone-scan #eaf0f8`) · faint-teal readiness stats (`--zone-ready #e8f2f2`) · visible
lilac seed panel (`--zone-derived #f3ecfd`) · amber needs-action band (`--zone-attn #fdf0d8`) · white
elevated editor. All zones ≥ ~93% luminance (ink ≥ 8:1); family stays element-accent-only; selection >
zone > default. Codex's namespaced variant (`…-codex-tint.html`) is retained for reference.

### D2 — G1 first split-editor slice — ✅ DECIDED
**Decision: single-item upsert from Phase 2a — no interim** (Fable's position; the long-term shape). Both
passes agreed the end state is single-item upsert; the only question was whether to build Codex's
session-patch *interim* first. It's rejected because:
- the interim is **throwaway** (you replace it with the real routes anyway) — and throwaway save code tends
  to *linger* as a second save path, the exact "two contradictory behaviours on one page" anti-pattern both
  reviews flagged for P5 seeding;
- the real route is **cheap** — Step 2 already ships single-item upsert (one small route per step, reusing
  existing validation), so the interim saves little;
- the interim still **rebuilds the whole list** (from session vs DOM), so it is *not* concurrency-clean;
  touch-one-item-keyed-by-id is the only multi-session-safe shape, and multi-session (**PR #200**) is the
  whole reason single-item matters;
- it delivers the cleaner **Save-in-editor / Continue-on-step** split sooner.

PR #200 timing affects only *urgency* (if concurrent, the interim is actively unsafe), not the choice. Net:
one small single-item-upsert route per step lands in Phase 2a — a contained Studio-`.py` slice.

---

## C. Redlines Action-4 inherits (beyond §A/§B)
- **§4:** the XML-security acceptance tests must **also** cover the *existing* pasted-content inspect
  endpoints (they parse user XML server-side today), not only the new file helper. *(Fable add; adopt.)*
- The save-response-returns-readiness rule (L8) is also the cheapest answer to the **five-surfaces refresh**
  (board row · editor banner · tab badges · ambient stats · rail chip) — otherwise it's N+1 fetches.
- **P7** seed-from-entity needs entity-field context the handoffs template doesn't receive today (a small
  read endpoint or added template context).
- Once items save individually, the step button becomes **Continue**; item **Save** lives in the editor
  footer — don't leave one button doing both.

---

## Gate readiness — ✅ CLOSED
Locked set (§A) **signed off by the maintainer 2026-07-03**; D1 + D2 (§B) decided the same day. **Action-4
is delivered:** [`implementation-design.md`](implementation-design.md) — the 24-PR phased build contract —
starts from this sheet + the two review passes.
