# Stronger Real-World CRUD Proof — 2026-03-31 (ConfigCat Permission Groups)

## Goal

Run the next stronger real-world CRUD proof on the merged Studio proof path, using a public business-domain OpenAPI contract that is meaningfully richer than Petstore while still staying inside the current CRUD lane.

This run was intended to prove:

1. Studio can ingest and export a richer real-world CRUD package.
2. EdgeForge Engine can validate and generate from that package on current `main`.
3. The generated Spring Boot app can build, start, and answer lightweight API smoke checks.

## Selected Spec

- API: ConfigCat Public Management API
- Original source URL: `https://api.apis.guru/v2/specs/configcat.com/v1/openapi.yaml`
- Local pinned spec used for the run:
  - `/tmp/openapi-directory/APIs/configcat.com/v1/openapi.yaml`
- Public source repo used to pin the spec locally:
  - `https://github.com/APIs-guru/openapi-directory`
- Pinned source repo commit:
  - `f7207cf0a5c56081d275ebae4cf615249323385d`

## Why This Is Stronger Than Petstore

This ConfigCat scope is a stronger CRUD proof target than the earlier Petstore flow because it exercises a more realistic business-domain contract:

- entity: `PermissionGroupModel`
- operations: `create-permission-group`, `get-permission-groups`, `get-permission-group`, `update-permission-group`
- multiple path-param flows:
  - `POST /v1/products/{productId}/permissions`
  - `GET /v1/products/{productId}/permissions`
  - `GET /v1/permissions/{permissionGroupId}`
  - `PUT /v1/permissions/{permissionGroupId}`
- richer entity shape than Petstore's minimal happy path:
  - `26` response fields
  - `24` request fields
  - required field: `name`
  - enum-backed fields: `accessType`, `newEnvironmentAccessType`
  - nested array/object field: `environmentAccesses`
  - many booleans used as real business controls

This stayed inside the current CRUD lane because the spec exposes direct request/response schemas for the chosen resource and does not require passthrough-router support.

## Baselines Used At Run Time

### EdgeForgeStudio

- Repo: `santosh-sh/EdgeForgeStudio`
- Branch used: `codex/feature/studio-stronger-realworld-crud-proof`
- Baseline source: `origin/main`
- Baseline commit: `13119ad689898dda976b5b5d5ee4ae43430ee9c3`
- Baseline meaning:
  - PR #13 merged
  - PR #14 merged
  - PR #15 merged
  - PR #16 merged
  - PR #17 merged
- Additional branch-local artifact used for this proof:
  - `scripts/proof_run_configcat_permission_groups.py`

### EdgeForge

- Repo: `santosh-sh/EdgeForge`
- Branch used: `main`
- Baseline commit: `84fcc9a6c034d6846be1e848e62c11dfe5649308`
- Baseline meaning:
  - current merged Engine baseline through PR #50

## Proof Path Used

- Script:
  - `python3 scripts/proof_run_configcat_permission_groups.py`
- Safer execution mode used:
  - local pinned public spec file via Studio file-ingest
  - generation/build output written into a temp directory under `/var/folders/.../T/`
  - no secrets or external business API calls involved

## Result Summary

| Step | Result |
|------|--------|
| Studio flow / spec intake | PASS |
| Manifest verification | PASS |
| Engine validation | PASS |
| Engine generation | PASS |
| Maven build | FAIL |
| App startup | NOT RUN |
| Actuator health check | NOT RUN |
| Generated app API smoke | NOT RUN |

## Commands Run

### Pin the public spec locally

```bash
git clone https://github.com/APIs-guru/openapi-directory /tmp/openapi-directory
```

### Full proof script

```bash
python3 scripts/proof_run_configcat_permission_groups.py
```

### Engine validation command executed by the script

```text
/Library/Developer/CommandLineTools/usr/bin/python3 -c import sys
sys.path.insert(0, '<edgeforge-engine-repo>')
from appbuilder.contracts.manifest import load_project_definition
load_project_definition('/var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_configcat_proofrun_t88ayei5/permissions/app-definition.yaml')
print('VALID')
```

### Engine generation command executed by the script

```text
/Library/Developer/CommandLineTools/usr/bin/python3 -m appbuilder.cli generate --manifest /var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_configcat_proofrun_t88ayei5/permissions/app-definition.yaml --output /var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_configcat_proofrun_t88ayei5/generated-configcat-permission-groups
```

### Maven build command executed by the script

```text
mvn clean package -DskipTests --batch-mode
```

## Detailed Results

### 1. Studio Flow / Spec Intake

- Entities classified: `79`
- Operations classified: `63`
- Selected entity: `PermissionGroupModel`
- Selected operations:
  - `create-permission-group`
  - `get-permission-groups`
  - `get-permission-group`
  - `update-permission-group`
- Selected interface:
  - `permissions-permissiongroupmodel-api`
- Completeness summary:
  - `10 READY`
  - `4 WARNING`
  - `0 MANUAL_FOLLOW_UP`
  - `exportable: true`

Result: PASS

### 2. Manifest Verification

- Export output dir:
  - `/var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_configcat_proofrun_t88ayei5/permissions`
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
- Duration: `0.188s`

Result: PASS

