"""Tests for Step 6 generated-ID rule mismatch warnings."""

from __future__ import annotations

import json

from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    OperationSample,
    ProjectSession,
    UpstreamInterface,
)
from app.routes.rules import _build_generated_id_warnings
from tests.session_helpers import reset_session, save_session

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session_with_customer(
    *,
    include_id_in_create_body: bool,
    field_is_id_flag: bool = False,
) -> ProjectSession:
    """Build a minimal session with a Customer entity and a createCustomer op."""
    session = reset_session()

    if include_id_in_create_body:
        create_body = json.dumps({"customerId": "abc123", "name": "Alice"})
    else:
        # Server-generated — ID absent from create request body
        create_body = json.dumps({"name": "Alice"})

    session.classified_entities = [
        ClassifiedEntity(
            name="CustomerResponse",
            canonical_name="Customer",
            classification="entity",
            fields=[
                ClassifiedField(
                    name="customerId",
                    type="string",
                    is_id=field_is_id_flag,
                ),
                ClassifiedField(name="name", type="string"),
            ],
        )
    ]
    session.upstream_interfaces = [
        UpstreamInterface(
            name="customer-api",
            entity_name="CustomerResponse",
            operations=[
                OperationSample(
                    name="createCustomer",
                    request_sample_content=create_body,
                ),
            ],
        )
    ]
    save_session(session)
    return session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_warning_for_likely_generated_id_field():
    """customerId absent from create body → warning emitted (heuristic: ends with Id + string)."""
    session = _make_session_with_customer(include_id_in_create_body=False)
    warnings, likely_fields = _build_generated_id_warnings(session)

    assert any("customerId" in w["message"] for w in warnings), (
        "Expected a warning mentioning customerId"
    )
    assert any("server-generated" in w["message"] for w in warnings), (
        "Expected 'server-generated' in warning text"
    )
    assert "Customer.customerId" in likely_fields


def test_warning_uses_is_id_flag():
    """is_id=True triggers warning even if field name doesn't end with 'Id'."""
    session = reset_session()
    create_body = json.dumps({"fullName": "Alice"})
    session.classified_entities = [
        ClassifiedEntity(
            name="PersonResponse",
            canonical_name="Person",
            classification="entity",
            fields=[
                ClassifiedField(name="pid", type="string", is_id=True),
                ClassifiedField(name="fullName", type="string"),
            ],
        )
    ]
    session.upstream_interfaces = [
        UpstreamInterface(
            name="person-api",
            entity_name="PersonResponse",
            operations=[
                OperationSample(
                    name="createPerson",
                    request_sample_content=create_body,
                ),
            ],
        )
    ]
    save_session(session)

    warnings, likely_fields = _build_generated_id_warnings(session)
    assert any("pid" in w["message"] for w in warnings)
    assert "Person.pid" in likely_fields


def test_no_warning_for_client_supplied_id():
    """customerId present in create body → no warning."""
    session = _make_session_with_customer(include_id_in_create_body=True)
    warnings, likely_fields = _build_generated_id_warnings(session)

    assert not any("customerId" in w["message"] for w in warnings), (
        "Expected no warning for client-supplied customerId"
    )
    assert "Customer.customerId" not in likely_fields


def test_no_warning_when_no_create_operations():
    """No create operations present → insufficient evidence → no warning."""
    session = reset_session()
    session.classified_entities = [
        ClassifiedEntity(
            name="CustomerResponse",
            canonical_name="Customer",
            classification="entity",
            fields=[
                ClassifiedField(name="customerId", type="string"),
            ],
        )
    ]
    session.upstream_interfaces = [
        UpstreamInterface(
            name="customer-api",
            entity_name="CustomerResponse",
            operations=[
                OperationSample(
                    name="getCustomer",
                    response_sample_content='{"customerId": "c1"}',
                ),
            ],
        )
    ]
    save_session(session)

    warnings, likely_fields = _build_generated_id_warnings(session)
    # No create body samples → cannot determine server-generation → no warning
    assert not warnings
    assert not likely_fields


def test_no_warning_for_non_entity_classification():
    """DTO entities are skipped — only 'entity' classification is considered."""
    session = reset_session()
    create_body = json.dumps({"fullName": "Alice"})
    session.classified_entities = [
        ClassifiedEntity(
            name="CustomerDto",
            canonical_name="CustomerDto",
            classification="dto",          # not "entity"
            fields=[
                ClassifiedField(name="customerId", type="string"),
            ],
        )
    ]
    session.upstream_interfaces = [
        UpstreamInterface(
            name="customer-api",
            entity_name="CustomerDto",
            operations=[
                OperationSample(
                    name="createCustomer",
                    request_sample_content=create_body,
                ),
            ],
        )
    ]
    save_session(session)

    warnings, likely_fields = _build_generated_id_warnings(session)
    assert not warnings
    assert not likely_fields


