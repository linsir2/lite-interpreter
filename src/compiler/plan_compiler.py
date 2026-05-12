"""Plan compiler — Instructor + LiteLLM → frozen ExecutionStrategy.

This module is a pure compilation function: it takes analysis context in,
returns an immutable ExecutionStrategy.  Blackboard I/O is the caller's
responsibility (analyst_node).
"""

from __future__ import annotations

from typing import Any

import instructor
from litellm import completion

from src.common import get_logger
from src.common.contracts import EvidencePlan, ExecutionStrategy, IterationMode, NetworkMode
from src.common.llm_client import LiteLLMClient

logger = get_logger(__name__)

_plan_client = instructor.from_litellm(completion)

# ---- Prompt builders -------------------------------------------------------


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


_SYSTEM_PROMPT = """You are an analysis planner for a governed data-analysis runtime.

Your job: read the query, data context, and knowledge snapshot, then produce
a structured ExecutionStrategy that tells the DAG what capability level is
needed and what kind of analysis code to generate.

## Network mode (network_mode)
How much network access the task needs:

- none: pure local data analysis, no external info needed
- bounded: one or more STRUCTURED lookups. Analyst specifies the search
  queries and domain; evidence is collected iteratively with a clear
  termination condition (e.g. "fill the tariff rate lookup table").
- open: multi-step open-ended research — LLM autonomously decides what to
  search, where to fetch, and when to stop. This triggers the dynamic
  exploration node.

## Iteration mode (iteration_mode)
How many static-chain passes are needed:

- single_pass: one analyst → coder → executor round is enough
- multi_round: need multiple passes. Analyst reviews RoundOutput after each
  pass and decides whether another round is needed (additional_rounds).

## Analysis mode (analysis_mode)
Pick the analysis type that best matches the data and query:
- dataset_analysis: structured CSV/TSV/JSON data, profile / aggregate / compare
- document_rule_audit: business rules / policies / compliance documents
- hybrid_analysis: mix of structured data + external evidence
- need_more_inputs: not enough data to proceed
- dynamic_research_analysis: purely external / open-ended research

## Summary (summary)
A 2-3 sentence plain-language summary of the plan. This replaces the old
free-text analysis_plan for display purposes.

## Evidence plan (evidence_plan)
If network_mode is bounded or open, specify search_queries, allowed_domains,
allowed_capabilities (web_search, web_fetch).
"""



def _build_analyst_messages(
    query: str,
    analysis_brief: dict[str, Any],
    knowledge_snapshot: dict[str, Any],
    business_context: dict[str, Any],
    approved_skills: list[dict[str, Any]],
    previous_round_summary: str = "",
) -> list[dict[str, str]]:
    datasets = analysis_brief.get("dataset_summaries") or []
    rules = analysis_brief.get("business_rules") or []
    metrics = analysis_brief.get("business_metrics") or []
    filters = analysis_brief.get("business_filters") or []
    known_gaps = analysis_brief.get("known_gaps") or []
    evidence_refs = analysis_brief.get("evidence_refs") or []
    skill_hints = _format_approved_skill_hints(approved_skills)

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
    if previous_round_summary:
        user_parts.append(f"## 上一轮执行结果\n{previous_round_summary}")
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]


# ---- Compilation entry point -----------------------------------------------


def compile_plan(
    *,
    query: str,
    analysis_brief: dict[str, Any],
    knowledge_snapshot: dict[str, Any],
    business_context: dict[str, Any],
    approved_skills: list[dict[str, Any]],
    model_alias: str = "reasoning_model",
    previous_round_summary: str = "",
) -> ExecutionStrategy:
    """Compile analysis context into a frozen ExecutionStrategy via Instructor.

    Returns STATIC_ONLY fallback on LLM failure -- the DAG can still proceed.
    """
    messages = _build_analyst_messages(
        query=query,
        analysis_brief=analysis_brief,
        knowledge_snapshot=knowledge_snapshot,
        business_context=business_context,
        approved_skills=approved_skills,
        previous_round_summary=previous_round_summary,
    )
    config = LiteLLMClient.get_model_config(model_alias)
    try:
        strategy = _plan_client.chat.completions.create(
            model=str(config.params.get("model") or model_alias),
            response_model=ExecutionStrategy,
            messages=messages,
            max_retries=3,
            temperature=float(config.params.get("temperature", 0.2)),
        )
        logger.info(
            f"[PlanCompiler] network={strategy.network_mode.value} "
            f"iteration={strategy.iteration_mode.value} "
            f"mode={strategy.analysis_mode} family={strategy.strategy_family}"
        )
        return strategy
    except Exception as exc:
        logger.error(f"[PlanCompiler] Instructor compilation failed: {exc}")
        return ExecutionStrategy(
            network_mode=NetworkMode.NONE,
            iteration_mode=IterationMode.SINGLE_PASS,
            analysis_mode=analysis_brief.get("analysis_mode") or "dataset_analysis",
            summary=f"Plan compilation failed ({exc}), falling back to static analysis.",
        )
