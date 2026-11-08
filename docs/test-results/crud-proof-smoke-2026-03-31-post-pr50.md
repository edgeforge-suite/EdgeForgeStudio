# Studio CRUD Proof Smoke — 2026-03-31 (Post-PR50)

## Goal

Re-run the merged EdgeForgeStudio CRUD proof path after EdgeForge PR #50 merged, to confirm that the newly landed passthrough-router emitter / engine wiring work did not regress the already proven CRUD path.

This is a fresh rerun of the full Studio proof script against the newer Engine baseline. It is intentionally narrower than a new domain/spec expansion run.

## Baselines Used At Run Time

### EdgeForgeStudio

- Repo: `santosh-sh/EdgeForgeStudio`
- Branch used for the rerun: `codex/feature/studio-refresh-crud-proof-smoke`
- Baseline source: `origin/main`
- Baseline commit: `07c5de640b5666a21d60db69d07ed25e96e3077f`
- Baseline meaning: merged Studio proof-run path from PR #15, including the PR #16 hard-fail `/pets` API smoke gate

### EdgeForge

- Repo: `santosh-sh/EdgeForge`
- Branch used for the rerun: `main`
- Baseline commit: `84fcc9a6c034d6846be1e848e62c11dfe5649308`
- Baseline meaning: merge of Engine PR #50 (`[FEATURE] Phase 2A: passthrough-router emitter and engine wiring`)

## Why This Rerun Was Needed

The previous fresh CRUD proof artifact on 2026-03-31 ran against Engine `main` at `7a487e2` (through PR #49). After that run, Engine PR #50 merged. Although PR #50 is passthrough-focused, it touched shared generation entry points such as:

- `appbuilder/generation/engine.py`
- `appbuilder/generation/build_emitter.py`

So the correct follow-up was to rerun the existing CRUD proof once on the newer Engine baseline before deciding whether to broaden into a stronger domain/spec smoke.

## Proof Path Used

- Script: `python3 scripts/proof_run_petstore.py`
- Spec: Petstore OpenAPI 3.0 — `https://petstore3.swagger.io/api/v3/openapi.json`
- Scope: `Pet` entity with `addPet` and `getPetById`
- Target profile: `springboot-legacy-compatible`

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
load_project_definition('/var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_proofrun_bj41mjxz/pets/app-definition.yaml')
print('VALID')
```

### Engine generation command executed by the script

```text
/Library/Developer/CommandLineTools/usr/bin/python3 -m appbuilder.cli generate --manifest /var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_proofrun_bj41mjxz/pets/app-definition.yaml --output /var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_proofrun_bj41mjxz/generated-petstore
```

### Maven build command executed by the script

```text
mvn clean package -DskipTests --batch-mode
```

### Generated app launch command executed by the script

```text
/opt/homebrew/opt/openjdk@17/bin/java -jar /var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_proofrun_bj41mjxz/generated-petstore/target/pets-0.0.1-SNAPSHOT.jar --server.port=8095
```

## Detailed Results

### 1. Studio Wizard / Export Path

- Entities classified: `Order`, `Category`, `User`, `Tag`, `Pet`, `ApiResponse`
- Operations classified: `19`
- Selected interface: `pets-pet-api`
- Completeness summary: `8 READY`, `4 WARNING`, `0 MANUAL_FOLLOW_UP`
- Export output dir:
  - `/var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_proofrun_bj41mjxz/pets`

Result: PASS

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
Generated application at: /var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_proofrun_bj41mjxz/generated-petstore
Files created: 20
Harness: PASSED
```

- Success: `True`
- Exit code: `0`
- Duration: `0.323s`
- Total files generated: `20`
- Java source files generated: `14`

Result: PASS

### 5. Maven Build

- `JAVA_HOME`: `/opt/homebrew/opt/openjdk@17`
- Return code: `0`
- Total time: `2.060 s`

Last 20 lines included:

```text
[INFO] BUILD SUCCESS
[INFO] Total time:  2.060 s
[INFO] Finished at: 2026-03-31T08:54:51-05:00
```

Result: PASS

### 6. App Startup + Health Check

- Port: `8095`
- Startup time to health: `~4.1s`
- Health response:

```json
{"status":"UP","components":{"db":{"status":"UP","details":{"database":"H2","validationQuery":"isValid()"}},"diskSpace":{"status":"UP","details":{"total":494384795648,"free":39614644224,"threshold":10485760,"path":"/private/var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_proofrun_bj41mjxz/generated-petstore/.","exists":true}},"ping":{"status":"UP"}}}
```

Result: PASS

### 7. API Smoke

- Endpoint: `GET /pets`
- HTTP status: `200`
- Response body:

```json
[]
```

The merged PR #16 logic remained effective here: non-200, `HTTPError`, `URLError`, or non-array responses would have failed the proof.

Result: PASS

## Warnings Observed

### Warning-level but expected proof-scope items

- Completeness report still recorded `4 WARNING`s because downstream interfaces, data handoffs, and rules were intentionally skipped for this minimal CRUD proof

### Environment note

- This live-spec proof still requires network access to fetch Petstore during ingest

### No regression warnings surfaced from PR #50

- No Engine validation warnings surfaced
- No Engine generation warnings surfaced
- No build failure or runtime health/API regression surfaced

## Ownership

| Observation | Owner | Notes |
|-------------|-------|-------|
| CRUD proof path still green after PR #50 | Shared contract | Confirmed |
| Passthrough-router work in PR #50 | Engine | Did not regress the CRUD lane in this rerun |
| Warning-level completeness items from skipped downstream/handoffs/rules | Proof scope | Expected for the minimal CRUD proof |
| Live-spec fetch requires network access | Environment | Not a Studio or Engine defect |

## Conclusion

This remains a **clean CRUD proof on current EdgeForge `main` after PR #50**:

- current Studio CRUD export remains compatible with current EdgeForge `main`
- Engine PR #50 did **not** regress the proven CRUD path
- the right next move is no longer “rerun the same Petstore proof again,” because that regression check is now complete

## Recommended Next Smoke

The next strongest follow-up is a **new real-world OpenAPI smoke**, not another Petstore repetition.

Best next step:

- pick one manageable real domain spec that is still CRUD-friendly
- keep the same end-to-end gate:
  - Studio export
  - manifest verification
  - Engine validate/generate
  - build
  - health
  - lightweight API check

That would extend confidence beyond the minimal Petstore lane while keeping the proof path honest and current.
