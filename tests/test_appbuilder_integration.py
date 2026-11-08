"""Tests for the AppBuilder subprocess integration layer.

Covers SubprocessResult shape, _run_subprocess helper paths (success, failure,
timeout, missing executable), mocked public-function seams, and optional
cross-repo proofs against an explicitly discovered Engine checkout.
"""

from __future__ import annotations

import builtins
import logging
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.integrations.appbuilder_integration import (
    SubprocessResult,
    _call_generate_app_mcp,
    _coerce_mcp_tool_result,
    _engine_module_args,
    _format_mcp_generation_output,
    _mcp_command,
    _mcp_env,
    _run_subprocess,
    _validation_repo_for,
    run_assess,
    run_generate,
    validate_manifest,
)
from app.services.diagnostics import project_engine_result
from tests.openapi_cache_helpers import write_openapi_cache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


@pytest.fixture
def cached_account_create_spec():
    """Match _full_session's selected write without changing its shared fixture."""
    return """openapi: 3.1.0
info: {title: URL semantics proof, version: '1.0'}
paths:
  /accounts:
    post:
      operationId: createAccount
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/Account'
      responses:
        '201':
          description: Created account
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Account'
components:
  schemas:
    Account:
      type: object
      properties:
        accountId: {type: string}
        label: {type: string}
        category: {type: string}
        status: {type: string}
        serverOnly: {type: string}
"""


@pytest.fixture
def engine_child_commands(monkeypatch):
    """Observe real children; never replace Engine execution or its result."""
    commands = []
    real_popen = subprocess.Popen

    class ObservedPopen(real_popen):
        def __init__(self, command, *args, **kwargs):
            super().__init__(command, *args, **kwargs)
            commands.append(list(command))

    monkeypatch.setattr(subprocess, "Popen", ObservedPopen)
    return commands


# ---------------------------------------------------------------------------
# SubprocessResult dataclass
# ---------------------------------------------------------------------------

class TestSubprocessResult:
    def test_fields_present(self):
        r = SubprocessResult(
            success=True, returncode=0,
            stdout="out", stderr="",
            combined_output="out",
            duration_seconds=0.1,
            command=["python", "-c", "pass"],
            cwd="/tmp",
        )
        assert r.success is True
        assert r.returncode == 0
        assert r.stdout == "out"
        assert r.stderr == ""
        assert r.combined_output == "out"
        assert r.duration_seconds == 0.1
        assert r.command == ["python", "-c", "pass"]
        assert r.cwd == "/tmp"


# ---------------------------------------------------------------------------
# _run_subprocess — success path
# ---------------------------------------------------------------------------

