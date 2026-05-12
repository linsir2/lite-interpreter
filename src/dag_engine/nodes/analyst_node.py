"""Analyst node — sole writer of the frozen ExecutionStrategy.

Delegates plan compilation to src.compiler.plan_compiler (Instructor + LiteLLM).
No other node may overwrite strategy fields after this point.
"""

from __future__ import annotations

from typing import Any

from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.global_blackboard import global_blackboard
from src.blackboard.schema import GlobalStatus
from src.common import get_logger
from src.compiler.plan_compiler import compile_plan
from src.dag_engine.graphstate import DagGraphState
from src.memory import MemoryService
from src.runtime import build_analysis_brief

logger = get_logger(__name__)


def _resolve_analysis_brief_payload(state: DagGraphState, exec_data: Any) -> dict[str, Any] | None:
    payload = state.get("analysis_brief") if isinstance(state.get("analysis_brief"), dict) else None
    if payload is None and exec_data.knowledge.analysis_brief.question:
        return exec_data.knowledge.analysis_brief.model_dump(mode="json")
    return payload


def _next_actions_from_mode(network_mode, iteration_mode) -> list[str]:
    """Determine next DAG nodes from analyst's strategy dimensions."""
    from src.common.contracts import IterationMode, NetworkMode

    nm = NetworkMode(network_mode) if isinstance(network_mode, str) else network_mode
    im = IterationMode(iteration_mode) if isinstance(iteration_mode, str) else iteration_mode
    actions: list[str] = []
    if nm == NetworkMode.BOUNDED:
        actions.append("static_evidence")
    if im == IterationMode.MULTI_ROUND:
        actions.append("analyst")  # enables re-entry after executor
    if "static_evidence" not in actions:
        actions.append("coder")
    return actions


def analyst_node(state: DagGraphState) -> dict[str, Any]:
    tenant_id = state["tenant_id"]
    task_id = state["task_id"]
    query = state["input_query"]
    round_idx = int(state.get("round_index", 0))
    prev_round_output = state.get("round_output")

    global_blackboard.update_global_status(
        task_id=task_id,
        new_status=GlobalStatus.ANALYZING,
        sub_status="正在生成静态执行计划",
    )

    exec_data = execution_blackboard.read(tenant_id, task_id)
    if not exec_data:
        logger.warning(f"[Analyst] 缺少任务 {task_id} 的执行上下文")
        return {"execution_strategy": {}, "next_actions": ["coder"]}

    # Recall approved skills
    allowed_tools = list(exec_data.control.task_envelope.allowed_tools) if exec_data.control.task_envelope else []
    memory_data = MemoryService.recall_skills(
        tenant_id=exec_data.tenant_id,
        task_id=exec_data.task_id,
        workspace_id=exec_data.workspace_id,
        query=query,
        stage="analyst",
        available_capabilities=allowed_tools,
        match_reason_detail="analyst reused historical skills while drafting the analysis plan",
    ).memory_data

    if round_idx > 0 and prev_round_output:
        # Round 2+: reuse existing analysis_brief (data context unchanged),
        # let LLM re-evaluate strategy based on previous round findings.
        analysis_brief = _resolve_analysis_brief_payload(state, exec_data) or {}
        execution_strategy = compile_plan(
            query=query,
            analysis_brief=analysis_brief,
            knowledge_snapshot=exec_data.knowledge.knowledge_snapshot.model_dump(mode="json"),
            business_context=exec_data.knowledge.business_context.model_dump(mode="json"),
            approved_skills=list(memory_data.approved_skills or []),
            model_alias="reasoning_model",
            previous_round_summary=prev_round_output.get("key_findings", ""),
        )
    else:
        # Round 0/1: build analysis brief from scratch + compile plan
        analysis_brief = (
            _resolve_analysis_brief_payload(state, exec_data)
            or build_analysis_brief(
                query=query,
                exec_data=exec_data,
                knowledge_snapshot=exec_data.knowledge.knowledge_snapshot.model_dump(mode="json"),
                business_context=exec_data.knowledge.business_context.model_dump(mode="json"),
                analysis_mode="auto",
            ).to_payload()
        )
        execution_strategy = compile_plan(
            query=query,
            analysis_brief=analysis_brief,
            knowledge_snapshot=exec_data.knowledge.knowledge_snapshot.model_dump(mode="json"),
            business_context=exec_data.knowledge.business_context.model_dump(mode="json"),
            approved_skills=list(memory_data.approved_skills or []),
            model_alias="reasoning_model",
        )

    # Persist
    exec_data.knowledge.analysis_brief = analysis_brief
    exec_data.static.execution_strategy = execution_strategy
    execution_blackboard.write(tenant_id, task_id, exec_data)
    execution_blackboard.persist(tenant_id, task_id)

    next_actions = _next_actions_from_mode(execution_strategy.network_mode, execution_strategy.iteration_mode)
    return {
        "execution_strategy": execution_strategy.model_dump(mode="json"),
        "next_actions": next_actions,
    }
