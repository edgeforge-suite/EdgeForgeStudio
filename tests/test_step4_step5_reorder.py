"""Tests for the Step 4 / Step 5 workflow reorder."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from tests.session_helpers import get_session, reset_session

client = TestClient(app)


def test_handoffs_page_is_now_step4():
    resp = client.get("/handoffs")
    assert resp.status_code == 200
    html = resp.text
    assert "Step 4: Data Handoffs" in html
    assert 'href="/entities"' in html
    assert 'href="/downstream"' in html


def test_downstream_page_is_now_step5():
    resp = client.get("/downstream")
    assert resp.status_code == 200
    html = resp.text
    assert "Step 5: Downstream Interfaces" in html
    assert 'href="/handoffs"' in html
    assert 'href="/rules"' in html


def test_downstream_page_includes_restore_escape_and_save_guards():
    resp = client.get("/downstream")
    assert resp.status_code == 200
    html = resp.text

    assert '<script src="/static/js/studio.js"></script>' in html
    assert 'placeholder="${escapeHtml(srcHint)}"' in html
    assert "Some downstream interfaces could not be rendered:" in html
    assert "async function saveNewInterfaces()" in html
    assert "card.dataset.restoredInterface !== 'true'" in html
    assert "removeInterfaceCard(this)" in html
    assert "postJSON('/downstream/save'" not in html


def test_step3_next_now_redirects_to_handoffs():
    resp = client.get("/entities/next", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/handoffs"


def test_handoffs_next_redirects_to_downstream():
    resp = client.get("/handoffs/next", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/downstream"


def test_handoffs_page_renders_after_saving_a_handoff():
    reset_session()


def test_handoffs_page_explains_manual_ddl_mode_and_regeneration_action():
    reset_session()

    response = client.get("/handoffs")

    assert response.status_code == 200
    assert "Manual DDL override is active when this field has text." in response.text
    assert "Structured field changes will not update this DDL until you regenerate from fields" in response.text
    assert "Regenerate DDL from fields" in response.text
    assert "Generated from fields" in response.text

    reset_session()

    save_resp = client.post("/handoffs/save", json={
        "handoffs": [
            {
                "name": "account-staging",
                "type": "staging-table",
                "entity_name": "Account",
                "ddl_content": "CREATE TABLE account_stage (account_id VARCHAR(36) NOT NULL);",
                "field_mappings": [
                    {"source": "Account.accountId", "target": "account_id"},
                ],
            }
        ]
    })
    assert save_resp.status_code == 200
    assert save_resp.json()["ok"] is True

    resp = client.get("/handoffs")
    assert resp.status_code == 200
    assert "account-staging" in resp.text

    reset_session()


def test_downstream_page_renders_after_saving_an_interface():
    reset_session()


def _synthetic_file_interfaces(width):
    return [
        {"name": f"{name.lower()}-file", "type": "file-fixed-width", "entity_name": name,
         "layout_fields": [
             {"name": "RECORD_ID", "start": 1, "length": width},
             {"name": "label", "start": width + 1, "length": 16},
         ], "field_mappings": [
             {"source": f"{name}.recordId", "target": "RECORD_ID"},
             {"source": f"{name}.label", "target": "label"},
         ]}
        for name in ("Workspace", "Item", "Tag")
    ]


def test_downstream_save_preserves_multiple_independent_interfaces():
    reset_session()
    interfaces = _synthetic_file_interfaces(40)
    response = client.post("/downstream/save", json={"interfaces": interfaces})
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["count"] == 3
    assert [row.name for row in get_session().downstream_interfaces] == [
        "workspace-file", "item-file", "tag-file",
    ]
    page = client.get("/downstream")
    assert page.status_code == 200
    for name in ("workspace-file", "item-file", "tag-file"):
        assert name in page.text
    reset_session()


def test_downstream_restore_keeps_three_interfaces_with_uuid_warnings():
    reset_session()
    response = client.post("/downstream/save", json={"interfaces": _synthetic_file_interfaces(20)})
    assert response.status_code == 200
    assert response.json()["ok"] is True
    page = client.get("/downstream")
    assert page.status_code == 200
    for name in ("workspace-file", "item-file", "tag-file", "RECORD_ID"):
        assert name in page.text
    assert "This field may contain a UUID-style identifier" in page.text
    reset_session()


def test_downstream_save_warns_when_interface_has_no_layout_or_mapping():
    reset_session()


def test_downstream_warning_ui_renders_server_messages_then_continues_to_rules():
    response = client.get("/downstream")

    assert response.status_code == 200
    assert "Saved new downstream interfaces with guidance." in response.text
    assert "showWarningStatusList(" in response.text
    assert "setTimeout(() => location.href = '/rules'" in response.text
    assert "document.createElement('li')" in response.text
    assert ".textContent = item" in response.text
    assert "fixed-width ID warning(s) shown below" not in response.text

    save_resp = client.post(
        "/downstream/save",
        json={
            "interfaces": [
                {
                    "name": "empty-eod-file",
                    "type": "file-fixed-width",
                    "entity_name": "Customer",
                    "layout_fields": [],
                    "field_mappings": [],
                }
            ]
        },
    )

    assert save_resp.status_code == 200
    warnings = save_resp.json()["warnings"]
    assert any("No visual layout rows are saved" in warning["message"] for warning in warnings)
    assert any("No field mappings are saved" in warning["message"] for warning in warnings)

    reset_session()

    save_resp = client.post("/downstream/save", json={
        "interfaces": [
            {
                "name": "customer-eod-file",
                "type": "file-fixed-width",
                "entity_name": "Customer",
                "layout_fields": [
                    {"name": "customer_id", "start": 1, "length": 36},
                    {"name": "status", "start": 37, "length": 12},
                ],
                "field_mappings": [
                    {"source": "Customer.customerId", "target": "customer_id"},
                    {"source": "Customer.status", "target": "status"},
                ],
                "sample_content": None,
            }
        ]
    })
    assert save_resp.status_code == 200
    assert save_resp.json()["ok"] is True

    resp = client.get("/downstream")
    assert resp.status_code == 200
    assert "customer-eod-file" in resp.text

    reset_session()


def test_downstream_next_redirects_to_rules():
    resp = client.get("/downstream/next", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/rules"


def test_rules_page_back_link_now_points_to_downstream():
    resp = client.get("/rules")
    assert resp.status_code == 200
    assert 'href="/downstream"' in resp.text
