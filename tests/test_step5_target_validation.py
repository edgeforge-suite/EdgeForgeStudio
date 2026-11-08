"""Tests for Step 5 staging mapping target validation against DDL column names."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.staging_ddl_validation import extract_column_names_from_ddl
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)


def _seed_session():
    reset_session()
    session = get_session()
    session.app_name = "TestApp"
    session.bounded_context = "test"
    session.target_profile = "springboot-legacy-compatible"
    save_session(session)


# ---------------------------------------------------------------------------
# Unit tests — extract_column_names_from_ddl
# ---------------------------------------------------------------------------

def test_extract_simple_columns():
    ddl = (
        "CREATE TABLE customer_stage (\n"
        "  customer_id   VARCHAR(64) NOT NULL,\n"
        "  customer_name VARCHAR(128),\n"
        "  status_cd     VARCHAR(32)\n"
        ");"
    )
    cols = extract_column_names_from_ddl(ddl)
    assert cols == {"customer_id", "customer_name", "status_cd"}


def test_extract_skips_constraint_lines():
    ddl = (
        "CREATE TABLE t (\n"
        "  acct_id VARCHAR(36) NOT NULL,\n"
        "  CONSTRAINT pk PRIMARY KEY (acct_id),\n"
        "  UNIQUE (acct_id)\n"
        ");"
    )
    cols = extract_column_names_from_ddl(ddl)
    assert cols == {"acct_id"}
    assert "pk" not in cols


def test_extract_skips_check_and_foreign_key():
    ddl = (
        "CREATE TABLE t (\n"
        "  id INT NOT NULL,\n"
        "  status VARCHAR(20) DEFAULT 'PENDING',\n"
        "  FOREIGN KEY (id) REFERENCES other(id),\n"
        "  CHECK (status IN ('ACTIVE','CLOSED'))\n"
        ");"
    )
    cols = extract_column_names_from_ddl(ddl)
    assert cols == {"id", "status"}


def test_extract_returns_none_for_no_create_table():
    assert extract_column_names_from_ddl("") is None
    assert extract_column_names_from_ddl("SELECT 1") is None
    assert extract_column_names_from_ddl(None) is None


def test_extract_returns_none_for_empty_body():
    # A CREATE TABLE with no recognisable column lines should return None
    # (treated as uncertain rather than an empty confirmed set)
    ddl = "CREATE TABLE t ();"
    result = extract_column_names_from_ddl(ddl)
    assert result is None


def test_partial_parse_returns_none():
    """If any non-constraint part cannot be matched as a column definition,
    the function must return None rather than a partial column set.

    Rationale: returning a partial set would cause hard-block errors for
    targets that belong to the unrecognised columns, which is worse than
    degrading to a non-blocking warning.
    """
    # Inline SQL comment starting with '--' is not a constraint keyword and
    # does not match _COLUMN_NAME_RE (starts with '-').
    ddl = (
        "CREATE TABLE customer_stage (\n"
        "  customer_id   VARCHAR(64) NOT NULL,\n"
        "  customer_name VARCHAR(128),\n"
        "  -- inline comment the lightweight parser cannot categorise\n"
        ");"
    )
    result = extract_column_names_from_ddl(ddl)
    # Must be None — the partial set {customer_id, customer_name} must NOT
    # be returned, because the comment line proves the parse is incomplete.
    assert result is None


def test_extract_exact_case_preserved():
    """Column names must be returned with their original casing — no normalisation."""
    ddl = "CREATE TABLE t (CustomerID VARCHAR(36), customerName VARCHAR(128));"
    cols = extract_column_names_from_ddl(ddl)
    assert "CustomerID" in cols
    assert "customerName" in cols
    # Lower-case variants must NOT be invented
    assert "customerid" not in cols


# ---------------------------------------------------------------------------
# Integration tests — /handoffs/save target validation
# ---------------------------------------------------------------------------

GOOD_DDL = (
    "CREATE TABLE customer_stage (\n"
    "  customer_id   VARCHAR(64) NOT NULL,\n"
    "  customer_name VARCHAR(128),\n"
    "  status_cd     VARCHAR(32)\n"
    ");"
)


def test_valid_targets_accepted():
    """All mapping targets present in the DDL must save successfully."""
    _seed_session()
    resp = client.post("/handoffs/save", json={"handoffs": [{
        "name": "customer-staging",
        "ddl_content": GOOD_DDL,
        "field_mappings": [
            {"source": "Customer.id",   "target": "customer_id"},
            {"source": "Customer.name", "target": "customer_name"},
            {"source": "Customer.status", "target": "status_cd"},
        ],
    }]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data.get("errors", []) == []
    reset_session()


def test_invalid_target_blocked():
    """A mapping target not in the DDL must be rejected with a blocking error."""
    _seed_session()
    resp = client.post("/handoffs/save", json={"handoffs": [{
        "name": "customer-staging",
        "ddl_content": GOOD_DDL,
        "field_mappings": [
            {"source": "Customer.id",  "target": "customer_id"},
            {"source": "Customer.foo", "target": "non_existent_col"},
        ],
    }]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert any("non_existent_col" in e for e in data["errors"])
    # Nothing persisted
    session = get_session()
    assert session.data_handoffs == []
    reset_session()


def test_invalid_target_error_names_known_columns():
    """The error message must include the known column set for user guidance."""
    _seed_session()
    resp = client.post("/handoffs/save", json={"handoffs": [{
        "name": "customer-staging",
        "ddl_content": GOOD_DDL,
        "field_mappings": [
            {"source": "Customer.x", "target": "bad_col"},
        ],
    }]})
    error_text = " ".join(resp.json()["errors"])
    assert "bad_col" in error_text
    assert "customer_id" in error_text   # known columns listed
    reset_session()


def test_no_ddl_skips_validation():
    """When no DDL is provided, mapping targets are accepted without validation."""
    _seed_session()
    resp = client.post("/handoffs/save", json={"handoffs": [{
        "name": "customer-staging",
        "ddl_content": None,
        "field_mappings": [
            {"source": "Customer.x", "target": "completely_made_up"},
        ],
    }]})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    reset_session()


def test_no_mappings_skips_validation():
    """Empty field_mappings with DDL present must save without errors."""
    _seed_session()
    resp = client.post("/handoffs/save", json={"handoffs": [{
        "name": "customer-staging",
        "ddl_content": GOOD_DDL,
        "field_mappings": [],
    }]})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    reset_session()


def test_unparseable_manual_ddl_warns_not_blocks():
    """Complex/custom DDL that cannot be parsed should produce a warning, not a hard error."""
    _seed_session()
    # DDL that has no recognisable column lines — all lines look like constraints
    unparseable_ddl = (
        "CREATE TABLE weird (\n"
        "  PRIMARY KEY (x),\n"
        "  CONSTRAINT fk FOREIGN KEY (x) REFERENCES other(x)\n"
        ");"
    )
    resp = client.post("/handoffs/save", json={"handoffs": [{
        "name": "weird-staging",
        "ddl_content": unparseable_ddl,
        "field_mappings": [
            {"source": "X.x", "target": "x"},
        ],
    }]})
    assert resp.status_code == 200
    data = resp.json()
    # Must NOT be a hard error
    assert data["ok"] is True
    # Must surface a warning
    assert any("not be parsed" in w or "not validated" in w for w in data.get("warnings", []))
    reset_session()


def test_exact_case_match_required():
    """Target validation must use exact case — 'Customer_ID' must not match 'customer_id'."""
    _seed_session()
    resp = client.post("/handoffs/save", json={"handoffs": [{
        "name": "customer-staging",
        "ddl_content": GOOD_DDL,   # has "customer_id" (lowercase)
        "field_mappings": [
            {"source": "Customer.id", "target": "Customer_ID"},  # wrong case
        ],
    }]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert any("Customer_ID" in e for e in data["errors"])
    reset_session()


def test_multiple_handoffs_errors_aggregated():
    """Errors from multiple handoffs in one save call are all reported."""
    _seed_session()
    resp = client.post("/handoffs/save", json={"handoffs": [
        {
            "name": "handoff-a",
            "ddl_content": GOOD_DDL,
            "field_mappings": [{"source": "X.a", "target": "bad_a"}],
        },
        {
            "name": "handoff-b",
            "ddl_content": GOOD_DDL,
            "field_mappings": [{"source": "X.b", "target": "bad_b"}],
        },
    ]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    errors = data["errors"]
    assert any("bad_a" in e for e in errors)
    assert any("bad_b" in e for e in errors)
    reset_session()


def test_partially_parseable_ddl_warns_not_blocks():
    """DDL that partially parses (some columns recognised, one unrecognised part)
    must degrade to a non-blocking warning, NOT a hard error.

    This is the Codex P2 regression test: the previous implementation returned a
    partial column set and then hard-blocked any target absent from that partial
    set, producing false 'unknown column' errors for targets that legitimately
    belonged to the unrecognised column line.
    """
    _seed_session()
    # One valid column line, one unrecognised part (inline comment starting with
    # '--').  The lightweight parser can extract customer_id but cannot prove it
    # understood the full column set, so it must return None and the save must
    # warn rather than block.
    partial_ddl = (
        "CREATE TABLE customer_stage (\n"
        "  customer_id   VARCHAR(64) NOT NULL,\n"
        "  customer_name VARCHAR(128),\n"
        "  -- inline comment not understood by the lightweight parser\n"
        ");"
    )
    resp = client.post("/handoffs/save", json={"handoffs": [{
        "name": "partial-staging",
        "ddl_content": partial_ddl,
        "field_mappings": [
            {"source": "Customer.id",   "target": "customer_id"},
            # This target is "unknown" to the partial parse — must NOT hard-block
            {"source": "Customer.name", "target": "customer_name"},
        ],
    }]})
    assert resp.status_code == 200
    data = resp.json()
    # Must save successfully (no hard error)
    assert data["ok"] is True
    # Must surface a warning about uncertain parsing
    assert any("not be parsed" in w or "not validated" in w for w in data.get("warnings", []))
    reset_session()


def test_independent_staging_targets_accepted():
    _seed_session()
    ddl = "CREATE TABLE workspace_stage (workspace_id VARCHAR(48) NOT NULL, label VARCHAR(80), capacity DECIMAL(8,2), state CHAR(1));"
    response = client.post("/handoffs/save", json={"handoffs": [{
        "name": "workspace-stage", "system": "Synthetic", "type": "staging-table",
        "version": "v1", "entity_name": "Workspace", "ddl_content": ddl,
        "field_mappings": [
            {"source": "Workspace.workspaceId", "target": "workspace_id"},
            {"source": "Workspace.label", "target": "label"},
            {"source": "Workspace.capacity", "target": "capacity"},
            {"source": "Workspace.state", "target": "state"},
        ],
    }]})
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert len(get_session().data_handoffs[0].field_mappings) == 4
    reset_session()
