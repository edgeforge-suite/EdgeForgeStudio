"""Tests for Step 6 rules route behavior."""

import asyncio
from contextlib import contextmanager

from fastapi import Request
from fastapi.testclient import TestClient

from app.integrations.ks_integration import KSCallError, KSUnavailableError
from app.main import app
from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    EntityRules,
    KSEvidenceLink,
    KSReviewHistoryEntry,
    OperationSample,
    RuleEntry,
    UpstreamInterface,
)
from app.routes.rules import assist_service, step6_get
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)


def _seed_step6_session(*, app_archetype: str = "crud", include_generated_id_warning: bool = False):
    session = reset_session()
    session.app_name = "Rules App"
    session.bounded_context = "accounts"
    session.target_profile = "springboot-legacy-compatible"
    session.app_archetype = app_archetype

    if app_archetype == "crud":
        account_fields = [
            ClassifiedField(name="creditLimit", type="decimal"),
            ClassifiedField(name="accountName", type="string"),
        ]
        if include_generated_id_warning:
            account_fields.append(ClassifiedField(name="accountId", type="string", is_id=True))

        session.selected_entity_names = ["AccountResponse"]
        session.classified_entities = [
            ClassifiedEntity(
                name="AccountResponse",
                canonical_name="Account",
                classification="entity",
                fields=account_fields,
            )
        ]
        session.project_id = "studio-ks-rules"
        session.ks_project_id = "studio-ks-rules"
        session.capabilities.knowledge_assist_enabled = True
        session.ks_active = True
        if include_generated_id_warning:
            session.upstream_interfaces = [
                UpstreamInterface(
                    name="AccountInterface",
                    entity_name="AccountResponse",
                    operations=[
                        OperationSample(
                            name="createAccount",
                            request_sample_content='{"name":"Primary"}',
                        )
                    ],
                )
            ]
    else:
        session.selected_entity_names = []
        session.classified_entities = []

    save_session(session)
    return session


def _seed_multi_entity_step6_session(count: int = 5):
    session = reset_session()
    session.app_name = "Rules App"
    session.bounded_context = "accounts"
    session.target_profile = "springboot-legacy-compatible"
    session.app_archetype = "crud"
    session.selected_entity_names = [f"Entity{index}Response" for index in range(1, count + 1)]
    session.classified_entities = [
        ClassifiedEntity(
            name=f"Entity{index}Response",
            canonical_name=f"Entity{index}",
            classification="entity",
            fields=[
                ClassifiedField(name="status", type="string"),
                ClassifiedField(name="amount", type="decimal"),
            ],
        )
        for index in range(1, count + 1)
    ]
    session.project_id = "studio-ks-rules"
    session.ks_project_id = "studio-ks-rules"
    session.capabilities.knowledge_assist_enabled = True
    session.ks_active = True
    save_session(session)
    return session


def _seed_cross_entity_step6_session():
    session = reset_session()
    session.app_name = "Cross Entity Rules"
    session.bounded_context = "accounts"
    session.target_profile = "springboot-legacy-compatible"
    session.app_archetype = "crud"
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
                ClassifiedField(name="accountStatus", type="string"),
            ],
        ),
        ClassifiedEntity(
            name="CustomerResponse",
            canonical_name="Customer",
            classification="entity",
            fields=[
                ClassifiedField(name="customerId", type="string", is_id=True),
                ClassifiedField(name="status", type="string", enum_values=["ACTIVE", "REVIEW", "FROZEN"]),
                ClassifiedField(name="approvedLimit", type="decimal"),
                ClassifiedField(name="creditScore", type="integer"),
                ClassifiedField(name="branchCode", type="string"),
            ],
        ),
    ]
    save_session(session)
    return session


def test_step6_save_persists_cross_entity_exists_target():
    reset_session()

    response = client.post(
        "/rules/save",
        json={
            "entity_rules": [
                {
                    "entity_name": "Account",
                    "rules": [
                        {
                            "field": "customerId",
                            "type": "cross-entity-exists",
                            "target_entity": "Customer",
                        }
                    ],
                }
            ],
            "legacy_notes": None,
            "legacy_slug": "dda",
        },
    )

    assert response.status_code == 200
    session = get_session()
    rule = session.entity_rules[0].rules[0]
    assert rule.type == "cross-entity-exists"
    assert rule.target_entity == "Customer"

    reset_session()


def test_step6_save_persists_field_comparison_rule():
    reset_session()

    response = client.post(
        "/rules/save",
        json={
            "entity_rules": [
                {
                    "entity_name": "Repayment",
                    "rules": [
                        {
                            "field": "paidAmount",
                            "type": "field-comparison",
                            "operator": "<=",
                            "compare_to_field": "dueAmount",
                        }
                    ],
                }
            ],
            "legacy_notes": None,
            "legacy_slug": "repayments",
        },
    )

    assert response.status_code == 200
    session = get_session()
    rule = session.entity_rules[0].rules[0]
    assert rule.type == "field-comparison"
    assert rule.operator == "<="
    assert rule.compare_to_field == "dueAmount"

    reset_session()


def test_step6_save_persists_new_cross_entity_rule_types():
    _seed_cross_entity_step6_session()

    response = client.post(
        "/rules/save",
        json={
            "entity_rules": [
                {
                    "entity_name": "Account",
                    "rules": [
                        {
                            "field": "customerId",
                            "type": "cross-entity-exists",
                            "target_entity": "Customer",
                        },
                        {
                            "field": "customerId",
                            "type": "cross-entity-field-check",
                            "target_field": "status",
                            "operator": "eq",
                            "expected_value": "ACTIVE",
                            "error_message": "Customer must be ACTIVE.",
                        },
                        {
                            "field": "customerId",
                            "type": "cross-entity-field-compare",
                            "target_field": "approvedLimit",
                            "source_field": "requestedAmount",
                            "operator": "lte",
                            "error_message": "Requested amount exceeds approved limit.",
                        },
                        {
                            "field": "customerId",
                            "type": "cross-entity-field-in",
                            "target_field": "status",
                            "values": ["ACTIVE", "REVIEW"],
                            "error_message": "Customer status must be eligible.",
                        },
                    ],
                }
            ],
            "legacy_notes": None,
            "legacy_slug": "accounts",
        },
    )

    assert response.status_code == 200
    rules = get_session().entity_rules[0].rules
    assert rules[1].type == "cross-entity-field-check"
    assert rules[1].target_entity == "Customer"
    assert rules[1].target_field == "status"
    assert rules[1].operator == "eq"
    assert rules[1].expected_value == "ACTIVE"
    assert rules[1].error_message == "Customer must be ACTIVE."

    assert rules[2].type == "cross-entity-field-compare"
    assert rules[2].target_entity == "Customer"
    assert rules[2].target_field == "approvedLimit"
    assert rules[2].source_field == "requestedAmount"
    assert rules[2].operator == "lte"
    assert rules[2].error_message == "Requested amount exceeds approved limit."

    assert rules[3].type == "cross-entity-field-in"
    assert rules[3].target_entity == "Customer"
    assert rules[3].target_field == "status"
    assert rules[3].values == ["ACTIVE", "REVIEW"]
    assert rules[3].error_message == "Customer status must be eligible."

    reset_session()


def test_step6_save_persists_numeric_cross_entity_field_check():
    _seed_cross_entity_step6_session()

    response = client.post(
        "/rules/save",
        json={
            "entity_rules": [
                {
                    "entity_name": "Account",
                    "rules": [
                        {
                            "field": "customerId",
                            "type": "cross-entity-exists",
                            "target_entity": "Customer",
                        },
                        {
                            "field": "customerId",
                            "type": "cross-entity-field-check",
                            "target_field": "approvedLimit",
                            "operator": "gte",
                            "expected_value": "1000.50",
                            "error_message": "Customer approved limit must be at least 1000.50.",
                        },
                    ],
                }
            ],
            "legacy_notes": None,
            "legacy_slug": "accounts",
        },
    )

    assert response.status_code == 200
    rule = get_session().entity_rules[0].rules[1]
    assert rule.type == "cross-entity-field-check"
    assert rule.target_field == "approvedLimit"
    assert rule.operator == "gte"
    assert rule.expected_value == "1000.50"

    reset_session()


def test_step6_save_normalizes_common_double_escaped_pattern_rule():
    reset_session()

    response = client.post(
        "/rules/save",
        json={
            "entity_rules": [
                {
                    "entity_name": "Customer",
                    "rules": [
                        {
                            "field": "email",
                            "type": "pattern",
                            "value": r"^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$",
                        }
                    ],
                }
            ],
            "legacy_notes": None,
            "legacy_slug": "dda",
        },
    )

    assert response.status_code == 200
    session = get_session()
    rule = session.entity_rules[0].rules[0]
    assert rule.type == "pattern"
    assert rule.value == r"^[^\s@]+@[^\s@]+\.[^\s@]+$"

    reset_session()


