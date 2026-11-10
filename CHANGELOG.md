# Changelog

## v5.0.0 — Release preparation (unreleased)

- Align Studio package/runtime metadata at 5.0.0 and prepare current private Org
  repository and newcomer instructions. Python 3.11 support, Studio snapshot 1.4,
  Engine manifest 2.0, dependencies, fonts and product behavior are unchanged.
  The entries below are promoted from the former v4.2.0 Unreleased section;
  their historical results do not establish final v5 acceptance. No release
  date, tag, publication or completed acceptance is asserted.

- Clarify independent community maintenance and optional self-managed enterprise
  adoption; use neutral publication-authorization wording in preparation
  guidance. Publication prerequisites, license terms and dated proof results
  remain unchanged.

- Prepared the intended fresh public tree with independently authored synthetic
  package/parser fixtures, retired external-specific proof material and neutral
  dated summaries. The maintained newcomer pack/guide remain unchanged. Corrected
  only joserfc 1.7.1 to 1.7.6 with refreshed current reference evidence; historical
  images and unresolved publication/image/accessibility gates remain unchanged.

- Corrected constrained Authlib to 1.9.1 and dnspython to 2.9.0 for the eight
  dependency-audit observations blocking the project-intent documentation PR.
  Clean Python 3.11/3.13 environments, focused security/adapter regressions and
  refreshed reference evidence retain existing pins and behavior elsewhere;
  historical image proof is not relabeled as containing these corrections.
- Prepared private v5 source terms (Apache-2.0 / Santosh Hommaradi, DCO 1.1,
  no CLA), selected edgeforge-suite destinations and unverified PVR/email
  routes. Maintainer publication authorization and route activation remain later
  gates; no version bump, tag or release is authorized.
- Updated FastMCP/fastmcp-slim to 3.4.10, OpenTelemetry API to 1.45.1 and the
  constrained setuptools toolchain to 84.1.0 for the fresh audit findings.
  Supported Python 3.11 hosts and the Python 3.13 image line remain unchanged;
  historical image findings and native/embedded coverage limits remain open.
- Corrected standalone certifi to 2026.10.19 and Pillow to 13.0.0, preserving
  supported Python 3.11 hosts and the existing Python 3.13 image policy. Added
  document/image/TLS compatibility proof and coherent dependency evidence;
  pip-private/ensurepip copies and other image residuals remain open.
- Corrected the cached-URL real-Engine test contract to match its selected
  create operation, retaining ingestion/source-label checks and proving strict
  CLI/MCP rejection of absent selected operations. No production behavior changed.
- Corrected the constrained MCP SDK to 1.30.0 while retaining FastMCP 3.4.0 and
  Studio's stdio-only adapters. The upstream stateful Streamable HTTP advisory
  does not establish exposure of Studio's existing stdio handoffs.
- Moved the unchanged data-handling disclosure from the fixed-height Project File card to an
  always-visible, keyboard-operable header control while retaining point-of-use upload notices.
- Made the refreshed Studio UX the only presentation and retired the refresh/split rollout switches.
- Made the desktop board/editor split standard at 1200px and wider while retaining the accessible
  full-page focus fallback below that breakpoint.
- Removed frozen legacy browser markup, wholesale focused-editor handlers, and confirm-replace seed
  handlers; compatibility HTTP routes remain available while focused editors use save-one contracts.
- Refreshed golden renders, UX markers, accessibility gates, and stored-DOM-XSS sink fingerprints for
  the single presentation.
