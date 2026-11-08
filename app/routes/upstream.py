"""Step 2 — Upstream API Ingestion."""

from __future__ import annotations

import threading
from copy import deepcopy
from dataclasses import asdict

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.models.project import ProjectSession, UpstreamInterface
from app.paths import TEMPLATE_DIR
from app.services import readiness_view
from app.services.edge_contract_file_inspector import inspect_file_contract_layout
from app.services.edge_contract_inspector import inspect_edge_contract_artifact
from app.services.edge_contracts import (
    EDGE_CONTRACT_TYPE_LABELS,
    EDGE_CONTRACT_TYPES,
    FILE_CSV_TYPE,
    FILE_FIXED_WIDTH_TYPE,
    SOAP_WSDL_TYPE,
    XML_XSD_TYPE,
    clean_text,
    default_artifact_path,
    default_sample_path,
    default_soap_operation_mapping_path,
    default_upstream_file_mapping_path,
    default_upstream_xml_mapping_path,
    edge_contract_readiness,
    edge_contract_readiness_rows,
    edge_contract_validation_blockers,
    payload_with_csv_controls,
    upstream_interface_from_payload,
    validate_edge_contract_payload,
)
from app.services.nav_context import build_nav_context
from app.services.openapi_service import (
    _component_schemas,
    _response_schema_refs,
    classify_openapi_spec,
    classify_schema,
    fetch_openapi_from_url,
    parse_openapi_text,
)
from app.services.session_context import get_current_session, save_current_session
from app.services.upload_limits import (
    OPENAPI_UPLOAD_POLICY,
    UploadFilePolicyError,
    UploadTooLargeError,
    read_upload_limited,
    validate_upload_file,
)

router = APIRouter(prefix="/upstream")
templates = Jinja2Templates(directory=TEMPLATE_DIR)
_SAVE_ONE_MUTATION_LOCK = threading.RLock()

# The focus editor is a static form, so these persisted fields have no control
# that can safely author them. Preserve them across focused edits instead of
# rebuilding them from a partial browser payload.
_FOCUSED_UPSTREAM_SAME_TYPE_FIELDS = (
    "spec_url",
    "mapping_path",
    "operation_mappings",
)
_FOCUSED_UPSTREAM_TEXT_FIELDS = (
    "system",
    "version",
    "spec",
    "spec_content",
    "entity_name",
    "xsd_path",
    "xsd_content",
    "root_element",
    "namespace",
    "namespace_alias",
    "wsdl_path",
    "wsdl_content",
    "service",
    "port",
    "binding",
    "soap_handler_method",
    "sample_path",
    "sample_content",
)


@router.get("", response_class=HTMLResponse)
async def step2_get(request: Request, focus: str = ""):
    session = get_current_session(request)
    nav = build_nav_context(session, "/upstream")
    edge_contract_readiness = edge_contract_readiness_rows(
        session.upstream_interfaces,
        direction="upstream",
        session=session,
    )
    saved_openapi_interfaces = [
        iface
        for iface in session.upstream_interfaces
        if iface.type not in EDGE_CONTRACT_TYPES and (iface.spec_url or iface.spec)
    ]
    upstream_csv_summaries = _upstream_csv_summaries(session.upstream_interfaces)
    has_openapi_classification = bool(
        session.classified_entities
        or (session.app_archetype == "passthrough-router" and session.classified_operations)
    )
    edge_contract_only = bool(edge_contract_readiness) and not (
        session.raw_spec_url
        or session.raw_spec_filename
        or saved_openapi_interfaces
        or has_openapi_classification
    )
    continue_href = "/passthrough" if session.app_archetype == "passthrough-router" else "/entities"
    if session.app_archetype == "passthrough-router":
        continue_label = "Continue to Route & Transform →"
        continue_copy = "Continue into constrained route and transform setup."
    elif edge_contract_only:
        continue_label = "Continue through wizard →"
        continue_copy = (
            "This edge-contract-only project can continue through the wizard even without "
            "OpenAPI-classified Step 3 entities."
        )
    else:
        continue_label = "Continue to Entity Model →"
        continue_copy = "Continue to Step 3 entity and operation modeling."
    focus_iface = next(
        (
            iface
            for iface in session.upstream_interfaces
            if iface.name == focus and iface.type in EDGE_CONTRACT_TYPES
        ),
        None,
    )
    focus_name = focus_iface.name if focus_iface is not None else None
    focus_item = _readiness_payload(session, focus_name) if focus_name else None
    if focus_item is None:
        focus_name = None
        focus_iface = None
    return templates.TemplateResponse(request, "step2_upstream.html", {
        "request": request,
        "session": session,
        "step": 2,
        "error": None,
        "edge_contract_type_labels": EDGE_CONTRACT_TYPE_LABELS,
        "edge_contract_readiness": edge_contract_readiness,
        "upstream_readiness_items": readiness_view.items_for_step(session, 2),
        "upstream_csv_summaries": upstream_csv_summaries,
        "upstream_artifact_paths": {
            row.name: row.artifact_path for row in edge_contract_readiness
        },
        "upstream_family_facts": {
            iface.name: _upstream_family_fact(iface)
            for iface in session.upstream_interfaces
            if iface.type in EDGE_CONTRACT_TYPES
        },
        "saved_openapi_interfaces": saved_openapi_interfaces,
        "edge_contract_only": edge_contract_only,
        "step2_continue_href": continue_href,
        "step2_continue_label": continue_label,
        "step2_continue_copy": continue_copy,
        "focus_name": focus_name,
        "focus_item": focus_item,
        "focus_interface": focus_iface.model_dump(mode="json") if focus_iface else None,
        "focus_source_of_truth_version": str(session.project_revision),
        **nav,
    })


