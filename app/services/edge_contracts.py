"""Shared helpers for Studio edge-contract shell metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from app.models.project import (
    DownstreamInterface,
    FieldMapping,
    OperationSample,
    SoapCanonicalInvocationConfig,
    SoapCanonicalOperationConfig,
    SoapRequestMapping,
    SoapResponseMapping,
    SoapReturnMapping,
    UpstreamInterface,
)

REST_OPENAPI_TYPE = "rest-json"
FILE_FIXED_WIDTH_TYPE = "file-fixed-width"
FILE_CSV_TYPE = "file-csv"
XML_XSD_TYPE = "xml-xsd"
SOAP_WSDL_TYPE = "soap-wsdl"

EDGE_CONTRACT_TYPES = {
    FILE_FIXED_WIDTH_TYPE,
    FILE_CSV_TYPE,
    XML_XSD_TYPE,
    SOAP_WSDL_TYPE,
}

SUPPORTED_INTERFACE_TYPES = {REST_OPENAPI_TYPE, *EDGE_CONTRACT_TYPES}

EDGE_CONTRACT_TYPE_LABELS = {
    FILE_FIXED_WIDTH_TYPE: "Fixed-width file",
    FILE_CSV_TYPE: "CSV / delimited file",
    XML_XSD_TYPE: "XML / XSD",
    SOAP_WSDL_TYPE: "SOAP / WSDL",
}

READY_TO_EXPORT = "Ready to export"
INCOMPLETE = "Incomplete"
REFERENCE_ONLY = "Reference only"

SOAP_MAPPING_MODE_ADAPTER_ONLY = "adapter_only"
SOAP_MAPPING_MODE_CANONICAL = "canonical"
SOAP_MAPPING_MODES = {SOAP_MAPPING_MODE_ADAPTER_ONLY, SOAP_MAPPING_MODE_CANONICAL}
SOAP_CANONICAL_KIND_READ_BY_ID = "read_by_id"
SOAP_CANONICAL_KIND_INVOKE_BY_ID = "invoke_by_id"
SOAP_RESPONSE_MODE_RETURN_ONLY = "return_only"
_SOAP_RESPONSE_TARGET_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class EdgeContractReadiness:
    direction: str
    name: str
    type: str
    type_label: str
    artifact_path: str | None
    has_content_to_write: bool
    will_export: bool
    status: str
    required_present: list[str] = field(default_factory=list)
    required_missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "contract"


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def edge_contract_validation_blockers(
    errors: list[str],
    contract_type: str,
) -> list[dict[str, str]]:
    """Map shared edge-contract validation errors to focused-editor references."""
    section_by_type = {
        FILE_FIXED_WIDTH_TYPE: "layout",
        FILE_CSV_TYPE: "layout",
        XML_XSD_TYPE: "xsd",
        SOAP_WSDL_TYPE: "wsdl",
    }
    section_ref = section_by_type.get(contract_type, "contract")
    blockers = []
    for error in errors:
        lowered = error.lower()
        field_ref = None
        if contract_type == SOAP_WSDL_TYPE:
            # Nested SOAP mapping errors often contain generic words such as
            # "name" or "type", so their controls must take precedence.
            soap_field_patterns = (
                (("request mapping", "required soap request field"), "soap_request_mappings"),
                (("response mapping", "required soap response field"), "soap_response_mappings"),
                (("response mode",), "soap_response_mode"),
                (("lookup request field",), "soap_request_field"),
                (("lookup field", "persistence id"), "soap_lookup_field"),
                (
                    (
                        "select a downstream soap operation",
                        "unknown downstream soap operation",
                        "select a soap operation",
                        "unknown soap operation",
                    ),
                    "selected_operation_name",
                ),
                (("operation mapping mode", "adapter-only", "operation kind"), "soap_operation_mode"),
                (
                    ("canonical entity", "canonical invocation configuration"),
                    "soap_canonical_entity",
                ),
            )
            field_ref = next(
                (
                    candidate
                    for phrases, candidate in soap_field_patterns
                    if any(phrase in lowered for phrase in phrases)
                ),
                None,
            )
        if contract_type == FILE_CSV_TYPE:
            csv_field_patterns = (
                (("changed after the visual rows", "malformed csv layout", "layout/spec yaml"), "spec_content"),
                (("delimiter",), "csv_delimiter"),
                (("header-row", "has_header_row"), "csv_has_header_row"),
                (("csv field", "record_types.data.fields", "csv record type"), "csv_layout_fields"),
            )
            field_ref = next(
                (
                    candidate
                    for phrases, candidate in csv_field_patterns
                    if any(phrase in lowered for phrase in phrases)
                ),
                field_ref,
            )
        if field_ref is None:
            field_ref = next(
                (
                    field
                    for field in (
                        "name",
                        "type",
                        "entity_name",
                        "spec",
                        "xsd_path",
                        "root_element",
                        "wsdl_path",
                        "selected_operation_name",
                    )
                    if field.replace("_", " ") in lowered or field in lowered
                ),
                None,
            )
        field_ref = field_ref or section_ref
        code_slug = slug(error)[:64] or "invalid-contract"
        blockers.append(
            {
                "code": f"invalid-{code_slug}",
                "label": error,
                "field_ref": field_ref,
                "section_ref": section_ref,
            }
        )
    return blockers


def clean_path(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    return text.lstrip("/")


def normalize_csv_delimiter(value: Any) -> str | None:
    """Normalize Studio's CSV delimiter control into the layout YAML value."""
    text = clean_text(value)
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"tab", "\\t"}:
        return "\t"
    if lowered in {"comma", ","}:
        return ","
    if lowered in {"pipe", "|"}:
        return "|"
    if lowered in {"tilde", "~"}:
        return "~"
    if len(text) == 1:
        return text
    return None