class TestRunSubprocessSuccess:
    def test_success_populates_all_fields(self):
        proc = _mock_proc(returncode=0, stdout="hello\n", stderr="")
        with patch("subprocess.run", return_value=proc):
            result = _run_subprocess(["echo", "hello"], label="test")

        assert result.success is True
        assert result.returncode == 0
        assert result.stdout == "hello\n"
        assert result.stderr == ""
        assert result.combined_output == "hello"   # stripped
        assert result.duration_seconds >= 0.0
        assert result.command == ["echo", "hello"]

    def test_failure_captures_stderr(self):
        proc = _mock_proc(returncode=1, stdout="", stderr="something broke\n")
        with patch("subprocess.run", return_value=proc):
            result = _run_subprocess(["false"], label="test")

        assert result.success is False
        assert result.returncode == 1
        assert result.stderr == "something broke\n"
        assert "something broke" in result.combined_output

    def test_combined_output_merges_stdout_and_stderr(self):
        proc = _mock_proc(returncode=1, stdout="stdout line\n", stderr="stderr line\n")
        with patch("subprocess.run", return_value=proc):
            result = _run_subprocess(["cmd"], label="test")

        assert "stdout line" in result.combined_output
        assert "stderr line" in result.combined_output

    def test_failure_logs_are_sanitized_but_raw_result_is_preserved(self, caplog):
        raw = (
            "Traceback (most recent call last):\n"
            '  File "/Users/example/private/engine.py", line 8, in generate\n'
            "RuntimeError: Field 'accountId' is missing; TOKEN=do-not-log\n"
            "Authorization: Bearer super-secret-token\n"
            "--authorization Bearer option-secret-token\n"
            "--authorization=Basic dXNlcjpwYXNz\n"
            "HTTP_AUTHORIZATION=Bearer env-secret-token\n"
            "REDIRECT_HTTP_AUTHORIZATION=Bearer redirect-secret-token\n"
            "X_AUTHORIZATION=Basic eDpzZWNyZXQ=\n"
            "DATABASE_URL=postgresql://alice:db-password@db.internal/prod\n"
            "JDBC_URL=jdbc:postgresql://bob:jdbc-password@db.internal/prod\n"
            "Manifest /Users/alice/My Private Project/app-definition.yaml\n"
            "Manifest /Users/alice/Hidden Workspace/generated-app\n"
            "Manifest C:\\Users\\Alice\\Sensitive Workspace\\generated-app\n"
            "Schema /tmp/generated-app because field customerId is required\n"
            "Manifest /Users/alice/Project,Secret/generated-app\n"
            "Manifest C:\\Users\\Alice\\Project (Secret)\\generated-app\n"
            "path:/Users/alice/Colon Secret/generated-app\n"
            "manifest:C:\\Users\\Alice\\Colon Secret\\generated-app\n"
            "Manifest /Users/alice/Project, file Boundary Secret/generated-app\n"
            "Manifest C:\\Users\\Alice\\Project because field Boundary Secret\\generated-app\n"
        )
        proc = _mock_proc(returncode=1, stderr=raw)

        with caplog.at_level(logging.ERROR), patch("subprocess.run", return_value=proc):
            result = _run_subprocess(
                ["python", "-m", "appbuilder.cli", "--token", "command-secret"],
                label="test",
            )

        assert result.stderr == raw
        assert result.combined_output == raw.strip()
        projection = project_engine_result(result)
        assert projection.diagnostic_id == result.diagnostic_id
        assert projection.diagnostic_id in caplog.text
        assert projection.diagnostic_id in projection.message
        assert "Field 'accountId' is missing" in caplog.text
        assert "/Users/example" not in caplog.text
        assert "do-not-log" not in caplog.text
        assert "super-secret-token" not in caplog.text
        assert "option-secret-token" not in caplog.text
        assert "dXNlcjpwYXNz" not in caplog.text
        assert "env-secret-token" not in caplog.text
        assert "redirect-secret-token" not in caplog.text
        assert "eDpzZWNyZXQ=" not in caplog.text
        assert "[redacted]]" not in caplog.text
        assert "db-password" not in caplog.text
        assert "jdbc-password" not in caplog.text
        assert "Private Project" not in caplog.text
        assert "Hidden Workspace" not in caplog.text
        assert "Sensitive Workspace" not in caplog.text
        assert "because field customerId is required" in caplog.text
        assert "Project,Secret" not in caplog.text
        assert "Project (Secret)" not in caplog.text
        assert "Colon Secret" not in caplog.text
        assert "Boundary Secret" not in caplog.text
        assert "command-secret" not in caplog.text


# ---------------------------------------------------------------------------
# _run_subprocess — timeout path
# ---------------------------------------------------------------------------

class TestRunSubprocessTimeout:
    def test_timeout_returns_failure_result(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["sleep"], timeout=1)):
            result = _run_subprocess(["sleep", "999"], timeout=1, label="test")

        assert result.success is False
        assert result.returncode == -1
        assert "Timed out" in result.stderr
        assert "Timed out" in result.combined_output
        assert result.duration_seconds >= 0.0

    def test_timeout_includes_timeout_value(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["x"], timeout=5)):
            result = _run_subprocess(["x"], timeout=5, label="test")
        assert "5s" in result.combined_output

    def test_timeout_preserves_partial_output(self):
        # TimeoutExpired carries partial stdout/stderr as bytes even when
        # subprocess.run() was called with text=True — this is Python's real
        # runtime behaviour and the regression test must reflect it.
        exc = subprocess.TimeoutExpired(cmd=["appbuilder"], timeout=120)
        exc.output = b"Processed 3 of 10 entities\n"
        exc.stderr = b"WARNING: slow schema resolution\n"
        with patch("subprocess.run", side_effect=exc):
            result = _run_subprocess(["appbuilder"], timeout=120, label="test")

        assert result.success is False
        assert result.stdout == "Processed 3 of 10 entities\n"
        assert result.stderr == "WARNING: slow schema resolution\n"
        assert "Processed 3 of 10 entities" in result.combined_output
        assert "WARNING: slow schema resolution" in result.combined_output
        assert "Timed out after 120s" in result.combined_output

    def test_timeout_partial_output_none(self):
        # When no output was captured before the kill, exc.output / exc.stderr
        # are None — must not raise, must still contain the timeout message.
        exc = subprocess.TimeoutExpired(cmd=["appbuilder"], timeout=30)
        exc.output = None
        exc.stderr = None
        with patch("subprocess.run", side_effect=exc):
            result = _run_subprocess(["appbuilder"], timeout=30, label="test")

        assert result.success is False
        assert result.stdout == ""
        assert "Timed out after 30s" in result.combined_output


