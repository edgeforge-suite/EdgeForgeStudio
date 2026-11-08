# Action-4 Build-Contract Verification - Codex

Status: complete. Verdict: approve with redlines.

Subject: `docs/studio-ux-refresh/implementation-design.md` at commit `9002313`.

Scope: design/docs verification only. No production code changed.

## Executive Verdict

The Action-4 implementation design is directionally correct and mostly buildable PR-by-PR. It faithfully carries forward the locked decisions from `proposal-final.md`, `review-reconciliation.md`, `review-pass-codex.md`, and `review-pass-fable.md`: P5 uses existing server-side inspect endpoints, P6 is one readiness producer, G1 is single-item save from Phase 2a, G2 keeps Step 6 advisory conflicts read-only, Matrix Lite is out of v1, and D1 uses role-based zone tints with family accents only.

I would approve gate 3 after the redlines below are folded into the design doc. None require production code before Action-5; they are build-contract clarifications that prevent mid-PR traps.

## Gate Redlines

| ID | Severity | Redline | Why it matters |
|---|---:|---|---|
| R1 | P0 | Fix the PR-03 readiness parity contract. Either add all current export-blocking `CompletenessReport` categories to `ReadinessItem` (`project`, current OpenAPI operation/sample/mapping blockers, etc.) or narrow the parity assertion to represented item kinds until later PRs add the missing producers. | The doc's listed item kinds are `downstream_interface`, `upstream_contract`, `handoff`, `entity`, `rule_set`, but `CompletenessReport.is_exportable()` also blocks on top-level project fields and existing non-edge upstream/sample states. As written, `report.is_exportable() == no blocks_export items` can fail by design. |
| R2 | P1 | Add an explicit test-backfill requirement before or inside PR-09. | `step3_entities.js` is 1,881 lines and current tests mostly assert script presence, strings, and server endpoints. A behavior-identical JS re-projection needs stronger fixtures/snapshots before it is safe to refactor. |
| R3 | P1 | Fix PR-01 acceptance from "grep shows no reference to old names" to "no app/test runtime references to old template names; historical docs may retain old references." | The old names intentionally remain in review/proposal docs and an unrelated future-design doc. A repo-wide grep acceptance would fail immediately. |
| R4 | P1 | Add dependency edge from PR-12 to PR-14, or split the dirty-state utility into its own prerequisite PR before both focus editors. | PR-12 lands the dirty-state utility in `studio.js`; PR-14 is also a focused editor and must satisfy G1 dirty-state behavior. The current parallel lane says PR-08 -> PR-14 can run disjoint from PR-12, but that is only true if PR-14 does not need the shared utility, which would violate the G1 acceptance. |
| R5 | P2 | Clarify smoke-test paths and fixture strategy: use `tests/smoke/`, root `tests/session_helpers.py`, and `tests/smoke/_shared.py`; do not imply a `tests/smoke/session_helpers.py` module exists. | Test strategy is feasible, but the named helper location is imprecise and `tests/fixtures/` currently has only one YAML fixture, so Action-5 must create fixture projects rather than assume they exist. |

## Task 1 - Source-Fact Audit

