"""Payload builders and directives for static code generation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from src.mcp_gateway.tools.sandbox_exec_tool import build_input_mount_manifest
from src.memory import MemoryService


@dataclass(frozen=True)
class StaticGenerationDirectives:
    focus_order: list[str]
    preferred_measure_terms: list[str]
    preferred_group_terms: list[str]
    preferred_date_terms: list[str]
    prefer_document_evidence: bool
    prefer_dataset_evidence: bool
    emit_rule_checks: bool
    emit_metric_checks: bool
    emit_filter_checks: bool
    skill_focus_hints: list[str]

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StaticCodegenPayload:
    query: str
    analysis_plan: str
    analysis_mode: str
    research_mode: str
    analysis_brief: dict[str, Any]
    business_context: dict[str, Any]
    compiled_knowledge: dict[str, Any]
    approved_skills: list[dict[str, Any]]
    skill_strategy_hints: list[dict[str, Any]]
    refined_context_excerpt: str
    input_mounts: list[dict[str, Any]]
    execution_strategy: dict[str, Any]
    static_evidence_bundle: dict[str, Any]
    structured_dataset_summaries: list[dict[str, Any]]
    generation_directives: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def serialize_preview(text: str, limit: int = 160) -> str:
    collapsed = " ".join(text.split())
    return collapsed[:limit]


def _merge_unique(*groups: list[str] | tuple[str, ...] | None) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for value in group or []:
            normalized = str(value).strip()
            if normalized and normalized not in merged:
                merged.append(normalized)
    return merged


def _normalize_skill_focus_hints(skill_strategy_hints: list[dict[str, Any]]) -> list[str]:
    normalized: list[str] = []
    for hint in skill_strategy_hints:
        for item in hint.get("focus_areas", []) or []:
            text = str(item).strip()
            if text and text not in normalized:
                normalized.append(text)
    return normalized


def build_skill_strategy_hints(approved_skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    for skill in approved_skills[:5]:
        capabilities = [str(item) for item in skill.get("required_capabilities", []) if str(item).strip()]
        focus_areas: list[str] = []
        if "knowledge_query" in capabilities:
            focus_areas.append("优先复用已有知识检索证据")
        if "sandbox_exec" in capabilities:
            focus_areas.append("保留可执行验证闭环")
        if "web_search" in capabilities or "web_fetch" in capabilities:
            focus_areas.append("在证据不足时补充外部检索")
        replay_cases = skill.get("replay_cases", []) or []
        expected_signals = []
        if replay_cases and isinstance(replay_cases[0], Mapping):
            expected_signals = [
                str(item) for item in replay_cases[0].get("expected_signals", [])[:3] if str(item).strip()
            ]
        hints.append(
            {
                "name": str(skill.get("name", "unknown_skill")),
                "focus_areas": focus_areas or ["复用该技能的既有执行模式"],
                "expected_signals": expected_signals,
                "promotion_status": str((skill.get("promotion") or {}).get("status", "unknown")),
            }
        )
    return hints


def build_static_input_mounts(exec_data: Any, extra_mounts: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    input_mounts = build_input_mount_manifest(exec_data.inputs.structured_datasets, exec_data.inputs.business_documents)
    for mount in input_mounts:
        if mount["kind"] != "structured_dataset":
            continue
        dataset_meta = next(
            (item for item in exec_data.inputs.structured_datasets if str(item.path) == mount["host_path"]),
            {},
        )
        load_kwargs = dataset_meta.load_kwargs if hasattr(dataset_meta, "load_kwargs") else {}
        mount["encoding"] = str(load_kwargs.get("encoding") or "utf-8")
        mount["sep"] = str(load_kwargs.get("sep") or ",")
        if load_kwargs.get("format"):
            mount["format"] = str(load_kwargs.get("format"))
    seen = {str(item.get("host_path") or "") for item in input_mounts}
    for mount in extra_mounts or []:
        host_path = str(mount.get("host_path") or "").strip()
        if not host_path or host_path in seen:
            continue
        seen.add(host_path)
        input_mounts.append(dict(mount))
    return input_mounts


def _collect_terms_from_specs(specs: list[dict[str, Any]], keys: tuple[str, ...]) -> list[str]:
    return _merge_unique(
        *[
            [str(item) for item in spec.get(key, []) if str(item).strip()]
            for spec in specs
            for key in keys
        ]
    )


def _derive_focus_order(
    *,
    emit_rule_checks: bool,
    emit_metric_checks: bool,
    emit_filter_checks: bool,
    prefer_document_evidence: bool,
    prefer_dataset_evidence: bool,
    analysis_plan: str,
) -> list[str]:
    base_order: list[str] = []
    if emit_rule_checks:
        base_order.append("rules")
    if emit_metric_checks:
        base_order.append("metrics")
    if emit_filter_checks:
        base_order.append("filters")

    evidence_order = ["documents", "datasets"] if prefer_document_evidence else ["datasets", "documents"]
    if not prefer_document_evidence and not prefer_dataset_evidence:
        evidence_order = ["datasets", "documents"]

    normalized_plan = str(analysis_plan or "")
    if "文档" in normalized_plan and "数据" not in normalized_plan:
        evidence_order = ["documents", "datasets"]
    elif "数据" in normalized_plan and "文档" not in normalized_plan:
        evidence_order = ["datasets", "documents"]

    return _merge_unique(base_order, evidence_order)


def build_static_generation_directives(
    *,
    analysis_plan: str,
    analysis_brief: Mapping[str, Any],
    compiled_knowledge: Mapping[str, Any],
    skill_strategy_hints: list[dict[str, Any]],
) -> StaticGenerationDirectives:
    rule_specs = [dict(item) for item in compiled_knowledge.get("rule_specs", []) or [] if isinstance(item, Mapping)]
    metric_specs = [dict(item) for item in compiled_knowledge.get("metric_specs", []) or [] if isinstance(item, Mapping)]
    filter_specs = [dict(item) for item in compiled_knowledge.get("filter_specs", []) or [] if isinstance(item, Mapping)]

    business_rules = [str(item).strip() for item in analysis_brief.get("business_rules", []) or [] if str(item).strip()]
    business_metrics = [str(item).strip() for item in analysis_brief.get("business_metrics", []) or [] if str(item).strip()]
    business_filters = [str(item).strip() for item in analysis_brief.get("business_filters", []) or [] if str(item).strip()]

    emit_rule_checks = bool(rule_specs or business_rules)
    emit_metric_checks = bool(metric_specs or business_metrics)
    emit_filter_checks = bool(filter_specs or business_filters)

    skill_focus_hints = _normalize_skill_focus_hints(skill_strategy_hints)
    prefer_document_evidence = any("优先复用已有知识检索证据" in hint for hint in skill_focus_hints)
    prefer_dataset_evidence = not prefer_document_evidence

    preferred_measure_terms = _merge_unique(
        _collect_terms_from_specs(metric_specs, ("measure_terms",)),
        [str(spec.get("metric_name", "")) for spec in metric_specs],
        business_metrics,
    )
    preferred_group_terms = _merge_unique(
        _collect_terms_from_specs(metric_specs, ("group_terms",)),
        business_metrics,
    )
    preferred_date_terms = _merge_unique(
        _collect_terms_from_specs(metric_specs, ("preferred_date_terms",)),
        _collect_terms_from_specs(filter_specs, ("preferred_date_terms",)),
        business_filters,
        business_metrics,
    )

    focus_order = _derive_focus_order(
        emit_rule_checks=emit_rule_checks,
        emit_metric_checks=emit_metric_checks,
        emit_filter_checks=emit_filter_checks,
        prefer_document_evidence=prefer_document_evidence,
        prefer_dataset_evidence=prefer_dataset_evidence,
        analysis_plan=analysis_plan,
    )

    return StaticGenerationDirectives(
        focus_order=focus_order,
        preferred_measure_terms=preferred_measure_terms,
        preferred_group_terms=preferred_group_terms,
        preferred_date_terms=preferred_date_terms,
        prefer_document_evidence=prefer_document_evidence,
        prefer_dataset_evidence=prefer_dataset_evidence,
        emit_rule_checks=emit_rule_checks,
        emit_metric_checks=emit_metric_checks,
        emit_filter_checks=emit_filter_checks,
        skill_focus_hints=skill_focus_hints,
    )


def _resolve_analysis_brief_payload(exec_data: Any, state: Mapping[str, Any]) -> dict[str, Any]:
    state_payload = state.get("analysis_brief")
    if isinstance(state_payload, Mapping):
        return dict(state_payload)
    persisted = getattr(exec_data.knowledge, "analysis_brief", None)
    if persisted and getattr(persisted, "question", ""):
        return persisted.model_dump(mode="json")
    if persisted and hasattr(persisted, "model_dump"):
        return persisted.model_dump(mode="json")
    return {}


def build_static_codegen_payload(*, exec_data: Any, state: Mapping[str, Any], input_mounts: list[dict[str, Any]], approved_skills: list[dict[str, Any]]) -> dict[str, Any]:
    analysis_brief = _resolve_analysis_brief_payload(exec_data, state)
    approved_skill_payloads = [
        skill.model_dump(mode="json", by_alias=True) if hasattr(skill, "model_dump") else dict(skill)
        for skill in approved_skills
    ]
    skill_strategy_hints = build_skill_strategy_hints(approved_skill_payloads)
    analysis_plan = (
        getattr(exec_data.static.execution_strategy, 'summary', None)
        if getattr(exec_data.static, "execution_strategy", None) is not None
        else ""
    )
    directives = build_static_generation_directives(
        analysis_plan=analysis_plan or "",
        analysis_brief=analysis_brief,
        compiled_knowledge=exec_data.knowledge.compiled.model_dump(mode="json"),
        skill_strategy_hints=skill_strategy_hints,
    )
    payload = StaticCodegenPayload(
        query=state["input_query"],
        analysis_plan=analysis_plan or "",
        analysis_mode=str(analysis_brief.get("analysis_mode") or ""),
        research_mode=str(

                exec_data.static.execution_strategy.research_mode
                if getattr(exec_data.static, "execution_strategy", None) is not None
                else state.get("research_mode")
                or "none"

        ),
        analysis_brief=analysis_brief,
        business_context=exec_data.knowledge.business_context.model_dump(mode="json"),
        compiled_knowledge=exec_data.knowledge.compiled.model_dump(mode="json"),
        approved_skills=[
            {
                "name": skill_payload.get("name"),
                "required_capabilities": skill_payload.get("required_capabilities", []),
                "promotion": skill_payload.get("promotion", {}),
                "replay_cases": skill_payload.get("replay_cases", []),
            }
            for skill_payload in approved_skill_payloads
        ],
        skill_strategy_hints=skill_strategy_hints,
        refined_context_excerpt=serialize_preview(str(state.get("refined_context", "") or ""), limit=400),
        input_mounts=input_mounts,
        execution_strategy=(
            exec_data.static.execution_strategy.model_dump(mode="json")
            if getattr(exec_data.static, "execution_strategy", None) is not None
            else {}
        ),
        static_evidence_bundle=(
            exec_data.static.static_evidence_bundle.model_dump(mode="json")
            if getattr(exec_data.static, "static_evidence_bundle", None) is not None
            else {}
        ),
        structured_dataset_summaries=[
            {
                "file_name": item.file_name,
                "schema": serialize_preview(str(item.dataset_schema), limit=240),
                "load_kwargs": item.load_kwargs,
            }
            for item in exec_data.inputs.structured_datasets
        ],
        generation_directives=directives.to_payload(),
    )
    return payload.to_payload()


def prepare_static_codegen_payload(*, exec_data: Any, state: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    query = str(state.get("input_query", ""))
    task_envelope = getattr(exec_data.control, "task_envelope", None)
    available_capabilities = list(task_envelope.allowed_tools) if task_envelope else []

    recall_result = MemoryService.recall_skills(
        tenant_id=exec_data.tenant_id,
        task_id=exec_data.task_id,
        workspace_id=exec_data.workspace_id,
        query=query,
        stage="coder",
        available_capabilities=available_capabilities,
        match_reason_detail="coder incorporated historical skills into the code-generation payload",
    )
    memory_data = MemoryService.mark_matches_used_in_codegen(
        memory_data=recall_result.memory_data,
        query=query,
        merged_skills=recall_result.merged_skills,
    )

    input_mounts = build_static_input_mounts(exec_data, extra_mounts=list(state.get("input_mounts") or []))
    payload = build_static_codegen_payload(
        exec_data=exec_data,
        state=state,
        input_mounts=input_mounts,
        approved_skills=list(memory_data.approved_skills or []),
    )
    return payload, input_mounts


def ensure_static_codegen_payload(payload: Mapping[str, Any] | StaticCodegenPayload) -> dict[str, Any]:
    if isinstance(payload, StaticCodegenPayload):
        payload_dict = payload.to_payload()
    else:
        payload_dict = dict(payload)

    if payload_dict.get("generation_directives"):
        return payload_dict

    directives = build_static_generation_directives(
        analysis_plan=str(payload_dict.get("analysis_plan") or ""),
        analysis_brief=dict(payload_dict.get("analysis_brief") or {}),
        compiled_knowledge=dict(payload_dict.get("compiled_knowledge") or {}),
        skill_strategy_hints=list(payload_dict.get("skill_strategy_hints") or []),
    )
    payload_dict["generation_directives"] = directives.to_payload()
    return payload_dict
