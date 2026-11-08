"""Tests for upstream mapping validation in the save endpoint."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    OperationSample,
    UpstreamInterface,
)
from app.routes.mappings import _sample_fields
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)

# ---------------------------------------------------------------------------
# Unit tests for _sample_fields helper
# ---------------------------------------------------------------------------

def test_sample_fields_dict_returns_top_level_keys():
    content = json.dumps({"customerId": "C-001", "accountType": "CHQ"})
    assert _sample_fields(content) == {"customerId", "accountType"}


def test_sample_fields_list_of_dicts_returns_first_item_keys():
    content = json.dumps([{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}])
    assert _sample_fields(content) == {"id", "name"}


def test_sample_fields_empty_string_returns_none():
    assert _sample_fields("") is None
    assert _sample_fields(None) is None


def test_sample_fields_invalid_json_returns_none():
    assert _sample_fields("{not json}") is None


def test_sample_fields_non_dict_list_returns_none():
    content = json.dumps([1, 2, 3])
    assert _sample_fields(content) is None


def test_sample_fields_nested_dict_includes_dot_notation():
    """Envelope patterns like Codat's create-customer response expose nested keys."""
    content = json.dumps({"data": {"id": "cust-1", "name": "Acme"}, "companyId": "co-1"})
    fields = _sample_fields(content)
    assert fields is not None
    # Top-level keys
    assert "data" in fields
    assert "companyId" in fields
    # One level of dot-notation nested keys
    assert "data.id" in fields
    assert "data.name" in fields
    # No deeper nesting expected
    assert "data.id.x" not in fields


def test_sample_fields_nested_dict_in_list():
    """List-of-dicts with an envelope wrapper also exposes nested dot-notation keys."""
    content = json.dumps([{"data": {"id": "1", "val": "x"}, "meta": "y"}])
    fields = _sample_fields(content)
    assert fields is not None
    assert "data" in fields
    assert "data.id" in fields
    assert "data.val" in fields
    assert "meta" in fields


def test_sample_fields_flat_dict_unchanged():
    """Flat samples still work correctly — no spurious dot-notation keys added."""
    content = json.dumps({"id": "1", "name": "Alice", "status": "Active"})
    fields = _sample_fields(content)
    assert fields == {"id", "name", "status"}


# ---------------------------------------------------------------------------
# Integration tests via the /mappings/upstream/save endpoint
# ---------------------------------------------------------------------------

def _seed_interface_with_samples(
    iface_name: str,
    op_name: str,
    request_sample: dict | None = None,
    response_sample: dict | None = None,
):
    """Seed the session with one interface + one operation with given sample bodies."""
    reset_session()
    session = get_session()
    session.app_name = "TestApp"
    session.bounded_context = "test"
    session.target_profile = "springboot-legacy-compatible"
    session.classified_entities = [
        ClassifiedEntity(
            name="Customer",
            fields=[
                ClassifiedField(name=name, type="string")
                for name in (
                    "accountId",
                    "accountType",
                    "any",
                    "companyId",
                    "customerId",
                    "customerName",
                    "id",
                    "name",
                    "status",
                    "x",
                )
            ],
        )
    ]
    session.selected_entity_names = ["Customer"]

    op = OperationSample(
        name=op_name,
        request_sample_content=json.dumps(request_sample) if request_sample is not None else None,
        response_sample_content=json.dumps(response_sample) if response_sample is not None else None,
    )
    iface = UpstreamInterface(
        name=iface_name,
        entity_name="Customer",
        type="rest-json",
        operations=[op],
    )
    session.upstream_interfaces = [iface]
    save_session(session)


def test_mapping_save_accepts_valid_source_field():
    """A source field that exists in the sample must be accepted and saved."""
    _seed_interface_with_samples(
        "test-api", "createCustomer",
        request_sample={"customerId": "C-001", "name": "Alice"},
    )

    resp = client.post("/mappings/upstream/save", json={
        "interface_name": "test-api",
        "operation_mappings": [{
            "name": "createCustomer",
            "request_mappings": [{"source": "customerId", "target": "Customer.customerId"}],
            "response_mappings": [],
        }],
    })

    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Confirm the mapping was persisted
    session = get_session()
    iface = next(i for i in session.upstream_interfaces if i.name == "test-api")
    om = next(om for om in iface.operation_mappings if om.name == "createCustomer")
    assert any(m.source == "customerId" for m in om.request_mappings)
    reset_session()


