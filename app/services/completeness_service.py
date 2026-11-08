"""Generate completeness report for a ProjectSession."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.models.project import ProjectSession
from app.services.canonical_mapping_validation import upstream_mapping_target_issues
from app.services.edge_contracts import (
    EDGE_CONTRACT_TYPES,
    FILE_CSV_TYPE,
    FILE_FIXED_WIDTH_TYPE,
    INCOMPLETE,
    REFERENCE_ONLY,
    SOAP_WSDL_TYPE,
    XML_XSD_TYPE,
    edge_contract_readiness,
)
from app.services.kafka_route_inventory import all_kafka_route_names, router_route_models
from app.services.kafka_schema_service import infer_reply_schema_content

Status = Literal["READY", "WARNING", "MANUAL_FOLLOW_UP"]


@dataclass
class CompletenessItem:
    status: Status
    category: str
    message: str


@dataclass
class CompletenessReport:
    items: list[CompletenessItem] = field(default_factory=list)

    def ready(self) -> list[CompletenessItem]:
        return [i for i in self.items if i.status == "READY"]

    def warnings(self) -> list[CompletenessItem]:
        return [i for i in self.items if i.status == "WARNING"]

    def manual(self) -> list[CompletenessItem]:
        return [i for i in self.items if i.status == "MANUAL_FOLLOW_UP"]

    def is_exportable(self) -> bool:
        """True if there are no MANUAL_FOLLOW_UP items at all.

        Any MANUAL_FOLLOW_UP item indicates a gap that would produce an
        invalid AppBuilder manifest (e.g. missing spec/spec_url, missing
        required field). The user must resolve all blockers before export.
        """
        return len(self.manual()) == 0

    def summary(self) -> dict:
        return {
            "ready": len(self.ready()),
            "warnings": len(self.warnings()),
            "manual_follow_up": len(self.manual()),
            "exportable": self.is_exportable(),
        }


def _interface_source_status(iface, session: ProjectSession) -> tuple[Status, str]:
    if iface.type in EDGE_CONTRACT_TYPES:
        readiness = edge_contract_readiness(iface, direction="upstream", session=session)
        if readiness.status == INCOMPLETE:
            missing = ", ".join(readiness.required_missing) or "required contract fields"
            return (
                "MANUAL_FOLLOW_UP",
                f"'{iface.name}': {readiness.type_label} contract is incomplete; missing {missing}.",
            )
        if readiness.status == REFERENCE_ONLY:
            return (
                "WARNING",
                f"'{iface.name}': {readiness.type_label} contract is reference only; Studio will not write artifact content into the package.",
            )
        return ("READY", f"'{iface.name}': has {readiness.type_label} contract source")

    if iface.type == XML_XSD_TYPE:
        if iface.spec_url:
            return (
                "MANUAL_FOLLOW_UP",
                f"'{iface.name}': XML/XSD contracts use xsd_path or spec, not spec_url.",
            )
        if iface.xsd_path or iface.spec:
            if iface.root_element:
                return (
                    "READY",
                    f"'{iface.name}': has XML/XSD contract source",
                )
            return (
                "MANUAL_FOLLOW_UP",
                f"'{iface.name}': XML/XSD contracts require a root element.",
            )
        return (
            "MANUAL_FOLLOW_UP",
            f"'{iface.name}': XML/XSD contracts require xsd_path or uploaded XSD content.",
        )

    if iface.type == SOAP_WSDL_TYPE:
        if iface.spec_url:
            return (
                "MANUAL_FOLLOW_UP",
                f"'{iface.name}': SOAP/WSDL contracts use wsdl_path or spec, not spec_url.",
            )
        if iface.wsdl_path or iface.spec:
            return (
                "READY",
                f"'{iface.name}': has SOAP/WSDL contract source",
            )
        return (
            "MANUAL_FOLLOW_UP",
            f"'{iface.name}': SOAP/WSDL contracts require wsdl_path or uploaded WSDL content.",
        )

    if iface.spec_url and iface.spec:
        return (
            "MANUAL_FOLLOW_UP",
            f"'{iface.name}': both spec and spec_url are set — AppBuilder requires exactly one. "
            "Remove one before exporting.",
        )
    if iface.spec_url or iface.spec:
        return ("READY", f"'{iface.name}': has spec source")
    if iface.spec_content:
        return (
            "READY",
            f"'{iface.name}': has embedded spec content; package path will be derived on export",
        )
    return (
        "MANUAL_FOLLOW_UP",
        f"'{iface.name}': no spec, spec_url, or embedded spec content. "
        "Provide an OpenAPI URL or upload a spec file. "
        "Manual/samples-only mode cannot produce a valid AppBuilder manifest.",
    )


def _downstream_interface_status(iface, session: ProjectSession) -> tuple[Status, str]:
    if iface.type in EDGE_CONTRACT_TYPES:
        readiness = edge_contract_readiness(iface, direction="downstream", session=session)
        if readiness.status == INCOMPLETE:
            missing = ", ".join(readiness.required_missing) or "required contract fields"
            return (
                "MANUAL_FOLLOW_UP",
                f"'{iface.name}': {readiness.type_label} contract is incomplete; missing {missing}.",
            )
        if readiness.status == REFERENCE_ONLY:
            return (
                "WARNING",
                f"'{iface.name}': {readiness.type_label} contract is reference only; Studio will not write artifact content into the package.",
            )
        return ("READY", f"'{iface.name}': has {readiness.type_label} contract source")
    if iface.type == FILE_CSV_TYPE:
        if iface.spec:
            return ("READY", f"'{iface.name}': has CSV/delimited file contract source")
        return (
            "MANUAL_FOLLOW_UP",
            f"'{iface.name}': CSV/delimited file contracts require a layout/spec path or uploaded layout/spec content.",
        )
    if iface.layout_fields:
        return ("READY", f"'{iface.name}': layout defined")
    return ("WARNING", f"'{iface.name}': no layout fields defined")


def _edge_contract_readiness_rows(session: ProjectSession):
    return [
        *(
            edge_contract_readiness(iface, direction="upstream", session=session)
            for iface in session.upstream_interfaces
            if iface.type in EDGE_CONTRACT_TYPES
        ),
        *(
            edge_contract_readiness(iface, direction="downstream", session=session)
            for iface in session.downstream_interfaces
            if iface.type in EDGE_CONTRACT_TYPES
        ),
    ]


def _has_crud_entity_classification(session: ProjectSession) -> bool:
    return any(entity.classification == "entity" for entity in session.classified_entities)


def _has_openapi_crud_source(session: ProjectSession) -> bool:
    if session.raw_spec_url or session.raw_spec_filename or session.raw_spec_content:
        return True
    return any(iface.type not in EDGE_CONTRACT_TYPES for iface in session.upstream_interfaces)


def build_completeness_report(session: ProjectSession) -> CompletenessReport:
    report = CompletenessReport()
    _add = report.items.append
    is_passthrough = session.app_archetype == "passthrough-router"
    is_kafka = session.app_archetype == "kafka-integration"
    edge_contract_rows = _edge_contract_readiness_rows(session)
    is_edge_contract_only = (
        bool(edge_contract_rows)
        and not _has_crud_entity_classification(session)
        and not _has_openapi_crud_source(session)
    )

    # --- Required top-level fields ---
    if session.app_name:
        _add(CompletenessItem("READY", "Project", "app_name is set"))
    else:
        _add(CompletenessItem("MANUAL_FOLLOW_UP", "Project", "app_name is required"))

    if session.bounded_context:
        _add(CompletenessItem("READY", "Project", "bounded_context is set"))
    else:
        _add(CompletenessItem("MANUAL_FOLLOW_UP", "Project", "bounded_context is required"))

    if session.target_profile:
        _add(CompletenessItem("READY", "Project", f"target_profile = {session.target_profile}"))
    else:
        _add(CompletenessItem("MANUAL_FOLLOW_UP", "Project", "target_profile is required"))

    # --- Archetype-specific authoring state ---
    if is_passthrough:
        _add(CompletenessItem("READY", "Project", "app_archetype = passthrough-router"))
    elif is_kafka:
        _add(CompletenessItem("READY", "Project", "app_archetype = kafka-integration"))
    else:
        _add(CompletenessItem("READY", "Project", "app_archetype = crud"))

    # --- Entities ---
    if is_passthrough:
        _add(CompletenessItem("READY", "Entities", "Passthrough archetype does not require CRUD entity selection"))
    elif is_kafka:
        _add(CompletenessItem("READY", "Entities", "Kafka archetype does not require CRUD entity selection"))
    elif session.selected_entity_names:
        _add(CompletenessItem(
            "READY", "Entities",
            f"{len(session.selected_entity_names)} entities selected: {', '.join(session.selected_entity_names)}"
        ))
    elif is_edge_contract_only:
        _add(CompletenessItem(
            "READY",
            "Entities",
            "Edge-contract-only package: CRUD entity selection is optional."
        ))
    else:
        _add(CompletenessItem(
            "MANUAL_FOLLOW_UP",
            "Entities",
            "No entities selected — select at least one entity before exporting"
        ))

    if is_kafka:
        cfg = session.kafka_config
        if cfg.consumer_group:
            _add(CompletenessItem("READY", "Kafka", f"consumer_group = {cfg.consumer_group}"))
        else:
            _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", "Kafka consumer_group is required"))
        if 1 <= cfg.concurrency <= 10:
            _add(CompletenessItem("READY", "Kafka", f"concurrency = {cfg.concurrency}"))
        else:
            _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", "Kafka concurrency must be between 1 and 10"))
        if cfg.dlq_enabled and not cfg.dlq_topic_suffix.startswith("."):
            _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", "DLQ topic suffix must start with '.' when DLQ is enabled"))
        elif cfg.dlq_enabled:
            _add(CompletenessItem("READY", "Kafka", f"DLQ enabled with suffix {cfg.dlq_topic_suffix}"))
        else:
            _add(CompletenessItem("READY", "Kafka", "DLQ disabled"))

        router_models = router_route_models(session)
        if session.kafka_topic_pairs:
            _add(CompletenessItem("READY", "Kafka", f"{len(session.kafka_topic_pairs)} Kafka route topic pair(s) defined"))
        elif router_models:
            _add(CompletenessItem("READY", "Kafka", f"{len(router_models)} Kafka router route(s) defined in Route Model"))
        else:
            _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", "Add at least one Kafka route topic pair"))

        route_names = all_kafka_route_names(session)
        route_name_set = set(route_names)
        if len(route_name_set) != len(route_names):
            _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", "Kafka route names must be unique"))

        route_models = {route.route_name: route for route in session.kafka_route_models}
        transforms = {transform.route_name: transform for transform in session.kafka_route_transforms}

        def add_router_config_checks(route_name: str, router_config) -> None:
            if router_config is None:
                _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", f"Route '{route_name}': router_config is required"))
                return
            if router_config.upstream_topics:
                _add(CompletenessItem("READY", "Kafka", f"Route '{route_name}': router upstream topic(s) defined"))
            else:
                _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", f"Route '{route_name}': router requires at least one upstream topic"))
            if router_config.targets:
                _add(CompletenessItem("READY", "Kafka", f"Route '{route_name}': router target(s) defined"))
            else:
                _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", f"Route '{route_name}': router requires at least one target"))
            target_ids = {target.id for target in router_config.targets if target.id}
            routing_fields = {
                field.name
                for field in router_config.routing_rules.routing_fields
                if field.name
            }
            for rule in router_config.routing_rules.rules:
                if rule.target in target_ids:
                    _add(CompletenessItem("READY", "Kafka", f"Route '{route_name}': router rule '{rule.id}' target is valid"))
                else:
                    _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", f"Route '{route_name}': router rule '{rule.id}' target must reference a target id"))
                for condition in rule.conditions:
                    if condition.field not in routing_fields:
                        _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", f"Route '{route_name}': router rule '{rule.id}' condition field must be declared"))
            if router_config.routing_rules.default_target and router_config.routing_rules.default_target not in target_ids:
                _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", f"Route '{route_name}': router default target must reference a target id"))
            if router_config.inbound_schema.file and router_config.outbound_schema.file:
                _add(CompletenessItem("READY", "Kafka", f"Route '{route_name}': router inbound/outbound schema references defined"))
            else:
                _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", f"Route '{route_name}': router inbound and outbound schema references are required"))
            if router_config.nack_routing.default_error_topic:
                _add(CompletenessItem("READY", "Kafka", f"Route '{route_name}': router NACK default error topic defined"))
            else:
                _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", f"Route '{route_name}': router NACK default_error_topic is required"))

        for pair in session.kafka_topic_pairs:
            if pair.upstream_topic:
                _add(CompletenessItem("READY", "Kafka", f"Route '{pair.route_name}': upstream topic = {pair.upstream_topic}"))
            else:
                _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", f"Route '{pair.route_name}': upstream topic is required"))
            if pair.downstream_topic:
                _add(CompletenessItem("READY", "Kafka", f"Route '{pair.route_name}': downstream topic = {pair.downstream_topic}"))
            else:
                _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", f"Route '{pair.route_name}': downstream topic is required"))
            if pair.upstream_schema_content:
                _add(CompletenessItem("READY", "Kafka", f"Route '{pair.route_name}': upstream schema content captured"))
            else:
                _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", f"Route '{pair.route_name}': upstream schema content is required"))
            if pair.downstream_schema_content:
                _add(CompletenessItem("READY", "Kafka", f"Route '{pair.route_name}': downstream schema content captured"))
            else:
                _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", f"Route '{pair.route_name}': downstream schema content is required"))

            model = route_models.get(pair.route_name)
            if model is None:
                _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", f"Route '{pair.route_name}': route model is required"))
                continue

            _add(CompletenessItem("READY", "Kafka", f"Route '{pair.route_name}': pattern = {model.pattern}"))
            transform = transforms.get(pair.route_name)
            if model.pattern == "router":
                add_router_config_checks(pair.route_name, model.router_config)
                continue

            if model.pattern == "request-reply":
                if model.upstream_reply_topic:
                    _add(CompletenessItem("READY", "Kafka", f"Route '{pair.route_name}': upstream reply topic = {model.upstream_reply_topic}"))
                else:
                    _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", f"Route '{pair.route_name}': upstream reply topic is required"))
                inferred_upstream_reply_schema = infer_reply_schema_content(model, transform, "upstream")
                inferred_downstream_reply_schema = infer_reply_schema_content(model, transform, "downstream")
                if inferred_upstream_reply_schema:
                    _add(CompletenessItem("READY", "Kafka", f"Route '{pair.route_name}': upstream reply schema content captured"))
                else:
                    _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", f"Route '{pair.route_name}': upstream reply schema content is required"))
                if model.downstream_reply_topic:
                    _add(CompletenessItem("READY", "Kafka", f"Route '{pair.route_name}': downstream reply topic = {model.downstream_reply_topic}"))
                else:
                    _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", f"Route '{pair.route_name}': downstream reply topic is required"))
                if inferred_downstream_reply_schema:
                    _add(CompletenessItem("READY", "Kafka", f"Route '{pair.route_name}': downstream reply schema content captured"))
                else:
                    _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", f"Route '{pair.route_name}': downstream reply schema content is required"))
                if model.correlation_field:
                    _add(CompletenessItem("READY", "Kafka", f"Route '{pair.route_name}': correlation field = {model.correlation_field}"))
                else:
                    _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", f"Route '{pair.route_name}': correlation field is required"))
                if model.reply_timeout_ms >= 1000:
                    _add(CompletenessItem("READY", "Kafka", f"Route '{pair.route_name}': reply timeout = {model.reply_timeout_ms} ms"))
                else:
                    _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", f"Route '{pair.route_name}': reply_timeout_ms must be at least 1000"))

            if transform and transform.mappings:
                _add(CompletenessItem("READY", "Kafka", f"Route '{pair.route_name}': request transform mappings defined"))
            else:
                _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", f"Route '{pair.route_name}': add at least one request transform mapping"))
            if model.pattern == "request-reply":
                if transform and transform.response_mappings:
                    _add(CompletenessItem("READY", "Kafka", f"Route '{pair.route_name}': response transform mappings defined"))
                else:
                    _add(CompletenessItem("MANUAL_FOLLOW_UP", "Kafka", f"Route '{pair.route_name}': add at least one response transform mapping"))

        fixed_route_name_set = {pair.route_name for pair in session.kafka_topic_pairs}
        for model in router_models:
            if model.route_name in fixed_route_name_set:
                continue
            _add(CompletenessItem("READY", "Kafka", f"Route '{model.route_name}': pattern = router"))
            add_router_config_checks(model.route_name, model.router_config)

    # --- Upstream interfaces ---
    if is_kafka:
        _add(CompletenessItem("READY", "Upstream", "Kafka archetype does not use CRUD upstream interfaces"))
    elif session.upstream_interfaces:
        for iface in session.upstream_interfaces:
            status, message = _interface_source_status(iface, session)
            _add(CompletenessItem(status, "Upstream", message))
            canonical_mapping_issues = upstream_mapping_target_issues(session, iface)
            for issue in canonical_mapping_issues:
                _add(CompletenessItem("MANUAL_FOLLOW_UP", "Upstream", issue.message))

            if iface.type == SOAP_WSDL_TYPE:
                if iface.selected_operation_name:
                    _add(CompletenessItem(
                        "READY",
                        "Upstream",
                        f"'{iface.name}': selected inbound SOAP operation '{iface.selected_operation_name}'"
                    ))
                    readiness = edge_contract_readiness(iface, direction="upstream", session=session)
                    if readiness.status == INCOMPLETE:
                        missing = ", ".join(readiness.required_missing) or "required SOAP mapping fields"
                        _add(CompletenessItem(
                            "MANUAL_FOLLOW_UP",
                            "Upstream",
                            f"'{iface.name}': SOAP operation mapping is incomplete; missing {missing}"
                        ))
                    elif iface.soap_operation_mode == "canonical":
                        _add(CompletenessItem(
                            "READY",
                            "Upstream",
                            f"'{iface.name}': Studio will export canonical SOAP read_by_id mapping"
                        ))
                    else:
                        _add(CompletenessItem(
                            "READY",
                            "Upstream",
                            f"'{iface.name}': Studio will export SOAP operation-to-handler mapping"
                        ))
                else:
                    _add(CompletenessItem(
                        "WARNING",
                        "Upstream",
                        f"'{iface.name}': select a SOAP operation to export inbound endpoint mapping"
                    ))
                continue

            if iface.type in {FILE_CSV_TYPE, FILE_FIXED_WIDTH_TYPE}:
                if canonical_mapping_issues:
                    pass
                elif iface.field_mappings and iface.entity_name:
                    _add(CompletenessItem(
                        "READY",
                        "Upstream",
                        f"'{iface.name}': has reviewed file-to-canonical mappings for {iface.entity_name}"
                    ))
                elif iface.field_mappings:
                    _add(CompletenessItem(
                        "WARNING",
                        "Upstream",
                        f"'{iface.name}': file mappings are saved, but canonical entity name is blank"
                    ))
                else:
                    _add(CompletenessItem(
                        "WARNING",
                        "Upstream",
                        f"'{iface.name}': no explicit file-to-canonical mappings; Engine may infer fields, but reviewed mappings are recommended."
                    ))
                continue

            # operations
            if is_passthrough:
                if iface.selected_operation_name:
                    _add(CompletenessItem(
                        "READY",
                        "Upstream",
                        f"'{iface.name}': selected passthrough operation '{iface.selected_operation_name}'"
                    ))
                else:
                    _add(CompletenessItem(
                        "MANUAL_FOLLOW_UP",
                        "Upstream",
                        f"'{iface.name}': select exactly one inbound passthrough operation"
                    ))
            elif not iface.operations:
                _add(CompletenessItem("WARNING", "Upstream", f"'{iface.name}': no operations defined"))
            else:
                for op in iface.operations:
                    if not op.has_sample():
                        _add(CompletenessItem(
                            "MANUAL_FOLLOW_UP", "Upstream",
                            f"'{iface.name}' → operation '{op.name}': needs at least one sample (request or response)"
                        ))
                    else:
                        _add(CompletenessItem("READY", "Upstream", f"'{iface.name}' → '{op.name}': has sample(s)"))

            # mapping
            if is_passthrough:
                _add(CompletenessItem("READY", "Upstream", f"'{iface.name}': passthrough export does not require CRUD field mappings"))
            elif canonical_mapping_issues:
                pass
            elif not iface.operation_mappings:
                _add(CompletenessItem("WARNING", "Upstream", f"'{iface.name}': no field mappings defined"))
            else:
                _add(CompletenessItem("READY", "Upstream", f"'{iface.name}': has field mappings"))
    else:
        if is_edge_contract_only:
            _add(CompletenessItem(
                "READY",
                "Upstream",
                "Edge-contract-only package uses reviewed edge-contract interfaces; OpenAPI upstream source is optional"
            ))
        else:
            _add(CompletenessItem(
                "MANUAL_FOLLOW_UP",
                "Upstream",
                "No upstream interfaces defined — define at least one upstream interface before exporting"
            ))

    # --- Downstream ---
    if is_kafka:
        _add(CompletenessItem("READY", "Downstream", "Kafka archetype does not use CRUD downstream interfaces"))
    elif session.downstream_interfaces:
        for iface in session.downstream_interfaces:
            if is_passthrough:
                if iface.system:
                    _add(CompletenessItem("READY", "Downstream", f"'{iface.name}': system = {iface.system}"))
                else:
                    _add(CompletenessItem("MANUAL_FOLLOW_UP", "Downstream", f"'{iface.name}': system name is required"))
                if iface.selected_operation_name:
                    _add(CompletenessItem("READY", "Downstream", f"'{iface.name}': selected target operation '{iface.selected_operation_name}'"))
                else:
                    _add(CompletenessItem("MANUAL_FOLLOW_UP", "Downstream", f"'{iface.name}': select exactly one target operation"))
                if iface.spec or iface.spec_url or iface.spec_content:
                    _add(CompletenessItem("READY", "Downstream", f"'{iface.name}': has spec source"))
                else:
                    _add(CompletenessItem("MANUAL_FOLLOW_UP", "Downstream", f"'{iface.name}': downstream spec source is required"))
            else:
                status, message = _downstream_interface_status(iface, session)
                _add(CompletenessItem(status, "Downstream", message))
            if is_passthrough:
                _add(CompletenessItem("READY", "Downstream", f"'{iface.name}': passthrough target captured"))
            elif iface.type == SOAP_WSDL_TYPE:
                readiness = edge_contract_readiness(iface, direction="downstream", session=session)
                if readiness.status == INCOMPLETE:
                    missing = ", ".join(readiness.required_missing) or "required SOAP mapping fields"
                    _add(CompletenessItem(
                        "MANUAL_FOLLOW_UP",
                        "Downstream",
                        f"'{iface.name}': downstream SOAP operation mapping is incomplete; missing {missing}"
                    ))
                elif iface.selected_operation_name and iface.soap_operation_mode == "canonical":
                    _add(CompletenessItem(
                        "READY",
                        "Downstream",
                        f"'{iface.name}': Studio will export canonical SOAP invoke_by_id mapping"
                    ))
                elif iface.selected_operation_name:
                    _add(CompletenessItem(
                        "READY",
                        "Downstream",
                        f"'{iface.name}': Studio will export adapter-only SOAP operation mapping"
                    ))
                else:
                    _add(CompletenessItem(
                        "WARNING",
                        "Downstream",
                        f"'{iface.name}': select a SOAP operation to export downstream operation mapping"
                    ))
            elif iface.field_mappings:
                _add(CompletenessItem("READY", "Downstream", f"'{iface.name}': field mappings defined"))
            else:
                if iface.type in {FILE_CSV_TYPE, FILE_FIXED_WIDTH_TYPE}:
                    _add(CompletenessItem("WARNING", "Downstream", f"'{iface.name}': no canonical-to-file mappings saved"))
                else:
                    _add(CompletenessItem("WARNING", "Downstream", f"'{iface.name}': no field mappings supplied"))
    else:
        _add(CompletenessItem("WARNING", "Downstream", "No downstream interface defined"))

    # --- Data handoffs ---
    if is_kafka:
        _add(CompletenessItem("READY", "DataHandoff", "Kafka archetype does not use staging handoffs"))
    elif session.data_handoffs:
        for h in session.data_handoffs:
            if h.ddl_content or h.spec:
                _add(CompletenessItem("READY", "DataHandoff", f"'{h.name}': DDL provided"))
            else:
                _add(CompletenessItem("WARNING", "DataHandoff", f"'{h.name}': no DDL provided"))
            if h.field_mappings:
                _add(CompletenessItem("READY", "DataHandoff", f"'{h.name}': mappings defined"))
            else:
                _add(CompletenessItem("WARNING", "DataHandoff", f"'{h.name}': no field mappings supplied"))
    else:
        _add(CompletenessItem("WARNING", "DataHandoff", "No staging handoff defined"))

    # --- Rules ---
    if is_passthrough:
        if session.passthrough_flow.route_field:
            _add(CompletenessItem("READY", "Rules", f"Routing field = {session.passthrough_flow.route_field}"))
        else:
            _add(CompletenessItem("MANUAL_FOLLOW_UP", "Rules", "Passthrough route field is required"))
        if session.passthrough_flow.routes:
            _add(CompletenessItem("READY", "Rules", f"{len(session.passthrough_flow.routes)} passthrough route row(s) defined"))
        else:
            _add(CompletenessItem("MANUAL_FOLLOW_UP", "Rules", "Add at least one passthrough route row"))
        if session.passthrough_flow.default_target:
            _add(CompletenessItem("READY", "Rules", f"Default passthrough target = {session.passthrough_flow.default_target}"))
        else:
            _add(CompletenessItem("MANUAL_FOLLOW_UP", "Rules", "Default passthrough target is required"))
        if session.passthrough_flow.transforms:
            _add(CompletenessItem("READY", "Rules", f"{len(session.passthrough_flow.transforms)} passthrough transform(s) defined"))
        else:
            _add(CompletenessItem("MANUAL_FOLLOW_UP", "Rules", "Add at least one flat passthrough transform"))
    elif is_kafka:
        if session.entity_rules:
            for er in session.entity_rules:
                if er.rules:
                    _add(CompletenessItem("READY", "Rules", f"Entity '{er.entity_name}': {len(er.rules)} rule(s) defined"))
                else:
                    _add(CompletenessItem("WARNING", "Rules", f"Entity '{er.entity_name}': no rules added"))
        else:
            _add(CompletenessItem("WARNING", "Rules", "No business rules defined"))
    elif session.entity_rules:
        for er in session.entity_rules:
            if er.rules:
                _add(CompletenessItem("READY", "Rules", f"Entity '{er.entity_name}': {len(er.rules)} rule(s) defined"))
            else:
                _add(CompletenessItem("WARNING", "Rules", f"Entity '{er.entity_name}': no rules added"))
    else:
        _add(CompletenessItem("WARNING", "Rules", "No business rules defined"))

    # --- Legacy ---
    if session.legacy_notes:
        _add(CompletenessItem("READY", "Legacy", "Legacy notes provided"))
    else:
        _add(CompletenessItem("WARNING", "Legacy", "No legacy notes — consider adding context for developers"))

    return report


def render_completeness_markdown(report: CompletenessReport, session: ProjectSession) -> str:
    lines = [
        f"# Completeness Report — {session.app_name or 'Unnamed Project'}",
        "",
        f"**Summary:** {len(report.ready())} READY | "
        f"{len(report.warnings())} WARNING | "
        f"{len(report.manual())} MANUAL FOLLOW-UP",
        "",
    ]

    for status, label in [("READY", "✅ READY"), ("WARNING", "⚠️ WARNING"), ("MANUAL_FOLLOW_UP", "🔴 MANUAL FOLLOW-UP REQUIRED")]:
        items = [i for i in report.items if i.status == status]
        if items:
            lines.append(f"## {label}")
            lines.append("")
            for item in items:
                lines.append(f"- **[{item.category}]** {item.message}")
            lines.append("")

    return "\n".join(lines)
