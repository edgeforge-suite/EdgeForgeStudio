# Composite Proof — Codat Customer + Downstream/Handoff — 2026-03-31

## Goal

Run the next meaningful Studio-led real-world proof beyond Petstore and ConfigCat by trying one combined package that covers both:

1. richer upstream path/query parameter behavior
2. downstream/handoff-including package shape

This run intentionally used one combined candidate first, rather than splitting into two proofs, because the selected package could exercise both goals without leaving the current CRUD lane.

## Selected Candidate

- Source spec: pinned local copy of Codat Accounting API 2.1.0
- Source URL: `https://api.apis.guru/v2/specs/codat.io/accounting/2.1.0/openapi.yaml`
- Local pinned path: `/tmp/openapi-directory/APIs/codat.io/accounting/2.1.0/openapi.yaml`
- Entity scope: `Customer`
- Selected upstream operations:
  - `create-customer`
  - `get-customers`
  - `get-customer`
  - `update-customer`

## Why This Was Stronger Than Petstore and ConfigCat

- The upstream contract includes multiple path parameters and query parameters on the selected `Customer` flow.
- `create-customer` includes path params plus `timeoutInMinutes` query param.
- `update-customer` includes path params plus `timeoutInMinutes` and `forceUpdate` query params.
- `get-customers` includes query-driven list behavior (`page`, `pageSize`, `query`, `orderBy`) plus a path param.
- The Studio package also included:
  - one downstream fixed-width interface
  - one staging-table handoff

That made this the first combined proof candidate that stretched both upstream parameter richness and downstream/handoff package shape in one run.

## Baselines Used

- EdgeForgeStudio base on `main` before this branch work: `a2beea2c5695e32fc1929d960a212f2dda4dd04a`
- EdgeForge `main`: `fc370cb283da950faa73c9a32a4f09dcd7a18948`
- Old Engine smoke PR `#40`: not used as source of truth

## Studio-Side Narrow Fix Included In This Branch

Before the combined proof could even export, Studio hit a real pre-export bug:

- Step 3 auto-sample generation crashed on OpenAPI fields whose `type` is a list such as `["string", "null"]`
- Root cause: `app/services/openapi_service.py` assumed `type` was always a scalar string
- Fix in this branch: normalize list-valued `type` fields by choosing the first non-`null` candidate
- Regression coverage added in `tests/test_openapi_service.py`

This fix is Studio-owned. It removed the pre-export blocker and allowed the proof to reach Engine generation.

## E2E Results

| Step | Result | Notes |
|------|--------|-------|
| Studio intake / spec ingestion | ✅ PASS | `94` entities, `127` operations classified |
| Entity + operation selection | ✅ PASS | `Customer` plus `create-customer`, `get-customers`, `get-customer`, `update-customer` |
| Upstream samples + mappings | ✅ PASS | Curated samples used to avoid wrapper-noise from response envelopes |
| Downstream interface save | ✅ PASS | one fixed-width interface |
| Data handoff save | ✅ PASS | one staging-table handoff |
| Completeness | ✅ PASS | `14 READY`, `2 WARNING`, `0 MANUAL FOLLOW-UP`, exportable |
| Manifest export | ✅ PASS | `schema_version: "1.0"`, `app_archetype: crud` |
| Package-shape verification | ✅ PASS | downstream + handoff files present |
| Engine manifest validation | ✅ PASS | manifest accepted on EdgeForge `main` |
| Engine generation | ❌ FAIL | blocked by Engine OpenAPI classifier on list-valued `type` fields |
| Maven build | ⛔ NOT REACHED | blocked by generation |
| App startup / health | ⛔ NOT REACHED | blocked by generation |
| API smoke | ⛔ NOT REACHED | blocked by generation |
| Batch/handoff runtime smoke | ⛔ NOT REACHED | blocked by generation |

## Exported Package Shape Verification

The exported Studio package correctly contained the combined package-shape artifacts:

- `downstream/customer-eod-handoff-file-layout.yaml`
- `downstream/customer-eod-handoff-file-mapping.yaml`
- `downstream/customer-eod-handoff-file-sample.txt`
- `data-handoffs/customer-staging-table.sql`
- `data-handoffs/customer-staging-table-mapping.yaml`

The exported upstream mapping also captured the richer operation set:

- `create-customer`
- `get-customers`
- `get-customer`
- `update-customer`

## Completeness Warnings

The run produced two non-blocking Studio warnings:

- no business rules defined
- no legacy notes provided

These were not related to the proof failure.

## Failure Detail

### Observed generation failure

`run_generate()` failed with:

```text
ERROR: 'list' object has no attribute 'lower'
```

### Isolated traceback

```text
Traceback (most recent call last):
  File "<stdin>", line 7, in <module>
  File ".../EdgeForge/appbuilder/metadata/translation.py", line 154, in build_metadata_project
    return translate_project(definition, project_root=manifest_file.parent)
  File ".../EdgeForge/appbuilder/metadata/translation.py", line 253, in translate_project
    openapi_ops = ingest_openapi_operations(openapi_spec_for_interface, interface.name)
  File ".../EdgeForge/appbuilder/ingestion/openapi_classifier.py", line 120, in ingest_openapi_operations
    response_fields=_extract_operation_response_fields(
  File ".../EdgeForge/appbuilder/ingestion/openapi_classifier.py", line 159, in _extract_operation_response_fields
    for field in _extract_operation_shape_fields(
  File ".../EdgeForge/appbuilder/ingestion/openapi_classifier.py", line 182, in _extract_operation_shape_fields
    for field in extract_entity_fields(
  File ".../EdgeForge/appbuilder/ingestion/openapi_classifier.py", line 583, in extract_entity_fields
    type=openapi_type_to_canonical_type(
  File ".../EdgeForge/appbuilder/ingestion/openapi_classifier.py", line 665, in openapi_type_to_canonical_type
    normalized_type = (openapi_type or "").lower()
AttributeError: 'list' object has no attribute 'lower'
```

### Root cause

The selected real-world OpenAPI 3.1 spec uses list-valued `type` declarations such as nullable unions. Engine generation currently assumes `openapi_type` is always a scalar string at `openapi_type_to_canonical_type()`.

## Ownership

- Studio: pre-export sample-generation bug found and fixed in this branch
- Engine: current blocking failure during generation
- Generated app: not reached
- Source spec: valid stronger real-world input that exposed an unsupported Engine classifier assumption

## Conclusion

This combined proof is valuable even though it is red:

- Studio now exports the combined upstream + downstream + handoff package cleanly
- the package validates on current EdgeForge `main`
- the next real boundary is Engine generation support for list-valued OpenAPI `type` fields in the selected real-world spec

This should now be treated as a precise red-to-green control proof. Once the Engine thread lands the corresponding fix, rerun the exact same proof script unchanged.

## Commands Used

```bash
python3 -B -m pytest tests/test_openapi_service.py -q
python3 -B scripts/proof_run_codat_customer_downstream_handoff.py
```
