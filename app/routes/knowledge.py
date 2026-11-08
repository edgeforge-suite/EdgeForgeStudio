"""Step 1 Knowledge Workspace routes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.integrations.ks_integration import KSCallError, KSUnavailableError
from app.middleware.upload_request_policy import upload_rejected_response
from app.models.project import ProjectSession
from app.paths import TEMPLATE_DIR
from app.services.csrf import require_form_csrf
from app.services.ks_lifecycle import ks_client
from app.services.ks_workspace import (
    current_workspace_identity,
    ensure_workspace_identity,
    mark_workspace_active,
    workspace_allowed_roots,
    workspace_db_path,
    workspace_dir,
)
from app.services.nav_context import build_nav_context
from app.services.path_resolver import PathResolutionError, contain_under_session_workspace
from app.services.quotas import QuotaExceededError, ensure_ks_db_quota, ensure_session_disk_quota
from app.services.session_context import (
    get_current_session,
    save_current_session_if_workspace_changed,
    workspace_session_marker,
)
from app.services.upload_limits import (
    KNOWLEDGE_UPLOAD_POLICY,
    UploadFilePolicyError,
    UploadTooLargeError,
    read_upload_limited,
    validate_upload_file,
)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATE_DIR)

_KS_SUPPORTED_UPLOAD_TYPES = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".csv": "csv",
    ".sql": "sql",
    ".xlsx": "excel",
    ".pdf": "pdf",
    ".docx": "docx",
}
_OPENAPI_SPEC_EXTENSIONS = {".yaml", ".yml"}
_KS_SUPPORTED_UPLOAD_HELP = [
    {"doc_type": "markdown", "extensions": ".md, .markdown"},
    {"doc_type": "csv", "extensions": ".csv"},
    {"doc_type": "sql", "extensions": ".sql"},
    {"doc_type": "excel", "extensions": ".xlsx"},
    {"doc_type": "pdf", "extensions": ".pdf"},
    {"doc_type": "docx", "extensions": ".docx"},
]

_DOCUMENT_GROUP_ORDER = [
    ("ddl-schema", "DDL / Schema"),
    ("business", "BRD / Business"),
    ("field-mapping", "Field Mappings"),
    ("kafka-schema", "Kafka Schemas"),
    ("other", "Other"),
]


def _safe_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).name).strip("-")
    return cleaned or "upload"


def _infer_doc_type(filename: str) -> str | None:
    return _KS_SUPPORTED_UPLOAD_TYPES.get(Path(filename).suffix.lower())


def _field_value(field: dict, *keys: str) -> object:
    for key in keys:
        value = field.get(key)
        if value not in (None, ""):
            return value
    return None


def _field_display_value(field: dict, *keys: str) -> object:
    value = _field_value(field, *keys)
    return "—" if value is None else value


def _knowledge_assist_enabled(session: ProjectSession) -> bool:
    return session.capabilities.knowledge_assist_enabled


def _redirect_to_step1_assist_off() -> RedirectResponse:
    return RedirectResponse("/?assist_notice=knowledge-off", status_code=303)


def _document_group_key(document: dict) -> str:
    doc_type = str(document.get("doc_type") or document.get("type") or "").lower()
    name = str(document.get("name") or document.get("document_name") or "").lower()
    haystack = f"{doc_type} {name}"
    if "kafka" in haystack and ("schema" in haystack or doc_type in {"json", "avro"}):
        return "kafka-schema"
    if any(token in haystack for token in ("sql", "ddl", "schema", "database")):
        return "ddl-schema"
    if any(token in haystack for token in ("brd", "business", "requirement", "pdf", "docx", "markdown")):
        return "business"
    if any(token in haystack for token in ("mapping", "csv", "xlsx", "excel", "field")):
        return "field-mapping"
    return "other"


def _document_status(document: dict) -> dict[str, str]:
    raw_status = str(document.get("status") or document.get("ingest_status") or "").strip().lower()
    error = str(document.get("error") or document.get("error_message") or "").strip()
    if error or raw_status in {"failed", "error", "parse_failed"}:
        return {"state": "failed", "label": "Failed", "symbol": "x"}
    if raw_status in {"indexing", "processing", "pending", "queued", "in_progress"}:
        return {"state": "indexing", "label": "Indexing", "symbol": "o"}
    return {"state": "ready", "label": "Ready", "symbol": "●"}


def _delete_document_status_message(result: dict, document_name: str) -> str:
    label = document_name.strip() or "document"
    count = (
        result.get("dependent_suggestions_refreshed")
        or result.get("invalidated_suggestions")
        or result.get("stale_suggestions")
        or result.get("suggestion_count")
    )
    suffix = ""
    if isinstance(count, int) and count > 0:
        suffix = f" {count} dependent suggestion{'s' if count != 1 else ''} refreshed."
    return (
        f"Removed {label} from the Knowledge Workspace.{suffix} "
        "Related suggestions and evidence may refresh."
    )


def _decorate_document(document: dict, selected_document_id: str | None) -> dict:
    document_id = str(document.get("document_id") or "")
    name = str(document.get("name") or document.get("document_name") or "Untitled document")
    return {
        **document,
        "document_id": document_id,
        "name": name,
        "doc_type": document.get("doc_type") or document.get("type") or "document",
        "section_count": document.get("section_count", "—"),
        "field_count": document.get("field_count", "—"),
        "chunk_count": document.get("chunk_count") or document.get("citation_count") or "—",
        "ingested_at": document.get("ingested_at") or document.get("created_at") or document.get("updated_at") or "—",
        "status": _document_status(document),
        "is_selected": bool(document_id and document_id == selected_document_id),
        "error": document.get("error") or document.get("error_message"),
    }


def _build_document_groups(documents: list[dict], selected_document_id: str | None) -> list[dict]:
    grouped = {
        key: {"key": key, "label": label, "items": [], "count": 0}
        for key, label in _DOCUMENT_GROUP_ORDER
    }
    for document in documents:
        decorated = _decorate_document(document, selected_document_id)
        group = grouped[_document_group_key(decorated)]
        group["items"].append(decorated)
        group["count"] += 1
    return [grouped[key] for key, _label in _DOCUMENT_GROUP_ORDER]


def _build_field_catalog_groups(field_catalog: list[dict], selected_entity: str = "", selected_field: str = "") -> list[dict]:
    groups_by_entity: dict[str, list[dict]] = {}
    for field in field_catalog:
        entity = str(field.get("entity") or "Unassigned")
        field_name = str(field.get("name") or field.get("field_name") or "")
        normalized_type = _field_value(field, "normalized_type", "type", "field_type") or "—"
        groups_by_entity.setdefault(entity, []).append(
            {
                **field,
                "entity": entity,
                "name": field_name,
                "type": normalized_type,
                "normalized_type": normalized_type,
                "length": _field_display_value(field, "length", "max_length", "character_maximum_length"),
                "precision": _field_display_value(field, "precision", "numeric_precision"),
                "scale": _field_display_value(field, "scale", "numeric_scale"),
                "source_document": _field_display_value(field, "source_document", "document_name", "source"),
                "source_location": _field_display_value(field, "source_location", "section", "location", "line"),
                "confidence": _field_display_value(field, "confidence", "confidence_score", "consistency_score"),
                "description": field.get("description") or "—",
                "is_selected": entity == selected_entity and field_name == selected_field,
            }
        )

    return [
        {
            "entity": entity,
            "count": len(fields),
            "fields": fields,
            "is_selected": entity == selected_entity and not selected_field,
        }
        for entity, fields in sorted(groups_by_entity.items(), key=lambda item: item[0].lower())
    ]


def _find_field_detail(field_catalog_groups: list[dict], selected_entity: str, selected_field: str) -> dict | None:
    if not selected_entity or not selected_field:
        return None
    for group in field_catalog_groups:
        if group["entity"] != selected_entity:
            continue
        for field in group["fields"]:
            if field["name"] == selected_field:
                return field
    return None


def _find_entity_detail(field_catalog_groups: list[dict], selected_entity: str) -> dict | None:
    if not selected_entity:
        return None
    for group in field_catalog_groups:
        if group["entity"] == selected_entity:
            return group
    return None


def _build_selected_detail(
    *,
    selected_document: dict | None,
    selected_document_id: str | None,
    documents: list[dict],
    field_catalog_groups: list[dict],
    selected_entity: str,
    selected_field: str,
) -> dict:
    if selected_document:
        document_meta = next(
            (
                _decorate_document(document, selected_document_id)
                for document in documents
                if str(document.get("document_id") or "") == selected_document_id
            ),
            None,
        )
        document_name = (
            selected_document.get("document_name")
            or selected_document.get("name")
            or (document_meta["name"] if document_meta else "Selected document")
        )
        return {
            "kind": "document",
            "document": {
                "document_id": selected_document_id,
                "document_name": document_name,
                "doc_type": document_meta["doc_type"] if document_meta else "document",
                "section_count": document_meta["section_count"] if document_meta else "—",
                "field_count": document_meta["field_count"] if document_meta else "—",
                "chunk_count": document_meta["chunk_count"] if document_meta else len(selected_document.get("citations", [])),
                "ingested_at": document_meta["ingested_at"] if document_meta else "—",
                "status": document_meta["status"] if document_meta else {"state": "ready", "label": "Ready", "symbol": "●"},
                "text": selected_document.get("text") or "",
                "citations": selected_document.get("citations", []),
            },
        }

    field_detail = _find_field_detail(field_catalog_groups, selected_entity, selected_field)
    if field_detail:
        return {"kind": "field", "field": field_detail}

    entity_detail = _find_entity_detail(field_catalog_groups, selected_entity)
    if entity_detail:
        return {"kind": "entity", "entity": entity_detail}

    return {"kind": "empty"}


def _build_workspace_context(
    request: Request,
    session: ProjectSession,
    *,
    status_message: str | None = None,
    status_type: str = "info",
    search_query: str = "",
    document_id: str | None = None,
    source_filter: str = "",
    entity_filter: str = "",
    field_filter: str = "",
    include_ks: bool = True,
) -> dict:
    workspace_before = workspace_session_marker(session)
    project_id = ensure_workspace_identity(session) if include_ks else current_workspace_identity(session)
    documents: list[dict] = []
    search_results: list[dict] = []
    search_warnings: list[str] = []
    selected_document: dict | None = None
    selected_document_warnings: list[str] = []
    field_catalog: list[dict] = []
    field_catalog_warnings: list[str] = []
    ks_warning: str | None = None
    ks_available = False

    if include_ks:
        try:
            with ks_client(
                allowed_roots=workspace_allowed_roots(session),
                db_path=workspace_db_path(session),
            ) as client:
                list_result = client.list_documents(project_id=project_id)
                documents = list_result.get("documents", [])

                if search_query.strip():
                    search_result = client.search_documents(
                        project_id=project_id,
                        query=search_query.strip(),
                        max_results=20,
                    )
                    search_results = search_result.get("results", [])
                    search_warnings = search_result.get("warnings", [])

                if document_id:
                    selected_document = client.read_document(
                        project_id=project_id,
                        document_id=document_id,
                    )
                    selected_document_warnings = selected_document.get("warnings", [])

                catalog_result = client.read_field_catalog(
                    project_id=project_id,
                    source=source_filter or None,
                    entity=entity_filter or None,
                )
                field_catalog = catalog_result.get("fields", [])
                field_catalog_warnings = catalog_result.get("warnings", [])
                mark_workspace_active(session)
                ks_available = True
        except KSUnavailableError as exc:
            ks_warning = f"Knowledge Server unavailable: {exc}"
        except KSCallError as exc:
            ks_warning = f"Knowledge Workspace request failed: {exc.error_message}"

    save_current_session_if_workspace_changed(request, session, workspace_before)

    nav = build_nav_context(session, "/")
    document_groups = _build_document_groups(documents, document_id)
    field_catalog_groups = _build_field_catalog_groups(field_catalog, entity_filter, field_filter)
    selected_detail = _build_selected_detail(
        selected_document=selected_document,
        selected_document_id=document_id,
        documents=documents,
        field_catalog_groups=field_catalog_groups,
        selected_entity=entity_filter,
        selected_field=field_filter,
    )
    return {
        "request": request,
        "session": session,
        "step": 1,
        "ks_project_id": project_id,
        "ks_available": ks_available,
        "ks_warning": ks_warning,
        "status_message": status_message,
        "status_type": status_type,
        "documents": documents,
        "document_groups": document_groups,
        "search_query": search_query,
        "search_results": search_results,
        "search_warnings": search_warnings,
        "selected_document": selected_document,
        "selected_document_id": document_id,
        "selected_document_warnings": selected_document_warnings,
        "field_catalog": field_catalog,
        "field_catalog_groups": field_catalog_groups,
        "field_catalog_warnings": field_catalog_warnings,
        "catalog_source": source_filter,
        "catalog_entity": entity_filter,
        "catalog_field": field_filter,
        "selected_detail": selected_detail,
        "supported_doc_types": _KS_SUPPORTED_UPLOAD_HELP,
        **nav,
    }


def _render_workspace(
    request: Request,
    session: ProjectSession,
    *,
    status_message: str | None = None,
    status_type: str = "info",
    search_query: str = "",
    document_id: str | None = None,
    source_filter: str = "",
    entity_filter: str = "",
    field_filter: str = "",
    status_code: int = 200,
    include_ks: bool = True,
) -> HTMLResponse:
    context = _build_workspace_context(
        request,
        session,
        status_message=status_message,
        status_type=status_type,
        search_query=search_query,
        document_id=document_id,
        source_filter=source_filter,
        entity_filter=entity_filter,
        field_filter=field_filter,
        include_ks=include_ks,
    )
    return templates.TemplateResponse(
        request,
        "knowledge_workspace.html",
        context,
        status_code=status_code,
    )


@router.get("/knowledge", response_class=HTMLResponse)
async def knowledge_workspace(
    request: Request,
    q: str = Query(""),
    document_id: Optional[str] = Query(None),
    source: str = Query(""),
    entity: str = Query(""),
    field: str = Query(""),
) -> HTMLResponse:
    session = get_current_session(request)
    if not _knowledge_assist_enabled(session):
        return _redirect_to_step1_assist_off()

    return _render_workspace(
        request,
        session,
        search_query=q,
        document_id=document_id,
        source_filter=source,
        entity_filter=entity,
        field_filter=field,
    )


@router.post("/knowledge/upload", response_class=HTMLResponse)
async def knowledge_upload(
    request: Request,
    _csrf: None = Depends(require_form_csrf),
    document_file: UploadFile = File(...),
    description: str = Form(""),
) -> HTMLResponse:
    session = get_current_session(request)
    if not _knowledge_assist_enabled(session):
        return _redirect_to_step1_assist_off()

    filename = document_file.filename or ""
    if not filename.strip():
        return _render_workspace(
            request,
            session,
            status_message="Choose a document file to upload into the Knowledge Workspace.",
            status_type="error",
            status_code=400,
        )

    doc_type = _infer_doc_type(filename)
    if doc_type is None:
        if Path(filename).suffix.lower() in _OPENAPI_SPEC_EXTENSIONS:
            return _render_workspace(
                request,
                session,
                status_message="OpenAPI/YAML specs should be uploaded in Step 2 Contract Source.",
                status_type="error",
                status_code=400,
            )
        supported = ", ".join(row["extensions"] for row in _KS_SUPPORTED_UPLOAD_HELP)
        return _render_workspace(
            request,
            session,
            status_message=(
                "Unsupported file type for Knowledge Workspace upload. "
                f"Supported extensions: {supported}."
            ),
            status_type="error",
            status_code=400,
        )

    try:
        validate_upload_file(document_file, policy=KNOWLEDGE_UPLOAD_POLICY)
    except UploadFilePolicyError as exc:
        return upload_rejected_response(
            path="/knowledge/upload",
            status_code=415,
            message=str(exc),
        )

    try:
        upload_bytes = await read_upload_limited(document_file)
    except UploadTooLargeError as exc:
        return _render_workspace(
            request,
            session,
            status_message=str(exc),
            status_type="error",
            status_code=413,
            include_ks=False,
        )

    try:
        ensure_session_disk_quota(session, additional_bytes=len(upload_bytes))
        ensure_ks_db_quota(session)
    except QuotaExceededError as exc:
        return _render_workspace(
            request,
            session,
            status_message=str(exc),
            status_type="error",
            status_code=413,
            include_ks=False,
        )
    except KSUnavailableError as exc:
        return _render_workspace(
            request, session, status_message=str(exc), status_type="error",
            status_code=400, include_ks=False,
        )

    workspace_before = workspace_session_marker(session)
    workspace_root = workspace_dir(session)
    save_current_session_if_workspace_changed(request, session, workspace_before)
    try:
        upload_dir = contain_under_session_workspace(session, workspace_root / "uploads")
        temp_path = contain_under_session_workspace(session, upload_dir / _safe_filename(filename))
    except PathResolutionError as exc:
        return _render_workspace(
            request, session, status_message=str(exc), status_type="error",
            status_code=400, include_ks=False,
        )
    upload_dir.mkdir(parents=True, exist_ok=True)
    temp_path.write_bytes(upload_bytes)

    try:
        with ks_client(
            allowed_roots=workspace_allowed_roots(session),
            db_path=workspace_db_path(session),
        ) as client:
            workspace_before = workspace_session_marker(session)
            project_id = ensure_workspace_identity(session)
            save_current_session_if_workspace_changed(request, session, workspace_before)
            result = client.ingest_document(
                project_id=project_id,
                file_path=str(temp_path),
                doc_type=doc_type,
                description=description.strip() or None,
            )
            workspace_before = workspace_session_marker(session)
            mark_workspace_active(session)
            save_current_session_if_workspace_changed(request, session, workspace_before)
    except KSUnavailableError as exc:
        return _render_workspace(
            request,
            session,
            status_message=f"Knowledge Workspace upload could not start because KS is unavailable: {exc}",
            status_type="warn",
        )
    except KSCallError as exc:
        return _render_workspace(
            request,
            session,
            status_message=f"Knowledge Workspace upload failed: {exc.error_message}",
            status_type="error",
            status_code=400,
        )
    finally:
        temp_path.unlink(missing_ok=True)

    return _render_workspace(
        request,
        session,
        status_message=(
            f"Ingested {result['document_name']} into the Knowledge Workspace "
            "linked to this Studio project."
        ),
        status_type="success",
        document_id=result["document_id"],
    )


@router.post("/knowledge/delete", response_class=HTMLResponse)
async def knowledge_delete_document(
    request: Request,
    _csrf: None = Depends(require_form_csrf),
    document_id: str = Form(""),
    document_name: str = Form(""),
) -> HTMLResponse:
    session = get_current_session(request)
    if not _knowledge_assist_enabled(session):
        return _redirect_to_step1_assist_off()

    normalized_document_id = document_id.strip()
    if not normalized_document_id:
        return _render_workspace(
            request,
            session,
            status_message="Choose a Knowledge Workspace document to remove.",
            status_type="error",
            status_code=400,
        )

    try:
        workspace_before = workspace_session_marker(session)
        project_id = ensure_workspace_identity(session)
        save_current_session_if_workspace_changed(request, session, workspace_before)
        with ks_client(
            allowed_roots=workspace_allowed_roots(session),
            db_path=workspace_db_path(session),
        ) as client:
            result = client.delete_document(
                project_id=project_id,
                document_id=normalized_document_id,
            )
            if result.get("ok") is False or result.get("success") is False:
                message = (
                    result.get("error")
                    or result.get("message")
                    or "Knowledge Server did not remove the document."
                )
                return _render_workspace(
                    request,
                    session,
                    status_message=f"Could not remove document: {message}",
                    status_type="error",
                    status_code=400,
                )
            workspace_before = workspace_session_marker(session)
            mark_workspace_active(session)
            save_current_session_if_workspace_changed(request, session, workspace_before)
    except KSUnavailableError as exc:
        return _render_workspace(
            request,
            session,
            status_message=f"Document removal could not start because KS is unavailable: {exc}",
            status_type="warn",
        )
    except KSCallError as exc:
        return _render_workspace(
            request,
            session,
            status_message=f"Document removal failed: {exc.error_message}",
            status_type="error",
            status_code=400,
        )

    return _render_workspace(
        request,
        session,
        status_message=_delete_document_status_message(result, document_name),
        status_type="success",
    )
