from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.services.session_context import _SQLITE_STORES
from tests.smoke._shared import (
    assert_build_run_rejected_server_side as _assert_build_run_rejected_server_side,
)
from tests.smoke._shared import (
    assert_csrf_enforced as _assert_csrf_enforced,
)
from tests.smoke._shared import (
    assert_openapi_url_policy as _assert_openapi_url_policy,
)
from tests.smoke._shared import (
    assert_path_under as _assert_path_under,
)
from tests.smoke._shared import (
    assert_server_owned_paths as _assert_server_owned_paths,
)
from tests.smoke._shared import (
    export_package as _export_package,
)
from tests.smoke._shared import (
    make_exportable_smoke_session as _make_exportable_smoke_session,
)
from tests.smoke._shared import (
    new_shared_client as _new_shared_client,
)
from tests.smoke._shared import (
    post_step1 as _post_step1,
)
from tests.smoke._shared import (
    save_session_for_client as _save_session_for_client,
)
from tests.smoke._shared import (
    session_for_client as _session_for_client,
)
from tests.smoke._shared import (
    session_id_from_client as _session_id_from_client,
)
from tests.smoke._shared import (
    upload_openapi as _upload_openapi,
)

pytestmark = [pytest.mark.smoke, pytest.mark.l2]

SMOKE_PREFIX = "edgeforge-suite-smoke-studio-l2-"
SHARED_SECRET = "l2-shared-mode-smoke-secret"


def _prune_previous_smoke_roots() -> None:
    for candidate in Path("/tmp").glob(f"{SMOKE_PREFIX}*"):
        if candidate.is_dir():
            shutil.rmtree(candidate, ignore_errors=True)