# ---------------------------------------------------------------------------
# _run_subprocess — missing executable path
# ---------------------------------------------------------------------------

class TestRunSubprocessMissingExecutable:
    def test_file_not_found_returns_failure_result(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("no such file")):
            result = _run_subprocess(["no-such-binary"], label="test")

        assert result.success is False
        assert result.returncode == -1
        assert "Executable not found" in result.stderr
        assert "Executable not found" in result.combined_output

    def test_os_error_returns_failure_result(self):
        with patch("subprocess.run", side_effect=OSError(35, "Resource deadlock avoided")):
            result = _run_subprocess(["python", "-c", "pass"], label="test")

        assert result.success is False
        assert result.returncode == -1
        assert "Failed to start subprocess" in result.stderr
        assert "Resource deadlock avoided" in result.combined_output


# ---------------------------------------------------------------------------
# validate_manifest
# ---------------------------------------------------------------------------

class TestValidateManifest:
    def test_success(self, tmp_path):
        proc = _mock_proc(returncode=0, stdout="VALID\n")
        with patch("subprocess.run", return_value=proc):
            result = validate_manifest(tmp_path / "app-definition.yaml", str(tmp_path))

        assert result.success is True
        assert "valid" in result.combined_output.lower()

    def test_failure_preserves_stderr(self, tmp_path):
        proc = _mock_proc(returncode=1, stderr="ValidationError: missing field\n")
        with patch("subprocess.run", return_value=proc):
            result = validate_manifest(tmp_path / "app-definition.yaml", str(tmp_path))

        assert result.success is False
        assert result.returncode == 1
        assert "ValidationError" in result.combined_output

    def test_child_os_error_is_summarized_as_infrastructure_failure(self, tmp_path):
        proc = _mock_proc(
            returncode=1,
            stderr=(
                "Traceback (most recent call last):\n"
                "  File \"<string>\", line 3, in <module>\n"
                "OSError: [Errno 35] Resource deadlock avoided\n"
            ),
        )
        with patch("subprocess.run", return_value=proc):
            result = validate_manifest(tmp_path / "app-definition.yaml", str(tmp_path))

        assert result.success is False
        assert "Validation subprocess failed before manifest checks" in result.combined_output
        assert "Resource deadlock avoided" in result.combined_output
        assert "Traceback" not in result.combined_output

    def test_missing_repo_returns_failure_without_subprocess(self):
        result = validate_manifest(Path("/fake/manifest.yaml"), "/nonexistent/repo")
        assert result.success is False
        assert "not found" in result.combined_output.lower()
        assert result.returncode == -1

    def test_valid_sentinel_missing_despite_exit_zero(self, tmp_path):
        # subprocess exits 0 but doesn't print VALID — should be treated as failure
        proc = _mock_proc(returncode=0, stdout="something unexpected\n")
        with patch("subprocess.run", return_value=proc):
            result = validate_manifest(tmp_path / "app-definition.yaml", str(tmp_path))

        assert result.success is False

    def test_validation_uses_package_loading_import_path(self, tmp_path):
        proc = _mock_proc(returncode=0, stdout="VALID\n")
        with patch("subprocess.run", return_value=proc) as run:
            validate_manifest(tmp_path / "app-definition.yaml", str(tmp_path))

        cmd = run.call_args.args[0]
        assert "-B" in cmd
        assert "-c" in cmd
        assert "load_project_definition" in cmd[cmd.index("-c") + 1]
        assert run.call_args.kwargs["cwd"] == str(tmp_path)
        assert str(tmp_path) in run.call_args.kwargs["env"]["PYTHONPATH"]

    def test_validation_uses_configured_runtime_repo_when_present(self, tmp_path, monkeypatch):
        configured_repo = tmp_path / "workspace" / "EdgeForge"
        runtime_repo = tmp_path / "runtime" / "EdgeForgeRuntime"
        configured_repo.mkdir(parents=True)
        runtime_repo.mkdir(parents=True)
        monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_VALIDATION_REPO", str(runtime_repo))

        proc = _mock_proc(returncode=0, stdout="VALID\n")
        with patch("subprocess.run", return_value=proc) as run:
            result = validate_manifest(tmp_path / "app-definition.yaml", str(configured_repo))

        assert result.success is True
        assert run.call_args.kwargs["cwd"] == str(runtime_repo)
        assert str(runtime_repo) in run.call_args.kwargs["env"]["PYTHONPATH"]

    def test_validation_repo_falls_back_when_override_missing(self, tmp_path, monkeypatch):
        configured_repo = tmp_path / "workspace" / "EdgeForge"
        configured_repo.mkdir(parents=True)
        monkeypatch.setenv(
            "EDGEFORGE_STUDIO_ENGINE_VALIDATION_REPO",
            str(tmp_path / "missing-runtime"),
        )

        assert _validation_repo_for(configured_repo) == configured_repo


