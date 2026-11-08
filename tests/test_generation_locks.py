from __future__ import annotations

from app.services.generation_locks import acquire_generation_lock


def test_generation_lock_blocks_same_output_path(tmp_path):
    output_path = tmp_path / "generated-app"

    with acquire_generation_lock(output_path) as first_acquired:
        assert first_acquired is True
        with acquire_generation_lock(output_path) as second_acquired:
            assert second_acquired is False


def test_generation_lock_allows_distinct_output_paths(tmp_path):
    output_a = tmp_path / "session-a" / "generated-app"
    output_b = tmp_path / "session-b" / "generated-app"

    with acquire_generation_lock(output_a) as first_acquired:
        assert first_acquired is True
        with acquire_generation_lock(output_b) as second_acquired:
            assert second_acquired is True
