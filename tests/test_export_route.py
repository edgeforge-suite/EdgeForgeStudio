"""Tests for Step 8 export route behavior."""

import json
import re
import time
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.main import app
from app.models.project import DownstreamInterface, FieldMapping, UpstreamInterface
from app.services.generation_locks import acquire_generation_lock
from app.services.identity import Principal
from app.services.session_context import get_session_store
from app.services.settings import get_studio_settings
from app.services.signed_tokens import sign_payload
from tests.session_helpers import get_session, reset_session, save_session
from tests.test_package_writer import _full_session

client = TestClient(app)


def _csrf_from_html(html: str) -> str:
    match = re.search(
        r'<meta\s+name="edgeforge-csrf-token"\s+content="([^"]+)"',
        html,
    )
    assert match, "CSRF meta tag was not rendered"
    return match.group(1)


def _shared_client() -> tuple[TestClient, dict[str, str]]:
    client = TestClient(app, base_url="https://testserver")
    page = client.get("/")
    assert page.status_code == 200
    return client, {"x-edgeforge-csrf-token": _csrf_from_html(page.text)}


def _signed_session_cookie(session_id: str) -> str:
    settings = get_studio_settings()
    now = int(time.time())
    return sign_payload(
        {
            "sid": session_id,
            "iat": now,
            "exp": now + settings.session_max_age_seconds,
        },
        secret=settings.session_secret,
    )


def test_export_write_sets_last_export_path_to_bounded_context_folder(tmp_path):
    reset_session()
    session = _full_session()
    session.output_path = str(tmp_path)
    save_session(session)

    response = client.post("/export/write")

    assert response.status_code == 200
    payload = response.json()
    expected = tmp_path / "records"
    assert payload["ok"] is True
    assert payload["output_dir"] == str(expected)
    assert "evidence-trail.json" in payload["files"]
    assert payload["export_artifacts"]["output_dir"] == str(expected)
    assert any(item["name"] == "evidence-trail.json" for item in payload["export_artifacts"]["artifacts"])
    assert payload["latest_revision"]["revision_id"] == get_session().ks_workspace_state.manifest_revisions[-1].revision_id
    assert payload["latest_revision"]["export_path"] == str(expected)
    assert get_session().last_export_path == str(expected)
    assert get_session().ks_workspace_state.manifest_revisions[-1].export_path == str(expected)

    reset_session()


def test_export_write_blocks_unknown_canonical_mapping_target(tmp_path):
    reset_session()
    session = _full_session()
    session.output_path = str(tmp_path)
    session.upstream_interfaces[0].operation_mappings[0].request_mappings.append(
        FieldMapping(source="currency_code", target="Account.currency_code")
    )
    save_session(session)

    response = client.post("/export/write")

    assert response.status_code == 400
    assert response.json()["ok"] is False
    assert any(
        "Account.currency_code" in blocker
        and "not a field on selected entity" in blocker
        for blocker in response.json()["blockers"]
    )
    assert not (tmp_path / "records").exists()
    reset_session()


def test_export_write_uses_env_default_output_path_when_empty(monkeypatch, tmp_path):
    from app.services.runtime_defaults import DEFAULT_OUTPUT_PATH_ENV

    reset_session()
    session = _full_session()
    session.output_path = ""
    save_session(session)
    default_output = tmp_path / "docker-data" / "GeneratedApps"
    monkeypatch.setenv(DEFAULT_OUTPUT_PATH_ENV, str(default_output))

    response = client.post("/export/write")

    assert response.status_code == 200
    expected = default_output / "records"
    payload = response.json()
    assert payload["ok"] is True
    assert payload["output_dir"] == str(expected)
    assert expected.exists()

    reset_session()