def test_step6_save_rejects_missing_cross_entity_exists_prerequisite():
    _seed_cross_entity_step6_session()

    response = client.post(
        "/rules/save",
        json={
            "entity_rules": [
                {
                    "entity_name": "Account",
                    "rules": [
                        {
                            "field": "customerId",
                            "type": "cross-entity-field-check",
                            "target_field": "status",
                            "operator": "eq",
                            "expected_value": "ACTIVE",
                        }
                    ],
                }
            ],
            "legacy_notes": None,
            "legacy_slug": "accounts",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["ok"] is False
    assert any("cross-entity-exists" in msg for msg in payload["errors"])

    reset_session()


def test_step6_save_rejects_missing_cross_entity_fk_field():
    _seed_cross_entity_step6_session()

    response = client.post(
        "/rules/save",
        json={
            "entity_rules": [
                {
                    "entity_name": "Account",
                    "rules": [
                        {
                            "field": "",
                            "type": "cross-entity-field-check",
                            "target_field": "status",
                            "operator": "eq",
                            "expected_value": "ACTIVE",
                        }
                    ],
                }
            ],
            "legacy_notes": None,
            "legacy_slug": "accounts",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["ok"] is False
    assert any("requires an FK field" in msg for msg in payload["errors"])

    reset_session()


def test_step6_save_rejects_invalid_cross_entity_field_check_operator():
    _seed_cross_entity_step6_session()

    response = client.post(
        "/rules/save",
        json={
            "entity_rules": [
                {
                    "entity_name": "Account",
                    "rules": [
                        {
                            "field": "customerId",
                            "type": "cross-entity-exists",
                            "target_entity": "Customer",
                        },
                        {
                            "field": "customerId",
                            "type": "cross-entity-field-check",
                            "target_field": "status",
                            "operator": "contains",
                            "expected_value": "ACTIVE",
                        },
                    ],
                }
            ],
            "legacy_notes": None,
            "legacy_slug": "accounts",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["ok"] is False
    assert any("cross-entity-field-check operator must be one of" in msg for msg in payload["errors"])

    reset_session()


def test_step6_save_rejects_cross_entity_field_check_expected_value_type_mismatch():
    _seed_cross_entity_step6_session()

    response = client.post(
        "/rules/save",
        json={
            "entity_rules": [
                {
                    "entity_name": "Account",
                    "rules": [
                        {
                            "field": "customerId",
                            "type": "cross-entity-exists",
                            "target_entity": "Customer",
                        },
                        {
                            "field": "customerId",
                            "type": "cross-entity-field-check",
                            "target_field": "approvedLimit",
                            "operator": "gte",
                            "expected_value": "ACTIVE",
                        },
                    ],
                }
            ],
            "legacy_notes": None,
            "legacy_slug": "accounts",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["ok"] is False
    assert any("expected-value is incompatible" in msg for msg in payload["errors"])

    reset_session()


def test_step6_save_rejects_decimal_expected_value_for_integer_field_check_target():
    _seed_cross_entity_step6_session()

    response = client.post(
        "/rules/save",
        json={
            "entity_rules": [
                {
                    "entity_name": "Account",
                    "rules": [
                        {
                            "field": "customerId",
                            "type": "cross-entity-exists",
                            "target_entity": "Customer",
                        },
                        {
                            "field": "customerId",
                            "type": "cross-entity-field-check",
                            "target_field": "creditScore",
                            "operator": "gte",
                            "expected_value": "1.5",
                        },
                    ],
                }
            ],
            "legacy_notes": None,
            "legacy_slug": "accounts",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["ok"] is False
    assert any("expected-value is incompatible" in msg for msg in payload["errors"])

    reset_session()


def test_step6_save_rejects_missing_required_cross_entity_fields():
    _seed_cross_entity_step6_session()

    response = client.post(
        "/rules/save",
        json={
            "entity_rules": [
                {
                    "entity_name": "Account",
                    "rules": [
                        {
                            "field": "customerId",
                            "type": "cross-entity-exists",
                            "target_entity": "Customer",
                        },
                        {
                            "field": "customerId",
                            "type": "cross-entity-field-compare",
                            "target_field": "approvedLimit",
                            "operator": "lte",
                        },
                    ],
                }
            ],
            "legacy_notes": None,
            "legacy_slug": "accounts",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["ok"] is False
    assert any("requires a source-field" in msg for msg in payload["errors"])

    reset_session()


def test_step6_save_rejects_cross_entity_compare_numeric_mismatches():
    _seed_cross_entity_step6_session()

    response = client.post(
        "/rules/save",
        json={
            "entity_rules": [
                {
                    "entity_name": "Account",
                    "rules": [
                        {
                            "field": "customerId",
                            "type": "cross-entity-exists",
                            "target_entity": "Customer",
                        },
                        {
                            "field": "customerId",
                            "type": "cross-entity-field-compare",
                            "target_field": "status",
                            "source_field": "accountStatus",
                            "operator": "eq",
                        },
                    ],
                }
            ],
            "legacy_notes": None,
            "legacy_slug": "accounts",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["ok"] is False
    assert any("requires numeric source-field and target-field values" in msg for msg in payload["errors"])

    reset_session()


def test_step6_save_preserves_blank_pattern_as_none():
    reset_session()

    response = client.post(
        "/rules/save",
        json={
            "entity_rules": [
                {
                    "entity_name": "Customer",
                    "rules": [
                        {
                            "field": "email",
                            "type": "pattern",
                            "value": "",
                        }
                    ],
                }
            ],
            "legacy_notes": None,
            "legacy_slug": "dda",
        },
    )

    assert response.status_code == 200
    session = get_session()
    rule = session.entity_rules[0].rules[0]
    assert rule.type == "pattern"
    assert rule.value is None

    reset_session()


def test_step6_save_rejects_incomplete_field_comparison_rule():
    reset_session()

    response = client.post(
        "/rules/save",
        json={
            "entity_rules": [
                {
                    "entity_name": "Repayment",
                    "rules": [
                        {
                            "field": "paidAmount",
                            "type": "field-comparison",
                            "operator": "<=",
                        }
                    ],
                }
            ],
            "legacy_notes": None,
            "legacy_slug": "repayments",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["ok"] is False
    assert any("compare-to-field" in msg for msg in payload["errors"])

    reset_session()


def test_step6_save_rejects_invalid_field_comparison_operator():
    reset_session()

    response = client.post(
        "/rules/save",
        json={
            "entity_rules": [
                {
                    "entity_name": "Repayment",
                    "rules": [
                        {
                            "field": "paidAmount",
                            "type": "field-comparison",
                            "operator": "!=",
                            "compare_to_field": "dueAmount",
                        }
                    ],
                }
            ],
            "legacy_notes": None,
            "legacy_slug": "repayments",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["ok"] is False
    assert any("operator must be one of" in msg for msg in payload["errors"])

    reset_session()


def test_step6_get_includes_canonical_entity_names_and_saved_target():
    session = reset_session()
    session.selected_entity_names = ["AccountResponse", "CustomerResponse"]
    session.classified_entities = [
        ClassifiedEntity(name="AccountResponse", canonical_name="Account", classification="entity"),
        ClassifiedEntity(name="CustomerResponse", canonical_name="Customer", classification="entity"),
    ]
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(
                    field="customerId",
                    type="cross-entity-exists",
                    target_entity="Customer",
                )
            ],
        )
    ]
    save_session(session)

    req = Request({"type": "http", "method": "GET", "path": "/rules", "headers": []})
    response = asyncio.run(step6_get(req))
    context = response.context

    assert context["canonical_entity_names"] == ["Account", "Customer"]
    assert context["entity_rules_data"][0]["rules"][0]["target_entity"] == "Customer"

    reset_session()


def test_step6_get_includes_saved_field_comparison_data():
    session = reset_session()
    session.selected_entity_names = ["Repayment"]
    session.classified_entities = [
        ClassifiedEntity(name="Repayment", canonical_name="Repayment", classification="entity"),
    ]
    session.entity_rules = [
        EntityRules(
            entity_name="Repayment",
            rules=[
                RuleEntry(
                    field="paidAmount",
                    type="field-comparison",
                    operator="<=",
                    compare_to_field="dueAmount",
                )
            ],
        )
    ]
    save_session(session)

    req = Request({"type": "http", "method": "GET", "path": "/rules", "headers": []})
    response = asyncio.run(step6_get(req))
    context = response.context

    saved = context["entity_rules_data"][0]["rules"][0]
    assert saved["type"] == "field-comparison"
    assert saved["operator"] == "<="
    assert saved["compare_to_field"] == "dueAmount"

    reset_session()


def test_step6_get_includes_saved_cross_entity_rule_data_for_rendering():
    session = _seed_cross_entity_step6_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(
                    field="customerId",
                    type="cross-entity-exists",
                    target_entity="Customer",
                ),
                RuleEntry(
                    field="customerId",
                    type="cross-entity-field-check",
                    target_entity="Customer",
                    target_field="status",
                    operator="eq",
                    expected_value="ACTIVE",
                    error_message="Customer must be ACTIVE.",
                ),
                RuleEntry(
                    field="customerId",
                    type="cross-entity-field-compare",
                    target_entity="Customer",
                    target_field="approvedLimit",
                    source_field="requestedAmount",
                    operator="lte",
                    error_message="Requested amount exceeds approved limit.",
                ),
                RuleEntry(
                    field="customerId",
                    type="cross-entity-field-in",
                    target_entity="Customer",
                    target_field="status",
                    values=["ACTIVE", "REVIEW"],
                    error_message="Customer status must be eligible.",
                ),
            ],
        )
    ]
    save_session(session)

    req = Request({"type": "http", "method": "GET", "path": "/rules", "headers": []})
    response = asyncio.run(step6_get(req))
    saved_rules = response.context["entity_rules_data"][0]["rules"]
    entity_fields_map = response.context["entity_fields_map"]

    assert saved_rules[1]["target_entity"] == "Customer"
    assert saved_rules[1]["target_field"] == "status"
    assert saved_rules[1]["expected_value"] == "ACTIVE"
    assert saved_rules[2]["source_field"] == "requestedAmount"
    assert saved_rules[2]["target_field"] == "approvedLimit"
    assert saved_rules[3]["values"] == ["ACTIVE", "REVIEW"]
    assert saved_rules[3]["error_message"] == "Customer status must be eligible."
    assert any(field["name"] == "status" and field["enum_values"] == ["ACTIVE", "REVIEW", "FROZEN"] for field in entity_fields_map["Customer"])
    response_body = response.body.decode()
    assert "Cross-Entity Field Compare" in response_body
    assert "Compare the current entity source field to the referenced entity target field." in response_body
    assert "{ value: 'lte', label: '<=' }" in response_body
    assert "{ value: 'neq', label: '!=' }" in response_body

    reset_session()


def test_step6_get_shows_rules_applied_from_validation_hints():
    session = _seed_step6_session()
    session.classified_entities[0].fields = [
        ClassifiedField(name="status", type="string", enum_values=["ACTIVE", "SUSPENDED"]),
        ClassifiedField(name="accountNumber", type="string", max_length=12),
    ]
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(field="accountNumber", type="max-length", value="14"),
            ],
            file_path="rules/account-business-rules.yaml",
        )
    ]
    save_session(session)

    response = client.get("/rules")

    assert response.status_code == 200
    refreshed_rules = get_session().entity_rules[0].rules
    assert any(rule.field == "accountNumber" and rule.type == "max-length" for rule in refreshed_rules)
    assert any(
        rule.field == "status" and rule.type == "allowed-values" and rule.values == ["ACTIVE", "SUSPENDED"]
        for rule in refreshed_rules
    )
    assert not any(rule.field == "accountNumber" and rule.type == "max-length" and rule.value == "12" for rule in refreshed_rules)
    assert "allowed-values" in response.text
    assert "max-length" in response.text
    assert "accountNumber" in response.text


def test_step6_noop_get_does_not_save_for_marker_only_auto_merge(monkeypatch):
    session = _seed_step6_session()
    session.capabilities.knowledge_assist_enabled = False
    session.ks_active = False
    session.classified_entities[0].fields = [
        ClassifiedField(name="status", type="string", enum_values=["ACTIVE", "SUSPENDED"]),
    ]
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(
                    field="status",
                    type="allowed-values",
                    values=["ACTIVE", "SUSPENDED"],
                    applied_by="openapi-spec",
                )
            ],
            file_path="rules/account-business-rules.yaml",
        )
    ]
    session.auto_rule_merge_completed_entities = []
    save_session(session)
    save_calls = []

    def spy_save_current_session(request, saved_session=None):
        save_calls.append(saved_session)

    monkeypatch.setattr("app.routes.rules.save_current_session", spy_save_current_session)

    response = client.get("/rules")

    assert response.status_code == 200
    assert save_calls == []
    assert "allowed-values" in response.text
    assert "ACTIVE" in response.text
    assert get_session().auto_rule_merge_completed_entities == []


def test_step6_get_renders_rule_provenance_badges():
    session = _seed_step6_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(
                    field="status",
                    type="not-null",
                    suggestion_id="v-status",
                    suggestion_type="validation",
                    applied_by="knowledge_assist",
                    applied_at="2026-05-03T00:00:00+00:00",
                    generated_by_ka=True,
                    ka_review_status="accepted",
                ),
                RuleEntry(field="accountNumber", type="max-length", value="14", applied_by="manual"),
            ],
            file_path="rules/account-business-rules.yaml",
        )
    ]
    save_session(session)

    response = client.get("/rules")

    assert response.status_code == 200
    assert "KA-applied" in response.text
    assert "ka-category-generated ka-taxonomy-change" in response.text
    assert "v-status" in response.text
    assert "Manual / imported" in response.text
    assert "ka-category-satisfied ka-taxonomy-satisfied" in response.text
    assert "ruleProvenanceBadge" in response.text
    assert "removeRuleRow(this)" in response.text
    assert "removeKaAppliedRule(this)" in response.text


def test_step6_rule_delete_handler_removes_full_rule_row() -> None:
    _seed_step6_session()
    response = client.get("/rules")

    assert response.status_code == 200
    assert "const row = buttonEl.closest('.rule-row');" in response.text
    assert "row?.remove();" in response.text
    assert "buttonEl.parentElement.remove();" not in response.text


def test_step6_save_persists_removal_of_ka_and_manual_rules() -> None:
    session = _seed_step6_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(
                    field="email",
                    type="pattern",
                    value=".+@.+",
                    suggestion_id="v-email",
                    suggestion_type="validation",
                    applied_by="knowledge_assist",
                    applied_at="2026-05-03T00:00:00+00:00",
                    generated_by_ka=True,
                    ka_review_status="accepted",
                ),
                RuleEntry(field="kycStatus", type="allowed-values", values=["VERIFIED"], applied_by="manual"),
            ],
        )
    ]
    save_session(session)

    response = client.post(
        "/rules/save",
        json={
            "entity_rules": [
                {
                    "entity_name": "Account",
                    "rules": [],
                }
            ],
            "legacy_notes": None,
            "legacy_slug": "",
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert get_session().entity_rules[0].rules == []


def test_step6_explicit_remove_deletes_unchanged_ka_validation_rule() -> None:
    session = _seed_step6_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(
                    field="accountName",
                    type="max-length",
                    value="14",
                    suggestion_id="v-name",
                    suggestion_type="validation",
                    applied_by="knowledge_assist",
                    generated_by_ka=True,
                    ka_review_status="accepted",
                )
            ],
        )
    ]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="v-name",
            type="validation",
            status="accepted",
            manifest_path="entities.Account.fields.accountName.validations.max-length",
            reviewed_at="2026-05-03T12:00:00+00:00",
            review_context={"constraint_fingerprint": "max=14"},
        )
    ]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="entities.Account.fields.accountName.validations.max-length",
            suggestion_id="v-name",
            provenance="ai-accepted",
        )
    ]
    save_session(session)

    response = client.post(
        "/rules/ka/remove-validation-rule",
        json={
            "suggestion_id": "v-name",
            "entity": "Account",
            "field": "accountName",
            "type": "max-length",
        },
    )

    assert response.status_code == 200
    assert response.json()["removed_count"] == 1
    assert get_session().entity_rules[0].rules == []
    assert get_session().ks_workspace_state.evidence_links == []


