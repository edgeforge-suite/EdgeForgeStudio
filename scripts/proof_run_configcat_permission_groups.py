"""
Stronger Real-World CRUD E2E Proof Run — EdgeForge Studio → Engine — 2026-03-31

Selected spec: ConfigCat Public Management API
Spec URL: https://api.apis.guru/v2/specs/configcat.com/v1/openapi.yaml
Entity scope: PermissionGroupModel
Operations: create-permission-group, get-permission-groups, get-permission-group, update-permission-group

Run this from the EdgeForgeStudio repo root:
    git clone https://github.com/APIs-guru/openapi-directory /tmp/openapi-directory
    python3 scripts/proof_run_configcat_permission_groups.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import yaml

# Ensure Studio package is importable from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from app.main import app
from app.services.completeness_service import build_completeness_report
from app.services.manifest_contract import STUDIO_MANIFEST_SCHEMA_VERSION
from app.services.openapi_service import (
    _component_schemas,
    classify_openapi_spec,
    generate_field_mappings,
    generate_operation_samples,
)
from app.services.runtime_defaults import default_edgeforge_repo_path
from app.services.session_store import get_session
from scripts.proof_runner_helpers import (
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

CONFIGCAT_URL = "https://api.apis.guru/v2/specs/configcat.com/v1/openapi.yaml"
CONFIGCAT_SPEC_PATH = Path("/tmp/openapi-directory/APIs/configcat.com/v1/openapi.yaml")
ENGINE_REPO = default_edgeforge_repo_path()
ENTITY_NAME = "PermissionGroupModel"
APP_NAME = "ConfigCat Permission Group Service"
BOUNDED_CONTEXT = "permissions"
TARGET_PROFILE = "springboot-legacy-compatible"
SELECTED_OPS = [
    "create-permission-group",
    "get-permission-groups",
    "get-permission-group",
    "update-permission-group",
]

REQUEST_SAMPLE = json.dumps(
    {
        "name": "Operators",
        "accessType": "custom",
        "canCreateOrUpdateConfig": True,
        "canCreateOrUpdateEnvironment": True,
        "canCreateOrUpdateSegments": False,
        "canCreateOrUpdateSetting": True,
        "canCreateOrUpdateTag": False,
        "canDeleteConfig": False,
        "canDeleteEnvironment": False,
        "canDeleteSegments": False,
        "canDeleteSetting": False,
        "canDeleteTag": False,
        "canManageIntegrations": False,
        "canManageMembers": True,
        "canManageProductPreferences": False,
        "canManageWebhook": False,
        "canRotateSdkKey": False,
        "canTagSetting": True,
        "canUseExportImport": False,
        "canViewProductAuditLog": True,
        "canViewProductStatistics": True,
        "canViewSdkKey": True,
        "environmentAccesses": [
            {
                "color": "green",
                "description": "Shared prod access",
                "environmentAccessType": "readOnly",
                "environmentId": "11111111-1111-1111-1111-111111111111",
                "name": "Production",
                "order": 1,
                "reasonRequired": False,
            }
        ],
        "newEnvironmentAccessType": "readOnly",
    },
    indent=2,
)

RESPONSE_SAMPLE = json.dumps(
    {
        "permissionGroupId": 101,
        "name": "Operators",
        "accessType": "custom",
        "canCreateOrUpdateConfig": True,
        "canCreateOrUpdateEnvironment": True,
        "canCreateOrUpdateSegments": False,
        "canCreateOrUpdateSetting": True,
        "canCreateOrUpdateTag": False,
        "canDeleteConfig": False,
        "canDeleteEnvironment": False,
        "canDeleteSegments": False,
        "canDeleteSetting": False,
        "canDeleteTag": False,
        "canManageIntegrations": False,
        "canManageMembers": True,
        "canManageProductPreferences": False,
        "canManageWebhook": False,
        "canRotateSdkKey": False,
        "canTagSetting": True,
        "canUseExportImport": False,
        "canViewProductAuditLog": True,
        "canViewProductStatistics": True,
        "canViewSdkKey": True,
        "environmentAccesses": [
            {
                "color": "green",
                "description": "Shared prod access",
                "environmentAccessType": "readOnly",
                "environmentId": "11111111-1111-1111-1111-111111111111",
                "name": "Production",
                "order": 1,
                "reasonRequired": False,
            }
        ],
        "newEnvironmentAccessType": "readOnly",
        "product": {
            "productId": "product-001",
            "name": "Feature Flags",
            "description": "Operations controls",
            "order": 1,
            "reasonRequired": False,
        },
    },
    indent=2,
)

print("\n=== STRONGER CRUD PROOF RUN — EdgeForge Studio → Engine — 2026-03-31 ===\n")

client = TestClient(app, raise_server_exceptions=True)

print("[Step 0] Resetting Studio session...")
r = client.post("/export/reset")
assert r.status_code == 200, f"Reset failed: {r.text}"
print("         OK — session reset")

print("\n[Step 1] Posting project setup...")
TMP_ROOT = Path(tempfile.mkdtemp(prefix="edgeforge_configcat_proofrun_"))
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

print(f"\n[Step 2] Ingesting ConfigCat spec from local pinned file {CONFIGCAT_SPEC_PATH}...")
assert CONFIGCAT_SPEC_PATH.exists(), (
    f"ConfigCat spec file not found: {CONFIGCAT_SPEC_PATH}. "
    "Clone https://github.com/APIs-guru/openapi-directory to /tmp/openapi-directory first."
)
r = client.post(
    "/upstream/ingest-file",
    files={
        "spec_file": (
            CONFIGCAT_SPEC_PATH.name,
            CONFIGCAT_SPEC_PATH.read_bytes(),
            "application/yaml",
        )
    },
)
assert r.status_code == 200, f"Ingest file failed: {r.status_code} {r.text[:200]}"
body = r.json()
assert body.get("ok"), f"Ingest URL returned ok=false: {body}"

entities = body["entities"]
operations = body["operations"]
entity_names = [e["name"] for e in entities]
op_names = [o["name"] for o in operations]
print(f"         Classified {len(entities)} entities")
print(f"         Classified {len(operations)} operations")
assert ENTITY_NAME in entity_names, f"{ENTITY_NAME} not found in: {entity_names[:25]}"
permission_ops = [o["name"] for o in operations if ENTITY_NAME in o.get("entity_candidates", [])]
print(f"         {ENTITY_NAME} operations: {permission_ops}")

print(f"\n[Step 3] Selecting {ENTITY_NAME} with create/list/get/update...")
selected_ops = [name for name in SELECTED_OPS if name in op_names]
assert selected_ops == SELECTED_OPS, f"Missing selected ops: expected {SELECTED_OPS}, got {selected_ops}"
print(f"         Selected operations: {selected_ops}")

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
print(f"         OK — {body['interface_count']} interface(s) created")

interfaces = body.get("interfaces", [])
print(f"         Interfaces: {[i['name'] for i in interfaces]}")

print("\n[Step 3b] Saving operation samples...")
spec = yaml.safe_load(CONFIGCAT_SPEC_PATH.read_text())
all_schemas = _component_schemas(spec)
_, classified_ops = classify_openapi_spec(spec)
op_lookup = {o.name: o for o in classified_ops}

session = get_session()
iface_name = session.upstream_interfaces[0].name if session.upstream_interfaces else "permissions-permission-group-model-api"
print(f"         Interface name: {iface_name}")

ops_payload = []
for op_name in selected_ops:
    op = op_lookup.get(op_name)
    auto_req, auto_resp = generate_operation_samples(
        op.request_schema if op else None,
        op.response_schema if op else None,
        all_schemas,
    )
    ops_payload.append(
        {
            "name": op_name,
            "request_sample_content": auto_req or (REQUEST_SAMPLE if op_name in {"create-permission-group", "update-permission-group"} else None),
            "response_sample_content": auto_resp or RESPONSE_SAMPLE,
        }
    )
    print(
        f"           {op_name}: req={'yes' if ops_payload[-1]['request_sample_content'] else 'no'}, "
        f"resp={'yes' if ops_payload[-1]['response_sample_content'] else 'no'}"
    )

r = client.post(
    "/mappings/upstream/samples/save",
    json={
        "interface_name": iface_name,
        "operations": ops_payload,
    },
)
assert r.status_code == 200, f"samples/save failed: {r.status_code} {r.text[:200]}"
assert r.json().get("ok"), "samples/save ok=false"
print("         OK — samples saved")

print("\n[Step 3c] Saving field mappings...")
operation_mappings = []
for op_name in selected_ops:
    op = op_lookup.get(op_name)
    req_maps = []
    resp_maps = []
    if op and op.request_schema and all_schemas:
        req_maps = generate_field_mappings(op.request_schema, ENTITY_NAME, all_schemas)
    if op and op.response_schema and all_schemas:
        resp_maps = generate_field_mappings(op.response_schema, ENTITY_NAME, all_schemas)
    operation_mappings.append(
        {
            "name": op_name,
            "request_mappings": req_maps,
            "response_mappings": resp_maps,
        }
    )
    print(f"           {op_name}: {len(req_maps)} req mappings, {len(resp_maps)} resp mappings")

r = client.post(
    "/mappings/upstream/save",
    json={
        "interface_name": iface_name,
        "operation_mappings": operation_mappings,
    },
)
assert r.status_code == 200, f"mappings/save failed: {r.status_code} {r.text[:200]}"
assert r.json().get("ok"), "mappings/save ok=false"
print("         OK — mappings saved")

print("\n[Steps 4-6] Skipping downstream, handoffs, rules (optional for CRUD proof)")

print("\n[Step 7] Checking completeness report...")
r = client.get("/review/report")
if r.status_code == 200:
    print_report(r.json())
else:
    session = get_session()
    print_report(None, build_completeness_report(session))

print("\n[Step 8] Exporting package...")
r = client.post("/export/write")
print(f"         Status: {r.status_code}")
body = r.json()
print(f"         Body: {body}")
if not body.get("ok"):
    print("\nEXPORT FAILED — checking session state...")
    session = get_session()
    report_obj = build_completeness_report(session)
    for item in report_obj.items:
        print(f"  [{item.status}] {item.category}: {item.message}")
    sys.exit(1)

output_dir = body.get("output_dir")
files = body.get("files", [])
print(f"         Output dir: {output_dir}")
print(f"         Files written: {files}")

print("\n[Step 9] Verifying exported app-definition.yaml...")
manifest_path = Path(output_dir) / "app-definition.yaml"
with manifest_path.open() as f:
    manifest = yaml.safe_load(f)

print_manifest_summary(manifest)

assert manifest.get("schema_version") == STUDIO_MANIFEST_SCHEMA_VERSION, (
    f"schema_version mismatch: expected {STUDIO_MANIFEST_SCHEMA_VERSION}, "
    f"got {manifest.get('schema_version')}"
)
assert manifest.get("app_archetype") == "crud", f"app_archetype mismatch: {manifest.get('app_archetype')}"
print(
    f"         PASS — schema_version={STUDIO_MANIFEST_SCHEMA_VERSION} "
    "and app_archetype=crud confirmed"
)

print("\n[Step 10] Validating manifest with EdgeForge Engine...")
validate_manifest_or_exit(manifest_path, ENGINE_REPO)

GENERATED_DIR = TMP_ROOT / "generated-configcat-permission-groups"
print(f"\n[Step 11] Generating Spring Boot app -> {GENERATED_DIR}...")
_, java_files, _all_files = generate_app_or_exit(manifest_path, GENERATED_DIR, ENGINE_REPO)

print("\n[Step 12] Maven build (mvn clean package -DskipTests)...")
java17_home = find_java17_home()
run_maven_build_or_exit(GENERATED_DIR, java17_home=java17_home)

APP_PORT = 8096
jar_path = resolve_generated_jar(GENERATED_DIR, "permissions-0.0.1-SNAPSHOT.jar")

print(f"\n[Step 13] Starting generated app on port {APP_PORT}...")
running_app = start_generated_app_or_exit(
    GENERATED_DIR,
    jar_path=jar_path,
    app_port=APP_PORT,
    java17_home=java17_home,
)
elapsed = running_app.elapsed_seconds
collection_path = discover_collection_path(GENERATED_DIR, excluded={"DemoController.java"})
api_url = f"http://localhost:{APP_PORT}{collection_path}"
print(f"          Collection endpoint discovered: {collection_path}")
try:
    status, api_body = json_request(api_url, timeout=5)
    print(f"          GET {collection_path} -> HTTP {status}  body: {api_body.strip()}")
    if status != 200:
        print(f"\nAPI SMOKE FAILED — GET {collection_path} returned HTTP {status}, expected 200.")
        sys.exit(1)
    parsed = assert_json_array(api_body, f"GET {collection_path}")
    print(f"          PASS — GET {collection_path} returned HTTP 200 with a JSON array ({len(parsed)} items)")
except Exception as exc:
    print(f"\nAPI SMOKE FAILED — GET {collection_path} failed: {exc}")
    sys.exit(1)
finally:
    running_app.stop()

print("          App stopped.")
print(
    f"""
=== STRONGER CRUD PROOF RUN COMPLETE — ALL STEPS PASSED ===
  Studio export                PASS  (schema_version={STUDIO_MANIFEST_SCHEMA_VERSION}, app_archetype=crud)
  Engine validation            PASS
  Engine generation            PASS  ({len(java_files)} Java source files)
  Maven build                  PASS  (BUILD SUCCESS)
  App start+health             PASS  (~{elapsed}s on :{APP_PORT})
  GET {collection_path} smoke  PASS  (HTTP 200, JSON array)

  Manifest:      {manifest_path}
  Generated app: {GENERATED_DIR}
"""
)
