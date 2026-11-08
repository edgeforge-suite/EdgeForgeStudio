# Studio UX Refresh — Action-4: Phased Implementation Design

> **Status:** ACTION-4 DELIVERED + **verified** — the build contract for Action-5. Codex ran an
> independent source-grounded pre-build verification ([`action4-review-codex.md`](archive/action4-review-codex.md),
> commit 28ff005): **approve with redlines**, all five (R1–R5) now folded in below. **§8 adds the agreed
> Action-5 execution model** (Claude/Codex per-PR ownership + cross-vendor review model, both confirmed
> by Codex). Maintainer gate 3 is approved; **Action-5 is complete and every PR-24 merge gate in §4.2
> has passed, including the August 9 maintainer demo sign-off.** **§7.1 records the approved PR-18-retirement /
> PR-24a amendment.**
> **Owner:** Suite design/architecture thread (Fable). **Audience:** the Studio build thread (Action-5)
> and its reviewers — each PR below is written to be independently buildable and reviewable.
> **Inputs (all on this branch):** [`proposal-final.md`](proposal-final.md) (round-3, §12 scope freeze) ·
> [`review-pass-fable.md`](archive/review-pass-fable.md) · [`review-pass-codex.md`](archive/review-pass-codex.md) ·
> [`review-reconciliation.md`](review-reconciliation.md) (locked set §A signed off by the maintainer
> 2026-07-03; D1 tint + D2 save-model decided) · the final mockups in [`final-mockups/`](final-mockups/).
> **Source facts** in this doc were re-verified against the working tree on 2026-07-03 (routes, services,
> template/JS line counts, save idioms, env conventions).
> **Date:** 2026-07-03. Design/docs only — no production code changed by this document.

---

## 0. Ground rules — binding on every PR

1. **Guardrails (proposal §4):** frontend-first · manifest-compatible · protect Engine/KS core ·
   deterministic-not-assumptive · phased/safe/reversible · **single readiness producer** ·
   **provenance never persisted to the manifest** · a11y contract (no colour-only encoding).
2. **Rollout discipline.** Visible changes shipped behind `EDGEFORGE_STUDIO_UX_REFRESH` through
   PR-23. Legacy markup remained frozen until PR-24 removed it; §1.1 and §3.1 define the post-flip
   single-presentation contract and retired-setting compatibility gate.
3. **Project-file compatibility (proposal §12.2).** No new *required* persisted field, ever. Anything new
   is optional + back-fillable. The round-trip tests (§3.2) are merge-blocking from PR-03 onward.
4. **Engine:** zero changes. **Studio `.py`:** only what §1.2–§1.4 specify (readiness adapter + producers,
   save-one routes, seed-patch migration); everything else is Jinja/CSS/JS.
5. **Conventions:** branch `<agent>/feature/ux-refresh-pr-NN-<slug>`; PR title
   `[FEATURE] UX Refresh PR-NN: <title>` (or `[CHORE]` where marked). One doc-PR-ID per GitHub PR —
   do not bundle.
6. **Definition of done (paste into every PR description):**
   - [ ] Before PR-24: flag-off rendering unchanged and both-state smoke green (§3.1)
   - [ ] PR-24 onward: retired setting values render the same refreshed surface
   - [ ] Round-trip + readiness-parity suites green (from PR-03)
   - [ ] A11y checklist items for touched surfaces (§1.5) checked
   - [ ] No manifest/schema change; no new required persisted field
   - [ ] Single `git revert` cleanly removes this PR (no cross-PR entanglement)
   - [ ] PR description links the PR-ID section of this doc + the mockup(s) it implements

---

## 1. Foundation contracts

### 1.1 Refresh runtime state (PR-24)

- The refresh and desktop-split rollout switches are retired. `EDGEFORGE_STUDIO_UX_REFRESH` and
  `EDGEFORGE_STUDIO_UX_SPLIT` no longer select markup or behaviour; old environment values are ignored.
- `app/services/nav_context.py:build_nav_context()` retains `ux_refresh=True` and `ux_split=True` as
  temporary compatibility context keys for callers that still inspect the settled state. They are not
  feature flags and are not user/session preferences.
- `base.html` always adds `class="ux-refresh"` to `<body>`. The class is now a stable CSS namespace,
  not a runtime gate. Templates render only the refreshed markup.
- Focus routes render the desktop board/editor split as the standard presentation at 1200px and wider.
  CSS collapses it to the supported single-column full-page focus presentation below 1200px.

### 1.2 `ReadinessItem` view-model — one producer (locked L4/L5)

New module **`app/services/readiness_view.py`** — an **adapter over the existing producers**, not a new
engine: `completeness_service.build_completeness_report()` (already export-aligned via
`is_exportable()` and consumed by `package_writer.py`) + `edge_contracts.edge_contract_readiness`.

```python
@dataclass(frozen=True)
class ReadinessItem:
    item_id: str        # "dsi:<name>"|"usc:<name>"|"handoff:<name>"|"entity:<name>"|"rules:<entity>"|"project"
    item_kind: str      # downstream_interface|upstream_contract|handoff|entity|rule_set|project
    family: str         # rest|fixed|csv|xml|soap|staging|entity|rules
    display_name: str
    state: str          # ready|warning|needs_action|blocks_export|draft
    export_blocking: bool
    blockers: list[Ref] # {code, label, field_ref, section_ref, deep_link}
    warnings: list[Ref]
    coverage: list[Cov] # {label, complete, total}
    capability: str     # populates_entities|manifest_reference|metadata_only
    source_of_truth_version: str   # session revision marker (see §1.3 conflict echo)
```

- **API:** `items_for_step(session, step) -> list[ReadinessItem]` · `step_counts(session) -> dict`
  (feeds ambient stats + rail chips) · `item(session, item_id) -> ReadinessItem`.
- **State precedence:** `blocks_export > needs_action > warning > draft > ready`. **Policy:** warning =
  export allowed · needs_action = continue allowed · blocks_export = export disabled · draft =
  intentionally incomplete (blocks only if in the active package).
- **Parity rule (merge-blocking test) — scoped to represented item-kinds (R1, P0 redline):** for every
  *represented* item, `export_blocking == (package_writer / edge_contract_readiness would block it)`.
  **`is_exportable()` is NOT re-derived from the item list** — `build_completeness_report().is_exportable()`
  stays the *authoritative* overall export gate (it also blocks on top-level `project` fields and non-edge
  upstream / sample / OpenAPI states that are not yet item-shaped, per Codex's audit of
  `completeness_service.py:25-60`). The board's ambient "export blockers" count = represented
  `blocks_export` items; **Step 8's export-disable keeps reading the full report, unchanged.** A `project`
  item-kind (added below) carries the top-level blockers into the rail/Step-7 as they get itemized; until
  then they surface via the existing report — never silently dropped. The invariant that must hold: **no
  represented item is `blocks_export` while `package_writer` would pass it, and vice-versa.**
