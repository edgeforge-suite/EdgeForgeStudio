"""PR-20 coverage for the Step 6 allowed-values paste bulk action.

Client-side only: paste a block of values into an `allowed-values` rule row,
preview a union with the current values, apply, and undo-last. Apply writes
the comma-joined union into the same `.rule-values` input the unchanged save
path (getCardRules/snapshotRuleRow -> POST /rules/save-one) already reads, so
no route, payload, model, or manifest change is involved.

Split/dedup is the one piece of non-trivial logic (parseAllowedValuesPaste)
and the union merge (unionAllowedValuesPaste) is also DOM-free -- both live
in studio.js and are exercised directly with Node here, mirroring PR-13's
test_step5_seed_patch.py precedent. This repo has no jsdom/Playwright, so the
DOM-wiring (toggle/apply/undo/delegation/dispatch) is verified by static
source assertions instead, mirroring test_step5_tab_badge_focus.py.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models.project import ClassifiedEntity, ClassifiedField, EntityRules, RuleEntry
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)
ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "app" / "templates" / "step6_rules.html"
STUDIO_JS = ROOT / "app" / "static" / "js" / "studio.js"
NODE = shutil.which("node")


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _seed_allowed_values_session():
    session = reset_session()
    session.app_name = "Allowed Values Paste Fixture"
    session.bounded_context = "allowed-values-paste"
    session.target_profile = "springboot-legacy-compatible"
    session.app_archetype = "crud"
    session.project_revision = 7
    session.selected_entity_names = ["AccountResponse"]
    session.classified_entities = [
        ClassifiedEntity(
            name="AccountResponse",
            canonical_name="Account",
            classification="entity",
            fields=[
                ClassifiedField(name="accountId", type="string", is_id=True),
                ClassifiedField(
                    name="status",
                    type="string",
                    enum_values=["ACTIVE", "REVIEW"],
                ),
            ],
        ),
    ]
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            file_path="rules/account-business-rules.yaml",
            rules=[
                RuleEntry(field="status", type="allowed-values", values=["ACTIVE", "REVIEW"]),
            ],
        ),
    ]
    session.auto_rule_merge_completed_entities = ["Account"]
    session.capabilities.knowledge_assist_enabled = False
    session.ks_active = False
    save_session(session)
    return session


# ---------------------------------------------------------------------------
# Pure, DOM-free logic: exercised directly with Node (no fake DOM required --
# neither function touches `document`/`window` except the final export line).
# ---------------------------------------------------------------------------


def _allowed_values_paste_source() -> str:
    studio_source = STUDIO_JS.read_text(encoding="utf-8")
    return studio_source[
        studio_source.index("/* ---- Allowed-values paste (PR-20) ---- */") : studio_source.index(
            "/* ---- Tabs ---- */"
        )
    ]


def _run_pure_js(script: str, expression: str) -> object:
    assert NODE, "PR-20 allowed-values paste logic tests require Node (no npm packages are used)."
    harness = f"""
const window = globalThis;
{script}
process.stdout.write(JSON.stringify({expression}));
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


def test_parse_allowed_values_paste_splits_trims_dedupes_case_sensitive():
    script = _allowed_values_paste_source()

    result = _run_pure_js(
        script,
        "parseAllowedValuesPaste(' CHQ ,SAV;\\nCUR\\tCHQ\\n\\n,, chq ,SAV')",
    )

    # comma + semicolon + tab + newline all split; each candidate trimmed;
    # empties from collapsed/adjacent separators dropped; dedup keeps the
    # FIRST occurrence only -- "chq" survives because case is significant.
    assert result == ["CHQ", "SAV", "CUR", "chq"]


def test_parse_allowed_values_paste_empty_and_nullish_input_returns_empty_list():
    script = _allowed_values_paste_source()

    assert _run_pure_js(script, "parseAllowedValuesPaste('')") == []
    assert _run_pure_js(script, "parseAllowedValuesPaste('   ,;\\t\\n  ')") == []
    assert _run_pure_js(script, "parseAllowedValuesPaste(null)") == []
    assert _run_pure_js(script, "parseAllowedValuesPaste(undefined)") == []


