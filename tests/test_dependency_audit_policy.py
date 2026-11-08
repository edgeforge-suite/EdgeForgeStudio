from __future__ import annotations

import csv
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _normalized_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirements(path: Path) -> dict[str, str]:
    requirements: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        name = _normalized_name(re.split(r"[<>=!~;\[ ]", line, maxsplit=1)[0])
        requirements[name] = line
    return requirements


def test_dependency_versions_match_their_declared_roles() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime = _requirements(ROOT / "requirements.txt")
    constraints = _requirements(ROOT / "constraints.txt")
    project_runtime = {
        _normalized_name(re.split(r"[<>=!~;\[ ]", requirement, maxsplit=1)[0]): requirement
        for requirement in project["project"]["dependencies"]
    }
    project_dev = project["project"]["optional-dependencies"]["dev"]

    assert (
        project_runtime["starlette"]
        == runtime["starlette"]
        == constraints["starlette"]
        == "starlette==1.3.1"
    )
    assert constraints["cryptography"] == "cryptography==50.0.0"
    assert constraints["anyio"] == "anyio==4.14.2"
    assert constraints["mcp"] == "mcp==1.30.0"
    assert constraints["fastmcp"] == "fastmcp==3.4.10"
    assert constraints["fastmcp-slim"] == "fastmcp-slim==3.4.10"
    assert constraints["opentelemetry-api"] == "opentelemetry-api==1.45.1"
    assert constraints["authlib"] == "Authlib==1.9.1"
    assert constraints["dnspython"] == "dnspython==2.9.0"
    assert constraints["joserfc"] == "joserfc==1.7.6"
    assert project_runtime["fastmcp"] == "fastmcp==3.4.10"
    assert runtime["fastmcp"].split(";", 1)[0] == "fastmcp==3.4.10"
    assert "mcp" not in runtime
    assert "mcp" not in project_runtime
    assert constraints["pip"] == "pip==26.2.1"
    assert constraints["pillow"] == "pillow==13.0.0"
    assert constraints["setuptools"] == "setuptools==84.1.0"
    assert constraints["wheel"] == "wheel==0.48.0"
    assert project["build-system"]["requires"] == [
        "setuptools==84.1.0",
        "wheel==0.48.0",
        "packaging==26.2",
    ]
    assert "cryptography" not in runtime
    assert constraints["httpcore2"] == "httpcore2==2.12.0"
    assert (
        runtime["httpx2"]
        == constraints["httpx2"]
        == "httpx2==2.12.0"
    )
    assert "httpx2==2.12.0" in project_dev
    assert "httpx2" not in project_runtime
    assert "pillow" not in runtime
    assert "setuptools" not in runtime


def test_generated_evidence_matches_constrained_security_and_toolchain_versions() -> None:
    sbom = json.loads(
        (ROOT / "docs/handover-evidence/sbom.cdx.json").read_text(encoding="utf-8")
    )
    components = {
        component["name"].lower(): component["version"]
        for component in sbom["components"]
    }
    with (ROOT / "docs/handover-evidence/dependency-licenses-transitive.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        transitive_licensed = {
            _normalized_name(row["Package"]): row["Version"] for row in csv.DictReader(stream)
        }
    with (ROOT / "docs/handover-evidence/dependency-licenses.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        declared_licensed = {
            _normalized_name(row["Package"]): row for row in csv.DictReader(stream)
        }
    audit = json.loads(
        (ROOT / "docs/handover-evidence/pip-audit.json").read_text(encoding="utf-8")
    )
    audited = {
        _normalized_name(dependency["name"]): dependency["version"]
        for dependency in audit["dependencies"]
    }
    constrained = _requirements(ROOT / "constraints.txt")
    constrained_versions = {
        name: requirement.split("==", 1)[1] for name, requirement in constrained.items()
    }

    evidence_names = {
        "authlib",
        "dnspython",
        "joserfc",
        "anyio",
        "certifi",
        "pillow",
        "mcp",
        "fastmcp",
        "fastmcp-slim",
        "opentelemetry-api",
        "httpcore2",
        "httpx2",
        "packaging",
        "pip",
        "setuptools",
        "wheel",
    }
    expected = {name: constrained_versions[name] for name in evidence_names}
    assert {name: components[name] for name in expected} == expected
    assert {name: transitive_licensed[name] for name in expected} == expected
    assert declared_licensed["httpx2"] == {
        "Package": "httpx2",
        "Declared": "httpx2==2.12.0",
        "Resolved": "2.12.0",
        "License": "BSD-3-Clause",
        "Scope": "test",
    }
    assert audited == constrained_versions


def test_supported_bootstrap_paths_pin_and_verify_the_packaging_toolchain() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/pytest-ci.yml").read_text(encoding="utf-8")

    install = "-m pip install -c constraints.txt pip setuptools wheel"
    verify = "scripts/verify-packaging-toolchain.py"
    assert install in makefile and verify in makefile
    assert install in readme and verify in readme
    assert install in contributing and verify in contributing
    assert install in dockerfile and verify in dockerfile
    assert "python -m venv /tmp/studio-ci" in workflow
    assert install in workflow and verify in workflow


def test_dependency_audit_ci_step_is_blocking_and_keeps_license_scan() -> None:
    workflow = (ROOT / ".github/workflows/pytest-ci.yml").read_text(encoding="utf-8")
    pytest_job_start = workflow.index("  pytest:\n")
    pytest_job_end = workflow.index("\n  ruff:\n", pytest_job_start)
    pytest_job = workflow[pytest_job_start:pytest_job_end]

    marker = "      - name: Run dependency audit and license scan"
    start = workflow.index(marker)
    remainder = workflow[start + len(marker) :]
    boundaries = [
        match.start()
        for match in re.finditer(r"(?m)^  [a-zA-Z0-9_-]+:$|^      - name:", remainder)
    ]
    end = start + len(marker) + min(boundaries) if boundaries else -1
    audit_step = workflow[start:] if end == -1 else workflow[start:end]

    audit_command = (
        "/tmp/studio-audit-tools/bin/pip-audit -r constraints.txt "
        "--no-deps --disable-pip "
        "--progress-spinner off --strict"
    )
    step_lines = {line.strip() for line in audit_step.splitlines()}
    assert audit_command in step_lines
    assert "continue-on-error:" not in pytest_job
    assert "set +e" not in audit_step
    assert "audit_status" not in audit_step
    assert "::warning::pip-audit" not in audit_step
    assert f"{audit_command} ||" not in audit_step

    license_command = "/tmp/studio-audit-tools/bin/pip-licenses"
    assert license_command in audit_step
    assert audit_step.index(audit_command) < audit_step.index(license_command)
