# B2 Capture Digest — Kafka-router · REST-passthrough · Knowledge Assist

> **What this is:** a source-grounded, current-state capture (read from the real Studio templates +
> routes on 2026-07-06) of the three surfaces the CRUD-wizard refresh deliberately deferred. Produced
> by the Claude Code thread so **Fable spends its hours on design, not source-reading**. This is the
> "capture" half of capture-first — Fable does the "apply" (exploratory design) half.
>
> **How Fable uses it:** read this + `../B2-blocked-archetypes-and-KA-brief.md`, then produce
> **EXPLORATORY** design options that apply the LOCKED pattern language. Every mock must carry a
> visible **"EXPLORATORY — not the current build contract"** badge. Do not treat any of this as
> build-ready; the eventual blind capture pass still runs. **KA design is exploratory only — KA *build*
> stays gated on the production-readiness / PII decision.**

## The locked pattern language to apply (from the CRUD refresh — do NOT re-decide it)
Board (compact scan, one short row per item, grouped, blocked-first) **+** focused single-item editor ·
family = monogram + label + accent (element-level only) · functional-zone tints (`--zone-scan #eaf0f8`
board · `#ffffff` editor · `--zone-derived #f3ecfd` seeds · `--zone-attn #fdf0d8` needs-action ·
`--zone-ready #e8f2f2`) · deterministic seed = reviewable patch (never auto-apply) · one readiness
view-model feeds every surface · a11y: label+shape+colour, never colour alone; selection > zone > default.
**These archetypes have NO CRUD entity model and NO Step-4 handoffs — don't transplant those.**

---

## 1) KAFKA-ROUTER archetype

**Wizard shape** (from `base.html` nav): Project Setup → **Topic Ingest** (`/kafka/topics`) → **Route
Model** (`/kafka/routes`) → **Transform Mappings** (`/kafka/transforms`) → Rules → Review → Export.
Downstream Interfaces + Entity Model + Data Handoffs are **not applicable**. Mental model:
**topic-in → route → topic-out** (a mediation router), *not* entity CRUD.

> ⚠️ **Capture finding (bug, flag it):** the templates' `<h2>` headings are mis-numbered — Topic Ingest
> renders "Step 2", Route Model renders "Step 3", Transform Mappings renders "Step 3" again (it's
> position 4). Numbering is inconsistent with the rail. A design refresh should fix this.

### 1a. Topic Ingest (`kafka_step1_topics.html`, 259 lines)
- **Purpose:** the shared consumer shape + one topic pair per route.
- **Structure today:** (1) *Consumer Group Config* card — consumer group*, concurrency*, and a
  disclosure for advanced retry (max attempts, backoff ms, backoff multiplier) + DLQ enable/suffix.
  (2) An optional *Router Topic Summary* (read-only KV cards, one per router route). (3) *Topic Pairs*
  — **repeatable "Kafka Route" cards** (route name · upstream topic · upstream system · downstream
  topic · downstream system · a disclosure for upstream/downstream JSON schema payloads).
- **Save:** wholesale `POST /kafka/topics/save` (collects all cards). "+ Add Route" adds a card.
- **Pain:** moderate — each topic-pair card is compact-ish (schemas hidden behind a disclosure), but
  they stack; past a handful of routes it's a long column. Same always-expanded-card family as old
  Steps 4/5, milder.

### 1b. Route Model (`kafka_step2_routes.html`, 604 lines) — **the density hotspot**
- **Purpose:** per route, choose fire-and-forget / request-reply / request-path-router behaviour and
  configure the whole mediation.
