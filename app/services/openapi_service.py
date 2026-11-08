"""OpenAPI fetch, parse, and classification service.

Classification logic mirrors AppBuilder's ``appbuilder.ingestion.openapi_classifier``
so that Studio and AppBuilder agree on which schemas are domain entities, DTOs,
and infrastructure wrappers.  Keeping these aligned ensures that entity candidates
shown in Studio's Step 3 are the same schemas AppBuilder would ingest.
"""

from __future__ import annotations

import json
import re
from typing import Any

import yaml

from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    ClassifiedOperation,
    EntityRules,
    RuleEntry,
)
from app.services.openapi_fetch_guard import fetch_url_with_policy

# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_openapi_from_url(url: str) -> dict[str, Any]:
    resp = fetch_url_with_policy(url)
    content = resp.text.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return yaml.safe_load(content)


def parse_openapi_text(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return yaml.safe_load(text)


# ---------------------------------------------------------------------------
# Schema extraction helpers — aligned with AppBuilder's openapi_classifier
# ---------------------------------------------------------------------------

# Infrastructure schema names lifted directly from AppBuilder's classifier
_INFRASTRUCTURE_NAMES: set[str] = {
    "PageableObject", "Pageable", "SortObject", "Sort", "SliceObject",
    "Error", "ApiError", "Problem", "ValidationError",
    "ErrorResponse", "ApiErrorResponse",
}
_TRANSPORT_WRAPPER_KEYS: set[str] = {"Data", "Links", "Meta", "Risk"}


def _is_infrastructure_schema_name(name: str) -> bool:
    """Mirror AppBuilder's _is_infrastructure_schema_name exactly."""
    if name.startswith("Page"):
        return True
    if name in _INFRASTRUCTURE_NAMES:
        return True
    return name.endswith(("Error", "Exception"))


def _component_schemas(spec: dict[str, Any]) -> dict[str, dict]:
    components = spec.get("components", {})
    if not isinstance(components, dict):
        return {}
    schemas = components.get("schemas", {}) or spec.get("definitions", {})
    if not isinstance(schemas, dict):
        return {}
    return {k: v for k, v in schemas.items() if isinstance(k, str) and isinstance(v, dict)}


def _component_responses(spec: dict[str, Any]) -> dict[str, dict]:
    components = spec.get("components", {})
    if not isinstance(components, dict):
        return {}
    responses = components.get("responses", {})
    if not isinstance(responses, dict):
        return {}
    return {k: v for k, v in responses.items() if isinstance(k, str) and isinstance(v, dict)}


def _iter_path_operations(spec: dict[str, Any]) -> list[tuple[str, str, dict]]:
    paths = spec.get("paths", {})
    if not isinstance(paths, dict):
        return []
    ops: list[tuple[str, str, dict]] = []
    for path, path_item in paths.items():
        if not isinstance(path, str) or not isinstance(path_item, dict):
            continue
        for method in ("get", "post", "put", "delete", "patch"):
            op = path_item.get(method)
            if isinstance(op, dict):
                ops.append((path, method, op))
    return ops


def _resolve_response_object(response: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """Resolve a response object, following #/components/responses refs."""
    current = response
    responses = _component_responses(spec)
    seen: set[str] = set()
    while isinstance(current, dict):
        ref = current.get("$ref")
        if not isinstance(ref, str) or not ref.startswith("#/components/responses/"):
            return current
        ref_name = ref.rsplit("/", 1)[-1]
        if ref_name in seen:
            return {}
        seen.add(ref_name)
        current = responses.get(ref_name, {})
    return {}


def _response_schema_from_content(content: dict[str, Any]) -> dict[str, Any] | None:
    """Return the first JSON-like response schema from a content map."""
    for media in ("application/json", "application/*+json", "*/*"):
        media_obj = content.get(media)
        if isinstance(media_obj, dict) and isinstance(media_obj.get("schema"), dict):
            return media_obj["schema"]

    for media_type, media_obj in content.items():
        if not isinstance(media_type, str) or not isinstance(media_obj, dict):
            continue
        lowered = media_type.lower()
        if lowered.startswith("application/json") or lowered.startswith("application/") and "+json" in lowered:
            schema = media_obj.get("schema")
            if isinstance(schema, dict):
                return schema
    return None


def _response_schemas_from_op(operation: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    responses = operation.get("responses", {})
    if not isinstance(responses, dict):
        return []
    result: list[dict[str, Any]] = []
    for status_code, response in responses.items():
        if not str(status_code).startswith("2") or not isinstance(response, dict):
            continue
        resolved = _resolve_response_object(response, spec)
        content = resolved.get("content", {})
        if not isinstance(content, dict):
            continue
        schema = _response_schema_from_content(content)
        if schema is not None:
            result.append(schema)
    return result


def _extract_schema_refs(schema: Any) -> set[str]:
    if not isinstance(schema, dict):
        return set()
    ref = schema.get("$ref")
    if isinstance(ref, str):
        return {ref.rsplit("/", 1)[-1]}
    refs: set[str] = set()
    items = schema.get("items")
    if isinstance(items, dict):
        refs.update(_extract_schema_refs(items))
    for key in ("allOf", "anyOf", "oneOf"):
        variants = schema.get(key, [])
        if isinstance(variants, list):
            for v in variants:
                refs.update(_extract_schema_refs(v))
    return refs


def _response_schema_refs(spec: dict[str, Any]) -> set[str]:
    """Return all schema names that appear as 2xx response refs — mirrors AppBuilder."""
    refs: set[str] = set()
    for _path, _method, operation in _iter_path_operations(spec):
        for schema in _response_schemas_from_op(operation, spec):
            refs.update(_extract_schema_refs(schema))
    return refs


def _schema_has_properties(schema_def: dict[str, Any]) -> bool:
    """Return True if a schema defines domain properties, directly or via allOf/anyOf/oneOf.

    Spring Boot / Springdoc commonly uses allOf for inheritance:
      allOf:
        - $ref: '#/components/schemas/BaseEntity'
        - type: object
          properties:
            id: ...
    In that case schema_def.get("properties") is None at the top level even though
    the schema clearly carries domain fields.  We recurse into allOf/anyOf/oneOf so
    these schemas are not silently dropped as infrastructure.
    """
    if isinstance(schema_def.get("properties"), dict):
        return True
    for combiner in ("allOf", "anyOf", "oneOf"):
        variants = schema_def.get(combiner)
        if isinstance(variants, list):
            for v in variants:
                if isinstance(v, dict) and isinstance(v.get("properties"), dict):
                    return True
    return False


def classify_schema(name: str, schema_def: dict[str, Any], response_refs: set[str]) -> str:
    """
    Classify a single schema — mirrors AppBuilder's classify_openapi_schemas().

    Rules (in priority order):
    1. Infrastructure name pattern → infrastructure
    2. Name ends with Request or Response:
       - if also in response_refs AND has properties → entity  (AppBuilder promotes these)
       - otherwise → dto
    3. In response_refs AND has properties → entity
    4. Anything else → infrastructure
    """
    if _is_infrastructure_schema_name(name):
        return "infrastructure"

    has_props = _schema_has_properties(schema_def)

    if name.endswith(("Request", "Response")):
        if name in response_refs and has_props:
            # AppBuilder promotes *Response schemas that appear in actual response
            # refs to "entity" when they carry domain properties.
            return "entity"
        return "dto"

    if name in response_refs and has_props:
        return "entity"

    return "infrastructure"


def _normalize_entity_name(name: str) -> str:
    """Mirror AppBuilder's _normalize_entity_name() from openapi_classifier.py.

    Strips Request/Response suffix and leading CRUD verb prefix so that
    `CustomerResponse` → `Customer`, `CreateAccountRequest` → `Account`.
    This ensures Studio entity names match the canonical class names AppBuilder
    generates, keeping downstream mappings, handoff mappings, and rules aligned.
    """
    normalized = re.sub(r"(Request|Response)$", "", name)
    normalized = re.sub(r"^(Create|Update|Delete|Get|List)", "", normalized)
    parts = re.split(r"[-_\s]+", normalized)
    return "".join(part[:1].upper() + part[1:] for part in parts if part)


def _resolve_schema(name: str, spec: dict[str, Any]) -> dict[str, Any] | None:
    schemas = (
        spec.get("components", {}).get("schemas", {})
        or spec.get("definitions", {})
    )
    return schemas.get(name)


def _resolve_schema_object(schema: Any, spec: dict[str, Any]) -> dict[str, Any]:
    """Resolve a schema dict, following #/components/schemas refs."""
    if not isinstance(schema, dict):
        return {}
    current = schema
    seen: set[str] = set()
    while isinstance(current, dict):
        ref = current.get("$ref")
        if not isinstance(ref, str) or not ref.startswith("#/components/schemas/"):
            return current
        ref_name = ref.rsplit("/", 1)[-1]
        if ref_name in seen:
            return {}
        seen.add(ref_name)
        current = _resolve_schema(ref_name, spec) or {}
    return {}


def _openapi_type_to_canonical(prop: dict[str, Any]) -> str:
    t = prop.get("type", "string")
    fmt = prop.get("format", "")
    if t == "integer" or t == "number" and fmt in ("int32", "int64"):
        return "integer"
    if t == "number":
        return "decimal"
    if t == "boolean":
        return "boolean"
    if t == "string" and fmt in ("date",):
        return "date"
    if t == "string" and fmt in ("date-time", "datetime"):
        return "datetime"
    return "string"


def _collect_properties_and_required(
    schema: dict[str, Any], spec: dict[str, Any]
) -> tuple[dict[str, Any], set[str]]:
    """Collect all properties and required fields from a schema, including
    allOf/anyOf/oneOf variants and their $ref targets.

    Mirrors AppBuilder's _collect_properties_and_required() so that Studio's
    entity field list always matches what AppBuilder ingests.

    Spring Boot / Springdoc uses allOf for inheritance:
      allOf:
        - $ref: '#/components/schemas/BaseEntity'   ← resolved here
        - type: object
          properties: {id: ..., name: ...}
          required: [id]
    Reading only schema.get("properties") misses all fields in allOf items.
    """
    # Resolve top-level $ref first
    if "$ref" in schema:
        ref_name = schema["$ref"].split("/")[-1]
        schema = _resolve_schema(ref_name, spec) or {}

    properties: dict[str, Any] = {}
    required: set[str] = set()

    direct_props = schema.get("properties")
    if isinstance(direct_props, dict):
        properties.update(direct_props)
    direct_required = schema.get("required", [])
    if isinstance(direct_required, list):
        required.update(f for f in direct_required if isinstance(f, str))

    for combiner in ("allOf", "anyOf", "oneOf"):
        for variant in schema.get(combiner, []):
            if not isinstance(variant, dict):
                continue
            # Resolve $ref variant (e.g. BaseEntity reference in allOf)
            resolved = variant
            if "$ref" in variant:
                ref_name = variant["$ref"].split("/")[-1]
                resolved = _resolve_schema(ref_name, spec) or {}
            variant_props = resolved.get("properties")
            if isinstance(variant_props, dict):
                properties.update(variant_props)
            variant_required = resolved.get("required", [])
            if isinstance(variant_required, list):
                required.update(f for f in variant_required if isinstance(f, str))

    return properties, required


def _extract_fields(schema: dict[str, Any], spec: dict[str, Any]) -> list[ClassifiedField]:
    """Extract ClassifiedField list from a schema, handling allOf/anyOf/oneOf and $ref variants."""
    props, required = _collect_properties_and_required(schema, spec)
    fields: list[ClassifiedField] = []

    for name, prop_schema in props.items():
        resolved_prop = _resolve_schema_object(prop_schema, spec) if isinstance(prop_schema, dict) else {}
        # Skip nested complex objects / arrays of objects for MVP
        prop_type = resolved_prop.get("type", prop_schema.get("type", "string"))
        if isinstance(prop_type, list):
            prop_type = next(
                (candidate for candidate in prop_type if candidate != "null"),
                prop_type[0] if prop_type else "string",
            )
        if prop_type == "object":
            continue
        if prop_type == "array":
            items = resolved_prop.get("items", prop_schema.get("items", {}))
            resolved_items = _resolve_schema_object(items, spec) if isinstance(items, dict) else {}
            item_type = resolved_items.get("type", items.get("type", "string") if isinstance(items, dict) else "string")
            if isinstance(item_type, list):
                item_type = next(
                    (candidate for candidate in item_type if candidate != "null"),
                    item_type[0] if item_type else "string",
                )
            if item_type == "object":
                continue

        # Coerce default to string for storage (JSON default may be int/bool/etc.)
        raw_default = resolved_prop.get("default", prop_schema.get("default"))
        default_str = str(raw_default) if raw_default is not None else None

        field = ClassifiedField(
            name=name,
            type=_openapi_type_to_canonical(resolved_prop or prop_schema),
            required=name in required,
            is_id=name.lower() in ("id", f"{name.lower()}id"),
            format=resolved_prop.get("format", prop_schema.get("format")),
            enum_values=resolved_prop.get("enum", prop_schema.get("enum", [])),
            max_length=resolved_prop.get("maxLength", prop_schema.get("maxLength")),
            min_length=resolved_prop.get("minLength", prop_schema.get("minLength")),
            pattern=resolved_prop.get("pattern", prop_schema.get("pattern")),
            minimum=resolved_prop.get("minimum", prop_schema.get("minimum")),
            maximum=resolved_prop.get("maximum", prop_schema.get("maximum")),
            default_value=default_str,
        )
        fields.append(field)
    return fields


def _unwrap_transport_payload_schema(
    schema: dict[str, Any], spec: dict[str, Any]
) -> dict[str, Any] | None:
    """Return nested Data payload schema for OB-style transport wrappers."""
    props, _ = _collect_properties_and_required(schema, spec)
    if not props or set(props) - _TRANSPORT_WRAPPER_KEYS:
        return None
    data_prop = props.get("Data")
    if not isinstance(data_prop, dict):
        return None
    resolved_data = _resolve_schema_object(data_prop, spec)
    if not isinstance(resolved_data, dict):
        return None
    if not _extract_fields(resolved_data, spec):
        return None
    return resolved_data


def _canonical_name_from_resource_path(path: str) -> str | None:
    """Derive a singular PascalCase entity name from the primary resource path."""
    segments = [segment for segment in path.strip("/").split("/") if segment and not segment.startswith("{")]
    if not segments:
        return None
    parts = [part for part in re.split(r"[-_]+", segments[0]) if part]
    if not parts:
        return None
    last = parts[-1]
    if last.endswith("ies") and len(last) > 3:
        parts[-1] = last[:-3] + "y"
    elif last.endswith("s") and len(last) > 1 and not last.endswith("ss"):
        parts[-1] = last[:-1]
    return "".join(part[:1].upper() + part[1:] for part in parts if part)


def _response_entity_overrides(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map wrapper response schema names to canonical entity metadata."""
    overrides: dict[str, dict[str, Any]] = {}
    schemas = _component_schemas(spec)

    for path, _method, operation in _iter_path_operations(spec):
        response_schema = _find_response_schema(operation, spec)
        if not response_schema:
            continue
        schema_def = schemas.get(response_schema)
        if not isinstance(schema_def, dict):
            continue
        payload_schema = _unwrap_transport_payload_schema(schema_def, spec)
        if payload_schema is None:
            continue
        canonical_name = _canonical_name_from_resource_path(path)
        if not canonical_name:
            continue
        existing = overrides.get(response_schema)
        if existing and existing.get("canonical_name") != canonical_name:
            continue
        overrides[response_schema] = {
            "canonical_name": canonical_name,
            "field_schema": payload_schema,
        }
    return overrides


# ---------------------------------------------------------------------------
# Classification entry point
# ---------------------------------------------------------------------------

def _merge_dto_constraints(
    entities: list[ClassifiedEntity],
    schemas: dict[str, Any],
    spec: dict[str, Any],
) -> None:
    """Second pass: merge field constraints from DTO/Request schemas into entity fields.

    Many OpenAPI specs (Spring Boot, FastAPI, .NET, etc.) place
    validation constraints — maxLength, minLength, pattern, minimum, maximum,
    enum — on Request/DTO schemas rather than Response schemas, because input
    validation is the primary concern.  Response schemas describe the output
    and often carry no explicit constraints.

    This function identifies every non-entity schema whose canonical name
    (after stripping Create/Update/Request/Response suffixes) matches a known
    entity, then merges any field-level constraints it finds into the entity's
    matching fields.  Fields present only in the DTO and not in the entity
    (write-only input fields) are silently skipped.

    Merge semantics (deterministic, schema-order-independent):
        max_length  — keep MIN across all DTOs (tightest upper bound wins)
        min_length  — keep MAX across all DTOs (strictest lower bound wins)
        minimum     — keep MAX across all DTOs (highest acceptable lower bound)
        maximum     — keep MIN across all DTOs (lowest acceptable upper bound)
        enum        — union of all values seen (ordered, deduplicated)
        pattern     — first non-None wins (patterns can't be merged meaningfully)
        default     — first non-None wins

    These rules mirror AppBuilder's _FieldAccumulator merge semantics from
    metadata/translation.py so that Studio and AppBuilder converge on identical
    constraint values for the same entity field.
    """
    # Build canonical_name → entity for all entity-classified schemas
    canonical_to_entity: dict[str, ClassifiedEntity] = {}
    for entity in entities:
        if entity.classification == "entity":
            canonical_to_entity[entity.display_name()] = entity

    if not canonical_to_entity:
        return

    for schema_name, schema in schemas.items():
        canonical = _normalize_entity_name(schema_name)
        entity = canonical_to_entity.get(canonical)
        if entity is None:
            continue  # no matching entity — unrelated DTO or infrastructure schema

        # Build a field-name lookup for quick access
        entity_field_map: dict[str, ClassifiedField] = {f.name: f for f in entity.fields}

        # Extract all properties from the DTO (resolves allOf/$ref variants)
        props, _ = _collect_properties_and_required(schema, spec)
        for prop_name, prop_schema in props.items():
            ef = entity_field_map.get(prop_name)
            if ef is None:
                continue  # write-only DTO field — not part of entity, skip

            # max_length: keep MIN (tightest upper bound)
            dto_max_len = prop_schema.get("maxLength")
            if dto_max_len is not None:
                v = int(dto_max_len)
                ef.max_length = v if ef.max_length is None else min(ef.max_length, v)

            # min_length: keep MAX (strictest lower bound)
            dto_min_len = prop_schema.get("minLength")
            if dto_min_len is not None:
                v = int(dto_min_len)
                ef.min_length = v if ef.min_length is None else max(ef.min_length, v)

            # pattern: first non-None wins (no meaningful way to merge two regexes)
            if ef.pattern is None and prop_schema.get("pattern") is not None:
                ef.pattern = prop_schema["pattern"]

            # minimum: keep MAX (highest lower bound — strictest acceptable floor)
            dto_minimum = prop_schema.get("minimum")
            if dto_minimum is not None:
                v = float(dto_minimum)
                ef.minimum = v if ef.minimum is None else max(ef.minimum, v)

            # maximum: keep MIN (lowest upper bound — strictest acceptable ceiling)
            dto_maximum = prop_schema.get("maximum")
            if dto_maximum is not None:
                v = float(dto_maximum)
                ef.maximum = v if ef.maximum is None else min(ef.maximum, v)

            # enum: union across all DTOs (ordered, deduplicated via dict.fromkeys)
            dto_enum = prop_schema.get("enum")
            if dto_enum:
                ef.enum_values = list(dict.fromkeys(ef.enum_values + [str(v) for v in dto_enum]))

            # default: first non-None wins
            if ef.default_value is None and prop_schema.get("default") is not None:
                ef.default_value = str(prop_schema["default"])


def classify_openapi_spec(spec: dict[str, Any]) -> tuple[
    list[ClassifiedEntity], list[ClassifiedOperation]
]:
    """Return (entities, operations) from an OpenAPI spec.

    Uses the same classification rules as AppBuilder's openapi_classifier so
    that the entity candidates shown in Studio match what AppBuilder would ingest.
    """
    schemas = _component_schemas(spec)
    response_refs = _response_schema_refs(spec)
    response_entity_overrides = _response_entity_overrides(spec)

    entities: list[ClassifiedEntity] = []
    for name, schema in schemas.items():
        classification = classify_schema(name, schema, response_refs)
        reason = _classification_reason(name, schema, classification, response_refs)
        override = response_entity_overrides.get(name)
        field_schema = override.get("field_schema", schema) if override else schema
        fields = _extract_fields(field_schema, spec) if classification == "entity" else []

        # Derive the canonical entity name (mirrors AppBuilder's _normalize_entity_name).
        # For plain domain schemas ("Account", "Customer") the canonical name is identical
        # to the schema name, so we only store it when it differs to keep serialisation clean.
        canonical = override.get("canonical_name") if override else _normalize_entity_name(name)
        if override:
            reason = (
                f"{reason} Studio surfaces the nested 'Data' payload as canonical "
                f"'{canonical}' for this wrapper-backed response."
            )
        entities.append(ClassifiedEntity(
            name=name,
            canonical_name=canonical if canonical != name else None,
            fields=fields,
            classification=classification,
            confidence="inferred",
            reason=reason,
            source_schema=name,
        ))

    # Second pass: pull constraints from DTO/Request schemas into entity fields.
    # Response schemas often omit validation constraints; Request schemas carry them.
    _merge_dto_constraints(entities, schemas, spec)

    operations = _extract_operations(spec, response_refs, response_entity_overrides)
    return entities, operations


def _classification_reason(
    name: str, schema: dict[str, Any], classification: str, response_refs: set[str]
) -> str:
    if classification == "infrastructure":
        if _is_infrastructure_schema_name(name):
            return "Matched infrastructure name pattern (Page*/Sort*/Error*/etc.)"
        return "No response usage detected and no domain properties found"
    if classification == "dto":
        if name.endswith("Request"):
            return "Name ends with 'Request' and not found in 2xx response refs — DTO"
        if name.endswith("Response"):
            return "Name ends with 'Response' but has no domain properties in response refs — DTO"
        return "No response ref usage and no id field — DTO"
    # entity
    if name in response_refs:
        if name.endswith("Response"):
            return (
                "Name ends with 'Response' but appears in 2xx response refs with domain properties "
                "— promoted to entity (mirrors AppBuilder ingestion)"
            )
        return "Appears in 2xx response refs with domain properties — domain entity candidate"
    props = schema.get("properties", {})
    id_fields = [k for k in props if k.lower() in ("id", f"{name.lower()}id", f"{name.lower()}_id")]
    if id_fields:
        return f"Has id field '{id_fields[0]}' — domain entity candidate"
    return f"Has {len(props)} properties — domain entity candidate"


def _extract_operations(
    spec: dict[str, Any],
    response_refs: set[str],
    response_entity_overrides: dict[str, dict[str, Any]] | None = None,
) -> list[ClassifiedOperation]:
    ops: list[ClassifiedOperation] = []
    schemas = _component_schemas(spec)
    paths = spec.get("paths", {})

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, op_def in path_item.items():
            if method not in ("get", "post", "put", "delete", "patch"):
                continue
            op_id = op_def.get("operationId") or _derive_op_id(method, path)
            resource = _derive_resource(path)
            request_schema = _find_request_schema(op_def, spec)
            response_schema = _find_response_schema(op_def, spec)

            entity_candidates: list[str] = []
            for sname in [request_schema, response_schema]:
                if sname:
                    schema_def = schemas.get(sname, {})
                    if classify_schema(sname, schema_def, response_refs) == "entity":
                        # Use canonical name so operation→entity assignment
                        # matches what AppBuilder generates (Customer not CustomerResponse)
                        override = (response_entity_overrides or {}).get(sname, {})
                        entity_candidates.append(
                            override.get("canonical_name") or _normalize_entity_name(sname)
                        )

            ops.append(ClassifiedOperation(
                name=op_id,
                method=method.upper(),
                path=path,
                resource=resource,
                request_schema=request_schema,
                response_schema=response_schema,
                entity_candidates=list(dict.fromkeys(entity_candidates)),
                is_draft=True,
            ))
    return ops


def _derive_op_id(method: str, path: str) -> str:
    parts = [p for p in path.strip("/").split("/") if not p.startswith("{")]
    resource = parts[-1] if parts else "resource"
    method_map = {
        "get": "get", "post": "create", "put": "update",
        "delete": "delete", "patch": "patch",
    }
    return f"{method_map.get(method, method)}{resource.capitalize()}"


def _derive_resource(path: str) -> str:
    parts = [p for p in path.strip("/").split("/") if not p.startswith("{")]
    return parts[0] if parts else "unknown"


def _find_request_schema(op_def: dict[str, Any], spec: dict[str, Any]) -> str | None:
    body = op_def.get("requestBody", {})
    content = body.get("content", {})
    for media_type in ("application/json", "application/xml", "*/*"):
        schema = content.get(media_type, {}).get("schema", {})
        ref = schema.get("$ref") or schema.get("items", {}).get("$ref")
        if ref:
            return ref.split("/")[-1]
    return None


# ---------------------------------------------------------------------------
# Auto-generation: sample JSON + field mappings from spec schemas
# ---------------------------------------------------------------------------

_TYPE_DEFAULTS: dict[str, Any] = {
    "string": "example",
    "integer": 0,
    "number": 0.0,
    "boolean": True,
    "array": [],
    "object": {},
}


def _schema_type(schema_def: dict[str, Any]) -> str:
    field_type = schema_def.get("type")
    if isinstance(field_type, list):
        field_type = next(
            (candidate for candidate in field_type if candidate != "null"),
            field_type[0] if field_type else None,
        )
    if isinstance(field_type, str):
        return field_type
    if isinstance(schema_def.get("properties"), dict):
        return "object"
    if isinstance(schema_def.get("items"), dict):
        return "array"
    return "string"


def _schema_properties(schema_def: dict[str, Any], all_schemas: dict[str, dict]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    direct = schema_def.get("properties")
    if isinstance(direct, dict):
        properties.update(direct)
    for combiner in ("allOf", "anyOf", "oneOf"):
        variants = schema_def.get(combiner, [])
        if not isinstance(variants, list):
            continue
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            ref = variant.get("$ref")
            resolved = (
                all_schemas.get(ref.rsplit("/", 1)[-1], {})
                if isinstance(ref, str)
                else variant
            )
            if isinstance(resolved.get("properties"), dict):
                properties.update(resolved["properties"])
    return properties


def _generate_sample_value(
    schema_def: dict[str, Any],
    all_schemas: dict[str, dict],
    *,
    _depth: int = 0,
    _seen_refs: frozenset[str] = frozenset(),
) -> Any:
    """Generate one deterministic JSON value while preserving referenced type."""
    if _depth > 6:
        return None

    for key in ("example", "default"):
        if key in schema_def:
            return schema_def[key]
    enum_values = schema_def.get("enum")
    if isinstance(enum_values, list) and enum_values:
        return enum_values[0]

    ref = schema_def.get("$ref")
    if isinstance(ref, str):
        ref_name = ref.rsplit("/", 1)[-1]
        if ref_name in _seen_refs:
            return None
        referenced = all_schemas.get(ref_name, {})
        # OpenAPI 3.1 permits useful sibling keywords beside $ref. Siblings
        # override the referenced defaults without changing its underlying type.
        merged = {**referenced, **{key: value for key, value in schema_def.items() if key != "$ref"}}
        return _generate_sample_value(
            merged,
            all_schemas,
            _depth=_depth + 1,
            _seen_refs=_seen_refs | {ref_name},
        )

    properties = _schema_properties(schema_def, all_schemas)
    if properties:
        return {
            field_name: _generate_sample_value(field_def, all_schemas, _depth=_depth + 1)
            if isinstance(field_def, dict)
            else None
            for field_name, field_def in properties.items()
        }

    # A combiner without object properties can wrap a primitive or array ref.
    # Follow the first concrete variant instead of defaulting every composed
    # schema to an object. This covers common alias schemas such as
    # ``allOf: [{$ref: CurrencyCode}]``.
    for combiner in ("allOf", "oneOf", "anyOf"):
        variants = schema_def.get(combiner)
        if not isinstance(variants, list):
            continue
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            value = _generate_sample_value(
                variant,
                all_schemas,
                _depth=_depth + 1,
                _seen_refs=_seen_refs,
            )
            if value is not None:
                return value

    field_type = _schema_type(schema_def)
    if field_type == "array":
        items = schema_def.get("items")
        if not isinstance(items, dict):
            return []
        return [_generate_sample_value(items, all_schemas, _depth=_depth + 1)]
    if field_type == "null":
        return None
    return _TYPE_DEFAULTS.get(field_type, "example")


def _generate_sample_from_schema(
    schema_def: dict[str, Any],
    all_schemas: dict[str, dict],
    _depth: int = 0,
) -> Any:
    """Generate a deterministic sample JSON value from an OpenAPI schema."""
    return _generate_sample_value(schema_def, all_schemas, _depth=_depth)


def generate_operation_samples(
    request_schema_name: str | None,
    response_schema_name: str | None,
    all_schemas: dict[str, dict],
) -> tuple[str | None, str | None]:
    """Return (request_json, response_json) strings auto-generated from spec schemas.

    Returns None for each side when no schema is available.
    """
    req_json = resp_json = None
    if request_schema_name and request_schema_name in all_schemas:
        sample = _generate_sample_from_schema(all_schemas[request_schema_name], all_schemas)
        if sample is not None and sample != {}:
            req_json = json.dumps(sample, indent=2)
    if response_schema_name and response_schema_name in all_schemas:
        sample = _generate_sample_from_schema(all_schemas[response_schema_name], all_schemas)
        if sample is not None and sample != {}:
            resp_json = json.dumps(sample, indent=2)
    return req_json, resp_json


def generate_field_mapping_plan(
    schema_name: str,
    entity_canonical_name: str,
    all_schemas: dict[str, dict],
    *,
    canonical_fields: set[str] | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    """Return safe automatic mappings and fields omitted for canonical review.

    source = API field name (as it appears in the schema)
    target = Entity.fieldName (canonical path AppBuilder uses)

    Uses _collect_properties_and_required() so that allOf/$ref variants are
    resolved the same way _extract_fields() and _generate_sample_from_schema()
    resolve them — keeping all three in sync and avoiding unmapped-sample warnings
    from AppBuilder's mapping ingestion layer.
    """
    schema_def = all_schemas.get(schema_name)
    if not schema_def:
        return [], []
    inline_spec = {"components": {"schemas": all_schemas}}
    field_schema = _unwrap_transport_payload_schema(schema_def, inline_spec) or schema_def
    fields = _extract_fields(field_schema, inline_spec)
    omitted = [
        field.name
        for field in fields
        if canonical_fields is not None and field.name not in canonical_fields
    ]
    mappings = [
        {"source": field.name, "target": f"{entity_canonical_name}.{field.name}"}
        for field in fields
        if canonical_fields is None or field.name in canonical_fields
    ]
    return mappings, omitted


def generate_field_mappings(
    schema_name: str,
    entity_canonical_name: str,
    all_schemas: dict[str, dict],
    *,
    canonical_fields: set[str] | None = None,
) -> list[dict[str, str]]:
    """Return safe automatic mapping rows for one schema."""
    mappings, _ = generate_field_mapping_plan(
        schema_name,
        entity_canonical_name,
        all_schemas,
        canonical_fields=canonical_fields,
    )
    return mappings


def _find_response_schema(op_def: dict[str, Any], spec: dict[str, Any]) -> str | None:
    responses = op_def.get("responses", {})
    for code in ("200", "201", "202"):
        resp = responses.get(code, {})
        if not isinstance(resp, dict):
            continue
        resolved = _resolve_response_object(resp, spec)
        content = resolved.get("content", {})
        if not isinstance(content, dict):
            continue
        schema = _response_schema_from_content(content)
        if not isinstance(schema, dict):
            continue
        ref = schema.get("$ref") or (schema.get("items") or {}).get("$ref")
        if ref:
            name = ref.split("/")[-1]
            # Skip pure infrastructure wrappers (Page*, Sort*, etc.)
            if not _is_infrastructure_schema_name(name):
                return name
    return None


# ---------------------------------------------------------------------------
# Auto rule generation from classified entity field constraints
# ---------------------------------------------------------------------------

def auto_generate_rules(entities: list[ClassifiedEntity]) -> list[EntityRules]:
    """Walk classified entities and produce EntityRules pre-populated from field constraints.

    For each field that carries a constraint extracted from the OpenAPI spec, a
    corresponding rule entry is generated:
        enum values       → allowed-values rule
        maxLength         → max-length rule
        minLength         → min-length rule
        pattern           → pattern rule
        minimum/maximum   → range rule
        default           → default rule
        required + string → not-null rule (when no other constraint already covers it)

    The result is passed to Step 6 so users see pre-filled rules they can edit,
    rather than starting from a blank slate.  Only entity-classified schemas with
    at least one rule are included.
    """
    import re as _re

    def _slug(name: str) -> str:
        return _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

    result: list[EntityRules] = []
    for entity in entities:
        if entity.classification != "entity":
            continue
        canonical = entity.display_name()
        rules: list[RuleEntry] = []

        for field in entity.fields:
            # 1. Enum → allowed-values
            # No continue here: a field can have BOTH enum values and a default
            # (e.g. { enum: [ACTIVE, INACTIVE], default: ACTIVE }) — we want both
            # rules in the package so AppBuilder can apply them independently.
            if field.enum_values:
                rules.append(RuleEntry(
                    field=field.name,
                    type="allowed-values",
                    values=list(field.enum_values),
                ))

            # 2. max-length / min-length (can coexist)
            if field.max_length is not None:
                rules.append(RuleEntry(
                    field=field.name,
                    type="max-length",
                    value=str(field.max_length),
                ))
            if field.min_length is not None:
                rules.append(RuleEntry(
                    field=field.name,
                    type="min-length",
                    value=str(field.min_length),
                ))

            # 3. pattern — skip when the field already has enum values, because the
            # pattern is typically just the enum alternatives expressed as a regex
            # (e.g. "^(USD|INR)$") and the allowed-values rule is more actionable.
            if field.pattern is not None and not field.enum_values:
                rules.append(RuleEntry(
                    field=field.name,
                    type="pattern",
                    value=field.pattern,
                ))

            # 4. range (numeric min/max)
            if field.minimum is not None or field.maximum is not None:
                entry = RuleEntry(field=field.name, type="range")
                if field.minimum is not None:
                    entry.value = str(field.minimum)
                if field.maximum is not None:
                    entry.values = [str(field.maximum)]
                rules.append(entry)

            # 5. default
            if field.default_value is not None:
                rules.append(RuleEntry(
                    field=field.name,
                    type="default",
                    value=field.default_value,
                ))

            # 6. not-null (required string/numeric fields without any other constraint)
            if (
                field.required
                and not field.is_id
                and field.enum_values == []
                and field.max_length is None
                and field.min_length is None
                and field.pattern is None
                and field.minimum is None
                and field.maximum is None
                and field.default_value is None
            ):
                rules.append(RuleEntry(field=field.name, type="not-null"))

        if rules:
            result.append(EntityRules(
                entity_name=canonical,
                rules=rules,
                file_path=f"rules/{_slug(canonical)}-business-rules.yaml",
            ))

    return result
