"""Minimal task creation and execution routes for lite-interpreter demos."""

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
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.api.audit_logging import record_api_audit
from src.api.auth import require_request_role
from src.api.execution_resources import (
    build_task_execution_summaries,
    read_task_execution_data,
    serialize_execution_record,
    to_jsonable_payload,
)
from src.api.request_scope import ensure_claimed_scope, ensure_resource_scope
from src.api.routers.upload_router import attach_workspace_assets_to_execution
from src.api.schemas import CreateTaskRequest, validation_error_payload
from src.blackboard import (
    ExecutionData,
    GlobalStatus,
    MemoryData,
    TaskNotExistError,
    execution_blackboard,
    global_blackboard,
    memory_blackboard,
)
from src.common.control_plane import ensure_task_envelope, task_redaction_rules
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
from src.dag_engine.nodes.summarizer_node import summarizer_node
from src.harness.policy import load_harness_policy
from src.memory import MemoryService
from src.privacy import mask_payload
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
# 单独给任务流一个专用线程池：
# - 任务流里跑的是整条同步 DAG，里面包含 DuckDB / pandas / 同步 HTTP / 沙箱执行等重路径
# - 如果继续占用 asyncio 默认线程池，会和系统里其他 `asyncio.to_thread(...)` 回退任务
#   互相抢 worker，导致“事件循环没堵，但默认线程池被占满”的软阻塞
_task_flow_executor = ThreadPoolExecutor(
    max_workers=TASK_FLOW_MAX_WORKERS,
    thread_name_prefix="lite-interpreter-task-flow",
)