- **Structure today:** one big card **per route**, rendered from a **deeply nested config object**
  (`defaultRouterConfig`): `upstream_topics[]` · `inbound_schema` · `routing_rules{routing_fields[],
  rules[{conditions[], target}], default_target}` · `duplicate_correlation_policy` · `targets[{request_topic,
  response_topic, request_schema, response_schema, request_transform, response_transform, retry,
  timeout_ms}]` · `outbound_schema` · `nack_routing` · `timeout` · `payload_logging` · `correlation_store`.
  Already split into **collapsible sub-sections**: *Router intake and schema · Routing fields and rules
  (N fields, N rules) · Targets and transform file references (N targets) · NACK routing and runtime
  policies (mode) · Reply channel details*. Two visual variants (router vs fire-and-forget/request-reply).
- **Save:** wholesale `POST /kafka/routes/save`.
- **Pain (severe):** this is the **densest surface in the entire app** — a full mediation config per
  route, many nested sub-objects, several routes stacked. Even with sub-section disclosures, one route
  is a very tall card; a real project (6+ routes) is an enormous scroll. **Clearest board+editor
  candidate in the whole non-CRUD space.**

### 1c. Transform Mappings (`kafka_step3_transforms.html`, 302 lines)
- **Purpose:** field-level mapping per route (without touching route/topic/schema config).
- **Structure today:** per-route cards with **two row types** — simple mapping rows
  (source_field → target_field) and richer *router transform rows* (source · target · type_coercion
  [`major_to_minor_units` / `minor_to_major_units`; the UI's `none` option = blank/**no** coercion, NOT a
  stored enum value — Codex nuance] · default_value · constant · value_map JSON).
  **KA suggestion badges per route** (mapping + router-transform suggestions).
- **Save:** wholesale `POST /kafka/transforms/save`. KA endpoints: `/kafka/ks/drawer`,
  `/kafka/ks/transform-review`, `/kafka/ks/review`.
- **Pain:** grid-shaped bulk mapping stacked per route — a good fit for a compact table + the seed-patch
  idiom; KA already plugs in here.

**Pattern-mapping hints for Fable (explore, don't prescribe):** a **routes board** (one row per route:
upstream-topic → pattern → target(s) → transform-count → readiness, blocked-first) + a **focused route
editor** grouping the nested config into clear blocks (intake · routing rules · targets · NACK/runtime).
The "family/type" axis here is **route pattern + direction** (fire-and-forget / request-reply / router;
in/out), not contract families — use as a **pattern accent, always with readable labels** (not acronyms
alone; Codex). New readiness `item_kind`s, **namespaced to avoid generic collisions (Codex):**
`kafka_topic_pair`, `kafka_route`, `kafka_transform_set`. Transforms → a compact table + deterministic
seeds (schema-pair seeding is a **proposed** helper, not implemented today — must be exact/normalized,
reviewable, never auto-apply; Codex). Trace = topic-in → route → topic-out.

---

## 2) REST-PASSTHROUGH archetype (`step3_passthrough.html`, 369 lines)

**Wizard shape:** Project Setup → Upstream Contract (`/upstream`, shared) → **Route & Transform**
(`/passthrough`) → Rules → Review → Export. Data Handoffs + Downstream + Entity Model **not
applicable**. Mental model: a **thin proxy** — inbound operation routed to downstream target(s) with
optional transforms.

- **Structure today: a single page, four sections** (not a list of big cards):
  1. *Inbound Operation* — interface name · system · contract source · spec URL · pasted OpenAPI ·
     the **inbound operation** picker (populated from the **Step-2 upstream OpenAPI already in session**,
     NOT from describe-spec — Codex correction).
  2. *Downstream Targets* — repeatable **target cards** ("+ Add Target").
  3. *Routing* — **Route Rows** (map inbound → target).
  4. *Transforms* — repeatable **transform rows** ("+ Add Transform").
- **Seed (Codex-corrected):** the inbound operation list comes from the **Step-2 upstream OpenAPI in
  session**; `POST /passthrough/describe-spec` (a real production endpoint) is used to **describe
  DOWNSTREAM TARGET specs** (in the Downstream Targets section), *not* the inbound picker. **Save:**
  wholesale `POST /passthrough/save`.