- **New producers (PR-04), read-only:** `handoff` (table name present · ≥1 column · DDL generated-or-
  manual · mappings reference existing columns) and `entity` (persistence key chosen unless
  metadata-only/out-of-scope → else `needs_action`, `blockers[{code:"missing-persistence-key",
  section_ref:"identity", …}]`). `rule_set` arrives with PR-19. Kafka/passthrough/KA kinds belong to the
  follow-on tracks — **out of scope**.
- **Consumers (added progressively):** board rows · editor banner + tab badges · ambient stats · rail
  chips · Step-7 report rendering · Trace Lens. **No consumer computes readiness client-side, ever.**
- **`deep_link` format:** `<step-route>?focus=<item name>#<section_ref>` (e.g.
  `/downstream?focus=account-status-soap-out#wsdl`).

### 1.3 Single-item save contract — G1, decided: upsert from Phase 2a, no interim

Today: `/downstream/save`, `/handoffs/save`, `/rules/save`, `/entities/save` are **whole-list,
DOM-as-truth** posts. Step 2's `/upstream/edge-contract/save` is already single-item (name-keyed
filter-and-append via `get_current_session`/`save_current_session`) — **but has no rename handling**:
saving under a changed name leaves the old row behind. The new contract fixes that everywhere.

**Routes (one per focused-editor step):**

| Route | PR | Replaces (for the focused editor path) |
|---|---|---|
| `POST /downstream/interface/save-one` | PR-12 | `/downstream/save` |
| `POST /handoffs/save-one` | PR-14 | `/handoffs/save` |
| `POST /upstream/edge-contract/save` *(gains `original_name`)* | PR-15 | itself |
| `POST /rules/save-one` *(one entity rule-set)* | PR-19 | `/rules/save` |