- Preserved the existing manifest and project schemas. This is unreleased metadata only: no `v5` tag
  or release is authorized. A11y-01 remains an
  [open known limitation](https://github.com/santosh-sh/EdgeForgeStudio/issues/302): one native
  desktop successful-save observation failed and three cases remain untested. In native Safari with
  VoiceOver and its Caption Panel, save a valid Step 5 downstream interface in desktop split view:
  the save may succeed without its outcome being spoken. Issue #302 is currently private and visible
  only to authorized readers. Any authorized public release or promoted demo while Studio remains
  private must include this impact and reproduction summary in an audience-accessible notice; link
  issue #302 as a public contribution path only if it becomes public. The proposed policy
  making A11y-01 alone non-blocking for source publication, internal baselines/tags, public releases,
  and promoted demos becomes operative only after [Studio PR #299](https://github.com/santosh-sh/EdgeForgeStudio/pull/299)
  and [Engine/Suite PR #313](https://github.com/santosh-sh/EdgeForge/pull/313) are independently
  reviewed and merged. The requirement and all four native cases remain open; no complete
  accessibility, tag, release, or promoted-demo authorization is claimed here.

## v4.1.0 — 2026-06-21

Studio regen-preview maintain baseline.

- Added a feature-flagged durable generated-baseline binding under per-session
  `managed-artifacts/`.
- Rendered the Engine Change Plan read-only, preserving Engine-owned diff and
  migration-safety semantics.
- Added approve-to-apply for additive plans with drift/destructive guards,
  per-package apply locking, audit events, and baseline refresh.
- Added L5 acceptance coverage for the regen-preview approve/apply addendum.

## v4.0.0 — 2026-06-21

Enterprise-ready Studio baseline.

- Added the identity/request-context seam, per-session SQLite state, and
  principal-scoped project ownership.
- Re-keyed routes to request-scoped sessions and removed the global session
  backdoor.
- Added shared-mode server-owned workspace/output paths, native-form CSRF,
  Build & Run gating, URL-fetch hardening, root-constrained Engine invocation,
  per-session KS DB paths, generation locking, audit hooks, quotas, retention,
  and lifecycle controls.
- Added Studio L2/L4/L5 smoke harness entries for shared-mode isolation,
  cross-repo author/generate, KS isolation, Engine fail-closed checks, and
  combined edge-contract generation.
- Added enterprise handover hygiene: project metadata, license placeholder,
  upload-size caps, dependency evidence, pytest CI, constraints, SBOM, and
  transitive license/audit evidence.

## v3.0.0 — 2026-05-04

UX v3 Knowledge Assist and evidence baseline.

- Expanded Knowledge Assist beyond field suggestions into full-width Step 3
  review, Step 6 rules/cross-entity suggestions, passthrough/Kafka mapping
  suggestions, advisory review surfaces, and Step 7 Decision History.
- Added Evidence Trail v1.1 for accepted/edited generated-artifact decisions.
- Added Docker Compose dev/runtime support with Java 21 + Maven for generated
  app Build & Run.
- Added Kafka integration / router Studio authoring, transform suggestions, and
  export evidence.

## v2.0.0 — 2026-04-21

Knowledge Server / Knowledge Assist MVP baseline.

- Added the Knowledge Workspace authoring surface and bounded KS subprocess
  adapter.
- Added Step 3 field-suggestion review with KA OFF clean by default.
- Preserved Studio-owned human review state while using KS for suggestion and
  citation support.

## v1.5.0 — 2026-04-12

Phase 4 Engine MCP generate baseline.

- Added the bounded Engine MCP `generate_app` integration.
- Preserved CLI/subprocess fallback for local generation.
- Added reusable proof-runner coverage for MCP generation and fallback
  behavior.

## v1.0.0 — 2026-04-07

Formal EdgeForge v1 Studio freeze.

- CRUD authoring flow across Steps 1-8.
- Step 8 Build & Run support after generation.
- Step 1 archetype selector for `crud` and `passthrough-router`.
- Constrained passthrough-router authoring/export.
- Step 2 upload hardening.

Key freeze-point PRs:

- PR `#41` Build & Run UI
- PR `#42` Step 2 upload hardening
- PR `#46` minimal Studio passthrough-router MVP
- PR `#47` Build & Run port/url/status polish
