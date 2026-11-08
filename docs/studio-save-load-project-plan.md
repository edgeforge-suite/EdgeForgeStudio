# EdgeForge Studio — Save/Open Project Planning Note

> **Studio-local planning note.** Updated 2026-04-20 after the merged KS save/open linkage follow-up. This remains a planning/reference note, not a production feature PR by itself.

S1A file-based save/open is already implemented on Studio main via PR `#54`.
The `studio_project_schema_version: "1.1"` follow-up for durable KS linkage and
workspace state is also now implemented on Studio main via PR `#68`.

This planning note is now a historical record of the S1A design decisions plus
an honest summary of what the shipped `1.1` save/open boundary already carries.

## Shared Design Anchor

The shared Engine/Studio design anchor is now:

- EdgeForge PR #93: `docs/studio-save-load-design.md`

This Studio note should stay lightweight and Studio-specific. If details diverge, treat the cross-repo design in EdgeForge PR #93 as the source of truth and update this file to point back to it rather than creating a competing design.

## Product Goal

EdgeForge Studio should let a user save in-progress authoring work and reopen it later without redoing the wizard from scratch.

The target user outcome is:

- start a Studio project
- work through the wizard
- save the project in a Studio-native editable form
- reopen it later
- modify only the required sections
- export a fresh Engine manifest package again

## Final Phase Framing

The aligned phase model is:

- **S1A:** Studio-native save/open project
- **S1B:** optional server-backed project catalog and locking
- **S2:** SSO
- **S3:** LOB-scoped access
- **S4:** RBAC

S1A is the first implementation target. S1B/S2/S3/S4 are later phases.

## S1A Scope

S1A should be a file-based Studio save/open feature, not a service.

Recommended S1A user-facing actions:

- `Save Project`
- `Open Project`
- `Save As`

Recommended S1A artifact:

- `edgeforge-studio-project.json`

S1A should restore Studio authoring state through Steps 1-6 and keep Step 7/8 recomputable.

S1A should not include:

- package re-import from `app-definition.yaml`
- server-backed project catalog
- PostgreSQL JSONB project storage
- pessimistic locking
- SSO login
- LOB access enforcement
- RBAC

## Current Studio State Boundary

S1A should be shaped around the current Studio `ProjectSession` model.

The durable authoring snapshot should include:

- `app_name`
- `bounded_context`
- `app_archetype`
- `target_profile`
- `output_path`
- `appbuilder_repo_path`
- `raw_spec_content`
- `raw_spec_url`
- `raw_spec_filename`
- `classified_entities`
- `classified_operations`
- `selected_entity_names`
- `selected_operation_names`
- `upstream_interfaces`
- `downstream_interfaces`
- `data_handoffs`
- `entity_rules`
- `legacy_notes`
- `legacy_slug`
- `passthrough_flow`

Step 8 runtime/build state should remain transient.

Current shipped `1.1` additive KS/workspace fields now include:

- `project_id`
- `ks_project_id`
- `ks_active`
- `suggestion_review_state`
- `evidence_links`
- `manifest_revisions`
- `conflict_resolutions`
- `review_history`

Those fields are already part of the Studio project file. This note should no
longer describe them as future additions.

Do not persist as durable project state:

- running process IDs
- local port bindings
- build logs
- run logs
- health status
- generated app runtime status
- active Build & Run subprocess state

Optional last-known convenience fields may be persisted, but must not be treated as authoritative:

- last export path
- last export timestamp
- last generated app path

## Spec Content Persistence

For S1A, save both source metadata and the actual ingested spec content.

For URL-backed specs, preserve:

- `raw_spec_url`
- `raw_spec_content`

For uploaded specs, preserve:

- `raw_spec_filename`
- `raw_spec_content`

Reason:

- reopening should be reproducible even if a remote URL changes, disappears, or returns different content later
- the original URL or filename is still valuable source traceability

A future explicit "refresh from source URL" action can re-ingest upstream changes when the user wants that behavior.

## Auth-Ready Fields

