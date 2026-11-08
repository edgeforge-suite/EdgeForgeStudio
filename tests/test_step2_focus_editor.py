"""PR-15 route and static-contract coverage for Step 2 focus mode.

The repository deliberately has no jsdom browser harness. These tests cover
server-rendered URL state and use static assertions for the DOM interactions
that need a live-browser review (save reconciliation, conflict recovery, and
dirty navigation).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models.project import FieldMapping, UpstreamInterface
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)
ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "app" / "templates" / "step2_upstream.html"
STUDIO_JS = ROOT / "app" / "static" / "js" / "studio.js"
NODE = shutil.which("node")


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _session_with_upstream_contract() -> UpstreamInterface:
    session = get_session()
    session.app_name = "Upstream Focus Fixture"
    session.bounded_context = "upstream-focus-fixture"
    session.app_archetype = "crud"
    session.project_revision = 11
    interface = UpstreamInterface(
        name="account-xml",
        type="xml-xsd",
        version="v1",
        system="CORE",
        entity_name="Account",
        xsd_path="contracts/account.xsd",
        xsd_content="<xs:schema/>",
        root_element="AccountMessage",
        namespace="urn:account:v1",
        mapping_path="upstream/account-mapping.yaml",
        field_mappings=[FieldMapping(source="accountId", target="Account.accountId")],
    )
    session.upstream_interfaces = [interface]
    save_session(session)
    return interface


def _rendered_inline_script(html: str) -> str:
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.DOTALL)
    return next(script for script in scripts if "function upstreamEdgeContractPayload" in script)


def test_flag_on_focus_loads_saved_static_form_values_from_route_context(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    interface = _session_with_upstream_contract()

    response = client.get(f"/upstream?focus={interface.name}")

    assert response.status_code == 200
    html = response.text
    assert f'data-uxr-focus-editor="{interface.name}"' in html
    assert 'data-source-of-truth-version="11"' in html
    assert 'data-uxr-save-one' in html
    assert 'data-uxr-cancel-focus' in html
    assert 'data-uxr-tab-badges' in html
    assert 'data-uxr-row-name="account-xml"' in html
    assert 'data-uxr-edit-target="account-xml"' in html
    assert 'id="xsd"' in html
    assert 'id="wsdl"' in html
    assert 'id="layout"' in html

    script = _rendered_inline_script(html)
    match = re.search(r"let uxrUpstreamLastSavedItem = (.*?);", script)
    assert match
    loaded = json.loads(match.group(1))
    assert loaded["name"] == interface.name
    assert loaded["xsd_path"] == interface.xsd_path
    assert loaded["root_element"] == interface.root_element
    assert loaded["mapping_path"] == interface.mapping_path


def test_unknown_or_absent_focus_stays_in_add_mode_and_retired_flag_is_inert(monkeypatch):
    interface = _session_with_upstream_contract()

    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    unknown = client.get("/upstream?focus=missing-contract").text
    absent = client.get("/upstream").text
    assert "data-uxr-focus-editor=" not in unknown
    assert "data-uxr-focus-editor=" not in absent
    unknown_markup = re.sub(r"<script[^>]*>.*?</script>", "", unknown, flags=re.DOTALL)
    assert "data-uxr-save-one" not in unknown_markup

    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    default_on = client.get(f"/upstream?focus={interface.name}").text
    assert f'data-uxr-focus-editor="{interface.name}"' in default_on
    assert f'data-uxr-row-name="{interface.name}"' in default_on
    assert "data-uxr-edit-target" in default_on
    assert "uxrSaveFocusedUpstreamInterface" in default_on


def test_focus_static_contract_preserves_dirty_conflict_and_five_surface_paths():
    template = TEMPLATE.read_text(encoding="utf-8")
    studio_js = STUDIO_JS.read_text(encoding="utf-8")

    assert "function loadUpstreamInterface(data)" in template
    assert "refreshEdgeContractFields();" in template
    assert "refreshSoapMappingMode();" in template
    assert "function upstreamEdgeContractPayload()" in template
    assert "item: upstreamEdgeContractPayload()" in template
    assert "original_name: uxrUpstreamFocusOriginalName" in template
    assert "source_of_truth_version: uxrUpstreamFocusSourceVersion" in template
    assert "postJSON('/upstream/edge-contract/save'" in template
    assert (
        "uxrUpdateBoardRowFromSaved(data.readiness, previousName, data.board_metadata)"
        in template
    )
    assert "uxrUpdateAmbientAndRail(data)" in template
    assert "uxrRegroupBoardRow(row)" in template
    assert "uxrRecomputeStatsAndFilterCounts()" in template
    assert "uxrApplyBoardFilters()" in template
    assert "if (!entry.count)" in template
    assert "chip.className = 'badge uxr-rail-chip'" in template
    assert "history.replaceState({}, '', `/upstream?focus=${encodeURIComponent(data.item.name)}`)" in template
    assert "window.createDirtyTracker({" in template
    assert "snapshot: upstreamEdgeContractPayload" in template
    assert "data-dirty-navigation" in template
    assert "function uxrPresentUpstreamConflict(data)" in template
    assert "Your unsaved edits are preserved" in template
    assert "function uxrReloadUpstreamConflictItem()" in template

    conflict_start = template.index("if (!data.ok)")
    conflict_end = template.index("uxrRenderUpstreamSaveBlockers(data.blockers)", conflict_start)
    conflict_branch = template[conflict_start:conflict_end]
    assert "uxrPresentUpstreamConflict(data)" in conflict_branch
    assert "loadUpstreamInterface" not in conflict_branch

    assert "function createDirtyTracker({ snapshot })" in studio_js
    assert "window.addEventListener('beforeunload'" in studio_js
    assert "document.addEventListener('click', guardNavigation, true)" in studio_js


def test_real_400_field_refs_have_focus_selectors_and_the_rendered_focus_script_parses(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _session_with_upstream_contract()
    template = TEMPLATE.read_text(encoding="utf-8")
    map_start = template.index("const UXR_UPSTREAM_SAVE_BLOCKER_FIELD_SELECTORS = {")
    map_end = template.index("};", map_start)
    selector_map = template[map_start:map_end]
    for field_ref, selector in {
        "name": "#edge-contract-name",
        "type": "#edge-contract-type",
        "xsd_path": "#edge-contract-xsd-path",
        "root_element": "#edge-contract-root-element",
        "wsdl_path": "#edge-contract-wsdl-path",
        "spec": "#edge-contract-spec",
        "entity_name": "#edge-contract-entity-name",
    }.items():
        assert f"{field_ref}: '{selector}'" in selector_map
        assert f'id="{selector[1:]}"' in template

    html = client.get("/upstream?focus=account-xml").text
    script = _rendered_inline_script(html)
    assert NODE, "Step 2 static script syntax check requires Node (no npm packages are used)."
    completed = subprocess.run(
        [NODE, "--check", "-"],
        input=script,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