| Claim | Confirm/refute | Source evidence | Build note |
|---|---|---|---|
| `build_nav_context()` reaches every step template, including Kafka/passthrough/knowledge. | Confirm with nuance. All main step routes build nav context and pass `**nav`; knowledge also does. Error templates can fall back through `base.html` without nav context. | `app/services/nav_context.py:91-132`; `app/routes/downstream.py:112-137`; `app/routes/handoffs.py:58-73`; `app/routes/entities.py:2304-2331`; `app/routes/kafka.py:1085-1098`, `1201-1216`, `1366-1384`; `app/routes/passthrough.py:347-366`; `app/routes/knowledge.py:341-378`; `app/templates/base.html:31-67`. | PR-02 is buildable. Wording should say routes already consume nav context; `ux_refresh` does not exist yet. If the team wants body class on non-step error pages, compute a default in `base.html` or pass nav there too. |
| `EDGEFORGE_STUDIO_*` env + truthy pattern is accurately described. | Confirm with preferred implementation detail. `app/cli.py` has `_truthy()` with `1,true,yes,on`; settings also has `_env_bool()` with the same truthy set and intentionally avoids caching. | `app/cli.py:11-20`; `app/services/settings.py:17-24`, `88-93`. | Prefer putting UX flag reading in settings/nav helper using the settings-style no-cache pattern rather than importing CLI code. This keeps tests parametrizable via `monkeypatch.setenv`. |
| Readiness adapter can build on existing producers and export alignment is real. | Confirm, but R1 applies. Edge-contract readiness directly drives package blocking and manifest emission. Completeness report drives Step 8 export disabling and package report rendering. | `app/services/edge_contracts.py:1278-1420`, `1431-1455`; `app/services/package_writer.py:164-181`, `514-515`; `app/services/manifest_generator.py:296-340`; `app/routes/export.py:360-366`, `377-386`. | The adapter is more than a thin mapper because `CompletenessReport` is category/message-only (`app/services/completeness_service.py:25-60`) and includes export blockers beyond the listed `ReadinessItem` kinds. |
| `/downstream/save`, `/handoffs/save`, `/rules/save`, `/entities/save` are whole-list DOM-as-truth. | Confirm. They replace the relevant session lists from submitted whole-page payloads. | Downstream: `app/routes/downstream.py:140-232`; handoffs: `app/routes/handoffs.py:76-163`; rules: `app/routes/rules.py:1388-1610`; entities: `app/routes/entities.py:2434-2545`. | Phase 1 collapse-only safety is real because cards stay in DOM and existing whole-list save remains untouched. |
| `/upstream/edge-contract/save` is single-item but lacks rename handling. | Confirm. It filters by the new interface name and appends; if the user changed the name, the old row remains. | `app/routes/upstream.py:191-220`, especially `207-214`. | PR-15 `original_name` is needed. |
| Per-item validators are reusable for save-one. | Mostly confirm. `validate_edge_contract_payload` is reusable for upstream/downstream edge contracts. Handoffs and rules have validation logic embedded in whole-list routes today and need extraction. | `app/services/edge_contracts.py:1004-1067`; `app/routes/handoffs.py:120-143`; `app/routes/rules.py:1415-1588`. | Update PR-12/14/19 wording to note "reuse or extract existing per-item validation" rather than implying every validator already exists as a reusable helper. |
| Session idiom is correct. | Confirm. Current routes use `get_current_session()` and `save_current_session()`. | Examples: `app/routes/downstream.py:155`, `230-231`; `app/routes/handoffs.py:90`, `161-162`; `app/routes/rules.py:1405`, `1609`; `app/routes/upstream.py:202`, `214`. | Save-one routes fit the existing idiom. |
| Four inspect endpoints and inspectors exist, with DTD/entity rejection. | Confirm. | Endpoints: `app/routes/upstream.py:224-265`; `app/routes/downstream.py:235-276`. XML rejection: `app/services/edge_contract_inspector.py:42-51`. XSD/WSDL inspection: `app/services/edge_contract_inspector.py:185-220`, `276-310`, `390-401`. File inspection: `app/services/edge_contract_file_inspector.py:17-72`, `95-173`. | PR-05 and PR-13/15 should consume these; no browser parser should be primary. |
| Confirm-then-replace seed handlers are where the doc says. | Confirm. | Step 2 upstream seed: `app/templates/step2_upstream.html:816-858`. Step 5 downstream seed/layout replace: `app/templates/step4_downstream.html:656-728`. Inspect/apply metadata: `app/templates/step2_upstream.html:875-914`, `1085-1176`; `app/templates/step4_downstream.html:845-882`, `1044-1133`. | The "migration, not addition" rule is essential. |
| Template rename scope covers source references. | Mostly confirm, with R3. Runtime references are the two route render calls. Docs contain historical old-name references. | Runtime references: `app/routes/downstream.py:116`; `app/routes/handoffs.py:62`. Repo grep also finds old names in review/proposal docs and `docs/staged-downstream-future-design-review.md`. | PR-01 should update app/test runtime references and any test assumptions. Do not require historical docs to erase old references. |
| `identity_role_review` and `role_behavior_rows` exist server-side. | Confirm. | Route context: `app/routes/entities.py:2304-2331`; service: `app/services/identity_roles.py:160-164`, `302-337`; template consumption: `app/templates/step3_entities.html:204-335`. | PR-10 can re-project existing data instead of inventing new state. |
| Handoff template lacks entity-field context. | Confirm. It receives existing handoffs and edge-contract-only flag, not entity field catalogs. | Route context: `app/routes/handoffs.py:58-73`; template data bootstrap: `app/templates/step5_handoffs.html:131-164`. | PR-14 needs a read-only entity field context or endpoint for seed-from-entity. |
| DDL generate endpoint + saved `ddl_content` can support before/after diff; round-trip is async. | Confirm. | DDL endpoint: `app/routes/validate.py:30-42`; saved DDL restore: `app/templates/step5_handoffs.html:178-198`; async preview/generation: `app/templates/step5_handoffs.html:319-327`, `458-472`; save all awaits card data: `app/templates/step5_handoffs.html:506-512`. | PR-14 pending state and Save disabling are required, not polish. |

