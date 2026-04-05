"""Minimal analyst node for the static execution path."""
from __future__ import annotations

from typing import Any, Dict

from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.global_blackboard import global_blackboard
from src.blackboard.schema import GlobalStatus
from src.common import get_logger
from src.dag_engine.graphstate import DagGraphState
from src.skillnet.skill_retriever import SkillRetriever
from src.storage.repository.skill_repo import SkillRepo

logger = get_logger(__name__)


def _format_approved_skill_hints(approved_skills: list[dict[str, Any]]) -> str:
    if not approved_skills:
        return "暂无已批准技能"
    parts = []
    for skill in approved_skills[:3]:
        name = str(skill.get("name", "unknown"))
        required = ", ".join(str(item) for item in (skill.get("required_capabilities") or [])[:3]) or "none"
        provenance = (skill.get("promotion") or {}).get("provenance", {}) or {}
        validation_status = provenance.get("validation_status") or "unknown"
        parts.append(f"{name}(caps={required}; validation={validation_status})")
    return "；".join(parts)


def analyst_node(state: DagGraphState) -> Dict[str, Any]:
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
    task_local_skills = list(exec_data.approved_skills or [])
    historical_repo_skills = SkillRepo.find_approved_skills(
        tenant_id,
        exec_data.workspace_id,
        required_capabilities=SkillRetriever.infer_query_capabilities(query),
        limit=5,
    )
    preset_skills = SkillRetriever.load_preset_skills_for_query(
        query=query,
        available_capabilities=exec_data.task_envelope.allowed_tools if exec_data.task_envelope else [],
        limit=5,
    )
    historical_skills = SkillRetriever.merge_skill_sources(historical_repo_skills, preset_skills)
    ranked_historical_matches = SkillRetriever.rank_matches_for_query(
        historical_skills,
        query=query,
        available_capabilities=exec_data.task_envelope.allowed_tools if exec_data.task_envelope else [],
        limit=5,
    )
    merged_skills = SkillRetriever.merge_task_and_historical(
        task_local_skills,
        historical_skills,
        query=query,
        available_capabilities=exec_data.task_envelope.allowed_tools if exec_data.task_envelope else [],
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
        stage="analyst",
        used_capabilities=SkillRetriever.infer_query_capabilities(query),
        match_reason_detail="analyst reused historical skills while drafting the analysis plan",
    )
    for match in new_matches:
        SkillRepo.record_skill_usage(
            tenant_id,
            exec_data.workspace_id,
            str(match.get("name", "")),
            task_id=task_id,
            stage="analyst",
        )

    evidence_summary = []
    if exec_data.business_context.get("rules"):
        evidence_summary.append(f"rules={len(exec_data.business_context['rules'])}")
    if exec_data.business_context.get("metrics"):
        evidence_summary.append(f"metrics={len(exec_data.business_context['metrics'])}")
    if exec_data.structured_datasets:
        evidence_summary.append(f"datasets={len(exec_data.structured_datasets)}")
    if refined_context:
        evidence_summary.append("refined_context=present")
    if getattr(exec_data, "approved_skills", None):
        evidence_summary.append(f"approved_skills={len(exec_data.approved_skills)}")

    analysis_plan = (
        f"目标: {query}\n"
        f"证据: {', '.join(evidence_summary) if evidence_summary else '无额外上下文'}\n"
        "步骤:\n"
        "1. 汇总可用业务上下文与检索证据\n"
        f"2. 优先评估可复用技能: {_format_approved_skill_hints(exec_data.approved_skills)}\n"
        "3. 生成一个可在沙箱中执行的最小安全代码片段\n"
        "4. 在执行前进行 AST 审计\n"
        "5. 将执行结果回写黑板与前端事件流"
    )

    exec_data.analysis_plan = analysis_plan
    execution_blackboard.write(tenant_id, task_id, exec_data)
    execution_blackboard.persist(tenant_id, task_id)
    return {"analysis_plan": analysis_plan, "next_actions": ["coder"]}
