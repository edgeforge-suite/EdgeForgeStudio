"""
Composite CRUD + package-shape E2E proof run — EdgeForge Studio -> Engine.

Selected spec: Codat Accounting API 2.1.0
Spec URL: https://api.apis.guru/v2/specs/codat.io/accounting/2.1.0/openapi.yaml
Entity scope: Customer

This proof intentionally combines:
  1. richer upstream path/query parameter behavior via Customer CRUD-adjacent ops
  2. downstream fixed-width + staging-table handoff package shape

Run this from the EdgeForgeStudio repo root:
    git clone https://github.com/APIs-guru/openapi-directory /tmp/openapi-directory
    python3 scripts/proof_run_codat_customer_downstream_handoff.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from app.main import app
from app.services.completeness_service import build_completeness_report
from app.services.manifest_contract import STUDIO_MANIFEST_SCHEMA_VERSION
from app.services.runtime_defaults import default_edgeforge_repo_path
from app.services.session_store import get_session
from scripts.proof_runner_helpers import (
    assert_expected_files,
    assert_expected_generated_filenames,
    assert_json_array,
    discover_collection_path,
    find_java17_home,
    generate_app_or_exit,
    json_request,
    print_manifest_summary,
    print_report,
    resolve_generated_jar,
    run_maven_build_or_exit,
    start_generated_app_or_exit,
    validate_manifest_or_exit,
)

CODAT_URL = "https://api.apis.guru/v2/specs/codat.io/accounting/2.1.0/openapi.yaml"
CODAT_SPEC_PATH = Path("/tmp/openapi-directory/APIs/codat.io/accounting/2.1.0/openapi.yaml")
ENGINE_REPO = default_edgeforge_repo_path()

ENTITY_NAME = "Customer"
APP_NAME = "Codat Customer Operations Service"
BOUNDED_CONTEXT = "customerops"
TARGET_PROFILE = "springboot-legacy-compatible"
SELECTED_OPS = [
    "create-customer",
    "get-customers",
    "get-customer",
    "update-customer",
]

CUSTOMER_REQUEST_SAMPLE = json.dumps(
    {
        "customerName": "Acme Holdings",
        "emailAddress": "ops@acme.example",
        "phone": "+1-312-555-0100",
        "defaultCurrency": "USD",
        "status": "Active",
        "registrationNumber": "REG-1001",
        "taxNumber": "TAX-1001",
    },
    indent=2,
)

CUSTOMER_RESPONSE_SAMPLE = json.dumps(
    {
        "id": "cust-1001",
        "customerName": "Acme Holdings",
        "emailAddress": "ops@acme.example",
        "phone": "+1-312-555-0100",
        "defaultCurrency": "USD",
        "status": "Active",
        "registrationNumber": "REG-1001",
        "taxNumber": "TAX-1001",
    },
    indent=2,
)

CREATE_CUSTOMER_RESPONSE_SAMPLE = json.dumps(
    {
        "data": json.loads(CUSTOMER_RESPONSE_SAMPLE),
        "changes": [],
        "companyId": "company-001",
        "dataConnectionKey": "conn-001",
        "dataType": "customer",
        "pushOperationKey": "push-001",
        "status": "Success",
        "statusCode": 200,
        "timeoutInMinutes": 2,
        "timeoutInSeconds": 120,
    },
    indent=2,
)

LIST_CUSTOMERS_RESPONSE_SAMPLE = json.dumps(
    {
        "results": [json.loads(CUSTOMER_RESPONSE_SAMPLE)],
        "pageNumber": 1,
        "pageSize": 20,
        "totalResults": 1,
        "_links": {},
    },
    indent=2,
)

DOWNSTREAM_SAMPLE_LINE = "cust-1001       Acme Holdings                 Active          ops@acme.example                      "


print("\n=== COMPOSITE CRUD + PACKAGE-SHAPE PROOF RUN — EdgeForge Studio -> Engine — 2026-03-31 ===\n")

client = TestClient(app, raise_server_exceptions=True)

print("[Step 0] Resetting Studio session...")
r = client.post("/export/reset")
assert r.status_code == 200, f"Reset failed: {r.text}"
print("         OK — session reset")

print("\n[Step 1] Posting project setup...")
TMP_ROOT = Path(tempfile.mkdtemp(prefix="edgeforge_codat_customer_proofrun_"))
print(f"         Output root: {TMP_ROOT}")
r = client.post(
    "/",
    data={
        "app_name": APP_NAME,
        "bounded_context": BOUNDED_CONTEXT,
        "target_profile": TARGET_PROFILE,
        "output_path": str(TMP_ROOT),
        "appbuilder_repo_path": ENGINE_REPO,
    },
    follow_redirects=False,
)
assert r.status_code in (200, 302, 303), f"Step 1 POST failed: {r.status_code} {r.text[:200]}"
print("         OK — project setup saved")

print(f"\n[Step 2] Ingesting pinned Codat spec from {CODAT_SPEC_PATH}...")
assert CODAT_SPEC_PATH.exists(), (
    f"Codat spec file not found: {CODAT_SPEC_PATH}. "
    "Clone https://github.com/APIs-guru/openapi-directory to /tmp/openapi-directory first."
)
r = client.post(
    "/upstream/ingest-file",
    files={
        "spec_file": (
            CODAT_SPEC_PATH.name,
            CODAT_SPEC_PATH.read_bytes(),
            "application/yaml",
        )
    },
)
assert r.status_code == 200, f"Ingest file failed: {r.status_code} {r.text[:200]}"
body = r.json()
assert body.get("ok"), f"Ingest returned ok=false: {body}"
entities = body["entities"]
operations = body["operations"]
entity_names = [entry["name"] for entry in entities]
op_names = [entry["name"] for entry in operations]
print(f"         Classified {len(entities)} entities")
print(f"         Classified {len(operations)} operations")
assert ENTITY_NAME in entity_names, f"{ENTITY_NAME} not found in: {entity_names[:25]}"
customer_ops = [entry["name"] for entry in operations if ENTITY_NAME in entry.get("entity_candidates", [])]
print(f"         {ENTITY_NAME} entity-linked operations: {customer_ops}")

print(f"\n[Step 3] Selecting {ENTITY_NAME} with richer path/query behavior...")
selected_ops = [name for name in SELECTED_OPS if name in op_names]
assert selected_ops == SELECTED_OPS, f"Missing selected ops: expected {SELECTED_OPS}, got {selected_ops}"
r = client.post(
    "/entities/save",
    json={
        "entities": [ENTITY_NAME],
        "operations": selected_ops,
        "entity_op_map": {ENTITY_NAME: selected_ops},
    },
)
assert r.status_code == 200, f"entities/save failed: {r.status_code} {r.text[:200]}"
body = r.json()
assert body.get("ok"), f"entities/save ok=false: {body}"
print(f"         Selected operations: {selected_ops}")
print(f"         OK — {body['interface_count']} interface(s) created")
interfaces = body.get("interfaces", [])
print(f"         Interfaces: {[entry['name'] for entry in interfaces]}")

session = get_session()
iface_name = session.upstream_interfaces[0].name if session.upstream_interfaces else "customerops-customer-api"
print(f"         Interface name: {iface_name}")

print("\n[Step 3b] Saving curated operation samples...")
ops_payload = [
    {
        "name": "create-customer",
        "request_sample_content": CUSTOMER_REQUEST_SAMPLE,
        "response_sample_content": CREATE_CUSTOMER_RESPONSE_SAMPLE,
    },
    {
        "name": "get-customers",
        "request_sample_content": None,
        "response_sample_content": LIST_CUSTOMERS_RESPONSE_SAMPLE,
    },
    {
        "name": "get-customer",
        "request_sample_content": None,
        "response_sample_content": CUSTOMER_RESPONSE_SAMPLE,
    },
    {
        "name": "update-customer",
        "request_sample_content": CUSTOMER_REQUEST_SAMPLE,
        "response_sample_content": CREATE_CUSTOMER_RESPONSE_SAMPLE,
    },
]
r = client.post(
    "/mappings/upstream/samples/save",
    json={
        "interface_name": iface_name,
        "operations": ops_payload,
    },
)
assert r.status_code == 200, f"samples/save failed: {r.status_code} {r.text[:200]}"
assert r.json().get("ok"), "samples/save ok=false"
for op in ops_payload:
    print(
        f"           {op['name']}: req={'yes' if op['request_sample_content'] else 'no'}, "
        f"resp={'yes' if op['response_sample_content'] else 'no'}"
    )
print("         OK — samples saved")

print("\n[Step 3c] Saving upstream field mappings...")
operation_mappings = [
    {
        "name": "create-customer",
        "request_mappings": [
            {"source": "customerName", "target": "Customer.customerName"},
            {"source": "emailAddress", "target": "Customer.emailAddress"},
            {"source": "phone", "target": "Customer.phone"},
            {"source": "defaultCurrency", "target": "Customer.defaultCurrency"},
            {"source": "status", "target": "Customer.status"},
            {"source": "registrationNumber", "target": "Customer.registrationNumber"},
            {"source": "taxNumber", "target": "Customer.taxNumber"},
        ],
        "response_mappings": [
            {"source": "data.id", "target": "Customer.id"},
            {"source": "data.customerName", "target": "Customer.customerName"},
            {"source": "data.emailAddress", "target": "Customer.emailAddress"},
            {"source": "data.phone", "target": "Customer.phone"},
            {"source": "data.defaultCurrency", "target": "Customer.defaultCurrency"},
            {"source": "data.status", "target": "Customer.status"},
        ],
    },
    {
        "name": "get-customers",
        "request_mappings": [],
        "response_mappings": [],
    },
    {
        "name": "get-customer",
        "request_mappings": [],
        "response_mappings": [
            {"source": "id", "target": "Customer.id"},
            {"source": "customerName", "target": "Customer.customerName"},
            {"source": "emailAddress", "target": "Customer.emailAddress"},
            {"source": "phone", "target": "Customer.phone"},
            {"source": "defaultCurrency", "target": "Customer.defaultCurrency"},
            {"source": "status", "target": "Customer.status"},
        ],
    },
    {
        "name": "update-customer",
        "request_mappings": [
            {"source": "customerName", "target": "Customer.customerName"},
            {"source": "emailAddress", "target": "Customer.emailAddress"},
            {"source": "phone", "target": "Customer.phone"},
            {"source": "defaultCurrency", "target": "Customer.defaultCurrency"},
            {"source": "status", "target": "Customer.status"},
            {"source": "registrationNumber", "target": "Customer.registrationNumber"},
            {"source": "taxNumber", "target": "Customer.taxNumber"},
        ],
        "response_mappings": [
            {"source": "data.id", "target": "Customer.id"},
            {"source": "data.customerName", "target": "Customer.customerName"},
            {"source": "data.emailAddress", "target": "Customer.emailAddress"},
            {"source": "data.phone", "target": "Customer.phone"},
            {"source": "data.defaultCurrency", "target": "Customer.defaultCurrency"},
            {"source": "data.status", "target": "Customer.status"},
        ],
    },
]
r = client.post(
    "/mappings/upstream/save",
    json={
        "interface_name": iface_name,
        "operation_mappings": operation_mappings,
    },
)
assert r.status_code == 200, f"mappings/save failed: {r.status_code} {r.text[:200]}"
assert r.json().get("ok"), "mappings/save ok=false"
for op in operation_mappings:
    print(
        f"           {op['name']}: "
        f"{len(op['request_mappings'])} req mappings, {len(op['response_mappings'])} resp mappings"
    )
print("         OK — upstream mappings saved")

print("\n[Step 4] Saving downstream fixed-width interface...")
r = client.post(
    "/downstream/save",
    json={
        "interfaces": [
            {
                "name": "customer-eod-handoff-file",
                "system": "DOWNSTREAM",
                "type": "file-fixed-width",
                "version": "v1",
                "entity_name": ENTITY_NAME,
                "layout_fields": [
                    {"name": "customer_id", "start": 1, "length": 16},
                    {"name": "customer_name", "start": 17, "length": 30},
                    {"name": "status_cd", "start": 47, "length": 16},
                    {"name": "email_address", "start": 63, "length": 40},
                ],
                "field_mappings": [
                    {"source": "Customer.id", "target": "customer_id"},
                    {"source": "Customer.customerName", "target": "customer_name"},
                    {"source": "Customer.status", "target": "status_cd"},
                    {"source": "Customer.emailAddress", "target": "email_address"},
                ],
                "sample_content": DOWNSTREAM_SAMPLE_LINE,
            }
        ]
    },
)
assert r.status_code == 200, f"downstream/save failed: {r.status_code} {r.text[:200]}"
assert r.json().get("ok"), "downstream/save ok=false"
print(f"         OK — {r.json()['count']} downstream interface(s) saved")

print("\n[Step 5] Saving staging-table handoff...")
r = client.post(
    "/handoffs/save",
    json={
        "handoffs": [
            {
                "name": "customer-staging-table",
                "system": "ETL",
                "type": "staging-table",
                "version": "v1",
                "entity_name": ENTITY_NAME,
                "ddl_content": (
                    "CREATE TABLE customer_stage ("
                    "customer_id VARCHAR(64) NOT NULL, "
                    "customer_name VARCHAR(128), "
                    "status_cd VARCHAR(32), "
                    "email_address VARCHAR(128)"
                    ");"
                ),
                "field_mappings": [
                    {"source": "Customer.id", "target": "customer_id"},
                    {"source": "Customer.customerName", "target": "customer_name"},
                    {"source": "Customer.status", "target": "status_cd"},
                    {"source": "Customer.emailAddress", "target": "email_address"},
                ],
            }
        ]
    },
)
assert r.status_code == 200, f"handoffs/save failed: {r.status_code} {r.text[:200]}"
assert r.json().get("ok"), "handoffs/save ok=false"
print(f"         OK — {r.json()['count']} handoff(s) saved")

print("\n[Step 6] Skipping business rules (not part of this proof)")

print("\n[Step 7] Checking completeness report...")
r = client.get("/review/report")
if r.status_code == 200:
    print_report(r.json())
else:
    print_report(None, build_completeness_report(get_session()))

print("\n[Step 8] Exporting package...")
r = client.post("/export/write")
print(f"         Status: {r.status_code}")
body = r.json()
print(f"         Body: {body}")
if not body.get("ok"):
    print("\nEXPORT FAILED — checking session state...")
    report_obj = build_completeness_report(get_session())
    for item in report_obj.items:
        print(f"  [{item.status}] {item.category}: {item.message}")
    sys.exit(1)

output_dir = body.get("output_dir")
files = body.get("files", [])
print(f"         Output dir: {output_dir}")
print(f"         Files written: {files}")

print("\n[Step 9] Verifying exported package shape...")
project_dir = Path(output_dir)
manifest_path = project_dir / "app-definition.yaml"
manifest = yaml.safe_load(manifest_path.read_text())
print_manifest_summary(manifest)

assert manifest.get("schema_version") == STUDIO_MANIFEST_SCHEMA_VERSION, (
    f"schema_version must be {STUDIO_MANIFEST_SCHEMA_VERSION}"
)
assert manifest.get("app_archetype") == "crud", "app_archetype must be crud"
assert len(manifest.get("downstream_interfaces", [])) == 1, "Expected one downstream interface"
assert len(manifest.get("data_handoffs", [])) == 1, "Expected one handoff"

expected_package_files = [
    project_dir / "downstream/customer-eod-handoff-file-layout.yaml",
    project_dir / "downstream/customer-eod-handoff-file-mapping.yaml",
    project_dir / "downstream/customer-eod-handoff-file-sample.txt",
    project_dir / "data-handoffs/customer-staging-table.sql",
    project_dir / "data-handoffs/customer-staging-table-mapping.yaml",
]
assert_expected_files(project_dir, expected_package_files, label="package artifact")

print("\n[Step 10] Validating manifest with EdgeForge Engine...")
validate_manifest_or_exit(manifest_path, ENGINE_REPO)

GENERATED_DIR = TMP_ROOT / "generated-codat-customer-composite"
print(f"\n[Step 11] Generating Spring Boot app -> {GENERATED_DIR}...")
_, java_files, _all_files = generate_app_or_exit(manifest_path, GENERATED_DIR, ENGINE_REPO)

print("\n[Step 11b] Verifying generated downstream/handoff artifacts...")
expected_generated_files = [
    "CustomerEodHandoffFileWriter.java",
    "CustomerStagingWriter.java",
    "CustomerEodBatchJob.java",
    "BatchTriggerController.java",
]
assert_expected_generated_filenames(GENERATED_DIR, expected_generated_files)

print("\n[Step 12] Maven build (mvn clean package -DskipTests)...")
java17_home = find_java17_home()
run_maven_build_or_exit(GENERATED_DIR, java17_home=java17_home)

APP_PORT = 8097
jar_path = resolve_generated_jar(GENERATED_DIR, "customerops-0.0.1-SNAPSHOT.jar")

print(f"\n[Step 13] Starting generated app on port {APP_PORT}...")
running_app = start_generated_app_or_exit(
    GENERATED_DIR,
    jar_path=jar_path,
    app_port=APP_PORT,
    java17_home=java17_home,
)
elapsed = running_app.elapsed_seconds
collection_path = discover_collection_path(GENERATED_DIR)
collection_url = f"http://localhost:{APP_PORT}{collection_path}"
created_customer_id = None

try:
    print(f"\n[Step 14] API smoke for generated CRUD app ({collection_path})...")
    status, body = json_request(collection_url)
    items = assert_json_array(body, f"GET {collection_path}")
    print(f"          GET {collection_path} -> HTTP {status}, {len(items)} item(s)")
    if status != 200:
        raise RuntimeError(f"GET {collection_path} returned HTTP {status}, expected 200")

    create_payload = json.loads(CUSTOMER_REQUEST_SAMPLE)
    status, body = json_request(collection_url, method="POST", payload=create_payload)
    print(f"          POST {collection_path} -> HTTP {status}, body: {body.strip()}")
    if status not in (200, 201):
        raise RuntimeError(f"POST {collection_path} returned HTTP {status}, expected 200/201")
    created = json.loads(body)
    if not isinstance(created, dict) or "id" not in created:
        raise RuntimeError(f"POST {collection_path} returned unexpected JSON body: {body}")
    created_customer_id = str(created["id"])

    status, body = json_request(collection_url)
    items = assert_json_array(body, f"GET {collection_path} after create")
    print(f"          GET {collection_path} after create -> HTTP {status}, {len(items)} item(s)")
    if len(items) < 1:
        raise RuntimeError("Expected at least one stored customer after POST")

    detail_url = f"{collection_url}/{created_customer_id}"
    status, body = json_request(detail_url)
    print(f"          GET {collection_path}/{created_customer_id} -> HTTP {status}, body: {body.strip()}")
    if status != 200:
        raise RuntimeError(f"GET detail returned HTTP {status}, expected 200")

    print("\n[Step 15] Batch/handoff smoke...")
    batch_url = f"http://localhost:{APP_PORT}/batch/run/customerEodJob"
    status, body = json_request(batch_url, method="POST", payload={})
    print(f"          POST /batch/run/customerEodJob -> HTTP {status}, body: {body.strip()}")
    if status != 200:
        raise RuntimeError(f"Batch trigger returned HTTP {status}, expected 200")
    batch_response = json.loads(body)
    batch_status = batch_response.get("status")
    if batch_status not in {"COMPLETED", "STARTED", "STARTING"}:
        raise RuntimeError(f"Unexpected batch status: {batch_status}")

    eod_dir = GENERATED_DIR / f"{BOUNDED_CONTEXT}-eod"
    eod_file = eod_dir / f"customer-eod-{date.today().strftime('%Y%m%d')}.dat"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not eod_file.exists():
        time.sleep(1)
    if not eod_file.exists():
        raise RuntimeError(f"Expected EOD output file not found: {eod_file}")
    eod_text = eod_file.read_text()
    print(f"          EOD output file: {eod_file}")
    if created_customer_id not in eod_text and create_payload["customerName"] not in eod_text:
        raise RuntimeError("EOD output file does not contain the created customer id or name")
    print("          PASS — batch trigger completed and produced downstream file output")
finally:
    running_app.stop()

print(
    f"""
=== COMPOSITE PROOF RUN COMPLETE — ALL STEPS PASSED ===
  Studio export                       PASS  (schema_version={STUDIO_MANIFEST_SCHEMA_VERSION}, app_archetype=crud)
  Package shape                       PASS  (downstream + handoff files present)
  Engine validation                   PASS
  Engine generation                   PASS  ({len(java_files)} Java source files)
  Generated batch/handoff classes     PASS
  Maven build                         PASS  (BUILD SUCCESS)
  App start + health                  PASS  (~{elapsed}s on :{APP_PORT})
  CRUD API smoke                      PASS  (list/create/detail)
  Batch/handoff smoke                 PASS  (/batch/run/customerEodJob + EOD file)

  Manifest:      {manifest_path}
  Generated app: {GENERATED_DIR}
  Created id:    {created_customer_id}
"""
)
