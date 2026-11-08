"""Generate app-definition.yaml from a ProjectSession."""

from __future__ import annotations

from typing import Any

import yaml

from app.models.project import ProjectSession
from app.services.edge_contracts import (
    EDGE_CONTRACT_TYPES,
    FILE_CSV_TYPE,
    FILE_FIXED_WIDTH_TYPE,
    SOAP_WSDL_TYPE,
    XML_XSD_TYPE,
    default_downstream_file_mapping_path,
    default_downstream_xml_mapping_path,
    default_soap_operation_mapping_path,
    default_upstream_file_mapping_path,
    default_upstream_xml_mapping_path,
    edge_contract_readiness,
)
from app.services.identity_roles import identity_overrides_for_manifest, identity_roles_for_manifest
from app.services.kafka_route_inventory import router_route_models
from app.services.manifest_contract import STUDIO_MANIFEST_SCHEMA_VERSION


def build_manifest_dict(session: ProjectSession) -> dict[str, Any]:
    """Return a dict that serialises to a valid app-definition.yaml.

    Field order matches the EdgeForge Engine manifest 2.0 contract:
    app_name, bounded_context, schema_version, app_archetype, target_profile, ...
    """

    manifest: dict[str, Any] = {
        "app_name": session.app_name,
        "bounded_context": session.bounded_context,
        "schema_version": STUDIO_MANIFEST_SCHEMA_VERSION,
        "app_archetype": session.app_archetype or "crud",
        "target_profile": session.target_profile,
    }

    if session.app_archetype == "kafka-integration":
        _add_kafka_sections(manifest, session)
    elif session.app_archetype == "crud":
        identity_overrides = identity_overrides_for_manifest(session)
        if identity_overrides:
            manifest["identity_overrides"] = identity_overrides
        identity_roles = identity_roles_for_manifest(session)
        if identity_roles:
            manifest["identity_roles"] = identity_roles

    # Upstream interfaces
    if session.upstream_interfaces:
        entries = [_upstream_entry(iface, session=session) for iface in session.upstream_interfaces]
        entries = [entry for entry in entries if entry is not None]
        if entries:
            manifest["upstream_interfaces"] = entries

    # Downstream interfaces
    if session.downstream_interfaces:
        entries = [_downstream_entry(iface, session=session) for iface in session.downstream_interfaces]
        entries = [entry for entry in entries if entry is not None]
        if entries:
            manifest["downstream_interfaces"] = entries

    # Data handoffs
    if session.app_archetype != "passthrough-router" and session.data_handoffs:
        manifest["data_handoffs"] = [
            _handoff_entry(h) for h in session.data_handoffs
        ]

    # Rules — list of file paths
    rule_paths: list[str] = []
    if session.app_archetype == "passthrough-router":
        if session.passthrough_flow.rule_path:
            rule_paths.append(session.passthrough_flow.rule_path)
    else:
        for er in session.entity_rules:
            if er.file_path and er.rules:
                rule_paths.append(er.file_path)
    if rule_paths:
        manifest["rules"] = rule_paths

    # Legacy references
    if session.legacy_notes and session.legacy_slug:
        manifest["legacy_references"] = [f"legacy/{session.legacy_slug}-notes.md"]

    return manifest


