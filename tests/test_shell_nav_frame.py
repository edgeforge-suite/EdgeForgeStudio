import re

from fastapi.testclient import TestClient

from app.main import app
from app.models.project import ClassifiedEntity, KafkaConfig, KafkaRouteModel, KafkaTopicPair
from app.services.nav_context import build_nav_context
from tests.session_helpers import get_session, reset_session, save_session
from tests.test_package_writer import _full_session

client = TestClient(app)

_CSRF_META_RE = re.compile(
    r'(<meta\s+name="edgeforge-csrf-token"\s+content=")[^"]*(")'
)
_CSRF_FIELD_RE = re.compile(
    r'(<input type="hidden" name="_edgeforge_csrf_token" value=")[^"]*(")'
)


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _normalize_csrf(html: str) -> str:
    """Strip the per-request signed CSRF token so two renders can be byte-diffed.

    The token embeds an `iat`/`exp` timestamp and a signature (app/services/csrf.py),
    so it differs between any two requests even with everything else held constant.
    It is the only per-request nondeterminism in a Step 1 render (no session id,
    timestamp, or uuid is otherwise embedded in step1_project.html or base.html).
    """

    html = _CSRF_META_RE.sub(r"\1<CSRF>\2", html)
    html = _CSRF_FIELD_RE.sub(r"\1<CSRF>\2", html)
    return html


def test_build_nav_context_ux_refresh_defaults_on(monkeypatch) -> None:
    monkeypatch.delenv("EDGEFORGE_STUDIO_UX_REFRESH", raising=False)
    monkeypatch.delenv("EDGEFORGE_STUDIO_UX_SPLIT", raising=False)
    session = get_session()

    nav = build_nav_context(session, "/")

    assert nav["ux_refresh"] is True
    assert nav["ux_split"] is True


def test_build_nav_context_ux_refresh_compatibility_keys_stay_on(monkeypatch) -> None:
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "on")
    session = get_session()

    nav = build_nav_context(session, "/")

    assert nav["ux_refresh"] is True
    assert nav["ux_split"] is True


def test_retired_refresh_flag_cannot_disable_the_refreshed_shell(monkeypatch) -> None:
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "true")
    session = get_session()

    nav = build_nav_context(session, "/")

    assert nav["ux_refresh"] is True
    assert nav["ux_split"] is True


def test_retired_split_flag_cannot_disable_desktop_split(monkeypatch) -> None:
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.delenv("EDGEFORGE_STUDIO_UX_SPLIT", raising=False)
    session = get_session()

    nav = build_nav_context(session, "/")

    assert nav["ux_refresh"] is True
    assert nav["ux_split"] is True


def test_step1_refreshed_body_class_is_on_by_default() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert 'class="ux-refresh"' in response.text


def test_retired_flag_values_render_identical_default_on_shell(monkeypatch) -> None:
    """PR-24 retires both deployment switches; old env values are inert."""
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "false")
    false_render = _normalize_csrf(client.get("/").text)

    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "true")
    true_render = _normalize_csrf(client.get("/").text)

    assert 'class="ux-refresh"' in false_render
    assert false_render == true_render


def test_base_shell_renders_right_rail_without_placeholder_drawer_toggle() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert 'id="shell-right-rail"' in response.text
    assert 'id="shell-bottom-drawer"' not in response.text
    assert "Toggle Right Rail" in response.text
    assert "Toggle Review Drawer" not in response.text
    assert "Context Panels" in response.text


def test_shell_header_shows_step_indicator_and_archetype() -> None:
    session = get_session()
    session.app_name = "DDA App"
    session.bounded_context = "dda"
    session.app_archetype = "crud"
    save_session(session)

    response = client.get("/")

    assert response.status_code == 200
    assert "DDA App" in response.text
    assert '<link rel="icon" href="/static/favicon.svg">' in response.text
    assert "Governed authoring workspace" in response.text
    assert "Step 1 of 8" in response.text
    assert ">CRUD<" in response.text
    assert response.text.count("wizard-nav-marker is-step-marker") == 1


def test_passthrough_shell_marks_not_applicable_slots() -> None:
    session = get_session()
    session.app_name = "Router"
    session.bounded_context = "payments"
    session.app_archetype = "passthrough-router"
    save_session(session)

    response = client.get("/passthrough")

    assert response.status_code == 200
    assert response.text.count("Not applicable") >= 2
    assert "/upstream" in response.text
    assert "/passthrough" in response.text
    assert response.text.count("wizard-nav-marker is-step-marker") == 1


