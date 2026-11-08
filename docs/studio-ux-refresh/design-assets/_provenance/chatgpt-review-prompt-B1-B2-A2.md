# Review request (ChatGPT Pro) — Fable design deliverables B1 · B2 · A2

**Continuation of our earlier thread.** You previously reviewed the EdgeForge **Studio UX-redesign
proposal** (the CRUD wizard flow). That proposal is now **frozen** — it became a locked 25-PR build
contract (`implementation-design.md`, tokens frozen in §1.5). This is the **follow-on**: the
design-system + exploratory + vision assets produced *after* the proposal was locked. Same suite,
same contract.

I want an **independent cross-check** — a fresh reviewer already looked once. Don't rubber-stamp;
re-verify accuracy, confirm honest build-vs-vision labeling, and flag anything the prior reviewer
missed. These are **design assets, not build contract** — the bar is *factual accuracy + honest
scoping*, not aesthetic taste. **Do not propose wizard redesigns** — that ship has sailed.

---

## ⬆️ WHAT TO UPLOAD (you have no repo access and can't read my disk — I must attach everything)

You can view PNGs directly. For each mockup: **the PNG is the rendered visual; the HTML is the
source of truth for exact hex/token values and label text.** For B1 especially, I'm giving you both
so you can verify the token values, not just eyeball them.

**A. The Fable deliverables under review** — from `…/Fable Design docs/`:

| Deliverable | Files to upload |
|---|---|
| **B1** design system | `B1-design-system/edgeforge-studio-design-system.html` **+** `.png` |
| **B2** capture (the anchor) | `B2-archetypes-KA/capture-digest.md` |
| **B2** Kafka route board | `B2-archetypes-KA/kafka-route-model-board.html` + `.png` |
| **B2** Kafka transforms | `B2-archetypes-KA/kafka-transforms-table.html` + `.png` |
| **B2** passthrough | `B2-archetypes-KA/passthrough-route-transform.html` + `.png` |
| **B2** KA suggestion queue | `B2-archetypes-KA/ka-suggestion-review.html` + `.png` |
| **A2a** onboarding | `A2-onboarding-etc/a2a-onboarding-tour.html` + `.png` |
| **A2b** dark mode | `A2-onboarding-etc/a2b-dark-mode.html` + `.png` |
| **A2c** responsive | `A2-onboarding-etc/a2c-responsive.html` + `.png` |
| **Truth sheet** | `Fable Design docs/README.md` |

**B. Repo reference docs** — from the Studio repo `docs/studio-ux-refresh/` (attach these so you can
check the assets against the *locked* contract):

| File | Why you need it |
|---|---|
| **`implementation-design.md`** ⭐ REQUIRED | The 25-PR contract + **§1.5 locked tokens** — the oracle for B1 token-faithfulness and A2c phase/PR/behavior claims. |
| `review-reconciliation.md` | The maintainer decisions: D1 (tint palette), D2 (single-item upsert / G1), and the L1–L16 locks. |
| `proposal-final.md` | The agreed CRUD wizard flow. **Skip if it's still in this thread** from our earlier review — re-upload only if you've lost it. |

> If upload count is tight, the **minimum viable set** is: all PNGs + the three `.md` anchors
> (`capture-digest.md`, `README.md`, `implementation-design.md`). Add the HTMLs and the other two
> repo docs for the exact-value checks.

---

## Anchors — the facts everything must respect (check against these; don't re-derive)

- Suite baseline **v4.1.0** (Engine 4.1.1 · Studio 4.1.0 · KS 4.1.0). Manifest `schema_version 1.0`.
- **Identity: only anonymous per-session (signed-cookie) is wired.** OIDC/proxy SSO + RBAC = roadmap,
  **NOT shipped**. Say **per-principal**, never "per-tenant." Audit is **session-level**.
- **SOAP is bounded canonical, both directions** — inbound `read_by_id` + outbound `invoke_by_id`;
  richer body/header/fault mapping is roadmap.
- **KA default OFF**; retrieval works with no LLM provider; every suggestion human-reviewed.
- **TestBench = optional local dev/test utility**, not a 4th pillar.
- Locked §1.5 tokens — zones `--zone-scan #eaf0f8 · --zone-editor #ffffff · --zone-derived #f3ecfd
  (line #ddd0f2) · --zone-attn #fdf0d8 (line #eccf97) · --zone-ready #e8f2f2`; family accents
  `REST #0d9488 · Fixed #15803d · CSV #4f46e5 · XML #b45309 · SOAP #1e3a5f · Staging #475569`.
  (Cross-check these against §1.5 in the doc I upload — flag any mismatch in either direction.)
- G1 = single-item upsert save; **Matrix Lite is OUT of v1**. No scope beyond the 25-PR contract.
- Type = monogram + label + accent, never colour alone (the a11y contract).

## What to check, per deliverable

**B1 (highest scrutiny — it feeds real acceptance checks):**
1. Do the token values in the HTML match `implementation-design.md` §1.5 **exactly**? Flag drift.
2. Are the 3 contrast findings (muted-on-tint ~4.3:1 · REST white monogram 3.74:1 · soft-chip text
   borderline) **correctly measured** and **correctly routed** to PR-02/PR-06/PR-18? Re-compute at
   least one contrast ratio yourself as a spot-check.
3. Is the framing honestly "**render the locked system**," not silently re-deciding tokens?

**B2 (exploratory — check honesty + source-faithfulness):**
1. Is `capture-digest.md` a plausible read of *current* Studio behavior (Kafka ≈ 3 steps; passthrough
   = a 4-section page; KA = a per-step suggestion drawer)? Flag any invented behavior. *(You can't see
   the source — judge internal consistency + whether claims are appropriately hedged.)*
2. Are all four mocks **visibly labeled EXPLORATORY / not-build-contract** (check the PNGs)?
3. Passthrough inbound ops must come from the **Step-2 upstream OpenAPI already in session**, NOT from
   a `/passthrough/describe-spec` call (that's for downstream target specs). Confirm mock + digest agree.
4. Is the KA suggestion-queue flagged as a **horizon direction** (needs its own capture pass vs. just
   improving the existing per-step drawers), not presented as decided?

**A2 (vision + one contract asset):**
1. Are a2a (onboarding) and a2b (dark mode) clearly badged **proposed/vision — not in the contract**?
   Any language reading as committed scope is a defect.
2. Is a2c **contract-faithful** to Phases 2a (PR-12 full page) · 2b (PR-17 split, flag-gated) · 2c
   (PR-18 gated mobile) and G1? Confirm **no behavioral drift** — presentation-only breakpoints, one
   `?focus=` route, single-item upsert, save re-renders from `ReadinessItem`. Cross-check the PR
   numbers/phase names against `implementation-design.md`.
3. Dark-mode contrast: are the stated ratios plausible?

## Output format

Per deliverable: a one-line **verdict** — `SHIP AS-IS` / `FIX-THEN-SHIP` / `CONCERN` — then:
- numbered **accuracy or labeling defects** with `file : location` + the correct fact;
- an explicit **"what the first reviewer may have missed"** section;
- confirmation of the boundary: *beautiful mockups are never new requirements* — only B1's contrast
  findings become real PR acceptance checks; B2/A2a/A2b are inspiration; A2c is orientation, not a
  substitute for `implementation-design.md`.

If everything's clean, say so plainly — don't manufacture findings. Note explicitly if a verdict is
limited by something you couldn't verify without repo/source access.
