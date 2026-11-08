from __future__ import annotations

import csv
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.integrations.ks_integration import (
    KSCallError,
    KSClient,
    KSUnavailableError,
    _ks_command,
    _ks_env,
    ks_client,
)

_HAS_KNOWLEDGE_SERVER = importlib.util.find_spec("knowledge_server") is not None


def _write_dict_csv(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["entity", "field_name", "type", "nullable", "description"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "entity": "Account",
                "field_name": "account_id",
                "type": "string",
                "nullable": "false",
                "description": "Primary key",
            }
        )
    return path


def _require_knowledge_server() -> None:
    if not _HAS_KNOWLEDGE_SERVER:
        pytest.skip(
            "knowledge_server package not installed; skipping KS subprocess tests"
        )


@pytest.fixture()
def ks(tmp_path: Path):
    _require_knowledge_server()
    docs = tmp_path / "docs"
    csv_path = _write_dict_csv(docs / "fields.csv")
    client = KSClient(
        allowed_roots=[str(docs)],
        db_path=str(tmp_path / "ks.sqlite3"),
    )
    client.start()
    try:
        yield {"client": client, "docs": docs, "csv": csv_path}
    finally:
        client.stop()


def test_ks_client_starts_and_is_ready(tmp_path: Path):
    _require_knowledge_server()
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    client = KSClient(
        allowed_roots=[str(docs)],
        db_path=str(tmp_path / "ks.sqlite3"),
    )
    assert client.is_ready() is False
    client.start()
    try:
        assert client.is_ready() is True
    finally:
        client.stop()
    assert client.is_ready() is False


def test_ks_client_stop_is_idempotent(tmp_path: Path):
    _require_knowledge_server()
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    client = KSClient(
        allowed_roots=[str(docs)],
        db_path=str(tmp_path / "ks.sqlite3"),
    )
    client.start()
    client.stop()
    client.stop()


def test_ks_client_raises_unavailable_before_start(tmp_path: Path):
    client = KSClient(
        allowed_roots=[str(tmp_path / "docs")],
        db_path=str(tmp_path / "ks.sqlite3"),
    )
    with pytest.raises(KSUnavailableError):
        client.call("list_documents", {"project_id": "x"})


def test_ks_env_sets_shared_mode_for_child(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "app.integrations.ks_integration.get_studio_settings",
        lambda: MagicMock(shared_mode=True),
    )

    env = _ks_env(
        tmp_path,
        [str(tmp_path / "session" / "ks")],
        str(tmp_path / "session" / "ks" / "knowledge.sqlite3"),
    )

    assert env["EDGEFORGE_SHARED_MODE"] == "1"