def test_export_write_rejects_session_disk_quota(monkeypatch):
    reset_session()
    session = _full_session()
    save_session(session)
    session = get_session()
    workspace_root = Path(session.workspace_root or "")
    workspace_root.mkdir(parents=True, exist_ok=True)
    (workspace_root / "quota.bin").write_bytes(b"12345")
    monkeypatch.setenv("EDGEFORGE_STUDIO_MAX_SESSION_DISK_BYTES", "4")

    response = client.post("/export/write")

    assert response.status_code == 413
    payload = response.json()
    assert payload["ok"] is False
    assert "Session workspace quota exceeded" in payload["error"]
    assert get_session().last_export_path is None
    reset_session()


def test_shared_mode_export_write_ignores_user_output_path(monkeypatch, tmp_path):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    reset_session()
    session = _full_session()
    evil_output = tmp_path / "evil-output"
    session.output_path = str(evil_output)
    save_session(session)
    workspace_root = Path(session.workspace_root or "")
    client, headers = _shared_client()

    response = client.post("/export/write", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    expected = workspace_root / "output" / "records"
    assert payload["ok"] is True
    assert payload["output_dir"] == str(expected)
    assert Path(payload["output_dir"]).is_relative_to(workspace_root)
    assert not (evil_output / "records").exists()
    assert get_session().last_export_path == str(expected)

    zip_response = client.get("/export/download-zip")

    assert zip_response.status_code == 200
    assert (workspace_root / "exports" / "records-appbuilder-package.zip").exists()
    reset_session()


def test_shared_mode_engine_actions_use_operator_repo_path(monkeypatch, tmp_path):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS", "example.com")
    operator_repo = tmp_path / "operator-engine"
    monkeypatch.setenv("EDGEFORGE_STUDIO_ENGINE_REPO", str(operator_repo))
    reset_session()
    session = _full_session()
    session.appbuilder_repo_path = str(tmp_path / "user-supplied-engine")
    save_session(session)
    client, headers = _shared_client()

    write_response = client.post("/export/write", headers=headers)
    assert write_response.status_code == 200
    export_dir = Path(write_response.json()["output_dir"])
    original_manifest_bytes = (export_dir / "app-definition.yaml").read_bytes()
    captured: dict[str, str] = {}

    class FakeResult:
        success = True
        combined_output = "ok"

    def fake_validate(manifest_path: Path, repo_path: str, **_kwargs):
        captured["validate"] = repo_path
        assert manifest_path == export_dir / "app-definition.yaml"
        return FakeResult()

    def fake_assess(spec_url: str, repo_path: str, **kwargs):
        captured["assess"] = repo_path
        cache_path = Path(kwargs["openapi_cache_path"])
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        local_source = cache_path.parent / cache["sources"][spec_url]
        assert yaml.safe_load(local_source.read_text(encoding="utf-8"))["openapi"] == "3.1.0"
        return FakeResult()

    def fake_generate(manifest_path: str, output_dir: str, repo_path: str, **kwargs):
        captured["generate"] = repo_path
        captured["generate_output"] = output_dir
        assert Path(manifest_path) == export_dir / "app-definition.yaml"
        invocation_payload = yaml.safe_load(Path(manifest_path).read_text(encoding="utf-8"))
        source = invocation_payload["upstream_interfaces"][0]
        assert source["spec_url"] == "https://example.com/synthetic-account.json"
        cache_path = Path(kwargs["openapi_cache_path"])
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        assert source["spec_url"] in cache["sources"]
        return FakeResult()

    monkeypatch.setattr("app.routes.export.validate_manifest", fake_validate)
    monkeypatch.setattr("app.routes.export.run_assess", fake_assess)
    monkeypatch.setattr("app.routes.export.run_generate", fake_generate)

    validate_response = client.post("/export/validate", headers=headers)
    assess_response = client.post("/export/assess", headers=headers)
    generate_response = client.post("/export/generate", headers=headers)

    assert validate_response.status_code == 200
    assert assess_response.status_code == 200
    assert generate_response.status_code == 200
    assert captured["validate"] == str(operator_repo)
    assert captured["assess"] == str(operator_repo)
    assert captured["generate"] == str(operator_repo)
    assert captured["generate_output"] == str(export_dir / "generated-app")
    assert Path(captured["generate_output"]).is_relative_to(Path(get_session().workspace_root or ""))
    exported_payload = yaml.safe_load(
        (export_dir / "app-definition.yaml").read_text(encoding="utf-8")
    )
    assert (export_dir / "app-definition.yaml").read_bytes() == original_manifest_bytes
    assert exported_payload["upstream_interfaces"][0]["spec_url"] == (
        "https://example.com/synthetic-account.json"
    )
    assert not list(export_dir.glob(".studio-openapi-*"))
    reset_session()


def test_export_generate_rejects_when_output_path_is_locked(monkeypatch, tmp_path):
    reset_session()
    session = _full_session()
    session.output_path = str(tmp_path)
    save_session(session)
    write_response = client.post("/export/write")
    assert write_response.status_code == 200
    export_dir = Path(write_response.json()["output_dir"])
    gen_output = export_dir / "generated-app"

    def fail_generate(*args, **kwargs):
        raise AssertionError("run_generate should not be called while output lock is held")

    monkeypatch.setattr("app.routes.export.run_generate", fail_generate)

    with acquire_generation_lock(gen_output) as acquired:
        assert acquired is True
        response = client.post("/export/generate")

    assert response.status_code == 409
    payload = response.json()
    assert payload["ok"] is False
    assert payload["output_dir"] == str(gen_output)
    assert "already in progress" in payload["error"]
    reset_session()


def test_shared_mode_generate_outputs_are_isolated_by_session_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    monkeypatch.setenv(
        "EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS",
        "example.com",
    )
    settings = get_studio_settings()
    store = get_session_store()
    generated_outputs: list[Path] = []
    workspaces: list[Path] = []

    class FakeResult:
        success = True
        combined_output = "generated"

    def fake_generate(manifest_path: str, output_dir: str, repo_path: str, **_kwargs):
        generated_outputs.append(Path(output_dir))
        return FakeResult()

    monkeypatch.setattr("app.routes.export.run_generate", fake_generate)

    for session_id, bounded_context in (("browser-a", "a-context"), ("browser-b", "b-context")):
        principal = Principal(
            user_id=f"anonymous:{session_id}",
            source="anonymous",
            claims={"anonymous_session_id": session_id},
        )
        active = store.get_or_create(principal)
        seeded = _full_session()
        seeded.session_id = active.session_id
        seeded.workspace_root = active.workspace_root
        seeded.bounded_context = bounded_context
        seeded.output_path = str(tmp_path / "evil-shared-output")
        store.save(seeded)

        browser = TestClient(app, base_url="https://testserver")
        browser.cookies.set(settings.session_cookie_name, _signed_session_cookie(session_id))
        page = browser.get("/")
        headers = {"x-edgeforge-csrf-token": _csrf_from_html(page.text)}
        write_response = browser.post("/export/write", headers=headers)
        assert write_response.status_code == 200, write_response.text
        generate_response = browser.post("/export/generate", headers=headers)
        assert generate_response.status_code == 200, generate_response.text
        workspaces.append(Path(active.workspace_root or ""))

    assert len(generated_outputs) == 2
    assert generated_outputs[0] != generated_outputs[1]
    assert generated_outputs[0].is_relative_to(workspaces[0])
    assert generated_outputs[1].is_relative_to(workspaces[1])
    assert not generated_outputs[0].is_relative_to(workspaces[1])
    assert not generated_outputs[1].is_relative_to(workspaces[0])


def test_shared_mode_export_assess_rejects_non_allowlisted_spec_url_before_engine(monkeypatch, tmp_path):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE", "allowlist")
    monkeypatch.delenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS", raising=False)
    reset_session()
    session = _full_session()
    session.output_path = str(tmp_path)
    save_session(session)
    client, headers = _shared_client()

    def fail_run_assess(*args, **kwargs):
        raise AssertionError("Engine assess should not be called for blocked shared-mode URLs")

    monkeypatch.setattr("app.routes.export.run_assess", fail_run_assess)

    response = client.post("/export/assess", headers=headers)

    assert response.status_code == 400
    assert response.json()["ok"] is False
    assert "host is not allowed" in response.json()["error"]
    reset_session()


def test_shared_mode_export_assess_rejects_disabled_fetch_mode_before_engine(monkeypatch, tmp_path):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE", "disabled")
    reset_session()
    session = _full_session()
    session.output_path = str(tmp_path)
    save_session(session)
    client, headers = _shared_client()

    def fail_run_assess(*args, **kwargs):
        raise AssertionError("Engine assess should not be called when shared-mode URL fetch is disabled")

    monkeypatch.setattr("app.routes.export.run_assess", fail_run_assess)

    response = client.post("/export/assess", headers=headers)

    assert response.status_code == 400
    assert response.json()["ok"] is False
    assert "fetch is disabled" in response.json()["error"]
    reset_session()


def test_shared_mode_export_assess_allows_allowlisted_spec_url(monkeypatch, tmp_path):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE", "allowlist")
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS", "example.com")
    reset_session()
    session = _full_session()
    session.output_path = str(tmp_path)
    save_session(session)
    client, headers = _shared_client()
    captured: dict[str, str] = {}

    class FakeResult:
        success = True
        combined_output = "assessed"

    def fake_run_assess(spec_url: str, repo_path: str, **kwargs):
        captured["spec_url"] = spec_url
        cache_path = Path(kwargs["openapi_cache_path"])
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        local_source = cache_path.parent / cache["sources"][spec_url]
        captured["local_source"] = local_source.read_text(encoding="utf-8")
        return FakeResult()

    monkeypatch.setattr("app.routes.export.run_assess", fake_run_assess)

    response = client.post("/export/assess", headers=headers)

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert captured["spec_url"] == "https://example.com/synthetic-account.json"
    assert json.loads(captured["local_source"])["openapi"] == "3.1.0"
    reset_session()


def test_shared_assess_rejects_unlisted_public_redirect_before_engine(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE", "allowlist")
    monkeypatch.setenv(
        "EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS",
        "example.com",
    )
    reset_session()
    session = _full_session()
    session.output_path = str(tmp_path)
    save_session(session)
    client, headers = _shared_client()

    class RedirectResponse:
        status = 302
        headers = {"Location": "https://unlisted.example/openapi.yaml"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(
        "app.services.openapi_fetch_guard._open_url",
        lambda target, timeout: RedirectResponse(),
    )
    monkeypatch.setattr(
        "app.routes.export.run_assess",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("unlisted redirect reached the Engine child")
        ),
    )

    response = client.post("/export/assess", headers=headers)

    assert response.status_code == 400
    assert response.json()["error"] == "OpenAPI URL redirect target is not allowed."
    reset_session()


def test_local_export_assess_honors_disabled_fetch_policy(monkeypatch, tmp_path):
    monkeypatch.delenv("EDGEFORGE_STUDIO_SHARED_MODE", raising=False)
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE", "disabled")
    reset_session()
    session = _full_session()
    session.output_path = str(tmp_path)
    save_session(session)

    monkeypatch.setattr(
        "app.routes.export.run_assess",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("disabled local policy reached Engine assess")
        ),
    )

    response = client.post("/export/assess")

    assert response.status_code == 400
    assert response.json()["error"] == "OpenAPI URL fetch is disabled by Studio policy."
    reset_session()


def test_local_loopback_assess_gives_engine_a_local_source(monkeypatch, tmp_path):
    monkeypatch.delenv("EDGEFORGE_STUDIO_SHARED_MODE", raising=False)
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE", "open")
    reset_session()
    session = _full_session()
    session.output_path = str(tmp_path)
    session.upstream_interfaces[0].spec_url = "http://127.0.0.1:8081/openapi.json"
    save_session(session)
    captured: dict[str, str] = {}

    class FakeResult:
        success = True
        combined_output = "assessed"

    def fake_run_assess(spec_url: str, repo_path: str, **kwargs):
        captured["spec_url"] = spec_url
        captured["openapi_cache_path"] = kwargs["openapi_cache_path"]
        assert Path(captured["openapi_cache_path"]).is_file()
        return FakeResult()

    monkeypatch.setattr("app.routes.export.run_assess", fake_run_assess)

    response = client.post("/export/assess")

    assert response.status_code == 200
    assert captured["spec_url"] == "http://127.0.0.1:8081/openapi.json"
    assert not Path(captured["openapi_cache_path"]).exists()
    reset_session()


def test_generate_preflight_blocks_disabled_saved_spec_url(monkeypatch, tmp_path):
    monkeypatch.delenv("EDGEFORGE_STUDIO_SHARED_MODE", raising=False)
    reset_session()
    session = _full_session()
    session.output_path = str(tmp_path)
    save_session(session)
    assert client.post("/export/write").status_code == 200
    session = get_session()
    session.upstream_interfaces = []
    save_session(session)
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE", "disabled")
    monkeypatch.setattr(
        "app.routes.export.run_generate",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("disabled saved spec_url reached Engine generation")
        ),
    )

    response = client.post("/export/generate")

    assert response.status_code == 400
    assert response.json()["error"] == "OpenAPI URL fetch is disabled by Studio policy."
    reset_session()


