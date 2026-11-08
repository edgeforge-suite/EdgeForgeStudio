"""PR-13 regression coverage for Step 5 deterministic seed patches.

The matcher and apply merger are intentionally DOM-free JavaScript. These
tests execute that public unit with Node against candidate shapes returned by
Studio's real inspectors and source fields returned by the real entity
inventory. DOM-only wiring remains covered by focused static invariants because
the repository deliberately has no browser/jsdom test toolchain.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    DownstreamInterface,
    FieldMapping,
    LayoutField,
)
from app.services.edge_contracts import _entity_field_inventory
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)
ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "app" / "templates" / "step5_downstream.html"
STUDIO_JS = ROOT / "app" / "static" / "js" / "studio.js"
STUDIO_CSS = ROOT / "app" / "static" / "css" / "studio.css"
NODE = shutil.which("node")


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _seed_session(*, source_fields: list[str] | None = None):
    session = get_session()
    session.app_name = "Deterministic Seed Fixture"
    session.bounded_context = "deterministic-seed-fixture"
    session.app_archetype = "crud"
    fields = source_fields or ["accountId", "displayName", "statusCode"]
    session.classified_entities = [
        ClassifiedEntity(
            name="Record",
            classification="entity",
            fields=[ClassifiedField(name=name, type="string") for name in fields],
        )
    ]
    session.downstream_interfaces = [
        DownstreamInterface(
            name="record-fixed",
            type="file-fixed-width",
            entity_name="Record",
            spec="downstream/record-layout.yaml",
            spec_content=(
                "format: fixed-width\n"
                "record_types:\n"
                "  data:\n"
                "    fields:\n"
                "      - name: accountId\n"
                "        position: 1\n"
                "        length: 36\n"
            ),
            layout_fields=[LayoutField(name="accountId", start=1, length=36)],
            field_mappings=[FieldMapping(source="Record.accountId", target="accountId")],
        ),
        DownstreamInterface(
            name="record-xml",
            type="xml-xsd",
            entity_name="Record",
            xsd_path="contracts/record.xsd",
            xsd_content="<xs:schema/>",
            root_element="RecordMessage",
            field_mappings=[FieldMapping(source="Record.accountId", target="accountId")],
        ),
        DownstreamInterface(
            name="record-soap",
            type="soap-wsdl",
            entity_name="Record",
            wsdl_path="contracts/record.wsdl",
            wsdl_content="<definitions/>",
            selected_operation_name="SyncRecord",
        ),
    ]
    save_session(session)
    return session


def _step5_script(monkeypatch, *, focus: str = "record-fixed") -> str:
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    response = client.get(f"/downstream?focus={focus}")
    assert response.status_code == 200
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", response.text, flags=re.DOTALL)
    page_script = next(script for script in scripts if "function getCardData(card)" in script)
    studio_source = STUDIO_JS.read_text(encoding="utf-8")
    shared_seed_source = studio_source[
        studio_source.index("/* ---- Deterministic seed patches ---- */") :
        studio_source.index("/* ---- Tabs ---- */")
    ]
    return f"{shared_seed_source}\n{page_script}"


def _run_seed_js(script: str, expression: str) -> object:
    assert NODE, "PR-13 seed-patch behavior tests require Node (no npm packages are used)."
    harness = f"""
const window = globalThis;
const document = {{
  addEventListener() {{}},
  body: {{ classList: {{ contains() {{ return true; }} }} }},
  querySelectorAll() {{ return []; }},
  querySelector() {{ return null; }},
  getElementById() {{ return null; }},
}};
const history = {{ replaceState() {{}} }};
const location = {{ href: '' }};
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


def _file_inspection_fields(field_names: list[str]) -> list[dict]:
    lines = ["format: fixed-width", "record_types:", "  data:", "    fields:"]
    start = 1
    for name in field_names:
        lines.extend(
            [
                f"      - name: {name}",
                f"        position: {start}",
                "        length: 12",
            ]
        )
        start += 12
    response = client.post(
        "/downstream/edge-contract/file-inspect",
        json={
            "direction": "downstream",
            "type": "file-fixed-width",
            "spec_content": "\n".join(lines),
            "sample_content": "",
        },
    )
    assert response.status_code == 200
    return response.json()["layout"]["fields"]


