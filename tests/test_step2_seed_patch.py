"""PR-15 coverage for Step 2's deterministic upstream mapping seeds.

The matching unit is intentionally shared, DOM-free JavaScript. These tests
run it with Node against fields returned by Studio's upstream inspector; DOM
wiring is checked statically because this Python project has no jsdom suite.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models.project import UpstreamInterface
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


def _seed_session() -> None:
    session = get_session()
    session.app_name = "Upstream Seed Fixture"
    session.bounded_context = "upstream-seed-fixture"
    session.app_archetype = "crud"
    session.upstream_interfaces = [
        UpstreamInterface(
            name="record-fixed",
            type="file-fixed-width",
            entity_name="Record",
            spec="upstream/record-layout.yaml",
            spec_content="format: fixed-width\n",
        )
    ]
    save_session(session)


def _seed_script(monkeypatch) -> str:
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    html = client.get("/upstream?focus=record-fixed").text
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.DOTALL)
    page_script = next(script for script in scripts if "function upstreamEdgeContractPayload" in script)
    source = STUDIO_JS.read_text(encoding="utf-8")
    shared = source[
        source.index("/* ---- Deterministic seed patches ----") : source.index("/* ---- Tabs ---- */")
    ]
    return f"{shared}\n{page_script}"


def _run_seed_js(script: str, expression: str) -> object:
    assert NODE, "Step 2 seed tests require Node; no npm packages are used."
    harness = f"""
const window = globalThis;
window.addEventListener = () => {{}};
const document = {{
  addEventListener() {{}},
  body: {{ classList: {{ contains() {{ return true; }} }} }},
  querySelectorAll() {{ return []; }},
  querySelector() {{ return null; }},
  getElementById() {{ return null; }},
}};
const history = {{ replaceState() {{}} }};
const location = {{ href: '', hash: '' }};
const CSS = {{ escape(value) {{ return String(value); }} }};
function confirm() {{ return false; }}
{script}
Promise.resolve(({expression}))
  .then(result => process.stdout.write(JSON.stringify(result)))
  .catch(error => {{
    process.stderr.write(String(error?.stack || error));
    process.exitCode = 1;
  }});