**Request:** `{ item: {...same field names the wholesale save posts today...}, original_name:
str|null }` — `null` = create (a `draft`). **Server:** load session → validate the ONE item (**reuse or
extract** the existing per-item validation — `validate_edge_contract_payload` is already reusable for
edge contracts, but **handoff + rule validation is embedded in the whole-list routes today** and must be
extracted into a per-item helper as part of PR-14 / PR-19, per Codex's audit) → upsert keyed by
`original_name` (rename = replace old row atomically) → `save_current_session` → respond.

**Response — the five-surface refresh payload (locked L8):**
```json
{ "ok": true, "item": {…saved…}, "readiness": <ReadinessItem>,
  "step_counts": {…}, "rail": [ {step, count, attention}… ] }
```
The editor applies it to: board row · editor banner · tab badges · ambient stats · rail chip. No
optimistic client summaries. Validation failure → `{ok:false, blockers:[{code,label,field_ref,
section_ref}]}` → tab badge + field focus (PR-16).

**Conflict echo (implemented for refreshed browser clients):** refreshed editors carry the
`source_of_truth_version` they edited from. When a non-empty value is supplied, the server rejects a
mismatch with **409 + fresh item**, preserving the shipped multi-session browser flow. The
compatibility endpoint contract still permits omission or an empty value; direct callers that do so
are not protected by this guard.

**Interaction rules:** editor **Save** = save-one; step-level button becomes **Continue** (validate +
navigate) — one button never does both. Cancel restores the editor from the last-saved server payload,
touching nothing else. Dirty state = serialized-snapshot diff + `beforeunload` + in-app nav guard (new
small utility in `studio.js`, PR-12). The refreshed browser paths use only the single-item contracts.
Compatibility whole-list HTTP routes remain callable for existing integrations and non-focused
archetype flows, but no focused editor calls them.

**Accepted PR-24 deviation:** PR-24 removes every refreshed-browser caller rather than deleting the
whole-list HTTP endpoints themselves. The routes remain compatibility APIs only, not supported UI
paths or an extension of the focused-editor contract; deleting them requires a separately versioned
API-compatibility decision.

### 1.4 Deterministic seed patch — P5, locked L2/L3

- **Parsing source (only):** the existing server-side inspectors —
  `POST /upstream/edge-contract/inspect`, `/upstream/edge-contract/file-inspect`,
  `POST /downstream/edge-contract/inspect`, `/downstream/edge-contract/file-inspect`
  (`edge_contract_inspector.py`, `edge_contract_file_inspector.py` — already DTD/entity-rejecting).
  **No browser `DOMParser`** — at most a non-authoritative preview, and not in v1.
- **Patch semantics:** inspector response → a review sheet of rows
  `{target_field, proposed_value, basis, state}`:
  - *pre-checked* only when **exact raw-name** match, or **normalized** (case / snake↔camel) match with
    exactly one source and one target remaining;
  - *collision* (multiple normalized candidates) → row shown unchecked + labelled, never pre-selected;
  - *no match* → honest "left blank" row;
  - **Apply writes only checked rows into EMPTY fields** — never overwrites non-empty (to change a
    filled field the user edits it directly);
  - every applied value renders with its `DERIVED` chip + basis; provenance is **recomputed, never
    persisted**.
- **Migration, not addition (L3):** the existing confirm-then-replace seed handlers in
  `step2_upstream.html` / the Step-5 template were replaced by the patch sheet and removed in PR-24.
  One page never exposes both seeding behaviours.

### 1.5 Design tokens + accessibility contract — D1 final values

Land in `studio.css :root` (PR-02), inert until applied:

```css
/* zone tints — by ROLE, never by family (D1 merged: shared palette @ moderate intensity) */
--zone-scan:#eaf0f8;  --zone-editor:#ffffff;  --zone-derived:#f3ecfd; --zone-derived-line:#ddd0f2;
--zone-attn:#fdf0d8;  --zone-attn-line:#eccf97;  --zone-ready:#e8f2f2;
/* family accents — element-level ONLY (monogram tile, 3px left border, ribbon, legend) */
--fam-rest:#0d9488; --fam-fixed:#15803d; --fam-csv:#4f46e5; --fam-xml:#b45309;
--fam-soap:#1e3a5f; --fam-staging:#475569;
```

**Rules:** family never tints a panel; zone never colours an element accent; **selection > zone >
default**. **A11y checklist** (applies per touched surface; acceptance gate in PR-24a, except the
vocalization half of item 7 — see §7.2):
contrast ≥ 4.5:1 for text on every zone · every family/state/provenance signal carries a text label or
`aria-label` (monograms, dots, chips) · error ≠ red-only · visible focus states · keyboard path through
board rows (arrow/enter to open) · the sub-1200px full-page focus fallback uses normal page focus,
preserves visible focus, restores route/back state, and honours the dirty guard · SR announcement on
save success/failure.

**Item 7 — verification split (§7.2, 2026-07-25).** The requirement is **retained in full**; only its
verification splits, and the halves land at different gates:
- **Structural — binding at PR-24a, test-enforced.** Every refreshed save surface exposes a correctly
  roled live region (`role="status" aria-live="polite"`, or `role="alert"` `aria-live="assertive"` for
  conflict recovery) **and** routes both its success and its failure text into that region. Enforced by
  `tests/test_pr24a_a11y_gate.py` — the region attributes *and* the writer→region binding, so
  re-pointing a writer at another id fails the gate.
- **Vocalization — A11y-01, mandatory pre-release.** Observing a screen reader *speak* the
  announcement is lifted out of the PR-24 merge gate, but it is **not** an open-ended follow-up: it
  must complete before the first release, version tag, or promoted demo baseline that ships the
  refresh default-on. Acceptance, ownership, and blocking behaviour are specified in §7.2.

  **Sequencing status:** this is the historical §7.2 rule. The revised §7.3 policy remains proposed
  until the Studio and Engine/Suite amendments are independently reviewed and merged. Once active,
  A11y-01 alone no longer blocks source publication, internal baselines/tags, public releases, or
  promoted demos; it remains an open, Studio-owned requirement.

Correct ARIA is **not** equivalent to observed speech: vocalization depends on Safari/VoiceOver
behaviour *and* on how Studio changes region visibility, content, and timing.

**Measured-contrast reconciliation** (B1 design-system pass — `design-assets/design-system/`; contrast
independently reproduced by Codex + ChatGPT-Pro). Three findings, with status:
- **(a) muted text on tinted zones** — shipped `--muted #5e718f` = 4.30–4.40:1 on the zone tints (under
  AA 4.5; 4.96:1 on white). **Shipped in PR-06:** `--muted-on-tint #546580` (≥5.1:1 on all four tints) +
  a scoped `.uxr-zone-* .text-muted` override; enforced by `tests/test_family_zone_skin.py`.
- **(b) REST monogram tile** — white on `--fam-rest #0d9488` = 3.74:1 (the other five families pass
  ≥5:1). **Shipped in PR-06:** the tile *fill* darkened to `#0b8277` (white → 4.69:1), tile-use-only; the
  locked `--fam-rest` token is untouched (accent uses — 3px border, ribbon, legend — unaffected);
  enforced by `tests/test_family_zone_skin.py`.
- **(c) soft-chip text** — ready-on-soft 4.46 · warn-on-soft 4.49 · draft-muted 3.99. **Shipped in
  PR-11 and test-enforced:** chip text was nudged one step darker (ready `#0f6a32` · warn `#96450a` ·
  draft `#4f6075`); no hue shift. Enforced by `tests/test_rail_step2_chips.py`; PR-24a re-verifies the
  result without reopening implementation ownership.

### 1.6 Template renames — L15, first PR

`app/templates/step4_downstream.html` → **`step5_downstream.html`** and
`app/templates/step5_handoffs.html` → **`step4_handoffs.html`** (files currently swapped vs displayed
order — confirmed in both review passes). Update render calls in `app/routes/downstream.py` /
`handoffs.py` + any test references. Done first so every later PR edits truthfully-named files.

---

## 2. The PR plan

Sizing: **S** < ~150 changed lines · **M** ~150–400 · **L** > 400. **26 active PRs**: the prior
26-PR plan - 1 retired PR-18 + 1 added PR-24a = 26 (PR-09a was added per R2; PR-17a was added
post-freeze, same shape as PR-09a — see §2 Phase 2b/2c). Merge-together candidates are marked ⊕
(collapsing them lands ~20, within the §12.4 estimate).

### Phase 0 — foundations (5 PRs; no visible change)

| ID | Title | Size | Files (primary) |
|---|---|---|---|
| **PR-01** ⊕ | `[CHORE]` Template naming rename (§1.6) | S | 2 templates (git mv), `routes/downstream.py`, `routes/handoffs.py`, test refs |
| **PR-02** ⊕ | `[FEATURE]` Feature flag + design tokens (§1.1, §1.5) | S | `nav_context.py`, `base.html`, `studio.css` |
| **PR-03** | `[FEATURE]` `ReadinessItem` adapter + parity & round-trip tests (§1.2) | M | `services/readiness_view.py` (new), `tests/test_readiness_view.py` (new) |
| **PR-04** | `[FEATURE]` Handoff + entity readiness producers (§1.2) | M | `readiness_view.py`, tests |
| **PR-05** | `[CHORE]` XML-security acceptance tests on the *existing* inspect endpoints | S–M | `tests/test_edge_contract_inspector_security.py` (new), extends `test_edge_contract_file_inspection.py` |

- **PR-01 acceptance (R3):** rendered output byte-identical; full suite green; **no `app/` or `tests/`
  runtime reference to the old template names** (the two route render calls `downstream.py:116` /
  `handoffs.py:62` + any test path assumptions). **Historical docs may retain the old names** (review /
  proposal docs and `docs/staged-downstream-future-design-review.md` intentionally do) — scope the grep to
  runtime, not the repo.
- **PR-02 acceptance:** flag off ⇒ zero DOM diff (marker test, §3.1); flag on ⇒ only `body.ux-refresh` differs.
- **PR-03 acceptance:** parity rule green (§1.2); service-level round-trip green (§3.2); no UI consumption yet.
- **PR-04 acceptance:** handoff "Review DDL"-style states + entity missing-key state emit correct
  `blockers[].section_ref/deep_link`; parity suite still green (new kinds never flip `is_exportable()`
  semantics for contracts).
- **PR-05 acceptance:** XXE/DTD payloads rejected deterministically; `../`/absolute-path artifacts refused;
  oversized/deep documents produce bounded deterministic errors. **Failures found = separate `[FIX]` PRs,
  never bundled.**

### Phase 1 — flag-gated compression (7 PRs; biggest visible delta, zero save-model risk)

**Phase-wide constraint (locked L6):** boards are **collapse-only** — every legacy card stays in the DOM
(visually collapsed); the wholesale `saveAll()` flows are untouched. This is what makes Phase 1 riskless.

| ID | Title | Size | Files (primary) |
|---|---|---|---|
| **PR-06** ⊕ | `[FEATURE]` Family + zone skin, Steps 2–5 | M | `step2_upstream.html`, `step5_downstream.html`, `step4_handoffs.html`, `studio.css` |
| **PR-07** | `[FEATURE]` Step 5 triage board (collapse-only) — mock: `step5-downstream-contract-board` (board half) | L | `step5_downstream.html`, page JS, `studio.css` |
| **PR-08** | `[FEATURE]` Step 4 handoff board (collapse-only) — mock: `step4-handoff-board` (board half) | M | `step4_handoffs.html` |
| **PR-09a** | `[CHORE]` **Step 3 test backfill (prerequisite, R2)** — route-render snapshots of Step 3 in representative states + a minimal jsdom harness (none exists today) or documented static invariants | M | `tests/test_step3_render_snapshots.py` (new), test harness |
| **PR-09** | `[FEATURE]` Step 3 lens part 1: behaviour-identical view-model extraction (**gated by PR-09a**) | L | `step3_entities.js` (refactor only) |
| **PR-10** | `[FEATURE]` Step 3 lens part 2: exceptions-first UI — mock: `step3-identity-role-lens` | L | `step3_entities.html`, `step3_entities.js` |
| **PR-11** ⊕ | `[FEATURE]` Rail count chips + Step 2 readiness/capability chips + legend | S–M | `nav_context.py`, `base.html`, `step2_upstream.html` |

- **PR-06:** monogram tiles + 3px family accents + tinted group headers + `--zone-scan` boards +
  `--zone-ready` stat strips; family label always adjacent to colour. No structural change.
- **PR-07:** one summary row per card (name · artifact path · family fact chip · coverage · capability
  icon+legend · status pill · **inline top-blocker line**) rendered **server-side from
  `items_for_step()`**; blocked-first sections; status/type filter chips; ambient stats strip;
  expand-one-at-a-time reveals the untouched legacy card. Acceptance: with 5+ interfaces the page shows
  all rows on one screen; expanded card saves exactly as before; readiness pills match Step-7/export.
- **PR-08:** same discipline; "Review DDL" state from the PR-04 producer.
- **PR-09a (R2 — mandatory prerequisite):** the current tests mostly assert script presence + strings +
  server endpoints, and the repo has **no jsdom/playwright harness** — not enough to gate a 1,881-line
  behaviour-identical refactor. Backfill first: route-render snapshots of Step 3 in representative states
  (empty · single-entity · many-fields · roles-assigned · KA-review-open), plus either a minimal jsdom
  harness or a documented set of static invariants the refactor must preserve. Acceptance: the snapshots
  exist and are green on the pre-refactor code.
- **PR-09:** pure refactor — extract `step3_entities.js` rendering into a projection over one page
  view-model. Acceptance: **PR-09a snapshots byte-identical before/after**; flag state irrelevant (no
  visual change); existing entity tests green. *Highest-risk JS PR; it intentionally contains no feature —
  and it does not merge until PR-09a is in.*
- **PR-10:** entity cards · one persistence-identity picker + **impact strip** · assigned-roles-only
  table with Engine-behaviour column (data already server-side per the Fable pass:
  `identity_role_review` / `role_behavior_rows`) · **"N No Role Hidden" trust counter** (count from the
  view-model, not hand-summed) · filter cards (filters, never assignments) · show-all reveal · >50-field
  default-to-assigned+required + search · missing-key state (PR-04 blocker). Writes the exact same
  `/entities/save` + `/entities/identity-roles` payloads (assert in test).
- **PR-11:** `build_nav_context()` gains per-step `count`/`attention` from `step_counts()`. **A11y (B1
  finding c):** the readiness/capability chip text must clear AA on its soft fill — nudge one step darker
  (ready `#0f6a32` · warn `#96450a` · draft `#4f6075`; no hue shift), matching the shape+label rule for
  `count`/`attention` chips; test-enforced by `tests/test_rail_step2_chips.py` and re-verified by PR-24a.

### Phase 2a — focused authoring (5 PRs)

| ID | Title | Size | Files (primary) |
|---|---|---|---|
| **PR-12** | `[FEATURE]` Step 5 `?focus=` editor + `save-one` route + dirty-state utility — mock: `step5-downstream-contract-board` (editor half) | L | `routes/downstream.py`, `step5_downstream.html`, `studio.js` |
| **PR-13** | `[FEATURE]` Step 5 seed-patch migration (§1.4) — mock: editor "Deterministic seeds" panel | M–L | `step5_downstream.html`, page JS |
| **PR-14** | `[FEATURE]` Step 4 `?focus=` + `save-one` + three-block editor + DDL diff — mock: `step4-handoff-board` (editor half) | L | `routes/handoffs.py`, `step4_handoffs.html` |
| **PR-15** | `[FEATURE]` Step 2 focus alignment + `original_name` rename semantics + upstream seed patch | M | `routes/upstream.py`, `step2_upstream.html` |
| **PR-16** ⊕ | `[FEATURE]` Step-7 deep links + validation deep-linking (blockers → tab badge + field focus) | S–M | `step7_review.html`, editor JS |

- **PR-12:** GET `/downstream?focus=<name>` renders the focus mode (progressive same-template mode — not
  a separate route file); editor header/banner/tab-error-badges from `item()`; `POST
  /downstream/interface/save-one` per §1.3 (incl. rename semantics + five-surface response); dirty-state
  utility (snapshot/diff/`beforeunload`/nav-guard) lands in `studio.js`; **Save (editor) vs Continue
  (step) split**. Acceptance: G1 criteria L8, all five, each with a test; save-one of an *unchanged*
  item = project no-op (§3.2).
- **PR-13:** patch sheet consuming the existing downstream inspect endpoints; collision rules per §1.4;
  legacy confirm-replace handlers replaced under flag. Acceptance: patch never writes a non-empty field
  (test with pre-filled mapping); collision fixture never pre-checked; SOAP heavy sections move
  **markup-wholesale with field names/ids unchanged** + a payload-snapshot test proving the posted body
  is byte-identical to the legacy editor's for the same inputs.
- **PR-14:** three blocks — identity · staging columns (derived-vs-manual **recomputed** per §1.2, never
  stored) · entity→staging mappings with seed-from-entity; DDL before/after via the existing generate
  endpoint + saved `ddl_content`; **async DDL ⇒ Save shows a pending state**; entity-field context
  plumbed into the template (small read-only context addition — the template receives none today).
- **PR-15:** Step 2 gains the same focus shell; `/upstream/edge-contract/save` gains `original_name`
  (fixes the verified rename-duplicate hazard); upstream inspect endpoints feed the same patch sheet.
- **PR-16:** Step-7 advisories become `deep_link`s into the focused editors; save-one validation
  `blockers[]` map to tab badges + field focus.

### Phase 2b — split; Phase 2c modal retired (3 tracked IDs)

| ID | Title | Size |
|---|---|---|
| **PR-17a** | `[FIX]` **Step 4/5 focus-editor parity, a11y + split-readiness prerequisite** — a11y gaps (§3.6) closed on both focus editors, board/row-updater plumbing made split-ready but left inert (no `ux_split` consumer yet); no box-size change | S–M |
| **PR-17** | `[FEATURE]` Desktop split behind `EDGEFORGE_STUDIO_UX_SPLIT` (**gated by PR-17a**) — board stays visible left, focus editor right (≥ ~1200px); five-surface refresh wired end-to-end from the save-one response | M |
| **PR-18** | **RETIRED — ID retained for traceability.** The sub-1200px single-column full-page focus fallback shipped by PR-12, with its a11y gaps closed in PR-17a, is the supported narrow presentation. It uses standard page semantics and native browser-back without a focus trap; adding a modal would introduce a11y-risk surface to replace an already-proven path. Authorized by the [PR #232 amendment proposal](https://github.com/santosh-sh/EdgeForgeStudio/pull/232#issuecomment-5017078838) and [Codex §7 approval](https://github.com/santosh-sh/EdgeForgeStudio/pull/232#issuecomment-5051412430). | — |

- **PR-17a (prerequisite, added post-freeze — mirrors PR-09a's shape):** PR-17 proved materially
  bigger than its original single-PR "M" estimate once building started — the board and focus editor
  are mutually exclusive `{% if focus_name %}`/`{% elif %}` Jinja branches (the board is *absent from
  the DOM* in focus mode, not CSS-hidden), so making them coexist is a template restructure, and doing
  so surfaces latent defects the moment the board becomes visible alongside the editor (an a11y gap on
  Step 4's `#save-status`, a missing accessible name on the focus-editor region, a stat-strip updater
  that only ever patched one of what would become two simultaneous strips, and a board-row-hide loop
  that would re-hide the just-focused card once it runs alongside the editor). Split so the defect
  fixes and split-readiness plumbing land first, with **no split consumer and no box-size change**,
  and PR-17 then does the layout on top of solid ground. Acceptance: both-flag-state suite green;
  flag-off byte-identity re-verified against `origin/main`; the two Phase-2a single-panel invariant
  tests (`test_step5_save_one.py`/`test_step4_focus_editor.py`) stay green unchanged.
- **PR-17:** the first consumer of `ux_split` (`nav_context.py:156`) — introduces the two-column
  wrapper (board left, focus editor right, `@media (min-width: 1200px)`) in both step templates,
  suppresses the focus editor's own duplicate ambient stat strip in favour of the board's, reclaims
  the previously-unreachable `.uxr-board-row.is-editing` treatment, and is the first render where
  PR-17a's `uxrUpdateBoardRowFromSaved` row-updater and un-early-returned board wiring actually execute
  (both were inert groundwork until now). Acceptance: `ux_split` off ⇒ focus mode byte-identical to
  today (board absent from the DOM, not just hidden); `ux_split` on + focus ⇒ board and editor both
  render, exactly one ambient strip, the edited row is marked, board Edit links/filters/roving nav
  work, and a save-one response updates the row's name/state/family/badge/`href` live, including
  through a rename.
- **PR-18 (retired):** no narrow-screen modal is built. Below the split breakpoint, the supported
  presentation remains the full-page focus route. The initiative-wide a11y acceptance responsibility
  formerly attached to PR-18 moves intact to PR-24a; only modal-specific focus-trap/restore and
  `Esc`-modal arbitration retire.

### Phase 3 — power & review (3 PRs)

| ID | Title | Size | Files (primary) |
|---|---|---|---|
| **PR-19** | `[FEATURE]` Step 6 rules board + field-grouped editor — mock: `step6-rules-board` (final; supersedes `step6-rules-board-sketch`) | L | `step6_rules.html`, `routes/rules.py`, `readiness_view.py` (`rule_set` kind) |
| **PR-20** ⊕ | `[FEATURE]` Allowed-values paste bulk action (preview-before-apply + undo-last) | S | `step6_rules.html`, page JS |
| **PR-21** | `[FEATURE]` Step 7 Trace Lens — mock: `step7-trace-lens` | M | `step7_review.html` |

- **PR-19:** board item = the **entity rule-set** (locked L9); rows carry rule count · fields covered ·
  provenance chip counts · advisory count · state; field-grouped editable cards; **advisory conflicts =
  dashed read-only strip** (state `warning`, never blocking — today's posture, unchanged); cross-entity
  prerequisites made explicit (`via customerId ✓` / "add cross-entity-exists first" — logic exists in
  `refreshCrossEntityRuleRow()`); Legacy Notes stays one quiet section; right rail reads the same
  view-model. Save: `POST /rules/save-one` scoped to one entity's rule-set, server-validating
  cross-entity prerequisites across the session. **Matrix Lite: OUT** (locked L10) — P9 acceptance
  criteria remain in `proposal-final.md` for any future revisit.
- **PR-21:** entity picker → upstream | canonical | downstream columns from session links
  (`entity_name` on interfaces + handoffs); pills from the view-model; **unrelated-blockers strip**
  always visible; `Fix ↗` uses the Phase-2a deep links.

### Phase 4 + Phase 5 — parity, polish & acceptance (4 PRs)

| ID | Title | Size |
|---|---|---|
| **PR-22** | `[FEATURE]` Step 2 full board parity (sections/filters) + surface existing seed actions | S–M |
| **PR-23** | `[FEATURE]` Step 7/8 package-story polish — Step-7 summary on tokens/zones; Step-8 artifact lists get family tokens; all counts from the view-model | S–M |
| **PR-24a** | `[CHORE]` **A11y acceptance gate** — after PR-23, verify the §1.5 checklist on every refreshed surface (Steps 2/3/4/5/6/7) and record keyboard-only + screen-reader walkthroughs of the Step-5 focus flow in both the desktop split and sub-1200px full-page fallback. Fix every defect found within PR-24a. **Status (§7.2):** structural, keyboard-only, and VoiceOver *navigation* acceptance are complete and test-enforced — including the writer→live-region binding for every refreshed save surface. Observing announcements **spoken** is *not* claimed as passed; it is scoped out to **A11y-01**, a mandatory pre-release gate. PR-24 is unblocked once the strengthened structural gate is green. | S |
| **PR-24** | `[CHORE]` **Flag flip + legacy removal + version bump** — default ON; delete frozen legacy blocks + dead handlers (incl. legacy wholesale saves for focused steps + old seed handlers); refresh golden markers; CHANGELOG + Studio minor version bump. **Gated on the §4.2 flip checklist.** | M |

The PR-24a row records the original §7.2 sequencing. The proposed §7.3 supersession is non-operative
until the Studio and Engine/Suite amendments are independently reviewed and merged; once active,
A11y-01 alone no longer gates publication, baselines/tags, releases, or promoted demos.

### 2.1 Dependency graph

```
PR-01 ─┬─ PR-02 ─── PR-06 ─┬─ PR-07 ─── PR-12 ─┬─ PR-13
       │                   ├─ PR-08 ─── PR-14  ├─ PR-16 ── PR-17a ── PR-17
       │                   │        ╲(R4)╱     └─ PR-15
       │                   │       PR-12 ───────┘   (PR-14 needs PR-12's dirty-state utility)
       └─ PR-03 ─┬─ PR-04 ─┤       PR-03 ── PR-11
                 │         ├─ PR-09a ─ PR-09 ─ PR-10
                 └─ PR-05  ┘
Phase-2a stable (12–16) ──── PR-19 ── PR-20
PR-12/14/15 (+16) ────────── PR-21
Phases 0–3 complete ──────── PR-22 ── PR-23 ── PR-24a ── PR-24
```
Explicit edges (per Codex): **PR-12 → PR-14** (R4 — PR-14's focus editor needs the dirty-state utility
PR-12 lands in `studio.js`) · **PR-03 → PR-11** (PR-11 uses `step_counts()`) · **PR-09a → PR-09** (R2) ·
PR-07/PR-08 need PR-03/04's data flow even though their file edits are separate.

Parallel lanes for two build agents: **(A)** 07→12→13 (Step 5 spine) and **(B)** 09a→09→10 (Step 3) then
08→14 (Step 4). They touch disjoint *templates* after Phase 0, **but lane B's PR-14 waits on lane A's
PR-12** for the shared dirty-state utility. To make the lanes fully independent, **extract the
dirty-state + focus-shell utility into its own small `[FEATURE]` PR (studio.js) before PR-12/PR-14** and
have both depend on it — recommended if two agents run concurrently. Shared-file changes (`studio.css`,
`base.html`, `nav_context.py`, `studio.js`) are serialized when they touch shared behaviour.

---

## 3. Test strategy (cross-cutting)

### 3.1 Retired-flag compatibility tests
PR-24 replaces both-state rollout CI with compatibility assertions that unset, false, and true values
for the retired environment variables render the same refreshed surface. **Correct helper locations
(R5):** the smoke package is **`tests/smoke/`**; shared session helpers are
**`tests/session_helpers.py`** (repo root of tests); smoke-only utilities are
**`tests/smoke/_shared.py`** — there is no `tests/smoke/session_helpers.py`. The pre-flip both-state
results remain recorded in the PR-24 evidence; post-flip tests enforce that old deployment settings
cannot resurrect removed legacy markup.

### 3.2 Project-file round-trip (proposal §12.2 — merge-blocking)
- **Service-level (PR-03):** fixture project → load → save → load → deep-equal (additive-only keys
  tolerated, none required). **Fixtures must be created (R5):** `tests/fixtures/` today holds only
  `parcel-response-upload.yaml`; Action-5 adds explicit project-JSON fixtures **or** reuses the
  programmatic rich-session builders already in `tests/smoke/_shared.py` (`_shared.py:136-240+`).
- **Save-one no-op (PR-12+):** `save-one` with an unchanged item payload ⇒ project state diff is
  empty; a changed item ⇒ diff confined to that item.
- **Legacy compatibility:** a pre-refresh project fixture loads + renders + exports identically in both
  flag states.

### 3.3 Readiness parity (PR-03 onward, every PR)
`export_blocking` ⇔ `package_writer` blocking; `is_exportable()` ⇔ no `blocks_export` items; every UI
pill/count in the refreshed surfaces is rendered from `readiness_view` output (assert no duplicate
client-side computation by code review + a grep-guard test for known legacy count helpers).

### 3.4 Security (PR-05, then standing)
The §1.4 inspectors are in the standing suite: XXE/DTD rejection · path traversal refusal ·
depth/size bounds · deterministic error shapes. Any new helper endpoint (none planned in v1) inherits
the same tests before merge.

### 3.5 Five-surface refresh + payload snapshots
- Save-one response contract test (shape of `readiness`/`step_counts`/`rail`).
- DOM smoke: after a save that changes state, board row pill + stats + rail chip all reflect the
  response payload.
- **Payload snapshot** (PR-12/13/14/15): for identical inputs, the focused editor posts a body
  byte-identical to the legacy editor's (the "forms moved verbatim" guarantee, made testable).

### 3.6 Accessibility
§1.5 checklist reviewed per surface PR. PR-24a is the acceptance gate across Steps 2/3/4/5/6/7 — but
**not** the final a11y verification: §7.2 scopes the vocalization half of item 7 to **A11y-01**, a
mandatory pre-release gate. PR-24a records keyboard-only + screen-reader **navigation** walkthroughs
of the Step-5 focus flow in both presentations: the desktop split and the sub-1200px full-page
fallback. The narrow fallback uses normal page focus,
visible focus, route/back restoration, the dirty guard, and save success/failure announcements; it has
no modal focus trap or `Esc` arbitration.

**Completed vs deferred (§7.2, 2026-07-25).** PR-24a **completed**: the keyboard-only walkthrough in
both presentations; the VoiceOver *navigation* walkthrough (VoiceOver entered the named Step-5 surface
and identified the Save control in both presentations); and the structural save-announcement contract,
now test-enforced for both the live-region attributes and the writer→region binding on every refreshed
save surface. PR-24a **did not complete**, and does not claim, the observation of announcements being
**spoken** for a successful and a validation-failing save. That is **A11y-01**, a mandatory pre-release
gate (§7.2) — deferred out of the PR-24 merge gate, not out of the release.

This paragraph records the original §7.2 boundary. See §7.3 for the proposed coordinated exception:
after activation A11y-01 remains an open known limitation but alone no longer blocks source
publication, internal baselines/tags, public releases, or promoted demos.

---

## 4. Rollout & versioning (proposal §12.3)

### 4.1 Flag lifecycle
`EDGEFORGE_STUDIO_UX_REFRESH` was default-OFF through Phases 0–5. PR-24 retires the switch and removes
the legacy render paths: the refreshed UX is the only presentation. `EDGEFORGE_STUDIO_UX_SPLIT` is
retired at the same boundary; the split is standard at 1200px and wider, with the supported full-page
focus fallback below the breakpoint.

### 4.2 Flip checklist (gates PR-24)

Completed evidence: [`pr24-pre-flip-evidence.md`](pr24-pre-flip-evidence.md).

- [x] All **non-retired** PRs through PR-23 (incl. PR-09a, PR-17a) merged; both-flag-state CI green;
      then PR-24a passed
- [x] Round-trip + parity + security suites green
- [x] PR-24a's a11y checklist passed on Steps 2/3/4/5/6/7, including the recorded Step-5
      **keyboard-only** walkthrough and the **VoiceOver navigation** walkthrough at desktop split and
      sub-1200px full-page fallback, and the **strengthened structural save-announcement gate** green
      (live-region attributes *and* writer→region binding for every refreshed save surface)
- [x] **A11y-01 is correctly retained as OPEN outside the PR-24 merge gate** (§7.2) — observing
      announcements **spoken** is a **mandatory pre-release** gate: it must complete before the first
      release, version tag, or promoted demo baseline shipping the refresh default-on

The checked item above is the historical PR-24 flip result. Section 7.3 does not alter that evidence;
its revised policy becomes operative only after independent exact-head review and merge of the Studio
and companion Engine/Suite amendments. Once active, A11y-01 alone no longer blocks source publication,
internal baselines/tags, public releases, or promoted demos.
- [x] Manual end-to-end: the Action-2 DDA sample project driven through the refreshed UX —
  author → readiness → export → generated app builds (`mvn -q -DskipTests package`)
- [x] Old-project fixture loads/exports identically (§3.2)
- [x] Maintainer demo sign-off — completed August 9, 2026, against PR #280 at `8a3c63c`; the historical
      project → Step 3 preservation → export/validate → generate/build/run walkthrough is recorded in
      [`pr24-pre-flip-evidence.md`](pr24-pre-flip-evidence.md)
- [x] `v4.1.x` demo baseline tag confirmed reproducible (checkout + run)

### 4.3 Fallbacks (always two)
1. **Pinned tag:** current Engine `v4.1.1` + Studio 4.1.x release stay the demo baseline until the flip.
2. **Clean revert:** after PR-24 there is no hidden legacy runtime path. A post-flip regression is
   handled by reverting the single PR while the pinned baseline remains available (§0.6).

Version bump: Studio **minor** bump at PR-24 (UX overhaul, zero manifest/contract change), CHANGELOG
entry summarising phases; Engine untouched.

---

## 5. Risks & effort flags

| # | Risk | Where | Mitigation |
|---|---|---|---|
| 1 | SOAP editor "verbatim move" is DOM surgery (~20 fields + 2 dynamic mapping-row builders) | PR-12/13 | Move markup wholesale, keep field names/ids; payload-snapshot test (§3.5); budget L |
| 2 | `step3_entities.js` re-projection (1,881 lines) regresses KA/filter/overlay behaviour | PR-09/10 | Two-PR split; PR-09 is behaviour-identical-only with existing tests as the gate |
| 3 | Two markup paths drift while the flag exists | Phases 1–5 | Legacy blocks frozen (§0.2); marker tests; PR-24 deletes them |
| 4 | Multi-session conflict safety across focused saves | Phase 2a+ | Shipped browser paths send `source_of_truth_version` and receive 409 on mismatch; compatibility callers may omit the field and are outside that guard (§1.3) |
| 5 | Handoff DDL round-trip is async; Save during pending regenerate | PR-14 | Explicit pending state; Save disabled until DDL settles or user confirms manual mode |
| 6 | Rules save-one vs cross-entity prerequisites (item = entity rule-set, deps span entities) | PR-19 | Server-side session-wide prerequisite validation in `save-one`; explicit prerequisite UI |
| 7 | Stale CSS after token changes (browser cache) | PR-02+ | Verify/add static asset version query param when tokens land |
| 8 | Estimate drift — 26 active PRs remains the top of the §12.4 range after -1 retired PR-18 +1 PR-24a = 26 | all | ⊕-marked merge candidates collapse to ~20 without scope change |

---

## 6. Out of scope (unchanged from the freeze)

Kafka-router + REST-passthrough (capture→apply follow-on tracks, post-freeze, parallel) · KA Workspace +
accept/edit/reject (dedicated pass; **build gated on the KA production-readiness decision**; KA-OFF
cleanliness untouchable) · Matrix Lite (P9 criteria preserved; revisit post-v1) · standalone spatial
Contract Map (Trace Lens first) · any Engine change · any manifest-schema change.

## 7. Handoff to Action-5

The build thread executes every non-retired PR through PR-23 (incl. PR-09a, PR-17a), then PR-24a →
PR-24, in dependency order (parallel lanes per §2.1), one doc-PR-ID per GitHub PR, pasting the §0.6 DoD
into each description. Design questions discovered mid-build come back to this thread as comments on
PR #232 — **this doc is amended first, then built**; the doc and the build never diverge silently.
Review gates: normal per-PR review (build-thread conventions) + the §4.2 checklist before PR-24. On
PR-24 merge, the initiative closes Action-5 and the §11 follow-on tracks (Kafka / passthrough / KA)
may start from their scoping briefs.

### 7.1 Approved amendment — PR-18 retirement + PR-24a a11y gate (2026-07-22)

Authorized by the [PR #232 amendment proposal](https://github.com/santosh-sh/EdgeForgeStudio/pull/232#issuecomment-5017078838)
and the [Codex §7 decision review + approval](https://github.com/santosh-sh/EdgeForgeStudio/pull/232#issuecomment-5051412430):

- PR-18 retires as a UI slice; its ID remains reserved for traceability.
- The initiative-wide a11y requirement survives and moves to PR-24a. Only modal-specific
  focus-trap/restore and `Esc`-modal arbitration retire.
- The supported narrow behavior is the sub-1200px single-column full-page focus route, whose standard
  semantics, native browser-back, dirty guard, and visible focus make it the more accessible
  presentation than adding a modal.
- PR-24a runs after PR-23 and before PR-24; the execution tail is PR-23 → PR-24a → PR-24.
- The plan remains **26 PRs**: 26 - 1 retired PR-18 + 1 added PR-24a = 26. The §2 sizing note and
  §5 Risk 8 therefore remain reconciled at 26.

### 7.2 Approved amendment — A11y-01: SR save-announcement verification split (2026-07-25)

> **Historical sequencing notice:** §7.2 remains the operative Suite rule until the proposed §7.3
> policy is independently reviewed and merged in both the Studio and Engine/Suite sources of truth.
> After that coordinated activation, A11y-01 remains open but alone no longer blocks source
> publication, internal baselines/tags, public releases, or promoted demos.

Authorized by the [PR #232 amendment proposal](https://github.com/santosh-sh/EdgeForgeStudio/pull/232#issuecomment-5078835098)
and the [Codex §7 decision review — approve with changes](https://github.com/santosh-sh/EdgeForgeStudio/pull/232#issuecomment-5079242179).
This is a **controlled sequencing exception**, not a finding that spoken feedback stopped mattering.

**The requirement is retained.** §1.5 item 7 ("SR announcement on save success/failure") is not
retired, narrowed in product scope, or downgraded. Only its *verification* splits:

- **Structural — binding at PR-24a.** Every refreshed save surface must expose a correctly roled live
  region **and** route both success and failure text into it. `tests/test_pr24a_a11y_gate.py` enforces
  the region attributes, the flag-off absence, *and* the writer→region binding. Approval condition 1:
  before PR-24, re-pointing any save writer at another id must fail the gate. (Previously only Step 2
  pinned its writers, so re-pointing every Step-3 Phase-1 writer left the gate green — that hole is
  what condition 1 closes.)
- **Vocalization — A11y-01, mandatory pre-release.** Lifted out of the PR-24 *merge* gate only.

**A11y-01 — acceptance (approval condition 2).** Not an open-ended follow-up. It must complete before
the **first release, version tag, or promoted demo baseline** containing the default-on refresh:
- native Safari + macOS VoiceOver with its Caption Panel;
- one **successful** save and one **validation-failing** save;
- in **both** the desktop split and the sub-1200px full-page presentation;
- the **exact announced text recorded** in `pr24a-a11y-walkthrough.md`;
- **any failed or missing announcement blocks that release** and returns to Studio for correction.

Owner: Studio build thread (same owner as PR-24a). Tracked as build-thread item #57.

**Why the split is acceptable but not equivalent.** Executed browser evidence showed Step-3 success
*and* validation-failure text populating `role="status" aria-live="polite"` regions, which materially
reduces the DOM/data-flow risk. It does not prove speech: vocalization depends on Safari/VoiceOver
behaviour *and* on how Studio changes region visibility, content, and timing. The unreliable VoiceOver
observation in PR-24a (#273) is precisely why correct ARIA is not accepted as a substitute.

**Scope unchanged:** the SR requirement is not retired · PR count remains **26** · ownership unchanged
· the PR-23 → PR-24a → PR-24 tail remains · flag-off behaviour stays frozen · no manifest,
project-schema, Engine, KA/KS, or generated-contract surface changes.

<a id="a11y-01-v5-baseline-deferral"></a>

### 7.3 Proposed coordinated amendment — A11y-01 open known limitation (revised 2026-09-21)

> **Status clarification, 2026-10-10:** the activation condition recorded below
> has since been fulfilled: independently reviewed Studio #299 merged as
> `56354ce184729c345aa6e4b66a354342c5b66bae` and Engine #313 as
> `d8f50c0edd2d9ec27e7def512455b2881a3c97fe`. The original proposal/condition text
> is preserved as decision history. A11y-01 remains open with the same evidence,
> acceptance cases and audience-accessible disclosure requirement. This note
> does not authorize publication or retire any other gate.

The 2026-09-13 proposal was recorded through the
[original maintainer decision](https://github.com/santosh-sh/EdgeForgeStudio/pull/299#issuecomment-5658690045)
and [independent review](https://github.com/santosh-sh/EdgeForgeStudio/pull/299#pullrequestreview-5193384579).
It would have exempted only the internal v5 baseline/tag while retaining a public-release and
promoted-demo block. The maintainer later revised that direction in the
[current decision record](https://github.com/santosh-sh/EdgeForgeStudio/pull/299#issuecomment-5770467239):
A11y-01 remains an accessibility requirement and open known limitation, but A11y-01 alone must no
longer block source publication, internal baselines/tags, public releases, or promoted demos. The
known impact, reproduction, exact acceptance text, and contribution invitation are recorded in
[Studio issue #302](https://github.com/santosh-sh/EdgeForgeStudio/issues/302). The issue is
publication-ready, but Studio is currently private, so outside contributors cannot access it.

This revised cross-repository policy is **proposed and non-operative** until this Studio amendment and
the [companion Engine/Suite PR #313](https://github.com/santosh-sh/EdgeForge/pull/313) each receive an
independent exact-head review and both merge. An approval of the earlier 2026-09-13 policy is not
carried forward to a changed SHA or to this revised policy. Until coordinated activation, the existing
merged policy remains authoritative.

Once coordinated and active, this amendment supersedes §7.2 only as to blocking consequences:
A11y-01 alone does not block source publication, internal baselines/tags, public releases, or promoted
demos. Section 7.2 remains above as historical decision evidence. Its product requirement, four-case
native Safari/VoiceOver acceptance contract, exact announcement expectations, and Studio ownership
remain unchanged.

If Studio remains private during an authorized public release or promoted demo, the release or demo
materials must carry an audience-accessible notice that A11y-01 is an open known limitation. The
notice must explain its impact (a successful Step 5 save may complete visually without VoiceOver
announcing the outcome) and how to reproduce it (in native Safari, enable VoiceOver and its Caption
Panel, open the desktop Step 5 downstream editor, and save a valid interface). Link issue #302 as a
public contribution path only once that issue is actually public. This disclosure requirement does
not require A11y-01 to be completed before the release or demo.

The controlled observation against Studio
`d23d99f480e242291750724d192875e53b37e85f` produced this evidence:

- **Desktop split, successful save — FAIL.** The save completed successfully in the visible UI.
  VoiceOver announced button-activation guidance but did not announce the save outcome. The exact
  Caption Panel transcript was not captured, so none is inferred or borrowed from earlier evidence.
- **Desktop split, validation-failing save — NOT RUN.**
- **Sub-1200px full page, successful save — NOT RUN.**
- **Sub-1200px full page, validation-failing save — NOT RUN.**

A11y-01 therefore remains open and Studio-owned. Completion still requires all four §7.2 native
observations to pass, including the complete blocker text for validation failures. The focused
structural run recorded `74 passed`; that automated evidence establishes neither native speech nor
A11y-01 completion. Existing structural, keyboard-only, screen-reader navigation, live-region, and
writer-to-region requirements remain binding.

After coordinated activation, A11y-01 remains an open known limitation and Studio retains
responsibility for closeout. Contributor help is welcome; issue #302 becomes an external contribution
path only when it is public. Completion still requires all four native observations in §7.2 to pass.
This exception applies only to A11y-01's native spoken save-outcome verification: it does not convert failed or unrun
evidence into a pass, narrow or waive the acceptance contract, weaken structural, keyboard-only,
screen-reader navigation, live-region, or writer-to-region requirements, waive any other
accessibility, security, correctness, CI, or Suite obligation, claim accessibility compliance or
certification, or itself authorize any publication, baseline, tag, release, or promoted demo.

## 8. Action-5 execution model (subscription-native; runs in a Studio build thread)

Chosen over the metered GitHub-Actions loop **for cost** — everything below runs on existing Claude +
Codex subscriptions (no OpenAI/Anthropic API meter, no Actions-minute spend). Full GitHub-Actions API
automation is deferred; revisit only if PR volume ever justifies the metered cost. **This loop runs in a
Studio-repo build thread, not the Engine/Suite design thread** (which owns this contract and handles
design amendments per §7).

**Roles:** Claude (Studio build thread) orchestrates the queue + reviews every PR + builds the mechanical
PRs (a **Sonnet** subagent builds, an **Opus** subagent reviews — model-diverse); **Codex** builds the
substantive/source-heavy PRs (pasted one at a time); a **human merges** (branch-protected — the only
gate automation never touches).

### 8.1 Per-PR ownership (agreed with Codex's buildability review)
| Builder | PRs |
|---|---|
| **Claude** (Sonnet build / Opus review) | PR-01, 02, 05, 06, 07, 08, 11, 16, 17, 20, 21, 23, 24a, 24 |
| **Codex** (pasted, one at a time) | PR-03, 04, **09a, 09, 10**, 12, 13, 14, 15, 19, 22 |

Notes: **PR-10** *(Codex's flag)* — looks frontend but touches `/entities/save` + identity-role payload
parity, so it is **Codex-built or Codex-reviewed regardless**. PR-07 may pull in Codex if the readiness
integration gets tricky. **PR-18 is retired. PR-22 was reassigned to Codex and shipped as #260.**
PR-24a is Claude-built as the a11y acceptance gate for everything except the vocalization half of
§1.5 item 7, which §7.2 scopes to **A11y-01** (a mandatory pre-release gate, same owner) — so PR-24a
is not the *last* a11y checkpoint before release. PR-24 (flag-flip + legacy removal) is
Claude-built **with a mandatory Codex review** (mechanical but risky). PR-05 is test-only for Claude
*unless* it surfaces failures → those become separate `[FIX]` PRs (Codex if source-heavy).

That ownership statement remains current. Its original sequencing remains operative until §7.3 is
independently reviewed and merged in both Studio and the Engine/Suite source of truth; after
activation, A11y-01 remains open but alone no longer blocks publication, baselines/tags, releases, or
promoted demos.

### 8.2 Review model — cross-vendor everywhere
- **Every PR** gets an **Opus** review against this contract before it's marked *ready-for-merge*.
- **Codex-built PRs:** the Opus review *is* the cross-vendor check.
- **Claude-built (Sonnet) PRs:** Opus review per-PR **+ a batched Codex review pass per phase** (Phase 0,
  1, 3-tail, 4-5) — restores cross-vendor scrutiny on the Claude-built set, batched to minimise pastes/cost.
  PR-10 + PR-24 get a Codex review regardless.

### 8.3 The loop (per PR)
`build` (per this contract, in an **isolated worktree**, flag-OFF behaviour preserved) → open/update the
PR + run the **required targeted tests** (broader suite at phase-tail) → `review` (§8.2) → `fix`
(**≤ 2–3 iterations**; cap then label `needs-human`) → CI-green + review-clean → label
`ready-for-human-merge` and **HALT** → human merges → advance the queue. **Stop on design ambiguity** →
back to the design thread; **this doc is amended first, then built** (§7).

### 8.4 Safety (unchanged, restated)
Three independent gates, not trust: per-PR **CI is merge-blocking** (both-flag-state + round-trip +
parity) · **branch protection** makes the human merge mandatory · every merge is **inert behind the
off-by-default flag**. Automation never has merge permission; one PR-slice per run; diff-scope guard
(files outside the PR's expected scope → stop).

> Public-tree note (2026-11-02): the fixture name above now points to an independently authored parser regression; the original dated review remains private history.
