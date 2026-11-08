# A2 — Onboarding + Dark Mode + Responsive (Fable brief · Channel A · claude.ai/design)

Secondary demo-polish pack. Run after A1. Save outputs to `Fable Design docs/A2-onboarding-etc/`.
Read the `README.md` truth sheet first; keep everything synthetic and honest about maturity.

## A2a — Studio first-run / onboarding tour (Studio has none today)
Design a first-run experience for the Studio wizard: a welcome/orientation moment, then a light
coach-mark tour of the two-speed model (scan board ↔ focused editor), the provenance idea, and
"Author → Generate → Search." Must feel skippable and calm, not a modal gauntlet. Ground it in the
real 8-step CRUD wizard (Project Setup → Upstream → Entity Model → Data Handoffs → Downstream →
Rules → Review → Export). Deliverable: the onboarding flow as screens/prototype.

## A2b — Dark mode
A full dark theme for the Studio surfaces + the A1 website hero. Start from the design-system tokens
(B1) — dark is a token remap, not a redraw. Preserve the a11y contract (contrast, family accents
still distinct, zone tints still legible when inverted). Deliverable: the token remap + 2–3 key
surfaces shown in dark (the Step-5 board/editor is the best proof).

## A2c — Responsive / narrow-screen
The proposal's Phase-2c is a narrow-screen focused editor. Design the responsive behaviour of the
two-speed pattern: wide = board + editor split; narrow = board only, editor opens as a full-page
route/takeover (route-addressable, browser-back-restorable, dirty-state preserved — per G1). Show
the breakpoints for the Step-5 surface. Deliverable: mobile/tablet/desktop frames of one flagship
surface.

**Guardrails:** synthetic data only; the editor's narrow mode must stay route-addressable + restore
dirty state (don't reintroduce the drawer problems); dark mode must pass the same a11y contract.
