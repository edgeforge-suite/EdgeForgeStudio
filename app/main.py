"""EdgeForge Studio — FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.middleware.browser_security import (
    BrowserSecurityHeadersMiddleware,
    browser_safe_internal_server_error,
)
from app.middleware.request_context import StudioRequestContextMiddleware
from app.middleware.resource_limits import ResourceControlMiddleware
from app.middleware.upload_request_policy import UploadRequestPolicyMiddleware
from app.paths import STATIC_DIR
from app.routes import (
    downstream,
    entities,
    export,
    handoffs,
    kafka,
    knowledge,
    mappings,
    passthrough,
    project,
    project_file,
    regen_preview,
    review,
    rules,
    upstream,
    validate,
)
from app.services.audit import initialize_audit
from app.services.settings import get_studio_settings


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    initialize_audit(get_studio_settings())
    yield


settings = get_studio_settings()
app = FastAPI(
    title="EdgeForge Studio",
    version="5.0.0",
    docs_url="/docs" if settings.enable_api_docs else None,
    redoc_url="/redoc" if settings.enable_api_docs else None,
    openapi_url="/openapi.json" if settings.enable_api_docs else None,
    lifespan=_lifespan,
)

# Starlette wraps middleware in reverse registration order. Resource controls sit
# after context/CSRF but before routes; upload and browser policy stay outermost.
app.add_middleware(ResourceControlMiddleware)
app.add_middleware(StudioRequestContextMiddleware)
app.add_middleware(UploadRequestPolicyMiddleware)
app.add_middleware(BrowserSecurityHeadersMiddleware)
app.add_exception_handler(Exception, browser_safe_internal_server_error)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(project.router)
app.include_router(project_file.router)
app.include_router(upstream.router)
app.include_router(knowledge.router)
app.include_router(kafka.router)
app.include_router(passthrough.router)
app.include_router(entities.router)
app.include_router(downstream.router)
app.include_router(handoffs.router)
app.include_router(rules.router)
app.include_router(review.router)
app.include_router(export.router)
app.include_router(regen_preview.router)
app.include_router(mappings.router)
app.include_router(validate.router)
