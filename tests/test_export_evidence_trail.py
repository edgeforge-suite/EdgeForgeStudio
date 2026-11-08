"""Tests for Step 8 evidence-trail export behavior."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.integrations.ks_integration import KSUnavailableError
from app.main import app
from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    DataHandoff,
    DownstreamInterface,
    EntityRules,
    FieldMapping,
    IdentityRoleDecision,
    KafkaRouterTargetTransform,
    KafkaRouterTransformRow,
    KafkaRouteTransform,
    KafkaTransformRow,
    KSEvidenceLink,
    KSReviewHistoryEntry,
    LayoutField,
    PassthroughTransform,
    ProjectSession,
    RuleEntry,
    SoapCanonicalInvocationConfig,
    SoapCanonicalOperationConfig,
    SoapRequestMapping,
    SoapResponseMapping,
    SoapReturnMapping,
    UpstreamInterface,
)
from tests.session_helpers import get_session, reset_session, save_session
from tests.test_package_writer import _full_session

client = TestClient(app)


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _seed_export_session(tmp_path: Path) -> None:
    session = _full_session()
    # Keep the shared Knowledge Assist export tests focused on KA-derived
    # evidence by excluding edge file contracts. Deterministic human-authored
    # file-contract evidence is exercised by the dedicated tests below.
    session.downstream_interfaces = [
        iface
        for iface in session.downstream_interfaces
        if iface.type not in {"file-fixed-width", "file-csv"}
    ]
    session.output_path = str(tmp_path)
    session.project_id = "proj-1"
    session.ks_project_id = "proj-1"
    session.ks_active = True
    session.capabilities.knowledge_assist_enabled = True
    save_session(session)


def test_identity_role_decisions_do_not_create_evidence_trail_links(tmp_path):
    _seed_export_session(tmp_path)
    session = get_session()
    session.capabilities.knowledge_assist_enabled = False
    session.ks_active = False
    session.classified_entities = [
        ClassifiedEntity(
            name="Account",
            fields=[
                ClassifiedField(name="accountId", type="string", is_id=True),
                ClassifiedField(name="label", type="string"),
                ClassifiedField(name="category", type="string"),
                ClassifiedField(name="status", type="string"),
            ],
        ),
        ClassifiedEntity(
            name="Transaction",
            fields=[ClassifiedField(name="transactionRowId", type="string")],
        )
    ]
    session.selected_entity_names = ["Account", "Transaction"]
    session.identity_role_decisions = [
        IdentityRoleDecision(
            entity="Transaction",
            field="transactionRowId",
            role="persistence_id",
            provenance="knowledge-assist",
            reviewed_at="2026-05-06T12:00:00+00:00",
        )
    ]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="id-role-1",
            type="identity_role",
            status="accepted",
            manifest_path="entities.Transaction.fields.transactionRowId",
            reviewed_at="2026-05-06T12:00:00+00:00",
            review_context={
                "entity": "Transaction",
                "field": "transactionRowId",
                "role": "persistence_id",
            },
        )
    ]
    save_session(session)

    response = client.post("/export/write")

    assert response.status_code == 200
    payload = response.json()
    sidecar = json.loads((Path(payload["output_dir"]) / "evidence-trail.json").read_text(encoding="utf-8"))
    assert sidecar["evidence_links"] == []
    assert "identity_role" not in json.dumps(sidecar)


def test_export_write_writes_evidence_trail_and_appends_manifest_revision(monkeypatch, tmp_path):
    _seed_export_session(tmp_path)
    session = get_session()
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["s-1"]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="s-1",
            type="field",
            status="accepted",
            manifest_path="entities.Account.fields.account_id",
            reviewed_at="2026-04-20T12:00:00+00:00",
        )
    ]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="entities.Account.fields.account_id",
            suggestion_id="s-1",
            provenance="ai-accepted",
        )
    ]
    save_session(session)

    class FakeClient:
        def get_suggestion_evidence_chain(
            self,
            project_id: str,
            scope: str,
            suggestion_id: str,
        ):
            assert project_id == "proj-1"
            assert scope == "fields"
            assert suggestion_id == "s-1"
            return {
                "suggestion": {
                    "entity": "Account",
                    "field_name": "account_id",
                    "consistency_score": 0.92,
                },
                "evidence_chunks": [
                    {
                        "citation": {
                            "document_id": "doc-1",
                            "document_name": "Account BRD.pdf",
                            "chunk_id": "chunk-1",
                            "content_hash": "sha256:abc123",
                            "parser_version": "pdf-v1",
                            "section": "Section 4.1",
                            "snippet": "Account IDs must be unique.",
                            "page": 7,
                        }
                    }
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.evidence_trail.ks_client", fake_ks_client)

    response = client.post("/export/write")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert "evidence-trail.json" in payload["files"]
    assert any(item["name"] == "evidence-trail.json" for item in payload["export_artifacts"]["artifacts"])
    assert payload["latest_revision"]["revision_id"] == payload["revision_id"]

    project_dir = Path(payload["output_dir"])
    sidecar = json.loads((project_dir / "evidence-trail.json").read_text(encoding="utf-8"))
    assert sidecar["schema_version"] == "1.1"
    assert sidecar["project_id"] == "proj-1"
    assert sidecar["manifest_revision_id"] == payload["revision_id"]
    assert sidecar["evidence_links"] == [
        {
            "manifest_path": "entities.Account.fields.account_id",
            "suggestion_type": "field",
            "provenance": "ai-accepted",
            "suggestion_id": "s-1",
            "confidence": 0.92,
            "citations": [
                {
                    "document_id": "doc-1",
                    "document_name": "Account BRD.pdf",
                    "chunk_id": "chunk-1",
                    "content_hash": "sha256:abc123",
                    "parser_version": "pdf-v1",
                    "page": 7,
                    "section": "Section 4.1",
                    "snippet": "Account IDs must be unique.",
                }
            ],
        }
    ]
    assert sidecar["provenance_summary"]["ai_accepted"] == 1
    assert sidecar["provenance_summary"]["ai_edited"] == 0
    assert sidecar["provenance_summary"]["no_evidence"] == 0
    assert sidecar["provenance_summary"]["by_type"] == {
        "field": 1,
        "validation": 0,
        "rule": 0,
        "cross_entity_rule": 0,
        "mapping": 0,
        "transform": 0,
    }

    session = get_session()
    assert session.last_export_path == str(project_dir)
    revision = session.ks_workspace_state.manifest_revisions[-1]
    assert revision.revision_id == sidecar["manifest_revision_id"]
    assert revision.exported_at == sidecar["exported_at"]
    assert revision.manifest_hash == payload["manifest_hash"]
    assert revision.export_path == str(project_dir)
    assert revision.archetype == session.app_archetype
    assert revision.target_profile == session.target_profile


def test_export_write_writes_empty_valid_sidecar_when_no_evidence_links(monkeypatch, tmp_path):
    _seed_export_session(tmp_path)

    @contextmanager
    def unexpected_ks_client(**kwargs):
        raise AssertionError("ks_client should not be used for an empty evidence workspace")
        yield

    monkeypatch.setattr("app.services.evidence_trail.ks_client", unexpected_ks_client)

    response = client.post("/export/write")

    assert response.status_code == 200
    payload = response.json()
    project_dir = Path(payload["output_dir"])
    sidecar = json.loads((project_dir / "evidence-trail.json").read_text(encoding="utf-8"))
    assert sidecar["schema_version"] == "1.1"
    assert sidecar["evidence_links"] == []
    assert sidecar["provenance_summary"] == {
        "human_authored": 0,
        "ai_accepted": 0,
        "ai_edited": 0,
        "no_evidence": 0,
        "by_type": {
            "field": 0,
            "validation": 0,
            "rule": 0,
            "cross_entity_rule": 0,
            "mapping": 0,
            "transform": 0,
        },
    }


def test_export_write_expands_non_field_evidence_links_for_v1_1(monkeypatch, tmp_path):
    _seed_export_session(tmp_path)
    session = get_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(
                    field="status",
                    type="not-null",
                    suggestion_id="v-1",
                    suggestion_type="validation",
                    applied_by="knowledge_assist",
                    generated_by_ka=True,
                    ka_review_status="accepted",
                ),
                RuleEntry(
                    field="status",
                    type="allowed-values",
                    values=["ACTIVE", "DORMANT"],
                    suggestion_id="rule-s-1",
                    suggestion_type="rule",
                    applied_by="knowledge_assist",
                    generated_by_ka=True,
                    ka_review_status="accepted",
                ),
                RuleEntry(
                    field="balance",
                    type="range",
                    value="0..100000",
                    suggestion_id="rule-s-2",
                    suggestion_type="rule",
                    applied_by="knowledge_assist",
                    generated_by_ka=True,
                    ka_review_status="edited",
                ),
                RuleEntry(
                    field="customerId",
                    type="cross-entity-field-check",
                    target_entity="Customer",
                    target_field="customerId",
                    operator="eq",
                    expected_value="customerId",
                    suggestion_id="x-1",
                    suggestion_type="cross_entity_rule",
                    applied_by="knowledge_assist",
                    generated_by_ka=True,
                    ka_review_status="accepted",
                ),
            ],
        )
    ]
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["v-1", "rule-s-1", "x-1"]
    session.ks_workspace_state.suggestion_review_state.edited_ids = ["rule-s-2"]
    session.ks_workspace_state.suggestion_review_state.rejected_ids = ["rule-rejected"]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="v-1",
            type="validation",
            status="accepted",
            manifest_path="entities.Account.fields.status.validations.not-null",
            reviewed_at="2026-04-28T12:00:00+00:00",
            review_context={"constraint_fingerprint": "nullable=False"},
        ),
        KSReviewHistoryEntry(
            suggestion_id="rule-s-1",
            type="rule",
            status="accepted",
            manifest_path="rules.Account.status.allowed-values",
            reviewed_at="2026-04-28T12:00:00+00:00",
        ),
        KSReviewHistoryEntry(
            suggestion_id="rule-s-2",
            type="rule",
            status="edited",
            manifest_path="rules.Account.balance.range",
            reviewed_at="2026-04-28T12:01:00+00:00",
        ),
        KSReviewHistoryEntry(
            suggestion_id="x-1",
            type="cross_entity_rule",
            status="accepted",
            manifest_path="rules.Account.customerId.cross-entity-field-check",
            reviewed_at="2026-04-28T12:02:00+00:00",
        ),
        KSReviewHistoryEntry(
            suggestion_id="rule-rejected",
            type="rule",
            status="rejected",
            manifest_path="rules.Account.status.pattern",
            reviewed_at="2026-04-28T12:03:00+00:00",
        ),
    ]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="entities.Account.fields.status.validations.not-null",
            suggestion_id="v-1",
            provenance="ai-accepted",
        ),
        KSEvidenceLink(
            manifest_path="rules.Account.status.allowed-values",
            suggestion_id="rule-s-1",
            provenance="ai-accepted",
        ),
        KSEvidenceLink(
            manifest_path="rules.Account.balance.range",
            suggestion_id="rule-s-2",
            provenance="ai-edited",
        ),
        KSEvidenceLink(
            manifest_path="rules.Account.customerId.cross-entity-field-check",
            suggestion_id="x-1",
            provenance="ai-accepted",
        ),
        KSEvidenceLink(
            manifest_path="rules.Account.status.pattern",
            suggestion_id="rule-rejected",
            provenance="ai-accepted",
        ),
    ]
    save_session(session)

    calls: list[tuple[str, str]] = []

    class FakeClient:
        def get_suggestion_evidence_chain(
            self,
            project_id: str,
            scope: str,
            suggestion_id: str,
        ):
            calls.append((scope, suggestion_id))
            return {
                "suggestion": {"confidence": 0.81},
                "evidence_chunks": [
                    {
                        "citation": {
                            "document_id": f"doc-{suggestion_id}",
                            "document_name": "Rules BRD.pdf",
                            "chunk_id": f"chunk-{suggestion_id}",
                            "content_hash": f"sha256:{suggestion_id}",
                            "parser_version": "pdf-v1",
                            "section": "Rules",
                            "snippet": f"Evidence for {suggestion_id}",
                        }
                    }
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.evidence_trail.ks_client", fake_ks_client)

    response = client.post("/export/write")

    assert response.status_code == 200
    payload = response.json()
    sidecar = json.loads((Path(payload["output_dir"]) / "evidence-trail.json").read_text(encoding="utf-8"))
    assert calls == [
        ("validations", "v-1"),
        ("rules", "rule-s-1"),
        ("rules", "rule-s-2"),
        ("cross_entity_rules", "x-1"),
    ]
    assert [link["suggestion_type"] for link in sidecar["evidence_links"]] == [
        "validation",
        "rule",
        "rule",
        "cross_entity_rule",
    ]
    assert sidecar["provenance_summary"]["ai_accepted"] == 3
    assert sidecar["provenance_summary"]["ai_edited"] == 1
    assert sidecar["provenance_summary"]["by_type"] == {
        "field": 0,
        "validation": 1,
        "rule": 2,
        "cross_entity_rule": 1,
        "mapping": 0,
        "transform": 0,
    }
    assert all(link["suggestion_id"] != "rule-rejected" for link in sidecar["evidence_links"])


def test_export_write_fails_clearly_when_ks_citation_expansion_fails(monkeypatch, tmp_path):
    _seed_export_session(tmp_path)
    session = get_session()
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["s-1"]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="s-1",
            type="field",
            status="accepted",
            manifest_path="entities.Account.fields.account_id",
            reviewed_at="2026-04-20T12:00:00+00:00",
        )
    ]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="entities.Account.fields.account_id",
            suggestion_id="s-1",
            provenance="ai-accepted",
        )
    ]
    save_session(session)

    @contextmanager
    def failing_ks_client(**kwargs):
        raise KSUnavailableError("KS is down")
        yield

    monkeypatch.setattr("app.services.evidence_trail.ks_client", failing_ks_client)

    response = client.post("/export/write")

    assert response.status_code == 400
    payload = response.json()
    assert payload["ok"] is False
    assert payload["evidence_export_failed"] is True
    assert "Knowledge Server unavailable" in payload["error"]
    assert get_session().ks_workspace_state.manifest_revisions == []


def test_export_write_counts_missing_supported_evidence_and_skips_unknown_links(monkeypatch, tmp_path):
    _seed_export_session(tmp_path)
    session = get_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(
                    field="status",
                    type="not-null",
                    suggestion_id="v-missing",
                    suggestion_type="validation",
                    applied_by="knowledge_assist",
                    generated_by_ka=True,
                    ka_review_status="accepted",
                ),
                RuleEntry(
                    field="status",
                    type="allowed-values",
                    values=["ACTIVE", "DORMANT"],
                    suggestion_id="r-linked",
                    suggestion_type="rule",
                    applied_by="knowledge_assist",
                    generated_by_ka=True,
                    ka_review_status="accepted",
                ),
            ],
        )
    ]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="v-missing",
            type="validation",
            status="accepted",
            manifest_path="entities.Account.fields.status.validations.not-null",
            reviewed_at="2026-04-28T12:00:00+00:00",
        ),
        KSReviewHistoryEntry(
            suggestion_id="r-linked",
            type="rule",
            status="accepted",
            manifest_path="rules.Account.status.allowed-values",
            reviewed_at="2026-04-28T12:01:00+00:00",
        ),
    ]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="rules.Account.status.allowed-values",
            suggestion_id="r-linked",
            provenance="ai-accepted",
        ),
        KSEvidenceLink(
            manifest_path="mappings.Account.status",
            suggestion_id="unsupported-1",
            provenance="ai-accepted",
        ),
    ]
    save_session(session)

    class FakeClient:
        def get_suggestion_evidence_chain(
            self,
            project_id: str,
            scope: str,
            suggestion_id: str,
        ):
            assert scope == "rules"
            assert suggestion_id == "r-linked"
            return {
                "suggestion": {"confidence": 0.83},
                "evidence_chunks": [
                    {
                        "citation": {
                            "document_id": "doc-rule",
                            "document_name": "Rules BRD.pdf",
                            "chunk_id": "chunk-rule",
                            "content_hash": "sha256:rule",
                            "parser_version": "pdf-v1",
                            "snippet": "Allowed statuses are constrained.",
                        }
                    }
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.evidence_trail.ks_client", fake_ks_client)

    response = client.post("/export/write")

    assert response.status_code == 200
    payload = response.json()
    sidecar = json.loads((Path(payload["output_dir"]) / "evidence-trail.json").read_text(encoding="utf-8"))
    assert sidecar["provenance_summary"]["no_evidence"] == 1
    assert sidecar["provenance_summary"]["by_type"]["rule"] == 1
    assert sidecar["evidence_links"][0]["suggestion_type"] == "rule"
    assert sidecar["warnings"] == [
        "Skipped unsupported evidence link without supported review history: mappings.Account.status"
    ]


def test_export_write_skips_deleted_ka_rule_evidence_link(monkeypatch, tmp_path):
    _seed_export_session(tmp_path)
    session = get_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(field="status", type="allowed-values", values=["ACTIVE"], applied_by="manual"),
            ],
        )
    ]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="r-deleted",
            type="rule",
            status="accepted",
            manifest_path="rules.Account.status.allowed-values",
            reviewed_at="2026-05-03T12:00:00+00:00",
        )
    ]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="rules.Account.status.allowed-values",
            suggestion_id="r-deleted",
            provenance="ai-accepted",
        )
    ]
    save_session(session)

    @contextmanager
    def unexpected_ks_client(**kwargs):
        raise AssertionError("deleted KA-owned rule evidence should not be expanded")
        yield

    monkeypatch.setattr("app.services.evidence_trail.ks_client", unexpected_ks_client)

    response = client.post("/export/write")

    assert response.status_code == 200
    payload = response.json()
    sidecar = json.loads((Path(payload["output_dir"]) / "evidence-trail.json").read_text(encoding="utf-8"))
    assert sidecar["evidence_links"] == []
    assert sidecar["provenance_summary"]["by_type"]["rule"] == 0
    assert sidecar["provenance_summary"]["no_evidence"] == 0
    assert sidecar["warnings"] == [
        "Skipped rule evidence because the current generated rule is absent: rules.Account.status.allowed-values"
    ]


def test_export_write_skips_stale_ka_rule_evidence_after_user_edits_row(monkeypatch, tmp_path):
    _seed_export_session(tmp_path)
    session = get_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(
                    field="statusCode",
                    type="pattern",
                    value="^[A-Z]+$",
                    suggestion_id="r-stale",
                    suggestion_type="rule",
                    applied_by="knowledge_assist",
                    generated_by_ka=True,
                    ka_review_status="accepted",
                ),
            ],
        )
    ]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="r-stale",
            type="rule",
            status="accepted",
            manifest_path="rules.Account.status.allowed-values",
            reviewed_at="2026-05-03T12:00:00+00:00",
        )
    ]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="rules.Account.status.allowed-values",
            suggestion_id="r-stale",
            provenance="ai-accepted",
        )
    ]
    save_session(session)

    @contextmanager
    def unexpected_ks_client(**kwargs):
        raise AssertionError("stale KA rule evidence should not be expanded")
        yield

    monkeypatch.setattr("app.services.evidence_trail.ks_client", unexpected_ks_client)

    response = client.post("/export/write")

    assert response.status_code == 200
    payload = response.json()
    sidecar = json.loads((Path(payload["output_dir"]) / "evidence-trail.json").read_text(encoding="utf-8"))
    assert sidecar["evidence_links"] == []
    assert sidecar["provenance_summary"]["by_type"]["rule"] == 0
    assert sidecar["warnings"] == [
        "Skipped rule evidence because the current generated rule is absent: rules.Account.status.allowed-values"
    ]


def test_export_write_skips_stale_ka_validation_evidence_after_value_edit(monkeypatch, tmp_path):
    _seed_export_session(tmp_path)
    session = get_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(
                    field="accountNumber",
                    type="max-length",
                    value="18",
                    suggestion_id="v-max",
                    suggestion_type="validation",
                    applied_by="knowledge_assist",
                    generated_by_ka=True,
                    ka_review_status="edited",
                )
            ],
        )
    ]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="v-max",
            type="validation",
            status="accepted",
            manifest_path="entities.Account.fields.accountNumber.validations.max-length",
            reviewed_at="2026-05-03T12:00:00+00:00",
            review_context={"constraint_fingerprint": "max=14"},
        )
    ]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="entities.Account.fields.accountNumber.validations.max-length",
            suggestion_id="v-max",
            provenance="ai-accepted",
        )
    ]
    save_session(session)

    @contextmanager
    def unexpected_ks_client(**kwargs):
        raise AssertionError("stale KA validation evidence should not be expanded")
        yield

    monkeypatch.setattr("app.services.evidence_trail.ks_client", unexpected_ks_client)

    response = client.post("/export/write")

    assert response.status_code == 200
    payload = response.json()
    sidecar = json.loads((Path(payload["output_dir"]) / "evidence-trail.json").read_text(encoding="utf-8"))
    assert sidecar["evidence_links"] == []
    assert sidecar["provenance_summary"]["by_type"]["validation"] == 0
    assert sidecar["warnings"] == [
        "Skipped validation evidence because the current generated rule is absent: "
        "entities.Account.fields.accountNumber.validations.max-length"
    ]


def test_export_write_skips_evidence_superseded_by_rejected_validation(monkeypatch, tmp_path):
    _seed_export_session(tmp_path)
    session = get_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Customer",
            rules=[
                RuleEntry(
                    field="kycStatus",
                    type="not-null",
                    suggestion_id="v-old",
                    suggestion_type="validation",
                    applied_by="knowledge_assist",
                    generated_by_ka=True,
                    ka_review_status="accepted",
                )
            ],
        )
    ]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="v-old",
            type="validation",
            status="accepted",
            manifest_path="entities.Customer.fields.kycStatus.validations.not-null",
            reviewed_at="2026-05-03T12:00:00+00:00",
        ),
        KSReviewHistoryEntry(
            suggestion_id="v-new",
            type="validation",
            status="rejected",
            manifest_path="entities.Customer.fields.kycStatus.validations.not-null",
            reviewed_at="2026-05-03T12:05:00+00:00",
        ),
    ]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="entities.Customer.fields.kycStatus.validations.not-null",
            suggestion_id="v-old",
            provenance="ai-accepted",
        )
    ]
    save_session(session)

    @contextmanager
    def unexpected_ks_client(**kwargs):
        raise AssertionError("superseded validation evidence should not be expanded")
        yield

    monkeypatch.setattr("app.services.evidence_trail.ks_client", unexpected_ks_client)

    response = client.post("/export/write")

    assert response.status_code == 200
    payload = response.json()
    sidecar = json.loads((Path(payload["output_dir"]) / "evidence-trail.json").read_text(encoding="utf-8"))
    assert sidecar["evidence_links"] == []
    assert sidecar["provenance_summary"]["by_type"]["validation"] == 0
    assert sidecar["warnings"] == [
        "Skipped stale evidence link superseded by a newer review entry: "
        "entities.Customer.fields.kycStatus.validations.not-null"
    ]


def test_export_write_ignores_conflict_portfolio_and_missing_transform_review_decisions(monkeypatch, tmp_path):
    _seed_export_session(tmp_path)
    session = get_session()
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["c-1", "p-1", "t-1"]
    session.ks_workspace_state.suggestion_review_state.edited_ids = ["c-2", "p-2"]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="c-1",
            type="conflict_resolution",
            status="accepted",
            manifest_path="conflicts.c-1",
            reviewed_at="2026-04-29T12:00:00+00:00",
        ),
        KSReviewHistoryEntry(
            suggestion_id="c-2",
            type="conflict_resolution",
            status="edited",
            manifest_path="conflicts.c-2",
            reviewed_at="2026-04-29T12:05:00+00:00",
            edited_payload={"resolution_note": "Prefer BRD."},
        ),
        KSReviewHistoryEntry(
            suggestion_id="p-1",
            type="portfolio_reuse",
            status="accepted",
            manifest_path="portfolio_reuse.p-1",
            reviewed_at="2026-04-29T13:00:00+00:00",
        ),
        KSReviewHistoryEntry(
            suggestion_id="p-2",
            type="portfolio_reuse",
            status="edited",
            manifest_path="portfolio_reuse.p-2",
            reviewed_at="2026-04-29T13:05:00+00:00",
            edited_payload={"reuse_note": "Useful for Step 6 follow-up."},
        ),
        KSReviewHistoryEntry(
            suggestion_id="t-1",
            type="transform",
            status="accepted",
            manifest_path="async_routes.payment-posted.router_config.targets.ledger-core.request_transform.paymentId.transactionId",
            reviewed_at="2026-04-29T14:00:00+00:00",
        ),
    ]
    save_session(session)

    @contextmanager
    def unexpected_ks_client(**kwargs):
        raise AssertionError("advisory and missing transform review decisions are not exportable evidence")
        yield

    monkeypatch.setattr("app.services.evidence_trail.ks_client", unexpected_ks_client)

    response = client.post("/export/write")

    assert response.status_code == 200
    payload = response.json()
    sidecar = json.loads((Path(payload["output_dir"]) / "evidence-trail.json").read_text(encoding="utf-8"))
    assert sidecar["schema_version"] == "1.1"
    assert sidecar["evidence_links"] == []
    assert sidecar["provenance_summary"]["no_evidence"] == 0
    assert "conflict_resolution" not in sidecar["provenance_summary"]["by_type"]
    assert "portfolio_reuse" not in sidecar["provenance_summary"]["by_type"]
    assert sidecar["provenance_summary"]["by_type"]["transform"] == 0


def test_export_write_expands_kafka_router_transform_review_history(monkeypatch, tmp_path):
    _seed_export_session(tmp_path)
    session = get_session()
    session.kafka_route_transforms = [
        KafkaRouteTransform(
            route_name="payment-router",
            router_target_transforms=[
                KafkaRouterTargetTransform(
                    target_id="ledger-core",
                    request_transform_rows=[
                        KafkaRouterTransformRow(
                            source="payment.amount",
                            target="amountMinor",
                            value_map={"USD": "840"},
                            type_coercion="major_to_minor_units",
                        )
                    ],
                    response_transform_rows=[
                        KafkaRouterTransformRow(
                            target="status",
                            default_value="PENDING",
                        )
                    ],
                )
            ],
        )
    ]
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["t-request"]
    session.ks_workspace_state.suggestion_review_state.edited_ids = ["t-response"]
    session.ks_workspace_state.suggestion_review_state.rejected_ids = ["t-rejected"]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="t-request",
            type="transform",
            status="accepted",
            manifest_path=(
                "async_routes.payment-router.router_config.targets.ledger-core."
                "request_transform.payment.amount.amountMinor"
            ),
            reviewed_at="2026-04-29T14:00:00+00:00",
            review_context={
                "route_name": "payment-router",
                "target_id": "ledger-core",
                "direction": "request",
                "source": "payment.amount",
                "target": "amountMinor",
                "value_map": {"USD": "840"},
                "type_coercion": "major_to_minor_units",
            },
        ),
        KSReviewHistoryEntry(
            suggestion_id="t-response",
            type="transform",
            status="edited",
            manifest_path=(
                "async_routes.payment-router.router_config.targets.ledger-core."
                "response_transform.default.status"
            ),
            reviewed_at="2026-04-29T14:05:00+00:00",
            edited_payload={
                "target": "status",
                "default_value": "PENDING",
                "rationale": "Default missing status responses.",
            },
            review_context={
                "route_name": "payment-router",
                "target_id": "ledger-core",
                "direction": "response",
                "target": "status",
                "default_value": "PENDING",
            },
        ),
        KSReviewHistoryEntry(
            suggestion_id="t-rejected",
            type="transform",
            status="rejected",
            manifest_path=(
                "async_routes.payment-router.router_config.targets.ledger-core."
                "request_transform.ignored.ignored"
            ),
            reviewed_at="2026-04-29T14:10:00+00:00",
        ),
    ]
    save_session(session)

    calls: list[tuple[str, str]] = []

    class FakeClient:
        def get_suggestion_evidence_chain(
            self,
            project_id: str,
            scope: str,
            suggestion_id: str,
        ):
            calls.append((scope, suggestion_id))
            stale_payload = {
                "route_name": "payment-router",
                "target_id": "ledger-core",
            }
            if suggestion_id == "t-response":
                stale_payload.update(
                    {
                        "source": "original.statusCode",
                        "constant": "STALE",
                        "value_map": {"200": "APPROVED"},
                        "type_coercion": "minor_to_major_units",
                    }
                )
            return {
                "suggestion": {
                    "confidence": 0.84,
                    "payload": stale_payload,
                },
                "evidence_chunks": [
                    {
                        "citation": {
                            "document_id": f"doc-{suggestion_id}",
                            "document_name": "Router Mapping BRD.pdf",
                            "chunk_id": f"chunk-{suggestion_id}",
                            "content_hash": f"sha256:{suggestion_id}",
                            "parser_version": "pdf-v1",
                            "snippet": f"Transform evidence for {suggestion_id}.",
                        }
                    }
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.evidence_trail.ks_client", fake_ks_client)

    response = client.post("/export/write")

    assert response.status_code == 200
    payload = response.json()
    sidecar = json.loads((Path(payload["output_dir"]) / "evidence-trail.json").read_text(encoding="utf-8"))
    assert calls == [("transforms", "t-request"), ("transforms", "t-response")]
    transform_links = sidecar["evidence_links"]
    assert [link["suggestion_id"] for link in transform_links] == ["t-request", "t-response"]
    assert all(link["suggestion_type"] == "transform" for link in transform_links)
    assert transform_links[0]["decision"] == "accepted"
    assert transform_links[0]["route_name"] == "payment-router"
    assert transform_links[0]["target_id"] == "ledger-core"
    assert transform_links[0]["direction"] == "request"
    assert transform_links[0]["source_field"] == "payment.amount"
    assert transform_links[0]["target_field"] == "amountMinor"
    assert transform_links[0]["value_map"] == {"USD": "840"}
    assert transform_links[0]["type_coercion"] == "major_to_minor_units"
    assert transform_links[1]["decision"] == "edited"
    assert transform_links[1]["direction"] == "response"
    assert transform_links[1]["target_field"] == "status"
    assert transform_links[1]["default_value"] == "PENDING"
    assert "source_field" not in transform_links[1]
    assert "constant" not in transform_links[1]
    assert "value_map" not in transform_links[1]
    assert "type_coercion" not in transform_links[1]
    assert all(link["suggestion_id"] != "t-rejected" for link in transform_links)
    assert sidecar["provenance_summary"]["ai_accepted"] == 1
    assert sidecar["provenance_summary"]["ai_edited"] == 1
    assert sidecar["provenance_summary"]["by_type"]["transform"] == 2
    assert sidecar["provenance_summary"]["no_evidence"] == 0


def test_export_write_skips_transform_evidence_when_applied_row_is_deleted(monkeypatch, tmp_path):
    _seed_export_session(tmp_path)
    session = get_session()
    session.kafka_route_transforms = [
        KafkaRouteTransform(
            route_name="payment-router",
            router_target_transforms=[
                KafkaRouterTargetTransform(
                    target_id="ledger-core",
                    request_transform_rows=[
                        KafkaRouterTransformRow(source="payment.id", target="transactionId")
                    ],
                )
            ],
        )
    ]
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["t-present", "t-deleted"]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="t-present",
            type="transform",
            status="accepted",
            manifest_path=(
                "async_routes.payment-router.router_config.targets.ledger-core."
                "request_transform.payment.id.transactionId"
            ),
            reviewed_at="2026-04-29T14:00:00+00:00",
            review_context={
                "route_name": "payment-router",
                "target_id": "ledger-core",
                "direction": "request",
                "source": "payment.id",
                "target": "transactionId",
            },
        ),
        KSReviewHistoryEntry(
            suggestion_id="t-deleted",
            type="transform",
            status="accepted",
            manifest_path=(
                "async_routes.payment-router.router_config.targets.ledger-core."
                "response_transform.status.status"
            ),
            reviewed_at="2026-04-29T14:05:00+00:00",
            review_context={
                "route_name": "payment-router",
                "target_id": "ledger-core",
                "direction": "response",
                "source": "status",
                "target": "status",
            },
        ),
    ]
    save_session(session)

    calls: list[tuple[str, str]] = []

    class FakeClient:
        def get_suggestion_evidence_chain(self, project_id: str, scope: str, suggestion_id: str):
            calls.append((scope, suggestion_id))
            return {
                "suggestion": {"confidence": 0.8},
                "evidence_chunks": [
                    {
                        "citation": {
                            "document_id": "doc-transform",
                            "document_name": "Router Mapping BRD.pdf",
                            "chunk_id": "chunk-transform",
                            "content_hash": "sha256:transform",
                            "parser_version": "pdf-v1",
                            "snippet": "Transform evidence.",
                        }
                    }
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.evidence_trail.ks_client", fake_ks_client)

    response = client.post("/export/write")

    assert response.status_code == 200
    payload = response.json()
    sidecar = json.loads((Path(payload["output_dir"]) / "evidence-trail.json").read_text(encoding="utf-8"))
    assert calls == [("transforms", "t-present")]
    assert [link["suggestion_id"] for link in sidecar["evidence_links"]] == ["t-present"]
    assert sidecar["provenance_summary"]["by_type"]["transform"] == 1
    assert sidecar["provenance_summary"]["no_evidence"] == 0
    assert sidecar["warnings"] == [
        "Skipped transform evidence because the current generated artifact is absent: "
        "async_routes.payment-router.router_config.targets.ledger-core."
        "response_transform.status.status"
    ]


def test_export_write_expands_mapping_review_history_for_v1_1(monkeypatch, tmp_path):
    _seed_export_session(tmp_path)
    session = get_session()
    session.ks_workspace_state.suggestion_review_state.accepted_ids = [
        "m-pass",
        "m-kafka-request",
        "m-kafka-response",
    ]
    session.ks_workspace_state.suggestion_review_state.edited_ids = ["m-edit"]
    session.ks_workspace_state.suggestion_review_state.rejected_ids = ["m-rejected"]
    session.passthrough_flow.upstream_operation_name = "routePayment"
    session.passthrough_flow.transforms = [
        PassthroughTransform(source="amount", target="settlementAmount"),
        PassthroughTransform(source="remittanceInfo", target="paymentReference"),
    ]
    session.kafka_route_transforms = [
        KafkaRouteTransform(
            route_name="payment-posted",
            mappings=[
                KafkaTransformRow(source_field="paymentId", target_field="ledgerId"),
            ],
            response_mappings=[
                KafkaTransformRow(source_field="approved", target_field="verified"),
            ],
        )
    ]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="m-pass",
            type="mapping",
            status="accepted",
            manifest_path="passthrough.routePayment.transforms.amount.settlementAmount",
            reviewed_at="2026-04-28T12:00:00+00:00",
        ),
        KSReviewHistoryEntry(
            suggestion_id="m-edit",
            type="mapping",
            status="edited",
            manifest_path="passthrough.routePayment.transforms.remittanceInfo.paymentReference",
            reviewed_at="2026-04-28T12:01:00+00:00",
            edited_payload={
                "route_name": "routePayment",
                "direction": "request",
                "source_entity": "InternalPaymentRequest",
                "target_entity": "SctPaymentRequest",
                "source_field": "remittanceInfo",
                "target_field": "paymentReference",
                "mapping_type": "copy",
                "confidence_basis": "Edited by reviewer.",
            },
            review_context={
                "mapping_context": "passthrough",
                "route_name": "routePayment",
                "direction": "request",
                "source_field": "remittanceInfo",
                "target_field": "paymentReference",
            },
        ),
        KSReviewHistoryEntry(
            suggestion_id="m-kafka-request",
            type="mapping",
            status="accepted",
            manifest_path="async_routes.payment-posted.transform_mapping.request.paymentId.ledgerId",
            reviewed_at="2026-04-28T12:02:00+00:00",
        ),
        KSReviewHistoryEntry(
            suggestion_id="m-kafka-response",
            type="mapping",
            status="accepted",
            manifest_path="async_routes.payment-posted.transform_mapping.response.approved.verified",
            reviewed_at="2026-04-28T12:03:00+00:00",
        ),
        KSReviewHistoryEntry(
            suggestion_id="m-rejected",
            type="mapping",
            status="rejected",
            manifest_path="async_routes.payment-posted.transform_mapping.request.unused.ignored",
            reviewed_at="2026-04-28T12:04:00+00:00",
        ),
    ]
    save_session(session)

    calls: list[tuple[str, str]] = []

    class FakeClient:
        def get_suggestion_evidence_chain(
            self,
            project_id: str,
            scope: str,
            suggestion_id: str,
        ):
            calls.append((scope, suggestion_id))
            return {
                "suggestion": {
                    "confidence": 0.79,
                    "payload": {
                        "route_name": "payment-posted" if suggestion_id.startswith("m-kafka") else "routePayment",
                    },
                },
                "evidence_chunks": [
                    {
                        "citation": {
                            "document_id": f"doc-{suggestion_id}",
                            "document_name": "Mapping BRD.pdf",
                            "chunk_id": f"chunk-{suggestion_id}",
                            "content_hash": f"sha256:{suggestion_id}",
                            "parser_version": "pdf-v1",
                            "snippet": f"Evidence for {suggestion_id}",
                        }
                    }
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.evidence_trail.ks_client", fake_ks_client)

    response = client.post("/export/write")

    assert response.status_code == 200
    payload = response.json()
    sidecar = json.loads((Path(payload["output_dir"]) / "evidence-trail.json").read_text(encoding="utf-8"))
    assert sidecar["schema_version"] == "1.1"
    assert calls == [
        ("mappings", "m-pass"),
        ("mappings", "m-edit"),
        ("mappings", "m-kafka-request"),
        ("mappings", "m-kafka-response"),
    ]
    mapping_links = sidecar["evidence_links"]
    assert [link["suggestion_id"] for link in mapping_links] == [
        "m-pass",
        "m-edit",
        "m-kafka-request",
        "m-kafka-response",
    ]
    assert all(link["suggestion_type"] == "mapping" for link in mapping_links)
    assert mapping_links[0]["decision"] == "accepted"
    assert mapping_links[0]["mapping_context"] == "passthrough"
    assert mapping_links[0]["direction"] == "request"
    assert mapping_links[0]["source_field"] == "amount"
    assert mapping_links[0]["target_field"] == "settlementAmount"
    assert mapping_links[1]["decision"] == "edited"
    assert mapping_links[1]["source_field"] == "remittanceInfo"
    assert mapping_links[1]["target_field"] == "paymentReference"
    assert mapping_links[2]["mapping_context"] == "kafka"
    assert mapping_links[2]["route_name"] == "payment-posted"
    assert mapping_links[2]["direction"] == "request"
    assert mapping_links[2]["source_field"] == "paymentId"
    assert mapping_links[2]["target_field"] == "ledgerId"
    assert mapping_links[3]["direction"] == "response"
    assert mapping_links[3]["source_field"] == "approved"
    assert mapping_links[3]["target_field"] == "verified"
    assert all(link["suggestion_id"] != "m-rejected" for link in mapping_links)
    assert sidecar["provenance_summary"]["ai_accepted"] == 3
    assert sidecar["provenance_summary"]["ai_edited"] == 1
    assert sidecar["provenance_summary"]["by_type"]["mapping"] == 4
    assert sidecar["provenance_summary"]["no_evidence"] == 0
    assert sidecar.get("warnings", []) == []


def test_export_write_skips_mapping_evidence_for_deleted_transform_rows(monkeypatch, tmp_path):
    _seed_export_session(tmp_path)
    session = get_session()
    session.passthrough_flow.upstream_operation_name = "routePayment"
    session.passthrough_flow.transforms = [
        PassthroughTransform(source="amount", target="settlementAmount"),
    ]
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["m-present", "m-deleted"]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="m-present",
            type="mapping",
            status="accepted",
            manifest_path="passthrough.routePayment.transforms.amount.settlementAmount",
            reviewed_at="2026-04-28T12:00:00+00:00",
        ),
        KSReviewHistoryEntry(
            suggestion_id="m-deleted",
            type="mapping",
            status="accepted",
            manifest_path="passthrough.routePayment.transforms.currency.settlementCurrency",
            reviewed_at="2026-04-28T12:01:00+00:00",
        ),
    ]
    save_session(session)

    calls: list[tuple[str, str]] = []

    class FakeClient:
        def get_suggestion_evidence_chain(
            self,
            project_id: str,
            scope: str,
            suggestion_id: str,
        ):
            calls.append((scope, suggestion_id))
            return {
                "suggestion": {"confidence": 0.81},
                "evidence_chunks": [
                    {
                        "citation": {
                            "document_id": "doc-map",
                            "document_name": "Mapping BRD.pdf",
                            "chunk_id": "chunk-map",
                            "content_hash": "sha256:map",
                            "parser_version": "pdf-v1",
                            "snippet": "Amount maps to settlement amount.",
                        }
                    }
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.evidence_trail.ks_client", fake_ks_client)

    response = client.post("/export/write")

    assert response.status_code == 200
    payload = response.json()
    sidecar = json.loads((Path(payload["output_dir"]) / "evidence-trail.json").read_text(encoding="utf-8"))
    assert calls == [("mappings", "m-present")]
    assert [link["suggestion_id"] for link in sidecar["evidence_links"]] == ["m-present"]
    assert sidecar["provenance_summary"]["by_type"]["mapping"] == 1
    assert sidecar["provenance_summary"]["no_evidence"] == 0
    assert sidecar["warnings"] == [
        "Skipped mapping evidence because the current transform row is absent: "
        "passthrough.routePayment.transforms.currency.settlementCurrency"
    ]


def test_export_write_keeps_mapping_evidence_for_dotted_field_paths(monkeypatch, tmp_path):
    _seed_export_session(tmp_path)
    session = get_session()
    session.passthrough_flow.upstream_operation_name = "routePayment"
    session.passthrough_flow.transforms = [
        PassthroughTransform(source="customer.id", target="account.customerId"),
    ]
    session.kafka_route_transforms = [
        KafkaRouteTransform(
            route_name="payment-posted",
            mappings=[
                KafkaTransformRow(source_field="payment.id", target_field="ledger.entry.id"),
            ],
        )
    ]
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["m-pass-dot", "m-kafka-dot"]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="m-pass-dot",
            type="mapping",
            status="accepted",
            manifest_path="passthrough.routePayment.transforms.customer.id.account.customerId",
            reviewed_at="2026-04-28T12:00:00+00:00",
            review_context={
                "mapping_context": "passthrough",
                "route_name": "routePayment",
                "direction": "request",
                "source_field": "customer.id",
                "target_field": "account.customerId",
            },
        ),
        KSReviewHistoryEntry(
            suggestion_id="m-kafka-dot",
            type="mapping",
            status="accepted",
            manifest_path="async_routes.payment-posted.transform_mapping.request.payment.id.ledger.entry.id",
            reviewed_at="2026-04-28T12:01:00+00:00",
            review_context={
                "mapping_context": "kafka",
                "route_name": "payment-posted",
                "direction": "request",
                "source_field": "payment.id",
                "target_field": "ledger.entry.id",
            },
        ),
    ]
    save_session(session)

    class FakeClient:
        def get_suggestion_evidence_chain(
            self,
            project_id: str,
            scope: str,
            suggestion_id: str,
        ):
            assert scope == "mappings"
            return {
                "suggestion": {"confidence": 0.82},
                "evidence_chunks": [
                    {
                        "citation": {
                            "document_id": f"doc-{suggestion_id}",
                            "document_name": "Mapping BRD.pdf",
                            "chunk_id": f"chunk-{suggestion_id}",
                            "content_hash": f"sha256:{suggestion_id}",
                            "parser_version": "pdf-v1",
                            "snippet": "Dotted mapping evidence.",
                        }
                    }
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.evidence_trail.ks_client", fake_ks_client)

    response = client.post("/export/write")

    assert response.status_code == 200
    payload = response.json()
    sidecar = json.loads((Path(payload["output_dir"]) / "evidence-trail.json").read_text(encoding="utf-8"))
    links = sidecar["evidence_links"]
    assert [link["suggestion_id"] for link in links] == ["m-pass-dot", "m-kafka-dot"]
    assert links[0]["source_field"] == "customer.id"
    assert links[0]["target_field"] == "account.customerId"
    assert links[0]["direction"] == "request"
    assert links[1]["source_field"] == "payment.id"
    assert links[1]["target_field"] == "ledger.entry.id"
    assert links[1]["direction"] == "request"
    assert sidecar.get("warnings", []) == []


def test_export_write_skips_colliding_dotted_mapping_review_without_current_context(monkeypatch, tmp_path):
    _seed_export_session(tmp_path)
    session = get_session()
    session.passthrough_flow.upstream_operation_name = "routePayment"
    session.passthrough_flow.transforms = [
        PassthroughTransform(source="customer", target="id.accountCustomerId"),
    ]
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["m-old"]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="m-old",
            type="mapping",
            status="accepted",
            manifest_path="passthrough.routePayment.transforms.customer.id.accountCustomerId",
            reviewed_at="2026-04-28T12:00:00+00:00",
        ),
    ]
    save_session(session)

    class FakeClient:
        def get_suggestion_evidence_chain(self, **kwargs):
            raise AssertionError("Stale colliding mapping evidence should not call KS")

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.evidence_trail.ks_client", fake_ks_client)

    response = client.post("/export/write")

    assert response.status_code == 200
    payload = response.json()
    sidecar = json.loads((Path(payload["output_dir"]) / "evidence-trail.json").read_text(encoding="utf-8"))
    assert sidecar["evidence_links"] == []
    assert sidecar["provenance_summary"]["by_type"]["mapping"] == 0
    assert sidecar["provenance_summary"]["no_evidence"] == 0
    assert sidecar["warnings"] == [
        "Skipped mapping evidence because the current transform row is absent: "
        "passthrough.routePayment.transforms.customer.id.accountCustomerId"
    ]


def test_export_write_preserves_same_path_cross_entity_rule_reviews(monkeypatch, tmp_path):
    _seed_export_session(tmp_path)
    session = get_session()
    session.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[
                RuleEntry(
                    field="customerId",
                    type="cross-entity",
                    target_entity="Customer",
                    expected_value="ACTIVE",
                    suggestion_id="x-old",
                    suggestion_type="cross_entity_rule",
                    applied_by="knowledge_assist",
                    generated_by_ka=True,
                    ka_review_status="accepted",
                ),
                RuleEntry(
                    field="customerId",
                    type="cross-entity",
                    target_entity="Customer",
                    expected_value="VERIFIED",
                    suggestion_id="x-new",
                    suggestion_type="cross_entity_rule",
                    applied_by="knowledge_assist",
                    generated_by_ka=True,
                    ka_review_status="accepted",
                )
            ],
        )
    ]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="x-old",
            type="cross_entity_rule",
            status="accepted",
            manifest_path="rules.Account.customerId.cross-entity",
            reviewed_at="2026-04-28T12:00:00+00:00",
        ),
        KSReviewHistoryEntry(
            suggestion_id="x-new",
            type="cross_entity_rule",
            status="accepted",
            manifest_path="rules.Account.customerId.cross-entity",
            reviewed_at="2026-04-28T12:05:00+00:00",
        ),
    ]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="rules.Account.customerId.cross-entity",
            suggestion_id="x-new",
            provenance="ai-accepted",
        )
    ]
    save_session(session)

    class FakeClient:
        def get_suggestion_evidence_chain(
            self,
            project_id: str,
            scope: str,
            suggestion_id: str,
        ):
            assert scope == "cross_entity_rules"
            assert suggestion_id == "x-new"
            return {
                "suggestion": {"confidence": 0.77},
                "evidence_chunks": [
                    {
                        "citation": {
                            "document_id": "doc-x",
                            "document_name": "Cross Entity BRD.pdf",
                            "chunk_id": "chunk-x",
                            "content_hash": "sha256:x",
                            "parser_version": "pdf-v1",
                            "snippet": "Customer status must be checked.",
                        }
                    }
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.evidence_trail.ks_client", fake_ks_client)

    response = client.post("/export/write")

    assert response.status_code == 200
    payload = response.json()
    sidecar = json.loads((Path(payload["output_dir"]) / "evidence-trail.json").read_text(encoding="utf-8"))
    assert sidecar["provenance_summary"]["no_evidence"] == 1
    assert sidecar["provenance_summary"]["by_type"]["cross_entity_rule"] == 1
    assert sidecar["evidence_links"][0]["suggestion_id"] == "x-new"


def test_export_write_does_not_count_superseded_same_field_review_as_no_evidence(monkeypatch, tmp_path):
    _seed_export_session(tmp_path)
    session = get_session()
    session.ks_workspace_state.suggestion_review_state.accepted_ids = ["s-old"]
    session.ks_workspace_state.suggestion_review_state.edited_ids = ["s-new"]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="s-old",
            type="field",
            status="accepted",
            manifest_path="entities.Account.fields.account_id",
            reviewed_at="2026-04-20T12:00:00+00:00",
        ),
        KSReviewHistoryEntry(
            suggestion_id="s-new",
            type="field",
            status="edited",
            manifest_path="entities.Account.fields.account_id",
            reviewed_at="2026-04-20T12:05:00+00:00",
            edited_payload={"field_name": "account_id"},
        ),
    ]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="entities.Account.fields.account_id",
            suggestion_id="s-new",
            provenance="ai-edited",
        )
    ]
    save_session(session)

    class FakeClient:
        def get_suggestion_evidence_chain(
            self,
            project_id: str,
            scope: str,
            suggestion_id: str,
        ):
            assert scope == "fields"
            assert suggestion_id == "s-new"
            return {
                "suggestion": {
                    "entity": "Account",
                    "field_name": "account_id",
                    "consistency_score": 0.88,
                },
                "evidence_chunks": [
                    {
                        "citation": {
                            "document_id": "doc-1",
                            "document_name": "Account BRD.pdf",
                            "chunk_id": "chunk-1",
                            "content_hash": "sha256:abc123",
                            "parser_version": "pdf-v1",
                            "section": "Section 4.1",
                            "snippet": "Account IDs must be unique.",
                        }
                    }
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.evidence_trail.ks_client", fake_ks_client)

    response = client.post("/export/write")

    assert response.status_code == 200
    payload = response.json()
    sidecar = json.loads(
        (Path(payload["output_dir"]) / "evidence-trail.json").read_text(encoding="utf-8")
    )
    assert sidecar["provenance_summary"]["no_evidence"] == 0


# ---------------------------------------------------------------------------
# Deterministic file-contract evidence (fixed-width and CSV) — Slice 1
# ---------------------------------------------------------------------------

_FIXED_WIDTH_INBOUND_SPEC = (
    "format: fixed-width\n"
    "record_types:\n"
    "  data:\n"
    "    fields:\n"
    "      - name: account_id\n"
    "        position: 1\n"
    "        length: 36\n"
    "      - name: available_balance\n"
    "        position: 37\n"
    "        length: 14\n"
)

_CSV_INBOUND_SPEC = (
    "format: csv\n"
    'delimiter: "|"\n'
    "has_header_row: true\n"
    "fields:\n"
    "  - name: account_number\n"
    "    column: 1\n"
    "  - name: available_balance\n"
    "    column: 2\n"
)

_CSV_OUTBOUND_SPEC = (
    "format: csv\n"
    'delimiter: "~"\n'
    "has_header_row: false\n"
    "fields:\n"
    "  - name: account_number\n"
    "    column: 1\n"
    "  - name: available_balance\n"
    "    column: 2\n"
)

_CSV_TRAILER_SPEC = (
    "format: csv\n"
    'delimiter: "|"\n'
    "record_types:\n"
    "  data:\n"
    "    fields:\n"
    "      - name: account_number\n"
    "        column: 1\n"
    "  trailer:\n"
    "    fields:\n"
    "      - name: record_count\n"
    "        column: 2\n"
    "control_mappings:\n"
    "  trailer:\n"
    "    - source: record_count\n"
    "      value_source: data_record_count\n"
)

_CSV_TRAILER_NO_CONTROL_SPEC = (
    "format: csv\n"
    'delimiter: "|"\n'
    "record_types:\n"
    "  data:\n"
    "    fields:\n"
    "      - name: account_number\n"
    "        column: 1\n"
    "  trailer:\n"
    "    fields:\n"
    "      - name: filler\n"
    "        column: 2\n"
)

_FIXED_WIDTH_TRAILER_SPEC = (
    "format: fixed-width\n"
    "record_types:\n"
    "  data:\n"
    "    fields:\n"
    "      - name: available_balance\n"
    "        position: 1\n"
    "        length: 14\n"
    "  trailer:\n"
    "    fields:\n"
    "      - name: total_balance\n"
    "        position: 1\n"
    "        length: 14\n"
    "        decimal_format: minor_units\n"
    "control_mappings:\n"
    "  trailer:\n"
    "    - source: total_balance\n"
    "      value_source: sum(Account.availableBalance)\n"
    "      type_coercion: major_to_minor_units\n"
)

_XML_CUSTOMER_XSD = (
    '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" '
    'targetNamespace="urn:customer" xmlns:cust="urn:customer">\n'
    '  <xs:element name="Customer">\n'
    "    <xs:complexType>\n"
    "      <xs:sequence>\n"
    '        <xs:element name="customerId" type="xs:string"/>\n'
    '        <xs:element name="status" type="xs:string"/>\n'
    "      </xs:sequence>\n"
    '      <xs:attribute name="tier" type="xs:string"/>\n'
    "    </xs:complexType>\n"
    "  </xs:element>\n"
    "</xs:schema>\n"
)

_XML_CUSTOMER_SAMPLE = (
    '<Customer xmlns="urn:customer" tier="gold">'
    "<customerId>C-100</customerId><status>ACTIVE</status>"
    "</Customer>\n"
)

_SOAP_CUSTOMER_WSDL = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<definitions xmlns="http://schemas.xmlsoap.org/wsdl/" '
    'xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/" '
    'targetNamespace="urn:customer-soap">\n'
    '  <service name="CustomerService">\n'
    '    <port name="CustomerPort" binding="tns:CustomerBinding">\n'
    '      <soap:address location="http://example.invalid/customer"/>\n'
    "    </port>\n"
    "  </service>\n"
    "</definitions>\n"
)


def _seed_file_contract_session(
    tmp_path: Path,
    *,
    upstream: list | None = None,
    downstream: list | None = None,
    handoffs: list | None = None,
    knowledge_assist: bool = False,
) -> None:
    """Seed a minimal file-contract project for export (Knowledge Assist OFF by default)."""
    session = ProjectSession()
    session.app_name = "File Contract App"
    session.bounded_context = "filebatch"
    session.target_profile = "springboot-legacy-compatible"
    session.output_path = str(tmp_path)
    session.upstream_interfaces = upstream or []
    session.downstream_interfaces = downstream or []
    session.data_handoffs = handoffs or []
    session.capabilities.knowledge_assist_enabled = knowledge_assist
    session.ks_active = knowledge_assist
    if knowledge_assist:
        session.project_id = "proj-file"
        session.ks_project_id = "proj-file"
    save_session(session)


def _read_sidecar(payload: dict) -> dict:
    return json.loads(
        (Path(payload["output_dir"]) / "evidence-trail.json").read_text(encoding="utf-8")
    )


def _human_authored_links(sidecar: dict) -> list[dict]:
    return [link for link in sidecar["evidence_links"] if link["provenance"] == "human-authored"]


def _ka_links(sidecar: dict) -> list[dict]:
    return [link for link in sidecar["evidence_links"] if link["provenance"] != "human-authored"]


def _fail_if_ks_called(monkeypatch) -> None:
    @contextmanager
    def unexpected_ks_client(**kwargs):
        raise AssertionError("deterministic edge-contract evidence must not call Knowledge Server")
        yield

    monkeypatch.setattr("app.services.evidence_trail.ks_client", unexpected_ks_client)


def _assert_no_absolute_paths(sidecar: dict, tmp_path: Path) -> None:
    serialized = json.dumps(sidecar)
    assert str(tmp_path) not in serialized
    for link in _human_authored_links(sidecar):
        for key in ("source_artifact", "sample_artifact", "xsd_path", "sample_path", "mapping_artifact"):
            value = link["metadata"].get(key)
            if value is not None:
                assert not value.startswith("/"), f"{key} must be package-relative: {value}"
                assert ":" not in value.split("/")[0], f"{key} must not be a URL: {value}"


def _add_customer_entity_model() -> None:
    session = get_session()
    session.classified_entities = [
        ClassifiedEntity(
            name="Customer",
            fields=[
                ClassifiedField(name="customerId", type="string", required=True, is_id=True),
                ClassifiedField(name="availableBalance", type="decimal"),
                ClassifiedField(name="status", type="string"),
                ClassifiedField(name="name", type="string"),
            ],
        )
    ]
    session.selected_entity_names = ["Customer"]
    save_session(session)


def _add_placeholder_openapi_upstream() -> None:
    session = get_session()
    session.upstream_interfaces.append(
        UpstreamInterface(
            name="customer-openapi",
            type="rest-json",
            spec="contracts/customer-openapi.yaml",
        )
    )
    save_session(session)


def test_export_write_emits_fixed_width_inbound_file_contract_evidence(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        upstream=[
            UpstreamInterface(
                name="account-fixed-inbound",
                type="file-fixed-width",
                entity_name="Account",
                spec_content=_FIXED_WIDTH_INBOUND_SPEC,
                field_mappings=[
                    FieldMapping(source="account_id", target="accountId"),
                    FieldMapping(source="available_balance", target="availableBalance"),
                ],
                sample_path="upstream/sample-account-fixed.dat",
                sample_content="ACC-0001                            00000000012345\n",
            )
        ],
    )

    response = client.post("/export/write")
    assert response.status_code == 200
    sidecar = _read_sidecar(response.json())

    links = _human_authored_links(sidecar)
    assert len(links) == 2
    by_path = {link["manifest_path"]: link for link in links}
    record = by_path["upstream_interfaces.account-fixed-inbound.layout.account_id"]
    assert record["suggestion_type"] == "field"
    assert record["provenance"] == "human-authored"
    assert record["citations"] == []
    assert "suggestion_id" not in record
    assert "type" not in record  # do not introduce a new top-level type
    meta = record["metadata"]
    assert meta["file_format"] == "fixed-width"
    assert meta["contract_type"] == "file-fixed-width"
    assert meta["interface_direction"] == "upstream"
    assert meta["direction"] == "inbound"
    assert meta["record_type"] == "data"
    assert meta["layout_field"] == "account_id"
    assert meta["field_position"] == 1
    assert meta["field_length"] == 36
    assert meta["source_path"] == "account_id"
    assert meta["target_path"] == "Account.accountId"
    assert meta["sample_artifact"] == "upstream/sample-account-fixed.dat"
    # second mapped data field carries its own position/length
    second = by_path["upstream_interfaces.account-fixed-inbound.layout.available_balance"]
    assert second["metadata"]["field_position"] == 37
    assert second["metadata"]["field_length"] == 14
    assert second["metadata"]["target_path"] == "Account.availableBalance"
    _assert_no_absolute_paths(sidecar, tmp_path)


def test_export_write_emits_fixed_width_outbound_file_contract_evidence(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        downstream=[
            DownstreamInterface(
                name="eod-account-out",
                type="file-fixed-width",
                entity_name="Account",
                layout_fields=[
                    LayoutField(name="account_id", start=1, length=12),
                    LayoutField(name="balance", start=13, length=14),
                ],
                field_mappings=[
                    FieldMapping(source="Account.accountId", target="account_id"),
                    FieldMapping(source="Account.availableBalance", target="balance"),
                ],
            )
        ],
    )

    response = client.post("/export/write")
    assert response.status_code == 200
    sidecar = _read_sidecar(response.json())

    links = _human_authored_links(sidecar)
    assert len(links) == 2
    record = next(
        link
        for link in links
        if link["manifest_path"] == "downstream_interfaces.eod-account-out.layout.account_id"
    )
    assert record["suggestion_type"] == "field"
    meta = record["metadata"]
    assert meta["interface_direction"] == "downstream"
    assert meta["direction"] == "outbound"
    assert meta["file_format"] == "fixed-width"
    assert meta["field_position"] == 1
    assert meta["field_length"] == 12
    # outbound: canonical is the source, file field is the target
    assert meta["source_path"] == "Account.accountId"
    assert meta["target_path"] == "account_id"
    assert meta["layout_field"] == "account_id"
    _assert_no_absolute_paths(sidecar, tmp_path)


def test_export_write_emits_csv_inbound_file_contract_evidence(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        upstream=[
            UpstreamInterface(
                name="account-csv-inbound",
                type="file-csv",
                entity_name="Account",
                spec_content=_CSV_INBOUND_SPEC,
                field_mappings=[
                    FieldMapping(source="account_number", target="accountId"),
                    FieldMapping(source="available_balance", target="availableBalance"),
                ],
            )
        ],
    )

    response = client.post("/export/write")
    assert response.status_code == 200
    sidecar = _read_sidecar(response.json())

    record = next(
        link
        for link in _human_authored_links(sidecar)
        if link["manifest_path"] == "upstream_interfaces.account-csv-inbound.layout.account_number"
    )
    assert record["suggestion_type"] == "field"
    meta = record["metadata"]
    assert meta["file_format"] == "csv"
    assert meta["contract_type"] == "file-csv"
    assert meta["direction"] == "inbound"
    assert meta["csv_column_index"] == 1
    assert meta["delimiter"] == "|"
    assert meta["source_path"] == "account_number"
    assert meta["target_path"] == "Account.accountId"
    assert "field_position" not in meta  # not a fixed-width contract
    _assert_no_absolute_paths(sidecar, tmp_path)


def test_export_write_emits_csv_outbound_file_contract_evidence(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        downstream=[
            DownstreamInterface(
                name="ledger-csv-out",
                type="file-csv",
                entity_name="Account",
                spec_content=_CSV_OUTBOUND_SPEC,
                field_mappings=[
                    FieldMapping(source="Account.accountId", target="account_number"),
                    FieldMapping(source="Account.availableBalance", target="available_balance"),
                ],
            )
        ],
    )

    response = client.post("/export/write")
    assert response.status_code == 200
    sidecar = _read_sidecar(response.json())

    record = next(
        link
        for link in _human_authored_links(sidecar)
        if link["manifest_path"] == "downstream_interfaces.ledger-csv-out.layout.available_balance"
    )
    assert record["suggestion_type"] == "field"
    meta = record["metadata"]
    assert meta["file_format"] == "csv"
    assert meta["direction"] == "outbound"
    assert meta["interface_direction"] == "downstream"
    assert meta["csv_column_index"] == 2
    assert meta["delimiter"] == "~"
    assert meta["source_path"] == "Account.availableBalance"
    assert meta["target_path"] == "available_balance"
    _assert_no_absolute_paths(sidecar, tmp_path)


def test_file_contract_evidence_uses_metadata_object_and_existing_suggestion_types(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        upstream=[
            UpstreamInterface(
                name="account-fixed-inbound",
                type="file-fixed-width",
                entity_name="Account",
                spec_content=_FIXED_WIDTH_INBOUND_SPEC,
                field_mappings=[FieldMapping(source="account_id", target="accountId")],
            )
        ],
    )

    response = client.post("/export/write")
    assert response.status_code == 200
    sidecar = _read_sidecar(response.json())

    # No new evidence type — reuse existing v1.1 suggestion_type values only.
    assert "file_contract" not in json.dumps(sidecar)
    supported = {"field", "validation", "rule", "cross_entity_rule", "mapping", "transform"}
    for link in _human_authored_links(sidecar):
        assert "metadata" in link  # edge-contract details live under metadata
        assert link["suggestion_type"] in supported
        assert "type" not in link  # never a top-level `type` key


def test_file_contract_evidence_increments_human_authored_and_by_type(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        upstream=[
            UpstreamInterface(
                name="account-csv-inbound",
                type="file-csv",
                entity_name="Account",
                spec_content=_CSV_TRAILER_SPEC,
                field_mappings=[FieldMapping(source="account_number", target="accountId")],
            )
        ],
    )

    response = client.post("/export/write")
    assert response.status_code == 200
    sidecar = _read_sidecar(response.json())

    summary = sidecar["provenance_summary"]
    # one data field (`field`) + one trailer control (`validation`)
    assert summary["human_authored"] == 2
    assert summary["ai_accepted"] == 0
    assert summary["ai_edited"] == 0
    assert summary["by_type"]["field"] == 1
    assert summary["by_type"]["validation"] == 1
    assert summary["by_type"]["mapping"] == 0


def test_file_contract_evidence_emits_csv_trailer_validation_when_value_source_present(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        upstream=[
            UpstreamInterface(
                name="account-csv-inbound",
                type="file-csv",
                entity_name="Account",
                spec_content=_CSV_TRAILER_SPEC,
                field_mappings=[FieldMapping(source="account_number", target="accountId")],
            )
        ],
    )

    response = client.post("/export/write")
    assert response.status_code == 200
    sidecar = _read_sidecar(response.json())

    trailer = next(
        link
        for link in _human_authored_links(sidecar)
        if link["metadata"].get("record_type") == "trailer"
    )
    assert trailer["suggestion_type"] == "validation"
    assert trailer["manifest_path"] == "upstream_interfaces.account-csv-inbound.trailer.record_count"
    meta = trailer["metadata"]
    assert meta["mapping_scope"] == "trailer_validation"
    assert meta["value_source"] == "data_record_count"
    assert meta["csv_column_index"] == 2
    assert meta["delimiter"] == "|"


def test_fixed_width_trailer_sum_carries_decimal_format_and_type_coercion(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        downstream=[
            DownstreamInterface(
                name="eod-recon-out",
                type="file-fixed-width",
                entity_name="Account",
                spec_content=_FIXED_WIDTH_TRAILER_SPEC,
                field_mappings=[FieldMapping(source="Account.availableBalance", target="available_balance")],
            )
        ],
    )

    response = client.post("/export/write")
    assert response.status_code == 200
    sidecar = _read_sidecar(response.json())

    trailer = next(
        link
        for link in _human_authored_links(sidecar)
        if link["metadata"].get("record_type") == "trailer"
    )
    meta = trailer["metadata"]
    assert meta["value_source"] == "sum(Account.availableBalance)"
    assert meta["decimal_format"] == "minor_units"
    assert meta["type_coercion"] == "major_to_minor_units"
    assert meta["field_position"] == 1
    assert meta["field_length"] == 14


def test_file_contract_trailer_evidence_omitted_without_explicit_value_source(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        upstream=[
            UpstreamInterface(
                name="account-csv-inbound",
                type="file-csv",
                entity_name="Account",
                spec_content=_CSV_TRAILER_NO_CONTROL_SPEC,
                field_mappings=[FieldMapping(source="account_number", target="accountId")],
            )
        ],
    )

    response = client.post("/export/write")
    assert response.status_code == 200
    sidecar = _read_sidecar(response.json())

    # trailer present in layout but no control value_source → no trailer evidence invented
    assert all(
        link["metadata"].get("record_type") != "trailer"
        for link in _human_authored_links(sidecar)
    )
    assert "trailer" not in json.dumps([link["manifest_path"] for link in sidecar["evidence_links"]])


def test_file_contract_evidence_emitted_with_knowledge_assist_off_without_ks(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        knowledge_assist=False,
        downstream=[
            DownstreamInterface(
                name="eod-account-out",
                type="file-fixed-width",
                entity_name="Account",
                layout_fields=[LayoutField(name="account_id", start=1, length=12)],
                field_mappings=[FieldMapping(source="Account.accountId", target="account_id")],
            )
        ],
    )

    response = client.post("/export/write")
    assert response.status_code == 200
    sidecar = _read_sidecar(response.json())

    # KA OFF: project_id stays null, but deterministic file evidence is still present.
    assert sidecar["project_id"] is None
    assert len(_human_authored_links(sidecar)) == 1
    assert _ka_links(sidecar) == []
    assert sidecar["provenance_summary"]["human_authored"] == 1


def test_file_contract_evidence_is_deterministic_across_exports(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        upstream=[
            UpstreamInterface(
                name="account-csv-inbound",
                type="file-csv",
                entity_name="Account",
                spec_content=_CSV_INBOUND_SPEC,
                field_mappings=[
                    FieldMapping(source="account_number", target="accountId"),
                    FieldMapping(source="available_balance", target="availableBalance"),
                ],
            )
        ],
    )

    first = _read_sidecar(client.post("/export/write").json())
    second = _read_sidecar(client.post("/export/write").json())

    assert first["evidence_links"] == second["evidence_links"]
    assert first["provenance_summary"] == second["provenance_summary"]


def test_export_write_emits_upstream_xml_xsd_validation_metadata(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        upstream=[
            UpstreamInterface(
                name="customer-xml-in",
                type="xml-xsd",
                xsd_path="upstream/customer.xsd",
                xsd_content=_XML_CUSTOMER_XSD,
                root_element="Customer",
                namespace="urn:customer",
                namespace_alias="cust",
                sample_path="upstream/customer-sample.xml",
                sample_content=_XML_CUSTOMER_SAMPLE,
            )
        ],
    )

    response = client.post("/export/write")
    assert response.status_code == 200
    sidecar = _read_sidecar(response.json())

    links = _human_authored_links(sidecar)
    assert len(links) == 1
    record = links[0]
    assert record["manifest_path"] == "upstream_interfaces.customer-xml-in.xsd.Customer"
    assert record["suggestion_type"] == "validation"
    assert record["provenance"] == "human-authored"
    assert record["citations"] == []
    assert "suggestion_id" not in record
    assert "xml_xsd" not in json.dumps(record)
    meta = record["metadata"]
    assert meta["artifact_type"] == "xsd"
    assert meta["contract_type"] == "xml-xsd"
    assert meta["interface_direction"] == "upstream"
    assert meta["mapping_scope"] == "inbound"
    assert meta["xml_root"] == "Customer"
    assert meta["namespace"] == "urn:customer"
    assert meta["xsd_path"] == "upstream/customer.xsd"
    assert meta["source_artifact"] == "upstream/customer.xsd"
    assert meta["sample_artifact"] == "upstream/customer-sample.xml"
    assert meta["sample_path"] == "upstream/customer-sample.xml"
    _assert_no_absolute_paths(sidecar, tmp_path)


def test_export_write_emits_downstream_xml_xsd_validation_metadata(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        downstream=[
            DownstreamInterface(
                name="customer-xml-out",
                type="xml-xsd",
                xsd_path="downstream/customer-response.xsd",
                xsd_content=_XML_CUSTOMER_XSD,
                root_element="Customer",
                namespace="urn:customer",
            )
        ],
    )

    response = client.post("/export/write")
    assert response.status_code == 200
    sidecar = _read_sidecar(response.json())

    record = _human_authored_links(sidecar)[0]
    assert record["manifest_path"] == "downstream_interfaces.customer-xml-out.xsd.Customer"
    assert record["suggestion_type"] == "validation"
    meta = record["metadata"]
    assert meta["interface_direction"] == "downstream"
    assert meta["mapping_scope"] == "outbound"
    assert meta["artifact_type"] == "xsd"
    assert meta["xml_root"] == "Customer"
    assert meta["xsd_path"] == "downstream/customer-response.xsd"
    _assert_no_absolute_paths(sidecar, tmp_path)


def test_export_write_emits_upstream_xml_to_canonical_mapping_metadata(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        upstream=[
            UpstreamInterface(
                name="customer-xml-in",
                type="xml-xsd",
                entity_name="Customer",
                xsd_path="upstream/customer.xsd",
                xsd_content=_XML_CUSTOMER_XSD,
                root_element="Customer",
                namespace="urn:customer",
                field_mappings=[
                    FieldMapping(source="/Customer/customerId", target="customerId"),
                    FieldMapping(source="/Customer/@tier", target="Customer.tier"),
                ],
            )
        ],
    )

    response = client.post("/export/write")
    assert response.status_code == 200
    payload = response.json()
    sidecar = _read_sidecar(payload)
    manifest = yaml.safe_load(
        (Path(payload["output_dir"]) / "app-definition.yaml").read_text(encoding="utf-8")
    )
    assert manifest["upstream_interfaces"][0]["mapping"] == "upstream/customer-xml-in-mapping.yaml"

    links = _human_authored_links(sidecar)
    assert [link["suggestion_type"] for link in links] == ["validation", "mapping", "mapping"]
    mapping = next(
        link
        for link in links
        if link["metadata"].get("source_path") == "/Customer/customerId"
    )
    meta = mapping["metadata"]
    assert meta["mapping_scope"] == "inbound"
    assert meta["source_path"] == "/Customer/customerId"
    assert meta["target_path"] == "Customer.customerId"
    assert meta["xpath"] == "/Customer/customerId"
    assert meta["xml_field_kind"] == "element"
    attribute = next(link for link in links if link["metadata"].get("xpath") == "/Customer/@tier")
    assert attribute["metadata"]["xml_field_kind"] == "attribute"
    _assert_no_absolute_paths(sidecar, tmp_path)


def test_export_write_emits_downstream_canonical_to_xml_mapping_metadata(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        downstream=[
            DownstreamInterface(
                name="customer-xml-out",
                type="xml-xsd",
                entity_name="Customer",
                xsd_path="downstream/customer-response.xsd",
                xsd_content=_XML_CUSTOMER_XSD,
                root_element="Customer",
                namespace="urn:customer",
                field_mappings=[
                    FieldMapping(source="customerId", target="/Customer/customerId"),
                    FieldMapping(source="Customer.status", target="/Customer/status"),
                ],
            )
        ],
    )

    response = client.post("/export/write")
    assert response.status_code == 200
    payload = response.json()
    sidecar = _read_sidecar(payload)
    manifest = yaml.safe_load(
        (Path(payload["output_dir"]) / "app-definition.yaml").read_text(encoding="utf-8")
    )
    assert manifest["downstream_interfaces"][0]["mapping"] == "downstream/customer-xml-out-mapping.yaml"

    links = _human_authored_links(sidecar)
    mapping = next(
        link
        for link in links
        if link["metadata"].get("target_path") == "/Customer/customerId"
    )
    meta = mapping["metadata"]
    assert mapping["suggestion_type"] == "mapping"
    assert meta["interface_direction"] == "downstream"
    assert meta["mapping_scope"] == "outbound"
    assert meta["source_path"] == "Customer.customerId"
    assert meta["target_path"] == "/Customer/customerId"
    assert meta["xpath"] == "/Customer/customerId"
    assert meta["xml_field_kind"] == "element"
    _assert_no_absolute_paths(sidecar, tmp_path)


def test_xml_xsd_evidence_increments_human_authored_and_by_type(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        upstream=[
            UpstreamInterface(
                name="customer-xml-in",
                type="xml-xsd",
                entity_name="Customer",
                xsd_path="upstream/customer.xsd",
                xsd_content=_XML_CUSTOMER_XSD,
                root_element="Customer",
                field_mappings=[
                    FieldMapping(source="/Customer/customerId", target="customerId"),
                ],
            )
        ],
    )

    response = client.post("/export/write")
    assert response.status_code == 200
    sidecar = _read_sidecar(response.json())

    summary = sidecar["provenance_summary"]
    assert summary["human_authored"] == 2
    assert summary["ai_accepted"] == 0
    assert summary["ai_edited"] == 0
    assert summary["by_type"]["validation"] == 1
    assert summary["by_type"]["mapping"] == 1
    assert "xml_contract" not in json.dumps(sidecar)
    assert "edge_contract" not in json.dumps(sidecar)


def test_xml_xsd_mapping_evidence_skipped_when_mapping_is_not_exported(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        upstream=[
            UpstreamInterface(
                name="customer-xml-in",
                type="xml-xsd",
                entity_name="",
                xsd_path="upstream/customer.xsd",
                xsd_content=_XML_CUSTOMER_XSD,
                root_element="Customer",
                field_mappings=[
                    FieldMapping(source="/Customer/customerId", target="customerId"),
                ],
            )
        ],
    )

    response = client.post("/export/write")
    assert response.status_code == 200
    payload = response.json()
    sidecar = _read_sidecar(payload)
    manifest = yaml.safe_load(
        (Path(payload["output_dir"]) / "app-definition.yaml").read_text(encoding="utf-8")
    )

    assert "mapping" not in manifest["upstream_interfaces"][0]
    links = _human_authored_links(sidecar)
    assert len(links) == 1
    assert links[0]["suggestion_type"] == "validation"
    assert sidecar["provenance_summary"]["by_type"]["mapping"] == 0
    assert "customerId" not in json.dumps(sidecar["evidence_links"])


def test_xml_xsd_evidence_is_deterministic_across_exports(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        upstream=[
            UpstreamInterface(
                name="customer-xml-in",
                type="xml-xsd",
                entity_name="Customer",
                xsd_path="upstream/customer.xsd",
                xsd_content=_XML_CUSTOMER_XSD,
                root_element="Customer",
                namespace="urn:customer",
                field_mappings=[
                    FieldMapping(source="/Customer/customerId", target="customerId"),
                    FieldMapping(source="/Customer/status", target="status"),
                ],
            )
        ],
    )

    first = _read_sidecar(client.post("/export/write").json())
    second = _read_sidecar(client.post("/export/write").json())

    assert first["evidence_links"] == second["evidence_links"]
    assert first["provenance_summary"] == second["provenance_summary"]


def test_export_write_emits_upstream_soap_adapter_operation_metadata(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        upstream=[
            UpstreamInterface(
                name="customer-soap-service",
                type="soap-wsdl",
                wsdl_path="upstream/customer-service.wsdl",
                wsdl_content=_SOAP_CUSTOMER_WSDL,
                service="CustomerService",
                port="CustomerPort",
                binding="CustomerBinding",
                namespace="urn:customer-soap",
                selected_operation_name="getCustomer",
                soap_operation_mode="adapter_only",
            )
        ],
    )

    response = client.post("/export/write")
    assert response.status_code == 200
    payload = response.json()
    sidecar = _read_sidecar(payload)
    manifest = yaml.safe_load(
        (Path(payload["output_dir"]) / "app-definition.yaml").read_text(encoding="utf-8")
    )
    assert manifest["upstream_interfaces"][0]["mapping"] == "mappings/customer-soap-service-operation-mapping.yaml"

    links = _human_authored_links(sidecar)
    assert len(links) == 1
    record = links[0]
    assert record["suggestion_type"] == "validation"
    assert record["manifest_path"] == "upstream_interfaces.customer-soap-service.soap.operation.getCustomer"
    meta = record["metadata"]
    assert meta["artifact_type"] == "wsdl"
    assert meta["contract_type"] == "soap-wsdl"
    assert meta["interface_direction"] == "upstream"
    assert meta["mapping_scope"] == "inbound"
    assert meta["operation_name"] == "getCustomer"
    assert meta["wsdl_service"] == "CustomerService"
    assert meta["wsdl_port"] == "CustomerPort"
    assert meta["wsdl_binding"] == "CustomerBinding"
    assert meta["wsdl_operation"] == "getCustomer"
    assert meta["namespace"] == "urn:customer-soap"
    assert meta["source_artifact"] == "upstream/customer-service.wsdl"
    assert meta["mapping_artifact"] == "mappings/customer-soap-service-operation-mapping.yaml"
    assert "canonical_operation" not in json.dumps(sidecar)
    _assert_no_absolute_paths(sidecar, tmp_path)


def test_export_write_emits_upstream_soap_canonical_read_by_id_metadata(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        upstream=[
            UpstreamInterface(
                name="customer-soap-service",
                type="soap-wsdl",
                wsdl_path="upstream/customer-service.wsdl",
                wsdl_content=_SOAP_CUSTOMER_WSDL,
                service="CustomerService",
                port="CustomerPort",
                binding="CustomerBinding",
                namespace="urn:customer-soap",
                selected_operation_name="getCustomer",
                soap_operation_mode="canonical",
                soap_canonical_operation=SoapCanonicalOperationConfig(
                    entity="Customer",
                    lookup_field="customerId",
                    request_path="/GetCustomerRequest/customerId",
                    response_mappings=[
                        SoapResponseMapping(
                            source="Customer.customerId",
                            target_path="/GetCustomerResponse/customerId",
                        ),
                        SoapResponseMapping(
                            source="Customer.name",
                            target_path="/GetCustomerResponse/name",
                        ),
                    ],
                    not_found_fault="CustomerNotFoundFault",
                    not_found_message="Customer not found",
                ),
            )
        ],
    )
    _add_customer_entity_model()

    response = client.post("/export/write")
    assert response.status_code == 200
    sidecar = _read_sidecar(response.json())

    links = _human_authored_links(sidecar)
    assert [link["suggestion_type"] for link in links] == [
        "validation",
        "field",
        "mapping",
        "mapping",
        "mapping",
        "validation",
    ]
    lookup = next(link for link in links if link["suggestion_type"] == "field")
    assert lookup["metadata"]["namespace"] == "urn:customer-soap"
    assert lookup["metadata"]["mapping_scope"] == "lookup"
    assert lookup["metadata"]["source_path"] == "/GetCustomerRequest/customerId"
    assert lookup["metadata"]["target_path"] == "Customer.customerId"
    assert lookup["metadata"]["soap_body_path"] == "/GetCustomerRequest/customerId"

    request_mapping = next(
        link
        for link in links
        if link["suggestion_type"] == "mapping"
        and link["metadata"].get("mapping_scope") == "request"
    )
    assert request_mapping["metadata"]["source_path"] == "/GetCustomerRequest/customerId"
    assert request_mapping["metadata"]["target_path"] == "Customer.customerId"

    response_mapping = next(
        link
        for link in links
        if link["metadata"].get("target_path") == "/GetCustomerResponse/name"
    )
    assert response_mapping["metadata"]["mapping_scope"] == "response"
    assert response_mapping["metadata"]["source_path"] == "Customer.name"
    assert response_mapping["metadata"]["soap_body_path"] == "/GetCustomerResponse/name"

    fault = next(link for link in links if link["metadata"].get("soap_fault") == "CustomerNotFoundFault")
    assert fault["suggestion_type"] == "validation"
    assert fault["metadata"]["mapping_scope"] == "fault"
    summary = sidecar["provenance_summary"]
    assert summary["human_authored"] == 6
    assert summary["by_type"]["validation"] == 2
    assert summary["by_type"]["field"] == 1
    assert summary["by_type"]["mapping"] == 3
    _assert_no_absolute_paths(sidecar, tmp_path)


def test_export_write_emits_downstream_soap_adapter_operation_metadata(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        downstream=[
            DownstreamInterface(
                name="customer-soap-client",
                type="soap-wsdl",
                wsdl_path="downstream/customer-client.wsdl",
                wsdl_content=_SOAP_CUSTOMER_WSDL,
                service="CustomerService",
                port="CustomerPort",
                binding="CustomerBinding",
                namespace="urn:customer-soap",
                selected_operation_name="syncCustomer",
                soap_operation_mode="adapter_only",
            )
        ],
    )

    response = client.post("/export/write")
    assert response.status_code == 200
    sidecar = _read_sidecar(response.json())

    links = _human_authored_links(sidecar)
    assert len(links) == 1
    record = links[0]
    assert record["suggestion_type"] == "validation"
    assert record["manifest_path"] == "downstream_interfaces.customer-soap-client.soap.operation.syncCustomer"
    meta = record["metadata"]
    assert meta["interface_direction"] == "downstream"
    assert meta["mapping_scope"] == "outbound"
    assert meta["operation_name"] == "syncCustomer"
    assert meta["wsdl_operation"] == "syncCustomer"
    assert meta["namespace"] == "urn:customer-soap"
    assert meta["source_artifact"] == "downstream/customer-client.wsdl"
    assert meta["mapping_artifact"] == "mappings/customer-soap-client-operation-mapping.yaml"
    assert "canonical_operation" not in json.dumps(sidecar)
    _assert_no_absolute_paths(sidecar, tmp_path)


def test_export_write_emits_downstream_soap_canonical_invoke_by_id_metadata(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        downstream=[
            DownstreamInterface(
                name="customer-soap-client",
                type="soap-wsdl",
                wsdl_path="downstream/customer-client.wsdl",
                wsdl_content=_SOAP_CUSTOMER_WSDL,
                service="CustomerService",
                port="CustomerPort",
                binding="CustomerBinding",
                namespace="urn:customer-soap",
                selected_operation_name="syncCustomer",
                soap_operation_mode="canonical",
                soap_canonical_invocation=SoapCanonicalInvocationConfig(
                    entity="Customer",
                    lookup_field="customerId",
                    request_field="id",
                    request_mappings=[
                        SoapRequestMapping(
                            source="Customer.customerId",
                            target_path="/SyncCustomerRequest/customerId",
                        ),
                        SoapRequestMapping(
                            source="Customer.status",
                            target_path="/SyncCustomerRequest/status",
                        ),
                    ],
                    response_mappings=[
                        SoapReturnMapping(
                            source_path="/SyncCustomerResponse/resultCode",
                            target="resultCode",
                        ),
                        SoapReturnMapping(
                            source_path="/SyncCustomerResponse/message",
                            target="message",
                        ),
                    ],
                ),
            )
        ],
    )
    _add_customer_entity_model()
    _add_placeholder_openapi_upstream()

    response = client.post("/export/write")
    assert response.status_code == 200
    payload = response.json()
    sidecar = _read_sidecar(payload)
    manifest = yaml.safe_load(
        (Path(payload["output_dir"]) / "app-definition.yaml").read_text(encoding="utf-8")
    )
    assert manifest["downstream_interfaces"][0]["mapping"] == "mappings/customer-soap-client-operation-mapping.yaml"

    links = _human_authored_links(sidecar)
    assert [link["suggestion_type"] for link in links] == [
        "validation",
        "field",
        "mapping",
        "mapping",
        "mapping",
        "mapping",
    ]
    lookup = next(link for link in links if link["suggestion_type"] == "field")
    assert lookup["metadata"]["namespace"] == "urn:customer-soap"
    assert lookup["metadata"]["mapping_scope"] == "lookup"
    assert lookup["metadata"]["source_path"] == "id"
    assert lookup["metadata"]["target_path"] == "Customer.customerId"

    request_mapping = next(
        link
        for link in links
        if link["metadata"].get("target_path") == "/SyncCustomerRequest/status"
    )
    assert request_mapping["metadata"]["mapping_scope"] == "request"
    assert request_mapping["metadata"]["source_path"] == "Customer.status"
    assert request_mapping["metadata"]["soap_body_path"] == "/SyncCustomerRequest/status"

    response_mapping = next(
        link
        for link in links
        if link["metadata"].get("source_path") == "/SyncCustomerResponse/message"
    )
    assert response_mapping["metadata"]["mapping_scope"] == "response"
    assert response_mapping["metadata"]["target_path"] == "message"
    assert response_mapping["metadata"]["soap_body_path"] == "/SyncCustomerResponse/message"

    summary = sidecar["provenance_summary"]
    assert summary["human_authored"] == 6
    assert summary["by_type"]["validation"] == 1
    assert summary["by_type"]["field"] == 1
    assert summary["by_type"]["mapping"] == 4
    assert summary["ai_accepted"] == 0
    assert summary["ai_edited"] == 0
    _assert_no_absolute_paths(sidecar, tmp_path)


def test_soap_wsdl_evidence_is_deterministic_across_exports(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        downstream=[
            DownstreamInterface(
                name="customer-soap-client",
                type="soap-wsdl",
                wsdl_path="downstream/customer-client.wsdl",
                wsdl_content=_SOAP_CUSTOMER_WSDL,
                service="CustomerService",
                port="CustomerPort",
                binding="CustomerBinding",
                namespace="urn:customer-soap",
                selected_operation_name="syncCustomer",
                soap_operation_mode="canonical",
                soap_canonical_invocation=SoapCanonicalInvocationConfig(
                    entity="Customer",
                    lookup_field="customerId",
                    request_field="id",
                    request_mappings=[
                        SoapRequestMapping(
                            source="Customer.customerId",
                            target_path="/SyncCustomerRequest/customerId",
                        ),
                    ],
                    response_mappings=[
                        SoapReturnMapping(
                            source_path="/SyncCustomerResponse/resultCode",
                            target="resultCode",
                        ),
                    ],
                ),
            )
        ],
    )
    _add_customer_entity_model()
    _add_placeholder_openapi_upstream()

    first = _read_sidecar(client.post("/export/write").json())
    second = _read_sidecar(client.post("/export/write").json())

    assert first["evidence_links"] == second["evidence_links"]
    assert first["provenance_summary"] == second["provenance_summary"]


def test_edge_contract_evidence_trail_combines_file_xml_and_soap_metadata(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        upstream=[
            UpstreamInterface(
                name="customer-fixed-in",
                type="file-fixed-width",
                entity_name="Customer",
                spec="upstream/customer-fixed-layout.yaml",
                spec_content=_FIXED_WIDTH_INBOUND_SPEC,
                field_mappings=[
                    FieldMapping(source="account_id", target="customerId"),
                    FieldMapping(source="available_balance", target="availableBalance"),
                ],
                sample_path="upstream/customer-fixed-sample.dat",
                sample_content="C-100                               00000000012345\n",
            ),
            UpstreamInterface(
                name="customer-csv-in",
                type="file-csv",
                entity_name="Customer",
                spec="upstream/customer-csv-layout.yaml",
                spec_content=_CSV_INBOUND_SPEC,
                field_mappings=[
                    FieldMapping(source="account_number", target="customerId"),
                ],
            ),
            UpstreamInterface(
                name="customer-xml-in",
                type="xml-xsd",
                entity_name="Customer",
                xsd_path="upstream/customer.xsd",
                xsd_content=_XML_CUSTOMER_XSD,
                root_element="Customer",
                namespace="urn:customer",
                namespace_alias="cust",
                sample_path="upstream/customer-sample.xml",
                sample_content=_XML_CUSTOMER_SAMPLE,
                field_mappings=[
                    FieldMapping(source="/Customer/customerId", target="customerId"),
                ],
            ),
            UpstreamInterface(
                name="customer-soap-service",
                type="soap-wsdl",
                wsdl_path="upstream/customer-service.wsdl",
                wsdl_content=_SOAP_CUSTOMER_WSDL,
                service="CustomerService",
                port="CustomerPort",
                binding="CustomerBinding",
                namespace="urn:customer-soap",
                selected_operation_name="getCustomer",
                soap_operation_mode="canonical",
                soap_canonical_operation=SoapCanonicalOperationConfig(
                    entity="Customer",
                    lookup_field="customerId",
                    request_path="/GetCustomerRequest/customerId",
                    response_mappings=[
                        SoapResponseMapping(
                            source="Customer.name",
                            target_path="/GetCustomerResponse/name",
                        ),
                    ],
                    not_found_fault="CustomerNotFoundFault",
                ),
            ),
        ],
        downstream=[
            DownstreamInterface(
                name="customer-csv-out",
                type="file-csv",
                entity_name="Customer",
                spec="downstream/customer-csv-layout.yaml",
                spec_content=_CSV_OUTBOUND_SPEC,
                field_mappings=[
                    FieldMapping(source="Customer.customerId", target="account_number"),
                ],
            ),
            DownstreamInterface(
                name="customer-xml-out",
                type="xml-xsd",
                entity_name="Customer",
                xsd_path="downstream/customer-response.xsd",
                xsd_content=_XML_CUSTOMER_XSD,
                root_element="Customer",
                namespace="urn:customer",
                field_mappings=[
                    FieldMapping(source="Customer.status", target="/Customer/status"),
                ],
            ),
            DownstreamInterface(
                name="customer-soap-client",
                type="soap-wsdl",
                wsdl_path="downstream/customer-client.wsdl",
                wsdl_content=_SOAP_CUSTOMER_WSDL,
                service="CustomerService",
                port="CustomerPort",
                binding="CustomerBinding",
                namespace="urn:customer-soap",
                selected_operation_name="syncCustomer",
                soap_operation_mode="canonical",
                soap_canonical_invocation=SoapCanonicalInvocationConfig(
                    entity="Customer",
                    lookup_field="customerId",
                    request_field="id",
                    request_mappings=[
                        SoapRequestMapping(
                            source="Customer.status",
                            target_path="/SyncCustomerRequest/status",
                        ),
                    ],
                    response_mappings=[
                        SoapReturnMapping(
                            source_path="/SyncCustomerResponse/resultCode",
                            target="resultCode",
                        ),
                    ],
                ),
            ),
        ],
    )
    _add_customer_entity_model()
    session = get_session()
    session.identity_role_decisions = [
        IdentityRoleDecision(
            entity="Customer",
            field="customerId",
            role="persistence_id",
            provenance="human-authored",
            reviewed_at="2026-06-08T00:00:00+00:00",
        )
    ]
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="advisory-1",
            type="portfolio_reuse",
            status="accepted",
            manifest_path="advisories.portfolio.customer",
            reviewed_at="2026-06-08T00:00:00+00:00",
        )
    ]
    save_session(session)

    first_response = client.post("/export/write")
    assert first_response.status_code == 200
    first = _read_sidecar(first_response.json())
    second = _read_sidecar(client.post("/export/write").json())

    assert first["schema_version"] == "1.1"
    assert first["project_id"] is None
    assert first["evidence_links"] == second["evidence_links"]
    assert first["provenance_summary"] == second["provenance_summary"]
    _assert_no_absolute_paths(first, tmp_path)

    links = _human_authored_links(first)
    assert len(links) == 17
    assert {link["suggestion_type"] for link in links} <= {
        "field",
        "mapping",
        "validation",
        "transform",
        "rule",
        "cross_entity_rule",
    }
    serialized = json.dumps(first)
    assert "file_contract" not in serialized
    assert "xml_xsd" not in serialized
    assert "soap_wsdl" not in serialized
    assert "identity_role" not in serialized
    assert "portfolio_reuse" not in serialized

    file_fixed = next(
        link
        for link in links
        if link["metadata"].get("contract_type") == "file-fixed-width"
        and link["metadata"].get("layout_field") == "account_id"
    )
    assert file_fixed["suggestion_type"] == "field"
    assert file_fixed["metadata"]["file_format"] == "fixed-width"
    assert file_fixed["metadata"]["record_type"] == "data"
    assert file_fixed["metadata"]["field_position"] == 1
    assert file_fixed["metadata"]["field_length"] == 36
    assert file_fixed["metadata"]["direction"] == "inbound"
    assert file_fixed["metadata"]["source_artifact"] == "upstream/customer-fixed-layout.yaml"

    csv_in = next(
        link
        for link in links
        if link["metadata"].get("contract_type") == "file-csv"
        and link["metadata"].get("interface_direction") == "upstream"
    )
    assert csv_in["metadata"]["delimiter"] == "|"
    assert csv_in["metadata"]["csv_column_index"] == 1
    assert csv_in["metadata"]["direction"] == "inbound"

    csv_out = next(
        link
        for link in links
        if link["metadata"].get("contract_type") == "file-csv"
        and link["metadata"].get("interface_direction") == "downstream"
    )
    assert csv_out["metadata"]["delimiter"] == "~"
    assert csv_out["metadata"]["direction"] == "outbound"

    xml_validation = next(
        link
        for link in links
        if link["suggestion_type"] == "validation"
        and link["metadata"].get("contract_type") == "xml-xsd"
        and link["metadata"].get("interface_direction") == "upstream"
    )
    assert xml_validation["metadata"]["artifact_type"] == "xsd"
    assert xml_validation["metadata"]["xsd_path"] == "upstream/customer.xsd"
    assert xml_validation["metadata"]["xml_root"] == "Customer"
    assert xml_validation["metadata"]["namespace"] == "urn:customer"

    xml_mapping = next(
        link
        for link in links
        if link["suggestion_type"] == "mapping"
        and link["metadata"].get("contract_type") == "xml-xsd"
        and link["metadata"].get("interface_direction") == "downstream"
    )
    assert xml_mapping["metadata"]["source_path"] == "Customer.status"
    assert xml_mapping["metadata"]["target_path"] == "/Customer/status"
    assert xml_mapping["metadata"]["xpath"] == "/Customer/status"

    soap_operation = next(
        link
        for link in links
        if link["suggestion_type"] == "validation"
        and link["metadata"].get("contract_type") == "soap-wsdl"
        and link["metadata"].get("operation_name") == "getCustomer"
    )
    assert soap_operation["metadata"]["artifact_type"] == "wsdl"
    assert soap_operation["metadata"]["wsdl_service"] == "CustomerService"
    assert soap_operation["metadata"]["wsdl_port"] == "CustomerPort"
    assert soap_operation["metadata"]["wsdl_binding"] == "CustomerBinding"
    assert soap_operation["metadata"]["wsdl_operation"] == "getCustomer"
    assert soap_operation["metadata"]["namespace"] == "urn:customer-soap"
    assert soap_operation["metadata"]["mapping_artifact"] == "mappings/customer-soap-service-operation-mapping.yaml"

    soap_lookup = next(
        link
        for link in links
        if link["suggestion_type"] == "field"
        and link["metadata"].get("contract_type") == "soap-wsdl"
        and link["metadata"].get("interface_direction") == "downstream"
    )
    assert soap_lookup["metadata"]["mapping_scope"] == "lookup"
    assert soap_lookup["metadata"]["source_path"] == "id"
    assert soap_lookup["metadata"]["target_path"] == "Customer.customerId"

    soap_request = next(
        link
        for link in links
        if link["metadata"].get("contract_type") == "soap-wsdl"
        and link["metadata"].get("mapping_scope") == "request"
        and link["metadata"].get("target_path") == "/SyncCustomerRequest/status"
    )
    assert soap_request["metadata"]["source_path"] == "Customer.status"
    assert soap_request["metadata"]["soap_body_path"] == "/SyncCustomerRequest/status"

    soap_response = next(
        link
        for link in links
        if link["metadata"].get("contract_type") == "soap-wsdl"
        and link["metadata"].get("mapping_scope") == "response"
        and link["metadata"].get("source_path") == "/SyncCustomerResponse/resultCode"
    )
    assert soap_response["metadata"]["target_path"] == "resultCode"
    assert soap_response["metadata"]["soap_body_path"] == "/SyncCustomerResponse/resultCode"

    summary = first["provenance_summary"]
    assert summary["human_authored"] == len(links)
    assert summary["ai_accepted"] == 0
    assert summary["ai_edited"] == 0
    assert summary["no_evidence"] == 0
    assert summary["by_type"]["validation"] == 5
    assert summary["by_type"]["field"] == 6
    assert summary["by_type"]["mapping"] == 6


def test_file_contract_evidence_excludes_handoffs_and_identity_roles(monkeypatch, tmp_path):
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        downstream=[
            DownstreamInterface(
                name="eod-account-out",
                type="file-fixed-width",
                entity_name="Account",
                layout_fields=[LayoutField(name="account_id", start=1, length=12)],
                field_mappings=[FieldMapping(source="Account.accountId", target="account_id")],
            )
        ],
        handoffs=[
            DataHandoff(
                name="account-staging-table",
                type="staging-table",
                entity_name="Account",
                ddl_content="CREATE TABLE acct_staging (acct_id VARCHAR(36));",
                table_name="acct_staging",
                field_mappings=[FieldMapping(source="Account.accountId", target="acct_id")],
            )
        ],
    )
    session = get_session()
    session.identity_role_decisions = [
        IdentityRoleDecision(
            entity="Account",
            field="accountId",
            role="persistence_id",
            provenance="human-authored",
            reviewed_at="2026-06-01T00:00:00+00:00",
        )
    ]
    save_session(session)

    response = client.post("/export/write")
    assert response.status_code == 200
    sidecar = _read_sidecar(response.json())

    # Only the file contract produces evidence — not data handoffs or identity roles.
    paths = [link["manifest_path"] for link in sidecar["evidence_links"]]
    assert paths == ["downstream_interfaces.eod-account-out.layout.account_id"]
    assert "data_handoffs" not in json.dumps(paths)
    assert "identity_role" not in json.dumps(sidecar)


def test_file_contract_evidence_coexists_with_knowledge_assist_links(monkeypatch, tmp_path):
    _seed_file_contract_session(
        tmp_path,
        knowledge_assist=True,
        downstream=[
            DownstreamInterface(
                name="eod-account-out",
                type="file-fixed-width",
                entity_name="Account",
                layout_fields=[LayoutField(name="account_id", start=1, length=12)],
                field_mappings=[FieldMapping(source="Account.accountId", target="account_id")],
            )
        ],
    )
    session = get_session()
    session.ks_workspace_state.review_history = [
        KSReviewHistoryEntry(
            suggestion_id="s-ka-1",
            type="field",
            status="accepted",
            manifest_path="entities.Account.fields.accountId",
            reviewed_at="2026-06-01T00:00:00+00:00",
        )
    ]
    session.ks_workspace_state.evidence_links = [
        KSEvidenceLink(
            manifest_path="entities.Account.fields.accountId",
            suggestion_id="s-ka-1",
            provenance="ai-accepted",
        )
    ]
    save_session(session)

    class FakeClient:
        def get_suggestion_evidence_chain(self, project_id, scope, suggestion_id):
            assert scope == "fields"
            return {
                "suggestion": {"entity": "Account", "field_name": "accountId", "consistency_score": 0.9},
                "evidence_chunks": [
                    {
                        "citation": {
                            "document_id": "doc-1",
                            "document_name": "Account BRD.pdf",
                            "chunk_id": "chunk-1",
                            "content_hash": "sha256:abc",
                            "parser_version": "pdf-v1",
                            "snippet": "Account IDs must be unique.",
                        }
                    }
                ],
            }

    @contextmanager
    def fake_ks_client(**kwargs):
        yield FakeClient()

    monkeypatch.setattr("app.services.evidence_trail.ks_client", fake_ks_client)

    response = client.post("/export/write")
    assert response.status_code == 200
    sidecar = _read_sidecar(response.json())

    ka_links = _ka_links(sidecar)
    human_links = _human_authored_links(sidecar)
    assert [link["suggestion_id"] for link in ka_links] == ["s-ka-1"]
    assert len(human_links) == 1
    # KA links precede human-authored file-contract links in evidence_links.
    assert sidecar["evidence_links"][0]["provenance"] == "ai-accepted"
    assert sidecar["evidence_links"][-1]["provenance"] == "human-authored"
    summary = sidecar["provenance_summary"]
    assert summary["ai_accepted"] == 1
    assert summary["human_authored"] == 1
    assert summary["by_type"]["field"] == 2  # one KA field + one file field


def test_upstream_file_evidence_skipped_when_entity_name_blank(monkeypatch, tmp_path):
    # Upstream file mapping YAML is exported only when entity_name is present.
    # With a blank entity_name the manifest carries no `mapping:`, so the sidecar
    # must not claim mapping-derived (canonical target_path) field evidence.
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        upstream=[
            UpstreamInterface(
                name="account-csv-inbound",
                type="file-csv",
                entity_name="",
                spec_content=_CSV_INBOUND_SPEC,
                field_mappings=[FieldMapping(source="account_number", target="accountId")],
            )
        ],
    )

    response = client.post("/export/write")
    assert response.status_code == 200
    payload = response.json()
    sidecar = _read_sidecar(payload)

    manifest = yaml.safe_load(
        (Path(payload["output_dir"]) / "app-definition.yaml").read_text(encoding="utf-8")
    )
    upstream_entry = manifest["upstream_interfaces"][0]
    assert "mapping" not in upstream_entry  # no canonical mapping exported
    assert _human_authored_links(sidecar) == []
    assert sidecar["provenance_summary"]["human_authored"] == 0
    assert "accountId" not in json.dumps(sidecar["evidence_links"])


def test_downstream_file_evidence_emitted_even_when_entity_name_blank(monkeypatch, tmp_path):
    # Downstream file mappings export on field_mappings alone (no entity_name
    # gate), so the sidecar evidence remains aligned with the exported mapping.
    _fail_if_ks_called(monkeypatch)
    _seed_file_contract_session(
        tmp_path,
        downstream=[
            DownstreamInterface(
                name="ledger-csv-out",
                type="file-csv",
                entity_name="",
                spec_content=_CSV_OUTBOUND_SPEC,
                field_mappings=[FieldMapping(source="Account.accountId", target="account_number")],
            )
        ],
    )

    response = client.post("/export/write")
    assert response.status_code == 200
    payload = response.json()
    sidecar = _read_sidecar(payload)

    manifest = yaml.safe_load(
        (Path(payload["output_dir"]) / "app-definition.yaml").read_text(encoding="utf-8")
    )
    assert "mapping" in manifest["downstream_interfaces"][0]  # mapping IS exported
    links = _human_authored_links(sidecar)
    assert len(links) == 1
    assert links[0]["metadata"]["source_path"] == "Account.accountId"
    assert links[0]["metadata"]["target_path"] == "account_number"