def _xml_inspection_fields() -> list[dict]:
    response = client.post(
        "/downstream/edge-contract/inspect",
        json={
            "direction": "downstream",
            "type": "xml-xsd",
            "content": """<?xml version="1.0"?>
            <xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
              <xs:element name="RecordMessage" type="RecordMessageType"/>
              <xs:complexType name="RecordMessageType">
                <xs:sequence>
                  <xs:element name="accountId" type="xs:string"/>
                  <xs:element name="status_code" type="xs:string"/>
                  <xs:element name="unmapped_field" type="xs:string"/>
                </xs:sequence>
              </xs:complexType>
            </xs:schema>""",
        },
    )
    assert response.status_code == 200
    return response.json()["candidates"]["fields"]


def test_flag_on_context_uses_sorted_real_entity_field_inventory(monkeypatch):
    session = _seed_session(source_fields=["statusCode", "accountId", "displayName"])

    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    html = client.get("/downstream?focus=record-fixed").text

    match = re.search(r"const uxrEntityFieldInventory = new Map\((.*?)\);", html)
    assert match
    rendered = dict(json.loads(match.group(1)))
    expected = {
        name: sorted(fields)
        for name, fields in _entity_field_inventory(session).items()
    }
    assert rendered == expected
    assert rendered["Record"] == ["accountId", "displayName", "statusCode"]


def test_exact_normalized_case_and_no_match_rows_use_real_inspection_shapes(monkeypatch):
    session = _seed_session(source_fields=["accountId", "displayName", "statusCode"])
    targets = [
        *_xml_inspection_fields(),
        *_file_inspection_fields(["DISPLAYNAME"]),
    ]
    sources = sorted(_entity_field_inventory(session)["Record"])
    script = _step5_script(monkeypatch)

    rows = _run_seed_js(
        script,
        (
            "window.EdgeForgeSeedPatch.buildRows("
            f"{json.dumps(sources)}, {json.dumps(targets)}, [])"
        ),
    )
    by_target = {row["target_field"]: row for row in rows}

    assert by_target["accountId"]["basis"] == "exact match"
    assert by_target["accountId"]["state"] == "matched"
    assert by_target["accountId"]["checked"] is True
    assert by_target["status_code"]["proposed_value"] == "statusCode"
    assert by_target["status_code"]["basis"] == "snake↔camel"
    assert by_target["status_code"]["checked"] is True
    assert by_target["DISPLAYNAME"]["proposed_value"] == "displayName"
    assert by_target["DISPLAYNAME"]["basis"] == "case match"
    assert by_target["DISPLAYNAME"]["checked"] is True
    assert by_target["unmapped_field"]["proposed_value"] is None
    assert by_target["unmapped_field"]["basis"] == "left blank"
    assert by_target["unmapped_field"]["state"] == "no-match"
    assert by_target["unmapped_field"]["checked"] is False


def test_collision_is_never_prechecked_or_applied_even_when_forced(monkeypatch):
    session = _seed_session(source_fields=["accountId", "account_id"])
    targets = _file_inspection_fields(["ACCOUNT_ID"])
    sources = sorted(_entity_field_inventory(session)["Record"])
    script = _step5_script(monkeypatch)
    expression = f"""(() => {{
      const rows = window.EdgeForgeSeedPatch.buildRows(
        {json.dumps(sources)}, {json.dumps(targets)}, []
      );
      const initialChecked = rows[0].checked;
      rows[0].checked = true;
      const applied = window.EdgeForgeSeedPatch.applyRows(rows, [], [rows[0].key]);
      return {{ row: rows[0], initialChecked, applied }};
    }})()"""

    result = _run_seed_js(script, expression)

    assert result["row"]["state"] == "collision"
    assert result["row"]["basis"] == "multiple matches - review"
    assert result["initialChecked"] is False
    assert result["row"]["writable"] is False
    assert result["applied"] == {"values": [], "applied": []}
    assert "checkbox.checked = Boolean(row.checked);" in script
    assert "basis.textContent = row.state === 'matched' && !row.writable" in script


