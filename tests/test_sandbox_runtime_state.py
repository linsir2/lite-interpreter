"""Tests for sandbox runtime state helpers."""
from __future__ import annotations

from src.sandbox import docker_executor
from src.sandbox.runtime_state import _tenant_concurrency, register_running_container, reset_runtime_state


def test_start_zombie_cleaner_daemon_is_idempotent(monkeypatch):
    started = {"count": 0}

    class _FakeThread:
        def __init__(self, *args, **kwargs):
            return None

        def start(self):
            started["count"] += 1

    flags = iter([True, False])
    monkeypatch.setattr("src.sandbox.docker_executor.should_start_zombie_cleaner", lambda: next(flags))
    monkeypatch.setattr("src.sandbox.docker_executor.threading.Thread", _FakeThread)

    docker_executor.start_zombie_cleaner_daemon()
    docker_executor.start_zombie_cleaner_daemon()

    assert started["count"] == 1


def test_reset_runtime_state_clears_in_memory_runtime_markers():
    _tenant_concurrency["tenant-reset"] = 2
    register_running_container("trace-reset", "container-reset")

    reset_runtime_state()

    assert "tenant-reset" not in _tenant_concurrency
    assert "trace-reset" not in docker_executor._running_containers
