"""Canonical control-plane helpers for task and execution state."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from src.common.contracts import (
    ArtifactRecord,
    DecisionRecord,
    ExecutionIntent,
    ExecutionRecord,
    TaskEnvelope,
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
            intent = "dynamic_flow"
        elif len(destination_values) > 1:
            intent = "hybrid_flow"
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
        return "dynamic" if execution_intent.intent == "dynamic_flow" else "static"
    if isinstance(execution_intent, Mapping):
        return "dynamic" if _normalize_string(execution_intent.get("intent")) == "dynamic_flow" else "static"
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
        artifacts.append({"path": artifact_path, "type": artifact_type})
    return artifacts


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
