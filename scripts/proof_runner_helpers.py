"""Shared helpers for Studio proof-runner scripts."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess as sp
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from app.integrations.appbuilder_integration import run_generate, validate_manifest


def find_java17_home() -> str | None:
    candidates = [
        "/opt/homebrew/opt/openjdk@17",
        "/usr/local/opt/openjdk@17",
        "/opt/homebrew/Cellar/openjdk@17",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if (path / "bin" / "java").exists():
            return str(path)
        if path.is_dir():
            for child in sorted(path.iterdir(), reverse=True):
                if (child / "bin" / "java").exists():
                    return str(child)
    return None


def discover_collection_path(generated_dir: Path, *, excluded: Iterable[str] | None = None) -> str:
    excluded_names = set(excluded or {"DemoController.java", "BatchTriggerController.java"})
    controller_files = sorted(generated_dir.rglob("*Controller.java"))
    controller_files = [f for f in controller_files if f.name not in excluded_names]
    if len(controller_files) != 1:
        raise RuntimeError(f"Expected exactly one entity controller, found {[f.name for f in controller_files]}")
    controller_text = controller_files[0].read_text()
    match = re.search(r'@RequestMapping\((?:(?:value|path)\s*=\s*)?"([^"]+)"', controller_text)
    if not match:
        raise RuntimeError(f"Could not find @RequestMapping path in {controller_files[0]}")
    return match.group(1)


def print_report(report: dict | None, report_obj=None) -> None:
    if report is not None:
        print(f"         Report: {report}")
        return
    if report_obj is not None:
        summary = report_obj.summary()
        print(f"         Completeness: {summary}")
        blockers = [item.message for item in report_obj.manual()]
        if blockers:
            print("         BLOCKERS:")
            for blocker in blockers:
                print(f"           - {blocker}")


def json_request(url: str, *, method: str = "GET", payload: dict | None = None, timeout: int = 10) -> tuple[int, str]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read().decode()


def assert_json_array(body: str, label: str) -> list[object]:
    parsed = json.loads(body)
    if not isinstance(parsed, list):
        raise RuntimeError(f"{label} returned unexpected JSON body (expected array): {body}")
    return parsed


def print_manifest_summary(manifest: dict) -> None:
    print(f"         schema_version: {manifest.get('schema_version')}")
    print(f"         app_archetype: {manifest.get('app_archetype')}")
    if "app_name" in manifest:
        print(f"         app_name: {manifest.get('app_name')}")
    if "bounded_context" in manifest:
        print(f"         bounded_context: {manifest.get('bounded_context')}")
    if "upstream_interfaces" in manifest:
        print(f"         upstream_interfaces: {[i.get('name') for i in manifest.get('upstream_interfaces', [])]}")
    if "downstream_interfaces" in manifest:
        print(f"         downstream_interfaces: {[i.get('name') for i in manifest.get('downstream_interfaces', [])]}")
    if "data_handoffs" in manifest:
        print(f"         data_handoffs: {[i.get('name') for i in manifest.get('data_handoffs', [])]}")


def assert_expected_files(base_dir: Path, expected_paths: Iterable[Path], *, label: str) -> None:
    for path in expected_paths:
        assert path.exists(), f"Missing {label}: {path}"
        print(f"         PASS — {label} present: {path.relative_to(base_dir)}")


def assert_expected_generated_filenames(generated_dir: Path, filenames: Iterable[str]) -> None:
    for filename in filenames:
        matches = list(generated_dir.rglob(filename))
        assert matches, f"Missing generated artifact: {filename}"
        print(f"         PASS — generated artifact present: {matches[0].relative_to(generated_dir)}")


def validate_manifest_or_exit(manifest_path: Path, engine_repo: str):
    result = validate_manifest(manifest_path, engine_repo)
    print(f"         Command: {' '.join(str(c) for c in result.command)}")
    print(f"         Output:  {result.combined_output}")
    print(f"         Success: {result.success} (exit={result.returncode}, {result.duration_seconds:.3f}s)")
    if not result.success:
        print("\nVALIDATION FAILED — stopping proof run.")
        sys.exit(1)
    print("         PASS — manifest accepted by Engine")
    return result


def generate_app_or_exit(manifest_path: Path, generated_dir: Path, engine_repo: str) -> tuple[object, list[Path], list[Path]]:
    result = run_generate(str(manifest_path), str(generated_dir), engine_repo)
    print(f"         Command: {' '.join(str(c) for c in result.command)}")
    print(f"         Output:\n{result.combined_output}")
    print(f"         Success: {result.success} (exit={result.returncode}, {result.duration_seconds:.3f}s)")
    if not result.success:
        print("\nGENERATION FAILED — stopping proof run.")
        sys.exit(1)
    java_files = list(generated_dir.rglob("*.java"))
    all_files = [path for path in generated_dir.rglob("*") if path.is_file()]
    print(f"         PASS — {len(all_files)} files generated, {len(java_files)} Java source files")
    return result, java_files, all_files


def run_maven_build_or_exit(generated_dir: Path, *, java17_home: str | None = None, timeout: int = 300) -> sp.CompletedProcess[str]:
    mvn_cmd = shutil.which("mvn") or "mvn"
    build_env = os.environ.copy()
    if java17_home:
        build_env["JAVA_HOME"] = java17_home
        print(f"         JAVA_HOME: {java17_home}")
    else:
        print("         JAVA_HOME: (system default — ensure Java 17+ is on PATH)")

    build_proc = sp.run(
        [mvn_cmd, "clean", "package", "-DskipTests", "--batch-mode"],
        cwd=str(generated_dir),
        env=build_env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    build_output = (build_proc.stdout + build_proc.stderr).strip()
    last_lines = "\n".join(build_output.splitlines()[-20:])
    print(f"         Last 20 lines:\n{last_lines}")
    print(f"         Return code: {build_proc.returncode}")
    if build_proc.returncode != 0:
        print("\nMAVEN BUILD FAILED — stopping proof run.")
        sys.exit(1)
    print("         PASS — BUILD SUCCESS")
    return build_proc


def resolve_generated_jar(generated_dir: Path, preferred_name: str) -> Path:
    jar_path = generated_dir / "target" / preferred_name
    if jar_path.exists():
        return jar_path
    target_jars = [
        path for path in (generated_dir / "target").glob("*.jar")
        if "sources" not in path.name and "original" not in path.name
    ]
    return target_jars[0] if target_jars else jar_path


@dataclass
class RunningApp:
    process: sp.Popen[str]
    startup_log: IO[str]
    startup_log_path: Path
    elapsed_seconds: float
    health_body: str

    def stop(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except sp.TimeoutExpired:
            self.process.kill()
        self.startup_log.close()


def start_generated_app_or_exit(
    generated_dir: Path,
    *,
    jar_path: Path,
    app_port: int,
    java17_home: str | None = None,
    timeout_seconds: int = 30,
) -> RunningApp:
    print(f"          JAR: {jar_path}")
    java_bin = str(Path(java17_home) / "bin" / "java") if java17_home else "java"
    startup_log_path = generated_dir / "startup.log"
    startup_log = startup_log_path.open("w+")
    app_proc = sp.Popen(
        [java_bin, "-jar", str(jar_path), f"--server.port={app_port}"],
        cwd=str(generated_dir),
        stdout=startup_log,
        stderr=sp.STDOUT,
        text=True,
    )

    health_url = f"http://localhost:{app_port}/actuator/health"
    started = False
    health_body = ""
    start_t = time.monotonic()
    for _ in range(timeout_seconds):
        time.sleep(1)
        try:
            status, health_body = json_request(health_url, timeout=2)
            if status == 200:
                started = True
                print(f"          Health response: {health_body}")
                break
        except (urllib.error.URLError, ConnectionRefusedError):
            pass

    elapsed = round(time.monotonic() - start_t, 1)
    if not started:
        app_proc.kill()
        app_proc.wait(timeout=5)
        startup_log.flush()
        startup_log.seek(0)
        app_out = startup_log.read()
        print(f"          Startup log path: {startup_log_path}")
        print(f"          App output (first 4000 chars):\n{(app_out or '')[:4000]}")
        startup_log.close()
        print("\nAPP DID NOT START within 30s — stopping proof run.")
        sys.exit(1)
    print(f"          PASS — app is UP (started in ~{elapsed}s)")
    return RunningApp(
        process=app_proc,
        startup_log=startup_log,
        startup_log_path=startup_log_path,
        elapsed_seconds=elapsed,
        health_body=health_body,
    )
