"""Regression coverage for Knowledge Assist OFF wizard behavior."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    ClassifiedOperation,
    DataHandoff,
    DownstreamInterface,
    EntityRules,
    FieldMapping,
    KafkaConfig,
    KafkaRouteModel,
    KafkaRouteTransform,
    KafkaTopicPair,
    KafkaTransformRow,
    KSEvidenceLink,
    KSReviewHistoryEntry,
    OperationMapping,
    OperationSample,
    PassthroughFlow,
    PassthroughRouteRow,
    PassthroughTransform,
    ProjectSession,
    RuleEntry,
    UpstreamInterface,
)
from app.services.project_file_service import deserialize_project, restore_session, save_project
from tests.session_helpers import get_session, reset_session, save_session
from tests.test_package_writer import _full_session

client = TestClient(app)


PASSTHROUGH_SPEC = """
openapi: 3.0.0
info:
  title: Router API
  version: "1.0"
paths:
  /payments:
    post:
      operationId: routePayment
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                paymentType:
                  type: string
                amount:
                  type: string
      responses:
        "200":
          description: ok
"""


def _fail_if_called(label: str):
    def _raise(*_args, **_kwargs):
        raise AssertionError(f"{label} should not be called when Knowledge Assist is off")

    return _raise


def _patch_knowledge_assist_calls_to_fail(monkeypatch) -> None:
    """Make hidden KS/workspace side effects fail loudly in OFF-path tests."""
    fail_ks = _fail_if_called("ks_client")
    fail_identity = _fail_if_called("ensure_workspace_identity")
    fail_workspace_dir = _fail_if_called("workspace_dir")
    fail_summary = _fail_if_called("build_workspace_summary")

    monkeypatch.setattr("app.services.assist_service.ks_client", fail_ks)
    monkeypatch.setattr("app.routes.knowledge.ks_client", fail_ks)
    monkeypatch.setattr("app.routes.entities.ks_client", fail_ks)
    monkeypatch.setattr("app.services.evidence_trail.ks_client", fail_ks)

    monkeypatch.setattr("app.services.assist_service.ensure_workspace_identity", fail_identity)
    monkeypatch.setattr("app.routes.knowledge.ensure_workspace_identity", fail_identity)
    monkeypatch.setattr("app.routes.entities.ensure_workspace_identity", fail_identity)
    monkeypatch.setattr("app.routes.knowledge.workspace_dir", fail_workspace_dir)
    monkeypatch.setattr("app.routes.project.build_workspace_summary", fail_summary)


def _keep_assist_off(session) -> None:
    session.capabilities.knowledge_assist_enabled = False
    session.ks_active = False


def _add_dormant_workspace_history(session) -> None:
    session.project_id = "workspace-dormant-123"
    session.ks_project_id = "workspace-dormant-123"
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["s-1"]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="entities.Account.fields.status",
            suggestion_id="s-1",
            provenance="ai-accepted",
        )
    ]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="s-1",
            type="field",
            status="accepted",
            manifest_path="entities.Account.fields.status",
            reviewed_at="2026-04-20T00:00:00Z",
        )
    ]


def _seed_crud_session(*, dormant_workspace: bool = True) -> None:
    reset_session()
    session = get_session()
    session.app_name = "Accounts Studio"
    session.bounded_context = "accounts"
    session.app_archetype = "crud"
    session.target_profile = "springboot-legacy-compatible"
    session.raw_spec_content = '{"openapi":"3.0.0"}'
    session.classified_entities = [
        ClassifiedEntity(
            name="AccountRequest",
            canonical_name="Account",
            classification="entity",
            confidence="confirmed",
            fields=[
                ClassifiedField(name="accountId", type="string", is_id=True),
                ClassifiedField(name="status", type="string"),
                ClassifiedField(name="balance", type="decimal"),
            ],
        )
    ]
    session.classified_operations = [
        ClassifiedOperation(
            name="createAccount",
            method="POST",
            path="/accounts",
            resource="accounts",
            request_schema="AccountRequest",
            response_schema="AccountResponse",
            entity_candidates=["Account"],
            is_draft=False,
        )
    ]
    session.selected_entity_names = ["AccountRequest"]
    session.selected_operation_names = ["createAccount"]
    session.upstream_interfaces = [
        UpstreamInterface(
            name="accounts-account-api",
            type="rest-json",
            entity_name="Account",
            operations=[
                OperationSample(
                    name="createAccount",
                    request_sample_content='{"status":"OPEN","balance":100}',
                    response_sample_content='{"accountId":"A1","status":"OPEN"}',
                    request_sample_path="upstream/sample-create-account-request.json",
                    response_sample_path="upstream/sample-create-account-response.json",
                )
            ],
            operation_mappings=[
                OperationMapping(
                    name="createAccount",
                    request_mappings=[FieldMapping(source="status", target="Account.status")],
                    response_mappings=[FieldMapping(source="accountId", target="Account.accountId")],
                )
            ],
        )
    ]
    session.downstream_interfaces = [
        DownstreamInterface(
            name="ledger-file",
            type="file-fixed-width",
            entity_name="Account",
            field_mappings=[FieldMapping(source="Account.accountId", target="account_id")],
        )
    ]
    session.data_handoffs = [
        DataHandoff(
            name="account-staging",
            type="staging-table",
            entity_name="Account",
            ddl_content="CREATE TABLE account_staging (account_id VARCHAR(36));",
            field_mappings=[FieldMapping(source="Account.accountId", target="account_id")],
        )
    ]
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            file_path="rules/account-business-rules.yaml",
            rules=[
                RuleEntry(field="status", type="allowed-values", values=["OPEN", "CLOSED"]),
            ],
        )
    ]
    if dormant_workspace:
        _add_dormant_workspace_history(session)
    _keep_assist_off(session)
    save_session(session)


def _seed_passthrough_session() -> None:
    reset_session()
    session = get_session()
    session.app_name = "Payment Router"
    session.bounded_context = "payments"
    session.app_archetype = "passthrough-router"
    session.target_profile = "springboot-legacy-compatible"
    session.raw_spec_content = PASSTHROUGH_SPEC
    session.raw_spec_filename = "payments-router.yaml"
    session.passthrough_flow = PassthroughFlow(
        upstream_operation_name="routePayment",
        route_field="paymentType",
        routes=[PassthroughRouteRow(match="INSTANT", target="SCT")],
        default_target="SDD",
        transforms=[PassthroughTransform(source="amount", target="settlementAmount")],
    )
    _keep_assist_off(session)
    save_session(session)


def _seed_kafka_session() -> None:
    reset_session()
    session = get_session()
    session.app_name = "Payment Mediation"
    session.bounded_context = "payments"
    session.app_archetype = "kafka-integration"
    session.target_profile = "springboot-standard-enterprise"
    session.kafka_config = KafkaConfig(consumer_group="payment-mediation-group")
    session.kafka_topic_pairs = [
        KafkaTopicPair(
            route_name="payment-posted",
            upstream_topic="payments.posted.v1",
            upstream_schema_content='{"type":"object","properties":{"paymentId":{"type":"string"}}}',
            downstream_topic="ledger.entries.v1",
            downstream_schema_content='{"type":"object","properties":{"ledgerId":{"type":"string"}}}',
        )
    ]
    session.kafka_route_models = [
        KafkaRouteModel(route_name="payment-posted", pattern="fire-and-forget")
    ]
    session.kafka_route_transforms = [
        KafkaRouteTransform(
            route_name="payment-posted",
            mappings=[KafkaTransformRow(source_field="paymentId", target_field="ledgerId")],
        )
    ]
    _keep_assist_off(session)
    save_session(session)


def _assert_common_wizard_no_assist_leaks(html: str) -> None:
    assert "Open Knowledge Workspace" not in html
    assert "KS Status" not in html
    assert "Knowledge Server unavailable" not in html
    assert "Knowledge Workspace field guidance" not in html
    assert "advisory signals compare your current CRUD model with live Knowledge Workspace" not in html
    assert "data-suggestion-drawer-open" not in html
    assert "ka-suggestion-badge" not in html
    assert "ka-suggestion-drawer" not in html


def _assert_step3_assist_panel_hidden(html: str) -> None:
    assert "Knowledge Assist Field Suggestions" not in html
    assert "Fetching suggestions" not in html
    assert "Open Knowledge Assist workspace" not in html
    assert ">Suggestions</h4>" not in html
    assert "CRUD field suggestions and evidence" not in html
    assert "Right rail: collapsed for this step" in html


def _assert_step6_assist_advisory_hidden(html: str) -> None:
    assert "Knowledge Assist field guidance" not in html
    assert "enabled Knowledge Assist guidance" not in html
    assert "Manual rules authoring remains available without live advisory conflict data." in html


def _assert_step7_assist_provenance_hidden(html: str) -> None:
    assert "Knowledge Assist is off" not in html
    assert "Knowledge Assist Provenance" not in html
    assert "Knowledge Assist Field Review" not in html
    assert "Evidence Coverage" not in html
    assert "Knowledge Assist field review entries" not in html
    assert "Dormant workspace history" not in html
    assert "Completeness" in html


def _assert_session_stayed_off() -> None:
    session = get_session()
    assert session.capabilities.knowledge_assist_enabled is False
    assert session.ks_active is False


def test_fresh_step1_defaults_knowledge_assist_off_without_workspace_fetch(monkeypatch) -> None:
    _patch_knowledge_assist_calls_to_fail(monkeypatch)
    reset_session()

    response = client.get("/")

    assert response.status_code == 200
    assert "Knowledge Assist is off" in response.text
    assert "Open Knowledge Workspace" not in response.text
    assert "KS Status" not in response.text
    _assert_session_stayed_off()


def test_crud_wizard_routes_render_without_ks_calls_when_assist_off(monkeypatch) -> None:
    _patch_knowledge_assist_calls_to_fail(monkeypatch)
    _seed_crud_session(dormant_workspace=True)

    route_expectations = {
        "/upstream": "Upstream Contract",
        "/entities": "Step 3: Entity Model",
        "/downstream": "Downstream",
        "/handoffs": "Data Handoffs",
        "/rules": "Business Rules",
        "/review": "Review Checkpoint",
        "/export": "Export Package",
    }
    for route, expected in route_expectations.items():
        response = client.get(route)
        assert response.status_code == 200, route
        assert expected in response.text
        _assert_common_wizard_no_assist_leaks(response.text)
        _assert_session_stayed_off()

        if route == "/upstream":
            assert "Add Upstream Edge Contract" in response.text
            assert "Select contract type..." in response.text
            assert "Enter the package-relative artifact path and optionally paste reviewed content." in response.text
            assert "Canonical mapping" in response.text
            assert "This maps parsed file/XML fields to canonical metadata." in response.text
            assert "Inspect artifact" in response.text
            assert "Inspection reads pasted artifact content to help select contract metadata." in response.text
            assert "Save Contract Reference" in response.text
            assert "Knowledge Assist" not in response.text or "Knowledge Assist is off" in response.text
        if route == "/downstream":
            assert 'data-uxr-board="downstream"' in response.text
            assert "Select contract type..." in response.text
            assert "Inspect artifact" in response.text
            assert "Canonical entity link (optional)" in response.text
            assert "uploaded artifact content" not in response.text
            assert "Knowledge Assist" not in response.text
        if route == "/entities":
            _assert_step3_assist_panel_hidden(response.text)
            assert "Identity Role Lens" in response.text
            assert "data-field=\"accountId\"" in response.text
        elif route == "/rules":
            _assert_step6_assist_advisory_hidden(response.text)
        elif route == "/review":
            _assert_step7_assist_provenance_hidden(response.text)


def test_crud_step3_page_badges_do_not_spawn_ks_when_assist_off(monkeypatch) -> None:
    spawn_count = 0

    @contextmanager
    def fake_ks_client(**kwargs):
        nonlocal spawn_count
        spawn_count += 1
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)
    _seed_crud_session(dormant_workspace=True)

    response = client.get("/entities")

    assert response.status_code == 200
    _assert_common_wizard_no_assist_leaks(response.text)
    _assert_step3_assist_panel_hidden(response.text)
    assert spawn_count == 0
    _assert_session_stayed_off()


def test_crud_step6_rule_badges_do_not_spawn_ks_when_assist_off(monkeypatch) -> None:
    spawn_count = 0

    @contextmanager
    def fake_ks_client(**kwargs):
        nonlocal spawn_count
        spawn_count += 1
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)
    _seed_crud_session(dormant_workspace=True)

    response = client.get("/rules")

    assert response.status_code == 200
    _assert_common_wizard_no_assist_leaks(response.text)
    _assert_step6_assist_advisory_hidden(response.text)
    assert "rule suggestions" not in response.text
    assert spawn_count == 0
    _assert_session_stayed_off()


def test_crud_step3_json_suggestions_return_empty_without_ks_calls_when_assist_off(monkeypatch) -> None:
    _patch_knowledge_assist_calls_to_fail(monkeypatch)
    _seed_crud_session(dormant_workspace=True)

    response = client.get("/entities/ks/suggestions", params={"entity": "Account"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["suggestions"] == []
    assert payload["empty"] is True
    assert "off or unavailable" in payload["empty_reason"]
    _assert_session_stayed_off()


def test_crud_step3_full_review_returns_empty_without_ks_calls_when_assist_off(monkeypatch) -> None:
    _patch_knowledge_assist_calls_to_fail(monkeypatch)
    _seed_crud_session(dormant_workspace=True)

    response = client.get("/entities/ks/full-review")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["entities"] == []
    assert payload["warnings"] == []
    _assert_session_stayed_off()


def test_crud_step3_validation_review_rejects_without_ks_calls_when_assist_off(monkeypatch) -> None:
    _patch_knowledge_assist_calls_to_fail(monkeypatch)
    _seed_crud_session(dormant_workspace=True)

    response = client.post(
        "/entities/ks/validation-review",
        json={
            "decisions": [
                {
                    "suggestion_id": "v-1",
                    "suggestion_type": "validation",
                    "status": "accepted",
                    "entity": "Account",
                    "payload": {"field": "status", "validation_type": "not_null"},
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "Knowledge Assist is off" in response.json()["errors"][0]
    _assert_session_stayed_off()


def test_step7_conflict_review_rejects_without_ks_calls_when_assist_off(monkeypatch) -> None:
    _patch_knowledge_assist_calls_to_fail(monkeypatch)
    _seed_crud_session(dormant_workspace=True)

    response = client.post(
        "/review/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "c-1",
                    "suggestion_type": "conflict_resolution",
                    "status": "accepted",
                    "payload": {"conflict_query": "Account.status"},
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "Knowledge Assist is off" in response.json()["message"]
    _assert_session_stayed_off()


def test_step7_portfolio_review_rejects_without_ks_calls_when_assist_off(monkeypatch) -> None:
    _patch_knowledge_assist_calls_to_fail(monkeypatch)
    _seed_crud_session(dormant_workspace=True)

    response = client.post(
        "/review/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "p-1",
                    "suggestion_type": "portfolio_reuse",
                    "status": "accepted",
                    "payload": {"portfolio_query": "Accounts Studio"},
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "Knowledge Assist is off" in response.json()["message"]
    _assert_session_stayed_off()


def test_passthrough_wizard_routes_render_without_ks_calls_when_assist_off(monkeypatch) -> None:
    _patch_knowledge_assist_calls_to_fail(monkeypatch)
    _seed_passthrough_session()

    route_expectations = {
        "/upstream": "Upstream Contract",
        "/passthrough": "Passthrough",
        "/rules": "Rules",
        "/review": "Review Checkpoint",
        "/export": "Export Package",
    }
    for route, expected in route_expectations.items():
        response = client.get(route)
        assert response.status_code == 200, route
        assert expected in response.text
        _assert_common_wizard_no_assist_leaks(response.text)
        _assert_session_stayed_off()

    rules_response = client.get("/rules")
    assert "No active advisory conflict surface is enabled for this step." in rules_response.text


def test_passthrough_mapping_drawer_returns_empty_without_ks_calls_when_assist_off(monkeypatch) -> None:
    _patch_knowledge_assist_calls_to_fail(monkeypatch)
    _seed_passthrough_session()

    response = client.get("/passthrough/ks/drawer", params={"scope": "mappings", "route_name": "routePayment"})

    assert response.status_code == 200
    assert response.json()["empty"] is True
    _assert_session_stayed_off()


def test_passthrough_mapping_review_rejects_without_ks_calls_when_assist_off(monkeypatch) -> None:
    _patch_knowledge_assist_calls_to_fail(monkeypatch)
    _seed_passthrough_session()

    response = client.post(
        "/passthrough/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "m-1",
                    "suggestion_type": "mapping",
                    "status": "accepted",
                    "payload": {
                        "route_name": "routePayment",
                        "direction": "request",
                        "source_entity": "Router API",
                        "target_entity": "Downstream",
                        "source_field": "amount",
                        "target_field": "settlementAmount",
                    },
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "Knowledge Assist is off" in response.json()["errors"][0]
    _assert_session_stayed_off()


def test_kafka_wizard_routes_render_without_ks_calls_when_assist_off(monkeypatch) -> None:
    _patch_knowledge_assist_calls_to_fail(monkeypatch)
    _seed_kafka_session()

    route_expectations = {
        "/kafka/topics": "Topic Ingest",
        "/kafka/routes": "Route Model",
        "/kafka/transforms": "Transform Mappings",
        "/rules": "Kafka integration keeps this step",
        "/review": "Review Checkpoint",
        "/export": "Export Package",
    }
    for route, expected in route_expectations.items():
        response = client.get(route)
        assert response.status_code == 200, route
        assert expected in response.text
        _assert_common_wizard_no_assist_leaks(response.text)
        _assert_session_stayed_off()

    rules_response = client.get("/rules")
    assert "No active advisory conflict surface is enabled for this step." in rules_response.text


def test_kafka_mapping_drawer_returns_empty_without_ks_calls_when_assist_off(monkeypatch) -> None:
    _patch_knowledge_assist_calls_to_fail(monkeypatch)
    _seed_kafka_session()

    response = client.get("/kafka/ks/drawer", params={"scope": "mappings", "route_name": "payment-posted"})

    assert response.status_code == 200
    assert response.json()["empty"] is True
    _assert_session_stayed_off()


def test_kafka_transform_drawer_returns_empty_without_ks_calls_when_assist_off(monkeypatch) -> None:
    _patch_knowledge_assist_calls_to_fail(monkeypatch)
    _seed_kafka_session()

    response = client.get(
        "/kafka/ks/drawer",
        params={
            "scope": "transforms",
            "route_name": "payment-posted",
            "target_id": "ledger-core",
            "direction": "request",
        },
    )

    assert response.status_code == 200
    assert response.json()["empty"] is True
    _assert_session_stayed_off()


def test_kafka_mapping_review_rejects_without_ks_calls_when_assist_off(monkeypatch) -> None:
    _patch_knowledge_assist_calls_to_fail(monkeypatch)
    _seed_kafka_session()

    response = client.post(
        "/kafka/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": "m-1",
                    "suggestion_type": "mapping",
                    "status": "accepted",
                    "payload": {
                        "route_name": "payment-posted",
                        "direction": "request",
                        "source_entity": "payment-posted-upstream",
                        "target_entity": "payment-posted-downstream",
                        "source_field": "paymentId",
                        "target_field": "ledgerId",
                    },
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "Knowledge Assist is off" in response.json()["errors"][0]
    _assert_session_stayed_off()


def test_kafka_transform_review_rejects_without_ks_calls_when_assist_off(monkeypatch) -> None:
    _patch_knowledge_assist_calls_to_fail(monkeypatch)
    _seed_kafka_session()

    response = client.post(
        "/kafka/ks/transform-review",
        json={
            "decisions": [
                {
                    "suggestion_id": "t-1",
                    "suggestion_type": "transform",
                    "status": "accepted",
                    "payload": {
                        "route_name": "payment-posted",
                        "target_id": "ledger-core",
                        "direction": "request",
                        "source": "paymentId",
                        "target": "transactionId",
                    },
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "Knowledge Assist is off" in response.json()["errors"][0]
    _assert_session_stayed_off()


def test_knowledge_workspace_off_redirect_does_not_mint_or_activate(monkeypatch) -> None:
    _patch_knowledge_assist_calls_to_fail(monkeypatch)
    reset_session()

    response = client.get("/knowledge", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/?assist_notice=knowledge-off"
    session = get_session()
    assert session.capabilities.knowledge_assist_enabled is False
    assert session.ks_active is False
    assert session.project_id is None
    assert session.ks_project_id is None


def test_knowledge_upload_off_redirect_does_not_write_or_activate(monkeypatch) -> None:
    _patch_knowledge_assist_calls_to_fail(monkeypatch)
    reset_session()

    response = client.post(
        "/knowledge/upload",
        files={"document_file": ("requirements.md", b"# Requirements", "text/markdown")},
        data={"description": "test upload"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/?assist_notice=knowledge-off"
    session = get_session()
    assert session.capabilities.knowledge_assist_enabled is False
    assert session.ks_active is False
    assert session.project_id is None
    assert session.ks_project_id is None


def test_save_open_round_trip_preserves_knowledge_assist_off_and_dormant_state(tmp_path: Path) -> None:
    _seed_crud_session(dormant_workspace=True)
    session = get_session()
    path = tmp_path / "ka-off-project.json"

    saved_project = save_project(session, path)
    restored_project = deserialize_project(path.read_text(encoding="utf-8"))
    restored_session = ProjectSession()
    restore_session(restored_project, restored_session)

    assert saved_project.capabilities.knowledge_assist_enabled is False
    assert saved_project.ks_active is False
    assert restored_session.capabilities.knowledge_assist_enabled is False
    assert restored_session.ks_active is False
    assert restored_session.ks_project_id == "workspace-dormant-123"
    assert restored_session.project_id == "workspace-dormant-123"
    assert len(restored_session.ks_workspace_state.evidence_links) == 1
    assert restored_session.app_name == "Accounts Studio"
    assert restored_session.entity_rules[0].rules[0].field == "status"


def test_export_write_with_dormant_evidence_links_does_not_call_ks_when_assist_off(monkeypatch, tmp_path: Path) -> None:
    _patch_knowledge_assist_calls_to_fail(monkeypatch)
    session = _full_session()
    session.output_path = str(tmp_path)
    _add_dormant_workspace_history(session)
    _keep_assist_off(session)
    save_session(session)

    response = client.post("/export/write")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    sidecar_text = (Path(payload["output_dir"]) / "evidence-trail.json").read_text(encoding="utf-8")
    sidecar = json.loads(sidecar_text)
    # KA OFF: the dormant Knowledge Assist evidence link must NOT be expanded
    # (no KS call); only deterministic human-authored file-contract evidence may
    # appear. The dormant suggestion id must be absent from the sidecar.
    assert all(link["provenance"] == "human-authored" for link in sidecar["evidence_links"])
    assert "s-1" not in sidecar_text
    assert sidecar["provenance_summary"]["ai_accepted"] == 0
    _assert_session_stayed_off()