## Task 2 - PR-Plan Buildability

| PR | Buildability | Notes |
|---|---|---|
| PR-01 template naming rename | Buildable S with R3 | Runtime scope is small (`routes/downstream.py`, `routes/handoffs.py`, two template files). Acceptance must restrict grep to runtime/test refs. |
| PR-02 feature flag + tokens | Buildable S | Use a no-cache env bool so both flag states can run in one test process. Add `body.ux-refresh` in `base.html`. |
| PR-03 `ReadinessItem` adapter | Buildable M with R1 | Needs a precise parity scope. Current `CompletenessReport` shape is message/category-only and includes blockers outside listed item kinds. |
| PR-04 handoff + entity readiness producers | Buildable M | Source supports this, but entity persistence-key policy must be explicit for edge-contract-only and metadata-only cases. |
| PR-05 inspector security tests | Buildable S-M | Endpoints and services exist. Add bounds/depth/path traversal tests if helpers expose those seams; failures should indeed become separate fixes. |
| PR-06 family + zone skin | Buildable M | CSS-only/tiny template work if no structural markup changes. |
| PR-07 Step 5 triage board | Buildable L | Server-rendered rows from `items_for_step()` are feasible once PR-03/04 are in. Route must pass the view model into the template. Keep legacy cards in DOM. |
| PR-08 Step 4 handoff board | Buildable M | Feasible after PR-04. Keep card DOM present for whole-list save. |
| PR-09 Step 3 view-model extraction | Buildable L with R2 | Slice is right, but the doc should require test backfill/snapshots before behavior-identical refactor. Existing JS coverage is not enough. |
| PR-10 Step 3 identity lens | Buildable L | Server data exists. Depends on PR-09. Assert `/entities/save` and `/entities/identity-roles` payload parity. |
| PR-11 rail count chips + Step 2 chips | Buildable S-M | Should explicitly depend on PR-03, and PR-04 if attention counts include handoff/entity blockers. |
| PR-12 Step 5 focus + save-one | Buildable L | Feasible in same template. Needs URL-safe focus identifiers, `original_name`, five-surface response, and dirty-state utility. |
| PR-13 Step 5 seed-patch migration | Buildable M-L | Correctly consumes existing downstream inspect endpoints. Heavy because SOAP/file mapping sections are dynamic. |
| PR-14 Step 4 focus + save-one + DDL diff | Buildable L with R4 | Needs entity-field context and async DDL pending state. Also needs dirty-state utility from PR-12 or a shared prerequisite. |
| PR-15 Step 2 focus + upstream rename + seed patch | Buildable M | Existing single-item route makes this tractable; `original_name` closes rename duplicate hazard. |
| PR-16 Step 7 deep links | Buildable S-M | Depends on stable `section_ref`/`field_ref` from readiness and save-one validation. |
| PR-17 desktop split | Buildable M | Correctly gated after Phase 2a. Must use save-one response, not client recomputation. |
| PR-18 narrow modal | Buildable M | A11y acceptance is clear. Good to keep after desktop split proves focus route. |
| PR-19 Step 6 rules board/save-one | Buildable L | Current whole-list rules validation computes cross-entity prerequisites from one submitted list. Save-one must build the effective full session rule set before validation, then replace only the selected entity's rule-set. Add explicit test. |
| PR-20 allowed-values paste bulk action | Buildable S | Correctly follows PR-19. Keep preview + undo only. |
| PR-21 Step 7 Trace Lens | Buildable M | Feasible from `entity_name` links and readiness items after PR-12/14/15/16. |
| PR-22 Step 2 full board parity | Buildable S-M | Good to defer until after CRUD core stabilizes. |
| PR-23 Step 7/8 polish | Buildable S-M | Feasible if all counts come from readiness view. |
| PR-24 flag flip + legacy removal | Buildable M | Correctly gated by checklist. Deleting legacy wholesale saves should only happen after focused paths cover equivalent behavior. |

