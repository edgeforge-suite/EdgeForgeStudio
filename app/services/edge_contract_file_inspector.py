"""Deterministic file-contract layout and sample inspection helpers."""

from __future__ import annotations

import csv
from io import StringIO
from typing import Any

import yaml

from app.services.edge_contracts import FILE_CSV_TYPE, FILE_FIXED_WIDTH_TYPE, clean_text

_UUID_WIDTH = 36
_FILE_TYPES = {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE}


def inspect_file_contract_layout(
    contract_type: str,
    spec_content: str | None,
    sample_content: str | None = None,
) -> dict[str, Any]:
    """Inspect pasted file layout YAML and optional sample content without mutation."""
    clean_type = clean_text(contract_type) or ""
    if clean_type not in _FILE_TYPES:
        return {
            "ok": False,
            "layout": {},
            "sample_preview": {},
            "warnings": [],
            "errors": ["File layout inspection is available for file-fixed-width and file-csv contracts."],
        }
    text = clean_text(spec_content)
    if not text:
        return {
            "ok": False,
            "layout": {},
            "sample_preview": {},
            "warnings": [],
            "errors": ["Paste layout/spec content before inspection. Reference-only contracts can still export if complete."],
        }
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return {
            "ok": False,
            "layout": {},
            "sample_preview": {},
            "warnings": [],
            "errors": [f"Malformed layout/spec YAML: {exc}"],
        }
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "layout": {},
            "sample_preview": {},
            "warnings": [],
            "errors": ["Layout/spec YAML must be a mapping with fields or record_types."],
        }

    if clean_type == FILE_FIXED_WIDTH_TYPE:
        layout, warnings = _inspect_fixed_width_layout(payload)
        sample_preview = _fixed_width_sample_preview(layout["fields"], sample_content)
    else:
        layout, warnings = _inspect_csv_layout(payload)
        sample_preview = _csv_sample_preview(layout, sample_content)
    return {
        "ok": True,
        "layout": layout,
        "sample_preview": sample_preview,
        "warnings": warnings + sample_preview.get("warnings", []),
        "errors": [],
    }


def _layout_fields(payload: dict[str, Any]) -> list[Any]:
    fields = payload.get("fields")
    if isinstance(fields, list):
        return fields
    record = _data_record(payload)
    if isinstance(record, dict) and isinstance(record.get("fields"), list):
        return record["fields"]
    return []


def _data_record(payload: dict[str, Any]) -> dict[str, Any] | None:
    record_types = payload.get("record_types")
    if isinstance(record_types, dict):
        for key in ("data", "detail"):
            record = record_types.get(key)
            if isinstance(record, dict):
                return record
    return None


