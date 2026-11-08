# Studio UX Refresh — Archive (deliberation trail)

> **Provenance, not the working set.** These are the intermediate artifacts behind the canonical docs one
> level up (`../proposal-final.md`, `../review-reconciliation.md`, `../implementation-design.md`,
> `../final-mockups/`). Nothing here is needed to *build* the refresh — it's kept for the handover audit
> trail ("how was this designed?"). Everything here is already distilled into the canonical docs.

## Action-3 — three independent passes
Three designers worked the same Action-2 baseline **without seeing each other's output**, so agreement is a
real signal and divergence marks the genuine judgment calls. Convergence synthesis produced
[`../proposal-final.md`](../proposal-final.md).

| Pass | Author | Artifact |
|---|---|---|
| **Fable** | Suite design thread | [`action-3-passes/fable/proposal.md`](action-3-passes/fable/proposal.md) + [`mockups/`](action-3-passes/fable/mockups/) (6) |
| **ChatGPT** | GPT Pro, parallel | [`action-3-passes/chatgpt/proposal.html`](action-3-passes/chatgpt/proposal.html) |
| **Codex** | Codex — real-source grounded | [`action-3-passes/codex/proposal.md`](action-3-passes/codex/proposal.md) + `mockups/` (3) |

## Cross-reviews (round-1 → round-3)
- ChatGPT → Fable: [`action-3-passes/chatgpt/review-of-fable-pass.md`](action-3-passes/chatgpt/review-of-fable-pass.md)
- Fable → Codex: [`action-3-passes/fable/review-of-codex-pass.md`](action-3-passes/fable/review-of-codex-pass.md)
- Codex + ChatGPT reviewed the **consolidation**: [`action-3-passes/codex/review-of-final.md`](action-3-passes/codex/review-of-final.md) · [`action-3-passes/chatgpt/review-of-final.md`](action-3-passes/chatgpt/review-of-final.md) (both "adopt with redlines" → folded into `../proposal-final.md` §2.2)

## Source-grounded review passes (fed the reconciliation)
- [`review-pass-fable.md`](review-pass-fable.md) — Fable design-review pass (line-level source read).
- [`review-pass-codex.md`](review-pass-codex.md) — Codex design-review pass (independent; converged on the same 2 P0s).
- [`action4-review-codex.md`](action4-review-codex.md) — Codex pre-build verification of the Action-4 contract (approve-with-redlines R1–R5, folded into `../implementation-design.md`).