def test_union_allowed_values_paste_never_drops_existing_and_orders_new_after_current():
    script = _allowed_values_paste_source()

    result = _run_pure_js(
        script,
        "unionAllowedValuesPaste(['ACTIVE', 'REVIEW'], ['REVIEW', 'FROZEN', 'ACTIVE', 'CLOSED'])",
    )

    assert result == {
        "union": ["ACTIVE", "REVIEW", "FROZEN", "CLOSED"],
        "added": ["FROZEN", "CLOSED"],
        "alreadyPresent": 2,
    }


def test_union_allowed_values_paste_with_nothing_pasted_is_a_pure_passthrough():
    script = _allowed_values_paste_source()

    result = _run_pure_js(script, "unionAllowedValuesPaste(['A', 'B'], [])")

    assert result == {"union": ["A", "B"], "added": [], "alreadyPresent": 0}


def test_union_allowed_values_paste_guards_non_array_inputs():
    script = _allowed_values_paste_source()

    result = _run_pure_js(script, "unionAllowedValuesPaste(null, undefined)")

    assert result == {"union": [], "added": [], "alreadyPresent": 0}


def test_parse_then_union_simulates_a_realistic_paste_end_to_end():
    script = _allowed_values_paste_source()
    expression = (
        "unionAllowedValuesPaste(['ACTIVE', 'REVIEW'], "
        "parseAllowedValuesPaste('REVIEW, FROZEN\\nCLOSED;REVIEW\\tACTIVE'))"
    )

    result = _run_pure_js(script, expression)

    assert result == {
        "union": ["ACTIVE", "REVIEW", "FROZEN", "CLOSED"],
        "added": ["FROZEN", "CLOSED"],
        "alreadyPresent": 2,
    }


def test_allowed_values_paste_functions_are_unconditionally_in_the_shared_static_file():
    """studio.js is served via StaticFiles, never Jinja-templated -- unlike
    the inline per-page script it cannot be flag-gated, and (like
    window.EdgeForgeSeedPatch before it) isn't: only inert, pure functions
    live here. The call sites that invoke them are what's flag-gated (see
    the template tests below)."""
    shared_source = STUDIO_JS.read_text(encoding="utf-8")

    assert "function parseAllowedValuesPaste(text)" in shared_source
    assert "window.parseAllowedValuesPaste = parseAllowedValuesPaste;" in shared_source
    assert "function unionAllowedValuesPaste(currentValues, pastedValues)" in shared_source
    assert "window.unionAllowedValuesPaste = unionAllowedValuesPaste;" in shared_source


# ---------------------------------------------------------------------------
# Affordance presence: flag-on renders it, flag-off is untouched.
# ---------------------------------------------------------------------------


def test_paste_affordance_renders_for_retired_flag_values(monkeypatch):
    _seed_allowed_values_session()

    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    flag_on = client.get("/rules?focus=Account")
    assert flag_on.status_code == 200
    for marker in (
        'data-uxr-av-paste-toggle',
        'data-uxr-av-undo',
        'data-uxr-av-panel',
        'data-uxr-av-textarea',
        'data-uxr-av-summary',
        'data-uxr-av-preview',
        'data-uxr-av-apply',
        'data-uxr-av-cancel',
        'uxr-seedbox uxr-zone-derived hidden',
    ):
        assert marker in flag_on.text, f"expected {marker!r} in flag-on render"

    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    flag_off = client.get("/rules?focus=Account")
    assert flag_off.status_code == 200
    for marker in (
        'data-uxr-av-paste-toggle',
        'data-uxr-av-undo',
        'data-uxr-av-panel',
        'data-uxr-av-textarea',
        'data-uxr-av-summary',
        'data-uxr-av-preview',
        'data-uxr-av-apply',
        'data-uxr-av-cancel',
        'uxr-av-paste',
        'uxrRenderAllowedValuesPaste',
        'uxrApplyAllowedValuesPaste',
        'uxrUndoAllowedValuesPaste',
        'uxrAllowedValuesPasteRefs',
    ):
        assert marker in flag_off.text, f"expected {marker!r} in default-on render"


