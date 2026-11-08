"""Tests for the Step 1 Knowledge Workspace routes."""

from __future__ import annotations

import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

from fastapi.testclient import TestClient

from app.integrations.ks_integration import KSCallError, KSUnavailableError
from app.main import app
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _enable_knowledge_assist() -> None:
    session = get_session()
    session.capabilities.knowledge_assist_enabled = True
    save_session(session)


def test_project_python_can_import_app_main():
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", "from app.main import app; print(app.title)"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )

    assert result.returncode == 0, result.stderr
    assert "EdgeForge Studio" in result.stdout


def test_knowledge_workspace_redirects_when_assist_off_without_minting(monkeypatch):
    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when Knowledge Assist is off")
        yield

    def fake_ensure_workspace_identity(session):
        raise AssertionError("workspace identity should not be minted when Knowledge Assist is off")

    monkeypatch.setattr("app.routes.knowledge.ks_client", fake_ks_client)
    monkeypatch.setattr("app.routes.knowledge.ensure_workspace_identity", fake_ensure_workspace_identity)

    response = client.get("/knowledge", follow_redirects=False)
    session = get_session()

    assert response.status_code == 303
    assert response.headers["location"] == "/?assist_notice=knowledge-off"
    assert session.project_id is None
    assert session.ks_project_id is None
    assert session.ks_active is False
    assert session.capabilities.knowledge_assist_enabled is False


def test_knowledge_upload_redirects_when_assist_off_without_workspace_write(monkeypatch):
    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when Knowledge Assist is off")
        yield

    def fake_workspace_dir(session):
        raise AssertionError("workspace upload storage should not be touched when Knowledge Assist is off")

    monkeypatch.setattr("app.routes.knowledge.ks_client", fake_ks_client)
    monkeypatch.setattr("app.routes.knowledge.workspace_dir", fake_workspace_dir)

    response = client.post(
        "/knowledge/upload",
        files={"document_file": ("sample.md", b"# Hello", "text/markdown")},
        data={"description": "BRD draft"},
        follow_redirects=False,
    )
    session = get_session()

    assert response.status_code == 303
    assert response.headers["location"] == "/?assist_notice=knowledge-off"
    assert session.project_id is None
    assert session.ks_project_id is None
    assert session.ks_active is False
    assert session.capabilities.knowledge_assist_enabled is False


def test_knowledge_workspace_mints_and_stores_durable_ids(monkeypatch):
    class FakeClient:
        def list_documents(self, project_id: str):
            return {"documents": [], "warnings": []}

        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {"fields": [], "warnings": []}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.routes.knowledge.ks_client", fake_ks_client)

    _enable_knowledge_assist()
    response = client.get("/knowledge")

    assert response.status_code == 200
    assert "Knowledge Workspace" in response.text
    assert "Library" in response.text
    assert "Detail" in response.text
    assert "Add Documents" in response.text
    assert "evidence/reference documents" in response.text
    assert "OpenAPI or YAML contract specs belong in Step 2 Contract Source" in response.text
    assert "Supported here: .md, .csv, .sql, .xlsx, .pdf, .docx" in response.text
    assert "knowledge-upload-modal" in response.text
    assert "Select a document or field to view details." in response.text
    assert "No Knowledge Workspace documents yet" in response.text
    session = get_session()
    assert session.project_id is not None
    assert session.ks_project_id == session.project_id
    assert session.ks_active is True
    assert session.capabilities.knowledge_assist_enabled is True
    UUID(session.project_id.removeprefix("studio-ks-"))


def test_knowledge_workspace_reuses_restored_durable_linkage(monkeypatch):
    class FakeClient:
        def list_documents(self, project_id: str):
            return {"documents": [], "warnings": []}

        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {"fields": [], "warnings": []}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.routes.knowledge.ks_client", fake_ks_client)

    session = get_session()
    session.capabilities.knowledge_assist_enabled = True
    session.project_id = "workspace-123"
    session.ks_project_id = "workspace-123"
    session.ks_active = False
    save_session(session)

    response = client.get("/knowledge")

    assert response.status_code == 200
    refreshed = get_session()
    assert refreshed.project_id == "workspace-123"
    assert refreshed.ks_project_id == "workspace-123"
    assert refreshed.ks_active is True
    assert refreshed.capabilities.knowledge_assist_enabled is True


