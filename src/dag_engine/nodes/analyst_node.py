"""Analyst node — sole writer of the frozen ExecutionStrategy.

Uses Instructor + LiteLLM to compile the analysis context into a structured,
immutable ExecutionStrategy.  No other node may overwrite strategy fields
after this point.
"""

from __future__ import annotations

from typing import Any

import instructor
from litellm import completion

from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.global_blackboard import global_blackboard
from src.blackboard.schema import GlobalStatus
from src.common import get_logger
from src.common.contracts import CapabilityTier, EvidencePlan, ExecutionStrategy
from src.common.llm_client import LiteLLMClient
from src.dag_engine.graphstate import DagGraphState
from src.memory import MemoryService
from src.runtime import build_analysis_brief

logger = get_logger(__name__)

# Instructor-wrapped LiteLLM client — produces Pydantic models directly.
_analyst_client = instructor.from_litellm(completion)


def _resolve_analysis_brief_payload(state: DagGraphState, exec_data: Any) -> dict[str, Any] | None:
    payload = state.get("analysis_brief") if isinstance(state.get("analysis_brief"), dict) else None
    if payload is None and exec_data.knowledge.analysis_brief.question:
        return exec_data.knowledge.analysis_brief.model_dump(mode="json")
    return payload


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
        validation_status = (
            provenance.validation_status
            if hasattr(provenance, "validation_status")
            else (provenance.get("validation_status") or "unknown")
        )
        parts.append(f"{name}(caps={required}; validation={validation_status})")
    return "；".join(parts)


def _build_analyst_messages(
    query: str,
    analysis_brief: dict[str, Any],
    knowledge_snapshot: dict[str, Any],
    business_context: dict[str, Any],
    approved_skills: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Build the system + user messages for Instructor → ExecutionStrategy."""
    datasets = analysis_brief.get("dataset_summaries") or []
    rules = analysis_brief.get("business_rules") or []
    metrics = analysis_brief.get("business_metrics") or []
    filters = analysis_brief.get("business_filters") or []
    known_gaps = analysis_brief.get("known_gaps") or []
    evidence_refs = analysis_brief.get("evidence_refs") or []
    skill_hints = _format_approved_skill_hints(approved_skills)

    system = """You are an analysis planner for a governed data-analysis runtime.

Your job: read the query, data context, and knowledge snapshot, then produce
a structured ExecutionStrategy that tells the DAG what capability level is
needed and what kind of analysis code to generate.

## CapabilityTier (capability_tier)
Choose the *lowest* tier that can satisfy the query:

- static_only: pure local data analysis, no external info needed
- static_with_network: needs one or two external lookups (web_search / web_fetch)
  to fill a known gap, then local analysis
- dynamic_exploration_then_static: needs multi-step open-ended research first,
  then structured analysis on the results
- dynamic_only: pure research / summarization — no code generation needed,
  the exploration result IS the deliverable

## Analysis mode (analysis_mode)
Pick the analysis type that best matches the data and query:
- dataset_analysis: structured CSV/TSV/JSON data, profile / aggregate / compare
- document_rule_audit: business rules / policies / compliance documents
- hybrid_analysis: mix of structured data + external evidence
- need_more_inputs: not enough data to proceed
- dynamic_research_analysis: purely external / open-ended research

## Summary (summary)
A 2-3 sentence plain-language summary of the plan.  This replaces the old
free-text analysis_plan for display purposes.

## Evidence plan (evidence_plan)
If capability_tier is static_with_network or higher, specify search_queries,
allowed_domains, allowed_capabilities (web_search, web_fetch), and a
research_mode (none / single_pass / iterative).

## Fallback tier (fallback_tier)
Optional. If the primary tier fails, declare the next lower tier to try.
Must be strictly lower capability than capability_tier."""

    user_parts = [
        f"## 用户查询\n{query}",
        f"## 分析模式\n{analysis_brief.get('analysis_mode') or 'auto'}",
        f"## 数据集\n" + ("\n".join(f"- {s}" for s in datasets) if datasets else "无结构化数据"),
        f"## 业务规则\n" + ("\n".join(f"- {r}" for r in rules) if rules else "无"),
        f"## 业务指标\n" + ("\n".join(f"- {m}" for m in metrics) if metrics else "无"),
        f"## 过滤条件\n" + ("\n".join(f"- {f}" for f in filters) if filters else "无"),
        f"## 已知缺口\n" + ("\n".join(f"- {g}" for g in known_gaps) if known_gaps else "无"),
        f"## 证据引用\n{', '.join(evidence_refs) if evidence_refs else 'none'}",
        f"## 可复用技能\n{skill_hints}",
        f"## 推荐下一步\n{analysis_brief.get('recommended_next_step') or 'auto'}",
    ]
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]


def _compile_execution_strategy(
    query: str,
    analysis_brief: dict[str, Any],
    knowledge_snapshot: dict[str, Any],
    business_context: dict[str, Any],
    approved_skills: list[dict[str, Any]],
    model_alias: str,
) -> ExecutionStrategy:
    """Instructor LLM → ExecutionStrategy.  Falls back to STATIC_ONLY on failure."""
    messages = _build_analyst_messages(
        query=query,
        analysis_brief=analysis_brief,
        knowledge_snapshot=knowledge_snapshot,
        business_context=business_context,
        approved_skills=approved_skills,
    )
    config = LiteLLMClient.get_model_config(model_alias)
    try:
        strategy = _analyst_client.chat.completions.create(
            model=str(config.params.get("model") or model_alias),
            response_model=ExecutionStrategy,
            messages=messages,
            max_retries=3,
            temperature=float(config.params.get("temperature", 0.2)),
        )
        logger.info(
            f"[Analyst] plan compiled tier={strategy.capability_tier.value} "
            f"mode={strategy.analysis_mode} family={strategy.strategy_family}"
        )
        return strategy
    except Exception as exc:
        logger.error(f"[Analyst] Instructor compilation failed: {exc}")
        return ExecutionStrategy(
            capability_tier=CapabilityTier.STATIC_ONLY,
            analysis_mode=analysis_brief.get("analysis_mode") or "dataset_analysis",
            summary=f"Plan compilation failed ({exc}), falling back to static analysis.",
        )


def _next_actions_from_tier(tier: CapabilityTier) -> list[str]:
    if tier == CapabilityTier.STATIC_WITH_NETWORK:
        return ["static_evidence"]
    return ["coder"]


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

    # Build analysis brief (delegates to existing runtime helpers for context assembly)
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

    # Compile immutable ExecutionStrategy via Instructor
    execution_strategy = _compile_execution_strategy(
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

    next_actions = _next_actions_from_tier(execution_strategy.capability_tier)
    return {
        "execution_strategy": execution_strategy.model_dump(mode="json"),
        "next_actions": next_actions,
    }
