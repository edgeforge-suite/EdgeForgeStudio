# Studio UX Refresh - Codex Review Pass

Status: review pass complete. Verdict: adopt with changes.

Subject: `docs/studio-ux-refresh/proposal-final.md` and `docs/studio-ux-refresh/final-mockups/`.

Method: I reviewed the consolidated proposal, final mockups, Action-3 passes/cross-reviews, and the real Studio source that the proposal would touch. I formed the findings below from source first, then read the Fable review only for the final reconciliation section.

Production code touched: none.

Additional Codex artifact: `docs/studio-ux-refresh/final-mockups/step5-downstream-contract-board-codex-tint.html` plus rendered PNG.

## Executive Verdict

The consolidated UX refresh is directionally sound and implementable against the current Studio codebase. The core pattern - scan board first, focused editor second, deterministic seed review third - fits the server-rendered Jinja + vanilla JS architecture better than a wholesale app rewrite.

I recommend adopting it with three required Action-4 redlines:

1. P5 must consume the existing server-side deterministic inspection endpoints instead of introducing browser-side XML/WSDL parsing as the primary path.
2. P6 must refactor the existing readiness/completeness services into a single item-shaped view model rather than creating a parallel readiness source.
3. The desktop split/focused editor needs an explicit save and dirty-state model before build starts, because current Step 4/5 pages still rely on DOM-as-truth whole-page saves.

## Task A - Source-Grounded Review

### A1. Existing Deterministic Inspection Already Exists

The proposal is right to push deterministic candidate generation, but its P5 wording should be changed. It currently implies WSDL/XSD parsing through browser `DOMParser`. That would duplicate production server-side logic that already exists.

Source evidence:

- `app/routes/upstream.py` exposes `POST /upstream/edge-contract/inspect` and `POST /upstream/edge-contract/file-inspect`, routing to deterministic inspectors.
- `app/routes/downstream.py` exposes `POST /downstream/edge-contract/inspect` and `POST /downstream/edge-contract/file-inspect`.
- `app/services/edge_contract_inspector.py` already parses XML/XSD and SOAP/WSDL safely enough for this UX layer, including DTD/entity rejection, target namespace extraction, XML root candidates, SOAP services, ports, bindings, operations, SOAPAction, and warnings.
- `app/services/edge_contract_file_inspector.py` already inspects fixed-width and CSV layouts, including expected line length, delimiter/header metadata, sample preview, and field candidates.
- `app/templates/step2_upstream.html` and `app/templates/step4_downstream.html` already call those endpoints from the UI and expose "apply selected metadata" and "seed mapping rows" flows.

Recommended correction:

P5 should say: "The patch/review UI consumes Studio's existing deterministic inspect endpoints as the single parsing source." Browser-side parsing may be used only as a non-authoritative preview if ever needed, but it should not create a second candidate picker.

### A2. Current Seeding Already Violates the Proposed Never-Overwrite Rule

The consolidated proposal's "never overwrite non-empty values" rule is the right target, but current source does not fully meet it.

Source evidence:

- `app/templates/step2_upstream.html` has seed helpers that confirm replacement and then clear existing mapping rows before re-seeding.
- `app/templates/step4_downstream.html` has similar helpers for downstream file mappings and fixed-width layout rows.
- XML/SOAP "apply selected metadata" flows directly copy selected root/service/port/binding/operation fields into form inputs when the user clicks apply.

This is acceptable today because it is explicit and confirm-driven, but Action-4 should treat P5 as a migration from "confirm and replace" to "reviewable patch." The new UI should show proposed additions, replacements, and conflicts before applying, and should preserve non-selected rows by default.

### A3. Readiness Exists Today, But Not Yet as One Item Model

The proposal's P6 direction is correct, but should be framed as a refactor over existing producers.

Source evidence:

- `app/services/edge_contracts.py` provides `edge_contract_readiness` and `edge_contract_readiness_rows`.
- `app/services/package_writer.py` uses edge-contract readiness rows to block incomplete contracts during export.
- `app/services/manifest_generator.py` uses `edge_contract_readiness` when emitting contract references.
- `app/services/completeness_service.py` already composes upstream, downstream, edge-contract, and export-readiness status into the review/completeness flow.

Recommendation:

