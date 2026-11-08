"""A passing image proof requires Maven test execution, not just packaging."""

import json
from pathlib import Path
from types import SimpleNamespace
from xml.etree.ElementTree import Element, ElementTree

import pytest

from scripts import maven_image_build_run_proof as proof


@pytest.fixture
def controlled_runner(tmp_path, monkeypatch):
    project_path = tmp_path / "synthetic.edgeforge-project.json"
    project_path.write_text(json.dumps({
        "capabilities": {"knowledge_assist_enabled": False}, "ks_active": False,
    }))
    app_dir = tmp_path / "generated-app"
    reports = app_dir / "target" / "surefire-reports"
    reports.mkdir(parents=True)
    jar = app_dir / "target" / "synthetic.jar"
    jar.write_bytes(b"synthetic packaging proof")
    home = tmp_path / "home"
    home.mkdir()
    routes = []
    commands = []

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, route, **_kwargs):
            routes.append(route)
            payload = {
                "ok": True, "warnings": [], "output_dir": str(app_dir),
                "command": "mvn package", "jar_path": str(jar),
            }
            return SimpleNamespace(
                status_code=303 if route == "/project/open" else 200,
                text="synthetic response", json=lambda: payload,
            )

    def verify(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(proof, "TestClient", lambda _app: Client())
    monkeypatch.setattr(proof.os, "getuid", lambda: 1000)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(proof.subprocess, "check_output", lambda *_args, **_kwargs: "synthetic Maven")
    monkeypatch.setattr(proof.subprocess, "run", verify)
    return SimpleNamespace(
        project=project_path, reports=reports, output=tmp_path / "proof",
        routes=routes, commands=commands,
    )


def _reports(runner, counts):
    for index, (tests, failures, errors, skipped) in enumerate(counts):
        attributes = dict(zip(("tests", "failures", "errors", "skipped"),
                              map(str, (tests, failures, errors, skipped)), strict=True))
        ElementTree(Element("testsuite", attributes)).write(runner.reports / f"TEST-{index}.xml")


@pytest.mark.parametrize("counts", [
    [(1, 0, 0, 1)],  # The independently reproduced all-skipped false pass.
    [(2, 0, 0, 1)],
    [(1, 0, 0, 0), (1, 0, 0, 1)],
    [(0, 0, 0, 0)],
    [],
    [(1, 1, 0, 0)],
    [(1, 0, 1, 0)],
    [(1, 0, 0, -1)],
])
def test_execute_rejects_unproven_maven_tests(controlled_runner, counts):
    runner = controlled_runner
    _reports(runner, counts)
    with pytest.raises(RuntimeError, match="Maven"):
        proof.execute(runner.project, "synthetic", runner.output, run=False, jobless=False)
    assert runner.commands == [["mvn", "-B", "-ntp", "clean", "verify"]]
    assert runner.routes == ["/project/open", "/export/write", "/export/generate"]
    assert not (runner.output / "result.json").exists()


@pytest.mark.parametrize("counts, expected", [
    ([(1, 0, 0, 0)], 1),
    ([(1, 0, 0, 0), (2, 0, 0, 0)], 3),
])
def test_execute_passes_only_with_executed_zero_skip_tests(controlled_runner, counts, expected):
    runner = controlled_runner
    _reports(runner, counts)
    result = proof.execute(runner.project, "synthetic", runner.output, run=False, jobless=False)
    assert result["result"] == "pass"
    assert result["maven_tests"] == {"tests": expected, "failures": 0, "errors": 0, "skipped": 0}
    assert result["python_optimization"] == 0
    assert len(result["maven_test_reports"]) == len(counts)
    for report in runner.reports.glob("TEST-*.xml"):
        assert (runner.output / "verified-test-reports" / report.name).read_bytes() == report.read_bytes()
    assert runner.routes[-1] == "/export/build"
    assert json.loads((runner.output / "result.json").read_text()) == result


def test_execute_rejects_incomplete_report(controlled_runner):
    runner = controlled_runner
    ElementTree(Element("testsuite", {"tests": "1", "failures": "0", "errors": "0"})).write(
        runner.reports / "TEST-incomplete.xml"
    )
    with pytest.raises(KeyError, match="skipped"):
        proof.execute(runner.project, "synthetic", runner.output, run=False, jobless=False)
    assert "/export/build" not in runner.routes
    assert not (runner.output / "result.json").exists()


def test_execute_retains_reports_before_packaging_cleans_them(controlled_runner, monkeypatch):
    runner = controlled_runner
    _reports(runner, [(1, 0, 0, 0)])
    original_client = proof.TestClient

    def client(app):
        instance = original_client(app)
        original_post = instance.post

        def post(route, **kwargs):
            if route == "/export/build":
                for report in runner.reports.glob("TEST-*.xml"):
                    report.unlink()
            return original_post(route, **kwargs)

        instance.post = post
        return instance

    monkeypatch.setattr(proof, "TestClient", client)
    result = proof.execute(runner.project, "synthetic", runner.output, run=False, jobless=False)
    assert list(runner.reports.glob("TEST-*.xml")) == []
    retained = runner.output / "verified-test-reports" / "TEST-0.xml"
    assert retained.is_file()
    assert result["maven_test_reports"][0]["name"] == retained.name
    assert len(result["maven_test_reports"][0]["sha256"]) == 64


@pytest.mark.parametrize("optimization", [1, 2, 7])
def test_execute_refuses_optimization_before_proof_work(controlled_runner, monkeypatch, optimization):
    runner = controlled_runner
    monkeypatch.setattr(proof, "sys", SimpleNamespace(flags=SimpleNamespace(optimize=optimization)))
    with pytest.raises(RuntimeError, match="unoptimized Python"):
        proof.execute(runner.project, "synthetic", runner.output, run=False, jobless=False)
    assert runner.commands == []
    assert runner.routes == []
    assert not runner.output.exists()
