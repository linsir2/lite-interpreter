"""DAG assembly for the hybrid static + dynamic orchestration path."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping


NodeMap = Mapping[str, Callable[[dict[str, Any]], dict[str, Any]]]

from src.dag_engine.graphstate import DagGraphState

try:  # pragma: no cover - runtime optional during local scaffolding
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover
    END = START = None
    StateGraph = None


def get_route_map() -> Dict[str, str]:
    return {
        "data_inspector": "data_inspector",
        "kag_retriever": "kag_retriever",
        "analyst": "analyst",
        "dynamic_swarm": "dynamic_swarm",
    }


def _next_actions(state: Dict[str, object]) -> List[str]:
    return list(state.get("next_actions", []) or [])


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
    graph.add_edge("dynamic_swarm", "skill_harvester")
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

    route_result = nodes["router"](state)
    next_actions = list(route_result.get("next_actions", []) or [])
    if next_actions == ["dynamic_swarm"]:
        dynamic_state = nodes["dynamic_swarm"]({**state, **route_result})
        dynamic_status = str(dynamic_state.get("dynamic_status") or "")
        if dynamic_status == "completed":
            harvested_state = nodes["skill_harvester"]({**dynamic_state, **state})
            summary_state = nodes["summarizer"]({**dynamic_state, **harvested_state, **state})
            return {
                **route_result,
                **dynamic_state,
                **harvested_state,
                **summary_state,
                "terminal_status": "success",
                "terminal_sub_status": "动态任务链路执行完成",
            }
        if dynamic_status == "denied":
            summary_state = nodes["summarizer"]({**dynamic_state, **state})
            return {
                **route_result,
                **dynamic_state,
                **summary_state,
                "terminal_status": "waiting_for_human",
                "terminal_sub_status": "动态任务被治理策略阻断，等待人工介入",
                "failure_type": "dynamic_governance",
                "error_message": str(dynamic_state.get("dynamic_summary") or "dynamic swarm denied by governance policy"),
            }
        summary_state = nodes["summarizer"]({**dynamic_state, **state})
        return {
            **route_result,
            **dynamic_state,
            **summary_state,
            "terminal_status": "failed",
            "terminal_sub_status": "动态任务链路未能完成",
            "failure_type": "dynamic_runtime",
            "error_message": str(dynamic_state.get("dynamic_summary") or "dynamic swarm unavailable"),
        }

    current_state: dict[str, Any] = {**state, **route_result, "next_actions": next_actions}
    for action in next_actions:
        if action == "data_inspector":
            current_state.update(nodes["data_inspector"](current_state))
            if current_state.get("blocked"):
                summary_state = nodes["summarizer"](current_state)
                return {
                    **current_state,
                    **summary_state,
                    "terminal_status": "waiting_for_human",
                    "terminal_sub_status": "结构化数据探查失败，等待人工介入",
                    "failure_type": "data_inspection",
                    "error_message": str(current_state.get("block_reason") or "data inspection blocked"),
                }
        elif action == "kag_retriever":
            current_state.update(nodes["kag_retriever"](current_state))
            current_state.update(nodes["context_builder"](current_state))

    current_state.update(nodes["analyst"](current_state))
    current_state.update(nodes["coder"](current_state))

    audit_state = nodes["auditor"](current_state)
    current_state.update(audit_state)
    if audit_state.get("next_actions") == ["debugger"]:
        current_state.update(nodes["debugger"](current_state))
        current_state.update(nodes["auditor"](current_state))
    if current_state.get("next_actions") == ["skill_harvester"]:
        harvested_state = nodes["skill_harvester"](current_state)
        summary_state = nodes["summarizer"]({**current_state, **harvested_state})
        return {
            **current_state,
            **harvested_state,
            **summary_state,
            "terminal_status": "success",
            "terminal_sub_status": "静态链路完成，跳过沙箱执行",
        }

    executor_state = nodes["executor"](current_state)
    current_state.update(executor_state)
    harvested_state = nodes["skill_harvester"](current_state)
    current_state.update(harvested_state)
    summary_state = nodes["summarizer"](current_state)
    current_state.update(summary_state)
    execution_result = executor_state.get("execution_result")
    if execution_result and execution_result.get("success"):
        return {
            **current_state,
            "terminal_status": "success",
            "terminal_sub_status": "静态链路执行完成",
        }
    return {
        **current_state,
        "terminal_status": "failed",
        "terminal_sub_status": "静态链路执行失败",
        "failure_type": "executing",
        "error_message": str(
            execution_result.get("error", "sandbox execution failed")
            if execution_result
            else "sandbox execution result missing"
        ),
    }