P6 should define a single item-shaped adapter over `completeness_service.py` and `edge_contract_readiness`, not a new independent readiness engine. Export, Step 7, board rows, focused editor banners, sidebar chips, and trace lens should all consume that same producer.

Current item kinds with no complete producer today:

- Data handoff/staging table rows as deep-linkable readiness items.
- Identity-role decisions as row-level readiness or metadata-only items.
- Rule rows and advisory conflict rows in Step 6.
- Kafka topic/route/transform rows.
- Passthrough target/transform rows.
- KA suggestion/review rows.
- Trace-lens nodes as first-class readiness items.

### A4. Real Markup Makes Some Patterns Harder Than the Proposal Implies

The proposal is implementable, but the build estimate should not treat it as mostly CSS.

Source evidence:

- `app/templates/step4_downstream.html` is the displayed Step 5 and contains the full downstream editor, readiness table, saved specs, inline restore logic, file/XML/SOAP fields, layout rows, mapping rows, and inspect/seed actions.
- `app/templates/step5_handoffs.html` is the displayed Step 4 and similarly restores all handoff cards from DOM/templates.
- `app/templates/step3_entities.html` plus `app/static/js/step3_entities.js` already has a complex identity-role, KA review, filtering, overlay, drawer, and evidence surface. The identity lens is feasible, but it is a real view-model re-projection, not just hiding "No role."
- `app/templates/step6_rules.html` mixes editable rules, KA badges, advisory conflicts, generated-ID warnings, legacy notes, and right-rail summary. It needs a design pass, not a direct copy of the Step 5 board.
- `app/static/js/studio.js` provides useful primitives (tabs, drawers, workspace modal, suggestion drawer), but it is not a generic focused-editor framework.

## Verdict by Major Section

| Section | Verdict | Codex note |
|---|---|---|
| Section 2.1 editor surface | Adopt with changes | The full-page route first, desktop split second, narrow modal later sequence fits Jinja. Action-4 must define the save/dirty model before desktop split. |
| P1 triage board | Adopt | Strongest near-term value. Keep cards present in DOM for the first collapse-only slice to avoid save regressions. |
| P2 focused editor | Adopt with changes | Good target, but "move forms verbatim" understates the template/JS work, especially SOAP and file mapping sections. |
| P3 identity role lens | Adopt | Hiding "No role" and surfacing an "N No Role Hidden" counter is exactly right. Keep the Engine-behavior column. |
| P4 visual system | Adopt with changes | Use family accents for contract family; use role-based zone tints for page function. Do not let family color become large background tint. |
| P5 deterministic seeds | Adopt with changes | Must reuse existing server-side inspect endpoints and convert current confirm-replace seeding into reviewable patches. |
| P6 readiness model | Adopt with changes | Make it a refactor of existing readiness/completeness producers. Do not add a parallel source of truth. |
| P7 handoff editor | Adopt with changes | Good UX target, but seed-from-entity needs entity field context or a small read endpoint. DDL/manual sections need explicit derived-vs-manual handling. |
| P8 trace lens | Adopt | Good as a later synthesis layer once P6 emits stable item refs and deep links. |
| P9 Matrix Lite | Adopt as optional later phase | Not v1. It is useful for narrow homogeneous scalar rows, not for Step 6 cross-entity rules or SOAP mappings. |
| Section 6 phasing | Adopt with changes | Add a Phase 0 inventory of current inspectors/readiness/save paths. Keep Phase 1 collapse-only where possible. |

## Prioritized Gap List

### P0 - Must Resolve Before Build

- P5 inspector source: update the spec so deterministic candidate generation consumes existing server-side inspect endpoints, not browser `DOMParser`.
- P5 overwrite behavior: define reviewable patch semantics for current seed/apply flows before implementing them.
- P6 single producer: define the `ReadinessItem` adapter over current readiness/completeness services and name missing item producers.
- G1 save/dirty state: settle single-item save, cancel, dirty prompts, and validation deep-link behavior before desktop split work.
- G2 Step 6 scope: decide v1 board/editor shape and Matrix Lite deferral before implementing rules UX.

### P1 - Important for Action-4 Estimation