"""
    completed = subprocess.run(
        [NODE, "-"],
        input=harness,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _file_inspection_fields(names: list[str]) -> list[dict]:
    lines = ["format: fixed-width", "record_types:", "  data:", "    fields:"]
    start = 1
    for name in names:
        lines.extend(
            [
                f"      - name: {name}",
                f"        position: {start}",
                "        length: 12",
            ]
        )
        start += 12
    response = client.post(
        "/upstream/edge-contract/file-inspect",
        json={
            "direction": "upstream",
            "type": "file-fixed-width",
            "spec_content": "\n".join(lines),
            "sample_content": "",
        },
    )
    assert response.status_code == 200
    return response.json()["layout"]["fields"]


def test_real_inspector_fields_drive_exact_normalized_and_blank_patch_rows(monkeypatch):
    _seed_session()
    fields = _file_inspection_fields(["accountId", "status_code", "unmapped_field"])
    sources = [
        {
            "name": "accountId",
            "proposed_value": {"source": "accountId", "target": "Record.accountId"},
        },
        {
            "name": "statusCode",
            "proposed_value": {"source": "statusCode", "target": "Record.statusCode"},
        },
    ]
    script = _seed_script(monkeypatch)

    rows = _run_seed_js(
        script,
        "window.EdgeForgeSeedPatch.buildRows("
        f"{json.dumps(sources)}, {json.dumps(fields)}, []"
        ")",
    )
    by_target = {row["target_field"]: row for row in rows}

    assert by_target["accountId"]["basis"] == "exact match"
    assert by_target["accountId"]["checked"] is True
    assert by_target["status_code"]["basis"] == "snake↔camel"
    assert by_target["status_code"]["checked"] is True
    assert by_target["unmapped_field"]["state"] == "no-match"
    assert by_target["unmapped_field"]["basis"] == "left blank"
    assert by_target["unmapped_field"]["checked"] is False


def test_collision_is_never_prechecked_or_applied_and_existing_mapping_stays_intact(monkeypatch):
    _seed_session()
    fields = _file_inspection_fields(["ACCOUNT_ID"])
    sources = [
        {
            "name": "accountId",
            "proposed_value": {"source": "accountId", "target": "Record.accountId"},
        },
        {
            "name": "account_id",
            "proposed_value": {"source": "account_id", "target": "Record.account_id"},
        },
    ]
    current = [
        {
            "target_field": "ACCOUNT_ID",
            "proposed_value": {"source": "manualId", "target": "Record.manualId"},
        }
    ]
    script = _seed_script(monkeypatch)
    expression = f"""(() => {{
      const rows = window.EdgeForgeSeedPatch.buildRows(
        {json.dumps(sources)}, {json.dumps(fields)}, {json.dumps(current)}
      );
      rows[0].checked = true;
      const result = window.EdgeForgeSeedPatch.applyRows(
        rows, {json.dumps(current)}, [rows[0].key]
      );
      return {{row: rows[0], result}};
    }})()"""

    result = _run_seed_js(script, expression)

    assert result["row"]["state"] == "collision"
    assert result["row"]["basis"] == "multiple matches - review"
    assert result["row"]["checked"] is True  # forced by the test after construction
    assert result["row"]["writable"] is False
    assert result["result"] == {"values": current, "applied": []}


def test_target_only_mapping_slot_is_reused_for_a_matching_seed(monkeypatch):
    _seed_session()
    fields = _file_inspection_fields(["status"])
    sources = [
        {
            "name": "status",
            "proposed_value": {"source": "status", "target": "Record.status"},
        }
    ]
    # A pre-existing target-only row is an empty source slot, not a reason to
    # append a duplicate mapping row when the inspected artifact has status.
    current = [
        {
            "target_field": "status",
            "proposed_value": {"source": "", "target": "Record.status"},
        }
    ]
    script = _seed_script(monkeypatch)
    expression = f"""(() => {{
      const rows = window.EdgeForgeSeedPatch.buildRows(
        {json.dumps(sources)}, {json.dumps(fields)}, {json.dumps(current)}
      );
      const result = window.EdgeForgeSeedPatch.applyRows(
        rows, {json.dumps(current)}, [rows[0].key]
      );
      return {{row: rows[0], result}};
    }})()"""

    result = _run_seed_js(script, expression)

    assert result["row"]["state"] == "matched"
    assert result["row"]["checked"] is True
    assert result["row"]["matching_slots"] == ["target"]
    assert result["result"] == {
        "values": [
            {
                "target_field": "status",
                "proposed_value": {"source": "status", "target": "Record.status"},
            }
        ],
        "applied": [
            {
                "key": "mapping:status:0",
                "target_field": "status",
                "proposed_value": {"source": "status", "target": "Record.status"},
                "basis": "exact match",
                "changed_slots": ["source"],
            }
        ],
    }

    template = TEMPLATE.read_text(encoding="utf-8")
    seed_start = template.index("function upstreamMappingSeedValues()")
    seed_end = template.index("function buildUpstreamMappingSeedRows", seed_start)
    seed_source = template[seed_start:seed_end]
    assert "target_field: source || targetParts[targetParts.length - 1] || ''" in seed_source

    apply_start = template.index("function applyUpstreamMappingSeedPatch")
    apply_end = template.index("function renderUpstreamMappingSeedPatch", apply_start)
    apply_source = template[apply_start:apply_end]
    assert "candidate.querySelector('.edge-map-target')?.value?.trim() === proposed.target" in apply_source
    assert apply_source.index("candidate.querySelector('.edge-map-target')?.value?.trim() === proposed.target") < apply_source.index("addEdgeFieldMappingRow()")


def test_step2_projection_reports_normalized_basis_and_real_duplicate_collisions(monkeypatch):
    _seed_session()
    script = _seed_script(monkeypatch)
    expression = """(() => {
      const controls = {
        'edge-contract-entity-name': {value: 'Record'},
      };
      document.getElementById = id => controls[id] || null;
      document.querySelectorAll = () => [];
      const normalized = buildUpstreamMappingSeedRows(['accountId', 'status_code']);
      const collision = buildUpstreamMappingSeedRows(['account_id', 'ACCOUNT_ID']);
      controls['edge-contract-entity-name'].value = '';
      const blank = buildUpstreamMappingSeedRows(['accountId']);
      return {normalized, collision, blank};
    })()"""

    result = _run_seed_js(script, expression)

    assert [row["basis"] for row in result["normalized"]] == ["exact match", "snake↔camel"]
    assert all(row["checked"] is True for row in result["normalized"])
    assert all(row["state"] == "collision" for row in result["collision"])
    assert all(row["checked"] is False for row in result["collision"])
    assert result["blank"][0]["state"] == "no-match"
    assert result["blank"][0]["basis"] == "left blank"


def test_retired_flag_value_keeps_only_shared_seed_helpers(monkeypatch):
    _seed_session()

    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    default_on_html = client.get("/upstream?focus=record-fixed").text
    assert "function seedEdgeFieldMappings()" not in default_on_html
    assert "function seedEdgeFieldMappingsFromNames(names)" not in default_on_html
    assert "Replace existing mapping rows with rows seeded from layout fields?" not in default_on_html

    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    refreshed_html = client.get("/upstream?focus=record-fixed").text
    shared_source = STUDIO_JS.read_text(encoding="utf-8")
    assert "function seedEdgeFieldMappings()" not in refreshed_html
    assert "function seedEdgeFieldMappingsFromNames(names)" not in refreshed_html
    assert "function buildUpstreamMappingSeedRows(names)" in default_on_html
    assert "function buildUpstreamMappingSeedRows(names)" in refreshed_html
    assert "window.EdgeForgeSeedPatch.buildRows" in refreshed_html
    assert "renderDeterministicSeedPatch" in refreshed_html
    assert "function renderDeterministicSeedPatch" in shared_source
    assert "function markDerivedSeed" in shared_source
    assert "function escapeHtml(value)" in shared_source
    assert "DOMParser" not in refreshed_html


def test_seed_wiring_is_stale_safe_and_provenance_is_display_only(monkeypatch):
    _seed_session()
    script = _seed_script(monkeypatch)

    file_inspector = script[
        script.index("async function inspectUpstreamFileContract") : script.index(
            "function renderFileInspectionResult"
        )
    ]
    edge_inspector = script[
        script.index("async function inspectUpstreamEdgeContract") : script.index(
            "async function inspectUpstreamFileContract"
        )
    ]
    for source in (file_inspector, edge_inspector):
        assert source.index("const requestContextFingerprint") < source.index("await postJSON(")
        assert source.index("discardStaleUpstreamInspection") > source.index("await postJSON(")

    assert "if (control && !control.value.trim() && proposed[slot])" in script
    assert "markDerivedSeed(controls[slot], applied.basis)" in script
    assert "function clearUpstreamMappingDerivedSeeds()" in script
    payload_start = script.index("function upstreamEdgeContractPayload()")
    payload_end = script.index("async function saveEdgeContract()", payload_start)
    payload_source = script[payload_start:payload_end]
    assert "derived" not in payload_source.lower()
    assert "basis" not in payload_source.lower()