def _upstream_csv_summaries(interfaces: list[UpstreamInterface]) -> dict[str, dict[str, str]]:
    summaries: dict[str, dict[str, str]] = {}
    for iface in interfaces:
        if iface.type != FILE_CSV_TYPE or not iface.spec_content:
            continue
        result = inspect_file_contract_layout(FILE_CSV_TYPE, iface.spec_content)
        if not result.get("ok"):
            continue
        layout = result.get("layout") or {}
        header = layout.get("has_header_row")
        summaries[iface.name] = {
            "delimiter": layout.get("delimiter") or ",",
            "delimiter_label": layout.get("delimiter_label") or "comma (,)",
            "header_row": "Not specified" if header is None else str(bool(header)).lower(),
        }
    return summaries


def _mapping_endpoint_name(value: str) -> str:
    return (clean_text(value) or "").rsplit(".", 1)[-1]


def _upstream_family_fact(iface: UpstreamInterface) -> str | None:
    """Return descriptive board metadata without participating in readiness."""
    if iface.type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE}:
        result = inspect_file_contract_layout(iface.type, iface.spec_content)
        if not result.get("ok"):
            return None
        layout = result.get("layout") or {}
        fields = [field for field in layout.get("fields") or [] if field.get("name")]
        if iface.type == FILE_CSV_TYPE:
            parts = []
            delimiter = layout.get("delimiter_label") or layout.get("delimiter")
            if delimiter:
                parts.append(f"delimiter {delimiter}")
            header = layout.get("has_header_row")
            if header is not None:
                parts.append(f"header {str(bool(header)).lower()}")
            return " · ".join(parts) or None
        if not fields:
            return None
        mapped_sources = {
            _mapping_endpoint_name(mapping.source)
            for mapping in iface.field_mappings
            if _mapping_endpoint_name(mapping.source)
        }
        field_count = len(fields)
        mapped_count = sum(1 for field in fields if field["name"] in mapped_sources)
        col_label = "col" if field_count == 1 else "cols"
        return f"{field_count} {col_label} · {mapped_count}/{field_count} mapped"
    if iface.type == XML_XSD_TYPE:
        if not iface.root_element:
            return None
        fact = f"root {iface.root_element}"
        if iface.namespace:
            fact += f" · {iface.namespace}"
        return fact
    if iface.type == SOAP_WSDL_TYPE:
        if not iface.selected_operation_name:
            return None
        mode = "canonical" if iface.soap_operation_mode == "canonical" else "adapter-only"
        return f"operation {iface.selected_operation_name} · {mode}"
    return None


def _upstream_board_metadata(
    session: ProjectSession,
    iface: UpstreamInterface,
) -> dict[str, str | None]:
    """Return the same display-only facts the board receives on a fresh render."""
    readiness = edge_contract_readiness(iface, direction="upstream", session=session)
    return {
        "artifact_path": readiness.artifact_path,
        "family_fact": _upstream_family_fact(iface),
    }


