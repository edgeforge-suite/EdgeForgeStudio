"""Route-render snapshots and static JS invariants for CRUD Step 3.

PR-09a is the safety net for the follow-up behavior-identical refactor of
``app/static/js/step3_entities.js``. Studio intentionally has no Node/jsdom or
Playwright harness, so this module captures the current server-rendered Step 3
HTML and documents the static client contract the JS refactor must preserve.

Static invariants verified from the current template/JS:

* ``window.STEP3_ENTITIES_BOOTSTRAP`` is the server-to-client seam. Its keys are
  ``paginationWrapperKeys``, ``initialPhase2Interfaces``, ``kaEnabled``,
  ``initialKsSelectedEntities``, ``initialIdentityReviewEntities``,
  ``identityRoleOptions``, and ``initialKaSummaryReviewStatuses``.
* Server-rendered common hooks for populated entity states include
  ``#entity-list``, ``#save-status``, ``#op-no-entity-hint``, ``#op-table``,
  ``#phase2``, ``#interface-panels``, ``.entity-checkbox``, ``.op-checkbox``,
  ``.op-entity-select``, ``.identity-role-select``, ``.identity-role-impact``,
  ``data-canonical``, and ``data-candidates``.
* Server-rendered KA hooks when Knowledge Assist is enabled include
  ``[data-step3-ka-full-review]``, ``[data-step3-ka-full-review-open]``,
  ``[data-step3-ka-full-review-close]``, ``[data-ka-full-review-body]``,
  ``[data-ka-full-review-count]``, ``[data-ka-full-review-save]``,
  ``[data-ka-full-review-status]``, ``[data-ka-full-refresh]``, and
  ``[data-ka-full-filter]``.
* Runtime-generated or query-only hooks used by ``step3_entities.js`` but not
  necessarily present in the initial server render include ``#ks-entity-select``,
  ``#ks-evidence-viewer``, ``#ks-loading``, ``#ks-save-review-btn``,
  ``#ks-suggestion-list``, ``#rail-evidence-panel``,
  ``#rail-suggestions-panel``, ``.mapping-source``, ``.mapping-target``,
  ``.ks-edit-description``, ``.ks-edit-field-name``, ``.ks-edit-nullable``,
  ``.ks-edit-type``, ``.ks-staged-status``, ``data-iface-name``,
  ``data-ka-full-field-name``, ``data-ka-full-field-type``,
  ``data-ka-full-field-nullable``, ``data-ka-full-field-description``,
  ``data-ka-full-identity-role``, ``data-ka-full-identity-impact``, and
  ``data-ka-full-validation-payload``. PR-09 must preserve these generated
  hooks even though a pure server-render test cannot execute the JS that creates
  all of them.
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    ClassifiedOperation,
    IdentityRoleDecision,
    KSReviewHistoryEntry,
    OperationSample,
    UpstreamInterface,
)
from app.routes.entities import assist_service
from app.services.assist_service import SuggestionBadge
from tests.session_helpers import get_session, reset_session, save_session

client = TestClient(app)

SNAPSHOT_DIR = Path(__file__).parent / "fixtures" / "step3_render_snapshots"
SNAPSHOT_STATES = (
    "empty",
    "single_entity",
    "many_fields",
    "roles_assigned",
    "ka_review_open",
)
BOOTSTRAP_KEYS = [
    "paginationWrapperKeys",
    "initialPhase2Interfaces",
    "kaEnabled",
    "initialKsSelectedEntities",
    "initialIdentityReviewEntities",
    "identityRoleOptions",
    "initialKaSummaryReviewStatuses",
]

_CSRF_META_RE = re.compile(
    r'(<meta\s+name="edgeforge-csrf-token"\s+content=")[^"]*(")'
)
_CSRF_FIELD_RE = re.compile(
    r'(<input type="hidden" name="_edgeforge_csrf_token" value=")[^"]*(")'
)
_BOOTSTRAP_RE = re.compile(
    r"window\.STEP3_ENTITIES_BOOTSTRAP = \{\n(?P<body>.*?)\n\};",
    re.S,
)


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


@pytest.fixture(autouse=True)
def _pin_retired_refresh_flag_value(monkeypatch):
    """PR-24 snapshots capture the single default-on Step 3 render.

    Pin the retired environment variable to false to prove it no longer
    selects an alternate markup path.
    """
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")


def _normalize_step3_html(html: str) -> str:
    """Strip per-request CSRF tokens and trailing line whitespace so Step 3
    renders can be byte-compared and the committed fixtures pass
    `git diff --check` (trailing whitespace is not semantically meaningful
    for HTML rendering -- stripping it does not weaken the snapshot as a
    regression guard for PR-09's refactor)."""

    html = _CSRF_META_RE.sub(r"\1<CSRF>\2", html)
    html = _CSRF_FIELD_RE.sub(r"\1<CSRF>\2", html)
    html = re.sub(r"[ \t]+(\r?\n)", r"\1", html)
    return html


def _extract_bootstrap(html: str) -> dict:
    match = _BOOTSTRAP_RE.search(html)
    assert match, "STEP3_ENTITIES_BOOTSTRAP block not found"
    body = match.group("body")
    jsonish = "{\n" + re.sub(r"^(\s*)([A-Za-z][A-Za-z0-9_]*):", r'\1"\2":', body, flags=re.M) + "\n}"
    jsonish = re.sub(r",\s*\n}", "\n}", jsonish)
    return json.loads(jsonish)


def _snapshot_path(state: str) -> Path:
    return SNAPSHOT_DIR / f"{state}.html"


def _seed_empty() -> None:
    session = get_session()
    session.app_name = "Step3 Empty"
    session.bounded_context = "snapshot-empty"
    session.app_archetype = "crud"
    session.target_profile = "springboot-legacy-compatible"
    session.classified_entities = []
    session.classified_operations = []
    save_session(session)


def _customer_fields(count: int = 4) -> list[ClassifiedField]:
    base_fields = [
        ClassifiedField(name="customerId", type="string", required=True, is_id=True),
        ClassifiedField(name="status", type="string", required=True),
        ClassifiedField(name="openedDate", type="date"),
        ClassifiedField(name="balance", type="decimal"),
    ]
    if count <= len(base_fields):
        return base_fields[:count]
    return [
        *base_fields,
        *[
            ClassifiedField(name=f"customField{index:02d}", type="string")
            for index in range(1, count - len(base_fields) + 1)
        ],
    ]


def _customer_operations() -> list[ClassifiedOperation]:
    return [
        ClassifiedOperation(
            name="createCustomer",
            method="POST",
            path="/customers",
            resource="customers",
            entity_candidates=["Customer"],
        ),
        ClassifiedOperation(
            name="getCustomer",
            method="GET",
            path="/customers/{customerId}",
            resource="customers",
            entity_candidates=["Customer"],
        ),
    ]


def _seed_customer_session(*, field_count: int = 4) -> None:
    session = get_session()
    session.app_name = "Step3 Customer"
    session.bounded_context = "snapshot-customer"
    session.app_archetype = "crud"
    session.target_profile = "springboot-legacy-compatible"
    session.classified_entities = [
        ClassifiedEntity(
            name="CustomerResponse",
            canonical_name="Customer",
            classification="entity",
            fields=_customer_fields(field_count),
            reason="OpenAPI schema selected as canonical entity.",
        )
    ]
    session.classified_operations = _customer_operations()
    session.selected_entity_names = ["CustomerResponse"]
    session.selected_operation_names = ["createCustomer", "getCustomer"]
    save_session(session)


def _seed_single_entity() -> None:
    _seed_customer_session(field_count=4)


def _seed_many_fields() -> None:
    _seed_customer_session(field_count=24)


def _seed_roles_assigned() -> None:
    _seed_customer_session(field_count=5)
    session = get_session()
    session.identity_role_decisions = [
        IdentityRoleDecision(
            entity="Customer",
            field="customerId",
            role="persistence_id",
            reviewed_at="2026-07-01T10:00:00+00:00",
        ),
        IdentityRoleDecision(
            entity="Customer",
            field="status",
            role="business_key",
            reviewed_at="2026-07-02T10:00:00+00:00",
        ),
    ]
    save_session(session)


def _seed_ka_review_open() -> None:
    _seed_customer_session(field_count=4)
    session = get_session()
    session.app_name = "Step3 KA Review"
    session.capabilities.knowledge_assist_enabled = True
    session.project_id = "step3-snapshot-ks"
    session.ks_project_id = "step3-snapshot-ks"
    session.ks_active = True
    session.upstream_interfaces = [
        UpstreamInterface(
            name="customer-customer-api",
            entity_name="Customer",
            operations=[
                OperationSample(
                    name="getCustomer",
                    response_sample_content='{"customerId":"C-001","status":"ACTIVE"}',
                )
            ],
        )
    ]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="field-customer-tier",
            type="field",
            status="accepted",
            manifest_path="entities.Customer.fields.customerTier",
            reviewed_at="2026-07-03T10:00:00+00:00",
            review_context={"entity": "Customer"},
        ),
        KSReviewHistoryEntry(
            suggestion_id="validation-status-required",
            type="validation",
            status="edited",
            manifest_path="entities.Customer.fields.status.validations.not-null",
            reviewed_at="2026-07-03T11:00:00+00:00",
            review_context={"entity": "Customer"},
        ),
        KSReviewHistoryEntry(
            suggestion_id="identity-customer-id",
            type="identity_role",
            status="rejected",
            manifest_path="entities.Customer.fields.customerId.identity_role",
            reviewed_at="2026-07-03T12:00:00+00:00",
            review_context={"entity": "Customer"},
        ),
    ]
    save_session(session)


