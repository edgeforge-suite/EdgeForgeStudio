"""Write a complete AppBuilder input package to disk."""

from __future__ import annotations

import copy
import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.models.project import KSManifestRevision, ProjectSession
from app.services.canonical_mapping_validation import all_upstream_mapping_target_issues
from app.services.completeness_service import (
    build_completeness_report,
    render_completeness_markdown,
)
from app.services.csv_layout import CsvLayoutError, prepare_csv_layout_for_export
from app.services.edge_contracts import (
    EDGE_CONTRACT_TYPES,
    FILE_CSV_TYPE,
    FILE_FIXED_WIDTH_TYPE,
    INCOMPLETE,
    SOAP_WSDL_TYPE,
    XML_XSD_TYPE,
    clean_package_path,
    default_artifact_path,
    default_downstream_file_mapping_path,
    default_downstream_xml_mapping_path,
    default_soap_operation_mapping_path,
    default_upstream_file_mapping_path,
    default_upstream_xml_mapping_path,
    edge_contract_readiness_rows,
)
from app.services.evidence_trail import EvidenceTrailBuildResult, build_evidence_trail
from app.services.kafka_route_inventory import router_route_models
from app.services.kafka_schema_service import infer_reply_schema_content
from app.services.manifest_generator import generate_manifest_yaml
from app.services.mapping_generator import (
    generate_downstream_layout,
    generate_downstream_mapping,
    generate_downstream_soap_operation_mapping,
    generate_downstream_xml_mapping,
    generate_handoff_mapping,
    generate_soap_operation_mapping,
    generate_upstream_file_mapping,
    generate_upstream_mapping,
    generate_upstream_xml_mapping,
)
from app.services.passthrough_service import (
    dump_openapi_spec,
    filter_spec_to_operation,
    load_openapi_spec,
    serialize_passthrough_rules,
)
from app.services.path_resolver import PathResolutionError, contain_under_session_workspace
from app.services.project_file_service import serialize_project, snapshot_session_for_save
from app.services.rule_generator import generate_rule_yaml


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _kafka_schema_path(route_name: str, direction: str) -> str:
    return f"schemas/{route_name}-{direction}.json"


def _generate_kafka_transform_yaml(rows: list) -> str:
    doc: dict[str, Any] = {
        "transforms": [
            {"source": row.source_field, "target": row.target_field}
            for row in rows
        ]
    }
    return yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _generate_kafka_router_transform_yaml(rows: list) -> str:
    transform_rows: list[dict[str, Any]] = []
    for row in rows:
        entry: dict[str, Any] = {"target": row.target}
        if row.source:
            entry["source"] = row.source
        if row.default_value is not None:
            entry["default"] = row.default_value
        if row.constant is not None:
            entry["constant"] = row.constant
        if row.value_map:
            entry["value_map"] = dict(row.value_map)
        if row.type_coercion:
            entry["type_coercion"] = row.type_coercion
        transform_rows.append(entry)
    return yaml.dump(
        {"transforms": transform_rows},
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )


def _router_file_references(router_config) -> list[str]:
    if router_config is None:
        return []

    refs: list[str] = []

    def add(ref: str | None) -> None:
        if ref:
            refs.append(ref)

    add(router_config.inbound_schema.file)
    add(router_config.outbound_schema.file)
    for target in router_config.targets:
        add(target.request_schema.file)
        add(target.response_schema.file)
        add(target.request_transform.file)
        add(target.response_transform.file)
    return refs


def _missing_package_references(project_dir: Path, refs: list[str]) -> list[str]:
    seen: set[str] = set()
    missing: list[str] = []
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        if not (project_dir / ref).exists():
            missing.append(ref)
    return missing


@dataclass(frozen=True)
class PackageWriteResult:
    written: list[str]
    project_dir: Path
    evidence_trail: EvidenceTrailBuildResult
    warnings: list[str]


class PackageWriteError(RuntimeError):
    """Raised when Studio cannot produce a self-contained package."""