def test_knowledge_workspace_backfills_project_id_from_legacy_session_namespace(monkeypatch):
    class FakeClient:
        def list_documents(self, project_id: str):
            return {"documents": [], "warnings": []}

        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {"fields": [], "warnings": []}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.routes.knowledge.ks_client", fake_ks_client)

    session = get_session()
    session.capabilities.knowledge_assist_enabled = True
    session.project_id = None
    session.ks_project_id = "legacy-workspace"
    session.ks_active = False
    save_session(session)

    response = client.get("/knowledge")

    assert response.status_code == 200
    refreshed = get_session()
    assert refreshed.project_id == "legacy-workspace"
    assert refreshed.ks_project_id == "legacy-workspace"
    assert refreshed.ks_active is True
    assert refreshed.capabilities.knowledge_assist_enabled is True


def test_knowledge_workspace_shows_degraded_mode_warning(monkeypatch):
    @contextmanager
    def fake_ks_client(**kwargs):
        raise KSUnavailableError("mock KS unavailable")
        yield

    monkeypatch.setattr("app.routes.knowledge.ks_client", fake_ks_client)

    _enable_knowledge_assist()
    response = client.get("/knowledge")

    assert response.status_code == 200
    assert "Knowledge Workspace degraded mode" in response.text
    assert "mock KS unavailable" in response.text


