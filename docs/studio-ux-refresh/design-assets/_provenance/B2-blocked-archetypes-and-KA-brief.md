# B2 — Blocked Target States: Kafka · Passthrough · KA (Fable brief · Channel B · this thread)

Run in the Claude Code thread on `claude-fable-5` (needs the real templates). This forward-loads the
three surfaces that are **scoped but never designed** — so Action-4/5 aren't blocked once Fable is
gone. Save outputs to `Fable Design docs/B2-archetypes-KA/`. **Design specs only.**

> **VISIBLE LABEL RULE (both suite threads):** every Kafka / passthrough / KA mock must **display an
> on-canvas badge reading "EXPLORATORY — not the current build contract."** These are pre-capture
> options visualizing how the locked pattern language *might* apply — not build-ready specs. They must
> not contaminate the eventual blind capture pass (L16 capture-first), and **KA build stays gated** on
> the production-readiness / data-handling decision.

The scoping already exists in `docs/studio-ux-refresh/archive/review-pass-fable.md` §B2/§B3 (now
archived) and is confirmed in `review-reconciliation.md` **L16** (Kafka + passthrough = capture-first,
no blind transplant; KA reuses the patch grammar but is **gated on KA production-readiness**). Read
those first, then apply the locked token system from `implementation-design.md` §1.5. **Capture-before-design discipline:** for each, read the
real template to ground the current state; if you assume anything not in the source, **mark it as an
assumption** so the maintainer knows.

## B2a — Kafka-router archetype
Real source: `app/templates/kafka_step1_topics.html`, `kafka_step2_routes.html`,
`kafka_step3_transforms.html` (per-route cards — the same always-expanded pattern that broke Steps
4/5; it *will* grow long). Flow: Topic Ingest → Route Model → Transform Mappings (no entity model, no
handoffs, shorter wizard).
- Apply: P1 board → **routes board** (in-topic → route kind → out-topic · transform count ·
  readiness); focused editor per route/transform-set; the "family" axis becomes **topic/route/
  transform kinds + direction** (propose a small sub-palette); readiness = new `item_kind`s
  (`topic_pair`, `route`, `transform_set`) in the same P6 contract; trace = **topic-in → route →
  topic-out** (replaces the entity-centric lens).
- Deliver: a routes-board + focused-editor mockup, and a pattern→applies/adapts/n-a table.

## B2b — REST-passthrough archetype
Real source: `app/templates/step3_passthrough.html` (sections: Inbound Operation · Downstream
Targets · Routing · Transforms; already has `/passthrough/describe-spec` as a deterministic seed
source). This page is **section-shaped, not list-shaped** — the full board machinery may be overkill.
- Apply: most likely keep the single page but add zone tints, family/type tokens on target rows, one
  readiness strip, and P5 seeds from `describe-spec`. Only build a targets board **if** a targets/
  transforms count genuinely grows long. Decide from the source, not assumption.
- Deliver: the tuned single-page design (+ a targets-board variant only if justified).

## B2c — Knowledge Assist review experience
Real source: `initSuggestionDrawer()` in `app/static/js/studio.js` (~700 lines), `/rules/ks/drawer`
endpoints, Step-6 rule datasets (`suggestion_id / generated_by_ka / ka_review_status`),
`knowledge_workspace.html`, and the `--ka-*` tokens in `studio.css`.
- Apply: the KA suggestion is a **stateful sibling of the P5 seed-patch row** — same anatomy (Apply? ·
  target · proposed value · basis), but the *basis* is evidence + confidence (deep-link into the
  Workspace detail pane) and the lifecycle **persists** (proposed / accepted / edited / rejected).
  Design a **suggestion-queue board** (grouped by entity/type, sorted by impact) + a **focused
  suggestion review** (before/after diff in patch-row anatomy). Reuse the provenance-chip legend.
- Deliver: the queue board + focused-review mockups, and a note on where the KA lifecycle differs
  from a deterministic seed.

**Hard gate on B2c:** KA is **default OFF** and its production-readiness is gated on the
PII/sanitization decision. This design is **exploratory** — it does not authorize shipping KA. Mark
it clearly as gated. Nothing here changes the KA-OFF-is-clean invariant.
