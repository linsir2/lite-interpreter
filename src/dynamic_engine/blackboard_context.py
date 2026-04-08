"""Helpers for injecting Blackboard constraints into dynamic agent runs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from src.common.control_plane import (
    execution_intent_routing_mode,
    task_allowed_tools,
    task_governance_profile,
)
from src.privacy import mask_payload, mask_text, merge_redaction_reports


@dataclass(frozen=True)
class DynamicContextEnvelope:
    """A compact, serializable view of the constraints for a dynamic run."""

    tenant_id: str
    task_id: str
    workspace_id: str
    input_query: str
    constraints: dict[str, Any] = field(default_factory=dict)
    knowledge_snapshot: dict[str, Any] = field(default_factory=dict)
    memory_snapshot: dict[str, Any] = field(default_factory=dict)
    execution_snapshot: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    writeback_channels: list[str] = field(default_factory=list)

    def to_system_context(self) -> dict[str, Any]:
        """Return a DeerFlow-friendly payload."""
        return asdict(self)


def _safe_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _task_max_dynamic_steps(task_envelope: Any, default: int = 6) -> int:
    if isinstance(task_envelope, Mapping):
        value = task_envelope.get("max_dynamic_steps")
    else:
        value = getattr(task_envelope, "max_dynamic_steps", None)
    try:
        return int(value or default)
    except Exception:
        return int(default)


def build_dynamic_context(
    state: Mapping[str, Any],
    execution_state: Mapping[str, Any] | None = None,
    *,
    token_budget: int | None = None,
    redaction_rules: Sequence[str] | None = None,
    writeback_channels: Sequence[str] | None = None,
) -> DynamicContextEnvelope:
    """Build the minimal context that a dynamic swarm must inherit.

    The function intentionally keeps the contract narrow so the DAG layer can
    inject safety and cost boundaries before delegating work to DeerFlow.
    """

    rules = list(redaction_rules or [])
    channels = list(writeback_channels or ["execution_blackboard", "dynamic_trace"])
    task_envelope = state.get("task_envelope")
    allowed_tools = task_allowed_tools(task_envelope) or list(state.get("allowed_tools", []))
    governance_profile = task_governance_profile(
        task_envelope,
        str(state.get("governance_profile", "researcher")),
    )
    redacted_query, query_report = mask_text(str(state.get("input_query", "")), rules)
    redacted_knowledge, knowledge_report = mask_payload(_safe_mapping(state.get("knowledge_snapshot")), rules)
    redacted_memory, memory_report = mask_payload(_safe_mapping(state.get("memory_snapshot")), rules)
    redacted_execution, execution_report = mask_payload(_safe_mapping(execution_state), rules)
    redaction_report = merge_redaction_reports(query_report, knowledge_report, memory_report, execution_report)
    decision_log = list(state.get("decision_log", []))
    latest_decision = decision_log[-1] if decision_log else {}
    decision_metadata = dict(latest_decision.get("metadata", {}) or {}) if isinstance(latest_decision, Mapping) else {}
    host_bash_access = str(decision_metadata.get("profile_host_bash_access") or "forbidden")
    profile_network_access = str(decision_metadata.get("profile_network_access") or "none")
    constraints = {
        "redaction_rules": rules,
        # 这里优先走 task_envelope / execution_intent 这样的规范契约，
        # 扁平 state 字段只作为兼容兜底。这样 dynamic context 的来源
        # 会更接近 blackboard 主状态，而不是依赖临时拼接出来的 graph state。
        "allowed_tools": allowed_tools,
        "governance_profile": governance_profile,
        "decision_log": decision_log,
        "routing_mode": state.get("routing_mode") or execution_intent_routing_mode(state.get("execution_intent")),
        "redaction_report": redaction_report,
        # Boundary contract:
        # - DeerFlow can use its own tool-mediated network stack for research
        # - Generated analysis code must still run inside lite-interpreter sandbox
        "network_boundary": {
            "platform_network_access": profile_network_access,
            "sandbox_network_access": "disabled",
            "host_bash_access": host_bash_access,
            "code_execution_owner": "lite_interpreter_sandbox",
        },
    }
    budget = {
        "token_budget": token_budget if token_budget is not None else state.get("token_budget"),
        "max_steps": _task_max_dynamic_steps(task_envelope, int(state.get("max_dynamic_steps", 6) or 6)),
    }
    return DynamicContextEnvelope(
        tenant_id=str(state.get("tenant_id", "")),
        task_id=str(state.get("task_id", "")),
        workspace_id=str(state.get("workspace_id", "")),
        input_query=redacted_query,
        constraints=constraints,
        knowledge_snapshot=redacted_knowledge,
        memory_snapshot=redacted_memory,
        execution_snapshot=redacted_execution,
        budget=budget,
        writeback_channels=channels,
    )