def test_knowledge_workspace_groups_documents_and_field_catalog(monkeypatch):
    class FakeClient:
        def list_documents(self, project_id: str):
            return {
                "documents": [
                    {
                        "document_id": "doc-sql",
                        "name": "accounts.ddl.sql",
                        "doc_type": "sql",
                        "section_count": 2,
                        "field_count": 4,
                    },
                    {
                        "document_id": "doc-brd",
                        "name": "Q2 business requirements.pdf",
                        "doc_type": "pdf",
                        "section_count": 5,
                        "field_count": 0,
                    },
                    {
                        "document_id": "doc-map",
                        "name": "field-map.xlsx",
                        "doc_type": "excel",
                        "section_count": 1,
                        "field_count": 3,
                    },
                    {
                        "document_id": "doc-kafka",
                        "name": "kafka-payment-schema.json",
                        "doc_type": "json",
                        "section_count": 1,
                        "field_count": 2,
                        "status": "indexing",
                    },
                ],
                "warnings": [],
            }

        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {
                "fields": [
                    {
                        "entity": "Account",
                        "name": "account_id",
                        "type": "string",
                        "nullable": False,
                        "source_document": "accounts.ddl.sql",
                        "description": "Primary key",
                    },
                    {
                        "entity": "Account",
                        "name": "status",
                        "type": "string",
                        "nullable": True,
                        "source_document": "field-map.xlsx",
                        "description": "Lifecycle status",
                    },
                    {
                        "entity": "Payment",
                        "name": "payment_id",
                        "type": "string",
                        "nullable": False,
                        "source_document": "kafka-payment-schema.json",
                        "description": "Kafka payment id",
                    },
                ],
                "warnings": [],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.routes.knowledge.ks_client", fake_ks_client)

    _enable_knowledge_assist()
    response = client.get("/knowledge")

    assert response.status_code == 200
    assert "DDL / Schema" in response.text
    assert "BRD / Business" in response.text
    assert "Field Mappings" in response.text
    assert "Kafka Schemas" in response.text
    assert "accounts.ddl.sql" in response.text
    assert "Q2 business requirements.pdf" in response.text
    assert "field-map.xlsx" in response.text
    assert "kafka-payment-schema.json" in response.text
    assert 'action="/knowledge/delete"' in response.text
    assert "Removing this document may refresh or stale related suggestions and evidence." in response.text
    assert ">Remove</button>" in response.text
    assert "Account" in response.text
    assert "2 fields" in response.text
    assert "Payment" in response.text
    assert "1 field" in response.text
    assert "Indexing" in response.text


def test_knowledge_upload_rejects_unsupported_file_type():
    _enable_knowledge_assist()
    response = client.post(
        "/knowledge/upload",
        files={"document_file": ("notes.txt", b"hello", "text/plain")},
        data={"description": ""},
    )

    assert response.status_code == 400
    assert "Unsupported file type for Knowledge Workspace upload" in response.text
    assert ".md, .markdown" in response.text


def test_knowledge_upload_rejects_yaml_with_step2_guidance(monkeypatch):
    class FakeClient:
        def list_documents(self, project_id: str):
            return {"documents": [], "warnings": []}

        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {"fields": [], "warnings": []}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.routes.knowledge.ks_client", fake_ks_client)

    _enable_knowledge_assist()
    response = client.post(
        "/knowledge/upload",
        files={"document_file": ("account-openapi.yaml", b"openapi: 3.0.0", "text/yaml")},
        data={"description": ""},
    )

    assert response.status_code == 400
    assert "OpenAPI/YAML specs should be uploaded in Step 2 Contract Source." in response.text


def test_knowledge_upload_rejects_oversized_file_before_storage_or_ks(monkeypatch):
    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called for oversized uploads")
        yield

    def fake_workspace_dir(session):
        raise AssertionError("workspace upload storage should not be touched for oversized uploads")

    monkeypatch.setenv("EDGEFORGE_STUDIO_MAX_UPLOAD_BYTES", "5")
    monkeypatch.setattr("app.routes.knowledge.ks_client", fake_ks_client)
    monkeypatch.setattr("app.routes.knowledge.workspace_dir", fake_workspace_dir)

    _enable_knowledge_assist()
    response = client.post(
        "/knowledge/upload",
        files={"document_file": ("sample.md", b"# Hello", "text/markdown")},
        data={"description": "BRD draft"},
    )
    session = get_session()

    assert response.status_code == 413
    assert "Uploaded file exceeds the 5 bytes limit." in response.text
    assert session.project_id is None
    assert session.ks_project_id is None
    assert session.ks_active is False


def test_knowledge_upload_rejects_session_disk_quota_before_storage_or_ks(monkeypatch):
    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called for over-quota uploads")
        yield

    def fake_workspace_dir(session):
        raise AssertionError("workspace upload storage should not be touched for over-quota uploads")

    monkeypatch.setenv("EDGEFORGE_STUDIO_MAX_SESSION_DISK_BYTES", "5")
    monkeypatch.setattr("app.routes.knowledge.ks_client", fake_ks_client)
    monkeypatch.setattr("app.routes.knowledge.workspace_dir", fake_workspace_dir)

    _enable_knowledge_assist()
    response = client.post(
        "/knowledge/upload",
        files={"document_file": ("sample.md", b"# Hello", "text/markdown")},
        data={"description": "BRD draft"},
    )
    session = get_session()

    assert response.status_code == 413
    assert "Session workspace quota exceeded" in response.text
    assert session.project_id is None
    assert session.ks_project_id is None
    assert session.ks_active is False


def test_knowledge_upload_rejects_ks_db_quota_before_ks_call(monkeypatch):
    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when KS DB quota is exceeded")
        yield

    monkeypatch.setenv("EDGEFORGE_STUDIO_MAX_KS_DB_BYTES", "4")
    monkeypatch.setattr("app.routes.knowledge.ks_client", fake_ks_client)

    _enable_knowledge_assist()
    session = get_session()
    from app.services.ks_workspace import workspace_db_path

    db_path = Path(workspace_db_path(session))
    db_path.write_bytes(b"12345")
    save_session(session)

    response = client.post(
        "/knowledge/upload",
        files={"document_file": ("sample.md", b"# Hi", "text/markdown")},
        data={"description": "BRD draft"},
    )

    assert response.status_code == 413
    assert "Knowledge Workspace database quota exceeded" in response.text


def test_knowledge_workspace_lists_documents_when_ks_db_is_over_quota(monkeypatch):
    class FakeClient:
        def list_documents(self, project_id: str):
            return {
                "documents": [
                    {
                        "document_id": "doc-cleanup",
                        "name": "cleanup-candidate.md",
                        "doc_type": "markdown",
                        "section_count": 1,
                        "field_count": 0,
                    }
                ],
                "warnings": [],
            }

        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {"fields": [], "warnings": []}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setenv("EDGEFORGE_STUDIO_MAX_KS_DB_BYTES", "4")
    monkeypatch.setattr("app.routes.knowledge.ks_client", fake_ks_client)

    _enable_knowledge_assist()
    session = get_session()
    from app.services.ks_workspace import workspace_db_path

    db_path = Path(workspace_db_path(session))
    db_path.write_bytes(b"12345")
    save_session(session)

    response = client.get("/knowledge")

    assert response.status_code == 200
    assert "cleanup-candidate.md" in response.text
    assert "Knowledge Workspace database quota exceeded" not in response.text


def test_knowledge_upload_ingests_supported_file_and_deletes_temp_upload(monkeypatch):
    seen: dict[str, str | list[str]] = {}

    class FakeClient:
        def ingest_document(
            self,
            project_id: str,
            file_path: str,
            doc_type: str,
            tags=None,
            description=None,
        ):
            path = Path(file_path)
            seen["project_id"] = project_id
            seen["doc_type"] = doc_type
            seen["file_path"] = file_path
            seen["file_exists_during_call"] = str(path.exists())
            return {
                "document_id": "doc-1",
                "document_name": path.name,
            }

        def list_documents(self, project_id: str):
            return {
                "documents": [
                    {
                        "document_id": "doc-1",
                        "name": "sample.md",
                        "doc_type": "markdown",
                        "section_count": 1,
                        "field_count": 0,
                    }
                ],
                "warnings": [],
            }

        def read_document(self, project_id: str, document_id: str, section=None):
            return {
                "document_name": "sample.md",
                "text": "Uploaded markdown content",
                "citations": [{"section": "Intro"}],
                "warnings": [],
            }

        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {"fields": [], "warnings": []}

    @contextmanager
    def fake_ks_client(**kwargs):
        seen["db_path"] = kwargs["db_path"]
        seen["allowed_roots"] = kwargs["allowed_roots"]
        yield FakeClient()

    monkeypatch.setattr("app.routes.knowledge.ks_client", fake_ks_client)

    _enable_knowledge_assist()
    response = client.post(
        "/knowledge/upload",
        files={"document_file": ("sample.md", b"# Hello", "text/markdown")},
        data={"description": "BRD draft"},
    )

    assert response.status_code == 200
    assert "Ingested" in response.text
    assert seen["doc_type"] == "markdown"
    assert seen["file_exists_during_call"] == "True"
    assert not Path(seen["file_path"]).exists()
    session = get_session()
    assert seen["project_id"] == session.project_id
    workspace_root = Path(session.workspace_root or "")
    assert Path(str(seen["db_path"])).is_relative_to(workspace_root)
    assert Path(str(seen["db_path"])).name == "knowledge.sqlite3"
    allowed_roots = seen["allowed_roots"]
    assert isinstance(allowed_roots, list)
    assert all(Path(root).is_relative_to(workspace_root) for root in allowed_roots)
    assert session.ks_project_id == session.project_id
    assert session.ks_active is True
    assert session.capabilities.knowledge_assist_enabled is True


def test_knowledge_delete_removes_document_after_ks_confirms(monkeypatch):
    documents = [
        {
            "document_id": "doc-remove",
            "name": "stale-fields.csv",
            "doc_type": "csv",
            "section_count": 1,
            "field_count": 2,
        },
        {
            "document_id": "doc-keep",
            "name": "current-fields.csv",
            "doc_type": "csv",
            "section_count": 1,
            "field_count": 1,
        },
    ]
    calls: list[tuple[str, str]] = []

    class FakeClient:
        def list_documents(self, project_id: str):
            return {"documents": list(documents), "warnings": []}

        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {
                "fields": [
                    {
                        "entity": "Account",
                        "name": "account_id",
                        "type": "string",
                        "source_document": "current-fields.csv",
                    }
                ],
                "warnings": [],
            }

        def delete_document(self, project_id: str, document_id: str):
            calls.append((project_id, document_id))
            documents[:] = [doc for doc in documents if doc["document_id"] != document_id]
            return {"ok": True, "dependent_suggestions_refreshed": 3}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.routes.knowledge.ks_client", fake_ks_client)

    _enable_knowledge_assist()
    response = client.post(
        "/knowledge/delete",
        data={"document_id": "doc-remove", "document_name": "stale-fields.csv"},
    )
    session = get_session()

    assert response.status_code == 200
    assert calls == [(session.project_id, "doc-remove")]
    assert "Removed stale-fields.csv from the Knowledge Workspace." in response.text
    assert "3 dependent suggestions refreshed." in response.text
    assert 'href="/knowledge?document_id=doc-remove"' not in response.text
    assert 'value="doc-remove"' not in response.text
    assert "current-fields.csv" in response.text
    assert "account_id" in response.text


def test_knowledge_delete_is_allowed_when_ks_db_is_over_quota(monkeypatch):
    calls: list[tuple[str, str]] = []

    class FakeClient:
        def list_documents(self, project_id: str):
            return {"documents": [], "warnings": []}

        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {"fields": [], "warnings": []}

        def delete_document(self, project_id: str, document_id: str):
            calls.append((project_id, document_id))
            return {"ok": True}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setenv("EDGEFORGE_STUDIO_MAX_KS_DB_BYTES", "4")
    monkeypatch.setattr("app.routes.knowledge.ks_client", fake_ks_client)

    _enable_knowledge_assist()
    session = get_session()
    from app.services.ks_workspace import workspace_db_path

    db_path = Path(workspace_db_path(session))
    db_path.write_bytes(b"12345")
    save_session(session)

    response = client.post(
        "/knowledge/delete",
        data={"document_id": "doc-cleanup", "document_name": "cleanup-candidate.md"},
    )
    refreshed = get_session()

    assert response.status_code == 200
    assert calls == [(refreshed.project_id, "doc-cleanup")]
    assert "Removed cleanup-candidate.md from the Knowledge Workspace." in response.text
    assert "Knowledge Workspace database quota exceeded" not in response.text


def test_knowledge_delete_failure_keeps_document_visible(monkeypatch):
    class FakeClient:
        def list_documents(self, project_id: str):
            return {
                "documents": [
                    {
                        "document_id": "doc-stays",
                        "name": "still-here.md",
                        "doc_type": "markdown",
                        "section_count": 1,
                        "field_count": 0,
                    }
                ],
                "warnings": [],
            }

        def read_field_catalog(self, project_id: str, source=None, entity=None):
            return {"fields": [], "warnings": []}

        def delete_document(self, project_id: str, document_id: str):
            raise KSCallError("delete_document", "document is locked")

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.routes.knowledge.ks_client", fake_ks_client)

    _enable_knowledge_assist()
    response = client.post(
        "/knowledge/delete",
        data={"document_id": "doc-stays", "document_name": "still-here.md"},
    )

    assert response.status_code == 400
    assert "Document removal failed: document is locked" in response.text
    assert "still-here.md" in response.text


def test_knowledge_delete_redirects_when_assist_off_without_ks_call(monkeypatch):
    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when Knowledge Assist is off")
        yield

    monkeypatch.setattr("app.routes.knowledge.ks_client", fake_ks_client)

    response = client.post(
        "/knowledge/delete",
        data={"document_id": "doc-1", "document_name": "stale.md"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/?assist_notice=knowledge-off"


def test_knowledge_workspace_renders_search_viewer_and_field_catalog(monkeypatch):
    class FakeClient:
        def list_documents(self, project_id: str):
            return {
                "documents": [
                    {
                        "document_id": "doc-1",
                        "name": "fields.csv",
                        "doc_type": "csv",
                        "section_count": 1,
                        "field_count": 1,
                    }
                ],
                "warnings": [],
            }

        def search_documents(self, project_id: str, query: str, max_results: int = 20):
            assert query == "account"
            return {
                "results": [
                    {
                        "document_id": "doc-1",
                        "document_name": "fields.csv",
                        "score": 1.0,
                        "snippet": "account_id string Primary key",
                    }
                ],
                "warnings": [],
            }

        def read_document(self, project_id: str, document_id: str, section=None):
            return {
                "document_name": "fields.csv",
                "text": "entity,field_name\nAccount,account_id",
                "citations": [{"section": "CSV Field Catalog"}],
                "warnings": [],
            }

        def read_field_catalog(self, project_id: str, source=None, entity=None):
            assert entity == "Account"
            return {
                "fields": [
                    {
                        "entity": "Account",
                        "name": "account_id",
                        "type": "string",
                        "nullable": False,
                        "source_document": "fields.csv",
                        "description": "Primary key",
                    }
                ],
                "warnings": [],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.routes.knowledge.ks_client", fake_ks_client)

    _enable_knowledge_assist()
    response = client.get("/knowledge?q=account&document_id=doc-1&entity=Account")

    assert response.status_code == 200
    assert "fields.csv" in response.text
    assert "Search Results" in response.text
    assert "account_id string Primary key" in response.text
    assert "Document" in response.text
    assert "Citations" in response.text
    assert "entity,field_name" in response.text
    assert "View Account field set" in response.text
    assert "Primary key" in response.text


def test_knowledge_workspace_detail_links_urlencode_catalog_values(monkeypatch):
    entity_name = "Customer & Account"
    field_name = "billing status"

    class FakeClient:
        def list_documents(self, project_id: str):
            return {
                "documents": [
                    {
                        "document_id": "doc & 1",
                        "name": "Customer schema.md",
                        "doc_type": "markdown",
                        "section_count": 1,
                        "field_count": 1,
                    }
                ],
                "warnings": [],
            }

        def read_field_catalog(self, project_id: str, source=None, entity=None):
            assert entity in {None, "", entity_name}
            return {
                "fields": [
                    {
                        "entity": entity_name,
                        "name": field_name,
                        "type": "string",
                        "normalized_type": "varchar",
                        "length": 32,
                        "precision": 12,
                        "scale": 0,
                        "nullable": True,
                        "source_document": "Customer schema.md",
                        "source_location": "CSV row 7",
                        "confidence": 0.91,
                        "description": "Billing lifecycle status",
                    }
                ],
                "warnings": [],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.routes.knowledge.ks_client", fake_ks_client)

    _enable_knowledge_assist()
    response = client.get("/knowledge")

    encoded_entity = quote(entity_name)
    encoded_field = quote(field_name)
    encoded_document = quote("doc & 1")
    assert response.status_code == 200
    assert f'href="/knowledge?entity={encoded_entity}"' in response.text
    assert f'href="/knowledge?entity={encoded_entity}&amp;field={encoded_field}"' in response.text
    assert f'href="/knowledge?document_id={encoded_document}"' in response.text

    detail_response = client.get(f"/knowledge?entity={encoded_entity}&field={encoded_field}")

    assert detail_response.status_code == 200
    assert f"<code>Customer &amp; Account.{field_name}</code>" in detail_response.text
    assert "varchar" in detail_response.text
    assert "32" in detail_response.text
    assert "CSV row 7" in detail_response.text
    assert "0.91" in detail_response.text
    assert "Billing lifecycle status" in detail_response.text
