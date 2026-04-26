"""Internal services for task creation, scheduling, and recovery."""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

from config.settings import (
    TASK_FLOW_MAX_WORKERS,
    TASK_LEASE_HEARTBEAT_SECONDS,
    TASK_LEASE_TTL_SECONDS,
    TASK_SCHEDULER_INSTANCE_ID,
)

from src.api.execution_resources import read_task_execution_data
from src.blackboard import (
    ExecutionData,
    GlobalStatus,
    MemoryData,
    execution_blackboard,
    global_blackboard,
    memory_blackboard,
)
from src.common.control_plane import ensure_task_envelope
from src.common.task_lease_runtime import clear_task_lease_loss, mark_task_lease_lost
from src.dag_engine.dag_graph import execute_task_flow
from src.dag_engine.nodes.analyst_node import analyst_node
from src.dag_engine.nodes.auditor_node import auditor_node
from src.dag_engine.nodes.coder_node import coder_node
from src.dag_engine.nodes.context_builder_node import context_builder_node
from src.dag_engine.nodes.data_inspector import data_inspector_node
from src.dag_engine.nodes.debugger_node import debugger_node
from src.dag_engine.nodes.dynamic_swarm_node import dynamic_swarm_node
from src.dag_engine.nodes.executor_node import executor_node
from src.dag_engine.nodes.kag_retriever import kag_retriever_node
from src.dag_engine.nodes.router_node import router_node
from src.dag_engine.nodes.skill_harvester_node import skill_harvester_node
from src.dag_engine.nodes.static_evidence_node import static_evidence_node
from src.dag_engine.nodes.summarizer_node import summarizer_node
from src.harness.policy import load_harness_policy
from src.memory import MemoryService
from src.storage.repository.memory_repo import MemoryRepo
from src.storage.repository.state_repo import StateRepo

_startup_recovery_state: dict[str, Any] = {
    "scheduled_task_ids": [],
    "last_error": None,
    "duplicate_schedule_skips": 0,
    "lease_conflicts": 0,
}
_active_task_flow_tasks: set[str] = set()
_active_task_flow_lock = threading.RLock()
_task_flow_executor = ThreadPoolExecutor(
    max_workers=TASK_FLOW_MAX_WORKERS,
    thread_name_prefix="lite-interpreter-task-flow",
)


