"""Step 5 — Downstream Interfaces."""

from __future__ import annotations

import re
import threading
from dataclasses import asdict

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.models.project import DownstreamInterface, FieldMapping, LayoutField, ProjectSession
from app.paths import TEMPLATE_DIR
from app.services import readiness_view
from app.services.csv_layout import (
    CsvLayoutError,
    materialize_csv_layout,
    prepare_csv_layout_for_export,
    project_csv_layout,
)
from app.services.edge_contract_file_inspector import inspect_file_contract_layout
from app.services.edge_contract_inspector import inspect_edge_contract_artifact
from app.services.edge_contracts import (
    EDGE_CONTRACT_TYPE_LABELS,
    FILE_CSV_TYPE,
    FILE_FIXED_WIDTH_TYPE,
    SOAP_WSDL_TYPE,
    XML_XSD_TYPE,
    _entity_field_inventory,
    clean_text,
    default_artifact_path,
    default_downstream_file_mapping_path,
    default_downstream_xml_mapping_path,
    default_sample_path,
    default_soap_operation_mapping_path,
    downstream_interface_from_payload,
    edge_contract_readiness,
    edge_contract_readiness_rows,
    validate_edge_contract_payload,
)
from app.services.edge_contracts import (
    edge_contract_validation_blockers as _validation_blockers,
)
from app.services.nav_context import build_nav_context
from app.services.session_context import get_current_session, save_current_session

router = APIRouter(prefix="/downstream")
templates = Jinja2Templates(directory=TEMPLATE_DIR)
_UUID_WIDTH = 36
_FIXED_WIDTH_ID_GUIDANCE = (
    "This field may contain a UUID-style identifier. Use length 36 unless "
    "the project has an explicit non-UUID identity strategy."
)
_SAVE_ONE_MUTATION_LOCK = threading.RLock()


def _slug(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (clean_text(name) or "").lower()).strip("-")


def _auto_derived_downstream_paths(iface: DownstreamInterface) -> dict[str, str | None]:
    """The artifact paths Studio would auto-derive for iface's current identity.

    A persisted path equal to its entry here was Studio-generated from the
    interface's name/type, so it is safe to regenerate when that identity
    changes. Anything else -- a custom path or a reviewed reference the author
    pointed Studio at (both are editable in Step 5 and round-trip through
    project save/open) -- is NOT identity-derived and must be preserved.
    """
    name, contract_type = iface.name, iface.type
    if contract_type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE}:
        mapping_default = default_downstream_file_mapping_path(name)
    elif contract_type == XML_XSD_TYPE:
        mapping_default = default_downstream_xml_mapping_path(name)
    elif contract_type == SOAP_WSDL_TYPE:
        mapping_default = default_soap_operation_mapping_path(name)
    else:
        mapping_default = None
    return {
        "spec": (
            default_artifact_path("downstream", name, contract_type)
            if contract_type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE}
            else None
        ),
        "mapping_path": mapping_default,
        "sample_path": default_sample_path("downstream", name, contract_type),
        "xsd_path": (
            default_artifact_path("downstream", name, contract_type)
            if contract_type == XML_XSD_TYPE
            else None
        ),
        "wsdl_path": (
            default_artifact_path("downstream", name, contract_type)
            if contract_type == SOAP_WSDL_TYPE
            else None
        ),
    }


def _downstream_soap_canonical_entity(raw: dict) -> str | None:
    config = raw.get("soap_canonical_invocation")
    if not isinstance(config, dict):
        return None
    return clean_text(config.get("entity"))


def _normalize_downstream_entity_name(raw: dict) -> dict:
    normalized = dict(raw)
    if clean_text(normalized.get("entity_name")):
        normalized["entity_name"] = clean_text(normalized.get("entity_name"))
        return normalized

    contract_type = clean_text(normalized.get("type")) or ""
    soap_mode = clean_text(normalized.get("soap_operation_mode")) or ""
    if contract_type == SOAP_WSDL_TYPE and soap_mode == "canonical":
        inferred_entity = _downstream_soap_canonical_entity(normalized)
        if inferred_entity:
            normalized["entity_name"] = inferred_entity
    return normalized


def _looks_like_id_field(name: str) -> bool:
    field_name = (name or "").strip()
    lower = field_name.lower()
    return (
        lower == "id"
        or lower.endswith("_id")
        or lower.endswith("-id")
        or field_name.endswith("Id")
        or field_name.endswith("ID")
    )


def _mapping_endpoint_name(value: str) -> str:
    return (value or "").strip().split(".")[-1]