def test_step6_explicit_remove_deletes_unchanged_ka_not_null_rule_with_boolean_fingerprint() -> None:
    session = _seed_step6_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(
                    field="accountName",
                    type="not-null",
                    suggestion_id="v-name-required",
                    suggestion_type="validation",
                    applied_by="knowledge_assist",
                    generated_by_ka=True,
                    ka_review_status="accepted",
                )
            ],
        )
    ]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="v-name-required",
            type="validation",
            status="accepted",
            manifest_path="entities.Account.fields.accountName.validations.not-null",
            reviewed_at="2026-05-03T12:00:00+00:00",
            review_context={"constraint_fingerprint": "not_null=True"},
        )
    ]
    save_session(session)

    response = client.post(
        "/rules/ka/remove-validation-rule",
        json={
            "suggestion_id": "v-name-required",
            "entity": "Account",
            "field": "accountName",
            "type": "not-null",
        },
    )

    assert response.status_code == 200
    assert response.json()["removed_count"] == 1
    assert get_session().entity_rules[0].rules == []


def test_step6_explicit_remove_keeps_edited_ka_validation_rule() -> None:
    session = _seed_step6_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(
                    field="accountName",
                    type="max-length",
                    value="18",
                    suggestion_id="v-name",
                    suggestion_type="validation",
                    applied_by="knowledge_assist",
                    generated_by_ka=True,
                    ka_review_status="accepted",
                )
            ],
        )
    ]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="v-name",
            type="validation",
            status="accepted",
            manifest_path="entities.Account.fields.accountName.validations.max-length",
            reviewed_at="2026-05-03T12:00:00+00:00",
            review_context={"constraint_fingerprint": "max=14"},
        )
    ]
    save_session(session)

    response = client.post(
        "/rules/ka/remove-validation-rule",
        json={
            "suggestion_id": "v-name",
            "entity": "Account",
            "field": "accountName",
            "type": "max-length",
        },
    )

    assert response.status_code == 409
    rule = get_session().entity_rules[0].rules[0]
    assert rule.value == "18"
    assert rule.ka_review_status == "edited"