def test_exact_raw_match_wins_before_normalized_target_remainder(monkeypatch):
    session = _seed_session(source_fields=["accountId"])
    targets = _file_inspection_fields(["accountId", "account_id"])
    sources = sorted(_entity_field_inventory(session)["Record"])
    script = _step5_script(monkeypatch)

    rows = _run_seed_js(
        script,
        (
            "window.EdgeForgeSeedPatch.buildRows("
            f"{json.dumps(sources)}, {json.dumps(targets)}, [])"
        ),
    )

    assert [row["target_field"] for row in rows] == ["accountId", "account_id"]
    assert rows[0]["state"] == "matched"
    assert rows[0]["basis"] == "exact match"
    assert rows[0]["checked"] is True
    assert rows[1]["state"] == "no-match"
    assert rows[1]["basis"] == "left blank"
    assert rows[1]["checked"] is False


def test_multiple_unmatched_normalized_inspector_targets_are_collisions(monkeypatch):
    session = _seed_session(source_fields=["accountId"])
    targets = _file_inspection_fields(["account_id", "ACCOUNT_ID"])
    sources = sorted(_entity_field_inventory(session)["Record"])
    script = _step5_script(monkeypatch)

    rows = _run_seed_js(
        script,
        (
            "window.EdgeForgeSeedPatch.buildRows("
            f"{json.dumps(sources)}, {json.dumps(targets)}, [])"
        ),
    )

    assert [row["target_field"] for row in rows] == ["account_id", "ACCOUNT_ID"]
    assert all(row["state"] == "collision" for row in rows)
    assert all(row["checked"] is False for row in rows)
    assert all(row["basis"] == "multiple matches - review" for row in rows)


def test_rendered_patch_context_rejects_entity_and_artifact_changes(monkeypatch):
    _seed_session()
    script = _step5_script(monkeypatch)
    expression = """(() => {
      const controls = {
        '.iface-type': {value: 'file-fixed-width'},
        '.iface-entity': {value: 'Record'},
        '.iface-spec-content': {value: 'format: fixed-width\\nrecord_types:\\n  data:\\n    fields: []'},
        '.iface-sample': {value: 'sample-a'},
        '.iface-xsd-content': {value: ''},
        '.iface-csv-delimiter': {value: ','},
        '.iface-csv-has-header': {value: 'true'},
      };
      const card = {
        querySelector(selector) { return controls[selector] || null; },
        querySelectorAll() { return []; },
      };
      const captured = downstreamSeedPatchContextFingerprint(card);
      const initiallyCurrent = downstreamSeedPatchContextFingerprint(card) === captured;
      controls['.iface-entity'].value = 'Customer';
      const afterEntityEdit = downstreamSeedPatchContextFingerprint(card) === captured;
      controls['.iface-entity'].value = 'Record';
      controls['.iface-spec-content'].value = 'format: fixed-width\\nrecord_types:\\n  data:\\n    fields:\\n      - name: account_id\\n        position: 1\\n        length: 12';
      const afterArtifactEdit = downstreamSeedPatchContextFingerprint(card) === captured;
      return {initiallyCurrent, afterEntityEdit, afterArtifactEdit};
    })()"""

    result = _run_seed_js(script, expression)

    assert result == {
        "initiallyCurrent": True,
        "afterEntityEdit": False,
        "afterArtifactEdit": False,
    }
    assert "if (isCurrent && !isCurrent())" in script
    assert "These suggestions are stale. Inspect the current entity and artifact again" in script
    assert "onApply(checkedKeys)" in script
    assert script.index("if (isCurrent && !isCurrent())") < script.index(
        "const result = onApply(checkedKeys)"
    )


