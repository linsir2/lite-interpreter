"""
Router 意图路由节点

作用：
1. 优先识别需要动态探索的高复杂度任务
2. 否则走既有静态链路（数据探查 / 知识检索 / Analyst）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.blackboard.global_blackboard import global_blackboard
from src.blackboard.schema import GlobalStatus
from src.blackboard.task_state_services import ExecutionStateService
from src.common.contracts import ExecutionIntent
from src.common.logger import get_logger
from src.dag_engine.graphstate import DagGraphState
from src.memory import MemoryService
from src.runtime import resolve_runtime_decision

logger = get_logger(__name__)


@dataclass(frozen=True)
class PreparedRouting:
    """Resolved routing branch plus the explanation to persist."""

    routing_mode: str
    destinations: list[str]
    routing_reasons: list[str]
    dynamic_reason: str | None = None


def _has_business_context(exec_data: Any) -> bool:
    context = getattr(getattr(exec_data, "knowledge", None), "business_context", None)
    if context is None:
        return False
    return any(bool(getattr(context, key, [])) for key in ("rules", "metrics", "filters", "sources"))


def _recall_router_candidate_skills(state: DagGraphState, exec_data: Any) -> list[dict[str, Any]]:
    recall_result = MemoryService.recall_skills(
        tenant_id=exec_data.tenant_id,
        task_id=exec_data.task_id,
        workspace_id=getattr(exec_data, "workspace_id", state.get("workspace_id", "default_ws")),
        query=state["input_query"],
        stage="router",
        available_capabilities=list(state.get("allowed_tools") or []),
        match_reason_detail="router ranked historical skills against the incoming query",
    )
    return [item.model_dump(mode="json") for item in recall_result.memory_data.approved_skills]


def _prepare_routing(
    *,
    runtime_decision: Any,
) -> PreparedRouting:
    destinations = list(runtime_decision.destinations or [])
    routing_reasons = list(runtime_decision.routing_reasons or [])
    if runtime_decision.final_mode == "dynamic":
        dynamic_reason = runtime_decision.decision_reason or "任务需要外部研究能力"
        return PreparedRouting(
            routing_mode="dynamic",
            destinations=destinations or ["dynamic_swarm"],
            routing_reasons=routing_reasons or [f"触发动态超级节点: {dynamic_reason}"],
            dynamic_reason=dynamic_reason,
        )
    return PreparedRouting(
        routing_mode="static",
        destinations=destinations or ["analyst"],
        routing_reasons=routing_reasons or [runtime_decision.decision_reason],
    )


def _build_execution_intent(
    *,
    runtime_decision: Any,
    prepared: PreparedRouting,
    candidate_skills: list[dict[str, Any]],
) -> ExecutionIntent:
    next_static_steps = list(
        dict.fromkeys(
            str(item).strip()
            for item in list(getattr(runtime_decision, "next_static_steps", ()) or [])
            if str(item).strip()
        )
    )
    return ExecutionIntent(
        intent=(
            "dynamic_then_static_flow"
            if runtime_decision.final_mode == "dynamic" and bool(next_static_steps)
            else "dynamic_only"
            if runtime_decision.final_mode == "dynamic"
            else "static_flow"
        ),
        destinations=prepared.destinations,
        reason=" | ".join(
            [runtime_decision.decision_reason, *prepared.routing_reasons]
            if runtime_decision.decision_reason
            else prepared.routing_reasons
        ),
        complexity_score=runtime_decision.complexity_score,
        candidate_skills=candidate_skills,
        metadata={
            **({"dynamic_reason": prepared.dynamic_reason} if prepared.dynamic_reason else {}),
            **({"next_static_steps": next_static_steps} if next_static_steps else {}),
            **runtime_decision.to_metadata(),
        },
    )


def router_node(state: DagGraphState) -> dict[str, Any]:
    """
    根据 blackboard 决定：
    - dynamic_swarm
    - data_inspector
    - kag_retriever
    - analyst
    """
    tenant_id = state["tenant_id"]
    task_id = state["task_id"]
    query = state["input_query"]

    logger.info(f"[Router] 开始评估任务: {task_id}")

    global_blackboard.update_global_status(
        task_id=task_id,
        new_status=GlobalStatus.ROUTING,
        sub_status="正在评估任务需求与数据状态",
    )

    exec_data = ExecutionStateService.load(tenant_id, task_id)
    if not exec_data:
        raise ValueError(f"严重错误：找不到任务 {task_id} 的 ExecutionData")
    candidate_skills = _recall_router_candidate_skills(state, exec_data)
    runtime_decision = resolve_runtime_decision(
        call_purpose="routing_assess",
        query=query,
        state=state,
        exec_data=exec_data,
        allowed_tools=list(state.get("allowed_tools") or []),
    )

    prepared = _prepare_routing(
        runtime_decision=runtime_decision,
    )
    execution_intent = _build_execution_intent(
        runtime_decision=runtime_decision,
        prepared=prepared,
        candidate_skills=candidate_skills,
    )
    ExecutionStateService.update_control(
        tenant_id=tenant_id,
        task_id=task_id,
        execution_intent=execution_intent,
    )

    return {
        "next_actions": prepared.destinations,
        "execution_intent": execution_intent.model_dump(mode="json"),
    }


def route_condition(state: DagGraphState) -> list[str]:
    """
    交通警察（Conditional Edge Callable）：
    供 LangGraph 图组装时使用，动态读取 Router 节点决定的下一步走向。
    """
    return state["next_actions"]
