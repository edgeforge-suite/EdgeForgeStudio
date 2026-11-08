"""Studio-managed KS subprocess lifecycle.

The low-level KS integration keeps its strict start/stop context-manager contract.
This wrapper is the Studio lifecycle layer: it reuses ready clients per
workspace, enforces a process-wide concurrency cap, and reaps idle clients.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Optional, Protocol

from app.integrations.ks_integration import KSClient, KSUnavailableError
from app.services.settings import get_studio_settings


class _LifecycleClient(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def is_ready(self) -> bool: ...


_ClientFactory = Callable[[list[str], Optional[str]], _LifecycleClient]


@dataclass
class _ClientEntry:
    client: _LifecycleClient
    in_use: bool
    last_used_at: float


_LOCK = RLock()
_CLIENTS: dict[tuple[tuple[str, ...], str], _ClientEntry] = {}
_CLIENT_FACTORY: _ClientFactory = KSClient


def _client_key(allowed_roots: list[str], db_path: str | None) -> tuple[tuple[str, ...], str]:
    return (tuple(allowed_roots), db_path or "")


def set_ks_client_factory_for_testing(factory: _ClientFactory) -> None:
    """Install a test client factory without spawning a real KS subprocess."""
    global _CLIENT_FACTORY
    with _LOCK:
        _CLIENT_FACTORY = factory


def reset_ks_lifecycle_for_testing() -> None:
    """Stop all managed clients and reset the lifecycle registry."""
    global _CLIENT_FACTORY
    with _LOCK:
        entries = list(_CLIENTS.values())
        _CLIENTS.clear()
        _CLIENT_FACTORY = KSClient
    for entry in entries:
        _stop_client(entry.client)


def active_ks_client_count() -> int:
    with _LOCK:
        return len(_CLIENTS)


def reap_idle_ks_clients(*, now: float | None = None) -> int:
    """Stop clients idle longer than the configured TTL."""
    settings = get_studio_settings()
    current = time.monotonic() if now is None else now
    idle_cutoff = current - settings.ks_idle_ttl_seconds
    to_stop: list[_LifecycleClient] = []
    with _LOCK:
        for key, entry in list(_CLIENTS.items()):
            if entry.in_use or entry.last_used_at > idle_cutoff:
                continue
            to_stop.append(entry.client)
            del _CLIENTS[key]

    for client in to_stop:
        _stop_client(client)
    return len(to_stop)


def stop_ks_clients_for_workspace(workspace_root: str) -> int:
    """Stop managed clients whose roots/db path live under a workspace."""
    root = Path(workspace_root).expanduser().resolve(strict=False)
    to_stop: list[_LifecycleClient] = []
    with _LOCK:
        for key, entry in list(_CLIENTS.items()):
            allowed_roots, db_path = key
            if _key_is_under_workspace(root, allowed_roots, db_path):
                to_stop.append(entry.client)
                del _CLIENTS[key]

    for client in to_stop:
        _stop_client(client)
    return len(to_stop)


@contextmanager
def ks_client(allowed_roots: list[str], db_path: str | None = None) -> Iterator[_LifecycleClient]:
    """Yield a Studio-managed KS client.

    The client remains alive after the context exits and is later stopped by the
    idle reaper. Concurrent use of the same workspace client is rejected instead
    of multiplexing stdio requests through one subprocess.
    """
    key = _client_key(allowed_roots, db_path)
    client: _LifecycleClient | None = None
    entry: _ClientEntry | None = None
    created = False

    reap_idle_ks_clients()
    with _LOCK:
        entry = _CLIENTS.get(key)
        if entry is not None:
            if entry.in_use:
                raise KSUnavailableError("KS workspace is already in use.")
            if entry.client.is_ready():
                entry.in_use = True
                client = entry.client
            else:
                del _CLIENTS[key]
                _stop_client(entry.client)
                entry = None

        if client is None:
            settings = get_studio_settings()
            if len(_CLIENTS) >= settings.max_ks_subprocesses:
                raise KSUnavailableError("KS subprocess concurrency limit reached.")
            client = _CLIENT_FACTORY(list(allowed_roots), db_path)
            entry = _ClientEntry(client=client, in_use=True, last_used_at=time.monotonic())
            _CLIENTS[key] = entry
            created = True

    if created:
        try:
            client.start()
        except Exception:
            with _LOCK:
                current_entry = _CLIENTS.get(key)
                if current_entry is entry:
                    del _CLIENTS[key]
            _stop_client(client)
            raise

    try:
        yield client
    finally:
        stop_after_release = False
        with _LOCK:
            current_entry = _CLIENTS.get(key)
            if current_entry is entry:
                if client.is_ready():
                    current_entry.in_use = False
                    current_entry.last_used_at = time.monotonic()
                else:
                    del _CLIENTS[key]
                    stop_after_release = True
        if stop_after_release:
            _stop_client(client)


def _stop_client(client: _LifecycleClient) -> None:
    try:
        client.stop()
    except Exception:
        # Best effort cleanup; callers already handle KS availability failures.
        pass


def _key_is_under_workspace(
    workspace_root: Path,
    allowed_roots: tuple[str, ...],
    db_path: str,
) -> bool:
    for raw_root in allowed_roots:
        if _path_is_under(workspace_root, Path(raw_root)):
            return True
    return bool(db_path and _path_is_under(workspace_root, Path(db_path)))


def _path_is_under(workspace_root: Path, candidate: Path) -> bool:
    resolved = candidate.expanduser().resolve(strict=False)
    if resolved == workspace_root:
        return True
    try:
        resolved.relative_to(workspace_root)
    except ValueError:
        return False
    return True
