"""Dynamic runtime supervision helpers.

This module keeps the DAG in charge while isolating the decisions required to
prepare a bounded dynamic run.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from src.common import ExecutionIntent, TaskEnvelope
from src.dynamic_engine.blackboard_context import DynamicContextEnvelope, build_dynamic_context
from src.dynamic_engine.deerflow_bridge import DeerflowTaskRequest
from src.harness import GovernanceDecision, HarnessGovernor
from src.harness.policy import load_harness_policy


@dataclass(frozen=True)
class DynamicRunPlan:
    """Prepared control-plane bundle for one dynamic runtime call."""

    task_envelope: TaskEnvelope
    execution_intent: ExecutionIntent
    governance_decision: GovernanceDecision
    context_envelope: DynamicContextEnvelope | None
    request: DeerflowTaskRequest | None

    def denied_patch(self) -> dict[str, Any]:
        patch = dict(self.governance_decision.to_patch())
        patch.update(
            {
                "dynamic_status": "denied",
                "dynamic_summary": "Dynamic swarm request denied by harness governance policy.",
                "dynamic_trace_refs": [f"governance:dynamic:{self.task_envelope.task_id}"],
                "task_envelope": self.task_envelope,
                "execution_intent": self.execution_intent,
            }
        )
        return patch


class DynamicSupervisor:
    """Prepare the bounded dynamic run owned by the deterministic DAG."""

    @staticmethod
    def ensure_execution_intent(
        state: Mapping[str, Any],
        execution_state: Mapping[str, Any],
    ) -> ExecutionIntent:
        execution_intent = state.get("execution_intent")
        if execution_intent and isinstance(execution_intent, ExecutionIntent):
            return execution_intent
        if execution_intent:
            return ExecutionIntent.model_validate(execution_intent)
        return ExecutionIntent(
            intent="dynamic_flow",
            destinations=["dynamic_swarm"],
            reason=str(state.get("dynamic_reason") or execution_state.get("dynamic_reason") or "dynamic super-node selected"),
            complexity_score=float(state.get("complexity_score") or execution_state.get("complexity_score") or 0.0),
            candidate_skills=list(state.get("candidate_skills") or execution_state.get("candidate_skills") or []),
        )

    @staticmethod
    def build_task_envelope(state: Mapping[str, Any]) -> TaskEnvelope:
        policy = load_harness_policy()
        return TaskEnvelope(
            task_id=str(state.get("task_id", "")),
            tenant_id=str(state.get("tenant_id", "")),
            workspace_id=str(state.get("workspace_id", "default_ws")),
            input_query=str(state.get("input_query", "")),
            governance_profile=str(state.get("governance_profile") or "researcher"),
            allowed_tools=list(state.get("allowed_tools") or []),
            redaction_rules=list(state.get("redaction_rules") or policy.get("redaction_rules") or []),
            token_budget=state.get("token_budget"),
            max_dynamic_steps=int(state.get("max_dynamic_steps", 6)),
            metadata={
                "routing_mode": state.get("routing_mode", "dynamic"),
                "runtime_backend": str(state.get("runtime_backend") or "deerflow"),
            },
        )

    @staticmethod
    def prepare(
        state: Mapping[str, Any],
        execution_state: Mapping[str, Any],
    ) -> DynamicRunPlan:
        task_envelope = DynamicSupervisor.build_task_envelope(state)
        execution_intent = DynamicSupervisor.ensure_execution_intent(state, execution_state)
        governance_decision = HarnessGovernor.evaluate_dynamic_request(
            query=task_envelope.input_query,
            requested_tools=task_envelope.allowed_tools,
            profile_name=task_envelope.governance_profile,
            max_steps=task_envelope.max_dynamic_steps,
            trace_ref=f"governance:dynamic:{task_envelope.task_id}",
        )
        if not governance_decision.allowed:
            return DynamicRunPlan(
                task_envelope=task_envelope,
                execution_intent=execution_intent,
                governance_decision=governance_decision,
                context_envelope=None,
                request=None,
            )

        context_envelope = build_dynamic_context(
            {
                **dict(state),
                "allowed_tools": governance_decision.allowed_tools,
                "governance_profile": governance_decision.profile,
                "governance_decisions": [governance_decision.to_patch()["governance_decisions"][0]],
            },
            execution_state,
            token_budget=task_envelope.token_budget,
            redaction_rules=task_envelope.redaction_rules,
        )
        request = DeerflowTaskRequest(
            task_id=task_envelope.task_id,
            tenant_id=task_envelope.tenant_id,
            query=task_envelope.input_query,
            system_context=context_envelope.to_system_context(),
            metadata={
                "routing_mode": task_envelope.metadata.get("routing_mode", "dynamic"),
                "complexity_score": execution_intent.complexity_score,
                "dynamic_reason": state.get("dynamic_reason"),
                "governance_profile": governance_decision.profile,
            },
        )
        return DynamicRunPlan(
            task_envelope=task_envelope,
            execution_intent=execution_intent,
            governance_decision=governance_decision,
            context_envelope=context_envelope,
            request=request,
        )