@router.post("/ingest-url", response_class=JSONResponse)
async def ingest_url(request: Request, spec_url: str = Form(...)):
    """Fetch OpenAPI from URL and classify. Returns JSON for JS to render."""
    try:
        spec = fetch_openapi_from_url(spec_url)
        entities, operations = classify_openapi_spec(spec)
        session = get_current_session(request)
        # Set URL source; clear file source so entities.py never carries stale filename
        session.raw_spec_url = spec_url
        session.raw_spec_filename = None   # clear: switching away from file mode
        import yaml
        session.raw_spec_content = yaml.dump(spec, default_flow_style=False)
        session.classified_entities = entities
        session.classified_operations = operations
        save_current_session(request, session)
        return JSONResponse({
            "ok": True,
            "entities": [e.model_dump() for e in entities],
            "operations": [o.model_dump() for o in operations],
        })
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@router.post("/ingest-file", response_class=JSONResponse)
async def ingest_file(request: Request, spec_file: UploadFile = File(...)):
    """Upload OpenAPI spec file and classify."""
    try:
        validate_upload_file(spec_file, policy=OPENAPI_UPLOAD_POLICY)
        content = (await read_upload_limited(spec_file)).decode("utf-8")
        spec = parse_openapi_text(content)
        entities, operations = classify_openapi_spec(spec)
        session = get_current_session(request)
        # Set file source; clear URL source so entities.py never carries stale url
        session.raw_spec_url = None        # clear: switching away from URL mode
        session.raw_spec_content = content
        session.raw_spec_filename = spec_file.filename
        session.classified_entities = entities
        session.classified_operations = operations
        save_current_session(request, session)
        return JSONResponse({
            "ok": True,
            "entities": [e.model_dump() for e in entities],
            "operations": [o.model_dump() for o in operations],
        })
    except UploadTooLargeError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=413)
    except UploadFilePolicyError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=415)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@router.post("/save-samples", response_class=JSONResponse)
async def save_samples(request: Request):
    """Save manually entered samples (no OpenAPI spec) — exploration mode only."""
    body = await request.json()
    session = get_current_session(request)
    # Clear ALL source fields: manual mode has no spec or spec_url.
    # Leaving raw_spec_filename set would cause entities.py to build a
    # spec: upstream/<filename> entry in the manifest even though the file
    # is never written, making the package non-exportable silently.
    session.raw_spec_content = None
    session.raw_spec_url = None
    session.raw_spec_filename = None   # must also clear filename
    # Store placeholder entity from manual mode
    from app.models.project import ClassifiedEntity
    entity_name = body.get("entity_name", "Entity")
    session.classified_entities = [
        ClassifiedEntity(
            name=entity_name,
            classification="entity",
            confidence="inferred",
            reason="Manually defined entity (no OpenAPI spec)",
        )
    ]
    session.classified_operations = []
    save_current_session(request, session)
    return JSONResponse({"ok": True})


@router.post("/edge-contract/save", response_class=JSONResponse)
async def save_edge_contract(request: Request):
    """Save reviewed upstream edge-contract metadata without parsing/classifying it."""
    request_body = await request.json()
    cached_session = get_current_session(request)
    with _SAVE_ONE_MUTATION_LOCK:
        session = _reload_session_for_save_one(request, cached_session)
        return _save_edge_contract_body(request, request_body, session)


def _reload_session_for_save_one(
    request: Request,
    cached_session: ProjectSession,
) -> ProjectSession:
    if not cached_session.session_id:
        return cached_session
    store = getattr(request.state, "session_store", None)
    if store is None:
        return cached_session
    session = store.load(cached_session.session_id)
    request.state.studio_session = session
    return session


def _readiness_payload(session: ProjectSession, name: str | None) -> dict | None:
    if not name:
        return None
    try:
        return asdict(readiness_view.item(session, f"usc:{name}"))
    except KeyError:
        return None