def test_step6_explicit_remove_keeps_field_type_edited_ka_validation_rule() -> None:
    session = _seed_step6_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(
                    field="creditLimit",
                    type="range",
                    value="0",
                    values=["5000"],
                    suggestion_id="v-name",
                    suggestion_type="validation",
                    applied_by="knowledge_assist",
                    generated_by_ka=True,
                    ka_review_status="accepted",
                )
            ],
        )
    ]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="v-name",
            type="validation",
            status="accepted",
            manifest_path="entities.Account.fields.accountName.validations.max-length",
            reviewed_at="2026-05-03T12:00:00+00:00",
            review_context={"constraint_fingerprint": "max=14"},
        )
    ]
    save_session(session)

    response = client.post(
        "/rules/ka/remove-validation-rule",
        json={
            "suggestion_id": "v-name",
            "entity": "Account",
            "field": "creditLimit",
            "type": "range",
        },
    )

    assert response.status_code == 409
    rule = get_session().entity_rules[0].rules[0]
    assert rule.field == "creditLimit"
    assert rule.type == "range"
    assert rule.ka_review_status == "edited"


def test_step6_explicit_remove_never_removes_manual_or_spec_rules() -> None:
    session = _seed_step6_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(field="accountName", type="max-length", value="14", applied_by="manual"),
                RuleEntry(field="accountNumber", type="not-null", applied_by="openapi-spec"),
            ],
        )
    ]
    save_session(session)

    response = client.post(
        "/rules/ka/remove-validation-rule",
        json={
            "suggestion_id": "v-name",
            "entity": "Account",
            "field": "accountName",
            "type": "max-length",
        },
    )

    assert response.status_code == 404
    assert len(get_session().entity_rules[0].rules) == 2


def test_step6_save_classifies_edited_ka_validation_rule() -> None:
    session = _seed_step6_session()
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="v-name",
            type="validation",
            status="accepted",
            manifest_path="entities.Account.fields.accountName.validations.max-length",
            reviewed_at="2026-05-03T12:00:00+00:00",
            review_context={"constraint_fingerprint": "max=14"},
        )
    ]
    save_session(session)

    response = client.post(
        "/rules/save",
        json={
            "entity_rules": [
                {
                    "entity_name": "Account",
                    "rules": [
                        {
                            "field": "accountName",
                            "type": "max-length",
                            "value": "18",
                            "suggestion_id": "v-name",
                            "suggestion_type": "validation",
                            "applied_by": "knowledge_assist",
                            "generated_by_ka": True,
                            "ka_review_status": "accepted",
                        }
                    ],
                }
            ],
            "legacy_notes": None,
            "legacy_slug": "",
        },
    )

    assert response.status_code == 200
    rule = get_session().entity_rules[0].rules[0]
    assert rule.value == "18"
    assert rule.ka_review_status == "edited"


def test_step6_save_classifies_field_type_edited_ka_validation_rule() -> None:
    session = _seed_step6_session()
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="v-name",
            type="validation",
            status="accepted",
            manifest_path="entities.Account.fields.accountName.validations.max-length",
            reviewed_at="2026-05-03T12:00:00+00:00",
            review_context={"constraint_fingerprint": "max=14"},
        )
    ]
    save_session(session)

    response = client.post(
        "/rules/save",
        json={
            "entity_rules": [
                {
                    "entity_name": "Account",
                    "rules": [
                        {
                            "field": "creditLimit",
                            "type": "range",
                            "value": "0",
                            "values": ["5000"],
                            "suggestion_id": "v-name",
                            "suggestion_type": "validation",
                            "applied_by": "knowledge_assist",
                            "generated_by_ka": True,
                            "ka_review_status": "accepted",
                        }
                    ],
                }
            ],
            "legacy_notes": None,
            "legacy_slug": "",
        },
    )

    assert response.status_code == 200
    rule = get_session().entity_rules[0].rules[0]
    assert rule.field == "creditLimit"
    assert rule.type == "range"
    assert rule.ka_review_status == "edited"


def test_step6_get_does_not_resurrect_deleted_or_edited_auto_rules():
    session = _seed_step6_session()
    session.classified_entities[0].fields = [
        ClassifiedField(name="status", type="string", enum_values=["ACTIVE", "SUSPENDED"]),
        ClassifiedField(name="accountNumber", type="string", max_length=12),
    ]
    save_session(session)
    save_response = client.post(
        "/rules/save",
        json={
            "entity_rules": [
                {
                    "entity_name": "Account",
                    "rules": [
                        {"field": "accountNumber", "type": "max-length", "value": "14"},
                    ],
                }
            ],
            "legacy_notes": "",
            "legacy_slug": "",
        },
    )

    assert save_response.status_code == 200
    response = client.get("/rules")

    assert response.status_code == 200
    refreshed_rules = get_session().entity_rules[0].rules
    assert any(rule.field == "accountNumber" and rule.type == "max-length" and rule.value == "14" for rule in refreshed_rules)
    assert not any(rule.field == "accountNumber" and rule.type == "max-length" and rule.value == "12" for rule in refreshed_rules)
    assert not any(rule.field == "status" and rule.type == "allowed-values" for rule in refreshed_rules)


def test_step6_save_marks_only_submitted_entities_merge_completed():
    session = _seed_step6_session()
    session.selected_entity_names = ["AccountResponse"]
    session.classified_entities = [
        ClassifiedEntity(
            name="AccountResponse",
            canonical_name="Account",
            classification="entity",
            fields=[ClassifiedField(name="accountNumber", type="string", max_length=14)],
        ),
        ClassifiedEntity(
            name="CustomerResponse",
            canonical_name="Customer",
            classification="entity",
            fields=[ClassifiedField(name="status", type="string", enum_values=["ACTIVE", "SUSPENDED"])],
        ),
    ]
    save_session(session)

    save_response = client.post(
        "/rules/save",
        json={
            "entity_rules": [
                {
                    "entity_name": "Account",
                    "rules": [
                        {"field": "accountNumber", "type": "max-length", "value": "14"},
                    ],
                }
            ],
            "legacy_notes": "",
            "legacy_slug": "",
        },
    )
    session = get_session()
    session.selected_entity_names = ["CustomerResponse"]
    save_session(session)

    response = client.get("/rules")

    assert save_response.status_code == 200
    assert response.status_code == 200
    refreshed = get_session()
    assert refreshed.auto_rule_merge_completed_entities == ["Account", "Customer"]
    customer_rules = next(entity_rules for entity_rules in refreshed.entity_rules if entity_rules.entity_name == "Customer")
    assert any(
        rule.field == "status" and rule.type == "allowed-values" and rule.values == ["ACTIVE", "SUSPENDED"]
        for rule in customer_rules.rules
    )


def test_step6_save_allows_hidden_generated_rules_to_regenerate_after_reselect():
    session = _seed_step6_session()
    session.selected_entity_names = ["AccountResponse", "CustomerResponse"]
    session.classified_entities = [
        ClassifiedEntity(
            name="AccountResponse",
            canonical_name="Account",
            classification="entity",
            fields=[ClassifiedField(name="accountNumber", type="string", max_length=14)],
        ),
        ClassifiedEntity(
            name="CustomerResponse",
            canonical_name="Customer",
            classification="entity",
            fields=[ClassifiedField(name="status", type="string", enum_values=["ACTIVE", "SUSPENDED"])],
        ),
    ]
    save_session(session)

    first_response = client.get("/rules")
    session = get_session()
    session.selected_entity_names = ["AccountResponse"]
    save_session(session)
    save_response = client.post(
        "/rules/save",
        json={
            "entity_rules": [
                {
                    "entity_name": "Account",
                    "rules": [
                        {"field": "accountNumber", "type": "max-length", "value": "14"},
                    ],
                }
            ],
            "legacy_notes": "",
            "legacy_slug": "",
        },
    )
    session = get_session()
    session.selected_entity_names = ["CustomerResponse"]
    save_session(session)

    second_response = client.get("/rules")

    assert first_response.status_code == 200
    assert save_response.status_code == 200
    assert second_response.status_code == 200
    refreshed = get_session()
    assert refreshed.auto_rule_merge_completed_entities == ["Account", "Customer"]
    customer_rules = next(entity_rules for entity_rules in refreshed.entity_rules if entity_rules.entity_name == "Customer")
    assert any(
        rule.field == "status" and rule.type == "allowed-values" and rule.values == ["ACTIVE", "SUSPENDED"]
        for rule in customer_rules.rules
    )


