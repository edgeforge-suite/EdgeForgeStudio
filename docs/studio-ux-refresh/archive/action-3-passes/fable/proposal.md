# EdgeForge Studio — UX Refresh Proposal (Action 3)

> **Status:** PROPOSAL (round-2, strengthened by the ChatGPT cross-review — §2.2) — awaiting maintainer
> review gate (initiative §5, gate 2).
> **Inputs:** Action-2 current-state walkthrough (`../../baseline/current-state-walkthrough.html`, 52
> stills) + the initiative brief (`../../initiative.md`, guardrails §3).
> **Method:** 3 independent design directions produced in parallel (A "Registry + Focused Editor",
> B "Progressive Disclosure in Place", C "Contract Hub") → judged against guardrails + pain
> observations → synthesized into one proposal, then **stress-tested by an adversarial ChatGPT review of
> this pass and revised accordingly (§2.2)**. Refinement: 1 round (mockup count fix).
> **Deliverables:** this proposal + 6 rendered target-state mockups in [`mockups/`](mockups/)
> (self-contained HTML you can open in a browser, plus PNG screenshots).
> **Date:** 2026-07-02.

## 1. Executive summary

Studio's pages grew as form-stacks; the fix is to make **collections scannable and editing focused**.
The synthesized design:

- **Every collection page (Steps 2 / 4 / 5) becomes a typed registry** — one ~46px row per
  contract/handoff — and **all editing moves to a focused editor** (right-side drawer; one item at a
  time). Learn the pattern once, use it on all three pages. This generalizes an idiom Studio already
  ships in the Knowledge Workspace; it is not a foreign pattern.
- **The entity model inverts**: instead of one identity-role dropdown per field × entity (mostly
  "No role"), each entity gets **one persistence-identity picker**; roles render only where they
  exist. All three independent directions converged on exactly this — the data model ("at most one
  `persistence_id` per entity") already implies it.
- **A three-axis visual token system**: *type = hue + monogram* (REST teal, fixed-width indigo, CSV
  green, XML/XSD amber, SOAP/WSDL violet, staging-table slate, Kafka orange), *state = pill*
  (unchanged palette), *provenance = chip* (`DERIVED` / `MANUAL` / KA badge — formalizing Step 6's
  existing `SPEC-DERIVED` grammar). A SOAP row can never again read as a CSV row.
- **Derive-don't-retype, deterministically**: WSDL/XSD parsed into pickers (browser `DOMParser` —
  frontend-only for pasted content), exact-name mapping seeds, staging columns seeded from linked
  entities via a documented type map. Every prefill is an exact transform, chip-marked, editable —
  never guessed.
- **Phase 3 (optional): a read-only "Contract Map"** — upstream | canonical core | downstream — as an
  additive overview route mirroring the product's own contract-hub thesis, with entity-connection
  highlighting and ambient readiness. The wizard remains; the map is a lens, not a replacement.

Backend touch across the whole proposal: **one small, optional, read-only helper** (fetch/parse a
package-relative artifact when only its path is given). Engine/KS logic and the manifest are untouched.

## 2. The three directions and the judgment

| | A — Registry + Focused Editor | B — Progressive Disclosure in Place | C — Contract Hub |
|---|---|---|---|
| Core idea | Master-detail everywhere; registry rows + drawer editor | Keep pages; collapse everything saved; accordion editing | Contract map as home; wizard demoted to readiness checklist |
| Pain-1 kill | **Strongest** (scan surface fully separated from edit surface) | Strong (cards collapse, but expanded form still pushes the page) | Strong (cards on a map) |
| Risk / cost | Medium (drawer JS; forms move verbatim) | **Lowest** (CSS/JS-only disclosure) | Highest (new home, two views of one state) |
| Distinct value | Symmetry: one pattern for Steps 2/4/5; native KW idiom | Cheapest first ship; provenance/capability chips; error-visibility discipline | Product-thesis alignment; reviewer comprehension; ambient readiness |