### Dependency Graph Notes

- Add an explicit `PR-03 -> PR-11` dependency because PR-11 uses `step_counts()`.
- Add an explicit `PR-12 -> PR-14` dependency or split dirty-state utility into a separate pre-focus PR. The current "parallel lane B" is not fully disjoint if PR-14 must implement dirty-state behavior.
- PR-07 and PR-08 require PR-03/04 data flow even though their primary file edits are separate.
- After Phase 0, the Step 5 and Step 3/4 lanes are mostly disjoint in templates, but shared `studio.css`, `base.html`, `nav_context.py`, and `studio.js` changes should be serialized when they touch shared behavior.

## Task 3 - Test Strategy Feasibility

| Area | Feasible? | Gaps / corrections |
|---|---|---|
| Both-flag-state smoke | Yes | Use request-time/no-cache env reading. Current root `tests/conftest.py:18-47` already uses monkeypatchable env isolation. Add parametrization either at smoke fixture level or specific route/render tests. |
| Smoke helper naming | Yes with wording fix | The package is `tests/smoke/`, but shared session helpers are `tests/session_helpers.py`; smoke utilities live in `tests/smoke/_shared.py`. The doc should not imply `tests/smoke/session_helpers.py` exists. |
| Marker tests | Yes | `base.html` can expose stable marker IDs/classes. Use marker tests rather than full HTML byte diff except PR-01/02. |
| Round-trip fixtures | Yes, but fixtures must be created | `tests/fixtures/` currently only contains `parcel-response-upload.yaml`. Existing smoke helpers programmatically build rich sessions in `tests/smoke/_shared.py:136-240+`, so Action-5 should add explicit project JSON fixtures or reusable builders. |
| Payload snapshots | Yes | Especially valuable for PR-12/13 SOAP/file mapping sections and PR-14 handoff DDL. No dependency issue. |
| Readiness parity tests | Yes after R1 | Implementable once item-kind scope is corrected. Test edge-contract blocking against `package_writer` and broader export disabling against `build_completeness_report`. |
| Step 3 JS refactor tests | Needs backfill | There is no jsdom/playwright test harness in the repo today. Current tests read JS text and assert strings. For PR-09, add route-render snapshots and/or minimal browser/jsdom-style checks before refactor, or keep PR-09 very small with targeted static invariants. |
| Accessibility | Feasible | `pytest` cannot fully prove keyboard/SR walkthroughs. PR-18's recorded/manual walkthrough requirement is appropriate. |

## Task 4 - Contract vs Proposal Fidelity

| Locked item | Reflected? | Notes |
|---|---|---|
| P5 existing server endpoints, no primary DOMParser | Yes | `implementation-design.md:140-144` correctly drops browser DOMParser and names the four endpoints. |
| P5 reviewable patch / never overwrite | Yes | `implementation-design.md:145-158` captures exact/normalized/collision rules and migration-not-addition. |
| P6 one producer | Yes with R1 | `implementation-design.md:58-96` names a single adapter over existing producers. Needs parity item-kind correction. |
| G1 single-item save, no interim | Yes | `implementation-design.md:98-136` follows D2. Needs PR-14 dependency clarification. |
| G2 Step 6 shape | Yes | `implementation-design.md:288-299` captures entity rule-set, read-only advisory strip, prerequisite visibility, and Matrix Lite out. |
| D1 tokens | Yes | `implementation-design.md:160-178` matches the decided moderate-intensity palette and a11y contract. |
| Matrix Lite out of v1 | Yes | `implementation-design.md:298-299`, `410-415`. |
| Kafka/passthrough/KA follow-ons out of scope | Yes | `implementation-design.md:410-415`, `419-424`. |
| Codex redlines reflected | Mostly yes | P5, P6, G1, G2, D1 are reflected. Remaining Codex verifier redlines are build-contract precision issues R1-R5 above. |

## Final Recommendation

Approve for gate 3 after amending `implementation-design.md` for R1-R5. The implementation plan is otherwise sound, source-grounded, and safe to hand to Action-5 PR-by-PR.

Do not start production build work until those redlines are either folded into the doc or explicitly waived by the maintainer.

> Public-tree note (2026-11-02): the fixture name above now points to an independently authored parser regression; the original dated review remains private history.
