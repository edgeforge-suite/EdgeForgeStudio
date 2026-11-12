"""Scenario isolation keeps fixture identities from inheriting rate history."""

from tests.smoke._shared import (
    csrf_headers, make_exportable_smoke_session, new_shared_client,
    post_step1, save_session_for_client, session_for_client,
)
from tests.smoke.l4_driver import _shared_mode_environment


def test_shared_smoke_scenarios_reset_history_but_enforce_each_scenario_limit(tmp_path):
    for stage in ("first", "second"):
        with _shared_mode_environment(tmp_path / stage):
            client, csrf = new_shared_client()
            try:
                post_step1(client, csrf, app_name="Rate Witness", bounded_context="rate-witness",
                           output_path=tmp_path / stage / "output")
                session = session_for_client(client)
                make_exportable_smoke_session(session, entity_name="Record", contract_name="record")
                save_session_for_client(client, session)
                for _ in range(6):
                    response = client.post("/export/write", headers=csrf_headers(csrf))
                    assert response.status_code == 200, response.text
                response = client.post("/export/write", headers=csrf_headers(csrf))
                assert response.status_code == 429
                assert response.json()["retry_after"] > 0
            finally:
                client.close()