def test_step6_get_merges_auto_rules_from_same_canonical_selected_schemas():
    session = _seed_step6_session()
    session.selected_entity_names = ["AccountResponse", "CreateAccountRequest"]
    session.classified_entities = [
        ClassifiedEntity(
            name="AccountResponse",
            canonical_name="Account",
            classification="entity",
            fields=[ClassifiedField(name="status", type="string", enum_values=["ACTIVE", "SUSPENDED"])],
        ),
        ClassifiedEntity(
            name="CreateAccountRequest",
            canonical_name="Account",
            classification="entity",
            fields=[ClassifiedField(name="accountNumber", type="string", max_length=14)],
        ),
    ]
    save_session(session)

    response = client.get("/rules")

    assert response.status_code == 200
    account_rules = next(entity_rules for entity_rules in get_session().entity_rules if entity_rules.entity_name == "Account")
    assert any(
        rule.field == "status" and rule.type == "allowed-values" and rule.values == ["ACTIVE", "SUSPENDED"]
        for rule in account_rules.rules
    )
    assert any(
        rule.field == "accountNumber" and rule.type == "max-length" and rule.value == "14"
        for rule in account_rules.rules
    )


def test_step6_edge_contract_only_project_shows_info_instead_of_entity_warning():
    session = reset_session()
    session.app_archetype = "crud"
    session.selected_entity_names = []
    session.classified_entities = []
    session.upstream_interfaces = [
        UpstreamInterface(
            name="account-xml-feed",
            type="xml-xsd",
            xsd_path="contracts/account.xsd",
            root_element="acct:Account",
        )
    ]
    save_session(session)

    response = client.get("/rules")

    assert response.status_code == 200
    assert "No CRUD entities are loaded. This edge-contract-only project can use legacy notes below or skip to Review." in response.text
    assert "No entities selected yet" not in response.text

    reset_session()


def test_step6_mixed_edge_contract_and_unselected_crud_entity_keeps_selection_warning():
    session = reset_session()
    session.app_archetype = "crud"
    session.selected_entity_names = []
    session.classified_entities = [
        ClassifiedEntity(
            name="AccountResponse",
            canonical_name="Account",
            classification="entity",
            fields=[ClassifiedField(name="accountId", type="string")],
        )
    ]
    session.upstream_interfaces = [
        UpstreamInterface(
            name="account-xml-feed",
            type="xml-xsd",
            xsd_path="contracts/account.xsd",
            root_element="acct:Account",
        )
    ]
    save_session(session)

    response = client.get("/rules")

    assert response.status_code == 200
    assert "No entities selected yet" in response.text
    assert "No CRUD entities are loaded." not in response.text

    reset_session()


def test_step6_get_renders_grouped_crud_conflict_advisories(monkeypatch):
    _seed_step6_session()

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            assert project_id == "studio-ks-rules"
            if scope != "fields":
                return {"suggestions": [], "suggestion_count": 0}
            assert entity == "Account"
            return {
                "suggestions": [
                    {
                        "suggestion_id": "s-1",
                        "field_name": "CREDIT_LIMIT",
                        "status": "pending",
                        "source_count": 2,
                        "consistency_score": 0.67,
                        "conflict_hint": "Spec says integer, but current field guidance leans decimal.",
                    }
                ]
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/rules")

    assert response.status_code == 200
    assert "Issues &amp; Conflicts" in response.text
    assert "Spec says integer, but current field guidance leans decimal." in response.text
    assert "creditLimit" in response.text
    assert "Conflicts Summary" in response.text
    assert 'data-shell-rail-default="expanded"' in response.text


def test_step6_conflict_advisories_ignore_non_current_fields(monkeypatch):
    _seed_step6_session()

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            if scope != "fields":
                return {"suggestions": [], "suggestion_count": 0}
            return {
                "suggestions": [
                    {
                        "suggestion_id": "s-ghost",
                        "field_name": "UNKNOWN_STATUS",
                        "conflict_hint": "Should not be actionable in Step 6.",
                    }
                ]
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/rules")

    assert response.status_code == 200
    assert "Should not be actionable in Step 6." not in response.text
    assert "No current advisory issues. Step 6 advisories appear" in response.text
    assert "advisory-issues-empty" not in response.text


def test_step6_get_shows_degraded_warning_without_breaking_rules_authoring(monkeypatch):
    _seed_step6_session()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise KSUnavailableError("mock KS unavailable")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/rules")

    assert response.status_code == 200
    assert "Knowledge Server advisory fetch is unavailable" not in response.text
    assert "No current advisory issues. Step 6 advisories appear when Knowledge Assist finds conflict hints for fields in the current CRUD model." in response.text
    assert "advisory-issues-empty" not in response.text
    assert "Rule suggestion badges appear in the main Business Rules header" not in response.text
    assert "Business Rules" in response.text
    assert 'data-shell-rail-default="collapsed"' in response.text


def test_step6_get_shows_empty_advisory_state_when_no_conflict_hints(monkeypatch):
    _seed_step6_session()

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            if scope != "fields":
                return {"suggestions": [], "suggestion_count": 0}
            return {
                "suggestions": [
                    {
                        "suggestion_id": "s-2",
                        "field_name": "account_name",
                        "status": "accepted",
                        "source_count": 3,
                        "consistency_score": 0.91,
                        "conflict_hint": "",
                    }
                ]
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/rules")

    assert response.status_code == 200
    assert "No current advisory issues. Step 6 advisories appear when Knowledge Assist finds conflict hints for fields in the current CRUD model." in response.text
    assert "Conflicts Summary" in response.text
    assert "advisory-issues-empty" not in response.text
    assert 'data-shell-rail-default="collapsed"' in response.text


def test_step6_dormant_workspace_does_not_reenable_knowledge_assist(monkeypatch):
    session = _seed_step6_session()
    session.capabilities.knowledge_assist_enabled = False
    session.ks_active = False
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="entities.Account.fields.credit_limit",
            suggestion_id="s-1",
            provenance="ai-accepted",
        )
    ]
    save_session(session)

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when Knowledge Assist is off")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/rules")
    refreshed = get_session()

    assert response.status_code == 200
    assert refreshed.capabilities.knowledge_assist_enabled is False
    assert refreshed.ks_active is False
    assert refreshed.ks_workspace_state.evidence_links[0].suggestion_id == "s-1"
    assert "No current advisory issues from Knowledge Assist field guidance." not in response.text
    assert "Open Knowledge Workspace" not in response.text
    assert "data-suggestion-drawer" not in response.text
    assert 'data-shell-rail-default="collapsed"' in response.text


def test_step6_rule_suggestion_badge_hidden_when_knowledge_assist_off(monkeypatch):
    session = _seed_step6_session()
    session.capabilities.knowledge_assist_enabled = False
    session.ks_active = False
    save_session(session)

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when Knowledge Assist is off")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/rules")

    assert response.status_code == 200
    assert "rule suggestions" not in response.text
    assert "data-suggestion-drawer-open" not in response.text


