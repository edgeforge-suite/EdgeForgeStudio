"""
Real-App E2E Proof Run — EdgeForge Studio → Engine — 2026-03-30

Selected spec: Petstore OpenAPI 3.0 (https://petstore3.swagger.io/api/v3/openapi.json)
Entity scope: Pet, operations: addPet (POST), getPetById (GET)

Run this from the EdgeForgeStudio repo root:
    python3 scripts/proof_run_petstore.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

# Ensure Studio package is importable from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from app.services.manifest_contract import STUDIO_MANIFEST_SCHEMA_VERSION
from app.services.runtime_defaults import default_edgeforge_repo_path

PETSTORE_URL = "https://petstore3.swagger.io/api/v3/openapi.json"
ENGINE_REPO = default_edgeforge_repo_path()

# ─────────────────────────────────────────────────────────────
# Step 0: Reset session so we start clean
# ─────────────────────────────────────────────────────────────
print("\n=== PROOF RUN — EdgeForge Studio → Engine — 2026-03-30 ===\n")

from app.main import app

client = TestClient(app, raise_server_exceptions=True)

print("[Step 0] Resetting Studio session...")
r = client.post("/export/reset")
assert r.status_code == 200, f"Reset failed: {r.text}"
print("         OK — session reset")

# ─────────────────────────────────────────────────────────────
# Step 1: Project setup (POST /)
# ─────────────────────────────────────────────────────────────
print("\n[Step 1] Posting project setup...")

# Use a tmp dir as output root so we write to a controlled location
TMP_ROOT = Path(tempfile.mkdtemp(prefix="edgeforge_proofrun_"))
print(f"         Output root: {TMP_ROOT}")

r = client.post(
    "/",
    data={
        "app_name": "Petstore Pet Service",
        "bounded_context": "pets",
        "target_profile": "springboot-legacy-compatible",
        "output_path": str(TMP_ROOT),
        "appbuilder_repo_path": ENGINE_REPO,
    },
    follow_redirects=False,
)
# Should redirect to /upstream
assert r.status_code in (200, 302, 303), f"Step 1 POST failed: {r.status_code} {r.text[:200]}"
print("         OK — project setup saved")

# ─────────────────────────────────────────────────────────────
# Step 2: Ingest Petstore spec via URL
# ─────────────────────────────────────────────────────────────
print(f"\n[Step 2] Ingesting Petstore spec from {PETSTORE_URL}...")
r = client.post(
    "/upstream/ingest-url",
    data={"spec_url": PETSTORE_URL},
)
assert r.status_code == 200, f"Ingest URL failed: {r.status_code} {r.text[:200]}"
body = r.json()
assert body.get("ok"), f"Ingest URL returned ok=false: {body}"

entities = body["entities"]
operations = body["operations"]
entity_names = [e["name"] for e in entities]
op_names = [o["name"] for o in operations]
print(f"         Classified {len(entities)} entities: {entity_names}")
print(f"         Classified {len(operations)} operations")

# Confirm Pet is present
assert "Pet" in entity_names, f"Pet entity not found in: {entity_names}"
pet_ops = [o["name"] for o in operations if "Pet" in o.get("entity_candidates", [])]
print(f"         Pet operations: {pet_ops}")

# ─────────────────────────────────────────────────────────────
# Step 3: Select Pet entity + addPet + getPetById
# ─────────────────────────────────────────────────────────────
print("\n[Step 3] Selecting Pet entity with addPet + getPetById...")

# Determine which ops to select
SELECTED_OPS = [o for o in ["addPet", "getPetById"] if o in op_names]
print(f"         Selected operations: {SELECTED_OPS}")

r = client.post(
    "/entities/save",
    json={
        "entities": ["Pet"],
        "operations": SELECTED_OPS,
        "entity_op_map": {"Pet": SELECTED_OPS},
    },
)
assert r.status_code == 200, f"entities/save failed: {r.status_code} {r.text[:200]}"
body = r.json()
assert body.get("ok"), f"entities/save ok=false: {body}"
print(f"         OK — {body['interface_count']} interface(s) created")

# Check the interface data returned
interfaces = body.get("interfaces", [])
print(f"         Interfaces: {[i['name'] for i in interfaces]}")
if interfaces:
    for iface in interfaces:
        print(f"         Operations for {iface['name']}:")
        for op in iface.get("operations", []):
            print(f"           {op['name']}: req_sample={'present' if op.get('request_sample_content') else 'MISSING'}, "
                  f"resp_sample={'present' if op.get('response_sample_content') else 'MISSING'}")

# ─────────────────────────────────────────────────────────────
# Save samples via /mappings/upstream/samples/save
# ─────────────────────────────────────────────────────────────
print("\n[Step 3b] Saving operation samples...")

# Generate samples from spec directly using openapi_service
from app.services.openapi_service import (
    _component_schemas,
    classify_openapi_spec,
    fetch_openapi_from_url,
    generate_operation_samples,
)

spec = fetch_openapi_from_url(PETSTORE_URL)
all_schemas = _component_schemas(spec)
_, classified_ops = classify_openapi_spec(spec)
op_lookup = {o.name: o for o in classified_ops}

PET_SAMPLE_REQ = json.dumps({
    "id": 10,
    "name": "doggie",
    "category": {"id": 1, "name": "Dogs"},
    "photoUrls": ["https://example.com/photo1.jpg"],
    "tags": [{"id": 0, "name": "friendly"}],
    "status": "available",
}, indent=2)

PET_SAMPLE_RESP = json.dumps({
    "id": 10,
    "name": "doggie",
    "category": {"id": 1, "name": "Dogs"},
    "photoUrls": ["https://example.com/photo1.jpg"],
    "tags": [{"id": 0, "name": "friendly"}],
    "status": "available",
}, indent=2)

# Get the interface name from saved state
from app.services.session_store import get_session

session = get_session()
iface_name = session.upstream_interfaces[0].name if session.upstream_interfaces else "pets-pet-api"
print(f"         Interface name: {iface_name}")

ops_payload = []
for op_name in SELECTED_OPS:
    o = op_lookup.get(op_name)
    auto_req, auto_resp = generate_operation_samples(
        o.request_schema if o else None,
        o.response_schema if o else None,
        all_schemas,
    )
    ops_payload.append({
        "name": op_name,
        "request_sample_content": auto_req or (PET_SAMPLE_REQ if op_name == "addPet" else None),
        "response_sample_content": auto_resp or PET_SAMPLE_RESP,
    })
    print(f"           {op_name}: req={'yes' if ops_payload[-1]['request_sample_content'] else 'no'}, "
          f"resp={'yes' if ops_payload[-1]['response_sample_content'] else 'no'}")

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

# ─────────────────────────────────────────────────────────────
# Save mappings via /mappings/upstream/save
# ─────────────────────────────────────────────────────────────
print("\n[Step 3c] Saving field mappings...")

from app.services.openapi_service import generate_field_mappings

operation_mappings = []
for op_name in SELECTED_OPS:
    o = op_lookup.get(op_name)
    req_maps = []
    resp_maps = []
    if o and o.request_schema and all_schemas:
        req_maps = generate_field_mappings(o.request_schema, "Pet", all_schemas)
    if o and o.response_schema and all_schemas:
        resp_maps = generate_field_mappings(o.response_schema, "Pet", all_schemas)
    operation_mappings.append({
        "name": op_name,
        "request_mappings": req_maps,
        "response_mappings": resp_maps,
    })
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

# ─────────────────────────────────────────────────────────────
# Steps 4-6: Skip (optional downstream, handoffs, rules)
# Downstream/handoffs/rules are WARNINGs not MANUAL_FOLLOW_UP
# so export should not be blocked
# ─────────────────────────────────────────────────────────────
print("\n[Steps 4-6] Skipping downstream, handoffs, rules (optional for minimal proof)")

# ─────────────────────────────────────────────────────────────
# Step 7: Check completeness report
# ─────────────────────────────────────────────────────────────
print("\n[Step 7] Checking completeness report...")
r = client.get("/review/report")
if r.status_code == 200:
    report = r.json()
    print(f"         Report: {report}")
else:
    # Fallback: use internal completeness check
    from app.services.completeness_service import build_completeness_report
    session = get_session()
    report_obj = build_completeness_report(session)
    summary = report_obj.summary()
    print(f"         Completeness: {summary}")
    blockers = [i.message for i in report_obj.manual()]
    if blockers:
        print("         BLOCKERS:")
        for b in blockers:
            print(f"           - {b}")

# ─────────────────────────────────────────────────────────────
# Step 8: Export package to disk
# ─────────────────────────────────────────────────────────────
print("\n[Step 8] Exporting package...")
r = client.post("/export/write")
print(f"         Status: {r.status_code}")
body = r.json()
print(f"         Body: {body}")

if not body.get("ok"):
    print("\nEXPORT FAILED — checking session state...")
    session = get_session()
    from app.services.completeness_service import build_completeness_report
    report_obj = build_completeness_report(session)
    for item in report_obj.items:
        print(f"  [{item.status}] {item.category}: {item.message}")
    sys.exit(1)

output_dir = body.get("output_dir")
files = body.get("files", [])
print(f"         Output dir: {output_dir}")
print(f"         Files written: {files}")

# ─────────────────────────────────────────────────────────────
# Step 9: Verify exported app-definition.yaml
# ─────────────────────────────────────────────────────────────
print("\n[Step 9] Verifying exported app-definition.yaml...")
manifest_path = Path(output_dir) / "app-definition.yaml"
import yaml as _yaml

with open(manifest_path) as f:
    manifest = _yaml.safe_load(f)

print(f"         schema_version: {manifest.get('schema_version')}")
print(f"         app_archetype: {manifest.get('app_archetype')}")
print(f"         app_name: {manifest.get('app_name')}")
print(f"         bounded_context: {manifest.get('bounded_context')}")
print(f"         upstream_interfaces: {[i.get('name') for i in manifest.get('upstream_interfaces', [])]}")

assert manifest.get("schema_version") == STUDIO_MANIFEST_SCHEMA_VERSION, (
    f"schema_version mismatch: expected {STUDIO_MANIFEST_SCHEMA_VERSION}, "
    f"got {manifest.get('schema_version')}"
)
assert manifest.get("app_archetype") == "crud", f"app_archetype mismatch: {manifest.get('app_archetype')}"
print(
    f"         PASS — schema_version={STUDIO_MANIFEST_SCHEMA_VERSION} "
    "and app_archetype=crud confirmed"
)

# ─────────────────────────────────────────────────────────────
# Step 10: EdgeForge Engine — manifest validation
# ─────────────────────────────────────────────────────────────
print("\n[Step 10] Validating manifest with EdgeForge Engine (load_project_definition)...")
from app.integrations.appbuilder_integration import run_generate, validate_manifest
from scripts.proof_runner_helpers import discover_collection_path

val_result = validate_manifest(manifest_path, ENGINE_REPO)
print(f"         Command: {' '.join(str(c) for c in val_result.command)}")
print(f"         Output:  {val_result.combined_output}")
print(f"         Success: {val_result.success}  (exit={val_result.returncode}, {val_result.duration_seconds:.3f}s)")
if not val_result.success:
    print("\nVALIDATION FAILED — stopping proof run.")
    sys.exit(1)
print("         PASS — manifest accepted by Engine")

# ─────────────────────────────────────────────────────────────
# Step 11: EdgeForge Engine — generate Spring Boot app
# ─────────────────────────────────────────────────────────────
GENERATED_DIR = TMP_ROOT / "generated-petstore"
print(f"\n[Step 11] Generating Spring Boot app -> {GENERATED_DIR}...")
gen_result = run_generate(str(manifest_path), str(GENERATED_DIR), ENGINE_REPO)
print(f"         Command: {' '.join(str(c) for c in gen_result.command)}")
print(f"         Output:\n{gen_result.combined_output}")
print(f"         Success: {gen_result.success}  (exit={gen_result.returncode}, {gen_result.duration_seconds:.3f}s)")
if not gen_result.success:
    print("\nGENERATION FAILED — stopping proof run.")
    sys.exit(1)
java_files = list(GENERATED_DIR.rglob("*.java"))
all_files  = [f for f in GENERATED_DIR.rglob("*") if f.is_file()]
print(f"         PASS — {len(all_files)} files generated, {len(java_files)} Java source files")

# Derive the collection route from the generated controller so the smoke
# test stays correct even if the Engine emits /pet instead of /pets.
collection_path = discover_collection_path(GENERATED_DIR)
print(f"         Discovered collection route: {collection_path}")

# ─────────────────────────────────────────────────────────────
# Step 12: Maven build (skip tests for speed)
# ─────────────────────────────────────────────────────────────
import os
import shutil
import subprocess as _sp

print("\n[Step 12] Maven build (mvn clean package -DskipTests)...")


def _find_java17_home() -> str | None:
    """Return JAVA_HOME for a Java 17 installation, or None to use system default."""
    candidates = [
        "/opt/homebrew/opt/openjdk@17",
        "/usr/local/opt/openjdk@17",
        "/opt/homebrew/Cellar/openjdk@17",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if (path / "bin" / "java").exists():
            return str(path)
        # Cellar paths may have version sub-directories
        if path.is_dir():
            for child in sorted(path.iterdir(), reverse=True):
                if (child / "bin" / "java").exists():
                    return str(child)
    return None


mvn_cmd = shutil.which("mvn") or "mvn"
java17_home = _find_java17_home()
build_env = os.environ.copy()
if java17_home:
    build_env["JAVA_HOME"] = java17_home
    print(f"         JAVA_HOME: {java17_home}")
else:
    print("         JAVA_HOME: (system default — ensure Java 17+ is on PATH)")

build_proc = _sp.run(
    [mvn_cmd, "clean", "package", "-DskipTests", "--batch-mode"],
    cwd=str(GENERATED_DIR),
    env=build_env,
    capture_output=True,
    text=True,
    timeout=300,
)
build_output = (build_proc.stdout + build_proc.stderr).strip()
last_lines = "\n".join(build_output.splitlines()[-20:])
print(f"         Last 20 lines:\n{last_lines}")
print(f"         Return code: {build_proc.returncode}")
if build_proc.returncode != 0:
    print("\nMAVEN BUILD FAILED — stopping proof run.")
    sys.exit(1)
print("         PASS — BUILD SUCCESS")

# ─────────────────────────────────────────────────────────────
# Step 13: Start the generated app and run a health check
# ─────────────────────────────────────────────────────────────
import time
import urllib.error
import urllib.request

APP_PORT = 8095
jar_path = GENERATED_DIR / "target" / "pets-0.0.1-SNAPSHOT.jar"
# Fallback: find any non-sources, non-original jar in target/
if not jar_path.exists():
    target_jars = [
        j for j in (GENERATED_DIR / "target").glob("*.jar")
        if "sources" not in j.name and "original" not in j.name
    ]
    jar_path = target_jars[0] if target_jars else jar_path

print(f"\n[Step 13] Starting generated app on port {APP_PORT}...")
print(f"          JAR: {jar_path}")

java_bin = str(Path(java17_home) / "bin" / "java") if java17_home else "java"
app_proc = _sp.Popen(
    [java_bin, "-jar", str(jar_path), f"--server.port={APP_PORT}"],
    cwd=str(GENERATED_DIR),
    stdout=_sp.PIPE,
    stderr=_sp.STDOUT,
    text=True,
)

health_url = f"http://localhost:{APP_PORT}/actuator/health"
started = False
start_t = time.monotonic()
print(f"          Waiting for {health_url} (up to 30s)...")
for _ in range(30):
    time.sleep(1)
    try:
        with urllib.request.urlopen(health_url, timeout=2) as resp:
            health_body = resp.read().decode()
            started = True
            print(f"          Health response: {health_body}")
            break
    except (urllib.error.URLError, ConnectionRefusedError):
        pass

elapsed = round(time.monotonic() - start_t, 1)

if not started:
    app_proc.kill()
    app_out, _ = app_proc.communicate(timeout=5)
    print(f"          App output (first 2000 chars):\n{(app_out or '')[:2000]}")
    print("\nAPP DID NOT START within 30s — stopping proof run.")
    sys.exit(1)

print(f"          PASS — app is UP (started in ~{elapsed}s)")

# API smoke: GET <collection_path> must return HTTP 200 with a JSON array body.
# This is a hard gate — a 404 or 500 means the controller layer is broken.
api_url = f"http://localhost:{APP_PORT}{collection_path}"
try:
    req = urllib.request.Request(api_url)
    with urllib.request.urlopen(req, timeout=5) as resp:
        status = resp.status
        api_body = resp.read().decode()
    print(f"          GET {collection_path} -> HTTP {status}  body: {api_body.strip()}")
    if status != 200:
        app_proc.kill()
        print(f"\nAPI SMOKE FAILED — GET {collection_path} returned HTTP {status}, expected 200.")
        sys.exit(1)
    import json as _json
    parsed = _json.loads(api_body)
    if not isinstance(parsed, list):
        app_proc.kill()
        print(f"\nAPI SMOKE FAILED — GET {collection_path} returned unexpected body (expected JSON array): {api_body.strip()}")
        sys.exit(1)
    print(f"          PASS — GET {collection_path} returned HTTP 200 with a JSON array ({len(parsed)} items)")
except urllib.error.HTTPError as exc:
    app_proc.kill()
    print(f"\nAPI SMOKE FAILED — GET {collection_path} raised HTTPError {exc.code}: {exc}")
    sys.exit(1)
except urllib.error.URLError as exc:
    app_proc.kill()
    print(f"\nAPI SMOKE FAILED — GET {collection_path} unreachable: {exc}")
    sys.exit(1)

app_proc.terminate()
try:
    app_proc.wait(timeout=10)
except _sp.TimeoutExpired:
    app_proc.kill()
print("          App stopped.")

# ─────────────────────────────────────────────────────────────
# All steps done
# ─────────────────────────────────────────────────────────────
print(f"""
=== PROOF RUN COMPLETE — ALL STEPS PASSED ===
  Studio export      PASS  (schema_version={STUDIO_MANIFEST_SCHEMA_VERSION}, app_archetype=crud)
  Engine validation  PASS
  Engine generation  PASS  ({len(java_files)} Java source files)
  Maven build        PASS  (BUILD SUCCESS)
  App start+health   PASS  (~{elapsed}s on :{APP_PORT})
  GET {collection_path} smoke    PASS  (HTTP 200, JSON array)

  Manifest:      {manifest_path}
  Generated app: {GENERATED_DIR}
""")
