"""Helpers for injecting Blackboard constraints into dynamic agent runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

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
    redacted_query, query_report = mask_text(str(state.get("input_query", "")), rules)
    redacted_knowledge, knowledge_report = mask_payload(_safe_mapping(state.get("knowledge_snapshot")), rules)
    redacted_execution, execution_report = mask_payload(_safe_mapping(execution_state), rules)
    redaction_report = merge_redaction_reports(query_report, knowledge_report, execution_report)
    constraints = {
        "redaction_rules": rules,
        "allowed_tools": list(state.get("allowed_tools", [])),
        "governance_profile": state.get("governance_profile", "researcher"),
        "governance_decisions": list(state.get("governance_decisions", [])),
        "routing_mode": state.get("routing_mode", "dynamic"),
        "redaction_report": redaction_report,
        # Boundary contract:
        # - DeerFlow can use its own tool-mediated network stack for research
        # - Generated analysis code must still run inside lite-interpreter sandbox
        "network_boundary": {
            "platform_network_access": "tool-mediated-only",
            "sandbox_network_access": "disabled",
            "host_bash_access": "forbidden",
            "code_execution_owner": "lite_interpreter_sandbox",
        },
    }
    budget = {
        "token_budget": token_budget if token_budget is not None else state.get("token_budget"),
        "max_steps": state.get("max_dynamic_steps", 6),
    }
    return DynamicContextEnvelope(
        tenant_id=str(state.get("tenant_id", "")),
        task_id=str(state.get("task_id", "")),
        workspace_id=str(state.get("workspace_id", "")),
        input_query=redacted_query,
        constraints=constraints,
        knowledge_snapshot=redacted_knowledge,
        execution_snapshot=redacted_execution,
        budget=budget,
        writeback_channels=channels,
    )
