from __future__ import annotations

import ipaddress
from email.message import Message
from pathlib import Path

import pytest

_ENGINE_PREFLIGHT_ROUTE_TESTS = {
    "test_audit.py",
    "test_concurrency_isolation.py",
    "test_export_build_run.py",
    "test_export_error_surfacing.py",
    "test_export_route.py",
    "test_export_structured_output.py",
    "test_regen_binding.py",
}


@pytest.fixture(autouse=True)
def isolated_sqlite_session_store(tmp_path, monkeypatch, request):
    """Give each test its own request-scoped SQLite session store.

    Most legacy route tests create a TestClient and also seed session state directly.
    P2-2b keeps that ergonomic test setup by making anonymous cookie issuance
    deterministic inside tests, while the backing store remains the real seam.
    """

    monkeypatch.setenv("EDGEFORGE_STUDIO_STATE_DIR", str(tmp_path / "studio-state"))
    if Path(str(request.fspath)).name in _ENGINE_PREFLIGHT_ROUTE_TESTS:
        engine_repo = tmp_path / "edgeforge-engine-placeholder"
        engine_repo.mkdir()
        # These route tests monkeypatch the Engine call itself, but the route
        # still performs an Engine-path preflight before reaching that seam.
        monkeypatch.setenv("EDGEFORGE_STUDIO_DEFAULT_ENGINE_REPO", str(engine_repo))
        monkeypatch.setattr(
            "app.services.openapi_fetch_guard._resolved_addresses",
            lambda host, port, **_kwargs: {ipaddress.ip_address("93.184.216.34")},
        )

        class _OpenAPIResponse:
            status = 200

            def __init__(self) -> None:
                self.headers = Message()
                self._body = (
                    b'{"openapi":"3.1.0","info":{"title":"Test",'
                    b'"version":"1"},"paths":{}}'
                )
                self._offset = 0

            def read(self, size: int) -> bytes:
                chunk = self._body[self._offset : self._offset + size]
                self._offset += len(chunk)
                return chunk

            def getcode(self) -> int:
                return self.status

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

        monkeypatch.setattr(
            "app.services.openapi_fetch_guard._open_url",
            lambda target, timeout: _OpenAPIResponse(),
        )
    monkeypatch.setattr(
        "app.services.identity.secrets.token_urlsafe",
        lambda _n=24: "test-session",
    )

    from app.services.ks_lifecycle import reset_ks_lifecycle_for_testing
    from app.services.request_resource_limits import (
        reset_request_resource_limiter_for_testing,
    )
    from app.services.session_context import _SQLITE_STORES, _reset_retention_sweeper_for_testing

    _SQLITE_STORES.clear()
    _reset_retention_sweeper_for_testing()
    reset_ks_lifecycle_for_testing()
    reset_request_resource_limiter_for_testing()
    yield
    reset_ks_lifecycle_for_testing()
    _reset_retention_sweeper_for_testing()
    reset_request_resource_limiter_for_testing()
    _SQLITE_STORES.clear()