def normalize_csv_header_row(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = clean_text(value)
    if text is None:
        return None
    lowered = text.lower()
    if lowered in {"true", "1", "yes", "y", "on"}:
        return True
    if lowered in {"false", "0", "no", "n", "off"}:
        return False
    return None


def csv_spec_content_with_controls(
    spec_content: Any,
    *,
    delimiter: Any = None,
    has_header_row: Any = None,
) -> str | None:
    """Return CSV layout YAML with explicit delimiter/header controls applied.

    Studio keeps the layout/spec YAML as the export source of truth.  This helper
    only updates already-provided spec content so reference-only contracts stay
    reference-only.
    """
    text = clean_text(spec_content)
    if not text:
        return None

    normalized_delimiter = normalize_csv_delimiter(delimiter)
    normalized_header = normalize_csv_header_row(has_header_row)
    if normalized_delimiter is None and normalized_header is None:
        return text

    lines = text.splitlines()
    if normalized_header is not None:
        lines = _upsert_yaml_scalar(lines, "has_header_row", "true" if normalized_header else "false")
    if normalized_delimiter is not None:
        lines = _upsert_yaml_scalar(lines, "delimiter", _yaml_scalar_for_csv_delimiter(normalized_delimiter))
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def payload_with_csv_controls(raw: dict[str, Any]) -> dict[str, Any]:
    if clean_text(raw.get("type")) != FILE_CSV_TYPE:
        return raw
    updated = dict(raw)
    updated_spec = csv_spec_content_with_controls(
        raw.get("spec_content"),
        delimiter=raw.get("csv_delimiter"),
        has_header_row=raw.get("csv_has_header_row"),
    )
    if updated_spec is not None:
        updated["spec_content"] = updated_spec
    return updated


def _upsert_yaml_scalar(lines: list[str], key: str, rendered_value: str) -> list[str]:
    pattern = re.compile(rf"^(\s*){re.escape(key)}\s*:")
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if match:
            updated = list(lines)
            updated[index] = f"{match.group(1)}{key}: {rendered_value}"
            return updated

    insert_at = 0
    for index, line in enumerate(lines):
        if re.match(r"^\s*format\s*:", line):
            insert_at = index + 1
            break
    updated = list(lines)
    updated.insert(insert_at, f"{key}: {rendered_value}")
    return updated


def _yaml_scalar_for_csv_delimiter(delimiter: str) -> str:
    if delimiter == "\t":
        return "tab"
    escaped = delimiter.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def package_path_error(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    normalized_input = text.replace("\\", "/")
    if normalized_input.startswith("/") or re.match(r"^[A-Za-z]:/", normalized_input):
        return "Package artifact paths must be relative, not absolute."
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", normalized_input):
        return "Package artifact paths must be package-relative files, not URLs."
    path = PurePosixPath(normalized_input)
    if any(part == ".." for part in path.parts):
        return "Package artifact paths cannot contain '..'."
    if str(path) in {"", "."}:
        return "Package artifact path is empty."
    return None


def clean_package_path(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    if error := package_path_error(text):
        raise ValueError(error)
    return PurePosixPath(text.replace("\\", "/")).as_posix()


def default_artifact_path(direction: str, name: str, contract_type: str) -> str:
    base = "upstream" if direction == "upstream" else "downstream"
    suffix = {
        FILE_FIXED_WIDTH_TYPE: "layout.yaml",
        FILE_CSV_TYPE: "layout.yaml",
        XML_XSD_TYPE: "schema.xsd",
        SOAP_WSDL_TYPE: "contract.wsdl",
    }.get(contract_type, "contract.yaml")
    return f"{base}/{slug(name)}-{suffix}"


def default_sample_path(direction: str, name: str, contract_type: str) -> str:
    base = "upstream" if direction == "upstream" else "downstream"
    suffix = {
        FILE_FIXED_WIDTH_TYPE: "sample.txt",
        FILE_CSV_TYPE: "sample.csv",
        XML_XSD_TYPE: "sample.xml",
        SOAP_WSDL_TYPE: "sample.xml",
    }.get(contract_type, "sample.txt")
    return f"{base}/{slug(name)}-{suffix}"


def default_soap_operation_mapping_path(interface_name: str) -> str:
    return f"mappings/{slug(interface_name)}-operation-mapping.yaml"


def default_upstream_file_mapping_path(interface_name: str) -> str:
    return f"upstream/{slug(interface_name)}-mapping.yaml"


def default_downstream_file_mapping_path(interface_name: str) -> str:
    return f"downstream/{slug(interface_name)}-mapping.yaml"


def default_upstream_xml_mapping_path(interface_name: str) -> str:
    return f"upstream/{slug(interface_name)}-mapping.yaml"


def default_downstream_xml_mapping_path(interface_name: str) -> str:
    return f"downstream/{slug(interface_name)}-mapping.yaml"


def soap_operation_handler_method(operation_name: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", operation_name) if part]
    if not parts:
        return "handleSoapOperation"
    pascal = "".join(part[:1].upper() + part[1:] for part in parts)
    if pascal[0].isdigit():
        pascal = f"Operation{pascal}"
    return f"handle{pascal}"


def _clean_response_mappings(rows: Any) -> list[SoapResponseMapping]:
    mappings: list[SoapResponseMapping] = []
    if not isinstance(rows, list):
        return mappings
    for row in rows:
        if not isinstance(row, dict):
            continue
        source = clean_text(row.get("source"))
        target_path = clean_text(row.get("target_path") or row.get("target"))
        if source and target_path:
            mappings.append(SoapResponseMapping(source=source, target_path=target_path))
    return mappings


def _clean_request_path_mappings(rows: Any) -> list[SoapRequestMapping]:
    mappings: list[SoapRequestMapping] = []
    if not isinstance(rows, list):
        return mappings
    for row in rows:
        if not isinstance(row, dict):
            continue
        source = clean_text(row.get("source"))
        target_path = clean_text(row.get("target_path") or row.get("target"))
        if source and target_path:
            mappings.append(SoapRequestMapping(source=source, target_path=target_path))
    return mappings


def _clean_return_mappings(rows: Any) -> list[SoapReturnMapping]:
    mappings: list[SoapReturnMapping] = []
    if not isinstance(rows, list):
        return mappings
    for row in rows:
        if not isinstance(row, dict):
            continue
        source_path = clean_text(row.get("source_path") or row.get("source"))
        target = clean_text(row.get("target"))
        if source_path and target:
            mappings.append(SoapReturnMapping(source_path=source_path, target=target))
    return mappings


def _has_canonical_config_values(raw: dict[str, Any]) -> bool:
    config = raw.get("soap_canonical_operation")
    if not isinstance(config, dict):
        return False
    scalar_keys = (
        "kind",
        "entity",
        "lookup_field",
        "request_path",
        "not_found_fault",
        "not_found_message",
    )
    if any(clean_text(config.get(key)) for key in scalar_keys):
        return True
    lookup = config.get("lookup")
    if isinstance(lookup, dict) and any(clean_text(value) for value in lookup.values()):
        return True
    fault = config.get("not_found_fault")
    if isinstance(fault, dict) and any(clean_text(value) for value in fault.values()):
        return True
    rows = config.get("response_mappings", [])
    if not isinstance(rows, list):
        return False
    return any(
        isinstance(row, dict)
        and (clean_text(row.get("source")) or clean_text(row.get("target_path") or row.get("target")))
        for row in rows
    )


def _has_canonical_invocation_values(raw: dict[str, Any]) -> bool:
    config = raw.get("soap_canonical_invocation")
    if not isinstance(config, dict):
        return False
    scalar_keys = ("kind", "entity", "lookup_field", "request_field", "response_mode")
    if any(clean_text(config.get(key)) for key in scalar_keys):
        return True
    lookup = config.get("lookup")
    if isinstance(lookup, dict) and any(clean_text(value) for value in lookup.values()):
        return True
    response = config.get("response")
    if isinstance(response, dict):
        if clean_text(response.get("mode")):
            return True
        response_rows = response.get("response_mappings", [])
        if isinstance(response_rows, list) and any(
            isinstance(row, dict)
            and (clean_text(row.get("source_path") or row.get("source")) or clean_text(row.get("target")))
            for row in response_rows
        ):
            return True
    request_rows = config.get("request_mappings", [])
    if isinstance(request_rows, list) and any(
        isinstance(row, dict)
        and (clean_text(row.get("source")) or clean_text(row.get("target_path") or row.get("target")))
        for row in request_rows
    ):
        return True
    response_rows = config.get("response_mappings", [])
    if isinstance(response_rows, list) and any(
        isinstance(row, dict)
        and (clean_text(row.get("source_path") or row.get("source")) or clean_text(row.get("target")))
        for row in response_rows
    ):
        return True
    return False


def soap_canonical_operation_from_payload(raw: dict[str, Any]) -> SoapCanonicalOperationConfig | None:
    config = raw.get("soap_canonical_operation")
    if not isinstance(config, dict):
        return None
    lookup = config.get("lookup") if isinstance(config.get("lookup"), dict) else {}
    fault = config.get("not_found_fault") if isinstance(config.get("not_found_fault"), dict) else {}
    response_mappings = _clean_response_mappings(config.get("response_mappings"))
    normalized = SoapCanonicalOperationConfig(
        kind=clean_text(config.get("kind")) or SOAP_CANONICAL_KIND_READ_BY_ID,
        entity=clean_text(config.get("entity")),
        lookup_field=clean_text(config.get("lookup_field") or lookup.get("field")),
        request_path=clean_text(config.get("request_path") or lookup.get("request_path")),
        response_mappings=response_mappings,
        not_found_fault=clean_text(
            config.get("not_found_fault")
            if not isinstance(config.get("not_found_fault"), dict)
            else fault.get("fault")
        ),
        not_found_message=clean_text(config.get("not_found_message") or fault.get("message")),
    )
    if (
        normalized.entity
        or normalized.lookup_field
        or normalized.request_path
        or normalized.response_mappings
        or normalized.not_found_fault
        or normalized.not_found_message
        or normalized.kind != SOAP_CANONICAL_KIND_READ_BY_ID
    ):
        return normalized
    return None


def soap_canonical_invocation_from_payload(raw: dict[str, Any]) -> SoapCanonicalInvocationConfig | None:
    config = raw.get("soap_canonical_invocation")
    if not isinstance(config, dict):
        return None
    lookup = config.get("lookup") if isinstance(config.get("lookup"), dict) else {}
    response = config.get("response") if isinstance(config.get("response"), dict) else {}
    request_mappings = _clean_request_path_mappings(config.get("request_mappings"))
    response_mappings = _clean_return_mappings(
        response.get("response_mappings")
        if isinstance(response, dict) and "response_mappings" in response
        else config.get("response_mappings")
    )
    normalized = SoapCanonicalInvocationConfig(
        kind=clean_text(config.get("kind")) or SOAP_CANONICAL_KIND_INVOKE_BY_ID,
        entity=clean_text(config.get("entity")),
        lookup_field=clean_text(config.get("lookup_field") or lookup.get("field")),
        request_field=clean_text(config.get("request_field") or lookup.get("request_field")) or "id",
        request_mappings=request_mappings,
        response_mode=clean_text(config.get("response_mode") or response.get("mode"))
        or SOAP_RESPONSE_MODE_RETURN_ONLY,
        response_mappings=response_mappings,
    )
    if (
        normalized.entity
        or normalized.lookup_field
        or normalized.request_field != "id"
        or normalized.request_mappings
        or normalized.response_mode != SOAP_RESPONSE_MODE_RETURN_ONLY
        or normalized.response_mappings
        or normalized.kind != SOAP_CANONICAL_KIND_INVOKE_BY_ID
    ):
        return normalized
    return None


def _entity_field_inventory(session: Any) -> dict[str, set[str]]:
    inventory: dict[str, set[str]] = {}
    for entity in getattr(session, "classified_entities", []) or []:
        names = {getattr(entity, "name", None), getattr(entity, "canonical_name", None)}
        display_name = entity.display_name() if hasattr(entity, "display_name") else None
        names.add(display_name)
        fields = {
            getattr(field, "name", "")
            for field in getattr(entity, "fields", []) or []
            if getattr(field, "name", "")
        }
        for name in names:
            if name:
                inventory.setdefault(str(name), set()).update(fields)
    return inventory


def _safe_persistence_fields(session: Any, entity_name: str) -> set[str]:
    fields: set[str] = set()
    for decision in getattr(session, "identity_role_decisions", []) or []:
        if getattr(decision, "entity", None) == entity_name and getattr(decision, "role", None) == "persistence_id":
            field = getattr(decision, "field", None)
            if field:
                fields.add(field)
    for entity in getattr(session, "classified_entities", []) or []:
        names = {getattr(entity, "name", None), getattr(entity, "canonical_name", None)}
        if hasattr(entity, "display_name"):
            names.add(entity.display_name())
        if entity_name not in names:
            continue
        for field in getattr(entity, "fields", []) or []:
            if getattr(field, "is_id", False) and getattr(field, "name", None):
                fields.add(field.name)
    return fields


def _validate_soap_canonical_config(
    config: SoapCanonicalOperationConfig,
    *,
    session: Any = None,
) -> list[str]:
    errors: list[str] = []
    if config.kind != SOAP_CANONICAL_KIND_READ_BY_ID:
        errors.append("Canonical SOAP operation kind must be read_by_id.")
    if not config.entity:
        errors.append("Canonical SOAP read_by_id mapping requires a canonical entity.")
    if not config.lookup_field:
        errors.append("Canonical SOAP read_by_id mapping requires a lookup field.")
    if not config.request_path:
        errors.append("Canonical SOAP read_by_id mapping requires a request path.")
    if not config.response_mappings:
        errors.append("Canonical SOAP read_by_id mapping requires at least one response mapping.")
    for mapping in config.response_mappings:
        if "." not in mapping.source:
            errors.append(f"SOAP response source '{mapping.source}' must be a canonical path like Entity.field.")
        elif config.entity:
            source_entity, _ = mapping.source.split(".", 1)
            if source_entity != config.entity:
                errors.append(
                    f"SOAP response source '{mapping.source}' must use canonical entity '{config.entity}'."
                )
        if not mapping.target_path.startswith("/"):
            errors.append(f"SOAP response target path '{mapping.target_path}' must start with '/'.")
    if config.request_path and not config.request_path.startswith("/"):
        errors.append(f"SOAP lookup request path '{config.request_path}' must start with '/'.")

    if session is None:
        errors.append("Canonical SOAP read_by_id mapping requires a known canonical entity model.")
        errors.append("Canonical SOAP read_by_id mapping requires a verified persistence ID field.")
        return errors

    inventory = _entity_field_inventory(session)
    if not inventory:
        errors.append("Canonical SOAP read_by_id mapping requires a known canonical entity model.")
        errors.append("Canonical SOAP read_by_id mapping requires a verified persistence ID field.")
        return errors

    if not config.entity:
        return errors
    if config.entity not in inventory:
        errors.append(f"Unknown canonical entity '{config.entity}' for SOAP canonical mapping.")
        return errors

    fields = inventory.get(config.entity, set())
    if fields and config.lookup_field and config.lookup_field not in fields:
        errors.append(f"Unknown lookup field '{config.lookup_field}' on canonical entity '{config.entity}'.")

    persistence_fields = _safe_persistence_fields(session, config.entity)
    if not persistence_fields:
        errors.append(
            f"Canonical SOAP read_by_id mapping requires a reviewed persistence ID or classified ID field for {config.entity}."
        )
    elif config.lookup_field and config.lookup_field not in persistence_fields:
        errors.append(
            f"SOAP read_by_id lookup field '{config.lookup_field}' should use the reviewed persistence ID field "
            f"for {config.entity}: {', '.join(sorted(persistence_fields))}."
        )

    for mapping in config.response_mappings:
        if "." not in mapping.source:
            continue
        source_entity, source_field = mapping.source.split(".", 1)
        source_fields = inventory.get(source_entity, set())
        if source_fields and source_field and source_field not in source_fields:
            errors.append(f"Unknown SOAP response mapping field '{source_field}' on canonical entity '{source_entity}'.")
    return errors


def _validate_canonical_source_path(
    source: str,
    *,
    expected_entity: str | None,
    inventory: dict[str, set[str]] | None = None,
    label: str,
) -> list[str]:
    errors: list[str] = []
    if "." not in source:
        errors.append(f"{label} source '{source}' must be a canonical path like Entity.field.")
        return errors
    source_entity, source_field = source.split(".", 1)
    if expected_entity and source_entity != expected_entity:
        errors.append(f"{label} source '{source}' must use canonical entity '{expected_entity}'.")
    if inventory is not None:
        source_fields = inventory.get(source_entity, set())
        if source_fields and source_field and source_field not in source_fields:
            errors.append(f"Unknown {label} field '{source_field}' on canonical entity '{source_entity}'.")
    return errors


def _is_supported_soap_canonical_path(path: str) -> bool:
    parts = path.split("/")
    return len(parts) == 3 and parts[0] == "" and bool(parts[1]) and bool(parts[2])


def _soap_field_path(field: Any) -> str | None:
    if not isinstance(field, dict):
        return None
    return clean_text(
        field.get("path")
        or field.get("target_path")
        or field.get("source_path")
        or field.get("xpath")
    )


def _soap_fields_by_path(fields: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(fields, list):
        return {}
    by_path: dict[str, dict[str, Any]] = {}
    for soap_field in fields:
        if not isinstance(soap_field, dict):
            continue
        path = _soap_field_path(soap_field)
        if path:
            by_path[path] = soap_field
    return by_path


def _soap_field_is_required(field: dict[str, Any]) -> bool:
    if isinstance(field.get("required"), bool):
        return bool(field.get("required"))
    min_occurs = clean_text(field.get("min_occurs") or field.get("minOccurs"))
    if min_occurs is not None:
        return min_occurs != "0"
    return False


def _soap_field_is_repeated(field: dict[str, Any]) -> bool:
    if isinstance(field.get("repeated"), bool):
        return bool(field.get("repeated"))
    max_occurs = clean_text(field.get("max_occurs") or field.get("maxOccurs"))
    return bool(max_occurs and max_occurs not in {"0", "1"})


def _soap_field_type(field: dict[str, Any]) -> str | None:
    value = clean_text(field.get("type") or field.get("xml_type") or field.get("xsd_type"))
    if not value:
        return None
    value = value.split(":", 1)[-1].lower()
    if value in {"int", "integer", "long", "decimal", "boolean", "date", "datetime", "string"}:
        return value
    return value


def _find_soap_operation_metadata(raw: dict[str, Any], operation: str | None) -> dict[str, Any] | None:
    if not operation:
        return None
    for key in ("soap_operation_metadata", "operation_metadata"):
        value = raw.get(key)
        if isinstance(value, dict):
            if isinstance(value.get(operation), dict):
                return value[operation]
            name = clean_text(value.get("name") or value.get("operation"))
            if name == operation or (not name and ("input_fields" in value or "output_fields" in value)):
                return value
    for key in ("soap_operation_candidates", "operation_candidates", "operations"):
        value = raw.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            name = clean_text(item.get("name") or item.get("operation"))
            if name != operation:
                continue
            metadata = item.get("metadata")
            if isinstance(metadata, dict):
                merged = dict(metadata)
                merged.setdefault("name", name)
                return merged
            return item
    return None


def _entity_field_details(session: Any) -> dict[str, dict[str, dict[str, Any]]]:
    details: dict[str, dict[str, dict[str, Any]]] = {}
    for entity in getattr(session, "classified_entities", []) or []:
        names = {getattr(entity, "name", None), getattr(entity, "canonical_name", None)}
        if hasattr(entity, "display_name"):
            names.add(entity.display_name())
        fields: dict[str, dict[str, Any]] = {}
        for entity_field in getattr(entity, "fields", []) or []:
            field_name = getattr(entity_field, "name", None)
            if not field_name:
                continue
            fields[field_name] = {
                "type": clean_text(getattr(entity_field, "type", None)),
                "enum_values": list(getattr(entity_field, "enum_values", []) or []),
            }
        for name in names:
            if name:
                details[str(name)] = fields
    return details


def _canonical_field_detail(
    source: str,
    *,
    field_details: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any] | None:
    if "." not in source:
        return None
    entity, field = source.split(".", 1)
    return field_details.get(entity, {}).get(field)


def _soap_types_compatible(xml_type: str | None, canonical_type: str | None) -> bool:
    if not xml_type or not canonical_type:
        return True
    xml = xml_type.lower()
    canonical = canonical_type.lower()
    if xml == "string":
        return True
    if xml in {"integer", "int", "long"}:
        return canonical in {"string", "integer"}
    if xml == "decimal":
        return canonical in {"string", "integer", "decimal"}
    if xml == "boolean":
        return canonical in {"string", "boolean"}
    if xml == "date":
        return canonical in {"string", "date"}
    if xml == "datetime":
        return canonical in {"string", "datetime"}
    return True


def _validate_soap_canonical_invocation_config(
    config: SoapCanonicalInvocationConfig,
    *,
    session: Any = None,
    operation_metadata: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    input_fields = _soap_fields_by_path(operation_metadata.get("input_fields") if operation_metadata else None)
    output_fields = _soap_fields_by_path(operation_metadata.get("output_fields") if operation_metadata else None)
    field_details = _entity_field_details(session) if session is not None else {}

    if config.kind != SOAP_CANONICAL_KIND_INVOKE_BY_ID:
        errors.append("Canonical downstream SOAP operation kind must be invoke_by_id.")
    if not config.entity:
        errors.append("Canonical downstream SOAP invoke_by_id mapping requires a canonical entity.")
    if not config.lookup_field:
        errors.append("Canonical downstream SOAP invoke_by_id mapping requires a lookup field.")
    if config.request_field != "id":
        errors.append("Canonical downstream SOAP invoke_by_id lookup request field must be id.")
    if not config.request_mappings:
        errors.append("Canonical downstream SOAP invoke_by_id mapping requires at least one request mapping.")
    if config.response_mode != SOAP_RESPONSE_MODE_RETURN_ONLY:
        errors.append("Canonical downstream SOAP invoke_by_id response mode must be return_only.")
    if not config.response_mappings:
        errors.append("Canonical downstream SOAP invoke_by_id mapping requires at least one response mapping.")

    request_sources: set[str] = set()
    request_targets: set[str] = set()
    for mapping in config.request_mappings:
        errors.extend(
            _validate_canonical_source_path(
                mapping.source,
                expected_entity=config.entity,
                inventory=None,
                label="SOAP request mapping",
            )
        )
        if mapping.source in request_sources:
            errors.append(f"SOAP request mapping source '{mapping.source}' is used more than once.")
        request_sources.add(mapping.source)
        if mapping.target_path in request_targets:
            errors.append(f"SOAP request mapping target path '{mapping.target_path}' is used more than once.")
        request_targets.add(mapping.target_path)
        if not _is_supported_soap_canonical_path(mapping.target_path):
            errors.append(
                f"SOAP request mapping target path '{mapping.target_path}' must be a flat SOAP path like /Message/field."
            )
            continue
        if input_fields:
            soap_field = input_fields.get(mapping.target_path)
            if soap_field is None:
                errors.append(f"Unknown SOAP request mapping target path '{mapping.target_path}' for selected operation.")
            else:
                if _soap_field_is_repeated(soap_field):
                    errors.append(f"SOAP request mapping target path '{mapping.target_path}' is repeated and unsupported.")
                canonical_detail = _canonical_field_detail(mapping.source, field_details=field_details)
                if canonical_detail and not _soap_types_compatible(
                    _soap_field_type(soap_field),
                    canonical_detail.get("type"),
                ):
                    errors.append(
                        f"SOAP request mapping source '{mapping.source}' type '{canonical_detail.get('type')}' "
                        f"is not compatible with SOAP target path '{mapping.target_path}' type '{_soap_field_type(soap_field)}'."
                    )

    if input_fields:
        for path, field in input_fields.items():
            if _soap_field_is_required(field) and path not in request_targets:
                errors.append(f"Required SOAP request field '{path}' is not mapped.")

    response_sources: set[str] = set()
    response_targets: set[str] = set()
    for mapping in config.response_mappings:
        if mapping.source_path in response_sources:
            errors.append(f"SOAP response mapping source path '{mapping.source_path}' is used more than once.")
        response_sources.add(mapping.source_path)
        if not _is_supported_soap_canonical_path(mapping.source_path):
            errors.append(
                f"SOAP response mapping source path '{mapping.source_path}' must be a flat SOAP path like /Message/field."
            )
            continue
        if output_fields:
            soap_field = output_fields.get(mapping.source_path)
            if soap_field is None:
                errors.append(f"Unknown SOAP response mapping source path '{mapping.source_path}' for selected operation.")
            elif _soap_field_is_repeated(soap_field):
                errors.append(f"SOAP response mapping source path '{mapping.source_path}' is repeated and unsupported.")
        if not mapping.target:
            errors.append("SOAP response mapping target is required.")
        elif not _SOAP_RESPONSE_TARGET_RE.match(mapping.target):
            errors.append(
                f"SOAP response mapping target '{mapping.target}' is not a supported response field name."
            )
        elif mapping.target in response_targets:
            errors.append(f"SOAP response mapping target '{mapping.target}' is used more than once.")
        response_targets.add(mapping.target)

    if output_fields:
        for path, field in output_fields.items():
            if _soap_field_is_required(field) and path not in response_sources:
                errors.append(f"Required SOAP response field '{path}' is not mapped.")

    if session is None:
        errors.append("Canonical downstream SOAP invoke_by_id mapping requires a known canonical entity model.")
        errors.append("Canonical downstream SOAP invoke_by_id mapping requires a verified persistence ID field.")
        return errors

    inventory = _entity_field_inventory(session)
    if not inventory:
        errors.append("Canonical downstream SOAP invoke_by_id mapping requires a known canonical entity model.")
        errors.append("Canonical downstream SOAP invoke_by_id mapping requires a verified persistence ID field.")
        return errors

    if not config.entity:
        return errors
    if config.entity not in inventory:
        errors.append(f"Unknown canonical entity '{config.entity}' for downstream SOAP canonical mapping.")
        return errors

    fields = inventory.get(config.entity, set())
    if fields and config.lookup_field and config.lookup_field not in fields:
        errors.append(f"Unknown lookup field '{config.lookup_field}' on canonical entity '{config.entity}'.")

    persistence_fields = _safe_persistence_fields(session, config.entity)
    if not persistence_fields:
        errors.append(
            f"Canonical downstream SOAP invoke_by_id mapping requires a reviewed persistence ID or classified ID field for {config.entity}."
        )
    elif config.lookup_field and config.lookup_field not in persistence_fields:
        errors.append(
            f"SOAP invoke_by_id lookup field '{config.lookup_field}' should use the reviewed persistence ID field "
            f"for {config.entity}: {', '.join(sorted(persistence_fields))}."
        )

    for mapping in config.request_mappings:
        errors.extend(
            _validate_canonical_source_path(
                mapping.source,
                expected_entity=config.entity,
                inventory=inventory,
                label="SOAP request mapping",
            )
        )
    return errors


def validate_soap_operation_mapping_payload(raw: dict[str, Any], *, session: Any = None) -> list[str]:
    errors: list[str] = []
    operation = clean_text(raw.get("selected_operation_name") or raw.get("operation"))
    mode = clean_text(raw.get("soap_operation_mode")) or SOAP_MAPPING_MODE_ADAPTER_ONLY
    if mode not in SOAP_MAPPING_MODES:
        errors.append("SOAP operation mapping mode must be adapter_only or canonical.")
        return errors

    has_canonical_config = _has_canonical_config_values(raw)
    if not operation:
        if mode == SOAP_MAPPING_MODE_CANONICAL or has_canonical_config:
            errors.append("Select a SOAP operation before configuring canonical operation mapping.")
        return errors

    if mode == SOAP_MAPPING_MODE_ADAPTER_ONLY:
        if has_canonical_config:
            errors.append("Adapter-only SOAP operation mappings cannot include canonical operation configuration.")
        return errors

    config = soap_canonical_operation_from_payload(raw)
    if config is None:
        errors.append("Canonical SOAP operation mappings require canonical operation configuration.")
        return errors
    errors.extend(_validate_soap_canonical_config(config, session=session))
    return errors


def validate_downstream_soap_operation_mapping_payload(raw: dict[str, Any], *, session: Any = None) -> list[str]:
    errors: list[str] = []
    operation = clean_text(raw.get("selected_operation_name") or raw.get("operation"))
    mode = clean_text(raw.get("soap_operation_mode")) or SOAP_MAPPING_MODE_ADAPTER_ONLY
    if mode not in SOAP_MAPPING_MODES:
        errors.append("Downstream SOAP operation mapping mode must be adapter_only or canonical.")
        return errors

    has_canonical_config = _has_canonical_invocation_values(raw)
    if not operation:
        if mode == SOAP_MAPPING_MODE_CANONICAL or has_canonical_config:
            errors.append("Select a downstream SOAP operation before configuring canonical invocation mapping.")
        return errors

    candidates = raw.get("soap_operation_candidates") or raw.get("operation_candidates")
    if isinstance(candidates, list):
        known = {
            clean_text(item.get("name") if isinstance(item, dict) else item)
            for item in candidates
        }
        known.discard(None)
        if known and operation not in known:
            errors.append(f"Unknown downstream SOAP operation '{operation}' for this WSDL.")

    if mode == SOAP_MAPPING_MODE_ADAPTER_ONLY:
        if has_canonical_config:
            errors.append("Adapter-only downstream SOAP operation mappings cannot include canonical invocation configuration.")
        return errors

    config = soap_canonical_invocation_from_payload(raw)
    if config is None:
        errors.append("Canonical downstream SOAP operation mappings require canonical invocation configuration.")
        return errors
    operation_metadata = _find_soap_operation_metadata(raw, operation)
    errors.extend(
        _validate_soap_canonical_invocation_config(
            config,
            session=session,
            operation_metadata=operation_metadata,
        )
    )
    return errors


def _soap_canonical_required_missing(iface: UpstreamInterface, *, session: Any = None) -> list[str]:
    config = iface.soap_canonical_operation
    if iface.soap_operation_mode != SOAP_MAPPING_MODE_CANONICAL:
        return []
    missing: list[str] = []
    if config is None:
        return ["canonical operation config"]
    if config.kind != SOAP_CANONICAL_KIND_READ_BY_ID:
        missing.append("read_by_id canonical kind")
    if not config.entity:
        missing.append("canonical entity")
    if not config.lookup_field:
        missing.append("lookup field")
    if not config.request_path:
        missing.append("request path")
    if not config.response_mappings:
        missing.append("response mappings")
    if missing:
        return missing

    validation_errors = _validate_soap_canonical_config(config, session=session)
    if validation_errors:
        missing.append("valid canonical operation mapping: " + "; ".join(validation_errors))
    return missing


def _soap_invocation_required_missing(iface: DownstreamInterface, *, session: Any = None) -> list[str]:
    if iface.soap_operation_mode != SOAP_MAPPING_MODE_CANONICAL:
        return []
    config = iface.soap_canonical_invocation
    missing: list[str] = []
    if config is None:
        return ["canonical invocation config"]
    if config.kind != SOAP_CANONICAL_KIND_INVOKE_BY_ID:
        missing.append("invoke_by_id canonical kind")
    if not config.entity:
        missing.append("canonical entity")
    if not config.lookup_field:
        missing.append("lookup field")
    if config.request_field != "id":
        missing.append("lookup request field id")
    if not config.request_mappings:
        missing.append("request mappings")
    if config.response_mode != SOAP_RESPONSE_MODE_RETURN_ONLY:
        missing.append("return_only response mode")
    if not config.response_mappings:
        missing.append("response mappings")
    if missing:
        return missing

    validation_errors = _validate_soap_canonical_invocation_config(config, session=session)
    if validation_errors:
        missing.append("valid canonical invocation mapping: " + "; ".join(validation_errors))
    return missing


def required_artifact_path(raw: dict[str, Any], direction: str, name: str, contract_type: str) -> str | None:
    if contract_type == XML_XSD_TYPE:
        return clean_package_path(raw.get("xsd_path")) or (
            default_artifact_path(direction, name, contract_type) if clean_text(raw.get("xsd_content")) else None
        )
    if contract_type == SOAP_WSDL_TYPE:
        return clean_package_path(raw.get("wsdl_path")) or (
            default_artifact_path(direction, name, contract_type) if clean_text(raw.get("wsdl_content")) else None
        )
    if contract_type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE}:
        return clean_package_path(raw.get("spec")) or (
            default_artifact_path(direction, name, contract_type) if clean_text(raw.get("spec_content")) else None
        )
    return clean_package_path(raw.get("spec"))


def validate_edge_contract_payload(raw: dict[str, Any], *, direction: str, session: Any = None) -> list[str]:
    errors: list[str] = []
    if direction not in {"upstream", "downstream"}:
        errors.append("Contract direction must be upstream or downstream.")

    name = clean_text(raw.get("name"))
    if not name:
        errors.append("Interface name is required.")

    contract_type = clean_text(raw.get("type")) or ""
    if not contract_type:
        errors.append("Select a contract type before saving.")
        return errors
    if contract_type not in SUPPORTED_INTERFACE_TYPES:
        errors.append(f"Unknown contract type '{contract_type}'.")
        return errors

    if contract_type == REST_OPENAPI_TYPE:
        return errors

    if contract_type not in EDGE_CONTRACT_TYPES:
        errors.append(f"Unsupported contract type '{contract_type}'.")
        return errors

    if raw.get("spec_url"):
        errors.append(f"{contract_type} contracts use package-relative files, not spec_url.")

    path_fields = {
        "spec": "Layout/spec path",
        "xsd_path": "XSD path",
        "wsdl_path": "WSDL path",
        "sample_path": "Sample path",
        "mapping_path": "Mapping path",
        "mapping": "Mapping path",
    }
    for key, label in path_fields.items():
        if error := package_path_error(raw.get(key)):
            errors.append(f"{label}: {error}")

    if not name:
        return errors

    try:
        artifact = required_artifact_path(raw, direction, name, contract_type)
    except ValueError:
        artifact = None
    if not artifact:
        if contract_type == XML_XSD_TYPE:
            errors.append("XML/XSD contracts require xsd_path or uploaded XSD content.")
        elif contract_type == SOAP_WSDL_TYPE:
            errors.append("SOAP/WSDL contracts require wsdl_path or uploaded WSDL content.")
        else:
            errors.append("File contracts require a layout/spec path or uploaded layout/spec content.")

    if contract_type == XML_XSD_TYPE and not clean_text(raw.get("root_element")):
        errors.append("XML/XSD contracts require a root element.")

    if contract_type == SOAP_WSDL_TYPE:
        if direction == "upstream":
            errors.extend(validate_soap_operation_mapping_payload(raw, session=session))
        else:
            errors.extend(validate_downstream_soap_operation_mapping_payload(raw, session=session))

    if contract_type == FILE_CSV_TYPE and direction == "downstream" and clean_text(raw.get("spec_content")):
        from app.services.csv_layout import CsvLayoutError, prepare_csv_layout_for_export

        try:
            prepare_csv_layout_for_export(raw.get("spec_content"), name=name)
        except CsvLayoutError as exc:
            errors.append(str(exc))

    return errors


def upstream_interface_from_payload(raw: dict[str, Any]) -> UpstreamInterface:
    name = clean_text(raw.get("name")) or "upstream-contract"
    contract_type = clean_text(raw.get("type")) or FILE_FIXED_WIDTH_TYPE
    sample_content = clean_text(raw.get("sample_content"))
    sample_path = clean_package_path(raw.get("sample_path")) or (
        default_sample_path("upstream", name, contract_type) if sample_content else None
    )
    spec = (
        required_artifact_path(raw, "upstream", name, contract_type)
        if contract_type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE}
        else clean_path(raw.get("spec"))
    )
    xsd_path = required_artifact_path(raw, "upstream", name, contract_type) if contract_type == XML_XSD_TYPE else None
    wsdl_path = required_artifact_path(raw, "upstream", name, contract_type) if contract_type == SOAP_WSDL_TYPE else None
    selected_operation_name = (
        clean_text(raw.get("selected_operation_name") or raw.get("operation"))
        if contract_type == SOAP_WSDL_TYPE
        else None
    )
    soap_operation_mode = SOAP_MAPPING_MODE_ADAPTER_ONLY
    if contract_type == SOAP_WSDL_TYPE:
        soap_operation_mode = clean_text(raw.get("soap_operation_mode")) or SOAP_MAPPING_MODE_ADAPTER_ONLY
    soap_canonical_operation = (
        soap_canonical_operation_from_payload(raw)
        if contract_type == SOAP_WSDL_TYPE and soap_operation_mode == SOAP_MAPPING_MODE_CANONICAL
        else None
    )
    field_mappings = []
    for mapping in raw.get("field_mappings", []):
        if not isinstance(mapping, dict):
            continue
        source = clean_text(mapping.get("source"))
        target = clean_text(mapping.get("target"))
        if source and target:
            field_mappings.append(FieldMapping(source=source, target=target))
    entity_name = clean_text(raw.get("entity_name"))
    has_exportable_field_mappings = (
        contract_type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE, XML_XSD_TYPE}
        and bool(field_mappings)
        and bool(entity_name)
    )

    return UpstreamInterface(
        name=name,
        system=clean_text(raw.get("system")),
        type=contract_type,
        version=clean_text(raw.get("version")),
        spec=spec,
        spec_url=None,
        spec_content=clean_text(raw.get("spec_content")) if contract_type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE} else None,
        mapping_path=(
            clean_package_path(raw.get("mapping_path") or raw.get("mapping"))
            or (default_soap_operation_mapping_path(name) if selected_operation_name else None)
            or (
                default_upstream_file_mapping_path(name)
                if has_exportable_field_mappings
                and contract_type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE}
                else None
            )
            or (
                default_upstream_xml_mapping_path(name)
                if has_exportable_field_mappings and contract_type == XML_XSD_TYPE
                else None
            )
        ),
        entity_name=entity_name,
        operations=[OperationSample(name=selected_operation_name)] if selected_operation_name else [],
        xsd_path=xsd_path,
        xsd_content=clean_text(raw.get("xsd_content")) if contract_type == XML_XSD_TYPE else None,
        root_element=clean_text(raw.get("root_element")) if contract_type == XML_XSD_TYPE else None,
        namespace=clean_text(raw.get("namespace")) if contract_type == XML_XSD_TYPE else None,
        namespace_alias=clean_text(raw.get("namespace_alias")) if contract_type == XML_XSD_TYPE else None,
        wsdl_path=wsdl_path,
        wsdl_content=clean_text(raw.get("wsdl_content")) if contract_type == SOAP_WSDL_TYPE else None,
        service=clean_text(raw.get("service")) if contract_type == SOAP_WSDL_TYPE else None,
        port=clean_text(raw.get("port")) if contract_type == SOAP_WSDL_TYPE else None,
        binding=clean_text(raw.get("binding")) if contract_type == SOAP_WSDL_TYPE else None,
        soap_operation_mode=soap_operation_mode,
        soap_handler_method=clean_text(raw.get("soap_handler_method")) if contract_type == SOAP_WSDL_TYPE else None,
        soap_canonical_operation=soap_canonical_operation,
        selected_operation_name=selected_operation_name,
        field_mappings=field_mappings if contract_type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE, XML_XSD_TYPE} else [],
        sample_path=sample_path,
        sample_content=sample_content,
    )


