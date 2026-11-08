# ChatGPT Pro — Review of the consolidated `proposal-final.md`

> **Provenance:** GPT Pro's review of the consolidated final (2026-07-02), saved verbatim (ChatGPT has
> no git access). Verdict: **approve the direction with redlines; not implementation-ready until the
> P0/P1 ambiguities are tightened.** Dispositions folded into
> [`../../proposal-final.md`](../../../proposal-final.md) §2.2 (round-3).

---

According to the consolidated proposal dated 2026-07-02, my verdict is: **approve the consolidation
direction, but do not treat it as implementation-ready until a few P0/P1 ambiguities are tightened.** It
captures my pass fairly and materially improves the Fable version. My remaining objections are mostly
about execution risk, not concept risk.

## 1. Is my pass + review captured fairly?
Yes — mostly fairly and explicitly. The final proposal synthesized Fable, ChatGPT, Codex, and both
cross-reviews, then lists the same hardened principles I pushed for: compact scan surfaces, one focused
editor, exceptions-first entity modeling, deterministic reviewable seeds, visible contract-family
silhouettes, and one readiness truth. Specific contributions present:

| My prior stress-test point | Final treatment | Verdict |
|---|---|---|
| Triage registry / blocked-first rows | P1 is now a triage board, grouped by family, sorted blocked-first, exact blockers inline. | Captured |
| Full-page-first instead of drawer-first | §2.1 makes full-page `?focus=<id>` the baseline, desktop split + narrow modal as variants. | Captured |
| Reviewable derivation patch | P5: exact transforms only, chip-marked, editable, never overwriting non-empty, review patch / Keep, nothing silent. | Captured |
| Single readiness view-model as P0 | P6/§4 make one read-only readiness object the source for rows, editor banners, Step 7, trace lens. | Captured |
| Matrix Lite, not spreadsheet mode | P9 is native-table Matrix Lite: paste/fill-down, preview-before-save, undo-last-bulk, validation, card fallback. | Captured |
| Trace Lens inside Step 7, not standalone map first | P8 moves comprehension into Step 7, defers the standalone Contract Map. | Captured |

The only fairness caveat: the final says Matrix Lite was "only 1.5/3 passes" and defers its mockup. That
is acceptable, but slightly underplays that Rules & Mappings is the one place where a matrix is not just
nice-to-have but the correct shape for bulk rule authoring. Leave it optional for Phase 3, but do not let
it disappear.

## 2. Resolved editor surface: sound, or do I still favor pure full-page-first?
The resolved surface is sound as a product target. I no longer argue for pure full-page-only as the final
design. The reconciliation is the right architecture: one URL-backed focused editor route, rendered as —
baseline: full-page `?focus=<id>`; wide desktop: persistent split (board left + editor right); narrow:
modal/route-style takeover. That captures the accessibility/deep-link benefits I wanted and the
context-preservation Codex wanted, while dropping Fable's drawer as primary.

But I still favor full-page-first as the Phase 2 *implementation order*. Tighten to:
- Phase 2a: full-page `?focus=` route only
- Phase 2b: desktop split enhancement behind a flag
- Phase 2c: narrow modal only after a11y acceptance passes

Reason: "narrow modal" reintroduces the same focus-management, dirty-close, scroll-containment, and
screen-reader risks that made the drawer suspect. The modal is fine as a later rendering mode, not a
baseline requirement.

## 3. Did the consolidation drop or dilute P0/P1 risk findings?
Most survived (single readiness truth, security-scoped helper, provenance out of manifest, a11y,
failure-state criteria). But I would still redline:

**P0 — Readiness view-model is named, but not specified.** Add a mini contract before Action 4:
```
ReadinessItem {
  item_id
  item_kind
  family
  display_name
  state: ready | warning | needs_action | blocks_export | draft
  export_blocking: boolean
  blockers: [{ code, label, field_ref, section_ref, deep_link }]
  warnings: [{ code, label, deep_link }]
  coverage: [{ label, complete, total }]
  capability: populates_entities | manifest_reference | metadata_only
  source_of_truth_version
}
```
Also define precedence: `blocks_export > needs_action > warning > draft > ready`. Without this, "Ready,"
"Needs action," "Blocks export," "Warnings" will drift between board, editor, review, trace lens, export.

**P0 — Save model is still too casually left as an open decision.** It is a P0 interaction-risk decision
because the desktop split creates two views of one selected item. Minimum acceptance:
- Editing one focused item cannot accidentally submit hidden rows.
- Cancel restores the selected item only.
- Browser back with dirty state prompts.
- Board row refreshes from saved state, not local optimistic summary.
- Validation errors deep-link to exact section + field.

**P1 — Step 4 mock violates blocked-first discipline.** The Step 4 handoff mock shows two ready handoffs
above Payment staging (Review DDL / needs action). Put needs-action first or use explicit sections.

**P1 — Step 5 editor blocker-count ambiguity.** "One field blocks export" while the Mapping tab has a red
badge 6 can read as six blockers. Rename tab badges by severity: `WSDL & Operation · 1 blocker` /
`Mapping · 6 warnings` / `Sample optional`, or two badge styles (red = export blocker, amber/blue =
incomplete non-blocking).

