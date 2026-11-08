# EdgeForge Studio — Architecture

> **Living document.** Updated 2026-06-29. For cross-repo architecture context, see `EdgeForge/docs/suite-architecture.md`.

## Studio Responsibilities

EdgeForge Studio is the human-facing intake, review, package export, and local execution surface for the EdgeForge suite. The current package is **4.2.0, unreleased**; the dated v4.1.0 baseline below is historical. It:

1. collects project setup and archetype selection
2. ingests and classifies OpenAPI specs
3. authors CRUD, passthrough-router, and kafka-integration flows
4. validates completeness before export
5. writes a valid EdgeForge manifest package
6. validates, plans, applies additive maintain changes, and generates through the Engine
7. optionally builds and runs generated apps in local single-user mode
8. orchestrates Knowledge Assist review while Studio remains the owner of human decisions and manifest state

Studio does **not**:

- generate Java/Spring Boot code by itself
- redefine the Engine manifest contract on its own
- implement staged downstream today
- broaden passthrough beyond the current proven Engine contract
- implement generated-app runtime behavior
- provide in-org SSO/RBAC policy, multi-replica HA, or a production Build & Run sandbox
- treat advisory Knowledge Assist reviews as generated-manifest evidence

## v1 Freeze Baseline

The original Studio v1 freeze marker was captured through PR `#47`, including:

- Build & Run in Step 8
- Step 2 upload hardening
- Step 1 archetype selector
- constrained passthrough-router authoring/export

The formal freeze marker for that historical baseline is the shared `v1.0.0`
tag created by the documented tag command.

Current Studio architecture state now extends beyond that freeze marker and the
older field-suggestion MVP. The v4.1.0 baseline includes UX v3 Knowledge Assist,
Evidence Trail v1.1, Docker Studio runtime, Kafka router authoring/evidence,
edge-contract authoring/evidence, shared-mode session isolation, root-constrained
Engine invocation, and the flag-gated regen-preview maintain flow.

## High-Level Runtime Shape

```text
EdgeForge Studio
  ├─ Wizard UI (Jinja2 + vanilla JS)
  ├─ Session store
  ├─ CRUD authoring path
  ├─ Passthrough-router authoring path
  ├─ Knowledge Workspace surface (Step 1)
  ├─ Step 3 compact + full-width Knowledge Assist Review
  ├─ Step 6 KA-applied rule provenance/removal semantics
  ├─ Step 7 Decision History + advisory reviews
  ├─ Package writer
  ├─ Engine subprocess adapter
  ├─ KS subprocess adapter
  ├─ Evidence-trail builder / export hook
  └─ Build & Run service for generated apps
                |
                v
     EdgeForge Engine      Knowledge Server
                |                 |
                v                 v
     Generated Spring Boot application
```

## Authoring Paths

### CRUD path

The CRUD path remains the canonical Studio flow:

- Step 1: project setup and archetype selection
- Step 2: upstream ingest
- Step 3: entity + operation selection
- Step 4: data handoffs / staging-table authoring
- Step 5: downstream interface authoring
- Step 6: rules + legacy notes
- Step 7: review
- Step 8: export / validate / generate / Build & Run

This path remains the main manifest 2.0 authoring surface.

### Passthrough-router path

The passthrough-router path is now part of the v1 baseline, but it is intentionally constrained.

Supported v1 passthrough topology:

- one inbound REST operation
- multiple downstream systems with one selected target operation each
- one route field
- equality-match routing rows
- one default target
- flat transform mappings only

Not supported:

- nested passthrough request modeling
- per-target custom transform graphs
- generalized passthrough orchestration beyond the proven Engine contract

Architecturally, Studio treats this as a separate authoring path, not as a retrofit of the CRUD-only steps.

### Kafka integration path

The kafka-integration path is current Studio baseline behavior. Studio owns
topic/schema intake, route model authoring, router route configuration,
request/response transform row authoring, shared rules/review/export flow, and
Knowledge Assist transform suggestion review. Router-native projects do not
need fake fixed topic pairs when route truth lives in `kafka_route_models[]`
with `pattern: router` and `router_config`.

## Session Model

Studio supports two deployment postures:

- local single-user mode, which behaves like the original local authoring tool
- shared multi-session mode, which uses signed anonymous-session cookies,
  request-scoped principals, SQLite-backed session/project state, and
  per-session server-owned `workspace_root` directories

`ProjectSession` remains the single active project model per browser session.
Shared mode scopes project catalog access by principal and keeps outputs,
Knowledge Server DB files, generated package exports, and managed regen
artifacts under the session workspace.

## Integration Layers

### Current: Engine integration

Studio currently calls EdgeForge Engine through `app/integrations/appbuilder_integration.py`:

- `validate_manifest()` uses the Engine package-loading validation path.
- `run_assess()` uses the Engine assess CLI path.
- `run_change_plan()` and `run_apply()` use the Engine regenerate/maintain CLI path.
- `run_generate()` uses Engine MCP in shared mode and local MCP/CLI fallback in local mode.