- Step 3 identity lens requires careful extraction from `step3_entities.js`; schedule it as one of the heavier front-end slices.
- Step 4/5 template naming is historically confusing (`step4_downstream.html` is displayed Step 5; `step5_handoffs.html` is displayed Step 4). Action-4 should call this out to avoid wrong-file edits.
- Add-new item behavior is under-specified. A draft item should open in the focused editor and appear as Draft in the board only after explicit create/save rules.
- Kafka and passthrough need a capture-first pass, not a blind CRUD pattern transplant.
- KA Workspace and accept/edit/reject review should reuse the patch grammar, but only after the KA production-readiness decision because KA is default OFF.

## Task B1 - Functional-Zone Tinting

I recommend tinting by role, not family. Family should remain an accent system (left rail, icon chip, monogram, ribbon), while zone tint communicates what the user does in that region.

Palette:

| Zone | Token | Color | Usage |
|---|---|---|---|
| Scan | `--zone-scan` | `#f3f7fb` | Boards, lists, low-intensity overview surfaces. |
| Editor brightest | `--zone-editor` | `#ffffff` | Focused editor, active work surface. |
| Derived seed | `--zone-derived` | `#f7f3ff` | Deterministic seed/preview/reviewable patch panels. |
| Needs action | `--zone-action` | `#fff6df` | Blockers, fix-required groups, warning rows. |
| Readiness | `--zone-readiness` | `#eef6f8` | Ambient readiness strips and compact status summaries. |

Guardrail check:

- Frontend-first: yes, CSS/token change only.
- Manifest-safe: yes.
- Deterministic: yes, purely presentational.
- A11y: each zone must carry text labels/icons in addition to color; body text contrast remains high because tints are very light.
- Provenance: unchanged.

Applied mock:

- `docs/studio-ux-refresh/final-mockups/step5-downstream-contract-board-codex-tint.html`
- `docs/studio-ux-refresh/final-mockups/step5-downstream-contract-board-codex-tint.png`

## Task B2 - Kafka Router and REST Passthrough Scope

The pattern language extends, but only after capture.

Source evidence:

- `app/templates/base.html` already branches the wizard by archetype.
- Kafka uses separate topic, route, and transform steps.
- Passthrough uses the OpenAPI upstream path plus a route/transform page rather than the CRUD entity/handoff/downstream flow.

### Kafka Capture Plan

Capture screens:

- Kafka topic ingest step with several source/target topic pairs.
- Kafka route model step with request/reply, router, NACK, timeout, duplicate-correlation, and target rows.
- Kafka transform mappings step with multiple route/target mappings.
- Kafka review/export steps.

Apply plan:

- P1 board becomes a route/topic board, not an entity board.
- P2 focused editor edits one topic pair, route, or transform set at a time.
- P4 family accents should represent topic, route, transform, target, and response-path roles rather than file/XML/SOAP families.
- P6 item kinds should include `topic_pair`, `route`, `target`, `transform_set`, `nack_policy`, and `timeout_policy`.
- P8 trace lens should read topic-in -> route -> target/topic-out -> response route, not entity -> contract.

What differs:

- No canonical CRUD entity page.
- No data handoff staging flow.
- No contract-family visual system as the primary family axis.

### REST Passthrough Capture Plan

Capture screens:

- Upstream OpenAPI source and selected operation state.
- Passthrough route/transform page with multiple downstream targets and transform rows.
- Review/export.

Apply plan:

- Start lighter than CRUD. This may need a sectioned route/target board rather than full card/editor machinery.
- Reuse existing deterministic `/passthrough/describe-spec` behavior as the seed source where applicable.
- P6 item kinds should include `selected_operation`, `downstream_target`, `route_field`, and `transform`.
- Matrix Lite may be useful only if transform rows grow large in real capture.

What differs:

- Passthrough is closer to one route plus target transforms, not a multi-contract canonical model.
- Do not copy Step 5 downstream file-contract patterns unless capture proves the target list grows similarly.

## Task B3 - KA Workspace and Review Scope

KA should reuse P5's reviewable-patch language, but the workflow is different enough to deserve a dedicated pass.

Reuse:

- Suggestion rows can share the patch anatomy: target, current value, suggested value, evidence/provenance, generated impact, action.
- Provenance chips can share the visual grammar: deterministic derived, spec-derived, KA-applied, manual.
- The full-width Step 3 KA Review remains the action surface; do not create a second review surface.

Differences:

- KA suggestions are retrieved from KS and reviewed by the user; they are not exact deterministic transforms from a local contract artifact.
- Accept/edit/reject states are durable review decisions.
- Evidence citations and stale/missing evidence states matter.
- KA is default OFF, so KA Workspace redesign should be gated on the KA production-readiness decision.