### 4. Engine Generation

Output:

```text
Generated application at: /var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_configcat_proofrun_t88ayei5/generated-configcat-permission-groups
Files created: 24
Harness: PASSED
```

- Success: `True`
- Exit code: `0`
- Duration: `0.950s`
- Total files generated: `24`
- Java source files generated: `18`

Result: PASS

### 5. Maven Build

- `JAVA_HOME`: `/opt/homebrew/opt/openjdk@17`
- Return code: `1`
- Build stopped during Java compilation

Representative build output:

```text
[ERROR] .../PermissionGroupModelController.java:[44,76] invalid method declaration; return type required
[ERROR] .../PermissionGroupModelService.java:[82,48] ';' expected
[ERROR] .../PermissionGroupModelService.java:[140,43] ';' expected
[ERROR] .../PermissionGroupModelService.java:[174,42] ';' expected
[ERROR] .../PermissionGroupModelService.java:[208,48] ';' expected
```

Result: FAIL

### 6. App Startup

Not reached because Maven build failed.

Result: NOT RUN

### 7. Actuator Health Check

Not reached because Maven build failed.

Result: NOT RUN

### 8. Generated App API Smoke

Not reached because Maven build failed.

Result: NOT RUN

## Exact Compile Blocker

The generated Java uses the raw hyphenated upstream operation IDs as Java method names. That is not valid Java syntax.

### Controller evidence

File:

- `/var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_configcat_proofrun_t88ayei5/generated-configcat-permission-groups/src/main/java/com/appbuilder/permissions/adapter/inbound/PermissionGroupModelController.java`

Relevant lines:

```java
public ResponseEntity<CreatePermissionGroupResponse> create-permission-group(@Valid @RequestBody CreatePermissionGroupRequest request) {
    CreatePermissionGroupResponse created = permissionGroupModelService.create-permission-group(request);
```

This appears at controller line `44`.

### Service evidence

File:

- `/var/folders/8g/27_vy7ms0bx5wxh5dy3wbw9w0000gn/T/edgeforge_configcat_proofrun_t88ayei5/generated-configcat-permission-groups/src/main/java/com/appbuilder/permissions/service/PermissionGroupModelService.java`

Relevant lines:

```java
public CreatePermissionGroupResponse create-permission-group(CreatePermissionGroupRequest request) {
```

```java
public GetPermissionGroupsResponse get-permission-groups(GetPermissionGroupsRequest request) {
```

```java
public GetPermissionGroupResponse get-permission-group(GetPermissionGroupRequest request) {
```

```java
public UpdatePermissionGroupResponse update-permission-group(UpdatePermissionGroupRequest request) {
```

These appear at service lines:

- `82`
- `140`
- `174`
- `208`

## What This Means

This stronger proof did **not** fail in Studio export or manifest contract alignment.

It failed after successful generation because the current Engine codegen path does not sanitize hyphenated OpenAPI `operationId` values into valid Java method identifiers for generated controllers/services.

The chosen stronger candidate is therefore still valuable:

- it proved the Studio path can export a richer real-world CRUD package cleanly
- it proved the current manifest contract still validates on current Engine `main`
- it exposed a concrete Engine-side codegen gap that the smaller Petstore lane did not trigger

## Warnings Observed

### Expected proof-scope warnings

- Completeness still showed `4 WARNING`s because downstream interfaces, handoffs, and rules were intentionally skipped for this focused CRUD proof

### Environment / execution note

- This run intentionally used a locally pinned copy of the public ConfigCat spec instead of a live fetch
- That made the proof safer and more reproducible without changing the underlying contract being exercised

### No Studio export/manifest drift surfaced

- no manifest validation errors
- no export contract drift
- no Phase 2 passthrough scope confusion

## Ownership

| Observation | Owner | Notes |
|-------------|-------|-------|
| Studio can ingest/export the stronger ConfigCat CRUD scope | Studio / shared contract | Confirmed |
| Manifest v1 contract remains valid on current Engine `main` | Shared contract | Confirmed |
| Engine generates code but emits invalid Java method names from hyphenated operation IDs | Engine | Primary blocker |
| Build never reaches app startup or API smoke | Generated app downstream of Engine codegen | Consequence of the Engine compile blocker |

## Conclusion

This is **not yet a clean stronger CRUD proof on current EdgeForge `main`**, but it is still a successful diagnostic smoke:

- current Studio export remains compatible with current Engine manifest validation/generation
- the stronger real-world ConfigCat contract exposed an Engine compile blocker that Petstore did not cover
- the blocker is specific and actionable: sanitize hyphenated operation IDs before generating Java method names

## Recommended Next Step

The next move should be:

1. Fix the Engine codegen path so Java method names are sanitized from hyphenated OpenAPI operation IDs.
2. Re-run this exact ConfigCat permission-group proof.
3. Only after that, decide whether to broaden to a third real-world CRUD candidate.

## Control Check Decision

No fallback Petstore rerun was added here.

Reason:

- Petstore already passed on the newer post-PR50 baseline in:
  - `docs/test-results/crud-proof-smoke-2026-03-31-post-pr50.md`
- the current failure is precise and candidate-specific enough that a same-turn Petstore control rerun would not materially change ownership