def test_cross_entity_warning_target_entity_has_generated_id():
    """When a cross-entity-exists target has a generated ID, it appears in likely_fields."""
    session = reset_session()
    # Account has an accountId (server-generated) and a customerId (FK to Customer)
    # Customer has customerId absent from create body
    customer_create = json.dumps({"name": "Alice"})   # customerId absent
    session.classified_entities = [
        ClassifiedEntity(
            name="CustomerResponse",
            canonical_name="Customer",
            classification="entity",
            fields=[
                ClassifiedField(name="customerId", type="string"),
                ClassifiedField(name="name", type="string"),
            ],
        ),
        ClassifiedEntity(
            name="AccountResponse",
            canonical_name="Account",
            classification="entity",
            fields=[
                ClassifiedField(name="accountId", type="string"),
                ClassifiedField(name="customerId", type="string"),
            ],
        ),
    ]
    session.upstream_interfaces = [
        UpstreamInterface(
            name="customer-api",
            entity_name="CustomerResponse",
            operations=[
                OperationSample(
                    name="createCustomer",
                    request_sample_content=customer_create,
                ),
            ],
        ),
    ]
    save_session(session)

    warnings, likely_fields = _build_generated_id_warnings(session)

    # Customer.customerId is likely server-generated (absent from create body)
    assert "Customer.customerId" in likely_fields

    # Account has no create body → no warning for Account fields
    # (insufficient evidence)
    assert "Account.accountId" not in likely_fields



def test_cross_entity_warning_does_not_fire_for_non_pk_generated_field():
    """Regression for Codex P2-2: cross-entity warning should only fire for the
    target entity's primary key, not for any *Id field on that entity.

    Scenario: Account has a non-PK field invoiceId absent from its create body
    (looks generated), but accountId IS in the create body (client-supplied).
    Using Account as a cross-entity-exists target should NOT trigger a warning,
    because Account's PK (accountId) is client-supplied.

    The JS check: likelyGeneratedIdFields.includes(`${targetEntity}.${targetPkField}`)
    where targetPkField = 'accountId'. Since accountId is present in the create body
    it is not in likely_fields, so no warning fires.
    """
    session = reset_session()
    account_create = json.dumps({"accountId": "ACC-001", "currency": "USD"})
    session.classified_entities = [
        ClassifiedEntity(
            name="AccountResponse",
            canonical_name="Account",
            classification="entity",
            fields=[
                ClassifiedField(name="accountId", type="string"),
                ClassifiedField(name="invoiceId", type="string"),  # absent from create -> generated
                ClassifiedField(name="currency", type="string"),
            ],
        )
    ]
    session.upstream_interfaces = [
        UpstreamInterface(
            name="account-api",
            entity_name="AccountResponse",
            operations=[
                OperationSample(
                    name="createAccount",
                    request_sample_content=account_create,
                ),
            ],
        )
    ]
    save_session(session)

    warnings, likely_fields = _build_generated_id_warnings(session)

    # invoiceId is generated (absent from create body) -> in likely_fields
    assert "Account.invoiceId" in likely_fields
    # accountId is client-supplied (present in create body) -> NOT in likely_fields
    # JS cross-entity check uses accountId (the PK) -> no warning fires for Account as target
    assert "Account.accountId" not in likely_fields

def test_save_payload_unchanged():
    """POST /rules/save with cross-entity-exists preserves target_entity on session."""
    from fastapi.testclient import TestClient

    from app.main import app

    reset_session()
    client = TestClient(app)

    response = client.post(
        "/rules/save",
        json={
            "entity_rules": [
                {
                    "entity_name": "Account",
                    "rules": [
                        {
                            "field": "customerId",
                            "type": "cross-entity-exists",
                            "target_entity": "Customer",
                        }
                    ],
                }
            ],
            "legacy_notes": None,
            "legacy_slug": "dda",
        },
    )
    assert response.status_code == 200
    from tests.session_helpers import get_session
    rule = get_session().entity_rules[0].rules[0]
    assert rule.type == "cross-entity-exists"
    assert rule.target_entity == "Customer"

    reset_session()
