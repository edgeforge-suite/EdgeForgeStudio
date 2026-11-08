# Codex Action-3 UX Refresh Proposal

Independent pass by Codex, grounded in the current Studio source and the Action-2 baseline. I did not read the Fable or ChatGPT Action-3 passes.

## Executive Thesis

Studio does not need a dramatic rebrand. It needs a change in information posture.

The current UI often renders authoring state as a stack of fully expanded forms. That is accurate, but it makes review feel like spelunking. The target state should make every long page work in two speeds:

1. A compact board for scan, compare, readiness, and navigation.
2. A focused editor for one contract, handoff, entity, or mapping at a time.

This keeps the suite stable: no manifest shape changes, no Engine changes, no KA/KS behavior changes, and no new frontend framework. It is mostly Jinja2 structure, CSS, and vanilla-JS orchestration over the same project/session model.

## Source Grounding

Real Studio source reviewed:

- `app/templates/step2_upstream.html`: Step 2 already has the better pattern. Loaded edge contracts render in a compact table, and the add form collapses into `details` when contracts exist.
- `app/templates/step4_downstream.html`: Step 5 renders downstream interfaces as always-expanded cards, then repeats readiness and saved specs in separate sections.
- `app/templates/step5_handoffs.html`: Step 4 renders each handoff as an always-expanded card with columns, DDL preview, manual DDL, and mappings inline.
- `app/templates/step3_entities.html`: Step 3 renders one identity-role `select` per field per entity. Most rows are "No role", but they occupy the same visual weight as meaningful role decisions.
- `app/static/css/studio.css`: Studio already has useful tokens and patterns: `step-section-card`, `review-summary-strip`, `disclosure-card`, `badge`, `alert`, shell rail, drawer, and modal styles.
- `app/static/js/studio.js` and `app/static/js/step3_entities.js`: vanilla-JS tab, drawer, modal, entity filtering, and Step 3 dynamic rendering are already available. No framework is required.

Baseline reviewed:

- `docs/studio-ux-refresh/baseline/current-state-walkthrough.html`: Action-2 visual baseline with 52 stills and 13 recordings.
- `docs/studio-ux-current-state-audit-2026-07.md`: companion audit, when present locally.

## Diagnosis By Pain

| Pain | Baseline Evidence | Real Source Cause | Product Reality | Target UX Direction |
| --- | --- | --- | --- | --- |
| Long upstream/downstream contract pages | Baseline reports Step 5 is about 85 scroll ticks for 3 downstream contracts and roughly 8x Step 2 for comparable contract count. | Step 2 uses a compact loaded table plus collapsible add form. Step 5 restores every downstream contract into a full editable card and separately renders readiness plus saved specs. | Downstream contracts are manifest references, not entity derivation. Users need confidence and surgical editing, not all fields open at once. | Make Step 5 a Contract Board: compact rows by contract family, one focused edit panel, readiness and artifact status inline. |
| Data handoff page grows past 3-4 handoffs | Baseline confirms four handoffs produce a long repeated form. | `step5_handoffs.html` restores each handoff into full cards with columns, DDL, manual override, and mappings all visible. | Handoffs are staging specs. They should not visually compete with edge contracts. | Make Step 4 a Handoff Board: table-first summary, one focused editor, DDL preview as secondary detail. |
| Entity identity-role density | Baseline calls out one identity-role dropdown per field x entity, mostly "No role". | `step3_entities.html` renders a select for every field in every entity role table. | Only non-default roles matter. "No role" should be implicit, not a repeatedly reviewed choice. | Use an Identity Role Lens: show chosen roles and deterministic field filters first; reveal all fields only on demand. |
| Visual monotony | Baseline notes a SOAP row looks like a CSV row. | Most surfaces reuse the same white card, table, and badge styling without contract-family silhouettes. | Type matters because CSV, fixed-width, XML, SOAP, REST, and staging have different authoring mental models. | Add contract-family visual language using existing tokens: left accent, compact type labels, family-specific metadata chips. |
| Heavy manual entry | Baseline highlights XML/XSD and SOAP mapping as fully hand-keyed. | Current inspectors and seed buttons exist, but the editing surface still makes users fill many rows manually. | Deterministic transforms are allowed; guesses are not. KA stays opt-in and review/accept. | Add a Deterministic Seeds panel: exact candidates from artifact/layout inspection and existing mappings, never auto-applied silently. |

## Design Principles

### 1. Contract Board, Not Form Stack

Use compact rows/cards as the default state. Put edit controls in a focused panel, modal, or drawer for one item at a time.

Why: users need to compare contract readiness across the package before editing details. This also matches Step 2's current stronger pattern.

Guardrail check: frontend-first, manifest-safe, deterministic. Applies mostly to `step4_downstream.html`, `step5_handoffs.html`, and CSS/JS. No Engine or manifest changes.