def downstream_interface_from_payload(raw: dict[str, Any], *, layout_fields=None, field_mappings=None) -> DownstreamInterface:
    name = clean_text(raw.get("name")) or "downstream-contract"
    contract_type = clean_text(raw.get("type")) or FILE_FIXED_WIDTH_TYPE
    sample_content = clean_text(raw.get("sample_content"))
    sample_path = clean_package_path(raw.get("sample_path")) or (
        default_sample_path("downstream", name, contract_type) if sample_content else None
    )
    spec = (
        required_artifact_path(raw, "downstream", name, contract_type)
        if contract_type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE}
        else clean_path(raw.get("spec"))
    )
    xsd_path = required_artifact_path(raw, "downstream", name, contract_type) if contract_type == XML_XSD_TYPE else None
    wsdl_path = required_artifact_path(raw, "downstream", name, contract_type) if contract_type == SOAP_WSDL_TYPE else None
    clean_field_mappings = list(field_mappings or [])
    entity_name = clean_text(raw.get("entity_name"))
    has_exportable_field_mappings = bool(clean_field_mappings) and bool(entity_name)
    selected_operation_name = (
        clean_text(raw.get("selected_operation_name") or raw.get("operation"))
        if contract_type == SOAP_WSDL_TYPE
        else None
    )
    soap_operation_mode = SOAP_MAPPING_MODE_ADAPTER_ONLY
    if contract_type == SOAP_WSDL_TYPE:
        soap_operation_mode = clean_text(raw.get("soap_operation_mode")) or SOAP_MAPPING_MODE_ADAPTER_ONLY
    soap_canonical_invocation = (
        soap_canonical_invocation_from_payload(raw)
        if contract_type == SOAP_WSDL_TYPE and soap_operation_mode == SOAP_MAPPING_MODE_CANONICAL
        else None
    )

    return DownstreamInterface(
        name=name,
        system=clean_text(raw.get("system")),
        type=contract_type,
        version=clean_text(raw.get("version")),
        spec=spec,
        spec_url=None,
        spec_content=clean_text(raw.get("spec_content")) if contract_type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE} else None,
        layout_fields=list(layout_fields or []),
        mapping_path=(
            clean_package_path(raw.get("mapping_path") or raw.get("mapping"))
            or (
                default_downstream_xml_mapping_path(name)
                if contract_type == XML_XSD_TYPE and has_exportable_field_mappings
                else None
            )
            or (
                default_downstream_file_mapping_path(name)
                if contract_type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE} and clean_field_mappings
                else None
            )
            or (
                default_soap_operation_mapping_path(name)
                if contract_type == SOAP_WSDL_TYPE and selected_operation_name
                else None
            )
        ),
        field_mappings=clean_field_mappings,
        entity_name=entity_name,
        samples=[sample_path] if sample_path and contract_type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE} else [],
        sample_path=sample_path,
        sample_content=sample_content,
        xsd_path=xsd_path,
        xsd_content=clean_text(raw.get("xsd_content")) if contract_type == XML_XSD_TYPE else None,
        root_element=clean_text(raw.get("root_element")) if contract_type == XML_XSD_TYPE else None,
        namespace=clean_text(raw.get("namespace")) if contract_type == XML_XSD_TYPE else None,
        namespace_alias=clean_text(raw.get("namespace_alias")) if contract_type == XML_XSD_TYPE else None,
        wsdl_path=wsdl_path,
        wsdl_content=clean_text(raw.get("wsdl_content")) if contract_type == SOAP_WSDL_TYPE else None,
        service=clean_text(raw.get("service")) if contract_type == SOAP_WSDL_TYPE else None,
        port=clean_text(raw.get("port")) if contract_type == SOAP_WSDL_TYPE else None,
        binding=clean_text(raw.get("binding")) if contract_type == SOAP_WSDL_TYPE else None,
        selected_operation_name=selected_operation_name,
        soap_operation_mode=soap_operation_mode,
        soap_canonical_invocation=soap_canonical_invocation,
    )