def test_inspector_response_is_discarded_when_context_changes_in_flight(monkeypatch):
    _seed_session()
    script = _step5_script(monkeypatch)
    expression = """(async () => {
      const controls = {
        '.iface-type': {value: 'file-fixed-width'},
        '.iface-entity': {value: 'Record'},
        '.iface-spec-content': {value: 'format: fixed-width\\nrecord_types:\\n  data:\\n    fields: []'},
        '.iface-sample': {value: 'sample-a'},
        '.iface-xsd-content': {value: ''},
        '.iface-wsdl-content': {value: ''},
        '.iface-csv-delimiter': {value: ','},
        '.iface-csv-has-header': {value: 'true'},
      };
      const card = {
        querySelector(selector) { return controls[selector] || null; },
        querySelectorAll() { return []; },
      };
      const button = {closest() { return card; }};
      const statuses = [];
      let resolveRequest;
      let rendered = false;
      postJSON = () => new Promise(resolve => { resolveRequest = resolve; });
      showStatus = (_id, message, kind) => statuses.push({message, kind});
      renderDownstreamFileInspectionResult = () => { rendered = true; };

      const pending = inspectDownstreamFileContract(button);
      controls['.iface-spec-content'].value = 'format: fixed-width\\nrecord_types:\\n  data:\\n    fields:\\n      - name: account_id\\n        position: 1\\n        length: 12';
      resolveRequest({ok: true, layout: {type: 'file-fixed-width', fields: []}});
      await pending;
      return {rendered, statuses};
    })()"""

    result = _run_seed_js(script, expression)

    assert result["rendered"] is False
    assert result["statuses"] == [
        {
            "message": (
                "The entity or artifact changed while inspection was running. "
                "Inspect again to refresh suggestions."
            ),
            "kind": "warn",
        }
    ]

    file_inspector = script[
        script.index("async function inspectDownstreamFileContract") : script.index(
            "function renderDownstreamFileInspectionResult"
        )
    ]
    edge_inspector = script[
        script.index("async function inspectDownstreamEdgeContract") : script.index(
            "async function inspectDownstreamFileContract"
        )
    ]
    for source, render_call in (
        (file_inspector, "renderDownstreamFileInspectionResult(card, result)"),
        (edge_inspector, "renderDownstreamInspectionResult(card, result)"),
    ):
        assert source.index("const requestContextFingerprint") < source.index("await postJSON(")
        assert source.index("discardStaleDownstreamInspection") < source.index(render_call)


def test_apply_never_overwrites_a_non_empty_mapping_value(monkeypatch):
    session = _seed_session(source_fields=["accountId"])
    targets = _file_inspection_fields(["accountId"])
    sources = [
        {"name": name, "proposed_value": f"Record.{name}"}
        for name in sorted(_entity_field_inventory(session)["Record"])
    ]
    script = _step5_script(monkeypatch)
    current = [{"target_field": "accountId", "proposed_value": "Record.manualId"}]
    expression = f"""(() => {{
      const rows = window.EdgeForgeSeedPatch.buildRows(
        {json.dumps(sources)}, {json.dumps(targets)}, {json.dumps(current)}
      );
      const result = window.EdgeForgeSeedPatch.applyRows(
        rows, {json.dumps(current)}, [rows[0].key]
      );
      return {{ row: rows[0], result }};
    }})()"""

    result = _run_seed_js(script, expression)

    assert result["row"]["checked"] is False
    assert result["row"]["writable"] is False
    assert result["result"]["values"] == current
    assert result["result"]["applied"] == []


def test_layout_apply_fills_only_empty_cells_and_preserves_existing_cells(monkeypatch):
    _seed_session()
    script = _step5_script(monkeypatch)
    expression = """window.EdgeForgeSeedPatch.applyRows(
      [{
        key: 'layout:accountId:0',
        target_field: 'accountId',
        proposed_value: {name: 'accountId', start: 1, length: 36},
        basis: 'inspected layout',
        state: 'matched',
      }],
      [{
        target_field: 'accountId',
        proposed_value: {name: 'accountId', start: 99, length: ''},
      }],
      ['layout:accountId:0'],
    )"""

    result = _run_seed_js(script, expression)

    assert result["values"] == [
        {
            "target_field": "accountId",
            "proposed_value": {"name": "accountId", "start": 99, "length": 36},
        }
    ]
    assert len(result["applied"]) == 1
    assert result["applied"][0]["changed_slots"] == ["length"]


def test_reopened_values_recompute_field_level_derived_slots(monkeypatch):
    _seed_session()
    script = _step5_script(monkeypatch)
    expression = """({
      mapping: window.EdgeForgeSeedPatch.matchingSlots(
        'Record.accountId', 'Record.accountId'
      ),
      layout: window.EdgeForgeSeedPatch.matchingSlots(
        {name: 'accountId', start: 99, length: 36},
        {name: 'accountId', start: 1, length: 36}
      ),
    })"""

    result = _run_seed_js(script, expression)

    assert result == {"mapping": ["value"], "layout": ["name", "length"]}
    assert "function recomputeDownstreamMappingDerivedSeeds(card, rows)" in script
    assert "function recomputeDownstreamLayoutDerivedSeeds(card, rows)" in script
    assert "(seed.matching_slots || []).forEach(slot =>" in script