def _replace_upstream_interface(
    interfaces: list[UpstreamInterface],
    saved: UpstreamInterface,
    *,
    original_name: str | None,
) -> list[UpstreamInterface]:
    if original_name is None:
        # Preserve the legacy add/upsert behavior: same-name rows are replaced
        # and the saved row is appended.
        return [iface for iface in interfaces if iface.name != saved.name] + [saved]

    replacement_index = next(
        (index for index, iface in enumerate(interfaces) if iface.name == original_name),
        None,
    )
    result: list[UpstreamInterface] = []
    inserted = False
    for index, iface in enumerate(interfaces):
        if index == replacement_index:
            result.append(saved)
            inserted = True
            continue
        if iface.name in {original_name, saved.name}:
            continue
        result.append(iface)
    if not inserted:
        result.append(saved)
    return result


def _validation_error_response(errors: list[str], contract_type: str) -> JSONResponse:
    return JSONResponse(
        {
            "ok": False,
            "errors": errors,
            "blockers": edge_contract_validation_blockers(errors, contract_type),
        },
        status_code=400,
    )


def _upstream_derived_default_paths(iface: UpstreamInterface, name: str) -> dict[str, str]:
    """The artifact paths write_package_result would auto-derive for *iface* from
    ``name``, for each field it currently has the content to (re)generate.

    Mirrors the upstream branch of write_package_result (and the sample-path
    default in upstream_interface_from_payload) so a rename can tell a
    Studio-GENERATED default apart from an author-supplied path: only a value
    equal to one of these is safe to re-point. Focus mode saves EDGE_CONTRACT_TYPES
    only, so only those derivations can appear here.
    """
    defaults: dict[str, str] = {}
    if iface.type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE} and iface.spec_content:
        defaults["spec"] = default_artifact_path("upstream", name, iface.type)
    if iface.type == XML_XSD_TYPE and iface.xsd_content:
        defaults["xsd_path"] = default_artifact_path("upstream", name, iface.type)
    if iface.type == SOAP_WSDL_TYPE and iface.wsdl_content:
        defaults["wsdl_path"] = default_artifact_path("upstream", name, iface.type)
    if iface.sample_content:
        defaults["sample_path"] = default_sample_path("upstream", name, iface.type)
    if iface.type == SOAP_WSDL_TYPE and iface.selected_operation_name:
        defaults["mapping_path"] = default_soap_operation_mapping_path(name)
    elif iface.type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE} and iface.field_mappings and iface.entity_name:
        defaults["mapping_path"] = default_upstream_file_mapping_path(name)
    elif iface.type == XML_XSD_TYPE and iface.field_mappings and iface.entity_name:
        defaults["mapping_path"] = default_upstream_xml_mapping_path(name)
    return defaults


def _repoint_renamed_upstream_default_paths(
    saved: UpstreamInterface, existing: UpstreamInterface
) -> None:
    """A rename keeps the contract type but changes the identity Studio derives
    artifact paths from. A derived path still equal to the OLD identity's default
    (mapping_path is copied verbatim above; spec/xsd_path/wsdl_path/sample_path are
    re-pinned when the static form resends the value the card loaded with) would
    otherwise survive into the manifest and every future export pointing at the
    old name -- the upstream parallel of the downstream E2E Finding 4 fix in
    routes/downstream.py. Re-point ONLY such Studio-generated defaults to the new
    identity; an author-supplied or custom path never equals the old default, so
    it is left untouched.
    """
    if existing.name == saved.name:
        return
    old_defaults = _upstream_derived_default_paths(existing, existing.name)
    new_defaults = _upstream_derived_default_paths(existing, saved.name)
    for field, old_default in old_defaults.items():
        if getattr(saved, field, None) == old_default:
            setattr(saved, field, new_defaults[field])


def _preserve_unposted_upstream_fields(
    saved: UpstreamInterface,
    existing: UpstreamInterface | None,
    body: dict,
) -> UpstreamInterface:
    """Merge a focused form payload without discarding state it cannot edit."""
    if existing is None:
        return saved

    # ``is_draft`` is type-neutral. The focus form cannot edit it, but an
    # intentional type change must rebuild every type-specific field below.
    saved.is_draft = deepcopy(existing.is_draft)
    if existing.type != saved.type:
        return saved

    for field in _FOCUSED_UPSTREAM_SAME_TYPE_FIELDS:
        setattr(saved, field, deepcopy(getattr(existing, field)))

    # Operation samples are not part of Step 2's static form. Keep their rich
    # request/response state and add a newly selected operation if necessary.
    saved_operations = deepcopy(existing.operations)
    if saved.selected_operation_name and not any(
        operation.name == saved.selected_operation_name for operation in saved_operations
    ):
        saved_operations.extend(deepcopy(saved.operations))
    saved.operations = saved_operations

    # Form controls trim textual values before posting. Reuse the persisted
    # spelling when its normalized value is unchanged so an untouched save is
    # a true model no-op rather than a whitespace-only revision.
    if existing.type == saved.type:
        for field in _FOCUSED_UPSTREAM_TEXT_FIELDS:
            existing_value = getattr(existing, field)
            if isinstance(existing_value, str) and clean_text(body.get(field)) == clean_text(existing_value):
                setattr(saved, field, existing_value)

    _repoint_renamed_upstream_default_paths(saved, existing)
    return saved


