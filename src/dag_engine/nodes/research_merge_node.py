"""Merge dynamic research results back into the static analysis context."""

from __future__ import annotations

from typing import Any

from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.schema import AnalysisBriefState, KnowledgeSnapshotState
from src.common import get_logger
from src.runtime import build_analysis_brief

logger = get_logger(__name__)


def _normalized_strings(values: list[Any] | None) -> list[str]:
    normalized: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def research_merge_node(state: dict[str, Any]) -> dict[str, Any]:
    tenant_id = state["tenant_id"]
    task_id = state["task_id"]
    query = state["input_query"]

    exec_data = execution_blackboard.read(tenant_id, task_id)
    if not exec_data:
        logger.warning(f"[ResearchMerge] 找不到任务 {task_id} 的执行上下文")
        next_actions = (
            ["analyst"]
            if bool((state.get("execution_intent") or {}).get("metadata", {}).get("requires_static_execution"))
            else ["skill_harvester"]
        )
        return {"next_actions": next_actions}

    execution_intent = state.get("execution_intent") or {}
    execution_intent_metadata = execution_intent.get("metadata") if isinstance(execution_intent, dict) else {}
    requires_static_execution = bool((execution_intent_metadata or {}).get("requires_static_execution"))
    if not requires_static_execution:
        return {"next_actions": ["skill_harvester"]}
    fallback_destinations = _normalized_strings(
        list((execution_intent_metadata or {}).get("fallback_destinations") or [])
    )
    next_actions = fallback_destinations or ["analyst"]

    dynamic_summary = str(state.get("dynamic_summary") or exec_data.dynamic.summary or "").strip()
    research_findings = _normalized_strings(
        list(state.get("dynamic_research_findings") or []) or list(exec_data.dynamic.research_findings or [])
    )
    if dynamic_summary and dynamic_summary not in research_findings:
        research_findings.insert(0, dynamic_summary)
    evidence_refs = _normalized_strings(
        list(state.get("dynamic_evidence_refs") or [])
        or list(exec_data.dynamic.evidence_refs or [])
        or list(state.get("dynamic_trace_refs") or [])
        or list(exec_data.dynamic.trace_refs or [])
    )
    artifact_refs = _normalized_strings(
        list(state.get("dynamic_artifacts") or []) or list(exec_data.dynamic.artifacts or [])
    )
    open_questions = _normalized_strings(
        list(state.get("dynamic_open_questions") or []) or list(exec_data.dynamic.open_questions or [])
    )
    suggested_static_actions = _normalized_strings(
        list(state.get("dynamic_suggested_static_actions") or []) or list(exec_data.dynamic.suggested_static_actions or [])
    )

    knowledge_snapshot_payload = exec_data.knowledge.knowledge_snapshot.model_dump(mode="json")
    existing_hits = list(knowledge_snapshot_payload.get("hits") or [])
    dynamic_hits = [
        {
            "chunk_id": f"dynamic:{task_id}:{index}",
            "text": finding,
            "score": 1.0,
            "source": "dynamic_swarm",
            "retrieval_type": "dynamic_research",
        }
        for index, finding in enumerate(research_findings, start=1)
    ]
    knowledge_snapshot_payload["hits"] = [*existing_hits, *dynamic_hits]
    knowledge_snapshot_payload["evidence_refs"] = _normalized_strings(
        list(knowledge_snapshot_payload.get("evidence_refs") or []) + evidence_refs + artifact_refs
    )
    metadata = dict(knowledge_snapshot_payload.get("metadata") or {})
    metadata["dynamic_research"] = {
        "finding_count": len(research_findings),
        "open_question_count": len(open_questions),
        "artifact_count": len(artifact_refs),
    }
    knowledge_snapshot_payload["metadata"] = metadata
    snapshot = KnowledgeSnapshotState.model_validate(knowledge_snapshot_payload)
    exec_data.knowledge.knowledge_snapshot = snapshot

    recommended_next_step = (
        suggested_static_actions[0]
        if suggested_static_actions
        else "基于动态研究结果生成静态分析计划并准备模板化执行代码"
    )
    brief = build_analysis_brief(
        query=query,
        exec_data=exec_data,
        knowledge_snapshot=snapshot.model_dump(mode="json"),
        business_context=exec_data.knowledge.business_context.model_dump(mode="json"),
        analysis_mode="dynamic_research_analysis",
        known_gaps=open_questions,
        recommended_next_step=recommended_next_step,
    )
    brief_payload = brief.to_payload()
    exec_data.knowledge.analysis_brief = AnalysisBriefState.model_validate(brief_payload)

    execution_blackboard.write(tenant_id, task_id, exec_data)
    execution_blackboard.persist(tenant_id, task_id)
    refined_context = "\n".join(
        [
            *(f"- 研究发现: {item}" for item in research_findings[:5]),
            *(f"- 证据引用: {item}" for item in knowledge_snapshot_payload["evidence_refs"][:5]),
        ]
    ).strip()
    return {
        "knowledge_snapshot": snapshot.model_dump(mode="json"),
        "analysis_brief": brief_payload,
        "refined_context": refined_context,
        "next_actions": next_actions,
    }