STATE_BUILDERS = {
    "empty": _seed_empty,
    "single_entity": _seed_single_entity,
    "many_fields": _seed_many_fields,
    "roles_assigned": _seed_roles_assigned,
    "ka_review_open": _seed_ka_review_open,
}


def _fake_step3_badge_counts(*_args, **_kwargs):
    return (
        [
            SuggestionBadge(
                scope="validations",
                label="2 validation hints",
                count=2,
                entity="Customer",
                drawer_url="/entities/ks/drawer?scope=validations&entity=Customer",
            )
        ],
        [
            SuggestionBadge(
                scope="identity_role",
                label="1 identity role suggestion",
                count=1,
                entity="Customer",
                drawer_url="/entities/ks/drawer?scope=identity_role&entity=Customer",
            )
        ],
    )


@contextmanager
def _route_patches_for_state(state: str):
    if state == "ka_review_open":
        with patch.object(
            assist_service,
            "batch_fetch_step3_badge_counts",
            side_effect=_fake_step3_badge_counts,
        ):
            yield
        return
    yield


def _render_state(state: str) -> str:
    reset_session()
    STATE_BUILDERS[state]()
    with _route_patches_for_state(state):
        response = client.get("/entities")
    assert response.status_code == 200
    return _normalize_step3_html(response.text)


