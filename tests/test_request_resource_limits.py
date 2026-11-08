"""Focused adversarial coverage for shared-mode resource controls."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from app.main import app as studio_app
from app.middleware.browser_security import (
    BROWSER_SECURITY_HEADERS,
    BrowserSecurityHeadersMiddleware,
)
from app.middleware.resource_limits import ResourceControlMiddleware
from app.services.identity import Principal
from app.services.project_file_service import serialize_project, snapshot_session_for_save
from app.services.request_resource_limits import (
    CONCURRENCY_RETRY_AFTER_SECONDS,
    EXPLICITLY_UNTHROTTLED_ROUTES,
    HTML_RATE_LIMITED_PATHS,
    MAX_PRINCIPAL_CLASS_ENTRIES,
    ROUTE_LIMIT_CLASSES,
    RequestCostClass,
    RequestResourceLimiter,
    ResourceLimitPermit,
    ResourceLimitRejection,
    get_request_resource_limiter,
    request_cost_class,
)
from app.services.settings import (
    RequestResourceLimits,
    ResourceLimitClassSettings,
    StudioSettingsError,
    get_studio_settings,
)
from tests.smoke._shared import save_session_for_client, session_for_client


@dataclass
class _Clock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now


def _limits(
    *,
    rate_max: int = 6,
    window_seconds: int = 300,
    principal_concurrency: int = 1,
    process_concurrency: int = 2,
) -> RequestResourceLimits:
    value = ResourceLimitClassSettings(
        rate_max=rate_max,
        rate_window_seconds=window_seconds,
        principal_concurrency=principal_concurrency,
        process_concurrency=process_concurrency,
    )
    return RequestResourceLimits(a=value, b=value, c=value, c2=value, d=value)


def _run(coroutine):
    return asyncio.run(coroutine)


_PASSTHROUGH_UPSTREAM_SPEC = """
openapi: 3.0.0
info:
  title: Inbound API
  version: "1.0"
paths:
  /payments:
    post:
      operationId: routePayment
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/InboundPayment'
      responses:
        "200":
          description: ok
components:
  schemas:
    InboundPayment:
      type: object
      properties:
        paymentType:
          type: string
"""

_PASSTHROUGH_REMOTE_SPEC = """
openapi: 3.0.0
info:
  title: Remote API
  version: "1.0"
paths:
  /payments:
    post:
      operationId: sendRemotePayment
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/RemotePayment'
      responses:
        "200":
          description: ok
components:
  schemas:
    RemotePayment:
      type: object
      properties:
        settlementAmount:
          type: string