def edge_contract_reference(iface: UpstreamInterface | DownstreamInterface) -> str | None:
    return iface.xsd_path or iface.wsdl_path or iface.spec or iface.spec_url


def _edge_contract_artifact_path(
    iface: UpstreamInterface | DownstreamInterface,
    direction: str,
) -> str | None:
    if iface.type == XML_XSD_TYPE:
        return iface.xsd_path or iface.spec or (
            default_artifact_path(direction, iface.name, iface.type) if iface.xsd_content else None
        )
    if iface.type == SOAP_WSDL_TYPE:
        return iface.wsdl_path or iface.spec or (
            default_artifact_path(direction, iface.name, iface.type) if iface.wsdl_content else None
        )
    if iface.type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE}:
        if iface.type == FILE_FIXED_WIDTH_TYPE and direction == "downstream":
            return iface.spec or default_artifact_path(direction, iface.name, iface.type)
        return iface.spec or (
            default_artifact_path(direction, iface.name, iface.type)
            if iface.spec_content or getattr(iface, "layout_fields", None)
            else None
        )
    return iface.spec


def _edge_contract_has_content(
    iface: UpstreamInterface | DownstreamInterface,
    direction: str,
) -> bool:
    if iface.type == XML_XSD_TYPE:
        return bool(iface.xsd_content)
    if iface.type == SOAP_WSDL_TYPE:
        return bool(iface.wsdl_content)
    if iface.type == FILE_CSV_TYPE:
        return bool(iface.spec_content)
    if iface.type == FILE_FIXED_WIDTH_TYPE:
        return bool(iface.spec_content or (direction == "downstream" and getattr(iface, "layout_fields", None)))
    return bool(getattr(iface, "spec_content", None))


