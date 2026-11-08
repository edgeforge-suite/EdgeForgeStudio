"""Deprecated global session-store module.

P2-2b moved Studio session state behind the request-scoped SessionStore seam in
``app.services.session_context``. This module intentionally exposes no global
mutable session accessors.
"""

from __future__ import annotations


def __getattr__(name: str):
    if name in {"get_session", "save_session", "reset_session"}:
        raise RuntimeError(
            "Global Studio session access has been removed; use "
            "app.services.session_context with a request-scoped SessionStore."
        )
    raise AttributeError(name)