def test_kafka_shell_uses_topic_ingest_and_route_model_labels() -> None:
    session = get_session()
    session.app_name = "Kafka Hub"
    session.bounded_context = "payments"
    session.app_archetype = "kafka-integration"
    session.kafka_config = KafkaConfig(consumer_group="payment-mediation-group")
    session.kafka_topic_pairs = [
        KafkaTopicPair(
            route_name="payment-posted",
            upstream_topic="abc.payments.posted.v1",
            downstream_topic="xyz.ledger.entries.v1",
        )
    ]
    session.kafka_route_models = [
        KafkaRouteModel(route_name="payment-posted", pattern="fire-and-forget")
    ]
    save_session(session)

    response = client.get("/kafka/topics")

    assert response.status_code == 200
    assert "Step 2 of 8" in response.text
    assert "Topic Ingest" in response.text
    assert "Route Model" in response.text
    assert "Transform Mappings" in response.text
    assert response.text.count("wizard-nav-marker is-step-marker") == 1


def test_review_page_content_still_renders_inside_shell() -> None:
    session = _full_session()
    session.capabilities.knowledge_assist_enabled = True
    save_session(session)

    response = client.get("/review")

    assert response.status_code == 200
    assert 'class="shell-main"' in response.text
    assert "Step 7: Review Checkpoint" in response.text
    assert "Evidence Trail Links / Exported Evidence" in response.text
    assert 'data-shell-drawer-default="expanded"' in response.text
    assert 'id="shell-bottom-drawer"' in response.text
    assert "Toggle Review Drawer" in response.text


def test_crud_step3_renders_with_active_right_rail_surfaces() -> None:
    session = get_session()
    session.app_name = "Accounts"
    session.bounded_context = "accounts"
    session.app_archetype = "crud"
    session.target_profile = "springboot-legacy-compatible"
    session.classified_entities = []
    save_session(session)

    response = client.get("/entities")

    assert response.status_code == 200
    assert 'data-shell-rail-default="collapsed"' in response.text

    session.classified_entities = [
        ClassifiedEntity(
            name="AccountResponse",
            canonical_name="Account",
            classification="entity",
        )
    ]
    session.selected_entity_names = ["AccountResponse"]
    session.capabilities.knowledge_assist_enabled = True
    session.project_id = "studio-ks-step3"
    session.ks_project_id = "studio-ks-step3"
    session.ks_active = True
    save_session(session)

    response = client.get("/entities")

    assert response.status_code == 200
    assert 'data-shell-rail-default="expanded"' in response.text
    assert 'id="rail-ka-summary-panel"' in response.text
    assert 'id="rail-evidence-panel"' not in response.text
    assert "Knowledge Assist Summary" in response.text


def test_rules_page_renders_active_conflicts_rail_for_step6() -> None:
    session = get_session()
    session.app_name = "Rules App"
    session.bounded_context = "accounts"
    session.app_archetype = "crud"
    save_session(session)

    response = client.get("/rules")

    assert response.status_code == 200
    assert 'data-shell-rail-default="collapsed"' in response.text
    assert 'id="rail-conflicts-panel"' in response.text
    assert "Conflicts Summary" in response.text


def test_upstream_page_renders_separate_shell_and_ingest_tab_scopes() -> None:
    session = get_session()
    session.app_name = "Payments"
    session.bounded_context = "payments"
    session.app_archetype = "crud"
    save_session(session)

    response = client.get("/upstream")

    assert response.status_code == 200
    assert 'data-tab-group="shell-drawer"' not in response.text
    assert 'data-tab-group="upstream-ingest"' in response.text
    assert 'id="ingest-tabs"' in response.text


def test_crud_wizard_steps_after_step1_render_previous_buttons() -> None:
    session = _full_session()
    save_session(session)

    expected_previous_links = {
        "/upstream": "/",
        "/entities": "/upstream",
        "/handoffs": "/entities",
        "/downstream": "/handoffs",
        "/rules": "/downstream",
        "/review": "/rules",
        "/export": "/review",
    }

    for route, previous_href in expected_previous_links.items():
        response = client.get(route)

        assert response.status_code == 200
        assert f'href="{previous_href}"' in response.text
        assert "Previous" in response.text


def test_kafka_wizard_steps_after_step1_render_previous_buttons() -> None:
    session = get_session()
    session.app_name = "Kafka Hub"
    session.bounded_context = "payments"
    session.app_archetype = "kafka-integration"
    session.kafka_config = KafkaConfig(consumer_group="payment-mediation-group")
    save_session(session)

    expected_previous_links = {
        "/kafka/topics": "/",
        "/kafka/routes": "/kafka/topics",
        "/kafka/transforms": "/kafka/routes",
    }

    for route, previous_href in expected_previous_links.items():
        response = client.get(route)

        assert response.status_code == 200
        assert f'href="{previous_href}"' in response.text
        assert "Previous" in response.text