**Verdict: A wins the core pattern.** B's disclosure mechanics and token axes are grafted in (and its
"smallest slice" discipline becomes Phase 1); C survives as an additive read-only overview (Phase 3)
rather than a navigation replacement — its comprehension value is real, but replacing the wizard spine
is not required to kill any pain and would put muscle memory and state-drift risk on the critical path.

**Convergent findings adopted as design facts** (independently reached by all three): the per-entity
persistence-identity inversion; the type-token system with orthogonal axes; the deterministic-defaults
inventory; one-at-a-time editing; making pain 5's asymmetry *legible* rather than hidden.

### 2.1 Cross-review with the parallel ChatGPT pass
An independent ChatGPT proposal was produced from the same baseline. It **converged almost entirely**:
the same three directions (registry+inspector, contract map, and a *Bulk Matrix* mode I had not
explored), the same "Contract Cockpit" synthesis (registry primary + map lens + matrix for dense
grids), the same exception-based identity roles, type-colour + capability badges, `DERIVED`-chip
helpers, and the identical no-Engine-change guardrail + "does not solve" scope. Two independent senior
passes reaching the same design is strong validation of the direction. **Adopted from it:** the
explicit **Bulk/Matrix mode** (P8) and the registry filter + **Compact** density toggle.
**Deliberately not adopted:** (a) its per-row *"generation impact"* column in the entity matrix — it
re-introduces the pain-2 boilerplate as a column and overflows horizontally; P3's hide-and-explain-once
is tighter; (b) its stacked source/canonical/outputs explainer cards above the Downstream list —
vertical bulk before the real work; a per-row capability chip carries the same truth more compactly.

### 2.2 Round-2 revision — response to ChatGPT's review of this pass
After this pass was shared, ChatGPT Pro returned a detailed adversarial review (saved verbatim at
[`../chatgpt/review-of-fable-pass.md`](../chatgpt/review-of-fable-pass.md)). Its verdict — *"would not
sign off as-is, would sign off a tightened version"* — is fair, and its central critique is correct
enough to change the implementation bias here: **compact rows, drawers, a matrix, and a map all share
one failure mode — they can make the app *look* solved while moving errors out of sight.** The cure is
to lead with the boring-but-robust surface and add the clever ones as enhancements. Disposition:

| Pattern | ChatGPT's push | Disposition |
|---|---|---|
| P1 Registry | Make it a **triage registry** — blocked-first, sticky status/type filters, the exact blocker inline (not a vague "2/4 dots") | **Adopt** |
| P2 Editor | **Full-page `?focus=` first**; drawer becomes a desktop-only enhancement (a11y / deep-link / build risk) | **Adopt — invert** |
| P3 Entity inversion | Keep it (the strongest bet) — but add a decision-local **generation-impact strip**, not a buried disclosure | **Adopt** |
| P4 Tokens | Hue must be **secondary**: type = monogram + label + border + hue; state = pill + icon + text; provenance = chip + source. Never colour-alone | **Adopt** |
| P5 Defaults | Show every derivation as a **reviewable patch** (Apply? / target / source / transform), never silent prefill | **Adopt + sharpen** |
| P6 Readiness | **One readiness view-model** per item, reused by rows / editor / Step 7 / map — no duplicated client-side "complete" logic | **Adopt → promote to P0** |
| P7 Contract Map | Ship a **Trace Lens inside Step 7** first; defer the standalone `/map` route until registry/editor prove stable | **Adopt** |
| P8 Matrix | Ship **"Matrix Lite"** — native table + fill-down/paste **with preview-before-save + undo + card fallback**; no faux spreadsheet | **Adopt** |

**Three places I push back or sharpen rather than adopt straight:**
1. **Derivation patch — exact transforms only; no speculative "candidate" tier.** The review sheet is
   right, but one of ChatGPT's own example rows (`openedAt → opened_at`, marked *"candidate only; not
   applied"*) is internally inconsistent: a camelCase↔snake_case normalization **is** a deterministic
   exact transform, so it should apply (chip-marked, editable) — while anything *fuzzy/similarity-based*
   must not appear as a pre-selectable candidate at all. A "maybe" tier would quietly reopen the
   deterministic-not-assumptive guardrail. So the patch lists **only** exact transforms (pre-checked)
   plus honest **"no match → left blank"** rows — no third guess tier.
