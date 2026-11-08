"""Step 4 — Data Handoffs."""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import asdict

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.models.project import DataHandoff, FieldMapping, ProjectSession
from app.paths import TEMPLATE_DIR
from app.services import readiness_view
from app.services.edge_contracts import EDGE_CONTRACT_TYPES, clean_package_path, clean_text
from app.services.nav_context import build_nav_context
from app.services.session_context import get_current_session, save_current_session
from app.services.staging_ddl_validation import (
    extract_column_names_from_ddl,
    extract_table_identifier_from_create_ddl,
    parse_columns_from_create_ddl,
    table_name_matches_create_identifier,
)

router = APIRouter(prefix="/handoffs")
templates = Jinja2Templates(directory=TEMPLATE_DIR)
logger = logging.getLogger(__name__)
_SAVE_ONE_MUTATION_LOCK = threading.RLock()


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _existing_handoff_payloads(session) -> list[dict]:
    payloads: list[dict] = []
    for handoff in session.data_handoffs:
        item = handoff.model_dump(mode="json")
        if handoff.ddl_content:
            parsed = parse_columns_from_create_ddl(handoff.ddl_content)
            if parsed:
                item["parsed_table_name"] = parsed["table_name"]
                item["structured_columns"] = parsed["columns"]
        payloads.append(item)
    return payloads


def _has_edge_contract_interfaces(session) -> bool:
    return any(
        iface.type in EDGE_CONTRACT_TYPES
        for iface in [*session.upstream_interfaces, *session.downstream_interfaces]
    )


def _has_openapi_entity_classification(session) -> bool:
    return any(entity.classification == "entity" for entity in session.classified_entities)


def _handoff_board_fact(handoff: DataHandoff) -> str | None:
    """Table name + column/mapping coverage for the triage board row — display only."""
    if not handoff.ddl_content:
        return None
    column_names = extract_column_names_from_ddl(handoff.ddl_content)
    if column_names is None:
        return handoff.table_name or None
    mapped_targets = {m.target.strip().lower() for m in handoff.field_mappings if m.target}
    mapped_count = sum(1 for name in column_names if name.strip().lower() in mapped_targets)
    col_count = len(column_names)
    col_label = "col" if col_count == 1 else "cols"
    fact = f"{col_count} {col_label} · {mapped_count}/{col_count} mapped"
    return f"{handoff.table_name} · {fact}" if handoff.table_name else fact


def _handoff_board_metadata(handoff: DataHandoff) -> dict[str, str | None]:
    """Return the same display-only fact the board receives on a fresh render."""
    return {"fact": _handoff_board_fact(handoff)}


def _build_one_handoff(
    raw: dict,
    *,
    session: ProjectSession,
    existing_handoffs: dict[str, DataHandoff],
) -> tuple[DataHandoff | None, list[str], list[str]]:
    """Build one handoff through the legacy whole-list validation path."""
    del session  # Reserved for parity with other per-item builders.
    name = clean_text(raw.get("name")) or ""
    if not name:
        return None, [], []

    warnings: list[str] = []
    errors: list[str] = []
    original_name = clean_text(raw.get("original_name")) or ""
    existing_handoff = existing_handoffs.get(original_name) or existing_handoffs.get(name)
    raw_ddl = raw.get("ddl_content")
    ddl = raw_ddl if isinstance(raw_ddl, str) and raw_ddl.strip() else None
    visible_table_name = clean_text(raw.get("table_name"))
    table_identifier = extract_table_identifier_from_create_ddl(ddl) if ddl else None
    table_name = table_identifier["name"] if table_identifier else visible_table_name
    handoff_slug = _slug(name)

    if (
        ddl
        and visible_table_name
        and table_identifier
        and not table_name_matches_create_identifier(visible_table_name, table_identifier)
    ):
        errors.append(
            f"[{name}] Manual DDL override is active. Table Name is read from the CREATE TABLE "
            f"statement ('{table_name}'), but the visible Table Name is '{visible_table_name}'. "
            "Update the CREATE TABLE statement or clear manual DDL override to regenerate."
        )

    field_mappings = [
        FieldMapping(source=m["source"], target=m["target"])
        for m in raw.get("field_mappings", [])
        if m.get("source") and m.get("target")
    ]

    # Preserve the legacy three-way DDL validation behavior exactly: absent
    # DDL skips validation, parseable DDL blocks bad targets, and uncertain
    # hand-authored SQL degrades to a warning.
    if ddl and field_mappings:
        column_names = extract_column_names_from_ddl(ddl)
        if column_names is None:
            warnings.append(
                f"[{name}] DDL could not be parsed confidently — mapping targets "
                "were not validated. Review your DDL to ensure column names match."
            )
        else:
            for mapping in field_mappings:
                target = mapping.target
                if target and target not in column_names:
                    errors.append(
                        f"[{name}] Mapping target '{target}' is not a column in the "
                        f"staging DDL. Known columns: {sorted(column_names)}"
                    )

    spec = f"data-handoffs/{handoff_slug}.sql" if ddl else None
    if not ddl and existing_handoff and not existing_handoff.ddl_content and existing_handoff.spec:
        try:
            spec = clean_package_path(existing_handoff.spec)
        except ValueError as exc:
            errors.append(f"[{name}] Existing DDL artifact reference is invalid: {exc}")

    handoff = DataHandoff(
        name=name,
        system=raw.get("system") or None,
        type=raw.get("type", "staging-table"),
        version=raw.get("version") or None,
        spec=spec,
        ddl_content=ddl,
        table_name=table_name,
        mapping_path=(
            f"data-handoffs/{handoff_slug}-mapping.yaml" if field_mappings else None
        ),
        field_mappings=field_mappings,
        entity_name=raw.get("entity_name") or None,
    )
    return handoff, warnings, errors


