"""Generate upstream, downstream, and data-handoff mapping YAML files."""

from __future__ import annotations

from typing import Any

import yaml

from app.models.project import DataHandoff, DownstreamInterface, UpstreamInterface
from app.services.edge_contracts import (
    SOAP_MAPPING_MODE_CANONICAL,
    SOAP_RESPONSE_MODE_RETURN_ONLY,
    soap_operation_handler_method,
)


def generate_upstream_mapping(iface: UpstreamInterface) -> str:
    """
    upstream mapping shape:
      interface: <name>
      entity: <entity_name>
      operations:
        - name: <op>
          request_mappings: [{source, target}]
          response_mappings: [{source, target}]
    """
    # AppBuilder's translation layer expects targets in "Entity.fieldName" format so it
    # can split on "." to resolve the canonical entity and field.  Qualify any target
    # that is a plain field name (no ".") with the interface's entity name.
    entity_prefix = iface.entity_name or ""

    def _qualify(field_name: str) -> str:
        if entity_prefix and "." not in field_name:
            return f"{entity_prefix}.{field_name}"
        return field_name

    ops_out = []
    for om in iface.operation_mappings:
        op_entry: dict[str, Any] = {"name": om.name}
        if om.request_mappings:
            op_entry["request_mappings"] = [
                {"source": m.source, "target": _qualify(m.target)} for m in om.request_mappings
            ]
        if om.response_mappings:
            op_entry["response_mappings"] = [
                {"source": m.source, "target": _qualify(m.target)} for m in om.response_mappings
            ]
        ops_out.append(op_entry)

    doc: dict[str, Any] = {
        "interface": iface.name,
        "entity": iface.entity_name or "",
    }
    if ops_out:
        doc["operations"] = ops_out

    return yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)


def generate_soap_operation_mapping(iface: UpstreamInterface) -> str:
    """Generate Engine SOAP operation mapping YAML."""
    operation = iface.selected_operation_name
    doc: dict[str, Any] = {"operation_mappings": []}
    if not operation:
        return yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)

    mode = iface.soap_operation_mode or "adapter_only"
    if mode == SOAP_MAPPING_MODE_CANONICAL and iface.soap_canonical_operation:
        canonical_config = iface.soap_canonical_operation
        canonical_operation: dict[str, Any] = {
            "kind": canonical_config.kind,
            "entity": canonical_config.entity or "",
            "lookup": {
                "request_path": canonical_config.request_path or "",
                "field": canonical_config.lookup_field or "",
            },
            "response_mappings": [
                {"source": mapping.source, "target_path": mapping.target_path}
                for mapping in canonical_config.response_mappings
            ],
        }
        if canonical_config.not_found_fault:
            fault: dict[str, Any] = {"fault": canonical_config.not_found_fault}
            if canonical_config.not_found_message:
                fault["message"] = canonical_config.not_found_message
            canonical_operation["not_found_fault"] = fault
        doc["operation_mappings"].append(
            {
                "operation": operation,
                "mode": SOAP_MAPPING_MODE_CANONICAL,
                "canonical_operation": canonical_operation,
            }
        )
        return yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)

    doc["operation_mappings"].append(
        {
            "operation": operation,
            "mode": "adapter_only",
            "handler_method": iface.soap_handler_method or soap_operation_handler_method(operation),
        }
    )
    return yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)


def generate_downstream_soap_operation_mapping(iface: DownstreamInterface) -> str:
    """Generate Engine outbound SOAP operation mapping YAML."""
    operation = iface.selected_operation_name
    doc: dict[str, Any] = {"operation_mappings": []}
    if not operation:
        return yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)

    mode = iface.soap_operation_mode or "adapter_only"
    if mode == SOAP_MAPPING_MODE_CANONICAL and iface.soap_canonical_invocation:
        canonical_config = iface.soap_canonical_invocation
        doc["operation_mappings"].append(
            {
                "operation": operation,
                "mode": SOAP_MAPPING_MODE_CANONICAL,
                "canonical_operation": {
                    "kind": canonical_config.kind,
                    "entity": canonical_config.entity or "",
                    "lookup": {
                        "request_field": canonical_config.request_field or "id",
                        "field": canonical_config.lookup_field or "",
                    },
                    "request_mappings": [
                        {"source": mapping.source, "target_path": mapping.target_path}
                        for mapping in canonical_config.request_mappings
                    ],
                    "response": {
                        "mode": canonical_config.response_mode or SOAP_RESPONSE_MODE_RETURN_ONLY,
                        "response_mappings": [
                            {"source_path": mapping.source_path, "target": mapping.target}
                            for mapping in canonical_config.response_mappings
                        ],
                    },
                },
            }
        )
        return yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)

    doc["operation_mappings"].append(
        {
            "operation": operation,
            "mode": "adapter_only",
        }
    )
    return yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)