def build_task_request_fingerprint(
    *,
    tenant_id: str,
    workspace_id: str,
    query: str,
    governance_profile: str,
    allowed_tools: list[str],
    workspace_asset_refs: list[str],
    autorun: bool,
) -> str:
    payload = {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "input_query": query,
        "governance_profile": governance_profile,
        "allowed_tools": sorted(str(item).strip() for item in allowed_tools if str(item).strip()),
        "workspace_asset_refs": sorted(str(item).strip() for item in workspace_asset_refs if str(item).strip()),
        "autorun": bool(autorun),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _record_historical_skill_outcomes(
    *,
    tenant_id: str,
    workspace_id: str,
    task_id: str,
    memory_data: Any | None,
    success: bool,
) -> None:
    if not memory_data:
        return
    used_skills = [match for match in (memory_data.historical_matches or []) if bool(match.used_in_codegen)]
    for match in used_skills:
        skill_name = str(match.name or "").strip()
        if not skill_name:
            continue
        updated_skill = MemoryRepo.record_skill_outcome(
            tenant_id,
            workspace_id,
            skill_name,
            task_id=task_id,
            success=success,
        )
        if isinstance(memory_data, MemoryData):
            MemoryService._apply_repo_skill_update(memory_data, updated_skill)
    if isinstance(memory_data, MemoryData):
        MemoryService.persist_task_memory(memory_data)


async def _run_task_flow(
    *,
    tenant_id: str,
    task_id: str,
    workspace_id: str,
    query: str,
    allowed_tools: list[str] | None = None,
    governance_profile: str = "researcher",
    lease_owner_id: str | None = None,
) -> None:
    policy = load_harness_policy()
    task_envelope = ensure_task_envelope(
        task_id=task_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        input_query=query,
        governance_profile=governance_profile or "researcher",
        allowed_tools=list(allowed_tools or []),
        redaction_rules=list(policy.get("redaction_rules") or []),
        max_dynamic_steps=int((policy.get("dynamic", {}) or {}).get("max_steps", 6)),
    )
    execution_data = read_task_execution_data(tenant_id, task_id)
    if execution_data is None:
        execution_data = ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            control={"task_envelope": task_envelope.model_dump(mode="json")},
        )
        execution_blackboard.write(tenant_id, task_id, execution_data)
        execution_blackboard.persist(tenant_id, task_id)
    elif execution_data.control.task_envelope is None:
        execution_data.control.task_envelope = task_envelope
        execution_blackboard.write(tenant_id, task_id, execution_data)
        execution_blackboard.persist(tenant_id, task_id)

    state: dict[str, Any] = {
        "tenant_id": tenant_id,
        "task_id": task_id,
        "workspace_id": workspace_id,
        "input_query": query,
        "allowed_tools": list(task_envelope.allowed_tools),
        "governance_profile": task_envelope.governance_profile,
        "redaction_rules": list(task_envelope.redaction_rules),
        "max_dynamic_steps": task_envelope.max_dynamic_steps,
        "task_envelope": task_envelope.model_dump(mode="json"),
    }
    if lease_owner_id:
        state["lease_owner_id"] = lease_owner_id
    try:
        loop = asyncio.get_running_loop()
        final_state = await loop.run_in_executor(
            _task_flow_executor,
            partial(
                execute_task_flow,
                {**state, "execution_snapshot": execution_data.model_dump(mode="json")},
                nodes={
                    "router": router_node,
                    "dynamic_swarm": dynamic_swarm_node,
                    "skill_harvester": skill_harvester_node,
                    "summarizer": summarizer_node,
                    "data_inspector": data_inspector_node,
                    "kag_retriever": kag_retriever_node,
                    "context_builder": context_builder_node,
                    "analyst": analyst_node,
                    "static_evidence": static_evidence_node,
                    "coder": coder_node,
                    "auditor": auditor_node,
                    "debugger": debugger_node,
                    "executor": executor_node,
                },
            ),
        )
        terminal_status = str(final_state.get("terminal_status") or "")
        memory_data = memory_blackboard.read(tenant_id, task_id) or (
            memory_blackboard.restore(tenant_id, task_id) and memory_blackboard.read(tenant_id, task_id)
        )
        if terminal_status == "success":
            _record_historical_skill_outcomes(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                task_id=task_id,
                memory_data=memory_data,
                success=True,
            )
            global_blackboard.update_global_status(
                task_id=task_id,
                new_status=GlobalStatus.SUCCESS,
                sub_status=str(final_state.get("terminal_sub_status") or "任务执行完成"),
            )
        elif terminal_status == "waiting_for_human":
            global_blackboard.update_global_status(
                task_id=task_id,
                new_status=GlobalStatus.WAITING_FOR_HUMAN,
                sub_status=str(final_state.get("terminal_sub_status") or "任务等待人工介入"),
                failure_type=final_state.get("failure_type"),
                error_message=final_state.get("error_message"),
            )
        else:
            _record_historical_skill_outcomes(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                task_id=task_id,
                memory_data=memory_data,
                success=False,
            )
            global_blackboard.update_global_status(
                task_id=task_id,
                new_status=GlobalStatus.FAILED,
                sub_status=str(final_state.get("terminal_sub_status") or "任务执行失败"),
                failure_type=final_state.get("failure_type"),
                error_message=final_state.get("error_message"),
            )
    except Exception as exc:
        global_blackboard.update_global_status(
            task_id=task_id,
            new_status=GlobalStatus.FAILED,
            sub_status=f"任务执行失败: {exc}",
            failure_type="task_flow",
            error_message=str(exc),
        )


