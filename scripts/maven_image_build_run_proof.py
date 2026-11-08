"""Opt-in synthetic Build & Run proof inside an already assessed Studio image.

Copy this script and a committed sample project into a task-owned container;
never bind-mount source over the image. Outputs belong outside the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def verified_test_totals(app_dir: Path) -> dict[str, int]:
    totals = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
    for report in app_dir.glob("target/surefire-reports/TEST-*.xml"):
        attributes = ET.parse(report).getroot().attrib
        counts = {key: int(attributes[key]) for key in totals}
        if any(count < 0 for count in counts.values()):
            raise RuntimeError(f"Invalid Maven test counts: {counts}")
        for key in totals:
            totals[key] += counts[key]
    # Surefire's tests count includes skipped cases; packaging is not test proof.
    executed = totals["tests"] - totals["skipped"]
    if executed <= 0 or any(totals[key] for key in ("failures", "errors", "skipped")):
        raise RuntimeError(f"Maven proof requires executed tests with zero failures/errors/skips: {totals}")
    return totals


def verify_account_requests(client: TestClient, port: int, sample: str) -> dict:
    """Bounded FS sample proof: create, read persisted fields, and refuse an absent ID."""
    payload = json.loads(sample)
    payload["accountId"] = "ACCT-IMG-01"
    payload["customerId"] = "CUST-IMG-01"
    prefix = f"/export/generated-app/{port}"
    created = client.post(prefix + "/accounts", json=payload)
    if created.status_code != 201 or any(created.json().get(k) != v for k, v in payload.items()):
        raise RuntimeError(f"Account create did not preserve the synthetic fields: {created.status_code}: {created.text}")
    read = client.get(prefix + "/accounts/" + payload["accountId"])
    if read.status_code != 200 or any(read.json().get(k) != v for k, v in payload.items()):
        raise RuntimeError("Account read did not return the persisted synthetic fields")
    missing = client.get(prefix + "/accounts/ACCT-MISSING")
    if missing.status_code != 404:
        raise RuntimeError("Absent account ID did not return 404")
    return {"request": payload, "create_status": created.status_code, "create_response": created.json(),
            "read_status": read.status_code, "read_response": read.json(), "missing_id_status": missing.status_code}


def execute(project_path: Path, profile: str, proof_root: Path, run: bool, jobless: bool,
            exercise_account: bool = False) -> dict:
    if sys.flags.optimize:
        raise RuntimeError("Image proof requires unoptimized Python")
    if os.getuid() == 0:
        raise RuntimeError("Image proof must run as the normal non-root user")
    if exercise_account and not run:
        raise ValueError("Account requests require --run")
    proof_root.mkdir(parents=True, exist_ok=True)
    project = json.loads(project_path.read_text())
    project["target_profile"] = profile
    project["output_path"] = str(proof_root)
    project["appbuilder_repo_path"] = "/opt/EdgeForgeRuntime"
    if jobless:
        # Temporary proof input only: file/staging handoffs require Batch, which
        # the frozen Engine intentionally rejects for its jobless Boot 4.1 preview.
        project["data_handoffs"] = []
        project["downstream_interfaces"] = []
    assert project["capabilities"]["knowledge_assist_enabled"] is False
    assert project["ks_active"] is False
    result = {"profile": profile, "uid": os.getuid(), "ka_enabled": False, "jobless": jobless,
              "python_optimization": sys.flags.optimize}
    result["maven"] = subprocess.check_output(["mvn", "--version"], text=True).strip()
    cache = Path.home() / ".m2"
    cache.mkdir(exist_ok=True)
    (cache / "write-proof").write_text("synthetic cache permission check\n")
    result["cache_writable"] = True

    with TestClient(app) as client:
        def post(route: str) -> dict:
            response = client.post(route)
            payload = response.json()
            (proof_root / (route.rsplit("/", 1)[1] + ".json")).write_text(
                json.dumps(payload, indent=2) + "\n"
            )
            if response.status_code != 200 or payload.get("ok") is not True:
                raise RuntimeError(f"{route} failed: {payload}")
            return payload

        opened = client.post(
            "/project/open", follow_redirects=False,
            files={"project_file": (project_path.name, json.dumps(project), "application/json")},
        )
        assert opened.status_code == 303, opened.text
        exported = post("/export/write")
        assert exported["warnings"] == [], exported
        generated = post("/export/generate")
        assert generated["warnings"] == [], generated
        app_dir = Path(generated["output_dir"])
        # The public Build route deliberately skips tests. Prove tests separately,
        # then use the unchanged public route for its actual packaging behavior.
        with (proof_root / "verify.log").open("w") as log:
            verified = subprocess.run(
                ["mvn", "-B", "-ntp", "clean", "verify"], cwd=app_dir,
                stdout=log, stderr=subprocess.STDOUT, timeout=900,
            )
        if verified.returncode:
            raise RuntimeError(f"Maven verify failed; see {proof_root / 'verify.log'}")
        result["maven_tests"] = verified_test_totals(app_dir)
        # Studio's packaging route runs clean again, deleting Surefire evidence.
        retained_reports = proof_root / "verified-test-reports"
        retained_reports.mkdir(exist_ok=True)
        result["maven_test_reports"] = []
        for report in sorted(app_dir.glob("target/surefire-reports/TEST-*.xml")):
            retained = retained_reports / report.name
            shutil.copy2(report, retained)
            result["maven_test_reports"].append({
                "name": report.name,
                "sha256": hashlib.sha256(retained.read_bytes()).hexdigest(),
            })
        built = post("/export/build")
        result["build_command"] = built["command"]
        result["jar_built"] = Path(built["jar_path"]).is_file()
        result["generated_app"] = str(app_dir)
        if run:
            try:
                started = post("/export/run")
                port = started["port"]
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    response = client.get(f"/export/generated-app/{port}/actuator/health")
                    if response.status_code == 200 and response.json().get("status") == "UP":
                        result["health_http_status"] = response.status_code
                        result["health"] = response.json()
                        break
                    time.sleep(1)
                else:
                    raise RuntimeError("Generated app did not become healthy through Studio's proxy")
                if exercise_account:
                    sample = project["upstream_interfaces"][0]["operations"][0]["request_sample_content"]
                    result["application_requests"] = verify_account_requests(client, port, sample)
            finally:
                post("/export/stop")
        result["result"] = "pass"
    (proof_root / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--proof-root", type=Path, required=True)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--jobless", action="store_true", help="Omit file/staging handoffs in temporary input")
    parser.add_argument("--exercise-account", action="store_true", help="Assert the maintained FS sample's create/read behavior")
    args = parser.parse_args()
    print(json.dumps(execute(args.project, args.profile, args.proof_root, args.run, args.jobless,
                             args.exercise_account), indent=2))


if __name__ == "__main__":
    main()
