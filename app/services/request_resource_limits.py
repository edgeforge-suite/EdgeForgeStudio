"""Bounded in-memory shared-mode request resource controls."""

from __future__ import annotations

import asyncio
import math
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from starlette.requests import Request

from app.services.settings import (
    RequestResourceLimits,
    ResourceLimitClassSettings,
    get_studio_settings,
)


class RequestCostClass(StrEnum):
    """The fixed cost classes approved for shared-mode request controls."""

    A = "A"
    B = "B"
    C = "C"
    C2 = "C2"
    D = "D"


ROUTE_LIMIT_CLASSES: Mapping[tuple[str, str], RequestCostClass] = MappingProxyType({
    ("POST", "/export/write"): RequestCostClass.A,
    ("POST", "/export/validate"): RequestCostClass.A,
    ("POST", "/export/assess"): RequestCostClass.A,
    ("POST", "/export/generate"): RequestCostClass.A,
    ("POST", "/export/build"): RequestCostClass.A,
    ("POST", "/export/run"): RequestCostClass.A,
    ("POST", "/regen/apply"): RequestCostClass.A,
    ("GET", "/regen/preview"): RequestCostClass.A,
    ("POST", "/api/validate/staging-ddl/generate"): RequestCostClass.A,
    ("POST", "/upstream/ingest-url"): RequestCostClass.B,
    ("POST", "/entities/ks/review"): RequestCostClass.C,
    ("POST", "/entities/ks/identity-role-review"): RequestCostClass.C,
    ("POST", "/entities/ks/validation-review"): RequestCostClass.C,
    ("POST", "/rules/ks/review"): RequestCostClass.C,
    ("POST", "/review/ks/review"): RequestCostClass.C,
    ("POST", "/kafka/ks/review"): RequestCostClass.C,
    ("POST", "/kafka/ks/transform-review"): RequestCostClass.C,
    ("POST", "/passthrough/ks/review"): RequestCostClass.C,
    ("POST", "/knowledge/upload"): RequestCostClass.C,
    ("POST", "/knowledge/delete"): RequestCostClass.C,
    ("GET", "/entities/ks/suggestions"): RequestCostClass.C2,
    ("GET", "/entities/ks/drawer"): RequestCostClass.C2,
    ("GET", "/entities/ks/full-review"): RequestCostClass.C2,
    ("GET", "/entities/ks/evidence"): RequestCostClass.C2,
    ("GET", "/rules/ks/drawer"): RequestCostClass.C2,
    ("GET", "/review/ks/drawer"): RequestCostClass.C2,
    ("GET", "/kafka/ks/drawer"): RequestCostClass.C2,
    ("GET", "/passthrough/ks/drawer"): RequestCostClass.C2,
    ("POST", "/upstream/ingest-file"): RequestCostClass.D,
    ("POST", "/upstream/edge-contract/inspect"): RequestCostClass.D,
    ("POST", "/upstream/edge-contract/file-inspect"): RequestCostClass.D,
    ("POST", "/downstream/edge-contract/inspect"): RequestCostClass.D,
    ("POST", "/downstream/edge-contract/file-inspect"): RequestCostClass.D,
    ("POST", "/project/open"): RequestCostClass.D,
    ("POST", "/api/validate/staging-ddl"): RequestCostClass.D,
    ("GET", "/upstream/classify-debug"): RequestCostClass.D,
    ("GET", "/export/download-zip"): RequestCostClass.D,
})

# These remain deliberately absent from ROUTE_LIMIT_CLASSES. Keeping the set visible
# documents the safety and navigation exclusions without applying prefix inference.
EXPLICITLY_UNTHROTTLED_ROUTES = frozenset(
    {
        ("GET", "/export/run-status"),
        ("POST", "/export/stop"),
        ("POST", "/export/reset"),
        ("GET", "/export/artifact/{artifact_name}"),
        ("GET", "/knowledge"),
    }
)

HTML_RATE_LIMITED_PATHS: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "/knowledge/upload": ("/knowledge", "Knowledge Workspace"),
        "/knowledge/delete": ("/knowledge", "Knowledge Workspace"),
        "/regen/apply": ("/export", "Export"),
        "/regen/preview": ("/export", "Export"),
        "/project/open": ("/", "Project Setup"),
    }
)

