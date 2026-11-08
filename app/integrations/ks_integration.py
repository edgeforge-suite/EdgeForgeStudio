"""Knowledge Server subprocess integration for Studio."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.services.settings import get_studio_settings

_KS_EXECUTABLE_MODULE = "knowledge_server.server"
_KS_ALLOWED_ROOTS_ENV = "EDGEFORGE_KS_ALLOWED_ROOTS"
_KS_DB_PATH_ENV = "EDGEFORGE_KS_DB_PATH"
_KS_DB_PATH_DEFAULT = "./edgeforge_knowledge.sqlite3"
_KS_SHARED_MODE_ENV = "EDGEFORGE_SHARED_MODE"
_MCP_PROTOCOL_VERSION = "2024-11-05"
_STUDIO_KS_COMMAND_ENV = "EDGEFORGE_STUDIO_KS_COMMAND"
_STUDIO_KS_REPO_ENV = "EDGEFORGE_STUDIO_KS_REPO"


class KSUnavailableError(RuntimeError):
    """Raised when the KS subprocess is unavailable or startup/handshake failed."""


class KSCallError(RuntimeError):
    """Raised when KS returns a JSON-RPC error response for a tool call."""

    def __init__(self, tool_name: str, error_message: str) -> None:
        super().__init__(f"KS tool '{tool_name}' failed: {error_message}")
        self.tool_name = tool_name
        self.error_message = error_message


class KSClient:
    def __init__(self, allowed_roots: list[str], db_path: str | None = None) -> None:
        self._allowed_roots = list(allowed_roots)
        self._db_path = db_path
        self._proc: subprocess.Popen[str] | None = None
        self._ready = False
        self._request_id = 0

    def start(self) -> None:
        """Start the KS subprocess and perform the MCP stdio handshake."""
        if self.is_ready():
            return
        if self._proc is not None:
            self.stop()

        ks_repo = _ks_repo()
        env = _ks_env(ks_repo, self._allowed_roots, self._db_path)
        command = _ks_command(ks_repo)

        try:
            self._proc = subprocess.Popen(
                [command, "-m", _KS_EXECUTABLE_MODULE],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=env,
            )
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": _MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "studio", "version": "1.0"},
                    },
                }
            )
            response = self._recv()
            if "result" not in response:
                raise KSUnavailableError("KS handshake failed")
            self._send(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                }
            )
            self._ready = True
            self._request_id = 1
        except Exception as exc:
            self.stop()
            if isinstance(exc, KSUnavailableError):
                raise
            raise KSUnavailableError("KS startup failed") from exc

    def stop(self) -> None:
        """Stop the KS subprocess if it is running."""
        proc = self._proc
        self._ready = False
        self._proc = None
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    def is_ready(self) -> bool:
        """Return True when the KS subprocess is live and handshake-complete."""
        return self._ready and self._proc is not None and self._proc.poll() is None

    def call(self, tool_name: str, arguments: dict) -> dict:
        """Call a KS MCP tool and return the decoded JSON payload."""
        if not self.is_ready():
            raise KSUnavailableError("KS client is not ready")

        self._request_id += 1
        self._send(
            {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            }
        )
        response = self._recv()
        if "error" in response:
            raise KSCallError(tool_name=tool_name, error_message=str(response["error"]))
        result = response.get("result")
        if not isinstance(result, dict):
            raise KSUnavailableError(f"Malformed KS tool response for '{tool_name}'")

        try:
            content_text = result["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise KSUnavailableError(
                f"Malformed KS tool response for '{tool_name}'"
            ) from exc
        if result.get("isError") is True:
            raise KSCallError(tool_name=tool_name, error_message=str(content_text))

        try:
            return json.loads(content_text)
        except json.JSONDecodeError as exc:
            raise KSUnavailableError(
                f"Malformed KS tool JSON payload for '{tool_name}'"
            ) from exc

    def ingest_document(
        self,
        project_id: str,
        file_path: str,
        doc_type: str,
        tags: list[str] | None = None,
        description: str | None = None,
    ) -> dict:
        arguments: dict[str, object] = {
            "project_id": project_id,
            "file_path": file_path,
            "doc_type": doc_type,
        }
        if tags is not None:
            arguments["tags"] = tags
        if description is not None:
            arguments["description"] = description
        return self.call("ingest_document", arguments)

    def list_documents(
        self,
        project_id: str,
        doc_type: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        arguments: dict[str, object] = {"project_id": project_id}
        if doc_type is not None:
            arguments["doc_type"] = doc_type
        if tags is not None:
            arguments["tags"] = tags
        return self.call("list_documents", arguments)

    def search_documents(
        self,
        project_id: str,
        query: str,
        doc_types: list[str] | None = None,
        max_results: int = 20,
    ) -> dict:
        arguments: dict[str, object] = {
            "project_id": project_id,
            "query": query,
            "max_results": max_results,
        }
        if doc_types is not None:
            arguments["doc_types"] = doc_types
        return self.call("search_documents", arguments)

    def read_document(
        self,
        project_id: str,
        document_id: str,
        section: str | None = None,
    ) -> dict:
        arguments: dict[str, object] = {
            "project_id": project_id,
            "document_id": document_id,
        }
        if section is not None:
            arguments["section"] = section
        return self.call("read_document", arguments)

    def delete_document(
        self,
        project_id: str,
        document_id: str,
    ) -> dict:
        return self.call(
            "delete_document",
            {
                "project_id": project_id,
                "document_id": document_id,
            },
        )

    def read_field_catalog(
        self,
        project_id: str,
        source: str | None = None,
        entity: str | None = None,
    ) -> dict:
        arguments: dict[str, object] = {"project_id": project_id}
        if source is not None:
            arguments["source"] = source
        if entity is not None:
            arguments["entity"] = entity
        return self.call("read_field_catalog", arguments)

    def suggest_fields(
        self,
        project_id: str,
        entity: str | None = None,
        field_name_pattern: str | None = None,
        min_source_count: int = 1,
        max_suggestions: int = 50,
    ) -> dict:
        arguments: dict[str, object] = {
            "project_id": project_id,
            "min_source_count": min_source_count,
            "max_suggestions": max_suggestions,
        }
        if entity is not None:
            arguments["entity"] = entity
        if field_name_pattern is not None:
            arguments["field_name_pattern"] = field_name_pattern
        return self.call("suggest_fields", arguments)

    def suggest_manifest_candidates(
        self,
        project_id: str,
        scope: str = "fields",
        entity: str | None = None,
        route_name: str | None = None,
        target_id: str | None = None,
        direction: str | None = None,
        source_entity: str | None = None,
        target_entity: str | None = None,
        field_name_pattern: str | None = None,
        min_source_count: int = 1,
        max_suggestions: int = 50,
    ) -> dict:
        arguments: dict[str, object] = {
            "project_id": project_id,
            "scope": scope,
            "min_source_count": min_source_count,
            "max_suggestions": max_suggestions,
        }
        if entity is not None:
            arguments["entity"] = entity
        if route_name is not None:
            arguments["route_name"] = route_name
        if target_id is not None:
            arguments["target_id"] = target_id
        if direction is not None:
            arguments["direction"] = direction
        if source_entity is not None:
            arguments["source_entity"] = source_entity
        if target_entity is not None:
            arguments["target_entity"] = target_entity
        if field_name_pattern is not None:
            arguments["field_name_pattern"] = field_name_pattern
        return self.call("suggest_manifest_candidates", arguments)

    def submit_suggestion_decisions(
        self,
        project_id: str,
        decisions: list[dict],
    ) -> dict:
        return self.call(
            "submit_suggestion_decisions",
            {
                "project_id": project_id,
                "decisions": decisions,
            },
        )

    def get_field_evidence_chain(
        self,
        project_id: str,
        field_name: str,
        entity: str | None = None,
        max_chunks: int = 10,
    ) -> dict:
        arguments: dict[str, object] = {
            "project_id": project_id,
            "field_name": field_name,
            "max_chunks": max_chunks,
        }
        if entity is not None:
            arguments["entity"] = entity
        return self.call("get_field_evidence_chain", arguments)

    def get_suggestion_evidence_chain(
        self,
        project_id: str,
        suggestion_id: str,
        scope: str = "fields",
        max_chunks: int = 10,
    ) -> dict:
        arguments: dict[str, object] = {
            "project_id": project_id,
            "scope": scope,
            "suggestion_id": suggestion_id,
            "max_chunks": max_chunks,
        }
        return self.call("get_suggestion_evidence_chain", arguments)

    def _send(self, msg: dict) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise KSUnavailableError("KS process is not running")
        try:
            self._proc.stdin.write(json.dumps(msg) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise KSUnavailableError("KS process terminated unexpectedly") from exc

    def _recv(self) -> dict:
        if self._proc is None or self._proc.stdout is None:
            raise KSUnavailableError("KS process is not running")

        line = self._proc.stdout.readline()
        if line == "":
            stderr_detail = ""
            if self._proc.poll() is not None and self._proc.stderr is not None:
                stderr_detail = self._proc.stderr.read().strip()
            if stderr_detail:
                raise KSUnavailableError(
                    f"KS process terminated unexpectedly: {stderr_detail}"
                )
            raise KSUnavailableError("KS process terminated unexpectedly")
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise KSUnavailableError(
                f"KS returned malformed JSON: {line.strip()}"
            ) from exc


@contextmanager
def ks_client(allowed_roots: list[str], db_path: str | None = None) -> Iterator[KSClient]:
    """Start a KS client and guarantee stop() on exit."""
    client = KSClient(allowed_roots=allowed_roots, db_path=db_path)
    client.start()
    try:
        yield client
    finally:
        client.stop()


def _ks_repo() -> Path:
    configured = os.environ.get(_STUDIO_KS_REPO_ENV)
    if configured and configured.strip():
        return Path(configured.strip()).expanduser()
    studio_repo = Path(__file__).resolve().parents[2]
    return studio_repo.parent / "EdgeForgeKnowledgeServer"


def _ks_env(
    ks_repo: Path,
    allowed_roots: list[str],
    db_path: str | None,
) -> dict[str, str]:
    settings = get_studio_settings()
    if settings.shared_mode:
        if db_path is None or not db_path.strip():
            raise KSUnavailableError(
                "Knowledge Server shared mode requires a real per-session "
                "database path (EDGEFORGE_KS_DB_PATH)."
            )
        if not any(root.strip() for root in allowed_roots):
            raise KSUnavailableError(
                "Knowledge Server shared mode requires at least one per-session "
                "allowed root (EDGEFORGE_KS_ALLOWED_ROOTS)."
            )
        resolved_db_path = db_path
    else:
        resolved_db_path = db_path or _KS_DB_PATH_DEFAULT

    env = os.environ.copy()
    if settings.shared_mode:
        env[_KS_SHARED_MODE_ENV] = "1"
    else:
        env.pop(_KS_SHARED_MODE_ENV, None)
    env[_KS_ALLOWED_ROOTS_ENV] = os.pathsep.join(allowed_roots)
    env[_KS_DB_PATH_ENV] = resolved_db_path
    env["FASTMCP_SHOW_SERVER_BANNER"] = "0"
    existing = env.get("PYTHONPATH", "")
    repo_path = str(ks_repo.expanduser().resolve(strict=False))
    env["PYTHONPATH"] = f"{repo_path}{os.pathsep if existing else ''}{existing}"
    return env


def _ks_command(ks_repo: Path) -> str:
    configured = os.environ.get(_STUDIO_KS_COMMAND_ENV)
    if configured and configured.strip():
        return configured.strip()

    repo_venv_python = ks_repo / ".venv" / "bin" / "python"
    if repo_venv_python.exists():
        return str(repo_venv_python)

    probe_env = _ks_probe_env(ks_repo)
    for candidate in _ks_command_candidates():
        if _can_launch_ks(candidate, probe_env):
            return candidate

    return sys.executable


def _ks_command_candidates() -> list[str]:
    candidates = [sys.executable]
    for name in ("python3.11", "python3.10", "python3"):
        resolved = shutil.which(name)
        if resolved:
            candidates.append(resolved)
    return list(dict.fromkeys(candidates))


def _ks_probe_env(ks_repo: Path) -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    repo_path = str(ks_repo.expanduser().resolve(strict=False))
    env["PYTHONPATH"] = f"{repo_path}{os.pathsep if existing else ''}{existing}"
    return env


def _can_launch_ks(command: str, env: dict[str, str]) -> bool:
    try:
        result = subprocess.run(
            [
                command,
                "-c",
                "import sys; assert sys.version_info >= (3, 10); import knowledge_server",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0
