"""Shared validation-rule fingerprint helpers for KA review reconciliation."""

from __future__ import annotations

import json
from typing import Any


def _normalize_value(value: Any) -> str:
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if isinstance(value, list):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value or "").strip()


def validation_rule_constraint_fingerprint(rule: Any) -> str:
    """Return the stable constraint fingerprint used in review history.

    Keep this intentionally compatible with the legacy Step 6, Step 7, and
    Evidence Trail helpers so existing review-history reconciliation stays
    deterministic.
    """

    rule_type = getattr(rule, "type", "")
    value = getattr(rule, "value", None)
    values = getattr(rule, "values", None) or []

    if rule_type == "max-length":
        return f"max={_normalize_value(value)}" if value else ""
    if rule_type == "min-length":
        return f"min={_normalize_value(value)}" if value else ""
    if rule_type == "pattern":
        return f"pattern={_normalize_value(value)}" if value else ""
    if rule_type == "range":
        items: list[tuple[str, str]] = []
        if value is not None and str(value).strip() != "":
            items.append(("min", _normalize_value(value)))
        if values:
            items.append(("max", _normalize_value(values[0])))
        return "|".join(f"{key}={item_value}" for key, item_value in items)
    if rule_type == "allowed-values" and values:
        return f"values={_normalize_value(values)}"
    return ""


def validation_rule_constraint_matches(rule: Any, expected_fingerprint: str) -> bool:
    expected_fingerprint = str(expected_fingerprint or "").strip()
    if not expected_fingerprint:
        return True
    if validation_rule_constraint_fingerprint(rule) == expected_fingerprint:
        return True
    if getattr(rule, "type", "") != "not-null":
        return False

    expected_items = [item for item in expected_fingerprint.split("|") if item]
    if not expected_items:
        return True
    for item in expected_items:
        key, separator, raw_value = item.partition("=")
        if not separator:
            return False
        key = key.strip()
        value = raw_value.strip().lower()
        if key in {"required", "not_null"} and value in {"true", "1", "yes"}:
            continue
        if key == "nullable" and value in {"false", "0", "no"}:
            continue
        return False
    return True
