# Studio UX Refresh — Initiative Home

> **Status:** Action 3 consolidated + reviewed — Fable + Codex design-review passes done ([`review-pass-fable.md`](archive/review-pass-fable.md) · [`review-pass-codex.md`](archive/review-pass-codex.md)); both "adopt-with-changes" and **converged on 2 locked P0s** (P5→existing endpoints, P6→one readiness producer). §12 scope-freeze (coverage map · project-file compat · rollout safety) added. Both open calls **decided** — D1 tint (shared palette @ moderate/Codex intensity, applied to canonical Step-5) · D2 save-model (single-item upsert, no interim). Gate 2 **signed off 2026-07-03**. **Action-4 delivered + verified:** [`implementation-design.md`](implementation-design.md) — the phased build contract (26 PRs, Phases 0–5); Codex pre-build verification ([`action4-review-codex.md`](archive/action4-review-codex.md)) = approve-with-redlines, R1–R5 folded in. The approved §7.1 amendment retires PR-18's modal and adds PR-24a as the a11y acceptance gate without changing the count; the approved §7.2 amendment then splits §1.5 item 7's verification — PR-24a test-enforces the **structural** save-announcement contract (live-region attributes *and* writer→region binding), while observing announcements **spoken** remains **A11y-01**. The revised §7.3 known-limitation policy is proposed until independently reviewed Studio and Engine/Suite amendments both merge. **Action-5 is complete:** PR-24 leaves one refreshed presentation, retires the rollout flags, removes legacy browser paths, and records an unreleased Studio minor bump; every PR-24 merge gate passed with the August 9 maintainer demo sign-off.
> **Owner:** Suite design/architecture thread (Fable).
> **Scope:** Studio **frontend** usability. No drastic Engine/KS backend changes; the manifest
> contract stays compatible.

> **Open accessibility known limitation (revised 2026-09-21):** Action-5 remains complete, but
> A11y-01 does not. Native speech evidence consists of one failed desktop successful-save outcome and
> three untested cases. All four cases and the automated accessibility checks remain binding. The
> maintainer proposes that A11y-01 alone no longer block source publication, internal baselines/tags,
> public releases, or promoted demos; this is non-operative until
> [Studio PR #299](https://github.com/santosh-sh/EdgeForgeStudio/pull/299) and
> [Engine/Suite PR #313](https://github.com/santosh-sh/EdgeForge/pull/313) are independently reviewed
> and merged. [Studio issue #302](https://github.com/santosh-sh/EdgeForgeStudio/issues/302) is
> recorded and publication-ready, but Studio is private, so only authorized readers can access it.
> For an audience-accessible impact and reproduction summary, see the [Studio README](../../README.md)
> and the [proposed §7.3 amendment](implementation-design.md#a11y-01-v5-baseline-deferral). See also the
> [attempted-observation record](pr24a-a11y-walkthrough.md#a11y-01-v5-deferral-evidence). No complete
> accessibility or verified-speech claim is made.

This folder is the working home for the **Studio UX Refresh** — the deliberate usability
re-engineering of the Studio authoring wizard after linear feature-addition regrew the friction
that the v2 redesign set out to solve.

## Lineage / prior art (referenced here, not absorbed)
- [`../studio-ux-v2-design.md`](../studio-ux-v2-design.md) — **v2 redesign (2026-04-20)** that shipped
  the current "STUDIO V2 FRAME" shell (main pane + collapsible right rail). The round before this one.
- **`studio-ux-current-state-audit-2026-07.md`** *(not on this branch)* — the **analytical current-state
  audit (2026-07)**, a markdown companion to the visual walkthrough below (same DDA Accounts & Payments
  sample). Owned by the Studio capture / handover-cleanup thread; it lands via that thread, not this PR.
  The committed `baseline/current-state-walkthrough.html` is the self-contained visual baseline this
  initiative depends on.

## What's here — canonical (read these)
| Path | What |
|---|---|
| [`initiative.md`](initiative.md) | The brief: why-now, seed pain points, guardrails, the 5-action plan (Appendix A = Action-1 capture prompt). |
| [`baseline/current-state-walkthrough.html`](baseline/current-state-walkthrough.html) | **Action-2** first-hand visual baseline — 52 stills + 13 flow recordings of live Studio. Open in a browser. |
| [`proposal-final.md`](proposal-final.md) | **Action-3 consolidated design** — the agreed proposal (synthesizes all three independent passes + the reviews). |
| [`final-mockups/`](final-mockups/) | The **final** target-state mockups (Steps 5 / 3 / 4 / 6 / 7) — the set is complete. `step6-rules-board.html` supersedes the earlier `step6-rules-board-sketch.html`; **Matrix Lite remains OUT (locked L10)**. |
| [`review-reconciliation.md`](review-reconciliation.md) | The **maintainer decision sheet** — locked set + D1/D2 (the gate-2 record). |
| [`implementation-design.md`](implementation-design.md) | **Action-4** — the phased build contract (26 PRs) that Action-5 executes. |

## `archive/` — the deliberation trail (provenance; not needed to build)
The full "show your work": the three independent Action-3 passes + their mockups, the four cross-reviews,
the two source-grounded review passes, and the Action-4 verification — see [`archive/README.md`](archive/README.md).
Kept for the handover audit trail; the canonical docs above are the working set.

## Guardrails (every pass + the final proposal must hold these)
**Frontend-first** · **Manifest-compatible** (never change what the Engine consumes or how generated
apps come out) · **Protect the core** (no drastic Engine/KS changes; minimal, well-contained backend
touches only) · **Deterministic, not assumptive** (pre-fills are exact transforms of the inputs, never
guessed; KS/KA suggestions stay opt-in + review/accept) · **Phased, safe, reversible.**

## Next
1. ✅ Action 3 (3 passes + cross-reviews + consolidation + review passes + reconciliation) · ✅ gate 2 signed off · ✅ **Action 4 delivered** → [`implementation-design.md`](implementation-design.md).
2. ✅ **Gate 3** — phased implementation design approved; approved amendments follow §7.
3. ✅ **Action-5 complete** — all PR-24 merge gates passed, including the August 9 maintainer demo sign-off. A11y-01 remains an open known limitation; its proposed non-blocking policy in §7.3 awaits independent review and coordinated Studio/Engine merge.
4. **Follow-on tracks** (post-freeze, parallel): Kafka-router + REST-passthrough capture→apply; KA Workspace (build-gated on KA production-readiness).
