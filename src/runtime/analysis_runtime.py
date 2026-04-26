"""Data-analysis-focused runtime decisions.

This module intentionally stays narrow:
- classify incoming tasks as data-analysis-oriented profiles
- resolve per-purpose model decisions without creating a generic framework
- build a compact analysis brief for downstream static/dynamic nodes
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from config.settings import ANALYSIS_RUNTIME_POLICY_PATH

from src.common.llm_client import LiteLLMClient
from src.kag.compiler import KnowledgeCompilerService
from src.runtime.guidance_runner import run_route_selection


@dataclass(frozen=True)
class AnalysisTaskProfile:
    """Normalized classification of one analysis task."""

    analysis_mode: str
    research_mode: str
    coarse_mode: str
    final_mode: str
    evidence_strategy: str
    routing_mode: str
    destinations: tuple[str, ...]
    route_candidates: tuple[str, ...]
    routing_stage: str
    routing_confidence: float
    routing_degraded: bool
    degrade_reason: str
    requires_static_execution: bool
    requires_external_research: bool
    fine_routing_invoked: bool
    continuation: str
    next_static_steps: tuple[str, ...]
    effective_tools: tuple[str, ...]
    known_gaps: tuple[str, ...]
    routing_reasons: tuple[str, ...]
    complexity_score: float
    decision_reason: str

    def to_metadata(self) -> dict[str, Any]:
        return {
            "analysis_mode": self.analysis_mode,
            "research_mode": self.research_mode,
            "coarse_mode": self.coarse_mode,
            "final_mode": self.final_mode,
            "evidence_strategy": self.evidence_strategy,
            "routing_mode": self.routing_mode,
            "destinations": list(self.destinations),
            "route_candidates": list(self.route_candidates),
            "routing_stage": self.routing_stage,
            "routing_confidence": self.routing_confidence,
            "routing_degraded": self.routing_degraded,
            "degrade_reason": self.degrade_reason,
            "requires_static_execution": self.requires_static_execution,
            "requires_external_research": self.requires_external_research,
            "fine_routing_invoked": self.fine_routing_invoked,
            "continuation": self.continuation,
            "next_static_steps": list(self.next_static_steps),
            "effective_tools": list(self.effective_tools),
            "known_gaps": list(self.known_gaps),
            "routing_reasons": list(self.routing_reasons),
            "complexity_score": self.complexity_score,
            "decision_reason": self.decision_reason,
        }


@dataclass(frozen=True)
class AnalysisRuntimeDecision:
    """Resolved runtime choice for one internal analysis call purpose."""

    call_purpose: str
    model_alias: str
    analysis_mode: str
    research_mode: str
    coarse_mode: str
    final_mode: str
    evidence_strategy: str
    routing_mode: str
    destinations: tuple[str, ...]
    route_candidates: tuple[str, ...]
    routing_stage: str
    routing_confidence: float
    routing_degraded: bool
    degrade_reason: str
    requires_static_execution: bool
    requires_external_research: bool
    fine_routing_invoked: bool
    continuation: str
    next_static_steps: tuple[str, ...]
    effective_tools: tuple[str, ...]
    known_gaps: tuple[str, ...]
    routing_reasons: tuple[str, ...]
    complexity_score: float
    decision_reason: str

    def to_metadata(self) -> dict[str, Any]:
        return {
            "call_purpose": self.call_purpose,
            "effective_model_alias": self.model_alias,
            "analysis_mode": self.analysis_mode,
            "research_mode": self.research_mode,
            "coarse_mode": self.coarse_mode,
            "final_mode": self.final_mode,
            "evidence_strategy": self.evidence_strategy,
            "routing_mode": self.routing_mode,
            "destinations": list(self.destinations),
            "route_candidates": list(self.route_candidates),
            "routing_stage": self.routing_stage,
            "routing_confidence": self.routing_confidence,
            "routing_degraded": self.routing_degraded,
            "degrade_reason": self.degrade_reason,
            "requires_static_execution": self.requires_static_execution,
            "requires_external_research": self.requires_external_research,
            "fine_routing_invoked": self.fine_routing_invoked,
            "continuation": self.continuation,
            "next_static_steps": list(self.next_static_steps),
            "effective_tools": list(self.effective_tools),
            "known_gaps": list(self.known_gaps),
            "routing_reasons": list(self.routing_reasons),
            "complexity_score": self.complexity_score,
            "decision_reason": self.decision_reason,
        }


@dataclass(frozen=True)
class AnalysisBrief:
    """Compact downstream brief for one data-analysis task."""

    question: str
    analysis_mode: str
    dataset_summaries: tuple[str, ...]
    business_rules: tuple[str, ...]
    business_metrics: tuple[str, ...]
    business_filters: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    known_gaps: tuple[str, ...]
    recommended_next_step: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "analysis_mode": self.analysis_mode,
            "dataset_summaries": list(self.dataset_summaries),
            "business_rules": list(self.business_rules),
            "business_metrics": list(self.business_metrics),
            "business_filters": list(self.business_filters),
            "evidence_refs": list(self.evidence_refs),
            "known_gaps": list(self.known_gaps),
            "recommended_next_step": self.recommended_next_step,
        }


def _default_policy() -> dict[str, Any]:
    return {
        "call_purposes": {
            "routing_assess": {"model_alias": "fast_model"},
            "query_rewrite": {"model_alias": "fast_model"},
            "context_compress": {"model_alias": "reasoning_model"},
            "analysis_summary": {"model_alias": "reasoning_model"},
            "dynamic_research": {"model_alias": "reasoning_model"},
        },
        "profiles": {
            "dataset_analysis": {"evidence_strategy": "dataset_first", "routing_mode": "static"},
            "document_rule_analysis": {"evidence_strategy": "rules_first", "routing_mode": "static"},
            "hybrid_analysis": {"evidence_strategy": "dataset_and_rules", "routing_mode": "static"},
            "dynamic_research_analysis": {"evidence_strategy": "external_research", "routing_mode": "dynamic"},
            "need_more_inputs": {"evidence_strategy": "input_gap", "routing_mode": "static"},
        },
        "dynamic_patterns": [],
        "single_pass_patterns": [],
        "iterative_patterns": [],
        "dataset_keywords": [],
        "document_keywords": [],
    }


def _merge_policy(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(merged.get(key), dict) and isinstance(value, Mapping):
            merged[key] = _merge_policy(dict(merged[key]), value)
            continue
        merged[key] = value
    return merged


@lru_cache(maxsize=1)
def load_analysis_runtime_policy() -> dict[str, Any]:
    policy = _default_policy()
    config_path = Path(ANALYSIS_RUNTIME_POLICY_PATH)
    if config_path.exists():
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if isinstance(raw, Mapping):
            policy = _merge_policy(policy, raw)
    return policy


def _normalize_strings(values: Sequence[Any] | None) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text:
            normalized.append(text)
    return tuple(normalized)


def _unique_strings(values: Sequence[str]) -> tuple[str, ...]:
    ordered: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in ordered:
            ordered.append(text)
    return tuple(ordered)


def _safe_len(value: Any) -> int:
    try:
        return len(value or [])
    except Exception:
        return 0


def _execution_inputs(exec_data: Any) -> tuple[int, int]:
    inputs = getattr(exec_data, "inputs", None)
    structured_count = _safe_len(getattr(inputs, "structured_datasets", None))
    document_count = _safe_len(getattr(inputs, "business_documents", None))
    return structured_count, document_count


def _business_context(exec_data: Any) -> tuple[list[str], list[str], list[str]]:
    knowledge = getattr(exec_data, "knowledge", None)
    context = getattr(knowledge, "business_context", None)
    rules = [str(item) for item in (getattr(context, "rules", None) or []) if str(item).strip()]
    metrics = [str(item) for item in (getattr(context, "metrics", None) or []) if str(item).strip()]
    filters = [str(item) for item in (getattr(context, "filters", None) or []) if str(item).strip()]
    return rules, metrics, filters


def _has_business_context(exec_data: Any) -> bool:
    rules, metrics, filters = _business_context(exec_data)
    return bool(rules or metrics or filters)


def _resolve_static_destinations(
    *,
    query: str,
    exec_data: Any | None,
    document_keywords: Sequence[str],
    structured_count: int,
    document_signal: bool,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    lowered_query = str(query or "").lower()
    inputs = getattr(exec_data, "inputs", None)
    structured_datasets = list(getattr(inputs, "structured_datasets", None) or [])
    business_documents = list(getattr(inputs, "business_documents", None) or [])
    destinations: list[str] = []
    reasons: list[str] = []

    if structured_datasets:
        has_uninspected_data = any(not str(getattr(dataset, "dataset_schema", "") or "").strip() for dataset in structured_datasets)
        if has_uninspected_data:
            destinations.append("data_inspector")
            reasons.append("发现新增的或尚未探查的结构化文件")

    if business_documents:
        has_unparsed_docs = any(str(getattr(document, "status", "") or "").strip() != "parsed" for document in business_documents)
        if has_unparsed_docs:
            destinations.append("kag_retriever")
            reasons.append("发现新增的业务文档，需追加提取业务规则")
        elif not _has_business_context(exec_data):
            destinations.append("kag_retriever")
            reasons.append("业务文档已存在但尚未形成业务上下文，需补齐规则准备")

    if structured_count > 0 and document_signal and not _has_business_context(exec_data):
        if "kag_retriever" not in destinations:
            destinations.append("kag_retriever")
        reasons.append("混合分析缺少已抽取的业务上下文，需补齐规则准备")

    if not business_documents:
        needs_business_context = any(keyword.lower() in lowered_query for keyword in document_keywords)
        if needs_business_context and not _has_business_context(exec_data):
            destinations.append("kag_retriever")
            reasons.append("缺少业务上下文，需先检索规则/文档知识")

    if not destinations:
        destinations.append("analyst")
        reasons.append("信息已齐备或无需前置检索，直通 Analyst")

    return _unique_strings(destinations), tuple(reasons)


def _score_routing_complexity(
    *,
    query: str,
    dynamic_hits: Sequence[str],
    structured_count: int,
    document_signal: bool,
    requires_static_execution: bool,
) -> float:
    lowered_query = str(query or "").lower()
    score = 0.0
    if len(query) >= 40:
        score += 0.15
    if dynamic_hits:
        score += min(0.45, 0.16 * len(dynamic_hits))
    coordination_hints = ("结合", "并", "同时", "然后", "再", "并且")
    if sum(1 for hint in coordination_hints if hint in query) >= 2:
        score += 0.15
    if structured_count > 0 and document_signal:
        score += 0.15
    if requires_static_execution and ("找数据" in query or "research" in lowered_query or "benchmark" in lowered_query):
        score += 0.15
    iterative_markers = ("自己找数据", "多来源", "benchmark", "财报", "宏观", "探索")
    if sum(1 for marker in iterative_markers if marker in query or marker in lowered_query) >= 2:
        score += 0.15
    if ("预测" in query or "走势" in query or "宏观" in query) and ("财报" in query or "数据" in query):
        score += 0.1
    return min(score, 1.0)


def _coarse_confidence(
    *,
    coarse_mode: str,
    route_candidates: Sequence[str],
    structured_count: int,
    document_signal: bool,
    dynamic_hits: Sequence[str],
) -> float:
    confidence = 0.62
    if coarse_mode == "dynamic":
        confidence += 0.15 + min(0.12, 0.04 * len(dynamic_hits))
    elif coarse_mode == "hybrid":
        confidence += 0.2 if structured_count > 0 and document_signal else 0.12
    else:
        confidence += 0.18 if structured_count > 0 or document_signal else 0.08
    if len(route_candidates) == 1:
        confidence += 0.1
    else:
        confidence -= 0.05
    return max(0.05, min(confidence, 0.97))


def _extract_json_object(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("fine routing response must be a JSON object")
    return payload


def _maybe_refine_route_with_llm(
    *,
    query: str,
    route_candidates: Sequence[str],
    coarse_mode: str,
    coarse_confidence: float,
    complexity_score: float,
    policy: Mapping[str, Any],
    model_alias: str,
) -> tuple[str, str, bool, bool, str, float, str | None]:
    fine_policy = policy.get("fine_routing", {})
    enabled = bool(fine_policy.get("enabled", False)) and _fine_routing_runtime_enabled(model_alias)
    min_candidate_count = int(fine_policy.get("min_candidate_count", 2) or 2)
    ambiguity_threshold = float(fine_policy.get("ambiguity_threshold", 0.45) or 0.45)
    if not enabled or len(route_candidates) < min_candidate_count or complexity_score < ambiguity_threshold:
        return coarse_mode, "coarse", False, False, "", coarse_confidence, None

    try:
        result = run_route_selection(query=query, route_candidates=list(route_candidates), model_alias=model_alias)
        payload = dict(result.payload)
        final_mode = str(payload.get("final_mode") or coarse_mode).strip()
        confidence = float(payload.get("confidence") or coarse_confidence)
        rationale = str(payload.get("rationale") or "").strip()
        return (
            final_mode,
            "fine",
            True,
            bool(result.degraded),
            str(result.degrade_reason or ""),
            max(coarse_confidence, min(confidence, 0.99)),
            rationale or None,
        )
    except Exception as exc:
        return coarse_mode, "fallback", True, True, f"fine routing unavailable: {exc}", coarse_confidence, None


def _fine_routing_runtime_enabled(model_alias: str) -> bool:
    try:
        config = LiteLLMClient.get_model_config(model_alias)
    except Exception:
        return False
    api_key = str(config.params.get("api_key") or "").strip()
    return bool(api_key)


def _analysis_mode_for_static_branch(
    *,
    structured_count: int,
    document_signal: bool,
    static_mode: str,
) -> str:
    if static_mode == "hybrid":
        return "hybrid_analysis"
    if structured_count > 0:
        return "dataset_analysis"
    if document_signal:
        return "document_rule_analysis"
    return "need_more_inputs"


def _build_non_dynamic_profile(
    *,
    policy: Mapping[str, Any],
    analysis_mode: str,
    research_mode: str,
    final_mode: str,
    destinations: tuple[str, ...],
    route_candidates: tuple[str, ...],
    structured_count: int,
    document_signal: bool,
    allowed: tuple[str, ...],
    known_gaps: list[str],
    decision_reason: str,
    routing_reasons: tuple[str, ...],
    complexity_score: float,
    requires_static_execution: bool,
    requires_external_research: bool = False,
) -> AnalysisTaskProfile:
    profile_payload = policy["profiles"][analysis_mode]
    return AnalysisTaskProfile(
        analysis_mode=analysis_mode,
        research_mode=research_mode,
        coarse_mode=final_mode,
        final_mode=final_mode,
        evidence_strategy=str(profile_payload.get("evidence_strategy") or "dataset_first"),
        routing_mode=str(profile_payload.get("routing_mode") or "static"),
        destinations=destinations,
        route_candidates=route_candidates,
        routing_stage="coarse",
        routing_confidence=_coarse_confidence(
            coarse_mode=final_mode,
            route_candidates=route_candidates,
            structured_count=structured_count,
            document_signal=document_signal,
            dynamic_hits=(),
        ),
        routing_degraded=False,
        degrade_reason="",
        requires_static_execution=requires_static_execution,
        requires_external_research=requires_external_research,
        fine_routing_invoked=False,
        continuation="finish",
        next_static_steps=(),
        effective_tools=allowed,
        known_gaps=tuple(dict.fromkeys(known_gaps)),
        routing_reasons=routing_reasons,
        complexity_score=complexity_score,
        decision_reason=decision_reason,
    )


def _keywords_for(policy: Mapping[str, Any], key: str) -> tuple[str, ...]:
    return _normalize_strings(policy.get(key))


def classify_analysis_task(
    *,
    query: str,
    exec_data: Any | None = None,
    allowed_tools: Sequence[str] | None = None,
    fine_model_alias: str | None = None,
) -> AnalysisTaskProfile:
    """Classify the task while keeping the project focused on data analysis."""

    policy = load_analysis_runtime_policy()
    lowered_query = str(query or "").lower()
    dynamic_patterns = _keywords_for(policy, "dynamic_patterns")
    single_pass_patterns = _keywords_for(policy, "single_pass_patterns")
    iterative_patterns = _keywords_for(policy, "iterative_patterns")
    dataset_keywords = _keywords_for(policy, "dataset_keywords")
    document_keywords = _keywords_for(policy, "document_keywords")
    structured_count, document_count = _execution_inputs(exec_data)
    rules, metrics, filters = _business_context(exec_data)
    known_gaps: list[str] = []
    allowed = _normalize_strings(allowed_tools)
    lexical_signals = KnowledgeCompilerService.classify_query(query)

    dynamic_hits = list(
        dict.fromkeys([match.canonical for match in lexical_signals.dynamic_hits] or [pattern for pattern in dynamic_patterns if pattern.lower() in lowered_query])
    )
    single_pass_hits = list(dict.fromkeys(pattern for pattern in single_pass_patterns if pattern.lower() in lowered_query))
    iterative_hits = list(dict.fromkeys(pattern for pattern in iterative_patterns if pattern.lower() in lowered_query))
    if not iterative_patterns and dynamic_hits:
        iterative_hits = list(dynamic_hits)
    dataset_signal = structured_count > 0 or bool(lexical_signals.dataset_hits) or any(
        token.lower() in lowered_query for token in dataset_keywords
    )
    document_signal = (
        document_count > 0
        or bool(lexical_signals.document_hits)
        or any(token.lower() in lowered_query for token in document_keywords)
        or bool(rules or metrics or filters)
    )
    static_destinations, static_reasons = _resolve_static_destinations(
        query=query,
        exec_data=exec_data,
        document_keywords=document_keywords,
        structured_count=structured_count,
        document_signal=document_signal,
    )
    static_mode = "hybrid" if structured_count > 0 and document_signal else "static"
    static_analysis_mode = _analysis_mode_for_static_branch(
        structured_count=structured_count,
        document_signal=document_signal,
        static_mode=static_mode,
    )
    requires_static_execution = bool(structured_count > 0 or "写代码" in query or "验证" in query or static_mode == "hybrid")
    requires_external_research = bool(dynamic_hits or single_pass_hits)
    complexity_score = _score_routing_complexity(
        query=query,
        dynamic_hits=dynamic_hits,
        structured_count=structured_count,
        document_signal=document_signal,
        requires_static_execution=requires_static_execution,
    )

    if iterative_hits:
        known_gaps.extend(gap for gap in ("需要外部事实核验", "结果可能依赖联网检索") if gap not in known_gaps)
        coarse_mode = "dynamic"
        coarse_analysis_mode = "dynamic_research_analysis"
        route_candidates = _unique_strings(("dynamic", static_mode))
        coarse_reasons = [f"命中动态研究信号: {', '.join(iterative_hits[:3])}"]
        coarse_confidence = _coarse_confidence(
            coarse_mode=coarse_mode,
            route_candidates=route_candidates,
            structured_count=structured_count,
            document_signal=document_signal,
            dynamic_hits=iterative_hits,
        )
        final_mode, routing_stage, fine_routing_invoked, routing_degraded, degrade_reason, routing_confidence, fine_rationale = _maybe_refine_route_with_llm(
            query=query,
            route_candidates=route_candidates,
            coarse_mode=coarse_mode,
            coarse_confidence=coarse_confidence,
            complexity_score=complexity_score,
            policy=policy,
            model_alias=str(fine_model_alias or policy.get("fine_routing", {}).get("model_alias") or "reasoning_model"),
        )
        if fine_rationale:
            coarse_reasons.append(f"精筛理由: {fine_rationale}")
        analysis_mode = coarse_analysis_mode if final_mode == "dynamic" else static_analysis_mode
        profile_key = analysis_mode
        destinations = ("dynamic_swarm",) if final_mode == "dynamic" else static_destinations
        continuation = "resume_static" if final_mode == "dynamic" and requires_static_execution else "finish"
        next_static_steps = static_destinations if continuation == "resume_static" else ()
        decision_reason = coarse_reasons[0]
        supporting_reasons: list[str] = list(coarse_reasons[1:])
        if final_mode != "dynamic":
            supporting_reasons.extend(static_reasons)
    elif structured_count > 0 and document_signal:
        if not rules and not metrics and not filters:
            known_gaps.append("业务规则尚未抽取完成")
        if requires_external_research:
            known_gaps.append("需要一次受控外部取证")
        return _build_non_dynamic_profile(
            policy=policy,
            analysis_mode="hybrid_analysis",
            research_mode="single_pass" if requires_external_research else "none",
            final_mode="hybrid",
            destinations=static_destinations,
            route_candidates=("hybrid", "static"),
            structured_count=structured_count,
            document_signal=document_signal,
            allowed=allowed,
            known_gaps=known_gaps,
            decision_reason="任务同时涉及结构化数据与业务规则/文档",
            routing_reasons=static_reasons,
            complexity_score=complexity_score,
            requires_static_execution=requires_static_execution,
            requires_external_research=requires_external_research,
        )
    elif structured_count > 0 or dataset_signal:
        if structured_count == 0:
            known_gaps.append("尚未上传结构化数据")
        if requires_external_research:
            known_gaps.append("需要一次受控外部取证")
        return _build_non_dynamic_profile(
            policy=policy,
            analysis_mode="dataset_analysis",
            research_mode="single_pass" if requires_external_research else "none",
            final_mode="static",
            destinations=static_destinations,
            route_candidates=("static",),
            structured_count=structured_count,
            document_signal=document_signal,
            allowed=allowed,
            known_gaps=known_gaps,
            decision_reason="任务以结构化数据分析为主",
            routing_reasons=static_reasons,
            complexity_score=complexity_score,
            requires_static_execution=requires_static_execution,
            requires_external_research=requires_external_research,
        )
    elif document_signal:
        if document_count == 0 and not (rules or metrics or filters):
            known_gaps.append("缺少业务文档输入")
        if requires_external_research:
            known_gaps.append("需要一次受控外部取证")
        return _build_non_dynamic_profile(
            policy=policy,
            analysis_mode="document_rule_analysis",
            research_mode="single_pass" if requires_external_research else "none",
            final_mode="static",
            destinations=static_destinations,
            route_candidates=("static",),
            structured_count=structured_count,
            document_signal=document_signal,
            allowed=allowed,
            known_gaps=known_gaps,
            decision_reason="任务以业务规则/口径解释为主",
            routing_reasons=static_reasons,
            complexity_score=complexity_score,
            requires_static_execution=requires_static_execution,
            requires_external_research=requires_external_research,
        )
    else:
        known_gaps.extend(["缺少结构化数据", "缺少业务规则文档"])
        return _build_non_dynamic_profile(
            policy=policy,
            analysis_mode="need_more_inputs",
            research_mode="single_pass" if requires_external_research else "none",
            final_mode="static",
            destinations=static_destinations,
            route_candidates=("static",),
            structured_count=structured_count,
            document_signal=document_signal,
            allowed=allowed,
            known_gaps=known_gaps,
            decision_reason="当前输入不足以支撑可靠的数据分析结论",
            routing_reasons=static_reasons,
            complexity_score=complexity_score,
            requires_static_execution=requires_static_execution,
            requires_external_research=requires_external_research,
        )

    profile_payload = policy["profiles"][profile_key]
    return AnalysisTaskProfile(
        analysis_mode=analysis_mode,
        research_mode="iterative" if final_mode == "dynamic" else "single_pass",
        coarse_mode=coarse_mode,
        final_mode=final_mode,
        evidence_strategy=str(profile_payload.get("evidence_strategy") or "dataset_first"),
        routing_mode="dynamic" if final_mode == "dynamic" else str(profile_payload.get("routing_mode") or "static"),
        destinations=tuple(destinations),
        route_candidates=tuple(route_candidates),
        routing_stage=routing_stage,
        routing_confidence=routing_confidence,
        routing_degraded=routing_degraded,
        degrade_reason=degrade_reason,
        requires_static_execution=requires_static_execution,
        requires_external_research=True,
        fine_routing_invoked=fine_routing_invoked,
        continuation=continuation,
        next_static_steps=tuple(next_static_steps),
        effective_tools=allowed,
        known_gaps=tuple(dict.fromkeys(known_gaps)),
        routing_reasons=tuple(supporting_reasons),
        complexity_score=complexity_score,
        decision_reason=decision_reason,
    )


def _resolve_model_alias(call_purpose: str, state: Mapping[str, Any] | None) -> str:
    policy = load_analysis_runtime_policy()
    task_envelope = state.get("task_envelope") if isinstance(state, Mapping) else None
    metadata = {}
    if isinstance(task_envelope, Mapping):
        metadata = dict(task_envelope.get("metadata") or {})
    task_overrides = metadata.get("model_overrides") if isinstance(metadata.get("model_overrides"), Mapping) else {}
    if isinstance(task_overrides, Mapping):
        override_value = str(task_overrides.get(call_purpose) or "").strip()
        if override_value:
            return override_value
    env_key = f"ANALYSIS_RUNTIME_{call_purpose.upper()}_MODEL"
    env_value = str(os.getenv(env_key, "")).strip()
    if env_value:
        return env_value
    purpose_payload = policy.get("call_purposes", {}).get(call_purpose, {})
    return str(purpose_payload.get("model_alias") or "fast_model")


def resolve_runtime_decision(
    *,
    call_purpose: str,
    query: str,
    state: Mapping[str, Any] | None = None,
    exec_data: Any | None = None,
    allowed_tools: Sequence[str] | None = None,
) -> AnalysisRuntimeDecision:
    assess_model_alias = _resolve_model_alias(call_purpose, state or {})
    fine_model_alias = _resolve_model_alias("routing_refine", state or {})
    profile = classify_analysis_task(
        query=query,
        exec_data=exec_data,
        allowed_tools=allowed_tools or (state.get("allowed_tools") if isinstance(state, Mapping) else []) or [],
        fine_model_alias=fine_model_alias,
    )
    return AnalysisRuntimeDecision(
        call_purpose=call_purpose,
        model_alias=fine_model_alias if profile.routing_stage in {"fine", "fallback"} else assess_model_alias,
        analysis_mode=profile.analysis_mode,
        research_mode=profile.research_mode,
        coarse_mode=profile.coarse_mode,
        final_mode=profile.final_mode,
        evidence_strategy=profile.evidence_strategy,
        routing_mode=profile.routing_mode,
        destinations=profile.destinations,
        route_candidates=profile.route_candidates,
        routing_stage=profile.routing_stage,
        routing_confidence=profile.routing_confidence,
        routing_degraded=profile.routing_degraded,
        degrade_reason=profile.degrade_reason,
        requires_static_execution=profile.requires_static_execution,
        requires_external_research=profile.requires_external_research,
        fine_routing_invoked=profile.fine_routing_invoked,
        continuation=profile.continuation,
        next_static_steps=profile.next_static_steps,
        effective_tools=profile.effective_tools,
        known_gaps=profile.known_gaps,
        routing_reasons=profile.routing_reasons,
        complexity_score=profile.complexity_score,
        decision_reason=profile.decision_reason,
    )


def _dataset_summaries(exec_data: Any) -> tuple[str, ...]:
    inputs = getattr(exec_data, "inputs", None)
    datasets = getattr(inputs, "structured_datasets", None) or []
    summaries: list[str] = []
    for dataset in datasets[:3]:
        file_name = str(getattr(dataset, "file_name", "") or "unknown.csv")
        schema = str(getattr(dataset, "dataset_schema", "") or "").strip()
        if schema:
            summaries.append(f"{file_name}: schema={schema[:120]}")
        else:
            summaries.append(f"{file_name}: schema=pending")
    return tuple(summaries)


def build_analysis_brief(
    *,
    query: str,
    exec_data: Any | None,
    knowledge_snapshot: Mapping[str, Any] | None = None,
    business_context: Mapping[str, Any] | None = None,
    analysis_mode: str | None = None,
    known_gaps: Sequence[str] | None = None,
    recommended_next_step: str | None = None,
) -> AnalysisBrief:
    if isinstance(business_context, Mapping):
        rules = [str(item) for item in (business_context.get("rules") or []) if str(item).strip()]
        metrics = [str(item) for item in (business_context.get("metrics") or []) if str(item).strip()]
        filters = [str(item) for item in (business_context.get("filters") or []) if str(item).strip()]
    else:
        rules, metrics, filters = _business_context(exec_data)
    dataset_summaries = _dataset_summaries(exec_data)
    evidence_refs = _normalize_strings(
        (knowledge_snapshot or {}).get("evidence_refs") if isinstance(knowledge_snapshot, Mapping) else []
    )
    gaps = [str(item) for item in (known_gaps or []) if str(item).strip()]
    if not dataset_summaries and not rules and not metrics and not filters:
        gaps.append("当前缺少可直接消费的分析上下文")
    if not evidence_refs:
        gaps.append("缺少强证据引用")
    next_step = str(recommended_next_step or "").strip() or "生成受控的数据分析计划并准备模板化执行代码"
    return AnalysisBrief(
        question=str(query or ""),
        analysis_mode=str(analysis_mode or "dataset_analysis"),
        dataset_summaries=dataset_summaries,
        business_rules=tuple(rules[:5]),
        business_metrics=tuple(metrics[:5]),
        business_filters=tuple(filters[:5]),
        evidence_refs=evidence_refs,
        known_gaps=tuple(dict.fromkeys(gaps)),
        recommended_next_step=next_step,
    )
