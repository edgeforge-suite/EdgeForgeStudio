# Composite Proof Red-to-Green Control Check — Codat Customer + Downstream/Handoff — 2026-03-31 Post-PR52

## Goal

Re-run the exact same composite Codat proof from PR #20 after EdgeForge PR #52 merged, using the same proof target and same proof flow, to confirm whether the original blocker turned green.

This is a control rerun, not a new candidate.

## Original Red-State Failure From PR #20

The first composite proof in PR #20 failed during Engine generation with:

```text
AttributeError: 'list' object has no attribute 'lower'
```

Root cause:

- Engine OpenAPI classifier assumed `type` was always a scalar string
- the selected pinned Codat OpenAPI 3.1 spec uses nullable/list-valued `type` shapes like `["string", "null"]`
- owner: Engine, not Studio

## Baselines Used For This Rerun

- EdgeForgeStudio branch: `codex/feature/studio-composite-proof-next`
- EdgeForgeStudio branch HEAD: `b15c84ff58977386388f880b8dde4ec1801c85dc`
- EdgeForge `main`: `d38c82f75a48870db66627ae8bf505d9408c25db`
- EdgeForge baseline note: `d38c82f` is the merge commit for PR #52

## Proof Target Reused Unchanged

- Source spec: pinned local copy of Codat Accounting API 2.1.0
- Source URL: `https://api.apis.guru/v2/specs/codat.io/accounting/2.1.0/openapi.yaml`
- Local pinned path: `/tmp/openapi-directory/APIs/codat.io/accounting/2.1.0/openapi.yaml`
- Entity scope: `Customer`
- Selected upstream operations:
  - `create-customer`
  - `get-customers`
  - `get-customer`
  - `update-customer`
- Downstream shape:
  - one fixed-width downstream interface
  - one staging-table handoff

Runner used unchanged:

- `scripts/proof_run_codat_customer_downstream_handoff.py`

## Result Summary

| Step | Result | Notes |
|------|--------|-------|
| Studio intake / spec ingestion | ✅ PASS | same pinned Codat input |
| Entity + operation selection | ✅ PASS | same `Customer` flow |
| Upstream samples + mappings | ✅ PASS | same curated sample/mapping setup |
| Downstream interface save | ✅ PASS | same fixed-width interface |
| Data handoff save | ✅ PASS | same staging-table handoff |
| Completeness | ✅ PASS | `14 READY`, `2 WARNING`, `0 MANUAL FOLLOW-UP` |
| Manifest export | ✅ PASS | `schema_version: "1.0"`, `app_archetype: crud` |
| Package-shape verification | ✅ PASS | downstream + handoff package artifacts present |
| Engine manifest validation | ✅ PASS | manifest accepted |
| Engine generation | ✅ PASS | original PR #20 blocker is closed |
| Generated downstream/handoff artifact verification | ✅ PASS | writers + batch controller generated |
| Maven build | ❌ FAIL | new blocker |
| App startup / actuator / API smoke | ⛔ NOT REACHED | blocked by Maven compile failure |
| Runtime downstream/handoff smoke | ⛔ NOT REACHED | blocked by Maven compile failure |

## What Turned Green After PR #52

The original blocker from PR #20 is closed.

The same proof case now successfully reaches and passes Engine generation:

- generation succeeded
- `29` files created
- `22` Java source files generated
- `Harness: PASSED`

That means PR #52 fixed the original nullable/list-valued OpenAPI `type` failure as intended.

## New Blocking Failure

The proof is still not fully green end-to-end yet. The new blocker is at Maven compile time:

```text
[ERROR] .../CreateCustomerResponse.java:[34,20] variable status is already defined
[ERROR] .../CreateCustomerResponse.java:[141,19] method getStatus() is already defined
[ERROR] .../CreateCustomerResponse.java:[145,17] method setStatus(java.lang.String) is already defined
[ERROR] .../UpdateCustomerResponse.java:[34,20] variable status is already defined
[ERROR] .../UpdateCustomerResponse.java:[141,19] method getStatus() is already defined
[ERROR] .../UpdateCustomerResponse.java:[145,17] method setStatus(java.lang.String) is already defined
```

### Generated-code detail

The generated response DTOs contain duplicate `status` members:

- one `status` coming from the mapped customer-level data
- one `status` coming from the push-operation response envelope fields auto-included in the canonical model

This produces duplicate field and accessor definitions in:

- `CreateCustomerResponse.java`
- `UpdateCustomerResponse.java`

## Generated Downstream/Handoff Artifact Verification

These generated artifacts were present before the Maven failure:

- `src/main/java/com/appbuilder/customerops/adapter/outbound/CustomerEodHandoffFileWriter.java`
- `src/main/java/com/appbuilder/customerops/adapter/outbound/CustomerStagingWriter.java`
- `src/main/java/com/appbuilder/customerops/batch/CustomerEodBatchJob.java`
- `src/main/java/com/appbuilder/customerops/adapter/inbound/BatchTriggerController.java`

This confirms the combined package shape is still being translated into the expected outbound/batch code paths.

## Generation Warnings Observed

Generation succeeded with warnings, including:

- response mappings such as `data.id` and `data.status` were reported as not present in the response sample
- response envelope fields like `data`, `changes`, `companyId`, `status`, `statusCode`, and others were auto-included into the canonical model
- handoff mapping targets like `customer_id` / `customer_name` were reported as unknown contract fields
- Engine warned about ambiguous id-field inference between `companyId` and `id`

These warnings are important context for the new compile failure because they show the response envelope is still being merged into the generated model shape.

## Ownership

- Studio: no new blocker in this rerun
- Engine / generated code: current blocker
- Source spec: same stronger real-world control input as PR #20

## Conclusion

This rerun is a real red-to-green progression, but not full end-to-end green yet:

- PR #52 fixed the original PR #20 blocker
- the exact same composite proof now passes generation
- the next blocker is later in the pipeline, at Maven compile time, due to duplicate generated response DTO members

So this does **not** yet close the composite-proof blocker from PR #20 all the way to runtime. It does close the original classifier failure and narrows the remaining boundary to generated response DTO merging/collision behavior.

## Commands Used

```bash
python3 -B scripts/proof_run_codat_customer_downstream_handoff.py
```