def test_shared_mode_exports_are_isolated_by_session_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    settings = get_studio_settings()
    store = get_session_store()
    outputs: list[Path] = []
    workspaces: list[Path] = []

    for session_id, bounded_context in (("browser-a", "a-context"), ("browser-b", "b-context")):
        principal = Principal(
            user_id=f"anonymous:{session_id}",
            source="anonymous",
            claims={"anonymous_session_id": session_id},
        )
        active = store.get_or_create(principal)
        seeded = _full_session()
        seeded.session_id = active.session_id
        seeded.workspace_root = active.workspace_root
        seeded.bounded_context = bounded_context
        seeded.output_path = str(tmp_path / "evil-shared-output")
        store.save(seeded)

        browser = TestClient(app, base_url="https://testserver")
        browser.cookies.set(settings.session_cookie_name, _signed_session_cookie(session_id))
        page = browser.get("/")
        headers = {"x-edgeforge-csrf-token": _csrf_from_html(page.text)}

        response = browser.post("/export/write", headers=headers)

        assert response.status_code == 200, response.text
        output = Path(response.json()["output_dir"])
        workspace = Path(active.workspace_root or "")
        assert output.is_relative_to(workspace)
        outputs.append(output)
        workspaces.append(workspace)

    assert outputs[0] != outputs[1]
    assert workspaces[0] != workspaces[1]
    assert not outputs[0].is_relative_to(workspaces[1])
    assert not outputs[1].is_relative_to(workspaces[0])


