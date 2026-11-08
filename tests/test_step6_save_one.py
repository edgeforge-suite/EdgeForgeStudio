"""PR-19 acceptance coverage for rule-set readiness, board, and save-one."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models.project import ClassifiedEntity, ClassifiedField, EntityRules, RuleEntry
from app.services import readiness_view
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)
TEMPLATE = Path(__file__).resolve().parents[1] / "app" / "templates" / "step6_rules.html"


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _seed_rules_session(*, include_prerequisite: bool = True):
    session = reset_session()
    session.app_name = "Rule Set Studio"
    session.bounded_context = "accounts"
    session.target_profile = "springboot-legacy-compatible"
    session.app_archetype = "crud"
    session.project_revision = 7
    session.selected_entity_names = ["AccountResponse", "CustomerResponse"]
    session.classified_entities = [
        ClassifiedEntity(
            name="AccountResponse",
            canonical_name="Account",
            classification="entity",
            fields=[
                ClassifiedField(name="accountId", type="string", is_id=True),
                ClassifiedField(name="customerId", type="string"),
                ClassifiedField(name="requestedAmount", type="decimal"),
            ],
        ),
        ClassifiedEntity(
            name="CustomerResponse",
            canonical_name="Customer",
            classification="entity",
            fields=[
                ClassifiedField(name="customerId", type="string", is_id=True),
                ClassifiedField(
                    name="status",
                    type="string",
                    enum_values=["ACTIVE", "REVIEW"],
                ),
            ],
        ),
    ]
    account_rules = EntityRules(
        entity_name="Account",
        file_path="rules/account-business-rules.yaml",
        rules=(
            [
                RuleEntry(
                    field="customerId",
                    type="cross-entity-exists",
                    target_entity="Customer",
                    applied_by="openapi-spec",
                )
            ]
            if include_prerequisite
            else []
        )
        + [
            RuleEntry(
                field="customerId",
                type="cross-entity-field-check",
                target_entity="Customer",
                target_field="status",
                operator="eq",
                expected_value="ACTIVE",
                applied_by="manual",
            )
        ],
    )
    customer_rules = EntityRules(
        entity_name="Customer",
        file_path="rules/customer-business-rules.yaml",
        rules=[],
    )
    session.entity_rules = [account_rules, customer_rules]
    session.auto_rule_merge_completed_entities = ["Account", "Customer"]
    session.capabilities.knowledge_assist_enabled = False
    session.ks_active = False
    save_session(session)
    return session


def _account_payload(*, include_prerequisite: bool = False) -> dict:
    rules = []
    if include_prerequisite:
        rules.append(
            {
                "field": "customerId",
                "type": "cross-entity-exists",
                "target_entity": "Customer",
                "values": [],
                "value": None,
                "applied_by": "openapi-spec",
            }
        )
    rules.append(
        {
            "field": "customerId",
            "type": "cross-entity-field-check",
            "target_entity": "Customer",
            "target_field": "status",
            "operator": "eq",
            "expected_value": "ACTIVE",
            "values": [],
            "value": None,
            "applied_by": "manual",
        }
    )
    return {
        "entity_name": "Account",
        "rules": rules,
    }


def _add_selected_widget_without_rules(session) -> None:
    session.selected_entity_names.append("WidgetResponse")
    session.classified_entities.append(
        ClassifiedEntity(
            name="WidgetResponse",
            canonical_name="Widget",
            classification="entity",
            fields=[ClassifiedField(name="widgetId", type="string", is_id=True)],
        )
    )


def _advisories(entity: str = "Account") -> dict:
    issue = {
        "entity": entity,
        "field_name": "customerId",
        "conflict_hint": "Review the customer relationship before publishing.",
        "status": "pending",
        "anchor_id": "issue-account-customerid",
    }
    return {
        "enabled": True,
        "available": True,
        "has_items": True,
        "item_count": 1,
        "entity_count": 1,
        "groups": [
            {
                "entity": entity,
                "items": [issue],
                "visible_items": [issue],
                "hidden_items": [],
                "hidden_count": 0,
            }
        ],
    }


def test_save_one_accepts_prerequisite_in_the_same_entity_rule_set():
    _seed_rules_session(include_prerequisite=True)

    response = client.post(
        "/rules/save-one",
        json={
            "item": _account_payload(include_prerequisite=True),
            "original_name": "Account",
            "source_of_truth_version": "7",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["readiness"]["item_id"] == "rule_set:Account"
    assert data["readiness"]["state"] == "ready"
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
    assert all(set(entry) == {"step", "count", "attention"} for entry in data["rail"])


def test_saving_an_unrelated_rule_set_does_not_change_account_readiness():
    _seed_rules_session(include_prerequisite=True)

    response = client.post(
        "/rules/save-one",
        json={
            "item": {
                "entity_name": "Customer",
                "rules": [
                    {
                        "field": "status",
                        "type": "allowed-values",
                        "values": ["ACTIVE", "REVIEW"],
                    }
                ],
            },
            "original_name": "Customer",
            "source_of_truth_version": "7",
        },
    )

    assert response.status_code == 200
    data = response.json()
    affected = next(
        item for item in data["affected_readiness"] if item["item_id"] == "rule_set:Account"
    )
    assert affected["state"] == "ready"
    assert data["step_counts"]["6"] == {"count": 2, "attention": 0}


def test_prerequisite_on_an_unrelated_rule_set_does_not_satisfy_account():
    session = _seed_rules_session(include_prerequisite=False)
    session.entity_rules[1].rules.append(
        RuleEntry(
            field="customerId",
            type="cross-entity-exists",
            target_entity="Customer",
        )
    )
    save_session(session)

    response = client.post(
        "/rules/save-one",
        json={
            "item": _account_payload(),
            "original_name": "Account",
            "source_of_truth_version": "7",
        },
    )

    assert response.status_code == 400
    assert response.json()["blockers"][0]["code"] == "cross-entity-prerequisite-missing"


def test_save_one_rejects_missing_same_owner_prerequisite_without_mutation():
    session = _seed_rules_session(include_prerequisite=False)
    before = session.model_dump(mode="json")

    response = client.post(
        "/rules/save-one",
        json={
            "item": _account_payload(),
            "original_name": "Account",
            "source_of_truth_version": "7",
        },
    )

    assert response.status_code == 400
    blocker = response.json()["blockers"][0]
    assert blocker == {
        "code": "cross-entity-prerequisite-missing",
        "label": "Account.customerId: add a cross-entity-exists rule for this field first.",
        "field_ref": "customerId",
        "section_ref": "cross-entity",
    }
    assert get_session().model_dump(mode="json") == before


def test_save_one_does_not_validate_against_the_stale_rule_set_being_replaced():
    session = _seed_rules_session(include_prerequisite=False)
    session.entity_rules[0].rules.insert(
        0,
        RuleEntry(
            field="customerId",
            type="cross-entity-exists",
            target_entity="Customer",
        ),
    )
    save_session(session)

    response = client.post(
        "/rules/save-one",
        json={
            "item": _account_payload(),
            "original_name": "Account",
            "source_of_truth_version": "7",
        },
    )

    assert response.status_code == 400
    assert response.json()["blockers"][0]["code"] == "cross-entity-prerequisite-missing"


def test_unchanged_save_one_is_a_project_noop():
    session = _seed_rules_session(include_prerequisite=True)
    before = session.model_dump(mode="json")

    response = client.post(
        "/rules/save-one",
        json={
            "item": session.entity_rules[0].model_dump(mode="json"),
            "original_name": "Account",
            "source_of_truth_version": "7",
        },
    )

    assert response.status_code == 200
    assert response.json()["source_of_truth_version"] == "7"
    assert get_session().model_dump(mode="json") == before


def test_unchanged_save_one_preserves_a_custom_server_owned_file_path():
    session = _seed_rules_session(include_prerequisite=True)
    session.entity_rules[0].file_path = "custom/account-rules.yaml"
    save_session(session)
    before = session.model_dump(mode="json")

    response = client.post(
        "/rules/save-one",
        json={
            "item": _account_payload(include_prerequisite=True),
            "original_name": "Account",
            "source_of_truth_version": "7",
        },
    )

    assert response.status_code == 200
    assert response.json()["item"]["file_path"] == "custom/account-rules.yaml"
    assert response.json()["source_of_truth_version"] == "7"
    assert get_session().model_dump(mode="json") == before


def test_legacy_notes_have_a_scoped_save_noop_and_conflict_contract():
    session = _seed_rules_session(include_prerequisite=True)
    session.legacy_notes = "Old notes"
    session.legacy_slug = "old-notes"
    save_session(session)

    saved = client.post(
        "/rules/legacy-notes/save",
        json={
            "legacy_notes": "  Updated notes  ",
            "legacy_slug": "Account Notes",
            "source_of_truth_version": "7",
        },
    )

    assert saved.status_code == 200
    assert saved.json() == {
        "ok": True,
        "legacy_notes": "Updated notes",
        "legacy_slug": "account-notes",
        "source_of_truth_version": "8",
    }
    persisted = get_session()
    assert persisted.legacy_notes == "Updated notes"
    assert persisted.legacy_slug == "account-notes"
    assert persisted.project_revision == 8

    unchanged = client.post(
        "/rules/legacy-notes/save",
        json={
            "legacy_notes": "Updated notes",
            "legacy_slug": "account-notes",
            "source_of_truth_version": "8",
        },
    )
    assert unchanged.status_code == 200
    assert unchanged.json()["source_of_truth_version"] == "8"

    stale = client.post(
        "/rules/legacy-notes/save",
        json={
            "legacy_notes": "Stale overwrite",
            "legacy_slug": "stale",
            "source_of_truth_version": "7",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["legacy_notes"] == "Updated notes"
    assert stale.json()["legacy_slug"] == "account-notes"
    assert stale.json()["source_of_truth_version"] == "8"
    assert get_session().legacy_notes == "Updated notes"


def test_save_one_rename_replaces_the_original_rule_set_without_an_orphan():
    _seed_rules_session(include_prerequisite=True)
    renamed = {
        "entity_name": "LedgerAccount",
        "rules": [
            {
                "field": "status",
                "type": "allowed-values",
                "values": ["OPEN", "CLOSED"],
                "value": None,
                "applied_by": "manual",
            }
        ],
    }

    response = client.post(
        "/rules/save-one",
        json={
            "item": renamed,
            "original_name": "Account",
            "source_of_truth_version": "7",
        },
    )

    assert response.status_code == 200
    names = [entity_rules.entity_name for entity_rules in get_session().entity_rules]
    assert names == ["LedgerAccount", "Customer"]
    assert "Account" not in names
    assert response.json()["readiness"]["item_id"] == "rule_set:LedgerAccount"


def test_stale_save_returns_exact_current_item_and_does_not_mutate():
    session = _seed_rules_session(include_prerequisite=True)
    before = session.model_dump(mode="json")

    response = client.post(
        "/rules/save-one",
        json={
            "item": {**_account_payload(), "entity_name": "RenamedAccount"},
            "original_name": "Account",
            "source_of_truth_version": "6",
        },
    )

    assert response.status_code == 409
    data = response.json()
    assert data["item"]["entity_name"] == "Account"
    assert data["readiness"]["item_id"] == "rule_set:Account"
    assert data["recovery"] == "review-current-item"
    assert data["source_of_truth_version"] == "7"
    assert get_session().model_dump(mode="json") == before


def test_rule_set_readiness_and_step_counts_use_same_owner_prerequisites():
    session = _seed_rules_session(include_prerequisite=True)

    items = readiness_view.items_for_step(session, 6)
    account = next(item for item in items if item.item_id == "rule_set:Account")

    assert len(items) == 2
    assert account.state == "ready"
    assert account.export_blocking is False
    assert account.coverage[0].complete == 1
    assert account.coverage[0].total == 3
    assert readiness_view.item(session, "rule_set:Account") == account
    assert readiness_view.step_counts(session)[6] == {"count": 2, "attention": 0}


def test_rule_set_readiness_needs_action_and_advisory_warning_precedence():
    missing_session = _seed_rules_session(include_prerequisite=False)
    missing = readiness_view.rule_set_item(
        missing_session,
        "Account",
        conflict_advisories=_advisories(),
    )
    assert missing.state == "needs_action"
    assert missing.blockers[0].field_ref == "customerId"

    ready_session = _seed_rules_session(include_prerequisite=True)
    warning = next(
        item
        for item in readiness_view.items_for_step(
            ready_session,
            6,
            conflict_advisories=_advisories(),
        )
        if item.item_id == "rule_set:Account"
    )
    assert warning.state == "warning"
    assert warning.warnings[0].label == "Review the customer relationship before publishing."
    assert warning.export_blocking is False


def test_flag_on_board_and_focus_render_from_readiness_and_server_metadata(monkeypatch):
    _seed_rules_session(include_prerequisite=True)
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setattr(
        "app.routes.rules.assist_service.get_advisory_conflicts",
        lambda *args, **kwargs: _advisories(),
    )

    board = client.get("/rules")
    focus = client.get("/rules?focus=Account")

    assert board.status_code == 200
    assert 'data-uxr-board="rules"' in board.text
    assert 'data-uxr-row-name="Account"' in board.text
    assert 'data-uxr-row-kind="rule_set"' in board.text
    assert "SPEC-DERIVED" in board.text
    assert "Review the customer relationship before publishing." in board.text
    assert focus.status_code == 200
    assert 'data-uxr-focus-editor="Account"' in focus.text
    assert 'data-rule-field="customerId"' in focus.text
    assert 'data-uxr-prerequisite-state="satisfied"' in focus.text
    assert "via customerId" in focus.text


def test_selected_entity_without_rules_keeps_board_and_add_rule_focus_path(monkeypatch):
    session = _seed_rules_session(include_prerequisite=True)
    _add_selected_widget_without_rules(session)
    save_session(session)
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")

    board = client.get("/rules")
    focus = client.get("/rules?focus=Widget")

    assert 'data-uxr-row-name="Widget"' in board.text
    assert 'data-uxr-focus-editor="Widget"' in focus.text
    assert 'data-rule-field="widgetId"' in focus.text
    assert 'data-uxr-add-field-rule data-field="widgetId"' in focus.text
    assert all(entity_rules.entity_name != "Widget" for entity_rules in get_session().entity_rules)

    before = get_session().model_dump(mode="json")
    unchanged = client.post(
        "/rules/save-one",
        json={
            "item": {"entity_name": "Widget", "rules": []},
            "original_name": "Widget",
            "source_of_truth_version": "7",
        },
    )
    assert unchanged.status_code == 200
    assert unchanged.json()["source_of_truth_version"] == "7"
    assert unchanged.json()["item"]["file_path"] is None
    assert get_session().model_dump(mode="json") == before


def test_save_response_keeps_projected_row_metadata_and_advisories(monkeypatch):
    session = _seed_rules_session(include_prerequisite=True)
    _add_selected_widget_without_rules(session)
    save_session(session)
    requested_entities: list[list[str]] = []

    def widget_advisory(*args, **kwargs):
        requested_entities.append(list(kwargs["canonical_entities"]))
        return _advisories("Widget")

    monkeypatch.setattr(
        "app.routes.rules.assist_service.get_advisory_conflicts",
        widget_advisory,
    )

    response = client.post(
        "/rules/save-one",
        json={
            "item": session.entity_rules[0].model_dump(mode="json"),
            "original_name": "Account",
            "source_of_truth_version": "7",
        },
    )

    assert response.status_code == 200
    data = response.json()
    widget = next(
        item for item in data["affected_readiness"] if item["item_id"] == "rule_set:Widget"
    )
    assert widget["state"] == "warning"
    assert widget["warnings"][0]["label"] == "Review the customer relationship before publishing."
    assert data["affected_board_metadata"]["Widget"] == {
        "rule_count": 0,
        "file_path": None,
        "fields_complete": 0,
        "fields_total": 1,
        "advisory_count": 1,
        "spec_derived": 0,
        "manual": 0,
        "ka_applied": 0,
    }
    assert requested_entities[-1] == ["Account", "Customer", "Widget"]


def test_get_and_save_refresh_use_the_same_visible_advisory_entities(monkeypatch):
    session = _seed_rules_session(include_prerequisite=True)
    session.selected_entity_names = ["AccountResponse"]
    save_session(session)
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    requested_entities: list[list[str]] = []

    def customer_advisory(*args, **kwargs):
        requested_entities.append(list(kwargs["canonical_entities"]))
        return _advisories("Customer")

    monkeypatch.setattr(
        "app.routes.rules.assist_service.get_advisory_conflicts",
        customer_advisory,
    )

    board = client.get("/rules")
    response = client.post(
        "/rules/save-one",
        json={
            "item": session.entity_rules[0].model_dump(mode="json"),
            "original_name": "Account",
            "source_of_truth_version": "7",
        },
    )

    assert board.status_code == 200
    assert 'data-uxr-row-name="Customer"' in board.text
    assert "Review the customer relationship before publishing." in board.text
    assert response.status_code == 200
    customer = next(
        item
        for item in response.json()["affected_readiness"]
        if item["item_id"] == "rule_set:Customer"
    )
    assert customer["state"] == "warning"
    assert requested_entities == [
        ["Account", "Customer"],
        ["Account", "Customer"],
    ]


def test_ka_off_board_has_no_advisory_strip_and_never_opens_ks(monkeypatch):
    _seed_rules_session(include_prerequisite=True)
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    called = False

    @contextmanager
    def fail_if_called(**kwargs):
        nonlocal called
        called = True
        raise AssertionError("KA-off Step 6 must not open a Knowledge Server client")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fail_if_called)

    response = client.get("/rules")

    assert response.status_code == 200
    assert called is False
    assert "data-uxr-advisory-strip" not in response.text


def test_retired_flag_off_value_keeps_refreshed_rules_surface(monkeypatch):
    _seed_rules_session(include_prerequisite=True)
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")

    response = client.get("/rules?focus=Account")

    assert response.status_code == 200
    assert 'data-uxr-focus-editor="Account"' in response.text
    assert 'data-uxr-board="rules"' in response.text
    assert 'data-uxr-split="true"' in response.text


def test_static_focus_contract_uses_saved_payload_and_shipped_reconciliation_guards():
    source = TEMPLATE.read_text()

    assert "postJSON('/rules/save-one'" in source
    assert "item: getCardRules(card)" in source
    assert "snapshot: () => uxrRulePageDirtyState(card)" in source
    assert "postJSON('/rules/legacy-notes/save'" in source
    assert "legacy_notes: !!uxrSavedLegacyNotes" in source
    assert "data-uxr-save-legacy-notes" in source
    assert "data-uxr-legacy-notes-conflict-server-state" in source
    assert "data-uxr-legacy-notes-use-server" in source
    assert "data-uxr-legacy-notes-keep-draft" in source
    save_notes = source.split("async function uxrSaveLegacyNotes()", 1)[1].split(
        "function uxrInitRulesBoard()", 1
    )[0]
    conflict_branch = save_notes.split("if (!data.ok)", 1)[1].split("return;", 1)[0]
    assert "uxrShowLegacyNotesConflict(data)" in conflict_branch
    assert "uxrUpdateRuleSourceVersion" not in conflict_branch
    assert "button.disabled = Boolean(uxrLegacyNotesConflict)" in save_notes
    resolve_notes = source.split("function uxrResolveLegacyNotesConflict(useServer)", 1)[
        1
    ].split("function uxrRuleGroupForState", 1)[0]
    assert "} else {\n    uxrSavedLegacyNotes = {" in resolve_notes
    assert "legacy_notes: data.legacy_notes || ''" in resolve_notes
    assert "legacy_slug: data.legacy_slug || ''" in resolve_notes
    assert "uxrRenderRuleSaveBlockers(data.blockers || [])" in source
    assert "if (!entry.count)" in source
    assert "chip.className = 'badge uxr-rail-chip'" in source
    assert "uxrRegroupRuleBoardRow(row)" in source
    assert "data-uxr-add-prerequisite" in source