2. **Compress the `MANIFEST REFERENCE` chip; don't delete it.** ChatGPT calls the repeated chip "noise"
   and wants it in a tooltip. Half-right: it does eat a column, so it compresses to a **capability icon +
   legend** — but it is *not* decoration. It is the one signal that makes pain 5's structural reality
   (only REST populates entities; everything else is a reference) legible on the scan surface. The
   distinction must survive the compression, not vanish into a hover.
3. **Keep the spatial Contract Map on the roadmap (deferred), not killed.** The Trace-Lens-in-Review is
   the right *first* comprehension surface and I adopt it. But a true upstream | core | downstream map
   still carries a whole-topology overview a linear trace can't — so it stays a *later, optional* surface
   generated from the same readiness view-model, not deleted outright.

**What this changes downstream in this doc:** §3 patterns carry a one-line pointer where a mechanic
changed; §6 gains three hard guardrails (single readiness view-model · security-scoped backend helper ·
provenance never enters the manifest); §7 gains a **Phase 0** (shared readiness view-model + accessibility
contract) and leads Phase 2 with full-page editors. Two further fully-agreed additions are folded in: the
**handoff three-block split** (identity · staging columns [derived vs manual-operational, *separated*] ·
entity→staging mappings, with a before/after DDL diff before save), and **empty/overflow/failure-state
acceptance criteria** as a pre-implementation requirement per surface. Net: the direction is unchanged and
now independently validated; the *implementation bias* moves from clever-first to robust-first.

## 3. The design, pattern by pattern

> **Round-2 note:** the patterns below are the round-1 synthesis; the §2.2 revisions supersede specific
> mechanics — registry → **triage** registry, drawer → **full-page-first**, matrix → **Matrix Lite**,
> map → **Trace-Lens-in-Review first**. Each affected pattern is flagged inline.

### P1 — Typed registry (Steps 2, 4, 5) · mock 1
> **Round-2:** becomes a *triage* registry — group **blocked-first**, add sticky status/type filters, and
> surface each row's **exact blocker** inline (not just "n/4 dots"). Compress `MANIFEST REFERENCE` to a
> capability icon + legend: keep the pain-5 signal, drop the column.

One row per saved item: type monogram tile + 3px hue left-border · name + artifact path (mono) ·
system/version · one **type-specific fact** (SOAP: `Service · op · mode`; CSV: `delimiter · header ·
cols`; FW: `n fields · m/n mapped`; TBL: `table · cols · mapped`) · **capability chip**
(`POPULATES ENTITIES` on REST; `MANIFEST REFERENCE` on file/XML/SOAP/downstream — pain 5 made
legible) · **completeness dots** (n/4 sections, red dot names the gap) · status pill · Edit/⋮.
Rows group under tinted, counted type headers; a filter box + a **Compact** density toggle sit above the list (scan 20+ items without scroll). The add-form collapses to a **type-picker chip row**
("Add: FW · CSV · XML · SOAP") — type first, then that type's editor. A slim sticky footer keeps
Previous/Continue one glance away. Today's per-row advisory prose moves into the editor's readiness
banner; **counts and dots must derive from the same validation state that drives export readiness —
summary lines must never lie.**

### P2 — Focused editor (drawer) · mocks 2, 4
> **Round-2:** the **full-page `?focus=` editor is now primary**; the drawer drops to a Phase-2
> desktop-only enhancement (safer on accessibility, deep-linking, and build cost). Section tabs carry
> **error badges** so a required blocker can't hide on an inactive tab.

