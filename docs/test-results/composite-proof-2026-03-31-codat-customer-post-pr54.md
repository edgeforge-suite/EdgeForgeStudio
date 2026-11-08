# Composite Proof Red-to-Green Control Check — Codat Customer + Downstream/Handoff — 2026-03-31 Post-PR54

## Goal

Re-run the exact same composite Codat proof from PR #20 against the updated EdgeForge PR #54 branch to confirm whether the remaining runtime CRUD ID-alignment blocker turns green.

This remains a control rerun, not a new candidate.

## Failure State Before PR #54

The prior rerun after PR #53 had already closed the original classifier failure and the duplicate-response-DTO compile failure, but the same proof still failed at runtime detail lookup:

- `POST /customers` returned `id: null`
- the response contained a generated `companyId`
- the follow-up detail request became `GET /customers/null`
- the generated app returned `404`

Owner at that point: Engine / generated runtime behavior.

## Baselines Used For This Rerun

- EdgeForgeStudio branch: `codex/feature/studio-composite-proof-next`
- EdgeForgeStudio branch HEAD before this artifact: `cd2c187159886a9357794bc9c568bf0345ce5e1f`
- EdgeForge branch: `codex/fix/id-field-alignment-codat`
- EdgeForge branch HEAD: `1576a1b`
- EdgeForge baseline note: PR #54 updated the real Codat-style `{customerId}` id-selection fix on this branch

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
| Engine generation | ✅ PASS | prior PR #20 / post-PR52 blockers remain closed |
| Generated downstream/handoff artifact verification | ✅ PASS | writers + batch controller generated |
| Maven build | ✅ PASS | prior post-PR53 blocker is closed |
| App startup / actuator health | ✅ PASS | successful outside sandbox |
| CRUD list smoke | ✅ PASS | `GET /customers -> HTTP 200 []` |
| CRUD create smoke | ✅ PASS | `POST /customers -> HTTP 201` with non-null `id` |
| CRUD detail smoke | ✅ PASS | `GET /customers/{id} -> HTTP 200` |
| Runtime downstream/handoff smoke | ✅ PASS | batch trigger completed and produced EOD output file |

## What Turned Green After PR #54

The remaining runtime ID-alignment blocker is closed.

The same proof case now successfully reaches and passes the full end-to-end flow:

- Studio intake/export
- package-shape verification
- Engine validation
- Engine generation
- generated downstream/handoff artifact verification
- Maven build
- application startup
- actuator health check
- CRUD list/create/detail API calls
- batch/handoff runtime smoke

Concrete stats from this rerun:

- generation: `29` files created
- Java sources: `22`
- harness: `PASSED`
- Maven: `BUILD SUCCESS`
- health: `{"status":"UP", ...}`
- app start time: about `4.1s`

## Runtime Confirmation

Observed successful CRUD sequence:

```text
GET /customers -> HTTP 200, 0 item(s)
POST /customers -> HTTP 201, body: {"id":"f5e9a433-7b34-4a14-b20b-a56610c891e5", ...}
GET /customers after create -> HTTP 200, 1 item(s)
GET /customers/f5e9a433-7b34-4a14-b20b-a56610c891e5 -> HTTP 200, body: {..., "id":"f5e9a433-7b34-4a14-b20b-a56610c891e5", ...}
```

Observed successful downstream/handoff runtime sequence:

```text
POST /batch/run/customerEodJob -> HTTP 200, body: {"exitCode":"COMPLETED", ...}
EOD output file: .../customerops-eod/customer-eod-20260331.dat
```

## Generated Downstream/Handoff Artifact Verification

These generated runtime artifacts were present and exercised successfully:

- `src/main/java/com/appbuilder/customerops/adapter/outbound/CustomerEodHandoffFileWriter.java`
- `src/main/java/com/appbuilder/customerops/adapter/outbound/CustomerStagingWriter.java`
- `src/main/java/com/appbuilder/customerops/batch/CustomerEodBatchJob.java`
- `src/main/java/com/appbuilder/customerops/adapter/inbound/BatchTriggerController.java`

## Warnings Observed

Generation still emitted warnings, including:

- `data.*` response mappings not found in the response sample
- response-envelope fields auto-included into the canonical model
- handoff mapping targets like `customer_id` / `customer_name` reported as unknown contract fields

These warnings did not block generation, build, startup, CRUD smoke, or batch/handoff runtime smoke in this rerun.

## Ownership

- Studio: no current blocker in this rerun
- Engine: PR #54 closes the prior runtime ID-alignment blocker for this proof target
- Generated app: green in this rerun
- Source spec: same stronger real-world control input as PR #20

## Conclusion

This rerun closes the composite-proof blocker from PR #20.

The exact same Codat composite proof is now green end-to-end against the updated EdgeForge PR #54 branch:

- richer CRUD path/query behavior remains proven
- downstream/handoff package shape remains proven
- runtime CRUD detail lookup is now aligned with the generated create response
- downstream batch/handoff runtime smoke also completes successfully

That makes PR #20 merge-ready once the branch and PR thread reflect this final green state.

## Commands Used

```bash
python3 -B scripts/proof_run_codat_customer_downstream_handoff.py
```