def test_updateextras_always_installs_allowed_values_paste_affordance():
    template = TEMPLATE.read_text(encoding="utf-8")

    assert (
        "  if (type === 'allowed-values') {\n"
        "    extrasDiv.innerHTML = `<input type=\"text\" placeholder=\"CHQ, SAV, CUR\" "
        "class=\"rule-values\" title=\"Comma-separated values\">`;\n"
        "    uxrRenderAllowedValuesPaste(extrasDiv);\n"
        "  } else if (['default', 'max-length', 'min-length', 'pattern'].includes(type)) {"
    ) in template

    assert "ux_refresh" not in template


def test_paste_call_site_is_scoped_to_the_allowed_values_branch_only():
    """cross-entity-field-in also renders a `.rule-values` input (same CSS
    class, same comma-separated contract) but the packet scopes PR-20's
    paste affordance to plain allowed-values rows only -- confirm the call
    site appears exactly once, and not inside the cross-entity-field-in
    branch."""
    template = TEMPLATE.read_text(encoding="utf-8")
    extras_start = template.index("function updateExtras(selectEl, data = null) {")
    extras_end = template.index("\nfunction getCardRules(card)")
    extras_body = template[extras_start:extras_end]

    assert extras_body.count("uxrRenderAllowedValuesPaste(extrasDiv)") == 1

    allowed_values_branch = extras_body[
        extras_body.index("if (type === 'allowed-values') {") : extras_body.index(
            "} else if (['default', 'max-length', 'min-length', 'pattern']"
        )
    ]
    assert "uxrRenderAllowedValuesPaste(extrasDiv)" in allowed_values_branch

    cross_entity_field_in_branch = extras_body[
        extras_body.index("} else if (type === 'cross-entity-field-in') {") : extras_body.index(
            "} else {\n    // iso-4217, not-null"
        )
    ]
    assert "uxrRenderAllowedValuesPaste" not in cross_entity_field_in_branch
    assert "class=\"rule-values\"" in cross_entity_field_in_branch


# ---------------------------------------------------------------------------
# DOM-wiring: static JS-source checks (no jsdom in this repo).
# ---------------------------------------------------------------------------


def _function_body(template: str, signature: str) -> str:
    start = template.index(signature)
    end = template.index("\n}\n", start)
    return template[start:end]


def test_apply_writes_the_union_dispatches_input_and_stashes_the_undo_value():
    template = TEMPLATE.read_text(encoding="utf-8")
    body = _function_body(template, "function uxrApplyAllowedValuesPaste(refs)")

    assert "uxrAllowedValuesPasteUnion(refs)" in body
    assert "if (!added.length) return;" in body
    assert "const previous = refs.valuesInput.value;" in body
    assert "uxrSetRuleValuesAndNotify(refs.valuesInput, union.join(', '));" in body
    assert "refs.row.dataset.uxrAvUndoValue = previous;" in body
    assert "refs.undoBtn.classList.remove('hidden');" in body

    notify_body = _function_body(template, "function uxrSetRuleValuesAndNotify(input, value)")
    assert "input.dispatchEvent(new Event('input', { bubbles: true }));" in notify_body


def test_undo_restores_the_stashed_value_dispatches_input_and_clears_state():
    template = TEMPLATE.read_text(encoding="utf-8")
    body = _function_body(template, "function uxrUndoAllowedValuesPaste(refs)")

    assert "if (refs.row.dataset.uxrAvUndoValue === undefined) return;" in body
    assert (
        "uxrSetRuleValuesAndNotify(refs.valuesInput, refs.row.dataset.uxrAvUndoValue);" in body
    )
    assert "delete refs.row.dataset.uxrAvUndoValue;" in body
    assert "refs.undoBtn.classList.add('hidden');" in body