Shared mode passes `EDGEFORGE_MCP_ALLOWED_ROOTS` and `EDGEFORGE_SHARED_MODE=1`
on every Engine invocation so the Engine fails closed on out-of-root paths.

For local stdio MCP, Studio starts the Engine MCP server from the configured
Engine repo path. If that repo has `.venv/bin/python`, Studio uses it as the
server command; otherwise it uses the current Studio Python. Operators can set
`EDGEFORGE_STUDIO_ENGINE_MCP_COMMAND` to force a Python executable with FastMCP
installed. Studio passes per-session `EDGEFORGE_MCP_ALLOWED_ROOTS` to Engine
child processes. In shared mode the Engine repo is not an allowed root; it
remains import-only.

### Current: local generated-app Build & Run

Step 8 includes a local generated-app runtime adapter in local single-user mode:

- build generated app
- start generated app
- detect port / URLs / health endpoint
- summarize discovered routes
- stop managed process

Build & Run is server-disabled by default in shared mode.

### Current: Knowledge Server integration

Studio now calls Knowledge Server through `app/integrations/ks_integration.py`
with the same adapter-boundary rule used for Engine integration:

- Studio owns subprocess lifecycle and degraded-mode handling
- routes do not manage stdio transport directly
- user intent is stored separately from runtime KS process state
- Knowledge Assist is default OFF; KA OFF is clean and makes no live KS calls
- Step 1 provides the bounded Knowledge Workspace surface
  - upload / ingest
  - browse / refresh
  - search
  - document read
  - field catalog browse
- Step 3 provides compact triage plus a full-width Knowledge Assist Review surface
  - field suggestions can shape/update Studio entity fields
  - validation hints can materialize Step 6 validation rules
  - full review supports filtering, current-vs-suggested values, no-op classification, description editing, and batch staging
- Step 6 supports manual rules plus KA rule and cross-entity rule suggestion drawers
  - cross-entity manual authoring supports `cross-entity-field-check`, `cross-entity-field-compare`, and `cross-entity-field-in`
  - KA-applied rules carry ownership/provenance metadata and explicit removal semantics
  - rejecting a validation hint is not silently destructive
- passthrough mapping and Kafka router transform suggestions can be reviewed and exported with generated-artifact evidence
- Step 7 separates Generated Artifact Decisions, Advisory Reviews, and Current Step 6 Rules
- Step 8 writes Evidence Trail v1.1 and appends manifest revision metadata

Evidence Trail v1.1 generated-artifact evidence supports:

- `field`
- `validation`
- `rule`
- `cross_entity_rule`
- `mapping`
- `transform`

Rejected suggestions are excluded from generated evidence. Advisory
`conflict_resolution` and `portfolio_reuse` reviews are intentionally review
artifacts, not generated-manifest evidence links.

Studio owns human review and manifest/package state. Knowledge Server suggests
and provides citations/evidence; EdgeForge Engine consumes the approved
manifest/package artifacts.

### Future: broader Engine MCP

Phase 4 is the planned transport shift from subprocess calls to Engine MCP calls.

Studio should make that change at the adapter boundary, not by redesigning the wizard.
The first bounded Studio increment is `generate_app` only; validation, assess,
and local generated-app Build & Run stay unchanged until their contracts are
explicitly revisited.

### Future: LegacyExtractor MCP

Phase 6 is the planned point for structured extraction from legacy sources that can feed Studio authoring flows.

## Manifest Contract and Evolution Policy

Studio emits the paired Engine manifest 2.0 contract:

- `schema_version: "2.0"`
- `app_archetype: crud | passthrough-router | kafka-integration`

Rules for future evolution:

- keep Studio and Engine aligned on manifest 2.0
- do not add a temporary manifest-1.0 compatibility bridge
- add future concepts only after the paired Engine schema and loader support them

The Studio project snapshot is a separate contract. Its current
`studio_project_schema_version` remains `"1.4"`; snapshots from 1.0 through 1.4
are migrated on open and can be re-exported as manifest 2.0.

That policy is especially important for planned additive Studio follow-ups:

- entity type selector
- unique / idempotency key toggle
- ID strategy panel

Studio must not expose those until the Engine schema is ready.

## CRUD Topology vs Deferred Staged Downstream

The current CRUD architecture remains canonical-as-hub:

- upstream API -> canonical entity
- canonical entity -> staging handoff
- canonical entity -> downstream file

The staged-downstream alternative (`Entity -> staging -> downstream`) remains deferred. The design review is preserved in `docs/staged-downstream-future-design-review.md`, but it is not part of the current architecture baseline.

## What Studio Does Not Own

- code generation
- canonical model semantics
- preserved-operation generation behavior
- the Engine Phase 3 hardening roadmap
- staged-downstream implementation
- future MCP server implementation
