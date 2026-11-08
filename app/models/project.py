"""In-memory project state models for EdgeForge Studio."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.models.project_capabilities import ProjectCapabilities
from app.services.runtime_defaults import default_edgeforge_repo_path

# ---------------------------------------------------------------------------
# Studio project snapshot schema version
# ---------------------------------------------------------------------------

STUDIO_PROJECT_SCHEMA_VERSION = "1.4"


# ---------------------------------------------------------------------------
# Upstream models
# ---------------------------------------------------------------------------

class OperationSample(BaseModel):
    name: str
    request_sample_path: Optional[str] = None   # relative path in package
    response_sample_path: Optional[str] = None  # relative path in package
    request_sample_content: Optional[str] = None
    response_sample_content: Optional[str] = None

    def has_sample(self) -> bool:
        """True only when a path AND its content are both present (file will actually be written)."""
        return bool(
            (self.request_sample_path and self.request_sample_content)
            or (self.response_sample_path and self.response_sample_content)
        )


class FieldMapping(BaseModel):
    source: str
    target: str


class SoapResponseMapping(BaseModel):
    source: str
    target_path: str


class SoapCanonicalOperationConfig(BaseModel):
    kind: str = "read_by_id"
    entity: Optional[str] = None
    lookup_field: Optional[str] = None
    request_path: Optional[str] = None
    response_mappings: list[SoapResponseMapping] = Field(default_factory=list)
    not_found_fault: Optional[str] = None
    not_found_message: Optional[str] = None


class SoapRequestMapping(BaseModel):
    source: str
    target_path: str


class SoapReturnMapping(BaseModel):
    source_path: str
    target: str


class SoapCanonicalInvocationConfig(BaseModel):
    kind: str = "invoke_by_id"
    entity: Optional[str] = None
    lookup_field: Optional[str] = None
    request_field: str = "id"
    request_mappings: list[SoapRequestMapping] = Field(default_factory=list)
    response_mode: str = "return_only"
    response_mappings: list[SoapReturnMapping] = Field(default_factory=list)


class OperationMapping(BaseModel):
    name: str
    request_mappings: list[FieldMapping] = Field(default_factory=list)
    response_mappings: list[FieldMapping] = Field(default_factory=list)


class UpstreamInterface(BaseModel):
    name: str
    system: Optional[str] = None
    type: str = "rest-json"
    version: Optional[str] = None
    # Exactly one of spec or spec_url
    spec: Optional[str] = None          # relative path in package
    spec_url: Optional[str] = None
    spec_content: Optional[str] = None  # raw OpenAPI content (for file upload)
    mapping_path: Optional[str] = None  # relative path in package
    operations: list[OperationSample] = Field(default_factory=list)
    operation_mappings: list[OperationMapping] = Field(default_factory=list)
    field_mappings: list[FieldMapping] = Field(default_factory=list)
    # Classified entity this interface maps to
    entity_name: Optional[str] = None
    selected_operation_name: Optional[str] = None
    xsd_path: Optional[str] = None
    xsd_content: Optional[str] = None
    root_element: Optional[str] = None
    namespace: Optional[str] = None
    namespace_alias: Optional[str] = None
    wsdl_path: Optional[str] = None
    wsdl_content: Optional[str] = None
    service: Optional[str] = None
    port: Optional[str] = None
    binding: Optional[str] = None
    soap_operation_mode: str = "adapter_only"
    soap_handler_method: Optional[str] = None
    soap_canonical_operation: Optional[SoapCanonicalOperationConfig] = None
    sample_path: Optional[str] = None
    sample_content: Optional[str] = None
    # Inferred/draft flag
    is_draft: bool = False

    def source_type(self) -> str:
        if self.spec_url:
            return "url"
        if self.spec:
            return "file"
        return "samples"


# ---------------------------------------------------------------------------
# Downstream models
# ---------------------------------------------------------------------------

class LayoutField(BaseModel):
    name: str
    start: int
    length: int
    locked_start: bool = False


class DownstreamInterface(BaseModel):
    name: str
    system: Optional[str] = None
    type: str = "file-fixed-width"
    version: Optional[str] = None
    spec: Optional[str] = None           # relative path to layout YAML
    spec_url: Optional[str] = None
    spec_content: Optional[str] = None
    layout_fields: list[LayoutField] = Field(default_factory=list)
    mapping_path: Optional[str] = None   # relative path to mapping YAML
    field_mappings: list[FieldMapping] = Field(default_factory=list)
    entity_name: Optional[str] = None
    selected_operation_name: Optional[str] = None
    samples: list[str] = Field(default_factory=list)
    sample_path: Optional[str] = None
    sample_content: Optional[str] = None
    xsd_path: Optional[str] = None
    xsd_content: Optional[str] = None
    root_element: Optional[str] = None
    namespace: Optional[str] = None
    namespace_alias: Optional[str] = None
    wsdl_path: Optional[str] = None
    wsdl_content: Optional[str] = None
    service: Optional[str] = None
    port: Optional[str] = None
    binding: Optional[str] = None
    soap_operation_mode: str = "adapter_only"
    soap_canonical_invocation: Optional[SoapCanonicalInvocationConfig] = None


# ---------------------------------------------------------------------------
# Data handoff models
# ---------------------------------------------------------------------------

class DataHandoff(BaseModel):
    name: str
    system: Optional[str] = None
    type: str = "staging-table"
    version: Optional[str] = None
    spec: Optional[str] = None          # relative path to .sql file
    ddl_content: Optional[str] = None
    table_name: Optional[str] = None    # extracted from DDL
    mapping_path: Optional[str] = None  # relative path to mapping YAML
    field_mappings: list[FieldMapping] = Field(default_factory=list)
    entity_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Rule models
# ---------------------------------------------------------------------------

class RuleEntry(BaseModel):
    field: str
    type: str   # allowed-values | default | iso-4217 | cross-entity-*
    values: list[str] = Field(default_factory=list)
    value: Optional[str] = None
    target_entity: Optional[str] = None
    operator: Optional[str] = None
    compare_to_field: Optional[str] = None
    target_field: Optional[str] = None
    source_field: Optional[str] = None
    expected_value: Optional[str] = None
    error_message: Optional[str] = None
    suggestion_id: Optional[str] = None
    suggestion_type: Optional[str] = None
    applied_by: Optional[str] = None
    applied_at: Optional[str] = None
    generated_by_ka: bool = False
    ka_review_status: Optional[str] = None


class EntityRules(BaseModel):
    entity_name: str
    rules: list[RuleEntry] = Field(default_factory=list)
    file_path: Optional[str] = None  # relative path in package


# ---------------------------------------------------------------------------
# Build / Run models (Step 8)
# ---------------------------------------------------------------------------

class BuildRunRoute(BaseModel):
    method: str
    path: str
    controller: Optional[str] = None


class BuildRunState(BaseModel):
    generated_app_path: Optional[str] = None
    build_status: str = "idle"     # idle | building | build_failed | build_succeeded
    run_status: str = "idle"       # idle | starting | running | stopped | run_failed
    build_log_path: Optional[str] = None
    run_log_path: Optional[str] = None
    build_summary: Optional[str] = None
    run_summary: Optional[str] = None
    jar_path: Optional[str] = None
    requested_port: Optional[int] = None
    port: Optional[int] = None
    pid: Optional[int] = None
    app_url: Optional[str] = None
    health_url: Optional[str] = None
    route_summary: list[BuildRunRoute] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Passthrough-router models
# ---------------------------------------------------------------------------


class PassthroughRouteRow(BaseModel):
    match: str
    target: str


class PassthroughTransform(BaseModel):
    source: str
    target: str
    default: Optional[str] = None


class PassthroughFlow(BaseModel):
    upstream_operation_name: Optional[str] = None
    route_field: str = ""
    routes: list[PassthroughRouteRow] = Field(default_factory=list)
    default_target: str = ""
    transforms: list[PassthroughTransform] = Field(default_factory=list)
    rule_path: Optional[str] = None


# ---------------------------------------------------------------------------
# Kafka-integration models
# ---------------------------------------------------------------------------


class KafkaTopicPair(BaseModel):
    route_name: str = ""
    upstream_topic: str = ""
    upstream_system: str = ""
    upstream_schema_path: str = ""
    upstream_schema_content: str = ""
    downstream_topic: str = ""
    downstream_system: str = ""
    downstream_schema_path: str = ""
    downstream_schema_content: str = ""


class KafkaRouterExtraction(BaseModel):
    mode: str = "header"
    header_key: str = ""
    body_field_path: str = ""


class KafkaRouterUpstreamTopic(BaseModel):
    id: str = ""
    name: str = ""
    consumer_group: str = ""
    source_system_extraction: KafkaRouterExtraction = Field(default_factory=KafkaRouterExtraction)
    reply_destination_extraction: KafkaRouterExtraction = Field(default_factory=KafkaRouterExtraction)


class KafkaRouterSchemaRef(BaseModel):
    file: str = ""
    validation_policy: str = "strict"
    failure_behavior: str = "nack"


class KafkaRouterRoutingField(BaseModel):
    name: str = ""
    json_path: str = ""


class KafkaRouterCondition(BaseModel):
    field: str = ""
    operator: str = "eq"
    value: str = ""


class KafkaRouterRule(BaseModel):
    id: str = ""
    conditions: list[KafkaRouterCondition] = Field(default_factory=list)
    target: str = ""


class KafkaRouterRoutingRules(BaseModel):
    routing_fields: list[KafkaRouterRoutingField] = Field(default_factory=list)
    rules: list[KafkaRouterRule] = Field(default_factory=list)
    default_target: Optional[str] = None


class KafkaRouterTransformRef(BaseModel):
    file: str = ""


class KafkaRouterRetry(BaseModel):
    max_attempts: int = 3
    backoff_ms: int = 1000
    dlq_topic: str = ""


class KafkaRouterTarget(BaseModel):
    id: str = ""
    request_topic: str = ""
    response_topic: str = ""
    request_schema: KafkaRouterSchemaRef = Field(default_factory=KafkaRouterSchemaRef)
    response_schema: KafkaRouterSchemaRef = Field(default_factory=KafkaRouterSchemaRef)
    request_transform: KafkaRouterTransformRef = Field(default_factory=KafkaRouterTransformRef)
    response_transform: KafkaRouterTransformRef = Field(default_factory=KafkaRouterTransformRef)
    retry: KafkaRouterRetry = Field(default_factory=KafkaRouterRetry)
    timeout_ms: int = 30000


class KafkaRouterNackRouting(BaseModel):
    mode: str = "default_error"
    per_source_system: dict[str, str] = Field(default_factory=dict)
    fixed_topic: Optional[str] = None
    default_error_topic: str = ""


class KafkaRouterTimeout(BaseModel):
    behavior_with_known_reply: str = "nack"
    behavior_without_reply: str = "error_topic"


class KafkaRouterPayloadLogging(BaseModel):
    policy: str = "none"
    capped_raw_bytes: int = 512


class KafkaRouterCorrelationStore(BaseModel):
    type: str = "in_memory"
    timeout_ms: int = 30000
    eviction_interval_ms: int = 60000


class KafkaRouterConfig(BaseModel):
    upstream_topics: list[KafkaRouterUpstreamTopic] = Field(default_factory=list)
    inbound_schema: KafkaRouterSchemaRef = Field(default_factory=KafkaRouterSchemaRef)
    routing_rules: KafkaRouterRoutingRules = Field(default_factory=KafkaRouterRoutingRules)
    duplicate_correlation_policy: str = "reject-new"
    targets: list[KafkaRouterTarget] = Field(default_factory=list)
    outbound_schema: KafkaRouterSchemaRef = Field(default_factory=KafkaRouterSchemaRef)
    nack_routing: KafkaRouterNackRouting = Field(default_factory=KafkaRouterNackRouting)
    timeout: KafkaRouterTimeout = Field(default_factory=KafkaRouterTimeout)
    payload_logging: KafkaRouterPayloadLogging = Field(default_factory=KafkaRouterPayloadLogging)
    correlation_store: KafkaRouterCorrelationStore = Field(default_factory=KafkaRouterCorrelationStore)


class KafkaRouteModel(BaseModel):
    route_name: str = ""
    pattern: str = "fire-and-forget"
    upstream_reply_topic: str = ""
    upstream_reply_schema_path: str = ""
    upstream_reply_schema_content: str = ""
    downstream_reply_topic: str = ""
    downstream_reply_schema_path: str = ""
    downstream_reply_schema_content: str = ""
    correlation_source: str = "header"
    correlation_field: str = ""
    reply_timeout_ms: int = 5000
    router_config: Optional[KafkaRouterConfig] = None


class KafkaTransformRow(BaseModel):
    source_field: str = ""
    target_field: str = ""


class KafkaRouterTransformRow(BaseModel):
    source: str = ""
    target: str = ""
    default_value: Optional[str] = None
    constant: Optional[str] = None
    value_map: dict[str, str] = Field(default_factory=dict)
    type_coercion: Optional[str] = None


class KafkaRouterTargetTransform(BaseModel):
    target_id: str = ""
    request_transform_rows: list[KafkaRouterTransformRow] = Field(default_factory=list)
    response_transform_rows: list[KafkaRouterTransformRow] = Field(default_factory=list)


class KafkaRouteTransform(BaseModel):
    route_name: str = ""
    mappings: list[KafkaTransformRow] = Field(default_factory=list)
    response_mappings: list[KafkaTransformRow] = Field(default_factory=list)
    router_target_transforms: list[KafkaRouterTargetTransform] = Field(default_factory=list)


class KafkaConfig(BaseModel):
    consumer_group: str = ""
    concurrency: int = 1
    retry_max_attempts: int = 3
    retry_backoff_ms: int = 1000
    retry_backoff_multiplier: float = 2.0
    dlq_enabled: bool = False
    dlq_topic_suffix: str = ".dlq"


# ---------------------------------------------------------------------------
# Knowledge Workspace durable linkage models
# ---------------------------------------------------------------------------


class KSSuggestionReviewState(BaseModel):
    accepted_ids: list[str] = Field(default_factory=list)
    rejected_ids: list[str] = Field(default_factory=list)
    edited_ids: list[str] = Field(default_factory=list)


class KSEvidenceLink(BaseModel):
    manifest_path: str
    suggestion_id: str
    provenance: str


class KSManifestRevision(BaseModel):
    revision_id: str
    exported_at: str
    manifest_hash: str
    archetype: str
    target_profile: str
    export_path: str


class KSConflictResolution(BaseModel):
    conflict_id: str
    resolution: str
    rationale: str
    resolved_at: str


class KSReviewHistoryEntry(BaseModel):
    suggestion_id: str
    type: str
    status: str
    manifest_path: str
    reviewed_at: str
    edited_payload: Optional[Any] = None
    review_context: dict[str, Any] = Field(default_factory=dict)


class KSWorkspaceState(BaseModel):
    suggestion_review_state: KSSuggestionReviewState = Field(default_factory=KSSuggestionReviewState)
    evidence_links: list[KSEvidenceLink] = Field(default_factory=list)
    manifest_revisions: list[KSManifestRevision] = Field(default_factory=list)
    conflict_resolutions: list[KSConflictResolution] = Field(default_factory=list)
    review_history: list[KSReviewHistoryEntry] = Field(default_factory=list)


IdentityRoleValue = Literal[
    "persistence_id",
    "parent_reference",
    "business_key",
    "event_id",
    "idempotency_key",
    "correlation_id",
    "external_reference",
]


class IdentityRoleDecision(BaseModel):
    """Manual, human-authored identity role classification for a CRUD field."""

    entity: str
    field: str
    role: IdentityRoleValue
    provenance: str = "human-authored"
    reviewed_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Classified OpenAPI entity (from Step 2 → Step 3)
# ---------------------------------------------------------------------------

class ClassifiedField(BaseModel):
    name: str
    type: str           # string, integer, decimal, boolean, date, datetime
    required: bool = False
    is_id: bool = False
    format: Optional[str] = None
    enum_values: list[str] = Field(default_factory=list)
    # Constraint metadata extracted from OpenAPI spec — used to auto-generate rules
    max_length: Optional[int] = None
    min_length: Optional[int] = None
    pattern: Optional[str] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    default_value: Optional[str] = None


class ClassifiedEntity(BaseModel):
    name: str
    """Original OpenAPI schema name (e.g. 'CustomerResponse')."""

    canonical_name: Optional[str] = None
    """AppBuilder-normalised entity name (e.g. 'Customer').

    Derived by mirroring AppBuilder's ``_normalize_entity_name()`` — strips
    Request/Response suffix and leading CRUD verb prefix.  This is the name
    that will appear in generated manifests, mappings, and rules, and matches
    the Java class name AppBuilder generates.  When ``None``, ``name`` is used
    as-is (already canonical for plain domain schemas like 'Account').
    """

    fields: list[ClassifiedField] = Field(default_factory=list)
    classification: str = "entity"   # entity | dto | infrastructure
    confidence: str = "inferred"     # inferred | confirmed
    reason: Optional[str] = None
    source_schema: Optional[str] = None

    def display_name(self) -> str:
        """The name to show in the UI and use in AppBuilder output."""
        return self.canonical_name or self.name


class ClassifiedOperation(BaseModel):
    name: str                        # e.g. createAccount
    method: str                      # GET, POST, PUT, DELETE, PATCH
    path: str                        # API path
    resource: str                    # grouped resource name
    request_schema: Optional[str] = None
    response_schema: Optional[str] = None
    entity_candidates: list[str] = Field(default_factory=list)
    is_draft: bool = True


# ---------------------------------------------------------------------------
# Top-level project session
# ---------------------------------------------------------------------------

class ProjectSession(BaseModel):
    # Request/session context — server-owned, not exported into Studio project files.
    session_id: Optional[str] = None
    workspace_root: Optional[str] = None

    # Step 1
    app_name: str = ""
    bounded_context: str = ""
    app_archetype: str = "crud"
    target_profile: str = ""
    output_path: str = ""
    appbuilder_repo_path: str = Field(default_factory=default_edgeforge_repo_path)
    project_id: Optional[str] = None
    ks_project_id: Optional[str] = None
    ks_active: bool = False
    capabilities: ProjectCapabilities = Field(default_factory=ProjectCapabilities)
    ks_workspace_state: KSWorkspaceState = Field(default_factory=KSWorkspaceState)
    review_approved: bool = False
    project_revision: int = 1
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    saved_at: Optional[str] = None
    created_by: Optional[str] = None
    modified_by: Optional[str] = None
    is_brand_new: bool = False

    # Step 2 — raw ingestion results
    raw_spec_content: Optional[str] = None   # uploaded/fetched OpenAPI spec text
    raw_spec_url: Optional[str] = None
    raw_spec_filename: Optional[str] = None

    # Step 3 — classification results (set after Step 2)
    classified_entities: list[ClassifiedEntity] = Field(default_factory=list)
    classified_operations: list[ClassifiedOperation] = Field(default_factory=list)

    # Step 3 — user selections
    selected_entity_names: list[str] = Field(default_factory=list)
    selected_operation_names: list[str] = Field(default_factory=list)
    identity_role_decisions: list[IdentityRoleDecision] = Field(default_factory=list)

    # Steps 2-3 — upstream interfaces (one per selected entity)
    upstream_interfaces: list[UpstreamInterface] = Field(default_factory=list)

    # Step 4 — downstream interfaces
    downstream_interfaces: list[DownstreamInterface] = Field(default_factory=list)

    # Step 5 — data handoffs
    data_handoffs: list[DataHandoff] = Field(default_factory=list)

    # Step 6 — rules + legacy
    entity_rules: list[EntityRules] = Field(default_factory=list)
    auto_rule_merge_completed_entities: list[str] = Field(default_factory=list)
    legacy_notes: Optional[str] = None
    legacy_slug: Optional[str] = None

    # Step 8 — export state
    last_export_path: Optional[str] = None
    last_generated_package_ref: Optional[str] = None
    generation_run_id: Optional[str] = None
    manifest_hash: Optional[str] = None
    baseline_hash: Optional[str] = None
    build_run: BuildRunState = Field(default_factory=BuildRunState)
    passthrough_flow: PassthroughFlow = Field(default_factory=PassthroughFlow)
    kafka_config: KafkaConfig = Field(default_factory=KafkaConfig)
    kafka_topic_pairs: list[KafkaTopicPair] = Field(default_factory=list)
    kafka_route_models: list[KafkaRouteModel] = Field(default_factory=list)
    kafka_route_transforms: list[KafkaRouteTransform] = Field(default_factory=list)

    def project_slug(self) -> str:
        return self.bounded_context.lower().replace(" ", "-") or "project"

    def selected_entities(self) -> list[ClassifiedEntity]:
        names = set(self.selected_entity_names)
        return [e for e in self.classified_entities if e.name in names]


# ---------------------------------------------------------------------------
# Studio project snapshot — durable save/open file format (S1A)
# ---------------------------------------------------------------------------

class StudioProject(BaseModel):
    """Durable Studio project snapshot written to / read from a .json file.

    Covers Steps 1-6 authoring state only.  Step 8 runtime/build state is
    intentionally excluded and remains transient.

    ``studio_project_schema_version`` must remain separate from the Engine
    manifest ``schema_version``.  Bump this constant when the snapshot shape
    changes in a breaking way.
    """

    # Schema identity
    studio_project_schema_version: str = STUDIO_PROJECT_SCHEMA_VERSION
    project_revision: int = 1
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    saved_at: Optional[str] = None  # ISO-8601 timestamp, set at save time
    created_by: Optional[str] = None
    modified_by: Optional[str] = None

    # Step 1 — project identity
    app_name: str = ""
    bounded_context: str = ""
    app_archetype: str = "crud"
    target_profile: str = ""
    output_path: str = ""
    appbuilder_repo_path: str = ""
    project_id: Optional[str] = None
    ks_project_id: Optional[str] = None
    ks_active: bool = False
    capabilities: ProjectCapabilities = Field(default_factory=ProjectCapabilities)
    suggestion_review_state: KSSuggestionReviewState = Field(default_factory=KSSuggestionReviewState)
    evidence_links: list[KSEvidenceLink] = Field(default_factory=list)
    manifest_revisions: list[KSManifestRevision] = Field(default_factory=list)
    conflict_resolutions: list[KSConflictResolution] = Field(default_factory=list)
    review_history: list[KSReviewHistoryEntry] = Field(default_factory=list)

    # Step 2 — raw spec source & ingested content
    raw_spec_content: Optional[str] = None
    raw_spec_url: Optional[str] = None
    raw_spec_filename: Optional[str] = None

    # Step 3 — classification results and user selections
    classified_entities: list[ClassifiedEntity] = Field(default_factory=list)
    classified_operations: list[ClassifiedOperation] = Field(default_factory=list)
    selected_entity_names: list[str] = Field(default_factory=list)
    selected_operation_names: list[str] = Field(default_factory=list)
    identity_role_decisions: list[IdentityRoleDecision] = Field(default_factory=list)

    # Steps 2-3 — upstream interfaces
    upstream_interfaces: list[UpstreamInterface] = Field(default_factory=list)

    # Step 4 — downstream interfaces
    downstream_interfaces: list[DownstreamInterface] = Field(default_factory=list)

    # Step 5 — data handoffs
    data_handoffs: list[DataHandoff] = Field(default_factory=list)

    # Step 6 — rules + legacy
    entity_rules: list[EntityRules] = Field(default_factory=list)
    auto_rule_merge_completed_entities: list[str] = Field(default_factory=list)
    legacy_notes: Optional[str] = None
    legacy_slug: Optional[str] = None

    # Passthrough-router flow (nullable — only set for passthrough archetype)
    passthrough_flow: Optional[PassthroughFlow] = None
    kafka_config: Optional[KafkaConfig] = None
    kafka_topic_pairs: list[KafkaTopicPair] = Field(default_factory=list)
    kafka_route_models: list[KafkaRouteModel] = Field(default_factory=list)
    kafka_route_transforms: list[KafkaRouteTransform] = Field(default_factory=list)

    # Auth-ready nullable fields (not enforced in S1A; reserved for S2/S3/S4)
    org_id: Optional[str] = None
    lob_id: Optional[str] = None
    owner_user_id: Optional[str] = None
    last_edited_by: Optional[str] = None

    # Optional last-known convenience fields (not authoritative)
    last_export_path: Optional[str] = None
    last_export_timestamp: Optional[str] = None
    last_generated_app_path: Optional[str] = None
    last_generated_package_ref: Optional[str] = None
    generation_run_id: Optional[str] = None
    manifest_hash: Optional[str] = None
    baseline_hash: Optional[str] = None
