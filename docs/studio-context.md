# EdgeForge Studio - Current Context

> **Current baseline.** Source preparation checked 2026-10-25 against Studio
> `main @ 74e065a95f0b129fcfd55fbea74412d6634cf17e`. This document describes
> implemented Studio behavior. Historical design documents are retained for
> decision traceability, not as current planning authority.

**Release-preparation update — 2026-11-07:** the current private Org repository
prepares package/runtime metadata at 5.0.0. The October source observation above
is historical. Final Suite source selection, acceptance, tags and publication
remain later gates; product behavior and dependency inputs are unchanged.

## Status At A Glance

| Area | Current state |
|---|---|
| Studio package | `5.0.0` (release preparation) |
| Release state | **Unreleased**; no tag, release, or promoted demo baseline is authorized here |
| Engine manifest dialect | `schema_version: "2.0"` only |
| Studio project snapshot | `studio_project_schema_version: "1.4"` |
| Runtime posture | Local single-user and shared multi-session modes both ship; shared mode is a single-replica contract |
| Identity | Anonymous signed-cookie identity ships; proxy/OIDC authentication remains deferred |
| UX | Refresh and visual-polish work from PRs `#280` and `#281` is the sole presentation |
| Web security | The Studio baseline through PRs `#284`-`#295` is implemented |
| Known-limitation policy | A11y-01 remains open; merged coordinated policy makes it alone non-blocking, with audience-accessible disclosure required |
| Source preparation | Apache-2.0 / Santosh Hommaradi; DCO 1.1, no CLA; current edgeforge-suite/EdgeForgeStudio repository is private release preparation |

`CHANGELOG.md` is authoritative for release history and continues to mark
`v5.0.0` as unreleased preparation. This update does not create or authorize a tag.

## Product Boundary

Studio is the local, human-facing authoring and review companion for EdgeForge:

- Studio captures intent, inspects source contracts, authors project state, and
  exports reviewed manifest packages.
- The paired EdgeForge Engine validates, assesses, generates, and owns generated
  application behavior. Studio does not generate code itself.
- Knowledge Assist remains default OFF. With it disabled, Studio makes no live
  Knowledge Server calls and does not show stale assistance state.
- Manifest output stays within the paired Engine contract; Studio does not add a
  compatibility bridge for older manifest dialects.

## Versioned Contracts

The two schema versions serve different purposes and must not be conflated:

| Contract | Version | Purpose |
|---|---|---|
| Engine manifest | `2.0` | Exported package contract consumed by the paired Engine |
| Studio project snapshot | `1.4` | Studio-owned save/open authoring state, with migrations from supported earlier snapshot versions |

Changing one version does not implicitly change the other. Current regression
coverage pins manifest 2.0 output and Studio project-file round trips separately.

## Runtime Modes

### Local single-user

Local mode is the default development posture. It requires no authentication,
uses a local authoring session, permits operator-selected local paths within the
documented boundary, and enables the local Build & Run workflow.

### Shared multi-session

Shared mode is shipped and proven with concurrent session isolation. It uses:

- an opaque, signed anonymous-session cookie through the pluggable identity seam;
- principal-scoped SQLite session/project storage and server-owned workspaces;
- CSRF protection, path confinement, quotas, retention, and concurrency controls;
- a separate durable SQLite audit sink by default;
- per-session Knowledge Server state and Engine generation roots; and
- Build & Run disabled by default at the server boundary.

This is anonymous multi-session isolation, not enterprise authentication.
Trusted-proxy identity and OIDC adapters remain deferred project-owned work;
operators own their eventual identity-provider configuration. Shared mode is
supported as a **single replica**:
its workspace filesystem, generation lock, and resource-control state are
replica-bound. More than one replica requires an external session store plus
sticky sessions or a shared workspace volume and externalized lock; that HA design
is not implemented.

See [Studio architecture](studio-architecture.md),
[multi-session design](multi-session-architecture-design.md), and
[deployment model](deployment-model.md) for the detailed boundaries.

## Shipped Authoring And Review

### Archetypes and wizard flow

Studio supports the paired Engine's current `crud`, `passthrough-router`, and
`kafka-integration` authoring contracts.

- CRUD uses the governed project, upstream, entity, handoff, downstream, rules,
  review, and export sequence.
- Passthrough uses `/upstream` for contract ingest and `/passthrough` for route
  and transform authoring. The former registry mismatch is fixed and protected by
  `tests/test_wizard_registry.py`.
- Kafka supports topic/schema ingest, route modeling, transform mappings, shared
  rules/review, and export without inventing CRUD-only state.
- Step 8 exports packages, validates and assesses through the Engine, generates
  through the bounded Engine integration, and offers local Build & Run where the
  runtime mode allows it.

The refreshed UX is now the only rendered presentation. It includes the governed
board/editor flow, readiness sourced from server-side producers, responsive focus
routes, Decision History, and contextual data-handling disclosure. Refreshed
browser save-one calls send their source version; when a supplied version is stale,
the server returns `409` with current state instead of applying the edit. The
save-one endpoint contract retains omission or an empty value for compatibility,
so callers that do not supply a version are not protected by the conflict guard.

