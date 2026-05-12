"""Dynamic exploration supervision — governance, context assembly, plan preparation.

Replaces the old supervisor.py + blackboard_context.py.  Stripped of all
DeerFlow-specific serialization (no DynamicContextEnvelope, no DeerflowTaskRequest).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.common import ExecutionIntent, TaskEnvelope
from src.common.control_plane import (
    decision_log_records,
    ensure_execution_intent,
    ensure_task_envelope,
)
from src.harness import GovernanceDecision, HarnessGovernor
from src.harness.policy import load_harness_policy
from src.memory import MemoryService


@dataclass(frozen=True)
class DynamicPlan:
    """Prepared control-plane bundle for one dynamic exploration run."""

    task_envelope: TaskEnvelope
    execution_intent: ExecutionIntent
    governance_decision: GovernanceDecision
    context: dict[str, Any] | None

    def denied_patch(self) -> dict[str, Any]:
        patch = dict(self.governance_decision.to_patch())
        patch.update({
            "dynamic_status": "denied",
            "dynamic_summary": "Dynamic exploration denied by governance policy.",
            "dynamic_continuation": "finish",
            "dynamic_next_static_steps": [],
            "dynamic_trace_refs": [f"governance:dynamic:{self.task_envelope.task_id}"],
            "task_envelope": self.task_envelope,
            "execution_intent": self.execution_intent,
        })
        return patch


class DynamicSupervisor:
    """Prepare a bounded dynamic exploration run owned by the DAG."""

    @staticmethod
    def ensure_execution_intent(
        state: Mapping[str, Any],
        execution_state: Mapping[str, Any],
    ) -> ExecutionIntent:
        execution_intent = state.get("execution_intent") or execution_state.get("execution_intent")
        return ensure_execution_intent(
            execution_intent,
            routing_mode="dynamic",
            destinations=["dynamic"],
            reason=str(state.get("dynamic_reason") or "dynamic node selected"),
        )

    @staticmethod
    def build_task_envelope(state: Mapping[str, Any]) -> TaskEnvelope:
        policy = load_harness_policy()
        return ensure_task_envelope(
            state.get("task_envelope"),
            task_id=str(state.get("task_id", "")),
            tenant_id=str(state.get("tenant_id", "")),
            workspace_id=str(state.get("workspace_id", "default_ws")),
            input_query=str(state.get("input_query", "")),
            governance_profile=str(state.get("governance_profile") or "researcher"),
            allowed_tools=list(state.get("allowed_tools") or []),
            redaction_rules=list(state.get("redaction_rules") or policy.get("redaction_rules") or []),
            token_budget=state.get("token_budget"),
            max_dynamic_steps=int(
                state.get("max_dynamic_steps") or (policy.get("dynamic", {}) or {}).get("max_steps", 6)
            ),
            metadata={
                "routing_mode": state.get("routing_mode", "dynamic"),
                "runtime_backend": "native",
            },
        )

    @staticmethod
    def build_context(
        state: Mapping[str, Any],
        execution_state: Mapping[str, Any],
        *,
        task_envelope: TaskEnvelope,
        governance_decision: GovernanceDecision,
    ) -> dict[str, Any]:
        """Build the context dict passed into the native exploration loop.

        No DeerFlow-specific serialization — context is a plain dict consumed
        in-process by exploration_loop.py.
        """
        persisted_knowledge = execution_state.get("knowledge_snapshot")
        current_knowledge = state.get("knowledge_snapshot")
        memory_snapshot = MemoryService.get_task_memory(
            tenant_id=str(task_envelope.tenant_id),
            task_id=str(task_envelope.task_id),
            workspace_id=str(task_envelope.workspace_id),
        ).model_dump(mode="json")

        base_decision_log = decision_log_records(
            execution_state.get("decision_log") or state.get("decision_log")
        )

        return {
            "tenant_id": task_envelope.tenant_id,
            "task_id": task_envelope.task_id,
            "workspace_id": task_envelope.workspace_id,
            "input_query": task_envelope.input_query,
            "knowledge_snapshot": dict(persisted_knowledge or current_knowledge or {}),
            "memory_snapshot": memory_snapshot,
            "allowed_tools": list(governance_decision.allowed_tools),
            "governance_profile": governance_decision.profile,
            "decision_log": [*base_decision_log, governance_decision.to_record()],
            "routing_mode": "dynamic",
            "runtime_backend": "native",
            "token_budget": task_envelope.token_budget,
            "max_dynamic_steps": task_envelope.max_dynamic_steps,
        }

    @staticmethod
    def prepare(
        state: Mapping[str, Any],
        execution_state: Mapping[str, Any],
    ) -> DynamicPlan:
        """Prepare the dynamic exploration plan.

        Returns a DynamicPlan.  If governance denies the request, the plan
        will have context=None and governance_decision.allowed=False.
        """
        merged = {**dict(execution_state), **dict(state)}
        merged["task_envelope"] = execution_state.get("task_envelope") or state.get("task_envelope")

        task_envelope = DynamicSupervisor.build_task_envelope(merged)
        execution_intent = DynamicSupervisor.ensure_execution_intent(state, execution_state)

        governance_decision = HarnessGovernor.evaluate_dynamic_request(
            query=task_envelope.input_query,
            requested_tools=task_envelope.allowed_tools,
            profile_name=task_envelope.governance_profile,
            max_steps=task_envelope.max_dynamic_steps,
            trace_ref=f"governance:dynamic:{task_envelope.task_id}",
        )

        if not governance_decision.allowed:
            return DynamicPlan(
                task_envelope=task_envelope,
                execution_intent=execution_intent,
                governance_decision=governance_decision,
                context=None,
            )

        context = DynamicSupervisor.build_context(
            state,
            execution_state,
            task_envelope=task_envelope,
            governance_decision=governance_decision,
        )

        return DynamicPlan(
            task_envelope=task_envelope,
            execution_intent=execution_intent,
            governance_decision=governance_decision,
            context=context,
        )