### 2. Two-Speed Authoring

Every heavy page should have a scan lane and an edit lane. The scan lane answers "what exists and is it ready?" The edit lane answers "what field do I change now?"

Why: long forms are correct but slow; scan/edit separation reduces scrolling without hiding data.

Guardrail check: frontend-first, reversible. Same persisted data. Existing save routes can remain at first; the JS can still compose the same form payload.

### 3. Exceptions-First Review

Make default states implicit. For identity roles, "No role" is the default and should not be shown as an equal-weight decision for every field.

Why: the meaningful review workload is role assignments and exceptions, not reading hundreds of repeated default selectors.

Guardrail check: frontend-first, manifest-safe. Existing identity role values and export behavior remain unchanged. Applies to `step3_entities.html` and `step3_entities.js`.

### 4. Contract Families Need Silhouettes

A fixed-width file contract should not look like SOAP. Use type labels, left accents, and family-specific metadata chips.

Why: visual shape helps users orient before reading. It also reduces the need for repeated explanatory copy.

Guardrail check: CSS/presentation only. Applies to `studio.css` or page-local classes. Does not change generated output.

### 5. Deterministic Seeds, Never Assumptions

When Studio can derive an exact value from the user's selected artifact, show it as a seed candidate. Do not invent entity mappings or business semantics.

Why: this respects the suite guardrail while lowering manual entry. Examples: layout fields to mapping rows, XSD root candidates, WSDL operation candidates, CSV delimiter from saved spec.

Guardrail check: deterministic. Existing inspectors/seeding can be made more visible, but no KS/KA calls, no hidden inference, no manifest changes.

## Target-State Redesign

### Step 5: Downstream Interfaces -> Contract Board

Current state:

- `step4_downstream.html` renders each downstream interface using `iface-template`, always expanded.
- Readiness appears in a separate "Contract Export Readiness" table.
- Saved file contract specs appear again in a separate card.
- Mapping, layout, SOAP, XML, CSV, and metadata fields live in the same vertical card.

Target state:

- A single Downstream Contract Board at the top.
- Rows group by family: File, XML/XSD, SOAP.
- Each row shows: type, name, mapped entity, artifact path, mapping coverage, package/write status, readiness, and actions.
- Selecting "Edit" opens a focused editor panel for that one contract.
- The editor panel switches by family:
  - Fixed-width: layout fields, mappings, sample inspection.
  - CSV: delimiter/header controls, columns, mappings.
  - XML/XSD: XSD artifact, root/namespace, XML path mappings.
  - SOAP/WSDL: service/port/binding/operation, canonical invoke/read mapping.
- Saved file specs collapse into the selected row's details instead of becoming a second page section.

Guardrail check: frontend-only in Phase 1; manifest-safe because it edits the same downstream interface fields; deterministic because all prefill comes from existing project state or explicit inspector output; source areas `app/templates/step4_downstream.html`, `app/static/css/studio.css`, optional vanilla JS alongside current Step 5 script.

Mockup: `mockups/contract-board.html`.

### Step 2: Upstream Contract -> Align With The Board Pattern

Current state:

- Step 2 is already the strongest edge-contract page.
- Loaded edge contracts are compact; the add form collapses when contracts exist.
- OpenAPI source is separated from edge-contract references.

Target state:

- Keep the compact loaded table.
- Add the same family silhouettes used by Step 5.
- Make "REST/OpenAPI creates entities; file/XML/SOAP are contract references until mapped" visible as a small structural reality note.
- Use the same focused editor pattern as Step 5 only after Step 5 proves the pattern.

Guardrail check: frontend-first and reversible; no manifest or Engine change; source area `app/templates/step2_upstream.html`.

### Step 4: Data Handoffs -> Handoff Board

Current state:

- `step5_handoffs.html` repeats every handoff as an expanded form.
- DDL preview, manual override, columns, and mappings are all inline.

Target state:

- Handoff Board rows show: handoff name, table, mapped entity, column count, mapping count, DDL mode, readiness.
- Selecting a row opens a Handoff Editor:
  - left side: table identity and staging columns.
  - right side: DDL preview and manual override.
  - bottom: mappings with "seed from selected entity" where deterministic.
- Show a "This is staging, not downstream artifact transform" banner when edge contracts also exist.

Guardrail check: frontend-first; manifest-safe because `data_handoffs[]` shape remains unchanged; deterministic seeding only from selected entity/staging column names; source area `app/templates/step5_handoffs.html`.

Mockup: `mockups/staging-handoff-board.html`.

### Step 3: Entity Model -> Identity Role Lens

Current state:

- `step3_entities.html` renders an Identity Role Review section with a role vocabulary and per-field role selector tables.
- Every field gets the same role dropdown even when it has no role.

Target state:

