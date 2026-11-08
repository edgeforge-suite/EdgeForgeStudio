"""Fast failure controls for the opt-in real S8 journey, not substitutes for it."""

import json
from pathlib import Path

import httpx
import pytest

from scripts import newcomer_journey as journey
from scripts.maven_image_build_run_proof import verified_test_totals


def test_customization_uses_declared_developer_hook(tmp_path):
    path = tmp_path / "AccountService.java"
    path.write_text("// EdgeForge-ownership: developer\n"
                    "        // Add pre-create business logic here.\n")
    journey.customize(path)
    assert f'account.setCustomerId("{journey.HOOK_VALUE}")' in path.read_text()
    before = path.read_bytes()
    journey.assert_preserved(before, path)
    path.write_bytes(before + b"changed")
    with pytest.raises(RuntimeError, match="changed during regeneration"):
        journey.assert_preserved(before, path)


@pytest.mark.parametrize("source", [
    "// EdgeForge-ownership: generated\n        // Add pre-create business logic here.",
    "// EdgeForge-ownership: developer\nnew scaffold",
    "// EdgeForge-ownership: developer\n" + "        // Add pre-create business logic here." * 2,
])
def test_customization_refuses_wrong_ownership_or_changed_seam(tmp_path, source):
    path = tmp_path / "service.java"
    path.write_text(source)
    with pytest.raises(RuntimeError):
        journey.customize(path)
    assert path.read_text() == source


@pytest.mark.parametrize("page", ["", "Engine error", "Unsafe change, apply disabled"])
def test_unapprovable_preview_cannot_pass(page):
    with pytest.raises(RuntimeError, match="no approvable plan"):
        journey.plan_hash(page)


def test_approval_uses_rendered_hash_without_inventing_one():
    assert journey.plan_hash('<input name="approved_plan_hash" value="sha256:123">') == "sha256:123"


def test_both_preview_reads_are_recorded_before_approval():
    steps = []
    with httpx.Client(base_url="http://studio.test", transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text='<input name="approved_plan_hash" value="actual">'))) as client:
        for _ in range(2):
            assert journey.plan_hash(journey.get_preview(client, steps).text) == "actual"
    assert steps == [{"method": "GET", "route": "/regen/preview", "status": 200}] * 2


def test_failed_preview_cannot_supply_an_approval():
    steps = []
    with httpx.Client(base_url="http://studio.test", transport=httpx.MockTransport(
            lambda request: httpx.Response(500, text='<input name="approved_plan_hash" value="stale">'))) as client:
        with pytest.raises(RuntimeError, match="preview failed"):
            journey.get_preview(client, steps)
    assert steps == [{"method": "GET", "route": "/regen/preview", "status": 500}]


@pytest.mark.parametrize("payload", [{}, {"error": "failed"}, {"ok": False}, [], None])
def test_actions_must_explicitly_succeed(payload):
    with pytest.raises(RuntimeError):
        journey.require_success("/export/validate", payload)


def test_saved_project_is_the_explicit_non_envelope_exception():
    project = {"studio_project_schema_version": "1.4"}
    assert journey.require_success("/project/save", project) == project
    assert journey.require_success("/export/stop", {"ok": True}) == {"ok": True}


@pytest.mark.parametrize("ref", [None, "", "../outside", "/outside"])
def test_missing_or_escaping_managed_package_refused(tmp_path, ref):
    with pytest.raises(RuntimeError):
        journey.managed_package({"last_generated_package_ref": ref}, tmp_path)


@pytest.mark.parametrize("counts", [(0, 0, 0, 0), (1, 0, 0, 1), (2, 1, 0, 0), (2, 0, 1, 0), (2, 0, 0, 1)])
def test_missing_executed_tests_or_any_skip_is_not_proof(tmp_path, counts):
    reports = tmp_path / "target/surefire-reports"
    reports.mkdir(parents=True)
    tests, failures, errors, skipped = counts
    (reports / "TEST-context.xml").write_text(
        f'<testsuite tests="{tests}" failures="{failures}" errors="{errors}" skipped="{skipped}"/>'
    )
    with pytest.raises(RuntimeError, match="executed tests"):
        verified_test_totals(tmp_path)