def generate_upstream_file_mapping(iface: UpstreamInterface) -> str:
    """Generate Engine inbound file field-to-canonical mapping YAML."""
    entity_prefix = iface.entity_name or ""

    def _qualify(target: str) -> str:
        if entity_prefix and "." not in target:
            return f"{entity_prefix}.{target}"
        return target

    doc: dict[str, Any] = {
        "entity": iface.entity_name or "",
        "direction": "inbound",
        "field_mappings": [
            {"source": mapping.source, "target": _qualify(mapping.target)}
            for mapping in iface.field_mappings
        ],
    }
    return yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)


def generate_upstream_xml_mapping(iface: UpstreamInterface) -> str:
    """Generate Engine inbound XML/XSD field-to-canonical mapping YAML."""
    entity_prefix = iface.entity_name or ""

    def _qualify(target: str) -> str:
        if entity_prefix and "." not in target:
            return f"{entity_prefix}.{target}"
        return target

    doc: dict[str, Any] = {
        "entity": iface.entity_name or "",
        "direction": "inbound",
        "field_mappings": [
            {"source": mapping.source, "target": _qualify(mapping.target)}
            for mapping in iface.field_mappings
        ],
    }
    return yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)


def generate_downstream_mapping(iface: DownstreamInterface) -> str:
    """
    downstream mapping shape:
      interface: <name>
      entity: <entity_name>
      field_mappings:
        - source: Entity.field
          target: downstream_field
    """
    doc: dict[str, Any] = {
        "interface": iface.name,
        "entity": iface.entity_name or "",
    }
    if iface.field_mappings:
        doc["field_mappings"] = [
            {"source": m.source, "target": m.target} for m in iface.field_mappings
        ]
    return yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)


def generate_downstream_xml_mapping(iface: DownstreamInterface) -> str:
    """Generate Engine outbound XML/XSD canonical-to-XML mapping YAML."""
    doc: dict[str, Any] = {
        "entity": iface.entity_name or "",
        "direction": "outbound",
        "field_mappings": [
            {"source": mapping.source, "target": mapping.target}
            for mapping in iface.field_mappings
        ],
    }
    return yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _record_types_layout_document(
    *,
    name: str,
    format_name: str,
    fields: list[dict[str, Any]],
    **controls: Any,
) -> dict[str, Any]:
    """Build the Engine's current data-record file-layout document shape."""
    return {
        "name": name,
        "format": format_name,
        **controls,
        "record_types": {"data": {"fields": fields}},
    }


def generate_downstream_layout(iface: DownstreamInterface) -> str:
    """Generate the current Engine fixed-width ``record_types`` layout shape."""
    fields = [
        {"name": field.name, "position": field.start, "length": field.length}
        for field in iface.layout_fields
    ]
    doc = _record_types_layout_document(
        name=iface.name,
        format_name="fixed-width",
        fields=fields,
    )
    return yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)


def generate_handoff_mapping(handoff: DataHandoff) -> str:
    """
    data handoff mapping shape:
      table: <table_name>
      entity: <entity_name>
      field_mappings:
        - source: Entity.field
          target: column_name
    """
    doc: dict[str, Any] = {
        "table": handoff.table_name or handoff.name,
        "entity": handoff.entity_name or "",
    }
    if handoff.field_mappings:
        doc["field_mappings"] = [
            {"source": m.source, "target": m.target} for m in handoff.field_mappings
        ]
    return yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)