def test_patch_and_manual_values_produce_byte_identical_save_payloads(monkeypatch):
    session = _seed_session(source_fields=["accountId"])
    targets = _file_inspection_fields(["accountId"])
    sources = [
        {"name": name, "proposed_value": f"Record.{name}"}
        for name in sorted(_entity_field_inventory(session)["Record"])
    ]
    script = _step5_script(monkeypatch, focus="record-xml")
    expression = f"""(() => {{
      const rows = window.EdgeForgeSeedPatch.buildRows(
        {json.dumps(sources)}, {json.dumps(targets)}, []
      );
      const patchedValues = window.EdgeForgeSeedPatch.applyRows(
        rows, [], [rows[0].key]
      ).values;
      function makeCard(source, target) {{
        const controls = {{
          '.iface-name': {{value: 'record-xml'}},
          '.iface-type': {{value: 'xml-xsd'}},
          '.iface-entity': {{value: 'Record'}},
          '.iface-xsd-path': {{value: 'contracts/record.xsd'}},
          '.iface-xsd-content': {{value: '<xs:schema/>'}},
          '.iface-root-element': {{value: 'RecordMessage'}},
          '.iface-soap-mode': {{value: 'adapter_only'}},
        }};
        const mappingRow = {{
          querySelector(selector) {{
            if (selector === '.map-source') return {{value: source}};
            if (selector === '.map-target') return {{value: target}};
            return null;
          }},
        }};
        return {{
          querySelector(selector) {{ return controls[selector] || {{value: '', checked: false}}; }},
          querySelectorAll(selector) {{ return selector === '.mapping-row' ? [mappingRow] : []; }},
        }};
      }}
      const patched = getCardData(makeCard(
        patchedValues[0].proposed_value,
        patchedValues[0].target_field,
      ));
      const manual = getCardData(makeCard('Record.accountId', 'accountId'));
      return {{
        patched,
        manual,
        patchedBytes: JSON.stringify(patched),
        manualBytes: JSON.stringify(manual),
      }};
    }})()"""

    result = _run_seed_js(script, expression)

    assert result["patched"] == result["manual"]
    assert result["patchedBytes"] == result["manualBytes"]
    assert "derived" not in result["patchedBytes"].lower()
    assert "basis" not in result["patchedBytes"].lower()


def test_retired_flag_value_exposes_only_deterministic_seed_mechanism(monkeypatch):
    _seed_session()

    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    default_on_html = client.get("/downstream?focus=record-fixed").text
    assert "function seedDownstreamFileMappings(button)" not in default_on_html
    assert "function populateFixedWidthLayoutRowsFromInspection(card, fields)" not in default_on_html
    assert "Replace existing mapping rows with rows seeded from layout fields?" not in default_on_html
    assert "edge-file-seed-action" not in default_on_html

    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    refreshed_html = client.get("/downstream?focus=record-fixed").text
    shared_source = STUDIO_JS.read_text(encoding="utf-8")
    assert "window.EdgeForgeSeedPatch" in shared_source
    assert "uxr-seedbox" in shared_source
    assert "window.EdgeForgeSeedPatch = window.EdgeForgeSeedPatch ||" not in refreshed_html
    assert "Deterministic mapping seeds" in refreshed_html
    assert "function seedDownstreamFileMappings(button)" not in refreshed_html
    assert "function populateFixedWidthLayoutRowsFromInspection(card, fields)" not in refreshed_html
    assert "function extractLayoutFieldNamesFromSpecContent(content)" not in refreshed_html
    assert "DOMParser" not in refreshed_html
    assert "Replace existing mapping rows with rows seeded from layout fields?" not in refreshed_html
    assert "edge-file-seed-action" not in refreshed_html
    assert "Deterministic mapping seeds" in default_on_html


