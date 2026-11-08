# B1 — Studio Design System + Component Kit (Fable brief · Channel B · run in this thread)

**Run this in the Claude Code thread switched to `claude-fable-5`** — it needs the real repo. Fable
already has this conversation's context (the Action-3 mockups, my review pass, the source). Save the
output to `Fable Design docs/B1-design-system/`. **Design spec only** — no production code.

---

> ⚠️ **CURRENCY (re-grounded 2026-07-06):** the Studio wizard refresh has **advanced to Action-4** —
> `docs/studio-ux-refresh/implementation-design.md` is a delivered **24-PR build contract**, and the
> **token system + a11y contract are LOCKED** in its §1.5 (D1 decided the tints at moderate intensity;
> family hues finalized). So this is **no longer a "decide/freeze" task** — the decisions are made.
> B1 is now: **render the locked system as a visual reference** (a companion to the prose contract).
> **Do NOT re-decide any token.** This makes B1 a *lower-priority, bounded* B-channel item — see the
> re-grounding note; the higher-value Fable work today is the **A1 website** and (exploratory) **B2**.

## Role & goal
You are a senior design-systems designer. Produce **one rendered visual design-system reference page**
— token swatches + a live component gallery — that the Action-4 24-PR build implements against.
**Everything is already decided in Action-4 §1.5; you are documenting/visualizing it, not choosing.**

## Sources of truth (read these first — in this order)
- `docs/studio-ux-refresh/implementation-design.md` **§1.5** — the **LOCKED** token values + a11y
  contract. Use these **verbatim**.
- `docs/studio-ux-refresh/review-reconciliation.md` — the maintainer decision sheet (D1 tint, D2 save,
  L1–L16). The prior `review-pass-fable.md` is now at `archive/review-pass-fable.md` (superseded).
- `docs/studio-ux-refresh/final-mockups/*.html` — the components in situ (the Step-5 mock already
  carries the D1-merged tints).
- `app/static/css/studio.css` `:root` — the shipped base tokens to stay compatible with.

## Token set to RENDER (locked — copy these exact values, do not alter)
1. **Base** — from shipped `studio.css :root` (navy `#1e3a5f`, primary `#2563eb`, surfaces, borders, ok/warn/danger).
2. **Contract-family accents** (element-level only) — `--fam-rest #0d9488`, `--fam-fixed #15803d`,
   `--fam-csv #4f46e5`, `--fam-xml #b45309`, `--fam-soap #1e3a5f`, `--fam-staging #475569`. **Decided.**
3. **Functional-zone tints** (D1-final, moderate intensity) — `--zone-scan #eaf0f8`, `--zone-editor
   #ffffff`, `--zone-derived #f3ecfd` (+line `#ddd0f2`), `--zone-attn #fdf0d8` (+line `#eccf97`),
   `--zone-ready #e8f2f2`. Rule: family never tints a panel; zone never colours an accent;
   **selection > zone > default**. A11y gate: text contrast ≥ **4.5:1** on every zone (per §1.5).
4. **State** — ready / warning / needs-action / blocks-export / draft, each pill + icon + text (never
   colour alone); precedence `blocks_export > needs_action > warning > draft > ready`.
5. **Provenance** — SPEC-DERIVED / MANUAL / DERIVED (lilac) / KA-APPLIED (`--ka-*` teal). One legend.

## Component gallery to document (each with all its states)
Pull each from the mockups; show default · hover · selected · error/blocked · empty · overflow:
- **Board row** (contract / handoff / entity / rule-set variants) — monogram + name + meta + shape
  chip + capability icon + inline blocker + status pill + Edit.
- **Focused editor shell** — header ribbon, section anchor-tabs **with severity badges** (blocker vs
  warning — the distinction ChatGPT flagged), readiness banner, pinned Cancel/Save footer,
  guardrail-legible note.
- **Family silhouette / monogram** — all 6 families.
- **Provenance chip**, **readiness pill**, **capability icon** (populates-entities vs manifest-ref).
- **Deterministic seed-patch row** — checkbox · source · target · transform-basis · blank-on-collision.
- **Ambient readiness strip / stat cards** and **left-rail count chips**.
- **Zone-tinted panels** — scan board, bright editor, derived/seed box, needs-action group, readiness strip.

## The a11y contract (must hold across the whole system)
Redundant non-colour encoding everywhere (label + shape + colour); contrast ≥ the documented ratios;
colour-blind-safe; **selection (blue) always wins over zone tint**; error is never red-only. State
this as the contract at the top of the system page.

## Deliverable
One self-contained **design-system HTML page**: token tables (with the resolved family palette +
contrast results) and a live component gallery showing every component in every state. Written so it
maps 1:1 to `studio.css` + Jinja partials (the build target) — **spec, not framework code**. Note any
place the mockups and the shipped `studio.css` currently disagree, so Action-4 reconciles them.