MAX_PRINCIPAL_CLASS_ENTRIES = 10_000
CONCURRENCY_RETRY_AFTER_SECONDS = 5


def request_cost_class(method: str, path: str) -> RequestCostClass | None:
    """Return a class only for an explicitly approved method/path pair."""

    return ROUTE_LIMIT_CLASSES.get((method.upper(), path))


@dataclass
class _PrincipalClassEntry:
    timestamps: deque[float] = field(default_factory=deque)
    active_permits: int = 0
    last_used_at: float = 0.0


@dataclass(frozen=True)
class ResourceLimitPermit:
    """A successfully acquired principal and process permit pair."""

    cost_class: RequestCostClass
    principal_id: str


@dataclass(frozen=True)
class ResourceLimitRejection:
    """A safe immediate rejection without queueing or an acquisition timeout."""

    retry_after_seconds: int


@dataclass(frozen=True)
class ResourceLimitPrincipalUnavailable:
    """Shared-mode request state did not yield a safe principal key."""


def _principal_id_from_request(request: Request) -> str | None:
    principal = getattr(request.state, "principal", None)
    user_id = getattr(principal, "user_id", None)
    if isinstance(user_id, str) and user_id:
        return user_id
    anonymous_session_id = getattr(request.state, "studio_anonymous_session_id", None)
    if isinstance(anonymous_session_id, str) and anonymous_session_id:
        return f"anonymous:{anonymous_session_id}"
    return None


