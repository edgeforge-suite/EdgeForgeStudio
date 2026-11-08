# Composite Proof Control Rerun — Codat Customer + Downstream/Handoff — 2026-04-02 Post-PR24

## Goal

Re-run the exact same composite Codat proof to confirm that the nested
mapping validation regression introduced by Studio PR #22 is fully closed
after Studio PR #24.

This is a control rerun only — not a new proof candidate.

## Background

Studio PR #22 added Step 3 upstream mapping validation that rejected mapping
source fields not found as top-level keys in the saved response sample.
The Codat `create-customer` and `update-customer` operations return an
envelope response (`{"data": {"id": ..., "customerName": ...}, ...}`), so
their mappings use dot-notation sources like `data.id` and `data.customerName`.
These paths are not top-level keys, so PR #22's validation incorrectly
blocked Step 3c and left the Codat lane at BLOCKED in the Phase 2 backlog
table.

Studio PR #24 fixed `_sample_fields()` in `app/routes/mappings.py` to emit
one level of dot-notation nested keys for any top-level value that is a
dict, while continuing to reject fields that genuinely don't exist in the
sample.

## Baselines Used

- EdgeForgeStudio: `main` @ `2ed69b8` (Merge PR #24)
- EdgeForge Engine: `main` @ `3940ae7` ([FIX] Initialize required server-set datetime lifecycle fields via @PrePersist — Engine PR #59)

## Proof Target Reused Unchanged

- Source spec: pinned local copy of Codat Accounting API 2.1.0
- Local pinned path: `/tmp/openapi-directory/APIs/codat.io/accounting/2.1.0/openapi.yaml`
- Entity scope: `Customer`
- Selected upstream operations: `create-customer`, `get-customers`, `get-customer`, `update-customer`
- Downstream shape: one fixed-width downstream interface + one staging-table handoff

Runner used unchanged: `scripts/proof_run_codat_customer_downstream_handoff.py`

## Result Summary

| Step | Result | Notes |
|------|--------|-------|
| Studio session reset | ✅ PASS | |
| Step 1 — project setup | ✅ PASS | |
| Step 2 — spec ingestion | ✅ PASS | 94 entities, 127 operations classified |
| Step 3 — entity + operation selection | ✅ PASS | `Customer` + 4 operations |
| Step 3b — operation samples | ✅ PASS | all 4 ops sampled |
| **Step 3c — upstream mappings (previously BLOCKED)** | ✅ **PASS** | `data.id`, `data.customerName` etc. now accepted |
| Step 4 — downstream fixed-width interface | ✅ PASS | |
| Step 5 — staging-table handoff | ✅ PASS | |
| Step 7 — completeness report | ✅ PASS | 14 READY, 2 WARNING, 0 MANUAL FOLLOW-UP |
| Step 8 — manifest export | ✅ PASS | `schema_version: "1.0"`, `app_archetype: crud`, 16 files |
| Step 9 — package-shape verification | ✅ PASS | all 5 downstream/handoff artifacts present |
| Step 10 — Engine manifest validation | ✅ PASS | manifest accepted by Engine |
| Step 11 — Engine generation | ✅ PASS | 29 files, 22 Java source files |
| Step 11b — generated artifact verification | ✅ PASS | all 4 downstream/handoff classes present |
| Step 12 — Maven build | ⚠️ SKIP | `mvn` not on PATH in this environment (environment constraint, not a product issue — same as all other proof lanes) |
| Steps 13–15 — app start / CRUD smoke / handoff smoke | ⚠️ SKIP | depends on Maven |

## The Regression Is Closed

Step 3c now passes with dot-notation response mapping sources. The upstream
mapping save for `create-customer` submitted 6 response mappings including
`data.id → Customer.id` and `data.customerName → Customer.customerName`
without any validation error. The same is true for `update-customer`.

The lane reaches Engine generation cleanly, producing the same output shape
as the last fully-green rerun (PR #54 baseline):

- 29 total files generated
- 22 Java source files
- `CustomerEodHandoffFileWriter.java` present
- `CustomerStagingWriter.java` present
- `CustomerEodBatchJob.java` present
- `BatchTriggerController.java` present

## Warnings Observed (non-blocking, same as prior green run)

Engine generation emitted the same advisory warnings as the prior green run.
None are regressions; all pre-existed the PR #24 fix:

- `data.*` response mapping fields auto-included in canonical model
  (envelope wrapper fields: `changes`, `companyId`, `dataConnectionKey`,
  `dataType`, `pushOperationKey`, `status`, `statusCode`,
  `timeoutInMinutes`, `timeoutInSeconds`, and list pagination fields)
- staging-table mapping targets (`customer_id`, `customer_name`,
  `status_cd`, `email_address`) reported as unknown contract fields

These warnings did not block generation. Both are tracked as Studio Phase 2
backlog items (1.1 paginated-wrapper guidance, 1.2 staging-table target
validation) and will be addressed in later PRs.

## Maven / Runtime

Maven build and app startup were not exercised because `mvn` is not on PATH
in this environment. This is identical to the situation in all four proof
lanes on the Phase 2 backlog table (public API and privately retained application proof lanes) and
is an environment-only constraint. The last fully-exercised Maven + runtime
result for this exact proof target was captured in
`docs/test-results/composite-proof-2026-03-31-codat-customer-post-pr54.md`
(Engine PR #54 baseline) and remains the reference for Maven + smoke
results.

## Ownership

- Studio PR #24: closes the nested mapping validation regression for
  envelope-pattern response samples.
- Engine: no change needed; Engine main @ PR #59 accepted the manifest
  without modification.
- Environment: Maven/Java not available; not a product issue.

## Conclusion

The Codat composite proof lane is green again through Engine generation on
current Studio main (post-PR #24) + Engine main (post-PR #59).

Backlog item 1.4 (`Mapping validation must support nested/dot-notation field
paths`) is closed.

## Commands Used

```bash
git checkout main && git pull origin main
python3 -B scripts/proof_run_codat_customer_downstream_handoff.py
```
