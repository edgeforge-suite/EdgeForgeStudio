"""Process-local locks for regeneration apply package mutations."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

_LOCKS_GUARD = Lock()
_APPLY_LOCKS: dict[str, Lock] = {}


def regen_apply_lock_key(package_path: str | Path) -> str:
    """Return the stable key used to serialize apply for one managed package."""

    return str(Path(package_path).expanduser().resolve(strict=False))


@contextmanager
def acquire_regen_apply_lock(package_path: str | Path) -> Iterator[bool]:
    """Try to acquire the apply lock for ``package_path`` without blocking."""

    key = regen_apply_lock_key(package_path)
    with _LOCKS_GUARD:
        lock = _APPLY_LOCKS.setdefault(key, Lock())

    acquired = lock.acquire(blocking=False)
    try:
        yield acquired
    finally:
        if acquired:
            lock.release()
