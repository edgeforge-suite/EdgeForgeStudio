"""Recipe boundaries are guards, not substitutes for executed image proof."""
import hashlib
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.image_bootstrap_proof import TOOLS, constrained_tools, verify_wheelhouse
from scripts.image_bundle_p_probe import behavior_regressions
from scripts.maven_image_build_run_proof import verify_account_requests

ROOT = Path(__file__).resolve().parents[1]


def test_current_bootstrap_toolchain_uses_exact_constraints():
    selected = constrained_tools(ROOT / "constraints.txt")
    assert selected == {**TOOLS, "setuptools": "84.1.0"}


def test_current_wheelhouse_cannot_be_mistaken_for_historical_pins(tmp_path):
    selected = constrained_tools(ROOT / "constraints.txt")
    hashes = {}
    for name, version in selected.items():
        filename = f"{name}-{version}-py3-none-any.whl"
        (tmp_path / filename).write_bytes(b"synthetic current toolchain wheel")
        hashes[filename] = hashlib.sha256((tmp_path / filename).read_bytes()).hexdigest()
    assert len(verify_wheelhouse(tmp_path, hashes, selected)) == 4
    with pytest.raises(ValueError):
        verify_wheelhouse(tmp_path, hashes)


@pytest.mark.parametrize("content", ["pip>=26\n", "pip==26.2.1\npip==26.2.1\n"])
def test_incomplete_or_duplicate_bootstrap_constraints_fail_closed(tmp_path, content):
    constraints = tmp_path / "constraints.txt"
    constraints.write_text(content)
    with pytest.raises(ValueError):
        constrained_tools(constraints)


def test_behavior_receipt_handles_morsel_cookie_error(monkeypatch):
    import imaplib
    from http.cookies import CookieError, Morsel

    original = Morsel.set

    def hardened_set(self, key, value, coded_value):
        if "\r" in coded_value or "\n" in coded_value:
            raise CookieError("synthetic control-character rejection")
        return original(self, key, value, coded_value)

    def reject_newline(*_args):
        raise ValueError("synthetic IMAP rejection")

    monkeypatch.setattr(Morsel, "set", hardened_set)
    monkeypatch.setattr(imaplib.IMAP4, "_command", reject_newline)
    result = behavior_regressions()
    assert result["morsel_rejects_control_characters"] is True
    assert result["imap_sent_bytes_hex"] == []
    assert result["temporary_directory"]["outside_contents_unchanged"]


def test_image_stages_use_reviewed_multiplatform_index_pins():
    stages = [line.split() for line in (ROOT / "Dockerfile").read_text().splitlines() if line.startswith("FROM ")]
    assert len(stages) == 3
    assert all(re.fullmatch(r".+@sha256:[0-9a-f]{64}", stage[1]) for stage in stages)
    assert stages[0][1] == "eclipse-temurin:21-jdk@sha256:3e3c176ffed168beb42c607be9bc1639b466cf00261a0fb04425562c9d0c5c2b"
    assert stages[1][1] == stages[2][1] == "python:3.13.16-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641"
    # No --platform=amd64 directive: assessment scope must not narrow recipe architectures.
    assert all(not token.startswith("--platform") for stage in stages for token in stage)
    text = (ROOT / "Dockerfile").read_text()
    assert "apt-get upgrade -y --no-install-recommends" in text
    assert "build-essential" in text and "\nUSER appuser\n" in text
    assert "-m pip install -c constraints.txt pip setuptools wheel" in text


@pytest.mark.parametrize("failure", [None, "create-status", "create-field", "read-status", "read-field", "missing-status"])
def test_meaningful_application_probe_rejects_wrong_behavior(failure):
    expected = {"accountId": "ACCT-IMG-01", "customerId": "CUST-IMG-01", "balance": 1250.0}
    calls = []

    def response(status, body):
        return SimpleNamespace(status_code=status, text=str(body), json=lambda: body)

    class Client:
        def post(self, route, json):
            calls.append(route)
            assert json == expected
            return response(200 if failure == "create-status" else 201,
                            {**expected, "balance": 0} if failure == "create-field" else expected)

        def get(self, route):
            calls.append(route)
            if route.endswith("ACCT-MISSING"):
                return response(200 if failure == "missing-status" else 404, {})
            return response(404 if failure == "read-status" else 200,
                            {**expected, "balance": 0} if failure == "read-field" else expected)

    sample = '{"balance": 1250.0}'
    if failure:
        with pytest.raises(RuntimeError):
            verify_account_requests(Client(), 8080, sample)
    else:
        result = verify_account_requests(Client(), 8080, sample)
        assert result["create_response"] == result["read_response"] == expected
        assert result["missing_id_status"] == 404
        assert len(calls) == 3


@pytest.mark.parametrize("mutation", [None, "missing", "extra", "changed", "symlink", "malformed"])
def test_offline_wheelhouse_integrity_is_fail_closed(tmp_path, mutation):
    hashes = {}
    for name, version in TOOLS.items():
        filename = f"{name}-{version}-py3-none-any.whl"
        (tmp_path / filename).write_bytes(b"synthetic wheel for integrity test")
        hashes[filename] = hashlib.sha256((tmp_path / filename).read_bytes()).hexdigest()
    target = tmp_path / next(iter(hashes))
    if mutation == "missing":
        target.unlink()
    elif mutation == "extra":
        (tmp_path / "unexpected.whl").write_bytes(b"extra")
    elif mutation == "changed":
        target.write_bytes(b"mutated")
    elif mutation == "symlink":
        target.unlink()
        target.symlink_to(tmp_path / list(hashes)[1])
    elif mutation == "malformed":
        hashes[target.name] = "not a hash"
    if mutation:
        with pytest.raises(ValueError):
            verify_wheelhouse(tmp_path, hashes)
    else:
        assert len(verify_wheelhouse(tmp_path, hashes)) == 4
