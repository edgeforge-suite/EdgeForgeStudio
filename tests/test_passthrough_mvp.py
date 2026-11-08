"""Focused tests for the minimal Studio passthrough-router MVP."""

from contextlib import contextmanager
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.main import app
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)


UPSTREAM_SPEC = """
openapi: 3.0.0
info:
  title: Internal Payment API
  version: "1.0"
paths:
  /payments:
    post:
      operationId: routePayment
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/InternalPaymentRequest'
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/InternalPaymentResponse'
components:
  schemas:
    InternalPaymentRequest:
      type: object
      properties:
        paymentType:
          type: string
        amount:
          type: string
        currency:
          type: string
        remittanceInfo:
          type: string
      required: [paymentType, amount, currency]
    InternalPaymentResponse:
      type: object
      properties:
        status:
          type: string
"""

SCT_SPEC = """
openapi: 3.0.0
info:
  title: SCT API
  version: "1.0"
paths:
  /sct/payments:
    post:
      operationId: sendSctPayment
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/SctPaymentRequest'
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/SctPaymentResponse'
components:
  schemas:
    SctPaymentRequest:
      type: object
      properties:
        settlementAmount:
          type: string
        settlementCurrency:
          type: string
        paymentReference:
          type: string
    SctPaymentResponse:
      type: object
      properties:
        status:
          type: string
"""

SDD_SPEC = """
openapi: 3.0.0
info:
  title: SDD API
  version: "1.0"
paths:
  /sdd/payments:
    post:
      operationId: sendSddPayment
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/SddPaymentRequest'
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/SddPaymentResponse'
components:
  schemas:
    SddPaymentRequest:
      type: object
      properties:
        settlementAmount:
          type: string
        settlementCurrency:
          type: string
        paymentReference:
          type: string
    SddPaymentResponse:
      type: object
      properties:
        status:
          type: string
"""


def _seed_passthrough_session(tmp_path: Path):
    reset_session()
    session = get_session()
    session.app_name = "SEPA Router"
    session.bounded_context = "payments"
    session.app_archetype = "passthrough-router"
    session.target_profile = "springboot-legacy-compatible"
    session.output_path = str(tmp_path)
    session.raw_spec_content = UPSTREAM_SPEC
    session.raw_spec_filename = "internal-payment-openapi.yaml"
    save_session(session)