def test_hand_edit_of_rule_values_retires_any_pending_undo():
    template = TEMPLATE.read_text(encoding="utf-8")
    input_wiring_start = template.index("editor.addEventListener('input', event => {")
    input_wiring_end = template.index("\n  });\n", input_wiring_start)
    body = template[input_wiring_start:input_wiring_end]

    assert "event.target.closest('.rule-values')" in body
    assert "!valuesInput.dataset.uxrAvSynthetic" in body
    assert "delete row.dataset.uxrAvUndoValue;" in body
    assert "row.querySelector('[data-uxr-av-undo]')?.classList.add('hidden');" in body


def test_hand_edit_while_paste_panel_open_refreshes_the_stale_preview():
    """The preview is a union against the *current* `.rule-values`, and Apply
    recomputes that union live at click time. So a hand edit to the values
    input while the panel is open must re-render the preview -- otherwise it
    keeps promising a merge (counts + chips + Apply-enabled state) that no
    longer matches what Apply would commit (PR-259 P2: preview said 3, Apply
    committed 4). The refresh sits inside the SAME `!uxrAvSynthetic` guard as
    the undo-retire, so Apply's/Undo's own synthetic write -- which fires an
    `input` event while the panel is still open -- never re-renders a panel it
    is about to tear down."""
    template = TEMPLATE.read_text(encoding="utf-8")
    input_wiring_start = template.index("editor.addEventListener('input', event => {")
    input_wiring_end = template.index("\n  });\n", input_wiring_start)
    body = template[input_wiring_start:input_wiring_end]

    # Refresh only when this row's panel is actually open, via the one shared
    # renderer that both the textarea-typed and hand-edit paths funnel through.
    assert "const pasteWrap = row?.querySelector('.uxr-av-paste');" in body
    assert "!refs.panel.classList.contains('hidden')" in body
    assert body.count("uxrRenderAllowedValuesPreview(refs)") == 2

    # The hand-edit refresh must be reached only through the synthetic guard,
    # so Apply/Undo's synthetic `input` dispatch cannot trigger it.
    guard = body.index("if (valuesInput && !valuesInput.dataset.uxrAvSynthetic) {")
    refresh = body.index("const pasteWrap = row?.querySelector('.uxr-av-paste');")
    assert refresh > guard


def test_preview_computes_a_union_and_marks_new_values_with_a_text_label():
    template = TEMPLATE.read_text(encoding="utf-8")
    body = _function_body(template, "function uxrRenderAllowedValuesPreview(refs)")

    assert "uxrAllowedValuesPasteUnion(refs)" in body
    assert "union.forEach(value => {" in body
    # Never colour-only: "new" is written into the chip's own text.
    assert "added.includes(value) ? `${value} · new` : value" in body


def test_paste_listeners_are_delegated_on_the_focus_editor_not_per_row():
    template = TEMPLATE.read_text(encoding="utf-8")

    # uxrRenderAllowedValuesPaste only builds markup -- it must never attach
    # a listener directly to a node it creates, since rows are rebuilt by
    # updateExtras/addRuleRowEl/uxrMoveRulesIntoFieldGroups (the replaced-
    # node trap PR-16/17 hit).
    render_body = _function_body(template, "function uxrRenderAllowedValuesPaste(extrasDiv)")
    assert "addEventListener" not in render_body

    refs_body = _function_body(template, "function uxrAllowedValuesPasteRefs(node)")
    assert "addEventListener" not in refs_body

    # Wired once, delegated on the stable `editor` ancestor inside
    # uxrInitFocusedRuleSet -- same ancestor data-uxr-add-field-rule and
    # data-uxr-add-prerequisite already delegate on.
    init_start = template.index("function uxrInitFocusedRuleSet() {")
    init_end = template.index("\nfunction uxrInitLegacyNotes()", init_start)
    init_body = template[init_start:init_end]
    assert init_body.count("editor.addEventListener('click'") == 1
    assert init_body.count("editor.addEventListener('input'") == 1
    assert "data-uxr-av-paste-toggle" in init_body
    assert "data-uxr-av-apply" in init_body
    assert "data-uxr-av-undo" in init_body
    assert "data-uxr-av-cancel" in init_body
    assert "data-uxr-av-textarea" in init_body