**P1 — Deterministic patch needs collision + normalization rules.** `accountID` / `accountId` /
`account_id` can normalize to collide. Rules: exact raw-name match wins; exact normalized match allowed
only if one source and one target remain; multiple normalized matches → leave blank + show collision;
never preselect a collision; show transform basis in the patch row.

**P1 — Matrix Lite is specced but visually deferred.** Acceptable, but Action 4 must not hand-wave it. Add
acceptance criteria now: paste preview before commit; undo last bulk action; per-cell validation before
save; row-level error summary; keyboard-only path documented; screen-reader fallback to card editor.

**P1 — Scope-out note for Kafka and KA got diluted.** §9 is strong on Engine/manifest/AI boundaries but
does not restate that Kafka archetype flow and KA accept/edit/reject were not validated by these mockups.
Add back under §9: *Not validated in this pass — Kafka archetype-specific flow; KA accept/edit/reject
loop; non-CRUD archetype navigation. Patterns are intended to extend but require a capture pass before
implementation.*

## 4. Per-mockup review

**Step 5 — Downstream Contract Board — adopt with small fixes.** Best proof the merged design works;
kills the ~85-scroll-tick disease. Fixes: (1) change left-rail `1!/5` to `1 blocker · 5 contracts`;
(2) distinguish export blockers from non-blocking incomplete mappings in the editor tabs; (3) keep
`MANIFEST REF` compressed but add an accessible text legend on the page, not only colour/icon; (4) for
20+ contracts define section behavior — Needs action always expanded, Ready collapsed after N rows with
Show all, filters sticky.

**Step 3 — Identity Role Lens — adopt.** Substantial improvement. Fixes: (1) `KA OFF · clean` →
`Knowledge Assist: Off` ("clean" could sound like validation passed); (2) add an explicit missing-key
state in the right panel (`Required before export / generation`), not only red text in the left card;
(3) table-mode threshold — if >50 fields, default to assigned + required with search.

**Step 4 — Handoff Board — adopt with one important correction.** Three-block editor is right and fixes
the operational-columns-as-failed-mappings ambiguity. Fixes: (1) sort needs-action handoffs first (the
mock doesn't); (2) rename `GENERATED DDL` → `DDL Preview` / `Derived DDL Preview` (risks sounding like
Engine output changed); (3) sharpen the banner — "This page authors staging tables only. File/XML/SOAP
artifact transforms remain in Step 5."; (4) in the DDL diff show changed lines with text labels, not only
colour.

**Step 7 — Trace Lens — adopt as the Contract Map replacement, with one safety addition.** Right
compromise; comprehension without a second home. Fix: add an *unrelated blockers* strip when tracing a
selected entity ("Other export blockers not connected to Account: …"). Even though it "never dims away
unrelated blockers," selecting one entity can still cause reviewer tunnel-vision; a visible strip makes
the guarantee concrete.

## 5. Anything the merge got wrong or left ambiguous
- **Ambiguity 1 — "Narrow modal" needs a fallback rule.** On narrow screens the focused editor must be
  route-addressable and restorable via browser back; modal presentation allowed only if it preserves
  focus, dirty state, and deep-link semantics.
- **Ambiguity 2 — "Export blockers" vs "Needs action" policy.** Taxonomy: Warning (export allowed) ·
  Needs action (continuation allowed, export may/may not) · Blocks export (export disabled until fixed) ·
  Draft (intentionally incomplete, export disabled only if in active package). Wire every pill to one.
- **Ambiguity 3 — Backend helper scope is right, but acceptance tests are missing.** Add: `../` traversal
  rejected; external entity rejected; recursive import depth exceeded; unresolved import → deterministic
  warning; helper disabled still leaves manual path workflow usable.
- **Ambiguity 4 — Provenance lifecycle.** Say whether provenance is recomputed or stored in Studio project
  state. Preference: default recompute where possible; optional UI-only project metadata allowed, never
  exported to the Engine manifest.
- **Ambiguity 5 — Step 2 parity comes late.** Bring family tokens + readiness chips to Step 2 in Phase 1;
  full editor parity in Phase 4 if still needed.

## Final verdict
Adopt the consolidated proposal with redlines. It captures my pass and review fairly and is stronger than
Fable's original: triage instead of mere registry, full-page route instead of drawer dependency,
reviewable deterministic patches, single readiness truth, Matrix Lite instead of spreadsheet sprawl,
Trace Lens instead of a premature Contract Map.

**Required fixes before Action 4:**
1. Specify the P6 readiness view-model shape + precedence.
2. Treat save/dirty-state as a P0 decision, not a minor open question.
3. Implement full-page `?focus=` first; split second; narrow modal only after a11y pass.
4. Make all boards actually blocked-first, including Step 4.
5. Add deterministic seed collision rules.
6. Add an unrelated-blockers strip to Step 7 Trace Lens.
7. Restore the explicit Kafka + KA unvalidated-surface caveat.
8. Add Matrix Lite acceptance criteria even if the mock is deferred.

With those changes, I would sign off the proposal as ready for the maintainer gate and Action-4
implementation design.
