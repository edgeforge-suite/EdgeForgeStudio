# Action-3 — Codex pass

This slot holds the **Codex** independent redesign pass. Codex's advantage over the other two passes:
it works from the **real Studio source** (Jinja2 templates, `studio.css`, `studio.js`) and the live app,
not just the baseline brief, so its recommendations are grounded in actual markup.

**Independence rule:** Codex must NOT read the Fable or ChatGPT passes (`../fable/`, `../chatgpt/`).
The whole value of a third pass is that it's uncontaminated.

**Deliverables:**
- [`proposal.md`](proposal.md) - diagnosis per pain, named patterns, page-by-page target state, per-item guardrail checks, phased rollout, and open decisions.
- [`mockups/contract-board.html`](mockups/contract-board.html) - target Step 5 downstream Contract Board and focused editor.
- [`mockups/identity-role-lens.html`](mockups/identity-role-lens.html) - target Step 3 exceptions-first identity role review.
- [`mockups/staging-handoff-board.html`](mockups/staging-handoff-board.html) - target Step 4 Data Handoff Board and focused DDL/mapping editor.

**Inputs:**
[`../../initiative.md`](../../../initiative.md) (brief + guardrails) ·
[`../../baseline/current-state-walkthrough.html`](../../../baseline/current-state-walkthrough.html) (visual baseline) ·
`studio-ux-current-state-audit-2026-07.md` (analytical baseline — companion doc from the capture thread, not on this branch) ·
the live Studio source in this repo.
