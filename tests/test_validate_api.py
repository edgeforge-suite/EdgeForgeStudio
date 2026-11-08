"""Tests for authoring-time validation API endpoints."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_staging_ddl_warns_for_short_uuid_width():
    response = client.post(
        "/api/validate/staging-ddl",
        json={"ddl": "CREATE TABLE t (acct_id VARCHAR(20) NOT NULL);"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["warnings"] == [
        {
            "column": "acct_id",
            "message": "acct_id is VARCHAR(20) — UUID values need VARCHAR(36). Consider widening.",
        }
    ]


def test_staging_ddl_no_warning_for_uuid_width_36():
    response = client.post(
        "/api/validate/staging-ddl",
        json={"ddl": "CREATE TABLE t (acct_id VARCHAR(36) NOT NULL);"},
    )

    assert response.status_code == 200
    assert response.json() == {"warnings": []}


def test_staging_ddl_non_id_columns_do_not_warn():
    response = client.post(
        "/api/validate/staging-ddl",
        json={"ddl": "CREATE TABLE t (currency VARCHAR(3) NOT NULL);"},
    )

    assert response.status_code == 200
    assert response.json() == {"warnings": []}


def test_staging_ddl_column_name_match_is_case_insensitive():
    response = client.post(
        "/api/validate/staging-ddl",
        json={"ddl": "CREATE TABLE t (ACCT_ID VARCHAR(12) NOT NULL);"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["warnings"][0]["column"] == "ACCT_ID"
    assert "VARCHAR(12)" in payload["warnings"][0]["message"]
