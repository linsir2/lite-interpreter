"""
Router 意图路由节点

作用：
1. 优先识别需要动态探索的高复杂度任务
2. 否则走既有静态链路（数据探查 / 知识检索 / Analyst）
"""
from __future__ import annotations

from typing import Dict, Any, List, Tuple

from src.blackboard.global_blackboard import global_blackboard
from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.schema import GlobalStatus
from src.common.contracts import ExecutionIntent
from src.dag_engine.graphstate import DagGraphState
from src.common.logger import get_logger
from src.skillnet.skill_retriever import SkillRetriever
from src.storage.repository.skill_repo import SkillRepo

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
    context = getattr(exec_data, "business_context", {}) or {}
    if not isinstance(context, dict):
        return False
    return any(bool(context.get(key)) for key in ("rules", "metrics", "filters", "sources"))


def _score_dynamic_complexity(query: str, exec_data: Any) -> Tuple[float, List[str]]:
    score = 0.0
    reasons: List[str] = []

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

    if getattr(exec_data, "structured_datasets", None) and getattr(exec_data, "business_documents", None):
        score += 0.15
        reasons.append("同一任务同时涉及结构化与非结构化上下文")

    if "写代码" in query and ("找数据" in query or "验证" in query):
        score += 0.2
        reasons.append("需要外部信息收集与代码验证闭环")

    if ("预测" in query or "走势" in query or "宏观" in query) and ("财报" in query or "数据" in query):
        score += 0.15
        reasons.append("包含趋势/预测任务，且依赖外部事实支撑")

    return min(score, 1.0), reasons


def router_node(state: DagGraphState) -> Dict[str, Any]:
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
    task_local_skills = list(getattr(exec_data, "approved_skills", []) or [])
    historical_repo_skills = SkillRepo.find_approved_skills(
        tenant_id,
        getattr(exec_data, "workspace_id", state.get("workspace_id", "default_ws")),
        required_capabilities=SkillRetriever.infer_query_capabilities(query),
        limit=5,
    )
    preset_skills = SkillRetriever.load_preset_skills_for_query(
        query=query,
        available_capabilities=state.get("allowed_tools") or [],
        limit=5,
    )
    historical_skills = SkillRetriever.merge_skill_sources(historical_repo_skills, preset_skills)
    ranked_historical_matches = SkillRetriever.rank_matches_for_query(
        historical_skills,
        query=query,
        available_capabilities=state.get("allowed_tools") or [],
        limit=5,
    )
    merged_skills = SkillRetriever.merge_task_and_historical(
        task_local_skills,
        historical_skills,
        query=query,
        available_capabilities=state.get("allowed_tools") or [],
        limit=5,
    )
    exec_data.approved_skills = [descriptor.to_payload() for descriptor in merged_skills]
    new_matches = SkillRetriever.extract_historical_matches(
        task_skills=task_local_skills,
        merged_skills=merged_skills,
        ranked_matches=ranked_historical_matches,
    )
    exec_data.historical_skill_matches = SkillRetriever.merge_historical_match_updates(
        exec_data.historical_skill_matches,
        new_matches,
        stage="router",
        used_capabilities=SkillRetriever.infer_query_capabilities(query),
        match_reason_detail="router ranked historical skills against the incoming query",
    )
    for match in new_matches:
        SkillRepo.record_skill_usage(
            tenant_id,
            getattr(exec_data, "workspace_id", state.get("workspace_id", "default_ws")),
            str(match.get("name", "")),
            task_id=task_id,
            stage="router",
        )

    complexity_score, complexity_reasons = _score_dynamic_complexity(query, exec_data)
    candidate_skills = list(getattr(exec_data, "approved_skills", []) or getattr(exec_data, "matched_skills", []))

    destinations: List[str] = []
    routing_mode = "static"
    routing_reasons: List[str] = []
    dynamic_reason = None

    if complexity_score >= 0.7:
        routing_mode = "dynamic"
        dynamic_reason = " | ".join(complexity_reasons) if complexity_reasons else "任务需要未知多步探索"
        destinations = ["dynamic_swarm"]
        routing_reasons.append(f"触发动态超级节点: {dynamic_reason}")
    else:
        if exec_data.structured_datasets:
            has_uninspected_data = any(not ds.get("schema") for ds in exec_data.structured_datasets)
            if has_uninspected_data:
                destinations.append("data_inspector")
                routing_reasons.append("发现新增的或尚未探查的结构化文件")

        if exec_data.business_documents:
            has_unparsed_docs = any(doc.get("status") != "parsed" for doc in exec_data.business_documents)
            if has_unparsed_docs:
                destinations.append("kag_retriever")
                routing_reasons.append("发现新增的业务文档，需追加提取业务规则")

        if not exec_data.business_documents:
            needs_business_context = any(kw in query for kw in _BUSINESS_KEYWORDS)
            if needs_business_context and not _has_business_context(exec_data):
                destinations.append("kag_retriever")
                routing_reasons.append("无新文档，但提问命中业务黑话，需全局检索企业规则库")

        if not destinations:
            destinations.append("analyst")
            routing_reasons.append("信息已齐备或无需前置检索，直通 Analyst")

    exec_data.routing_decision = ",".join(destinations)
    exec_data.routing_reasons = " | ".join(routing_reasons)
    exec_data.routing_mode = routing_mode
    exec_data.complexity_score = complexity_score
    exec_data.dynamic_reason = dynamic_reason
    exec_data.candidate_skills = candidate_skills
    execution_intent = ExecutionIntent(
        intent="dynamic_flow" if routing_mode == "dynamic" else "hybrid_flow" if len(destinations) > 1 else "static_flow",
        destinations=destinations,
        reason=exec_data.routing_reasons,
        complexity_score=complexity_score,
        candidate_skills=candidate_skills,
        metadata={"dynamic_reason": dynamic_reason} if dynamic_reason else {},
    )
    exec_data.execution_intent = execution_intent

    execution_blackboard.write(tenant_id, task_id, exec_data)
    execution_blackboard.persist(tenant_id, task_id)

    return {
        "next_actions": destinations,
        "routing_mode": routing_mode,
        "complexity_score": complexity_score,
        "dynamic_reason": dynamic_reason,
        "candidate_skills": candidate_skills,
        "execution_intent": execution_intent.model_dump(mode="json"),
    }


def route_condition(state: DagGraphState) -> List[str]:
    """
    交通警察（Conditional Edge Callable）：
    供 LangGraph 图组装时使用，动态读取 Router 节点决定的下一步走向。
    """
    return state["next_actions"]
