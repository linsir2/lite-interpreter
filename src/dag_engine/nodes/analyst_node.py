"""Minimal analyst node for the static execution path."""
from __future__ import annotations

from typing import Any

from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.global_blackboard import global_blackboard
from src.blackboard.schema import GlobalStatus
from src.common import get_logger
from src.dag_engine.graphstate import DagGraphState
from src.memory import MemoryService
from src.runtime import build_analysis_brief, resolve_runtime_decision

logger = get_logger(__name__)


def _format_approved_skill_hints(approved_skills: list[dict[str, Any]]) -> str:
    if not approved_skills:
        return "暂无已批准技能"
    parts = []
    for skill in approved_skills[:3]:
        name = str(skill.name if hasattr(skill, "name") else skill.get("name", "unknown"))
        required_capabilities = (
            skill.required_capabilities
            if hasattr(skill, "required_capabilities")
            else (skill.get("required_capabilities") or [])
        )
        required = ", ".join(str(item) for item in required_capabilities[:3]) or "none"
        promotion = skill.promotion if hasattr(skill, "promotion") else (skill.get("promotion") or {})
        provenance = promotion.provenance if hasattr(promotion, "provenance") else (promotion.get("provenance") or {})
        validation_status = provenance.validation_status if hasattr(provenance, "validation_status") else (provenance.get("validation_status") or "unknown")
        parts.append(f"{name}(caps={required}; validation={validation_status})")
    return "；".join(parts)


def analyst_node(state: DagGraphState) -> dict[str, Any]:
    tenant_id = state["tenant_id"]
    task_id = state["task_id"]
    query = state["input_query"]
    refined_context = str(state.get("refined_context", "") or "")

    global_blackboard.update_global_status(
        task_id=task_id,
        new_status=GlobalStatus.ANALYZING,
        sub_status="正在生成静态执行计划",
    )

    exec_data = execution_blackboard.read(tenant_id, task_id)
    if not exec_data:
        logger.warning(f"[Analyst] 缺少任务 {task_id} 的执行上下文")
        return {"analysis_plan": "", "next_actions": ["coder"]}
    memory_data = MemoryService.recall_skills(
        tenant_id=tenant_id,
        task_id=task_id,
        workspace_id=exec_data.workspace_id,
        query=query,
        stage="analyst",
        available_capabilities=exec_data.control.task_envelope.allowed_tools if exec_data.control.task_envelope else [],
        match_reason_detail="analyst reused historical skills while drafting the analysis plan",
    ).memory_data
    runtime_decision = resolve_runtime_decision(
        call_purpose="analysis_summary",
        query=query,
        state=state,
        exec_data=exec_data,
        allowed_tools=exec_data.control.task_envelope.allowed_tools if exec_data.control.task_envelope else [],
    )
    analysis_brief_payload = state.get("analysis_brief") if isinstance(state.get("analysis_brief"), dict) else None
    if analysis_brief_payload is None and exec_data.knowledge.analysis_brief.question:
        analysis_brief_payload = exec_data.knowledge.analysis_brief.model_dump(mode="json")
    analysis_brief = analysis_brief_payload or build_analysis_brief(
        query=query,
        exec_data=exec_data,
        knowledge_snapshot=exec_data.knowledge.knowledge_snapshot.model_dump(mode="json"),
        business_context=exec_data.knowledge.business_context.model_dump(mode="json"),
        analysis_mode=runtime_decision.analysis_mode,
        known_gaps=runtime_decision.known_gaps,
    ).to_payload()

    evidence_summary = []
    if analysis_brief.get("business_rules"):
        evidence_summary.append(f"rules={len(analysis_brief['business_rules'])}")
    if analysis_brief.get("business_metrics"):
        evidence_summary.append(f"metrics={len(analysis_brief['business_metrics'])}")
    if analysis_brief.get("dataset_summaries"):
        evidence_summary.append(f"datasets={len(analysis_brief['dataset_summaries'])}")
    if refined_context:
        evidence_summary.append("refined_context=present")
    if memory_data.approved_skills:
        evidence_summary.append(f"approved_skills={len(memory_data.approved_skills)}")
    if analysis_brief.get("evidence_refs"):
        evidence_summary.append(f"evidence_refs={len(analysis_brief['evidence_refs'])}")

    analysis_plan = (
        f"任务类型: {analysis_brief.get('analysis_mode') or runtime_decision.analysis_mode}\n"
        f"目标: {query}\n"
        f"证据策略: {runtime_decision.evidence_strategy}\n"
        f"证据概览: {', '.join(evidence_summary) if evidence_summary else '无额外上下文'}\n"
        f"数据输入: {'；'.join(analysis_brief.get('dataset_summaries') or ['暂无结构化数据'])}\n"
        f"规则与口径: {'；'.join(list(analysis_brief.get('business_rules') or []) + list(analysis_brief.get('business_metrics') or []) + list(analysis_brief.get('business_filters') or [])) or '暂无规则/指标/过滤条件'}\n"
        f"证据引用: {', '.join(analysis_brief.get('evidence_refs') or []) or 'none'}\n"
        f"已知缺口: {'；'.join(analysis_brief.get('known_gaps') or []) or 'none'}\n"
        "步骤:\n"
        "1. 先核对数据结构、业务规则和证据引用是否足以支撑分析结论\n"
        f"2. 优先评估可复用技能: {_format_approved_skill_hints(memory_data.approved_skills)}\n"
        "3. 生成一个面向统计、校验、分组和过滤的数据分析代码片段\n"
        "4. 在执行前进行 AST 审计\n"
        f"5. {analysis_brief.get('recommended_next_step') or '将执行结果回写黑板与前端事件流'}"
    )

    exec_data.knowledge.analysis_brief = analysis_brief
    exec_data.static.analysis_plan = analysis_plan
    execution_blackboard.write(tenant_id, task_id, exec_data)
    execution_blackboard.persist(tenant_id, task_id)
    return {"analysis_plan": analysis_plan, "next_actions": ["coder"]}