def _save_edge_contract_body(
    request: Request,
    request_body: dict,
    session: ProjectSession,
) -> JSONResponse:
    if not isinstance(request_body, dict):
        return _validation_error_response(["An upstream interface item is required."], "")
    wrapped_item = request_body.get("item")
    focused_request = "item" in request_body
    if focused_request and not isinstance(wrapped_item, dict):
        return _validation_error_response(["An upstream interface item is required."], "")

    raw = wrapped_item if focused_request else request_body
    original_name = clean_text(request_body.get("original_name"))
    supplied_version = clean_text(request_body.get("source_of_truth_version"))
    current_version = str(session.project_revision)
    if supplied_version is not None and supplied_version != current_version:
        # A rename draft may collide with another current item. Recovery must
        # identify only the row the editor opened, never the proposed new name.
        fresh_name = original_name if original_name is not None else clean_text(raw.get("name"))
        fresh_iface = next(
            (
                iface
                for iface in session.upstream_interfaces
                if fresh_name is not None and iface.name == fresh_name
            ),
            None,
        )
        return JSONResponse(
            {
                "ok": False,
                "error": "This upstream interface changed after the editor was opened.",
                "item": fresh_iface.model_dump(mode="json") if fresh_iface else None,
                "readiness": (
                    _readiness_payload(session, fresh_iface.name) if fresh_iface else None
                ),
                "recovery": "review-current-item" if fresh_iface else "reload-current-list",
                "current_items": [
                    {"name": iface.name, "type": iface.type}
                    for iface in session.upstream_interfaces
                ],
                "source_of_truth_version": current_version,
            },
            status_code=409,
        )

    body = payload_with_csv_controls(raw)
    direction = clean_text(body.get("direction"))
    if direction != "upstream":
        return _validation_error_response(
            ["Contract direction is required and must be upstream."],
            clean_text(body.get("type")) or "",
        )

    errors = validate_edge_contract_payload(body, direction="upstream", session=session)
    if errors:
        return _validation_error_response(errors, clean_text(body.get("type")) or "")

    iface = upstream_interface_from_payload(body)
    existing_original = next(
        (
            existing
            for existing in session.upstream_interfaces
            if original_name is not None and existing.name == original_name
        ),
        None,
    )
    if focused_request:
        iface = _preserve_unposted_upstream_fields(iface, existing_original, body)
    if focused_request and iface.type not in EDGE_CONTRACT_TYPES:
        return _validation_error_response(
            ["Only represented edge-contract interfaces can be saved from focus mode."],
            iface.type,
        )

    duplicate_name = any(existing.name == iface.name for existing in session.upstream_interfaces)
    if focused_request and (
        (original_name is None and duplicate_name)
        or (original_name and iface.name != original_name and duplicate_name)
    ):
        error = f"An upstream interface named '{iface.name}' already exists."
        return JSONResponse(
            {
                "ok": False,
                "errors": [error],
                "blockers": [
                    {
                        "code": "duplicate-name",
                        "label": error,
                        "field_ref": "name",
                        "section_ref": "contract",
                    }
                ],
            },
            status_code=400,
        )

    before = [existing.model_dump(mode="json") for existing in session.upstream_interfaces]
    updated = _replace_upstream_interface(
        session.upstream_interfaces,
        iface,
        original_name=original_name,
    )
    after = [existing.model_dump(mode="json") for existing in updated]
    if after != before:
        session.upstream_interfaces = updated
        session.project_revision = max(1, session.project_revision) + 1
        save_current_session(request, session)
        current_version = str(session.project_revision)

    saved_item = iface.model_dump(mode="json")
    readiness = _readiness_payload(session, iface.name)
    if focused_request and readiness is None:
        raise RuntimeError(f"Saved upstream interface '{iface.name}' has no readiness item.")
    counts = readiness_view.step_counts(session)
    rail = [
        {"step": step, "count": values["count"], "attention": values["attention"]}
        for step, values in sorted(counts.items())
    ]
    return JSONResponse(
        {
            "ok": True,
            "message": f"Saved upstream {iface.type} contract reference for {iface.name}.",
            "interface": saved_item,
            "item": saved_item,
            "readiness": readiness,
            "board_metadata": _upstream_board_metadata(session, iface),
            "step_counts": counts,
            "rail": rail,
            "warnings": readiness.get("warnings", []) if readiness else [],
            "source_of_truth_version": current_version,
        }
    )