def test_step6_renders_rule_suggestion_badge_when_suggestions_exist(monkeypatch):
    _seed_step6_session()

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            if scope == "fields":
                return {"suggestions": [], "suggestion_count": 0}
            return {
                "suggestions": [{"suggestion_id": f"{scope}-1", "field": "status"}],
                "suggestion_count": 1,
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/rules")

    assert response.status_code == 200
    assert "Account · 2 rule suggestions" in response.text
    assert 'data-suggestion-drawer-url="/rules/ks/drawer?scope=rules&amp;entity=Account"' in response.text


def test_step6_rule_badge_batch_keeps_get_context_count_bounded(monkeypatch):
    context_entries = 0

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            if scope == "fields":
                return {"suggestions": [], "suggestion_count": 0}
            return {
                "suggestions": [{"suggestion_id": f"{scope}-{entity}"}],
                "suggestion_count": 1,
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        nonlocal context_entries
        context_entries += 1
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    _seed_multi_entity_step6_session(count=1)
    response = client.get("/rules")
    assert response.status_code == 200
    one_entity_contexts = context_entries

    context_entries = 0
    _seed_multi_entity_step6_session(count=5)
    response = client.get("/rules")
    assert response.status_code == 200
    many_entity_contexts = context_entries

    assert one_entity_contexts == many_entity_contexts == 2


def test_step6_rule_badge_batch_matches_single_badge_contract(monkeypatch):
    _seed_step6_session()

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            if scope == "rules":
                count = 1
            elif scope == "cross_entity_rules":
                count = 2
            else:
                count = 0
            return {
                "suggestions": [{"suggestion_id": f"{scope}-{index}"} for index in range(count)],
                "suggestion_count": count,
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)
    session = get_session()

    single_badge = assist_service.get_rule_suggestion_badge(session, entity="Account")
    batch_badges = assist_service.get_rule_suggestion_badges_batch(session, entities=["Account"])

    assert batch_badges == [single_badge]
    assert batch_badges[0].scope == "rules"
    assert batch_badges[0].label == "3 rule suggestions"
    assert batch_badges[0].count == 3
    assert batch_badges[0].entity == "Account"
    assert batch_badges[0].context == {"scopes": ["rules", "cross_entity_rules"]}
    assert batch_badges[0].drawer_url == "/rules/ks/drawer?scope=rules&entity=Account"


def test_step6_rule_badge_batch_isolates_per_scope_errors(monkeypatch):
    _seed_multi_entity_step6_session(count=2)

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            if scope == "fields":
                return {"suggestions": [], "suggestion_count": 0}
            if scope == "rules" and entity == "Entity1":
                raise KSCallError("suggest_manifest_candidates", "rule boom")
            if scope == "cross_entity_rules" and entity == "Entity2":
                return {"suggestions": [], "suggestion_count": 0}
            return {
                "suggestions": [{"suggestion_id": f"{scope}-{entity}"}],
                "suggestion_count": 1,
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/rules")

    assert response.status_code == 200
    badges = assist_service.get_rule_suggestion_badges_batch(
        get_session(),
        entities=["Entity1", "Entity2"],
    )
    assert [(badge.entity, badge.count, badge.label) for badge in badges] == [
        ("Entity1", 1, "1 rule suggestion"),
        ("Entity2", 1, "1 rule suggestion"),
    ]


def test_step6_rule_badge_batch_skips_non_crud_without_spawning(monkeypatch):
    spawn_count = 0

    @contextmanager
    def fake_ks_client(**kwargs):
        nonlocal spawn_count
        spawn_count += 1
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    for app_archetype in ("passthrough-router", "kafka-integration"):
        session = _seed_step6_session(app_archetype=app_archetype)
        session.capabilities.knowledge_assist_enabled = True
        save_session(session)

        badges = assist_service.get_rule_suggestion_badges_batch(session, entities=["Account"])

        assert badges == []
    assert spawn_count == 0


def test_step6_rule_drawer_route_returns_rule_rows(monkeypatch):
    _seed_step6_session()

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            if scope == "cross_entity_rules":
                return {"suggestions": [], "suggestion_count": 0}
            assert scope == "rules"
            assert entity == "Account"
            return {
                "suggestions": [
                    {
                        "suggestion_id": "r-1",
                        "rule_type": "allowed-values",
                        "field": "status",
                        "rationale": "Status values are repeated in the corpus.",
                    }
                ]
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/rules/ks/drawer?scope=rules&entity=Account")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["scope"] == "rules"
    assert payload["empty"] is False
    assert payload["scopes"][0]["rows"][0]["title"] == "allowed-values on status"
    assert payload["scopes"][0]["rows"][0]["summary"] == "Status values are repeated in the corpus."


def test_step6_empty_rule_drawer_surfaces_ks_warning_context(monkeypatch):
    _seed_step6_session()

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            return {
                "suggestions": [],
                "suggestion_count": 0,
                "warnings": [f"{scope} scope found no matching field catalog evidence."],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/rules/ks/drawer?scope=rules&entity=Account")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["empty"] is True
    assert payload["scopes"] == []
    assert "rules scope found no matching field catalog evidence." in payload["warnings"]
    assert "cross_entity_rules scope found no matching field catalog evidence." in payload["warnings"]
    assert get_session().entity_rules == []


def test_step6_combined_rule_drawer_route_returns_cross_entity_only_rows(monkeypatch):
    _seed_step6_session()

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            if scope == "rules":
                return {"suggestions": [], "suggestion_count": 0}
            assert scope == "cross_entity_rules"
            return {
                "suggestions": [
                    {
                        "suggestion_id": "x-1",
                        "rule_type": "cross-entity-field-check",
                        "field": "customerId",
                    }
                ],
                "suggestion_count": 1,
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/rules/ks/drawer?scope=rules&entity=Account")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["scope"] == "rules"
    assert payload["empty"] is False
    assert payload["scopes"][0]["scope"] == "cross_entity_rules"
    assert payload["scopes"][0]["rows"][0]["title"] == "cross-entity-field-check on customerId"


def test_step6_cross_entity_rule_drawer_route_returns_rows(monkeypatch):
    _seed_step6_session()

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            assert scope == "cross_entity_rules"
            return {
                "suggestions": [
                    {
                        "suggestion_id": "x-1",
                        "rule_type": "cross-entity-field-check",
                        "field": "customerId",
                    }
                ]
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/rules/ks/drawer?scope=cross_entity_rules&entity=Account")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["scope"] == "cross_entity_rules"
    assert payload["scopes"][0]["rows"][0]["title"] == "cross-entity-field-check on customerId"


def test_step6_rule_suggestion_review_rejects_ka_off_without_ks_call(monkeypatch):
    session = _seed_step6_session()
    session.capabilities.knowledge_assist_enabled = False
    save_session(session)

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when Knowledge Assist is off")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/rules/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "r-1",
                    "suggestion_type": "rule",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {"rule_type": "allowed_values", "field": "status", "values": ["ACTIVE"]},
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "Knowledge Assist is off" in response.json()["errors"][0]


def test_step6_rule_suggestion_review_applies_allowed_values(monkeypatch):
    _seed_step6_session()
    submitted: list[list[dict]] = []

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            submitted.append(decisions)
            return {"success": True, "outcomes": [{"suggestion_id": "r-1", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/rules/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "r-1",
                    "suggestion_type": "rule",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {
                        "rule_type": "allowed_values",
                        "field": "status",
                        "values": ["ACTIVE", "SUSPENDED"],
                    },
                }
            ]
        },
    )
    session = get_session()

    assert response.status_code == 200
    assert response.json()["applied_count"] == 1
    assert submitted == [[{"suggestion_id": "r-1", "status": "accepted"}]]
    applied = session.entity_rules[0].rules[0]
    assert applied.type == "allowed-values"
    assert applied.field == "status"
    assert applied.values == ["ACTIVE", "SUSPENDED"]
    assert applied.suggestion_id == "r-1"
    assert applied.suggestion_type == "rule"
    assert applied.applied_by == "knowledge_assist"
    assert applied.generated_by_ka is True
    assert applied.ka_review_status == "accepted"
    assert applied.applied_at
    assert session.ks_workspace_state.suggestion_review_state.accepted_ids == ["r-1"]
    assert session.ks_workspace_state.evidence_links == [
        KSEvidenceLink(
            manifest_path="rules.Account.r-1",
            suggestion_id="r-1",
            provenance="ai-accepted",
        )
    ]
    assert session.ks_workspace_state.review_history[0].type == "rule"


def test_step6_rule_reject_marks_existing_ka_rule_without_removing(monkeypatch):
    session = _seed_step6_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(
                    field="status",
                    type="allowed-values",
                    values=["ACTIVE"],
                    suggestion_id="r-existing",
                    suggestion_type="rule",
                    applied_by="knowledge_assist",
                    applied_at="2026-05-03T00:00:00+00:00",
                    generated_by_ka=True,
                    ka_review_status="accepted",
                )
            ],
            file_path="rules/account-business-rules.yaml",
        )
    ]
    save_session(session)

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {"success": True, "outcomes": [{"suggestion_id": "r-existing", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/rules/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "r-existing",
                    "suggestion_type": "rule",
                    "status": "rejected",
                    "entity": "Account",
                    "payload": {"rule_type": "allowed_values", "field": "status", "values": ["ACTIVE"]},
                }
            ]
        },
    )
    session = get_session()

    assert response.status_code == 200
    payload = response.json()
    assert payload["applied_count"] == 0
    assert (
        "r-existing: Reject records review only; existing generated rule remains until manually removed."
        in payload["warnings"]
    )
    assert len(session.entity_rules[0].rules) == 1
    rule = session.entity_rules[0].rules[0]
    assert rule.generated_by_ka is True
    assert rule.suggestion_id == "r-existing"
    assert rule.ka_review_status == "rejected"


def test_step6_rule_suggestion_review_maps_legacy_field_to_current_field(monkeypatch):
    _seed_step6_session()

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {"success": True, "outcomes": [{"suggestion_id": "r-status", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)
    session = get_session()
    session.classified_entities[0].fields.append(ClassifiedField(name="accountStatus", type="string"))
    save_session(session)

    response = client.post(
        "/rules/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "r-status",
                    "suggestion_type": "rule",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {
                        "rule_type": "allowed_values",
                        "field": "ACCOUNT_STATUS",
                        "values": ["ACTIVE", "DORMANT"],
                    },
                }
            ]
        },
    )

    assert response.status_code == 200
    rule = get_session().entity_rules[0].rules[0]
    assert rule.field == "accountStatus"
    assert rule.values == ["ACTIVE", "DORMANT"]
    assert get_session().ks_workspace_state.review_history[0].manifest_path == "rules.Account.r-status"


def test_step6_rule_suggestion_review_applies_range_and_pattern(monkeypatch):
    _seed_step6_session()

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {
                "success": True,
                "outcomes": [
                    {"suggestion_id": "r-range", "success": True},
                    {"suggestion_id": "r-pattern", "success": True},
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/rules/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "r-range",
                    "suggestion_type": "rule",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {"rule_type": "range", "field": "balance", "constraint": {"min": "0", "max": "999"}},
                },
                {
                    "suggestion_id": "r-pattern",
                    "suggestion_type": "rule",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {"rule_type": "pattern", "field": "accountNumber", "pattern": "^[0-9]{10}$"},
                },
            ]
        },
    )

    assert response.status_code == 200
    rules = get_session().entity_rules[0].rules
    assert rules[0].type == "range"
    assert rules[0].value == "0"
    assert rules[0].values == ["999"]
    assert rules[1].type == "pattern"
    assert rules[1].value == "^[0-9]{10}$"