class RequestResourceLimiter:
    """A single-process bounded limiter with atomic non-waiting acquisition."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_entries: int = MAX_PRINCIPAL_CLASS_ENTRIES,
    ) -> None:
        self._clock = clock
        self._max_entries = max_entries
        self._entries: OrderedDict[tuple[RequestCostClass, str], _PrincipalClassEntry] = (
            OrderedDict()
        )
        self._process_active = {cost_class: 0 for cost_class in RequestCostClass}
        # This lock covers rate history plus both counters, making the two-stage
        # principal/process acquisition atomic without a semaphore wait queue.
        self._lock = asyncio.Lock()

    async def try_acquire(
        self,
        *,
        cost_class: RequestCostClass,
        principal_id: str,
        limits: RequestResourceLimits,
    ) -> ResourceLimitPermit | ResourceLimitRejection:
        """Atomically consume rate budget and acquire both concurrency permits."""

        class_limits = limits.for_class(cost_class.value)
        now = self._clock()
        key = (cost_class, principal_id)
        async with self._lock:
            entry = self._entry_for(key, now=now, limits=limits)
            if entry is None:
                return ResourceLimitRejection(CONCURRENCY_RETRY_AFTER_SECONDS)

            self._prune_rate_window(entry, now=now, class_limits=class_limits)
            entry.last_used_at = now
            self._entries.move_to_end(key)

            rate_rejection = self._consume_rate_budget(
                entry,
                now=now,
                class_limits=class_limits,
            )
            if rate_rejection is not None:
                return rate_rejection

            # Principal acquisition occurs first. A zero cap disables enforcement
            # but still increments active_permits so live entries cannot be evicted.
            if (
                class_limits.principal_concurrency > 0
                and entry.active_permits >= class_limits.principal_concurrency
            ):
                return ResourceLimitRejection(CONCURRENCY_RETRY_AFTER_SECONDS)
            entry.active_permits += 1

            # If process acquisition fails, immediately roll back the principal
            # counter while retaining the already-consumed rate budget.
            process_active = self._process_active[cost_class]
            if (
                class_limits.process_concurrency > 0
                and process_active >= class_limits.process_concurrency
            ):
                entry.active_permits -= 1
                return ResourceLimitRejection(CONCURRENCY_RETRY_AFTER_SECONDS)
            self._process_active[cost_class] = process_active + 1
            return ResourceLimitPermit(cost_class=cost_class, principal_id=principal_id)

    async def release(self, permit: ResourceLimitPermit) -> None:
        """Release both counters after completion, error, or task cancellation."""

        key = (permit.cost_class, permit.principal_id)
        async with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                entry.active_permits = max(0, entry.active_permits - 1)
                entry.last_used_at = self._clock()
                self._entries.move_to_end(key)
            self._process_active[permit.cost_class] = max(
                0,
                self._process_active[permit.cost_class] - 1,
            )

    async def state_for_testing(self) -> dict[str, object]:
        """Expose only synthetic counts for focused limiter tests."""

        async with self._lock:
            return {
                "entry_count": len(self._entries),
                "active_permits": {
                    cost_class.value: self._process_active[cost_class]
                    for cost_class in RequestCostClass
                },
                "keys": tuple((cost.value, principal) for cost, principal in self._entries),
            }

    def _entry_for(
        self,
        key: tuple[RequestCostClass, str],
        *,
        now: float,
        limits: RequestResourceLimits,
    ) -> _PrincipalClassEntry | None:
        existing = self._entries.get(key)
        if existing is not None:
            return existing

        self._evict_idle_entries(now=now, limits=limits)
        if len(self._entries) >= self._max_entries and not self._evict_lru_inactive_entry():
            return None

        entry = _PrincipalClassEntry(last_used_at=now)
        self._entries[key] = entry
        return entry

    def _evict_idle_entries(self, *, now: float, limits: RequestResourceLimits) -> None:
        stale_keys: list[tuple[RequestCostClass, str]] = []
        for key, entry in self._entries.items():
            if entry.active_permits:
                continue
            window_seconds = limits.for_class(key[0].value).rate_window_seconds
            if window_seconds == 0 or now - entry.last_used_at > 2 * window_seconds:
                stale_keys.append(key)
        for key in stale_keys:
            self._entries.pop(key, None)

    def _evict_lru_inactive_entry(self) -> bool:
        for key, entry in self._entries.items():
            if entry.active_permits == 0:
                del self._entries[key]
                return True
        return False

    @staticmethod
    def _prune_rate_window(
        entry: _PrincipalClassEntry,
        *,
        now: float,
        class_limits: ResourceLimitClassSettings,
    ) -> None:
        if class_limits.rate_max == 0 or class_limits.rate_window_seconds == 0:
            entry.timestamps.clear()
            return
        cutoff = now - class_limits.rate_window_seconds
        while entry.timestamps and entry.timestamps[0] <= cutoff:
            entry.timestamps.popleft()

    @staticmethod
    def _consume_rate_budget(
        entry: _PrincipalClassEntry,
        *,
        now: float,
        class_limits: ResourceLimitClassSettings,
    ) -> ResourceLimitRejection | None:
        if class_limits.rate_max == 0 or class_limits.rate_window_seconds == 0:
            return None
        if len(entry.timestamps) >= class_limits.rate_max:
            retry_after = entry.timestamps[0] + class_limits.rate_window_seconds - now
            return ResourceLimitRejection(max(1, math.ceil(retry_after)))
        entry.timestamps.append(now)
        return None


_resource_limiter = RequestResourceLimiter()


def get_request_resource_limiter() -> RequestResourceLimiter:
    """Return Studio's process-local shared-mode limiter."""

    return _resource_limiter


async def try_acquire_request_resource(
    request: Request,
    *,
    cost_class: RequestCostClass,
) -> ResourceLimitPermit | ResourceLimitRejection | ResourceLimitPrincipalUnavailable | None:
    """Acquire one shared-mode resource permit for request-scoped work.

    ``None`` is the intentionally constant-time local-mode bypass. Keeping this
    handoff here lets a route protect a narrow expensive operation (such as a
    single remote fetch) without expanding a whole otherwise-unthrottled route.
    """

    if not getattr(request.state, "studio_shared_mode", False):
        return None
    principal_id = _principal_id_from_request(request)
    if principal_id is None:
        return ResourceLimitPrincipalUnavailable()
    return await get_request_resource_limiter().try_acquire(
        cost_class=cost_class,
        principal_id=principal_id,
        limits=get_studio_settings().request_resource_limits,
    )


def reset_request_resource_limiter_for_testing() -> None:
    """Reset process-local state so tests never inherit another request history."""

    global _resource_limiter
    _resource_limiter = RequestResourceLimiter()