def _build_fixed_width_id_warnings(
    interface_name: str,
    layout_fields: list[LayoutField],
    field_mappings: list[FieldMapping] | None = None,
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    mappings_by_target = {
        _mapping_endpoint_name(mapping.target): mapping
        for mapping in field_mappings or []
        if _mapping_endpoint_name(mapping.target)
    }
    for field in layout_fields:
        mapping = mappings_by_target.get(field.name)
        mapped_source_name = _mapping_endpoint_name(mapping.source) if mapping else ""
        mapped_target_name = _mapping_endpoint_name(mapping.target) if mapping else ""
        looks_like_id = (
            _looks_like_id_field(field.name)
            or _looks_like_id_field(mapped_source_name)
            or _looks_like_id_field(mapped_target_name)
        )
        if looks_like_id and field.length < _UUID_WIDTH:
            warnings.append({
                "interface": interface_name,
                "field": field.name,
                "message": (
                    f"{field.name} is length {field.length}. "
                    f"{_FIXED_WIDTH_ID_GUIDANCE}"
                ),
            })
    return warnings


def _downstream_family_fact(iface: DownstreamInterface) -> str | None:
    """A short, type-specific display fact for the triage board row — never
    used for readiness/state computation, purely descriptive (mirrors what
    the legacy per-interface card already lets the user see/edit)."""
    if iface.type == FILE_FIXED_WIDTH_TYPE:
        if not iface.layout_fields:
            return None
        mapped_targets = {
            _mapping_endpoint_name(mapping.target)
            for mapping in iface.field_mappings
            if _mapping_endpoint_name(mapping.target)
        }
        field_count = len(iface.layout_fields)
        mapped_count = sum(1 for field in iface.layout_fields if field.name in mapped_targets)
        col_label = "col" if field_count == 1 else "cols"
        return f"{field_count} {col_label} · {mapped_count}/{field_count} mapped"
    if iface.type == FILE_CSV_TYPE:
        if not iface.spec_content:
            return None
        projection = project_csv_layout(iface.spec_content)
        if projection.errors:
            return None
        return (
            f"delimiter {projection.delimiter_label} · "
            f"header {'true' if projection.has_header_row else 'false'}"
        )
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


def _build_downstream_interface(
    raw: dict,
    *,
    session,
) -> tuple[DownstreamInterface | None, list[dict[str, str]], list[str]]:
    """Build one downstream interface through the legacy validation path."""
    raw = _normalize_downstream_entity_name(dict(raw))
    name = clean_text(raw.get("name")) or ""
    if not name:
        return None, [], []
    iface_slug = _slug(name)
    contract_type = clean_text(raw.get("type")) or ""

    if contract_type == FILE_CSV_TYPE and raw.get("spec_content"):
        try:
            if raw.get("csv_layout_apply"):
                raw["spec_content"] = materialize_csv_layout(
                    raw.get("spec_content"),
                    name=name,
                    fields=raw.get("csv_layout_fields") or [],
                    delimiter=raw.get("csv_delimiter"),
                    has_header_row=raw.get("csv_has_header_row"),
                    expected_source_hash=clean_text(raw.get("csv_layout_source_hash")),
                )
            elif raw.get("csv_delimiter") is not None or raw.get("csv_has_header_row") is not None:
                projection = project_csv_layout(raw.get("spec_content"))
                if projection.errors:
                    raise CsvLayoutError(projection.errors[0])
                raw["spec_content"] = materialize_csv_layout(
                    raw.get("spec_content"),
                    name=name,
                    fields=projection.fields,
                    delimiter=raw.get("csv_delimiter", projection.delimiter),
                    has_header_row=raw.get(
                        "csv_has_header_row",
                        projection.has_header_row,
                    ),
                    expected_source_hash=clean_text(raw.get("csv_layout_source_hash")),
                )
            else:
                raw["spec_content"] = prepare_csv_layout_for_export(
                    raw.get("spec_content"),
                    name=name,
                )
        except CsvLayoutError as exc:
            return None, [], [str(exc)]
    elif contract_type == FILE_CSV_TYPE and raw.get("csv_layout_apply"):
        try:
            raw["spec_content"] = materialize_csv_layout(
                None,
                name=name,
                fields=raw.get("csv_layout_fields") or [],
                delimiter=raw.get("csv_delimiter"),
                has_header_row=raw.get("csv_has_header_row"),
                expected_source_hash=None,
            )
        except CsvLayoutError as exc:
            return None, [], [str(exc)]

    layout_fields = [
        LayoutField(
            name=f["name"],
            start=int(f["start"]),
            length=int(f["length"]),
            locked_start=bool(f.get("locked_start")),
        )
        for f in raw.get("layout_fields", [])
        if f.get("name") and f.get("start") and f.get("length")
    ]
    field_mappings = [
        FieldMapping(source=m["source"], target=m["target"])
        for m in raw.get("field_mappings", [])
        if m.get("source") and m.get("target")
    ]

    sample_content = raw.get("sample_content") or None
    validation_raw = dict(raw)
    validation_raw["type"] = contract_type
    if contract_type == FILE_FIXED_WIDTH_TYPE and not validation_raw.get("spec"):
        validation_raw["spec"] = f"downstream/{iface_slug}-layout.yaml"
    contract_errors = validate_edge_contract_payload(
        validation_raw,
        direction="downstream",
        session=session,
    )
    if contract_errors:
        return None, [], contract_errors

    iface = downstream_interface_from_payload(
        {
            **raw,
            "type": contract_type,
            "spec": raw.get("spec")
            or (
                f"downstream/{iface_slug}-layout.yaml"
                if contract_type == FILE_FIXED_WIDTH_TYPE
                else raw.get("spec")
            ),
            "mapping_path": raw.get("mapping_path")
            or (f"downstream/{iface_slug}-mapping.yaml" if field_mappings else None),
            "sample_content": sample_content,
        },
        layout_fields=layout_fields,
        field_mappings=field_mappings,
    )
    if contract_type == FILE_CSV_TYPE:
        exact_spec_content = raw.get("spec_content")
        iface.spec_content = exact_spec_content if isinstance(exact_spec_content, str) and exact_spec_content.strip() else None
    warnings: list[dict[str, str]] = []
    if iface.type == FILE_FIXED_WIDTH_TYPE:
        if not layout_fields:
            layout_message = (
                "No visual layout rows are saved. Studio will still export the reviewed "
                "layout/spec content when present."
                if iface.spec_content
                else "No visual layout rows are saved for this downstream interface."
            )
            warnings.append({"interface": name, "field": "", "message": layout_message})
        if not field_mappings:
            warnings.append(
                {
                    "interface": name,
                    "field": "",
                    "message": (
                        "No field mappings are saved. Full file operation/mapping authoring "
                        "is a later slice."
                    ),
                }
            )
        warnings.extend(_build_fixed_width_id_warnings(name, layout_fields, field_mappings))
    return iface, warnings, []


def _readiness_payload(session, name: str) -> dict | None:
    try:
        return asdict(readiness_view.item(session, f"dsi:{name}"))
    except KeyError:
        return None


def _downstream_board_metadata(session: ProjectSession, iface: DownstreamInterface) -> dict[str, str | None]:
    """Return the same display-only facts the board receives on a fresh render."""
    readiness = edge_contract_readiness(iface, direction="downstream", session=session)
    return {
        "artifact_path": readiness.artifact_path,
        "family_fact": _downstream_family_fact(iface),
    }


def _downstream_interface_payload(iface: DownstreamInterface) -> dict:
    payload = iface.model_dump(mode="json")
    if iface.type == FILE_CSV_TYPE:
        payload["csv_layout_projection"] = project_csv_layout(iface.spec_content).as_dict()
    return payload


def _replace_downstream_interface(
    interfaces: list[DownstreamInterface],
    saved: DownstreamInterface,
    *,
    original_name: str | None,
) -> list[DownstreamInterface]:
    """Replace in place; create-on-existing is an upsert and names stay unique."""
    replacement_name = original_name or saved.name
    replacement_index = next(
        (index for index, iface in enumerate(interfaces) if iface.name == replacement_name),
        None,
    )
    result: list[DownstreamInterface] = []
    inserted = False
    for index, iface in enumerate(interfaces):
        if index == replacement_index:
            result.append(saved)
            inserted = True
            continue
        if iface.name in {replacement_name, saved.name}:
            continue
        result.append(iface)
    if not inserted:
        result.append(saved)
    return result


@router.get("", response_class=HTMLResponse)
async def step5_get(request: Request, focus: str = ""):
    session = get_current_session(request)
    nav = build_nav_context(session, "/downstream")
    raw_entity_field_inventory = _entity_field_inventory(session)
    entity_field_inventory = {
        name: sorted(raw_entity_field_inventory[name])
        for name in sorted(raw_entity_field_inventory)
    }
    downstream_readiness_rows = edge_contract_readiness_rows(
        session.downstream_interfaces,
        direction="downstream",
        session=session,
    )
    focus_iface = next(
        (iface for iface in session.downstream_interfaces if iface.name == focus),
        None,
    )
    focus_name = focus_iface.name if focus_iface is not None else None
    focus_item = _readiness_payload(session, focus_name) if focus_name else None
    if focus_item is None:
        focus_name = None
    return templates.TemplateResponse(request, "step5_downstream.html", {
        "request": request,
        "session": session,
        "step": 5,
        "existing_downstreams": [_downstream_interface_payload(iface) for iface in session.downstream_interfaces],
        "edge_contract_type_labels": EDGE_CONTRACT_TYPE_LABELS,
        "edge_contract_readiness": downstream_readiness_rows,
        "downstream_readiness_items": readiness_view.items_for_step(session, 5),
        "focus_name": focus_name,
        "focus_item": focus_item,
        "focus_source_of_truth_version": str(session.project_revision),
        "entity_field_inventory": entity_field_inventory,
        "downstream_artifact_paths": {row.name: row.artifact_path for row in downstream_readiness_rows},
        "downstream_family_facts": {
            iface.name: _downstream_family_fact(iface) for iface in session.downstream_interfaces
        },
        "fixed_width_id_guidance_by_interface": {
            iface.name: _build_fixed_width_id_warnings(
                iface.name,
                iface.layout_fields,
                iface.field_mappings,
            )
            for iface in session.downstream_interfaces
            if iface.type == FILE_FIXED_WIDTH_TYPE
        },
        **nav,
    })


# Compatibility-only whole-list endpoint. The refreshed browser uses save-one.
@router.post("/save", response_class=JSONResponse)
async def step5_save(request: Request):
    """
    Body: {
      interfaces: [
        {
          name, system, type, version, entity_name,
          layout_fields: [{name, start, length}],
          field_mappings: [{source, target}],
          sample_content: str | null
        }
      ]
    }
    """
    body = await request.json()
    session = get_current_session(request)

    interfaces: list[DownstreamInterface] = []
    warnings: list[dict[str, str]] = []
    errors: list[str] = []
    for raw in body.get("interfaces", []):
        iface, iface_warnings, contract_errors = _build_downstream_interface(raw, session=session)
        name = clean_text(raw.get("name")) or ""
        warnings.extend(iface_warnings)
        if contract_errors:
            errors.extend(f"{name}: {error}" for error in contract_errors)
        elif iface is not None:
            interfaces.append(iface)

    if errors:
        return JSONResponse(
            {"ok": False, "errors": errors, "warnings": warnings},
            status_code=400,
        )

    session.downstream_interfaces = interfaces
    save_current_session(request, session)
    return JSONResponse({"ok": True, "count": len(interfaces), "warnings": warnings})


@router.post("/interface/save-one", response_class=JSONResponse)
async def save_downstream_interface(request: Request):
    body = await request.json()
    cached_session = get_current_session(request)
    with _SAVE_ONE_MUTATION_LOCK:
        session = _reload_session_for_save_one(request, cached_session)
        return _save_downstream_interface_body(request, body, session)


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


def _save_downstream_interface_body(
    request: Request,
    body: dict,
    session: ProjectSession,
) -> JSONResponse:
    raw = body.get("item")
    if not isinstance(raw, dict):
        blockers = _validation_blockers(["A downstream interface item is required."], "")
        return JSONResponse({"ok": False, "blockers": blockers}, status_code=400)

    original_name = clean_text(body.get("original_name"))
    supplied_version = clean_text(body.get("source_of_truth_version"))
    current_version = str(session.project_revision)
    if supplied_version is not None and supplied_version != current_version:
        fresh_name = original_name or clean_text(raw.get("name")) or ""
        fresh_iface = next(
            (
                iface
                for iface in session.downstream_interfaces
                if iface.name in {fresh_name, clean_text(raw.get("name"))}
            ),
            None,
        )
        return JSONResponse(
            {
                "ok": False,
                "error": "This downstream interface changed after the editor was opened.",
                "item": _downstream_interface_payload(fresh_iface) if fresh_iface else None,
                "readiness": (
                    _readiness_payload(session, fresh_iface.name) if fresh_iface else None
                ),
                "recovery": (
                    "review-current-item" if fresh_iface else "reload-current-list"
                ),
                "current_items": [
                    {"name": iface.name, "type": iface.type}
                    for iface in session.downstream_interfaces
                ],
                "source_of_truth_version": current_version,
            },
            status_code=409,
        )

    name = clean_text(raw.get("name")) or ""
    if not name:
        blockers = _validation_blockers(["Interface name is required."], clean_text(raw.get("type")) or "")
        return JSONResponse({"ok": False, "blockers": blockers}, status_code=400)
    duplicate_name = any(iface.name == name for iface in session.downstream_interfaces)
    if (original_name is None and duplicate_name) or (
        original_name and name != original_name and duplicate_name
    ):
        return JSONResponse(
            {
                "ok": False,
                "blockers": [
                    {
                        "code": "duplicate-name",
                        "label": f"A downstream interface named '{name}' already exists.",
                        "field_ref": "name",
                        "section_ref": "contract",
                    }
                ],
            },
            status_code=400,
        )

    existing_iface = next(
        (
            iface
            for iface in session.downstream_interfaces
            if iface.name == (original_name or name)
        ),
        None,
    )
    if existing_iface is not None:
        raw = {**existing_iface.model_dump(mode="json"), **raw}
        # A rename or contract-type change can leave the previously-derived
        # artifact paths pointing at the OLD identity -- the client never
        # resends mapping_path, and resends spec/sample_path/xsd_path/wsdl_path
        # only as the values the card loaded with, so the merge above otherwise
        # re-pins the old-name paths into the manifest and every future export
        # (E2E Finding 4: "mapping: downstream/<old-name>-mapping.yaml" surviving
        # a rename).
        #
        # Only Studio-GENERATED defaults are safe to invalidate. A custom path,
        # a reviewed reference (e.g. an author-supplied XSD), and any path the
        # client freshly submitted for the new type must all be preserved --
        # dropping those produced spurious 400s and discarded real references.
        # So invalidate a path field ONLY when it still equals the value the OLD
        # identity would have auto-derived AND the client did not submit a
        # different one; downstream_interface_from_payload then regenerates it
        # from the new identity. Content fields (spec_content, sample_content,
        # xsd_content, wsdl_content) are always preserved.
        if name != existing_iface.name or clean_text(raw.get("type")) != existing_iface.type:
            # A path counts as Studio-GENERATED only when the interface also
            # carries the content Studio writes to it. Matching the default
            # filename is not enough: a reference-only contract whose author
            # pointed xsd_path/wsdl_path/spec at a file that happens to equal
            # Studio's default name has no content to regenerate, so dropping it
            # just fails validation (the reference is the only source).
            generates_content = {
                "spec": bool(existing_iface.spec_content) or bool(existing_iface.layout_fields),
                # SOAP operation mappings are generated from the selected
                # operation, not field_mappings (package_writer gates the SOAP
                # mapping write on selected_operation_name); every other type's
                # mapping is generated from field_mappings.
                "mapping_path": (
                    bool(existing_iface.selected_operation_name)
                    if existing_iface.type == SOAP_WSDL_TYPE
                    else bool(existing_iface.field_mappings)
                ),
                "sample_path": bool(existing_iface.sample_content),
                "xsd_path": bool(existing_iface.xsd_content),
                "wsdl_path": bool(existing_iface.wsdl_content),
            }
            for field, old_default in _auto_derived_downstream_paths(existing_iface).items():
                existing_value = getattr(existing_iface, field)
                if (
                    old_default is not None
                    and generates_content.get(field)
                    and existing_value == old_default
                    and raw.get(field) == existing_value
                ):
                    raw.pop(field, None)

    saved, warnings, errors = _build_downstream_interface(raw, session=session)
    if errors or saved is None:
        blockers = _validation_blockers(
            errors or ["The downstream interface could not be saved."],
            clean_text(raw.get("type")) or "",
        )
        return JSONResponse({"ok": False, "blockers": blockers}, status_code=400)
    if saved.type not in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE, XML_XSD_TYPE, SOAP_WSDL_TYPE}:
        blockers = _validation_blockers(
            ["Only represented edge-contract interfaces can be saved from focus mode."],
            saved.type,
        )
        return JSONResponse({"ok": False, "blockers": blockers}, status_code=400)

    before = [iface.model_dump(mode="json") for iface in session.downstream_interfaces]
    updated = _replace_downstream_interface(
        session.downstream_interfaces,
        saved,
        original_name=original_name,
    )
    after = [iface.model_dump(mode="json") for iface in updated]
    if after != before:
        session.downstream_interfaces = updated
        session.project_revision = max(1, session.project_revision) + 1
        save_current_session(request, session)
        current_version = str(session.project_revision)

    readiness = _readiness_payload(session, saved.name)
    if readiness is None:  # Defensive: represented types must always resolve through readiness_view.
        raise RuntimeError(f"Saved downstream interface '{saved.name}' has no readiness item.")
    counts = readiness_view.step_counts(session)
    rail = [
        {"step": step, "count": values["count"], "attention": values["attention"]}
        for step, values in sorted(counts.items())
    ]
    return JSONResponse(
        {
            "ok": True,
            "item": _downstream_interface_payload(saved),
            "readiness": readiness,
            "board_metadata": _downstream_board_metadata(session, saved),
            "step_counts": counts,
            "rail": rail,
            "warnings": warnings,
            "source_of_truth_version": current_version,
        }
    )


