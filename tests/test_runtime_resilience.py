"""Tests for startup recovery and strict persistence behavior."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import Mock

import pytest
from src.api.services import task_flow_service as analysis_router
from src.blackboard import ExecutionData, GlobalStatus, execution_blackboard, global_blackboard
from src.common.utils import get_utc_now
from src.dag_engine.dag_exceptions import TaskLeaseLostError
from src.dag_engine.dag_graph import execute_task_flow
from src.storage.repository.memory_repo import MemoryRepo
from src.storage.repository.state_repo import StateRepo


def test_state_repo_raises_without_postgres_outside_test_backend(monkeypatch):
    monkeypatch.setattr("src.storage.repository.state_repo.StateRepo._allow_test_backend", staticmethod(lambda: False))
    monkeypatch.setattr("src.storage.repository.state_repo.pg_client.engine", None)
    with pytest.raises(RuntimeError):
        StateRepo.save_blackboard_state(
            "tenant-strict", "task-strict", "ws-strict", {"global": {"task_id": "task-strict"}}
        )
    assert StateRepo._memory_store.get("tenant-strict", {}).get("task-strict") is None


def test_state_repo_raises_on_write_failure(monkeypatch):
    class _BrokenConnection:
        def __enter__(self):
            raise RuntimeError("write failed")

        def __exit__(self, exc_type, exc, tb):
            return False

    class _BrokenEngine:
        def begin(self):
            return _BrokenConnection()

    monkeypatch.setattr("src.storage.repository.state_repo.pg_client.engine", _BrokenEngine())
    with pytest.raises(RuntimeError):
        StateRepo.save_blackboard_state(
            "tenant-strict", "task-strict", "ws-strict", {"global": {"task_id": "task-strict"}}
        )


def test_state_repo_claim_task_lease_raises_without_postgres_outside_test_backend(monkeypatch):
    monkeypatch.setattr("src.storage.repository.state_repo.StateRepo._allow_test_backend", staticmethod(lambda: False))
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


def test_state_repo_task_lease_owned_by_checks_owner_and_expiry():
    StateRepo._memory_task_leases["task-owned"] = {
        "tenant_id": "tenant-owned",
        "workspace_id": "ws-owned",
        "owner_id": "owner-a",
        "lease_expires_at": get_utc_now() + timedelta(minutes=1),
        "heartbeat_at": get_utc_now(),
    }

    assert StateRepo.task_lease_owned_by("task-owned", "owner-a") is True
    assert StateRepo.task_lease_owned_by("task-owned", "owner-b") is False


def test_state_repo_task_lease_status_returns_unknown_on_backend_error(monkeypatch):
    monkeypatch.setattr("src.storage.repository.state_repo.pg_client.engine", object())
    monkeypatch.setattr(
        "src.storage.repository.state_repo.StateRepo._ensure_task_lease_table",
        lambda: None,
    )

    class _BrokenConnection:
        def __enter__(self):
            raise RuntimeError("lease read failed")

        def __exit__(self, exc_type, exc, tb):
            return False

    class _BrokenEngine:
        def connect(self):
            return _BrokenConnection()

    monkeypatch.setattr("src.storage.repository.state_repo.pg_client.engine", _BrokenEngine())

    status = StateRepo.task_lease_status("task-owned", "owner-a")

    assert status["status"] == "unknown"
    assert "lease read failed" in status["error"]


def test_memory_repo_raises_without_postgres_outside_test_backend(monkeypatch):
    monkeypatch.setattr("src.storage.repository.memory_repo.MemoryRepo._allow_test_backend", staticmethod(lambda: False))
    monkeypatch.setattr("src.storage.repository.memory_repo.pg_client.engine", None)
    with pytest.raises(RuntimeError):
        MemoryRepo.list_approved_skills("tenant-strict", "ws-strict")


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

    monkeypatch.setattr("src.api.services.task_flow_service._run_task_flow", fake_run_task_flow)

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


def test_recover_unfinished_tasks_skips_waiting_and_terminal_states(monkeypatch):
    global_blackboard._task_states.clear()
    execution_blackboard._storage.clear()
    analysis_router._active_task_flow_tasks.clear()
    analysis_router._startup_recovery_state["scheduled_task_ids"] = []

    tenant_id = "tenant-recover-filter"
    pending_task = global_blackboard.create_task(tenant_id, "ws-recover-filter", "pending query")
    coding_task = global_blackboard.create_task(tenant_id, "ws-recover-filter", "coding query")
    waiting_task = global_blackboard.create_task(tenant_id, "ws-recover-filter", "waiting query")
    success_task = global_blackboard.create_task(tenant_id, "ws-recover-filter", "success query")
    failed_task = global_blackboard.create_task(tenant_id, "ws-recover-filter", "failed query")

    global_blackboard.update_global_status(coding_task, GlobalStatus.CODING)
    global_blackboard.update_global_status(waiting_task, GlobalStatus.WAITING_FOR_HUMAN)
    global_blackboard.update_global_status(success_task, GlobalStatus.SUCCESS)
    global_blackboard.update_global_status(failed_task, GlobalStatus.FAILED)

    scheduled: list[str] = []

    async def fake_run_task_flow(**kwargs):
        scheduled.append(str(kwargs["task_id"]))

    monkeypatch.setattr("src.api.services.task_flow_service._run_task_flow", fake_run_task_flow)

    async def scenario():
        recovered = await analysis_router.recover_unfinished_tasks()
        await asyncio.sleep(0)
        return recovered

    recovered = asyncio.run(scenario())

    assert set(recovered) == {pending_task, coding_task}
    assert set(scheduled) == {pending_task, coding_task}
    assert waiting_task not in recovered
    assert success_task not in recovered
    assert failed_task not in recovered


def test_recover_unfinished_tasks_reuses_task_envelope_settings(monkeypatch):
    global_blackboard._task_states.clear()
    execution_blackboard._storage.clear()
    analysis_router._active_task_flow_tasks.clear()

    tenant_id = "tenant-recover-envelope"
    task_id = global_blackboard.create_task(tenant_id, "ws-recover-envelope", "继续执行")
    global_blackboard.update_global_status(task_id, GlobalStatus.CODING)
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id="ws-recover-envelope",
            control={
                "task_envelope": {
                    "task_id": task_id,
                    "tenant_id": tenant_id,
                    "workspace_id": "ws-recover-envelope",
                    "input_query": "继续执行",
                    "governance_profile": "reviewer",
                    "allowed_tools": ["knowledge_query", "sandbox_exec"],
                    "redaction_rules": [],
                    "max_dynamic_steps": 6,
                    "metadata": {},
                }
            },
        ),
    )

    captured: dict[str, object] = {}

    def fake_schedule_task_flow(**kwargs):
        captured.update(kwargs)
        return {"scheduled": True, "reason": "scheduled"}

    monkeypatch.setattr("src.api.services.task_flow_service.schedule_task_flow", fake_schedule_task_flow)

    recovered = asyncio.run(analysis_router.recover_unfinished_tasks())

    assert recovered == [task_id]
    assert captured["task_id"] == task_id
    assert captured["governance_profile"] == "reviewer"
    assert captured["allowed_tools"] == ["knowledge_query", "sandbox_exec"]


def test_schedule_task_flow_skips_duplicate_task_ids(monkeypatch):
    analysis_router._startup_recovery_state["duplicate_schedule_skips"] = 0
    analysis_router._active_task_flow_tasks.clear()

    blocker = asyncio.Event()

    async def fake_run_task_flow(**kwargs):  # noqa: ARG001
        await blocker.wait()

    monkeypatch.setattr("src.api.services.task_flow_service._run_task_flow", fake_run_task_flow)

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


def test_schedule_task_flow_releases_active_marker_and_lease_after_completion(monkeypatch):
    analysis_router._active_task_flow_tasks.clear()

    async def fake_run_task_flow(**kwargs):  # noqa: ARG001
        return None

    monkeypatch.setattr("src.api.services.task_flow_service._run_task_flow", fake_run_task_flow)

    async def scenario():
        scheduled = analysis_router.schedule_task_flow(
            tenant_id="tenant-cleanup",
            task_id="task-cleanup",
            workspace_id="ws-cleanup",
            query="run once",
        )
        assert "task-cleanup" in analysis_router._active_task_flow_tasks
        assert StateRepo.get_task_lease("task-cleanup") is not None
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return scheduled

    scheduled = asyncio.run(scenario())

    assert scheduled["scheduled"] is True
    assert "task-cleanup" not in analysis_router._active_task_flow_tasks
    assert StateRepo.get_task_lease("task-cleanup") is None


def test_schedule_task_flow_allows_distinct_tasks_to_run_concurrently(monkeypatch):
    analysis_router._active_task_flow_tasks.clear()
    blocker = asyncio.Event()
    started: list[str] = []

    async def fake_run_task_flow(**kwargs):
        started.append(str(kwargs["task_id"]))
        await blocker.wait()

    monkeypatch.setattr("src.api.services.task_flow_service._run_task_flow", fake_run_task_flow)

    async def scenario():
        first = analysis_router.schedule_task_flow(
            tenant_id="tenant-parallel",
            task_id="task-parallel-a",
            workspace_id="ws-parallel",
            query="run a",
        )
        second = analysis_router.schedule_task_flow(
            tenant_id="tenant-parallel",
            task_id="task-parallel-b",
            workspace_id="ws-parallel",
            query="run b",
        )
        assert analysis_router._active_task_flow_tasks == {"task-parallel-a", "task-parallel-b"}
        blocker.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return first, second

    first, second = asyncio.run(scenario())

    assert first["scheduled"] is True
    assert second["scheduled"] is True
    assert set(started) == {"task-parallel-a", "task-parallel-b"}
    assert analysis_router._active_task_flow_tasks == set()
    assert StateRepo.get_task_lease("task-parallel-a") is None
    assert StateRepo.get_task_lease("task-parallel-b") is None


def test_schedule_task_flow_skips_when_lease_not_acquired(monkeypatch):
    analysis_router._startup_recovery_state["lease_conflicts"] = 0
    analysis_router._active_task_flow_tasks.clear()
    monkeypatch.setattr(
        "src.api.services.task_flow_service.StateRepo.claim_task_lease",
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


def test_run_task_flow_uses_dedicated_task_flow_executor():
    tenant_id = "tenant-task-flow-executor"
    task_id = global_blackboard.create_task(tenant_id, "ws-task-flow-executor", "继续执行")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id="ws-task-flow-executor",
        ),
    )

    captured: dict[str, object] = {}

    class FakeLoop:
        def run_in_executor(self, executor, func):
            captured["executor"] = executor
            captured["callable"] = func
            future = asyncio.Future()
            future.set_result({"terminal_status": "success", "terminal_sub_status": "ok"})
            return future

    async def scenario():
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("src.api.services.task_flow_service.asyncio.get_running_loop", lambda: FakeLoop())
            await analysis_router._run_task_flow(
                tenant_id=tenant_id,
                task_id=task_id,
                workspace_id="ws-task-flow-executor",
                query="继续执行",
            )

    asyncio.run(scenario())

    assert captured["executor"] is analysis_router._task_flow_executor


def test_get_startup_recovery_status_captures_task_lease_error(monkeypatch):
    monkeypatch.setattr(
        "src.api.services.task_flow_service.StateRepo.list_task_leases",
        lambda: (_ for _ in ()).throw(RuntimeError("lease unavailable")),
    )
    status = analysis_router.get_startup_recovery_status()
    assert status["task_leases"] == []
    assert "lease unavailable" in status["task_lease_error"]


def test_execute_task_flow_reuses_completed_node_checkpoints():
    tenant_id = "tenant-checkpoint"
    task_id = global_blackboard.create_task(tenant_id, "ws-checkpoint", "继续执行")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id="ws-checkpoint",
            control={
                "node_checkpoints": {
                    "router": {
                        "status": "completed",
                        "output_patch": {
                            "next_actions": ["analyst"],
                            "execution_intent": {"intent": "static_flow", "destinations": ["analyst"]},
                        },
                    },
                    "analyst": {
                        "status": "completed",
                        "output_patch": {"execution_strategy": {}, "next_actions": ["coder"]},
                    },
                }
            },
        ),
    )
    execution_blackboard.persist(tenant_id, task_id)

    router = Mock(side_effect=AssertionError("router should not rerun"))
    analyst = Mock(side_effect=AssertionError("analyst should not rerun"))

    result = execute_task_flow(
        {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "workspace_id": "ws-checkpoint",
            "input_query": "继续执行",
        },
        nodes={
            "router": router,
            "dynamic_swarm": lambda state: {},
            "skill_harvester": lambda state: {},
            "summarizer": lambda state: {"final_response": {"mode": "static"}},
            "data_inspector": lambda state: {},
            "kag_retriever": lambda state: {},
            "context_builder": lambda state: {},
            "analyst": analyst,
            "coder": lambda state: {"generated_code": "print('ok')", "next_actions": ["auditor"]},
            "auditor": lambda state: {"audit_result": {"safe": True}, "next_actions": ["skill_harvester"]},
            "debugger": lambda state: {},
            "executor": lambda state: {},
        },
    )

    assert result["terminal_status"] == "success"
    assert router.call_count == 0
    assert analyst.call_count == 0


def test_execute_task_flow_stops_when_task_lease_is_lost(monkeypatch):
    monkeypatch.setattr(
        "src.dag_engine.dag_graph.ensure_task_lease_owned",
        lambda task_id, owner_id: (_ for _ in ()).throw(TaskLeaseLostError("lost")),
    )
    router = Mock(side_effect=AssertionError("router should not run after lease loss"))

    result = execute_task_flow(
        {
            "tenant_id": "tenant-lease-lost",
            "task_id": "task-lease-lost",
            "workspace_id": "ws-lease-lost",
            "input_query": "继续执行",
            "lease_owner_id": "owner-a",
        },
        nodes={
            "router": router,
            "dynamic_swarm": lambda state: {},
            "skill_harvester": lambda state: {},
            "summarizer": lambda state: {"final_response": {"mode": "static"}},
            "data_inspector": lambda state: {},
            "kag_retriever": lambda state: {},
            "context_builder": lambda state: {},
            "analyst": lambda state: {},
            "coder": lambda state: {},
            "auditor": lambda state: {},
            "debugger": lambda state: {},
            "executor": lambda state: {},
        },
    )

    assert result["terminal_status"] == "failed"
    assert result["failure_type"] == "lease_lost"


def test_execute_task_flow_fails_when_task_lease_status_is_unknown(monkeypatch):
    monkeypatch.setattr(
        "src.common.task_lease_runtime.StateRepo.task_lease_status",
        lambda task_id, owner_id: {"status": "unknown", "error": "db unavailable"},
    )

    result = execute_task_flow(
        {
            "tenant_id": "tenant-lease-unknown",
            "task_id": "task-lease-unknown",
            "workspace_id": "ws-lease-unknown",
            "input_query": "继续执行",
            "lease_owner_id": "owner-a",
        },
        nodes={
            "router": lambda state: {"next_actions": ["dynamic_swarm"]},
            "dynamic_swarm": lambda state: {"dynamic_status": "completed", "dynamic_summary": "ok"},
            "skill_harvester": lambda state: {},
            "summarizer": lambda state: {"final_response": {"mode": "dynamic"}},
            "data_inspector": lambda state: {},
            "kag_retriever": lambda state: {},
            "context_builder": lambda state: {},
            "analyst": lambda state: {},
            "coder": lambda state: {},
            "auditor": lambda state: {},
            "debugger": lambda state: {},
            "executor": lambda state: {},
        },
    )

    assert result["terminal_status"] == "failed"
    assert result["failure_type"] == "lease_lost"