def _positive_layout_int(value: object) -> bool:
    """Mirror the Engine's `_positive_int`: an int >= 1, and not a bool."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def fixed_width_layout_contiguity_errors(layout_fields) -> list[str]:
    """Blocker phrases for a visually-authored fixed-width layout the Engine
    would reject at generation.

    Studio emits ``LayoutField.start``/``.length`` as the Engine ``position``/
    ``length`` for each record field (mapping_generator.generate_downstream_layout).
    The Engine then requires (appbuilder.metadata.file_contracts): every field a
    positive-integer position and length (`_positive_int`), unique field names
    (`_ensure_unique_field_names`), and positions that tile 1..N with no leading
    gap, no interior gap, and no overlap (`_validate_contiguous_spans`). This
    mirrors ALL of those so Studio blocks export on exactly the layouts the
    Engine rejects -- not just the contiguity subset. The equivalence is pinned
    field-by-field against the real Engine validator in
    tests/test_fixed_width_contiguity.py.

    Each returned phrase is a noun-phrase (e.g. "a valid length for 'b' (found
    0)") so it reads correctly both as a standalone board/Step-7 blocker label
    and inside completeness_service's "... incomplete; missing {phrase}."
    """
    fields = list(layout_fields or [])
    errors: list[str] = []

    # Unique names (Engine _ensure_unique_field_names).
    seen_names: set[str] = set()
    for layout_field in fields:
        field_name = (getattr(layout_field, "name", "") or "").strip()
        if not field_name:
            continue
        if field_name in seen_names:
            errors.append(f"unique field names ('{field_name}' repeated)")
        seen_names.add(field_name)

    # A non-empty name for every field (Engine _required_name), then positive
    # position + length (Engine _positive_int). Only fully-valid fields become
    # spans for the contiguity check.
    spans: list[tuple[int, int, str]] = []
    for layout_field in fields:
        label = (getattr(layout_field, "name", "") or "").strip()
        start = getattr(layout_field, "start", None)
        length = getattr(layout_field, "length", None)
        if not label:
            # Blank/whitespace-only name -- reported once (a nameless field has
            # nothing to disambiguate it by).
            message = "a non-empty name for every field"
            if message not in errors:
                errors.append(message)
            continue
        if not _positive_layout_int(start):
            errors.append(f"a valid position for '{label}' (found {start})")
            continue
        if not _positive_layout_int(length):
            errors.append(f"a valid length for '{label}' (found {length})")
            continue
        spans.append((start, length, label))

    # Contiguity from position 1 (Engine _validate_contiguous_spans).
    expected = 1
    seen_any = False
    for start, length, label in sorted(spans, key=lambda span: span[0]):
        if start < expected:
            errors.append(
                f"contiguous positions ('{label}' overlaps: expected {expected}, found {start})"
            )
        elif start > expected:
            if not seen_any:
                errors.append(f"a first field at position 1 ('{label}' starts at {start})")
            else:
                errors.append(
                    f"contiguous positions (gap before '{label}': expected {expected}, found {start})"
                )
        expected = start + length
        seen_any = True
    return errors


def edge_contract_readiness(
    iface: UpstreamInterface | DownstreamInterface,
    *,
    direction: str,
    session: Any = None,
) -> EdgeContractReadiness:
    """Return export readiness for one edge-contract interface without mutation."""
    name = iface.name or "Unnamed contract"
    contract_type = iface.type or ""
    type_label = EDGE_CONTRACT_TYPE_LABELS.get(contract_type, contract_type or "Unknown")
    required_present: list[str] = []
    required_missing: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    if contract_type not in EDGE_CONTRACT_TYPES:
        return EdgeContractReadiness(
            direction=direction,
            name=name,
            type=contract_type,
            type_label=type_label,
            artifact_path=edge_contract_reference(iface),
            has_content_to_write=bool(getattr(iface, "spec_content", None)),
            will_export=True,
            status=READY_TO_EXPORT,
            required_present=[],
            required_missing=[],
            warnings=[],
            notes=[],
        )

    artifact_path = _edge_contract_artifact_path(iface, direction)
    if iface.spec_url:
        warnings.append(f"{name}: {type_label} contracts use package-relative files, not spec_url.")

    if artifact_path:
        if error := package_path_error(artifact_path):
            required_missing.append("valid artifact path")
            warnings.append(f"{name}: {error}")
        else:
            artifact_path = clean_package_path(artifact_path)
            required_present.append("artifact path")
    else:
        required_missing.append(_missing_artifact_label(contract_type))

    if contract_type == XML_XSD_TYPE:
        if iface.root_element:
            required_present.append("root element")
        else:
            required_missing.append("root element")

    if contract_type == SOAP_WSDL_TYPE and direction == "upstream":
        if iface.selected_operation_name:
            required_present.append("selected SOAP operation")
            canonical_missing = _soap_canonical_required_missing(iface, session=session)
            if canonical_missing:
                required_missing.extend(canonical_missing)
            elif iface.soap_operation_mode == SOAP_MAPPING_MODE_CANONICAL:
                required_present.append("canonical read_by_id mapping")
        else:
            warnings.append(
                f"{name}: inbound SOAP generation needs a selected operation for Studio to export an operation mapping file."
            )

    if contract_type == SOAP_WSDL_TYPE and direction == "downstream":
        if iface.selected_operation_name:
            required_present.append("selected SOAP operation")
            if iface.soap_operation_mode == SOAP_MAPPING_MODE_CANONICAL:
                invocation_missing = _soap_invocation_required_missing(iface, session=session)
                if invocation_missing:
                    required_missing.extend(invocation_missing)
                else:
                    required_present.append("canonical invoke_by_id mapping")
                    notes.append(
                        f"{name}: Studio validates the canonical mapping shape. Engine validates "
                        "WSDL request/response paths during generation."
                    )
            else:
                required_present.append("adapter-only operation mapping")
        else:
            if iface.soap_operation_mode == SOAP_MAPPING_MODE_CANONICAL or iface.soap_canonical_invocation:
                required_missing.append("selected SOAP operation")
            else:
                warnings.append(
                    f"{name}: downstream SOAP client scaffolding can export without an operation mapping, "
                    "but canonical invoke_by_id runtime needs a selected operation."
                )

    if contract_type == XML_XSD_TYPE:
        mappings = getattr(iface, "field_mappings", None)
        if mappings and not iface.entity_name:
            warnings.append(
                f"{name}: XML mappings are saved, but canonical entity name is blank."
            )
        elif not mappings:
            if direction == "upstream":
                warnings.append(
                    f"{name}: No reviewed XML-to-canonical mappings saved; XML ingest runtime needs explicit mappings."
                )
            else:
                warnings.append(
                    f"{name}: No reviewed canonical-to-XML mappings saved; XML output runtime needs explicit mappings."
                )

    if contract_type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE}:
        if direction == "upstream":
            if getattr(iface, "field_mappings", None) and not iface.entity_name:
                warnings.append(
                    f"{name}: file mappings are saved, but canonical entity name is blank."
                )
            elif not getattr(iface, "field_mappings", None):
                warnings.append(
                    f"{name}: No explicit file-to-canonical mappings; Engine may infer fields, but reviewed mappings are recommended."
                )
        if direction == "downstream" and not getattr(iface, "field_mappings", None):
            warnings.append(f"{name}: No canonical-to-file mappings saved.")

    if contract_type == FILE_CSV_TYPE and direction == "downstream" and iface.spec_content:
        from app.services.csv_layout import CsvLayoutError, prepare_csv_layout_for_export

        try:
            prepare_csv_layout_for_export(iface.spec_content, name=name)
            required_present.append("valid Engine-current CSV layout")
        except CsvLayoutError as exc:
            required_missing.append("valid Engine-current CSV layout")
            warnings.append(f"{name}: {exc}")

    if (
        contract_type == FILE_FIXED_WIDTH_TYPE
        and direction == "downstream"
        and getattr(iface, "layout_fields", None)
    ):
        layout_errors = fixed_width_layout_contiguity_errors(iface.layout_fields)
        if layout_errors:
            # Each specific phrase becomes its own blocker so the actionable
            # field detail reaches every surface that reads required_missing
            # (Step 5 board, Step 7, /export/write), not just the focused editor.
            required_missing.extend(layout_errors)
        else:
            required_present.append("contiguous fixed-width field positions")

    has_content = _edge_contract_has_content(iface, direction)
    will_export = bool(artifact_path and not required_missing)
    if not will_export:
        status = INCOMPLETE
    elif has_content:
        status = READY_TO_EXPORT
    else:
        status = REFERENCE_ONLY
        warnings.append(
            f"{name}: Studio will export the manifest path, but no uploaded artifact content is available to write into the package."
        )

    return EdgeContractReadiness(
        direction=direction,
        name=name,
        type=contract_type,
        type_label=type_label,
        artifact_path=artifact_path,
        has_content_to_write=has_content,
        will_export=will_export,
        status=status,
        required_present=required_present,
        required_missing=required_missing,
        warnings=warnings,
        notes=notes,
    )


def _missing_artifact_label(contract_type: str) -> str:
    if contract_type == XML_XSD_TYPE:
        return "xsd_path or uploaded XSD content"
    if contract_type == SOAP_WSDL_TYPE:
        return "wsdl_path or uploaded WSDL content"
    return "layout/spec path or uploaded layout/spec content"


def edge_contract_readiness_rows(
    interfaces: list[UpstreamInterface] | list[DownstreamInterface],
    *,
    direction: str,
    session: Any = None,
) -> list[EdgeContractReadiness]:
    return [
        edge_contract_readiness(iface, direction=direction, session=session)
        for iface in interfaces
        if iface.type in EDGE_CONTRACT_TYPES
    ]


def edge_contract_export_warnings(
    upstream_interfaces: list[UpstreamInterface],
    downstream_interfaces: list[DownstreamInterface],
    *,
    session: Any = None,
) -> list[str]:
    warnings: list[str] = []
    for row in edge_contract_readiness_rows(upstream_interfaces, direction="upstream", session=session):
        warnings.extend(row.warnings)
    for row in edge_contract_readiness_rows(downstream_interfaces, direction="downstream", session=session):
        warnings.extend(row.warnings)
    return warnings
