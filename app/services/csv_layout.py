"""Round-trip CSV layout projection, materialization, and validation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import StringIO
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError

from app.services.mapping_generator import _record_types_layout_document

_CSV_FIELD_TYPES = frozenset(
    {
        "string",
        "char",
        "text",
        "integer",
        "int",
        "long",
        "decimal",
        "number",
        "bigdecimal",
        "date",
        "localdate",
        "datetime",
        "date-time",
        "timestamp",
        "localdatetime",
        "boolean",
        "bool",
    }
)
_JAVA_ENCODINGS = frozenset(
    {
        "ascii",
        "iso-8859-1",
        "us-ascii",
        "utf-8",
        "utf-16",
        "utf-16be",
        "utf-16le",
        "windows-1252",
    }
)


class CsvLayoutError(ValueError):
    """Raised when CSV layout content cannot be safely projected or materialized."""


@dataclass(frozen=True)
class CsvLayoutProjection:
    fields: list[dict[str, Any]]
    delimiter: str
    delimiter_label: str
    has_header_row: bool
    source_hash: str
    legacy_flat: bool
    errors: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "fields": self.fields,
            "delimiter": self.delimiter,
            "delimiter_label": self.delimiter_label,
            "has_header_row": self.has_header_row,
            "source_hash": self.source_hash,
            "legacy_flat": self.legacy_flat,
            "errors": self.errors,
        }


def csv_layout_source_hash(spec_content: str | None) -> str:
    return hashlib.sha256((spec_content or "").encode("utf-8")).hexdigest()


def project_csv_layout(spec_content: str | None) -> CsvLayoutProjection:
    """Project durable CSV YAML into editable rows without changing the source text."""
    text = spec_content or ""
    if not text.strip():
        return CsvLayoutProjection(
            fields=[],
            delimiter=",",
            delimiter_label="comma (,)",
            has_header_row=False,
            source_hash=csv_layout_source_hash(text),
            legacy_flat=False,
            errors=[],
        )

    try:
        document = _load_document(text)
    except CsvLayoutError as exc:
        return CsvLayoutProjection(
            fields=[],
            delimiter=",",
            delimiter_label="comma (,)",
            has_header_row=False,
            source_hash=csv_layout_source_hash(text),
            legacy_flat=False,
            errors=[str(exc)],
        )

    fields, legacy_flat, field_errors = _projected_fields(document)
    raw_delimiter = document.get("delimiter", document.get("separator", ","))
    delimiter = _normalized_delimiter(raw_delimiter, allow_legacy_label=True)
    raw_header = document.get("has_header_row", document.get("header", False))
    header = _normalized_header(raw_header)
    errors = list(field_errors)
    if delimiter is None:
        errors.append("CSV delimiter must be one character, or use tab.")
    if header is None:
        errors.append("CSV header-row value must be true or false.")
    display_delimiter = delimiter
    if display_delimiter is None:
        display_delimiter = raw_delimiter if isinstance(raw_delimiter, str) else ","
    return CsvLayoutProjection(
        fields=fields,
        delimiter="tab" if display_delimiter == "\t" else display_delimiter,
        delimiter_label=_delimiter_label(display_delimiter),
        has_header_row=header if header is not None else False,
        source_hash=csv_layout_source_hash(text),
        legacy_flat=legacy_flat,
        errors=errors,
    )


def materialize_csv_layout(
    spec_content: str | None,
    *,
    name: str,
    fields: list[dict[str, Any]],
    delimiter: Any = None,
    has_header_row: Any = None,
    expected_source_hash: str | None = None,
) -> str:
    """Apply Studio-owned CSV fields to round-trip YAML while preserving all other content."""
    original = spec_content or ""
    if expected_source_hash and expected_source_hash != csv_layout_source_hash(original):
        raise CsvLayoutError(
            "Layout/spec content changed after the visual rows were inspected. "
            "Inspect layout/sample again before saving."
        )

    normalized_fields = _normalize_editor_fields(fields)
    if not normalized_fields:
        raise CsvLayoutError("CSV layouts require at least one visual field row before saving content.")
    normalized_delimiter = _normalized_delimiter(
        delimiter if delimiter is not None else ",",
        allow_legacy_label=True,
    )
    if normalized_delimiter is None:
        raise CsvLayoutError("CSV delimiter must be one character, or use tab.")
    normalized_header = _normalized_header(has_header_row)
    if normalized_header is None:
        raise CsvLayoutError("CSV header-row value must be true or false.")

    if original.strip():
        document = _load_document(original)
        projected = project_csv_layout(original)
        if projected.errors:
            raise CsvLayoutError(projected.errors[0])
        if (
            not projected.legacy_flat
            and not _requires_control_upgrade(document)
            and _editor_semantics(projected.fields) == _editor_semantics(normalized_fields)
            and _normalized_delimiter(projected.delimiter, allow_legacy_label=True) == normalized_delimiter
            and projected.has_header_row == normalized_header
        ):
            errors = validate_csv_layout_content(original)
            if not errors:
                return original
    else:
        document = _to_round_trip_document(
            _record_types_layout_document(
                name=name,
                format_name="csv",
                fields=[_owned_field_values(field) for field in normalized_fields],
                delimiter=normalized_delimiter,
                has_header_row=normalized_header,
            )
        )

    document["format"] = "csv"
    _set_control_if_changed(document, "delimiter", normalized_delimiter, default=",")
    _set_control_if_changed(document, "has_header_row", normalized_header, default=False)
    document.pop("header", None)
    document.pop("separator", None)

    existing_fields, legacy_flat = _field_nodes(document)
    updated_fields = _updated_field_nodes(existing_fields, normalized_fields)
    record_types = document.get("record_types")
    if not isinstance(record_types, CommentedMap):
        record_types = CommentedMap()
        document["record_types"] = record_types
    data_record = record_types.get("data")
    if not isinstance(data_record, CommentedMap):
        data_record = CommentedMap()
        record_types["data"] = data_record
    data_record["fields"] = CommentedSeq(updated_fields)
    if legacy_flat:
        document.pop("fields", None)

    rendered = _dump_document(document)
    errors = validate_csv_layout_content(rendered)
    if errors:
        raise CsvLayoutError(errors[0])
    return rendered


def prepare_csv_layout_for_export(spec_content: str | None, *, name: str) -> str:
    """Validate current CSV YAML or deterministically upgrade legacy flat fields."""
    text = spec_content or ""
    if not text.strip():
        raise CsvLayoutError("CSV layout/spec content is empty.")
    projection = project_csv_layout(text)
    if projection.errors:
        raise CsvLayoutError(projection.errors[0])
    document = _load_document(text)
    if projection.legacy_flat or _requires_control_upgrade(document):
        return materialize_csv_layout(
            text,
            name=name,
            fields=projection.fields,
            delimiter=projection.delimiter,
            has_header_row=projection.has_header_row,
            expected_source_hash=projection.source_hash,
        )
    errors = validate_csv_layout_content(text)
    if errors:
        raise CsvLayoutError(errors[0])
    return text


def validate_csv_layout_content(spec_content: str | None) -> list[str]:
    """Return deterministic errors for the Engine-current CSV layout contract."""
    text = spec_content or ""
    if not text.strip():
        return ["CSV layout/spec content is empty."]
    try:
        document = _load_document(text)
    except CsvLayoutError as exc:
        return [str(exc)]

    errors: list[str] = []
    if document.get("format") != "csv":
        errors.append("CSV layout must declare format: csv.")

    delimiter = _normalized_delimiter(document.get("delimiter", ","))
    if delimiter is None:
        errors.append("CSV delimiter must be a single character.")
    quote_char = _optional_single_character(document.get("quote_char", '"'))
    if document.get("quote_char", '"') is not None and quote_char is None:
        errors.append("CSV quote_char must be a single character or null.")
    escape_char = _optional_single_character(document.get("escape_char", "\\"))
    if document.get("escape_char", "\\") is not None and escape_char is None:
        errors.append("CSV escape_char must be a single character or null.")
    characters = [value for value in (delimiter, quote_char, escape_char) if value is not None]
    if len(characters) != len(set(characters)):
        errors.append("CSV delimiter, quote_char, and escape_char must be different characters.")

    header = document.get("has_header_row", False)
    if not isinstance(header, bool):
        errors.append("CSV has_header_row must be true or false.")
    line_separator = _normalized_line_separator(document.get("line_separator", "\n"))
    if line_separator is None:
        errors.append("CSV line_separator must be one of \\n, \\r\\n, or \\r.")
    elif any(value and value in line_separator for value in characters):
        errors.append("CSV delimiter, quote_char, and escape_char must not occur in line_separator.")

    encoding = document.get("encoding", "UTF-8")
    if encoding is not None and (
        not isinstance(encoding, str) or encoding.strip().lower() not in _JAVA_ENCODINGS
    ):
        errors.append("CSV encoding must be a supported non-empty Java charset name.")

    record_types = document.get("record_types")
    if not isinstance(record_types, dict) or not isinstance(record_types.get("data"), dict):
        errors.append("CSV layout requires record_types.data.fields.")
        return errors

    parsed_indicators: list[tuple[int, str] | None] = []
    for record_name, record in record_types.items():
        if not isinstance(record_name, str) or not record_name.strip():
            errors.append("CSV layout has an empty record type name.")
            continue
        if not isinstance(record, dict):
            errors.append(f"CSV record type '{record_name}' must be a mapping.")
            continue
        indicator = record.get("indicator")
        parsed_indicator: tuple[int, str] | None = None
        if indicator is not None:
            if not isinstance(indicator, dict):
                errors.append(f"CSV record type '{record_name}' indicator must be a mapping.")
            elif indicator.get("position") is not None or indicator.get("length") is not None:
                errors.append(f"CSV record type '{record_name}' must use indicator.column routing.")
            else:
                column = _strict_positive_int(indicator.get("column"))
                value = indicator.get("value")
                if column is None or not isinstance(value, str) or not value.strip():
                    errors.append(f"CSV record type '{record_name}' indicator requires column and value.")
                else:
                    parsed_indicator = (column, value.strip())
        parsed_indicators.append(parsed_indicator)
        errors.extend(_validate_record_fields(record_name, record, parsed_indicator))

    if len(record_types) > 1:
        if not any(parsed_indicators):
            errors.append("CSV layouts with multiple record types require indicator-column routing.")
        elif not all(parsed_indicators):
            errors.append("Every CSV record type must declare an indicator when any record type does.")
        else:
            indicators = [value for value in parsed_indicators if value]
            if len({column for column, _ in indicators}) != 1:
                errors.append("CSV record types must use one shared indicator column.")
            if len({value for _, value in indicators}) != len(indicators):
                errors.append("CSV record-type indicator values must be unique.")
    return errors


def _load_document(text: str) -> CommentedMap:
    yaml = _round_trip_yaml()
    try:
        document = yaml.load(text)
    except (YAMLError, ValueError) as exc:
        raise CsvLayoutError(f"Malformed CSV layout/spec YAML: {exc}") from exc
    if not isinstance(document, CommentedMap):
        raise CsvLayoutError("CSV layout/spec YAML must be a mapping.")
    return document


def _round_trip_yaml() -> YAML:
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.allow_duplicate_keys = False
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def _dump_document(document: CommentedMap) -> str:
    output = StringIO()
    _round_trip_yaml().dump(document, output)
    return output.getvalue()


def _to_round_trip_document(value: Any) -> Any:
    if isinstance(value, dict):
        return CommentedMap((key, _to_round_trip_document(item)) for key, item in value.items())
    if isinstance(value, list):
        return CommentedSeq(_to_round_trip_document(item) for item in value)
    return value


def _field_nodes(document: CommentedMap) -> tuple[list[CommentedMap], bool]:
    fields, legacy_flat = _raw_field_nodes(document)
    if not isinstance(fields, list):
        return [], legacy_flat
    return [field for field in fields if isinstance(field, CommentedMap)], legacy_flat


def _raw_field_nodes(document: CommentedMap) -> tuple[Any, bool]:
    record_types = document.get("record_types")
    if isinstance(record_types, dict):
        data_record = record_types.get("data")
        if isinstance(data_record, dict) and "fields" in data_record:
            return data_record.get("fields"), False
    if "fields" in document:
        return document.get("fields"), True
    return None, False


def _projected_fields(
    document: CommentedMap,
) -> tuple[list[dict[str, Any]], bool, list[str]]:
    raw_nodes, legacy_flat = _raw_field_nodes(document)
    errors: list[str] = []
    if not isinstance(raw_nodes, list) or not raw_nodes:
        message = (
            "Legacy CSV layout requires non-empty fields."
            if legacy_flat
            else "CSV layout requires record_types.data.fields."
        )
        return [], legacy_flat, [message]

    if legacy_flat:
        errors.extend(_validate_legacy_projection_fields(raw_nodes))
    else:
        record_types = document.get("record_types")
        data_record = record_types.get("data") if isinstance(record_types, dict) else None
        if isinstance(data_record, dict):
            parsed_indicator = _projection_indicator(data_record.get("indicator"), errors)
            errors.extend(_validate_record_fields("data", data_record, parsed_indicator))

    rows = []
    for index, field in enumerate(raw_nodes, start=1):
        if not isinstance(field, CommentedMap):
            continue
        name = field.get("name")
        column = index if legacy_flat else _strict_positive_int(field.get("column"))
        field_type = field.get("type")
        projected_type = (
            field_type.strip().lower()
            if isinstance(field_type, str) and field_type.strip()
            else None
        )
        required = field.get("required") if isinstance(field.get("required"), bool) else None
        rows.append(
            {
                "name": name.strip() if isinstance(name, str) else "",
                "column": column,
                "type": projected_type,
                "required": required,
                "original_name": name.strip() if isinstance(name, str) else "",
                "original_column": column,
            }
        )
    return rows, legacy_flat, errors


def _projection_indicator(
    indicator: Any,
    errors: list[str],
) -> tuple[int, str] | None:
    if indicator is None:
        return None
    if not isinstance(indicator, dict):
        errors.append("CSV record type 'data' indicator must be a mapping.")
        return None
    if indicator.get("position") is not None or indicator.get("length") is not None:
        errors.append("CSV record type 'data' must use indicator.column routing.")
        return None
    column = _strict_positive_int(indicator.get("column"))
    value = indicator.get("value")
    if column is None or not isinstance(value, str) or not value.strip():
        errors.append("CSV record type 'data' indicator requires column and value.")
        return None
    return column, value.strip()


def _validate_legacy_projection_fields(fields: list[Any]) -> list[str]:
    errors: list[str] = []
    names: set[str] = set()
    for index, field in enumerate(fields, start=1):
        if not isinstance(field, dict):
            errors.append(f"Legacy CSV field {index} must be a mapping.")
            continue
        name = field.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"Legacy CSV field {index} requires a name.")
            continue
        name = name.strip()
        if name in names:
            errors.append(f"Legacy CSV layout declares duplicate field name '{name}'.")
        names.add(name)
        field_type = field.get("type")
        if field_type is not None and (
            not isinstance(field_type, str) or field_type.lower() not in _CSV_FIELD_TYPES
        ):
            errors.append(f"Legacy CSV field '{name}' has unsupported type '{field_type}'.")
    return errors


def _normalize_editor_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    names: set[str] = set()
    columns: set[int] = set()
    for index, raw in enumerate(fields, start=1):
        if not isinstance(raw, dict):
            raise CsvLayoutError(f"CSV field row {index} must be an object.")
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise CsvLayoutError(f"CSV field row {index} requires a name.")
        name = name.strip()
        column = _coerce_positive_int(raw.get("column"))
        if column is None:
            raise CsvLayoutError(f"CSV field '{name}' requires a positive integer column.")
        if name in names:
            raise CsvLayoutError(f"CSV layout declares duplicate field name '{name}'.")
        if column in columns:
            raise CsvLayoutError(f"CSV layout declares duplicate column {column}.")
        names.add(name)
        columns.add(column)
        field_type = raw.get("type")
        field_type = field_type.strip().lower() if isinstance(field_type, str) and field_type.strip() else None
        if field_type and field_type not in _CSV_FIELD_TYPES:
            raise CsvLayoutError(f"CSV field '{name}' has unsupported type '{field_type}'.")
        required = raw.get("required")
        if required not in {None, True, False}:
            raise CsvLayoutError(f"CSV field '{name}' required must be true, false, or unspecified.")
        normalized.append(
            {
                "name": name,
                "column": column,
                "type": field_type,
                "required": required,
                "original_name": str(raw.get("original_name") or "").strip(),
                "original_column": _coerce_positive_int(raw.get("original_column")),
            }
        )
    return normalized


def _updated_field_nodes(
    existing: list[CommentedMap],
    fields: list[dict[str, Any]],
) -> list[CommentedMap]:
    unused = list(existing)
    updated: list[CommentedMap] = []
    for field in fields:
        original_name = field.get("original_name")
        original_column = field.get("original_column")
        node = next(
            (
                candidate
                for candidate in unused
                if candidate.get("name") == original_name
                and _strict_positive_int(candidate.get("column")) == original_column
            ),
            None,
        )
        if node is None and original_column is not None:
            node = next(
                (
                    candidate
                    for candidate in unused
                    if _strict_positive_int(candidate.get("column")) == original_column
                ),
                None,
            )
        if node is None and original_name:
            node = next((candidate for candidate in unused if candidate.get("name") == original_name), None)
        if node is None:
            node = next(
                (candidate for candidate in unused if candidate.get("name") == field["name"]),
                None,
            )
        if node is None:
            node = CommentedMap()
        elif node in unused:
            unused.remove(node)

        node["name"] = field["name"]
        node["column"] = field["column"]
        if field["type"] is None:
            node.pop("type", None)
        else:
            node["type"] = field["type"]
        if field["required"] is None:
            node.pop("required", None)
        else:
            node["required"] = field["required"]
        node.pop("start", None)
        node.pop("position", None)
        node.pop("length", None)
        node.pop("locked_start", None)
        updated.append(node)
    return updated


def _owned_field_values(field: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {"name": field["name"], "column": field["column"]}
    if field.get("type") is not None:
        values["type"] = field["type"]
    if field.get("required") is not None:
        values["required"] = field["required"]
    return values


def _set_control_if_changed(document: CommentedMap, key: str, value: Any, *, default: Any) -> None:
    current = document.get(key, default)
    if key == "delimiter":
        current = _normalized_delimiter(current, allow_legacy_label=True)
    if current == value and key not in document:
        return
    document[key] = value


def _requires_control_upgrade(document: CommentedMap) -> bool:
    if "header" in document or "separator" in document:
        return True
    delimiter = document.get("delimiter", ",")
    if isinstance(delimiter, str) and delimiter.strip().lower() in {
        "tab",
        "comma",
        "pipe",
        "tilde",
    }:
        return True
    header = document.get("has_header_row", False)
    return not isinstance(header, bool) and _normalized_header(header) is not None


def _editor_semantics(fields: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return [
        (field.get("name"), field.get("column"), field.get("type"), field.get("required"))
        for field in fields
    ]


def _normalized_delimiter(value: Any, *, allow_legacy_label: bool = False) -> str | None:
    if not isinstance(value, str):
        return None
    if value in {"\t", "\\t"}:
        return "\t"
    lowered = value.strip().lower()
    if allow_legacy_label and lowered == "tab":
        return "\t"
    if allow_legacy_label:
        if lowered == "comma":
            return ","
        if lowered == "pipe":
            return "|"
        if lowered == "tilde":
            return "~"
    return value if len(value) == 1 else None


def _normalized_header(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return None


def _optional_single_character(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    return value if len(value) == 1 else None


def _normalized_line_separator(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.replace("\\r", "\r").replace("\\n", "\n")
    return normalized if normalized in {"\n", "\r\n", "\r"} else None


def _strict_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def _coerce_positive_int(value: Any) -> int | None:
    parsed = _strict_positive_int(value)
    if parsed is not None:
        return parsed
    if isinstance(value, str) and value.strip().isdigit() and int(value.strip()) > 0:
        return int(value.strip())
    return None


def _validate_record_fields(
    record_name: str,
    record: dict[str, Any],
    indicator: tuple[int, str] | None,
) -> list[str]:
    fields = record.get("fields")
    if not isinstance(fields, list) or not fields:
        return [f"CSV record type '{record_name}' requires non-empty fields."]
    errors: list[str] = []
    names: set[str] = set()
    columns: set[int] = set()
    for index, field in enumerate(fields, start=1):
        if not isinstance(field, dict):
            errors.append(f"CSV record type '{record_name}' field {index} must be a mapping.")
            continue
        name = field.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"CSV record type '{record_name}' field {index} requires a name.")
            continue
        name = name.strip()
        if name in names:
            errors.append(f"CSV record type '{record_name}' declares duplicate field name '{name}'.")
        names.add(name)
        column = _strict_positive_int(field.get("column"))
        if column is None:
            errors.append(f"CSV field '{record_name}.{name}' requires a positive integer column.")
            continue
        if column in columns:
            errors.append(f"CSV record type '{record_name}' declares duplicate column {column}.")
        columns.add(column)
        field_type = field.get("type")
        if field_type is not None and (
            not isinstance(field_type, str) or field_type.lower() not in _CSV_FIELD_TYPES
        ):
            errors.append(f"CSV field '{record_name}.{name}' has unsupported type '{field_type}'.")
    occupied = set(columns)
    if indicator:
        occupied.add(indicator[0])
    if occupied:
        missing = sorted(set(range(1, max(occupied) + 1)) - occupied)
        if missing:
            errors.append(
                f"CSV record type '{record_name}' is missing column(s): "
                + ", ".join(str(column) for column in missing)
                + "."
            )
    return errors


def _delimiter_label(delimiter: str) -> str:
    if delimiter == "\t":
        return "tab"
    labels = {",": "comma (,)", "|": "pipe (|)", "~": "tilde (~)"}
    return labels.get(delimiter, delimiter)
