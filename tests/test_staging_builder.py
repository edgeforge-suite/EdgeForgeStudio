"""Tests for the structured staging-table DDL builder."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.project import UpstreamInterface
from app.services.staging_ddl_validation import (
    generate_ddl_from_columns,
    parse_columns_from_create_ddl,
)
from tests.session_helpers import reset_session, save_session

client = TestClient(app)


def test_step4_edge_contract_only_project_shows_skip_safe_guidance():
    session = reset_session()
    session.app_archetype = "crud"
    session.classified_entities = []
    session.selected_entity_names = []
    session.data_handoffs = []
    session.upstream_interfaces = [
        UpstreamInterface(
            name="account-xml-feed",
            type="xml-xsd",
            xsd_path="contracts/account.xsd",
            root_element="acct:Account",
        )
    ]
    save_session(session)

    response = client.get("/handoffs")

    assert response.status_code == 200
    assert "This edge-contract-only project has no table-based data handoffs." in response.text
    assert "You can safely skip to Step 5." in response.text
    assert "alert-info" in response.text

    reset_session()


# ---------------------------------------------------------------------------
# Unit tests — generate_ddl_from_columns
# ---------------------------------------------------------------------------

def test_varchar_column_with_length():
    ddl = generate_ddl_from_columns("customer_stage", [
        {"name": "customer_id", "type": "VARCHAR", "length": 64, "nullable": False},
    ])
    assert "CREATE TABLE customer_stage" in ddl
    assert "customer_id VARCHAR(64) NOT NULL" in ddl


def test_nullable_column_has_no_not_null():
    ddl = generate_ddl_from_columns("t", [
        {"name": "notes", "type": "TEXT", "nullable": True},
    ])
    assert "NOT NULL" not in ddl
    assert "notes TEXT" in ddl


def test_varchar_defaults_to_255_when_no_length():
    ddl = generate_ddl_from_columns("t", [
        {"name": "label", "type": "VARCHAR"},
    ])
    assert "label VARCHAR(255)" in ddl


def test_int_column_has_no_length():
    ddl = generate_ddl_from_columns("t", [
        {"name": "count", "type": "INT", "nullable": False},
    ])
    assert "count INT NOT NULL" in ddl
    assert "INT(" not in ddl


def test_decimal_with_precision_and_scale():
    ddl = generate_ddl_from_columns("t", [
        {"name": "amount", "type": "DECIMAL", "length": 18, "scale": 4, "nullable": False},
    ])
    assert "amount DECIMAL(18,4) NOT NULL" in ddl


def test_decimal_without_scale():
    ddl = generate_ddl_from_columns("t", [
        {"name": "amount", "type": "DECIMAL", "length": 10},
    ])
    assert "amount DECIMAL(10)" in ddl
    assert "DECIMAL(10," not in ddl


def test_parse_oracle_and_common_sql_types_for_structured_restore():
    ddl = (
        "CREATE TABLE CUSTOMER_STAGE (\n"
        "  CUSTOMER_ID VARCHAR2(64) NOT NULL,\n"
        "  BALANCE NUMBER(18,0),\n"
        "  RISK_CODE CHAR(1),\n"
        "  OPENED_ON DATE,\n"
        "  UPDATED_AT TIMESTAMP\n"
        ");"
    )

    parsed = parse_columns_from_create_ddl(ddl)

    assert parsed is not None
    assert parsed["table_name"] == "CUSTOMER_STAGE"
    assert parsed["columns"] == [
        {"name": "CUSTOMER_ID", "type": "VARCHAR", "nullable": False, "length": 64},
        {"name": "BALANCE", "type": "DECIMAL", "nullable": True, "length": 18, "scale": 0},
        {"name": "RISK_CODE", "type": "CHAR", "nullable": True, "length": 1},
        {"name": "OPENED_ON", "type": "DATE", "nullable": True},
        {"name": "UPDATED_AT", "type": "TIMESTAMP", "nullable": True},
    ]


def test_parse_schema_qualified_create_table_uses_table_segment():
    parsed = parse_columns_from_create_ddl(
        "CREATE TABLE dbo.customer_stage (customer_id VARCHAR2(64) NOT NULL);"
    )

    assert parsed is not None
    assert parsed["table_name"] == "customer_stage"
    assert parsed["columns"][0] == {
        "name": "customer_id",
        "type": "VARCHAR",
        "nullable": False,
        "length": 64,
    }


def test_multiple_columns_all_present():
    ddl = generate_ddl_from_columns("customer_stage", [
        {"name": "customer_id",   "type": "VARCHAR", "length": 64,  "nullable": False},
        {"name": "customer_name", "type": "VARCHAR", "length": 128, "nullable": True},
        {"name": "status_cd",     "type": "VARCHAR", "length": 32,  "nullable": True},
        {"name": "email_address", "type": "VARCHAR", "length": 128, "nullable": True},
    ])
    assert "customer_id VARCHAR(64) NOT NULL" in ddl
    assert "customer_name VARCHAR(128)" in ddl
    assert "status_cd VARCHAR(32)" in ddl
    assert "email_address VARCHAR(128)" in ddl
    assert ddl.startswith("CREATE TABLE customer_stage (")
    assert ddl.endswith(");")


def test_empty_table_name_raises():
    with pytest.raises(ValueError, match="table_name"):
        generate_ddl_from_columns("", [{"name": "x", "type": "INT"}])


def test_empty_columns_raises():
    with pytest.raises(ValueError, match="column"):
        generate_ddl_from_columns("t", [])


def test_column_with_no_name_skipped_raises_if_all_empty():
    with pytest.raises(ValueError, match="column"):
        generate_ddl_from_columns("t", [{"name": "", "type": "INT"}])


def test_independent_staging_scalar_shapes():
    """Independently authored nullable/text/numeric DDL coverage."""
    ddl = generate_ddl_from_columns("workspace_stage", [
        {"name": "workspace_id", "type": "VARCHAR", "length": 48, "nullable": False},
        {"name": "label", "type": "VARCHAR", "length": 80, "nullable": True},
        {"name": "capacity", "type": "DECIMAL", "precision": 8, "scale": 2},
        {"name": "state", "type": "CHAR", "length": 1},
    ])
    assert "CREATE TABLE workspace_stage" in ddl
    assert "workspace_id VARCHAR(48) NOT NULL" in ddl
    assert "label VARCHAR(80)" in ddl
    assert "capacity DECIMAL(8,2)" in ddl
    assert "state CHAR(1)" in ddl


# ---------------------------------------------------------------------------
# API endpoint tests — /api/validate/staging-ddl/generate
# ---------------------------------------------------------------------------

def test_generate_endpoint_basic():
    resp = client.post("/api/validate/staging-ddl/generate", json={
        "table_name": "acct_stage",
        "columns": [
            {"name": "acct_id",   "type": "VARCHAR", "length": 36,  "nullable": False},
            {"name": "acct_name", "type": "VARCHAR", "length": 100, "nullable": True},
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "CREATE TABLE acct_stage" in data["ddl"]
    assert "acct_id VARCHAR(36) NOT NULL" in data["ddl"]
    assert "acct_name VARCHAR(100)" in data["ddl"]


def test_generate_endpoint_empty_table_name_returns_error():
    resp = client.post("/api/validate/staging-ddl/generate", json={
        "table_name": "",
        "columns": [{"name": "x", "type": "INT"}],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "table_name" in data["error"]


def test_generate_endpoint_no_columns_returns_error():
    resp = client.post("/api/validate/staging-ddl/generate", json={
        "table_name": "t",
        "columns": [],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False


def test_generate_endpoint_ddl_passes_uuid_width_check():
    """A VARCHAR(64) _id column must NOT trigger the UUID width warning."""
    resp = client.post("/api/validate/staging-ddl/generate", json={
        "table_name": "customer_stage",
        "columns": [
            {"name": "customer_id", "type": "VARCHAR", "length": 64, "nullable": False},
        ],
    })
    ddl = resp.json()["ddl"]
    warn_resp = client.post("/api/validate/staging-ddl", json={"ddl": ddl})
    assert warn_resp.json()["warnings"] == []


def test_generate_endpoint_ddl_triggers_uuid_width_warning():
    """A VARCHAR(16) _id column must still trigger the UUID width warning."""
    resp = client.post("/api/validate/staging-ddl/generate", json={
        "table_name": "customer_stage",
        "columns": [
            {"name": "customer_id", "type": "VARCHAR", "length": 16, "nullable": False},
        ],
    })
    ddl = resp.json()["ddl"]
    warn_resp = client.post("/api/validate/staging-ddl", json={"ddl": ddl})
    warnings = warn_resp.json()["warnings"]
    assert len(warnings) == 1
    assert warnings[0]["column"] == "customer_id"


# ---------------------------------------------------------------------------
# Round-trip — save endpoint still accepts generated DDL unchanged
# ---------------------------------------------------------------------------

def test_handoff_save_accepts_generated_ddl():
    """The /handoffs/save endpoint must accept DDL produced by the builder."""
    from tests.session_helpers import get_session, reset_session, save_session

    reset_session()
    session = get_session()
    session.app_name = "TestApp"
    session.bounded_context = "test"
    session.target_profile = "springboot-legacy-compatible"
    save_session(session)

    ddl = generate_ddl_from_columns("customer_stage", [
        {"name": "customer_id",   "type": "VARCHAR", "length": 64,  "nullable": False},
        {"name": "customer_name", "type": "VARCHAR", "length": 128, "nullable": True},
    ])

    resp = client.post("/handoffs/save", json={"handoffs": [{
        "name": "customer-staging-table",
        "system": "ETL",
        "type": "staging-table",
        "version": "v1",
        "entity_name": "Customer",
        "table_name": "customer_stage",
        "ddl_content": ddl,
        "field_mappings": [
            {"source": "Customer.id",           "target": "customer_id"},
            {"source": "Customer.customerName", "target": "customer_name"},
        ],
    }]})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["count"] == 1

    session = get_session()
    handoff = session.data_handoffs[0]
    assert handoff.ddl_content == ddl
    assert handoff.table_name == "customer_stage"
    assert len(handoff.field_mappings) == 2
    reset_session()


def test_handoff_get_restores_structured_rows_from_existing_oracle_ddl():
    from app.models.project import DataHandoff
    from tests.session_helpers import get_session, reset_session, save_session

    reset_session()
    session = get_session()
    session.data_handoffs = [
        DataHandoff(
            name="customer-staging-table",
            table_name="CUSTOMER_STAGE",
            ddl_content=(
                "CREATE TABLE CUSTOMER_STAGE (\n"
                "  CUSTOMER_ID VARCHAR2(64) NOT NULL,\n"
                "  BALANCE NUMBER(18,0),\n"
                "  RISK_CODE CHAR(1),\n"
                "  OPENED_ON DATE,\n"
                "  UPDATED_AT TIMESTAMP\n"
                ");"
            ),
        )
    ]
    save_session(session)

    resp = client.get("/handoffs")
    assert resp.status_code == 200
    html = resp.text
    assert '"structured_columns"' in html
    assert '"type": "VARCHAR"' in html
    assert '"type": "DECIMAL"' in html
    assert "Manual DDL override is active. Table Name is read from the CREATE TABLE statement." in html

    reset_session()


def test_handoff_save_blocks_manual_ddl_table_name_mismatch():
    from tests.session_helpers import reset_session

    reset_session()
    resp = client.post("/handoffs/save", json={"handoffs": [{
        "name": "customer-staging-table",
        "table_name": "customer_stage",
        "ddl_content": "CREATE TABLE CUSTOMER (customer_id VARCHAR(64));",
        "field_mappings": [],
    }]})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is False
    assert "Manual DDL override is active" in payload["errors"][0]
    assert "CREATE TABLE statement ('CUSTOMER')" in payload["errors"][0]
    assert "visible Table Name is 'customer_stage'" in payload["errors"][0]

    reset_session()


def test_handoff_save_manual_ddl_matching_table_name_saves():
    from tests.session_helpers import get_session, reset_session

    reset_session()
    ddl = "CREATE TABLE CUSTOMER_STAGE (customer_id VARCHAR(64));"
    resp = client.post("/handoffs/save", json={"handoffs": [{
        "name": "customer-staging-table",
        "table_name": "CUSTOMER_STAGE",
        "ddl_content": ddl,
        "field_mappings": [],
    }]})

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    handoff = get_session().data_handoffs[0]
    assert handoff.table_name == "CUSTOMER_STAGE"
    assert handoff.ddl_content == ddl

    reset_session()


def test_handoff_save_allows_unquoted_table_name_case_difference():
    from tests.session_helpers import get_session, reset_session

    reset_session()
    ddl = "CREATE TABLE CUSTOMER_STAGE (customer_id VARCHAR(64));"
    resp = client.post("/handoffs/save", json={"handoffs": [{
        "name": "customer-staging-table",
        "table_name": "customer_stage",
        "ddl_content": ddl,
        "field_mappings": [],
    }]})

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    handoff = get_session().data_handoffs[0]
    assert handoff.table_name == "CUSTOMER_STAGE"

    reset_session()


def test_handoff_save_accepts_schema_qualified_manual_ddl_table_segment():
    from tests.session_helpers import get_session, reset_session

    reset_session()
    ddl = "CREATE TABLE dbo.customer_stage (customer_id VARCHAR(64));"
    resp = client.post("/handoffs/save", json={"handoffs": [{
        "name": "customer-staging-table",
        "table_name": "customer_stage",
        "ddl_content": ddl,
        "field_mappings": [],
    }]})

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert get_session().data_handoffs[0].table_name == "customer_stage"

    reset_session()


def test_handoff_save_preserves_quoted_table_name_case_sensitivity():
    from tests.session_helpers import reset_session

    reset_session()
    ddl = 'CREATE TABLE "Customer_Stage" (customer_id VARCHAR(64));'
    resp = client.post("/handoffs/save", json={"handoffs": [{
        "name": "customer-staging-table",
        "table_name": "customer_stage",
        "ddl_content": ddl,
        "field_mappings": [],
    }]})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is False
    assert "CREATE TABLE statement ('Customer_Stage')" in payload["errors"][0]

    reset_session()


def test_handoff_save_generated_mode_uses_visible_table_name():
    from tests.session_helpers import get_session, reset_session

    reset_session()
    resp = client.post("/handoffs/save", json={"handoffs": [{
        "name": "customer-staging-table",
        "table_name": "customer_stage",
        "ddl_content": None,
        "field_mappings": [],
    }]})

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert get_session().data_handoffs[0].table_name == "customer_stage"

    reset_session()


# ---------------------------------------------------------------------------
# Regression — custom/extended DDL must survive a reload/save cycle unchanged
# ---------------------------------------------------------------------------

def test_handoff_save_preserves_custom_ddl_verbatim():
    """Custom DDL with extra clauses must not be silently rewritten.

    This is the regression test for the Codex P2 finding on PR #26:
    existing ddl_content was being silently replaced with a simplified
    generated form when the DDL was parseable.  The fix ensures the
    original raw DDL is always preserved as the authoritative value.
    """
    from tests.session_helpers import get_session, reset_session, save_session

    reset_session()
    session = get_session()
    session.app_name = "TestApp"
    session.bounded_context = "test"
    session.target_profile = "springboot-legacy-compatible"
    save_session(session)

    # DDL with extra hand-authored clauses a simple generator would drop
    custom_ddl = (
        "CREATE TABLE customer_stage (\n"
        "  customer_id   VARCHAR(64)  NOT NULL,\n"
        "  customer_name VARCHAR(128) DEFAULT 'Unknown',\n"
        "  status_cd     VARCHAR(32)  NOT NULL DEFAULT 'PENDING',\n"
        "  created_at    TIMESTAMP    NOT NULL,\n"
        "  CONSTRAINT pk_customer_stage PRIMARY KEY (customer_id),\n"
        "  CONSTRAINT chk_status CHECK (status_cd IN ('PENDING','ACTIVE','CLOSED'))\n"
        ");"
    )

    # First save — persist the custom DDL
    resp = client.post("/handoffs/save", json={"handoffs": [{
        "name": "customer-staging-table",
        "system": "ETL",
        "type": "staging-table",
        "version": "v1",
        "entity_name": "Customer",
        "ddl_content": custom_ddl,
        "field_mappings": [
            {"source": "Customer.id", "target": "customer_id"},
        ],
    }]})
    assert resp.json()["ok"] is True

    # Simulate a reload/re-save (the server-side save endpoint must echo the
    # ddl_content back unchanged — it never regenerates DDL itself).
    session = get_session()
    handoff = session.data_handoffs[0]
    assert handoff.ddl_content == custom_ddl, (
        "Server side: custom DDL was rewritten — expected verbatim preservation"
    )

    # Constraint/default lines must still be present
    assert "CONSTRAINT pk_customer_stage PRIMARY KEY" in handoff.ddl_content
    assert "CONSTRAINT chk_status CHECK" in handoff.ddl_content
    assert "DEFAULT 'Unknown'" in handoff.ddl_content
    assert "DEFAULT 'PENDING'" in handoff.ddl_content

    reset_session()


def test_handoff_save_with_index_clause_preserved():
    """Extra INDEX / UNIQUE lines in DDL must not be dropped on save."""
    from tests.session_helpers import get_session, reset_session, save_session

    reset_session()
    session = get_session()
    session.app_name = "TestApp"
    session.bounded_context = "test"
    session.target_profile = "springboot-legacy-compatible"
    save_session(session)

    ddl_with_index = (
        "CREATE TABLE acct_stage (\n"
        "  acct_id   VARCHAR(36) NOT NULL,\n"
        "  ref_code  VARCHAR(20),\n"
        "  UNIQUE (ref_code)\n"
        ");"
    )

    resp = client.post("/handoffs/save", json={"handoffs": [{
        "name": "acct-staging",
        "ddl_content": ddl_with_index,
        "field_mappings": [],
    }]})
    assert resp.json()["ok"] is True

    session = get_session()
    saved_ddl = session.data_handoffs[0].ddl_content
    assert saved_ddl == ddl_with_index
    assert "UNIQUE (ref_code)" in saved_ddl

    reset_session()