def test_step6_rule_suggestion_review_sends_and_applies_edited_payload(monkeypatch):
    _seed_step6_session()
    submitted: list[list[dict]] = []

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            submitted.append(decisions)
            return {"success": True, "outcomes": [{"suggestion_id": "r-2", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/rules/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "r-2",
                    "suggestion_type": "rule",
                    "status": "edited",
                    "entity": "Account",
                    "payload": {"rule_type": "allowed_values", "field": "status", "values": ["A"]},
                    "edited_payload": {"rule_type": "allowed_values", "field": "status", "values": ["ACTIVE"]},
                }
            ]
        },
    )

    assert response.status_code == 200
    assert submitted[0][0]["edited_payload"] == {
        "rule_type": "allowed_values",
        "field": "status",
        "values": ["ACTIVE"],
    }
    rule = get_session().entity_rules[0].rules[0]
    assert rule.values == ["ACTIVE"]
    assert get_session().ks_workspace_state.review_history[0].edited_payload["values"] == ["ACTIVE"]


def test_step6_rule_suggestion_review_records_rejected_without_applying(monkeypatch):
    _seed_step6_session()

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {"success": True, "outcomes": [{"suggestion_id": "r-reject", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/rules/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "r-reject",
                    "suggestion_type": "rule",
                    "status": "rejected",
                    "entity": "Account",
                    "payload": {"rule_type": "not_null", "field": "status"},
                }
            ]
        },
    )
    session = get_session()

    assert response.status_code == 200
    assert response.json()["applied_count"] == 0
    assert session.entity_rules == []
    assert session.ks_workspace_state.suggestion_review_state.rejected_ids == ["r-reject"]
    assert session.ks_workspace_state.evidence_links == []


def test_step6_rule_suggestion_review_avoids_duplicate_rules(monkeypatch):
    session = _seed_step6_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[RuleEntry(field="status", type="not-null")],
            file_path="rules/account-business-rules.yaml",
        )
    ]
    save_session(session)

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {"success": True, "outcomes": [{"suggestion_id": "r-dup", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/rules/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "r-dup",
                    "suggestion_type": "rule",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {"rule_type": "not_null", "field": "status"},
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["applied_count"] == 0
    assert len(get_session().entity_rules[0].rules) == 1
    assert "matching rule already exists" in response.json()["warnings"][0]
    assert get_session().ks_workspace_state.evidence_links == [
        KSEvidenceLink(
            manifest_path="rules.Account.r-dup",
            suggestion_id="r-dup",
            provenance="ai-accepted",
        )
    ]
    rule = get_session().entity_rules[0].rules[0]
    assert rule.generated_by_ka is False
    assert rule.suggestion_id is None


def test_step6_rule_duplicate_accept_does_not_relabel_manual_rule(monkeypatch):
    session = _seed_step6_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[RuleEntry(field="status", type="not-null", applied_by="manual")],
            file_path="rules/account-business-rules.yaml",
        )
    ]
    save_session(session)

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {"success": True, "outcomes": [{"suggestion_id": "r-manual-dup", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/rules/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "r-manual-dup",
                    "suggestion_type": "rule",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {"rule_type": "not_null", "field": "status"},
                }
            ]
        },
    )
    rule = get_session().entity_rules[0].rules[0]

    assert response.status_code == 200
    assert response.json()["applied_count"] == 0
    assert rule.generated_by_ka is False
    assert rule.suggestion_id is None
    assert rule.applied_by == "manual"


def test_step6_rule_suggestion_review_applies_only_successful_partial_outcomes(monkeypatch):
    _seed_step6_session()

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {
                "success": False,
                "outcomes": [
                    {"suggestion_id": "r-ok", "success": True},
                    {"suggestion_id": "r-fail", "success": False},
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/rules/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "r-ok",
                    "suggestion_type": "rule",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {"rule_type": "not_null", "field": "status"},
                },
                {
                    "suggestion_id": "r-fail",
                    "suggestion_type": "rule",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {"rule_type": "not_null", "field": "balance"},
                },
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["partial_failure"] is True
    assert payload["saved_count"] == 1
    assert payload["failed_count"] == 1
    assert [rule.field for rule in get_session().entity_rules[0].rules] == ["status"]


def test_step6_rule_suggestion_review_rejects_unsupported_suggestion_type(monkeypatch):
    _seed_step6_session()

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called for invalid payloads")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/rules/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "m-1",
                    "suggestion_type": "mapping",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {"field": "status"},
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "unsupported suggestion_type" in response.json()["errors"][0]


def test_step6_cross_entity_review_applies_fk_reference(monkeypatch):
    _seed_step6_session()

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {"success": True, "outcomes": [{"suggestion_id": "x-fk", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/rules/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "x-fk",
                    "suggestion_type": "cross_entity_rule",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {
                        "rule_type": "cross-entity-exists",
                        "source_field": "customerId",
                        "target_entity": "Customer",
                    },
                }
            ]
        },
    )

    assert response.status_code == 200
    rule = get_session().entity_rules[0].rules[0]
    assert rule.type == "cross-entity-exists"
    assert rule.field == "customerId"
    assert rule.target_entity == "Customer"