def schedule_task_flow(
    *,
    tenant_id: str,
    task_id: str,
    workspace_id: str,
    query: str,
    allowed_tools: list[str] | None = None,
    governance_profile: str = "researcher",
) -> dict[str, Any]:
    clear_task_lease_loss(task_id)
    lease = StateRepo.claim_task_lease(
        tenant_id=tenant_id,
        task_id=task_id,
        workspace_id=workspace_id,
        owner_id=TASK_SCHEDULER_INSTANCE_ID,
        lease_ttl_seconds=TASK_LEASE_TTL_SECONDS,
    )
    if not lease.get("acquired"):
        _startup_recovery_state["lease_conflicts"] = int(_startup_recovery_state.get("lease_conflicts", 0) or 0) + 1
        return {"scheduled": False, "reason": "lease_conflict", "lease": lease}

    with _active_task_flow_lock:
        if task_id in _active_task_flow_tasks:
            _startup_recovery_state["duplicate_schedule_skips"] = int(
                _startup_recovery_state.get("duplicate_schedule_skips", 0) or 0
            ) + 1
            StateRepo.release_task_lease(task_id=task_id, owner_id=TASK_SCHEDULER_INSTANCE_ID)
            return {"scheduled": False, "reason": "duplicate_local_task", "lease": lease}
        _active_task_flow_tasks.add(task_id)

    async def _lease_heartbeat() -> None:
        while True:
            await asyncio.sleep(TASK_LEASE_HEARTBEAT_SECONDS)
            with _active_task_flow_lock:
                if task_id not in _active_task_flow_tasks:
                    break
            renewed = StateRepo.renew_task_lease(
                task_id=task_id,
                owner_id=TASK_SCHEDULER_INSTANCE_ID,
                lease_ttl_seconds=TASK_LEASE_TTL_SECONDS,
            )
            if not renewed:
                reason = f"failed to renew task lease for {task_id}"
                _startup_recovery_state["last_error"] = reason
                mark_task_lease_lost(task_id, reason)
                break

    task = asyncio.create_task(
        _run_task_flow(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id=workspace_id,
            query=query,
            allowed_tools=allowed_tools,
            governance_profile=governance_profile,
            lease_owner_id=TASK_SCHEDULER_INSTANCE_ID,
        )
    )
    heartbeat = asyncio.create_task(_lease_heartbeat())

    def _cleanup(_task: asyncio.Task) -> None:
        with _active_task_flow_lock:
            _active_task_flow_tasks.discard(task_id)
        heartbeat.cancel()
        clear_task_lease_loss(task_id)
        StateRepo.release_task_lease(task_id=task_id, owner_id=TASK_SCHEDULER_INSTANCE_ID)

    task.add_done_callback(_cleanup)
    return {"scheduled": True, "reason": "scheduled", "lease": lease}


async def recover_unfinished_tasks() -> list[str]:
    recovered_task_ids: list[str] = []
    _startup_recovery_state["last_error"] = None
    try:
        unfinished_tasks = global_blackboard.list_unfinished_tasks()
        for task in unfinished_tasks:
            execution_data = read_task_execution_data(task.tenant_id, task.task_id)
            task_envelope = execution_data.control.task_envelope if execution_data else None
            schedule_result = schedule_task_flow(
                tenant_id=task.tenant_id,
                task_id=task.task_id,
                workspace_id=task.workspace_id,
                query=task.input_query,
                allowed_tools=list(task_envelope.allowed_tools) if task_envelope else [],
                governance_profile=str(task_envelope.governance_profile) if task_envelope else "researcher",
            )
            if schedule_result["scheduled"]:
                recovered_task_ids.append(task.task_id)
    except Exception as exc:
        _startup_recovery_state["last_error"] = str(exc)
        raise
    finally:
        _startup_recovery_state["scheduled_task_ids"] = list(recovered_task_ids)
    return recovered_task_ids


def get_startup_recovery_status() -> dict[str, Any]:
    with _active_task_flow_lock:
        active_task_ids = list(_active_task_flow_tasks)
    try:
        task_leases = StateRepo.list_task_leases()
        lease_error = None
    except Exception as exc:
        task_leases = []
        lease_error = str(exc)
    return {
        "scheduled_task_ids": list(_startup_recovery_state.get("scheduled_task_ids") or []),
        "scheduled_count": len(_startup_recovery_state.get("scheduled_task_ids") or []),
        "last_error": _startup_recovery_state.get("last_error"),
        "duplicate_schedule_skips": int(_startup_recovery_state.get("duplicate_schedule_skips", 0) or 0),
        "lease_conflicts": int(_startup_recovery_state.get("lease_conflicts", 0) or 0),
        "scheduler_instance_id": TASK_SCHEDULER_INSTANCE_ID,
        "active_task_flow_task_ids": active_task_ids,
        "task_leases": task_leases,
        "task_lease_error": lease_error,
    }


def create_execution_data_for_task(
    *,
    task_id: str,
    tenant_id: str,
    workspace_id: str,
    query: str,
    governance_profile: str,
    allowed_tools: list[str],
) -> ExecutionData:
    policy = load_harness_policy()
    return ExecutionData(
        task_id=task_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        control={
            "task_envelope": ensure_task_envelope(
                task_id=task_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                input_query=query,
                governance_profile=governance_profile,
                allowed_tools=list(allowed_tools),
                redaction_rules=list(policy.get("redaction_rules") or []),
                max_dynamic_steps=int((policy.get("dynamic", {}) or {}).get("max_steps", 6)),
            ).model_dump(mode="json")
        },
    )
