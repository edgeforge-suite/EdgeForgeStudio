"""Process-local locks for Engine generation output directories."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

_LOCKS_GUARD = Lock()
_OUTPUT_LOCKS: dict[str, Lock] = {}


def generation_lock_key(output_path: str | Path) -> str:
    """Return the stable key used to serialize generation for an output path."""

    return str(Path(output_path).expanduser().resolve())


@contextmanager
def acquire_generation_lock(output_path: str | Path) -> Iterator[bool]:
    """Try to acquire the generation lock for ``output_path`` without blocking."""

    key = generation_lock_key(output_path)
    with _LOCKS_GUARD:
        lock = _OUTPUT_LOCKS.setdefault(key, Lock())

    acquired = lock.acquire(blocking=False)
    try:
        yield acquired
    finally:
        if acquired:
            lock.release()