def test_ks_env_strips_inherited_shared_mode_for_solo_child(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("EDGEFORGE_SHARED_MODE", "1")
    monkeypatch.setattr(
        "app.integrations.ks_integration.get_studio_settings",
        lambda: MagicMock(shared_mode=False),
    )

    env = _ks_env(tmp_path, [str(tmp_path / "docs")], None)

    assert "EDGEFORGE_SHARED_MODE" not in env


@pytest.mark.parametrize("db_path", [None, ""])
def test_ks_client_shared_mode_missing_db_path_fails_before_spawn(
    monkeypatch,
    tmp_path: Path,
    db_path: str | None,
):
    monkeypatch.setattr(
        "app.integrations.ks_integration.get_studio_settings",
        lambda: MagicMock(shared_mode=True),
    )
    monkeypatch.setattr(
        "app.integrations.ks_integration._ks_repo",
        lambda: tmp_path,
    )
    popen = MagicMock(side_effect=AssertionError("KS process must not be spawned"))
    monkeypatch.setattr(
        "app.integrations.ks_integration.subprocess.Popen",
        popen,
    )

    client = KSClient(allowed_roots=[str(tmp_path / "session" / "ks")], db_path=db_path)

    with pytest.raises(KSUnavailableError, match="per-session database path"):
        client.start()
    popen.assert_not_called()


@pytest.mark.parametrize("allowed_roots", [[], [""], ["   "]])
def test_ks_client_shared_mode_blank_roots_fail_before_spawn(
    monkeypatch,
    tmp_path: Path,
    allowed_roots: list[str],
):
    monkeypatch.setattr(
        "app.integrations.ks_integration.get_studio_settings",
        lambda: MagicMock(shared_mode=True),
    )
    monkeypatch.setattr(
        "app.integrations.ks_integration._ks_repo",
        lambda: tmp_path,
    )
    popen = MagicMock(side_effect=AssertionError("KS process must not be spawned"))
    monkeypatch.setattr(
        "app.integrations.ks_integration.subprocess.Popen",
        popen,
    )

    client = KSClient(
        allowed_roots=allowed_roots,
        db_path=str(tmp_path / "session" / "ks" / "knowledge.sqlite3"),
    )

    with pytest.raises(KSUnavailableError, match="per-session allowed root"):
        client.start()
    popen.assert_not_called()


def test_ks_env_solo_mode_preserves_default_database_path(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(
        "app.integrations.ks_integration.get_studio_settings",
        lambda: MagicMock(shared_mode=False),
    )

    env = _ks_env(tmp_path, [str(tmp_path / "docs")], None)

    assert env["EDGEFORGE_KS_DB_PATH"] == "./edgeforge_knowledge.sqlite3"


def test_ks_env_accepts_real_shared_workspace_values(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "app.integrations.ks_integration.get_studio_settings",
        lambda: MagicMock(shared_mode=True),
    )
    workspace_ks_root = tmp_path / "sessions" / "session-1" / "ks"
    workspace_ks_root.mkdir(parents=True)
    db_path = workspace_ks_root / "knowledge.sqlite3"

    env = _ks_env(tmp_path, [str(workspace_ks_root)], str(db_path))

    assert env["EDGEFORGE_SHARED_MODE"] == "1"
    assert env["EDGEFORGE_KS_ALLOWED_ROOTS"] == str(workspace_ks_root)
    assert env["EDGEFORGE_KS_DB_PATH"] == str(db_path)


def test_ks_suggest_manifest_candidates_passes_mapping_context(monkeypatch, tmp_path: Path):
    client = KSClient(
        allowed_roots=[str(tmp_path / "docs")],
        db_path=str(tmp_path / "ks.sqlite3"),
    )
    calls: list[tuple[str, dict]] = []

    def fake_call(tool_name: str, arguments: dict):
        calls.append((tool_name, arguments))
        return {"suggestions": []}

    monkeypatch.setattr(client, "call", fake_call)

    result = client.suggest_manifest_candidates(
        project_id="proj",
        scope="mappings",
        route_name="payment-posted",
        direction="request",
        source_entity="Payment",
        target_entity="LedgerEntry",
        field_name_pattern="payment",
    )

    assert result == {"suggestions": []}
    assert calls == [
        (
            "suggest_manifest_candidates",
            {
                "project_id": "proj",
                "scope": "mappings",
                "min_source_count": 1,
                "max_suggestions": 50,
                "route_name": "payment-posted",
                "direction": "request",
                "source_entity": "Payment",
                "target_entity": "LedgerEntry",
                "field_name_pattern": "payment",
            },
        )
    ]


def test_ks_ingest_document_returns_success(ks):
    client = ks["client"]
    csv_path = ks["csv"]

    result = client.ingest_document(
        project_id="proj",
        file_path=str(csv_path),
        doc_type="csv",
    )

    assert result["success"] is True
    assert result["tool_name"] == "ingest_document"
    assert result["document_id"]
    assert result["field_count"] >= 1


def test_ks_list_documents_returns_ingested_document(ks):
    client = ks["client"]
    csv_path = ks["csv"]

    client.ingest_document(
        project_id="proj",
        file_path=str(csv_path),
        doc_type="csv",
    )
    result = client.list_documents(project_id="proj")

    assert len(result["documents"]) == 1
    assert "fields.csv" in result["documents"][0]["name"]


def test_ks_search_documents_returns_results(ks):
    client = ks["client"]
    csv_path = ks["csv"]

    client.ingest_document(
        project_id="proj",
        file_path=str(csv_path),
        doc_type="csv",
    )
    result = client.search_documents(project_id="proj", query="account")

    assert result["tool_name"] == "search_documents"
    assert result["result_count"] >= 1
    assert result["results"][0]["document_name"] == "fields.csv"


def test_ks_read_document_returns_text_and_citations(ks):
    client = ks["client"]
    csv_path = ks["csv"]

    ingest_result = client.ingest_document(
        project_id="proj",
        file_path=str(csv_path),
        doc_type="csv",
    )
    result = client.read_document(
        project_id="proj",
        document_id=ingest_result["document_id"],
    )

    assert result["tool_name"] == "read_document"
    assert "account_id" in result["text"]
    assert result["citations"]


def test_ks_read_field_catalog_returns_structured_fields(ks):
    client = ks["client"]
    csv_path = ks["csv"]

    client.ingest_document(
        project_id="proj",
        file_path=str(csv_path),
        doc_type="csv",
    )
    result = client.read_field_catalog(project_id="proj", entity="Account")

    assert result["tool_name"] == "read_field_catalog"
    assert [field["name"] for field in result["fields"]] == ["account_id"]


def test_ks_suggest_fields_returns_suggestion_ids_and_status(ks):
    client = ks["client"]
    csv_path = ks["csv"]

    client.ingest_document(
        project_id="proj",
        file_path=str(csv_path),
        doc_type="csv",
    )
    result = client.suggest_fields(
        project_id="proj",
        entity="Account",
        field_name_pattern="account_id",
    )

    assert result["tool_name"] == "suggest_fields"
    assert result["suggestion_count"] >= 1
    suggestion = result["suggestions"][0]
    assert suggestion["suggestion_id"]
    assert suggestion["status"] == "pending"


def test_ks_suggest_manifest_candidates_fields_returns_suggestion_ids_and_status(ks):
    client = ks["client"]
    csv_path = ks["csv"]

    client.ingest_document(
        project_id="proj",
        file_path=str(csv_path),
        doc_type="csv",
    )
    result = client.suggest_manifest_candidates(
        project_id="proj",
        scope="fields",
        entity="Account",
        field_name_pattern="account_id",
    )

    assert result["tool_name"] == "suggest_manifest_candidates"
    assert result["scope"] == "fields"
    assert result["suggestion_count"] >= 1
    suggestion = result["suggestions"][0]
    assert suggestion["suggestion_id"]
    assert suggestion["status"] == "pending"


def test_ks_submit_suggestion_decisions_returns_outcomes(ks):
    client = ks["client"]
    csv_path = ks["csv"]

    client.ingest_document(
        project_id="proj",
        file_path=str(csv_path),
        doc_type="csv",
    )
    suggestion = client.suggest_fields(
        project_id="proj",
        field_name_pattern="account_id",
    )["suggestions"][0]

    result = client.submit_suggestion_decisions(
        project_id="proj",
        decisions=[
            {
                "suggestion_id": suggestion["suggestion_id"],
                "status": "edited",
                "edited_payload": {
                    "manifest_path": "entities.Account.fields.account_id",
                    "field_name": "account_id",
                    "suggested_type": "string",
                },
            }
        ],
    )

    assert result["tool_name"] == "submit_suggestion_decisions"
    assert result["outcome_count"] == 1
    assert result["outcomes"][0]["success"] is True
    assert result["outcomes"][0]["status"] == "edited"


def test_ks_suggest_fields_reflects_persisted_status_after_review(ks):
    client = ks["client"]
    csv_path = ks["csv"]

    client.ingest_document(
        project_id="proj",
        file_path=str(csv_path),
        doc_type="csv",
    )
    initial = client.suggest_fields(
        project_id="proj",
        field_name_pattern="account_id",
    )
    suggestion = initial["suggestions"][0]

    client.submit_suggestion_decisions(
        project_id="proj",
        decisions=[
            {
                "suggestion_id": suggestion["suggestion_id"],
                "status": "accepted",
            }
        ],
    )
    refreshed = client.suggest_fields(
        project_id="proj",
        field_name_pattern="account_id",
    )

    assert refreshed["suggestions"][0]["suggestion_id"] == suggestion["suggestion_id"]
    assert refreshed["suggestions"][0]["status"] == "accepted"


def test_ks_suggest_manifest_candidates_reflects_persisted_status_after_review(ks):
    client = ks["client"]
    csv_path = ks["csv"]

    client.ingest_document(
        project_id="proj",
        file_path=str(csv_path),
        doc_type="csv",
    )
    initial = client.suggest_manifest_candidates(
        project_id="proj",
        scope="fields",
        field_name_pattern="account_id",
    )
    suggestion = initial["suggestions"][0]

    client.submit_suggestion_decisions(
        project_id="proj",
        decisions=[
            {
                "suggestion_id": suggestion["suggestion_id"],
                "status": "accepted",
            }
        ],
    )
    refreshed = client.suggest_manifest_candidates(
        project_id="proj",
        scope="fields",
        field_name_pattern="account_id",
    )

    assert refreshed["suggestions"][0]["suggestion_id"] == suggestion["suggestion_id"]
    assert refreshed["suggestions"][0]["status"] == "accepted"


def test_ks_get_field_evidence_chain_returns_composed_result(ks):
    client = ks["client"]
    csv_path = ks["csv"]

    client.ingest_document(
        project_id="proj",
        file_path=str(csv_path),
        doc_type="csv",
    )
    result = client.get_field_evidence_chain(
        project_id="proj",
        field_name="account_id",
    )

    assert result["tool_name"] == "get_field_evidence_chain"
    assert result["suggestion"] is not None
    assert result["suggestion"]["entity"] == "Account"
    assert len(result["definitions"]) >= 1
    assert len(result["evidence_chunks"]) >= 1


def test_ks_get_suggestion_evidence_chain_fields_returns_composed_result(ks):
    client = ks["client"]
    csv_path = ks["csv"]

    client.ingest_document(
        project_id="proj",
        file_path=str(csv_path),
        doc_type="csv",
    )
    result = client.get_suggestion_evidence_chain(
        project_id="proj",
        scope="fields",
        suggestion_id=client.suggest_manifest_candidates(
            project_id="proj",
            scope="fields",
            field_name_pattern="account_id",
        )["suggestions"][0]["suggestion_id"],
    )

    assert result["tool_name"] == "get_suggestion_evidence_chain"
    assert result["scope"] == "fields"
    assert result["suggestion"] is not None
    assert result["suggestion"]["entity"] == "Account"
    assert len(result["definitions"]) >= 1
    assert len(result["evidence_chunks"]) >= 1


def test_ks_client_context_manager_stops_on_exit(tmp_path: Path):
    _require_knowledge_server()
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)

    with ks_client(
        allowed_roots=[str(docs)],
        db_path=str(tmp_path / "ks.sqlite3"),
    ) as client:
        assert client.is_ready() is True

    assert client.is_ready() is False


def test_ks_get_field_evidence_chain_returns_empty_for_unknown_project(ks):
    client = ks["client"]

    result = client.get_field_evidence_chain(
        project_id="no-such-project",
        field_name="account_id",
    )

    assert result["suggestion"] is None
    assert result["definitions"] == []
    assert result["source_count"] == 0
    assert result["warnings"]


def test_ks_invalid_tool_name_raises_call_error(ks):
    client = ks["client"]

    with pytest.raises(KSCallError) as exc_info:
        client.call("no_such_tool", {"project_id": "proj"})

    assert exc_info.value.tool_name == "no_such_tool"
    assert "Unknown tool" in exc_info.value.error_message


def test_ks_command_prefers_importable_python_when_sys_executable_fails(
    monkeypatch,
    tmp_path: Path,
):
    ks_repo = tmp_path / "EdgeForgeKnowledgeServer"
    ks_repo.mkdir(parents=True, exist_ok=True)

    monkeypatch.delenv("EDGEFORGE_STUDIO_KS_COMMAND", raising=False)
    monkeypatch.setattr(
        "app.integrations.ks_integration.sys.executable",
        "/usr/bin/python3",
    )

    def fake_which(name: str) -> str | None:
        return {
            "python3.11": "/opt/homebrew/bin/python3.11",
            "python3.10": None,
            "python3": "/usr/bin/python3",
        }.get(name)

    monkeypatch.setattr("app.integrations.ks_integration.shutil.which", fake_which)

    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(cmd, capture_output, text, timeout, env):
        calls.append((cmd, env))
        executable = cmd[0]
        return MagicMock(
            returncode=0 if executable == "/opt/homebrew/bin/python3.11" else 1
        )

    monkeypatch.setattr("app.integrations.ks_integration.subprocess.run", fake_run)

    command = _ks_command(ks_repo)

    assert command == "/opt/homebrew/bin/python3.11"
    assert calls[0][0][0] == "/usr/bin/python3"
    assert str(ks_repo) in calls[0][1]["PYTHONPATH"]