def _save_valid_passthrough_flow() -> None:
    response = client.post("/passthrough/save", json={
        "upstream_operation_name": "routePayment",
        "downstream_targets": [
            {
                "name": "sct-api",
                "system": "SCT",
                "source_mode": "text",
                "spec_content": SCT_SPEC,
                "selected_operation_name": "sendSctPayment",
            },
        ],
        "route_field": "paymentType",
        "routes": [{"match": "INSTANT", "target": "SCT"}],
        "default_target": "SCT",
        "transforms": [
            {"source": "amount", "target": "settlementAmount"},
        ],
    })
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_step1_can_select_passthrough_archetype():
    reset_session()
    response = client.post("/", data={
        "app_name": "Router",
        "bounded_context": "payments",
        "app_archetype": "passthrough-router",
        "target_profile": "springboot-legacy-compatible",
        "output_path": "",
        "appbuilder_repo_path": "",
    }, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/upstream"
    assert get_session().app_archetype == "passthrough-router"
    reset_session()


def test_upstream_next_branches_by_archetype():
    reset_session()
    session = get_session()
    session.app_archetype = "passthrough-router"
    save_session(session)

    response = client.get("/upstream/next", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/passthrough"

    session.app_archetype = "crud"
    save_session(session)
    response = client.get("/upstream/next", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/entities"
    reset_session()


def test_passthrough_save_and_export_package(tmp_path):
    _seed_passthrough_session(tmp_path)

    save_response = client.post("/passthrough/save", json={
        "upstream_operation_name": "routePayment",
        "downstream_targets": [
            {
                "name": "sct-api",
                "system": "SCT",
                "source_mode": "text",
                "spec_content": SCT_SPEC,
                "selected_operation_name": "sendSctPayment",
            },
            {
                "name": "sdd-api",
                "system": "SDD",
                "source_mode": "text",
                "spec_content": SDD_SPEC,
                "selected_operation_name": "sendSddPayment",
            },
        ],
        "route_field": "paymentType",
        "routes": [{"match": "INSTANT", "target": "SCT"}],
        "default_target": "SDD",
        "transforms": [
            {"source": "amount", "target": "settlementAmount"},
            {"source": "currency", "target": "settlementCurrency"},
            {"source": "remittanceInfo", "target": "paymentReference", "default": "UNSTRUCTURED"},
        ],
    })

    assert save_response.status_code == 200
    assert save_response.json()["ok"] is True

    export_response = client.post("/export/write")
    assert export_response.status_code == 200
    payload = export_response.json()
    assert payload["ok"] is True

    project_dir = Path(payload["output_dir"])
    manifest = yaml.safe_load((project_dir / "app-definition.yaml").read_text())
    assert manifest["app_archetype"] == "passthrough-router"
    assert manifest["upstream_interfaces"][0]["name"] == "payments-router-upstream-api"
    assert len(manifest["downstream_interfaces"]) == 2
    assert manifest["rules"] == ["rules/payments-passthrough-routing.yaml"]
    assert "data_handoffs" not in manifest

    upstream_spec = yaml.safe_load((project_dir / "upstream/internal-payment-openapi.yaml").read_text())
    assert list(upstream_spec["paths"].keys()) == ["/payments"]
    assert list(upstream_spec["paths"]["/payments"].keys()) == ["post"]

    sct_spec = yaml.safe_load((project_dir / "downstream/sct-api-openapi.yaml").read_text())
    assert list(sct_spec["paths"].keys()) == ["/sct/payments"]
    assert list(sct_spec["paths"]["/sct/payments"].keys()) == ["post"]

    rules = yaml.safe_load((project_dir / "rules/payments-passthrough-routing.yaml").read_text())
    assert rules["routing_rules"]["route_field"] == "paymentType"
    assert rules["routing_rules"]["default_target"] == "SDD"
    assert rules["transforms"][0]["source"] == "amount"
    assert rules["transforms"][0]["target"] == "settlementAmount"

    reset_session()


def test_passthrough_mapping_badge_hidden_when_knowledge_assist_off(tmp_path, monkeypatch):
    _seed_passthrough_session(tmp_path)
    _save_valid_passthrough_flow()
    session = get_session()
    session.capabilities.knowledge_assist_enabled = False
    save_session(session)

    @contextmanager
    def fake_ks_client(**kwargs):
        raise AssertionError("ks_client should not be called when Knowledge Assist is off")
        yield

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/passthrough")

    assert response.status_code == 200
    assert "mapping suggestion" not in response.text
    assert "data-suggestion-drawer-open" not in response.text
    reset_session()


def test_passthrough_mapping_drawer_uses_generated_change_taxonomy() -> None:
    js = Path("app/static/js/studio.js").read_text(encoding="utf-8")

    assert "Applies generated change" in js
    assert "ka-category-generated ka-taxonomy-change" in js
    assert "'mappings'" in js


def test_passthrough_renders_mapping_badge_and_drawer_rows(tmp_path, monkeypatch):
    _seed_passthrough_session(tmp_path)
    _save_valid_passthrough_flow()
    session = get_session()
    session.capabilities.knowledge_assist_enabled = True
    save_session(session)
    calls: list[tuple[str, str | None, str | None, str | None, str | None]] = []

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            route_name: str | None = None,
            direction: str | None = None,
            source_entity: str | None = None,
            target_entity: str | None = None,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            calls.append((scope, route_name, direction, source_entity, target_entity))
            return {
                "scope": scope,
                "suggestions": [
                    {
                        "suggestion_id": "m-1",
                        "suggestion_type": "mapping",
                        "payload": {
                            "source_field": "amount",
                            "target_field": "settlementAmount",
                        },
                        "summary": "Amount maps to settlement amount.",
                        "citation_count": 2,
                    }
                ],
                "suggestion_count": 1,
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)

    response = client.get("/passthrough")
    drawer = client.get("/passthrough/ks/drawer?scope=mappings&route_name=routePayment")

    assert response.status_code == 200
    assert "1 mapping suggestion" in response.text
    assert "/passthrough/ks/drawer?scope=mappings&amp;route_name=routePayment" in response.text
    assert drawer.status_code == 200
    payload = drawer.json()
    assert payload["ok"] is True
    assert payload["scope"] == "mappings"
    assert payload["scopes"][0]["rows"][0]["suggestion_id"] == "m-1"
    assert payload["scopes"][0]["rows"][0]["title"] == "amount → settlementAmount"
    row_payload = payload["scopes"][0]["rows"][0]["payload"]
    assert row_payload["route_name"] == "routePayment"
    assert row_payload["direction"] == "request"
    assert row_payload["source_entity"] == "InternalPaymentRequest"
    assert row_payload["target_entity"] == "SctPaymentRequest"
    assert calls == [
        ("mappings", "routePayment", "request", "InternalPaymentRequest", "SctPaymentRequest"),
        ("mappings", "routePayment", "request", "InternalPaymentRequest", "SctPaymentRequest"),
    ]
    reset_session()


def test_passthrough_mapping_review_posts_actual_drawer_row_payload(tmp_path, monkeypatch):
    _seed_passthrough_session(tmp_path)
    _save_valid_passthrough_flow()
    session = get_session()
    session.capabilities.knowledge_assist_enabled = True
    save_session(session)
    submitted: list[list[dict]] = []

    class FakeClient:
        def suggest_manifest_candidates(
            self,
            project_id: str,
            scope: str,
            route_name: str | None = None,
            direction: str | None = None,
            source_entity: str | None = None,
            target_entity: str | None = None,
            min_source_count: int = 1,
            max_suggestions: int = 50,
        ):
            return {
                "scope": scope,
                "suggestions": [
                    {
                        "suggestion_id": "m-drawer-edit",
                        "suggestion_type": "mapping",
                        "payload": {
                            "source_field": "amount",
                            "target_field": "settlementAmount",
                            "mapping_type": "copy",
                        },
                        "summary": "Amount maps to settlement amount.",
                        "confidence_basis": "Matched by field catalog name and compatible type.",
                        "citation_count": 2,
                    }
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    def fake_submit(session, *, decisions: list[dict]):
        submitted.append(decisions)
        return {"success": True, "outcomes": [{"suggestion_id": "m-drawer-edit", "success": True}]}

    monkeypatch.setattr("app.services.assist_service.ks_client", fake_ks_client)
    monkeypatch.setattr(
        "app.routes.passthrough.assist_service.submit_mapping_suggestion_decisions",
        fake_submit,
    )

    drawer = client.get("/passthrough/ks/drawer?scope=mappings&route_name=routePayment")
    row = drawer.json()["scopes"][0]["rows"][0]
    response = client.post(
        "/passthrough/ks/review",
        json={
            "decisions": [
                {
                    "suggestion_id": row["suggestion_id"],
                    "suggestion_type": row["suggestion_type"],
                    "status": "edited",
                    "manifest_path": row.get("manifest_path") or "",
                    "payload": row["payload"],
                    "edited_payload": {
                        "source_field": "remittanceInfo",
                        "target_field": "paymentReference",
                    },
                }
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["partial_failure"] is False
    assert payload["saved_count"] == 1
    assert payload["applied_count"] == 1
    expected_edited_payload = {
        "route_name": "routePayment",
        "direction": "request",
        "source_entity": "InternalPaymentRequest",
        "target_entity": "SctPaymentRequest",
        "source_field": "remittanceInfo",
        "target_field": "paymentReference",
        "mapping_type": "copy",
        "confidence_basis": "Matched by field catalog name and compatible type.",
    }
    assert submitted == [
        [
            {
                "suggestion_id": "m-drawer-edit",
                "status": "edited",
                "edited_payload": expected_edited_payload,
            }
        ]
    ]
    session = get_session()
    assert any(
        transform.source == "remittanceInfo" and transform.target == "paymentReference"
        for transform in session.passthrough_flow.transforms
    )
    assert session.ks_workspace_state.review_history[-1].edited_payload == expected_edited_payload
    reset_session()


def _passthrough_mapping_decision(
    suggestion_id: str,
    status: str,
    *,
    source: str = "currency",
    target: str = "settlementCurrency",
    edited_payload: dict | None = None,
    mapping_type: str = "copy",
) -> dict:
    decision = {
        "suggestion_id": suggestion_id,
        "suggestion_type": "mapping",
        "status": status,
        "manifest_path": f"passthrough.routePayment.transforms.{target}",
    }
    decision["payload"] = {
        "route_name": "routePayment",
        "direction": "request",
        "source_entity": "InternalPaymentRequest",
        "target_entity": "SctPaymentRequest",
        "source_field": source,
        "target_field": target,
        "mapping_type": mapping_type,
        "confidence_basis": "Matched by field catalog name and compatible type.",
    }
    if edited_payload is not None:
        decision["edited_payload"] = edited_payload
    return decision


def _enable_passthrough_mapping_reviews(tmp_path, monkeypatch):
    _seed_passthrough_session(tmp_path)
    _save_valid_passthrough_flow()
    session = get_session()
    session.capabilities.knowledge_assist_enabled = True
    save_session(session)
    submitted: list[list[dict]] = []

    def fake_submit(session, *, decisions: list[dict]):
        submitted.append(decisions)
        return {
            "success": True,
            "outcomes": [
                {"suggestion_id": decision["suggestion_id"], "success": True}
                for decision in decisions
            ],
        }

    monkeypatch.setattr(
        "app.routes.passthrough.assist_service.submit_mapping_suggestion_decisions",
        fake_submit,
    )
    return submitted


def test_passthrough_mapping_review_accept_applies_transform(tmp_path, monkeypatch):
    submitted = _enable_passthrough_mapping_reviews(tmp_path, monkeypatch)

    response = client.post(
        "/passthrough/ks/review",
        json={"decisions": [_passthrough_mapping_decision("m-accept", "accepted")]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["applied_count"] == 1
    session = get_session()
    assert any(
        transform.source == "currency" and transform.target == "settlementCurrency"
        for transform in session.passthrough_flow.transforms
    )
    assert session.ks_workspace_state.suggestion_review_state.accepted_ids == ["m-accept"]
    assert session.ks_workspace_state.review_history[-1].type == "mapping"
    assert session.ks_workspace_state.review_history[-1].review_context == {
        "mapping_context": "passthrough",
        "route_name": "routePayment",
        "direction": "request",
        "source_entity": "InternalPaymentRequest",
        "target_entity": "SctPaymentRequest",
        "source_field": "currency",
        "target_field": "settlementCurrency",
    }
    assert session.ks_workspace_state.evidence_links == []
    assert submitted == [[{"suggestion_id": "m-accept", "status": "accepted"}]]
    reset_session()


def test_passthrough_mapping_review_edit_applies_edited_payload(tmp_path, monkeypatch):
    submitted = _enable_passthrough_mapping_reviews(tmp_path, monkeypatch)
    edited = {
        "source_field": "remittanceInfo",
        "target_field": "paymentReference",
    }

    response = client.post(
        "/passthrough/ks/review",
        json={"decisions": [_passthrough_mapping_decision("m-edit", "edited", edited_payload=edited)]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["partial_failure"] is False
    assert payload["saved_count"] == 1
    assert payload["applied_count"] == 1
    session = get_session()
    assert any(
        transform.source == "remittanceInfo" and transform.target == "paymentReference"
        for transform in session.passthrough_flow.transforms
    )
    assert session.ks_workspace_state.suggestion_review_state.edited_ids == ["m-edit"]
    expected_edited_payload = {
        "route_name": "routePayment",
        "direction": "request",
        "source_entity": "InternalPaymentRequest",
        "target_entity": "SctPaymentRequest",
        "source_field": "remittanceInfo",
        "target_field": "paymentReference",
        "mapping_type": "copy",
        "confidence_basis": "Matched by field catalog name and compatible type.",
    }
    assert session.ks_workspace_state.review_history[-1].edited_payload == expected_edited_payload
    assert session.ks_workspace_state.review_history[-1].review_context == {
        "mapping_context": "passthrough",
        "route_name": "routePayment",
        "direction": "request",
        "source_entity": "InternalPaymentRequest",
        "target_entity": "SctPaymentRequest",
        "source_field": "remittanceInfo",
        "target_field": "paymentReference",
    }
    assert session.ks_workspace_state.review_history[-1].manifest_path == (
        "passthrough.routePayment.transforms.remittanceInfo.paymentReference"
    )
    assert "settlementCurrency" not in session.ks_workspace_state.review_history[-1].manifest_path
    assert submitted == [[{"suggestion_id": "m-edit", "status": "edited", "edited_payload": expected_edited_payload}]]
    reset_session()


def test_passthrough_mapping_review_edit_accepts_source_target_aliases(tmp_path, monkeypatch):
    submitted = _enable_passthrough_mapping_reviews(tmp_path, monkeypatch)
    edited = {
        "source": "remittanceInfo",
        "target": "paymentReference",
    }

    response = client.post(
        "/passthrough/ks/review",
        json={"decisions": [_passthrough_mapping_decision("m-edit-alias", "edited", edited_payload=edited)]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["applied_count"] == 1
    session = get_session()
    assert any(
        transform.source == "remittanceInfo" and transform.target == "paymentReference"
        for transform in session.passthrough_flow.transforms
    )
    assert submitted[0][0]["edited_payload"]["source_field"] == "remittanceInfo"
    assert submitted[0][0]["edited_payload"]["target_field"] == "paymentReference"
    reset_session()


def test_passthrough_mapping_review_surfaces_ks_failed_outcome(tmp_path, monkeypatch):
    _seed_passthrough_session(tmp_path)
    _save_valid_passthrough_flow()
    session = get_session()
    session.capabilities.knowledge_assist_enabled = True
    save_session(session)

    def fake_submit(session, *, decisions: list[dict]):
        return {
            "success": False,
            "outcomes": [
                {
                    "suggestion_id": "m-edit-fail",
                    "success": False,
                    "error": "edited_payload.confidence_basis is required.",
                    "warnings": ["KS stored no decision for this suggestion."],
                }
            ],
        }

    monkeypatch.setattr(
        "app.routes.passthrough.assist_service.submit_mapping_suggestion_decisions",
        fake_submit,
    )

    response = client.post(
        "/passthrough/ks/review",
        json={
            "decisions": [
                _passthrough_mapping_decision(
                    "m-edit-fail",
                    "edited",
                    edited_payload={"source_field": "remittanceInfo", "target_field": "paymentReference"},
                )
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["partial_failure"] is True
    assert payload["saved_count"] == 0
    assert payload["applied_count"] == 0
    assert "m-edit-fail: edited_payload.confidence_basis is required." in payload["errors"]
    assert "m-edit-fail: KS stored no decision for this suggestion." in payload["warnings"]
    assert not get_session().ks_workspace_state.review_history
    assert not any(
        transform.source == "remittanceInfo" and transform.target == "paymentReference"
        for transform in get_session().passthrough_flow.transforms
    )
    reset_session()


def test_passthrough_mapping_review_reject_records_without_mutating_transforms(tmp_path, monkeypatch):
    _enable_passthrough_mapping_reviews(tmp_path, monkeypatch)
    before = list(get_session().passthrough_flow.transforms)

    response = client.post(
        "/passthrough/ks/review",
        json={"decisions": [_passthrough_mapping_decision("m-reject", "rejected")]},
    )

    assert response.status_code == 200
    assert response.json()["applied_count"] == 0
    session = get_session()
    assert session.passthrough_flow.transforms == before
    assert session.ks_workspace_state.suggestion_review_state.rejected_ids == ["m-reject"]
    assert session.ks_workspace_state.review_history[-1].type == "mapping"
    assert session.ks_workspace_state.review_history[-1].review_context == {
        "mapping_context": "passthrough",
        "route_name": "routePayment",
        "direction": "request",
        "source_entity": "InternalPaymentRequest",
        "target_entity": "SctPaymentRequest",
        "source_field": "currency",
        "target_field": "settlementCurrency",
    }
    reset_session()


def test_passthrough_mapping_review_does_not_duplicate_existing_transform(tmp_path, monkeypatch):
    _enable_passthrough_mapping_reviews(tmp_path, monkeypatch)

    response = client.post(
        "/passthrough/ks/review",
        json={
            "decisions": [
                _passthrough_mapping_decision(
                    "m-dupe",
                    "accepted",
                    source="amount",
                    target="settlementAmount",
                )
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["applied_count"] == 0
    assert "matching passthrough transform already exists" in payload["warnings"][0]
    transforms = get_session().passthrough_flow.transforms
    assert sum(1 for row in transforms if row.source == "amount" and row.target == "settlementAmount") == 1
    reset_session()


def test_passthrough_mapping_review_rejects_unsupported_mapping_payload(tmp_path, monkeypatch):
    _enable_passthrough_mapping_reviews(tmp_path, monkeypatch)

    def fail_submit(session, *, decisions: list[dict]):
        raise AssertionError("invalid mapping payloads should not be submitted to KS")

    monkeypatch.setattr(
        "app.routes.passthrough.assist_service.submit_mapping_suggestion_decisions",
        fail_submit,
    )

    response = client.post(
        "/passthrough/ks/review",
        json={
            "decisions": [
                _passthrough_mapping_decision(
                    "m-value-map",
                    "accepted",
                    mapping_type="value_map",
                )
            ]
        },
    )

    assert response.status_code == 400
    assert "copy mappings only" in response.json()["errors"][0]
    reset_session()


def test_passthrough_mapping_review_off_rejects_without_ks_call(tmp_path, monkeypatch):
    _seed_passthrough_session(tmp_path)
    _save_valid_passthrough_flow()

    def fail_submit(session, *, decisions: list[dict]):
        raise AssertionError("Knowledge Assist OFF should not submit mapping decisions")

    monkeypatch.setattr(
        "app.routes.passthrough.assist_service.submit_mapping_suggestion_decisions",
        fail_submit,
    )

    response = client.post(
        "/passthrough/ks/review",
        json={"decisions": [_passthrough_mapping_decision("m-off", "accepted")]},
    )

    assert response.status_code == 400
    assert "Knowledge Assist is off" in response.json()["errors"][0]
    reset_session()
