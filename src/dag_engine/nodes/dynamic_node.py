"""Dynamic exploration DAG node — native LLM tool-calling loop.

Replaces dynamic_node.py.  The DAG owns the task lifecycle; this node
runs the native exploration loop via the MCP gateway and writes results back
through ExecutionStateService.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.blackboard.task_state_services import ExecutionStateService
from src.common import EventTopic, event_bus
from src.common.control_plane import ensure_dynamic_resume_overlay
from src.common.task_lease_runtime import ensure_task_lease_owned
from src.dynamic_engine.dynamic_supervisor import DynamicSupervisor
from src.dynamic_engine.exploration_loop import run_exploration_loop
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
            "source": "dynamic",
            "decision": decision_payload,
        },
        trace_id=context.task_id,
    )


def _make_forward_event(
    context: DynamicNodeContext,
    forwarded_events: list[dict[str, Any]],
):
    def forward_event(event: dict[str, Any]) -> None:
        _ensure_active_lease(context.task_id, context.lease_owner_id)
        normalized_event = TraceNormalizer.normalize_runtime_event(
            event,
            source=str(event.get("source") or "dynamic"),
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
                "source": "dynamic",
                "event": normalized_event,
            },
            trace_id=context.task_id,
        )

    return forward_event


def _build_dynamic_patch(result_patch: dict[str, Any]) -> dict[str, Any]:
    resume_overlay = ensure_dynamic_resume_overlay(result_patch.get("dynamic_resume_overlay") or {})
    return {
        "status": result_patch.get("dynamic_status"),
        "summary": result_patch.get("dynamic_summary"),
        "continuation": resume_overlay.continuation,
        "resume_overlay": resume_overlay.model_dump(mode="json"),
        "next_static_steps": list(resume_overlay.next_static_steps),
        "runtime_metadata": result_patch.get("dynamic_runtime_metadata") or {},
        "trace": result_patch.get("dynamic_trace") or [],
        "trace_refs": result_patch.get("dynamic_trace_refs") or [],
        "artifacts": result_patch.get("dynamic_artifacts") or [],
        "recommended_static_skill": result_patch.get("recommended_static_skill"),
    }


def dynamic_node(state: Mapping[str, Any]) -> dict[str, Any]:
    """Run the native exploration loop and return a normalized state patch.

    Replaces the DeerFlow sidecar call with an in-process LLM tool-calling
    loop that consumes MCP gateway tools directly.
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
            resume_overlay=ensure_dynamic_resume_overlay({
                "continuation": denied_patch.get("dynamic_continuation") or "finish",
                "next_static_steps": denied_patch.get("dynamic_next_static_steps") or [],
            }).model_dump(mode="json"),
            next_static_steps=denied_patch.get("dynamic_next_static_steps") or [],
            trace_refs=denied_patch.get("dynamic_trace_refs") or [],
            runtime_metadata={"effective_runtime_mode": "denied", "requested_runtime_mode": "native"},
        )
        return {
            **denied_patch,
            "task_envelope": plan.task_envelope.model_dump(mode="json"),
            "execution_intent": plan.execution_intent.model_dump(mode="json"),
        }

    # Resolve continuation from execution intent
    continuation_default = (
        "resume_static"
        if plan.execution_intent.intent == "dynamic_then_static_flow"
        else "finish"
    )

    forwarded_events: list[dict[str, Any]] = []
    result = run_exploration_loop(
        query=plan.task_envelope.input_query,
        context=plan.context or {},
        allowed_tools=plan.governance_decision.allowed_tools,
        max_steps=plan.task_envelope.max_dynamic_steps or 6,
        continuation_default=continuation_default,
        on_event=_make_forward_event(context, forwarded_events),
    )

    result_patch = result.to_state_patch()
    dynamic_patch = _build_dynamic_patch(result_patch)

    _ensure_active_lease(context.task_id, context.lease_owner_id)

    if forwarded_events:
        dynamic_patch.pop("trace", None)

    ExecutionStateService.update_dynamic(
        tenant_id=context.tenant_id,
        task_id=context.task_id,
        runtime_backend="native",
        status=dynamic_patch.get("status"),
        summary=dynamic_patch.get("summary"),
        continuation=dynamic_patch.get("continuation"),
        resume_overlay=dynamic_patch.get("resume_overlay"),
        next_static_steps=dynamic_patch.get("next_static_steps") or [],
        runtime_metadata=dynamic_patch.get("runtime_metadata"),
        trace=dynamic_patch.get("trace"),
        trace_refs=dynamic_patch.get("trace_refs"),
        artifacts=dynamic_patch.get("artifacts"),
        recommended_static_skill=dynamic_patch.get("recommended_static_skill"),
    )

    return {
        **decision_patch,
        "task_envelope": plan.task_envelope.model_dump(mode="json"),
        "execution_intent": plan.execution_intent.model_dump(mode="json"),
        "dynamic_request": {"runtime": {"runtime_mode": "native"}},
        "runtime_backend": "native",
        **result_patch,
        "dynamic_resume_overlay": dynamic_patch.get("resume_overlay"),
    }
