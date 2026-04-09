"""Dynamic swarm super-node scaffold.

This node is intentionally kept as a thin adapter: the deterministic DAG stays
in charge of routing and lifecycle management, while DeerFlow handles bounded
sub-agent exploration behind a stable interface.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.blackboard.execution_blackboard import execution_blackboard
from src.common import EventTopic, event_bus
from src.common.task_lease_runtime import ensure_task_lease_owned
from src.dynamic_engine.runtime_gateway import RuntimeGateway
from src.dynamic_engine.supervisor import DynamicSupervisor
from src.dynamic_engine.trace_normalizer import TraceNormalizer
from src.mcp_gateway import default_mcp_client


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
    execution_data = execution_blackboard.read(tenant_id, task_id)
    if execution_data is None and execution_blackboard.restore(tenant_id, task_id):
        execution_data = execution_blackboard.read(tenant_id, task_id)
    execution_state = (
        execution_data.model_dump(mode="json") if execution_data else dict(state.get("execution_snapshot") or {})
    )
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


def _sync_control_patch(context: DynamicNodeContext, patch: dict[str, Any]) -> None:
    _ensure_active_lease(context.task_id, context.lease_owner_id)
    default_mcp_client.call_tool(
        "state_sync",
        {"patch": patch},
        context={"tenant_id": context.tenant_id, "task_id": context.task_id},
    )


def _make_forward_event(context: DynamicNodeContext, forwarded_events: list[dict[str, Any]]):
    def forward_event(event: dict[str, Any]) -> None:
        _ensure_active_lease(context.task_id, context.lease_owner_id)
        normalized_event = TraceNormalizer.normalize_runtime_event(
            event,
            source=str(event.get("source") or "dynamic_swarm"),
        )
        forwarded_events.append(normalized_event)
        default_mcp_client.call_tool(
            "dynamic_trace",
            {"event": normalized_event},
            context={"tenant_id": context.tenant_id, "task_id": context.task_id},
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
        "runtime_metadata": result_patch.get("dynamic_runtime_metadata") or {},
        "trace": result_patch.get("dynamic_trace") or [],
        "trace_refs": result_patch.get("dynamic_trace_refs") or [],
        "artifacts": result_patch.get("dynamic_artifacts") or [],
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
    if not plan.governance_decision.allowed:
        denied_patch = plan.denied_patch()
        _sync_control_patch(
            context,
            {
                "control": {
                    "decision_log": denied_patch.get("decision_log") or [],
                    "governance_trace_ref": denied_patch.get("governance_trace_ref"),
                    "task_envelope": plan.task_envelope.model_dump(mode="json"),
                    "execution_intent": plan.execution_intent.model_dump(mode="json"),
                },
                "dynamic": {
                    "status": denied_patch.get("dynamic_status"),
                    "summary": denied_patch.get("dynamic_summary"),
                    "trace_refs": denied_patch.get("dynamic_trace_refs") or [],
                },
            },
        )
        return {
            **denied_patch,
            "task_envelope": plan.task_envelope.model_dump(mode="json"),
            "execution_intent": plan.execution_intent.model_dump(mode="json"),
        }
    gateway = RuntimeGateway(
        max_steps=int(plan.task_envelope.max_dynamic_steps or 6),
        backend_name=str(plan.task_envelope.metadata.get("runtime_backend") or "deerflow"),
    )
    dynamic_request = gateway.build_payload(plan)

    _sync_control_patch(
        context,
        {
            "control": {
                "decision_log": decision_patch.get("decision_log") or [],
                "governance_trace_ref": decision_patch.get("governance_trace_ref"),
                "task_envelope": plan.task_envelope.model_dump(mode="json"),
                "execution_intent": plan.execution_intent.model_dump(mode="json"),
            },
            "dynamic": {
                "request": dynamic_request,
                "runtime_backend": gateway.backend_name,
            },
        },
    )

    forwarded_events: list[dict[str, Any]] = []
    result = gateway.run(plan, on_event=_make_forward_event(context, forwarded_events))
    _ensure_active_lease(context.task_id, context.lease_owner_id)
    result_patch = result.to_state_patch()
    if forwarded_events:
        # 运行期事件已经通过 `dynamic_trace` 增量写回过一次。
        # 这里只保留状态摘要、引用和产物，避免同一批 trace 再整包回写一遍。
        result_patch.pop("dynamic_trace", None)
    _sync_control_patch(context, {"dynamic": _build_dynamic_patch(result_patch)})
    return {
        **decision_patch,
        "task_envelope": plan.task_envelope.model_dump(mode="json"),
        "execution_intent": plan.execution_intent.model_dump(mode="json"),
        "dynamic_request": dynamic_request,
        "runtime_backend": gateway.backend_name,
        **result_patch,
    }