@pytest.fixture
def smoke_root(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> Iterator[Path]:
    _prune_previous_smoke_roots()
    root = Path(tempfile.mkdtemp(prefix=SMOKE_PREFIX, dir="/tmp"))
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", SHARED_SECRET)
    monkeypatch.setenv("EDGEFORGE_STUDIO_STATE_DIR", str(root / "studio-state"))
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE", "allowlist")
    monkeypatch.delenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("EDGEFORGE_STUDIO_BUILD_RUN_ENABLED", raising=False)
    _SQLITE_STORES.clear()
    yield root
    call_report = getattr(request.node, "rep_call", None)
    if call_report is not None and call_report.passed:
        shutil.rmtree(root, ignore_errors=True)
    else:
        print(f"Studio L2 smoke retained temp root for triage: {root}")
    _SQLITE_STORES.clear()


def test_studio_l2_shared_mode_two_session_smoke(monkeypatch: pytest.MonkeyPatch, smoke_root: Path):
    calls: list[str] = []

    def fail_ks_client(*_args, **_kwargs):
        calls.append("ks_client")
        raise AssertionError("KS must not be called in the KA-OFF L2 smoke")

    def fail_ks_start(*_args, **_kwargs):
        calls.append("KSClient.start")
        raise AssertionError("KSClient.start must not be called in the KA-OFF L2 smoke")

    monkeypatch.setattr("app.integrations.ks_integration.KSClient.start", fail_ks_start)
    monkeypatch.setattr("app.integrations.ks_integration.ks_client", fail_ks_client)
    monkeypatch.setattr("app.services.assist_service.ks_client", fail_ks_client)
    monkeypatch.setattr("app.routes.knowledge.ks_client", fail_ks_client)
    monkeypatch.setattr("app.routes.entities.ks_client", fail_ks_client)
    monkeypatch.setattr("app.services.evidence_trail.ks_client", fail_ks_client)

    token_values = iter(["browser-a", "browser-b"])
    monkeypatch.setattr(
        "app.services.identity.secrets.token_urlsafe",
        lambda _n=24: next(token_values),
    )

    client_a, csrf_a = _new_shared_client()
    client_b, csrf_b = _new_shared_client()
    session_id_a = _session_id_from_client(client_a)
    session_id_b = _session_id_from_client(client_b)
    assert session_id_a == "browser-a"
    assert session_id_b == "browser-b"
    assert session_id_a != session_id_b

    # CSRF: native-form and fetch-style POSTs both fail without a token in shared mode.
    _assert_csrf_enforced(client_a)

    evil_a = smoke_root.parent / f"{smoke_root.name}-evil-a"
    evil_b = smoke_root.parent / f"{smoke_root.name}-evil-b"
    _post_step1(
        client_a,
        csrf_a,
        app_name="Alpha Smoke App",
        bounded_context="alpha-smoke",
        output_path=evil_a,
    )
    _post_step1(
        client_b,
        csrf_b,
        app_name="Beta Smoke App",
        bounded_context="beta-smoke",
        output_path=evil_b,
    )

    page_a = client_a.get("/")
    page_b = client_b.get("/")
    assert page_a.status_code == 200
    assert page_b.status_code == 200
    assert "Alpha Smoke App" in page_a.text
    assert "Beta Smoke App" not in page_a.text
    assert "Beta Smoke App" in page_b.text
    assert "Alpha Smoke App" not in page_b.text

    # OpenAPI URL policy: shared-mode allowlist defaults closed, including loopback.
    _assert_openapi_url_policy(client_a, csrf_a)

    _upload_openapi(client_a, csrf_a, filename="alpha-openapi.yaml", entity_name="AlphaRecord")
    _upload_openapi(client_b, csrf_b, filename="beta-openapi.yaml", entity_name="BetaRecord")
    session_a = _session_for_client(client_a)
    session_b = _session_for_client(client_b)
    assert session_a.raw_spec_filename == "alpha-openapi.yaml"
    assert session_b.raw_spec_filename == "beta-openapi.yaml"
    assert "AlphaRecord" in (session_a.raw_spec_content or "")
    assert "BetaRecord" not in (session_a.raw_spec_content or "")
    assert "BetaRecord" in (session_b.raw_spec_content or "")
    assert "AlphaRecord" not in (session_b.raw_spec_content or "")

    workspace_a = Path(session_a.workspace_root or "")
    workspace_b = Path(session_b.workspace_root or "")
    assert workspace_a != workspace_b
    _assert_path_under(workspace_a, smoke_root / "studio-state")
    _assert_path_under(workspace_b, smoke_root / "studio-state")

    _make_exportable_smoke_session(session_a, entity_name="AlphaRecord", contract_name="alpha")
    _make_exportable_smoke_session(session_b, entity_name="BetaRecord", contract_name="beta")
    _save_session_for_client(client_a, session_a)
    _save_session_for_client(client_b, session_b)

    export_a = _export_package(client_a, csrf_a)
    export_b = _export_package(client_b, csrf_b)
    output_a = Path(export_a["output_dir"])
    output_b = Path(export_b["output_dir"])
    _assert_server_owned_paths(
        output_a=output_a,
        output_b=output_b,
        workspace_a=workspace_a,
        workspace_b=workspace_b,
        evil_a=evil_a,
        evil_b=evil_b,
    )
    assert (output_a / "app-definition.yaml").exists()
    assert (output_b / "app-definition.yaml").exists()
    assert "AlphaRecord" in (output_a / "contracts" / "alpha-openapi.yaml").read_text(encoding="utf-8")
    assert "BetaRecord" in (output_b / "contracts" / "beta-openapi.yaml").read_text(encoding="utf-8")
    assert not (output_a / "contracts" / "beta-openapi.yaml").exists()
    assert not (output_b / "contracts" / "alpha-openapi.yaml").exists()

    # Shared-mode Build & Run stays server-disabled by default even with exported packages.
    _assert_build_run_rejected_server_side(client_a, csrf_a)

    import app.services.session_store as deprecated_session_store

    for accessor in ("get_session", "save_session", "reset_session"):
        with pytest.raises(RuntimeError):
            getattr(deprecated_session_store, accessor)

    assert calls == []
    assert smoke_root.exists()