It is acceptable for S1A to reserve nullable auth-ready metadata fields:

- `org_id`
- `lob_id`
- `owner_user_id`
- `last_edited_by`

Guardrails:

- no SSO enforcement in S1A
- no LOB filtering in S1A
- no RBAC in S1A
- no provider-specific auth assumptions in S1A
- local placeholders or null values are acceptable when no authenticated user context exists

This keeps a clean path to S2/S3/S4 without putting unclear auth work into the MVP.

## Engine Impact

Expected Engine impact for S1A: **none**.

Engine continues to own:

- manifest schema
- manifest loading/validation
- metadata translation
- generation behavior

Studio owns:

- Studio project save/open format
- Studio project file read/write
- snapshot schema
- wizard resume behavior

The Studio project file's `studio_project_schema_version` must remain separate from the Engine manifest `schema_version`.

## S1B Timing

Do not start S1B immediately after S1A by default.

S1B should be revisited after the Engine MCP phase clarifies the service boundary and deployment model.

Prioritize S1B only when Studio needs concrete server-backed behavior:

- multi-project catalog
- multi-user access
- shared team workflows
- locking / read-only conflict handling
- enterprise deployment support

Until those needs are concrete, S1A's file-based save/open path is the preferred scope.

## Historical Relationship To Manifest Evolution

Save/open landed before broader manifest evolution so new authoring decisions were
not introduced into a no-resume workflow. The later coordinated version cut makes
manifest 2.0 the active export contract while the Studio project snapshot remains
independently versioned at 1.4.

Relevant future wizard additions:

- entity type selector
- unique / idempotency key toggle
- ID strategy panel

Studio did not invent manifest fields in S1A. Current Studio reopens supported
project snapshots through its migration path and exports the paired Engine manifest
2.0 shape.

## Package Re-Import

Package re-import remains a later, separate feature.

It should be treated as best-effort reconstruction from exported package files, not the first save/open implementation.

The canonical editable source for S1A should be the Studio project file, not `app-definition.yaml`.

## Likely Studio Impact Areas When Implementation Starts

The likely implementation touchpoints are:

- [app/models/project.py](../app/models/project.py)
  Define the durable authoring snapshot boundary and any explicit save-file schema model.
- [app/services/session_store.py](../app/services/session_store.py)
  Extend current local session persistence into explicit user-facing save/open behavior.
- [app/routes/project.py](../app/routes/project.py)
  Likely entry-point integration for opening/resetting projects.
- Step routes across Steps 1-6
  Restore and preserve resumable authoring state consistently.
- shared UI/template layer
  Add save/open affordances and later dirty-state support.
- export/build-run routes
  Ensure transient Step 8 state is cleared or recomputed on reopen.

## Current Recommendation

When this feature is taken up, implement S1A first:

1. Studio-native file-based save/open project
2. durable `studio_project_schema_version` from day one
3. restore Steps 1-6 cleanly from saved Studio authoring state
4. save spec source metadata plus ingested spec content
5. keep Step 8 transient
6. defer S1B, SSO, LOB access, RBAC, package re-import, and autosave

## Implemented `1.1` Evolution and Remaining Follow-ons

The additive save/open evolution that this note previously described as future
is now implemented on Studio main:

- `studio_project_schema_version` is now `"1.1"`
- durable KS linkage is persisted through `project_id`, `ks_project_id`, and
  `ks_active`
- workspace review state, evidence links, manifest revisions, conflict
  resolutions, and review history are persisted in the Studio project file

What remains future work is narrower:

- richer reconnect behavior on reopen
- broader non-field suggestion scopes using the existing workspace state
- longer-term evolution workflows that build on `review_history` and
  `manifest_revisions`

This document does not propose another schema bump beyond the shipped `1.1`
baseline unless repo truth changes in a future design/update PR.

Migration rule:

- files without these fields open with empty / false defaults

Reference:

- `EdgeForge/docs/project-workspace-decision-ledger-design.md`
- `EdgeForge/docs/EdgeForge Target State Features v1.md`
