# Stronger Real-World CRUD Proof — 2026-03-31 (Post-PR51 Red-to-Green)

## Goal

Re-run the exact stronger real-world CRUD proof from Studio PR #18 after EdgeForge PR #51 merged, to confirm whether the original ConfigCat failure now turns green end to end.

This is a red-to-green confirmation run, not a new proof target.

## Previous Failure Cause

The original ConfigCat proof in `docs/test-results/stronger-realworld-crud-proof-2026-03-31-configcat.md` failed at Maven build time.

Root cause:

- EdgeForge generated raw hyphenated OpenAPI operation IDs directly into Java method names
- examples:
  - `create-permission-group`
  - `get-permission-groups`
  - `get-permission-group`
  - `update-permission-group`
- result:
  - generated Java did not compile

Ownership of that original failure:

- Engine-owned
- not a Studio export/package problem

## Exact Proof Case Reused

The proof target was intentionally unchanged from PR #18:

- API: ConfigCat Public Management API
- source URL: `https://api.apis.guru/v2/specs/configcat.com/v1/openapi.yaml`
- local pinned spec used for reproducibility:
  - `/tmp/openapi-directory/APIs/configcat.com/v1/openapi.yaml`
- selected entity:
  - `PermissionGroupModel`
- selected operations:
  - `create-permission-group`
  - `get-permission-groups`
  - `get-permission-group`
  - `update-permission-group`
- script:
  - `python3 scripts/proof_run_configcat_permission_groups.py`

## Baselines Used At Run Time

### EdgeForgeStudio

- Repo: `santosh-sh/EdgeForgeStudio`
- Branch used: `codex/feature/studio-stronger-realworld-crud-proof`
- Baseline source: PR #18 branch
- Mainline base: `13119ad689898dda976b5b5d5ee4ae43430ee9c3`
- Proof harness update in this rerun:
  - ConfigCat runner now writes startup output to `startup.log` instead of an unread pipe, avoiding a false negative from verbose Spring startup logs

### EdgeForge

- Repo: `santosh-sh/EdgeForge`
- Branch used: `main`
- Baseline commit: `fc370cb283da950faa73c9a32a4f09dcd7a18948`
- Baseline meaning:
  - merge of Engine PR #51
  - Java identifier sanitization fix for operation-derived symbols

## Result Summary

| Step | Result |
|------|--------|
| Studio intake/export | PASS |
| Manifest verification | PASS |
| Engine validation | PASS |
| Engine generation | PASS |
| Maven build | PASS |
| App startup | PASS |
| Actuator health | PASS |
| API smoke | PASS |

## Commands Run

### Proof script

```bash
python3 scripts/proof_run_configcat_permission_groups.py
```

### Engine validation command executed by the script

```text
/Library/Developer/CommandLineTools/usr/bin/python3 -c import sys
sys.path.insert(0, '<edgeforge-engine-repo>')
from appbuilder.contracts.manifest import load_project_definition
load_project_definition('/var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_configcat_proofrun_t2wy9jov/permissions/app-definition.yaml')
print('VALID')
```

### Engine generation command executed by the script

```text
/Library/Developer/CommandLineTools/usr/bin/python3 -m appbuilder.cli generate --manifest /var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_configcat_proofrun_t2wy9jov/permissions/app-definition.yaml --output /var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_configcat_proofrun_t2wy9jov/generated-configcat-permission-groups
```

### Maven build command executed by the script

```text
mvn clean package -DskipTests --batch-mode
```

### Generated app launch command executed by the script

```text
/opt/homebrew/opt/openjdk@17/bin/java -jar /var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_configcat_proofrun_t2wy9jov/generated-configcat-permission-groups/target/permissions-0.0.1-SNAPSHOT.jar --server.port=8096
```

## Detailed Results

### 1. Studio Intake / Export

- Entities classified: `79`
- Operations classified: `63`
- Selected interface:
  - `permissions-permissiongroupmodel-api`