@router.post("/edge-contract/inspect", response_class=JSONResponse)
async def inspect_edge_contract(request: Request):
    """Inspect pasted downstream XML/XSD or SOAP/WSDL content without saving project state."""
    body = await request.json()
    direction = clean_text(body.get("direction"))
    if direction != "downstream":
        return JSONResponse(
            {"ok": False, "errors": ["Contract direction is required and must be downstream."]},
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
    """Inspect pasted downstream file layout/spec and sample content without saving project state."""
    body = await request.json()
    direction = clean_text(body.get("direction"))
    if direction != "downstream":
        return JSONResponse(
            {"ok": False, "errors": ["Contract direction is required and must be downstream."]},
            status_code=400,
        )
    contract_type = clean_text(body.get("type")) or ""
    if contract_type not in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE}:
        return JSONResponse(
            {"ok": False, "errors": ["File inspection is available for file-fixed-width and file-csv contracts."]},
            status_code=400,
        )
    spec_content = body.get("spec_content") if isinstance(body.get("spec_content"), str) else ""
    inspection_content = spec_content
    csv_projection = None
    if contract_type == FILE_CSV_TYPE:
        source_projection = project_csv_layout(spec_content)
        csv_projection = source_projection
        requested_fields = body.get("csv_layout_fields") or []
        requested_source_hash = clean_text(body.get("csv_layout_source_hash"))
        inspected_text_was_sent = "csv_layout_inspected_text" in body
        source_is_current = (
            bool(requested_source_hash)
            and requested_source_hash == source_projection.source_hash
        ) or (
            inspected_text_was_sent
            and body.get("csv_layout_inspected_text") == spec_content
        ) or (
            not requested_source_hash and not inspected_text_was_sent
        )
        if (
            source_is_current
            and not source_projection.errors
            and (source_projection.fields or requested_fields)
        ):
            try:
                inspection_content = materialize_csv_layout(
                    spec_content,
                    name=clean_text(body.get("name")) or "inspected-csv",
                    fields=(
                        requested_fields
                        if body.get("csv_layout_apply") and requested_fields
                        else source_projection.fields
                    ),
                    delimiter=body.get("csv_delimiter", source_projection.delimiter),
                    has_header_row=body.get(
                        "csv_has_header_row",
                        source_projection.has_header_row,
                    ),
                    expected_source_hash=source_projection.source_hash,
                )
                effective_projection = project_csv_layout(inspection_content).as_dict()
                if body.get("csv_layout_apply") and requested_fields:
                    for projected, requested in zip(
                        effective_projection["fields"], requested_fields, strict=False
                    ):
                        if not isinstance(requested, dict):
                            continue
                        projected["original_name"] = requested.get("original_name") or ""
                        projected["original_column"] = requested.get("original_column")
                effective_projection["source_hash"] = source_projection.source_hash
                effective_projection["legacy_flat"] = source_projection.legacy_flat
                csv_projection = effective_projection
            except CsvLayoutError as exc:
                return JSONResponse(
                    {"ok": False, "errors": [str(exc)], "warnings": [], "layout": {}},
                    status_code=400,
                )
    result = inspect_file_contract_layout(
        contract_type,
        inspection_content,
        "" if body.get("sample_content") is None else str(body.get("sample_content")),
    )
    if contract_type == FILE_CSV_TYPE:
        projection_payload = (
            csv_projection.as_dict()
            if hasattr(csv_projection, "as_dict")
            else csv_projection
        )
        result["csv_layout_projection"] = projection_payload
        projection_errors = projection_payload.get("errors", []) if projection_payload else []
        if projection_errors:
            result["ok"] = False
            result["errors"] = projection_errors
    status_code = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status_code)


@router.get("/next")
async def step5_next():
    return RedirectResponse("/rules", status_code=303)
