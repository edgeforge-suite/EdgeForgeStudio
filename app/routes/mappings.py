"""Upstream mapping entry — called from Step 3 detail panel."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.models.project import FieldMapping, OperationMapping
from app.services.canonical_mapping_validation import (
    canonical_mapping_target_error,
    mapping_path_whitespace_error,
)
from app.services.session_context import get_current_session, save_current_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/mappings")


def _sample_fields(content: str | None) -> set[str] | None:
    """Parse a JSON sample string and return all valid mapping source field names.

    Returns top-level keys plus one level of dot-notation nested keys for any
    top-level value that is itself a dict (e.g. envelope patterns like Codat's
    ``{"data": {"id": "...", "name": "..."}}`` yield ``{"data", "data.id",
    "data.name", ...}``).

    Returns None when content is absent or unparseable — callers skip
    validation rather than incorrectly blocking a save.
    """
    if not content:
        return None
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(parsed, list):
        if not parsed or not isinstance(parsed[0], dict):
            return None
        parsed = parsed[0]
    if not isinstance(parsed, dict):
        return None
    fields: set[str] = set(parsed.keys())
    for key, value in parsed.items():
        if isinstance(value, dict):
            for nested_key in value:
                fields.add(f"{key}.{nested_key}")
    return fields


@router.post("/upstream/save", response_class=JSONResponse)
async def save_upstream_mappings(request: Request):
    """Validate and save upstream field mappings.

    Body: {
      interface_name: str,
      operation_mappings: [
        {
          name: str,
          request_mappings: [{source, target}],
          response_mappings: [{source, target}]
        }
      ]
    }

    Validation: when a sample body is present for an operation, every
    mapping source field must appear as a top-level key in that sample.
    Unknown source fields are rejected with a clear error so users catch
    mis-named fields here rather than at Step 8 generate time.
    """
    body = await request.json()
    session = get_current_session(request)
    iface_name = body.get("interface_name", "")

    # Build a lookup of saved operation samples for this interface so we
    # can validate mapping sources against the known sample field names.
    op_samples: dict[str, tuple[str | None, str | None]] = {}
    selected_iface = next(
        (iface for iface in session.upstream_interfaces if iface.name == iface_name),
        None,
    )
    if selected_iface is not None:
        for op in selected_iface.operations:
            op_samples[op.name] = (op.request_sample_content, op.response_sample_content)

    # Validate all mapping sources before persisting anything.
    validation_errors: list[str] = []
    for om in body.get("operation_mappings", []):
        op_name = om.get("name", "")
        req_sample_content, resp_sample_content = op_samples.get(op_name, (None, None))

        req_fields = _sample_fields(req_sample_content)
        resp_fields = _sample_fields(resp_sample_content)

        for m in om.get("request_mappings", []):
            raw_src = str(m.get("source", "") or "")
            raw_target = str(m.get("target", "") or "")
            src = raw_src.strip()
            target = raw_target.strip()
            if source_error := mapping_path_whitespace_error(raw_src, label="source"):
                validation_errors.append(f"[{op_name}] Request mapping is invalid. {source_error}")
            target_path_error = mapping_path_whitespace_error(raw_target, label="target")
            if target_path_error:
                validation_errors.append(
                    f"[{op_name}] Request mapping is invalid. {target_path_error}"
                )
            if src and req_fields is not None and src not in req_fields:
                validation_errors.append(
                    f"[{op_name}] Request mapping source '{src}' is not a field in the "
                    f"request sample. Known fields: {sorted(req_fields)}"
                )
            if src and target and selected_iface is not None and target_path_error is None:
                if target_error := canonical_mapping_target_error(
                    session,
                    expected_entity=selected_iface.entity_name,
                    target=raw_target,
                ):
                    validation_errors.append(f"[{op_name}] Request mapping is invalid. {target_error}")

        for m in om.get("response_mappings", []):
            raw_src = str(m.get("source", "") or "")
            raw_target = str(m.get("target", "") or "")
            src = raw_src.strip()
            target = raw_target.strip()
            if source_error := mapping_path_whitespace_error(raw_src, label="source"):
                validation_errors.append(f"[{op_name}] Response mapping is invalid. {source_error}")
            target_path_error = mapping_path_whitespace_error(raw_target, label="target")
            if target_path_error:
                validation_errors.append(
                    f"[{op_name}] Response mapping is invalid. {target_path_error}"
                )
            if src and resp_fields is not None and src not in resp_fields:
                validation_errors.append(
                    f"[{op_name}] Response mapping source '{src}' is not a field in the "
                    f"response sample. Known fields: {sorted(resp_fields)}"
                )
            if src and target and selected_iface is not None and target_path_error is None:
                if target_error := canonical_mapping_target_error(
                    session,
                    expected_entity=selected_iface.entity_name,
                    target=raw_target,
                ):
                    validation_errors.append(f"[{op_name}] Response mapping is invalid. {target_error}")

    if validation_errors:
        logger.warning("[save_upstream_mappings] validation errors for %s: %s", iface_name, validation_errors)
        return JSONResponse({"ok": False, "errors": validation_errors})

    # Validation passed — persist the mappings.
    for iface in session.upstream_interfaces:
        if iface.name == iface_name:
            iface.operation_mappings = [
                OperationMapping(
                    name=om["name"],
                    request_mappings=[
                        FieldMapping(source=m["source"], target=m["target"])
                        for m in om.get("request_mappings", [])
                        if m.get("source") and m.get("target")
                    ],
                    response_mappings=[
                        FieldMapping(source=m["source"], target=m["target"])
                        for m in om.get("response_mappings", [])
                        if m.get("source") and m.get("target")
                    ],
                )
                for om in body.get("operation_mappings", [])
                if om.get("name")
            ]
            break

    save_current_session(request, session)
    return JSONResponse({"ok": True})


@router.post("/upstream/samples/save", response_class=JSONResponse)
async def save_operation_samples(request: Request):
    """
    Body: {
      interface_name: str,
      operations: [
        {
          name: str,
          request_sample_content: str | null,
          response_sample_content: str | null
        }
      ]
    }
    """
    body = await request.json()
    session = get_current_session(request)
    iface_name = body.get("interface_name", "")

    for iface in session.upstream_interfaces:
        if iface.name == iface_name:
            for op_data in body.get("operations", []):
                op_name = op_data.get("name", "")
                for op in iface.operations:
                    if op.name == op_name:
                        op.request_sample_content = op_data.get("request_sample_content") or None
                        op.response_sample_content = op_data.get("response_sample_content") or None
                        break
            break

    save_current_session(request, session)
    return JSONResponse({"ok": True})