# ---------------------------------------------------------------------------
# run_assess
# ---------------------------------------------------------------------------

class TestRunAssess:
    def test_success(self, tmp_path):
        url = "http://localhost/v3/api-docs"
        cache = write_openapi_cache(tmp_path, url)
        proc = _mock_proc(returncode=0, stdout="Assessment passed\n")
        with patch("subprocess.run", return_value=proc) as run:
            result = run_assess(
                url,
                str(tmp_path),
                openapi_cache_path=str(cache),
            )

        assert result.success is True
        assert result.returncode == 0
        assert "Assessment passed" in result.combined_output
        assert run.call_args.args[0][1] == "-c"

    def test_failure_preserves_stderr(self, tmp_path):
        url = "http://localhost/v3/api-docs"
        cache = write_openapi_cache(tmp_path, url)
        proc = _mock_proc(returncode=1, stderr="connection refused\n")
        with patch("subprocess.run", return_value=proc):
            result = run_assess(
                url,
                str(tmp_path),
                openapi_cache_path=str(cache),
            )

        assert result.success is False
        assert "connection refused" in result.combined_output

    def test_remote_url_without_approved_cache_fails_before_spawn(self, tmp_path):
        with patch("subprocess.run") as run:
            result = run_assess(
                "https://api.example.com/openapi.yaml",
                str(tmp_path),
            )

        assert result.success is False
        assert "OpenAPI cache" in result.combined_output
        run.assert_not_called()

    def test_cached_source_keeps_original_url_semantics_without_network(self, tmp_path):
        url = "https://api.example.com/openapi.yaml"
        cache = write_openapi_cache(tmp_path, url)
        proc = _mock_proc(returncode=0, stdout="Assessment passed\n")

        with patch("subprocess.run", return_value=proc) as run:
            result = run_assess(
                url,
                str(tmp_path),
                openapi_cache_path=str(cache),
            )

        assert result.success is True
        command = run.call_args.args[0]
        assert command[1] == "-c"
        assert url in command
        assert "--swagger" in command
        assert run.call_args.kwargs["env"]["EDGEFORGE_STUDIO_ENGINE_OPENAPI_CACHE"] == str(
            cache.resolve()
        )

    def test_real_shared_engine_assesses_cached_url_without_network(
        self,
        tmp_path,
        monkeypatch,
    ):
        engine_repo = Path(
            os.environ.get(
                "EDGEFORGE_ENGINE_REPO",
                Path(__file__).resolve().parents[2] / "EdgeForge",
            )
        )
        if not (engine_repo / "appbuilder" / "cli.py").is_file():
            pytest.skip("Sibling EdgeForge checkout is not available")
        url = "https://must-not-resolve.invalid/openapi.yaml"
        cache = write_openapi_cache(
            tmp_path,
            url,
            "openapi: 3.1.0\n"
            "info:\n"
            "  title: Materialized proof\n"
            "  version: '1.0'\n"
            "paths: {}\n",
        )
        monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
        monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")

        result = run_assess(
            url,
            str(engine_repo),
            allowed_roots=[str(tmp_path)],
            openapi_cache_path=str(cache),
        )

        assert result.success is True, result.combined_output
        assert "Materialized proof" in result.combined_output
        assert "--swagger" in result.command

    def test_missing_repo_returns_failure(self):
        result = run_assess("http://x/api-docs", "/nonexistent/repo")
        assert result.success is False
        assert result.returncode == -1


# ---------------------------------------------------------------------------
# run_generate
# ---------------------------------------------------------------------------

