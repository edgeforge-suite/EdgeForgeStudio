"""Tests for Step 3 paginated-wrapper guidance."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    ClassifiedOperation,
    IdentityRoleDecision,
    OperationSample,
    UpstreamInterface,
)
from app.routes.entities import _detect_paginated_wrapper_fields
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)


def _step3_js() -> str:
    return Path("app/static/js/step3_entities.js").read_text(encoding="utf-8")


def _seed_step3_session(*, response_sample: str | None = None) -> None:
    reset_session()
    session = get_session()
    session.app_name = "TestApp"
    session.bounded_context = "customers"
    session.target_profile = "springboot-legacy-compatible"
    session.classified_entities = [
        ClassifiedEntity(
            name="Customer",
            classification="entity",
            fields=[
                ClassifiedField(name="customerId", type="string", required=True),
                ClassifiedField(name="currentPage", type="integer"),
                ClassifiedField(name="content", type="array"),
            ],
        )
    ]
    session.selected_entity_names = ["Customer"]
    session.classified_operations = [
        ClassifiedOperation(
            name="listCustomers",
            method="GET",
            path="/customers",
            resource="customers",
            entity_candidates=["Customer"],
        )
    ]
    session.upstream_interfaces = [
        UpstreamInterface(
            name="customers-customer-api",
            entity_name="Customer",
            operations=[
                OperationSample(
                    name="listCustomers",
                    response_sample_content=response_sample,
                )
            ],
        )
    ]
    save_session(session)


def test_detect_paginated_wrapper_fields_returns_known_wrapper_keys():
    sample = json.dumps({
        "content": [{"customerId": "C-001"}],
        "totalElements": 42,
        "size": 20,
        "number": 0,
    })

    assert _detect_paginated_wrapper_fields(sample) == [
        "content",
        "totalElements",
        "size",
        "number",
    ]


def test_detect_paginated_wrapper_fields_ignores_non_wrapper_shapes():
    assert _detect_paginated_wrapper_fields(json.dumps({"size": 20, "status": "ACTIVE"})) == []
    assert _detect_paginated_wrapper_fields(json.dumps({"content": "hello", "status": "ACTIVE"})) == []
    assert _detect_paginated_wrapper_fields(json.dumps({"content": [{"customerId": "C-001"}], "status": "ACTIVE"})) == []
    assert _detect_paginated_wrapper_fields(json.dumps([{"customerId": "C-001"}])) == []
    assert _detect_paginated_wrapper_fields(json.dumps({"customerId": "C-001", "status": "ACTIVE"})) == []
    assert _detect_paginated_wrapper_fields("{not-json") == []


def test_step3_save_includes_paginated_wrapper_fields_for_phase2_guidance():
    _seed_step3_session(response_sample=json.dumps({
        "content": [{"customerId": "C-001"}],
        "totalElements": 42,
        "pageable": {"pageSize": 20},
    }))

    response = client.post("/entities/save", json={
        "entities": ["Customer"],
        "operations": ["listCustomers"],
        "entity_op_map": {"Customer": ["listCustomers"]},
    })

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    op = payload["interfaces"][0]["operations"][0]
    assert op["pagination_wrapper_fields"] == ["content", "totalElements", "pageable"]
    reset_session()


def test_step3_template_includes_paginated_wrapper_guidance_text():
    _seed_step3_session()

    response = client.get("/entities")

    assert response.status_code == 200
    js = _step3_js()
    assert "Pagination-wrapper guidance" in js
    assert "consider using a cleaner non-paginated response sample" in js
    assert "Array.isArray(parsed.content)" in js
    assert "key !== 'content'" in js
    reset_session()


def test_step3_renders_identity_role_lens_with_eligible_fields():
    _seed_step3_session(response_sample=json.dumps({
        "content": [{"customerId": "C-001"}],
        "totalElements": 42,
        "pageSize": 20,
    }))
    session = get_session()
    session.identity_role_decisions = [
        IdentityRoleDecision(
            entity="Customer",
            field="customerId",
            role="persistence_id",
            reviewed_at="2026-05-06T12:00:00+00:00",
        )
    ]
    save_session(session)

    response = client.get("/entities")

    assert response.status_code == 200
    assert "Identity Role Lens" in response.text
    assert "Generation impact of this decision" in response.text
    assert "exports to → identity_overrides" in response.text
    assert "persistence_id" in response.text
    assert "Affects generated persistence identity: Java @Id, DB primary key, and repository identity." in response.text
    assert "Exported as metadata only; no generated app behavior yet." in response.text
    assert "Does not change Java, DDL, rules, APIs, or runtime behavior." in response.text
    assert "Future behavior requires explicit uniqueness or lookup policy." in response.text
    assert "Future behavior requires explicit relationship or rule policy." in response.text
    for role in (
        "parent_reference",
        "business_key",
        "event_id",
        "idempotency_key",
        "correlation_id",
        "external_reference",
    ):
        assert role in response.text
    assert "Non-persistence roles do not change generated Java, DDL, API, or runtime behavior." in response.text
    assert "Save Role Decisions" in response.text
    assert "Save identity roles" not in response.text
    assert 'data-field="customerId"' in response.text
    assert 'data-field="currentPage"' not in response.text
    assert 'data-field="content"' not in response.text
    assert "Reviewed 2026-05-06" in response.text
    assert "2026-05-06T12:00:00+00:00" not in response.text
    reset_session()


def test_identity_role_save_validates_and_replaces_persistence_id():
    _seed_step3_session()
    session = get_session()
    session.classified_entities[0].fields.append(ClassifiedField(name="externalId", type="string"))
    session.identity_role_decisions = [
        IdentityRoleDecision(entity="Customer", field="externalId", role="persistence_id")
    ]
    save_session(session)

    response = client.post("/entities/identity-roles", json={
        "decisions": [
            {"entity": "Customer", "field": "customerId", "role": "persistence_id"},
            {"entity": "Customer", "field": "externalId", "role": "business_key"},
        ]
    })

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert "identity_role_review" not in payload
    saved = {(item["field"], item["role"]) for item in payload["decisions"]}
    assert saved == {("customerId", "persistence_id"), ("externalId", "business_key")}
    reset_session()


def test_identity_role_save_rejects_duplicate_field_or_persistence_id_payloads():
    _seed_step3_session()
    session = get_session()
    session.classified_entities[0].fields.append(ClassifiedField(name="externalId", type="string"))
    save_session(session)

    response = client.post("/entities/identity-roles", json={
        "decisions": [
            {"entity": "Customer", "field": "customerId", "role": "business_key"},
            {"entity": "Customer", "field": "customerId", "role": "external_reference"},
        ]
    })
    assert response.status_code == 400
    assert "can have only one active identity role" in " ".join(response.json().get("errors", []))

    response = client.post("/entities/identity-roles", json={
        "decisions": [
            {"entity": "Customer", "field": "customerId", "role": "persistence_id"},
            {"entity": "Customer", "field": "externalId", "role": "persistence_id"},
        ]
    })
    assert response.status_code == 400
    assert "can have only one active persistence_id" in " ".join(response.json().get("errors", []))
    reset_session()


def test_identity_role_save_rejects_unknown_invalid_and_wrapper_fields():
    _seed_step3_session(response_sample=json.dumps({
        "content": [{"customerId": "C-001"}],
        "totalElements": 42,
        "size": 20,
    }))

    for decision, expected in [
        ({"entity": "Ghost", "field": "customerId", "role": "persistence_id"}, "Unknown CRUD entity"),
        ({"entity": "Customer", "field": "missing", "role": "persistence_id"}, "Unknown field"),
        ({"entity": "Customer", "field": "currentPage", "role": "persistence_id"}, "transport wrapper/page field"),
        ({"entity": "Customer", "field": "customerId", "role": "made_up"}, "Invalid identity role"),
    ]:
        response = client.post("/entities/identity-roles", json={"decisions": [decision]})
        assert response.status_code == 400
        assert expected in " ".join(response.json().get("errors", []))
    reset_session()


def test_identity_role_save_clears_existing_role():
    _seed_step3_session()
    session = get_session()
    session.identity_role_decisions = [
        IdentityRoleDecision(entity="Customer", field="customerId", role="persistence_id")
    ]
    save_session(session)

    response = client.post("/entities/identity-roles", json={
        "decisions": [{"entity": "Customer", "field": "customerId", "role": ""}]
    })

    assert response.status_code == 200
    assert response.json()["decisions"] == []
    assert get_session().identity_role_decisions == []
    reset_session()
