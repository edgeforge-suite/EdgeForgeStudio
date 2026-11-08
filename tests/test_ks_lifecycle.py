from __future__ import annotations

import time

import pytest

from app.integrations.ks_integration import KSUnavailableError
from app.services.ks_lifecycle import (
    active_ks_client_count,
    ks_client,
    reap_idle_ks_clients,
    reset_ks_lifecycle_for_testing,
    set_ks_client_factory_for_testing,
)


class FakeKSClient:
    instances: list[FakeKSClient] = []

    def __init__(self, allowed_roots: list[str], db_path: str | None = None) -> None:
        self.allowed_roots = allowed_roots
        self.db_path = db_path
        self.started = False
        self.stopped = False
        FakeKSClient.instances.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True
        self.started = False

    def is_ready(self) -> bool:
        return self.started and not self.stopped


@pytest.fixture(autouse=True)
def fake_ks_lifecycle():
    reset_ks_lifecycle_for_testing()
    FakeKSClient.instances.clear()
    set_ks_client_factory_for_testing(FakeKSClient)
    yield
    reset_ks_lifecycle_for_testing()
    FakeKSClient.instances.clear()


def test_ks_lifecycle_reuses_ready_client_for_same_workspace():
    with ks_client(["/tmp/session-a/ks"], db_path="/tmp/session-a/ks/knowledge.sqlite3") as first:
        assert first.started is True

    with ks_client(["/tmp/session-a/ks"], db_path="/tmp/session-a/ks/knowledge.sqlite3") as second:
        assert second is first

    assert len(FakeKSClient.instances) == 1
    assert active_ks_client_count() == 1
    assert first.stopped is False


def test_ks_lifecycle_reaps_idle_clients(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_KS_IDLE_TTL_SECONDS", "5")

    with ks_client(["/tmp/session-a/ks"], db_path="/tmp/session-a/ks/knowledge.sqlite3") as client:
        assert client.started is True

    reaped = reap_idle_ks_clients(now=time.monotonic() + 6)

    assert reaped == 1
    assert client.stopped is True
    assert active_ks_client_count() == 0


def test_ks_lifecycle_concurrency_cap_rejects_new_client(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_MAX_KS_SUBPROCESSES", "1")

    with ks_client(["/tmp/session-a/ks"], db_path="/tmp/session-a/ks/knowledge.sqlite3"):
        with pytest.raises(KSUnavailableError, match="concurrency limit"):
            with ks_client(["/tmp/session-b/ks"], db_path="/tmp/session-b/ks/knowledge.sqlite3"):
                pass

    assert len(FakeKSClient.instances) == 1


def test_idle_reap_without_ka_spawn_is_noop():
    assert reap_idle_ks_clients(now=10_000.0) == 0
    assert FakeKSClient.instances == []
