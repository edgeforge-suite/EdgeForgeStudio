"""Flag-gated Step 4 focus-editor and client-contract coverage."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.project import ClassifiedEntity, ClassifiedField, DataHandoff, FieldMapping
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "app" / "templates" / "step4_handoffs.html"
STEP5_TEMPLATE = ROOT / "app" / "templates" / "step5_downstream.html"
STUDIO_JS = ROOT / "app" / "static" / "js" / "studio.js"
_CSRF_META_RE = re.compile(r'(<meta\s+name="edgeforge-csrf-token"\s+content=")[^"]*(")')
_CSRF_FIELD_RE = re.compile(
    r'(<input type="hidden" name="_edgeforge_csrf_token" value=")[^"]*(")'
)


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _normalize_csrf(html: str) -> str:
    html = _CSRF_META_RE.sub(r"\1<CSRF>\2", html)
    return _CSRF_FIELD_RE.sub(r"\1<CSRF>\2", html)


def _focus_session() -> None:
    session = get_session()
    session.app_archetype = "crud"
    session.project_revision = 11
    session.classified_entities = [
        ClassifiedEntity(
            name="Account",
            classification="entity",
            fields=[
                ClassifiedField(
                    name="accountId",
                    type="string",
                    required=True,
                    is_id=True,
                    max_length=36,
                ),
                ClassifiedField(name="status", type="string", required=False),
            ],
        )
    ]
    session.data_handoffs = [
        DataHandoff(
            name="account-stage",
            type="staging-table",
            spec="data-handoffs/account-stage.sql",
            ddl_content=(
                "CREATE TABLE account_stage (\n"
                "  accountId VARCHAR(36) NOT NULL,\n"
                "  status VARCHAR(255)\n"
                ");"
            ),
            table_name="account_stage",
            mapping_path="data-handoffs/account-stage-mapping.yaml",
            field_mappings=[
                FieldMapping(source="Account.accountId", target="accountId")
            ],
            entity_name="Account",
        )
    ]
    save_session(session)


def test_known_focus_renders_split_editor_and_entity_seed_context(monkeypatch):
    # PR-17 gives EDGEFORGE_STUDIO_UX_SPLIT its first real consumer -- pin it
    # off explicitly rather than letting this test's "single-panel" scenario
    # (by definition the split-off case) silently depend on whatever the
    # ambient process env happens to be. Before PR-17, ux_split had no
    # template consumer at all, so this test passed regardless of the
    # variable's value; a whole-suite run with EDGEFORGE_STUDIO_UX_SPLIT=true
    # in the outer shell env would otherwise now flip this into split mode
    # and fail the board-absence assertion below for the wrong reason.
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "false")
    _focus_session()

    response = client.get("/handoffs?focus=account-stage")
    html = response.text

    assert response.status_code == 200
    assert 'data-uxr-focus-editor="account-stage"' in html
    assert 'data-source-of-truth-version="11"' in html
    assert 'data-uxr-save-one' in html
    assert 'data-uxr-cancel-focus' in html
    assert 'data-uxr-conflict-review' in html
    assert 'data-uxr-ddl-comparison' in html
    assert "Saved DDL (before)" in html
    assert "Regenerated DDL (after)" in html
    comparison_start = html.index('data-uxr-ddl-comparison')
    comparison_end = html.index('</div>\n      </div>', comparison_start) + len('</div>\n      </div>')
    assert 'class="h-ddl-before"' in html[comparison_start:comparison_end]
    assert 'class="h-ddl-preview"' in html[comparison_start:comparison_end]
    assert 'data-uxr-handoff-seed' in html
    assert 'data-uxr-board="handoffs"' in html
    assert 'data-uxr-split="true"' in html
    assert "Save &amp; Continue" not in html
    assert "focus_item.blockers" not in html

    start = html.index("const handoffEntityFields = ") + len("const handoffEntityFields = ")
    inventory = json.loads(html[start : html.index(";", start)])
    assert inventory == {
        "Account": [
            {
                "name": "accountId",
                "type": "string",
                "required": True,
                "is_id": True,
                "format": None,
                "enum_values": [],
                "max_length": 36,
                "min_length": None,
                "pattern": None,
                "minimum": None,
                "maximum": None,
                "default_value": None,
            },
            {
                "name": "status",
                "type": "string",
                "required": False,
                "is_id": False,
                "format": None,
                "enum_values": [],
                "max_length": None,
                "min_length": None,
                "pattern": None,
                "minimum": None,
                "maximum": None,
                "default_value": None,
            },
        ]
    }


@pytest.mark.parametrize("focus", [None, "missing"])
def test_flag_on_unknown_or_absent_focus_renders_board(monkeypatch, focus):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _focus_session()
    url = "/handoffs" if focus is None else f"/handoffs?focus={focus}"

    html = client.get(url).text

    assert 'data-uxr-board="handoffs"' in html
    assert "data-uxr-focus-editor=" not in html
    # PR-17a item 6: Edit is now a real <a href> link (not a JS-navigated
    # <button data-uxr-focus-url>), mirroring Step 2's already-correct
    # precedent -- pin the full tag shape, not just one attribute.
    assert (
        '<a href="/handoffs?focus=account-stage" class="uxr-board-edit-btn" '
        'data-uxr-edit-target="account-stage">Edit</a>'
    ) in html


def test_retired_flag_off_value_still_honors_focus_query(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    _focus_session()

    focused = _normalize_csrf(client.get("/handoffs?focus=account-stage").text)

    assert 'data-uxr-focus-editor="account-stage"' in focused
    assert 'data-uxr-split="true"' in focused
    assert "uxrSaveFocusedHandoff" in focused
    assert 'onclick="saveAll()">Save &amp; Continue' not in focused


def test_async_ddl_save_contract_waits_aborts_and_restores_pending_state():
    template = TEMPLATE.read_text(encoding="utf-8")
    save_start = template.index("async function uxrSaveFocusedHandoff()")
    save_end = template.index("\n}\n\nfunction uxrInitFocusedEditor", save_start)
    save_body = template[save_start:save_end]

    assert "saveButton.disabled = true" in save_body
    assert "saveButton.setAttribute('aria-busy', 'true')" in save_body
    assert "requiresDdlGeneration ? 'Generating DDL…' : 'Saving…'" in save_body
    assert "await getCardData(card, { requireGeneratedDdl: true })" in save_body
    assert save_body.index("await getCardData") < save_body.index("postJSON('/handoffs/save-one'")
    assert "lockedControls.forEach(control => { control.disabled = true; })" in save_body
    assert "disabledBeforeSave[index]" in save_body
    assert "JSON.stringify(uxrHandoffCardSnapshot(card)) !== saveSnapshot" in save_body
    assert "The handoff changed while DDL was generating" in save_body
    assert "catch (error)" in save_body
    assert "saveButton.disabled = false" in save_body
    assert "saveButton.removeAttribute('aria-busy')" in save_body

    collector_start = template.index("async function getCardData(")
    collector_end = template.index("\n}\n\nfunction addMappingRowEl", collector_start)
    collector = template[collector_start:collector_end]
    assert "if (!ddlContent)" in collector
    assert "requireGeneratedDdl" in collector
    assert "Enter a table name before saving generated DDL." in collector
    assert "Add at least one staging column before saving generated DDL." in collector
    assert "if (preview) preview.textContent = data.ddl" in collector
    assert "await validateAndShowWarnings(data.ddl" in collector
    assert "throw new Error(data.error || 'DDL generation failed.')" in collector
    assert collector.index("if (!ddlContent)") < collector.index("postJSON('/api/validate/staging-ddl/generate'")


def test_seed_from_entity_contract_is_previewed_reusable_empty_only_and_transient():
    template = TEMPLATE.read_text(encoding="utf-8")

    assert "function buildHandoffEntitySeedPatch(" in template
    assert "function applyHandoffEntitySeedPatch(" in template
    assert "function uxrRenderHandoffSeedPreview(" in template
    assert "panel._edgeforgeSeedRows = rows" in template
    assert "rows.filter(row => selected.has(row.key))" in template
    assert "Append a purpose-built row instead of repurposing a partially-filled" in template
    assert "!row.querySelector('.map-source')?.value?.trim()" in template
    assert "!row.querySelector('.map-target')?.value?.trim()" in template
    assert "if (source && !source.value.trim())" in template
    assert "if (target && !target.value.trim())" in template
    assert "DERIVED · ${basis}" in template
    assert "function uxrRecomputeHandoffDerivedProvenance(card)" in template
    assert "function uxrHandoffSeedContextFingerprint(card)" in template
    assert "Seed suggestions were refreshed because the entity or handoff fields changed" in template
    assert "_edgeforgeDerivedSeedChip" in template
    assert "derived" not in template[template.index("return {", template.index("async function getCardData")):template.index("};", template.index("async function getCardData"))]


def test_focus_client_reconciles_saved_state_and_preserves_draft_on_conflict():
    template = TEMPLATE.read_text(encoding="utf-8")

    assert "uxrRenderEditorReadiness(data.readiness)" in template
    # PR-17a item 4: Step 4 reaches parity with Step 5 -- it now has its own
    # board-row updater, so the old single-panel comment is stale and gone.
    assert "Focus mode is intentionally single-panel" not in template, (
        "stale comment from the pre-parity single-panel design -- PR-17a "
        "adds uxrUpdateBoardRowFromSaved, mirroring Step 5"
    )
    assert "function uxrUpdateBoardRowFromSaved(readiness, previousName, boardMetadata)" in template
    assert "uxrUpdateAmbientAndRail(data)" in template
    assert "const stepFour = data.step_counts?.['4'] || data.step_counts?.[4]" in template
    assert "chip.className = 'badge uxr-rail-chip'" in template
    assert "if (!entry.count)" in template
    assert "chip?.remove()" in template
    assert "function uxrPresentSaveConflict(data)" in template
    assert "Your unsaved edits are preserved below" in template
    conflict_start = template.index("if (!data.ok)", template.index("uxrSaveFocusedHandoff"))
    conflict_end = template.index("uxrRenderSaveBlockers(data.blockers)", conflict_start)
    assert "uxrRestoreFocusedCardFromSaved()" not in template[conflict_start:conflict_end]
    # PR-17a item 6: Edit is now a real <a href> link -- native navigation
    # replaces the old programmatic window.location.href click handler,
    # which also makes it dirty-guardable via studio.js's guardNavigation
    # (it only matches a[href] / [data-dirty-navigation], never a bare
    # <button>, and a programmatic assignment can't be intercepted anyway).
    assert "window.location.href = button.dataset.uxrFocusUrl" not in template
    assert ".uxr-board-row:not(.hidden) [data-uxr-edit-target]" in template

    # The board-row updater must actually be wired into the save path, in the
    # right order relative to the ambient/rail updater, using a `previousName`
    # captured before the save response can rename uxrFocusOriginalName out
    # from under it (mirrors Step 5's uxrSaveFocusedInterface exactly).
    save_start = template.index("async function uxrSaveFocusedHandoff()")
    save_end = template.index("\n}\n\nfunction uxrInitFocusedEditor", save_start)
    save_body = template[save_start:save_end]
    assert "const previousName = uxrFocusOriginalName;" in save_body
    assert "uxrUpdateBoardRowFromSaved(data.readiness, previousName, data.board_metadata)" in save_body
    assert save_body.index("uxrUpdateBoardRowFromSaved(data.readiness, previousName, data.board_metadata)") < (
        save_body.index("uxrUpdateAmbientAndRail(data)")
    )


def test_dirty_cancel_and_blocker_focus_use_sync_snapshot_and_real_field_map():
    template = TEMPLATE.read_text(encoding="utf-8")
    studio_js = STUDIO_JS.read_text(encoding="utf-8")

    assert "function createDirtyTracker({ snapshot })" in studio_js
    assert "window.addEventListener('beforeunload'" in studio_js
    assert "showWarningStatusList" in studio_js
    assert "snapshot: () => uxrHandoffCardSnapshot(uxrFocusedCard())" in template
    assert "snapshot: () => getCardData(" not in template
    assert "uxrDirtyTracker?.isDirty()" in template
    assert "uxrRestoreFocusedCardFromSaved()" in template
    assert "data-dirty-navigation" in template
    assert "function uxrRenderSaveBlockers(blockers)" in template
    assert "uxrScrollToSectionInCard(card, first.section_ref || '')" in template
    assert "uxrFocusHandoffField(card, first.field_ref || '')" in template
    assert "ddl_content: '.h-ddl-manual'" in template
    assert "field_mappings: '.map-target, .h-mappings-container + button'" in template
    assert "name: '.h-name'" in template
    assert "const disclosure = field?.closest('details')" in template
    assert "if (disclosure) disclosure.open = true" in template
    assert 'id="ddl"' in template
    assert 'id="mappings"' in template


def test_warning_status_list_is_shared_without_a_step5_shadow_copy():
    studio_js = STUDIO_JS.read_text(encoding="utf-8")
    step5 = STEP5_TEMPLATE.read_text(encoding="utf-8")

    assert studio_js.count("function showWarningStatusList(") == 1
    assert "function showWarningStatusList(" not in step5
    assert "showWarningStatusList(" in step5


# ---------------------------------------------------------------------------
# PR-17a: Step 4/5 focus-editor parity, a11y + split-readiness hardening.
# ---------------------------------------------------------------------------


def test_save_status_role_and_aria_live_now_matches_step5_exactly():
    """Item 1: Step 4's #save-status previously had no SR role at all --
    save/error confirmations were silent to screen readers. Step 5 has had
    role="status" aria-live="polite" (flag-gated) since PR-12. Pins the
    byte-identical flag-gated source form in both templates so they cannot
    silently drift apart again."""
    step4 = TEMPLATE.read_text(encoding="utf-8")
    step5 = STEP5_TEMPLATE.read_text(encoding="utf-8")
    expected = '<div id="save-status" class="alert hidden" role="status" aria-live="polite"></div>'
    assert expected in step4
    assert expected in step5


def test_flag_on_save_status_carries_sr_role_at_runtime(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _focus_session()

    html = client.get("/handoffs?focus=account-stage").text
    assert '<div id="save-status" class="alert hidden" role="status" aria-live="polite"></div>' in html


def test_retired_flag_off_value_keeps_save_status_announcing(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    _focus_session()

    html = client.get("/handoffs").text
    assert '<div id="save-status" class="alert hidden" role="status" aria-live="polite"></div>' in html


def test_focus_editor_region_role_and_accessible_name_matches_step5_exactly():
    """Item 2 (§3.6 a11y contract): the data-uxr-focus-editor <section> had
    no role and no accessible name -- today the full-page swap carries SR
    context, but PR-17's split will not. Adds role="region" +
    aria-labelledby pointing at the focus-title element (given a stable id).
    Pins the byte-identical flag-gated source form in both templates."""
    step4 = TEMPLATE.read_text(encoding="utf-8")
    step5 = STEP5_TEMPLATE.read_text(encoding="utf-8")
    expected_section_tail = (
        'data-uxr-focus-editor="{{ focus_name }}" '
        'data-source-of-truth-version="{{ focus_source_of_truth_version }}" '
        'role="region" aria-labelledby="uxr-focus-title">'
    )
    expected_title = 'data-uxr-focus-title id="uxr-focus-title">'
    for template in (step4, step5):
        assert expected_section_tail in template
        assert expected_title in template


def test_flag_on_focus_editor_region_has_role_and_labelledby_at_runtime(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    _focus_session()

    html = client.get("/handoffs?focus=account-stage").text
    section_start = html.rindex("<section", 0, html.index('data-uxr-focus-editor="account-stage"'))
    section_tag_end = html.index(">", section_start)
    section_tag = html[section_start:section_tag_end]

    assert 'role="region"' in section_tag
    assert 'aria-labelledby="uxr-focus-title"' in section_tag
    assert html.count('id="uxr-focus-title"') == 1


def test_board_row_updater_mirrors_step5_and_uses_href_not_focus_url_dataset():
    """Item 4 (mirrors Step 5's uxrUpdateBoardRowFromSaved) + item 6 (the
    board Edit control is a real <a href>, so the updater must set .href
    directly rather than a now-nonexistent data-uxr-focus-url dataset
    property). Directly enforces the build packet's Known-hazard checklist
    #1 ("reconcile against shipped siblings; mirror Step 5's implementation
    rather than inventing a new one") via a structural byte comparison,
    modulo the one intentional per-step difference (route path + state-label
    helper name)."""
    step4 = TEMPLATE.read_text(encoding="utf-8")
    step5 = STEP5_TEMPLATE.read_text(encoding="utf-8")

    def _extract(template: str) -> str:
        start = template.index("function uxrUpdateBoardRowFromSaved")
        end = template.index("\n}", start)
        return template[start:end]

    step4_fn = _extract(step4)
    step5_fn = _extract(step5)
    assert "edit.dataset.uxrFocusUrl" not in step4_fn
    assert "edit.dataset.uxrFocusUrl" not in step5_fn
    assert "edit.href = " in step4_fn
    assert "edit.href = " in step5_fn

    # Intentional Step-5-only divergence (E2E Finding 5): Step 5 repaints the
    # family monogram tile because a downstream contract's type -- and hence
    # its family -- can change on save. Step 4 handoffs are invariably the
    # "staging" family (step4_handoffs.html hardcodes uxr-fam-staging / "STG"),
    # so a family repaint is not just unnecessary there, it would be wrong:
    # Step 5's UXR_DOWNSTREAM_FAMILY_* maps have no "staging" key, so applying
    # the same block to Step 4 would paint the tile "STAGING" instead of "STG".
    # Assert the asymmetry, then strip the block before the structural compare.
    assert "const tile = row.querySelector('.uxr-fam-tile');" in step5_fn
    assert "const tile = row.querySelector('.uxr-fam-tile');" not in step4_fn
    tile_block_start = step5_fn.index("  // Repaint the family monogram tile")
    tile_block_end = step5_fn.index("  const badge = ", tile_block_start)
    step5_fn = step5_fn[:tile_block_start] + step5_fn[tile_block_end:]

    normalized_step5_fn = step5_fn.replace(
        "/downstream?focus=", "/handoffs?focus="
    ).replace(
        "uxrStateLabel(", "uxrHandoffStateLabel("
    )
    assert step4_fn == normalized_step5_fn, (
        "Step 4's board-row updater must mirror Step 5's implementation "
        "exactly, modulo the route path, the state-label helper name, and "
        "the Step-5-only family-tile repaint block"
    )

    # This function no-ops today (the board is absent in focus mode, so the
    # `if (!row) return;` guard always fires) -- it becomes load-bearing only
    # once PR-17 renders the board alongside the focus editor. Confirm the
    # guard is genuinely there rather than assuming it.
    assert "if (!row) return;" in step4_fn
