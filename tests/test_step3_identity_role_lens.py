"""PR-10 acceptance coverage for the flag-gated Step 3 identity-role lens."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    ClassifiedOperation,
    IdentityRoleDecision,
)
from app.services.identity_roles import eligible_identity_fields
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "app" / "templates" / "step3_entities.html"
STEP3_JS = ROOT / "app" / "static" / "js" / "step3_entities.js"


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _fields(count: int = 4, *, has_model_id: bool = True) -> list[ClassifiedField]:
    return [
        ClassifiedField(
            name="accountId" if index == 0 else f"field{index:02d}",
            type="string",
            required=index < 3,
            is_id=has_model_id and index == 0,
        )
        for index in range(count)
    ]


def _seed_lens(
    *,
    field_count: int = 4,
    roles: dict[str, str] | None = None,
    has_model_id: bool = True,
    selected: bool = True,
) -> None:
    session = get_session()
    session.app_name = "Identity Lens Fixture"
    session.bounded_context = "identity-lens-fixture"
    session.app_archetype = "crud"
    session.classified_entities = [
        ClassifiedEntity(
            name="AccountResponse",
            canonical_name="Account",
            classification="entity",
            fields=_fields(field_count, has_model_id=has_model_id),
        )
    ]
    session.classified_operations = [
        ClassifiedOperation(
            name="getAccount",
            method="GET",
            path="/accounts/{accountId}",
            resource="accounts",
            entity_candidates=["Account"],
        )
    ]
    session.selected_entity_names = ["AccountResponse"] if selected else []
    session.selected_operation_names = ["getAccount"] if selected else []
    session.identity_role_decisions = [
        IdentityRoleDecision(
            entity="Account",
            field=field,
            role=role,
            reviewed_at="2026-07-10T10:00:00+00:00",
        )
        for field, role in (roles or {}).items()
    ]
    save_session(session)


def _render(monkeypatch: pytest.MonkeyPatch, *, enabled: bool) -> str:
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true" if enabled else "false")
    response = client.get("/entities")
    assert response.status_code == 200
    return response.text


def _selected_option_value(options_html: str) -> str:
    for option in re.finditer(r"<option(?P<attrs>.*?)>", options_html, re.S):
        attrs = option.group("attrs")
        if re.search(r"\sselected(?:\s|$)", attrs):
            value = re.search(r'\bvalue="([^"]*)"', attrs)
            return value.group(1) if value else ""
    return ""


def _identity_payload(html: str) -> dict:
    decisions = []
    for match in re.finditer(
        r'<select\s+class="identity-role-select"\s+data-entity="([^"]+)"\s+'
        r'data-field="([^"]+)"[^>]*>(.*?)</select>',
        html,
        re.S,
    ):
        decisions.append(
            {
                "entity": match.group(1),
                "field": match.group(2),
                "role": _selected_option_value(match.group(3)),
            }
        )
    return {"decisions": decisions}


def _selection_payload(html: str) -> dict:
    selected_entities = []
    selected_operations = []
    for tag in re.findall(r"<input\b[^>]*>", html, re.S):
        value = re.search(r'\bvalue="([^"]*)"', tag)
        if not value or not re.search(r"\schecked(?:\s|>)", tag):
            continue
        if 'class="entity-checkbox"' in tag:
            selected_entities.append(value.group(1))
        if 'class="op-checkbox"' in tag:
            selected_operations.append(value.group(1))

    entity_op_map: dict[str, list[str]] = {}
    for match in re.finditer(
        r'<select\s+class="op-entity-select"\s+data-op="([^"]+)"[^>]*>(.*?)</select>',
        html,
        re.S,
    ):
        operation = match.group(1)
        entity = _selected_option_value(match.group(2))
        if entity and operation in selected_operations:
            entity_op_map.setdefault(entity, []).append(operation)
    return {
        "entities": selected_entities,
        "operations": selected_operations,
        "entity_op_map": entity_op_map,
    }


def _semantic_snapshot(html: str) -> dict:
    stats = {
        key: int(value)
        for key, value in re.findall(
            r'data-uxr-identity-stat="([^"]+)">(\d+)',
            html,
        )
    }
    return {
        "stats": stats,
        "entity_cards": re.findall(r'data-uxr-identity-entity="([^"]+)"', html),
        "field_selects": html.count('class="identity-role-select"'),
        "collapsed_rows": len(
            re.findall(r'class="uxr-identity-field-row is-collapsed"', html)
        ),
        "has_search": "data-uxr-identity-search" in html,
        "missing_key": "uxr-identity-role-chip is-missing" in html,
    }


@pytest.mark.parametrize(
    ("state", "seed_kwargs", "expected"),
    [
        (
            "empty",
            {"selected": False},
            {
                "stats": {
                    "entities": 0,
                    "persistence_ids": 0,
                    "metadata_roles": 0,
                    "no_role_hidden": 0,
                },
                "entity_cards": [],
                "field_selects": 0,
                "collapsed_rows": 0,
                "has_search": False,
                "missing_key": False,
            },
        ),
        (
            "single_entity",
            {},
            {
                "stats": {
                    "entities": 1,
                    "persistence_ids": 0,
                    "metadata_roles": 0,
                    "no_role_hidden": 4,
                },
                "entity_cards": ["Account"],
                "field_selects": 4,
                "collapsed_rows": 4,
                "has_search": False,
                "missing_key": False,
            },
        ),
        (
            "many_fields",
            {"field_count": 55},
            {
                "stats": {
                    "entities": 1,
                    "persistence_ids": 0,
                    "metadata_roles": 0,
                    "no_role_hidden": 52,
                },
                "entity_cards": ["Account"],
                "field_selects": 55,
                "collapsed_rows": 52,
                "has_search": True,
                "missing_key": False,
            },
        ),
        (
            "roles_assigned",
            {"roles": {"accountId": "persistence_id", "field01": "business_key"}},
            {
                "stats": {
                    "entities": 1,
                    "persistence_ids": 1,
                    "metadata_roles": 1,
                    "no_role_hidden": 2,
                },
                "entity_cards": ["Account"],
                "field_selects": 4,
                "collapsed_rows": 2,
                "has_search": False,
                "missing_key": False,
            },
        ),
        (
            "missing_key",
            {"roles": {"field01": "business_key"}, "has_model_id": False},
            {
                "stats": {
                    "entities": 1,
                    "persistence_ids": 0,
                    "metadata_roles": 1,
                    "no_role_hidden": 3,
                },
                "entity_cards": ["Account"],
                "field_selects": 4,
                "collapsed_rows": 3,
                "has_search": False,
                "missing_key": True,
            },
        ),
    ],
)
def test_flag_on_lens_semantic_render_snapshots(
    monkeypatch: pytest.MonkeyPatch,
    state: str,
    seed_kwargs: dict,
    expected: dict,
) -> None:
    del state  # Param id documents the five required render states.
    _seed_lens(**seed_kwargs)

    assert _semantic_snapshot(_render(monkeypatch, enabled=True)) == expected


def test_identity_payload_is_byte_equivalent_and_keeps_hidden_blank_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_lens(roles={"accountId": "persistence_id", "field01": "business_key"})
    legacy_payload = _identity_payload(_render(monkeypatch, enabled=False))
    lens_payload = _identity_payload(_render(monkeypatch, enabled=True))

    assert lens_payload == legacy_payload
    assert lens_payload == {
        "decisions": [
            {"entity": "Account", "field": "accountId", "role": "persistence_id"},
            {"entity": "Account", "field": "field01", "role": "business_key"},
            {"entity": "Account", "field": "field02", "role": ""},
            {"entity": "Account", "field": "field03", "role": ""},
        ]
    }

    response = client.post("/entities/identity-roles", json=lens_payload)
    assert response.status_code == 200
    assert response.json()["saved_count"] == 2


def test_identity_save_returns_authoritative_live_lens_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_lens(roles={"field01": "business_key"}, has_model_id=False)
    before_stats = _semantic_snapshot(_render(monkeypatch, enabled=True))["stats"]
    decisions = [
        {"entity": "Account", "field": "accountId", "role": "persistence_id"},
        {"entity": "Account", "field": "field01", "role": "business_key"},
        {"entity": "Account", "field": "field02", "role": ""},
        {"entity": "Account", "field": "field03", "role": ""},
    ]

    with patch("app.integrations.ks_integration.KSClient.start") as start:
        response = client.post("/entities/identity-roles", json={"decisions": decisions})

    start.assert_not_called()
    assert response.status_code == 200
    result = response.json()
    assert before_stats["persistence_ids"] == 0
    assert result["stats"] == {
        "entities": 1,
        "persistence_ids": 1,
        "metadata_roles": 1,
        "no_role_hidden": 2,
    }
    entity = result["entities"][0]
    assert entity["name"] == "Account"
    assert entity["assigned_count"] == 2
    assert entity["missing_key"] is False
    assert {field["name"]: field["current_role"] for field in entity["fields"]} == {
        "accountId": "persistence_id",
        "field01": "business_key",
        "field02": "",
        "field03": "",
    }
    assert next(
        field["reviewed_at"] for field in entity["fields"] if field["name"] == "accountId"
    )
    assert "ka_summary" not in result

    cleared = client.post(
        "/entities/identity-roles",
        json={"decisions": [{"entity": "Account", "field": "accountId", "role": ""}]},
    )
    assert cleared.status_code == 200
    cleared_account = next(
        field
        for field in cleared.json()["entities"][0]["fields"]
        if field["name"] == "accountId"
    )
    assert cleared_account["current_role"] == ""
    assert cleared_account["reviewed_at"] == ""


def test_selection_payload_is_byte_equivalent_in_both_flag_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_lens()

    legacy_payload = _selection_payload(_render(monkeypatch, enabled=False))
    lens_payload = _selection_payload(_render(monkeypatch, enabled=True))

    assert lens_payload == legacy_payload == {
        "entities": ["AccountResponse"],
        "operations": ["getAccount"],
        "entity_op_map": {"AccountResponse": ["getAccount"]},
    }
    response = client.post("/entities/save", json=lens_payload)
    assert response.status_code == 200
    assert response.json()["interface_count"] == 1


def test_missing_key_and_engine_behavior_copy_come_from_server_producers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_lens(roles={"field01": "business_key"}, has_model_id=False)

    html = _render(monkeypatch, enabled=True)

    assert "No persistence key chosen" in html
    assert "uxr-identity-role-chip is-missing" in html
    assert "Exported as metadata only; no generated app behavior yet." in html
    assert "data-uxr-persistence-impact-ready hidden" in html


def test_model_id_fallback_does_not_render_a_false_missing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_lens(roles={}, has_model_id=True)

    html = _render(monkeypatch, enabled=True)

    assert "Existing model identity <code>accountId</code> remains authoritative." in html
    assert "data-uxr-persistence-impact-fallback" in html
    assert "data-uxr-persistence-impact-missing hidden" in html


def test_is_id_is_projected_for_deterministic_filtering() -> None:
    _seed_lens()

    fields = eligible_identity_fields(get_session(), "Account")

    assert fields[0]["name"] == "accountId"
    assert fields[0]["is_id"] is True
    assert all(field["is_id"] is False for field in fields[1:])


def test_id_looking_filter_uses_model_name_and_type_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_lens(field_count=5, has_model_id=False)
    session = get_session()
    fields = session.classified_entities[0].fields
    fields[0].name = "accountId"
    fields[1].name = "externalAccountNumber"
    fields[2].name = "requestUuid"
    fields[3].name = "opaqueKey"
    fields[3].type = "uuid"
    fields[4].name = "status"
    save_session(session)

    html = _render(monkeypatch, enabled=True)

    assert "ID-looking fields · 4" in html
    assert html.count('data-id-looking="true"') == 4
    assert 'data-uxr-identity-field="status" data-is-id="false"\n                        data-id-looking="false"' in html


def test_ka_off_lens_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_lens()
    session = get_session()
    session.capabilities.knowledge_assist_enabled = False
    save_session(session)

    with patch("app.integrations.ks_integration.KSClient.start") as start:
        html = _render(monkeypatch, enabled=True)

    start.assert_not_called()
    assert "Knowledge Assist: Off" in html
    assert "data-step3-ka-full-review" not in html
    assert "/entities/ks/" not in html


def test_js_preserves_payload_producers_and_uses_delegated_lens_controls() -> None:
    source = STEP3_JS.read_text(encoding="utf-8")
    identity_save = source[
        source.index("async function saveIdentityRoles()") : source.index(
            "\n}\n\ndocument.addEventListener('change'",
            source.index("async function saveIdentityRoles()"),
        )
    ]
    selection_save = source[
        source.index("async function saveSelectionPhase1()") : source.index(
            "\n}\n\n/* -----------------------------------------------------------------------",
            source.index("async function saveSelectionPhase1()"),
        )
    ]

    assert "document.querySelectorAll('.identity-role-select')" in identity_save
    assert "role: selectEl.value || ''" in identity_save
    assert "postJSON('/entities/identity-roles', { decisions })" in identity_save
    assert "postJSON('/entities/save', {" in selection_save
    assert "entities: selection.selectedEntityNames" in selection_save
    assert "operations: selection.selectedOperationNames" in selection_save
    assert "entity_op_map: selection.entityOperationMap" in selection_save
    assert "document.addEventListener('click', event =>" in source
    assert "document.addEventListener('input', event =>" in source
    assert "data-uxr-identity-filter" in source
    assert "data-uxr-identity-show-all" in source
    assert "syncIdentityLensPersistencePicker(detail);" in source
    assert "applyIdentityRoleLensProjection(lens, result);" in identity_save
    assert "window.location.reload()" not in identity_save
    assert "stashStep3SelectionReloadDraft()" not in identity_save
    assert "lens.querySelectorAll('[data-uxr-identity-stat]')" in source
    assert "fields.forEach(field =>" in source
    assert "role = field.current_role || ''" in source
    assert "row.querySelector('[data-uxr-identity-reviewed]')" in source
    assert "reviewed.classList.toggle('hidden', !reviewedAt)" in source
    assert "if (!lens)" in identity_save
    assert "detail.dataset.uxrFilterMode = 'assigned'" in source
    assert "control.setAttribute('aria-pressed', 'false')" in source


def test_retired_flag_off_value_keeps_identity_lens_and_full_payload_selects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_lens()

    html = _render(monkeypatch, enabled=False)

    assert "data-uxr-identity-lens" in html
    assert html.count('class="identity-role-select"') == 4
    assert "identity-role-select-legacy" not in html
    assert 'id="identity-role-status"' in html


def test_flag_on_save_status_is_a_live_region(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_lens()

    html = _render(monkeypatch, enabled=True)

    assert (
        'id="identity-role-status" class="alert hidden" role="status" '
        'aria-live="polite" aria-atomic="true"'
    ) in html
    assert html.count("data-uxr-identity-reviewed") == 4


def test_identity_live_patch_preserves_unrelated_step3_drafts_without_reload() -> None:
    """Phase 1/2 drafts remain in place because role save no longer reloads the page."""
    source = STEP3_JS.read_text(encoding="utf-8")
    identity_save = source[
        source.index("async function saveIdentityRoles()") : source.index(
            "\n}\n\ndocument.addEventListener('change'",
            source.index("async function saveIdentityRoles()"),
        )
    ]
    live_patch = source[
        source.index("function applyIdentityRoleLensProjection") : source.index(
            "\n}\n\nasync function saveIdentityRoles()",
            source.index("function applyIdentityRoleLensProjection"),
        )
    ]

    assert "STEP3_SELECTION_RELOAD_DRAFT_KEY" not in source
    assert "captureStep3SelectionReloadDraft" not in source
    assert "stashStep3SelectionReloadDraft" not in source
    assert "consumeStep3SelectionReloadDraft" not in source
    assert "restoreStep3SelectionReloadDraft" not in source
    assert "restoreStep3Phase2ReloadDraft" not in source
    assert "window.location.reload()" not in identity_save
    assert "window.setTimeout(" not in identity_save
    assert "renderPhase2(" not in identity_save
    assert ".entity-checkbox" not in live_patch
    assert ".op-checkbox" not in live_patch
    assert "#interface-panels" not in live_patch