Right-side drawer (~800px): pinned header (monogram, name, type ribbon, status pill, one-line
**readiness banner** saying exactly what unblocks export) · section anchor tabs (Identity / type
section / Mapping / Sample) · body = **today's form fields moved verbatim** (same names, same save
endpoints) · pinned footer (validation summary + Cancel/Save). Implemented as a server-rendered
fragment injected by vanilla JS (`<dialog>`); **fallback:** the same template rendered full-page via
`?focus=<id>` — the fallback alone delivers most of the win if drawer JS proves fiddly. Dirty-close
guard prompts save/discard.

### P3 — Entity-model inversion (Step 3) · mock 3
> **Round-2:** add a decision-local **generation-impact strip** under the persistence picker (Java `@Id`
> · DB PK · repository lookup · CRUD route identity · `→ identity_overrides`); use explicit decision-state
> language (required / metadata-only / out-of-scope / reference-only); add field search + required-only
> filter for 100+ field entities.

Left: entity registry cards (name, field/rule counts, scope, **🔑 key chip** or red "no key chosen").
Right: the focused entity — a single **"Persistence identity"** select at top with the Engine-behavior
explanation stated **once**, then a compact field table where the role column renders only actual
roles ("—" otherwise). Metadata-only roles live behind "▶ Other identity roles (n assigned)"; the full
vocabulary legend behind a second disclosure. An `ENTITY SOURCE` note names the REST contract that
populated the entities (pain 5, again legible).

### P4 — Visual token system (cross-cutting) · legend on mock 1
> **Round-2:** **hue is secondary** — every type/state/provenance signal needs a redundant
> monogram/label/border, an icon, and text; dots need labels; error is never colour-alone. Now part of
> the Phase-0 accessibility contract.

CSS custom properties in `studio.css`. Three orthogonal axes — **type = hue + monogram** (tile, left
border, group header tint, drawer ribbon), **state = pill** (existing palette, unchanged), **provenance
= chip** (`DERIVED` lilac / `MANUAL` neutral / existing KA badge). Applied identically on Steps 2–5,
Step 7 snapshot, Step 8 artifact lists, and the Phase-3 map. Palette to pass a contrast/color-blind
check before implementation (open decision 3).

### P5 — Deterministic defaults (derive-don't-retype) · mocks 2, 4
> **Round-2:** derivations surface as a **reviewable patch** (Apply? · target · source · transform) —
> **exact transforms only**, pre-checked + editable, plus honest "no match → left blank" rows; **no
> speculative "candidate" tier**. The backend helper ships only under §6's security scoping.

All prefills are exact transforms, chip-marked `DERIVED`, editable, and **never overwrite non-empty
values**:
1. **WSDL → pickers**: Service/Port/Binding/Operation become dropdowns of what the WSDL actually
   declares (auto-select singletons). Browser `DOMParser` on pasted content; no backend.
2. **XSD → root element + namespace prefill**; element list feeds mapping targets.
3. **Exact-name mapping seeds** (Steps 4/5, XML + SOAP + staging): canonical field ↔ contract field
   paired on exact match after case/`snake_case`↔`camelCase` normalization; unmatched rows stay
   blank — labeled so ("no exact match — left blank, never guessed").
4. **Handoff seeding**: table name = `snake_case(handoff name)`; columns seeded from the linked
   entity via a **documented, visible type map** (string→VARCHAR, decimal→DECIMAL(18,2), date→DATE,
   timestamp→TIMESTAMP); lengths only where a spec-derived max-length rule exists.