@pytest.mark.parametrize("state", SNAPSHOT_STATES)
def test_step3_route_render_snapshots_match_current_baseline(state: str) -> None:
    actual = _render_state(state)
    expected = _snapshot_path(state).read_text(encoding="utf-8")

    assert actual == expected


@pytest.mark.parametrize("state", SNAPSHOT_STATES)
def test_step3_bootstrap_contract_keys_are_stable(state: str) -> None:
    bootstrap = _extract_bootstrap(_render_state(state))

    assert list(bootstrap) == BOOTSTRAP_KEYS
    assert isinstance(bootstrap["paginationWrapperKeys"], list)
    assert isinstance(bootstrap["initialPhase2Interfaces"], list)
    assert isinstance(bootstrap["kaEnabled"], bool)
    assert isinstance(bootstrap["initialKsSelectedEntities"], list)
    assert isinstance(bootstrap["initialIdentityReviewEntities"], list)
    assert isinstance(bootstrap["identityRoleOptions"], list)
    assert isinstance(bootstrap["initialKaSummaryReviewStatuses"], dict)


def test_step3_bootstrap_values_cover_representative_states() -> None:
    empty = _extract_bootstrap(_render_state("empty"))
    roles = _extract_bootstrap(_render_state("roles_assigned"))
    ka = _extract_bootstrap(_render_state("ka_review_open"))

    assert empty["kaEnabled"] is False
    assert empty["initialKsSelectedEntities"] == []
    assert empty["initialIdentityReviewEntities"] == []
    assert roles["kaEnabled"] is False
    assert roles["initialIdentityReviewEntities"] == ["Customer"]
    assert ka["kaEnabled"] is True
    assert ka["initialKsSelectedEntities"] == ["Customer"]
    assert ka["initialIdentityReviewEntities"] == ["Customer"]
    assert ka["initialKaSummaryReviewStatuses"]["field:suggestion:field-customer-tier"] == "accepted"
    assert (
        ka["initialKaSummaryReviewStatuses"]["validation:suggestion:validation-status-required"]
        == "edited"
    )
    assert ka["initialKaSummaryReviewStatuses"]["identity_role:suggestion:identity-customer-id"] == (
        "rejected"
    )