def test_export_write_blocks_when_no_entities_selected():
    reset_session()
    session = get_session()
    session.app_name = "LoanLite"
    session.bounded_context = "lending"
    session.target_profile = "springboot-legacy-compatible"
    save_session(session)

    response = client.post("/export/write")

    assert response.status_code == 400
    payload = response.json()
    assert payload["ok"] is False
    assert "cannot be exported" in payload["error"].lower()
    assert any("No entities selected" in blocker for blocker in payload["blockers"])

    reset_session()


def test_export_write_allows_valid_edge_contract_only_project(tmp_path):
    reset_session()
    session = get_session()
    session.app_name = "Edge Contracts"
    session.bounded_context = "edge-contracts"
    session.target_profile = "springboot-legacy-compatible"
    session.output_path = str(tmp_path)
    session.selected_entity_names = []
    session.classified_entities = []
    session.upstream_interfaces = [
        UpstreamInterface(
            name="account-xml",
            type="xml-xsd",
            xsd_path="contracts/account.xsd",
            xsd_content="<xs:schema/>",
            root_element="acct:Account",
        ),
        UpstreamInterface(
            name="account-soap",
            type="soap-wsdl",
            wsdl_path="contracts/account.wsdl",
            wsdl_content="<definitions/>",
        ),
    ]
    session.downstream_interfaces = [
        DownstreamInterface(
            name="account-csv",
            type="file-csv",
            spec="downstream/account-csv-layout.yaml",
            spec_content=(
                "format: csv\n"
                "record_types:\n"
                "  data:\n"
                "    fields:\n"
                "      - name: account_id\n"
                "        column: 1\n"
            ),
        )
    ]
    save_session(session)

    response = client.post("/export/write")

    assert response.status_code == 200
    payload = response.json()
    project_dir = tmp_path / "edge-contracts"
    assert payload["ok"] is True
    assert (project_dir / "app-definition.yaml").exists()
    assert (project_dir / "contracts/account.xsd").read_text(encoding="utf-8") == "<xs:schema/>"
    assert (project_dir / "contracts/account.wsdl").read_text(encoding="utf-8") == "<definitions/>"
    exported_csv = yaml.safe_load(
        (project_dir / "downstream/account-csv-layout.yaml").read_text(encoding="utf-8")
    )
    assert exported_csv["record_types"]["data"]["fields"] == [
        {"name": "account_id", "column": 1}
    ]

    reset_session()


