"""Canonical control-plane helpers for task and execution state."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, get_args

from config.settings import OUTPUT_DIR, UPLOAD_DIR

from src.common.contracts import (
    ArtifactEmitSpec,
    ArtifactPlan,
    ArtifactRecord,
    ArtifactVerificationResult,
    ComputationStep,
    DebugAttemptRecord,
    DebugHint,
    DecisionRecord,
    DynamicResumeOverlay,
    EvidencePlan,
    ExecutionIntent,
    ExecutionRecord,
    ExecutionStrategy,
    GeneratorManifest,
    RepairHint,
    ResearchMode,
    StaticEvidenceBundle,
    StaticEvidenceRecord,
    StaticEvidenceRequest,
    StaticProgramSpec,
    StaticRepairPlan,
    StrategyFamily,
    TaskEnvelope,
    VerificationPlan,
)


def _normalize_string(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _normalize_string_list(values: Iterable[Any] | None) -> list[str]:
    normalized: list[str] = []
    for item in values or []:
        text = str(item).strip()
        if text:
            normalized.append(text)
    return normalized


def _normalize_payload_list(values: Iterable[Any] | None) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for item in values or []:
        if isinstance(item, Mapping):
            payloads.append(dict(item))
    return payloads


_DYNAMIC_RESUME_STATIC_STEPS = {"analyst", "coder"}


def _normalize_resume_static_steps(values: Iterable[Any] | None) -> list[str]:
    return [item for item in _normalize_string_list(values) if item in _DYNAMIC_RESUME_STATIC_STEPS]


def ensure_task_envelope(
    value: Any = None,
    *,
    task_id: str,
    tenant_id: str,
    workspace_id: str = "default_ws",
    input_query: str = "",
    governance_profile: str = "researcher",
    allowed_tools: Iterable[Any] | None = None,
    redaction_rules: Iterable[Any] | None = None,
    token_budget: int | None = None,
    max_dynamic_steps: int | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> TaskEnvelope:
    if isinstance(value, TaskEnvelope):
        payload = value.model_dump(mode="json")
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        payload = {}
    payload.setdefault("task_id", task_id)
    payload.setdefault("tenant_id", tenant_id)
    payload.setdefault("workspace_id", workspace_id)
    payload.setdefault("input_query", input_query)
    payload.setdefault("governance_profile", governance_profile)
    payload["allowed_tools"] = _normalize_string_list(payload.get("allowed_tools") or allowed_tools)
    payload["redaction_rules"] = _normalize_string_list(payload.get("redaction_rules") or redaction_rules)
    if payload.get("token_budget") is None:
        payload["token_budget"] = token_budget
    if payload.get("max_dynamic_steps") is None:
        payload["max_dynamic_steps"] = max_dynamic_steps
    payload["metadata"] = dict(payload.get("metadata") or metadata or {})
    return TaskEnvelope.model_validate(payload)


def task_governance_profile(task_envelope: TaskEnvelope | Mapping[str, Any] | None, default: str = "researcher") -> str:
    if isinstance(task_envelope, TaskEnvelope):
        return _normalize_string(task_envelope.governance_profile, default)
    if isinstance(task_envelope, Mapping):
        return _normalize_string(task_envelope.get("governance_profile"), default)
    return default


def task_redaction_rules(task_envelope: TaskEnvelope | Mapping[str, Any] | None) -> list[str]:
    if isinstance(task_envelope, TaskEnvelope):
        return _normalize_string_list(task_envelope.redaction_rules)
    if isinstance(task_envelope, Mapping):
        return _normalize_string_list(task_envelope.get("redaction_rules"))
    return []


def task_allowed_tools(task_envelope: TaskEnvelope | Mapping[str, Any] | None) -> list[str]:
    if isinstance(task_envelope, TaskEnvelope):
        return _normalize_string_list(task_envelope.allowed_tools)
    if isinstance(task_envelope, Mapping):
        return _normalize_string_list(task_envelope.get("allowed_tools"))
    return []


def ensure_execution_intent(
    value: Any = None,
    *,
    routing_mode: str | None = None,
    destinations: Iterable[Any] | None = None,
    reason: str = "",
    complexity_score: float = 0.0,
    candidate_skills: Iterable[Any] | None = None,
    dynamic_reason: str | None = None,
) -> ExecutionIntent:
    if isinstance(value, ExecutionIntent):
        payload = value.model_dump(mode="json")
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        payload = {}
    destination_values = _normalize_string_list(payload.get("destinations") or destinations)
    intent = _normalize_string(payload.get("intent"))
    resolved_routing_mode = _normalize_string(routing_mode or payload.get("routing_mode"), "static")
    if not intent:
        if destination_values == ["dynamic_swarm"] or resolved_routing_mode == "dynamic":
            next_static_steps = _normalize_string_list((payload.get("metadata") or {}).get("next_static_steps"))
            intent = "dynamic_then_static_flow" if next_static_steps else "dynamic_only"
        else:
            intent = "static_flow"
    metadata = dict(payload.get("metadata") or {})
    if dynamic_reason and "dynamic_reason" not in metadata:
        metadata["dynamic_reason"] = dynamic_reason
    payload.update(
        {
            "intent": intent,
            "destinations": destination_values,
            "reason": _normalize_string(payload.get("reason"), reason),
            "complexity_score": float(payload.get("complexity_score", complexity_score) or 0.0),
            "candidate_skills": _normalize_payload_list(payload.get("candidate_skills") or candidate_skills),
            "metadata": metadata,
        }
    )
    return ExecutionIntent.model_validate(payload)


def ensure_dynamic_resume_overlay(
    value: Any = None,
    *,
    continuation: str = "finish",
    next_static_steps: Iterable[Any] | None = None,
    skip_static_steps: Iterable[Any] | None = None,
    evidence_refs: Iterable[Any] | None = None,
    suggested_static_actions: Iterable[Any] | None = None,
    recommended_static_action: str = "",
    open_questions: Iterable[Any] | None = None,
    strategy_family: str | None = None,
) -> DynamicResumeOverlay:
    if isinstance(value, DynamicResumeOverlay):
        payload = value.model_dump(mode="json")
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        payload = {}
    payload.setdefault("continuation", _normalize_string(payload.get("continuation"), continuation))
    payload["next_static_steps"] = _normalize_resume_static_steps(payload.get("next_static_steps") or next_static_steps)
    payload["skip_static_steps"] = _normalize_resume_static_steps(payload.get("skip_static_steps") or skip_static_steps)
    payload["evidence_refs"] = _normalize_string_list(payload.get("evidence_refs") or evidence_refs)
    payload["suggested_static_actions"] = _normalize_string_list(
        payload.get("suggested_static_actions") or suggested_static_actions
    )
    payload["recommended_static_action"] = _normalize_string(
        payload.get("recommended_static_action"),
        recommended_static_action,
    )
    if not payload["recommended_static_action"] and payload["suggested_static_actions"]:
        payload["recommended_static_action"] = payload["suggested_static_actions"][0]
    payload["open_questions"] = _normalize_string_list(payload.get("open_questions") or open_questions)
    normalized_strategy_family = _normalize_string(payload.get("strategy_family"), strategy_family or "")
    payload["strategy_family"] = (
        normalized_strategy_family
        if normalized_strategy_family in set(get_args(StrategyFamily))
        else None
    )
    return DynamicResumeOverlay.model_validate(payload)


def ensure_artifact_plan(
    value: Any = None,
    *,
    strategy_family: str = "legacy_dataset_aware_generator",
    output_root: str = "/app/outputs",
) -> ArtifactPlan:
    if isinstance(value, ArtifactPlan):
        payload = value.model_dump(mode="json")
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        payload = {}
    payload.setdefault("strategy_family", _normalize_string(payload.get("strategy_family"), strategy_family))
    payload.setdefault("output_root", _normalize_string(payload.get("output_root"), output_root))
    return ArtifactPlan.model_validate(payload)


def ensure_evidence_plan(
    value: Any = None,
    *,
    research_mode: ResearchMode = "none",
) -> EvidencePlan:
    if isinstance(value, EvidencePlan):
        payload = value.model_dump(mode="json")
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        payload = {}
    payload.setdefault("research_mode", _normalize_string(payload.get("research_mode"), research_mode))
    payload["search_queries"] = _normalize_string_list(payload.get("search_queries"))
    payload["urls"] = _normalize_string_list(payload.get("urls"))
    payload["allowed_domains"] = _normalize_string_list(payload.get("allowed_domains"))
    payload["allowed_capabilities"] = _normalize_string_list(payload.get("allowed_capabilities"))
    return EvidencePlan.model_validate(payload)


def ensure_static_evidence_request(
    value: Any = None,
    *,
    query: str = "",
    research_mode: ResearchMode = "none",
) -> StaticEvidenceRequest:
    if isinstance(value, StaticEvidenceRequest):
        payload = value.model_dump(mode="json")
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        payload = {}
    payload.setdefault("query", _normalize_string(payload.get("query"), query))
    payload.setdefault("research_mode", _normalize_string(payload.get("research_mode"), research_mode))
    payload["search_queries"] = _normalize_string_list(payload.get("search_queries"))
    payload["urls"] = _normalize_string_list(payload.get("urls"))
    payload["allowed_domains"] = _normalize_string_list(payload.get("allowed_domains"))
    payload["allowed_capabilities"] = _normalize_string_list(payload.get("allowed_capabilities"))
    return StaticEvidenceRequest.model_validate(payload)


def ensure_static_evidence_bundle(
    value: Any = None,
    *,
    request: StaticEvidenceRequest | Mapping[str, Any] | None = None,
) -> StaticEvidenceBundle:
    if isinstance(value, StaticEvidenceBundle):
        payload = value.model_dump(mode="json")
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        payload = {}
    payload["request"] = ensure_static_evidence_request(payload.get("request") or request).model_dump(mode="json")
    payload["records"] = [
        item.model_dump(mode="json") if isinstance(item, StaticEvidenceRecord) else dict(item)
        for item in payload.get("records", []) or []
        if isinstance(item, (StaticEvidenceRecord, Mapping))
    ]
    payload["errors"] = _normalize_string_list(payload.get("errors"))
    return StaticEvidenceBundle.model_validate(payload)


def ensure_verification_plan(
    value: Any = None,
    *,
    strategy_family: str = "legacy_dataset_aware_generator",
    required_artifact_keys: Iterable[Any] | None = None,
) -> VerificationPlan:
    if isinstance(value, VerificationPlan):
        payload = value.model_dump(mode="json")
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        payload = {}
    payload.setdefault("strategy_family", _normalize_string(payload.get("strategy_family"), strategy_family))
    payload["required_artifact_keys"] = _normalize_string_list(
        payload.get("required_artifact_keys") or required_artifact_keys
    )
    payload["prohibited_extensions"] = _normalize_string_list(payload.get("prohibited_extensions"))
    payload["allowed_output_roots"] = _normalize_string_list(payload.get("allowed_output_roots"))
    return VerificationPlan.model_validate(payload)


def ensure_static_program_spec(
    value: Any = None,
    *,
    spec_id: str = "",
    strategy_family: str = "legacy_dataset_aware_generator",
    analysis_mode: str = "",
    research_mode: ResearchMode = "none",
) -> StaticProgramSpec:
    if isinstance(value, StaticProgramSpec):
        payload = value.model_dump(mode="json")
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        payload = {}
    payload.setdefault("spec_id", _normalize_string(payload.get("spec_id"), spec_id))
    payload.setdefault("strategy_family", _normalize_string(payload.get("strategy_family"), strategy_family))
    payload.setdefault("analysis_mode", _normalize_string(payload.get("analysis_mode"), analysis_mode))
    payload.setdefault("research_mode", _normalize_string(payload.get("research_mode"), research_mode))
    payload["steps"] = [
        item.model_dump(mode="json") if isinstance(item, ComputationStep) else dict(item)
        for item in payload.get("steps", []) or []
        if isinstance(item, (ComputationStep, Mapping))
    ]
    payload["artifact_emits"] = [
        item.model_dump(mode="json") if isinstance(item, ArtifactEmitSpec) else dict(item)
        for item in payload.get("artifact_emits", []) or []
        if isinstance(item, (ArtifactEmitSpec, Mapping))
    ]
    payload["debug_hints"] = [
        item.model_dump(mode="json") if isinstance(item, DebugHint) else dict(item)
        for item in payload.get("debug_hints", []) or []
        if isinstance(item, (DebugHint, Mapping))
    ]
    if payload.get("evidence_bundle") is not None:
        payload["evidence_bundle"] = ensure_static_evidence_bundle(payload.get("evidence_bundle")).model_dump(mode="json")
    return StaticProgramSpec.model_validate(payload)


def ensure_static_repair_plan(
    value: Any = None,
    *,
    reason: str = "",
    attempt_index: int = 1,
) -> StaticRepairPlan:
    if isinstance(value, StaticRepairPlan):
        payload = value.model_dump(mode="json")
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        payload = {}
    payload.setdefault("reason", _normalize_string(payload.get("reason"), reason))
    payload.setdefault("attempt_index", int(payload.get("attempt_index", attempt_index) or attempt_index))
    payload.setdefault("updates", dict(payload.get("updates") or {}))
    return StaticRepairPlan.model_validate(payload)


def ensure_debug_attempt_record(
    value: Any = None,
    *,
    attempt_index: int = 1,
    reason: str = "",
) -> DebugAttemptRecord:
    if isinstance(value, DebugAttemptRecord):
        payload = value.model_dump(mode="json")
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        payload = {}
    payload.setdefault("attempt_index", int(payload.get("attempt_index", attempt_index) or attempt_index))
    payload.setdefault("reason", _normalize_string(payload.get("reason"), reason))
    if payload.get("repair_plan") is not None:
        payload["repair_plan"] = ensure_static_repair_plan(payload.get("repair_plan")).model_dump(mode="json")
    return DebugAttemptRecord.model_validate(payload)


def ensure_generator_manifest(
    value: Any = None,
    *,
    generator_id: str,
    strategy_family: str = "legacy_dataset_aware_generator",
    renderer_id: str = "dataset_aware_renderer",
    fallback_used: bool = False,
    expected_artifact_keys: Iterable[Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> GeneratorManifest:
    if isinstance(value, GeneratorManifest):
        payload = value.model_dump(mode="json")
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        payload = {}
    payload.setdefault("generator_id", _normalize_string(payload.get("generator_id"), generator_id))
    payload.setdefault("strategy_family", _normalize_string(payload.get("strategy_family"), strategy_family))
    payload.setdefault("renderer_id", _normalize_string(payload.get("renderer_id"), renderer_id))
    payload.setdefault("fallback_used", bool(payload.get("fallback_used", fallback_used)))
    payload["expected_artifact_keys"] = _normalize_string_list(
        payload.get("expected_artifact_keys") or expected_artifact_keys
    )
    payload["metadata"] = dict(payload.get("metadata") or metadata or {})
    return GeneratorManifest.model_validate(payload)


def ensure_execution_strategy(
    value: Any = None,
    *,
    analysis_mode: str = "",
    research_mode: ResearchMode = "none",
    strategy_family: str = "legacy_dataset_aware_generator",
    generator_id: str = "legacy_dataset_aware_generator",
    evidence_plan: EvidencePlan | Mapping[str, Any] | None = None,
    artifact_plan: ArtifactPlan | Mapping[str, Any] | None = None,
    verification_plan: VerificationPlan | Mapping[str, Any] | None = None,
    program_spec: StaticProgramSpec | Mapping[str, Any] | None = None,
    repair_plan: StaticRepairPlan | Mapping[str, Any] | None = None,
    resume_overlay: DynamicResumeOverlay | Mapping[str, Any] | None = None,
    legacy_compatibility: Mapping[str, Any] | None = None,
) -> ExecutionStrategy:
    if isinstance(value, ExecutionStrategy):
        payload = value.model_dump(mode="json")
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        payload = {}
    payload.setdefault("analysis_mode", _normalize_string(payload.get("analysis_mode"), analysis_mode))
    payload.setdefault("research_mode", _normalize_string(payload.get("research_mode"), research_mode))
    payload.setdefault("strategy_family", _normalize_string(payload.get("strategy_family"), strategy_family))
    payload.setdefault("generator_id", _normalize_string(payload.get("generator_id"), generator_id))
    payload["evidence_plan"] = ensure_evidence_plan(
        payload.get("evidence_plan") or evidence_plan,
        research_mode=str(payload.get("research_mode") or research_mode),
    ).model_dump(mode="json")
    payload["artifact_plan"] = ensure_artifact_plan(
        payload.get("artifact_plan") or artifact_plan,
        strategy_family=str(payload.get("strategy_family") or strategy_family),
    ).model_dump(mode="json")
    payload["verification_plan"] = ensure_verification_plan(
        payload.get("verification_plan") or verification_plan,
        strategy_family=str(payload.get("strategy_family") or strategy_family),
    ).model_dump(mode="json")
    if payload.get("program_spec") is not None or program_spec is not None:
        payload["program_spec"] = ensure_static_program_spec(
            payload.get("program_spec") or program_spec,
            spec_id=str((payload.get("program_spec") or {}).get("spec_id") or ""),
            strategy_family=str(payload.get("strategy_family") or strategy_family),
            analysis_mode=str(payload.get("analysis_mode") or analysis_mode),
            research_mode=str(payload.get("research_mode") or research_mode),
        ).model_dump(mode="json")
    if payload.get("repair_plan") is not None or repair_plan is not None:
        payload["repair_plan"] = ensure_static_repair_plan(
            payload.get("repair_plan") or repair_plan,
        ).model_dump(mode="json")
    if payload.get("resume_overlay") or resume_overlay is not None:
        payload["resume_overlay"] = ensure_dynamic_resume_overlay(
            payload.get("resume_overlay") or resume_overlay,
        ).model_dump(mode="json")
    payload["legacy_compatibility"] = dict(payload.get("legacy_compatibility") or legacy_compatibility or {})
    return ExecutionStrategy.model_validate(payload)


def ensure_artifact_verification_result(
    value: Any = None,
    *,
    strategy_family: str = "legacy_dataset_aware_generator",
    passed: bool = False,
) -> ArtifactVerificationResult:
    if isinstance(value, ArtifactVerificationResult):
        payload = value.model_dump(mode="json")
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        payload = {}
    payload.setdefault("strategy_family", _normalize_string(payload.get("strategy_family"), strategy_family))
    payload.setdefault("passed", bool(payload.get("passed", passed)))
    payload["verified_artifact_keys"] = _normalize_string_list(payload.get("verified_artifact_keys"))
    payload["missing_artifact_keys"] = _normalize_string_list(payload.get("missing_artifact_keys"))
    payload["unexpected_artifacts"] = _normalize_string_list(payload.get("unexpected_artifacts"))
    payload["failure_reasons"] = _normalize_string_list(payload.get("failure_reasons"))
    payload["debug_hints"] = [
        item.model_dump(mode="json") if isinstance(item, RepairHint) else dict(item)
        for item in payload.get("debug_hints", []) or []
        if isinstance(item, (RepairHint, Mapping))
    ]
    return ArtifactVerificationResult.model_validate(payload)


def execution_intent_destinations(execution_intent: ExecutionIntent | Mapping[str, Any] | None) -> list[str]:
    if isinstance(execution_intent, ExecutionIntent):
        return _normalize_string_list(execution_intent.destinations)
    if isinstance(execution_intent, Mapping):
        return _normalize_string_list(execution_intent.get("destinations"))
    return []


def execution_intent_reason(execution_intent: ExecutionIntent | Mapping[str, Any] | None) -> str:
    if isinstance(execution_intent, ExecutionIntent):
        return _normalize_string(execution_intent.reason)
    if isinstance(execution_intent, Mapping):
        return _normalize_string(execution_intent.get("reason"))
    return ""


def execution_intent_candidate_skills(
    execution_intent: ExecutionIntent | Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if isinstance(execution_intent, ExecutionIntent):
        return _normalize_payload_list(execution_intent.candidate_skills)
    if isinstance(execution_intent, Mapping):
        return _normalize_payload_list(execution_intent.get("candidate_skills"))
    return []


def execution_intent_dynamic_reason(execution_intent: ExecutionIntent | Mapping[str, Any] | None) -> str | None:
    metadata: Mapping[str, Any] | None = None
    if isinstance(execution_intent, ExecutionIntent):
        metadata = execution_intent.metadata
    elif isinstance(execution_intent, Mapping):
        metadata = execution_intent.get("metadata") if isinstance(execution_intent.get("metadata"), Mapping) else None
    if not metadata:
        return None
    value = _normalize_string(metadata.get("dynamic_reason"))
    return value or None


def execution_intent_routing_mode(execution_intent: ExecutionIntent | Mapping[str, Any] | None) -> str:
    if isinstance(execution_intent, ExecutionIntent):
        return "dynamic" if execution_intent.intent in {"dynamic_only", "dynamic_then_static_flow"} else "static"
    if isinstance(execution_intent, Mapping):
        return (
            "dynamic"
            if _normalize_string(execution_intent.get("intent")) in {"dynamic_only", "dynamic_then_static_flow"}
            else "static"
        )
    return "static"


def decision_log_records(
    decision_log: Sequence[Any] | None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in decision_log or []:
        if not isinstance(item, Mapping):
            continue
        try:
            records.append(DecisionRecord.model_validate(item).model_dump(mode="json"))
        except Exception:
            records.append(dict(item))
    return records


def decision_mode(decision_log: Sequence[Any] | None, default: str = "standard") -> str:
    records = decision_log_records(decision_log)
    if not records:
        return default
    return _normalize_string(records[-1].get("mode"), default)


def decision_allowed_tools(decision_log: Sequence[Any] | None) -> list[str]:
    records = decision_log_records(decision_log)
    allowed_tools: list[str] = []
    for record in records[-3:]:
        allowed_tools.extend(record.get("allowed_tools") or [])
    return _normalize_string_list(allowed_tools)


def knowledge_evidence_refs(knowledge_snapshot: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(knowledge_snapshot, Mapping):
        return []
    return _normalize_string_list(knowledge_snapshot.get("evidence_refs"))


def parser_reports_from_documents(business_documents: Sequence[Any] | None) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for item in business_documents or []:
        if isinstance(item, Mapping):
            parse_mode = _normalize_string(item.get("parse_mode"), "default")
            parser_diagnostics = dict(item.get("parser_diagnostics") or {})
            file_name = _normalize_string(item.get("file_name"))
        else:
            parse_mode = _normalize_string(getattr(item, "parse_mode", None), "default")
            parser_diagnostics = dict(getattr(item, "parser_diagnostics", {}) or {})
            file_name = _normalize_string(getattr(item, "file_name", None))
        if parse_mode == "default" and not parser_diagnostics:
            continue
        reports.append(
            {
                "file_name": file_name,
                "parse_mode": parse_mode,
                "parser_diagnostics": parser_diagnostics,
            }
        )
    return reports


def ensure_execution_record(
    value: Any = None,
    *,
    tenant_id: str,
    workspace_id: str,
    task_id: str | None = None,
) -> ExecutionRecord | None:
    if isinstance(value, ExecutionRecord):
        return value
    if isinstance(value, Mapping):
        return ExecutionRecord.model_validate(dict(value))
    return None


def execution_output(execution_record: ExecutionRecord | Mapping[str, Any] | None) -> str:
    if isinstance(execution_record, ExecutionRecord):
        return str(execution_record.output or "")
    if isinstance(execution_record, Mapping):
        return str(execution_record.get("output") or "")
    return ""


def execution_error(execution_record: ExecutionRecord | Mapping[str, Any] | None) -> str:
    if isinstance(execution_record, ExecutionRecord):
        return str(execution_record.error or "")
    if isinstance(execution_record, Mapping):
        return str(execution_record.get("error") or "")
    return ""


def execution_success(execution_record: ExecutionRecord | Mapping[str, Any] | None) -> bool:
    if isinstance(execution_record, ExecutionRecord):
        return bool(execution_record.success)
    if isinstance(execution_record, Mapping):
        return bool(execution_record.get("success"))
    return False


def static_artifacts(execution_record: ExecutionRecord | Mapping[str, Any] | None) -> list[dict[str, str]]:
    records: Sequence[Any]
    if isinstance(execution_record, ExecutionRecord):
        records = execution_record.artifacts
    elif isinstance(execution_record, Mapping):
        records = execution_record.get("artifacts", []) or []
    else:
        records = []
    artifacts: list[dict[str, str]] = []
    for item in records:
        if isinstance(item, ArtifactRecord):
            artifact_path = _normalize_string(item.path)
            artifact_type = _normalize_string(item.artifact_type, "artifact")
        elif isinstance(item, Mapping):
            artifact_path = _normalize_string(item.get("path"))
            artifact_type = _normalize_string(item.get("artifact_type") or item.get("type"), "artifact")
        else:
            continue
        if not artifact_path:
            continue
        artifacts.append({"path": sanitize_artifact_reference(artifact_path), "type": artifact_type})
    return artifacts


def artifact_category_from_path(path_value: str | None, artifact_type: str | None = None) -> str:
    explicit = _normalize_string(artifact_type)
    if explicit in {"report", "chart", "export", "diagnostic"}:
        return explicit
    suffix = Path(_normalize_string(path_value)).suffix.lower()
    if suffix in {".md", ".pdf"}:
        return "report"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        return "chart"
    if suffix in {".csv", ".json", ".tsv"}:
        return "export"
    return "diagnostic"


def sort_output_entries(outputs: Sequence[Any] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in outputs or []:
        if not isinstance(item, Mapping):
            continue
        normalized.append(dict(item))
    category_rank = {"report": 0, "chart": 1, "export": 2, "diagnostic": 3}

    def _sort_key(item: Mapping[str, Any]) -> tuple[int, str, str]:
        category = artifact_category_from_path(
            str(item.get("path") or ""),
            str(item.get("category") or item.get("type") or ""),
        )
        title = _normalize_string(item.get("name") or item.get("title") or item.get("path"))
        path = _normalize_string(item.get("path"))
        return category_rank.get(category, 9), title.lower(), path.lower()

    return sorted(normalized, key=_sort_key)


def sanitize_artifact_reference(value: str | None) -> str | None:
    text = _normalize_string(value)
    if not text:
        return None
    lowered = text.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return text
    path = Path(text)
    if not path.is_absolute():
        return text
    try:
        resolved = path.resolve(strict=False)
    except Exception:
        return None
    allowed_roots = [Path(OUTPUT_DIR).resolve(strict=False), Path(UPLOAD_DIR).resolve(strict=False)]
    for root in allowed_roots:
        if resolved == root or str(resolved).startswith(str(root) + "/"):
            return str(resolved)
    return None


def _merge_list_unique(current: list[Any], incoming: list[Any]) -> list[Any]:
    merged = list(current)
    for item in incoming:
        if item in merged:
            continue
        merged.append(item)
    return merged


def _merge_domain_value(current: Any, incoming: Any) -> Any:
    if incoming is None:
        return current
    if isinstance(current, Mapping) and isinstance(incoming, Mapping):
        merged = dict(current)
        for key, value in incoming.items():
            merged[key] = _merge_domain_value(merged.get(key), value)
        return merged
    if isinstance(current, list) and isinstance(incoming, list):
        return _merge_list_unique(current, incoming)
    return incoming


def merge_domain_patch(current: Mapping[str, Any], incoming: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    for key, value in incoming.items():
        merged[key] = _merge_domain_value(merged.get(key), value)
    return merged