def test_step3_server_rendered_common_dom_hooks_are_present() -> None:
    html = _render_state("single_entity")

    for hook in (
        'id="entity-list"',
        'id="save-status"',
        'id="op-no-entity-hint"',
        'id="op-table"',
        'id="phase2"',
        'id="interface-panels"',
        'class="entity-checkbox"',
        'class="op-checkbox"',
        'class="op-entity-select"',
        'class="identity-role-select"',
        'class="text-muted text-sm identity-role-impact"',
        'data-canonical="Customer"',
        'data-candidates="Customer"',
    ):
        assert hook in html


def test_step3_empty_snapshot_preserves_no_entities_branch() -> None:
    html = _render_state("empty")

    assert "No entities classified yet" in html
    assert 'id="entity-list"' not in html
    assert 'id="op-table"' not in html


def test_step3_many_fields_snapshot_preserves_large_identity_review_table() -> None:
    html = _render_state("many_fields")

    assert "24 fields" in html
    assert html.count('class="identity-role-select"') == 24
    assert 'data-field="customField20"' in html


def test_step3_roles_assigned_snapshot_preserves_selected_role_markup() -> None:
    html = _render_state("roles_assigned")

    assert 'data-field="customerId"' in html
    assert 'data-field="status"' in html
    assert "Reviewed 2026-07-01" in html
    assert "Reviewed 2026-07-02" in html
    assert 'data-affects-engine="true" selected>persistence_id</option>' in html
    assert 'data-affects-engine="false" selected>business_key</option>' in html
    assert "Engine-active" in html
    assert "Metadata-only" in html


def test_step3_ka_snapshot_preserves_full_review_static_hooks() -> None:
    html = _render_state("ka_review_open")

    for hook in (
        "Knowledge Assist Review",
        'data-step3-ka-full-review',
        'data-step3-ka-full-review-open',
        'data-step3-ka-full-review-close',
        'data-ka-full-review-body',
        'data-ka-full-review-count',
        'data-ka-full-review-save',
        'data-ka-full-review-status',
        'data-ka-full-refresh',
        'data-ka-full-filter="entity"',
        'data-ka-full-filter="type"',
        'data-ka-full-filter="category"',
        'data-ka-full-filter="status"',
        'data-ka-summary-type="field"',
        'data-ka-summary-type="validation"',
        'data-ka-summary-type="identity_role"',
        'data-ka-summary-status="accepted"',
        'data-ka-summary-status="edited"',
        'data-ka-summary-status="rejected"',
    ):
        assert hook in html
    assert "Pending: 2" not in html
    assert "Open review to inspect" in html