def _inspect_fixed_width_layout(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    parsed_fields: list[dict[str, Any]] = []
    indicator = _fixed_width_data_indicator(payload)
    data_start = (
        indicator["position"] + indicator["length"]
        if indicator and indicator.get("position") == 1 and indicator.get("length")
        else 1
    )
    next_start = data_start
    for index, raw_field in enumerate(_layout_fields(payload), start=1):
        if not isinstance(raw_field, dict):
            warnings.append(f"Field {index}: expected a mapping with name/start/length.")
            continue
        name = clean_text(raw_field.get("name"))
        if not name:
            warnings.append(f"Field {index}: missing field name.")
        length = _positive_int(raw_field.get("length"))
        if length is None:
            warnings.append(f"{name or f'field {index}'}: invalid or missing length.")
        explicit_start = _positive_int(raw_field.get("start") or raw_field.get("position"))
        if (raw_field.get("start") or raw_field.get("position")) and explicit_start is None:
            warnings.append(f"{name or f'field {index}'}: invalid start position.")
        start = explicit_start or next_start
        field = {
            "name": name or "",
            "start": start,
            "length": length,
            "type": clean_text(raw_field.get("type")),
            "required": _optional_bool(raw_field.get("required")),
        }
        parsed_fields.append(field)
        if length:
            next_start = start + length
        if name and length and _looks_like_id_field(name) and length < _UUID_WIDTH:
            warnings.append(
                f"{name} is length {length}. This field may contain a UUID-style identifier. "
                "Use length 36 unless the project has an explicit non-UUID identity strategy."
            )

    warnings.extend(_fixed_width_position_warnings(parsed_fields, expected_start=data_start))
    return {
        "type": FILE_FIXED_WIDTH_TYPE,
        "indicator": indicator,
        "fields": parsed_fields,
        "expected_line_length": _expected_fixed_width_line_length(parsed_fields),
    }, warnings


def _inspect_csv_layout(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    delimiter = _normalize_delimiter(payload.get("delimiter") or payload.get("separator"))
    if delimiter is None:
        delimiter = ","
    header_value = payload.get("has_header_row") if "has_header_row" in payload else payload.get("header")
    parsed_fields: list[dict[str, Any]] = []
    for index, raw_field in enumerate(_layout_fields(payload), start=1):
        if not isinstance(raw_field, dict):
            warnings.append(f"Field {index}: expected a mapping with name/column metadata.")
            continue
        name = clean_text(raw_field.get("name"))
        if not name:
            warnings.append(f"Field {index}: missing field name.")
        column = _positive_int(raw_field.get("column") or raw_field.get("index") or raw_field.get("position")) or index
        parsed_fields.append(
            {
                "name": name or "",
                "column": column,
                "type": clean_text(raw_field.get("type")),
                "required": _optional_bool(raw_field.get("required")),
            }
        )
    return {
        "type": FILE_CSV_TYPE,
        "delimiter": delimiter,
        "delimiter_label": _delimiter_label(delimiter),
        "has_header_row": _optional_bool(header_value),
        "fields": parsed_fields,
    }, warnings


def _fixed_width_position_warnings(fields: list[dict[str, Any]], *, expected_start: int = 1) -> list[str]:
    warnings: list[str] = []
    positioned = [
        field
        for field in fields
        if field.get("start") and field.get("length")
    ]
    for field in sorted(positioned, key=lambda item: int(item["start"])):
        name = field.get("name") or "unnamed field"
        start = int(field["start"])
        length = int(field["length"])
        if start < expected_start:
            warnings.append(f"{name}: overlaps a previous fixed-width field.")
        elif start > expected_start:
            warnings.append(f"{name}: gap before field; expected start {expected_start}, found {start}.")
        expected_start = max(expected_start, start + length)
    return warnings


def _expected_fixed_width_line_length(fields: list[dict[str, Any]]) -> int | None:
    ends = [
        int(field["start"]) + int(field["length"]) - 1
        for field in fields
        if field.get("start") and field.get("length")
    ]
    return max(ends) if ends else None


def _fixed_width_sample_preview(
    fields: list[dict[str, Any]],
    sample_content: str | None,
) -> dict[str, Any]:
    sample = "" if sample_content is None else str(sample_content)
    if not sample:
        return {"rows": [], "warnings": []}
    line = next((row for row in sample.splitlines() if row != ""), "")
    values = []
    warnings: list[str] = []
    expected_length = _expected_fixed_width_line_length(fields)
    if expected_length and len(line) < expected_length:
        warnings.append(f"Sample line is length {len(line)}, shorter than expected fixed-width length {expected_length}.")
    for field in fields:
        name = field.get("name")
        start = field.get("start")
        length = field.get("length")
        if not name or not start or not length:
            continue
        begin = int(start) - 1
        end = begin + int(length)
        values.append({"field": name, "value": line[begin:end]})
    return {"rows": [{"line": line, "values": values}], "warnings": warnings}


def _csv_sample_preview(layout: dict[str, Any], sample_content: str | None) -> dict[str, Any]:
    sample = "" if sample_content is None else str(sample_content)
    if not sample:
        return {"rows": [], "warnings": []}
    delimiter = layout.get("delimiter") or ","
    try:
        rows = list(csv.reader(StringIO(sample), delimiter=delimiter))
    except csv.Error as exc:
        return {"rows": [], "warnings": [f"Unable to parse sample rows: {exc}"]}
    fields = sorted(layout.get("fields") or [], key=lambda field: int(field.get("column") or 0))
    expected_columns = max((int(field.get("column") or 0) for field in fields), default=0)
    warnings: list[str] = []
    preview_rows = []
    for index, row in enumerate(rows[:3], start=1):
        if expected_columns and len(row) != expected_columns:
            warnings.append(f"Sample row {index} has {len(row)} columns; layout defines {expected_columns}.")
        preview_rows.append(
            {
                "row_number": index,
                "columns": [
                    {
                        "field": field.get("name") or f"column_{field.get('column')}",
                        "value": row[int(field.get("column") or 0) - 1]
                        if 0 < int(field.get("column") or 0) <= len(row)
                        else "",
                    }
                    for field in fields
                ],
            }
        )
    return {"rows": preview_rows, "warnings": warnings}


def _fixed_width_data_indicator(payload: dict[str, Any]) -> dict[str, int | str] | None:
    record = _data_record(payload)
    if not isinstance(record, dict):
        return None
    indicator = record.get("indicator")
    if not isinstance(indicator, dict):
        return None
    position = _positive_int(indicator.get("position"))
    length = _positive_int(indicator.get("length"))
    if not position or not length:
        return None
    result: dict[str, int | str] = {
        "position": position,
        "length": length,
    }
    value = clean_text(indicator.get("value"))
    if value:
        result["value"] = value
    return result


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "y"}
    return bool(value)


def _looks_like_id_field(name: str) -> bool:
    field_name = (name or "").strip()
    lower = field_name.lower()
    return (
        lower == "id"
        or lower.endswith("_id")
        or lower.endswith("-id")
        or field_name.endswith("Id")
        or field_name.endswith("ID")
    )


def _normalize_delimiter(value: Any) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    lower = text.lower()
    if lower in {"comma", ","}:
        return ","
    if lower in {"pipe", "|"}:
        return "|"
    if lower in {"tilde", "~"}:
        return "~"
    if lower in {"tab", "\\t", "\t"}:
        return "\t"
    return text[0]


def _delimiter_label(delimiter: str) -> str:
    if delimiter == "\t":
        return "tab"
    if delimiter == ",":
        return "comma (,)"
    if delimiter == "|":
        return "pipe (|)"
    if delimiter == "~":
        return "tilde (~)"
    return delimiter