def test_derived_chip_is_control_scoped_recomputed_and_absent_from_payload(monkeypatch):
    _seed_session()
    script = _step5_script(monkeypatch)

    assert "chip.dataset.uxrDerivedChip = 'true'" in script
    assert "chip.textContent = `DERIVED · ${basis}`" in script
    assert "wrapper.className = 'uxr-derived-control'" in script
    assert "control.parentNode.insertBefore(wrapper, control)" in script
    assert "wrapper.appendChild(chip)" in script
    assert "control.addEventListener('input', () => clearDerivedSeed(control))" in script
    assert "if (source && !source.value.trim()) source.value = applied.proposed_value;" in script
    assert "markDerivedSeed(source, applied.basis)" in script
    assert "markDerivedSeed(row?.querySelector(selectors[slot]), applied.basis)" in script
    assert "markDerivedSeed(row, applied.basis)" not in script
    get_card_source = script[script.index("function getCardData(card)") : script.index(
        "function refreshContractTypeSections(card)"
    )]
    assert "uxr-derived-chip" not in get_card_source
    assert "basis" not in get_card_source


def test_soap_path_has_no_patch_sheet_and_manual_mapping_builders_are_unchanged(monkeypatch):
    _seed_session()
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    legacy_html = client.get("/downstream?focus=record-soap").text
    legacy_script = next(
        script
        for script in re.findall(r"<script[^>]*>(.*?)</script>", legacy_html, flags=re.DOTALL)
        if "function renderDownstreamSoapInspectionControls" in script
    )
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    html = client.get("/downstream?focus=record-soap").text
    markup_without_scripts = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    script = _step5_script(monkeypatch, focus="record-soap")
    soap_source = script[
        script.index("function renderDownstreamSoapInspectionControls") : script.index(
            "function buildCandidateSelect"
        )
    ]
    legacy_soap_source = legacy_script[
        legacy_script.index("function renderDownstreamSoapInspectionControls") : legacy_script.index(
            "function buildCandidateSelect"
        )
    ]

    assert "data-uxr-seed-patch" not in markup_without_scripts
    assert soap_source == legacy_soap_source
    assert "renderDownstreamMappingSeedPatch" not in soap_source
    assert "renderDownstreamLayoutSeedPatch" not in soap_source
    assert "buildCandidateSelect('downstream-inspect-service'" in soap_source
    assert "buildCandidateSelect('downstream-inspect-operation'" in soap_source
    assert "function addSoapRequestMappingRowEl" in script
    assert "function addSoapResponseMappingRowEl" in script


def _css_var(name: str) -> str:
    css = STUDIO_CSS.read_text(encoding="utf-8")
    match = re.search(rf"--{re.escape(name)}\s*:\s*(#[0-9a-fA-F]{{6}})", css)
    assert match, f"--{name} not found"
    return match.group(1)


def _relative_luminance(hex_color: str) -> float:
    channels = [int(hex_color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(first: str, second: str) -> float:
    lighter, darker = sorted(
        (_relative_luminance(first), _relative_luminance(second)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


def test_derived_chip_live_token_pairing_passes_wcag_aa():
    ratio = _contrast_ratio(_css_var("derived-ink"), _css_var("zone-derived"))

    assert ratio >= 4.5, f"DERIVED chip contrast is {ratio:.2f}:1, below WCAG AA"


def test_rendered_flag_on_script_passes_node_syntax_check(monkeypatch, tmp_path):
    _seed_session()
    script = _step5_script(monkeypatch)
    script_path = tmp_path / "step5-flag-on.js"
    script_path.write_text(script, encoding="utf-8")

    assert NODE, "Rendered Step 5 syntax check requires Node."
    completed = subprocess.run(
        [NODE, "--check", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr


def test_seed_patch_is_pre_save_only_and_does_not_change_save_contract():
    route_source = (ROOT / "app" / "routes" / "downstream.py").read_text(encoding="utf-8")
    template_source = TEMPLATE.read_text(encoding="utf-8")

    assert '"entity_field_inventory": entity_field_inventory' in route_source
    assert "@router.post(\"/interface/save-one\"" in route_source
    assert "/downstream/interface/save-one" in template_source
    assert "window.EdgeForgeSeedPatch.applyRows" in template_source
    assert "postJSON('/downstream/edge-contract/file-inspect'" in template_source
    assert "postJSON('/downstream/edge-contract/inspect'" in template_source