def _build_task_request_fingerprint(
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
        # 这里不能直接“裸跑” DAG。
        # 调度链路需要一个稳定的 execution 主状态作为控制面快照来源，
        # 否则冷恢复/幂等复用时会在真正进入流程前因 None.model_dump() 崩掉。
        execution_data = ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            control={"task_envelope": task_envelope.model_dump(mode="json")},
        )
        execution_blackboard.write(tenant_id, task_id, execution_data)
        execution_blackboard.persist(tenant_id, task_id)
    elif execution_data.control.task_envelope is None:
        # 兼容历史任务或异常状态：execution 存在，但缺少控制面信封时补齐。
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
                {
                    **state,
                    "execution_snapshot": execution_data.model_dump(mode="json"),
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
            ),
        )
        terminal_status = str(final_state.get("terminal_status") or "")
        if terminal_status == "success":
            # 记录本次任务中使用的skills的成功结果，更新skillrepo中的统计
            _record_historical_skill_outcomes(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                task_id=task_id,
                memory_data=(
                    memory_blackboard.read(tenant_id, task_id)
                    or (memory_blackboard.restore(tenant_id, task_id) and memory_blackboard.read(tenant_id, task_id))
                ),
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
            # 记录skills使用的失败结果，更新统计数据
            _record_historical_skill_outcomes(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                task_id=task_id,
                memory_data=(
                    memory_blackboard.read(tenant_id, task_id)
                    or (memory_blackboard.restore(tenant_id, task_id) and memory_blackboard.read(tenant_id, task_id))
                ),
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
    """
    核心调度函数：为每个任务在单进程内调度一次任务流，实现分布式锁控制、并发安全、任务生命周期管理

    【分布式调度核心逻辑】：基于租约（Lease）的抢占式调度，保证同一任务在分布式集群中只会被一个实例执行

    params:

    - tenant_id：租户ID
    - task_id：任务ID
    - workspace_id：工作空间ID
    - query：用户输入查询
    - allowed_tools：允许使用的工具列表
    - governance_profile：治理配置文件

    返回值：调度结果字典，包含是否调度成功、失败原因、租约信息
    """
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
        # 返回调度失败结果，原因为租约冲突
        return {
            "scheduled": False,
            "reason": "lease_conflict",
            "lease": lease,
        }

    with _active_task_flow_lock:
        if task_id in _active_task_flow_tasks:
            _startup_recovery_state["duplicate_schedule_skips"] = (
                int(_startup_recovery_state.get("duplicate_schedule_skips", 0) or 0) + 1
            )
            StateRepo.release_task_lease(task_id=task_id, owner_id=TASK_SCHEDULER_INSTANCE_ID)
            return {
                "scheduled": False,
                "reason": "duplicate_local_task",
                "lease": lease,
            }
        _active_task_flow_tasks.add(task_id)

    async def _lease_heartbeat() -> None:
        """
        内部异步函数：租约心跳保活协程
        核心作用：定期续期任务租约，保证任务执行期间，租约不会过期，避免被其他实例抢占
        """
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
    # 创建异步任务，启动租约心跳保活协程，与任务执行协程并行运行
    heartbeat = asyncio.create_task(_lease_heartbeat())

    def _cleanup(_task: asyncio.Task) -> None:
        with _active_task_flow_lock:
            _active_task_flow_tasks.discard(task_id)
        heartbeat.cancel()
        clear_task_lease_loss(task_id)
        StateRepo.release_task_lease(task_id=task_id, owner_id=TASK_SCHEDULER_INSTANCE_ID)

    task.add_done_callback(_cleanup)
    return {
        "scheduled": True,
        "reason": "scheduled",
        "lease": lease,
    }


async def recover_unfinished_tasks() -> list[str]:
    """
    服务启动时的故障恢复函数：调度服务重启前未完成的任务，实现断点续跑
    核心作用：避免服务重启导致正在执行的任务丢失，保证任务的最终执行
    返回值：成功恢复调度的任务ID列表
    """
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
    """
    状态查询函数：获取当前调度器实例的启动恢复状态、运行时统计信息
    核心作用：用于监控、运维、问题排查，查看调度器的运行状态、任务统计、租约信息
    返回值：调度器状态字典，包含所有统计与配置信息
    """
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


# 接收前端发来的 request，并写入execution_data -> execution_blackboard中，开始走流程
async def create_task(request: Request) -> JSONResponse:
    role_error = require_request_role(request, "operator")
    if role_error is not None:
        return role_error
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "invalid json body"}, status_code=400)
    try:
        command = CreateTaskRequest.model_validate(body)
    except ValidationError as exc:
        return JSONResponse(validation_error_payload(exc), status_code=422)

    policy = load_harness_policy()
    tenant_id = command.tenant_id
    workspace_id = command.workspace_id
    scope_error = ensure_claimed_scope(
        request,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    if scope_error is not None:
        record_api_audit(
            request,
            action="task.create",
            outcome="denied",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            resource_type="task",
            metadata={"reason": "scope_forbidden"},
        )
        return scope_error
    query = command.input_query
    autorun = command.autorun
    allowed_tools = list(command.allowed_tools)
    governance_profile = command.governance_profile
    idempotency_key = command.idempotency_key
    request_fingerprint = _build_task_request_fingerprint(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        query=query,
        governance_profile=governance_profile,
        allowed_tools=list(allowed_tools),
        workspace_asset_refs=list(command.workspace_asset_refs),
        autorun=autorun,
    )

    if idempotency_key:
        existing = global_blackboard.find_task_by_idempotency(tenant_id, workspace_id, idempotency_key)
        if existing:
            if str(existing.request_fingerprint or "") and existing.request_fingerprint != request_fingerprint:
                return JSONResponse(
                    {
                        "error": "idempotency key conflict",
                        "task_id": existing.task_id,
                        "idempotency_key": idempotency_key,
                    },
                    status_code=409,
                )
            existing_execution = execution_blackboard.read(tenant_id, existing.task_id)
            if existing_execution is None:
                existing_execution = read_task_execution_data(tenant_id, existing.task_id)
            schedule_result = {"scheduled": False, "reason": "already_exists"}
            if autorun and existing.global_status == GlobalStatus.PENDING:
                envelope = existing_execution.control.task_envelope if existing_execution else None
                schedule_result = schedule_task_flow(
                    tenant_id=tenant_id,
                    task_id=existing.task_id,
                    workspace_id=workspace_id,
                    query=existing.input_query,
                    allowed_tools=list(envelope.allowed_tools) if envelope else list(allowed_tools),
                    governance_profile=str(envelope.governance_profile) if envelope else governance_profile,
                )
            return JSONResponse(
                {
                    "task_id": existing.task_id,
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "autorun": autorun,
                    "autorun_scheduled": bool(schedule_result["scheduled"]) if autorun else False,
                    "autorun_reason": str(schedule_result["reason"]) if autorun else "not_requested",
                    "governance_profile": governance_profile,
                    "idempotency_key": idempotency_key,
                    "idempotency_hit": True,
                }
            )

    task_id = global_blackboard.create_task(
        tenant_id,
        workspace_id,
        query,
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
    )
    execution_data = ExecutionData(
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
    if command.workspace_asset_refs:
        execution_data = attach_workspace_assets_to_execution(
            execution_data=execution_data,
            asset_refs=list(command.workspace_asset_refs),
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

    response_payload = {
        "task_id": task_id,
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "autorun": autorun,
        "autorun_scheduled": bool(schedule_result["scheduled"]) if autorun else False,
        "autorun_reason": str(schedule_result["reason"]) if autorun else "not_requested",
        "governance_profile": governance_profile,
        "idempotency_key": idempotency_key,
        "idempotency_hit": False,
    }
    record_api_audit(
        request,
        action="task.create",
        outcome="success",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        resource_type="task",
        resource_id=task_id,
        metadata={
            "autorun": autorun,
            "governance_profile": governance_profile,
            "idempotency_hit": False,
        },
    )
    return JSONResponse(response_payload)


async def get_task_result(request: Request) -> JSONResponse:
    role_error = require_request_role(request, "viewer")
    if role_error is not None:
        return role_error
    task_id = request.path_params["task_id"]
    try:
        task = global_blackboard.get_task_state(task_id)
    except TaskNotExistError:
        return JSONResponse({"error": "task not found", "task_id": task_id}, status_code=404)
    scope_error = ensure_resource_scope(
        request,
        tenant_id=task.tenant_id,
        workspace_id=task.workspace_id,
    )
    if scope_error is not None:
        record_api_audit(
            request,
            action="task.result.read",
            outcome="denied",
            tenant_id=task.tenant_id,
            workspace_id=task.workspace_id,
            task_id=task_id,
            resource_type="task_result",
            resource_id=task_id,
            metadata={"reason": "scope_mismatch"},
        )
        return scope_error

    execution_data = read_task_execution_data(task.tenant_id, task_id)
    memory_data = memory_blackboard.read(task.tenant_id, task_id)
    if memory_data is None and memory_blackboard.restore(task.tenant_id, task_id):
        memory_data = memory_blackboard.read(task.tenant_id, task_id)
    final_response = execution_data.control.final_response if execution_data else None
    dynamic_summary = execution_data.dynamic.summary if execution_data else None
    task_lease = StateRepo.get_task_lease(task_id)

    payload = to_jsonable_payload(
        {
            "task": {
                "task_id": task_id,
                "tenant_id": task.tenant_id,
                "workspace_id": task.workspace_id,
            },
            "status": {
                "global_status": task.global_status.value,
                "sub_status": task.sub_status,
                "failure_type": task.failure_type,
                "error_message": task.error_message,
                "task_lease": task_lease,
            },
            "response": final_response,
            "static": {
                "analysis_plan": execution_data.static.analysis_plan if execution_data else None,
                "generated_code_present": bool(execution_data.static.generated_code) if execution_data else False,
                "audit_result": execution_data.static.audit_result if execution_data else None,
                "execution_record": serialize_execution_record(execution_data.static.execution_record)
                if execution_data
                else None,
            },
            "dynamic": {
                "runtime_backend": execution_data.dynamic.runtime_backend if execution_data else None,
                "status": execution_data.dynamic.status if execution_data else None,
                "summary": dynamic_summary,
                "runtime_metadata": execution_data.dynamic.runtime_metadata if execution_data else {},
                "trace_refs": execution_data.dynamic.trace_refs if execution_data else [],
                "artifacts": execution_data.dynamic.artifacts if execution_data else [],
                "recommended_skill": execution_data.dynamic.recommended_static_skill if execution_data else None,
            },
            "knowledge": {
                "business_context": execution_data.knowledge.business_context if execution_data else {},
                "knowledge_snapshot": execution_data.knowledge.knowledge_snapshot if execution_data else {},
                "analysis_brief": execution_data.knowledge.analysis_brief if execution_data else {},
            },
            "skills": {
                "approved": memory_data.approved_skills if memory_data else [],
                "historical_matches": memory_data.historical_matches if memory_data else [],
                "harvested_candidates": memory_data.harvested_candidates if memory_data else [],
            },
            "control": {
                "task_envelope": execution_data.control.task_envelope.model_dump(mode="json")
                if execution_data and execution_data.control.task_envelope
                else None,
                "execution_intent": execution_data.control.execution_intent.model_dump(mode="json")
                if execution_data and execution_data.control.execution_intent
                else None,
                "decision_log": execution_data.control.decision_log if execution_data else [],
            },
            "executions": build_task_execution_summaries(execution_data),
        }
    )
    redacted_payload, _ = mask_payload(
        payload,
        task_redaction_rules(execution_data.control.task_envelope) if execution_data else None,
    )
    record_api_audit(
        request,
        action="task.result.read",
        outcome="success",
        tenant_id=task.tenant_id,
        workspace_id=task.workspace_id,
        task_id=task_id,
        resource_type="task_result",
        resource_id=task_id,
        metadata={"global_status": task.global_status.value},
    )
    return JSONResponse(redacted_payload)