def test_export_write_blocks_incomplete_edge_contract_only_project(tmp_path):
    reset_session()
    session = get_session()
    session.app_name = "Edge Contracts"
    session.bounded_context = "edge-contracts"
    session.target_profile = "springboot-legacy-compatible"
    session.output_path = str(tmp_path)
    session.selected_entity_names = []
    session.classified_entities = []
    session.upstream_interfaces = [
        UpstreamInterface(
            name="account-xml",
            type="xml-xsd",
            xsd_path="contracts/account.xsd",
        )
    ]
    save_session(session)

    response = client.post("/export/write")

    assert response.status_code == 400
    payload = response.json()
    assert any("account-xml" in blocker and "root element" in blocker for blocker in payload["blockers"])
    assert not any("No entities selected" in blocker for blocker in payload["blockers"])

    reset_session()


def test_export_artifact_download_helper_streams_last_written_sidecar(tmp_path):
    reset_session()
    session = _full_session()
    session.output_path = str(tmp_path)
    save_session(session)

    write_response = client.post("/export/write")

    assert write_response.status_code == 200
    artifact_response = client.get("/export/artifact/evidence-trail.json")

    assert artifact_response.status_code == 200
    assert artifact_response.headers["content-disposition"].endswith('filename="evidence-trail.json"')
    expected = Path(write_response.json()["output_dir"]) / "evidence-trail.json"
    assert artifact_response.content == expected.read_bytes()

    reset_session()


