"""Tests for rule YAML generation."""

import yaml

from app.models.project import EntityRules, RuleEntry
from app.services.rule_generator import extract_table_name_from_ddl, generate_rule_yaml


def test_allowed_values_rule():
    er = EntityRules(
        entity_name="Account",
        rules=[RuleEntry(field="accountType", type="allowed-values", values=["CHQ", "SAV", "CUR", "LON"])],
    )
    doc = yaml.safe_load(generate_rule_yaml(er))
    assert doc["entity"] == "Account"
    rule = doc["rules"][0]
    assert rule["field"] == "accountType"
    assert rule["type"] == "allowed-values"
    assert rule["values"] == ["CHQ", "SAV", "CUR", "LON"]
    assert "value" not in rule


def test_default_rule():
    er = EntityRules(
        entity_name="Account",
        rules=[RuleEntry(field="status", type="default", value="PENDING")],
    )
    doc = yaml.safe_load(generate_rule_yaml(er))
    rule = doc["rules"][0]
    assert rule["type"] == "default"
    assert rule["value"] == "PENDING"
    assert "values" not in rule


def test_iso4217_rule():
    er = EntityRules(
        entity_name="Account",
        rules=[RuleEntry(field="currency", type="iso-4217")],
    )
    doc = yaml.safe_load(generate_rule_yaml(er))
    rule = doc["rules"][0]
    assert rule["type"] == "iso-4217"
    # No extra fields needed
    assert "values" not in rule
    assert "value" not in rule


def test_multiple_rules():
    er = EntityRules(
        entity_name="Account",
        rules=[
            RuleEntry(field="accountType", type="allowed-values", values=["CHQ", "SAV"]),
            RuleEntry(field="currency", type="iso-4217"),
            RuleEntry(field="status", type="default", value="PENDING"),
        ],
    )
    doc = yaml.safe_load(generate_rule_yaml(er))
    assert len(doc["rules"]) == 3


def test_cross_entity_exists_rule():
    er = EntityRules(
        entity_name="Account",
        rules=[
            RuleEntry(
                field="customerId",
                type="cross-entity-exists",
                target_entity="Customer",
            )
        ],
    )
    doc = yaml.safe_load(generate_rule_yaml(er))
    rule = doc["rules"][0]
    assert rule["field"] == "customerId"
    assert rule["type"] == "cross-entity-exists"
    assert rule["target-entity"] == "Customer"
    assert "target_entity" not in rule


def test_field_comparison_rule():
    er = EntityRules(
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
    doc = yaml.safe_load(generate_rule_yaml(er))
    rule = doc["rules"][0]
    assert rule["field"] == "paidAmount"
    assert rule["type"] == "field-comparison"
    assert rule["operator"] == "<="
    assert rule["compare-to-field"] == "dueAmount"
    assert "compare_to_field" not in rule


def test_cross_entity_field_check_rule():
    er = EntityRules(
        entity_name="Account",
        rules=[
            RuleEntry(
                field="customerId",
                type="cross-entity-field-check",
                target_entity="Customer",
                target_field="status",
                operator="eq",
                expected_value="ACTIVE",
                error_message="Customer must be ACTIVE before this action.",
            )
        ],
    )

    doc = yaml.safe_load(generate_rule_yaml(er))
    rule = doc["rules"][0]
    assert rule["field"] == "customerId"
    assert rule["type"] == "cross-entity-field-check"
    assert rule["target-entity"] == "Customer"
    assert rule["target-field"] == "status"
    assert rule["operator"] == "eq"
    assert rule["expected-value"] == "ACTIVE"
    assert rule["error-message"] == "Customer must be ACTIVE before this action."


def test_cross_entity_field_compare_rule():
    er = EntityRules(
        entity_name="Account",
        rules=[
            RuleEntry(
                field="customerId",
                type="cross-entity-field-compare",
                target_entity="Customer",
                target_field="approvedLimit",
                source_field="requestedAmount",
                operator="lte",
                error_message="Requested amount exceeds approved limit.",
            )
        ],
    )

    doc = yaml.safe_load(generate_rule_yaml(er))
    rule = doc["rules"][0]
    assert rule["field"] == "customerId"
    assert rule["type"] == "cross-entity-field-compare"
    assert rule["target-entity"] == "Customer"
    assert rule["target-field"] == "approvedLimit"
    assert rule["source-field"] == "requestedAmount"
    assert rule["operator"] == "lte"
    assert rule["error-message"] == "Requested amount exceeds approved limit."


def test_cross_entity_field_in_rule():
    er = EntityRules(
        entity_name="Account",
        rules=[
            RuleEntry(
                field="customerId",
                type="cross-entity-field-in",
                target_entity="Customer",
                target_field="status",
                values=["ACTIVE", "REVIEW"],
                error_message="Customer status must be eligible.",
            )
        ],
    )

    doc = yaml.safe_load(generate_rule_yaml(er))
    rule = doc["rules"][0]
    assert rule["field"] == "customerId"
    assert rule["type"] == "cross-entity-field-in"
    assert rule["target-entity"] == "Customer"
    assert rule["target-field"] == "status"
    assert rule["allowed-values"] == ["ACTIVE", "REVIEW"]
    assert rule["error-message"] == "Customer status must be eligible."


def test_pattern_rule_preserves_single_regex_escapes():
    er = EntityRules(
        entity_name="Customer",
        rules=[
            RuleEntry(
                field="email",
                type="pattern",
                value=r"^[^\s@]+@[^\s@]+\.[^\s@]+$",
            )
        ],
    )
    doc = yaml.safe_load(generate_rule_yaml(er))
    rule = doc["rules"][0]
    assert rule["type"] == "pattern"
    assert rule["value"] == r"^[^\s@]+@[^\s@]+\.[^\s@]+$"


def test_validation_hint_rule_shapes_serialize_to_yaml():
    er = EntityRules(
        entity_name="Account",
        rules=[
            RuleEntry(field="status", type="not-null"),
            RuleEntry(field="accountNumber", type="max-length", value="14"),
            RuleEntry(field="accountNumber", type="min-length", value="8"),
            RuleEntry(field="accountNumber", type="pattern", value="^[0-9]+$"),
            RuleEntry(field="balance", type="range", value="0.0", values=["999.0"]),
        ],
    )

    doc = yaml.safe_load(generate_rule_yaml(er))

    assert doc["rules"] == [
        {"field": "status", "type": "not-null"},
        {"field": "accountNumber", "type": "max-length", "value": "14"},
        {"field": "accountNumber", "type": "min-length", "value": "8"},
        {"field": "accountNumber", "type": "pattern", "value": "^[0-9]+$"},
        {"field": "balance", "type": "range", "min": "0.0", "max": "999.0"},
    ]


def test_extract_table_name_simple():
    ddl = "CREATE TABLE acct_staging_tbl (id VARCHAR(20) NOT NULL);"
    assert extract_table_name_from_ddl(ddl) == "acct_staging_tbl"


def test_extract_table_name_if_not_exists():
    ddl = "CREATE TABLE IF NOT EXISTS my_table (col1 INT);"
    assert extract_table_name_from_ddl(ddl) == "my_table"


def test_extract_table_name_none():
    assert extract_table_name_from_ddl("SELECT 1") is None
