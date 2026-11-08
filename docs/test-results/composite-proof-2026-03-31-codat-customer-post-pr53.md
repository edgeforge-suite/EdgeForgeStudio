# Composite Proof Red-to-Green Control Check — Codat Customer + Downstream/Handoff — 2026-03-31 Post-PR53

## Goal

Re-run the exact same composite Codat proof from PR #20 after EdgeForge PR #53 merged, using the same proof target and same proof flow, to confirm whether the previous compile-stage blocker turned green.

This remains a control rerun, not a new candidate.

## Failure State Before PR #53

The prior rerun after PR #52 had already closed the original classifier failure from PR #20, but it still failed at Maven compile time because generated CRUD response DTOs emitted duplicate `status` fields/getters/setters.

Examples:

- `CreateCustomerResponse`
- `UpdateCustomerResponse`

Owner at that point: Engine / generated code.

## Baselines Used For This Rerun

- EdgeForgeStudio branch: `codex/feature/studio-composite-proof-next`
- EdgeForgeStudio branch HEAD before this artifact: `ee0679ef42e345af55b9b191141bae5c8f1e8b11`
- EdgeForge `main`: `e4baebe55a36ce017c4c0f2c6ec43681f464cd05`
- EdgeForge baseline note: `e4baebe` is the merge commit for PR #53

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
| Engine generation | ✅ PASS | previous PR #20 and post-PR52 blockers are closed |
| Generated downstream/handoff artifact verification | ✅ PASS | writers + batch controller generated |
| Maven build | ✅ PASS | previous duplicate-response-DTO blocker is closed |
| App startup / actuator health | ✅ PASS | successful outside sandbox |
| CRUD list smoke | ✅ PASS | `GET /customers -> HTTP 200 []` |
| CRUD create smoke | ✅ PASS | `POST /customers -> HTTP 201` |
| CRUD detail smoke | ❌ FAIL | `GET /customers/{id}` returns `404` |
| Runtime downstream/handoff smoke | ⛔ NOT REACHED | blocked by prior CRUD detail failure in the proof flow |

## What Turned Green After PR #53

The prior compile-stage blocker is closed.

The same proof case now successfully reaches:

- Engine generation
- Maven build
- application startup
- actuator health check
- first CRUD list/create API calls

Concrete stats from this rerun:

- generation: `29` files created
- Java sources: `22`
- harness: `PASSED`
- Maven: `BUILD SUCCESS`
- health: `{"status":"UP", ...}`
- app start time: about `4.1s`

## New Blocking Failure

The proof is still not fully green end-to-end. The next blocker is now in runtime CRUD behavior:

```text
GET /customers -> HTTP 200, 0 item(s)
POST /customers -> HTTP 201, body: {"id":null, ... "companyId":"312ca3f0-b315-48ec-8698-f3529e2c2e96", ...}
GET /customers after create -> HTTP 200, 1 item(s)
GET /customers/{id} -> HTTP 404
```

The proof script uses the created response `id` field for the detail readback. In this rerun:

- `POST /customers` returned `"id": null`
- the same response contained a generated `"companyId"` value
- the follow-up detail request therefore became `GET /customers/null`
- the generated app correctly returned `404`

## Likely Root Cause

The generation warnings during this run still included:

```text
Customer: Ambiguous id-field inference among candidates 'companyId' and 'id'; selected 'companyId' by source order.
```

Inspection of the generated domain and service code confirms that:

- `companyId` is treated as the JPA `@Id`
- `id` is a separate non-key field
- create responses return:
  - `id` from `saved.getId()`
  - `companyId` from `saved.getCompanyId()`

In this proof case, `saved.getId()` remains `null` while `saved.getCompanyId()` contains the actual persisted identifier. That means the generated app’s create response and detail route are still misaligned for this stronger real-world contract.

## Generated Downstream/Handoff Artifact Verification

These generated runtime artifacts were present before the proof stopped:

- `src/main/java/com/appbuilder/customerops/adapter/outbound/CustomerEodHandoffFileWriter.java`
- `src/main/java/com/appbuilder/customerops/adapter/outbound/CustomerStagingWriter.java`
- `src/main/java/com/appbuilder/customerops/batch/CustomerEodBatchJob.java`
- `src/main/java/com/appbuilder/customerops/adapter/inbound/BatchTriggerController.java`

## Warnings Observed

Generation still emitted warnings, including:

- `data.*` response mappings not found in the response sample
- response-envelope fields auto-included into the canonical model
- handoff mapping targets like `customer_id` / `customer_name` reported as unknown contract fields
- ambiguous id-field inference between `companyId` and `id`

These warnings matter because the remaining runtime failure aligns with the still-ambiguous ID ownership in the generated model.

## Ownership

- Studio: no new blocker in this rerun
- Engine / generated runtime behavior: current blocker
- Source spec: same stronger real-world control input as PR #20

## Conclusion

This rerun is another real step forward in the PR #20 red-to-green chain:

- PR #52 fixed the original classifier crash
- PR #53 fixed the duplicate response DTO compile failure
- the exact same proof now builds and runs successfully

But the control case is still not fully green end-to-end:

- runtime CRUD detail lookup still fails because the generated app returns `id: null` after create while persisting under `companyId`
- downstream/handoff runtime smoke was not reached in the unchanged proof flow because the detail-route check failed first

So PR #20 is now much closer to green, but the remaining blocker has moved to CRUD runtime ID alignment for this stronger real-world contract.

## Commands Used

```bash
python3 -B scripts/proof_run_codat_customer_downstream_handoff.py
```