def test_executed_test_counts_retained(tmp_path):
    reports = tmp_path / "target/surefire-reports"
    reports.mkdir(parents=True)
    (reports / "TEST-context.xml").write_text('<testsuite tests="1" failures="0" errors="0" skipped="0"/>')
    assert verified_test_totals(tmp_path) == {"tests": 1, "failures": 0, "errors": 0, "skipped": 0}


@pytest.mark.parametrize("wrong", ["create_status", "hook", "nickname", "persisted", "missing_id"])
def test_wrong_application_behavior_fails_even_with_healthy_server(monkeypatch, wrong):
    real_client = httpx.Client
    sample = json.dumps({"accountId": "ACCT-0001", "customerId": "CUST-0001", "balance": 1250.0})
    expected = {"accountId": "ACCT-S8-001", "customerId": journey.HOOK_VALUE,
                "balance": 1250.0, "nickname": "SYNTHETIC-NICKNAME"}

    def respond(request):
        value = dict(expected)
        if wrong == "hook":
            value["customerId"] = "CUST-INPUT"
        if wrong == "nickname":
            value.pop("nickname")
        if request.method == "POST":
            return httpx.Response(200 if wrong == "create_status" else 201, json=value)
        if request.url.path.endswith("ACCT-MISSING"):
            return httpx.Response(200 if wrong == "missing_id" else 404, json={})
        if wrong == "persisted":
            value["balance"] = 0
        return httpx.Response(200, json=value)

    monkeypatch.setattr(journey.httpx, "Client", lambda **kw: real_client(
        **kw, transport=httpx.MockTransport(respond)))
    with pytest.raises(RuntimeError):
        journey.exercise("http://app.test", sample, customized=True, changed=True)


def test_proof_does_not_use_session_injection_or_direct_engine_cli():
    source = Path(journey.__file__).read_text()
    for forbidden in ("get_session()", "save_session(", "restore_session(", "appbuilder.cli", "TestClient("):
        assert forbidden not in source
    assert 'receipt["status"] = "pass"' in source
    assert '"status": "incomplete"' in source


@pytest.mark.parametrize("wrong", [None, "create_default", "read_default", "hook", "read_status"])
def test_omitted_field_requires_persisted_default_and_preserved_hook(monkeypatch, wrong):
    real_client = httpx.Client
    sample = json.dumps({"nickname": "MUST-BE-REMOVED", "balance": 1250.0})
    sent = []
    expected = {"accountId": "ACCT-S8-DEFAULT", "customerId": journey.HOOK_VALUE,
                "balance": 1250.0, "nickname": "UNNAMED"}

    def respond(request):
        if request.url.path.endswith("ACCT-MISSING"):
            return httpx.Response(404)
        value = dict(expected)
        if wrong == "hook":
            value["customerId"] = "CUST-INPUT"
        if request.method == "POST":
            sent.append(json.loads(request.content))
            assert "nickname" not in sent[-1]
            if wrong == "create_default":
                value.pop("nickname")
            return httpx.Response(201, json=value)
        assert request.url.path == "/accounts/ACCT-S8-DEFAULT"
        if wrong == "read_default":
            value["nickname"] = None
        return httpx.Response(404 if wrong == "read_status" else 200, json=value)

    monkeypatch.setattr(journey.httpx, "Client", lambda **kw: real_client(
        **kw, transport=httpx.MockTransport(respond)))
    if wrong:
        with pytest.raises(RuntimeError):
            journey.exercise("http://app.test", sample, customized=True, changed=True, omit_nickname=True)
    else:
        result = journey.exercise("http://app.test", sample, customized=True, changed=True, omit_nickname=True)
        assert result["request"] == sent[0]
        assert result["create_response"] == result["read_response"] == expected


def test_default_proof_requires_changed_application():
    with pytest.raises(RuntimeError, match="regenerated application"):
        journey.exercise("http://app.test", "{}", customized=True, changed=False, omit_nickname=True)