def generate_manifest_yaml(session: ProjectSession) -> str:
    d = build_manifest_dict(session)
    return yaml.dump(d, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _add_kafka_sections(manifest: dict[str, Any], session: ProjectSession) -> None:
    cfg = session.kafka_config
    kafka_config: dict[str, Any] = {
        "consumer_group": cfg.consumer_group,
        "concurrency": cfg.concurrency,
    }
    if cfg.retry_max_attempts:
        kafka_config["retry"] = {
            "max_attempts": cfg.retry_max_attempts,
            "backoff_ms": cfg.retry_backoff_ms,
            "backoff_multiplier": cfg.retry_backoff_multiplier,
        }
    if cfg.dlq_enabled:
        kafka_config["dlq"] = {
            "enabled": True,
            "topic_suffix": cfg.dlq_topic_suffix,
        }
    manifest["kafka_config"] = kafka_config

    route_models = {r.route_name: r for r in session.kafka_route_models}
    transforms = {t.route_name: t for t in session.kafka_route_transforms}

    async_routes = []
    emitted_route_names: set[str] = set()
    for pair in session.kafka_topic_pairs:
        rname = pair.route_name
        model = route_models.get(rname)
        transform = transforms.get(rname)
        pattern = model.pattern if model else "fire-and-forget"
        if pattern == "router":
            route = {
                "name": rname,
                "pattern": "router",
                "router_config": _router_config_entry(model),
            }
            async_routes.append(route)
            emitted_route_names.add(rname)
            continue

        route: dict[str, Any] = {
            "name": rname,
            "pattern": pattern,
            "upstream_topic": {
                "name": pair.upstream_topic,
                "system": pair.upstream_system,
                "message_schema": pair.upstream_schema_path or f"schemas/{rname}-upstream.json",
            },
            "downstream_topic": {
                "name": pair.downstream_topic,
                "system": pair.downstream_system,
                "message_schema": pair.downstream_schema_path or f"schemas/{rname}-downstream.json",
            },
        }
        if transform and transform.mappings:
            route["transform_mapping"] = f"mappings/{rname}.yaml"
        if model and model.pattern == "request-reply":
            route["upstream_reply_topic"] = {
                "name": model.upstream_reply_topic,
                "message_schema": model.upstream_reply_schema_path or f"schemas/{rname}-upstream-reply.json",
            }
            route["downstream_reply_topic"] = {
                "name": model.downstream_reply_topic,
                "message_schema": model.downstream_reply_schema_path or f"schemas/{rname}-downstream-reply.json",
            }
            route["correlation_id"] = {
                "source": "body_field" if model.correlation_source == "payload" else model.correlation_source,
                "field_name": model.correlation_field,
            }
            route["reply_timeout_ms"] = model.reply_timeout_ms
            if transform and transform.response_mappings:
                route["response_transform_mapping"] = f"mappings/{rname}-response.yaml"
        async_routes.append(route)
        emitted_route_names.add(rname)

    for model in router_route_models(session):
        if model.route_name in emitted_route_names:
            continue
        async_routes.append(
            {
                "name": model.route_name,
                "pattern": "router",
                "router_config": _router_config_entry(model),
            }
        )
        emitted_route_names.add(model.route_name)

    if async_routes:
        manifest["async_routes"] = async_routes


def _router_config_entry(model) -> dict[str, Any]:
    if model is None or model.router_config is None:
        return {}
    config = model.router_config.model_dump(exclude_none=True)
    for topic in config.get("upstream_topics", []):
        for key in ("source_system_extraction", "reply_destination_extraction"):
            extraction = topic.get(key)
            if not isinstance(extraction, dict):
                continue
            if extraction.get("mode") == "header":
                extraction.pop("body_field_path", None)
            if extraction.get("mode") == "body_field":
                extraction.pop("header_key", None)
    nack_routing = config.get("nack_routing")
    if isinstance(nack_routing, dict):
        _normalize_router_nack_routing(nack_routing)
    return config


def _normalize_router_nack_routing(nack_routing: dict[str, Any]) -> None:
    mode = nack_routing.get("mode")

    if mode == "per_source_system":
        mappings = nack_routing.get("per_source_system")
        if isinstance(mappings, dict):
            valid_mappings = {
                str(source): str(topic)
                for source, topic in mappings.items()
                if source and topic
            }
            if valid_mappings:
                nack_routing["per_source_system"] = valid_mappings
            else:
                nack_routing.pop("per_source_system", None)
        else:
            nack_routing.pop("per_source_system", None)
    else:
        nack_routing.pop("per_source_system", None)

    if mode != "fixed" or not nack_routing.get("fixed_topic"):
        nack_routing.pop("fixed_topic", None)


# ---------------------------------------------------------------------------
# Per-entry builders
# ---------------------------------------------------------------------------

def _upstream_entry(iface, *, session: ProjectSession | None = None) -> dict[str, Any] | None:
    entry: dict[str, Any] = {"name": iface.name}
    if iface.system:
        entry["system"] = iface.system
    entry["type"] = iface.type
    if iface.version:
        entry["version"] = iface.version
    if not _add_interface_contract_reference(entry, iface, session=session):
        return None
    if iface.type == SOAP_WSDL_TYPE and iface.selected_operation_name:
        entry["mapping"] = iface.mapping_path or default_soap_operation_mapping_path(iface.name)
    elif iface.type == XML_XSD_TYPE and iface.field_mappings and iface.entity_name:
        entry["mapping"] = iface.mapping_path or default_upstream_xml_mapping_path(iface.name)
    elif iface.type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE} and iface.field_mappings and iface.entity_name:
        entry["mapping"] = iface.mapping_path or default_upstream_file_mapping_path(iface.name)
    elif iface.mapping_path and iface.type not in EDGE_CONTRACT_TYPES:
        entry["mapping"] = iface.mapping_path
    if iface.sample_path and iface.sample_content and iface.type in {XML_XSD_TYPE, SOAP_WSDL_TYPE}:
        entry["sample"] = iface.sample_path
    elif iface.sample_path and iface.sample_content:
        entry["samples"] = [iface.sample_path]
    if iface.operations and not (iface.type == SOAP_WSDL_TYPE and iface.selected_operation_name):
        entry["operations"] = [_operation_entry(op) for op in iface.operations]
    return entry


