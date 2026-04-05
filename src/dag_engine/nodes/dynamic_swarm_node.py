"""Dynamic swarm super-node scaffold.

This node is intentionally kept as a thin adapter: the deterministic DAG stays
in charge of routing and lifecycle management, while DeerFlow handles bounded
sub-agent exploration behind a stable interface.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

from src.blackboard.execution_blackboard import execution_blackboard
from src.common import EventTopic, event_bus
from src.dynamic_engine.runtime_gateway import RuntimeGateway
from src.dynamic_engine.supervisor import DynamicSupervisor
from src.dynamic_engine.trace_normalizer import TraceNormalizer
from src.mcp_gateway import default_mcp_client


def dynamic_swarm_node(state: Mapping[str, Any]) -> Dict[str, Any]:
    """Execute the DeerFlow bridge and return a normalized state patch.

    When the local DeerFlow runtime is unavailable, the bridge degrades to a
    planning preview instead of failing the DAG outright.
    """

    tenant_id = str(state.get("tenant_id", ""))
    task_id = str(state.get("task_id", ""))
    workspace_id = str(state.get("workspace_id", "default_ws"))
    execution_data = execution_blackboard.read(tenant_id, task_id)
    execution_state = state.get("execution_snapshot") or (
        execution_data.model_dump() if execution_data else {}
    )
    plan = DynamicSupervisor.prepare(state, execution_state)

    def publish_governance_event(decision_payload: Dict[str, Any]) -> None:
        event_bus.publish(
            topic=EventTopic.UI_TASK_GOVERNANCE_UPDATE,
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id=workspace_id,
            payload={
                "source": "dynamic_swarm",
                "decision": decision_payload,
            },
            trace_id=task_id,
        )

    decision_patch = plan.governance_decision.to_patch()
    publish_governance_event(decision_patch["governance_decisions"][0])
    if not plan.governance_decision.allowed:
        denied_patch = plan.denied_patch()
        default_mcp_client.call_tool(
            "state_sync",
            {"patch": denied_patch},
            context={"tenant_id": tenant_id, "task_id": task_id},
        )
        return {
            "routing_mode": "dynamic",
            **denied_patch,
            "task_envelope": plan.task_envelope.model_dump(mode="json"),
            "execution_intent": plan.execution_intent.model_dump(mode="json"),
            "return_to_node": state.get("return_to_node", "analyst"),
        }
    gateway = RuntimeGateway(
        max_steps=int(state.get("max_dynamic_steps", 6)),
        backend_name=str(plan.task_envelope.metadata.get("runtime_backend") or "deerflow"),
    )

    default_mcp_client.call_tool(
        "state_sync",
        {
            "patch": {
                "routing_mode": "dynamic",
                **decision_patch,
                "task_envelope": plan.task_envelope,
                "execution_intent": plan.execution_intent,
                "dynamic_request": gateway.build_payload(plan),
                "runtime_backend": gateway.backend_name,
                "return_to_node": state.get("return_to_node", "analyst"),
            }
        },
        context={"tenant_id": tenant_id, "task_id": task_id},
    )

    def forward_event(event: Dict[str, Any]) -> None:
        normalized_event = TraceNormalizer.normalize_runtime_event(event)
        default_mcp_client.call_tool(
            "dynamic_trace",
            {"event": normalized_event},
            context={"tenant_id": tenant_id, "task_id": task_id},
        )
        event_bus.publish(
            topic=EventTopic.UI_TASK_TRACE_UPDATE,
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id=workspace_id,
            payload={
                "source": "dynamic_swarm",
                "event": normalized_event,
            },
            trace_id=task_id,
        )

    result = gateway.run(plan, on_event=forward_event)
    default_mcp_client.call_tool(
        "state_sync",
        {"patch": result.to_state_patch()},
        context={"tenant_id": tenant_id, "task_id": task_id},
    )
    return {
        "routing_mode": "dynamic",
        **decision_patch,
        "task_envelope": plan.task_envelope.model_dump(mode="json"),
        "execution_intent": plan.execution_intent.model_dump(mode="json"),
        "dynamic_request": gateway.build_payload(plan),
        "runtime_backend": gateway.backend_name,
        **result.to_state_patch(),
        "return_to_node": state.get("return_to_node", "analyst"),
    }
