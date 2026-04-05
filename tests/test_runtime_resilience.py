"""Tests for startup recovery and strict persistence behavior."""
from __future__ import annotations

import asyncio

import pytest

from src.api.routers import analysis_router
from src.blackboard import ExecutionData, GlobalStatus, execution_blackboard, global_blackboard
from src.storage.repository.skill_repo import SkillRepo
from src.storage.repository.state_repo import StateRepo


def test_state_repo_strict_persistence_raises_without_postgres(monkeypatch):
    monkeypatch.setattr("src.storage.repository.state_repo.STRICT_PERSISTENCE", True)
    monkeypatch.setattr("src.storage.repository.state_repo.pg_client.engine", None)
    with pytest.raises(RuntimeError):
        StateRepo.save_blackboard_state("tenant-strict", "task-strict", "ws-strict", {"global": {"task_id": "task-strict"}})


def test_state_repo_strict_persistence_raises_for_task_lease_without_postgres(monkeypatch):
    monkeypatch.setattr("src.storage.repository.state_repo.STRICT_PERSISTENCE", True)
    monkeypatch.setattr("src.storage.repository.state_repo.pg_client.engine", None)
    with pytest.raises(RuntimeError):
        StateRepo.claim_task_lease(
            tenant_id="tenant-strict",
            task_id="task-strict",
            workspace_id="ws-strict",
            owner_id="owner-strict",
        )


def test_state_repo_memory_task_lease_prevents_foreign_duplicate_claim():
    first = StateRepo.claim_task_lease(
        tenant_id="tenant-lease",
        task_id="task-lease",
        workspace_id="ws-lease",
        owner_id="owner-a",
    )
    second = StateRepo.claim_task_lease(
        tenant_id="tenant-lease",
        task_id="task-lease",
        workspace_id="ws-lease",
        owner_id="owner-b",
    )
    assert first["acquired"] is True
    assert second["acquired"] is False
    assert second["owner_id"] == "owner-a"
    current = StateRepo.get_task_lease("task-lease")
    assert current is not None
    assert current["owner_id"] == "owner-a"


def test_skill_repo_strict_persistence_raises_without_postgres(monkeypatch):
    monkeypatch.setattr("src.storage.repository.skill_repo.STRICT_PERSISTENCE", True)
    monkeypatch.setattr("src.storage.repository.skill_repo.pg_client.engine", None)
    with pytest.raises(RuntimeError):
        SkillRepo.list_approved_skills("tenant-strict", "ws-strict")


def test_recover_unfinished_tasks_schedules_task_runs(monkeypatch):
    global_blackboard._task_states.clear()
    execution_blackboard._storage.clear()
    analysis_router._startup_recovery_state["duplicate_schedule_skips"] = 0
    analysis_router._active_task_flow_tasks.clear()
    tenant_id = "tenant-recover"
    task_id = global_blackboard.create_task(tenant_id, "ws-recover", "继续执行")
    global_blackboard.update_global_status(task_id, GlobalStatus.CODING)
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id="ws-recover",
        ),
    )
    analysis_router._startup_recovery_state["scheduled_task_ids"] = []
    analysis_router._startup_recovery_state["last_error"] = None

    scheduled: list[str] = []

    async def fake_run_task_flow(**kwargs):
        scheduled.append(str(kwargs["task_id"]))

    monkeypatch.setattr("src.api.routers.analysis_router._run_task_flow", fake_run_task_flow)

    async def scenario():
        recovered = await analysis_router.recover_unfinished_tasks()
        await asyncio.sleep(0)
        return recovered

    recovered = asyncio.run(scenario())
    status = analysis_router.get_startup_recovery_status()

    assert recovered == [task_id]
    assert scheduled == [task_id]
    assert status["scheduled_count"] == 1
    assert status["scheduled_task_ids"] == [task_id]


def test_schedule_task_flow_skips_duplicate_task_ids(monkeypatch):
    analysis_router._startup_recovery_state["duplicate_schedule_skips"] = 0
    analysis_router._active_task_flow_tasks.clear()

    blocker = asyncio.Event()

    async def fake_run_task_flow(**kwargs):  # noqa: ARG001
        await blocker.wait()

    monkeypatch.setattr("src.api.routers.analysis_router._run_task_flow", fake_run_task_flow)

    async def scenario():
        first = analysis_router.schedule_task_flow(
            tenant_id="tenant-dup",
            task_id="task-dup",
            workspace_id="ws-dup",
            query="run once",
        )
        second = analysis_router.schedule_task_flow(
            tenant_id="tenant-dup",
            task_id="task-dup",
            workspace_id="ws-dup",
            query="run twice",
        )
        blocker.set()
        await asyncio.sleep(0)
        return first, second

    first, second = asyncio.run(scenario())
    status = analysis_router.get_startup_recovery_status()

    assert first["scheduled"] is True
    assert second["scheduled"] is False
    assert second["reason"] == "duplicate_local_task"
    assert status["duplicate_schedule_skips"] >= 1


def test_schedule_task_flow_skips_when_lease_not_acquired(monkeypatch):
    analysis_router._startup_recovery_state["lease_conflicts"] = 0
    analysis_router._active_task_flow_tasks.clear()
    monkeypatch.setattr(
        "src.api.routers.analysis_router.StateRepo.claim_task_lease",
        lambda **kwargs: {"acquired": False, "owner_id": "other-owner"},  # noqa: ARG005
    )

    async def scenario():
        return analysis_router.schedule_task_flow(
            tenant_id="tenant-lease",
            task_id="task-lease-conflict",
            workspace_id="ws-lease",
            query="run never",
        )

    scheduled = asyncio.run(scenario())
    status = analysis_router.get_startup_recovery_status()

    assert scheduled["scheduled"] is False
    assert scheduled["reason"] == "lease_conflict"
    assert status["lease_conflicts"] >= 1


def test_get_startup_recovery_status_captures_task_lease_error(monkeypatch):
    monkeypatch.setattr("src.api.routers.analysis_router.StateRepo.list_task_leases", lambda: (_ for _ in ()).throw(RuntimeError("lease unavailable")))
    status = analysis_router.get_startup_recovery_status()
    assert status["task_leases"] == []
    assert "lease unavailable" in status["task_lease_error"]
