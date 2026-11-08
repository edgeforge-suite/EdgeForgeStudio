# Studio CRUD Proof Smoke — 2026-03-31

## Goal

Re-prove that the merged EdgeForgeStudio CRUD export path still works cleanly against the current merged EdgeForge `main` baseline after recent Engine Phase 2 work, and capture a fresher artifact than older smoke reports.

This run uses the merged Studio proof-run path from PR #15 plus the PR #16 hard-fail API smoke gate.

## Baselines Used At Run Time

### EdgeForgeStudio

- Repo: `santosh-sh/EdgeForgeStudio`
- Branch used for the run: `codex/feature/studio-refresh-crud-proof-smoke`
- Baseline source: `origin/main`
- Baseline commit: `07c5de640b5666a21d60db69d07ed25e96e3077f`
- Baseline meaning: merge of Studio PR #15 (`[FEATURE] Prove Studio real-app E2E flow on current EdgeForge main`)

Note: Studio PR #16 was merged into the PR #15 branch before PR #15 merged, so the hard-fail `GET /pets` smoke gate is included in this Studio `main` baseline even though PR #16 was not a separate merge into `main`.

### EdgeForge

- Repo: `santosh-sh/EdgeForge`
- Branch used for the run: `main`
- Baseline commit: `7a487e2fc908400e6dc003f3628a0a12ed7b6fb3`
- Current merged Engine baseline confirmed in local `main`: PRs #45, #46, #47, #48, #49 are present

### EdgeForge PR #50 Status

- PR #50 (`codex/feature/phase2a-passthrough-emitter`) was still **OPEN** at run time
- It was treated as **not relevant** to this CRUD proof path

## Proof Path Used

- Script: `python3 scripts/proof_run_petstore.py`
- Spec: Petstore OpenAPI 3.0 — `https://petstore3.swagger.io/api/v3/openapi.json`
- Scope: `Pet` entity with `addPet` and `getPetById`
- Target profile: `springboot-legacy-compatible`

## Important Environment Note

The proof script requires live network access to fetch the Petstore OpenAPI document at ingest time. In the agent sandbox, the first attempt failed with:

```text
AssertionError: Ingest URL failed: 400 {"ok":false,"error":"[Errno 8] nodename nor servname provided, or not known"}
```

The run succeeded once the script was re-executed with network access enabled. This is an execution-environment constraint, not a Studio or Engine defect.

## Result Summary

| Step | Result |
|------|--------|
| Studio wizard / export path | PASS |
| Manifest verification | PASS |
| Engine validation | PASS |
| Engine generation | PASS |
| Maven build | PASS |
| App startup | PASS |
| Actuator health check | PASS |
| `GET /pets` API smoke | PASS |

## Commands Run

### Full proof script

```bash
python3 scripts/proof_run_petstore.py
```

### Engine validation command executed by the script

```text
/Library/Developer/CommandLineTools/usr/bin/python3 -c import sys
sys.path.insert(0, '<edgeforge-engine-repo>')
from appbuilder.contracts.manifest import load_project_definition
load_project_definition('/var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_proofrun_uwbc255b/pets/app-definition.yaml')
print('VALID')
```

### Engine generation command executed by the script

```text
/Library/Developer/CommandLineTools/usr/bin/python3 -m appbuilder.cli generate --manifest /var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_proofrun_uwbc255b/pets/app-definition.yaml --output /var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_proofrun_uwbc255b/generated-petstore
```

### Maven build command executed by the script

```text
mvn clean package -DskipTests --batch-mode
```

### Generated app launch command executed by the script

```text
/opt/homebrew/opt/openjdk@17/bin/java -jar /var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_proofrun_uwbc255b/generated-petstore/target/pets-0.0.1-SNAPSHOT.jar --server.port=8095
```

## Detailed Results

### 1. Studio Wizard / Export Path

- Entities classified: `Order`, `Category`, `User`, `Tag`, `Pet`, `ApiResponse`
- Operations classified: `19`
- Selected interface: `pets-pet-api`
- Completeness summary: `8 READY`, `4 WARNING`, `0 MANUAL_FOLLOW_UP`
- Export output dir:
  - `/var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_proofrun_uwbc255b/pets`