def test_step6_cross_entity_review_applies_same_batch_prerequisite(monkeypatch):
    _seed_step6_session()

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {
                "success": True,
                "outcomes": [
                    {"suggestion_id": "x-fk", "success": True},
                    {"suggestion_id": "x-check", "success": True},
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/rules/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "x-fk",
                    "suggestion_type": "cross_entity_rule",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {
                        "rule_type": "cross-entity-exists",
                        "source_field": "customerId",
                        "target_entity": "Customer",
                    },
                },
                {
                    "suggestion_id": "x-check",
                    "suggestion_type": "cross_entity_rule",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {
                        "rule_type": "cross-entity-field-check",
                        "source_field": "customerId",
                        "target_entity": "Customer",
                        "target_field": "status",
                        "operator": "eq",
                        "expected_value": "ACTIVE",
                    },
                },
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["applied_count"] == 2
    rules = get_session().entity_rules[0].rules
    assert [rule.type for rule in rules] == [
        "cross-entity-exists",
        "cross-entity-field-check",
    ]


def test_step6_cross_entity_field_check_auto_adds_prerequisite(monkeypatch):
    _seed_step6_session()

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {"success": True, "outcomes": [{"suggestion_id": "x-check", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/rules/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "x-check",
                    "suggestion_type": "cross_entity_rule",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {
                        "rule_type": "cross-entity-field-check",
                        "source_field": "customerId",
                        "target_entity": "Customer",
                        "target_field": "status",
                        "operator": "eq",
                        "expected_value": "ACTIVE",
                    },
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["applied_count"] == 2
    assert response.json()["warnings"] == []
    rules = get_session().entity_rules[0].rules
    assert [rule.type for rule in rules] == ["cross-entity-exists", "cross-entity-field-check"]
    assert rules[0].field == "customerId"
    assert rules[0].target_entity == "Customer"
    assert rules[0].suggestion_id == "x-check"
    assert rules[0].suggestion_type == "cross_entity_rule"
    assert rules[0].applied_by == "knowledge_assist"
    assert rules[0].generated_by_ka is True
    assert rules[1].target_field == "status"
    assert rules[1].expected_value == "ACTIVE"
    assert get_session().ks_workspace_state.review_history[0].suggestion_id == "x-check"
    assert get_session().ks_workspace_state.evidence_links[0].suggestion_id == "x-check"


def test_step6_cross_entity_field_check_warns_when_payload_insufficient(monkeypatch):
    _seed_step6_session()

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {"success": True, "outcomes": [{"suggestion_id": "x-missing", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/rules/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "x-missing",
                    "suggestion_type": "cross_entity_rule",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {
                        "rule_type": "cross-entity-field-check",
                        "target_entity": "Customer",
                        "target_field": "status",
                        "operator": "eq",
                        "expected_value": "ACTIVE",
                    },
                }
            ]
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["applied_count"] == 0
    assert "Review saved, but rule was not applied because source field was missing." in payload["warnings"][0]
    assert get_session().entity_rules == []
    assert get_session().ks_workspace_state.review_history[0].suggestion_id == "x-missing"
    assert get_session().ks_workspace_state.evidence_links == []


def test_step6_cross_entity_field_rules_apply_with_prerequisite(monkeypatch):
    session = _seed_step6_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(
                    field="customerId",
                    type="cross-entity-exists",
                    target_entity="Customer",
                )
            ],
            file_path="rules/account-business-rules.yaml",
        )
    ]
    save_session(session)

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {
                "success": True,
                "outcomes": [
                    {"suggestion_id": "x-check", "success": True},
                    {"suggestion_id": "x-compare", "success": True},
                    {"suggestion_id": "x-in", "success": True},
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/rules/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "x-check",
                    "suggestion_type": "cross_entity_rule",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {
                        "rule_type": "cross-entity-field-check",
                        "source_field": "customerId",
                        "target_entity": "Customer",
                        "target_field": "status",
                        "operator": "eq",
                        "expected_value": "ACTIVE",
                    },
                },
                {
                    "suggestion_id": "x-compare",
                    "suggestion_type": "cross_entity_rule",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {
                        "rule_type": "cross-entity-field-compare",
                        "source_field": "customerId",
                        "target_entity": "Customer",
                        "target_field": "approvedLimit",
                        "compare_source_field": "requestedAmount",
                        "operator": "lte",
                    },
                },
                {
                    "suggestion_id": "x-in",
                    "suggestion_type": "cross_entity_rule",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {
                        "rule_type": "cross-entity-field-in",
                        "source_field": "customerId",
                        "target_entity": "Customer",
                        "target_field": "status",
                        "allowed_values": ["ACTIVE", "REVIEW"],
                    },
                },
            ]
        },
    )

    assert response.status_code == 200
    rules = get_session().entity_rules[0].rules
    assert [rule.type for rule in rules] == [
        "cross-entity-exists",
        "cross-entity-field-check",
        "cross-entity-field-compare",
        "cross-entity-field-in",
    ]
    assert rules[1].expected_value == "ACTIVE"
    assert rules[2].source_field == "requestedAmount"
    assert rules[3].values == ["ACTIVE", "REVIEW"]


def test_step6_cross_entity_review_canonicalizes_source_and_target_aliases(monkeypatch):
    session = _seed_step6_session()
    session.classified_entities = [
        ClassifiedEntity(
            name="AccountResponse",
            canonical_name="Account",
            classification="entity",
            fields=[ClassifiedField(name="customerId", type="string")],
        ),
        ClassifiedEntity(
            name="BranchResponse",
            canonical_name="Branch",
            classification="entity",
            fields=[ClassifiedField(name="branchCode", type="string")],
        ),
    ]
    session.selected_entity_names = ["AccountResponse", "BranchResponse"]
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(
                    field="customerId",
                    type="cross-entity-exists",
                    target_entity="Branch",
                )
            ],
            file_path="rules/account-business-rules.yaml",
        )
    ]
    save_session(session)

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {"success": True, "outcomes": [{"suggestion_id": "x-branch", "success": True}]}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/rules/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "x-branch",
                    "suggestion_type": "cross_entity_rule",
                    "status": "accepted",
                    "entity": "Account",
                    "manifest_path": "rules.Account.CUSTOMER_ID.cross-entity-field-check",
                    "payload": {
                        "rule_type": "cross-entity-field-check",
                        "source_field": "CUSTOMER_ID",
                        "target_entity": "Branch",
                        "target_field": "BRANCH_CODE",
                        "operator": "eq",
                        "expected_value": "ACTIVE",
                    },
                }
            ]
        },
    )

    assert response.status_code == 200
    rule = get_session().entity_rules[0].rules[1]
    assert rule.field == "customerId"
    assert rule.target_field == "branchCode"
    assert (
        get_session().ks_workspace_state.review_history[0].manifest_path
        == "rules.Account.customerId.cross-entity-field-check"
    )
    assert (
        get_session().ks_workspace_state.evidence_links[0].manifest_path
        == "rules.Account.customerId.cross-entity-field-check"
    )


def test_step6_cross_entity_review_history_preserves_same_manifest_path(monkeypatch):
    session = _seed_step6_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(
                    field="customerId",
                    type="cross-entity-exists",
                    target_entity="Customer",
                )
            ],
            file_path="rules/account-business-rules.yaml",
        )
    ]
    save_session(session)

    class FakeClient:
        def submit_suggestion_decisions(self, project_id: str, decisions: list[dict]):
            return {
                "success": True,
                "outcomes": [
                    {"suggestion_id": "x-check-status", "success": True},
                    {"suggestion_id": "x-check-branch", "success": True},
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/rules/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "x-check-status",
                    "suggestion_type": "cross_entity_rule",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {
                        "rule_type": "cross-entity-field-check",
                        "source_field": "customerId",
                        "target_entity": "Customer",
                        "target_field": "status",
                        "operator": "eq",
                        "expected_value": "ACTIVE",
                    },
                },
                {
                    "suggestion_id": "x-check-branch",
                    "suggestion_type": "cross_entity_rule",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {
                        "rule_type": "cross-entity-field-check",
                        "source_field": "customerId",
                        "target_entity": "Customer",
                        "target_field": "branchCode",
                        "operator": "neq",
                        "expected_value": "BLOCKED",
                    },
                },
            ]
        },
    )

    assert response.status_code == 200
    session = get_session()
    assert [link.suggestion_id for link in session.ks_workspace_state.evidence_links] == [
        "x-check-status",
        "x-check-branch",
    ]
    history = session.ks_workspace_state.review_history
    assert [entry.suggestion_id for entry in history] == ["x-check-status", "x-check-branch"]
    assert {entry.manifest_path for entry in history} == {
        "rules.Account.customerId.cross-entity-field-check"
    }


def test_step6_cross_entity_review_rejects_invalid_operator(monkeypatch):
    session = _seed_step6_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[RuleEntry(field="customerId", type="cross-entity-exists", target_entity="Customer")],
        )
    ]
    save_session(session)

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called for invalid payloads")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.post(
        "/rules/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "x-bad",
                    "suggestion_type": "cross_entity_rule",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {
                        "rule_type": "cross-entity-field-check",
                        "source_field": "customerId",
                        "target_entity": "Customer",
                        "target_field": "status",
                        "operator": "contains",
                        "expected_value": "ACTIVE",
                    },
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "valid operator" in response.json()["errors"][0]


def test_step6_get_does_not_invent_conflicts_for_non_crud(monkeypatch):
    _seed_step6_session(app_archetype="passthrough-router")

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called for non-CRUD Step 6")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/rules")

    assert response.status_code == 200
    assert "Manual rules authoring remains available without live advisory conflict data." in response.text
    assert "No current advisory issues from Knowledge Assist field guidance." not in response.text
    assert 'data-shell-rail-default="collapsed"' in response.text


def test_step6_generated_id_warnings_render_independently_of_conflict_signals(monkeypatch):
    _seed_step6_session(include_generated_id_warning=True)

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            entity: str,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            if scope != "fields":
                return {"suggestions": [], "suggestion_count": 0}
            return {"suggestions": []}

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/rules")

    assert response.status_code == 200
    assert "Generated-ID rule warnings" in response.text
    assert "Account.accountId looks server-generated" in response.text
    assert "No current advisory issues. Step 6 advisories appear" in response.text
    assert "advisory-issues-empty" not in response.text
