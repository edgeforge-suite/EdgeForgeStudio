"""Lightweight Step 1 Knowledge Workspace summary helpers."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.project import ProjectSession
from app.services.ks_workspace import current_workspace_identity


@dataclass
class WorkspaceSummary:
    namespace: str | None
    linkage_label: str
    linkage_detail: str
    ks_status: str
    ks_status_label: str
    ks_status_detail: str
    document_count: int | None
    document_summary: str
    warning: str | None = None


def build_workspace_summary(session: ProjectSession) -> WorkspaceSummary:
    workspace_id = current_workspace_identity(session)
    if not workspace_id:
        return WorkspaceSummary(
            namespace=None,
            linkage_label="Created on first workspace use",
            linkage_detail="Durable workspace linkage is minted once and then preserved across local save/open.",
            ks_status="idle",
            ks_status_label="Ready on open",
            ks_status_detail="Step 1 stays lightweight. Open the detailed workspace to establish live workspace status.",
            document_count=None,
            document_summary="Open the detailed workspace to begin document ingest.",
            warning=None,
        )

    return WorkspaceSummary(
        namespace=workspace_id,
        linkage_label=workspace_id,
        linkage_detail="Durable workspace linkage is preserved across local save/open.",
        ks_status="linked",
        ks_status_label="Linked",
        ks_status_detail="Open the detailed workspace to verify current workspace availability and refresh live document summary.",
        document_count=None,
        document_summary="Live document count is refreshed from the detailed workspace when needed.",
        warning=None,
    )
