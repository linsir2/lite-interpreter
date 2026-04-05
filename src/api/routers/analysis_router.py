"""Minimal task creation and execution routes for lite-interpreter demos."""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict

from starlette.requests import Request
from starlette.responses import JSONResponse

from src.api.execution_resources import build_task_execution_summaries, serialize_execution_record
from src.blackboard import ExecutionData, GlobalStatus, TaskNotExistError, execution_blackboard, global_blackboard
from src.common.contracts import TaskEnvelope
from config.settings import TASK_LEASE_HEARTBEAT_SECONDS, TASK_LEASE_TTL_SECONDS, TASK_SCHEDULER_INSTANCE_ID
from src.harness.policy import load_harness_policy
from src.dag_engine.dag_graph import execute_task_flow
from src.dag_engine.nodes.analyst_node import analyst_node
from src.dag_engine.nodes.auditor_node import auditor_node
from src.dag_engine.nodes.coder_node import coder_node
from src.dag_engine.nodes.context_builder_node import context_builder_node
from src.dag_engine.nodes.data_inspector import data_inspector_node
from src.dag_engine.nodes.dynamic_swarm_node import dynamic_swarm_node
from src.dag_engine.nodes.debugger_node import debugger_node
from src.dag_engine.nodes.executor_node import executor_node
from src.dag_engine.nodes.kag_retriever import kag_retriever_node
from src.dag_engine.nodes.router_node import router_node
from src.dag_engine.nodes.skill_harvester_node import skill_harvester_node
from src.dag_engine.nodes.summarizer_node import summarizer_node
from src.storage.repository.skill_repo import SkillRepo
from src.storage.repository.state_repo import StateRepo
from src.privacy import mask_payload


_startup_recovery_state: dict[str, Any] = {
    "scheduled_task_ids": [],
    "last_error": None,
    "duplicate_schedule_skips": 0,
    "lease_conflicts": 0,
}
_active_task_flow_tasks: set[str] = set()
_active_task_flow_lock = threading.RLock()


def _record_historical_skill_outcomes(
    *,
    tenant_id: str,
    workspace_id: str,
    task_id: str,
    execution_data: ExecutionData | None,
    success: bool,
) -> None:
    if not execution_data:
        return
    used_skills = [
        match for match in (execution_data.historical_skill_matches or [])
        if bool(match.get("used_in_codegen"))
    ]
    for match in used_skills:
        skill_name = str(match.get("name", "")).strip()
        if not skill_name:
            continue
        SkillRepo.record_skill_outcome(
            tenant_id,
            workspace_id,
            skill_name,
            task_id=task_id,
            success=success,
        )