def _handoff_validation_blockers(errors: list[str]) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    for error in errors:
        lowered = error.lower()
        if "mapping target" in lowered and "not a column" in lowered:
            field_ref, section_ref = "field_mappings", "mappings"
        elif "manual ddl override" in lowered or "ddl artifact reference" in lowered:
            field_ref, section_ref = "ddl_content", "ddl"
        elif lowered in {
            "a data handoff item is required.",
            "handoff name is required.",
        }:
            field_ref, section_ref = "name", "identity"
        else:
            field_ref, section_ref = "ddl_content", "ddl"
        code_slug = _slug(error)[:64] or "invalid-handoff"
        blockers.append(
            {
                "code": f"invalid-{code_slug}",
                "label": error,
                "field_ref": field_ref,
                "section_ref": section_ref,
            }
        )
    return blockers


def _readiness_payload(session: ProjectSession, name: str) -> dict | None:
    try:
        return asdict(readiness_view.item(session, f"handoff:{name}"))
    except KeyError:
        return None


def _replace_handoff(
    handoffs: list[DataHandoff],
    saved: DataHandoff,
    *,
    original_name: str | None,
) -> list[DataHandoff]:
    replacement_name = original_name or saved.name
    replacement_index = next(
        (index for index, handoff in enumerate(handoffs) if handoff.name == replacement_name),
        None,
    )
    result: list[DataHandoff] = []
    inserted = False
    for index, handoff in enumerate(handoffs):
        if index == replacement_index:
            result.append(saved)
            inserted = True
            continue
        if handoff.name in {replacement_name, saved.name}:
            continue
        result.append(handoff)
    if not inserted:
        result.append(saved)
    return result


@router.get("", response_class=HTMLResponse)
async def step4_get(request: Request, focus: str = ""):
    session = get_current_session(request)
    nav = build_nav_context(session, "/handoffs")
    focus_handoff = next(
        (handoff for handoff in session.data_handoffs if handoff.name == focus),
        None,
    )
    focus_name = focus_handoff.name if focus_handoff is not None else None
    focus_item = _readiness_payload(session, focus_name) if focus_name else None
    if focus_item is None:
        focus_name = None
    entity_fields = {
        entity.display_name(): [field.model_dump(mode="json") for field in entity.fields]
        for entity in session.classified_entities
    }
    return templates.TemplateResponse(request, "step4_handoffs.html", {
        "request": request,
        "session": session,
        "step": 4,
        "existing_handoffs": _existing_handoff_payloads(session),
        "edge_contract_only_no_handoffs": (
            _has_edge_contract_interfaces(session)
            and not _has_openapi_entity_classification(session)
            and not session.data_handoffs
        ),
        "handoff_readiness_items": readiness_view.items_for_step(session, 4),
        "handoff_board_facts": {h.name: _handoff_board_fact(h) for h in session.data_handoffs},
        "focus_name": focus_name,
        "focus_item": focus_item,
        "focus_source_of_truth_version": str(session.project_revision),
        "handoff_entity_fields": entity_fields,
        **nav,
    })


# Compatibility-only whole-list endpoint. The refreshed browser uses save-one.
@router.post("/save", response_class=JSONResponse)
async def step4_save(request: Request):
    """
    Body: {
      handoffs: [
        {
          name, system, type, version, entity_name,
          ddl_content: str,
          field_mappings: [{source, target}]
        }
      ]
    }
    """
    body = await request.json()
    session = get_current_session(request)

    validation_errors: list[str] = []
    validation_warnings: list[str] = []
    existing_handoffs = {handoff.name: handoff for handoff in session.data_handoffs}

    handoffs: list[DataHandoff] = []
    for raw in body.get("handoffs", []):
        handoff, warnings, errors = _build_one_handoff(
            raw,
            session=session,
            existing_handoffs=existing_handoffs,
        )
        validation_warnings.extend(warnings)
        validation_errors.extend(errors)
        if handoff is not None:
            handoffs.append(handoff)

    if validation_errors:
        logger.warning("[step4_save] validation errors: %s", validation_errors)
        return JSONResponse(
            {"ok": False, "errors": validation_errors, "warnings": validation_warnings}
        )

    session.data_handoffs = handoffs
    save_current_session(request, session)
    return JSONResponse(
        {"ok": True, "count": len(handoffs), "warnings": validation_warnings}
    )


