# EdgeForge Studio — UX Refresh Initiative (Brief & Action Plan)

> **Status:** Kickoff — Action 1 (capture prompt) ready; Action 2 (capture) not started.
> **Owner:** Suite design/architecture thread (Fable).
> **Scope:** Studio **frontend** usability. No drastic Engine/KS backend changes.
> **Created:** 2026-06-30.
> **This folder** (`docs/studio-ux-refresh/`) will hold the initiative's artifacts:
> this brief, the current-state UX walkthrough (Action 2), the UX Refresh proposal +
> mockups (Action 3), and the phased implementation design doc (Action 4).

> **Sequencing supersession (revised 2026-09-21):** the original A11y-01 pre-release sequencing below
> remains historical. The [proposed §7.3 amendment](implementation-design.md#a11y-01-v5-baseline-deferral)
> becomes operative only after the Studio and Engine/Suite amendments are independently reviewed and
> merged. Once active, A11y-01 alone no longer blocks source publication, internal baselines/tags,
> public releases, or promoted demos. It remains an
> [open known limitation](https://github.com/santosh-sh/EdgeForgeStudio/issues/302), Studio retains
> ownership, and all four native cases remain required for completion.

**Goal:** Re-engineer EdgeForge Studio's usability — **primarily in the frontend** — so
authoring an app across many edge-contract types feels coherent and low-friction, **without
disturbing the stable Engine/KS core or the manifest contract.**

---

## 1. Why now
Studio's UI grew by *linear feature-addition* — each new edge-contract type or capability was
stacked onto existing pages with no usability pass. The result: pages that scale badly, weak
visual structure, and heavy manual data entry. It has been hard to catch solo (deep manual
testing is the bottleneck), so this initiative brings dedicated, agent-assisted UX review to
fix it deliberately.

## 2. Observed UX pain points (seed set — Action 1 surfaces the full, first-hand list)
1. **Long, undifferentiated contract pages.** The Upstream-Contracts and Downstream-Interfaces
   pages grow without bound as contract types are added. You cannot visually tell which type
   goes where; editing one contract means scrolling past all others; the bottom-of-page list
   reads poorly. *(Candidate direction: a table per contract type + add/edit in a modal —
   open to better patterns.)*
2. **Long data-handoff / staging-table page.** Same failure mode past ~3–4 handoffs.
3. **Entity-model page complexity.** Dense, confusing layout — needs a serious refresh.
4. **Visual monotony / weak mental model.** Near-uniform white/cream; boxes are the only
   separator. Nothing helps the user mentally separate the many contract types and their data.
5. **No deterministic defaults.** Nearly every field is hand-filled. Where a value can be
   *deterministically derived from the interface inputs* (not guessed), Studio should pre-fill
   it. *(Distinct from KS suggestions, which stay opt-in + review/accept.)*

## 3. Guardrails (apply to every proposal / design / build action)
- **Frontend-first.** Re-engineer usability in the Studio UI layer.
- **Protect the core.** No drastic backend changes; do **not** disturb stable Engine or KS
  logic/code. Minimal, well-contained backend touches are acceptable (e.g., a
  deterministic-defaults helper) — but nothing that reinvents working suite behavior.
- **Manifest-compatible.** The approved manifest (Engine's input) stays schema/output-
  compatible — UX changes must not alter what Engine consumes or how generated apps come out.
- **Deterministic, not assumptive.** Defaults are derived deterministically from inputs, never
  guessed. KS AI suggestions remain opt-in + review/accept.
- **Phased, safe, reversible.** Ship in independent phases; zero disruption to the working suite.

## 4. Action plan
| # | Owner | Input → Output | Purpose |
|---|---|---|---|
| **1** | Suite design (this doc) | brief → detailed capture prompt (Appendix A) | Define exactly how to baseline current Studio UX |
| **2** | Studio design agent | Action-1 prompt → **current-state UX walkthrough** (per-page screenshots, purpose, how-used, first-hand pain points) + short flow recording | Capture and *feel* the current UX as a real user |
| **3** | Suite Architect (Fable) | Action-2 baseline → **Studio UX Refresh Proposal** + **redrawn target-state mock UI** (images/video) | Propose frontend-first refinements; show target state visually for sign-off |
| **4** | Suite Architect (Fable) | approved proposal → **phased implementation design doc** | How to implement safely in phases, no suite disruption |
| **5** | Studio build | design doc → implementation | Build the changes phase by phase |

## 5. Review gates (maintainer)
- **After Action 2** — confirm the baseline captured the real pain points.
- **After Action 3** — visually sign off the target-state mockups before any design/build.
- **After Action 4** — approve the phased design before implementation.

## 6. Status log
- **2026-06-30** — Initiative kicked off; brief + Action-1 capture prompt authored.
- **2026-07-01** — Action 2 delivered: current-state walkthrough
  (`studio-ux-current-state-standalone.html`, 52 stills + 13 recordings).
- **2026-07-02** — Action 3 delivered: [`action-3-passes/fable/proposal.md`](archive/action-3-passes/fable/proposal.md)
  + 6 rendered target-state mockups in [`action-3-passes/fable/mockups/`](archive/action-3-passes/fable/mockups/) (3 directions → judged → synthesized).
- **2026-07-02/03** — Action 3 consolidated + hardened: 3 independent passes (Fable / ChatGPT / Codex) →
  [`proposal-final.md`](proposal-final.md) + [`final-mockups/`](final-mockups/) → round-3 review folds →
  two source-grounded review passes → [`review-reconciliation.md`](review-reconciliation.md).
  **Gate 2 signed off 2026-07-03** (locked set + D1 tint + D2 single-item save).
- **2026-07-03** — **Action 4 delivered:** [`implementation-design.md`](implementation-design.md) —
  phased build contract (Phases 0–5, flag-gated `EDGEFORGE_STUDIO_UX_REFRESH`, 4.1.x demo baseline
  pinned). Codex pre-build verification ([`action4-review-codex.md`](archive/action4-review-codex.md)) =
  **approve with redlines**; R1–R5 folded in (parity scope · PR-09a test backfill · rename grep scope ·
  PR-12→PR-14 edge · test-path/fixtures) → 26 PRs. The approved §7.1 amendment later retired PR-18's
  modal and added PR-24a as the a11y acceptance gate, preserving that count; the approved §7.2
  amendment then split §1.5 item 7's verification — PR-24a test-enforces the structural
  save-announcement contract, while observing announcements **spoken** becomes **A11y-01**, a
  mandatory pre-release gate. **Action-5 is complete: PR-24 retired the rollout flags and removed the
  legacy browser paths, and the maintainer demo sign-off passed on 2026-08-09. No release tag was
  created by the flip.**

---

## Appendix A — Action-1: Current-State Capture Prompt
*Paste to the Studio design agent thread (Sonnet works; **Opus recommended** for richer UX
judgment). Output feeds Action 3 (Fable architect).*

```
CONTEXT — you are the Studio UX-capture thread. We are starting a Studio UX Refresh.
EdgeForge Studio's UI grew by linear feature-addition and now scales badly (long
undifferentiated pages, dense entity model, visual monotony, heavy manual entry). Before
anyone proposes redesigns, we need a faithful, FIRST-HAND baseline of the CURRENT Studio UX.
THIS TASK IS CAPTURE + OBSERVE ONLY — do NOT propose fixes, redesign, or change any Studio
code. A separate Architect (Fable) thread does the proposal next, using your output.

GOAL — drive EdgeForge Studio as a real architect would, building a deliberately rich sample
project, and produce a CURRENT-STATE UX WALKTHROUGH documenting every page: its purpose,
screenshots (including the "grown-long" states), how it's used in the authoring flow, and the
concrete usability pain points you hit first-hand.

SETUP
1. Run Studio locally per its README/run docs (the Docker Studio runtime / documented port,
   e.g. 8083), with Engine + KS wired as Studio expects. Confirm it's up.
2. Open Studio in a browser and drive it via the Claude-in-Chrome browser MCP (preferred) or
   the in-built preview/browser tools. Confirm you can navigate AND screenshot before going on.
3. Use SYNTHETIC data only (no real bank data — suite policy). Fill fields yourself,
   deterministically/illustratively, as a competent architect would.

BUILD A RICH SAMPLE PROJECT (to stress the pages that scale badly). A banking-modernization
example works well (e.g. a DDA/Accounts + Payments service). Include:
  - Upstream contracts across EVERY supported type, several of each: REST/OpenAPI (multiple
    endpoints), inbound fixed-width file, inbound CSV/delimited, inbound XML/XSD, inbound
    SOAP/WSDL (read-by-id).
  - Downstream interfaces across types, several of each: outbound fixed-width EOD file,
    outbound CSV, 4+ staging/handoff tables, a Kafka topic, outbound SOAP (invoke-by-id).
  - Several entities with fields, types, relationships, and a few rules (field-check,
    cross-entity) — enough to make the entity-model page realistically complex.
  - Exercise KA suggestions (accept/edit/reject a few) so that flow is captured too.

WALK THE FULL AUTHORING FLOW end-to-end (the wizard, in order), then revisit each page in its
POPULATED / grown-long state.

FOR EVERY PAGE/STEP, CAPTURE:
  - Screenshot(s) — INCLUDING the long/scrolled states (upstream page after 5+ contracts;
    handoff page after 4+ tables; the full entity model). Capture the whole page (multiple
    shots or scroll-stitched).
  - Purpose — what the page is for.
  - How it's used — what the user does here, in what order, what decisions they make.
  - Fields/sections — the key inputs and structure.
  - First-hand pain points — concrete + quantified: how far you scrolled, how many clicks,
    where you got confused or lost, what was hard to read, what you had to fill that felt
    like it could be derived. Write these as a real user's diary, not a spec.
  - Frontend-vs-backend flag (one line) — does this pain look UI-only fixable, or coupled to
    backend/manifest behavior? Just a flag, NO solutions.

SPECIFICALLY PROBE these known pain points (confirm/quantify first-hand + add others you find):
  1. Upstream/downstream pages growing long + undifferentiated by contract type; the
     bottom-of-page list's readability.
  2. Data-handoff / staging-table page length past 3–4 handoffs.
  3. Entity-model page layout complexity.
  4. Visual monotony (colors, separation, typography) — does the UI help you mentally separate
     contract types and their data?
  5. Fields that must be hand-filled but could be deterministically derived from the interface
     inputs.

ALSO capture the cross-cutting UI system: navigation/wizard structure, the visual/color
system, cross-page consistency, and overall "where am I / what do I do next" clarity.

DELIVERABLE — a self-contained CURRENT-STATE UX WALKTHROUGH:
  - A page-inventory SUMMARY TABLE (page - purpose - one-line top pain point).
  - PER-PAGE detail — purpose, screenshot(s) embedded, how-used, pain points, frontend/backend
    flag.
  - BONUS: a short end-to-end flow recording (GIF or MP4) to viscerally show the scroll/length
    pain.
Format: a self-contained HTML report (screenshots in an images/ folder) is ideal; a pptx deck
or Markdown+images is fine if easier. Save it under docs/studio-ux-refresh/ (or a shared
handoff folder) and report the exact path.

BOUNDARIES — capture the current state faithfully. Do NOT redesign, propose fixes, or edit any
Studio code. This is the baseline the Architect thread builds on. If Studio won't run or a page
won't load, document that too — it's a finding.
```