Dedicated pass scope:

- Knowledge Workspace document list/upload/delete/source health.
- Step 3 full review table, evidence details, and accept/edit/reject flows.
- Step 6 rule suggestion badges/drawers.
- Step 7 Decision History and Evidence Trail separation.
- KA OFF smoke expectations.

## Task C1 - G1 Save and Dirty-State Recommendation

Current source behavior:

- Step 5 downstream (`app/templates/step4_downstream.html`) collects all cards from the DOM and posts the complete list.
- Step 4 handoffs (`app/templates/step5_handoffs.html`) also collects all cards from the DOM and posts the complete list.
- Step 2 upstream edge-contract save is closer to single-item authoring.

Recommended approach:

Phase 1 can keep whole-page save if cards remain present in DOM and only visually collapse. This is the lowest-risk first move.

For desktop split and full-page focused editor, add a single-item save/upsert model:

- The editor owns one selected item snapshot.
- Save posts only that item plus a stable identifier such as original name/id.
- Cancel discards only the local editor snapshot.
- Browser back and in-app navigation warn when the selected item is dirty.
- The board refreshes from the server's saved state after save, not from optimistic DOM assumptions.
- Validation responses include `section_ref` and `field_ref` so the focused editor can deep-link to the failing tab/field.

If adding a new route is considered too much for the first desktop split slice, an acceptable interim is server-side patching through the existing save route: build the full list from the saved session plus the selected item patch, not from hidden DOM rows. But the long-term target should be single-item upsert.

Guardrail check:

- Frontend-first: mostly, with small backend route/helper only when split editor begins.
- Manifest-safe: yes.
- Deterministic: yes.
- Reversible: yes, phase 1 can ship without changing save semantics.

## Task C2 - G2 Step 6 Rules and Mappings

Step 6 should not be solved by copying the downstream contract board unchanged. It has two fundamentally different surfaces: editable rules and read-only advisory conflicts.

Source evidence:

- `app/templates/step6_rules.html` renders advisory issues/conflicts, editable business rules, KA rule badges, generated-ID warnings, legacy notes, and a right-rail conflict summary.
- Editable rules can be entity/field-scoped and include validation, cross-entity, generated/spec-derived, manual, and KA-applied rows.
- Advisory conflicts are not generated-app changes and should remain visibly advisory.

V1 recommendation:

- Board item = entity rule set, not individual rule.
- Board rows show entity, active rule count, fields covered, generated/spec/manual/KA counts, and attention state.
- Focused editor groups rules by field and by rule type.
- Cross-entity rules get a separate block with prerequisite state made explicit.
- Advisory conflicts sit in a dashed/amber read-only strip or side summary. They should not look editable and should not block export unless future policy changes.
- Legacy Notes stay separate and quiet.
- The right rail can stay as a read-only advisory/status summary, fed by the same P6 model.

Matrix Lite call:

- Out for v1.
- In later only for homogeneous scalar rule rows, after board/editor and dirty-state are stable.
- Cross-entity rules and advisory conflicts should stay out of Matrix Lite.

## Reconcile With Fable

After writing the independent conclusions above, I read Fable's review pass. The two reviews strongly converge:

- Both recommend "adopt with changes."
- Both identify P5 server-side inspectors as the correct source and browser `DOMParser` as a drift risk.
- Both identify P6 as a refactor around existing readiness/completeness rather than a new source.
- Both recommend resolving G1 before desktop split and deferring Matrix Lite from v1.
- Both agree Step 6 needs its own board/editor treatment and should keep advisory conflicts read-only.

The main difference is emphasis. Fable goes further by proposing single-item upsert routes as the strong Phase 2 target and by adding a Step 6 sketch. My pass keeps a slightly broader fallback open for the first split-editor slice: if the team wants to avoid new routes initially, the safe fallback is server-side patching from saved session plus selected item, never hidden DOM. I still agree the long-term shape should be single-item upsert.

I also kept the Codex tint work separate in a namespaced mock instead of altering the consolidated final mockups directly. That gives the maintainer a clean option to compare role-based zone tinting without mutating the canonical mock set before the gate.

## Halt

This pass is complete and ready for maintainer review. No build work should begin until the maintainer signs off on the P0 redlines, especially P5, P6, G1, and G2.