def test_export_assess_refreshes_assessment_report_artifact(monkeypatch, tmp_path):
    reset_session()
    session = _full_session()
    session.output_path = str(tmp_path)
    save_session(session)

    write_response = client.post("/export/write")
    assert write_response.status_code == 200
    export_dir = Path(write_response.json()["output_dir"])

    def fake_run_assess(spec_url: str, repo_path: str, **_kwargs):
        class FakeResult:
            success = True
            combined_output = f"assessed {spec_url}"

        return FakeResult()

    monkeypatch.setattr("app.routes.export.run_assess", fake_run_assess)

    assess_response = client.post("/export/assess")

    assert assess_response.status_code == 200
    payload = json.loads((export_dir / "assessment-report.json").read_text(encoding="utf-8"))
    assert payload["source"] == "export/assess"
    assert payload["app_name"] == session.app_name
    assert payload["bounded_context"] == session.bounded_context
    assert len(payload["results"]) == 1
    result = payload["results"][0]
    assert result["interface"] == "synthetic-account-api"
    assert result["ok"] is True
    assert result["output"] == "assessed https://example.com/synthetic-account.json"
    assert result["warnings"] == []
    assert result["errors"] == []
    assert result["summary"] is None
    assert result["diagnostic_id"].startswith("diag-")

    reset_session()


