"""Tests for Studio project file save/open service."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.project import (
    STUDIO_PROJECT_SCHEMA_VERSION,
    ClassifiedEntity,
    ClassifiedField,
    ClassifiedOperation,
    DataHandoff,
    DownstreamInterface,
    EntityRules,
    FieldMapping,
    IdentityRoleDecision,
    KafkaConfig,
    KafkaRouteModel,
    KafkaRouterTargetTransform,
    KafkaRouterTransformRow,
    KafkaRouteTransform,
    KafkaTopicPair,
    KafkaTransformRow,
    KSConflictResolution,
    KSEvidenceLink,
    KSManifestRevision,
    KSReviewHistoryEntry,
    KSSuggestionReviewState,
    LayoutField,
    OperationSample,
    PassthroughFlow,
    PassthroughRouteRow,
    PassthroughTransform,
    ProjectSession,
    RuleEntry,
    SoapCanonicalInvocationConfig,
    SoapCanonicalOperationConfig,
    SoapRequestMapping,
    SoapResponseMapping,
    SoapReturnMapping,
    StudioProject,
    UpstreamInterface,
)
from app.models.project_capabilities import ProjectCapabilities
from app.services.identity_roles import IDENTITY_ROLE_VALUES
from app.services.ks_workspace import mark_workspace_active
from app.services.manifest_generator import build_manifest_dict
from app.services.package_writer import write_package_result
from app.services.project_file_service import (
    _current_user_hint,
    deserialize_project,
    restore_session,
    save_project,
    serialize_project,
    snapshot_session,
    snapshot_session_for_save,
)
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _crud_session() -> ProjectSession:
    """Minimal CRUD session with data across Steps 1-6."""
    s = ProjectSession()
    # Step 1
    s.app_name = "DDA App"
    s.bounded_context = "dda"
    s.app_archetype = "crud"
    s.target_profile = "springboot-legacy-compatible"
    s.output_path = "/tmp/output"
    s.appbuilder_repo_path = "/tmp/edgeforge"
    # Step 2
    s.raw_spec_content = '{"openapi": "3.0.0"}'
    s.raw_spec_url = "https://example.com/spec.json"
    s.raw_spec_filename = "spec.json"
    # Step 3
    s.classified_entities = [
        ClassifiedEntity(
            name="Account",
            fields=[ClassifiedField(name="accountId", type="string")],
            classification="entity",
            confidence="confirmed",
        )
    ]
    s.classified_operations = [
        ClassifiedOperation(
            name="createAccount", method="POST", path="/accounts", resource="accounts"
        )
    ]
    s.selected_entity_names = ["Account"]
    s.selected_operation_names = ["createAccount"]
    # Step 3 upstream
    s.upstream_interfaces = [
        UpstreamInterface(name="synthetic-api", system="Synthetic", type="rest-json", entity_name="Account")
    ]
    # Step 4 downstream
    s.downstream_interfaces = [
        DownstreamInterface(name="eod-file", system="EOD", type="file-fixed-width", entity_name="Account")
    ]
    # Step 5 data handoffs
    s.data_handoffs = [
        DataHandoff(name="staging", system="STG", type="staging-table", entity_name="Account")
    ]
    # Step 6 rules + legacy
    s.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[RuleEntry(field="currency", type="allowed-values", values=["USD", "EUR"])],
            file_path="rules/account-rules.yaml",
        )
    ]
    s.legacy_notes = "Some legacy note"
    s.legacy_slug = "dda-legacy"
    return s


def test_edge_contract_interfaces_round_trip_save_open(tmp_path):
    session = _crud_session()
    session.upstream_interfaces = [
        UpstreamInterface(
            name="fixed-in",
            type="file-fixed-width",
            spec="upstream/fixed-layout.yaml",
            spec_content="format: fixed-width\n",
            entity_name="Account",
            field_mappings=[FieldMapping(source="account_id", target="accountId")],
            mapping_path="upstream/fixed-in-mapping.yaml",
        ),
        UpstreamInterface(
            name="csv-in",
            type="file-csv",
            spec="upstream/csv-layout.yaml",
            spec_content="format: csv\n",
        ),
        UpstreamInterface(
            name="xml-in",
            type="xml-xsd",
            xsd_path="contracts/input.xsd",
            xsd_content="<xs:schema/>",
            root_element="acct:Input",
            namespace="urn:input",
            namespace_alias="acct",
            entity_name="Account",
            field_mappings=[FieldMapping(source="accountId", target="Account.accountId")],
            mapping_path="upstream/xml-in-mapping.yaml",
        ),
        UpstreamInterface(
            name="soap-in",
            type="soap-wsdl",
            wsdl_path="contracts/service.wsdl",
            wsdl_content="<definitions/>",
            service="AccountService",
            port="AccountPort",
            binding="AccountBinding",
            selected_operation_name="GetAccountStatus",
            operations=[OperationSample(name="GetAccountStatus")],
            mapping_path="mappings/soap-in-operation-mapping.yaml",
            soap_operation_mode="canonical",
            soap_canonical_operation=SoapCanonicalOperationConfig(
                entity="Account",
                lookup_field="accountId",
                request_path="/GetAccountStatusRequest/accountId",
                response_mappings=[
                    SoapResponseMapping(
                        source="Account.accountId",
                        target_path="/GetAccountStatusResponse/accountId",
                    )
                ],
                not_found_fault="accountFault",
                not_found_message="Account not found",
            ),
        ),
    ]
    session.downstream_interfaces = [
        DownstreamInterface(
            name="csv-out",
            type="file-csv",
            spec="downstream/csv-layout.yaml",
            spec_content=(
                "# reviewed CSV layout\n"
                "format: csv\n"
                "record_types:\n"
                "  data:\n"
                "    fields:\n"
                "      - name: account_id # identifier\n"
                "        column: 1\n"
            ),
        ),
        DownstreamInterface(
            name="xml-out",
            type="xml-xsd",
            xsd_path="contracts/output.xsd",
            root_element="acct:Output",
            entity_name="Account",
            field_mappings=[FieldMapping(source="Account.accountId", target="accountId")],
            mapping_path="downstream/xml-out-mapping.yaml",
        ),
        DownstreamInterface(
            name="soap-out",
            type="soap-wsdl",
            wsdl_path="contracts/client.wsdl",
            service="ClientService",
            port="ClientPort",
            binding="ClientBinding",
            selected_operation_name="SendAccountStatus",
            mapping_path="mappings/soap-out-operation-mapping.yaml",
            soap_operation_mode="canonical",
            soap_canonical_invocation=SoapCanonicalInvocationConfig(
                entity="Account",
                lookup_field="accountId",
                request_mappings=[
                    SoapRequestMapping(source="Account.accountId", target_path="/SendAccountStatusRequest/accountId"),
                ],
                response_mappings=[
                    SoapReturnMapping(source_path="/SendAccountStatusResponse/resultCode", target="resultCode"),
                ],
            ),
        ),
    ]

    path = tmp_path / "edge-contract.project.json"
    save_project(session, path)
    project = deserialize_project(path.read_text(encoding="utf-8"))
    restored = ProjectSession()
    restore_session(project, restored)

    assert [iface.type for iface in restored.upstream_interfaces] == [
        "file-fixed-width",
        "file-csv",
        "xml-xsd",
        "soap-wsdl",
    ]
    assert restored.upstream_interfaces[0].entity_name == "Account"
    assert restored.upstream_interfaces[0].mapping_path == "upstream/fixed-in-mapping.yaml"
    assert [(m.source, m.target) for m in restored.upstream_interfaces[0].field_mappings] == [
        ("account_id", "accountId")
    ]
    assert restored.upstream_interfaces[2].xsd_path == "contracts/input.xsd"
    assert restored.upstream_interfaces[2].root_element == "acct:Input"
    assert restored.upstream_interfaces[2].entity_name == "Account"
    assert restored.upstream_interfaces[2].mapping_path == "upstream/xml-in-mapping.yaml"
    assert [(m.source, m.target) for m in restored.upstream_interfaces[2].field_mappings] == [
        ("accountId", "Account.accountId")
    ]
    assert restored.upstream_interfaces[3].wsdl_path == "contracts/service.wsdl"
    assert restored.upstream_interfaces[3].selected_operation_name == "GetAccountStatus"
    assert [op.name for op in restored.upstream_interfaces[3].operations] == ["GetAccountStatus"]
    assert restored.upstream_interfaces[3].mapping_path == "mappings/soap-in-operation-mapping.yaml"
    assert restored.upstream_interfaces[3].soap_operation_mode == "canonical"
    assert restored.upstream_interfaces[3].soap_canonical_operation is not None
    assert restored.upstream_interfaces[3].soap_canonical_operation.lookup_field == "accountId"
    assert restored.upstream_interfaces[3].soap_canonical_operation.response_mappings[0].target_path == (
        "/GetAccountStatusResponse/accountId"
    )
    assert [iface.type for iface in restored.downstream_interfaces] == [
        "file-csv",
        "xml-xsd",
        "soap-wsdl",
    ]
    assert restored.downstream_interfaces[0].spec_content == session.downstream_interfaces[0].spec_content
    assert restored.downstream_interfaces[1].entity_name == "Account"
    assert restored.downstream_interfaces[1].mapping_path == "downstream/xml-out-mapping.yaml"
    assert [(m.source, m.target) for m in restored.downstream_interfaces[1].field_mappings] == [
        ("Account.accountId", "accountId")
    ]
    assert restored.downstream_interfaces[2].selected_operation_name == "SendAccountStatus"
    assert restored.downstream_interfaces[2].mapping_path == "mappings/soap-out-operation-mapping.yaml"
    assert restored.downstream_interfaces[2].soap_operation_mode == "canonical"
    assert restored.downstream_interfaces[2].soap_canonical_invocation is not None
    assert restored.downstream_interfaces[2].soap_canonical_invocation.kind == "invoke_by_id"
    assert restored.downstream_interfaces[2].soap_canonical_invocation.lookup_field == "accountId"
    assert restored.downstream_interfaces[2].soap_canonical_invocation.request_field == "id"
    assert restored.downstream_interfaces[2].soap_canonical_invocation.request_mappings[0].target_path == (
        "/SendAccountStatusRequest/accountId"
    )
    assert restored.downstream_interfaces[2].soap_canonical_invocation.response_mappings[0].source_path == (
        "/SendAccountStatusResponse/resultCode"
    )


def _passthrough_session() -> ProjectSession:
    """Session with passthrough-router archetype and passthrough_flow populated."""
    s = ProjectSession()
    s.app_name = "Router App"
    s.bounded_context = "router"
    s.app_archetype = "passthrough-router"
    s.target_profile = "springboot-legacy-compatible"
    s.passthrough_flow = PassthroughFlow(
        upstream_operation_name="routeRequest",
        route_field="accountType",
        routes=[PassthroughRouteRow(match="savings", target="savings-service")],
        default_target="default-service",
    )
    return s


def _project_with_ks_placeholders() -> StudioProject:
    session = _crud_session()
    base = snapshot_session(session)
    return base.model_copy(
        update={
            "project_id": "workspace-123",
            "ks_project_id": "workspace-123",
            "ks_active": True,
            "suggestion_review_state": KSSuggestionReviewState(
                accepted_ids=["s-1"],
                rejected_ids=["s-2"],
                edited_ids=["s-3"],
            ),
            "evidence_links": [
                KSEvidenceLink(
                    manifest_path="entities.Account.fields.account_id",
                    suggestion_id="s-1",
                    provenance="ai-accepted",
                )
            ],
            "manifest_revisions": [
                KSManifestRevision(
                    revision_id="rev-001",
                    exported_at="2026-04-19T00:00:00Z",
                    manifest_hash="sha256:abc123",
                    archetype="crud",
                    target_profile="springboot-legacy-compatible",
                    export_path="/tmp/export",
                )
            ],
            "conflict_resolutions": [
                KSConflictResolution(
                    conflict_id="c-1",
                    resolution="use-source-a",
                    rationale="Latest BRD wins",
                    resolved_at="2026-04-19T00:00:00Z",
                )
            ],
            "review_history": [
                KSReviewHistoryEntry(
                    suggestion_id="s-1",
                    type="field",
                    status="accepted",
                    manifest_path="entities.Account.fields.account_id",
                    reviewed_at="2026-04-19T00:00:00Z",
                    edited_payload={"name": "account_id"},
                )
            ],
        }
    )


# ---------------------------------------------------------------------------
# Test 1 — Saving a CRUD project writes JSON with schema version + Steps 1-6
# ---------------------------------------------------------------------------


def test_save_crud_project_json_structure():
    """Saving a CRUD project produces JSON with schema version and Steps 1-6 fields."""
    session = _crud_session()
    project = snapshot_session(session)
    raw = serialize_project(project)
    data = json.loads(raw)

    # Schema identity
    assert data["studio_project_schema_version"] == STUDIO_PROJECT_SCHEMA_VERSION
    assert "saved_at" in data and data["saved_at"]

    # Step 1
    assert data["app_name"] == "DDA App"
    assert data["bounded_context"] == "dda"
    assert data["app_archetype"] == "crud"
    assert data["target_profile"] == "springboot-legacy-compatible"
    assert data["project_id"] is None
    assert data["ks_project_id"] is None
    assert data["ks_active"] is False
    assert data["capabilities"] == {"knowledge_assist_enabled": False}
    assert data["project_revision"] == 1
    assert data["saved_at"]

    # Step 2
    assert data["raw_spec_content"] == '{"openapi": "3.0.0"}'
    assert data["raw_spec_url"] == "https://example.com/spec.json"

    # Step 3
    assert len(data["classified_entities"]) == 1
    assert data["classified_entities"][0]["name"] == "Account"
    assert data["selected_entity_names"] == ["Account"]
    assert data["identity_role_decisions"] == []

    # Step 4 + 5 + 6
    assert len(data["upstream_interfaces"]) == 1
    assert len(data["downstream_interfaces"]) == 1
    assert len(data["data_handoffs"]) == 1
    assert len(data["entity_rules"]) == 1
    assert data["legacy_notes"] == "Some legacy note"
    assert data["legacy_slug"] == "dda-legacy"


# ---------------------------------------------------------------------------
# Test 2 — Opening a saved CRUD project restores session state
# ---------------------------------------------------------------------------


def test_open_crud_project_restores_session():
    """Deserialised project restores a clean session to the original authoring state."""
    original = _crud_session()
    project = snapshot_session(original)
    raw = serialize_project(project)

    restored_project = deserialize_project(raw)
    session = ProjectSession()
    restore_session(restored_project, session)

    assert session.app_name == "DDA App"
    assert session.bounded_context == "dda"
    assert session.app_archetype == "crud"
    assert session.target_profile == "springboot-legacy-compatible"
    assert session.output_path == "/tmp/output"
    assert session.appbuilder_repo_path == "/tmp/edgeforge"
    assert len(session.classified_entities) == 1
    assert session.selected_entity_names == ["Account"]
    assert len(session.upstream_interfaces) == 1
    assert len(session.downstream_interfaces) == 1
    assert len(session.data_handoffs) == 1
    assert len(session.entity_rules) == 1
    assert session.entity_rules[0].rules[0].values == ["USD", "EUR"]
    assert session.legacy_notes == "Some legacy note"
    assert session.legacy_slug == "dda-legacy"
    assert session.project_id is None
    assert session.ks_project_id is None
    assert session.ks_active is False


def test_identity_role_decisions_survive_save_open_round_trip():
    original = _crud_session()
    original.identity_role_decisions = [
        IdentityRoleDecision(
            entity="Account",
            field="accountId",
            role="persistence_id",
            reviewed_at="2026-05-06T12:00:00+00:00",
        )
    ]

    raw = serialize_project(snapshot_session(original))
    restored_project = deserialize_project(raw)
    restored = ProjectSession()
    restore_session(restored_project, restored)

    assert len(restored.identity_role_decisions) == 1
    decision = restored.identity_role_decisions[0]
    assert decision.entity == "Account"
    assert decision.field == "accountId"
    assert decision.role == "persistence_id"
    assert decision.provenance == "human-authored"


def test_identity_role_decision_rejects_invalid_role_value():
    with pytest.raises(ValidationError):
        IdentityRoleDecision(entity="Account", field="accountId", role="made_up")


def test_identity_role_service_values_match_model_validation():
    assert "persistence_id" in IDENTITY_ROLE_VALUES
    assert "external_reference" in IDENTITY_ROLE_VALUES
    for role in IDENTITY_ROLE_VALUES:
        assert IdentityRoleDecision(entity="Account", field="accountId", role=role).role == role


def test_older_project_without_identity_roles_defaults_empty():
    project = snapshot_session(_crud_session())
    data = json.loads(serialize_project(project))
    data.pop("identity_role_decisions", None)

    restored_project = deserialize_project(json.dumps(data))
    restored = ProjectSession()
    restore_session(restored_project, restored)

    assert restored.identity_role_decisions == []


def test_older_soap_project_without_mapping_mode_defaults_adapter_only():
    project = snapshot_session(_crud_session())
    data = json.loads(serialize_project(project))
    data["upstream_interfaces"] = [
        {
            "name": "customer-soap",
            "type": "soap-wsdl",
            "wsdl_path": "contracts/customer.wsdl",
            "selected_operation_name": "getCustomer",
            "mapping_path": "mappings/customer-soap-operation-mapping.yaml",
        }
    ]
    data["downstream_interfaces"] = [
        {
            "name": "customer-soap-client",
            "type": "soap-wsdl",
            "wsdl_path": "contracts/customer-client.wsdl",
            "selected_operation_name": "syncCustomer",
            "mapping_path": "mappings/customer-soap-client-operation-mapping.yaml",
        }
    ]

    restored_project = deserialize_project(json.dumps(data))
    restored = ProjectSession()
    restore_session(restored_project, restored)

    iface = restored.upstream_interfaces[0]
    assert iface.soap_operation_mode == "adapter_only"
    assert iface.soap_handler_method is None
    assert iface.soap_canonical_operation is None
    downstream = restored.downstream_interfaces[0]
    assert downstream.soap_operation_mode == "adapter_only"
    assert downstream.soap_canonical_invocation is None


def test_v1_2_project_migration_defaults_identity_roles_empty():
    project = snapshot_session(_crud_session())
    data = json.loads(serialize_project(project))
    data["studio_project_schema_version"] = "1.2"
    data.pop("identity_role_decisions", None)
    data.pop("auto_rule_merge_completed_entities", None)

    restored_project = deserialize_project(json.dumps(data))
    restored = ProjectSession()
    restore_session(restored_project, restored)

    assert restored.identity_role_decisions == []
    assert restored_project.studio_project_schema_version == STUDIO_PROJECT_SCHEMA_VERSION


def test_project_open_drops_invalid_identity_role_decisions():
    project = snapshot_session(_crud_session())
    data = json.loads(serialize_project(project))
    data["identity_role_decisions"] = [
        {"entity": "Account", "field": "accountId", "role": "made_up"},
        {"entity": "Account", "field": "accountId", "role": "persistence_id"},
    ]

    restored_project = deserialize_project(json.dumps(data))
    restored = ProjectSession()
    restore_session(restored_project, restored)

    assert [decision.role for decision in restored.identity_role_decisions] == ["persistence_id"]


def test_open_v1_1_project_restores_durable_ks_linkage():
    """Opening a linked project restores dormant linkage without implicit KS activation."""
    original = _crud_session()
    original.project_id = "workspace-123"
    original.ks_project_id = "workspace-123"
    original.ks_active = True
    project = snapshot_session(original)
    raw = serialize_project(project)

    restored_project = deserialize_project(raw)
    session = ProjectSession()
    session.project_id = "old-workspace"
    session.ks_project_id = "old-workspace"
    restore_session(restored_project, session)

    assert session.project_id == "workspace-123"
    assert session.ks_project_id == "workspace-123"
    assert session.ks_active is False
    assert session.capabilities.knowledge_assist_enabled is False
    assert session.is_brand_new is False
    assert session.review_approved is False


def test_project_session_defaults_capabilities_off():
    session = ProjectSession()

    assert session.capabilities.knowledge_assist_enabled is False
    assert session.capabilities.any_assist_active is False


def test_studio_project_defaults_capabilities_off():
    project = StudioProject()

    assert project.capabilities.knowledge_assist_enabled is False
    assert project.capabilities.any_assist_active is False


def test_snapshot_and_restore_preserve_enabled_capabilities():
    original = _crud_session()
    original.project_id = "workspace-123"
    original.ks_project_id = "workspace-123"
    original.ks_active = True
    original.capabilities = ProjectCapabilities(knowledge_assist_enabled=True)

    project = snapshot_session(original)
    restored_project = deserialize_project(serialize_project(project))
    session = ProjectSession()
    restore_session(restored_project, session)

    assert project.capabilities.knowledge_assist_enabled is True
    assert project.ks_active is True
    assert session.capabilities.knowledge_assist_enabled is True
    assert session.ks_active is True


def test_snapshot_sets_saved_at_and_modified_by(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_USER", "studio-user")

    project = snapshot_session(_crud_session())

    assert project.saved_at
    assert project.modified_by == "studio-user"


def test_current_user_hint_respects_edgeforge_user(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_USER", "override-user")
    monkeypatch.setenv("USER", "os-user")

    assert _current_user_hint() == "override-user"


def test_current_user_hint_empty_edgeforge_user_suppresses_identity(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_USER", "")
    monkeypatch.setenv("USER", "os-user")
    monkeypatch.setenv("USERNAME", "windows-user")

    assert _current_user_hint() is None


def test_save_project_increments_revision_and_writes_backup(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGEFORGE_USER", "save-user")
    session = _crud_session()
    session.project_revision = 3
    target = tmp_path / "studio-project.json"
    target.write_text('{"old": true}', encoding="utf-8")

    project = save_project(session, target)
    saved_data = json.loads(target.read_text(encoding="utf-8"))
    backup_data = json.loads(target.with_name("studio-project.json.bak").read_text(encoding="utf-8"))

    assert project.project_revision == 4
    assert session.project_revision == 4
    assert saved_data["project_revision"] == 4
    assert saved_data["modified_by"] == "save-user"
    assert backup_data == {"old": True}


def test_brand_new_first_save_sets_created_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGEFORGE_USER", "creator")
    session = _crud_session()
    session.is_brand_new = True

    project = save_project(session, tmp_path / "first-save.json")

    assert project.project_revision == 1
    assert project.created_at
    assert project.created_by == "creator"
    assert project.modified_by == "creator"
    assert session.is_brand_new is False


def test_save_as_resets_revision_but_preserves_project_id(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGEFORGE_USER", "save-as-user")
    session = _crud_session()
    session.project_id = "project-123"
    session.project_revision = 9
    session.created_at = "2026-04-01T00:00:00+00:00"
    session.created_by = "original"
    session.is_brand_new = True

    project = save_project(session, tmp_path / "copy.json", save_as=True)

    assert project.project_id == "project-123"
    assert project.project_revision == 1
    assert project.created_by == "save-as-user"
    assert project.created_at != "2026-04-01T00:00:00+00:00"
    assert session.is_brand_new is False

    next_project = save_project(session, tmp_path / "copy.json")

    assert next_project.project_revision == 2
    assert session.project_revision == 2


def test_failed_save_keeps_original_file(tmp_path, monkeypatch):
    session = _crud_session()
    session.project_revision = 5
    target = tmp_path / "studio-project.json"
    target.write_text("original", encoding="utf-8")
    original_write_text = Path.write_text

    def fail_tmp_write(self, *args, **kwargs):
        if str(self).endswith(".tmp"):
            raise OSError("mock tmp write failed")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_tmp_write)

    with pytest.raises(OSError, match="mock tmp write failed"):
        save_project(session, target)

    assert target.read_text(encoding="utf-8") == "original"
    assert not target.with_name("studio-project.json.tmp").exists()
    assert session.project_revision == 5
    assert session.saved_at is None


def test_snapshot_session_for_save_updates_saved_metadata(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_USER", "download-user")
    session = _crud_session()
    session.project_revision = 1

    project = snapshot_session_for_save(session)

    assert project.project_revision == 2
    assert session.project_revision == 2
    assert project.saved_at == session.saved_at
    assert project.modified_by == "download-user"


def test_workspace_activation_persists_active_runtime_when_assist_enabled():
    original = _crud_session()
    original.project_id = "workspace-123"
    original.ks_project_id = "workspace-123"
    original.capabilities.knowledge_assist_enabled = True

    mark_workspace_active(original)
    project = snapshot_session(original)
    restored_project = deserialize_project(serialize_project(project))
    session = ProjectSession()
    restore_session(restored_project, session)

    assert project.capabilities.knowledge_assist_enabled is True
    assert project.ks_active is True
    assert session.capabilities.knowledge_assist_enabled is True
    assert session.ks_active is True
    assert session.ks_project_id == "workspace-123"


def test_cross_entity_rule_fields_survive_save_open_round_trip():
    session = _crud_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(
                    field="customerId",
                    type="cross-entity-field-check",
                    target_entity="Customer",
                    target_field="status",
                    operator="eq",
                    expected_value="ACTIVE",
                    error_message="Customer must be ACTIVE.",
                ),
                RuleEntry(
                    field="customerId",
                    type="cross-entity-field-compare",
                    target_entity="Customer",
                    target_field="approvedLimit",
                    source_field="requestedAmount",
                    operator="lte",
                    error_message="Requested amount exceeds approved limit.",
                ),
                RuleEntry(
                    field="customerId",
                    type="cross-entity-field-in",
                    target_entity="Customer",
                    target_field="status",
                    values=["ACTIVE", "REVIEW"],
                    error_message="Customer status must be eligible.",
                ),
            ],
            file_path="rules/account-rules.yaml",
        )
    ]

    raw = serialize_project(snapshot_session(session))
    restored = ProjectSession()
    restore_session(deserialize_project(raw), restored)

    rules = restored.entity_rules[0].rules
    assert rules[0].target_field == "status"
    assert rules[0].expected_value == "ACTIVE"
    assert rules[0].error_message == "Customer must be ACTIVE."
    assert rules[1].source_field == "requestedAmount"
    assert rules[1].target_field == "approvedLimit"
    assert rules[1].operator == "lte"
    assert rules[2].values == ["ACTIVE", "REVIEW"]
    assert rules[2].target_field == "status"


def test_kafka_router_config_survives_save_open_round_trip():
    session = ProjectSession(
        app_name="Payment Router",
        bounded_context="payments",
        app_archetype="kafka-integration",
        target_profile="springboot-standard-enterprise",
    )
    session.kafka_config = KafkaConfig(consumer_group="payment-router-group")
    session.kafka_topic_pairs = [
        KafkaTopicPair(
            route_name="payment-router",
            upstream_topic="payment.request",
            downstream_topic="payment.target",
        )
    ]
    session.kafka_route_models = [
        KafkaRouteModel(
            route_name="payment-router",
            pattern="router",
            router_config={
                "upstream_topics": [
                    {
                        "id": "u1",
                        "name": "payment.request",
                        "consumer_group": "payment-router-group",
                        "source_system_extraction": {
                            "mode": "header",
                            "header_key": "X-Source-System",
                        },
                        "reply_destination_extraction": {
                            "mode": "header",
                            "header_key": "X-Reply-To",
                        },
                    }
                ],
                "inbound_schema": {"file": "schemas/router-in.json"},
                "routing_rules": {
                    "routing_fields": [{"name": "country", "json_path": "$.country"}],
                    "rules": [
                        {
                            "id": "uk",
                            "conditions": [{"field": "country", "operator": "eq", "value": "UK"}],
                            "target": "d1",
                        }
                    ],
                    "default_target": "d1",
                },
                "targets": [
                    {
                        "id": "d1",
                        "request_topic": "payment.target",
                        "response_topic": "payment.target.reply",
                        "request_schema": {"file": "schemas/d1-request.json"},
                        "response_schema": {"file": "schemas/d1-response.json"},
                        "request_transform": {"file": "transforms/router-request.yaml"},
                        "response_transform": {"file": "transforms/router-response.yaml"},
                        "retry": {"max_attempts": 3, "backoff_ms": 1000, "dlq_topic": "payment.target.dlq"},
                        "timeout_ms": 30000,
                    }
                ],
                "outbound_schema": {"file": "schemas/router-out.json"},
                "nack_routing": {
                    "mode": "fixed",
                    "fixed_topic": "payment.router.nack",
                    "default_error_topic": "payment.router.error",
                },
            },
        )
    ]

    raw = serialize_project(snapshot_session(session))
    restored = ProjectSession()
    restore_session(deserialize_project(raw), restored)

    restored_model = restored.kafka_route_models[0]
    assert restored_model.pattern == "router"
    assert restored_model.router_config is not None
    assert restored_model.router_config.targets[0].response_transform.file == "transforms/router-response.yaml"
    assert restored_model.router_config.routing_rules.default_target == "d1"


def test_kafka_router_transform_rows_survive_save_open_round_trip():
    session = ProjectSession(
        app_name="Payment Router",
        bounded_context="payments",
        app_archetype="kafka-integration",
        target_profile="springboot-standard-enterprise",
    )
    session.kafka_config = KafkaConfig(consumer_group="payment-router-group")
    session.kafka_topic_pairs = [KafkaTopicPair(route_name="payment-router")]
    session.kafka_route_models = [
        KafkaRouteModel(route_name="payment-router", pattern="router")
    ]
    session.kafka_route_transforms = [
        KafkaRouteTransform(
            route_name="payment-router",
            router_target_transforms=[
                KafkaRouterTargetTransform(
                    target_id="d1",
                    request_transform_rows=[
                        KafkaRouterTransformRow(
                            source="paymentId",
                            target="transactionId",
                            value_map={"APPROVED": "A"},
                            type_coercion="major_to_minor_units",
                        )
                    ],
                    response_transform_rows=[
                        KafkaRouterTransformRow(
                            source="processorStatus",
                            target="status",
                            constant="OK",
                        )
                    ],
                )
            ],
        )
    ]

    raw = serialize_project(snapshot_session(session))
    restored = ProjectSession()
    restore_session(deserialize_project(raw), restored)

    restored_target = restored.kafka_route_transforms[0].router_target_transforms[0]
    assert restored_target.target_id == "d1"
    assert restored_target.request_transform_rows[0].value_map == {"APPROVED": "A"}
    assert restored_target.request_transform_rows[0].type_coercion == "major_to_minor_units"
    assert restored_target.response_transform_rows[0].constant == "OK"


# ---------------------------------------------------------------------------
# Test 3 — target_profile preserved through save/open cycle
# ---------------------------------------------------------------------------


def test_target_profile_preserved():
    """target_profile survives the full save → deserialise → restore cycle."""
    session = _crud_session()
    session.target_profile = "springboot-enterprise-postgres-java17"

    raw = serialize_project(snapshot_session(session))
    restored = ProjectSession()
    restore_session(deserialize_project(raw), restored)

    assert restored.target_profile == "springboot-enterprise-postgres-java17"


# ---------------------------------------------------------------------------
# Test 4 — raw_spec_content + raw_spec_url/filename preserved
# ---------------------------------------------------------------------------


def test_raw_spec_preserved():
    """raw_spec_content, raw_spec_url, and raw_spec_filename survive save/open."""
    session = _crud_session()
    session.raw_spec_content = '{"openapi":"3.0.1","info":{"title":"My API"}}'
    session.raw_spec_url = "https://myapi.example.com/openapi.json"
    session.raw_spec_filename = "myapi-openapi.json"

    raw = serialize_project(snapshot_session(session))
    restored = ProjectSession()
    restore_session(deserialize_project(raw), restored)

    assert restored.raw_spec_content == session.raw_spec_content
    assert restored.raw_spec_url == "https://myapi.example.com/openapi.json"
    assert restored.raw_spec_filename == "myapi-openapi.json"


# ---------------------------------------------------------------------------
# Test 5 — passthrough_flow preserved through save/open cycle
# ---------------------------------------------------------------------------


def test_passthrough_flow_preserved():
    """passthrough_flow survives save/open for passthrough-router projects."""
    session = _passthrough_session()

    raw = serialize_project(snapshot_session(session))
    restored = ProjectSession()
    restore_session(deserialize_project(raw), restored)

    assert restored.app_archetype == "passthrough-router"
    assert restored.passthrough_flow is not None
    assert restored.passthrough_flow.upstream_operation_name == "routeRequest"
    assert restored.passthrough_flow.route_field == "accountType"
    assert len(restored.passthrough_flow.routes) == 1
    assert restored.passthrough_flow.routes[0].match == "savings"
    assert restored.passthrough_flow.default_target == "default-service"


def test_mapping_rows_and_review_state_survive_save_open_round_trip():
    """Applied mapping suggestions and dormant review state survive save/open."""
    session = _passthrough_session()
    session.capabilities.knowledge_assist_enabled = True
    session.passthrough_flow.transforms = [
        PassthroughTransform(source="currency", target="settlementCurrency")
    ]
    session.kafka_route_transforms = [
        KafkaRouteTransform(
            route_name="payment-posted",
            mappings=[KafkaTransformRow(source_field="paymentId", target_field="ledgerId")],
            router_target_transforms=[
                KafkaRouterTargetTransform(
                    target_id="ledger-core",
                    request_transform_rows=[
                        KafkaRouterTransformRow(source="amount", target="amountMinor")
                    ],
                )
            ],
        )
    ]
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["m-1"]
    session.ks_workspace_state.suggestion_review_state.edited_ids = ["m-2", "t-1"]
    session.ks_workspace_state.suggestion_review_state.rejected_ids = ["c-1", "p-1"]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="m-1",
            type="mapping",
            status="accepted",
            manifest_path="passthrough.routeRequest.transforms.currency.settlementCurrency",
            reviewed_at="2026-04-28T12:00:00+00:00",
            review_context={
                "mapping_context": "passthrough",
                "route_name": "routeRequest",
                "direction": "request",
                "source_field": "currency",
                "target_field": "settlementCurrency",
            },
        ),
        KSReviewHistoryEntry(
            suggestion_id="m-2",
            type="mapping",
            status="edited",
            manifest_path="async_routes.payment-posted.transform_mapping.request.paymentId.ledgerId",
            reviewed_at="2026-04-28T12:01:00+00:00",
            edited_payload={"source_field": "paymentId", "target_field": "ledgerId"},
            review_context={
                "mapping_context": "kafka",
                "route_name": "payment-posted",
                "direction": "request",
                "source_field": "paymentId",
                "target_field": "ledgerId",
            },
        ),
        KSReviewHistoryEntry(
            suggestion_id="c-1",
            type="conflict_resolution",
            status="rejected",
            manifest_path="conflicts.c-1",
            reviewed_at="2026-04-29T12:00:00+00:00",
            edited_payload=None,
            review_context={"conflict_query": "Account.status", "document_ids": ["brd-1"]},
        ),
        KSReviewHistoryEntry(
            suggestion_id="p-1",
            type="portfolio_reuse",
            status="rejected",
            manifest_path="portfolio_reuse.p-1",
            reviewed_at="2026-04-29T13:00:00+00:00",
            edited_payload=None,
            review_context={
                "portfolio_query": "Account Hub",
                "matched_project_id": "portfolio-project-1",
                "document_labels": ["Account Pattern BRD.pdf"],
            },
        ),
        KSReviewHistoryEntry(
            suggestion_id="t-1",
            type="transform",
            status="edited",
            manifest_path="async_routes.payment-posted.router_config.targets.ledger-core.request_transform.amount.amountMinor",
            reviewed_at="2026-04-29T14:00:00+00:00",
            edited_payload={"source": "amount", "target": "amountMinor"},
            review_context={
                "mapping_context": "kafka_router_transform",
                "route_name": "payment-posted",
                "target_id": "ledger-core",
                "direction": "request",
                "source": "amount",
                "target": "amountMinor",
            },
        ),
    ]

    raw = serialize_project(snapshot_session(session))
    restored = ProjectSession()
    restore_session(deserialize_project(raw), restored)

    assert restored.passthrough_flow.transforms == [
        PassthroughTransform(source="currency", target="settlementCurrency")
    ]
    assert restored.kafka_route_transforms[0].mappings == [
        KafkaTransformRow(source_field="paymentId", target_field="ledgerId")
    ]
    assert restored.kafka_route_transforms[0].router_target_transforms[0].request_transform_rows == [
        KafkaRouterTransformRow(source="amount", target="amountMinor")
    ]
    assert restored.ks_workspace_state.suggestion_review_state.accepted_ids == ["m-1"]
    assert restored.ks_workspace_state.review_history[0].review_context["source_field"] == "currency"
    assert restored.ks_workspace_state.review_history[1].review_context["target_field"] == "ledgerId"
    assert restored.ks_workspace_state.suggestion_review_state.edited_ids == ["m-2", "t-1"]
    assert restored.ks_workspace_state.suggestion_review_state.rejected_ids == ["c-1", "p-1"]
    assert restored.ks_workspace_state.review_history[0].type == "mapping"
    assert restored.ks_workspace_state.review_history[1].status == "edited"
    assert restored.ks_workspace_state.review_history[1].manifest_path.endswith("paymentId.ledgerId")
    assert restored.ks_workspace_state.review_history[2].type == "conflict_resolution"
    assert restored.ks_workspace_state.review_history[2].review_context["document_ids"] == ["brd-1"]
    assert restored.ks_workspace_state.review_history[3].type == "portfolio_reuse"
    assert restored.ks_workspace_state.review_history[3].review_context["matched_project_id"] == "portfolio-project-1"
    assert restored.ks_workspace_state.review_history[3].review_context["document_labels"] == [
        "Account Pattern BRD.pdf"
    ]
    assert restored.ks_workspace_state.review_history[4].type == "transform"
    assert restored.ks_workspace_state.review_history[4].review_context["target_id"] == "ledger-core"
    assert restored.ks_workspace_state.evidence_links == []


# ---------------------------------------------------------------------------
# Test 6 — Step 8 transient state NOT in saved project
# ---------------------------------------------------------------------------


def test_step8_state_not_in_saved_project():
    """BuildRunState fields (PID, port, logs, health) must not appear in the snapshot."""
    session = _crud_session()
    # Populate Step 8 state
    session.build_run.pid = 12345
    session.build_run.port = 8080
    session.build_run.build_status = "build_succeeded"
    session.build_run.run_status = "running"
    session.build_run.build_log_path = "/tmp/build.log"
    session.build_run.run_log_path = "/tmp/run.log"
    session.build_run.app_url = "http://localhost:8080"
    session.build_run.health_url = "http://localhost:8080/actuator/health"

    project = snapshot_session(session)
    raw = serialize_project(project)
    data = json.loads(raw)

    # None of the Step 8 runtime fields should appear in the saved snapshot
    for forbidden_key in (
        "build_run",
        "pid",
        "port",
        "build_status",
        "run_status",
        "build_log_path",
        "run_log_path",
        "app_url",
        "health_url",
    ):
        assert forbidden_key not in data, (
            f"Forbidden Step 8 field '{forbidden_key}' found in saved project"
        )


def test_restore_clears_stale_build_run_state():
    """Opening a project into a session that already has Step 8 state must reset it."""

    # Simulate a session that previously built/ran an app
    existing_session = _crud_session()
    existing_session.build_run.pid = 99999
    existing_session.build_run.port = 9090
    existing_session.build_run.run_status = "running"
    existing_session.build_run.app_url = "http://localhost:9090"

    # Save a fresh project and restore it into that existing session
    new_project_session = _crud_session()
    project = snapshot_session(new_project_session)
    restore_session(project, existing_session)

    # build_run must be a fresh default — no stale PID, port, or status
    assert existing_session.build_run.pid is None
    assert existing_session.build_run.port is None
    assert existing_session.build_run.run_status in (None, "", "idle", "not_started")
    assert existing_session.build_run.app_url is None


# ---------------------------------------------------------------------------
# Test 7 — Malformed JSON returns clear error
# ---------------------------------------------------------------------------


def test_malformed_json_raises_error():
    """Passing malformed JSON to deserialize_project raises a ValueError with a clear message."""
    with pytest.raises(ValueError, match="Malformed project file"):
        deserialize_project("{this is not valid json}")


def test_empty_string_raises_error():
    """An empty string raises a ValueError."""
    with pytest.raises(ValueError, match="Malformed project file"):
        deserialize_project("")


def test_non_object_json_raises_error():
    """Valid JSON that is not an object (e.g. a list) raises ValueError, not AttributeError."""
    with pytest.raises(ValueError, match="expected a JSON object"):
        deserialize_project("[]")

    with pytest.raises(ValueError, match="expected a JSON object"):
        deserialize_project('"just a string"')

    with pytest.raises(ValueError, match="expected a JSON object"):
        deserialize_project("42")


# ---------------------------------------------------------------------------
# Test 8 — Unknown future schema version returns clear unsupported error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("schema_version", ["1.5", "2.0", "99.0"])
def test_unknown_schema_version_raises_error(schema_version):
    """A project file with an unsupported schema version raises a clear ValueError."""
    session = _crud_session()
    raw = serialize_project(snapshot_session(session))
    data = json.loads(raw)
    data["studio_project_schema_version"] = schema_version

    with pytest.raises(ValueError, match="Unsupported Studio project schema version"):
        deserialize_project(json.dumps(data))


@pytest.mark.parametrize("schema_version", ["1.0", "1.1", "1.2", "1.3", "1.4"])
def test_supported_studio_snapshots_reopen_and_export_manifest_v2(tmp_path, schema_version):
    session = ProjectSession(
        app_name="Migrated Studio Project",
        bounded_context=f"snapshot-{schema_version.replace('.', '-')}",
        app_archetype="crud",
    )
    data = json.loads(serialize_project(snapshot_session(session)))
    data["studio_project_schema_version"] = schema_version

    project = deserialize_project(json.dumps(data))
    restored = ProjectSession()
    restore_session(project, restored)
    result = write_package_result(restored, tmp_path)
    manifest = yaml.safe_load(
        (result.project_dir / "app-definition.yaml").read_text(encoding="utf-8")
    )

    assert project.studio_project_schema_version == "1.4"
    assert manifest["schema_version"] == "2.0"


def test_missing_schema_version_raises_error():
    """A project file missing studio_project_schema_version raises a clear ValueError."""
    session = _crud_session()
    raw = serialize_project(snapshot_session(session))
    data = json.loads(raw)
    del data["studio_project_schema_version"]

    with pytest.raises(ValueError, match="Unsupported Studio project schema version"):
        deserialize_project(json.dumps(data))


def test_v1_1_round_trip_preserves_ks_linkage_and_placeholders():
    project = _project_with_ks_placeholders()
    data = json.loads(serialize_project(project))
    data["studio_project_schema_version"] = "1.1"
    data.pop("capabilities", None)
    data["ks_active"] = True

    restored = deserialize_project(json.dumps(data))

    assert restored.studio_project_schema_version == STUDIO_PROJECT_SCHEMA_VERSION
    assert restored.project_id == "workspace-123"
    assert restored.ks_project_id == "workspace-123"
    assert restored.capabilities.knowledge_assist_enabled is False
    assert restored.ks_active is False
    assert restored.suggestion_review_state.accepted_ids == ["s-1"]
    assert restored.suggestion_review_state.rejected_ids == ["s-2"]
    assert restored.suggestion_review_state.edited_ids == ["s-3"]
    assert restored.evidence_links[0].provenance == "ai-accepted"
    assert restored.manifest_revisions[0].revision_id == "rev-001"
    assert restored.conflict_resolutions[0].conflict_id == "c-1"
    assert restored.review_history[0].edited_payload == {"name": "account_id"}


@pytest.mark.parametrize("schema_version", ["1.0", "1.1"])
def test_v1_0_and_v1_1_migrations_run_full_chain_to_revision_metadata(schema_version):
    project = _project_with_ks_placeholders()
    data = json.loads(serialize_project(project))
    data["studio_project_schema_version"] = schema_version
    data["saved_at"] = ""
    data.pop("capabilities", None)
    for key in ("project_revision", "created_at", "updated_at", "created_by", "modified_by"):
        data.pop(key, None)

    restored = deserialize_project(json.dumps(data))

    assert restored.studio_project_schema_version == STUDIO_PROJECT_SCHEMA_VERSION
    assert restored.project_revision == 1
    assert restored.created_at is None
    assert restored.updated_at is None
    assert restored.saved_at is None
    assert restored.created_by is None
    assert restored.modified_by is None
    assert restored.capabilities.knowledge_assist_enabled is False
    assert restored.ks_active is False
    assert restored.project_id == "workspace-123"
    assert restored.review_history[0].suggestion_id == "s-1"


def test_v1_2_migration_adds_revision_metadata_without_inventing_history():
    project = _project_with_ks_placeholders()
    data = json.loads(serialize_project(project))
    data["studio_project_schema_version"] = "1.2"
    data["capabilities"] = {"knowledge_assist_enabled": True}
    data["ks_active"] = True
    for key in ("project_revision", "created_at", "updated_at", "saved_at", "created_by", "modified_by"):
        data.pop(key, None)

    restored = deserialize_project(json.dumps(data))

    assert restored.studio_project_schema_version == STUDIO_PROJECT_SCHEMA_VERSION
    assert restored.project_revision == 1
    assert restored.created_at is None
    assert restored.updated_at is None
    assert restored.saved_at is None
    assert restored.created_by is None
    assert restored.modified_by is None
    assert restored.project_id == "workspace-123"
    assert restored.capabilities.knowledge_assist_enabled is True
    assert restored.ks_active is True
    assert restored.review_history[0].suggestion_id == "s-1"


def test_v1_3_migration_adds_regen_preview_binding_defaults():
    data = json.loads(serialize_project(snapshot_session(_crud_session())))
    data["studio_project_schema_version"] = "1.3"
    for key in (
        "last_generated_package_ref",
        "generation_run_id",
        "manifest_hash",
        "baseline_hash",
    ):
        data.pop(key, None)

    restored = deserialize_project(json.dumps(data))

    assert restored.studio_project_schema_version == STUDIO_PROJECT_SCHEMA_VERSION
    assert restored.last_generated_package_ref is None
    assert restored.generation_run_id is None
    assert restored.manifest_hash is None
    assert restored.baseline_hash is None


def test_regen_preview_binding_fields_survive_project_round_trip():
    session = _crud_session()
    session.last_generated_package_ref = "managed-artifacts/run-1/generated-app"
    session.generation_run_id = "run-1"
    session.manifest_hash = "manifest-hash"
    session.baseline_hash = "baseline-hash"

    restored = deserialize_project(serialize_project(snapshot_session(session)))

    assert restored.last_generated_package_ref == "managed-artifacts/run-1/generated-app"
    assert restored.generation_run_id == "run-1"
    assert restored.manifest_hash == "manifest-hash"
    assert restored.baseline_hash == "baseline-hash"


def test_legacy_project_backfills_auto_rule_merge_completed_entities():
    project = _project_with_ks_placeholders()
    project.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[RuleEntry(field="accountNumber", type="max-length", value="14")],
            file_path="rules/account-business-rules.yaml",
        )
    ]
    data = json.loads(serialize_project(project))
    data["studio_project_schema_version"] = "1.2"
    data.pop("auto_rule_merge_completed_entities", None)

    restored = deserialize_project(json.dumps(data))

    assert restored.auto_rule_merge_completed_entities == ["Account"]


def test_explicit_empty_auto_rule_merge_marker_survives_open():
    project = _project_with_ks_placeholders()
    project.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[RuleEntry(field="accountNumber", type="max-length", value="14")],
            file_path="rules/account-business-rules.yaml",
        )
    ]
    project.auto_rule_merge_completed_entities = []
    data = json.loads(serialize_project(project))
    data["auto_rule_merge_completed_entities"] = []

    restored = deserialize_project(json.dumps(data))

    assert restored.auto_rule_merge_completed_entities == []


def test_rule_entry_ka_metadata_survives_save_open_round_trip():
    project = _project_with_ks_placeholders()
    project.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(
                    field="status",
                    type="not-null",
                    suggestion_id="v-status",
                    suggestion_type="validation",
                    applied_by="knowledge_assist",
                    applied_at="2026-05-03T00:00:00+00:00",
                    generated_by_ka=True,
                    ka_review_status="accepted",
                )
            ],
            file_path="rules/account-business-rules.yaml",
        )
    ]

    restored = deserialize_project(serialize_project(project))
    rule = restored.entity_rules[0].rules[0]

    assert rule.suggestion_id == "v-status"
    assert rule.suggestion_type == "validation"
    assert rule.applied_by == "knowledge_assist"
    assert rule.applied_at == "2026-05-03T00:00:00+00:00"
    assert rule.generated_by_ka is True
    assert rule.ka_review_status == "accepted"


def test_removed_ka_rule_state_survives_save_open_round_trip():
    project = _project_with_ks_placeholders()
    project.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[],
            file_path="rules/account-business-rules.yaml",
        )
    ]
    project.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="v-status",
            type="validation",
            status="rejected",
            manifest_path="entities.Account.fields.status.validations.not-null",
            reviewed_at="2026-05-03T00:00:00+00:00",
        )
    ]

    restored = deserialize_project(serialize_project(project))

    assert restored.entity_rules[0].entity_name == "Account"
    assert restored.entity_rules[0].rules == []
    assert restored.review_history[0].suggestion_id == "v-status"


def test_v1_2_migration_normalizes_empty_saved_at_to_none():
    data = json.loads(serialize_project(snapshot_session(_crud_session())))
    data["studio_project_schema_version"] = "1.2"
    data["saved_at"] = ""
    data.pop("project_revision", None)

    restored = deserialize_project(json.dumps(data))

    assert restored.project_revision == 1
    assert restored.saved_at is None


def test_current_schema_project_is_not_re_migrated():
    data = json.loads(serialize_project(snapshot_session(_crud_session())))
    data["studio_project_schema_version"] = STUDIO_PROJECT_SCHEMA_VERSION
    data["project_revision"] = 7
    data["created_at"] = "2026-06-14T00:00:00+00:00"
    data["updated_at"] = "2026-06-14T01:00:00+00:00"
    data["saved_at"] = ""
    data["created_by"] = "creator"
    data["modified_by"] = "modifier"
    data["auto_rule_merge_completed_entities"] = []

    restored = deserialize_project(json.dumps(data))

    assert restored.studio_project_schema_version == STUDIO_PROJECT_SCHEMA_VERSION
    assert restored.project_revision == 7
    assert restored.created_at == "2026-06-14T00:00:00+00:00"
    assert restored.updated_at == "2026-06-14T01:00:00+00:00"
    assert restored.saved_at == ""
    assert restored.created_by == "creator"
    assert restored.modified_by == "modifier"


def test_older_v1_1_rule_entries_without_cross_entity_keys_still_deserialize():
    session = _crud_session()
    data = json.loads(serialize_project(snapshot_session(session)))
    data["studio_project_schema_version"] = "1.1"
    data.pop("capabilities", None)

    for entity_rules in data["entity_rules"]:
        for rule in entity_rules["rules"]:
            rule.pop("target_field", None)
            rule.pop("source_field", None)
            rule.pop("expected_value", None)
            rule.pop("error_message", None)

    restored = deserialize_project(json.dumps(data))
    restored_rule = restored.entity_rules[0].rules[0]

    assert restored.studio_project_schema_version == STUDIO_PROJECT_SCHEMA_VERSION
    assert restored_rule.target_field is None
    assert restored_rule.source_field is None
    assert restored_rule.expected_value is None
    assert restored_rule.error_message is None
    assert restored_rule.suggestion_id is None
    assert restored_rule.generated_by_ka is False
    assert restored_rule.ka_review_status is None


def test_older_v1_1_kafka_route_models_without_router_config_still_deserialize():
    session = ProjectSession(
        app_name="Kafka App",
        bounded_context="payments",
        app_archetype="kafka-integration",
        target_profile="springboot-standard-enterprise",
    )
    session.kafka_config = KafkaConfig(consumer_group="payments")
    session.kafka_topic_pairs = [
        KafkaTopicPair(
            route_name="payment-posted",
            upstream_topic="abc.payments.posted.v1",
            downstream_topic="xyz.ledger.entries.v1",
        )
    ]
    session.kafka_route_models = [
        KafkaRouteModel(route_name="payment-posted", pattern="fire-and-forget")
    ]
    data = json.loads(serialize_project(snapshot_session(session)))
    data["studio_project_schema_version"] = "1.1"
    data.pop("capabilities", None)
    data["kafka_route_models"][0].pop("router_config", None)

    restored = deserialize_project(json.dumps(data))

    assert restored.kafka_route_models[0].pattern == "fire-and-forget"
    assert restored.kafka_route_models[0].router_config is None


def test_older_v1_1_kafka_transforms_without_router_rows_still_deserialize():
    session = ProjectSession(
        app_name="Kafka App",
        bounded_context="payments",
        app_archetype="kafka-integration",
        target_profile="springboot-standard-enterprise",
    )
    session.kafka_config = KafkaConfig(consumer_group="payments")
    session.kafka_route_transforms = [
        KafkaRouteTransform(
            route_name="payment-posted",
            mappings=[],
            response_mappings=[],
        )
    ]
    data = json.loads(serialize_project(snapshot_session(session)))
    data["studio_project_schema_version"] = "1.1"
    data.pop("capabilities", None)
    data["kafka_route_transforms"][0].pop("router_target_transforms", None)

    restored = deserialize_project(json.dumps(data))

    assert restored.kafka_route_transforms[0].route_name == "payment-posted"
    assert restored.kafka_route_transforms[0].router_target_transforms == []


def test_v1_0_migration_initializes_new_ks_fields_safely():
    session = _crud_session()
    raw = serialize_project(snapshot_session(session))
    data = json.loads(raw)
    data["studio_project_schema_version"] = "1.0"
    data.pop("project_id", None)
    data.pop("ks_project_id", None)
    data.pop("ks_active", None)
    data.pop("suggestion_review_state", None)
    data.pop("evidence_links", None)
    data.pop("manifest_revisions", None)
    data.pop("conflict_resolutions", None)
    data.pop("review_history", None)

    restored = deserialize_project(json.dumps(data))

    assert restored.studio_project_schema_version == STUDIO_PROJECT_SCHEMA_VERSION
    assert restored.project_id is None
    assert restored.ks_project_id is None
    assert restored.ks_active is False
    assert restored.capabilities.knowledge_assist_enabled is False
    assert restored.suggestion_review_state == KSSuggestionReviewState()
    assert restored.evidence_links == []
    assert restored.manifest_revisions == []
    assert restored.conflict_resolutions == []
    assert restored.review_history == []


def test_snapshot_and_restore_preserve_ks_linkage_fields():
    session = _crud_session()
    session.project_id = "workspace-123"
    session.ks_project_id = "workspace-123"
    session.ks_active = True

    project = snapshot_session(session)
    restored = ProjectSession()
    restore_session(project, restored)

    assert project.project_id == "workspace-123"
    assert project.ks_project_id == "workspace-123"
    assert project.ks_active is False
    assert restored.project_id == "workspace-123"
    assert restored.ks_project_id == "workspace-123"
    assert restored.ks_active is False
    assert restored.capabilities.knowledge_assist_enabled is False


def test_snapshot_and_restore_preserve_placeholder_workspace_state():
    project = _project_with_ks_placeholders()
    session = ProjectSession()

    restore_session(project, session)
    round_tripped = snapshot_session(session)

    assert round_tripped.suggestion_review_state.accepted_ids == ["s-1"]
    assert round_tripped.evidence_links[0].suggestion_id == "s-1"
    assert round_tripped.manifest_revisions[0].revision_id == "rev-001"
    assert round_tripped.conflict_resolutions[0].resolution == "use-source-a"
    assert round_tripped.review_history[0].status == "accepted"


def test_applied_rule_suggestion_state_survives_snapshot_restore():
    session = _crud_session()
    session.capabilities.knowledge_assist_enabled = True
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            file_path="rules/account-business-rules.yaml",
            rules=[
                RuleEntry(
                    field="status",
                    type="allowed-values",
                    values=["ACTIVE", "SUSPENDED"],
                )
            ],
        )
    ]
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["r-1"]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="rules.Account.r-1",
            suggestion_id="r-1",
            provenance="ai-accepted",
        )
    ]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="r-1",
            type="rule",
            status="accepted",
            manifest_path="rules.Account.r-1",
            reviewed_at="2026-04-28T12:00:00+00:00",
        )
    ]

    project = snapshot_session(session)
    restored = ProjectSession()
    restore_session(project, restored)

    assert restored.entity_rules[0].rules[0].type == "allowed-values"
    assert restored.entity_rules[0].rules[0].values == ["ACTIVE", "SUSPENDED"]
    assert restored.ks_workspace_state.suggestion_review_state.accepted_ids == ["r-1"]
    assert restored.ks_workspace_state.evidence_links[0].provenance == "ai-accepted"
    assert restored.ks_workspace_state.review_history[0].type == "rule"


def test_snapshot_backfills_project_id_from_existing_ks_project_id():
    session = _crud_session()
    session.ks_project_id = "legacy-session-workspace"

    project = snapshot_session(session)

    assert project.project_id == "legacy-session-workspace"
    assert project.ks_project_id == "legacy-session-workspace"
    assert project.ks_active is False


def test_open_v1_0_project_restores_empty_ks_linkage_defaults():
    session = _crud_session()
    raw = serialize_project(snapshot_session(session))
    data = json.loads(raw)
    data["studio_project_schema_version"] = "1.0"
    data.pop("project_id", None)
    data.pop("ks_project_id", None)
    data.pop("ks_active", None)

    restored_project = deserialize_project(json.dumps(data))
    restored_session = ProjectSession(project_id="stale", ks_project_id="stale", ks_active=True)
    restore_session(restored_project, restored_session)

    assert restored_session.project_id is None
    assert restored_session.ks_project_id is None
    assert restored_session.ks_active is False


def test_project_open_clears_stale_review_posture_state():
    reset_session()
    try:
        session = get_session()
        session.review_approved = True
        raw = serialize_project(snapshot_session(_crud_session())).encode("utf-8")

        open_response = client.post(
            "/project/open",
            files={"project_file": ("studio-project.json", raw, "application/json")},
            follow_redirects=False,
        )

        assert open_response.status_code == 303
        assert get_session().review_approved is False
    finally:
        reset_session()


def test_project_open_rejects_oversized_upload_without_restoring_session(monkeypatch):
    reset_session()
    try:
        session = get_session()
        session.app_name = "Existing Studio Session"
        session.bounded_context = "existing"
        save_session(session)
        raw = serialize_project(snapshot_session(_crud_session())).encode("utf-8")
        monkeypatch.setenv("EDGEFORGE_STUDIO_MAX_UPLOAD_BYTES", str(len(raw) - 1))

        open_response = client.post(
            "/project/open",
            files={"project_file": ("studio-project.json", raw, "application/json")},
            follow_redirects=False,
        )

        assert open_response.status_code == 413
        assert f"Uploaded file exceeds the {len(raw) - 1} bytes limit." in open_response.text
        session = get_session()
        assert session.app_name == "Existing Studio Session"
        assert session.bounded_context == "existing"
    finally:
        reset_session()


def test_project_open_corrects_host_paths_in_docker(monkeypatch):
    from app.services.runtime_defaults import (
        DEFAULT_EDGEFORGE_PATH_ENV,
        DEFAULT_OUTPUT_PATH_ENV,
        DOCKER_MODE_ENV,
    )

    monkeypatch.setenv(DOCKER_MODE_ENV, "1")
    monkeypatch.delenv(DEFAULT_EDGEFORGE_PATH_ENV, raising=False)
    monkeypatch.delenv(DEFAULT_OUTPUT_PATH_ENV, raising=False)
    reset_session()
    try:
        original = _crud_session()
        original.appbuilder_repo_path = "/Users/example/Documents/GitHub/EdgeForge"
        original.output_path = "/Users/example/Documents/EdgeForgeGeneratedApps"
        original.last_export_path = "/Users/example/Documents/EdgeForgeGeneratedApps/old-export"
        raw = serialize_project(snapshot_session(original)).encode("utf-8")

        open_response = client.post(
            "/project/open",
            files={"project_file": ("studio-project.json", raw, "application/json")},
            follow_redirects=False,
        )

        assert open_response.status_code == 303
        assert open_response.headers["location"] == "/?project_notice=docker-paths-corrected"
        session = get_session()
        assert session.appbuilder_repo_path == "/workspace/EdgeForge"
        assert session.output_path == "/workspace/data/GeneratedApps"
        assert session.last_export_path is None
    finally:
        reset_session()


def test_project_open_then_save_preserves_placeholder_workspace_state():
    reset_session()
    try:
        raw = serialize_project(_project_with_ks_placeholders()).encode("utf-8")

        open_response = client.post(
            "/project/open",
            files={"project_file": ("studio-project.json", raw, "application/json")},
            follow_redirects=False,
        )

        assert open_response.status_code == 303
        session = get_session()
        assert session.ks_workspace_state.suggestion_review_state.accepted_ids == ["s-1"]
        assert session.ks_workspace_state.evidence_links[0].manifest_path == "entities.Account.fields.account_id"

        save_response = client.post("/project/save")

        assert save_response.status_code == 200
        saved_project = deserialize_project(save_response.text)
        assert saved_project.suggestion_review_state.accepted_ids == ["s-1"]
        assert saved_project.evidence_links[0].provenance == "ai-accepted"
        assert saved_project.manifest_revisions[0].revision_id == "rev-001"
        assert saved_project.conflict_resolutions[0].conflict_id == "c-1"
        assert saved_project.review_history[0].suggestion_id == "s-1"
    finally:
        reset_session()


def test_validation_hint_metadata_and_review_state_round_trip():
    session = _crud_session()
    session.capabilities.knowledge_assist_enabled = True
    session.classified_entities = [
        ClassifiedEntity(
            name="AccountResponse",
            canonical_name="Account",
            classification="entity",
            fields=[
                ClassifiedField(
                    name="accountNumber",
                    type="string",
                    max_length=14,
                    pattern="^[0-9]+$",
                )
            ],
        )
    ]
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(field="accountNumber", type="max-length", value="14"),
                RuleEntry(field="accountNumber", type="pattern", value="^[0-9]+$"),
            ],
            file_path="rules/account-business-rules.yaml",
        )
    ]
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["v-1"]
    session.ks_workspace_state.suggestion_review_state.rejected_ids = ["v-2"]
    session.ks_workspace_state.suggestion_review_state.edited_ids = ["v-3"]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="entities.Account.fields.accountNumber.validations.max-length",
            suggestion_id="v-1",
            provenance="ai-accepted",
        )
    ]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="v-1",
            type="validation",
            status="accepted",
            manifest_path="entities.Account.fields.accountNumber.validations.max-length",
            reviewed_at="2026-04-28T12:00:00+00:00",
            review_context={
                "entity": "Account",
                "field": "accountNumber",
                "validation_type": "max-length",
                "constraint_fingerprint": "max=14",
                "validation_fallback_key": (
                    "account|accountnumber|max-length|"
                    "entities.account.fields.accountnumber.validations.max-length|max=14"
                ),
            },
        ),
        KSReviewHistoryEntry(
            suggestion_id="v-2",
            type="validation",
            status="rejected",
            manifest_path="entities.Account.fields.accountNumber.validations.pattern",
            reviewed_at="2026-04-28T12:05:00+00:00",
            review_context={
                "entity": "Account",
                "field": "accountNumber",
                "validation_type": "pattern",
            },
        ),
        KSReviewHistoryEntry(
            suggestion_id="v-3",
            type="validation",
            status="edited",
            manifest_path="entities.Account.fields.accountNumber.validations.min-length",
            reviewed_at="2026-04-28T12:10:00+00:00",
            edited_payload={
                "entity": "Account",
                "field": "accountNumber",
                "validation_type": "min-length",
                "min": 8,
                "min_length": 8,
            },
            review_context={
                "entity": "Account",
                "field": "accountNumber",
                "validation_type": "min-length",
                "constraint_fingerprint": "min=8",
                "validation_fallback_key": (
                    "account|accountnumber|min-length|"
                    "entities.account.fields.accountnumber.validations.min-length|min=8"
                ),
            },
        ),
    ]

    project = deserialize_project(serialize_project(snapshot_session(session)))
    restored = ProjectSession()
    restore_session(project, restored)

    restored_field = restored.classified_entities[0].fields[0]
    assert restored_field.max_length == 14
    assert restored_field.pattern == "^[0-9]+$"
    assert [rule.type for rule in restored.entity_rules[0].rules] == ["max-length", "pattern"]
    assert restored.ks_workspace_state.suggestion_review_state.accepted_ids == ["v-1"]
    assert restored.ks_workspace_state.suggestion_review_state.rejected_ids == ["v-2"]
    assert restored.ks_workspace_state.suggestion_review_state.edited_ids == ["v-3"]
    assert [entry.status for entry in restored.ks_workspace_state.review_history] == [
        "accepted",
        "rejected",
        "edited",
    ]
    assert restored.ks_workspace_state.review_history[0].type == "validation"
    assert restored.ks_workspace_state.review_history[2].edited_payload["min"] == 8
    assert (
        restored.ks_workspace_state.review_history[2].review_context["validation_fallback_key"]
        == "account|accountnumber|min-length|entities.account.fields.accountnumber.validations.min-length|min=8"
    )
    assert restored.ks_workspace_state.evidence_links[0].manifest_path.endswith(".validations.max-length")


def test_project_save_route_stamps_brand_new_creator_metadata(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_USER", "route-saver")
    reset_session()
    try:
        session = get_session()
        session.app_name = "New App"
        session.bounded_context = "new-app"

        save_response = client.post("/project/save")
        saved_project = deserialize_project(save_response.text)

        assert save_response.status_code == 200
        assert saved_project.project_revision == 1
        assert saved_project.created_at
        assert saved_project.created_by == "route-saver"
        assert saved_project.modified_by == "route-saver"
        assert get_session().is_brand_new is False
    finally:
        reset_session()


def test_project_open_surfaces_saved_contract_reference_when_raw_spec_fields_are_empty():
    reset_session()
    try:
        project = snapshot_session(_crud_session()).model_copy(
            update={
                "raw_spec_content": None,
                "raw_spec_url": None,
                "raw_spec_filename": None,
                "upstream_interfaces": [
                    UpstreamInterface(
                        name="synthetic-account-api",
                        entity_name="Account",
                        spec="contracts/synthetic-account-api-spec.json",
                        spec_content='{"openapi":"3.0.0"}',
                    )
                ],
            }
        )
        raw = serialize_project(project).encode("utf-8")

        open_response = client.post(
            "/project/open",
            files={"project_file": ("studio-project.json", raw, "application/json")},
            follow_redirects=False,
        )

        assert open_response.status_code == 303

        upstream_response = client.get("/upstream")
        assert upstream_response.status_code == 200
        assert "Current Contract Source" in upstream_response.text
        assert "Uploaded file inputs stay blank after reopen" in upstream_response.text
        assert "contracts/synthetic-account-api-spec.json" in upstream_response.text
    finally:
        reset_session()


def test_project_open_hides_contract_source_summary_when_no_saved_reference_exists():
    reset_session()
    try:
        project = snapshot_session(_crud_session()).model_copy(
            update={
                "raw_spec_content": None,
                "raw_spec_url": None,
                "raw_spec_filename": None,
                "upstream_interfaces": [
                    UpstreamInterface(
                        name="manual-account-interface",
                        entity_name="Account",
                    )
                ],
            }
        )
        raw = serialize_project(project).encode("utf-8")

        open_response = client.post(
            "/project/open",
            files={"project_file": ("studio-project.json", raw, "application/json")},
            follow_redirects=False,
        )

        assert open_response.status_code == 303

        upstream_response = client.get("/upstream")
        assert upstream_response.status_code == 200
        assert "Current Contract Source" not in upstream_response.text
        assert "Uploaded file inputs stay blank after reopen" not in upstream_response.text
    finally:
        reset_session()


# ---------------------------------------------------------------------------
# Test 9 — Save → restore → manifest generation is unchanged
# ---------------------------------------------------------------------------


def test_save_restore_manifest_generation_unchanged():
    """Export behaviour is unchanged after a save/open cycle.

    Verifies that build_manifest_dict produces the same manifest from a
    restored session as it did from the original session, demonstrating that
    Save/Open does not alter downstream export behaviour.
    """
    original = _crud_session()
    manifest_before = build_manifest_dict(original)

    # Save → deserialise → restore
    raw = serialize_project(snapshot_session(original))
    restored = ProjectSession()
    restore_session(deserialize_project(raw), restored)

    manifest_after = build_manifest_dict(restored)

    # Core manifest fields must be identical
    for key in ("app_name", "bounded_context", "schema_version", "app_archetype", "target_profile"):
        assert manifest_before[key] == manifest_after[key], (
            f"Manifest field '{key}' changed after save/open cycle"
        )

    # Structural shape must match
    assert set(manifest_before.keys()) == set(manifest_after.keys())


def test_downstream_layout_lock_state_survives_save_open():
    original = _crud_session()
    original.downstream_interfaces[0].layout_fields = [
        LayoutField(name="account_id", start=1, length=12, locked_start=True),
        LayoutField(name="status", start=13, length=10, locked_start=False),
    ]

    raw = serialize_project(snapshot_session(original))
    restored = ProjectSession()
    restore_session(deserialize_project(raw), restored)

    fields = restored.downstream_interfaces[0].layout_fields
    assert fields[0].locked_start is True
    assert fields[1].locked_start is False