- Keep Step 3's current structure, but replace the dense role table default with a lens:
  - Summary per entity: persistence ID, metadata-only roles, unassigned fields, generated impact.
  - "Assigned roles" table lists only non-default roles.
  - "Field spotlight" filters deterministic candidates such as ID-looking fields, required fields, or fields with existing role suggestions. These are filters, not assignments.
  - "Show all fields" reveal keeps the full table available for edge cases.
- The selected/accepted role still writes exactly the same Studio project state.
- Step 3 full-width KA Review remains the one action surface for KA suggestions.

Guardrail check: frontend-first; manifest-safe; deterministic because candidate spotlight is only a filter over existing field names/types, not auto-accept; source areas `app/templates/step3_entities.html`, `app/static/js/step3_entities.js`.

Mockup: `mockups/identity-role-lens.html`.

### Cross-Cutting Visual System

Current state:

- `studio.css` already has strong base tokens, but most contract families share the same white-card silhouette.
- Step 7 has a useful summary pattern: `review-summary-strip`, summary cards, and compact status labels.

Target state:

- Keep Studio's current palette and typography. Evolve, do not replace.
- Add a small family taxonomy:
  - REST: blue primary accent.
  - Fixed-width: green file accent.
  - CSV: teal table accent.
  - XML/XSD: amber document accent.
  - SOAP/WSDL: navy service accent.
  - Staging: muted slate accent.
- Use each family consistently:
  - left border accent on board rows.
  - uppercase family label.
  - one-line "shape" metadata chips, e.g. `delimiter |`, `root AccountMessage`, `operation getCustomer`.
- Prefer summary cards and tables over nested white cards.
- Use the right rail as context only, not a second action surface.

Guardrail check: CSS/presentation only; no manifest, Engine, KS, or Evidence Trail changes; source area `app/static/css/studio.css`.

## Phased Rollout

### Phase 0: Token And Inventory Prep

Add page-local prototype classes or shared CSS utilities for contract family labels, board rows, and focused editor panels. No behavior change.

Risk: low. Reversible CSS-only slice.

### Phase 1: Step 5 Downstream Contract Board

Convert Step 5 from always-expanded cards into a compact board plus focused editor. Preserve the same JS payload assembly initially to avoid backend churn.

Risk: medium. Highest UX payoff. Needs careful regression around existing downstream interface save/open/export tests.

### Phase 2: Step 4 Handoff Board

Apply the same board/editor pattern to data handoffs. Keep DDL generation and manual DDL behavior unchanged.

Risk: medium. Similar mechanics to Phase 1.

### Phase 3: Step 3 Identity Role Lens

Switch identity role review from field-dropdown-first to exceptions-first. Keep the full table behind "show all fields."

Risk: medium. Needs careful copy so users trust that unshown fields still mean "No role."

### Phase 4: Step 2 Alignment And Deterministic Seeds

Bring Step 2 visual language into parity with Step 5. Improve the visibility of deterministic seed actions already present in the product.

Risk: low to medium. Step 2 is already strong; avoid overworking it.

### Phase 5: Full Walkthrough Polish

Tune Step 7/8 summaries so the package story is coherent from board rows to export artifacts to Evidence Trail.

Risk: low. Mostly copy and summary presentation.

## Open Decisions For Maintainer

1. Focused editor shape: should Step 4/5 use an in-page side panel, shell drawer, or modal? I prefer in-page side panel on desktop and modal on narrow screens.
2. Save model: should Phase 1 keep the current save-all behavior under the hood, or introduce a small single-contract save route? Keeping save-all is safer for the first build slice.
3. Row density: should boards default to table rows or compact cards? I prefer table rows for desktop, stacked cards below 900px.
4. Identity role candidate spotlight: should deterministic ID-looking filters be included in Phase 3, or should Phase 3 only show assigned roles first? I prefer including filters, clearly labeled as filters, not suggestions.
5. Family accents: should the accents become shared CSS utilities now, or remain page-local until two pages adopt them?
6. Generated-app boundary copy: how prominent should the "REST/OpenAPI derives entities; file/XML/SOAP are contract references" note be? I prefer one short note on Step 2/3, not repeated everywhere.

## What This Does Not Attempt

- No generated-app changes.
- No manifest schema changes.
- No Engine or KS behavior changes.
- No hidden parsing or AI inference.
- No change to KA OFF cleanliness.
- No attempt to make file/XML/SOAP magically create entity models. That is a backend/product capability boundary, not a UI problem to paper over.

## Mockups

- `mockups/contract-board.html`: target Step 5 downstream Contract Board and focused editor.
- `mockups/identity-role-lens.html`: target Step 3 exceptions-first identity role review.
- `mockups/staging-handoff-board.html`: target Step 4 Handoff Board and focused DDL/mapping editor.
