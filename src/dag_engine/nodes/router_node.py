"""
Router 意图路由节点

作用：
1. 优先识别需要动态探索的高复杂度任务
2. 否则走既有静态链路（数据探查 / 知识检索 / Analyst）
"""
from __future__ import annotations

from typing import Any

from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.global_blackboard import global_blackboard
from src.blackboard.schema import GlobalStatus
from src.common.contracts import ExecutionIntent
from src.common.logger import get_logger
from src.dag_engine.graphstate import DagGraphState
from src.memory import MemoryService
from src.runtime import resolve_runtime_decision

logger = get_logger(__name__)

_DYNAMIC_PATTERNS = [
    "自己找数据",
    "自己收集",
    "自己验证",
    "多步",
    "探索",
    "对比方案",
    "联网",
    "外部资料",
    "财报",
    "research",
    "benchmark",
]
_COORDINATION_HINTS = ["结合", "并", "同时", "然后", "再", "并且"]
_BUSINESS_KEYWORDS = ["定义", "规则", "口径", "标准", "合规", "说明"]


def _has_business_context(exec_data: Any) -> bool:
    context = getattr(getattr(exec_data, "knowledge", None), "business_context", None)
    if context is None:
        return False
    return any(bool(getattr(context, key, [])) for key in ("rules", "metrics", "filters", "sources"))


def _score_dynamic_complexity(query: str, exec_data: Any) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    if len(query) >= 40:
        score += 0.15
        reasons.append("用户目标描述较长，疑似包含多阶段目标")

    matched_patterns = [pattern for pattern in _DYNAMIC_PATTERNS if pattern in query]
    if matched_patterns:
        score += min(0.5, 0.18 * len(matched_patterns))
        reasons.append(f"命中复杂探索关键词: {', '.join(matched_patterns[:3])}")

    matched_coordination_hints = [hint for hint in _COORDINATION_HINTS if hint in query]
    if len(matched_coordination_hints) >= 2:
        score += 0.2
        reasons.append("用户请求同时包含多个协作/串联动作")

    if exec_data.inputs.structured_datasets and exec_data.inputs.business_documents:
        score += 0.15
        reasons.append("同一任务同时涉及结构化与非结构化上下文")

    if "写代码" in query and ("找数据" in query or "验证" in query):
        score += 0.2
        reasons.append("需要外部信息收集与代码验证闭环")

    if ("预测" in query or "走势" in query or "宏观" in query) and ("财报" in query or "数据" in query):
        score += 0.15
        reasons.append("包含趋势/预测任务，且依赖外部事实支撑")

    return min(score, 1.0), reasons


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

    exec_data = execution_blackboard.read(tenant_id, task_id)
    if not exec_data:
        raise ValueError(f"严重错误：找不到任务 {task_id} 的 ExecutionData")
    recall_result = MemoryService.recall_skills(
        tenant_id=tenant_id,
        task_id=task_id,
        workspace_id=getattr(exec_data, "workspace_id", state.get("workspace_id", "default_ws")),
        query=query,
        stage="router",
        available_capabilities=list(state.get("allowed_tools") or []),
        match_reason_detail="router ranked historical skills against the incoming query",
    )
    runtime_decision = resolve_runtime_decision(
        call_purpose="routing_assess",
        query=query,
        state=state,
        exec_data=exec_data,
        allowed_tools=list(state.get("allowed_tools") or []),
    )

    complexity_score, complexity_reasons = _score_dynamic_complexity(query, exec_data)
    candidate_skills = [item.model_dump(mode="json") for item in recall_result.memory_data.approved_skills]

    destinations: list[str] = []
    routing_mode = "static"
    routing_reasons: list[str] = []
    dynamic_reason = None

    if runtime_decision.routing_mode == "dynamic":
        routing_mode = "dynamic"
        dynamic_reason = " | ".join(complexity_reasons) if complexity_reasons else runtime_decision.decision_reason or "任务需要未知多步探索"
        destinations = ["dynamic_swarm"]
        routing_reasons.append(f"触发动态超级节点: {dynamic_reason}")
    else:
        if complexity_score >= 0.7:
            routing_reasons.append("任务复杂度较高，但未命中外部研究型动态分析条件，保持静态/混合分析链")
        if exec_data.inputs.structured_datasets:
            has_uninspected_data = any(not ds.dataset_schema for ds in exec_data.inputs.structured_datasets)
            if has_uninspected_data:
                destinations.append("data_inspector")
                routing_reasons.append("发现新增的或尚未探查的结构化文件")

        if exec_data.inputs.business_documents:
            has_unparsed_docs = any(doc.status != "parsed" for doc in exec_data.inputs.business_documents)
            if has_unparsed_docs:
                destinations.append("kag_retriever")
                routing_reasons.append("发现新增的业务文档，需追加提取业务规则")

        if not exec_data.inputs.business_documents:
            needs_business_context = any(kw in query for kw in _BUSINESS_KEYWORDS)
            if needs_business_context and not _has_business_context(exec_data):
                destinations.append("kag_retriever")
                routing_reasons.append("无新文档，但提问命中业务黑话，需全局检索企业规则库")

        if not destinations:
            destinations.append("analyst")
            routing_reasons.append("信息已齐备或无需前置检索，直通 Analyst")

    execution_intent = ExecutionIntent(
        intent="dynamic_flow" if routing_mode == "dynamic" else "hybrid_flow" if len(destinations) > 1 else "static_flow",
        destinations=destinations,
        reason=" | ".join([runtime_decision.decision_reason, *routing_reasons] if runtime_decision.decision_reason else routing_reasons),
        complexity_score=complexity_score,
        candidate_skills=candidate_skills,
        metadata={
            **({"dynamic_reason": dynamic_reason} if dynamic_reason else {}),
            "runtime_profile": runtime_decision.call_purpose,
            "analysis_mode": runtime_decision.analysis_mode,
            "evidence_strategy": runtime_decision.evidence_strategy,
            "effective_model_alias": runtime_decision.model_alias,
            "effective_tools": list(runtime_decision.effective_tools),
            "known_gaps": list(runtime_decision.known_gaps),
            "decision_reason": runtime_decision.decision_reason,
        },
    )
    exec_data.control.execution_intent = execution_intent

    execution_blackboard.write(tenant_id, task_id, exec_data)
    execution_blackboard.persist(tenant_id, task_id)

    return {
        "next_actions": destinations,
        "execution_intent": execution_intent.model_dump(mode="json"),
    }


def route_condition(state: DagGraphState) -> list[str]:
    """
    交通警察（Conditional Edge Callable）：
    供 LangGraph 图组装时使用，动态读取 Router 节点决定的下一步走向。
    """
    return state["next_actions"]
