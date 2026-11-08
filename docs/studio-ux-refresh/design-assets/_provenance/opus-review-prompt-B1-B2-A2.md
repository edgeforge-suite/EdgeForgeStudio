# Independent review request — Fable design deliverables B1 · B2 · A2

**You are an independent Opus reviewer on the EdgeForge *suite* thread.** Codex has already
reviewed all of these once and its corrections are folded in. I don't want a rubber-stamp — I
want a **fresh cross-check** that (a) re-verifies accuracy against the suite truth, (b) confirms
honest build-vs-vision labeling, and (c) catches anything Codex missed. These are **Fable-generated
design assets, not build contract** — the bar is *factual accuracy + honest scoping*, not aesthetic
preference. Do **not** propose wizard redesigns: the CRUD wizard refresh is **locked** in Action-4
(`docs/studio-ux-refresh/implementation-design.md`, 25-PR contract, tokens frozen in §1.5).

## Read these (absolute paths — outside your repo cwd, but readable)

Truth sheet to check everything against:
- `~/Documents/EdgeForge Docs & PPTs/Fable Design docs/README.md`  ← the EdgeForge truth sheet

**B1 — design-system reference** (build-relevant):
- `~/Documents/EdgeForge Docs & PPTs/Fable Design docs/B1-design-system/edgeforge-studio-design-system.html`
- `…/B1-design-system/edgeforge-studio-design-system.png`

**B2 — exploratory archetype + KA mocks** (NOT build contract):
- `…/B2-archetypes-KA/capture-digest.md`  ← the source-grounded capture (the anchor)
- `…/B2-archetypes-KA/kafka-route-model-board.html`
- `…/B2-archetypes-KA/kafka-transforms-table.html`
- `…/B2-archetypes-KA/passthrough-route-transform.html`
- `…/B2-archetypes-KA/ka-suggestion-review.html`

**A2 — onboarding / dark-mode / responsive** (vision + one contract-faithful):
- `…/A2-onboarding-etc/a2a-onboarding-tour.html`  (proposed — nothing ships today)
- `…/A2-onboarding-etc/a2b-dark-mode.html`  (vision asset — not in the build contract)
- `…/A2-onboarding-etc/a2c-responsive.html`  (visualizes Phases 2a–2c + G1 — should be drift-free)

## Anchors — the facts everything must respect (don't re-derive; check against these)

- Suite baseline **v4.1.0** (Engine 4.1.1 · Studio 4.1.0 · KS 4.1.0). Manifest `schema_version 1.0`.
- **Identity: only anonymous per-session (signed-cookie) is wired.** `ProxyHeaderIdentity` +
  `OidcIdentity` are STUBS that raise — **OIDC/proxy SSO + RBAC = roadmap, NOT shipped.** Any asset
  implying named-user auth/audit is wrong. Say **per-principal**, never "per-tenant." Audit is
  **session-level**.
- **SOAP is bounded canonical, both directions** — inbound `read_by_id` + outbound `invoke_by_id`;
  richer body/header/fault mapping is roadmap.
- **KA default OFF**; retrieval works with no LLM provider; every suggestion human-reviewed.
- **TestBench = optional local dev/test utility**, not a 4th pillar.
- Locked §1.5 tokens — zone tints `--zone-scan #eaf0f8 · --zone-editor #ffffff · --zone-derived
  #f3ecfd (line #ddd0f2) · --zone-attn #fdf0d8 (line #eccf97) · --zone-ready #e8f2f2`; family accents
  `REST #0d9488 · Fixed #15803d · CSV #4f46e5 · XML #b45309 · SOAP #1e3a5f · Staging #475569`.
- G1 = single-item upsert save; **Matrix Lite is OUT of v1**. No scope beyond the 25-PR contract.
- Type = monogram + label + accent, never colour alone (the a11y contract).

## What to check, per deliverable

**B1 (highest scrutiny — it feeds real acceptance checks):**
1. Do the token values match `implementation-design.md` §1.5 **exactly**? Flag any drift.
2. Are the 3 contrast findings (muted-on-tint ~4.3:1 · REST white monogram 3.74:1 · soft-chip text
   borderline) **correctly measured** and **correctly routed** to PR-02/PR-06/PR-18? Re-compute at
   least one contrast ratio yourself as a spot-check.
3. Is the framing honestly "**render the locked system**," not silently re-deciding tokens?

**B2 (exploratory — check honesty + source-faithfulness):**
1. Is `capture-digest.md` faithful to *current* Studio source? (Kafka ≈ 3 steps; passthrough = a
   4-section page; KA = per-step suggestion drawer lifecycle.) Flag any invented behavior.
2. Are all four mocks **visibly labeled EXPLORATORY / not-build-contract**?
3. Passthrough inbound ops must come from the **Step-2 upstream OpenAPI already in session**, NOT
   from `/passthrough/describe-spec` (which is for downstream target specs). Confirm the mock + digest
   say this.
4. Is the KA suggestion-queue flagged as a **horizon direction** (needs a capture pass comparing it
   against improving the *existing* per-step drawers), not presented as a decided design?

**A2 (vision + one contract asset):**
1. Are a2a (onboarding) and a2b (dark mode) clearly badged **proposed/vision — not in the 25-PR
   contract**? Any language that reads as committed scope is a defect.
2. Is a2c **contract-faithful** to Phases 2a (PR-12 full page) · 2b (PR-17 split, flag-gated) · 2c
   (PR-18 gated mobile) and the G1 rules? Confirm **no behavioral drift** — breakpoints are
   presentation-only, one `?focus=` route, single-item upsert, save re-renders from `ReadinessItem`.
3. Dark-mode contrast: are the stated ratios plausible/measured?

## Output format

For each deliverable: a one-line **verdict** — `SHIP AS-IS` / `FIX-THEN-SHIP` / `CONCERN` — then:
- a numbered list of any **accuracy or labeling defects** with `file : location` and the correct fact;
- an explicit **"anything Codex missed"** section;
- confirmation the handoff boundary holds: *beautiful mockups are never new requirements* — B1's
  contrast findings are the only items that become actual PR acceptance checks; B2/A2a/A2b are
  inspiration; A2c is orientation, not a substitute for `implementation-design.md`.

Keep it tight and high-signal. If everything is clean, say so plainly — don't manufacture findings.
