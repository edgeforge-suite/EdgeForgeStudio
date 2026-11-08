"""Project-level user-intent capability flags."""

from __future__ import annotations

from pydantic import BaseModel


class ProjectCapabilities(BaseModel):
    """Durable user intent for assistive Studio capabilities.

    Runtime state such as ``ks_active`` is intentionally separate from these
    flags so legacy process state cannot masquerade as user opt-in.
    """

    knowledge_assist_enabled: bool = False

    @property
    def any_assist_active(self) -> bool:
        return self.knowledge_assist_enabled
