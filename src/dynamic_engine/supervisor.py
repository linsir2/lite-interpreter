"""Dynamic runtime supervision helpers.

This module keeps the DAG in charge while isolating the decisions required to
prepare a bounded dynamic run.
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
    execution_intent_dynamic_reason,
)
from src.dynamic_engine.blackboard_context import DynamicContextEnvelope, build_dynamic_context
from src.dynamic_engine.deerflow_bridge import DeerflowTaskRequest
from src.harness import GovernanceDecision, HarnessGovernor
from src.harness.policy import load_harness_policy
from src.memory import MemoryService
from src.runtime import resolve_runtime_decision


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
        execution_intent = state.get("execution_intent") or execution_state.get("execution_intent")
        return ensure_execution_intent(
            execution_intent,
            routing_mode="dynamic",
            destinations=["dynamic_swarm"],
            reason=str(state.get("dynamic_reason") or "dynamic super-node selected"),
            complexity_score=float(state.get("complexity_score") or 0.0),
            candidate_skills=list(state.get("candidate_skills") or []),
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
                "runtime_backend": str(state.get("runtime_backend") or "deerflow"),
            },
        )

    @staticmethod
    def build_authoritative_context_state(
        state: Mapping[str, Any],
        execution_state: Mapping[str, Any],
        *,
        task_envelope: TaskEnvelope,
        governance_decision: GovernanceDecision,
    ) -> dict[str, Any]:
        """
        构建动态链真正应该继承的上下文输入。

        设计原则：
        - `execution_state` 是持久化主状态，优先作为事实来源
        - `state` 只保留本轮 DAG 的瞬时补充信息
        - 当前这一步新增的 governance decision 要显式追加进去

        这样可以避免一种常见漂移：
        - dynamic 节点已经能读到最新 execution blackboard
        - 但真正注入 DeerFlow 的 knowledge / decision context 却还在读旧 state
        """

        persisted_knowledge_snapshot = execution_state.get("knowledge_snapshot")
        current_knowledge_snapshot = state.get("knowledge_snapshot")
        memory_snapshot = MemoryService.get_task_memory(
            tenant_id=str(task_envelope.tenant_id),
            task_id=str(task_envelope.task_id),
            workspace_id=str(task_envelope.workspace_id),
        ).model_dump(mode="json")
        base_decision_log = decision_log_records(execution_state.get("decision_log") or state.get("decision_log"))
        return {
            **dict(state),
            "task_envelope": task_envelope.model_dump(mode="json"),
            "execution_intent": execution_state.get("execution_intent") or state.get("execution_intent"),
            "knowledge_snapshot": dict(persisted_knowledge_snapshot or current_knowledge_snapshot or {}),
            "memory_snapshot": memory_snapshot,
            "allowed_tools": list(governance_decision.allowed_tools),
            "governance_profile": governance_decision.profile,
            "decision_log": [*base_decision_log, governance_decision.to_record()],
            "routing_mode": str(task_envelope.metadata.get("routing_mode") or state.get("routing_mode") or "dynamic"),
            "runtime_backend": str(
                task_envelope.metadata.get("runtime_backend") or state.get("runtime_backend") or "deerflow"
            ),
            "token_budget": task_envelope.token_budget,
            "max_dynamic_steps": task_envelope.max_dynamic_steps,
        }

    @staticmethod
    def prepare(
        state: Mapping[str, Any],
        execution_state: Mapping[str, Any],
    ) -> DynamicRunPlan:
        task_envelope = DynamicSupervisor.build_task_envelope(
            {
                **dict(execution_state),
                **dict(state),
                "task_envelope": execution_state.get("task_envelope") or state.get("task_envelope"),
            }
        )
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

        execution_metadata = dict(execution_intent.metadata or {})
        runtime_decision = resolve_runtime_decision(
            call_purpose="dynamic_research",
            query=task_envelope.input_query,
            state=state,
            exec_data=None,
            allowed_tools=governance_decision.allowed_tools,
        )
        analysis_mode = str(execution_metadata.get("analysis_mode") or runtime_decision.analysis_mode)
        evidence_strategy = str(execution_metadata.get("evidence_strategy") or runtime_decision.evidence_strategy)
        effective_model_alias = str(execution_metadata.get("effective_model_alias") or runtime_decision.model_alias)
        effective_tools = list(execution_metadata.get("effective_tools") or list(runtime_decision.effective_tools))
        context_state = DynamicSupervisor.build_authoritative_context_state(
            state,
            execution_state,
            task_envelope=task_envelope,
            governance_decision=governance_decision,
        )
        context_envelope = build_dynamic_context(
            context_state,
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
                "dynamic_reason": execution_intent_dynamic_reason(execution_intent),
                "governance_profile": governance_decision.profile,
                "analysis_mode": analysis_mode,
                "evidence_strategy": evidence_strategy,
                "effective_model_alias": effective_model_alias,
                "effective_tools": effective_tools,
            },
        )
        return DynamicRunPlan(
            task_envelope=task_envelope,
            execution_intent=execution_intent,
            governance_decision=governance_decision,
            context_envelope=context_envelope,
            request=request,
        )