"""


def _expected_registry() -> dict[tuple[str, str], RequestCostClass]:
    return {
        ("POST", "/export/write"): RequestCostClass.A,
        ("POST", "/export/validate"): RequestCostClass.A,
        ("POST", "/export/assess"): RequestCostClass.A,
        ("POST", "/export/generate"): RequestCostClass.A,
        ("POST", "/export/build"): RequestCostClass.A,
        ("POST", "/export/run"): RequestCostClass.A,
        ("POST", "/regen/apply"): RequestCostClass.A,
        ("GET", "/regen/preview"): RequestCostClass.A,
        ("POST", "/api/validate/staging-ddl/generate"): RequestCostClass.A,
        ("POST", "/upstream/ingest-url"): RequestCostClass.B,
        ("POST", "/entities/ks/review"): RequestCostClass.C,
        ("POST", "/entities/ks/identity-role-review"): RequestCostClass.C,
        ("POST", "/entities/ks/validation-review"): RequestCostClass.C,
        ("POST", "/rules/ks/review"): RequestCostClass.C,
        ("POST", "/review/ks/review"): RequestCostClass.C,
        ("POST", "/kafka/ks/review"): RequestCostClass.C,
        ("POST", "/kafka/ks/transform-review"): RequestCostClass.C,
        ("POST", "/passthrough/ks/review"): RequestCostClass.C,
        ("POST", "/knowledge/upload"): RequestCostClass.C,
        ("POST", "/knowledge/delete"): RequestCostClass.C,
        ("GET", "/entities/ks/suggestions"): RequestCostClass.C2,
        ("GET", "/entities/ks/drawer"): RequestCostClass.C2,
        ("GET", "/entities/ks/full-review"): RequestCostClass.C2,
        ("GET", "/entities/ks/evidence"): RequestCostClass.C2,
        ("GET", "/rules/ks/drawer"): RequestCostClass.C2,
        ("GET", "/review/ks/drawer"): RequestCostClass.C2,
        ("GET", "/kafka/ks/drawer"): RequestCostClass.C2,
        ("GET", "/passthrough/ks/drawer"): RequestCostClass.C2,
        ("POST", "/upstream/ingest-file"): RequestCostClass.D,
        ("POST", "/upstream/edge-contract/inspect"): RequestCostClass.D,
        ("POST", "/upstream/edge-contract/file-inspect"): RequestCostClass.D,
        ("POST", "/downstream/edge-contract/inspect"): RequestCostClass.D,
        ("POST", "/downstream/edge-contract/file-inspect"): RequestCostClass.D,
        ("POST", "/project/open"): RequestCostClass.D,
        ("POST", "/api/validate/staging-ddl"): RequestCostClass.D,
        ("GET", "/upstream/classify-debug"): RequestCostClass.D,
        ("GET", "/export/download-zip"): RequestCostClass.D,
    }


def test_registry_is_exact_and_explicitly_excludes_safety_and_page_routes():
    assert dict(ROUTE_LIMIT_CLASSES) == _expected_registry()
    assert EXPLICITLY_UNTHROTTLED_ROUTES == {
        ("GET", "/export/run-status"),
        ("POST", "/export/stop"),
        ("POST", "/export/reset"),
        ("GET", "/export/artifact/{artifact_name}"),
        ("GET", "/knowledge"),
    }
    for method, path in EXPLICITLY_UNTHROTTLED_ROUTES:
        assert request_cost_class(method, path.replace("{artifact_name}", "package.zip")) is None
    assert request_cost_class("POST", "/entities/save") is None
    assert request_cost_class("GET", "/entities") is None


def test_shared_mode_defaults_and_explicit_per_class_overrides(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_RATE_A_MAX", "9")
    monkeypatch.setenv("EDGEFORGE_STUDIO_RATE_C2_CONCURRENCY_PROCESS", "17")

    settings = get_studio_settings()

    assert settings.request_resource_limits.a == ResourceLimitClassSettings(9, 300, 1, 2)
    assert settings.request_resource_limits.b == ResourceLimitClassSettings(20, 300, 2, 6)
    assert settings.request_resource_limits.c == ResourceLimitClassSettings(30, 300, 2, 6)
    assert settings.request_resource_limits.c2 == ResourceLimitClassSettings(120, 300, 4, 17)
    assert settings.request_resource_limits.d == ResourceLimitClassSettings(60, 300, 4, 12)


@pytest.mark.parametrize("value", ["not-an-integer", "-1"])
def test_invalid_resource_limit_settings_fail_closed(monkeypatch, value):
    monkeypatch.setenv("EDGEFORGE_STUDIO_RATE_B_WINDOW_S", value)

    with pytest.raises(StudioSettingsError, match="EDGEFORGE_STUDIO_RATE_B_WINDOW_S"):
        get_studio_settings()


def test_each_zero_dimension_disables_only_that_dimension():
    settings = _limits(rate_max=0, window_seconds=0, principal_concurrency=0, process_concurrency=0)

    assert settings.a.rate_max == 0
    assert settings.a.rate_window_seconds == 0
    assert settings.a.principal_concurrency == 0
    assert settings.a.process_concurrency == 0


def test_sliding_window_prunes_and_returns_rounded_retry_after():
    async def scenario() -> None:
        clock = _Clock()
        limiter = RequestResourceLimiter(clock=clock)
        limits = _limits(rate_max=1, window_seconds=10, principal_concurrency=0, process_concurrency=0)

        first = await limiter.try_acquire(
            cost_class=RequestCostClass.A, principal_id="alice", limits=limits
        )
        assert isinstance(first, ResourceLimitPermit)
        await limiter.release(first)
        clock.now = 0.1
        rejected = await limiter.try_acquire(
            cost_class=RequestCostClass.A, principal_id="alice", limits=limits
        )
        assert rejected == ResourceLimitRejection(10)
        clock.now = 10.0
        accepted = await limiter.try_acquire(
            cost_class=RequestCostClass.A, principal_id="alice", limits=limits
        )
        assert isinstance(accepted, ResourceLimitPermit)

    _run(scenario())


def test_concurrency_rejection_is_immediate_and_consumes_rate_budget():
    async def scenario() -> None:
        limiter = RequestResourceLimiter()
        limits = _limits(rate_max=2, principal_concurrency=1, process_concurrency=1)
        started = asyncio.Event()
        release_first = asyncio.Event()

        async def held_request() -> None:
            permit = await limiter.try_acquire(
                cost_class=RequestCostClass.A, principal_id="alice", limits=limits
            )
            assert isinstance(permit, ResourceLimitPermit)
            try:
                started.set()
                await release_first.wait()
            finally:
                await limiter.release(permit)

        first = asyncio.create_task(held_request())
        await started.wait()
        rejected = await limiter.try_acquire(
            cost_class=RequestCostClass.A, principal_id="alice", limits=limits
        )
        assert rejected == ResourceLimitRejection(CONCURRENCY_RETRY_AFTER_SECONDS)
        release_first.set()
        await first
        rate_rejected = await limiter.try_acquire(
            cost_class=RequestCostClass.A, principal_id="alice", limits=limits
        )
        assert rate_rejected == ResourceLimitRejection(300)

    _run(scenario())


def test_process_rejection_rolls_back_principal_permit_and_cancellation_releases():
    async def scenario() -> None:
        limiter = RequestResourceLimiter()
        limits = _limits(rate_max=0, principal_concurrency=1, process_concurrency=1)
        alice = await limiter.try_acquire(
            cost_class=RequestCostClass.A, principal_id="alice", limits=limits
        )
        assert isinstance(alice, ResourceLimitPermit)
        bob_rejected = await limiter.try_acquire(
            cost_class=RequestCostClass.A, principal_id="bob", limits=limits
        )
        assert bob_rejected == ResourceLimitRejection(CONCURRENCY_RETRY_AFTER_SECONDS)
        await limiter.release(alice)
        bob = await limiter.try_acquire(
            cost_class=RequestCostClass.A, principal_id="bob", limits=limits
        )
        assert isinstance(bob, ResourceLimitPermit)
        await limiter.release(bob)

        started = asyncio.Event()

        async def cancellable_request() -> None:
            permit = await limiter.try_acquire(
                cost_class=RequestCostClass.A, principal_id="alice", limits=limits
            )
            assert isinstance(permit, ResourceLimitPermit)
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                await limiter.release(permit)

        task = asyncio.create_task(cancellable_request())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        recovered = await limiter.try_acquire(
            cost_class=RequestCostClass.A, principal_id="alice", limits=limits
        )
        assert isinstance(recovered, ResourceLimitPermit)

    _run(scenario())


def test_class_and_principal_state_are_isolated():
    async def scenario() -> None:
        limiter = RequestResourceLimiter()
        limits = _limits(rate_max=1, principal_concurrency=0, process_concurrency=0)
        for cost_class, principal in ((RequestCostClass.A, "alice"), (RequestCostClass.B, "alice"), (RequestCostClass.A, "bob")):
            result = await limiter.try_acquire(
                cost_class=cost_class, principal_id=principal, limits=limits
            )
            assert isinstance(result, ResourceLimitPermit)
            await limiter.release(result)
        rejected = await limiter.try_acquire(
            cost_class=RequestCostClass.A, principal_id="alice", limits=limits
        )
        assert isinstance(rejected, ResourceLimitRejection)

    _run(scenario())


def test_idle_and_lru_eviction_never_remove_active_entries():
    async def scenario() -> None:
        clock = _Clock()
        limits = _limits(rate_max=0, window_seconds=10, principal_concurrency=0, process_concurrency=0)
        limiter = RequestResourceLimiter(clock=clock, max_entries=2)
        for principal in ("alice", "bob"):
            permit = await limiter.try_acquire(
                cost_class=RequestCostClass.A, principal_id=principal, limits=limits
            )
            assert isinstance(permit, ResourceLimitPermit)
            await limiter.release(permit)
        # Touch Alice so Bob is the least-recently-used inactive entry.
        permit = await limiter.try_acquire(
            cost_class=RequestCostClass.A, principal_id="alice", limits=limits
        )
        assert isinstance(permit, ResourceLimitPermit)
        await limiter.release(permit)
        charlie = await limiter.try_acquire(
            cost_class=RequestCostClass.A, principal_id="charlie", limits=limits
        )
        assert isinstance(charlie, ResourceLimitPermit)
        state = await limiter.state_for_testing()
        assert state["entry_count"] == 2
        assert ("A", "bob") not in state["keys"]

        active_limiter = RequestResourceLimiter(clock=clock, max_entries=1)
        active = await active_limiter.try_acquire(
            cost_class=RequestCostClass.A, principal_id="active", limits=limits
        )
        assert isinstance(active, ResourceLimitPermit)
        blocked = await active_limiter.try_acquire(
            cost_class=RequestCostClass.A, principal_id="new", limits=limits
        )
        assert blocked == ResourceLimitRejection(CONCURRENCY_RETRY_AFTER_SECONDS)
        state = await active_limiter.state_for_testing()
        assert state["keys"] == (("A", "active"),)

        assert MAX_PRINCIPAL_CLASS_ENTRIES == 10_000

    _run(scenario())


def test_window_zero_entries_are_immediately_evictable_when_inactive():
    async def scenario() -> None:
        limiter = RequestResourceLimiter(max_entries=1)
        limits = _limits(rate_max=0, window_seconds=0, principal_concurrency=0, process_concurrency=0)
        first = await limiter.try_acquire(
            cost_class=RequestCostClass.A, principal_id="alice", limits=limits
        )
        assert isinstance(first, ResourceLimitPermit)
        await limiter.release(first)
        second = await limiter.try_acquire(
            cost_class=RequestCostClass.A, principal_id="bob", limits=limits
        )
        assert isinstance(second, ResourceLimitPermit)
        assert (await limiter.state_for_testing())["keys"] == (("A", "bob"),)

    _run(scenario())


def test_zero_rate_dimension_leaves_principal_concurrency_enforced():
    async def scenario() -> None:
        limiter = RequestResourceLimiter()
        limits = _limits(
            rate_max=0,
            window_seconds=0,
            principal_concurrency=1,
            process_concurrency=0,
        )
        first = await limiter.try_acquire(
            cost_class=RequestCostClass.A, principal_id="alice", limits=limits
        )
        assert isinstance(first, ResourceLimitPermit)
        second = await limiter.try_acquire(
            cost_class=RequestCostClass.A, principal_id="alice", limits=limits
        )
        assert second == ResourceLimitRejection(CONCURRENCY_RETRY_AFTER_SECONDS)

    _run(scenario())


class _TestRequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.studio_shared_mode = True
        request.state.principal = Principal(
            user_id=request.headers.get("x-test-principal", "anonymous:test"),
            source="anonymous",
        )
        return await call_next(request)


def _limited_test_app() -> FastAPI:
    test_app = FastAPI()

    @test_app.post("/export/write")
    async def export_write():
        return JSONResponse({"ok": True})

    @test_app.post("/knowledge/upload")
    async def knowledge_upload():
        return HTMLResponse("<p>ok</p>")

    test_app.add_middleware(ResourceControlMiddleware)
    test_app.add_middleware(_TestRequestContextMiddleware)
    test_app.add_middleware(BrowserSecurityHeadersMiddleware)
    return test_app


def test_json_and_standalone_html_rejections_keep_browser_security_headers(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_RATE_A_MAX", "1")
    monkeypatch.setenv("EDGEFORGE_STUDIO_RATE_C_MAX", "1")
    client = TestClient(_limited_test_app())

    assert client.post("/export/write").status_code == 200
    json_rejected = client.post("/export/write")
    assert json_rejected.status_code == 429
    assert json_rejected.json() == {
        "ok": False,
        "error": "Request limit reached. Please retry later.",
        "retry_after": 300,
    }
    assert json_rejected.headers["retry-after"] == "300"

    assert client.post("/knowledge/upload").status_code == 200
    html_rejected = client.post("/knowledge/upload")
    assert html_rejected.status_code == 429
    assert "<html lang=\"en\">" in html_rejected.text
    assert "Request limit reached" in html_rejected.text
    assert "Knowledge Workspace" in html_rejected.text
    assert "edgeforge_studio_session" not in html_rejected.text
    for response in (json_rejected, html_rejected):
        for name, value in BROWSER_SECURITY_HEADERS.items():
            assert response.headers[name] == value


def test_local_mode_bypasses_classification_and_state(monkeypatch):
    async def scenario() -> None:
        middleware = ResourceControlMiddleware(lambda _scope, _receive, _send: None)
        request = Request({"type": "http", "method": "POST", "path": "/export/write", "headers": []})
        request.state.studio_shared_mode = False
        called = False

        async def call_next(_request: Request) -> Response:
            nonlocal called
            called = True
            return JSONResponse({"ok": True})

        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 200
        assert called is True
        assert (await get_request_resource_limiter().state_for_testing())["entry_count"] == 0

    _run(scenario())


def test_pr291_rejection_occurs_before_shared_mode_capacity_consumption(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    response = TestClient(studio_app, base_url="https://testserver").post(
        "/upstream/ingest-file",
        headers={
            "content-type": "multipart/form-data; boundary=proof",
            "content-length": str(52 * 1024 * 1024),
        },
        content=b"ignored",
    )

    assert response.status_code == 413
    assert _run(get_request_resource_limiter().state_for_testing())["entry_count"] == 0


def test_shared_mode_toggle_after_app_import_enforces_live_settings(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_RATE_D_MAX", "1")
    client = TestClient(studio_app, base_url="https://testserver")
    page = client.get("/")
    csrf_token = re.search(
        r'name="edgeforge-csrf-token"\s+content="([^"]+)"',
        page.text,
    )
    assert csrf_token is not None
    headers = {"x-edgeforge-csrf-token": csrf_token.group(1)}

    assert client.post("/api/validate/staging-ddl", json={"ddl": ""}, headers=headers).status_code == 200
    rejected = client.post("/api/validate/staging-ddl", json={"ddl": ""}, headers=headers)

    assert rejected.status_code == 429
    assert rejected.headers["retry-after"] == "300"


def test_shared_mode_classify_debug_consumes_class_d_capacity(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_RATE_D_MAX", "1")
    client = TestClient(studio_app, base_url="https://testserver")
    client.get("/")

    session = session_for_client(client)
    session.raw_spec_content = _PASSTHROUGH_UPSTREAM_SPEC
    session.raw_spec_filename = "stored-openapi.yaml"
    save_session_for_client(client, session)

    classified = client.get("/upstream/classify-debug")

    assert classified.status_code == 200
    assert classified.json()["ok"] is True
    assert classified.json()["total_schemas"] == 1

    rejected = client.get("/upstream/classify-debug")

    assert rejected.status_code == 429
    assert rejected.headers["retry-after"] == "300"
    assert rejected.json() == {
        "ok": False,
        "error": "Request limit reached. Please retry later.",
        "retry_after": 300,
    }


def test_passthrough_url_fetches_consume_class_b_per_fetch(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_RATE_B_MAX", "3")
    fetched_urls: list[str] = []
    remote_spec = yaml.safe_load(_PASSTHROUGH_REMOTE_SPEC)

    def fetch_remote_spec(url: str) -> dict:
        fetched_urls.append(url)
        return remote_spec

    monkeypatch.setattr(
        "app.services.passthrough_service.fetch_openapi_from_url",
        fetch_remote_spec,
    )
    client = TestClient(studio_app, base_url="https://testserver")
    page = client.get("/")
    csrf_token = re.search(
        r'name="edgeforge-csrf-token"\s+content="([^"]+)"', page.text
    )
    assert csrf_token is not None
    headers = {"x-edgeforge-csrf-token": csrf_token.group(1)}

    described = client.post(
        "/passthrough/describe-spec",
        json={"source_mode": "url", "spec_url": "https://example.test/describe.yaml"},
        headers=headers,
    )
    assert described.status_code == 200

    session = session_for_client(client)
    session.app_archetype = "passthrough-router"
    session.raw_spec_content = _PASSTHROUGH_UPSTREAM_SPEC
    save_session_for_client(client, session)
    saved = client.post(
        "/passthrough/save",
        json={
            "upstream_operation_name": "routePayment",
            "downstream_targets": [
                {
                    "name": "first-remote",
                    "system": "FIRST",
                    "source_mode": "url",
                    "spec_url": "https://example.test/first.yaml",
                    "selected_operation_name": "sendRemotePayment",
                },
                {
                    "name": "second-remote",
                    "system": "SECOND",
                    "source_mode": "url",
                    "spec_url": "https://example.test/second.yaml",
                    "selected_operation_name": "sendRemotePayment",
                },
            ],
            "route_field": "paymentType",
            "routes": [{"match": "instant", "target": "FIRST"}],
            "default_target": "SECOND",
            "transforms": [
                {"source": "paymentType", "target": "settlementAmount"},
            ],
        },
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["ok"] is True
    assert fetched_urls == [
        "https://example.test/describe.yaml",
        "https://example.test/first.yaml",
        "https://example.test/second.yaml",
    ]

    rejected = client.post(
        "/passthrough/describe-spec",
        json={"source_mode": "url", "spec_url": "https://example.test/over-budget.yaml"},
        headers=headers,
    )
    assert rejected.status_code == 429
    assert rejected.json() == {
        "ok": False,
        "error": "Request limit reached. Please retry later.",
        "retry_after": 300,
    }
    assert fetched_urls[-1] == "https://example.test/second.yaml"


def test_exhausted_native_form_limit_preserves_the_intentional_html_429(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_RATE_D_MAX", "1")
    client = TestClient(studio_app, base_url="https://testserver")
    page = client.get("/")
    csrf_token = re.search(
        r'name="edgeforge-csrf-token"\s+content="([^"]+)"', page.text
    )
    assert csrf_token is not None
    project_json = serialize_project(snapshot_session_for_save(session_for_client(client)))

    consumed = client.post(
        "/project/open",
        data={"_edgeforge_csrf_token": csrf_token.group(1)},
        files={"project_file": ("project.json", project_json, "application/json")},
        follow_redirects=False,
    )
    assert consumed.status_code == 303

    for form_data in (
        {"_edgeforge_csrf_token": csrf_token.group(1)},
        {},
    ):
        limited = client.post(
            "/project/open",
            data=form_data,
            files={"project_file": ("project.json", project_json, "application/json")},
            follow_redirects=False,
        )
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "300"
        assert "Request limit reached. Please retry later." in limited.text
        assert "Missing CSRF token" not in limited.text
        for name, value in BROWSER_SECURITY_HEADERS.items():
            assert limited.headers[name] == value


def test_deferred_multipart_csrf_rejection_releases_shared_capacity(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_RATE_C_CONCURRENCY_PRINCIPAL", "1")
    monkeypatch.setenv("EDGEFORGE_STUDIO_RATE_C_CONCURRENCY_PROCESS", "1")
    client = TestClient(studio_app, base_url="https://testserver")
    client.get("/")

    response = client.post(
        "/knowledge/upload",
        files={"document_file": ("notes.md", b"# Notes", "text/markdown")},
        data={"description": "test"},
    )

    assert response.status_code == 403
    assert _run(get_request_resource_limiter().state_for_testing())["active_permits"]["C"] == 0


def test_html_path_mapping_is_fixed_and_session_free():
    assert HTML_RATE_LIMITED_PATHS == {
        "/knowledge/upload": ("/knowledge", "Knowledge Workspace"),
        "/knowledge/delete": ("/knowledge", "Knowledge Workspace"),
        "/regen/apply": ("/export", "Export"),
        "/regen/preview": ("/export", "Export"),
        "/project/open": ("/", "Project Setup"),
    }