def test_export_assess_sanitizes_browser_and_persisted_engine_output(monkeypatch, tmp_path):
    reset_session()
    session = _full_session()
    session.output_path = str(tmp_path)
    save_session(session)
    export_dir = Path(client.post("/export/write").json()["output_dir"])
    raw = (
        "Traceback (most recent call last):\n"
        '  File "/Users/example/private/assess.py", line 7, in assess\n'
        "RuntimeError: Schema field 'accountId' is invalid; PASSWORD=hunter2\n"
        "Authorization: Bearer super-secret-token\n"
        "--authorization Bearer option-secret-token\n"
        "--authorization=Basic dXNlcjpwYXNz\n"
        "HTTP_AUTHORIZATION=Bearer env-secret-token\n"
        "REDIRECT_HTTP_AUTHORIZATION=Bearer redirect-secret-token\n"
        "X_AUTHORIZATION=Basic eDpzZWNyZXQ=\n"
        "DATABASE_URL=postgresql://alice:db-password@db.internal/prod\n"
        "JDBC_URL=jdbc:postgresql://bob:jdbc-password@db.internal/prod\n"
        "Manifest /Users/alice/My Private Project/app-definition.yaml\n"
        "Manifest /Users/alice/Hidden Workspace/generated-app\n"
        "Manifest C:\\Users\\Alice\\Sensitive Workspace\\generated-app\n"
        "Schema /tmp/generated-app because field customerId is required\n"
        "Manifest /Users/alice/Project,Secret/generated-app\n"
        "Manifest C:\\Users\\Alice\\Project (Secret)\\generated-app\n"
        "path:/Users/alice/Colon Secret/generated-app\n"
        "manifest:C:\\Users\\Alice\\Colon Secret\\generated-app\n"
        "Manifest /Users/alice/Project, file Boundary Secret/generated-app\n"
        "Manifest C:\\Users\\Alice\\Project because field Boundary Secret\\generated-app\n"
        "https://user:pass@example.test/openapi.yaml?token=query-secret\n"
    )

    class FakeResult:
        success = False
        combined_output = raw

    monkeypatch.setattr("app.routes.export.run_assess", lambda *_args, **_kwargs: FakeResult())

    response = client.post("/export/assess")
    report_text = (export_dir / "assessment-report.json").read_text(encoding="utf-8")
    response_text = response.text

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["diagnostic_id"].startswith("diag-")
    assert result["diagnostic_id"] in report_text
    assert "Schema field 'accountId' is invalid" in response_text
    for sentinel in (
        "Traceback",
        "/Users/example",
        "hunter2",
        "super-secret-token",
        "option-secret-token",
        "dXNlcjpwYXNz",
        "env-secret-token",
        "redirect-secret-token",
        "eDpzZWNyZXQ=",
        "db-password",
        "jdbc-password",
        "Private Project",
        "Hidden Workspace",
        "Sensitive Workspace",
        "Project,Secret",
        "Project (Secret)",
        "Colon Secret",
        "Boundary Secret",
        "user:pass",
        "query-secret",
    ):
        assert sentinel not in response_text
        assert sentinel not in report_text
    assert "[redacted]]" not in response_text
    assert "[redacted]]" not in report_text
    assert "because field customerId is required" in response_text
    assert "because field customerId is required" in report_text

    reset_session()
