"""Dynamic swarm super-node scaffold.

This node is intentionally kept as a thin adapter: the deterministic DAG stays
in charge of routing and lifecycle management, while DeerFlow handles bounded
sub-agent exploration behind a stable interface.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.blackboard.execution_blackboard import execution_blackboard
from src.common import EventTopic, event_bus
from src.common.task_lease_runtime import ensure_task_lease_owned
from src.dynamic_engine.runtime_gateway import RuntimeGateway
from src.dynamic_engine.supervisor import DynamicSupervisor
from src.dynamic_engine.trace_normalizer import TraceNormalizer
from src.mcp_gateway import default_mcp_client


def dynamic_swarm_node(state: Mapping[str, Any]) -> dict[str, Any]:
    """Execute the DeerFlow bridge and return a normalized state patch.

    When the local DeerFlow runtime is unavailable, the bridge degrades to a
    planning preview instead of failing the DAG outright.
    """

    tenant_id = str(state.get("tenant_id", ""))
    task_id = str(state.get("task_id", ""))
    workspace_id = str(state.get("workspace_id", "default_ws"))
    lease_owner_id = str(state.get("lease_owner_id", "")).strip()
    execution_data = execution_blackboard.read(tenant_id, task_id)
    if execution_data is None and execution_blackboard.restore(tenant_id, task_id):
        execution_data = execution_blackboard.read(tenant_id, task_id)
    execution_state = (
        execution_data.model_dump(mode="json")
        if execution_data
        else dict(state.get("execution_snapshot") or {})
    )
    plan = DynamicSupervisor.prepare(state, execution_state)

    def ensure_active_lease() -> None:
        ensure_task_lease_owned(task_id, lease_owner_id)

    def publish_governance_event(decision_payload: dict[str, Any]) -> None:
        ensure_active_lease()
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
    publish_governance_event(plan.governance_decision.to_record())
    if not plan.governance_decision.allowed:
        denied_patch = plan.denied_patch()
        ensure_active_lease()
        default_mcp_client.call_tool(
            "state_sync",
            {
                "patch": {
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
                }
            },
            context={"tenant_id": tenant_id, "task_id": task_id},
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

    ensure_active_lease()
    default_mcp_client.call_tool(
        "state_sync",
        {
            "patch": {
                "control": {
                    "decision_log": decision_patch.get("decision_log") or [],
                    "governance_trace_ref": decision_patch.get("governance_trace_ref"),
                    "task_envelope": plan.task_envelope.model_dump(mode="json"),
                    "execution_intent": plan.execution_intent.model_dump(mode="json"),
                },
                "dynamic": {
                    "request": gateway.build_payload(plan),
                    "runtime_backend": gateway.backend_name,
                },
            }
        },
        context={"tenant_id": tenant_id, "task_id": task_id},
    )

    forwarded_events: list[dict[str, Any]] = []

    def forward_event(event: dict[str, Any]) -> None:
        ensure_active_lease()
        normalized_event = TraceNormalizer.normalize_runtime_event(
            event,
            source=str(event.get("source") or "dynamic_swarm"),
        )
        forwarded_events.append(normalized_event)
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
    ensure_active_lease()
    result_patch = result.to_state_patch()
    if forwarded_events:
        # 运行期事件已经通过 `dynamic_trace` 增量写回过一次。
        # 这里只保留状态摘要、引用和产物，避免同一批 trace 再整包回写一遍。
        result_patch.pop("dynamic_trace", None)
    ensure_active_lease()
    dynamic_patch = {
        "status": result_patch.get("dynamic_status"),
        "summary": result_patch.get("dynamic_summary"),
        "runtime_metadata": result_patch.get("dynamic_runtime_metadata") or {},
        "trace": result_patch.get("dynamic_trace") or [],
        "trace_refs": result_patch.get("dynamic_trace_refs") or [],
        "artifacts": result_patch.get("dynamic_artifacts") or [],
        "recommended_static_skill": result_patch.get("recommended_static_skill"),
    }
    default_mcp_client.call_tool(
        "state_sync",
        {"patch": {"dynamic": dynamic_patch}},
        context={"tenant_id": tenant_id, "task_id": task_id},
    )
    return {
        **decision_patch,
        "task_envelope": plan.task_envelope.model_dump(mode="json"),
        "execution_intent": plan.execution_intent.model_dump(mode="json"),
        "dynamic_request": gateway.build_payload(plan),
        "runtime_backend": gateway.backend_name,
        **result_patch,
    }