5. **Convention prefills**: artifact paths from interface names; version default `1.0`. Deliberately
   **no** silent carry-forward of System (that's a guess) — an explicit "copy from previous" button.
6. **Optional small backend helper** (the one core touch, flagged): read-only fetch/parse of a
   package-relative artifact when only a path is given (also covers WSDL-with-imports). Contained,
   deterministic, permitted by the guardrail.

### P6 — Wayfinding & ambient readiness · mocks 1, 5
> **Round-2 → P0:** every one of these signals reads from **one readiness view-model** per item (rows,
> editor banner, Step 7, any lens/map) — no duplicated client-side "complete" math, or the summaries
> eventually lie.

Left-rail steps gain count chips ("Downstream · 6 · 1!"). Step 7 stays the review home; its Ready /
Warnings / Follow-up counters also surface in the Phase-3 map header. Step-7 advisories deep-link to
the owning registry row's editor (`step5#dsi-…`), so review stops being a dead end.

### P7 — Contract Map (Phase 3, additive) · mock 5
> **Round-2:** ship a **Trace Lens inside Step 7** first (`Trace by entity ▼` — upstream | canonical |
> downstream); defer the standalone `/map` route until registry/editor prove stable, and if built it reads
> the same readiness view-model (no map-specific summaries) and never dims away unrelated blockers.

Read-only `/map` route: three columns (upstream | canonical core | downstream) with faint directional
washes, typed lanes, ~84px cards carrying entity **link chips**; clicking an entity highlights its
connected contracts and dims the rest (class toggle on `data-entities` — no SVG, no canvas). Readiness
rail mirrors the 8 steps 1:1; "Switch to classic step view" is always present. Cards link to the
focused editor. Promotion to default home is explicitly **not** proposed now (open decision 2).

### P8 — Bulk / matrix mode (mapping-heavy & multi-field editing) · adopted from the parallel pass
> **Round-2:** ship as **Matrix Lite** — native table, paste-into-column, fill-down, **preview-before-save
> + undo-last-bulk-action**, row-level validation, and a "switch to card editor" fallback. No full
> spreadsheet interaction model in v1 (destructive ops must be previewable + reversible).

For the genuinely grid-shaped work — **Rules & Mappings**, multi-field entity edits, many
canonical-to-contract mapping rows — the focused inspector (one item at a time) is the wrong tool;
a power user wants to edit *many rows at once*. Offer an optional **matrix mode**: a compact,
keyboard-navigable grid (tab across cells, fill-down, paste a column) over the same manifest fields,
`DERIVED` chips intact, non-matches left blank. This complements — does not replace — the
registry+inspector: **registry = scan, inspector = focused single edit, matrix = bulk power-edit.**
Same guardrails (same fields/endpoints, deterministic-only pre-fill). *(Independently proposed by the
parallel ChatGPT pass as its "Bulk Matrix Authoring" direction — its strongest original contribution.)*

## 4. Mockups (rendered + eyeballed via headless Chrome)

| File | Shows | Kills |
|---|---|---|
| [`mock-1-step5-registry.html`](mockups/mock-1-step5-registry.html) | Step 5 as typed registry, 6 interfaces on one screen + token legend | Pain 1, 3, 5 |
| [`mock-2-step5-soap-drawer.html`](mockups/mock-2-step5-soap-drawer.html) | SOAP focused editor; WSDL-derived pickers, readiness banner | Pain 1, 4 |
| [`mock-3-step3-entity-model.html`](mockups/mock-3-step3-entity-model.html) | Entity master-detail; persistence-identity inversion | Pain 2 |
| [`mock-4-step4-handoffs-derived.html`](mockups/mock-4-step4-handoffs-derived.html) | Handoffs registry symmetry + DERIVED column/mapping seeding | Pain 1, 4 |
| [`mock-5-contract-map.html`](mockups/mock-5-contract-map.html) | Phase-3 Contract Map; connection highlighting, ambient readiness | Comprehension / review |
| [`mock-6-rules-matrix.html`](mockups/mock-6-rules-matrix.html) | Rules &amp; Mappings in **Bulk/Matrix mode** (P8) — Cards/Matrix toggle, keyboard grid, DERIVED provenance | Pain 4 + grid-density power-editing |

PNG screenshots sit alongside each HTML. Open the HTML files in a browser for the live versions.

> **Round-2 note:** these six are the *round-1* target-state illustrations. The §2.2 revisions (triage
> registry, full-page-editor-first, Matrix Lite, Review Trace Lens, decision-impact strip, colour-secondary
> tokens) are captured in the text but **re-rendering the affected mockups is deliberately deferred to the
> consolidation step / Action-4** — the Codex pass and the three-way synthesis may move specifics again, so
> re-mocking now would be throwaway. Read the mockups as direction, the §2.2/§3 text as the current spec.

## 5. Pain → resolution matrix

| # | Pain (Action-2 baseline) | Resolution | Where |
|---|---|---|---|
| 1 | Steps 4/5 never collapse (≈85 scroll-ticks; item in 3 places); Step 2 asymmetry | P1 registry + P2 focused editor; one law on all three pages: *collections collapse, editors focus* | Mocks 1, 2, 4 |
| 2 | Identity-role row per field × entity, mostly "No role" | P3 inversion: one picker per entity; roles render only where assigned; legend stated once | Mock 3 |
| 3 | Status pills the only color; SOAP row ≙ CSV row | P4 tokens: type hue + monogram; three orthogonal axes | All mocks |
| 4 | XML/XSD + SOAP mapping fully manual | P5: WSDL/XSD pickers + exact-name seeds + handoff seeding, all `DERIVED`-chipped | Mocks 2, 4 |
| 5 | Only REST populates entities (structural — design around) | Made legible, not "fixed": `POPULATES ENTITIES` vs `MANIFEST REFERENCE` chips; `ENTITY SOURCE` note; map ghost-note | Mocks 1, 3, 5 |

## 6. Guardrail compliance

- **Frontend-first** — Jinja templates + `studio.css` tokens + vanilla JS (`<dialog>`, class toggles);
  no framework, no build system. Forms move **verbatim**; fields, names, and save endpoints unchanged.
- **Manifest-compatible** — zero change to what Studio exports or Engine consumes; presentation and
  prefill only. Prefills write the same values a user would type.
- **Protect Engine/KS core** — one optional read-only artifact fetch/parse helper (flagged); nothing
  else server-side beyond template rendering.
- **Deterministic, not assumptive** — every prefill an exact transform of user-supplied artifacts,
  `DERIVED`-chipped, editable, never overwriting non-empty input; no fuzzy matching; KA untouched,
  opt-in, review/accept.
- **Phased, safe, reversible** — see §7; each phase is per-page, additive, and independently
  revertable (template-level toggle back to the classic layout in Phases 1–2; Phase 3 is a deletable
  additive route).

*Round-2 hard guardrails (added from the ChatGPT review):*
- **Single readiness view-model (P0)** — every readiness signal (registry rows, editor banners, Step 7,
  any future lens/map) reads from **one** server-rendered/read-only readiness object per item. No
  duplicated client-side "n/4 complete" logic — or the summaries will eventually contradict export.
- **Security-scoped backend helper** — the one optional read-only artifact helper ships only if it is:
  read-only, project-root-confined, **no network fetch by default**, import-depth-limited, XXE-safe, with
  deterministic error reporting, **no manifest writes**, and fully behind a flag. (Bank-auditable.)
- **Provenance stays out of the manifest** — `DERIVED`/`MANUAL` provenance is UI/project-side only (or
  recomputed fresh from current values); it must **never** become new Engine-manifest state, or it reopens
  manifest drift.
- **Per-surface failure-state acceptance criteria** — before a surface ships, specify its empty / overflow
  (50+ items) / long-path / nested-XML / unresolved-import / duplicate-name / parser-failure / stale-after-
  back / paste-conflict / keyboard-only states. Mockups not required; acceptance criteria are.

## 7. Phasing (each phase independently shippable + revertable)

*(Round-2 phasing — leads with a foundations phase and inverts the editor order per §2.2.)*

- **Phase 0 — foundations (no visible UI, but everything below depends on it).**
  Define the **single readiness view-model** per item (the one object rows / editor banners / Step 7 all
  read) and the **accessibility contract** for the token system (contrast, redundant shape/icon/label
  encoding, focus states, error semantics beyond colour). Nothing below ships correctly without these.
- **Phase 1 — low-risk compression (biggest visible delta; no backend, no routes).**
  Type-token CSS across Steps 2–5 (hue *secondary* to monogram/label/border); Step 3 persistence-identity
  inversion **with the decision-impact strip** (template-local); the **triage registry** for Steps 5 and 4
  (blocked-first + status/type filters + expand-one-at-a-time — **no drawer yet**); rail count chips.
- **Phase 2 — focused authoring (the core pattern; full-page first).**
  Full-page `?focus=` editors rolled 5 → 4 → 2, forms moved verbatim; **deterministic-derivation review
  sheets** (exact transforms only); WSDL/XSD client `DOMParser` for pasted content; the security-scoped
  backend helper **only** if approved; the **drawer added as a desktop-only progressive enhancement**,
  never a dependency. Footer bar + deep links from Step 7.
- **Phase 3 — power & review.**
  **Matrix Lite** for Rules & Mappings (preview-before-save + undo + card fallback); the **Review Trace
  Lens** inside Step 7; and only after those prove stable, consider the standalone Contract Map (same
  readiness view-model, additive, deletable).

Rollback story: Phase 0 is internal; Phases 1–2 keep the old template blocks behind a flag until sign-off;
every Phase-3 surface (Matrix Lite, Trace Lens, map) is additive and deletable.

## 8. Open decisions for the maintainer (listed, not guessed)

1. **Editor surface** *(round-2: leaning full-page-first)*: full-page `?focus=` as the primary editor,
   with the drawer as a later desktop-only enhancement — confirm this ordering (vs drawer-first as
   originally mocked).
2. **Contract Map** *(round-2: reframed)*: adopt the **Review Trace Lens** in Step 7 as the first
   comprehension surface; the standalone `/map` route is deferred until registry/editor prove stable —
   confirm the spatial map stays on the roadmap (same readiness view-model) vs parked entirely.
3. **Token palette accessibility:** proposed hues need a contrast + color-blind pass (violet/indigo
   adjacency); monograms mitigate but confirm.
4. **Step 2 scope:** adopt the registry there too (recommended for symmetry) or leave its existing
   compact table as-is in Phase 2.
5. **Deterministic-defaults scope for v1:** client-side `DOMParser` only, or also the small read-only
   backend helper (needed for path-only artifacts and WSDL-with-imports).
6. **Completeness semantics:** should "Needs operation/mapping" soft-block Continue (today it
   doesn't)? The UI renders either; this is workflow policy.
7. **Template naming cleanup:** `step4_downstream.html` / `step5_handoffs.html` are swapped vs the
   displayed step order — fix during Phase 2 or leave (cosmetic, dev-facing).
8. **Artifact placement** *(resolved)*: homed in the Studio repo at `docs/studio-ux-refresh/` on branch
   `fable/docs/studio-ux-refresh` (PR #232), alongside the ChatGPT + Codex passes.
9. **Bulk/Matrix mode (P8) scope:** ship in v1 for Rules & Mappings (highest grid density) + the
   entity field/role grid, or add it after the registry+inspector lands.

## 9. Un-captured surface (flagged per the handoff)

The **Kafka archetype flow** (separate kafka_step1–3 templates) and the **KA accept/edit/reject loop**
were scoped out of the Action-2 baseline. P1/P2/P4 are designed to extend to both (typed lanes/rows and
drawers generalize; KA's accept/edit/reject is already provenance-chip-shaped), but no proposal element
here was validated against them — extending is design-by-analogy until a capture pass covers them.

## 10. Definition-of-done self-check → HALT

- Every pain observation has ≥1 addressed direction — §5 matrix. ✅
- Every element passes all guardrails — §6. ✅
- Mockups exist for the priority pages (long contract/handoff pages, entity model, visual system —
  plus the map), rendered and eyeballed. ✅ (1 refinement round used, cap ≤2.)
- Open decisions listed for the maintainer, not guessed — §8. ✅

**HALT.** Convergence is the maintainer's call (initiative §5, gate 2): review this proposal + the
mockups, decide the §8 items, then Action 4 (phased implementation design doc) follows sign-off.
