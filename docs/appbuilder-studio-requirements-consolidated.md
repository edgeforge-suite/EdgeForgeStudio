# EdgeForge Studio — Consolidated & Corrected Requirements

> **Foundational requirements document.** This is the original specification used to build
> Studio MVP (PR #1) and is preserved as the requirements record. The active producer now
> uses the coordinated manifest 2.0 contract; the manifest section below is updated to that
> current boundary. For current implementation status, see [`studio-context.md`](studio-context.md).
> For architecture, see [`studio-architecture.md`](studio-architecture.md). Current suite planning
> lives in the Engine [enterprise readiness roadmap](https://github.com/santosh-sh/EdgeForge/blob/main/docs/enterprise-readiness-roadmap.md)
> and [generated tracker](https://github.com/santosh-sh/EdgeForge/tree/main/docs/tracker).

> This document is the corrected and enhanced version of the original Codex prompt,
> verified against the actual EdgeForge Engine repo at
> `<local EdgeForge Engine checkout>`.
>
> All corrections are marked with **[CORRECTION]** and enhancements with **[ENHANCEMENT]**.

---

## 1. What This App Is

**EdgeForge Studio** is a standalone companion web application.
Its purpose is to collect user input in a structured, user-friendly way and generate
a valid **EdgeForge Engine input package** that EdgeForge Engine can consume directly.

- **Repo location:** `<local EdgeForge Studio checkout>`
- **Does NOT modify AppBuilder.** Studio integrates with AppBuilder as an external local tool.
- **Product name:** `EdgeForge Studio` throughout UI, README, and code.

---

## 2. Source of Truth (EdgeForge Engine Files)

These EdgeForge Engine files define the contract Studio must comply with:

| File | Purpose |
|------|---------|
| `appbuilder/contracts/manifest.py` | Manifest schema + validation logic (Pydantic) |
| `appbuilder/target_profiles/catalog.py` | Valid target profile definitions |
| `appbuilder/rules/models.py` + `ingestion.py` | Rule types + YAML loading |
| `appbuilder/ingestion/openapi_classifier.py` | OpenAPI schema classification logic |
| `appbuilder/mapping/models.py` + `ingestion.py` | Mapping shapes + validation |
| `docs/manifest-schema.md` | Human-readable manifest contract |
| `docs/openapi-intake-and-multi-entity-design-note.md` | OpenAPI + multi-entity design |
| `docs/merged-review-claude-codex-ingestion-multi-entity.md` | Capability coverage |
| `examples/input-projects/xyz-accounts-modernization/` | Single-entity example |
| `examples/input-projects/loans-modernization/` | Single-entity example |
| `examples/input-projects/dda-app/` | Multi-entity example |

---

## 3. Current EdgeForge Engine Capabilities (What Studio Must Align To)

### Supported input types

| Priority | Input | Format | Status |
|----------|-------|--------|--------|
| P1 | OpenAPI 3.x / Swagger 2.0 | JSON/YAML at URL or file | Implemented |
| P1 | Sample JSON request/response | JSON files | Implemented |
| P1 | DDL (CREATE TABLE) | `.sql` files | Implemented |
| P1 | Fixed-width file layouts | YAML spec + sample files | Implemented |
| P1 | Explicit mapping YAML | Per-interface YAML | Implemented |
| P1 | Business rules YAML | Per-entity YAML | Implemented |

### NOT supported by EdgeForge Engine (Studio must NOT guide users toward these)

- WSDL/XSD ingestion (P2 future)
- Kafka/event schema generation
- Inter-service client generation
- Full automatic business-logic recreation
- Ecosystem manifest / cross-app governance
- Production DB provisioning logic
- Postman collection, COBOL copybook, Protobuf, Avro (P3/P4 future)

### Target profiles (from `catalog.py`)

| Profile Name | Java | Spring Boot | Database | Flyway | Batch | XML |
|-------------|------|-------------|----------|--------|-------|-----|
| `springboot-legacy-compatible` | 17 | 3.3.5 | H2 | Yes | Yes | Yes |
| `springboot-enterprise-postgres-java17` | 17 | 3.3.5 | PostgreSQL | Yes | Yes | Yes |
| `springboot-standard-enterprise` | 21 | 3.3.5 | PostgreSQL | Yes | Yes | Yes |

**[ENHANCEMENT]** Studio should import/read these from the actual AppBuilder catalog at runtime
if the AppBuilder repo path is configured. Fall back to hardcoded values if unavailable.

---

## 4. Manifest Schema (Exact Contract)

The generated `app-definition.yaml` must conform exactly to `ProjectDefinition` in `manifest.py` (EdgeForge Engine).

### Top-level fields

```yaml
app_name: string          # required, non-empty
bounded_context: string   # required, non-empty
schema_version: "2.0"     # required in the paired EdgeForge manifest 2.0 contract
app_archetype: crud       # emitted by Studio today; future archetypes reserved
target_profile: string    # required, must match catalog key
upstream_interfaces: []   # optional, list of InterfaceDefinition
downstream_interfaces: [] # optional, list of InterfaceDefinition
data_handoffs: []         # optional, list of DataHandoffDefinition
rules: []                 # list of relative file paths to rule YAML files
legacy_references: []     # list of relative file paths
```

**[CORRECTION]** `rules` is a list of **file paths** (e.g., `- rules/account-business-rules.yaml`),
not inline rule objects. Studio must generate rule YAML files and reference them by path.

**[CURRENT CONTRACT]** EdgeForge manifest 2.0 requires `schema_version: "2.0"`.
Studio emits `app_archetype` explicitly and must be paired with an Engine that
supports manifest 2.0. Saved Studio project snapshots retain their separate 1.4
schema and are migrated through Studio before re-export; exported manifest-1.0
packages are not a Studio import format.

### InterfaceDefinition (upstream or downstream)

```yaml
name: string              # required, non-empty
system: string            # optional
type: string              # required, non-empty
version: string           # optional
spec: string              # relative path — mutually exclusive with spec_url
spec_url: string          # HTTP(S) URL — mutually exclusive with spec
mapping: string           # optional, relative path to mapping YAML
samples: []               # optional, list of relative paths to JSON files
operations: []            # optional, list of InterfaceOperationDefinition
```

**[CORRECTION]** `spec` and `spec_url` are **mutually exclusive and exactly one is required**.
The manifest validator enforces: `if bool(spec) == bool(spec_url): raise ValueError`.
Studio must enforce this in its UI — show either a file upload/path OR a URL field, not both.

### InterfaceOperationDefinition

```yaml
name: string              # required, non-empty
request_sample: string    # optional, relative path
response_sample: string   # optional, relative path
```

**[CORRECTION]** At least one of `request_sample` or `response_sample` **is required** per operation.
The manifest validator enforces this. Studio must require at least one sample per operation.

### DataHandoffDefinition

```yaml
name: string              # required, non-empty
system: string            # optional
type: string              # required, non-empty
version: string           # optional
spec: string              # required, relative path (usually SQL DDL)
mapping: string           # optional, relative path to mapping YAML
```

**[CORRECTION]** The `system` field exists on DataHandoffDefinition (e.g., `system: ETL`).
The Codex prompt's data handoff examples omitted this. Studio forms should include it.

### Path rules

- All paths must be relative (no absolute paths)
- Leading `./` is stripped
- `..` is allowed only when staying inside project root
- Paths are validated to exist on disk during manifest loading

---

## 5. Mapping YAML Shapes (All Three Directions)

**[CORRECTION]** The Codex prompt only showed downstream and data-handoff mapping shapes.
AppBuilder actually has three distinct mapping directions, and Studio must support all three.

### 5a. Upstream mapping (request/response per operation)

```yaml
interface: crm-account-api
entity: Account
operations:
  - name: createAccount
    request_mappings:
      - source: customerId          # field name in API request
        target: Account.customerId  # Entity.field
      - source: accountType
        target: Account.accountType
    response_mappings:
      - source: accountId           # field name in API response
        target: Account.accountId
      - source: status
        target: Account.status
```

Key points:
- Upstream mappings are **operation-scoped** with separate `request_mappings` and `response_mappings`
- Source is the raw API field name; target is `Entity.fieldName`
- One mapping file per upstream interface

### 5b. Downstream mapping (field-level, no operations)

```yaml
interface: eod-handoff-file
entity: Account
field_mappings:
  - source: Account.accountId       # Entity.field
    target: account_id              # downstream field name
  - source: Account.customerId
    target: customer_id
  - source: Account.status
    target: status
```

### 5c. Data handoff mapping (field-level, no operations)

```yaml
table: acct_staging_tbl
entity: Account
field_mappings:
  - source: Account.accountId       # Entity.field
    target: acct_id                 # column name
  - source: Account.customerId
    target: cust_ref
```

---

## 6. Rule YAML Shape

**[CORRECTION]** The supported rule types in AppBuilder are:

| YAML `type` value | RuleType enum | Extra fields |
|-------------------|---------------|--------------|
| `allowed-values` | `ALLOWED_VALUES` | `values: [list]` |
| `default` | `DEFAULT` | `value: string` |
| `iso-4217` | maps to `FORMAT` | (none — stored as `format: "iso-4217"` internally) |

Note: `iso-4217` is a **valid YAML type value** that AppBuilder maps to `RuleType.FORMAT` with
`format="iso-4217"`. It is NOT a separate enum value — it's a convenience alias in the YAML.
The `format` rule type itself is also valid (for custom format strings).

Studio should support all three YAML type values: `allowed-values`, `default`, `iso-4217`.

Rule file shape:
```yaml
entity: Account
rules:
  - field: accountType
    type: allowed-values
    values: [CHQ, SAV, CUR, LON]
  - field: currency
    type: iso-4217
  - field: status
    type: default
    value: PENDING
```

---

## 7. Multi-Entity Pattern

**[ENHANCEMENT]** One OpenAPI contract can serve multiple entity-scoped
interfaces. The public-tree illustration below is independently authored;
the original design's external example remains in private development history.

```yaml
upstream_interfaces:
  - name: workspace-api
    system: SyntheticWorkspace
    type: rest-json
    spec: contracts/workspace.yaml
    mapping: upstream/workspace-mapping.yaml
    operations:
      - name: createWorkspace
        request_sample: upstream/workspace-request.json
        response_sample: upstream/workspace-response.json
  - name: item-api
    system: SyntheticWorkspace
    type: rest-json
    spec: contracts/workspace.yaml
    mapping: upstream/item-mapping.yaml
    operations:
      - name: createItem
        request_sample: upstream/item-request.json
        response_sample: upstream/item-response.json
```

Studio's entity selection screen must support this: after parsing one OpenAPI spec,
the user selects which entities to include, and Studio creates one upstream interface
entry per entity with its own mapping file and operation samples.

---

## 8. Recommended Stack

- Python 3.11+
- FastAPI
- Jinja2 templates
- Vanilla JavaScript
- Minimal CSS
- PyYAML
- No frontend build chain

Rationale: alignment with AppBuilder's Python models/YAML, easy local execution, easy filesystem I/O.

---

## 9. Wizard Steps (Detailed Requirements)

### Step 1: Project Setup

Collect:
- `app_name` (required)
- `bounded_context` (required)
- `target_profile` (required — dropdown populated from AppBuilder catalog if available)
- Output path (optional, default: `./output/<project-slug>/`)
- AppBuilder repo path (optional, default: sibling `../EdgeForge` checkout or `EDGEFORGE_STUDIO_DEFAULT_ENGINE_REPO`)

**[ENHANCEMENT]** If AppBuilder repo path is set and valid, read `target_profiles/catalog.py`
or import `TARGET_PROFILES` dict to populate the dropdown dynamically.

### Step 2: Upstream API Ingestion

Input modes:
- OpenAPI URL (`spec_url`)
- OpenAPI file upload (`spec`)
- Manual request/response JSON samples (no OpenAPI)

**[CORRECTION]** These are mutually exclusive per interface — enforce exactly one of `spec` or `spec_url`.

For OpenAPI URL/file:
- Parse the spec (JSON or YAML, OpenAPI 3.x or Swagger 2.0)
- Classify schemas into: domain entity candidates, DTOs, infrastructure schemas
- Show operations grouped by resource/domain
- Skip infrastructure wrappers: `Page*`, `Pageable*`, `Sort*`, `Error*`, `Validation*`,
  `*Response` wrappers when clearly infrastructure
- Classification logic should match `openapi_classifier.py` behavior

### Step 3: Entity + Operation Selection

This is the core Studio screen.

Show:
- Candidate entities (from OpenAPI classification or manual samples)
- Operations found (from OpenAPI paths or manually defined)
- Which operations reference which entities
- Warnings for unsupported or suspicious patterns

User actions:
- Include/exclude entities
- Include/exclude operations
- Define bounded context scope
- Assign operations to entities when inference is ambiguous
- **[ENHANCEMENT]** When multiple entities come from the same OpenAPI spec, Studio should
  create separate upstream interface entries per entity (matching the DDA pattern)

All inferred associations must be marked as **draft** until user confirms.

### Step 4: Downstream Interfaces

Support creation of downstream interface entries.

Input:
- Fixed-width file layout via structured form OR YAML text area
- Optional sample output file (text upload or paste)
- Mapping entry builder:
  - source: `Entity.field`
  - target: downstream field name

Generated files:
- `downstream/<name>-layout.yaml` or `contracts/<name>-layout.yaml`
- `downstream/<name>-mapping.yaml` or `contracts/<name>-mapping.yaml`

**[CORRECTION]** The downstream mapping shape uses `interface` + `entity` + `field_mappings`
(not `table`). See section 5b above.

### Step 5: Data Handoffs

Input options:
- Paste SQL DDL
- Upload SQL file
- Build mapping entries via form:
  - source: `Entity.field`
  - target: table column name
- **[CORRECTION]** Include `system` field (e.g., "ETL") and `type` field (e.g., "staging-table")

Generated files:
- `data-handoffs/<name>.sql` or `contracts/<name>.sql`
- `data-handoffs/<name>-mapping.yaml` or `contracts/<name>-mapping.yaml`

**[CORRECTION]** The data handoff mapping shape uses `table` + `entity` + `field_mappings`.
If the DDL contains a physical table name, preserve it — do not derive/rename.

### Step 6: Rules + Legacy Notes

Rule input via structured form.

Supported rule types:
- `allowed-values` — requires `values` list
- `default` — requires `value` string
- `iso-4217` — no extra fields (applied to currency fields)

**[CORRECTION]** The `format` type is also valid in the RuleType enum but no example
uses it directly in YAML. For MVP, support the three types above which cover all examples.

Generated files:
- `rules/<entity>-business-rules.yaml` (one per entity)
- Referenced in manifest as file paths: `rules: [rules/<entity>-business-rules.yaml]`

Legacy notes:
- Markdown note text (paste or type)
- Output as `legacy/<slug>-notes.md`
- Referenced in manifest: `legacy_references: [legacy/<slug>-notes.md]`

### Step 7: Review + Completeness Report

Show before export:
- Full manifest preview (YAML)
- File tree preview
- Selected entities and operations
- Upstream mappings (per operation, request + response)
- Downstream interfaces and mappings
- Data handoffs and mappings
- Rules
- Gaps / warnings

Completeness categories:
- **READY** — all required fields satisfied
- **WARNING** — recommended-but-missing items
- **MANUAL FOLLOW-UP REQUIRED** — items needing user action

Warning examples:
- No downstream interface defined
- No staging handoff defined
- Nested object fields detected and skipped
- Arrays of complex objects detected
- Unsupported OpenAPI schema constructs (e.g., `oneOf`, `anyOf`)
- Operations present without any samples
- Mappings not yet supplied for downstream or handoff
- `spec` and `spec_url` both missing or both present
- Operations with no request_sample AND no response_sample
- **[ENHANCEMENT]** Entity referenced in mappings but not in any upstream interface
- **[ENHANCEMENT]** Upstream interface with no operations defined

### Step 8: Export Package

Generate a valid AppBuilder input package on disk.

Package structure (either style is valid):

**Style A (flat contracts/):**
```
<output-root>/<project-slug>/
  app-definition.yaml
  contracts/
  samples/
  rules/
  legacy/
  assessment-report.json
  completeness-report.md
```

**Style B (categorized folders):**
```
<output-root>/<project-slug>/
  app-definition.yaml
  upstream/
  downstream/
  data-handoffs/
  samples/
  rules/
  legacy/
  assessment-report.json
  completeness-report.md
```

**[CORRECTION]** Whichever structure is used, all relative paths in the manifest
must match the actual file locations. The manifest validator resolves paths relative
to the manifest file's parent directory and checks that referenced files exist.

Additional export options:
- Download as ZIP
- Copy to a specified output path

---

## 10. EdgeForge Engine Integration

Settings field: local EdgeForge Engine repo path.

When configured, Studio can:

1. **Validate manifest** — Import `ProjectDefinition` from `appbuilder.contracts.manifest`
   and call `load_project_definition()` against the generated `app-definition.yaml`.

2. **Run `appbuilder assess`** — For OpenAPI-backed upstreams, run:
   ```
   python -m appbuilder assess --swagger <spec_url> [--output assessment-report.json]
   ```

3. **Run `appbuilder generate`** — Optional button (clearly labeled as advanced/optional):
   ```
   python -m appbuilder generate --manifest <path>/app-definition.yaml --output <output-dir>
   ```

**[CORRECTION]** Integration should use **subprocess calls** to the EdgeForge Engine CLI,
not direct Python imports. This keeps Studio decoupled and avoids dependency conflicts.
The CLI commands are:
- `python -m appbuilder assess --swagger <url> [--output <file>]`
- `python -m appbuilder generate --manifest <path> --output <dir> [--generation-run-id <id>]`

**[ENHANCEMENT]** For manifest validation specifically, Studio can optionally add EdgeForge Engine
to its Python path and import `load_project_definition` for faster validation without subprocess.
But generation and assessment should always use subprocess.

---

## 11. Architecture

```
app/
  main.py                    # FastAPI app + startup
  routes/
    project.py               # Step 1: project setup
    upstream.py               # Step 2: upstream API ingestion
    entities.py               # Step 3: entity + operation selection
    downstream.py             # Step 4: downstream interfaces
    handoffs.py               # Step 5: data handoffs
    rules.py                  # Step 6: rules + legacy notes
    review.py                 # Step 7: review + completeness
    export.py                 # Step 8: export package
  services/
    openapi_service.py        # OpenAPI fetch + parse
    classifier_service.py     # Schema classification (entity/DTO/infra)
    manifest_generator.py     # Build app-definition.yaml
    package_writer.py         # Write full package to disk
    completeness_service.py   # Generate completeness report
    mapping_generator.py      # [ENHANCEMENT] Generate all 3 mapping directions
    rule_generator.py         # [ENHANCEMENT] Generate rule YAML files
  models/
    project.py                # In-memory project state
    upstream.py               # Upstream interface models
    downstream.py             # Downstream interface models
    handoff.py                # Data handoff models
    rules.py                  # Rule models
  templates/                  # Jinja2 HTML templates
  static/                     # CSS + JS
  generators/                 # File generation helpers
  validators/                 # Input validation
  integrations/
    appbuilder_integration.py # Subprocess calls to AppBuilder CLI
tests/
```

**[ENHANCEMENT]** Added `mapping_generator.py` and `rule_generator.py` as explicit services
since mapping generation (all 3 directions) and rule file generation are distinct concerns.

---

## 12. Deterministic Behavior Rules

- Never silently invent mappings
- Never silently invent rules
- Never silently invent entity ownership if ambiguous
- Suggestions are OK but must be visually marked as **inferred/draft**
- Safe default: warn and ask for confirmation, not guess
- **[ENHANCEMENT]** Any auto-classified entity or operation should show its classification
  confidence/reason (e.g., "classified as entity because it's a response schema for a CRUD path")

---

## 13. MVP Usability

- Fast local startup
- Clear forms with sensible defaults
- Readable preview panels (YAML preview, file tree preview)
- Export button + download ZIP button
- No auth, no database, no heavy frontend
- Draft state: in-memory (with optional file-backed persistence for session recovery)
- **[ENHANCEMENT]** Consider auto-save to a temp JSON file so users don't lose work on page refresh

---

## 14. Tests

Required test coverage:

1. OpenAPI classification into entity/DTO/infrastructure
2. Manifest generation shape matches `ProjectDefinition` schema
3. **[CORRECTION]** Upstream mapping file generation (request_mappings + response_mappings shape)
4. Downstream mapping file generation (field_mappings shape)
5. Data handoff mapping file generation (table + field_mappings shape)
6. Rules file generation (all 3 types: allowed-values, default, iso-4217)
7. Completeness report generation
8. Package export creates expected file tree with correct relative paths
9. **[CORRECTION]** Manifest path validation — all referenced files exist in package
10. **[CORRECTION]** Mutual exclusivity of spec/spec_url enforced
11. **[CORRECTION]** Operation sample requirement enforced (at least one of request/response)
12. One end-to-end flow that creates a valid sample package and validates it against AppBuilder's
    `load_project_definition()` if AppBuilder is available on the path

---

## 15. Scope Discipline (Do NOT Build)

- User authentication
- Multi-user collaboration
- Database-backed project storage
- AI chat assistant inside Studio
- Code generation itself (that's AppBuilder's job)
- WSDL/XSD ingestion
- AppBuilder engine changes
- Kafka/event schemas
- Any feature AppBuilder doesn't support as input

---

## 16. Acceptance Criteria

The app is complete when:

1. Start Studio locally with `python -m app.main` or `uvicorn app.main:app`
2. Point it at an OpenAPI URL or upload a spec file
3. It shows candidate entities and operations, classified into entity/DTO/infrastructure
4. Select a bounded context scope (e.g., Customer + Account only from a larger spec)
5. Add downstream file definitions with layout + mapping
6. Add staging-table DDL with mapping
7. Add business rules (allowed-values, default, iso-4217)
8. It generates a valid AppBuilder input package with:
   - `app-definition.yaml` with correct relative paths
   - Upstream mapping files (with request_mappings + response_mappings per operation)
   - Downstream layout + mapping files
   - Data handoff SQL + mapping files
   - Rule YAML files
   - Legacy notes (if provided)
   - `completeness-report.md`
   - `assessment-report.json`
9. The generated manifest passes `load_project_definition()` validation
10. All referenced file paths in the manifest exist in the package
11. It does NOT silently fabricate rules, mappings, or entity associations
12. Tests pass

---

## 17. Summary of All Corrections vs Original Codex Prompt

| # | Issue | Correction |
|---|-------|------------|
| 1 | Upstream mapping YAML shape missing | Added section 5a with operation-scoped request_mappings + response_mappings |
| 2 | spec/spec_url mutual exclusivity not emphasized | Marked as enforced by manifest validator, Studio must enforce in UI |
| 3 | `rules` shown as inline in manifest | Corrected: `rules` is a list of file paths, not inline objects |
| 4 | Operation sample requirement missing | Added: at least one of request_sample/response_sample required per operation |
| 5 | Multi-entity from same spec pattern implicit | Made explicit with DDA example showing same spec, different interface entries |
| 6 | `iso-4217` rule type unclear | Clarified: valid YAML type that maps to FORMAT enum internally |
| 7 | AppBuilder integration method unspecified | Specified: subprocess for assess/generate, optional import for validation |
| 8 | `system` field missing from data handoff examples | Added to data handoff form requirements |
| 9 | Downstream vs handoff mapping shapes conflated | Separated: downstream uses `interface`, handoff uses `table` |
| 10 | Test list incomplete | Added tests for upstream mappings, path validation, mutual exclusivity, sample requirements |