def test_mapping_save_rejects_unknown_source_field():
    """A source field absent from the sample must be rejected with an error."""
    _seed_interface_with_samples(
        "test-api", "createCustomer",
        request_sample={"customerId": "C-001", "name": "Alice"},
    )

    resp = client.post("/mappings/upstream/save", json={
        "interface_name": "test-api",
        "operation_mappings": [{
            "name": "createCustomer",
            # 'kycid' is not in the request sample — should be rejected
            "request_mappings": [{"source": "kycid", "target": "Customer.kycId"}],
            "response_mappings": [],
        }],
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "errors" in data
    assert len(data["errors"]) >= 1
    assert any("kycid" in e for e in data["errors"])

    # Confirm nothing was persisted
    session = get_session()
    iface = next(i for i in session.upstream_interfaces if i.name == "test-api")
    assert iface.operation_mappings == []
    reset_session()


def test_mapping_save_rejects_target_missing_from_selected_canonical_entity():
    _seed_interface_with_samples(
        "test-api",
        "createCustomer",
        request_sample={"currency_code": "USD"},
    )

    response = client.post(
        "/mappings/upstream/save",
        json={
            "interface_name": "test-api",
            "operation_mappings": [
                {
                    "name": "createCustomer",
                    "request_mappings": [
                        {"source": "currency_code", "target": "Customer.currency_code"}
                    ],
                    "response_mappings": [],
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert any("not a field on selected entity" in error for error in response.json()["errors"])
    assert get_session().upstream_interfaces[0].operation_mappings == []


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (" customerId", "Customer.customerId"),
        ("customerId", " Customer.customerId "),
        ("customerId", "   "),
    ],
)
def test_mapping_save_rejects_paths_with_surrounding_whitespace(source, target):
    _seed_interface_with_samples(
        "test-api",
        "createCustomer",
        request_sample={"customerId": "C-001"},
    )

    response = client.post(
        "/mappings/upstream/save",
        json={
            "interface_name": "test-api",
            "operation_mappings": [
                {
                    "name": "createCustomer",
                    "request_mappings": [{"source": source, "target": target}],
                    "response_mappings": [],
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert any("whitespace" in error for error in response.json()["errors"])
    assert get_session().upstream_interfaces[0].operation_mappings == []
    reset_session()


def test_mapping_save_no_sample_skips_validation():
    """When no sample body is present, mapping sources are accepted without validation."""
    _seed_interface_with_samples("test-api", "createCustomer")  # no samples

    resp = client.post("/mappings/upstream/save", json={
        "interface_name": "test-api",
        "operation_mappings": [{
            "name": "createCustomer",
            "request_mappings": [{"source": "anyFieldName", "target": "Customer.any"}],
            "response_mappings": [],
        }],
    })

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    reset_session()


def test_mapping_save_rejects_unknown_response_field():
    """An unknown response mapping source is rejected even when request mappings are valid."""
    _seed_interface_with_samples(
        "test-api", "getCustomer",
        response_sample={"accountId": "ACC-001", "status": "ACTIVE"},
    )

    resp = client.post("/mappings/upstream/save", json={
        "interface_name": "test-api",
        "operation_mappings": [{
            "name": "getCustomer",
            "request_mappings": [],
            "response_mappings": [{"source": "nonExistentField", "target": "Customer.x"}],
        }],
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert any("nonExistentField" in e for e in data["errors"])
    reset_session()


def test_mapping_save_accepts_nested_dot_notation_response_source():
    """Dot-notation sources like 'data.id' must be accepted for envelope-wrapped responses (Codat pattern)."""
    envelope_response = {
        "data": {"id": "cust-1001", "customerName": "Acme Holdings", "status": "Active"},
        "companyId": "co-001",
        "dataType": "customer",
        "statusCode": 200,
    }
    _seed_interface_with_samples(
        "test-api", "createCustomer",
        response_sample=envelope_response,
    )

    resp = client.post("/mappings/upstream/save", json={
        "interface_name": "test-api",
        "operation_mappings": [{
            "name": "createCustomer",
            "request_mappings": [],
            "response_mappings": [
                {"source": "data.id", "target": "Customer.id"},
                {"source": "data.customerName", "target": "Customer.customerName"},
                {"source": "data.status", "target": "Customer.status"},
                {"source": "companyId", "target": "Customer.companyId"},
            ],
        }],
    })

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    reset_session()


def test_mapping_save_rejects_truly_unknown_field_in_envelope_response():
    """A field that doesn't exist anywhere in the envelope sample must still be rejected."""
    envelope_response = {
        "data": {"id": "cust-1001", "customerName": "Acme Holdings"},
        "companyId": "co-001",
    }
    _seed_interface_with_samples(
        "test-api", "createCustomer",
        response_sample=envelope_response,
    )

    resp = client.post("/mappings/upstream/save", json={
        "interface_name": "test-api",
        "operation_mappings": [{
            "name": "createCustomer",
            "request_mappings": [],
            "response_mappings": [
                {"source": "data.nonExistentField", "target": "Customer.x"},
            ],
        }],
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert any("data.nonExistentField" in e for e in data["errors"])
    reset_session()


def test_mapping_save_empty_mappings_always_accepted():
    """Saving empty mapping lists is always valid — clears stale entries."""
    _seed_interface_with_samples(
        "test-api", "createCustomer",
        request_sample={"customerId": "C-001"},
    )

    resp = client.post("/mappings/upstream/save", json={
        "interface_name": "test-api",
        "operation_mappings": [{
            "name": "createCustomer",
            "request_mappings": [],
            "response_mappings": [],
        }],
    })

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    reset_session()