### Contracts, files, and evidence

The current edge-contract surface covers REST/OpenAPI, fixed-width and CSV files,
XML/XSD, and SOAP/WSDL within the paired Engine contract. Studio preserves source
artifacts for Engine consumption while its inspectors and regeneration discovery
fail closed on active DTD/entity declarations and other unsafe XML constructs.
Existing parsers remain authoritative for actual file content.

Evidence Trail records accepted or edited generated-artifact decisions and exports
the reviewed evidence sidecar without adding provenance fields to the manifest.
Project reopen preserves Studio-owned review, evidence, revision, and managed
regeneration state under the project snapshot contract.

## Security Baseline

Studio's web-security work through PRs `#284`-`#295` is implemented. The baseline
includes dependency and secret gates, bounded and address-pinned upstream fetches,
shared-mode API-document containment, sanitized diagnostics, durable audit,
request/upload bounds, resource controls, browser security headers, and
point-of-use data-handling notices.

These controls do not turn anonymous shared mode into authenticated multi-user
access, do not make client-declared MIME a content guarantee, and do not replace
host encryption, reverse-proxy policy, or adopter infrastructure controls. See
[security boundary map](security-boundary-map.md) and
[compliance and portability](compliance-and-portability.md).

## Current Planning And Historical Records

Suite-wide planning is owned by the Engine repository:

- [Enterprise readiness roadmap](https://github.com/santosh-sh/EdgeForge/blob/main/docs/enterprise-readiness-roadmap.md)
  is the narrative source of truth.
- [Generated suite tracker](https://github.com/santosh-sh/EdgeForge/tree/main/docs/tracker)
  is the derived task view; its source data, not the generated page, is edited.

Within Studio, this document and [Studio architecture](studio-architecture.md)
describe the current implementation. Documents such as
[the April 2026 implementation plan](studio-implementation-plan.md),
[the UX v2 design](studio-ux-v2-design.md), and the
[UX refresh implementation design](studio-ux-refresh/implementation-design.md)
remain useful historical decision records. Their dated plans and PR numbering do
not override current code, tests, this baseline, or the suite roadmap.

## Open And Deferred

- **A11y-01 remains an open, Studio-owned known limitation.** One desktop successful-save
  spoken-announcement case failed and the desktop validation-failure plus both sub-1200px cases remain
  untested. All four native Safari/VoiceOver cases remain required for completion, and existing
  structural, keyboard-only, screen-reader navigation, live-region, and writer-to-region checks stay
  binding. A11y-01 alone no longer blocks source publication, internal
  baselines/tags, public releases, or promoted demos under the coordinated policy merged in
  [Studio PR #299](https://github.com/santosh-sh/EdgeForgeStudio/pull/299) and the
  [companion Engine/Suite PR #313](https://github.com/santosh-sh/EdgeForge/pull/313), following
  independent review (merges: Studio `56354ce`, Engine `d8f50c0`). This exception applies only to
  A11y-01 and does not waive another acceptance gate or
  support a claim of complete accessibility. [Studio issue #302](https://github.com/santosh-sh/EdgeForgeStudio/issues/302)
  records the impact and reproduction and is publication-ready, but the private Studio repository
  restricts access to authorized readers. Any authorized public release or promoted demo while Studio
  remains private must carry an audience-accessible notice of the impact and reproduction; link #302
  as a public contribution path only if it becomes public. See the
  [amendment](studio-ux-refresh/implementation-design.md#a11y-01-v5-baseline-deferral)
  and [observation record](studio-ux-refresh/pr24a-a11y-walkthrough.md#a11y-01-v5-deferral-evidence).
- Proxy/OIDC authentication, SSO, RBAC, and adopter identity-provider wiring are
  not shipped by anonymous shared mode.
- Broader manifest semantics, richer passthrough modeling, additional downstream
  topologies, and LegacyExtractor work require their own approved design and
  paired Engine contract.
- Release/tag decisions, maintainer publication authorization, adopter hosting, and enterprise
  infrastructure controls remain outside this repository's implementation state.
  The [publication-preparation record](publication-preparation.md#remaining-maintainer-decisions)
  separates project-maintainer decisions from adopter configuration. Image #311
  delivered dispositions, not a corrected image or M2 clearance; newcomer #312
  remains dated reference proof, not final selected-release acceptance.
- Source preparation follows maintainer-approved EF-V5-RELEASE-SCOPE-RESET
  revision 3, superseding conflicting older gate sequencing. PVR and
  security@edgeforgesuite.com are selected, not activated/verified here. Image
  residuals remain OPEN known limitations with owners/triggers; required audits
  remain blocking. This does not accept risk or complete M2 or final-pair proof.

## Non-Negotiable Invariants

- Studio authors and reviews; the Engine generates.
- Manifest `2.0` and Studio project snapshot `1.4` remain separate contracts.
- Knowledge Assist remains default OFF and human review remains authoritative.
- Shared mode fails closed at its documented boundaries; anonymous identity is
  not described as authentication.
- No release, tag, or A11y-01 completion is implied by this document.
