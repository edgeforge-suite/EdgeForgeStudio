# PR-24a accessibility walkthrough

Date: 2026-07-24

> **Current policy notice (revised 2026-09-21):** the July walkthrough below remains historical
> evidence. The proposed [§7.3 amendment](implementation-design.md#a11y-01-v5-baseline-deferral) is
> non-operative until the Studio and Engine/Suite amendments are independently reviewed and merged.
> Once active, A11y-01 remains an open known limitation but alone no longer blocks source publication,
> internal baselines/tags, public releases, or promoted demos. The limitation is recorded in
> [Studio issue #302](https://github.com/santosh-sh/EdgeForgeStudio/issues/302), which is
> publication-ready but available only to authorized readers while Studio is private.

This records the completed keyboard, VoiceOver navigation, and
accessibility-tree checks for the Step 5 focus flow in both supported
presentations, plus the Step 6 board keyboard regression check found during
PR-24a review.

Observing announcements **spoken** by a screen reader is **not** recorded here: it
is deferred to **A11y-01**, a mandatory pre-release gate approved in §7.2 of
`implementation-design.md`. PR-24a is therefore **not** the final a11y
verification for this initiative — see "Acceptance status" below for exactly what
passed and what A11y-01 still owes.

Every result is labelled:

- **[executed: browser]** was observed against a running local Studio server
  with seeded Step 5 and Step 6 data.
- **[executed: VoiceOver]** was spoken by macOS VoiceOver and displayed in its
  Caption Panel while traversing the real Step 5 page in the in-app browser.
- **[static]** is enforced by `tests/test_pr24a_a11y_gate.py` or an existing
  source-level gate.

The VoiceOver run and browser accessibility-tree checks are separate evidence.
The latter verifies rendered roles, names, and live regions; it is not used as
a substitute for the former.

## Acceptance status

**Passed, with one scoped deferral (approved amendment §7.2, 2026-07-25).**

**Completed here.** VoiceOver successfully entered the named Step 5 surface and
identified the Save control in both presentations. The keyboard-only walkthrough
passed in both presentations. Browser execution confirmed that both a successful
save *and* a validation-failing save populate their polite live regions. The
structural save-announcement contract is test-enforced for every refreshed save
surface — both the live-region attributes and the **writer→region binding**, so
re-pointing a save writer at another id now fails
`tests/test_pr24a_a11y_gate.py`.

**Deferred to A11y-01 — vocalization is still unverified.** The walkthrough did
not reliably observe VoiceOver *announce* both a successful save and a
validation-failing save. Correct ARIA is **not** accepted as equivalent to
observed speech: vocalization depends on Safari/VoiceOver behaviour *and* on how
Studio changes region visibility, content, and timing. Nothing below should be
read as satisfying that check.

Per §7.2 this no longer blocks the **PR-24 merge**, but it **is a mandatory
pre-release gate**: it must complete before the first release, version tag, or
promoted demo baseline that ships the refresh default-on. Acceptance is exactly —
native Safari + macOS VoiceOver with its Caption Panel; one successful save and
one validation-failing save; both the desktop split and the sub-1200px full-page
presentation; the exact announced text recorded **in this document**; and **any
failed or missing announcement blocks that release** and returns to Studio for
correction.

See §7.2 of `implementation-design.md` for the decision record; tracked as
build-thread item #57.

## Seed and evidence

> **Historical record of the 2026-07-24 run.** The two rollout flags below existed
> and were genuinely set when this walkthrough was executed. They were retired at
> PR-24 (#280), which made the refreshed UX the sole presentation. The results in
> this section stand as recorded; the flags are simply no longer the way to select
> a presentation. For a run today, use
> [Current reproduction](#current-reproduction--a11y-01) instead.

- **[executed: browser]** Master flag:
  `EDGEFORGE_STUDIO_UX_REFRESH=true`.
- **[executed: browser]** Split flag:
  `EDGEFORGE_STUDIO_UX_SPLIT=true`.
- **[executed: browser]** Step 5 focus route:
  `/downstream?focus=fixed-ready`.
- **[executed: browser]** Desktop viewport: `1360x900`.
- **[executed: browser]** Narrow viewport: `900x800`.
- **[executed: browser]** The seeded Step 5 board exposed eight contracts across
  attention, review, and ready states. The accessibility tree exposed the board
  as `region "Downstream contract triage board"` and its filters as
  `group "Filter downstream contracts"`.
- **[executed: VoiceOver]** macOS VoiceOver was run with its Caption Panel
  visible. On entry it announced
  `EdgeForge Studio — Step 5: Downstream Interfaces, frame`. On the focused
  Save control it announced
  `You are currently on a button. To click this button, press Control-Option-Space.`
- **[static]** Empty projects intentionally omit board/filter scaffolding, so
  the durable gate uses the existing non-empty per-surface fixtures.

Screenshots:

- [Desktop split at 1360px](pr24a-a11y-walkthrough-images/step5-desktop-split-1360px.jpg)
- [Full-page fallback at 900px](pr24a-a11y-walkthrough-images/step5-full-page-900px.jpg)
- [VoiceOver on the narrow Save control](pr24a-a11y-walkthrough-images/voiceover-narrow-save-control.png)

## Current reproduction — A11y-01

Instructions for running the outstanding A11y-01 observations on `main` today.
Presentation is selected **by viewport width only** — do not set
`EDGEFORGE_STUDIO_UX_REFRESH` or `EDGEFORGE_STUDIO_UX_SPLIT`; both were retired at
PR-24 (#280) and setting them has no effect.

**Environment**

```bash
.venv/bin/uvicorn app.main:app --port 8080
```

- Native **Safari**, not a Chromium browser.
- macOS **VoiceOver** on (`⌘F5`), with **VoiceOver Utility → Visuals → Caption
  Panel → Show Caption Panel** enabled.
- Presentation is set by window width: the board/editor split activates at
  **`min-width: 1200px`** (`app/static/css/studio.css`); below that, the focused
  editor is the full-page route.

**Surface.** Step 5 focused editor — `/downstream?focus=<interface-name>` — for a
downstream interface authored through the UI. One interface is enough; the eight-item
seeded board used on 2026-07-24 is not required for these four observations.

**The four observations.** Record the **verbatim Caption Panel text** for each.

| # | Presentation | Action | Expected announcement |
|---|---|---|---|
| 1 | Split (≥1200px) | Save a valid contract | `Downstream interface saved.` |
| 2 | Split (≥1200px) | Clear Name, Save | `This contract needs attention before it can be saved:` followed by `Interface name is required.` |
| 3 | Full page (<1200px) | Save a valid contract | as #1 |
| 4 | Full page (<1200px) | Clear Name, Save | as #2, including `Interface name is required.` |

Both outcomes are written to the same `role="status" aria-live="polite"` region
(`id="save-status"`), but by **different writers**: successes go through
`showStatus`, and a blocker list goes through `showWarningStatusList`. A save that
is rejected with no blocker labels announces
`The downstream interface could not be saved.` instead, and a save that succeeds
with warnings announces `Saved with guidance.` — record whichever text is actually
spoken rather than the text expected here.

**Between saves, change a field so the message text actually differs.** Re-writing
an identical string into a live region may not re-trigger an announcement; that is
an artefact of the test procedure, not a Studio defect.

**Also record:** tested Studio SHA, macOS / Safari / VoiceOver versions, and both
viewport sizes.

**Outcome.** Four passing observations close A11y-01 and are recorded in this
document. A missing or incorrect announcement remains a Studio-owned defect and open
known limitation that returns for a focused correction with regression coverage. After
the proposed §7.3 policy is independently reviewed and merged on both sides, A11y-01
alone no longer blocks source publication, internal baselines/tags, public releases, or
promoted demos. Accessibility-tree or DOM inspection is **not** a substitute for
observed speech.

<a id="a11y-01-v5-deferral-evidence"></a>

## A11y-01 attempted observation and known-limitation policy — 2026-09-13, revised 2026-09-21

This section records a later controlled attempt and the maintainer's dated sequencing decision. It
does not change the July 2026 walkthrough above or below, convert the observation into a pass, or
reduce the four observations required by [§7.2 and §7.3](implementation-design.md#a11y-01-v5-baseline-deferral).

**Environment actually captured**

- Tested Studio SHA: `d23d99f480e242291750724d192875e53b37e85f`.
- Observation date and timezone: `2026-09-13`, America/Chicago.
- macOS: `26.5` (build `25F71`).
- Safari: `26.5` (build `21624.2.5.11.4`).
- VoiceOver: `10` (build `993`), bundled with the recorded macOS build.
- Caption Panel: enabled and confirmed visible by the maintainer.
- Method: maintainer-assisted observation in native Safari with VoiceOver.
- Desktop CSS viewport: `1496x848`; the split board and focused editor were visible.
- Surface: Step 5 at `/downstream?focus=account-eod`, opened from a temporary copy of the synthetic
  Financial Services sample with Knowledge Assist off.
- Narrow viewport: not established because the narrow cases were not run.

| Case | Result | Evidence |
|---|---|---|
| Desktop split, successful save | **FAIL** | Save succeeded visually; VoiceOver announced button-activation guidance but did not announce the save outcome |
| Desktop split, validation failure | **NOT RUN** | No native observation recorded |
| Sub-1200px full page, successful save | **NOT RUN** | No native observation recorded |
| Sub-1200px full page, validation failure | **NOT RUN** | No native observation recorded |

The exact Caption Panel text for the attempted save was **not captured**. The summary above records
what was observed without inventing a transcript or reusing the July 2026 button-navigation text.

The focused structural checks recorded `74 passed`. This automated evidence does not establish that
VoiceOver spoke the save outcome or that A11y-01 is complete. Existing structural, keyboard-only,
screen-reader navigation, live-region, and writer-to-region requirements remain binding.

The revised maintainer direction is proposed and non-operative until
[Studio PR #299](https://github.com/santosh-sh/EdgeForgeStudio/pull/299) and the
[companion Engine/Suite PR #313](https://github.com/santosh-sh/EdgeForge/pull/313) each receive an
independent exact-head review and both merge. Until then, the existing coordinated policy remains
authoritative. Once activated, A11y-01 remains an open, Studio-owned
[known limitation](https://github.com/santosh-sh/EdgeForgeStudio/issues/302) (private and accessible
only to authorized readers), but A11y-01 alone no
longer blocks source publication, internal baselines/tags, public releases, or promoted demos. It is
complete only after native Safari/VoiceOver observations pass for a successful save and a
validation-failing save in both the desktop split and sub-1200px full-page presentations, with the
exact expected text recorded above. Contributor help is welcome, but Studio retains responsibility
for closeout. This proposal authorizes no publication, baseline, tag, release, promoted demo, waiver,
or accessibility certification. See the
[revised maintainer decision record](https://github.com/santosh-sh/EdgeForgeStudio/pull/299#issuecomment-5770467239).

## Desktop split, 1360px

1. **[executed: browser]** `[data-uxr-split="true"]` rendered with both the board and
   `[data-uxr-focus-editor="fixed-ready"]` at computed `display: block`.
2. **[executed: browser]** The accessibility tree exposed the board as a named region,
   filter chips as real buttons with visible labels and pressed state, every
   row action as a native `Edit` link, and the editor as a second named region
   labelled by `#uxr-focus-title`.
3. **[executed: browser]** With focus on the `fixed-ready` Edit anchor, `ArrowDown`
   moved `document.activeElement` to
   `/downstream?focus=csv-ready`. The destination matched
   `:focus-visible` and had a visible browser outline.
4. **[executed: browser]** Activating the native `fixed-ready` Edit link changed the URL
   from `/downstream` to `/downstream?focus=fixed-ready`; Browser Back restored
   `/downstream`.
5. **[executed: VoiceOver]** VoiceOver entered the named Step 5 frame and
   identified the focused Save control as a button with the standard
   `Control-Option-Space` activation instruction.
6. **[executed: browser]** Activating that Save control populated
   `#save-status[role="status"][aria-live="polite"]` with
   `Saved with guidance...`; the region became visible without a reload.
7. **[executed: browser]** After changing the interface name to
   `fixed-ready-draft`, attempting to open `/rules` displayed a confirm dialog.
   Dismissing it retained both the focus URL and draft value. Accepting the next
   prompt navigated to `/rules`, and Browser Back restored the focus URL.
8. **[static]** `[data-uxr-tab-badges]` remains a polite live region and
   `[data-uxr-conflict-review]` remains an assertive alert for higher-priority
   conflict recovery.
9. **[static]** `createDirtyTracker` also installs the `beforeunload` guard.
   The live run exercised the same tracker's in-app cancel and accept paths;
   the durable gate locks both listener registrations.

Result: **partial pass**. Keyboard row movement, native route activation,
visible focus, browser-rendered save status, dirty-navigation cancel/accept,
and route restoration were observed live. VoiceOver save success/failure
announcements remain unverified.

## Full-page fallback, 900px

1. **[executed: browser]** The same focus URL and
   `[data-uxr-split="true"]` markup rendered, but the split board computed to
   `display: none` while the focus editor remained `display: block`.
2. **[executed: browser]** Keyboard focus on `.iface-name` matched `:focus-visible` and
   rendered the shipped three-pixel focus box shadow.
3. **[executed: VoiceOver]** With the viewport below 1200px, VoiceOver again
   identified the focused Save control as a button and announced its
   `Control-Option-Space` activation instruction.
4. **[executed: browser]** Saving populated the same polite `#save-status` region with
   the same `Saved with guidance...` text as desktop.
5. **[executed: browser]** Opening `fixed-ready` from the board produced the real
   `?focus=` route with the board hidden and editor visible. Browser Back
   restored `/downstream`.
6. **[executed: browser]** After changing the name to
   `fixed-ready-narrow-draft`, dismissing the dirty-navigation prompt retained
   the draft and focus URL; accepting the next prompt navigated to `/rules`.
7. **[static]** The sub-1200px presentation is normal page flow, not a modal:
   no focus trap, focus-restoration shim, or Escape-key arbitration is added.
   The breakpoint and single-column fallback remain locked in `studio.css`.
8. **[static]** The shared `beforeunload` listener remains presentation
   independent.

Result: **partial pass**. The supported narrow presentation used full-page
semantics, visible focus, the same browser-rendered save status, dirty-state
protection, and native route/back behavior. VoiceOver save success/failure
announcements remain unverified.

## Step 6 keyboard regression check

- **[executed: browser]** At `1360x900`, `ArrowDown` on
  `/rules?focus=Account` moved `document.activeElement` to
  `/rules?focus=Customer`.
- **[executed: browser]** The Customer Edit anchor matched `:focus-visible` and rendered
  a visible browser outline.
- **[static]** The PR-24a gate now requires the identical ArrowUp/ArrowDown
  source contract on all four board surfaces: Steps 2, 4, 5, and 6.

Result: **pass after the PR-24a fix**.

## Cross-surface durable gate

| Surface | Evidence |
| --- | --- |
| Step 2 Upstream | **[static]** Labelled board/filter controls and flag-on `#edge-contract-status[role="status"][aria-live="polite"]` for add and focus saves |
| Step 3 Entities | **[static]** Labelled identity sections plus flag-on polite `#save-status` and `#phase2-status` save regions |
| Step 4 Handoffs | **[static]** Labelled board/filter controls, Arrow navigation, and a focused-save polite live region |
| Step 5 Downstream | **[executed: browser] + [executed: VoiceOver] + [static]** Labelled board, native Edit links, split/full-page focus semantics, visible focus, polite status, and assertive conflict alert; VoiceOver navigation/control identification passed, but save success/failure announcement observation is deferred |
| Step 6 Rules | **[executed: browser] + [static]** Labelled board/filter controls, text provenance labels, Arrow navigation, and a focused-save polite live region |
| Step 7 Review | **[static]** Labelled Contract Trace Lens plus flag-on polite `#review-posture-status` for review-posture saves |

- **[static]** Flag-off renders the original shared status nodes without the new
  ARIA attributes.
- **[static]** The gate re-verifies, without reopening them, the shipped contrast
  values for muted tint text, the REST monogram tile, and
  ready/warning/draft soft chips.

## Defects closed by the gate

1. Step 6 now has the same ArrowUp/ArrowDown roving board path as Steps 2, 4,
   and 5.
2. Step 2's shared `#edge-contract-status` announces add and focus save results
   when the refresh flag is on.
3. Step 3's Phase 1 and Phase 2 save-result regions announce success and
   failure when the refresh flag is on.
4. Step 7's review-posture save-result region announces success and failure
   when the refresh flag is on.

All four live-region additions are flag-gated; flag-off markup remains
byte-identical.
