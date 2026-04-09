"""Data-analysis-focused runtime decisions.

This module intentionally stays narrow:
- classify incoming tasks as data-analysis-oriented profiles
- resolve per-purpose model decisions without creating a generic framework
- build a compact analysis brief for downstream static/dynamic nodes
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from config.settings import ANALYSIS_RUNTIME_POLICY_PATH


@dataclass(frozen=True)
class AnalysisTaskProfile:
    """Normalized classification of one analysis task."""

    analysis_mode: str
    evidence_strategy: str
    routing_mode: str
    effective_tools: tuple[str, ...]
    known_gaps: tuple[str, ...]
    decision_reason: str

    def to_metadata(self) -> dict[str, Any]:
        return {
            "analysis_mode": self.analysis_mode,
            "evidence_strategy": self.evidence_strategy,
            "routing_mode": self.routing_mode,
            "effective_tools": list(self.effective_tools),
            "known_gaps": list(self.known_gaps),
            "decision_reason": self.decision_reason,
        }


@dataclass(frozen=True)
class AnalysisRuntimeDecision:
    """Resolved runtime choice for one internal analysis call purpose."""

    call_purpose: str
    model_alias: str
    analysis_mode: str
    evidence_strategy: str
    routing_mode: str
    effective_tools: tuple[str, ...]
    known_gaps: tuple[str, ...]
    decision_reason: str

    def to_metadata(self) -> dict[str, Any]:
        return {
            "call_purpose": self.call_purpose,
            "effective_model_alias": self.model_alias,
            "analysis_mode": self.analysis_mode,
            "evidence_strategy": self.evidence_strategy,
            "routing_mode": self.routing_mode,
            "effective_tools": list(self.effective_tools),
            "known_gaps": list(self.known_gaps),
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


def _keywords_for(policy: Mapping[str, Any], key: str) -> tuple[str, ...]:
    return _normalize_strings(policy.get(key))


def classify_analysis_task(
    *,
    query: str,
    exec_data: Any | None = None,
    allowed_tools: Sequence[str] | None = None,
) -> AnalysisTaskProfile:
    """Classify the task while keeping the project focused on data analysis."""

    policy = load_analysis_runtime_policy()
    lowered_query = str(query or "").lower()
    dynamic_patterns = _keywords_for(policy, "dynamic_patterns")
    dataset_keywords = _keywords_for(policy, "dataset_keywords")
    document_keywords = _keywords_for(policy, "document_keywords")
    structured_count, document_count = _execution_inputs(exec_data)
    rules, metrics, filters = _business_context(exec_data)
    known_gaps: list[str] = []
    allowed = _normalize_strings(allowed_tools)

    dynamic_hits = [pattern for pattern in dynamic_patterns if pattern.lower() in lowered_query]
    dataset_signal = structured_count > 0 or any(token.lower() in lowered_query for token in dataset_keywords)
    document_signal = (
        document_count > 0
        or any(token.lower() in lowered_query for token in document_keywords)
        or bool(rules or metrics or filters)
    )

    if dynamic_hits:
        known_gaps.extend(gap for gap in ("需要外部事实核验", "结果可能依赖联网检索") if gap not in known_gaps)
        profile_payload = policy["profiles"]["dynamic_research_analysis"]
        return AnalysisTaskProfile(
            analysis_mode="dynamic_research_analysis",
            evidence_strategy=str(profile_payload.get("evidence_strategy") or "external_research"),
            routing_mode=str(profile_payload.get("routing_mode") or "dynamic"),
            effective_tools=allowed,
            known_gaps=tuple(known_gaps),
            decision_reason=f"命中动态研究信号: {', '.join(dynamic_hits[:3])}",
        )

    if structured_count > 0 and document_signal:
        profile_payload = policy["profiles"]["hybrid_analysis"]
        if not rules and not metrics and not filters:
            known_gaps.append("业务规则尚未抽取完成")
        return AnalysisTaskProfile(
            analysis_mode="hybrid_analysis",
            evidence_strategy=str(profile_payload.get("evidence_strategy") or "dataset_and_rules"),
            routing_mode=str(profile_payload.get("routing_mode") or "static"),
            effective_tools=allowed,
            known_gaps=tuple(known_gaps),
            decision_reason="任务同时涉及结构化数据与业务规则/文档",
        )

    if structured_count > 0 or dataset_signal:
        profile_payload = policy["profiles"]["dataset_analysis"]
        if structured_count == 0:
            known_gaps.append("尚未上传结构化数据")
        return AnalysisTaskProfile(
            analysis_mode="dataset_analysis",
            evidence_strategy=str(profile_payload.get("evidence_strategy") or "dataset_first"),
            routing_mode=str(profile_payload.get("routing_mode") or "static"),
            effective_tools=allowed,
            known_gaps=tuple(known_gaps),
            decision_reason="任务以结构化数据分析为主",
        )

    if document_signal:
        profile_payload = policy["profiles"]["document_rule_analysis"]
        if document_count == 0 and not (rules or metrics or filters):
            known_gaps.append("缺少业务文档输入")
        return AnalysisTaskProfile(
            analysis_mode="document_rule_analysis",
            evidence_strategy=str(profile_payload.get("evidence_strategy") or "rules_first"),
            routing_mode=str(profile_payload.get("routing_mode") or "static"),
            effective_tools=allowed,
            known_gaps=tuple(known_gaps),
            decision_reason="任务以业务规则/口径解释为主",
        )

    profile_payload = policy["profiles"]["need_more_inputs"]
    known_gaps.extend(["缺少结构化数据", "缺少业务规则文档"])
    return AnalysisTaskProfile(
        analysis_mode="need_more_inputs",
        evidence_strategy=str(profile_payload.get("evidence_strategy") or "input_gap"),
        routing_mode=str(profile_payload.get("routing_mode") or "static"),
        effective_tools=allowed,
        known_gaps=tuple(known_gaps),
        decision_reason="当前输入不足以支撑可靠的数据分析结论",
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
    profile = classify_analysis_task(
        query=query,
        exec_data=exec_data,
        allowed_tools=allowed_tools or (state.get("allowed_tools") if isinstance(state, Mapping) else []) or [],
    )
    return AnalysisRuntimeDecision(
        call_purpose=call_purpose,
        model_alias=_resolve_model_alias(call_purpose, state or {}),
        analysis_mode=profile.analysis_mode,
        evidence_strategy=profile.evidence_strategy,
        routing_mode=profile.routing_mode,
        effective_tools=profile.effective_tools,
        known_gaps=profile.known_gaps,
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