def write_package(session: ProjectSession, root: Path) -> list[str]:
    return write_package_result(session, root).written


def write_package_result(session: ProjectSession, root: Path) -> PackageWriteResult:
    """Write all files to root/<project-slug>/. Returns list of written relative paths.

    Works on a deep copy of *session* so that transient generate-compatibility
    rewrites (e.g. resolving spec_url → local spec file so AppBuilder skips live
    entity ingestion) never mutate the caller's live session object.  Stable
    file-path assignments that were newly derived here (mapping files, rule files,
    DDL files) are propagated back to the original session so that subsequent saves
    retain the correct paths.
    """
    # Deep copy so all mutations are isolated to this function.
    working = copy.deepcopy(session)

    for iface in working.downstream_interfaces:
        if iface.type != FILE_CSV_TYPE or not iface.spec_content:
            continue
        try:
            iface.spec_content = prepare_csv_layout_for_export(
                iface.spec_content,
                name=iface.name,
            )
        except CsvLayoutError as exc:
            raise PackageWriteError(
                f"Downstream CSV contract '{iface.name}' has an invalid layout: {exc}"
            ) from exc

    canonical_mapping_issues = all_upstream_mapping_target_issues(working)
    if canonical_mapping_issues:
        raise PackageWriteError(
            "Canonical mapping export is invalid. Resolve these mappings before exporting: "
            + "; ".join(issue.message for issue in canonical_mapping_issues)
        )

    readiness_rows = [
        *edge_contract_readiness_rows(working.upstream_interfaces, direction="upstream", session=working),
        *edge_contract_readiness_rows(working.downstream_interfaces, direction="downstream", session=working),
    ]
    incomplete_rows = [row for row in readiness_rows if row.status == INCOMPLETE]
    if incomplete_rows:
        details = []
        for row in incomplete_rows:
            missing = ", ".join(row.required_missing) or "required contract fields"
            details.append(f"{row.direction} '{row.name}' ({row.type}): missing {missing}")
        raise PackageWriteError(
            "Edge contract export is incomplete. Resolve these contract references before exporting: "
            + "; ".join(details)
        )

    warnings: list[str] = []
    for row in readiness_rows:
        warnings.extend(row.warnings)

    def confined(path: Path) -> Path:
        try:
            return contain_under_session_workspace(session, path)
        except PathResolutionError as exc:
            raise PackageWriteError(str(exc)) from exc

    project_dir = confined(root / _slug(working.bounded_context or working.app_name or "project"))
    project_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    written_content: dict[str, str] = {}

    def write(rel: str, content: str) -> None:
        try:
            safe_rel = clean_package_path(rel)
        except ValueError as exc:
            raise PackageWriteError(f"Invalid package artifact path '{rel}': {exc}") from exc
        if not safe_rel:
            raise PackageWriteError("Invalid package artifact path: empty path.")
        previous_content = written_content.get(safe_rel)
        if previous_content is not None and previous_content != content:
            raise PackageWriteError(
                f"Duplicate package artifact path '{safe_rel}' has different content. "
                "Choose unique package-relative paths for edge-contract artifacts."
            )
        written_content[safe_rel] = content
        p = confined(project_dir / safe_rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        if safe_rel not in written:
            written.append(safe_rel)

    def include_existing(rel: str) -> None:
        if rel not in written and confined(project_dir / rel).exists():
            written.append(rel)

    # ------------------------------------------------------------------
    # Upstream mappings and samples
    # ------------------------------------------------------------------
    for iface in working.upstream_interfaces:
        if iface.type in EDGE_CONTRACT_TYPES:
            if iface.type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE} and iface.spec_content:
                iface.spec = iface.spec or default_artifact_path("upstream", iface.name, iface.type)
                write(iface.spec, iface.spec_content)
            elif iface.type == XML_XSD_TYPE and iface.xsd_content:
                iface.xsd_path = iface.xsd_path or default_artifact_path("upstream", iface.name, iface.type)
                write(iface.xsd_path, iface.xsd_content)
            elif iface.type == SOAP_WSDL_TYPE and iface.wsdl_content:
                iface.wsdl_path = iface.wsdl_path or default_artifact_path("upstream", iface.name, iface.type)
                write(iface.wsdl_path, iface.wsdl_content)
            if iface.type == SOAP_WSDL_TYPE and iface.selected_operation_name:
                iface.mapping_path = iface.mapping_path or default_soap_operation_mapping_path(iface.name)
                write(iface.mapping_path, generate_soap_operation_mapping(iface))
            if iface.type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE} and iface.field_mappings and iface.entity_name:
                iface.mapping_path = iface.mapping_path or default_upstream_file_mapping_path(iface.name)
                write(iface.mapping_path, generate_upstream_file_mapping(iface))
            if iface.type == XML_XSD_TYPE and iface.field_mappings and iface.entity_name:
                iface.mapping_path = iface.mapping_path or default_upstream_xml_mapping_path(iface.name)
                write(iface.mapping_path, generate_upstream_xml_mapping(iface))
            if iface.sample_path and iface.sample_content:
                write(iface.sample_path, iface.sample_content)
            continue

        if working.app_archetype == "passthrough-router":
            if iface.selected_operation_name:
                spec = load_openapi_spec(spec_url=iface.spec_url, spec_content=iface.spec_content)
                filtered_spec = filter_spec_to_operation(spec, iface.selected_operation_name)
                spec_rel = iface.spec or f"upstream/{_slug(iface.name)}-spec.yaml"
                iface.spec = spec_rel
                iface.spec_url = None
                write(spec_rel, dump_openapi_spec(filtered_spec))
            continue

        # Spec file — always use a local copy so AppBuilder reads the spec
        # from disk rather than fetching it live.  When spec_url is present
        # AppBuilder runs ingest_openapi_entities() against the live URL,
        # which derives entity names from URL path segments (e.g. /api/v1/…
        # → entity "Api") instead of from the actual schema names.  Writing
        # a local file and switching to spec: prevents that mis-classification.
        #
        # This rewrite happens only on *working* (the deep copy) so the caller's
        # session retains the original spec_url for assess and other URL-aware ops.
        if iface.spec_content:
            # Content was uploaded directly — write it to the declared path
            # (or a default contracts/ path if none was set yet).
            spec_rel = iface.spec or f"contracts/{_slug(iface.name)}-spec.json"
            iface.spec = spec_rel
            write(spec_rel, iface.spec_content)
        elif iface.spec_url and not iface.spec and working.raw_spec_content:
            # Spec was fetched from a URL.  Write the cached content locally
            # and point the manifest at the local file instead of spec_url.
            ext = ".json"
            if working.raw_spec_filename:
                suffix = Path(working.raw_spec_filename).suffix
                if suffix:
                    ext = suffix
            spec_rel = f"contracts/{_slug(iface.name)}-spec{ext}"
            write(spec_rel, working.raw_spec_content)
            iface.spec = spec_rel
            iface.spec_url = None  # suppress live-fetch in manifest (working copy only)

        # Operation samples
        for op in iface.operations:
            if op.request_sample_path and op.request_sample_content:
                write(op.request_sample_path, op.request_sample_content)
            if op.response_sample_path and op.response_sample_content:
                write(op.response_sample_path, op.response_sample_content)

        # Upstream mapping YAML
        if iface.operation_mappings and iface.entity_name:
            mapping_rel = iface.mapping_path or f"upstream/{_slug(iface.name)}-mapping.yaml"
            iface.mapping_path = mapping_rel
            write(mapping_rel, generate_upstream_mapping(iface))

    # ------------------------------------------------------------------
    # Downstream layout + mapping
    # ------------------------------------------------------------------
    for iface in working.downstream_interfaces:
        if iface.type in EDGE_CONTRACT_TYPES - {FILE_FIXED_WIDTH_TYPE}:
            if iface.type == FILE_CSV_TYPE and iface.spec_content:
                iface.spec = iface.spec or default_artifact_path("downstream", iface.name, iface.type)
                write(iface.spec, iface.spec_content)
            elif iface.type == XML_XSD_TYPE and iface.xsd_content:
                iface.xsd_path = iface.xsd_path or default_artifact_path("downstream", iface.name, iface.type)
                write(iface.xsd_path, iface.xsd_content)
            elif iface.type == SOAP_WSDL_TYPE and iface.wsdl_content:
                iface.wsdl_path = iface.wsdl_path or default_artifact_path("downstream", iface.name, iface.type)
                write(iface.wsdl_path, iface.wsdl_content)
            if iface.sample_path and iface.sample_content:
                write(iface.sample_path, iface.sample_content)
            if iface.type == XML_XSD_TYPE and iface.field_mappings and iface.entity_name:
                mapping_rel = iface.mapping_path or default_downstream_xml_mapping_path(iface.name)
                iface.mapping_path = mapping_rel
                write(mapping_rel, generate_downstream_xml_mapping(iface))
            elif iface.type == SOAP_WSDL_TYPE and iface.selected_operation_name:
                mapping_rel = iface.mapping_path or default_soap_operation_mapping_path(iface.name)
                iface.mapping_path = mapping_rel
                write(mapping_rel, generate_downstream_soap_operation_mapping(iface))
            elif iface.type in {FILE_FIXED_WIDTH_TYPE, FILE_CSV_TYPE} and iface.field_mappings:
                mapping_rel = iface.mapping_path or default_downstream_file_mapping_path(iface.name)
                iface.mapping_path = mapping_rel
                write(mapping_rel, generate_downstream_mapping(iface))
            continue

        if working.app_archetype == "passthrough-router":
            if iface.selected_operation_name:
                spec = load_openapi_spec(spec_url=iface.spec_url, spec_content=iface.spec_content)
                filtered_spec = filter_spec_to_operation(spec, iface.selected_operation_name)
                spec_rel = iface.spec or f"downstream/{_slug(iface.name)}-openapi.yaml"
                iface.spec = spec_rel
                iface.spec_url = None
                write(spec_rel, dump_openapi_spec(filtered_spec))
            continue

        if iface.layout_fields:
            layout_rel = iface.spec or f"downstream/{_slug(iface.name)}-layout.yaml"
            iface.spec = layout_rel
            write(layout_rel, generate_downstream_layout(iface))
        elif iface.type == FILE_FIXED_WIDTH_TYPE and iface.spec_content:
            iface.spec = iface.spec or default_artifact_path("downstream", iface.name, iface.type)
            write(iface.spec, iface.spec_content)

        if iface.field_mappings:
            mapping_rel = iface.mapping_path or f"downstream/{_slug(iface.name)}-mapping.yaml"
            iface.mapping_path = mapping_rel
            write(mapping_rel, generate_downstream_mapping(iface))

        if iface.sample_content and iface.samples:
            write(iface.samples[0], iface.sample_content)
        elif iface.sample_path and iface.sample_content:
            write(iface.sample_path, iface.sample_content)

    # ------------------------------------------------------------------
    # Data handoffs DDL + mapping
    # ------------------------------------------------------------------
    for handoff in working.data_handoffs:
        if handoff.ddl_content:
            sql_rel = handoff.spec or f"data-handoffs/{_slug(handoff.name)}.sql"
            handoff.spec = sql_rel
            write(sql_rel, handoff.ddl_content)

        if handoff.field_mappings:
            mapping_rel = handoff.mapping_path or f"data-handoffs/{_slug(handoff.name)}-mapping.yaml"
            handoff.mapping_path = mapping_rel
            write(mapping_rel, generate_handoff_mapping(handoff))

    # ------------------------------------------------------------------
    # Kafka schemas + transform mappings
    # ------------------------------------------------------------------
    if working.app_archetype == "kafka-integration":
        route_models = {route.route_name: route for route in working.kafka_route_models}
        transforms = {transform.route_name: transform for transform in working.kafka_route_transforms}
        topic_pair_route_names = {pair.route_name for pair in working.kafka_topic_pairs}

        def write_router_route_files(model) -> None:
            if not model or model.pattern != "router" or not model.router_config:
                return
            router_config = model.router_config
            transform = transforms.get(model.route_name)
            router_target_transforms = {
                target_transform.target_id: target_transform
                for target_transform in (transform.router_target_transforms if transform else [])
            }
            for target in router_config.targets:
                target_transform = router_target_transforms.get(target.id)
                if target_transform:
                    if target_transform.request_transform_rows:
                        write(
                            target.request_transform.file,
                            _generate_kafka_router_transform_yaml(
                                target_transform.request_transform_rows
                            ),
                        )
                    if target_transform.response_transform_rows:
                        write(
                            target.response_transform.file,
                            _generate_kafka_router_transform_yaml(
                                target_transform.response_transform_rows
                            ),
                        )
            for ref in _router_file_references(router_config):
                include_existing(ref)
            missing = _missing_package_references(
                project_dir,
                _router_file_references(router_config),
            )
            if missing:
                raise PackageWriteError(
                    "Kafka router route "
                    f"'{model.route_name}' references package file(s) that Studio did not write: "
                    + ", ".join(missing)
                    + ". Provide those router schema/transform files in the package directory "
                    "or keep export pending until detailed router transform/schema authoring is complete."
                )

        for pair in working.kafka_topic_pairs:
            upstream_rel = pair.upstream_schema_path or _kafka_schema_path(pair.route_name, "upstream")
            downstream_rel = pair.downstream_schema_path or _kafka_schema_path(pair.route_name, "downstream")
            pair.upstream_schema_path = upstream_rel
            pair.downstream_schema_path = downstream_rel

            if pair.upstream_schema_content:
                write(upstream_rel, pair.upstream_schema_content)

            model = route_models.get(pair.route_name)
            transform = transforms.get(pair.route_name)
            router_target_request_schema_paths: set[str] = set()
            if model and model.pattern == "router" and model.router_config:
                router_target_request_schema_paths = {
                    target.request_schema.file
                    for target in model.router_config.targets
                    if target.request_schema.file
                }
            if pair.downstream_schema_content and downstream_rel not in router_target_request_schema_paths:
                write(downstream_rel, pair.downstream_schema_content)
            if model and model.pattern == "router" and model.router_config:
                router_config = model.router_config
                if pair.upstream_schema_content and router_config.inbound_schema.file:
                    write(router_config.inbound_schema.file, pair.upstream_schema_content)
                single_router_target = len(router_config.targets) == 1
                for target in router_config.targets:
                    should_write_compat_request_schema = (
                        pair.downstream_schema_content
                        and target.request_schema.file
                        and single_router_target
                        and target.request_schema.file == downstream_rel
                        and not (project_dir / target.request_schema.file).exists()
                    )
                    if should_write_compat_request_schema:
                        write(target.request_schema.file, pair.downstream_schema_content)
                write_router_route_files(model)

            if transform and transform.mappings:
                write(
                    f"mappings/{pair.route_name}.yaml",
                    _generate_kafka_transform_yaml(transform.mappings),
                )

            if model and model.pattern == "request-reply":
                upstream_reply_rel = model.upstream_reply_schema_path or _kafka_schema_path(pair.route_name, "upstream-reply")
                downstream_reply_rel = model.downstream_reply_schema_path or _kafka_schema_path(pair.route_name, "downstream-reply")
                model.upstream_reply_schema_path = upstream_reply_rel
                model.downstream_reply_schema_path = downstream_reply_rel

                upstream_reply_content = infer_reply_schema_content(model, transform, "upstream")
                downstream_reply_content = infer_reply_schema_content(model, transform, "downstream")
                if upstream_reply_content:
                    write(upstream_reply_rel, upstream_reply_content)
                if downstream_reply_content:
                    write(downstream_reply_rel, downstream_reply_content)

            if (
                model
                and model.pattern == "request-reply"
                and transform
                and transform.response_mappings
            ):
                write(
                    f"mappings/{pair.route_name}-response.yaml",
                    _generate_kafka_transform_yaml(transform.response_mappings),
                )

        for model in router_route_models(working):
            if model.route_name not in topic_pair_route_names:
                write_router_route_files(model)

    # ------------------------------------------------------------------
    # Rules
    # ------------------------------------------------------------------
    if working.app_archetype == "passthrough-router":
        flow = working.passthrough_flow
        if flow.route_field and flow.routes and flow.default_target and flow.transforms:
            rule_rel = flow.rule_path or f"rules/{_slug(working.bounded_context or working.app_name or 'project')}-passthrough-routing.yaml"
            flow.rule_path = rule_rel
            write(rule_rel, serialize_passthrough_rules(flow))
    else:
        for er in working.entity_rules:
            if er.rules:
                rule_rel = er.file_path or f"rules/{_slug(er.entity_name)}-business-rules.yaml"
                er.file_path = rule_rel
                write(rule_rel, generate_rule_yaml(er))

    # ------------------------------------------------------------------
    # Legacy notes
    # ------------------------------------------------------------------
    if working.legacy_notes and working.legacy_slug:
        write(f"legacy/{working.legacy_slug}-notes.md", working.legacy_notes)

    # ------------------------------------------------------------------
    # Manifest (last — so all paths are populated)
    # ------------------------------------------------------------------
    manifest_yaml = generate_manifest_yaml(working)
    write("app-definition.yaml", manifest_yaml)

    # ------------------------------------------------------------------
    # Completeness report
    # ------------------------------------------------------------------
    report = build_completeness_report(working)
    write("completeness-report.md", render_completeness_markdown(report, working))

    # ------------------------------------------------------------------
    # Assessment report placeholder
    # ------------------------------------------------------------------
    assessment: dict[str, Any] = {
        "generated_by": "EdgeForge Studio",
        "app_name": working.app_name,
        "bounded_context": working.bounded_context,
        "entities": working.selected_entity_names,
        "upstream_count": len(working.upstream_interfaces),
        "downstream_count": len(working.downstream_interfaces),
        "handoff_count": len(working.data_handoffs),
        "note": "Run `appbuilder assess --swagger <spec_url>` for full OpenAPI assessment.",
    }
    write("assessment-report.json", json.dumps(assessment, indent=2))

    evidence_trail = build_evidence_trail(
        working,
        manifest_yaml=manifest_yaml,
        export_path=str(project_dir),
    )
    write("evidence-trail.json", json.dumps(evidence_trail.payload, indent=2))

    # Persist the same local authoring snapshot as Save Project so exported
    # packages remain reproducible without including transient Step 8 runtime
    # process state.
    working.last_export_path = str(project_dir)
    working.ks_workspace_state.manifest_revisions.append(
        KSManifestRevision(
            revision_id=evidence_trail.revision_id,
            exported_at=evidence_trail.exported_at,
            manifest_hash=evidence_trail.manifest_hash,
            archetype=working.app_archetype,
            target_profile=working.target_profile,
            export_path=str(project_dir),
        )
    )
    project_snapshot = snapshot_session_for_save(working)
    # Exported provenance cannot resolve the author's local directories after
    # transfer. Keep revision identities, but require a fresh export for paths.
    project_snapshot.last_export_path = None
    project_snapshot.manifest_revisions = [
        revision.model_copy(update={"export_path": ""})
        for revision in project_snapshot.manifest_revisions
    ]
    write("studio-project.json", serialize_project(project_snapshot))

    # ------------------------------------------------------------------
    # Propagate stable path assignments back to the original session.
    # These are paths that were newly derived (None → value) during this
    # write; they are safe to persist.  Spec/spec_url changes on
    # URL-backed interfaces are intentionally NOT propagated so that the
    # caller's session retains spec_url for assess operations.
    # Keep this after evidence export so a sidecar failure does not leave
    # partial export-path mutations behind in the live session.
    #
    # The `not orig.spec_url` guard is what actually enforces that intent.
    # `not orig.spec` alone does NOT: a URL-backed interface has an empty
    # spec by definition, so the packaging copy's package-relative spec
    # sailed straight through into the live session. The session then held
    # BOTH spec and spec_url, violating the "Exactly one of spec or
    # spec_url" invariant on the model, and the next export failed with
    # "both spec and spec_url are set -- AppBuilder requires exactly one"
    # until the author re-fetched in Step 2 AND re-saved Step 3.
    # ------------------------------------------------------------------
    for orig, work in zip(session.upstream_interfaces, working.upstream_interfaces, strict=False):
        if work.mapping_path and not orig.mapping_path:
            orig.mapping_path = work.mapping_path
        if work.spec and not orig.spec and not orig.spec_url:
            orig.spec = work.spec
        if work.xsd_path and not orig.xsd_path:
            orig.xsd_path = work.xsd_path
        if work.wsdl_path and not orig.wsdl_path:
            orig.wsdl_path = work.wsdl_path
        if work.sample_path and not orig.sample_path:
            orig.sample_path = work.sample_path

    # Same guard downstream: the passthrough-router branch above sets
    # `iface.spec_url = None` on the *working* copy after writing the
    # filtered spec, so an untouched `orig.spec_url` would otherwise be
    # joined by a propagated spec here in exactly the same way.
    for orig, work in zip(session.downstream_interfaces, working.downstream_interfaces, strict=False):
        if work.spec and not orig.spec and not orig.spec_url:
            orig.spec = work.spec
        if work.mapping_path and not orig.mapping_path:
            orig.mapping_path = work.mapping_path
        if work.xsd_path and not orig.xsd_path:
            orig.xsd_path = work.xsd_path
        if work.wsdl_path and not orig.wsdl_path:
            orig.wsdl_path = work.wsdl_path
        if work.sample_path and not orig.sample_path:
            orig.sample_path = work.sample_path

    for orig, work in zip(session.data_handoffs, working.data_handoffs, strict=False):
        if work.spec and not orig.spec:
            orig.spec = work.spec
        if work.mapping_path and not orig.mapping_path:
            orig.mapping_path = work.mapping_path

    for orig, work in zip(session.entity_rules, working.entity_rules, strict=False):
        if work.file_path and not orig.file_path:
            orig.file_path = work.file_path

    if working.passthrough_flow.rule_path and not session.passthrough_flow.rule_path:
        session.passthrough_flow.rule_path = working.passthrough_flow.rule_path

    for orig, work in zip(session.kafka_topic_pairs, working.kafka_topic_pairs, strict=False):
        if work.upstream_schema_path and not orig.upstream_schema_path:
            orig.upstream_schema_path = work.upstream_schema_path
        if work.downstream_schema_path and not orig.downstream_schema_path:
            orig.downstream_schema_path = work.downstream_schema_path

    for orig, work in zip(session.kafka_route_models, working.kafka_route_models, strict=False):
        if work.upstream_reply_schema_path and not orig.upstream_reply_schema_path:
            orig.upstream_reply_schema_path = work.upstream_reply_schema_path
        if work.downstream_reply_schema_path and not orig.downstream_reply_schema_path:
            orig.downstream_reply_schema_path = work.downstream_reply_schema_path

    return PackageWriteResult(
        written=written,
        project_dir=project_dir,
        evidence_trail=evidence_trail,
        warnings=warnings,
    )


def build_zip(session: ProjectSession, root: Path) -> bytes:
    """Build package in-memory and return ZIP bytes."""
    result = write_package_result(session, root)
    written = result.written
    project_dir = result.project_dir

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in written:
            path = contain_under_session_workspace(session, project_dir / rel)
            zf.write(path, arcname=f"{project_dir.name}/{rel}")
    return buf.getvalue()
