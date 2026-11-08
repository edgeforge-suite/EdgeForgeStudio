# Studio KS MVP Smoke Proof — 2026-04-20

## Date / Baseline

- Repo: `santosh-sh/EdgeForgeStudio`
- Branch at run time: `main`
- Studio commit tested: `5f35b3a`
- Local URL used: `http://127.0.0.1:8081`

This report records an already-completed manual smoke/proof for the bounded
field-suggestion-only Studio + KS MVP. It is a durable artifact of that run,
not a new execution in this PR.

## Scope of Proof

This smoke covered the shipped Studio + KS MVP path only:

- Step 1 Knowledge Workspace upload / ingest / search / read / field-catalog foundation
- durable KS workspace linkage through save/open
- CRUD Step 3 field suggestion review with batched write-back
- Step 7 provenance review for current field-suggestion-backed workflow
- Step 8 `evidence-trail.json` export and manifest revision tracking

This proof did **not** attempt to cover:

- non-field suggestion flows
- manifest prefill
- generic chat / Q&A retrieval
- full-manifest provenance beyond the current field-suggestion-backed workflow

## Test Data Bundle

- Local deterministic bundle path:
  - `/tmp/edgeforge-studio-ks-smoke-final`
- Bundle files:
  - `account-service-openapi.yaml`
  - `account_dictionary.csv`
  - `account_schema.sql`
  - `account_policy.md`
  - `loan_reference.csv`
- Saved Studio project snapshot:
  - `/tmp/edgeforge-studio-ks-smoke-final/studio-ks-smoke-project.json`
- Export directory:
  - `/tmp/edgeforge-studio-ks-smoke-final/exports/account-servicing`

## Workflow Exercised

1. Opened Studio at `http://127.0.0.1:8081`
2. Used the Step 1 Knowledge Workspace with the bundle above
3. Preserved the KS workspace linkage through Studio save/open
4. Reviewed three CRUD Step 3 field suggestions
5. Reopened the saved Studio project and confirmed durability
6. Checked Step 7 provenance summary
7. Exported the package and verified Step 8 sidecar output plus manifest revision append

## Results

### Durable workspace linkage

- Durable workspace namespace / linkage:
  - `studio-ks-8aa55a49-62e2-4215-97f3-466966558e2e`
- The same `project_id` and `ks_project_id` survived save/open

### Review decisions exercised

- accepted as-is:
  - `credit_limit`
- edited then accepted:
  - `status_code`
- rejected:
  - `legacy_branch_code`
- Happy-path review write-back:
  - `partial_failure: false`

### Reopen durability

Reopen preserved:

- workspace namespace
- review buckets
- review history count: `3`
- evidence link count: `2`

### Step 7 provenance summary observed

- `ACCEPTED=1`
- `EDITED=1`
- `REJECTED=1`
- `LINKED EVIDENCE=2`

## Artifacts Verified

### Step 8 export outputs

The smoke export wrote:

- `app-definition.yaml`
- `evidence-trail.json`

The exported `evidence-trail.json` contained evidence links for:

- `entities.Account.fields.credit_limit`
- `entities.Account.fields.status_code`

Observed provenance summary:

```text
{'human_authored': 0, 'ai_accepted': 1, 'ai_edited': 1, 'no_evidence': 0}
```

### Manifest revision tracking

`manifest_revisions` appended successfully with revision:

- `rev-8bffa8a9-8e16-4ffa-a789-688593036876`

## Limitations / Not Covered

This bounded proof should not be interpreted as evidence for:

- non-field KS suggestion scopes
- rules or mappings review flows
- manifest prefill
- generic chat / Q&A surfaces
- full-manifest provenance coverage
- reconnect automation beyond the exercised durable linkage / reopen path

## Notes / Follow-up

- Minor UX note:
  - Step 1 Knowledge Workspace copy still said review persistence / evidence export were out of scope even though the shipped later-stage workflow worked
- This note was non-blocking and did not invalidate the smoke pass

## Final Conclusion

- Smoke conclusion: `pass with notes`

The bounded field-suggestion-only Studio KS MVP worked end to end for the
exercised path: document workspace foundation, durable save/open linkage, CRUD
Step 3 review write-back, Step 7 provenance summary, and Step 8
`evidence-trail.json` export plus manifest revision append.
