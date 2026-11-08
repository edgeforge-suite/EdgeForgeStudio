"""Lightweight validation and generation APIs for authoring-time feedback."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services.staging_ddl_validation import generate_ddl_from_columns, validate_staging_ddl

router = APIRouter(prefix="/api/validate")


class StagingDdlRequest(BaseModel):
    ddl: str = ""


@router.post("/staging-ddl", response_class=JSONResponse)
async def validate_staging_ddl_endpoint(body: StagingDdlRequest):
    return JSONResponse({"warnings": validate_staging_ddl(body.ddl)})


class StagingDdlGenerateRequest(BaseModel):
    table_name: str = ""
    columns: list[dict[str, Any]] = []


@router.post("/staging-ddl/generate", response_class=JSONResponse)
async def generate_staging_ddl_endpoint(body: StagingDdlGenerateRequest):
    """Generate a CREATE TABLE statement from structured column definitions.

    Returns {ok: true, ddl: "..."} or {ok: false, error: "..."}.
    The caller can then pass the returned DDL through /api/validate/staging-ddl
    for UUID-width warnings.
    """
    try:
        ddl = generate_ddl_from_columns(body.table_name, body.columns)
        return JSONResponse({"ok": True, "ddl": ddl})
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)})
