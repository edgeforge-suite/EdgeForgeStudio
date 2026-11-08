# Studio UX v2 — Historical Redesign Review and Implementation Guide

> **Historical design snapshot.** Updated 2026-04-20. No production code changed.
> It was grounded in the then-current post-Kafka/post-KS Studio baseline through PR #70.
> For current implementation truth, use [`studio-context.md`](studio-context.md) and
> [`studio-architecture.md`](studio-architecture.md); for current suite planning, use the
> [Engine enterprise roadmap](https://github.com/santosh-sh/EdgeForge/blob/main/docs/enterprise-readiness-roadmap.md)
> and its [generated tracker](https://github.com/santosh-sh/EdgeForge/tree/main/docs/tracker).
>
> Live app status at time of writing: **UP** (http://127.0.0.1:38081 reachable).
> All assertions in this document are grounded in code truth (templates + routes),
> not in live app observation alone.
>
> **Current contract note:** the UX decisions remain applicable, but the coordinated
> V2-S/V2-E cut supersedes this document's former manifest-1.x invariant. Studio now
> emits manifest `schema_version: "2.0"`; its project snapshot remains version 1.4.

---

## Purpose

This document is the actionable UX review and implementation guide for Studio v2.
It describes the current UX state honestly, identifies specific friction points,
and specifies a redesign that:

- preserves every existing backend contract and manifest schema
- requires no backend changes for the recommended baseline
- gives implementation teams slice-by-slice guidance to execute incrementally
- distinguishes clearly between what can be done in the UI layer now versus what
  requires future backend or MCP work

The design is anchored to `EdgeForge Target-State Architecture Roadmap v1.md`
Section D, which defines the required v2 Studio frame as:
main pane (structured authoring) + persistent right rail (AI assistance panels) +
bottom drawer (manifest diff, decision history, completeness).

---

## Current-State UX Audit

Studio currently uses a Jinja2/vanilla-JS server-rendered wizard over FastAPI.
The layout is a fixed two-column shell: left sidebar (brand + step nav + save/open)
and a single main content area. There is no right rail and no bottom drawer.

| Step | Current behavior | Friction / gap |
|------|-----------------|----------------|
| 1 — Project Setup | Form: app name, context, archetype radio cards, target profile, output path, repo path. Separate card below for Knowledge Workspace entry link. | Knowledge Workspace is a second card bolted on below the form — not integrated into the flow. Archetype selection has no visual completion state. No ingest kickoff cue. Step nav shows no progress indicators (active vs complete vs incomplete). |
| 2 — Upstream Contract (CRUD/PT) or Topic Ingest (Kafka) | CRUD/passthrough: URL/upload/paste for OpenAPI spec. Kafka: consumer group config + topic pair cards with inline JSON schema fields. | `wizard_registry.py` already uses archetype-specific labels here — CRUD and passthrough get "Upstream Contract" while Kafka gets "Topic Ingest". However, the `base.html` fallback nav still hardcodes "Upstream APIs" for the `nav_steps`-absent case. So label generalization has landed in the registry but the template fallback lags. Dense Kafka cards (9+ fields per card) still have no progressive disclosure, and structural unevenness across archetypes remains. |
| 3 — Entity Model (CRUD) / Route & Transform (Passthrough) / Route Model (Kafka) | CRUD: Phase 1 entity+operation checkboxes → Phase 2 sample bodies + mappings (revealed after save). KS field suggestion panel appears below for CRUD only. Passthrough: separate `/passthrough` page with inbound op, targets, routing, transforms all on one page. Kafka: `/kafka/routes` — pattern selection per route (fire-and-forget / request-reply), reply topics, correlation config. | `wizard_registry.py` already uses archetype-specific labels for this step: CRUD gets "Entity Model", Kafka gets "Route Model" and "Transform Mappings" as separate steps, passthrough gets "Route & Transform". However, structural unevenness remains: the passthrough router page puts inbound op + downstream targets + routing + transforms onto one long single page with no subsection navigation; Kafka and passthrough differ structurally from CRUD. KS suggestion panel is a card appended after Phase 1/2 save — not a persistent rail. |
| 4 — Handoffs / Downstream | CRUD: staging-table authoring. Passthrough: step skipped. Kafka: transforms page (`/kafka/transforms`). | Kafka and passthrough skip step 4 but nav still shows it as a step without a clear "skipped" or "not applicable" indicator. |
| 5 — Downstream | CRUD: fixed-width downstream interface authoring. Others: not applicable or redirect. | CRUD-only content. Other archetypes silently skip or redirect. |
| 6 — Rules & Legacy | Shared: business rules, `field-comparison` rules, legacy notes. | Rules page exists but is relatively thin. There is no conflict card UI, no advisory/blocking distinction, and no structured rationale capture — just a notes textarea for legacy content. |
| 7 — Review | Completeness summary (ready/warning/manual counts). KS provenance table (accepted/edited/rejected/linked evidence counts). Manifest preview (full YAML). Project summary table. | Three conceptually distinct sections (completeness, provenance, manifest preview) are stacked vertically into one dense page. Provenance is field-suggestion-only (correct scope, but no visual differentiation between human-authored vs AI-accepted). Manifest diff against a prior baseline is absent. No decision history panel. No approval action — user clicks "Proceed to Export" without an explicit approval checkpoint. |
| 8 — Export Package | 8a: Write / Validate / Assess pipeline. 8b: Generate App + Build & Run with polling. Start Over. | Already well-structured with 8a/8b sections. `evidence-trail.json` is written as a sidecar. Main gap: no compatibility check summary, no "open next revision" handoff, and the evidence trail export is not visibly surfaced or downloadable from the UI (file is written but only shown in path). |
| Knowledge Workspace | Separate page at `/knowledge` with upload/ingest, document browser, search, document viewer, field catalog browse. | Accessed only via a link on Step 1 — not embedded in the wizard flow. Search and document viewer share the same page without visual separation. Field catalog browse requires manual source/entity filter inputs rather than faceted navigation. |
| Passthrough navigation | The implemented flow is `/upstream` -> `/passthrough`. At the time of this audit, `wizard_registry.py` still pointed at non-existent routes. | **Resolved after this snapshot.** The registry now uses `/upstream` and `/passthrough`, and `tests/test_wizard_registry.py` protects the mapping. No manifest or backend contract changed. |
| Step nav completion state | Nav renders active step with `active` class but shows no completion indicators. All steps render identically regardless of whether they have been filled. | No way to tell at a glance whether prior steps are complete, have warnings, or are unfilled. |
| Right rail | Absent. KS suggestions appear as an injected card in the main pane (Step 3 CRUD only). Evidence is loaded inline via a toggle button on each suggestion card. | The absence of a right rail forces all AI assistance into the main pane, creating a dual-role page (authoring + suggestion review in the same scroll area). |
| Bottom drawer | Absent. Manifest diff and decision history do not exist in any current view. | |

**What already works well and must not be re-invented:**

- The 8-step wizard backbone is structurally sound and should remain the governed authoring frame.
- Step 8 8a/8b sectioning is a good pattern to extend.
- The KS suggestion card design (accept / edit / reject with staged-then-batch-save pattern) is well-engineered and should be the model for future suggestion surfaces.
- The save/open project file mechanic in the sidebar is clean and should be preserved.
- Step 7 provenance table columns (manifest path, status, provenance class, evidence, reviewed-at) are the right fields for a provenance view.
- Passthrough route authoring page layout (inbound op → targets → routing → transforms) is conceptually correct even if the single-page density is high.

---

## UX Goals

- Simplify the main pane: each step shows only its primary structured form, with
  detail deferred to the right rail, drawers, and tooltips.
- Progressive disclosure: dense secondary content (suggestion lists, evidence
  chains, conflict detail, manifest YAML, decision history) lives in panels, not
  inline in the scroll area.
- Unified archetype flow: CRUD, passthrough-router, and kafka-integration share
  the same numbered step shell with archetype-appropriate content per step.
- Persistent right rail for AI assistance: Suggestions, Evidence, Chat, Conflicts
  panels are always available but collapsed by default on steps where they are
  not primary.
- Governed review: Step 7 becomes a real diff / provenance / approval checkpoint,
  not just a completeness summary.
- Preserve the resolved passthrough navigation mapping: `wizard_registry.py`
  routes passthrough-router through `/upstream` and `/passthrough`, with focused
  regression coverage and no manifest or backend contract impact.
- Step nav completion indicators: completed, active, warning, and not-started
  states should be visually distinct.
- Consistent visual system: lighter enterprise tones, blue accent, clear
  card/badge/pill component language throughout.

---

## Non-Goals

- No manifest schema redesign within this UX work. The active cross-repo contract is
  now manifest `schema_version: "2.0"` under the later coordinated version cut.
- No freeform chat-first UI. The wizard backbone is not replaced by a chat surface.
- No collapsing archetypes into identical forms. CRUD, passthrough-router, and
  kafka-integration each have their own step content — the shell unifies them,
  not the content.
- No production behavior changes. This document does not change routes, session
  models, manifest generation, Engine integration, or KS integration.
- No backend MCP contract changes. The KS tool vocabulary and the Engine MCP
  seven-tool surface are unchanged.
- No multi-user or authentication work was part of this April 2026 design. Shared
  multi-session isolation shipped later; real proxy/OIDC authentication remains deferred.
- No React/SPA rewrite. The Jinja2/vanilla-JS architecture is preserved.
- No staged downstream implementation. That remains explicitly deferred.
- No LegacyExtractor integration. LE attachment points are described as future
  extension slots, not part of this baseline.

---

## Design Principles

1. **Governance first.** The wizard-backed sequential flow is never replaced by AI
   shortcuts. AI assistance prepares drafts; humans approve every step.

2. **Progressive disclosure.** Dense detail — suggestion lists, evidence chains,
   conflict cards, manifest YAML, decision history — lives in right-rail panels,
   drawers, and tooltips. The main pane shows only the primary authoring form.

3. **Archetype-aware, shell-unified.** All three archetypes (CRUD, passthrough-
   router, kafka-integration) share one shell and one numbered step nav. The step
   content differs per archetype; the navigation model does not.

4. **Honest completion state.** The step nav always reflects actual state:
   completed, active, warning, skipped/not-applicable, and not-started are
   visually distinct.

5. **Evidence stays explicit.** AI suggestions must carry citations and provenance
   class. Evidence is not buried in chat logs or implicit model memory.

6. **Additive by default.** Every UX change either adds UI surface to existing
   routes or changes visual presentation. No change removes existing functionality
   or alters data contracts.

7. **Conflict surfaces clearly, does not block quietly.** Unresolved conflicts
   must be visible in Step 6 and summarized in Step 7. Blocking vs advisory
   distinction must be explicit, not implicit.

8. **Review is a checkpoint, not a formality.** Step 7 is the structured review
   point — completeness, provenance, advisory signals. Step 8 executes the
   export. In the v2 baseline, Step 7 provides a "Mark as reviewed" posture
   indicator but does not hard-gate the export. A full blocking approval gate is
   a deferred follow-on slice.

---

## Shared Studio v2 Shell

### ASCII layout sketch

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  EdgeForge Studio                 [DDA App]  [crud]          Step 3 of 8   │
├────────────┬────────────────────────────────────┬────────────────────────────┤
│  STEP NAV  │                                    │  RIGHT RAIL                │
│            │           MAIN PANE                │                            │
│  1 ● done  │                                    │  [▸ Suggestions]           │
│  2 ● done  │   Step-specific structured form    │  [▸ Evidence]              │
│  3 ► active│   (primary authoring content only) │  [▸ Chat]                  │
│  4 ○ open  │                                    │  [▸ Conflicts]             │
│  5 ○ open  │   No suggestion lists here in      │                            │
│  6 ○ open  │   the main pane — those live       │  Rail is open by default   │
│  7 ○ open  │   in the right rail.               │  on Steps 2–6.             │
│  8 ○ open  │                                    │  Collapsed by default      │
│            │                                    │  on Steps 1, 7, 8.         │
│  ─────     │                                    │                            │
│  ↓ Save    │                                    │  Width: ~280px (resizable) │
│  ↑ Open    │                                    │  Collapse toggle: ›        │
├────────────┴────────────────────────────────────┴────────────────────────────┤
│  BOTTOM DRAWER (collapsed by default; opens automatically on Step 7)         │
│  [Manifest Diff]  [Decision History]  [Completeness]  [Evidence Coverage]   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Shell element definitions

**Header bar**
- Brand name (left), project name + archetype pill (center), step indicator
  "Step N of 8" (right).
- On narrow windows (< 900px), header collapses project name; step indicator
  moves to a floating chip.

**Left step nav**
- Fixed width ~180px.
- Each step shows: step number badge, step label, completion indicator.
- Completion indicator states:
  - `●` filled blue dot — step completed with no warnings
  - `●` filled amber dot — step completed with warnings
  - `►` active triangle — current step
  - `○` hollow circle — not yet visited
  - `–` dash — not applicable for this archetype (e.g., Step 4 for passthrough)
- Save Project / Open Project controls remain at the bottom of the nav, unchanged.
- Nav is not scrollable — all 8 steps must fit in the available height. On very
  short viewports (< 600px), the nav collapses to icon-only mode.

**Main pane**
- Fills the remaining width after nav and rail.
- Contains only the step's primary structured form.
- KS suggestion lists, conflict detail, and evidence chains do NOT appear inline
  in the main pane in v2. They appear in the right rail.
- Exception: the Step 6 conflict workbench surfaces conflict cards in the main
  pane as first-class authoring decisions, not suggestions.
- Step actions (Save & Continue, Back) remain in the main pane at the bottom of
  the form.

**Right rail**
- Default width ~280px. Resizable by drag. Collapse toggle `›` at the rail edge.
- Contains four panels: Suggestions, Evidence, Chat, Conflicts.
- Each panel is independently collapsible with an accordion toggle.
- Rail is open by default on Steps 2–6.
- Rail is collapsed by default on Steps 1, 7, and 8.
- On narrow windows (< 900px), the rail appears as a slide-in drawer triggered
  by a floating "AI" button in the corner of the main pane.

**Bottom drawer**
- Collapsed by default on all steps.
- Opens automatically when Step 7 is loaded.
- Contains four tabs: Manifest Diff, Decision History, Completeness, Evidence Coverage.
- A persistent toggle button in the header bar allows manual open/close.
- On narrow windows, the drawer appears as a full-width slide-up panel.

---

## Step-by-Step v2 Flow

### Step 1 — Project Setup + Ingest Kickoff

**Intent:** Define project identity, choose archetype, configure paths, and
kick off document ingest for the Knowledge Workspace. This step initializes the
project-scoped workspace namespace.

**Main pane:**
- Same form as today: app name, bounded context, archetype selector, target
  profile, output path, repo path.
- Below the form (not a separate card): a compact "Knowledge Workspace" status
  subpanel showing:
  - workspace namespace (project_id) if already linked
  - document count if KS is active
  - "Open Knowledge Workspace" button (links to `/knowledge` as today)
  - degraded indicator if KS is unavailable
- The Knowledge Workspace subpanel replaces the current separate card and brings
  ingest kickoff into the same visual flow as project setup.

**Recommendation for KS placement at Step 1:**
The Knowledge Workspace should be a compact status subpanel within Step 1's
main form card — not a side card, not a full subpage, not a modal. It shows
workspace state and offers a launch point. The full workspace UI remains at
`/knowledge` for detailed upload and browsing. This preserves the current
routing contract while improving visual coherence.

**Right rail:** Collapsed at Step 1. No suggestions available before archetype
and upstream contract are defined.

**What is deferred to rail/drawer:** Nothing at Step 1. Workspace status is
in the main pane.

**CRUD behavior:** Standard setup + KS subpanel.
**Passthrough behavior:** Standard setup + KS subpanel; archetype note about
constrained contract scope.
**Kafka behavior:** Standard setup + KS subpanel; Kafka archetype note shows
next step is `/kafka/topics` not `/upstream`.

---

### Step 2 — Upstream Ingest (archetype-specific label)

**Intent:** Ingest the upstream contract that defines the inbound interface.
The visible step label is archetype-specific (per `wizard_registry.py`):
- CRUD: **"Upstream Contract"**
- passthrough-router: **"Upstream Contract"**
- kafka-integration: **"Topic Ingest"**

These are the registry-defined labels. The conceptual purpose is the same across
archetypes (ingest the upstream interface definition), but the label the user sees
differs. The old fallback nav label "Upstream APIs" is incorrect for all archetypes
and should be replaced by the registry-defined label per archetype.

**Main pane:**
- CRUD: URL/upload/paste for OpenAPI spec (unchanged from current `/upstream`)
  with archetype label "OpenAPI / REST upstream contract."
- Passthrough-router: same ingest UI with label "Inbound REST contract."
- Kafka: consumer group config + topic pair cards with label "Kafka topic and
  schema ingest."
  - Kafka cards maintain current field structure but use progressive disclosure:
    advanced config (retry, DLQ, reply topics) hidden behind "Advanced" toggle
    per card. This reduces initial card height significantly.

**Right rail:** Open. Suggestions panel may show KS-sourced contract hints
(currently not implemented — rail shows empty state with "Upload documents in
the Knowledge Workspace to enable suggestions here").

**What is deferred to rail/drawer:** Evidence panel shows relevant document
snippets if the user asks about a topic name or operation name via the Chat
panel. This is a future KS capability, not baseline v2.

**CRUD behavior:** OpenAPI spec ingest as today. Step label updated.
**Passthrough behavior:** Same ingest as today. Step label updated.
**Kafka behavior:** Topic pairs with progressive disclosure for advanced config.
Route name, upstream topic, downstream topic shown by default. Schemas,
reply topics, correlation config behind toggle.

---

### Step 3 — Domain or Route Model Authoring

**Intent:** Define the internal model (entities + operations for CRUD), the
route model (passthrough routing logic), or the async route model (Kafka
fire-and-forget / request-reply patterns). The step label "Domain or Route
Model Authoring" works for all three archetypes.

**Main pane:**
- CRUD: Entity + operation selection (Phase 1) then samples + mappings (Phase 2),
  unchanged from today. KS field suggestion panel MOVES to the right rail
  (see right rail spec below). This is the key v2 change for Step 3.
- Passthrough-router: The current single-page approach is split into two visible
  sub-sections within Step 3:
  - Sub-section A (always visible): Inbound operation selector + downstream
    target cards.
  - Sub-section B (revealed after targets are saved): Routing rows + default
    target.
  Transform mappings move to Step 4 (or remain in Step 3b if keeping archetype
  compact). This design required the then-broken registry mapping to be aligned
  with `/upstream` and `/passthrough`. That correction has since shipped and is
  covered by the wizard-registry tests; it did not add routes or change a contract.
- Kafka: Route model cards (`/kafka/routes`) become Step 3b after topics saved.
  Shows fire-and-forget vs request-reply pattern per route. Advanced reply fields
  remain behind a toggle per card.

**Right rail (CRUD):** Open. Suggestions panel shows KS field suggestions
for the currently selected entity. This replaces the current inline KS suggestion
panel. Evidence panel shows per-suggestion evidence on selection. Conflict panel
shows any field-level conflicts detected by KS (currently shown as `conflict_hint`
inline — moves to right rail Conflicts panel).

**Right rail (passthrough/Kafka):** Open but shows empty Suggestions state
(future LE/KS work). Evidence panel available for chat-based lookup.

**What is deferred to rail/drawer:** Suggestion accept/edit/reject actions remain
in the right rail Suggestions panel. Evidence chains are in the Evidence panel.
Phase 2 samples and mappings remain in the main pane (they are authoring inputs,
not AI suggestions).

---

### Step 4 — Handoffs / Integration Contract Authoring

**Intent:** Define staging tables (CRUD), integration contract details
(passthrough), or transform mappings (Kafka). Renamed from "Data Handoffs."

**Main pane:**
- CRUD: Staging-table authoring (unchanged).
- Passthrough: Integration-level contract notes (currently no dedicated step —
  v2 makes this explicit as a pass-through confirmation of the downstream targets
  already entered in Step 3).
- Kafka: Transform mappings (`/kafka/transforms`) become Step 4 for the Kafka
  path.

**Right rail:** Open. Future KS staging-field prefill suggestions would appear
here. Currently empty state.

**What is deferred:** Staging field suggestions (future KS).

---

### Step 5 — Downstream Interface Authoring

**Intent:** Define the downstream output interface. For CRUD this is fixed-width
file authoring. For passthrough this step is not applicable (routing and targets
were defined in Step 3). For Kafka this step is not applicable (downstream topics
defined in Step 2).

**Main pane:**
- CRUD: Fixed-width downstream interface authoring (unchanged).
- Passthrough: Step shows "Not applicable for passthrough-router" with a nav
  indicator of `–` (skipped).
- Kafka: Step shows "Not applicable for kafka-integration" with a nav indicator
  of `–` (skipped).

**Right rail:** Open for CRUD. Collapsed for passthrough/Kafka (skipped).

---

### Step 6 — Rules, Mappings, and Conflict Workbench

**Intent:** Author business rules, field-comparison rules, legacy notes, and
resolve any detected conflicts. This becomes the richest decision workbench in
Studio v2.

**Main pane:**
- Rules form (unchanged): rule type, rule fields, legacy notes textarea.
- Conflict cards: new in v2. Any conflicts detected (by KS or flagged during
  Step 3 suggestion review) appear as structured cards in the main pane:
  - conflict description
  - source A vs source B
  - advisory or blocking indicator (badge)
  - resolution choices: "Accept A", "Accept B", "Override with custom rule"
  - resolution rationale text field
- Conflict cards appear above the rules form when unresolved conflicts exist.
- Resolved conflicts collapse and are shown as a count badge.

**Right rail:** Open. Suggestions panel shows KS-sourced rule and mapping
suggestions (future scope — currently empty state per current KS field-only MVP).
Conflicts panel shows the full conflict list (summary mirror of main-pane cards).

**What is deferred to rail/drawer:** Detailed evidence for each conflict lives in
the Evidence panel. Rule suggestions (future KS scope).

---

### Step 7 — Diff, Provenance, and Decision History

**Intent:** Approve the manifest snapshot. This is the explicit approval
checkpoint before export. The user sees a structured review of what was authored,
what AI suggested (and how it was handled), what conflicts remain, and how the
manifest differs from any prior baseline.

**Main pane:**
- Completeness summary widget (ready/warning/manual counts) — kept from today.
- Review posture card (Option B — no hard gate):
  - Summary of advisory conflict signals from KS suggestion review
  - Summary of pending suggestions not yet reviewed
  - Summary of low-confidence accepted items
  - "Mark as reviewed" posture indicator — sets `review_approved` session flag;
    advisory only, does not block export (requires small session addition + `/review/approve` route)
  - "Proceed to Export →" link — unchanged from today, no blocking gate
- Compact provenance summary (4 counters: accepted, edited, rejected, linked
  evidence) — kept from today's design.

**Bottom drawer (opens automatically at Step 7):**
- Tab 1 — Manifest Diff: shows the full manifest YAML diff against the prior
  approved baseline (if one exists), or the full manifest if no prior baseline.
  Diff lines show `+` / `-` with color. If no prior revision exists, shows
  full manifest in read-only view.
- Tab 2 — Decision History: shows the full provenance table from today's Step 7
  (manifest path, status, provenance class, evidence, reviewed-at). Filterable
  by status and provenance class. This moves the provenance table out of the main
  pane and into the drawer.
- Tab 3 — Completeness: shows the full item-by-item completeness report
  (ready/warning/manual items) that is currently in the main pane. Moves to
  drawer to reduce main pane density.
- Tab 4 — Evidence Coverage: shows a count of fields with linked evidence vs
  fields without. Points to gaps.

**Right rail:** Collapsed at Step 7 by default. Can be opened manually to query
the Chat panel.

**What is deferred to drawer:** The full manifest YAML preview moves to the
bottom drawer Manifest Diff tab. The full provenance table moves to the Decision
History tab. The full completeness item list moves to the Completeness tab.

---

### Step 8 — Export, Validate, Generate, Build, Run, Verify

**Intent:** Execute what was approved in Step 7. Write the manifest package,
validate, assess, generate, build, run, and verify. This step is well-structured
today and requires minimal changes.

**Main pane:**
- 8a: Manifest Package section (Write / Validate / Assess / Download ZIP) —
  unchanged.
- Evidence trail note: a visible "evidence-trail.json will be written alongside
  app-definition.yaml" indicator, with a direct download link for the
  evidence-trail.json file after writing.
- 8b: Engine Actions section (Generate / Build / Run / Stop) — unchanged.
- Manifest revision checkpoint indicator: after successful export+write, show
  the revision number and timestamp that was captured in session state.
- "Open next revision" hint (future): a grayed-out note at the bottom of 8b
  pointing to a future capability to reopen this project workspace against the
  approved baseline for a subsequent enhancement cycle.

**Right rail:** Collapsed at Step 8 by default.

**What is deferred:** Compatibility check summary (future Engine capability).
Post-generation evolution mode (future feature).

---

## Archetype Step Matrix

| Step | CRUD | passthrough-router | kafka-integration |
|------|------|--------------------|-------------------|
| 1 | Project setup + KS subpanel | Project setup + KS subpanel | Project setup + KS subpanel |
| 2 | **"Upstream Contract"** — OpenAPI / REST upstream contract ingest | **"Upstream Contract"** — Inbound REST contract ingest | **"Topic Ingest"** — Kafka topic + schema ingest |
| 3 | Entity + operation selection; KS field suggestions in right rail | Inbound op + downstream targets + route rows | Kafka route model authoring (fire-and-forget / request-reply) |
| 4 | Staging table / data handoff authoring | Integration contract confirmation (passthrough) | Kafka transform mappings |
| 5 | Downstream fixed-width interface authoring | Not applicable (`–`) | Not applicable (`–`) |
| 6 | Rules, legacy notes, conflict workbench | Rules, legacy notes, conflict workbench | Rules, legacy notes, conflict workbench |
| 7 | Shared: diff / provenance / approval | Shared: diff / provenance / approval | Shared: diff / provenance / approval |
| 8 | Shared: export / validate / generate / build / run | Shared: export / validate / generate / build / run | Shared: export / validate / generate / build / run |

---

## Right-Rail Panel Specs

### Suggestions Panel

| Attribute | Spec |
|-----------|------|
| Primary purpose | Show AI-sourced field suggestions (KS) with accept / edit / reject actions |
| Appears on steps | 2, 3, 4, 5, 6 |
| Default state | Open on Steps 3–4; collapsed (header visible) on Steps 2, 5, 6 |
| Read-only or action | Action-oriented: Stage Accept, Stage Edit & Accept, Stage Reject per suggestion |
| Current KS scope | CRUD Step 3 field-review only (per PR #69) |
| Future LE scope | LE-sourced rule/mapping candidates would appear as additional suggestion cards with `origin: legacy-extractor` badge |
| Key UX behavior | Suggestion cards show: field name, confidence/consistency score, source count, origin badge, persisted status badge. Evidence toggle expands inline within the panel (not a separate panel call). Save suggestion review button at top of panel — consistent with current batched write-back design. Empty state message when KS is unavailable or no suggestions exist for the current selection. |

### Evidence Panel

| Attribute | Spec |
|-----------|------|
| Primary purpose | Show citation trail for the currently selected suggestion or an approved field |
| Appears on steps | 2, 3, 4, 5, 6, 7 (read-only at Step 7) |
| Default state | Collapsed unless a suggestion is selected in the Suggestions panel |
| Read-only or action | Read-only |
| Current KS scope | Evidence chains from `get_field_evidence_chain` tool — document name, section, snippet (per PR #69) |
| Future LE scope | LE extraction source indicator added to evidence entries: provenance lines showing `extraction-source: <copybook-name>` |
| Key UX behavior | Opens automatically when user clicks "Evidence" on a suggestion card or on a field row in Step 7 decision history. Shows source document, section heading, and snippet. Multiple evidence chunks listed. If no evidence exists, shows explicit "No evidence linked" state. |

### Chat Panel

| Attribute | Spec |
|-----------|------|
| Primary purpose | Q&A against the project Knowledge Workspace — lookup, not authoring |
| Appears on steps | 1–8 (always available in rail) |
| Default state | Collapsed by default on all steps |
| Read-only or action | Action: user enters question, receives cited answer |
| Current KS scope | Not yet implemented in Studio — future KS `search_and_answer` tool attachment point |
| Future LE scope | Chat answers can cite LE-extracted structural artifacts by document name and field |
| Key UX behavior | Input field + submit. Responses show answer text + citation list (document name, section). Chat history is session-local, not persisted. Explicit note: "Chat is for lookup only. Decisions require explicit accept/edit/reject in the Suggestions panel." |

### Conflicts Panel

| Attribute | Spec |
|-----------|------|
| Primary purpose | Surface detected contradictions and their resolution status |
| Appears on steps | 3, 4, 5, 6 |
| Default state | Collapsed unless unresolved conflicts exist; badge count shown on collapsed header |
| Read-only or action | Action at Step 6 (resolve); read-only summary mirror at Steps 3–5 |
| Current KS scope | Currently: `conflict_hint` string on field suggestion cards. In v2 baseline this becomes an advisory conflict signal panel — not a fully structured conflict workbench (which requires a later slice with model extension). |
| Future LE scope | LE may surface structural conflicts (e.g., field type mismatch between copybook and OpenAPI) that flow into this panel |
| Key UX behavior | Baseline: conflict hint signals from suggestion cards shown as advisory entries with amber badge. Summary count badge on collapsed panel header. Panel provides navigation context to Step 6 advisory section. Full structured conflict cards (source A vs source B, resolution choices, blocking/advisory determination) are a later slice requiring conflict_resolutions model population. No hard blocking gate on export in the v2 baseline. |

---

## Conflict-Resolution Model

### Current shipped state (honest baseline)

What exists today in `ks_workspace_state`:
- `conflict_resolutions: list[KSConflictResolution]` — the field exists in the model
  (`KSWorkspaceState` in `app/models/project.py`) but is not populated by any current
  route or integration. It is a reserved schema slot, not a live data feed.
- `conflict_hint` — present as a string on individual KS suggestion payloads surfaced
  via `suggest_fields`. This is a display/advisory signal attached to suggestions, not
  a durable structured conflict record.

What this means for v2 baseline design:
- A fully structured per-conflict resolution workflow (accept/reject/resolve per
  conflict with durable stored records) cannot be built today from already-persisted
  conflict data — `conflict_resolutions` is empty for all projects.
- An Issues/Conflicts advisory panel **can** be built today using `conflict_hint`
  strings from suggestion payloads. However, those suggestion payloads are produced
  by a **live call** to `/entities/ks/suggestions` (which calls `suggest_fields` on
  the KS client) — they are not persisted as durable suggestion rows in session state.
  What the session persists is: review buckets (`accepted_ids`, `rejected_ids`,
  `edited_ids`), `review_history` entries, and `evidence_links`. Raw suggestion
  payloads and `conflict_hint` strings are not stored durably. Therefore the advisory
  baseline depends on either a lightweight re-fetch of current KS suggestions for the
  active context, or a client-side cache of suggestion signals currently displayed in
  the browser — not on reading durable persisted conflict rows that already exist today.
- A full conflict workbench with durable resolution records would require a light model
  extension to populate `conflict_resolutions` from detected divergences, and a new
  route to write those records. That is a follow-on slice, not baseline.

### v2 Baseline: Issues/Conflicts advisory panel

For the baseline, the Conflicts panel in the right rail surfaces:
1. `conflict_hint` strings from suggestion cards — advisory signals from KS indicating
   where a suggested field may conflict with another source or with the current spec.
2. Any current-step warnings accumulated during suggestion review (low confidence,
   multi-source disagreement indicators present in suggestion payloads).

Visual treatment for advisory panel entries:
- Amber border + "ADVISORY" badge for `conflict_hint` warning signals.
- No "BLOCKING" badge at baseline — blocking conflict determination requires structured
  conflict records that are not yet populated.
- Panel header shows count badge (e.g., "3 advisory signals") when collapsed.

### Full conflict workbench (later slice — requires light backend support)

A full structured conflict workbench (blocking vs advisory, per-conflict resolution
choices with rationale, durable storage in `conflict_resolutions`) is deferred to a
later slice. It requires:
- A conflict detection pass that populates `conflict_resolutions` from detected
  divergences (KS suggestion vs session entity field type, etc.)
- A new route or endpoint to write resolution decisions back to session state
- Extension of `evidence-trail.json` sidecar to include resolution records

This is listed in Potential Future Functional Follow-ons, not in the baseline
Implementation Slices.

### Where the user interacts with advisory signals (baseline)

- Right rail Conflicts panel: summarizes advisory signals during Steps 3–6.
- Step 6 main pane: shows grouped conflict hint signals above the rules form.
  Resolution in the baseline means acknowledging and optionally recording a note
  in the existing legacy_notes textarea, not a structured accept/reject action.
- Step 7: conflict advisory summary is shown in the posture card (count of
  unacknowledged advisory signals). No hard blocking gate at baseline.

### How to avoid overwhelming the main pane

- Conflict advisory signals are shown only at Step 6, not on earlier steps.
- On earlier steps, the Conflicts panel in the right rail provides a read-only
  summary view.
- Acknowledged signals are collapsed at Step 6 — only their count is shown.
- The main pane at Step 6 shows conflict advisory signals ABOVE the rules form.
  If zero signals exist, the conflict section is absent entirely.
- Advisory signals are grouped by entity/field.
- Maximum visible entries before "Show more" pagination: 5 per page.

---

## Step 7 — Diff, Provenance, and Decision History

### Step 7 approval posture: Option B (no hard gate in baseline)

The v2 baseline adopts **Option B** for Step 7:

- No hard approval gate. The existing "Proceed to Export" link to `/export/write`
  and `/export/generate` is unchanged and never blocked.
- Step 7 adds an optional **"Mark reviewed" / "Ready for export" posture indicator**:
  a toggle or button that sets a small `review_approved` flag in session state.
  This is advisory — it communicates review intent but does not disable the export flow.
- A small `review_approved` boolean added to session state is acceptable and sufficient
  for this posture indicator. This requires a new `/review/approve` POST route (light
  backend addition — not pure UI-only).
- The export routes (`/export/write`, `/export/generate`) remain unchanged and do not
  check `review_approved` before proceeding.
- A full hard approval gate (export disabled until approved, blocking on unresolved
  conflicts) is deferred to a later slice and would require additional state support
  and explicit product decision.

This resolves the earlier ambiguity in the doc between "Approve for Export" as a hard
gate versus a posture indicator. The baseline is clearly the softer posture approach.

### Layout of Step 7 in v2

The Step 7 main pane is deliberately lighter than today:
- Completeness summary widget (3 counters) — top of main pane
- Review posture card — below completeness (shows advisory conflict signals and
  suggestion review status; includes "Mark as reviewed" action)
- "Proceed to Export →" link remains as today, unchanged behavior

The bottom drawer opens automatically and provides the dense detail:

### How manifest diff is shown

Bottom drawer > Manifest Diff tab:
- If a prior revision exists in `session.manifest_revisions`: shows a unified
  diff of the current manifest YAML against the most recent approved revision.
  Lines prefixed `+` shown in green, `-` in red, unchanged lines in gray.
  Diff is rendered as a read-only pre block with syntax-aware line coloring.
- If no prior revision exists: shows the full current manifest YAML in read-only
  view with a note "No prior baseline — showing full manifest."
- A "Copy YAML" button allows clipboard copy.
- The Manifest Preview that exists today (`<pre id="manifest-preview">`) moves
  from the main pane into this drawer tab.

### How provenance is shown

Bottom drawer > Decision History tab:
- The provenance table from today's Step 7 becomes this tab's content.
- Provenance class badges: `human-authored` (no AI involvement),
  `ai-accepted` (AI suggestion accepted unchanged), `ai-edited` (AI suggestion
  accepted with user edits), `superseded` (overridden by later decision),
  `rejected` (suggestion rejected, human authored instead).
- The "human-authored" provenance class is new in v2: any field in the manifest
  that has no associated KS suggestion or where the suggestion was rejected is
  classified as `human-authored` for provenance purposes.
- Filter controls: filter by status (accepted / edited / rejected), provenance
  class, and entity name.

### How decision history is surfaced

The Decision History tab also shows conflict advisory signals from Step 6 as a
separate sub-section:
- In the v2 baseline: advisory conflict hint signals acknowledged during Step 6,
  shown with field name, hint text, and acknowledged timestamp (if acknowledged).
- Unacknowledged advisory signals shown with an amber "ADVISORY" badge.
- Note: full structured conflict resolutions (conflict description, resolution
  choice A/B/override, rationale, blocking/advisory determination) are a later
  slice once `conflict_resolutions` model population is implemented. They will
  appear as an additional sub-section here when available.

### How completeness and review posture are shown

Main pane > Review Posture card:
- 3 completeness counters (from today): ready, warnings, manual follow-up.
- Advisory conflict signal summary: N advisory signals from KS suggestion review.
- Suggestion summary: Z pending suggestions not yet reviewed.
- Low-confidence note: N accepted items have consistency score < 0.5.
- "Mark as reviewed" / "Ready for export" posture indicator: sets `review_approved`
  in session state as an advisory flag. Does NOT block the export flow.
- "Proceed to Export →" link remains as today, unchanged behavior. No gating.

Note: a hard "Approve for Export" gate that disables export until approved is
deliberately deferred. The posture indicator communicates intent without blocking.

### How to keep it powerful but not cluttered

- The main pane at Step 7 shows only the review posture summary — not the
  full manifest YAML, not the full provenance table, not the full completeness
  item list.
- All dense detail is in the bottom drawer tabs.
- The bottom drawer opens automatically when Step 7 loads.
- Users who only want to proceed quickly can ignore the drawer and click
  "Proceed to Export."
- Users who want to govern carefully use the drawer and optionally mark the
  session as reviewed before proceeding.

---

## Knowledge Server Now / LegacyExtractor Later

### Current KS-backed UX (what is already in Studio through PR #70)

| Surface | Location | What it does |
|---------|----------|--------------|
| Knowledge Workspace | `/knowledge` page | Upload / ingest, document list, search, document viewer, field catalog browse |
| KS workspace subpanel | Step 1 main pane | Workspace namespace display + launch link |
| KS field suggestion panel | Step 3 CRUD main pane (inline card) | Accept / edit / reject per field suggestion; batched write-back |
| KS provenance review | Step 7 main pane (table) | Per-field review history with provenance class and evidence status |
| evidence-trail.json | Step 8 sidecar export | Links accepted suggestions to manifest field paths with evidence metadata |

### Future LE attachment points (clean extensions, not retrofits)

| Attachment point | Where it slots in | What LE would provide |
|-----------------|-------------------|----------------------|
| Step 1 Knowledge Workspace subpanel | Add "Structural sources" ingest section alongside document ingest | COBOL copybook / PL-SQL / DDL source uploads for deterministic extraction |
| Step 2 right rail Suggestions panel | Add `origin: legacy-extractor` suggestion cards | Extracted field candidates from copybooks / DDL |
| Step 3 right rail Suggestions panel | Add `origin: legacy-extractor` entity/field suggestions | Extracted entity and field shapes |
| Step 6 conflict cards | Add conflicts sourced from LE structural analysis | Type mismatches, field name discrepancies between legacy source and OpenAPI contract |
| Step 7 Decision History tab | Add `extraction-source` column | Which LE document backed each accepted LE-sourced suggestion |
| Step 8 evidence-trail.json | Extend sidecar schema | Include LE provenance rows alongside KS provenance rows |

**Design rule:** LE attachment points are designed as additive cards / rows /
sections with a clear `origin` label. They do not replace existing KS surfaces.
The suggestion card design (origin badge, confidence, citations, accept/edit/reject)
is the same for KS and LE sourced suggestions — only the origin badge differs.

---

## Visual System Direction

**Color direction:**
- Background: `#f8fafc` (very light blue-gray) for the page, `#ffffff` for cards.
- Primary accent: `#2563eb` (blue-600) for active steps, primary buttons, and
  progress indicators.
- Success: `#16a34a` (green-600) for ready states, accepted decisions.
- Warning: `#d97706` (amber-600) for warnings, advisory conflicts.
- Danger: `#dc2626` (red-600) for errors, blocking conflicts, manual follow-up.
- Border: `#e2e8f0` for card borders, `#cbd5e1` for table rows.
- Muted text: `#64748b` for hints and secondary labels.

**Typography:**
- Heading hierarchy: h2 (20px, 700) for step titles, h3 (16px, 600) for section
  headers within steps, h4 (14px, 600) for sub-sections.
- Body: 14px, 400 weight. Hints and muted labels: 12px.
- Code: monospace for manifest paths, field names, topic names.

**Component language:**
- Cards: white background, 8px border-radius, 1px border, 16px internal padding.
  Current card design is correct — no change.
- Badges: `badge-entity` (blue), `badge-draft` (gray), `badge-manual` (red),
  `badge-warning` (amber). Add: `badge-advisory` (amber), `badge-blocking` (red),
  `badge-ai-accepted` (blue), `badge-ai-edited` (purple), `badge-human` (gray).
- Progress indicators in step nav: filled/hollow/active dots as specified above.
- Conflict cards: left border color indicates severity (amber for advisory, red
  for blocking).
- Drawers: slide animation from bottom (200ms ease-out). Right rail: slide from
  right (150ms ease-out).
- Tooltips: appear on hover over any badge or truncated label, max-width 240px.

**Motion:**
- Smooth transitions for drawer open/close and right-rail expand/collapse.
- No flashy or distracting animations. Enterprise calm.
- Loading states use existing `.spinner` class (already in the codebase).

**Governed / auditable feel:**
- Review posture is always explicit: the "Mark as reviewed" indicator is visually
  distinct from the "Proceed to Export" link. Both are present; neither blocks.
- Step completion indicators make project state legible at a glance.
- Conflict badges show count even when the Conflicts panel is collapsed.
- Suggestion count in the right rail header badge when panel is collapsed.

---

## Backend / Contract Invariants To Preserve

The UX redesign must not assume it can change any of the following:

- `schema_version: "2.0"` manifest contract — any fields
  added to session state for approval posture or conflict tracking must not leak
  into the manifest YAML.
- `studio_project_schema_version: "1.4"` save/open schema — conflict decisions
  and approval state may be added as optional new keys, but existing keys must
  not be renamed or removed.
- CRUD entity/operation data shape, passthrough route/transform shape, and Kafka
  topic/route/transform shape in the session model — the main pane forms write
  to these shapes exactly as today.
- Engine deterministic generation contract — manifest YAML produced by the wizard
  must remain identical to what Engine expects. UX changes do not alter manifest
  generation logic.
- KS MCP boundary and current tool vocabulary — the right rail Suggestions
  panel calls the same `suggest_fields`, `submit_suggestion_decisions`, and
  `get_field_evidence_chain` KS tools as today, just from a new display location.
- Current bounded KS MVP scope: field-review only at Step 3 CRUD. Moving the KS
  suggestion panel to the right rail does not expand the scope of which steps or
  archetypes receive KS suggestions.
- Engine MCP seven-tool surface — unchanged.
- Route URLs: `/`, `/upstream`, `/entities`, `/handoffs`, `/downstream`, `/rules`,
  `/review`, `/export`, `/passthrough`, `/kafka/topics`, `/kafka/routes`,
  `/kafka/transforms`, `/knowledge` — all route URLs must remain stable. New
  views are added as new routes or are purely CSS/JS rearrangements.
- The `evidence-trail.json` sidecar schema — conflict resolutions are added as
  an additive new section, not as changes to existing fields.

---

## Recommended UX v2 Baseline

### Summary of what changes

Changes below are split honestly into two categories:

**Truly UI-only (no route, session, or model changes required):**
- Shell: add persistent right rail (CSS + JS toggle), add bottom drawer with
  tabs (CSS + JS), add step completion indicators to nav.
- Step 1: integrate Knowledge Workspace as a subpanel within the project setup
  card instead of a separate card below.
- Step 2: align label copy with registry labels (template fallback already lags
  the registry); add progressive disclosure for Kafka card advanced fields.
- Step 3: move KS suggestion panel from main pane inline card to right rail
  Suggestions panel (reuses `/entities/ks/suggestions`, `/entities/ks/evidence`,
  `/entities/ks/review` endpoints unchanged); split passthrough Step 3 into two
  visible sub-sections within the same page.
- Step 6: add structured Issues/Conflicts advisory panel — **UI-first with lightweight
  re-fetch or client-side cache of KS suggestion signals; no new durable conflict model
  needed for the advisory baseline**. The `conflict_hint` strings come from a live call
  to `/entities/ks/suggestions`, not from persisted conflict rows. Add advisory badge
  rendering for fields where KS provides a conflict hint.
- Step 8: add visible `evidence-trail.json` download link after write; add
  manifest revision checkpoint indicator.
- Passthrough navigation correction: completed by aligning the registry with
  `/upstream` and `/passthrough`; focused regression coverage preserves the mapping
  with no manifest or backend contract impact.

**UI-first with light Studio state/route support needed (NOT purely UI-only):**
- Step 7 optional review posture indicator: adding a `review_approved` flag in
  session state is acceptable and sufficient for a baseline "Mark reviewed" posture
  indicator, but requires a small session/model addition and likely a new
  `/review/approve` route.
- Full structured conflict resolution workflow (accept/reject/resolve per conflict
  with durable storage): the current `ks_workspace_state.conflict_resolutions` field
  exists in the model but is unpopulated today. A full per-conflict decision workflow
  would need a light model extension to populate and read structured conflict records.

### Summary of what stays the same

- All existing routes and URL paths.
- All existing session model fields (no removals or renames).
- All manifest generation logic.
- All KS integration logic.
- All Engine integration logic.
- All save/open project logic.
- All existing completeness report logic.
- All existing evidence trail sidecar logic.

### Concise statement of scope

Studio v2 baseline is primarily a **visual and structural redesign of the Jinja2
templates and their accompanying JavaScript** — adding the right rail, bottom drawer,
step completion indicators, and reorganizing existing content between main pane and
drawer/rail. Most slices are truly UI-only. Step 7 posture and full conflict workbench
are UI-first but require acknowledged light backend support.

---

## Potential Future Functional Follow-ons

These are NOT part of the baseline recommendation. They require backend or MCP
changes and are listed here as a parking lot.

- **Richer KS suggestion scopes**: rule suggestions, mapping suggestions, and
  route/config suggestions flowing into the right rail Suggestions panel at Steps
  4–6. Requires KS tool scope expansion.
- **Manifest prefill from accepted suggestions**: accepted field suggestions
  directly pre-populate entity field definitions in the main pane forms. Requires
  a deliberate prefill contract design.
- **LegacyExtractor integration**: LE-sourced suggestions in the Suggestions
  panel with `origin: legacy-extractor` badge. Requires Phase 6 LE design and
  implementation.
- **Chat panel Q&A**: right rail Chat panel connected to KS `search_and_answer`
  tool for cited Q&A against uploaded documents. Requires KS tool surface
  extension.
- **Manifest diff against remote baseline**: Step 7 diff against a server-stored
  prior approved revision. Currently diff can only be shown against in-session
  revision history.
- **Post-generation evolution mode**: reopen project, ingest updated BRDs,
  compare against approved manifest baseline, propose safe enhancements.
- **Better passthrough ingest flow**: if Engine broadens passthrough contract,
  Studio can expose richer target modeling.
- **Structured conflict detection**: programmatic conflict detection between KS
  catalog fields and user-authored entities. Currently `conflict_hint` is a KS-
  sourced string. Future: Studio computes structured conflicts from suggestion vs
  session state divergence.

---

## Implementation Slices

| Slice | What changes | What stays | Truly UI-only? | Backend coupling risk | Recommended order |
|-------|-------------|------------|----------------|----------------------|-------------------|
| 1. Shell / nav / visual frame | `base.html`: add right rail DOM structure, bottom drawer DOM structure, step completion indicator logic, CSS variables for new tokens | All routes, all session model, all integration logic | **Yes** — pure CSS/JS/template change | None | First — establishes the frame for all subsequent slices |
| 2. Step 1 KS subpanel integration | `step1_project.html`: merge Knowledge Workspace card into project setup card as a compact subpanel | `/knowledge` route, KS integration logic, session model | **Yes** | None | Second — immediately improves Step 1 coherence |
| 3. Step 2 / Step 3 label alignment + passthrough nav fix | Historical slice: template label copy updates in `step2_upstream.html`, `kafka_step1_topics.html`; Kafka progressive disclosure; passthrough Step 3 sub-section split; and registry alignment with `/upstream` and `/passthrough` | Route URLs, session shapes, form fields | **Yes** for label changes and registry route correction | None for label changes; the registry correction was a small metadata-only fix | Historical sequence; the navigation correction is now implemented and regression-tested |
| 4. Right-rail panel integration (KS suggestions move) | `step3_entities.html`: remove inline KS suggestion panel from main pane, connect it to right rail Suggestions panel template; update Evidence toggle to use Evidence panel in rail | KS API calls (`/entities/ks/suggestions`, `/entities/ks/evidence`, `/entities/ks/review`), batch write-back logic, staged decisions map | **Yes** — JS wiring changes only; route calls (`suggest_fields`, `get_field_evidence_chain`, `submit_suggestion_decisions`) unchanged | Low — only changes display location, not data flow | Fourth — core UX improvement for Step 3 |
| 5. Step 6 Issues/Conflicts advisory panel | `step6_rules.html`: add advisory conflict signals section above rules form; read `conflict_hint` strings from KS suggestion payloads into the Conflicts panel structure; add advisory badge rendering | Rules route, session entity_rules model, existing rules form fields | **Mostly — requires live KS re-fetch or client cache**: `conflict_hint` strings come from a live call to `/entities/ks/suggestions`, not from durable persisted conflict rows. No new structured conflict model is needed for the advisory baseline, but the panel cannot be built purely from already-stored session data. | Low — no new persisted conflict model needed; panel relies on live KS suggestion data (re-fetch on Step 6 load, or client cache from prior Step 3 session). No new structured conflict records required. | Fifth |
| 6. Step 7 restructure + optional review posture | `step7_review.html`: move manifest YAML to drawer Manifest Diff tab; move provenance table to Decision History tab; move completeness items to Completeness tab; add review posture card in main pane with "Mark as reviewed" indicator | `/review` route Python logic, completeness service, evidence trail service, manifest generator | **No — UI-first with light backend support needed**: requires adding `review_approved` boolean to session state and a new `/review/approve` POST route. Export routes remain unchanged (no blocking gate). | Low — small additive session flag + one new route; no manifest or contract impact | Sixth — makes Step 7 a real review checkpoint (without hard gate) |
| 7. Step 8 export polish | `step8_export.html`: add visible evidence-trail.json download link; add manifest revision checkpoint indicator display | Export route, write logic, evidence trail builder | **Yes** | None | Seventh |
| 8. Motion / density reduction / progressive disclosure pass | All templates: audit and reduce inline styles; move dense detail to tooltips; add smooth transitions to drawers/rail; add spinner states for right-rail loads | No content changes | **Yes** | None | Eighth — polish pass after functional slices are complete |
| 9. Full structured conflict workbench (deferred) | `step6_rules.html`: full per-conflict resolution cards; route to write resolutions to `conflict_resolutions`; blocking/advisory determination logic | Existing suggestion and advisory panel from Slice 5 | **No — requires backend support**: needs conflict detection pass to populate `ks_workspace_state.conflict_resolutions`, new write route, evidence-trail sidecar extension | Medium — new model population + route + sidecar schema extension | Deferred — listed for planning visibility only |

---

*Historical document grounded in templates and routes read on 2026-04-20.
The live app at http://127.0.0.1:38081 was UP at that time. Current behavior is
described by `docs/studio-context.md`; no production code was changed in producing
this design record.*