class TestRunGenerate:
    def test_success(self, tmp_path):
        """Default auto mode falls back to subprocess when FastMCP is absent."""
        proc = _mock_proc(returncode=0, stdout="Generated 42 files\n")
        with patch("subprocess.run", return_value=proc):
            result = run_generate(
                str(tmp_path / "app-definition.yaml"),
                str(tmp_path / "out"),
                str(tmp_path),
            )

        assert result.success is True
        assert result.returncode == 0
        assert "Generated" in result.combined_output

    def test_failure_captures_exit_code_and_output(self, tmp_path):
        proc = _mock_proc(returncode=2, stderr="KeyError: 'entity'\n")
        with patch("subprocess.run", return_value=proc):
            result = run_generate(
                str(tmp_path / "app-definition.yaml"),
                str(tmp_path / "out"),
                str(tmp_path),
            )

        assert result.success is False
        assert result.returncode == 2
        assert "KeyError" in result.combined_output

    def test_remote_manifest_source_fails_before_spawn(self, tmp_path):
        manifest = tmp_path / "app-definition.yaml"
        manifest.write_text(
            "schema_version: '2.0'\n"
            "upstream_interfaces:\n"
            "  - name: accounts\n"
            "    type: rest-json\n"
            "    spec_url: https://api.example.com/openapi.yaml\n",
            encoding="utf-8",
        )

        with patch("subprocess.run") as run:
            result = run_generate(
                str(manifest),
                str(tmp_path / "out"),
                str(tmp_path),
            )

        assert result.success is False
        assert "OpenAPI cache" in result.combined_output
        run.assert_not_called()

    def test_remote_manifest_uses_original_path_and_cached_url_bootstrap(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_TRANSPORT", "subprocess")
        manifest = tmp_path / "app-definition.yaml"
        url = "https://api.example.com/openapi.yaml"
        manifest.write_text(
            "schema_version: '2.0'\n"
            "upstream_interfaces:\n"
            "  - name: accounts\n"
            "    type: rest-json\n"
            f"    spec_url: {url}\n",
            encoding="utf-8",
        )
        cache = write_openapi_cache(tmp_path / ".studio-openapi-proof", url)
        proc = _mock_proc(returncode=0, stdout="Generated 42 files\n")

        with patch("subprocess.run", return_value=proc) as run:
            result = run_generate(
                str(manifest),
                str(tmp_path / "out"),
                str(tmp_path),
                openapi_cache_path=str(cache),
            )

        assert result.success is True
        command = run.call_args.args[0]
        assert command[1] == "-c"
        assert command[command.index("--manifest") + 1] == str(manifest)
        assert url not in command
        assert run.call_args.kwargs["env"]["EDGEFORGE_STUDIO_ENGINE_OPENAPI_CACHE"] == str(
            cache.resolve()
        )

    def test_cached_manifest_url_must_match_exactly_before_spawn(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_TRANSPORT", "subprocess")
        manifest = tmp_path / "app-definition.yaml"
        manifest.write_text(
            "schema_version: '2.0'\n"
            "upstream_interfaces:\n"
            "  - name: accounts\n"
            "    type: rest-json\n"
            "    spec_url: https://required.example/openapi.yaml\n",
            encoding="utf-8",
        )
        cache = write_openapi_cache(
            tmp_path / ".studio-openapi-proof",
            "https://different.example/openapi.yaml",
        )

        with patch("subprocess.run") as run:
            result = run_generate(
                str(manifest),
                str(tmp_path / "out"),
                str(tmp_path),
                openapi_cache_path=str(cache),
            )

        assert result.success is False
        assert "does not cover every manifest URL" in result.combined_output
        run.assert_not_called()

    def test_real_engine_cached_url_generation_preserves_ingestion_and_source_label(
        self,
        tmp_path,
        monkeypatch,
        cached_account_create_spec,
        engine_child_commands,
    ):
        from app.services.package_writer import write_package_result
        from tests.test_package_writer import _full_session

        engine_repo = Path(
            os.environ.get(
                "EDGEFORGE_ENGINE_REPO",
                Path(__file__).resolve().parents[2] / "EdgeForge",
            )
        )
        if not (engine_repo / "appbuilder" / "cli.py").is_file():
            pytest.skip("Sibling EdgeForge checkout is not available")

        package = write_package_result(_full_session(), tmp_path / "package-root").project_dir
        manifest = package / "app-definition.yaml"
        spec_url = "https://example.com/synthetic-account.json"
        generated_labels: list[set[str]] = []

        for cache_name, output_name, transport in (
            (".studio-openapi-first", "generated-first", "subprocess"),
            (".studio-openapi-second", "generated-second", "mcp"),
        ):
            monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_TRANSPORT", transport)
            cache = write_openapi_cache(package / cache_name, spec_url, cached_account_create_spec)
            output = package / output_name
            engine_child_commands.clear()
            result = run_generate(
                str(manifest),
                str(output),
                str(engine_repo),
                openapi_cache_path=str(cache),
            )
            assert result.success is True, result.combined_output
            module = "appbuilder.mcp_server" if transport == "mcp" else "appbuilder.cli"
            assert len(engine_child_commands) == 1, engine_child_commands
            assert module in engine_child_commands[0]
            if transport == "mcp":
                assert result.command == ["mcp", "edgeforge-engine", "generate_app"]
            account_source = next(output.rglob("Account.java")).read_text(encoding="utf-8")
            assert "serverOnly" in account_source
            # Keep the retired durable runner's useful artifact checks on the
            # independent fixture, without reassigning its historical runtime result.
            assert list(output.rglob("AccountEodHandoffFileWriter.java"))
            staging = next(output.rglob("AccountStagingWriter.java")).read_text()
            assert "synthetic_stage" in staging and "record_id" in staging
            assert list(output.rglob("AccountEodBatchJob.java"))
            assert list(output.rglob("BatchTriggerController.java"))
            labels = {
                line.strip()
                for path in output.rglob("*")
                if path.is_file()
                for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()
                if "Source manifest:" in line
            }
            assert labels
            assert all("app-definition.yaml" in label for label in labels)
            assert all(".studio-openapi-" not in label for label in labels)
            generated_labels.append(labels)

        assert generated_labels[0] == generated_labels[1]

    @pytest.mark.parametrize("transport", ["subprocess", "mcp"])
    def test_real_engine_cached_url_refuses_absent_selected_operation(
        self, tmp_path, monkeypatch, cached_account_create_spec, engine_child_commands, transport,
    ):
        from app.services.package_writer import write_package_result
        from tests.test_package_writer import _full_session

        engine_repo = Path(os.environ.get(
            "EDGEFORGE_ENGINE_REPO", Path(__file__).resolve().parents[2] / "EdgeForge",
        ))
        if not (engine_repo / "appbuilder" / "cli.py").is_file():
            pytest.skip("Sibling EdgeForge checkout is not available")

        package = write_package_result(_full_session(), tmp_path / "package-root").project_dir
        cache = write_openapi_cache(
            package / ".studio-openapi-missing-operation",
            "https://example.com/synthetic-account.json",
            cached_account_create_spec.replace("operationId: createAccount", "operationId: otherCreate"),
        )
        monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_TRANSPORT", transport)
        output = package / "generated"
        result = run_generate(
            str(package / "app-definition.yaml"), str(output), str(engine_repo),
            openapi_cache_path=str(cache),
        )

        assert result.success is False, result.combined_output
        assert "createAccount" in result.combined_output
        assert "selected operation is unresolved or ambiguous" in result.combined_output
        assert "Falling back to sample ingestion" not in result.combined_output
        assert not list(output.rglob("Account.java"))
        module = "appbuilder.mcp_server" if transport == "mcp" else "appbuilder.cli"
        assert len(engine_child_commands) == 1, engine_child_commands
        assert module in engine_child_commands[0]
        if transport == "mcp":
            assert result.command == ["mcp", "edgeforge-engine", "generate_app"]

    def test_real_engine_unapproved_cache_lookup_fails_closed_in_child(
        self,
        tmp_path,
        monkeypatch,
    ):
        """The child cache seam must not turn an approval miss into sample fallback."""
        from app.services.package_writer import write_package_result
        from tests.test_package_writer import _full_session

        engine_repo = Path(
            os.environ.get(
                "EDGEFORGE_ENGINE_REPO",
                Path(__file__).resolve().parents[2] / "EdgeForge",
            )
        )
        if not (engine_repo / "appbuilder" / "cli.py").is_file():
            pytest.skip("Sibling EdgeForge checkout is not available")

        package = write_package_result(_full_session(), tmp_path / "package-root").project_dir
        manifest = package / "app-definition.yaml"
        cache = write_openapi_cache(
            package / ".studio-openapi-unapproved",
            "https://different.example/openapi.yaml",
        )
        output = package / "generated-unapproved"
        monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_TRANSPORT", "subprocess")

        # Bypass only the parent guard to prove the child boundary independently.
        with patch(
            "app.integrations.appbuilder_integration._openapi_cache_error",
            return_value=None,
        ):
            result = run_generate(
                str(manifest),
                str(output),
                str(engine_repo),
                openapi_cache_path=str(cache),
            )

        assert result.success is False
        assert "OpenAPI URL was not approved by Studio" in result.combined_output
        assert "Falling back to sample ingestion" not in result.combined_output
        assert not list(output.rglob("Account.java"))

    def test_real_engine_malformed_cached_yaml_uses_reviewed_sample_fallback(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Approved malformed content retains Engine's existing sample fallback."""
        from app.services.package_writer import write_package_result
        from tests.test_package_writer import _full_session

        engine_repo = Path(
            os.environ.get(
                "EDGEFORGE_ENGINE_REPO",
                Path(__file__).resolve().parents[2] / "EdgeForge",
            )
        )
        if not (engine_repo / "appbuilder" / "cli.py").is_file():
            pytest.skip("Sibling EdgeForge checkout is not available")

        package = write_package_result(_full_session(), tmp_path / "package-root").project_dir
        manifest = package / "app-definition.yaml"
        spec_url = "https://example.com/synthetic-account.json"
        cache = write_openapi_cache(
            package / ".studio-openapi-malformed",
            spec_url,
            "openapi: [unterminated\n",
        )
        output = package / "generated-malformed"
        monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_TRANSPORT", "subprocess")

        result = run_generate(
            str(manifest),
            str(output),
            str(engine_repo),
            openapi_cache_path=str(cache),
        )

        assert result.success is True, result.combined_output
        account_source = next(output.rglob("Account.java")).read_text(encoding="utf-8")
        assert "label" in account_source
        assert "accountId" in account_source

    def test_timeout(self, tmp_path):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["x"], timeout=120)):
            result = run_generate("m.yaml", "out/", str(tmp_path))

        assert result.success is False
        assert "Timed out" in result.combined_output

    def test_missing_repo_returns_failure(self):
        result = run_generate("manifest.yaml", "out/", "/nonexistent/repo")
        assert result.success is False
        assert result.returncode == -1

    def test_mcp_success_returns_existing_result_shape(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_TRANSPORT", "mcp")

        async def fake_call(manifest_path, output_dir, repo):
            return {
                "success": True,
                "output_dir": output_dir,
                "files_written": ["pom.xml", "src/main/java/App.java"],
                "warnings": ["generated with defaults"],
                "errors": [],
            }

        monkeypatch.setattr("app.integrations.appbuilder_integration._call_generate_app_mcp", fake_call)

        result = run_generate(
            str(tmp_path / "app-definition.yaml"),
            str(tmp_path / "out"),
            str(tmp_path),
        )

        assert result.success is True
        assert result.returncode == 0
        assert result.command == ["mcp", "edgeforge-engine", "generate_app"]
        assert "Generated application at:" in result.combined_output
        assert "Files written: 2" in result.combined_output
        assert "WARNING: generated with defaults" in result.combined_output

    def test_auto_mode_falls_back_to_subprocess_when_mcp_unavailable(self, tmp_path, monkeypatch):
        async def fake_call(*args, **kwargs):
            raise RuntimeError("client not configured")

        proc = _mock_proc(returncode=0, stdout="Generated by CLI\n")
        monkeypatch.setattr("app.integrations.appbuilder_integration._call_generate_app_mcp", fake_call)
        with patch("subprocess.run", return_value=proc):
            result = run_generate(
                str(tmp_path / "app-definition.yaml"),
                str(tmp_path / "out"),
                str(tmp_path),
            )

        assert result.success is True
        assert result.command[2:4] == ["appbuilder.cli", "generate"]
        assert "Generated by CLI" in result.combined_output

    def test_auto_mode_does_not_fallback_when_mcp_returns_generation_failure(self, tmp_path, monkeypatch):
        async def fake_call(manifest_path, output_dir, repo):
            return {
                "success": False,
                "output_dir": output_dir,
                "files_written": [],
                "warnings": ["partial metadata warning"],
                "errors": ["generation contract failed"],
            }

        monkeypatch.setattr("app.integrations.appbuilder_integration._call_generate_app_mcp", fake_call)
        with patch("subprocess.run") as run:
            result = run_generate(
                str(tmp_path / "app-definition.yaml"),
                str(tmp_path / "out"),
                str(tmp_path),
            )

        assert result.success is False
        assert result.returncode == 1
        assert result.command == ["mcp", "edgeforge-engine", "generate_app"]
        assert "WARNING: partial metadata warning" in result.combined_output
        assert "ERROR: generation contract failed" in result.combined_output
        run.assert_not_called()

    def test_strict_mcp_mode_does_not_fallback_when_mcp_unavailable(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_TRANSPORT", "mcp")

        async def fake_call(*args, **kwargs):
            raise RuntimeError("client not configured")

        monkeypatch.setattr("app.integrations.appbuilder_integration._call_generate_app_mcp", fake_call)
        with patch("subprocess.run") as run:
            result = run_generate(
                str(tmp_path / "app-definition.yaml"),
                str(tmp_path / "out"),
                str(tmp_path),
            )

        assert result.success is False
        assert result.returncode == -1
        assert "client not configured" in result.combined_output
        run.assert_not_called()


class TestGenerateMcpHelpers:
    def test_mcp_env_allows_manifest_and_output_roots(self, tmp_path, monkeypatch):
        manifest = tmp_path / "package" / "app-definition.yaml"
        output = tmp_path / "generated" / "app"
        manifest.parent.mkdir()
        monkeypatch.setenv("EDGEFORGE_MCP_ALLOWED_ROOTS", "/already/allowed")

        env = _mcp_env(str(manifest), str(output), tmp_path)

        allowed = env["EDGEFORGE_MCP_ALLOWED_ROOTS"].split(os.pathsep)
        assert str(tmp_path) in allowed
        assert str(manifest.parent) in allowed
        assert str(output.parent) in allowed
        assert "/already/allowed" in allowed
        assert str(tmp_path) in env["PYTHONPATH"]

    def test_mcp_cache_bootstrap_is_explicit_and_ambient_cache_is_stripped(
        self,
        tmp_path,
        monkeypatch,
    ):
        manifest = tmp_path / "package" / "app-definition.yaml"
        output = tmp_path / "package" / "generated-app"
        manifest.parent.mkdir()
        cache = tmp_path / "package" / "cache.json"
        cache.write_text('{"version": 1, "sources": {}}', encoding="utf-8")
        monkeypatch.setenv(
            "EDGEFORGE_STUDIO_ENGINE_OPENAPI_CACHE",
            "/tmp/operator-must-not-control-cache.json",
        )

        plain_env = _mcp_env(str(manifest), str(output), tmp_path)
        cached_env = _mcp_env(
            str(manifest),
            str(output),
            tmp_path,
            openapi_cache_path=str(cache),
        )
        cached_args = _engine_module_args(
            "appbuilder.mcp_server",
            openapi_cache_path=str(cache),
        )

        assert "EDGEFORGE_STUDIO_ENGINE_OPENAPI_CACHE" not in plain_env
        assert cached_env["EDGEFORGE_STUDIO_ENGINE_OPENAPI_CACHE"] == str(cache.resolve())
        assert cached_args[0] == "-c"
        assert cached_args[-1] == "appbuilder.mcp_server"
        assert "runpy.run_module" in cached_args[1]

    def test_shared_mode_mcp_env_excludes_repo_and_inherited_roots(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
        monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
        repo = tmp_path / "EdgeForge"
        manifest = tmp_path / "workspace" / "package" / "app-definition.yaml"
        output = tmp_path / "workspace" / "generated" / "app"
        manifest.parent.mkdir(parents=True)
        output.mkdir(parents=True)
        repo.mkdir()
        monkeypatch.setenv("EDGEFORGE_MCP_ALLOWED_ROOTS", os.pathsep.join([str(repo), "/already/allowed"]))

        env = _mcp_env(str(manifest), str(output), repo)

        allowed = env["EDGEFORGE_MCP_ALLOWED_ROOTS"].split(os.pathsep)
        assert str(repo.resolve()) not in allowed
        assert "/already/allowed" not in allowed
        assert str(manifest.parent.resolve()) in allowed
        assert str(output.parent.resolve()) in allowed
        assert str(repo.resolve()) in env["PYTHONPATH"]

    def test_mcp_command_prefers_configured_command(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_MCP_COMMAND", "/opt/edgeforge/python")

        assert _mcp_command(tmp_path) == "/opt/edgeforge/python"

    def test_mcp_command_prefers_engine_venv_when_present(self, tmp_path, monkeypatch):
        monkeypatch.delenv("EDGEFORGE_STUDIO_ENGINE_MCP_COMMAND", raising=False)
        python = tmp_path / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.write_text("", encoding="utf-8")

        assert _mcp_command(tmp_path) == str(python)

    def test_format_mcp_generation_output_surfaces_errors_and_warnings(self):
        output = _format_mcp_generation_output(
            {
                "success": False,
                "output_dir": "/tmp/out",
                "files_written": [],
                "warnings": ["check target profile"],
                "errors": ["missing field mapping"],
            }
        )

        assert "Generation failed via Engine MCP." in output
        assert "WARNING: check target profile" in output
        assert "ERROR: missing field mapping" in output

    def test_coerce_mcp_tool_result_reads_structured_data(self):
        class FakeResult:
            data = {
                "success": True,
                "output_dir": "/tmp/out",
                "files_written": [],
                "warnings": [],
                "errors": [],
            }

        assert _coerce_mcp_tool_result(FakeResult())["success"] is True

    @pytest.mark.asyncio
    async def test_call_generate_app_mcp_reports_missing_fastmcp(self, tmp_path, monkeypatch):
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "fastmcp":
                raise ModuleNotFoundError("No module named 'fastmcp'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(RuntimeError, match="fastmcp is not installed"):
            await _call_generate_app_mcp("manifest.yaml", "out", tmp_path)
