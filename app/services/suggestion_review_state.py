"""Shared helpers for recording governed Knowledge Assist decisions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models.project import KSReviewHistoryEntry, ProjectSession


def set_review_bucket(session: ProjectSession, suggestion_id: str, status: str) -> None:
    review_state = session.ks_workspace_state.suggestion_review_state
    for values in (
        review_state.accepted_ids,
        review_state.edited_ids,
        review_state.rejected_ids,
    ):
        while suggestion_id in values:
            values.remove(suggestion_id)

    if status == "accepted":
        review_state.accepted_ids.append(suggestion_id)
    elif status == "edited":
        review_state.edited_ids.append(suggestion_id)
    elif status == "rejected":
        review_state.rejected_ids.append(suggestion_id)


def record_review_history_without_evidence(
    session: ProjectSession,
    *,
    suggestion_id: str,
    suggestion_type: str,
    status: str,
    manifest_path: str,
    edited_payload: Any = None,
    review_context: dict[str, Any] | None = None,
) -> None:
    """Record a governed decision while keeping evidence sidecars dormant.

    Some suggestion scopes, such as mappings in KS-B3 PR 2, are reviewed and
    applied before Evidence Trail export support exists. Remove any stale link
    for the suggestion so Step 8 does not try to expand unsupported evidence.
    """

    set_review_bucket(session, suggestion_id, status)
    session.ks_workspace_state.evidence_links = [
        link
        for link in session.ks_workspace_state.evidence_links
        if link.suggestion_id != suggestion_id
    ]
    session.ks_workspace_state.review_history.append(
        KSReviewHistoryEntry(
            suggestion_id=suggestion_id,
            type=suggestion_type,
            status=status,
            manifest_path=manifest_path,
            reviewed_at=datetime.now(timezone.utc).isoformat(),
            edited_payload=edited_payload if status == "edited" else None,
            review_context=review_context or {},
        )
    )