@router.post("/save-one", response_class=JSONResponse)
async def save_one_handoff(request: Request):
    body = await request.json()
    cached_session = get_current_session(request)
    with _SAVE_ONE_MUTATION_LOCK:
        session = _reload_session_for_save_one(request, cached_session)
        return _save_one_handoff_body(request, body, session)


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


def _save_one_handoff_body(
    request: Request,
    body: dict,
    session: ProjectSession,
) -> JSONResponse:
    raw = body.get("item")
    if not isinstance(raw, dict):
        blockers = _handoff_validation_blockers(["A data handoff item is required."])
        return JSONResponse({"ok": False, "blockers": blockers}, status_code=400)

    original_name = clean_text(body.get("original_name"))
    supplied_version = clean_text(body.get("source_of_truth_version"))
    current_version = str(session.project_revision)
    if supplied_version is not None and supplied_version != current_version:
        # A stale rename must only recover the item identity the editor opened.
        # The dirty draft name may now belong to an unrelated concurrent create.
        fresh_handoff = next(
            (
                handoff
                for handoff in session.data_handoffs
                if original_name is not None and handoff.name == original_name
            ),
            None,
        )
        return JSONResponse(
            {
                "ok": False,
                "error": "This data handoff changed after the editor was opened.",
                "item": fresh_handoff.model_dump(mode="json") if fresh_handoff else None,
                "readiness": (
                    _readiness_payload(session, fresh_handoff.name) if fresh_handoff else None
                ),
                "recovery": "review-current-item" if fresh_handoff else "reload-current-list",
                "current_items": [
                    {"name": handoff.name, "type": handoff.type}
                    for handoff in session.data_handoffs
                ],
                "source_of_truth_version": current_version,
            },
            status_code=409,
        )

    name = clean_text(raw.get("name")) or ""
    if not name:
        blockers = _handoff_validation_blockers(["Handoff name is required."])
        return JSONResponse({"ok": False, "blockers": blockers}, status_code=400)
    duplicate_name = any(handoff.name == name for handoff in session.data_handoffs)
    if (original_name is None and duplicate_name) or (
        original_name and name != original_name and duplicate_name
    ):
        return JSONResponse(
            {
                "ok": False,
                "blockers": [
                    {
                        "code": "duplicate-name",
                        "label": f"A data handoff named '{name}' already exists.",
                        "field_ref": "name",
                        "section_ref": "identity",
                    }
                ],
            },
            status_code=400,
        )

    existing_handoffs = {handoff.name: handoff for handoff in session.data_handoffs}
    existing = existing_handoffs.get(original_name or name)
    submitted_ddl = raw.get("ddl_content")
    if submitted_ddl is not None and not isinstance(submitted_ddl, str):
        blockers = _handoff_validation_blockers(["DDL content must be text."])
        return JSONResponse({"ok": False, "blockers": blockers}, status_code=400)
    has_submitted_ddl = isinstance(submitted_ddl, str) and bool(submitted_ddl.strip())
    if existing is not None and existing.ddl_content and not has_submitted_ddl:
        blockers = _handoff_validation_blockers(
            ["Generated DDL is required before replacing the saved DDL."]
        )
        return JSONResponse({"ok": False, "blockers": blockers}, status_code=400)
    if existing is not None:
        raw = {**existing.model_dump(mode="json"), **raw, "original_name": original_name}

    saved, warnings, errors = _build_one_handoff(
        raw,
        session=session,
        existing_handoffs=existing_handoffs,
    )
    if errors or saved is None:
        blockers = _handoff_validation_blockers(errors or ["The data handoff could not be saved."])
        return JSONResponse({"ok": False, "blockers": blockers}, status_code=400)

    before = [handoff.model_dump(mode="json") for handoff in session.data_handoffs]
    updated = _replace_handoff(
        session.data_handoffs,
        saved,
        original_name=original_name,
    )
    after = [handoff.model_dump(mode="json") for handoff in updated]
    if after != before:
        session.data_handoffs = updated
        session.project_revision = max(1, session.project_revision) + 1
        save_current_session(request, session)
        current_version = str(session.project_revision)

    readiness = _readiness_payload(session, saved.name)
    if readiness is None:
        raise RuntimeError(f"Saved data handoff '{saved.name}' has no readiness item.")
    counts = readiness_view.step_counts(session)
    rail = [
        {"step": step, "count": values["count"], "attention": values["attention"]}
        for step, values in sorted(counts.items())
    ]
    return JSONResponse(
        {
            "ok": True,
            "item": saved.model_dump(mode="json"),
            "readiness": readiness,
            "board_metadata": _handoff_board_metadata(saved),
            "step_counts": counts,
            "rail": rail,
            "warnings": warnings,
            "source_of_truth_version": current_version,
        }
    )


@router.get("/next")
async def step4_next():
    return RedirectResponse("/downstream", status_code=303)
