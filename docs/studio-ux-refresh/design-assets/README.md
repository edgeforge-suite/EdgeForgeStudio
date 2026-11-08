# Studio UX Refresh — design-asset reference pack

Design references produced with the Fable design model to support the Studio UX refresh, and
**cross-verified by three independent reviewers** (Codex build thread · Claude suite thread ·
ChatGPT Pro, 2026-07). They are promoted here from the out-of-repo working area now that they are
review-clean.

> **These are references, not the build contract.** The 26-PR contract in
> [`../implementation-design.md`](../implementation-design.md) always wins. **Beautiful mockups are
> never new requirements.** Nothing here broadens scope, and nothing here touches backend or Engine
> generation logic.

## What's build-relevant vs. not (read before using any of this)

| Folder | Asset | Status | How the build should treat it |
|---|---|---|---|
| `design-system/` | **B1** — Studio design-system reference | **BUILD-RELEVANT** | Renders the **locked §1.5** token system (not a proposal). Its §3 measured contrast findings shipped through PR-02 / PR-06 / PR-11 and are re-verified by the PR-24a acceptance gate. |
| `exploration/` | **B2** — Kafka / passthrough / KA mocks + capture digest | **EXPLORATORY** | Application of the locked visual language to the non-CRUD archetypes. **Not build scope.** No Matrix Lite. KA stays **default-OFF** and build-gated on the PII/data-handling decision. The mocks are marked EXPLORATORY on their face. |
| `vision/` | **A2a** onboarding · **A2b** dark mode | **VISION / demo** | Not in the 26-PR contract. Nothing here ships today. |
| `vision/` | **A2c** responsive | **ORIENTATION** | A faithful visualization of the supported responsive story: full-page focus, desktop split, and the sub-1200px full-page fallback. Useful orientation — **not** a substitute for `implementation-design.md`. |
| `_provenance/` | Briefs + the two independent-review prompts | audit trail | How the pack was directed and reviewed. Reference only. |

## Keep-honest facts (so any visual stays accurate to the shipped suite)

- Suite baseline **v4.1.0** (Engine 4.1.1 · Studio 4.1.0 · KS 4.1.0). Manifest `schema_version 1.0`.
- **Identity today = anonymous per-session (signed cookie) only.** `ProxyHeaderIdentity` /
  `OidcIdentity` are stubs — **OIDC/proxy SSO + RBAC are roadmap, not shipped.** Say **per-principal**,
  never "per-tenant." Audit is **session-level**.
- **SOAP is bounded canonical, both directions** — inbound `read_by_id` + outbound `invoke_by_id`;
  richer body/header/fault mapping is roadmap.
- **Knowledge Assist is default-OFF**, opt-in, every suggestion human-reviewed; retrieval works with no
  AI provider connected.
- **TestBench** is an optional local dev/test utility, not a user-facing pillar.
- Locked §1.5 tokens — zones `--zone-scan #eaf0f8 · --zone-editor #ffffff · --zone-derived #f3ecfd
  (line #ddd0f2) · --zone-attn #fdf0d8 (line #eccf97) · --zone-ready #e8f2f2`; family accents
  `REST #0d9488 · Fixed #15803d · CSV #4f46e5 · XML #b45309 · SOAP #1e3a5f · Staging #475569`.
- Type = monogram **+ label + accent**, never colour alone (the a11y contract).
- Synthetic fixtures only — no real/production data in any visual.

## Not included here
- **A1 suite website** — suite-level, still in messaging round-2; lands separately (Engine repo).
- PR-24a's live a11y acceptance evidence — it is produced by the build thread, not bundled with this
  reference pack.
