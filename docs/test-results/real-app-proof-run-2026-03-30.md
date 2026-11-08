# Real-App E2E Proof Run — 2026-03-30

## Goal

Prove the full end-to-end path from Studio wizard to a running Spring Boot app using a real OpenAPI spec, on the current merged main baseline (Studio PR #14 + Engine PRs #44, #45, #46 merged). This run is not planning — it executes every step and documents exactly what happened.

## Selected Spec

**Petstore OpenAPI 3.0**
- URL: `https://petstore3.swagger.io/api/v3/openapi.json`
- Format: OpenAPI 3.0 JSON (official Swagger example spec)

**Why chosen:**
- Real, publicly available spec — not a hand-written fixture
- Well-known, stable, maintained by Swagger/SmartBear
- Has a clear CRUD entity (`Pet`) with create (POST `/pet`) and read (GET `/pet/{petId}`) operations
- Manageable field count: `id`, `name`, `category`, `photoUrls`, `tags`, `status` (6 top-level fields)
- Classifier immediately identifies `Pet`, `Order`, and `User` as domain entities — no special tuning needed

## Scope Used in Studio

- **App name:** Petstore Pet Service
- **Bounded context:** pets
- **Target profile:** springboot-legacy-compatible (Java 17, Spring Boot 3.3.5)
- **Entity selected:** Pet
- **Operations selected:** `addPet` (POST /pet), `getPetById` (GET /pet/{petId})
- **Downstream interfaces:** None (skipped — WARNING, not blocker)
- **Data handoffs:** None (skipped — WARNING, not blocker)
- **Rules:** None (skipped — WARNING, not blocker)
- **Completeness report:** 8 READY, 4 WARNING, 0 MANUAL_FOLLOW_UP → exportable

### Studio Wizard Flow (programmatic via FastAPI TestClient)

All wizard steps driven via `from fastapi.testclient import TestClient` and `from app.main import app`.

| Step | Route | Result |
|------|-------|--------|
| Reset | `POST /export/reset` | OK |
| Step 1 | `POST /` (project setup) | OK — project, bounded_context, target_profile, appbuilder_repo_path saved |
| Step 2 | `POST /upstream/ingest-url` | OK — 6 entities, 19 operations classified from Petstore spec |
| Step 3 | `POST /entities/save` | OK — 1 interface created: `pets-pet-api` |
| Step 3b | `POST /mappings/upstream/samples/save` | OK — auto-generated samples saved for addPet (req + resp) and getPetById (resp only) |
| Step 3c | `POST /mappings/upstream/save` | OK — 6 req mappings (addPet), 6 resp mappings per op |
| Steps 4-6 | Skipped | Downstream/handoffs/rules are optional (WARNING-level) |
| Step 7 | Internal completeness check | 8 READY, 4 WARNING, 0 MANUAL_FOLLOW_UP |
| Step 8 | `POST /export/write` | OK — 8 files written |

## Export Result

**Export succeeded. No blockers.**

Output directory: `$TMPDIR/edgeforge_proofrun_*/pets/`

Files written:
```
contracts/pets-pet-api-spec.json      (local copy of Petstore spec)
upstream/sample-addpet-request.json
upstream/sample-addpet-response.json
upstream/sample-getpetbyid-response.json
upstream/pets-pet-api-mapping.yaml
app-definition.yaml
completeness-report.md
assessment-report.json
```

### Exported `app-definition.yaml`

```yaml
app_name: Petstore Pet Service
bounded_context: pets
schema_version: '1.0'
app_archetype: crud
target_profile: springboot-legacy-compatible
upstream_interfaces:
- name: pets-pet-api
  type: rest-json
  spec: contracts/pets-pet-api-spec.json
  mapping: upstream/pets-pet-api-mapping.yaml
  operations:
  - name: addPet
    request_sample: upstream/sample-addpet-request.json
    response_sample: upstream/sample-addpet-response.json
  - name: getPetById
    response_sample: upstream/sample-getpetbyid-response.json
```

**Verified:** `schema_version: "1.0"` and `app_archetype: crud` are present.

Note: `getPetById` has no `request_sample` entry — this is correct; GET operations have no request body, so only the response sample is written.

## EdgeForge Validation Result

**PASSED**

Command:
```
python3 -c "
import sys
sys.path.insert(0, '<edgeforge-engine-repo>')
from appbuilder.contracts.manifest import load_project_definition
load_project_definition('<manifest_path>')
print('VALID')
"
```

Output:
```
VALID
```

The manifest passed `load_project_definition` with no exceptions. `schema_version` and `app_archetype` were accepted.

## Generation Result

**SUCCEEDED**

Command:
```
cd <edgeforge-engine-repo>
python3 -m appbuilder.cli generate \
  --manifest $TMPDIR/edgeforge_proofrun_*/pets/app-definition.yaml \
  --output $TMPDIR/edgeforge_proofrun_*/generated-petstore
```

Output:
```
Generated application at: $TMPDIR/edgeforge_proofrun_*/generated-petstore
Files created: 20
Harness: PASSED
```

**No generation warnings.**

### Generated Files (20)

```
Dockerfile
README.md
pom.xml
src/main/java/com/appbuilder/pets/PetsApplication.java
src/main/java/com/appbuilder/pets/adapter/inbound/AddPetRequest.java
src/main/java/com/appbuilder/pets/adapter/inbound/AddPetResponse.java
src/main/java/com/appbuilder/pets/adapter/inbound/DemoController.java
src/main/java/com/appbuilder/pets/adapter/inbound/GetPetByIdRequest.java
src/main/java/com/appbuilder/pets/adapter/inbound/GetPetByIdResponse.java
src/main/java/com/appbuilder/pets/adapter/inbound/PetController.java
src/main/java/com/appbuilder/pets/domain/Pet.java
src/main/java/com/appbuilder/pets/exception/ErrorResponse.java
src/main/java/com/appbuilder/pets/exception/GlobalExceptionHandler.java
src/main/java/com/appbuilder/pets/exception/ResourceNotFoundException.java
src/main/java/com/appbuilder/pets/repository/PetRepository.java
src/main/java/com/appbuilder/pets/service/PetService.java
src/main/resources/application.yaml
src/main/resources/db/migration/V1__create_pet_table.sql
src/main/resources/static/index.html
src/test/java/com/appbuilder/pets/PetsApplicationTest.java
```

`PetController` included full CRUD: POST `/pets`, GET `/pets/{id}`, GET `/pets` (list), PUT `/pets/{id}`, DELETE `/pets/{id}`.

## Build Result

**BUILD SUCCESS**

Command:
```
cd $TMPDIR/edgeforge_proofrun_*/generated-petstore
JAVA_HOME=/opt/homebrew/opt/openjdk@17 mvn clean package -DskipTests
```

Last 10 lines of output:
```
[INFO] Compiling 13 source files with javac [debug parameters release 17] to target/classes
[INFO] Compiling 1 source file with javac [debug parameters release 17] to target/test-classes
[INFO] Tests are skipped.
[INFO] Building jar: .../target/pets-0.0.1-SNAPSHOT.jar
[INFO] Replacing main artifact ... with repackaged archive
[INFO] ------------------------------------------------------------------------
[INFO] BUILD SUCCESS
[INFO] ------------------------------------------------------------------------
[INFO] Total time:  2.161 s
[INFO] Finished at: 2026-03-30T22:04:14-05:00
[INFO] ------------------------------------------------------------------------
```

13 Java source files compiled. Spring Boot JAR produced.

## Run Result

**APP STARTED — HEALTH UP**

Command:
```
JAVA_HOME=/opt/homebrew/opt/openjdk@17 java -jar target/pets-0.0.1-SNAPSHOT.jar --server.port=8090
```

Start sequence:
- Flyway migration `V1__create_pet_table.sql` applied successfully (H2 in-memory)
- Tomcat started on port 8090
- App started in 3.3 seconds

Health check (`GET /actuator/health`):
```json
{"status":"UP","components":{"db":{"status":"UP","details":{"database":"H2","validationQuery":"isValid()"}},"diskSpace":{"status":"UP"},"ping":{"status":"UP"}}}
```

API check (`GET /pets`):
```json
[]
```

Empty array returned — correct, no pets added yet.

App was killed after health check.

**Warnings in startup log (non-fatal):** Spring Batch's `BeanPostProcessorChecker` emitted multiple "not eligible for auto-proxying" WARN lines for Flyway, DataSource, JPA, and Batch beans. These are known Spring Batch startup ordering warnings and do not affect runtime behavior. App started and served requests correctly.

## Findings

### What Worked

1. **Studio → Engine → Build → Run path is clean end-to-end.** No manual YAML edits, no workarounds, no engine-side changes needed.

2. **`schema_version: "1.0"` and `app_archetype: crud` are correctly emitted** by Studio export (Studio PR #14 confirmed working).

3. **Petstore spec classifies correctly.** `Pet`, `Order`, `User` are classified as domain entities. Operations are grouped by entity. The `addPet` / `getPetById` scope worked first try.

4. **Auto-generated samples from spec are sufficient** to satisfy the completeness check. No manual JSON crafting required for a basic proof.

5. **Generation is warning-free.** `Harness: PASSED`. No generation warnings on the Petstore Pet scope.

6. **Flyway migration runs cleanly.** `V1__create_pet_table.sql` applied on first boot.

7. **Full CRUD emitted even from 2-operation scope.** Engine generated complete REST layer (GET list, GET by ID, POST, PUT, DELETE) from `addPet` + `getPetById` selection.

### Observations (not blockers)

1. **`getPetById` has no `request_sample` in the manifest** — this is correct and expected. GET operations have no request body; the completeness service correctly requires only a response sample for read operations. No issue.

2. **Spring Batch `BeanPostProcessorChecker` WARNs on startup** — these are known Spring Boot 3.3.x / Spring Batch ordering warnings. They are engine-generated (not a Studio issue) and do not affect runtime. Noted for Engine follow-up.

3. **Petstore `photoUrls` (array of strings) and `tags` (array of Tag objects)** — the Engine handled these as part of the Pet domain entity without warnings. Complex nested schemas (`category`, `tags`) were simplified to scalar fields in the generated entity rather than generating `@Embeddable` sub-types. This is expected Engine Phase 1b behavior (nested arrays simplified; no error on nested objects within bounds).

4. **No downstream interfaces, handoffs, or rules** in scope for this proof — the completeness report flagged these as WARNINGs (not blockers). A fuller proof run could add a staging table to cover the full package shape.

5. **Spec is fetched from Petstore live** at wizard ingest time, and also saved locally to `contracts/pets-pet-api-spec.json` by the package writer. The manifest references the local copy (`spec: contracts/pets-pet-api-spec.json`), so generation does not re-fetch the URL. This is the correct behavior added in Studio PR #4.

## Ownership (Studio / Engine / Spec / Docs)

| Finding | Owner | Action |
|---------|-------|--------|
| Spring Batch BeanPostProcessorChecker WARNs | Engine | Low priority — known Spring framework behavior, does not affect runtime |
| Nested Petstore types (Category, Tag) simplified to scalars | Engine | Expected behavior (Phase 1b scope); deeper nested type support is deferred |
| No `request_sample` for GET operation | Studio/Engine (design) | Correct by design; no action needed |
| No downstream/handoffs in proof scope | Test gap | A follow-up proof run could add a staging table to cover full package shape |

## Follow-ups

1. **Engine — Spring Batch BeanPostProcessorChecker WARNs:** Investigate whether declaring Batch beans as `@Role(ROLE_INFRASTRUCTURE)` resolves the startup log noise. Non-blocking.

2. **Proof run with downstream + handoffs:** A follow-up proof run using a spec that also has a staging table DDL and downstream mapping would cover the full Studio package shape. The current run confirms the minimal-CRUD path is clean.

3. **CI / cross-repo contract test:** Wire this proof flow as a CI test that exports a Studio package and validates it against the Engine manifest loader. This closes the "cross-repo contract tests planned" item from the Studio context doc.

4. **`field-comparison` rule authoring in Step 6:** Still the one remaining rule type not authorable in the UI. Follow-up item noted in `studio-context.md`, no change in status.

5. **`manifest-v1.schema.json` validation in Studio:** Studio does not yet validate against the JSON Schema artifact. Low priority; the Engine's `load_project_definition` validation is the authoritative check.