@router.post("/edge-contract/inspect", response_class=JSONResponse)
async def inspect_edge_contract(request: Request):
    """Inspect pasted upstream XML/XSD or SOAP/WSDL content without saving project state."""
    body = await request.json()
    direction = clean_text(body.get("direction"))
    if direction != "upstream":
        return JSONResponse(
            {"ok": False, "errors": ["Contract direction is required and must be upstream."]},
            status_code=400,
        )

    result = inspect_edge_contract_artifact(
        clean_text(body.get("type")) or "",
        clean_text(body.get("content")) or "",
    )
    status_code = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status_code)


@router.post("/edge-contract/file-inspect", response_class=JSONResponse)
async def inspect_file_edge_contract(request: Request):
    """Inspect pasted upstream file layout/spec and sample content without saving project state."""
    body = payload_with_csv_controls(await request.json())
    direction = clean_text(body.get("direction"))
    if direction != "upstream":
        return JSONResponse(
            {"ok": False, "errors": ["Contract direction is required and must be upstream."]},
            status_code=400,
        )
    contract_type = clean_text(body.get("type")) or ""
    if contract_type not in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE}:
        return JSONResponse(
            {"ok": False, "errors": ["File inspection is available for file-fixed-width and file-csv contracts."]},
            status_code=400,
        )
    result = inspect_file_contract_layout(
        contract_type,
        clean_text(body.get("spec_content")) or "",
        "" if body.get("sample_content") is None else str(body.get("sample_content")),
    )
    status_code = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status_code)


@router.get("/classify-debug", response_class=JSONResponse)
async def classify_debug(request: Request):
    """Return per-schema classification detail for the current session's spec.

    Useful for diagnosing why certain schemas aren't appearing as entities in Step 3.
    Call GET /upstream/classify-debug after ingesting a spec in Step 2.
    """
    session = get_current_session(request)
    if not session.raw_spec_content:
        return JSONResponse({"ok": False, "error": "No spec ingested yet. Complete Step 2 first."})
    import yaml as _yaml
    spec = _yaml.safe_load(session.raw_spec_content)
    schemas = _component_schemas(spec)
    response_refs = _response_schema_refs(spec)
    rows = []
    for name, schema_def in schemas.items():
        classification = classify_schema(name, schema_def, response_refs)
        rows.append({
            "name": name,
            "classification": classification,
            "in_response_refs": name in response_refs,
            "has_direct_properties": isinstance(schema_def.get("properties"), dict),
            "has_allof_properties": any(
                isinstance(v.get("properties"), dict)
                for v in schema_def.get("allOf", []) + schema_def.get("anyOf", []) + schema_def.get("oneOf", [])
                if isinstance(v, dict)
            ),
        })
    rows.sort(key=lambda r: (r["classification"], r["name"]))
    return JSONResponse({
        "ok": True,
        "total_schemas": len(rows),
        "response_refs": sorted(response_refs),
        "by_classification": {
            "entity": [r for r in rows if r["classification"] == "entity"],
            "dto": [r for r in rows if r["classification"] == "dto"],
            "infrastructure": [r for r in rows if r["classification"] == "infrastructure"],
        },
    })


@router.get("/next", response_class=HTMLResponse)
async def step2_next(request: Request):
    session = get_current_session(request)
    next_path = "/passthrough" if session.app_archetype == "passthrough-router" else "/entities"
    return RedirectResponse(next_path, status_code=303)