- **Pain:** mildest of the three — it's **section-shaped, not a long card stack**. It grows via target
  cards + route rows + transform rows, but the four-section frame holds. The full board+editor machinery
  is likely **overkill** here.

**Pattern-mapping hints (explore):** most likely **keep the single page** (Codex: keep strongly —
section-shaped source, board would be over-design unless real capture shows scale pain), apply zone
tints + type tokens on target/route rows + one readiness strip + surface **both** deterministic seeds
as reviewable patches (inbound ops from the Step-2 upstream OpenAPI; downstream target specs via
`describe-spec`). Only build a **targets board** if the capture of a real project shows targets/transforms
genuinely growing long — decide from data, not assumption. Item-kinds: `inbound_operation`, `target`,
`route_row`, `transform`.

---

## 3) KNOWLEDGE ASSIST (KA) — Workspace + accept/edit/reject review

> **Gate:** KA is **default OFF**; its production-readiness is gated on the PII/sanitization decision.
> This is **exploratory design only** — it does not unblock KA build, and must not imply it does.
> The KA-OFF-is-clean invariant is untouchable.

### 3a. Knowledge Workspace (`knowledge_workspace.html`, 374 lines)
- **Purpose:** the evidence/reference-document library KA draws on (explicitly *not* contract specs —
  those live in Step 2).
- **Structure today: a two-panel layout** — *Library* panel (search box · **Documents** grouped in
  disclosures with per-doc open/remove · **Field Catalog**) + a *Detail* pane. An **"Add Documents"**
  upload modal. Removing a document warns it "may refresh or stale related suggestions and evidence."
- **Pain:** it's the calmest KA surface; the real UX weight is the suggestion loop below.

### 3b. The suggestion review loop (`initSuggestionDrawer` in `studio.js`; drawers on Steps 3/6 + Kafka)
- **Lifecycle: a 3-way per-suggestion decision — accept / edit / reject — staged then batch-saved.**
  Buttons are `data-suggestion-stage` = `accepted` / `edited` / `rejected`, with **context-specific
  labels** by suggestion type: *Acknowledge · Record note · Dismiss* · / *Save Role Decision · Save
  Edited Role · Reject* · / *Apply · Apply edited · Reject*.
- **Edit** opens a payload editor (a `ka-suggestion-edit` disclosure with a JSON/textarea →
  `studio_edited_payload`). Decisions **stage** and the footer reads *"Save suggestion review (N)" /
  "N staged decisions."* — a **batch review**, not one-at-a-time commit.
- **Provenance already exists** (Step 6): rules carry `generated_by_ka` + `ka_review_status`
  (accepted / edited / rejected) and render as **KA-applied** chips alongside SPEC-DERIVED / MANUAL.

**Pattern-mapping hints (explore):** the KA suggestion is a **stateful sibling of the deterministic
seed-patch row** — same anatomy (apply? · target · proposed value · basis), but the *basis* is
evidence + confidence (deep-link into the Workspace Detail pane) and the lifecycle **persists** (staged
accept/edit/reject, batch-saved). Explore a **suggestion-queue board** (grouped by entity/type, sorted
by impact) + a **focused suggestion review** (before/after diff in the patch-row anatomy), reusing the
provenance-chip legend. Keep the Workspace two-panel library; make the suggestion loop the hero.
**Codex caution:** the standalone queue is the **biggest departure** from today's per-step drawers —
treat it as a *horizon direction*; the eventual capture pass should compare it against simply improving
the existing per-step drawers first. KA stays gated regardless.

---

## What Fable produces from this (per `../B2-blocked-archetypes-and-KA-brief.md`)
Exploratory, visibly-labelled option mocks — priority order by pain: **Kafka Route Model** (board +
focused route editor) first; then Kafka topics/transforms; then a tuned passthrough single-page; then
the KA suggestion-queue + review. Apply the locked §1.5 tokens. Mark assumptions. Save outputs beside
this file in `B2-archetypes-KA/`.