- Completeness summary:
  - `10 READY`
  - `4 WARNING`
  - `0 MANUAL_FOLLOW_UP`
  - `exportable: true`
- Export output dir:
  - `/var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_configcat_proofrun_t2wy9jov/permissions`

Result: PASS

### 2. Manifest Verification

- `schema_version: 1.0`
- `app_archetype: crud`
- `app_name: ConfigCat Permission Group Service`
- `bounded_context: permissions`
- `upstream_interfaces: ['permissions-permissiongroupmodel-api']`

Result: PASS

### 3. Engine Validation

- Output:
  - `Manifest is valid (passed AppBuilder validation)`
- Success: `True`
- Exit code: `0`
- Duration: `0.174s`

Result: PASS

### 4. Engine Generation

Output:

```text
Generated application at: /var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_configcat_proofrun_t2wy9jov/generated-configcat-permission-groups
Files created: 24
Harness: PASSED
```

- Success: `True`
- Exit code: `0`
- Duration: `0.936s`
- Total files generated: `24`
- Java source files generated: `18`

Result: PASS

### 5. Maven Build

- `JAVA_HOME`: `/opt/homebrew/opt/openjdk@17`
- Return code: `0`
- Total time: `1.815 s`

Last 20 lines included:

```text
[INFO] BUILD SUCCESS
[INFO] Total time:  1.815 s
[INFO] Finished at: 2026-03-31T14:55:08-05:00
```

Result: PASS

### 6. App Startup + Health

- Port: `8096`
- Startup time to health: `~4.1s`
- Health response:

```json
{"status":"UP","components":{"db":{"status":"UP","details":{"database":"H2","validationQuery":"isValid()"}},"diskSpace":{"status":"UP","details":{"total":494384795648,"free":37907263488,"threshold":10485760,"path":"/private/var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_configcat_proofrun_t2wy9jov/generated-configcat-permission-groups/.","exists":true}},"ping":{"status":"UP"}}}
```

Result: PASS

### 7. API Smoke

- Collection endpoint discovered from generated controller:
  - `/permission_group_models`
- Request:
  - `GET /permission_group_models`
- HTTP status:
  - `200`
- Response body:

```json
[]
```

Result: PASS

## Red-to-Green Conclusion

The original stronger real-world CRUD blocker is now closed.

What changed:

- before PR #51:
  - same ConfigCat case failed at Maven build due to invalid Java identifiers derived from hyphenated operation IDs
- after PR #51:
  - same ConfigCat case now validates, generates, builds, starts, returns healthy actuator status, and passes runtime API smoke

This is a clean red-to-green confirmation of the PR #18 failure case.

## Residual Warnings / Notes

### Expected proof-scope warnings

- Completeness still reported `4 WARNING`s because downstream interfaces, handoffs, and rules were intentionally skipped for this focused CRUD proof

### Startup/runtime environment note

- In the default agent sandbox, the generated Spring Boot app may fail to bind a localhost port with:
  - `java.net.SocketException: Operation not permitted`
- That is an execution-environment restriction, not a generated-app defect
- The successful end-to-end runtime confirmation was completed outside that port-binding restriction

### Startup logging note

- The ConfigCat proof runner now writes Spring Boot startup logs to `startup.log`
- This avoids a false negative where verbose startup output could block an unread subprocess pipe during health polling

## Ownership

| Observation | Owner | Notes |
|-------------|-------|-------|
| Original ConfigCat compile blocker | Engine | Closed by PR #51 |
| Studio export/package shape | Studio / shared contract | Confirmed clean |
| Current end-to-end ConfigCat proof | Shared contract | Now green |
| Localhost bind restriction inside default agent sandbox | Environment | Not a product defect |

## Final Assessment

Yes: the same ConfigCat proof case now passes end to end after EdgeForge PR #51.

That closes the stronger real-world CRUD proof blocker originally recorded in Studio PR #18.