def test_paste_controls_are_real_focusable_buttons_with_labels():
    template = TEMPLATE.read_text(encoding="utf-8")
    render_body = _function_body(template, "function uxrRenderAllowedValuesPaste(extrasDiv)")

    assert '<button type="button" class="btn btn-secondary btn-sm" data-uxr-av-paste-toggle aria-expanded="false">Paste values</button>' in render_body
    assert '<button type="button" class="btn btn-secondary btn-sm hidden" data-uxr-av-undo>Undo paste</button>' in render_body
    assert '<button type="button" class="btn btn-primary btn-sm" data-uxr-av-apply disabled>Apply</button>' in render_body
    assert '<button type="button" class="btn btn-secondary btn-sm" data-uxr-av-cancel>Cancel</button>' in render_body
    assert '<textarea data-uxr-av-textarea rows="3" placeholder="e.g. CHQ, SAV, CUR" aria-label="Values to add"></textarea>' in render_body


def test_rendered_flag_on_step6_script_passes_node_syntax_check(monkeypatch, tmp_path):
    _seed_allowed_values_session()
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    response = client.get("/rules?focus=Account")
    assert response.status_code == 200
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", response.text, flags=re.DOTALL)
    page_script = next(script for script in scripts if "function uxrApplyAllowedValuesPaste" in script)
    script_path = tmp_path / "step6-flag-on.js"
    script_path.write_text(page_script, encoding="utf-8")

    assert NODE, "Rendered Step 6 syntax check requires Node."
    completed = subprocess.run(
        [NODE, "--check", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr


# ---------------------------------------------------------------------------
# Payload untouched: `.rule-values` remains the save source; /rules/save and
# /rules/save-one are not modified by this PR.
# ---------------------------------------------------------------------------


def test_rule_values_remains_the_single_save_source_for_both_save_paths():
    template = TEMPLATE.read_text(encoding="utf-8")

    # snapshotRuleRow (dirty-tracker snapshot) and getCardRules (both
    # /rules/save and /rules/save-one payload builder) read `.rule-values`
    # exactly as before -- PR-20 only ever writes into this same input via
    # uxrSetRuleValuesAndNotify, never adds a second value source.
    assert "const valuesRaw = row.querySelector('.rule-values')?.value || '';" in template
    assert template.count("const raw = row.querySelector('.rule-values')?.value || '';") == 2
    assert "postJSON('/rules/save-one'" in template
    assert "item: getCardRules(card)" in template
    assert "postJSON('/rules/save'" in template
    assert "entity_rules, legacy_notes, legacy_slug" in template


def test_paste_applied_values_save_through_the_unchanged_save_one_contract(monkeypatch):
    """Simulates what Apply produces: a plain comma-list `values[]` payload
    (union of the pre-existing ["ACTIVE", "REVIEW"] plus a pasted "FROZEN")
    written into `.rule-values` and posted exactly like any hand-typed rule.
    /rules/save-one is not touched by this PR -- this proves it doesn't need
    to be by exercising it with a paste-shaped payload."""
    _seed_allowed_values_session()
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")

    response = client.post(
        "/rules/save-one",
        json={
            "item": {
                "entity_name": "Account",
                "rules": [
                    {
                        "field": "status",
                        "type": "allowed-values",
                        "values": ["ACTIVE", "REVIEW", "FROZEN"],
                        "value": None,
                        "applied_by": "manual",
                    }
                ],
            },
            "original_name": "Account",
            "source_of_truth_version": "7",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert set(data) == {
        "ok",
        "item",
        "readiness",
        "board_metadata",
        "affected_readiness",
        "affected_board_metadata",
        "step_counts",
        "rail",
        "warnings",
        "source_of_truth_version",
    }
    saved_rule = data["item"]["rules"][0]
    assert saved_rule["type"] == "allowed-values"
    assert saved_rule["values"] == ["ACTIVE", "REVIEW", "FROZEN"]
    persisted = get_session().entity_rules[0].rules[0]
    assert persisted.values == ["ACTIVE", "REVIEW", "FROZEN"]