async def _run_task_flow(
    *,
    tenant_id: str,
    task_id: str,
    workspace_id: str,
    query: str,
    allowed_tools: list[str] | None = None,
    governance_profile: str = "researcher",
) -> None:
    policy = load_harness_policy()
    task_envelope = TaskEnvelope(
        task_id=task_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        input_query=query,
        governance_profile=governance_profile or "researcher",
        allowed_tools=list(allowed_tools or []),
        redaction_rules=list(policy.get("redaction_rules") or []),
    )
    state: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "task_id": task_id,
        "workspace_id": workspace_id,
        "input_query": query,
        "allowed_tools": allowed_tools or [],
        "governance_profile": governance_profile or "researcher",
        "redaction_rules": list(policy.get("redaction_rules") or []),
        "task_envelope": task_envelope.model_dump(mode="json"),
    }
    try:
        final_state = execute_task_flow(
            {
                **state,
                "execution_snapshot": execution_blackboard.read(tenant_id, task_id).model_dump(),
            },
            nodes={
                "router": router_node,
                "dynamic_swarm": dynamic_swarm_node,
                "skill_harvester": skill_harvester_node,
                "summarizer": summarizer_node,
                "data_inspector": data_inspector_node,
                "kag_retriever": kag_retriever_node,
                "context_builder": context_builder_node,
                "analyst": analyst_node,
                "coder": coder_node,
                "auditor": auditor_node,
                "debugger": debugger_node,
                "executor": executor_node,
            },
        )
        terminal_status = str(final_state.get("terminal_status") or "")
        if terminal_status == "success":
            _record_historical_skill_outcomes(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                task_id=task_id,
                execution_data=execution_blackboard.read(tenant_id, task_id),
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
                execution_data=execution_blackboard.read(tenant_id, task_id),
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
    """Schedule one task flow once per process and return a structured scheduling result."""
    lease = StateRepo.claim_task_lease(
        tenant_id=tenant_id,
        task_id=task_id,
        workspace_id=workspace_id,
        owner_id=TASK_SCHEDULER_INSTANCE_ID,
        lease_ttl_seconds=TASK_LEASE_TTL_SECONDS,
    )
    if not lease.get("acquired"):
        _startup_recovery_state["lease_conflicts"] = int(_startup_recovery_state.get("lease_conflicts", 0) or 0) + 1
        return {
            "scheduled": False,
            "reason": "lease_conflict",
            "lease": lease,
        }

    with _active_task_flow_lock:
        if task_id in _active_task_flow_tasks:
            _startup_recovery_state["duplicate_schedule_skips"] = int(_startup_recovery_state.get("duplicate_schedule_skips", 0) or 0) + 1
            StateRepo.release_task_lease(task_id=task_id, owner_id=TASK_SCHEDULER_INSTANCE_ID)
            return {
                "scheduled": False,
                "reason": "duplicate_local_task",
                "lease": lease,
            }
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
                _startup_recovery_state["last_error"] = f"failed to renew task lease for {task_id}"
                break

    task = asyncio.create_task(
        _run_task_flow(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id=workspace_id,
            query=query,
            allowed_tools=allowed_tools,
            governance_profile=governance_profile,
        )
    )
    heartbeat = asyncio.create_task(_lease_heartbeat())

    def _cleanup(_task: asyncio.Task) -> None:
        with _active_task_flow_lock:
            _active_task_flow_tasks.discard(task_id)
        heartbeat.cancel()
        StateRepo.release_task_lease(task_id=task_id, owner_id=TASK_SCHEDULER_INSTANCE_ID)

    task.add_done_callback(_cleanup)
    return {
        "scheduled": True,
        "reason": "scheduled",
        "lease": lease,
    }


async def recover_unfinished_tasks() -> list[str]:
    """Schedule unfinished tasks after service restart."""
    recovered_task_ids: list[str] = []
    _startup_recovery_state["last_error"] = None
    try:
        unfinished_tasks = global_blackboard.list_unfinished_tasks()
        for task in unfinished_tasks:
            execution_data = execution_blackboard.read(task.tenant_id, task.task_id)
            if execution_data is None:
                execution_blackboard.restore(task.tenant_id, task.task_id)
                execution_data = execution_blackboard.read(task.tenant_id, task.task_id)
            task_envelope = execution_data.task_envelope if execution_data else None
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


async def create_task(request: Request) -> JSONResponse:
    body = await request.json()
    policy = load_harness_policy()
    tenant_id = body.get("tenant_id", "demo-tenant")
    workspace_id = body.get("workspace_id", "demo-workspace")
    query = body["input_query"]
    autorun = bool(body.get("autorun", True))
    allowed_tools = body.get("allowed_tools") or []
    governance_profile = str(body.get("governance_profile") or "researcher")

    task_id = global_blackboard.create_task(tenant_id, workspace_id, query)
    execution_data = ExecutionData(
        task_id=task_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_envelope=TaskEnvelope(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            input_query=query,
            governance_profile=governance_profile,
            allowed_tools=list(allowed_tools),
            redaction_rules=list(policy.get("redaction_rules") or []),
        ),
    )
    execution_blackboard.write(tenant_id, task_id, execution_data)
    execution_blackboard.persist(tenant_id, task_id)

    if autorun:
        schedule_result = schedule_task_flow(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id=workspace_id,
            query=query,
            allowed_tools=allowed_tools,
            governance_profile=governance_profile,
        )
        if not schedule_result["scheduled"]:
            _startup_recovery_state["last_error"] = f"task {task_id} scheduling skipped: {schedule_result['reason']}"

    return JSONResponse(
        {
            "task_id": task_id,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "autorun": autorun,
            "autorun_scheduled": bool(schedule_result["scheduled"]) if autorun else False,
            "autorun_reason": str(schedule_result["reason"]) if autorun else "not_requested",
            "governance_profile": governance_profile,
        }
    )


async def get_task_result(request: Request) -> JSONResponse:
    task_id = request.path_params["task_id"]
    try:
        task = global_blackboard.get_task_state(task_id)
    except TaskNotExistError:
        return JSONResponse({"error": "task not found", "task_id": task_id}, status_code=404)

    execution_data = execution_blackboard.read(task.tenant_id, task_id)
    final_response = execution_data.final_response if execution_data else None
    execution_result = execution_data.execution_result if execution_data else None
    dynamic_summary = execution_data.dynamic_summary if execution_data else None
    task_lease = StateRepo.get_task_lease(task_id)

    payload = {
        "task_id": task_id,
        "tenant_id": task.tenant_id,
        "workspace_id": task.workspace_id,
        "global_status": task.global_status.value,
        "sub_status": task.sub_status,
        "failure_type": task.failure_type,
        "error_message": task.error_message,
        "final_response": final_response,
        "execution_result": execution_result,
        "dynamic_summary": dynamic_summary,
        "dynamic_runtime_metadata": execution_data.dynamic_runtime_metadata if execution_data else {},
        "knowledge_snapshot": execution_data.knowledge_snapshot if execution_data else {},
        "governance_profile": execution_data.governance_profile if execution_data else None,
        "governance_decisions": execution_data.governance_decisions if execution_data else [],
        "decision_log": execution_data.decision_log if execution_data else [],
        "approved_skills": execution_data.approved_skills if execution_data else [],
        "historical_skill_matches": execution_data.historical_skill_matches if execution_data else [],
        "task_envelope": execution_data.task_envelope.model_dump(mode="json") if execution_data and execution_data.task_envelope else None,
        "execution_intent": execution_data.execution_intent.model_dump(mode="json") if execution_data and execution_data.execution_intent else None,
        "execution_record": serialize_execution_record(execution_data.execution_record) if execution_data else None,
        "executions": build_task_execution_summaries(execution_data),
        "runtime_backend": execution_data.runtime_backend if execution_data else None,
        "task_lease": task_lease,
    }
    redacted_payload, _ = mask_payload(
        payload,
        list(execution_data.task_envelope.redaction_rules or []) if execution_data and execution_data.task_envelope else None,
    )
    return JSONResponse(redacted_payload)
