"""Generate business rule YAML files."""

from __future__ import annotations

from typing import Any

import yaml

from app.models.project import EntityRules


def generate_rule_yaml(entity_rules: EntityRules) -> str:
    """
    Rule file shape:
      entity: Account
      rules:
        - field: accountType
          type: allowed-values
          values: [CHQ, SAV, CUR, LON]
        - field: currency
          type: iso-4217
        - field: status
          type: default
          value: PENDING
        - field: accountNumber
          type: max-length
          value: "10"
        - field: accountNumber
          type: min-length
          value: "10"
        - field: accountNumber
          type: pattern
          value: "^[0-9]{10}$"
        - field: amount
          type: range
          min: "0.01"
          max: "999999.99"
        - field: customerId
          type: not-null
    """
    rules_out = []
    for rule in entity_rules.rules:
        entry: dict[str, Any] = {
            "field": rule.field,
            "type": rule.type,
        }
        if rule.type == "allowed-values" and rule.values:
            entry["values"] = rule.values
        elif rule.type in ("default", "max-length", "min-length", "pattern") and rule.value is not None:
            entry["value"] = rule.value
        elif rule.type == "range":
            # value = minimum, values[0] = maximum (both optional)
            if rule.value is not None:
                entry["min"] = rule.value
            if rule.values:
                entry["max"] = rule.values[0]
        elif rule.type == "cross-entity-exists" and rule.target_entity:
            entry["target-entity"] = rule.target_entity
        elif rule.type == "field-comparison" and rule.operator and rule.compare_to_field:
            entry["operator"] = rule.operator
            entry["compare-to-field"] = rule.compare_to_field
        elif (
            rule.type == "cross-entity-field-check"
            and rule.target_entity
            and rule.target_field
            and rule.operator
            and rule.expected_value is not None
        ):
            entry["target-entity"] = rule.target_entity
            entry["target-field"] = rule.target_field
            entry["operator"] = rule.operator
            entry["expected-value"] = rule.expected_value
            if rule.error_message:
                entry["error-message"] = rule.error_message
        elif (
            rule.type == "cross-entity-field-compare"
            and rule.target_entity
            and rule.target_field
            and rule.source_field
            and rule.operator
        ):
            entry["target-entity"] = rule.target_entity
            entry["target-field"] = rule.target_field
            entry["source-field"] = rule.source_field
            entry["operator"] = rule.operator
            if rule.error_message:
                entry["error-message"] = rule.error_message
        elif (
            rule.type == "cross-entity-field-in"
            and rule.target_entity
            and rule.target_field
            and rule.values
        ):
            entry["target-entity"] = rule.target_entity
            entry["target-field"] = rule.target_field
            entry["allowed-values"] = rule.values
            if rule.error_message:
                entry["error-message"] = rule.error_message
        # iso-4217 and not-null need no extra fields
        rules_out.append(entry)

    doc: dict[str, Any] = {
        "entity": entity_rules.entity_name,
        "rules": rules_out,
    }
    return yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)


def extract_table_name_from_ddl(ddl: str) -> str | None:
    """Extract table name from a CREATE TABLE statement."""
    import re
    match = re.search(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?(\w+)[`\"]?",
        ddl,
        re.IGNORECASE,
    )
    return match.group(1) if match else None
