"""Opt-in local S8 journey: real HTTP Studio actions, real Engine and Maven.

No session injection or Engine CLI shortcuts. Generated developer-file editing
and terminal Maven/Java steps are explicit, matching docs/newcomer-journey.md.
All output belongs to a new directory outside either source checkout.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path

import httpx

STUDIO = Path(__file__).resolve().parents[1]
ENGINE_PIN = "64f51d0bac92b4c70f26c8f5f067888717df7b14"
SAMPLE = "docs/sample-packs/fs-account-servicing/project/fs-account-servicing.edgeforge-project.json"
PROFILE = "springboot-legacy-compatible"
HOOK_VALUE = "CUST-S8-HOOK"
SERVICE = "src/main/java/com/appbuilder/account_servicing/service/AccountService.java"
BASE = "src/main/java/com/appbuilder/account_servicing/service/AccountServiceBase.java"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()


def source_identity(path):
    head = command(["git", "rev-parse", "HEAD"], path)
    require(not command(["git", "status", "--porcelain", "--untracked-files=normal"], path),
            f"Source checkout is not clean: {path}")
    return head


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_http(url, process, client=None):
    with (nullcontext(client) if client else httpx.Client(trust_env=False, timeout=3)) as client:
        for _ in range(120):
            require(process.poll() is None, "Server exited before becoming ready; inspect local logs")
            try:
                response = client.get(url)
                if response.status_code == 200:
                    return response
            except httpx.TransportError:
                pass
            time.sleep(.5)
    raise RuntimeError(f"Timed out waiting for {url}")


@contextmanager
def process(args, *, cwd, env, log):
    with log.open("w") as output:
        proc = subprocess.Popen(args, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT)
        try:
            yield proc
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)


def plan_hash(page):
    match = re.search(r'name="approved_plan_hash" value="([^"]+)"', page)
    require(match is not None, "Preview has no approvable plan; inspect the retained HTML")
    return html.unescape(match.group(1))


def get_preview(client, steps):
    response = client.get("/regen/preview")
    steps.append({"method": "GET", "route": "/regen/preview", "status": response.status_code})
    require(response.status_code == 200, "Regeneration preview failed")
    return response


def require_success(route, payload):
    # Save Project returns the project itself; other JSON actions must explicitly succeed.
    require(isinstance(payload, dict), f"{route}: response is not an object")
    if route != "/project/save":
        require(payload.get("ok") is True, f"{route} refused or omitted success: {payload}")
    return payload


def managed_package(snapshot, workspace):
    relative = snapshot.get("last_generated_package_ref")
    require(isinstance(relative, str) and relative, "Project has no managed baseline")
    path = (workspace / relative).resolve()
    require(path.is_relative_to(workspace.resolve()) and path.is_dir(), "Invalid managed baseline path")
    return path


def customize(path):
    source = path.read_text()
    require("EdgeForge-ownership: developer" in source, "Customization target is not developer-owned")
    placeholder = "        // Add pre-create business logic here."
    require(source.count(placeholder) == 1, "Declared beforeCreate scaffold has changed")
    path.write_text(source.replace(placeholder,
        f'        // S8 synthetic preservation witness, not a business recommendation.\n'
        f'        account.setCustomerId("{HOOK_VALUE}");'))


def assert_preserved(before, path):
    require(path.read_bytes() == before, "Developer-owned service changed during regeneration")


def exercise(url, sample, *, customized, changed, omit_nickname=False):
    require(not omit_nickname or changed, "Default proof requires the regenerated application")
    payload = json.loads(sample)
    payload["accountId"] = "ACCT-S8-DEFAULT" if omit_nickname else "ACCT-S8-001"
    payload["customerId"] = "CUST-INPUT"
    if omit_nickname:
        payload.pop("nickname", None)
    elif changed:
        payload["nickname"] = "SYNTHETIC-NICKNAME"
    with httpx.Client(base_url=url, trust_env=False, timeout=15) as client:
        created = client.post("/accounts", json=payload)
        require(created.status_code == 201, f"Create failed: {created.status_code}: {created.text}")
        result = created.json()
        expected = {**payload, "customerId": HOOK_VALUE if customized else "CUST-INPUT"}
        if omit_nickname:
            expected["nickname"] = "UNNAMED"
        for key, value in expected.items():
            require(result.get(key) == value, f"Create response differs at {key}: {result}")
        retrieved = client.get(f"/accounts/{payload['accountId']}")
        require(retrieved.status_code == 200, "Read-by-ID did not retrieve the created account")
        for key, value in expected.items():
            require(retrieved.json().get(key) == value, f"Persisted value differs at {key}")
        absent = client.get("/accounts/ACCT-MISSING")
        require(absent.status_code == 404, "Missing ID did not return 404")
        return {"request": payload, "create_status": created.status_code,
                "create_response": result, "read_status": retrieved.status_code,
                "read_response": retrieved.json(), "missing_id_status": absent.status_code}


def verify_and_run(app_dir, root, label, env, sample, *, changed):
    # Reuse the existing strict executed-test guard, including its skipped-only refusal.
    sys.path.insert(0, str(STUDIO))
    from scripts.maven_image_build_run_proof import verified_test_totals

    with (root / f"{label}-verify.log").open("w") as log:
        result = subprocess.run(["mvn", "-B", "-ntp", "clean", "verify"], cwd=app_dir,
                                env=env, stdout=log, stderr=subprocess.STDOUT, timeout=900)
    require(result.returncode == 0, f"{label}: Maven verify failed; inspect the retained log")
    counts = verified_test_totals(app_dir)
    reports = root / f"{label}-surefire"
    reports.mkdir()
    for report in app_dir.glob("target/surefire-reports/TEST-*.xml"):
        shutil.copy2(report, reports / report.name)
    jars = list((app_dir / "target").glob("*.jar"))
    require(len(jars) == 1, "Expected exactly one executable application JAR")
    port = free_port()
    with process(["java", "-jar", str(jars[0]), "--server.address=127.0.0.1", f"--server.port={port}"],
                 cwd=app_dir, env=env, log=root / f"{label}-run.log") as app:
        url = f"http://127.0.0.1:{port}"
        wait_http(url + "/actuator/health", app)
        requests = exercise(url, sample, customized=True, changed=changed)
        default_requests = (exercise(url, sample, customized=True, changed=True, omit_nickname=True)
                            if changed else None)
    result = {"command": "mvn -B -ntp clean verify", "tests": counts, "requests": requests,
            "jar_sha256": sha(jars[0]),
            "test_reports": {p.name: sha(p) for p in sorted(reports.iterdir())}}
    if changed:
        result["omitted_nickname_requests"] = default_requests
    return result


def execute(engine, root):
    require(not sys.flags.optimize, "Run with unoptimized Python")
    require(sys.version_info[:2] == (3, 11), "Reference proof requires Python 3.11")
    engine = engine.resolve()
    root = root.resolve()
    require(not root.is_relative_to(STUDIO) and not root.is_relative_to(engine),
            "Proof output must be outside both repositories")
    require(not root.exists(), "Use a new, nonexistent proof directory")
    studio_sha = source_identity(STUDIO)
    require(source_identity(engine) == ENGINE_PIN, "Use the documented frozen merged Engine revision")
    require((engine / ".venv/bin/python").is_file(), "Install the frozen Engine's isolated .venv first")
    for tool in ("mvn", "java"):
        require(shutil.which(tool), f"Missing prerequisite: {tool}")
    maven = command(["mvn", "--version"])
    java = command(["java", "-version"])
    require("Java version: 17." in maven and 'version "17.' in java,
            "Select JDK 17 for both Java and Maven")
    root.mkdir(parents=True)
    # Isolated state/cache; no inherited Engine/KS/Studio feature overrides.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("EDGEFORGE_", "STUDIO_", "KS_", "SPRING_"))}
    env.update(EDGEFORGE_STUDIO_STATE_DIR=str(root / "state"),
               EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED="true",
               EDGEFORGE_STUDIO_SHARED_MODE="false", SERVER_ADDRESS="127.0.0.1",
               MAVEN_OPTS=f"-Dmaven.repo.local={root / 'maven-cache'}")
    receipt = {"candidate": "EF-V5-STUDIO-S8-NEWCOMER-JOURNEY", "revision": 1,
               "status": "incomplete", "started_at": datetime.now(timezone.utc).isoformat(),
               "studio_sha": studio_sha, "engine_sha": ENGINE_PIN, "source_clean": True,
               "python": sys.version.split()[0], "platform": platform.platform(),
               "java": java, "maven": maven.splitlines()[0], "sample": SAMPLE,
               "sample_sha256": sha(STUDIO / SAMPLE), "profile": PROFILE,
               "flags": {"regen_preview": True, "shared_mode": False, "knowledge_assist": False},
               "observation": "HTTP route automation plus explicit terminal developer/Maven/Java steps; not browser observation",
               "steps": []}
    # Do not publish private local paths or logs. This receipt contains only bounded synthetic results.
    def save_receipt():
        (root / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    save_receipt()
    port = free_port()
    try:
        with process([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                      "--port", str(port)], cwd=STUDIO, env=env, log=root / "studio.log") as studio:
            url = f"http://127.0.0.1:{port}"
            with httpx.Client(base_url=url, timeout=900, trust_env=False) as client:
                page = wait_http(url + "/", studio, client)
                token = re.search(r'name="edgeforge-csrf-token"\s+content="([^"]+)"', page.text)
                require(token is not None, "Studio did not render CSRF metadata")
                csrf = html.unescape(token.group(1))
                client.headers["x-edgeforge-csrf-token"] = csrf

                def post(route, *, json_body=None, data=None, files=None, expect_json=True):
                    if data is not None or files is not None:
                        data = {**(data or {}), "_edgeforge_csrf_token": csrf}
                    response = client.post(route, json=json_body, data=data, files=files)
                    require(response.status_code in (200, 303), f"{route}: {response.status_code}: {response.text[:1000]}")
                    receipt["steps"].append({"method": "POST", "route": route, "status": response.status_code})
                    if not expect_json:
                        return response
                    return require_success(route, response.json())

                try:
                    sample_path = STUDIO / SAMPLE
                    post("/project/open", files={"project_file": (sample_path.name, sample_path.read_bytes(), "application/json")}, expect_json=False)
                    # Read-only discovery of the one session workspace in this clean local server.
                    workspaces = list((root / "state/workspaces").iterdir())
                    require(len(workspaces) == 1, "Proof requires exactly one isolated local session")
                    workspace = workspaces[0]
                    post("/", data={"app_name": "Synthetic Account Servicing", "bounded_context": "account-servicing",
                        "app_archetype": "crud", "target_profile": PROFILE,
                        "output_path": str(workspace / "output"), "appbuilder_repo_path": str(engine)}, expect_json=False)
                    post("/entities/save", json_body={"entities": ["Account"], "operations": ["createAccount"],
                        "entity_op_map": {"Account": ["createAccount"]}})
                    for route in ("/upstream", "/entities", "/handoffs", "/downstream", "/rules", "/review", "/export"):
                        response = client.get(route)
                        require(response.status_code == 200, f"Review page failed: {route}")
                        receipt["steps"].append({"method": "GET", "route": route, "status": 200})
                    exported = post("/export/write")
                    require(exported["warnings"] == [], "Unexpected export warnings")
                    post("/export/validate")
                    generated = post("/export/generate")
                    require(generated["warnings"] == [], "Unexpected generation warnings")
                    snapshot = post("/project/save")
                    require(snapshot["capabilities"]["knowledge_assist_enabled"] is False and not snapshot["ks_active"], "KA must remain OFF")
                    receipt["project_schema"] = snapshot["studio_project_schema_version"]
                    receipt["manifest_schema"] = "2.0"
                    require('schema_version: "2.0"' in (Path(exported["output_dir"]) / "app-definition.yaml").read_text()
                            or "schema_version: '2.0'" in (Path(exported["output_dir"]) / "app-definition.yaml").read_text(), "Manifest dialect changed")
                    original = Path(generated["output_dir"])
                    built = post("/export/build")
                    require(Path(built["generated_app_path"]).resolve() == original.resolve(), "Build path differs from generation output")
                    started = post("/export/run")
                    app_url = f"http://127.0.0.1:{started['port']}"
                    wait_http(app_url + "/actuator/health", studio)
                    iface = snapshot["upstream_interfaces"][0]
                    sample = iface["operations"][0]["request_sample_content"]
                    receipt["studio_build_run"] = {"command": built["command"], "tests_skipped_by_build_button": True,
                        "requests": exercise(app_url, sample, customized=False, changed=False)}
                    post("/export/stop")

                    managed = managed_package(snapshot, workspace)
                    customize(managed / SERVICE)
                    developer_bytes = (managed / SERVICE).read_bytes()
                    base_before = sha(managed / BASE)
                    receipt["before_regeneration"] = verify_and_run(managed, root, "before", env, sample, changed=False)

                    spec = json.loads(snapshot["raw_spec_content"])
                    spec["components"]["schemas"]["Account"]["properties"]["nickname"] = {"type": "string", "maxLength": 40, "default": "UNNAMED"}
                    spec_text = json.dumps(spec, indent=2) + "\n"
                    (root / "account-with-nickname.json").write_text(spec_text)
                    post("/upstream/ingest-file", files={"spec_file": ("account-api-spec.json", spec_text, "application/json")})
                    post("/entities/save", json_body={"entities": ["Account"], "operations": ["createAccount"],
                        "entity_op_map": {"Account": ["createAccount"]}})
                    operation = iface["operations"][0]
                    for key in ("request_sample_content", "response_sample_content"):
                        value = json.loads(operation[key])
                        value["nickname"] = "SYNTHETIC-NICKNAME"
                        operation[key] = json.dumps(value)
                    post("/mappings/upstream/samples/save", json_body={"interface_name": iface["name"], "operations": [operation]})
                    mapping = iface["operation_mappings"][0]
                    for key in ("request_mappings", "response_mappings"):
                        mapping[key].append({"source": "nickname", "target": "Account.nickname"})
                    post("/mappings/upstream/save", json_body={"interface_name": iface["name"], "operation_mappings": [mapping]})
                    current = post("/project/save")
                    item = current["entity_rules"][0]
                    item["rules"].append({"field": "nickname", "type": "default", "value": "UNNAMED"})
                    post("/rules/save-one", json_body={"original_name": "Account", "item": item,
                        "source_of_truth_version": str(current["project_revision"])})
                    require(post("/export/write")["warnings"] == [], "Changed export produced warnings")
                    preview = get_preview(client, receipt["steps"])
                    (root / "preview.html").write_text(preview.text)
                    approved = plan_hash(preview.text)
                    require("regen-additive" in preview.text and "regen-unsafe" not in preview.text and "regen-destructive" not in preview.text,
                            "Optional/defaulted field is not a purely additive plan")
                    # Real negative control: developer-file drift invalidates actual approval.
                    (managed / SERVICE).write_bytes(developer_bytes + b"\n// S8 drift control\n")
                    refused = post("/regen/apply", data={"approved_plan_hash": approved}, expect_json=False)
                    require("The Change Plan changed or is no longer ready." in refused.text, "Stale approval was not refused")
                    require(sha(managed / BASE) == base_before, "Refused apply mutated generated code")
                    (managed / SERVICE).write_bytes(developer_bytes)
                    preview = get_preview(client, receipt["steps"])
                    approved = plan_hash(preview.text)
                    applied = post("/regen/apply", data={"approved_plan_hash": approved}, expect_json=False)
                    (root / "applied.html").write_text(applied.text)
                    require("Additive Change Plan applied and managed baseline refreshed." in applied.text, "Apply did not succeed")
                    updated = post("/project/save")
                    new_managed = managed_package(updated, workspace)
                    assert_preserved(developer_bytes, new_managed / SERVICE)
                    require(sha(new_managed / BASE) != base_before, "Generated base did not refresh")
                    migrations = sorted((new_managed / "src/main/resources/db/migration").glob("*nickname*.sql"))
                    require(len(migrations) == 1 and "UNNAMED" in migrations[0].read_text(), "Missing defaulted nickname migration")
                    receipt["preservation"] = {"path": SERVICE, "before_sha256": hashlib.sha256(developer_bytes).hexdigest(),
                        "after_sha256": sha(new_managed / SERVICE), "generated_base_changed": True,
                        "stale_approval_refused": True, "migration": migrations[0].name,
                        "migration_sha256": sha(migrations[0])}
                    receipt["after_regeneration"] = verify_and_run(new_managed, root, "after", env, sample, changed=True)
                    require(updated["capabilities"]["knowledge_assist_enabled"] is False and not updated["ks_active"], "KA changed")
                    receipt["limitations"] = [
                        "Local macOS ARM64, Python 3.11, Java 17/H2 reference only; profile intentionally selected in Step 1.",
                        "HTTP automation is not browser, keyboard, or native accessibility observation; A11y-01 remains open.",
                        "Step 8 skips tests and still targets the original output; terminal verification uses the managed regenerated copy.",
                        "Fresh H2 memory database per process; no production data migration or persistent-database continuity claim.",
                        "Create and read-by-ID only; filtered lists, computed reads, EOD delivery and arbitrary generated-file edits are not proven.",
                        "Final selected Studio/Engine release pair requires applicability review and relevant journey re-proof."]
                finally:
                    stopped = client.post("/export/stop")
                    stopped.raise_for_status()
                    require_success("/export/stop", stopped.json())
        # Cleanup is part of the proof: only a fully exited run may report pass.
        receipt["status"] = "pass"
    finally:
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        save_receipt()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-repo", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    execute(args.engine_repo, args.work_dir)
    print(f"PASS: {args.work_dir / 'receipt.json'}")


if __name__ == "__main__":
    main()
