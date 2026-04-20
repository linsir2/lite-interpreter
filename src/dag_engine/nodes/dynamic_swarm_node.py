"""Dynamic swarm super-node scaffold.

This node is intentionally kept as a thin adapter: the deterministic DAG stays
in charge of routing and lifecycle management, while DeerFlow handles bounded
sub-agent exploration behind a stable interface.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.blackboard.task_state_services import ExecutionStateService
from src.common import EventTopic, event_bus
from src.common.task_lease_runtime import ensure_task_lease_owned
from src.dynamic_engine.deerflow_bridge import DeerflowBridge, DeerflowRuntimeConfig
from src.dynamic_engine.supervisor import DynamicSupervisor
from src.dynamic_engine.trace_normalizer import TraceNormalizer


@dataclass(frozen=True)
class DynamicNodeContext:
    """Execution context resolved from node state and persisted execution data."""

    tenant_id: str
    task_id: str
    workspace_id: str
    lease_owner_id: str
    execution_state: dict[str, Any]


def _load_dynamic_node_context(state: Mapping[str, Any]) -> DynamicNodeContext:
    tenant_id = str(state.get("tenant_id", ""))
    task_id = str(state.get("task_id", ""))
    workspace_id = str(state.get("workspace_id", "default_ws"))
    lease_owner_id = str(state.get("lease_owner_id", "")).strip()
    execution_state = ExecutionStateService.load(tenant_id, task_id).model_dump(mode="json")
    return DynamicNodeContext(
        tenant_id=tenant_id,
        task_id=task_id,
        workspace_id=workspace_id,
        lease_owner_id=lease_owner_id,
        execution_state=execution_state,
    )


def _ensure_active_lease(task_id: str, lease_owner_id: str) -> None:
    ensure_task_lease_owned(task_id, lease_owner_id)


def _publish_governance_event(context: DynamicNodeContext, decision_payload: dict[str, Any]) -> None:
    _ensure_active_lease(context.task_id, context.lease_owner_id)
    event_bus.publish(
        topic=EventTopic.UI_TASK_GOVERNANCE_UPDATE,
        tenant_id=context.tenant_id,
        task_id=context.task_id,
        workspace_id=context.workspace_id,
        payload={
            "source": "dynamic_swarm",
            "decision": decision_payload,
        },
        trace_id=context.task_id,
    )

def _make_forward_event(context: DynamicNodeContext, forwarded_events: list[dict[str, Any]]):
    def forward_event(event: dict[str, Any]) -> None:
        _ensure_active_lease(context.task_id, context.lease_owner_id)
        normalized_event = TraceNormalizer.normalize_runtime_event(
            event,
            source=str(event.get("source") or "dynamic_swarm"),
        )
        forwarded_events.append(normalized_event)
        ExecutionStateService.append_dynamic_trace_event(
            tenant_id=context.tenant_id,
            task_id=context.task_id,
            event=normalized_event,
        )
        event_bus.publish(
            topic=EventTopic.UI_TASK_TRACE_UPDATE,
            tenant_id=context.tenant_id,
            task_id=context.task_id,
            workspace_id=context.workspace_id,
            payload={
                "source": "dynamic_swarm",
                "event": normalized_event,
            },
            trace_id=context.task_id,
        )

    return forward_event


def _build_dynamic_patch(result_patch: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": result_patch.get("dynamic_status"),
        "summary": result_patch.get("dynamic_summary"),
        "continuation": result_patch.get("dynamic_continuation") or "finish",
        "next_static_steps": result_patch.get("dynamic_next_static_steps") or [],
        "runtime_metadata": result_patch.get("dynamic_runtime_metadata") or {},
        "trace": result_patch.get("dynamic_trace") or [],
        "trace_refs": result_patch.get("dynamic_trace_refs") or [],
        "artifacts": result_patch.get("dynamic_artifacts") or [],
        "research_findings": result_patch.get("dynamic_research_findings") or [],
        "evidence_refs": result_patch.get("dynamic_evidence_refs") or [],
        "open_questions": result_patch.get("dynamic_open_questions") or [],
        "suggested_static_actions": result_patch.get("dynamic_suggested_static_actions") or [],
        "recommended_static_skill": result_patch.get("recommended_static_skill"),
    }


def dynamic_swarm_node(state: Mapping[str, Any]) -> dict[str, Any]:
    """Execute the DeerFlow bridge and return a normalized state patch.

    When the local DeerFlow runtime is unavailable, the bridge degrades to a
    planning preview instead of failing the DAG outright.
    """

    context = _load_dynamic_node_context(state)
    plan = DynamicSupervisor.prepare(state, context.execution_state)

    decision_patch = plan.governance_decision.to_patch()
    _publish_governance_event(context, plan.governance_decision.to_record())
    ExecutionStateService.update_control(
        tenant_id=context.tenant_id,
        task_id=context.task_id,
        decision_log=decision_patch.get("decision_log") or [],
        governance_trace_ref=decision_patch.get("governance_trace_ref"),
        task_envelope=plan.task_envelope,
        execution_intent=plan.execution_intent,
    )
    if not plan.governance_decision.allowed:
        denied_patch = plan.denied_patch()
        ExecutionStateService.update_dynamic(
            tenant_id=context.tenant_id,
            task_id=context.task_id,
            status=denied_patch.get("dynamic_status"),
            summary=denied_patch.get("dynamic_summary"),
            continuation=denied_patch.get("dynamic_continuation"),
            next_static_steps=denied_patch.get("dynamic_next_static_steps") or [],
            trace_refs=denied_patch.get("dynamic_trace_refs") or [],
            runtime_metadata={"requested_runtime_mode": "sidecar", "effective_runtime_mode": "denied"},
        )
        return {
            **denied_patch,
            "task_envelope": plan.task_envelope.model_dump(mode="json"),
            "execution_intent": plan.execution_intent.model_dump(mode="json"),
        }
    bridge = DeerflowBridge(
        runtime_config=DeerflowRuntimeConfig(
            max_steps=int(plan.task_envelope.max_dynamic_steps or 6),
        ),
    )
    dynamic_request = bridge.build_payload(plan.request) if plan.request is not None else {}
    ExecutionStateService.update_dynamic(
        tenant_id=context.tenant_id,
        task_id=context.task_id,
        request=dynamic_request,
        runtime_backend="deerflow",
    )

    forwarded_events: list[dict[str, Any]] = []
    result = bridge.run(plan.request, on_event=_make_forward_event(context, forwarded_events))
    _ensure_active_lease(context.task_id, context.lease_owner_id)
    result_patch = result.to_state_patch()
    dynamic_patch = _build_dynamic_patch(result_patch)
    if forwarded_events:
        dynamic_patch.pop("trace", None)
    ExecutionStateService.update_dynamic(
        tenant_id=context.tenant_id,
        task_id=context.task_id,
        status=dynamic_patch.get("status"),
        summary=dynamic_patch.get("summary"),
        continuation=dynamic_patch.get("continuation"),
        next_static_steps=dynamic_patch.get("next_static_steps") or [],
        runtime_metadata=dynamic_patch.get("runtime_metadata"),
        trace=dynamic_patch.get("trace"),
        trace_refs=dynamic_patch.get("trace_refs"),
        artifacts=dynamic_patch.get("artifacts"),
        research_findings=dynamic_patch.get("research_findings"),
        evidence_refs=dynamic_patch.get("evidence_refs"),
        open_questions=dynamic_patch.get("open_questions"),
        suggested_static_actions=dynamic_patch.get("suggested_static_actions"),
        recommended_static_skill=dynamic_patch.get("recommended_static_skill"),
    )
    return {
        **decision_patch,
        "task_envelope": plan.task_envelope.model_dump(mode="json"),
        "execution_intent": plan.execution_intent.model_dump(mode="json"),
        "dynamic_request": dynamic_request,
        "runtime_backend": "deerflow",
        **result_patch,
    }
