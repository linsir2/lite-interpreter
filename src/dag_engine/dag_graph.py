"""DAG assembly for the hybrid static + dynamic orchestration path."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from src.blackboard.execution_blackboard import execution_blackboard
from src.common import get_utc_now
from src.common.task_lease_runtime import ensure_task_lease_owned
from src.dag_engine.dag_exceptions import TaskLeaseLostError
from src.dag_engine.graphstate import DagGraphState

NodeMap = Mapping[str, Callable[[dict[str, Any]], dict[str, Any]]]

try:  # pragma: no cover - runtime optional during local scaffolding
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover
    END = START = None
    StateGraph = None


def get_route_map() -> dict[str, str]:
    return {
        "data_inspector": "data_inspector",
        "kag_retriever": "kag_retriever",
        "analyst": "analyst",
        "dynamic_swarm": "dynamic_swarm",
    }


def _next_actions(state: dict[str, object]) -> list[str]:
    actions = [str(item) for item in (state.get("next_actions", []) or []) if str(item)]
    filtered = [item for item in actions if item in {"executor", "debugger", "skill_harvester"}]
    return filtered or []


def _research_merge_next_actions(state: dict[str, object]) -> list[str]:
    actions = [str(item) for item in (state.get("next_actions", []) or []) if str(item)]
    filtered = [item for item in actions if item in {"data_inspector", "kag_retriever", "analyst", "skill_harvester"}]
    return filtered or ["skill_harvester"]


def _execution_intent_metadata(state: Mapping[str, Any]) -> dict[str, Any]:
    execution_intent = state.get("execution_intent")
    if isinstance(execution_intent, Mapping):
        metadata = execution_intent.get("metadata")
        if isinstance(metadata, Mapping):
            return dict(metadata)
    return {}


def _fallback_actions(state: Mapping[str, Any]) -> list[str]:
    metadata = _execution_intent_metadata(state)
    return list(metadata.get("fallback_destinations") or [])


def _normalize_output_patch(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    if not isinstance(value, dict):
        return {}
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def _normalize_checkpoint(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, dict):
        return dict(value)
    return {}


def _ensure_task_lease(state: Mapping[str, Any]) -> None:
    task_id = str(state.get("task_id", "")).strip()
    lease_owner_id = str(state.get("lease_owner_id", "")).strip()
    ensure_task_lease_owned(task_id, lease_owner_id)


def _run_checkpointed_node(
    *,
    node_name: str,
    node_fn: Callable[[dict[str, Any]], dict[str, Any]],
    state: dict[str, Any],
) -> dict[str, Any]:
    _ensure_task_lease(state)
    tenant_id = str(state.get("tenant_id", ""))
    task_id = str(state.get("task_id", ""))
    execution_data = execution_blackboard.read(tenant_id, task_id)

    if execution_data:
        checkpoint = _normalize_checkpoint((execution_data.control.node_checkpoints or {}).get(node_name))
        if checkpoint.get("status") == "completed":
            output_patch = checkpoint.get("output_patch")
            normalized_patch = _normalize_output_patch(output_patch)
            if normalized_patch:
                return normalized_patch

        checkpoints = dict(execution_data.control.node_checkpoints or {})
        previous = _normalize_checkpoint(checkpoints.get(node_name))
        checkpoints[node_name] = {
            **previous,
            "status": "running",
            "started_at": get_utc_now().isoformat(),
            "attempt_count": int(previous.get("attempt_count", 0) or 0) + 1,
        }
        execution_data.control.node_checkpoints = checkpoints
        _ensure_task_lease(state)
        execution_blackboard.write(tenant_id, task_id, execution_data)
        execution_blackboard.persist(tenant_id, task_id)

    try:
        output_patch = node_fn(state) or {}
    except Exception as exc:
        if execution_data:
            latest = execution_blackboard.read(tenant_id, task_id) or execution_data
            checkpoints = dict(latest.control.node_checkpoints or {})
            previous = _normalize_checkpoint(checkpoints.get(node_name))
            checkpoints[node_name] = {
                **previous,
                "status": "failed",
                "failed_at": get_utc_now().isoformat(),
                "error": str(exc),
            }
            latest.control.node_checkpoints = checkpoints
            _ensure_task_lease(state)
            execution_blackboard.write(tenant_id, task_id, latest)
            execution_blackboard.persist(tenant_id, task_id)
        raise

    if execution_data:
        latest = execution_blackboard.read(tenant_id, task_id) or execution_data
        checkpoints = dict(latest.control.node_checkpoints or {})
        previous = _normalize_checkpoint(checkpoints.get(node_name))
        checkpoints[node_name] = {
            **previous,
            "status": "completed",
            "completed_at": get_utc_now().isoformat(),
            "error": None,
            "output_patch": _normalize_output_patch(output_patch),
        }
        latest.control.node_checkpoints = checkpoints
        _ensure_task_lease(state)
        execution_blackboard.write(tenant_id, task_id, latest)
        execution_blackboard.persist(tenant_id, task_id)
    return output_patch


def _execute_static_flow(
    *,
    state: dict[str, Any],
    next_actions: list[str],
    nodes: NodeMap,
    success_sub_status: str,
) -> dict[str, Any]:
    current_state: dict[str, Any] = {**state, "next_actions": next_actions}
    for action in next_actions:
        if action == "data_inspector":
            current_state.update(
                _run_checkpointed_node(
                    node_name="data_inspector", node_fn=nodes["data_inspector"], state=current_state
                )
            )
            if current_state.get("blocked"):
                summary_state = _run_checkpointed_node(
                    node_name="summarizer",
                    node_fn=nodes["summarizer"],
                    state=current_state,
                )
                return {
                    **current_state,
                    **summary_state,
                    "terminal_status": "waiting_for_human",
                    "terminal_sub_status": "结构化数据探查失败，等待人工介入",
                    "failure_type": "data_inspection",
                    "error_message": str(current_state.get("block_reason") or "data inspection blocked"),
                }
        elif action == "kag_retriever":
            current_state.update(
                _run_checkpointed_node(
                    node_name="kag_retriever", node_fn=nodes["kag_retriever"], state=current_state
                )
            )
            if current_state.get("blocked"):
                summary_state = _run_checkpointed_node(
                    node_name="summarizer",
                    node_fn=nodes["summarizer"],
                    state=current_state,
                )
                return {
                    **current_state,
                    **summary_state,
                    "terminal_status": "waiting_for_human",
                    "terminal_sub_status": "知识构建失败，等待人工介入",
                    "failure_type": "knowledge_ingestion",
                    "error_message": str(current_state.get("block_reason") or "knowledge ingestion blocked"),
                }
            current_state.update(
                _run_checkpointed_node(
                    node_name="context_builder", node_fn=nodes["context_builder"], state=current_state
                )
            )

    current_state.update(_run_checkpointed_node(node_name="analyst", node_fn=nodes["analyst"], state=current_state))
    current_state.update(_run_checkpointed_node(node_name="coder", node_fn=nodes["coder"], state=current_state))

    audit_state = _run_checkpointed_node(node_name="auditor", node_fn=nodes["auditor"], state=current_state)
    current_state.update(audit_state)
    if audit_state.get("next_actions") == ["debugger"]:
        current_state.update(
            _run_checkpointed_node(node_name="debugger", node_fn=nodes["debugger"], state=current_state)
        )
        current_state.update(
            _run_checkpointed_node(node_name="auditor", node_fn=nodes["auditor"], state=current_state)
        )
    if current_state.get("next_actions") == ["skill_harvester"]:
        harvested_state = _run_checkpointed_node(
            node_name="skill_harvester",
            node_fn=nodes["skill_harvester"],
            state=current_state,
        )
        summary_state = _run_checkpointed_node(
            node_name="summarizer",
            node_fn=nodes["summarizer"],
            state={**current_state, **harvested_state},
        )
        return {
            **current_state,
            **harvested_state,
            **summary_state,
            "terminal_status": "success",
            "terminal_sub_status": "静态链路完成，跳过沙箱执行",
        }

    executor_state = _run_checkpointed_node(node_name="executor", node_fn=nodes["executor"], state=current_state)
    current_state.update(executor_state)
    harvested_state = _run_checkpointed_node(
        node_name="skill_harvester",
        node_fn=nodes["skill_harvester"],
        state=current_state,
    )
    current_state.update(harvested_state)
    summary_state = _run_checkpointed_node(node_name="summarizer", node_fn=nodes["summarizer"], state=current_state)
    current_state.update(summary_state)
    execution_record = executor_state.get("execution_record")
    if execution_record and execution_record.get("success"):
        return {
            **current_state,
            "terminal_status": "success",
            "terminal_sub_status": success_sub_status,
        }
    return {
        **current_state,
        "terminal_status": "failed",
        "terminal_sub_status": "静态链路执行失败",
        "failure_type": "executing",
        "error_message": str(
            execution_record.get("error", "sandbox execution failed")
            if execution_record
            else "sandbox execution result missing"
        ),
    }


def build_dag_graph():
    """Build the static+dynamic graph when LangGraph is available."""
    if StateGraph is None:
        return None

    from src.dag_engine.nodes.analyst_node import analyst_node
    from src.dag_engine.nodes.auditor_node import auditor_node
    from src.dag_engine.nodes.coder_node import coder_node
    from src.dag_engine.nodes.context_builder_node import context_builder_node
    from src.dag_engine.nodes.data_inspector import data_inspector_node
    from src.dag_engine.nodes.debugger_node import debugger_node
    from src.dag_engine.nodes.dynamic_swarm_node import dynamic_swarm_node
    from src.dag_engine.nodes.executor_node import executor_node
    from src.dag_engine.nodes.kag_retriever import kag_retriever_node
    from src.dag_engine.nodes.research_merge_node import research_merge_node
    from src.dag_engine.nodes.router_node import route_condition, router_node
    from src.dag_engine.nodes.skill_harvester_node import skill_harvester_node
    from src.dag_engine.nodes.summarizer_node import summarizer_node

    graph = StateGraph(DagGraphState)
    graph.add_node("router", router_node)
    graph.add_node("data_inspector", data_inspector_node)
    graph.add_node("kag_retriever", kag_retriever_node)
    graph.add_node("context_builder", context_builder_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("coder", coder_node)
    graph.add_node("auditor", auditor_node)
    graph.add_node("debugger", debugger_node)
    graph.add_node("executor", executor_node)
    graph.add_node("dynamic_swarm", dynamic_swarm_node)
    graph.add_node("research_merge", research_merge_node)
    graph.add_node("skill_harvester", skill_harvester_node)
    graph.add_node("summarizer", summarizer_node)

    graph.add_edge(START, "router")
    graph.add_conditional_edges("router", route_condition, get_route_map())
    graph.add_edge("data_inspector", "analyst")
    graph.add_edge("kag_retriever", "context_builder")
    graph.add_edge("context_builder", "analyst")
    graph.add_edge("analyst", "coder")
    graph.add_edge("coder", "auditor")
    graph.add_conditional_edges(
        "auditor",
        _next_actions,
        {
            "executor": "executor",
            "debugger": "debugger",
            "skill_harvester": "skill_harvester",
        },
    )
    graph.add_edge("debugger", "auditor")
    graph.add_edge("executor", "skill_harvester")
    graph.add_edge("dynamic_swarm", "research_merge")
    graph.add_conditional_edges(
        "research_merge",
        _research_merge_next_actions,
        {
            "data_inspector": "data_inspector",
            "kag_retriever": "kag_retriever",
            "analyst": "analyst",
            "skill_harvester": "skill_harvester",
        },
    )
    graph.add_edge("skill_harvester", "summarizer")
    graph.add_edge("summarizer", END)
    return graph.compile()


def execute_task_flow(
    state: dict[str, Any],
    *,
    nodes: NodeMap,
) -> dict[str, Any]:
    """Run the task orchestration through the existing static/dynamic design.

    The deterministic routing remains unchanged; this function only centralizes
    the orchestration so API routes stop carrying a second copy of the flow.
    """

    try:
        route_result = _run_checkpointed_node(node_name="router", node_fn=nodes["router"], state=state)
        next_actions = list(route_result.get("next_actions", []) or [])
        if next_actions == ["dynamic_swarm"]:
            dynamic_state = _run_checkpointed_node(
                node_name="dynamic_swarm",
                node_fn=nodes["dynamic_swarm"],
                state={**state, **route_result},
            )
            dynamic_status = str(dynamic_state.get("dynamic_status") or "")
            if dynamic_status == "completed":
                merged_state = _run_checkpointed_node(
                    node_name="research_merge",
                    node_fn=nodes["research_merge"],
                    state={**state, **route_result, **dynamic_state},
                )
                merge_actions = list(merged_state.get("next_actions") or [])
                if merge_actions == ["skill_harvester"]:
                    harvested_state = _run_checkpointed_node(
                        node_name="skill_harvester",
                        node_fn=nodes["skill_harvester"],
                        state={**dynamic_state, **merged_state, **state},
                    )
                    summary_state = _run_checkpointed_node(
                        node_name="summarizer",
                        node_fn=nodes["summarizer"],
                        state={**dynamic_state, **merged_state, **harvested_state, **state},
                    )
                    return {
                        **route_result,
                        **dynamic_state,
                        **merged_state,
                        **harvested_state,
                        **summary_state,
                        "terminal_status": "success",
                        "terminal_sub_status": "动态任务链路执行完成",
                    }
                static_result = _execute_static_flow(
                    state={**state, **route_result, **dynamic_state, **merged_state},
                    next_actions=merge_actions,
                    nodes=nodes,
                    success_sub_status="动态研究回流后静态链执行完成",
                )
                if static_result.get("terminal_status") == "success":
                    static_result["dynamic_status"] = dynamic_status
                    static_result["dynamic_summary"] = dynamic_state.get("dynamic_summary")
                return static_result
            fallback_actions = _fallback_actions(route_result)
            if fallback_actions:
                degraded_state = {
                    **state,
                    **route_result,
                    **dynamic_state,
                    "next_actions": fallback_actions,
                    "routing_degraded": True,
                    "degrade_reason": _execution_intent_metadata(route_result).get("fallback_reason")
                    or dynamic_state.get("dynamic_summary")
                    or "dynamic route degraded to static path",
                }
                return _execute_static_flow(
                    state=degraded_state,
                    next_actions=fallback_actions,
                    nodes=nodes,
                    success_sub_status="动态任务降级后静态链执行完成",
                )
            if dynamic_status == "denied":
                summary_state = nodes["summarizer"]({**dynamic_state, **state})
                return {
                    **route_result,
                    **dynamic_state,
                    **summary_state,
                    "terminal_status": "waiting_for_human",
                    "terminal_sub_status": "动态任务被治理策略阻断，等待人工介入",
                    "failure_type": "dynamic_governance",
                    "error_message": str(
                        dynamic_state.get("dynamic_summary") or "dynamic swarm denied by governance policy"
                    ),
                }
            summary_state = _run_checkpointed_node(
                node_name="summarizer",
                node_fn=nodes["summarizer"],
                state={**dynamic_state, **state},
            )
            return {
                **route_result,
                **dynamic_state,
                **summary_state,
                "terminal_status": "failed",
                "terminal_sub_status": "动态任务链路未能完成",
                "failure_type": "dynamic_runtime",
                "error_message": str(dynamic_state.get("dynamic_summary") or "dynamic swarm unavailable"),
            }
        return _execute_static_flow(
            state={**state, **route_result},
            next_actions=next_actions,
            nodes=nodes,
            success_sub_status="静态链路执行完成",
        )
    except TaskLeaseLostError as exc:
        return {
            **state,
            "terminal_status": "failed",
            "terminal_sub_status": "任务租约已丢失，本地执行已停止",
            "failure_type": "lease_lost",
            "error_message": str(exc),
        }