- Files written:
  - `contracts/pets-pet-api-spec.json`
  - `upstream/sample-addpet-request.json`
  - `upstream/sample-addpet-response.json`
  - `upstream/sample-getpetbyid-response.json`
  - `upstream/pets-pet-api-mapping.yaml`
  - `app-definition.yaml`
  - `completeness-report.md`
  - `assessment-report.json`

### 2. Manifest Verification

- `schema_version: 1.0`
- `app_archetype: crud`
- `app_name: Petstore Pet Service`
- `bounded_context: pets`
- `upstream_interfaces: ['pets-pet-api']`

Result: PASS

### 3. Engine Validation

- Result: `Manifest is valid (passed AppBuilder validation)`
- Success: `True`
- Exit code: `0`
- Duration: `0.196s`

Result: PASS

### 4. Engine Generation

Output:

```text
Generated application at: /var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_proofrun_uwbc255b/generated-petstore
Files created: 20
Harness: PASSED
```

- Success: `True`
- Exit code: `0`
- Duration: `0.342s`
- Total files generated: `20`
- Java source files generated: `14`

Result: PASS

### 5. Maven Build

- `JAVA_HOME`: `/opt/homebrew/opt/openjdk@17`
- Return code: `0`
- Total time: `2.609 s`

Last 20 lines included:

```text
[INFO] BUILD SUCCESS
[INFO] Total time:  2.609 s
[INFO] Finished at: 2026-03-31T08:41:34-05:00
```

Result: PASS

### 6. App Startup + Health Check

- Port: `8095`
- Startup time to health: `~4.1s`
- Health response:

```json
{"status":"UP","components":{"db":{"status":"UP","details":{"database":"H2","validationQuery":"isValid()"}},"diskSpace":{"status":"UP","details":{"total":494384795648,"free":39773220864,"threshold":10485760,"path":"/private/var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_proofrun_uwbc255b/generated-petstore/.","exists":true}},"ping":{"status":"UP"}}}
```

Result: PASS

### 7. API Smoke

- Endpoint: `GET /pets`
- HTTP status: `200`
- Response body:

```json
[]
```

The merged PR #16 logic correctly treats this as a hard gate; a non-200, `HTTPError`, `URLError`, or non-array body would have failed the run.

Result: PASS

## Warnings Observed

### Warning-level but non-blocking proof-scope items

- Completeness report recorded `4 WARNING`s because downstream interfaces, data handoffs, and rules were intentionally skipped for this minimal CRUD proof

### Environment warning

- The live Petstore fetch required network access and failed under the default sandbox environment before being rerun with network access enabled

### No product warnings surfaced in the scripted path

- No Engine validation warnings surfaced
- No Engine generation warnings surfaced
- No Maven build failure or warning caused the build to fail
- No app health or `/pets` smoke warnings remained after the run completed

Note: this script does not preserve full application startup logs on the success path, so this artifact should not overclaim that zero runtime log warnings existed. It only confirms that no warnings surfaced in the captured proof outputs and that the app started healthy.

## Ownership

| Observation | Owner | Notes |
|-------------|-------|-------|
| Live-spec fetch needs network access | Environment | Not a Studio or Engine defect |
| Warning-level completeness items from skipped downstream/handoffs/rules | Proof scope | Expected for a minimal CRUD proof |
| Studio export compatibility with current Engine main | Shared contract | Confirmed working |
| Recent Engine Phase 2 work through PR #49 | Engine baseline | No regression observed on CRUD proof path |
| EdgeForge PR #50 still open | Not relevant to this proof | Passthrough-router emitter work was not part of the CRUD path exercised here |

## Conclusion

This remains a **clean CRUD proof on current `main`**:

- current Studio CRUD export remains compatible with current EdgeForge `main`
- recent Engine Phase 2 work through PR #49 did **not** regress the proven CRUD path
- the merged Studio proof-run path from PRs #15 and #16 still works end to end on a fresh run

## Suggested Next Stronger Candidate

If a second stronger smoke is wanted later, the next best candidate is not another minimal Petstore rerun. The next increment should be a proof that exercises more of the Studio package shape, for example:

- one CRUD-friendly spec plus a simple downstream mapping, or
- one CRUD-friendly spec plus a staging-table handoff

That would extend confidence beyond the minimal upstream-only CRUD proof without broadening into passthrough-router work.