def _operation_entry(op) -> dict[str, Any]:
    e: dict[str, Any] = {"name": op.name}
    # Only include sample paths when content actually exists — otherwise AppBuilder
    # rejects the manifest because the referenced file is missing on disk.
    if op.request_sample_path and op.request_sample_content:
        e["request_sample"] = op.request_sample_path
    if op.response_sample_path and op.response_sample_content:
        e["response_sample"] = op.response_sample_path
    return e


def _downstream_entry(iface, *, session: ProjectSession | None = None) -> dict[str, Any] | None:
    entry: dict[str, Any] = {"name": iface.name}
    if iface.system:
        entry["system"] = iface.system
    entry["type"] = iface.type
    if iface.version:
        entry["version"] = iface.version
    if not _add_interface_contract_reference(entry, iface, session=session):
        return None
    if iface.type == XML_XSD_TYPE and iface.field_mappings and iface.entity_name:
        entry["mapping"] = iface.mapping_path or default_downstream_xml_mapping_path(iface.name)
    elif iface.type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE} and iface.field_mappings:
        entry["mapping"] = iface.mapping_path or default_downstream_file_mapping_path(iface.name)
    elif iface.type == SOAP_WSDL_TYPE and iface.selected_operation_name:
        entry["mapping"] = iface.mapping_path or default_soap_operation_mapping_path(iface.name)
    elif iface.mapping_path and iface.type not in EDGE_CONTRACT_TYPES:
        entry["mapping"] = iface.mapping_path
    if iface.sample_path and iface.sample_content and iface.type in {XML_XSD_TYPE, SOAP_WSDL_TYPE}:
        entry["sample"] = iface.sample_path
    elif iface.sample_path and iface.sample_content:
        entry["samples"] = [iface.sample_path]
    elif iface.samples:
        entry["samples"] = iface.samples
    return entry


def _add_interface_contract_reference(entry: dict[str, Any], iface, *, session: ProjectSession | None = None) -> bool:
    if iface.type in EDGE_CONTRACT_TYPES:
        direction = "downstream" if hasattr(iface, "layout_fields") else "upstream"
        readiness = edge_contract_readiness(iface, direction=direction, session=session)
        if not readiness.will_export:
            return False

    if iface.type == XML_XSD_TYPE:
        if not readiness.artifact_path or not iface.root_element:
            return False
        if iface.xsd_path:
            entry["xsd_path"] = iface.xsd_path
        elif iface.spec:
            entry["spec"] = iface.spec
        elif readiness.artifact_path:
            entry["xsd_path"] = readiness.artifact_path
        entry["root_element"] = iface.root_element
        if iface.namespace:
            entry["namespace"] = iface.namespace
        if iface.namespace_alias:
            entry["namespace_alias"] = iface.namespace_alias
        return True

    if iface.type == SOAP_WSDL_TYPE:
        if not readiness.artifact_path:
            return False
        if iface.wsdl_path:
            entry["wsdl_path"] = iface.wsdl_path
        elif iface.spec:
            entry["spec"] = iface.spec
        elif readiness.artifact_path:
            entry["wsdl_path"] = readiness.artifact_path
        if iface.service:
            entry["service"] = iface.service
        if iface.port:
            entry["port"] = iface.port
        if iface.binding:
            entry["binding"] = iface.binding
        return True

    if iface.type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE}:
        if not readiness.artifact_path:
            return False
        entry["spec"] = readiness.artifact_path
        return True

    if iface.spec_url:
        entry["spec_url"] = iface.spec_url
    elif iface.spec:
        entry["spec"] = iface.spec
    return True


def _handoff_entry(h) -> dict[str, Any]:
    entry: dict[str, Any] = {"name": h.name}
    if h.system:
        entry["system"] = h.system
    entry["type"] = h.type
    if h.version:
        entry["version"] = h.version
    if h.spec:
        entry["spec"] = h.spec
    if h.mapping_path:
        entry["mapping"] = h.mapping_path
    return entry
