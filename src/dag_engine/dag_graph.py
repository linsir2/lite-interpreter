"""Canonical task orchestrator for lite-interpreter."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.task_state_services import KnowledgeStateService
from src.common import get_utc_now
from src.common.task_lease_runtime import ensure_task_lease_owned
from src.dag_engine.dag_exceptions import TaskLeaseLostError
from src.runtime import build_analysis_brief

NodeMap = Mapping[str, Callable[[dict[str, Any]], dict[str, Any]]]


def _next_actions(state: dict[str, object]) -> list[str]:
    actions = [str(item) for item in (state.get("next_actions", []) or []) if str(item)]
    filtered = [item for item in actions if item in {"executor", "debugger", "skill_harvester"}]
    return filtered or []


def _normalize_output_patch(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    if not isinstance(value, dict):
        return {}
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


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
        checkpoint = dict((execution_data.control.node_checkpoints or {}).get(node_name) or {})
        if checkpoint.get("status") == "completed":
            normalized_patch = _normalize_output_patch(checkpoint.get("output_patch"))
            if normalized_patch:
                return normalized_patch

        checkpoints = dict(execution_data.control.node_checkpoints or {})
        previous = dict(checkpoints.get(node_name) or {})
        checkpoints[node_name] = {
            **previous,
            "status": "running",
            "started_at": get_utc_now().isoformat(),
            "attempt_count": int(previous.get("attempt_count", 0) or 0) + 1,
        }
        execution_data.control.node_checkpoints = checkpoints
        execution_blackboard.write(tenant_id, task_id, execution_data)
        execution_blackboard.persist(tenant_id, task_id)

    try:
        output_patch = node_fn(state) or {}
    except Exception as exc:
        if execution_data:
            latest = execution_blackboard.read(tenant_id, task_id) or execution_data
            checkpoints = dict(latest.control.node_checkpoints or {})
            previous = dict(checkpoints.get(node_name) or {})
            checkpoints[node_name] = {
                **previous,
                "status": "failed",
                "failed_at": get_utc_now().isoformat(),
                "error": str(exc),
            }
            latest.control.node_checkpoints = checkpoints
            execution_blackboard.write(tenant_id, task_id, latest)
            execution_blackboard.persist(tenant_id, task_id)
        raise

    normalized_output_patch = _normalize_output_patch(output_patch)
    if execution_data:
        latest = execution_blackboard.read(tenant_id, task_id) or execution_data
        checkpoints = dict(latest.control.node_checkpoints or {})
        previous = dict(checkpoints.get(node_name) or {})
        checkpoints[node_name] = {
            **previous,
            "status": "completed",
            "completed_at": get_utc_now().isoformat(),
            "error": None,
            "output_patch": normalized_output_patch,
        }
        latest.control.node_checkpoints = checkpoints
        execution_blackboard.write(tenant_id, task_id, latest)
        execution_blackboard.persist(tenant_id, task_id)
    return normalized_output_patch


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


def _merge_dynamic_research_into_static_state(state: dict[str, Any]) -> dict[str, Any]:
    tenant_id = str(state.get("tenant_id", ""))
    task_id = str(state.get("task_id", ""))
    query = str(state.get("input_query", ""))
    try:
        execution_data = KnowledgeStateService.load(tenant_id, task_id)
    except ValueError:
        next_actions = [
            str(item).strip()
            for item in list(
                state.get("dynamic_next_static_steps")
                or ((state.get("execution_intent") or {}).get("metadata") or {}).get("next_static_steps")
                or []
            )
            if str(item).strip()
        ] or ["analyst"]
        refined_context = "\n".join(
            f"- 研究发现: {str(item).strip()}"
            for item in list(state.get("dynamic_research_findings") or [])[:5]
            if str(item).strip()
        ).strip()
        return {
            "knowledge_snapshot": {},
            "analysis_brief": {
                "question": query,
                "analysis_mode": "dynamic_research_analysis",
                "dataset_summaries": [],
                "business_rules": [],
                "business_metrics": [],
                "business_filters": [],
                "evidence_refs": list(state.get("dynamic_evidence_refs") or []),
                "known_gaps": list(state.get("dynamic_open_questions") or []),
                "recommended_next_step": (
                    list(state.get("dynamic_suggested_static_actions") or []) or ["生成静态分析计划"]
                )[0],
            },
            "refined_context": refined_context,
            "next_actions": next_actions,
        }

    dynamic_summary = str(state.get("dynamic_summary") or execution_data.dynamic.summary or "").strip()
    research_findings = [
        str(item).strip()
        for item in list(state.get("dynamic_research_findings") or execution_data.dynamic.research_findings or [])
        if str(item).strip()
    ]
    if dynamic_summary and dynamic_summary not in research_findings:
        research_findings.insert(0, dynamic_summary)
    evidence_refs = [
        str(item).strip()
        for item in list(state.get("dynamic_evidence_refs") or execution_data.dynamic.evidence_refs or [])
        if str(item).strip()
    ]
    artifact_refs = [
        str(item).strip()
        for item in list(state.get("dynamic_artifacts") or execution_data.dynamic.artifacts or [])
        if str(item).strip()
    ]
    open_questions = [
        str(item).strip()
        for item in list(state.get("dynamic_open_questions") or execution_data.dynamic.open_questions or [])
        if str(item).strip()
    ]
    suggested_static_actions = [
        str(item).strip()
        for item in list(state.get("dynamic_suggested_static_actions") or execution_data.dynamic.suggested_static_actions or [])
        if str(item).strip()
    ]
    next_actions = [
        str(item).strip()
        for item in list(
            state.get("dynamic_next_static_steps")
            or ((state.get("execution_intent") or {}).get("metadata") or {}).get("next_static_steps")
            or []
        )
        if str(item).strip()
    ] or ["analyst"]

    knowledge_snapshot_payload = execution_data.knowledge.knowledge_snapshot.model_dump(mode="json")
    existing_hits = list(knowledge_snapshot_payload.get("hits") or [])
    dynamic_hits = [
        {
            "chunk_id": f"dynamic:{task_id}:{index}",
            "text": finding,
            "score": 1.0,
            "source": "dynamic_swarm",
            "retrieval_type": "dynamic_research",
        }
        for index, finding in enumerate(research_findings, start=1)
    ]
    knowledge_snapshot_payload["hits"] = [*existing_hits, *dynamic_hits]
    combined_evidence = []
    for value in list(knowledge_snapshot_payload.get("evidence_refs") or []) + evidence_refs + artifact_refs:
        text = str(value).strip()
        if text and text not in combined_evidence:
            combined_evidence.append(text)
    knowledge_snapshot_payload["evidence_refs"] = combined_evidence
    metadata = dict(knowledge_snapshot_payload.get("metadata") or {})
    metadata["dynamic_research"] = {
        "finding_count": len(research_findings),
        "open_question_count": len(open_questions),
        "artifact_count": len(artifact_refs),
    }
    knowledge_snapshot_payload["metadata"] = metadata

    recommended_next_step = (
        suggested_static_actions[0]
        if suggested_static_actions
        else "基于动态研究结果生成静态分析计划并准备模板化执行代码"
    )
    brief = build_analysis_brief(
        query=query,
        exec_data=execution_data,
        knowledge_snapshot=knowledge_snapshot_payload,
        business_context=execution_data.knowledge.business_context.model_dump(mode="json"),
        analysis_mode="dynamic_research_analysis",
        known_gaps=open_questions,
        recommended_next_step=recommended_next_step,
    )
    brief_payload = brief.to_payload()
    KnowledgeStateService.update_snapshot_and_brief(
        tenant_id=tenant_id,
        task_id=task_id,
        knowledge_snapshot=knowledge_snapshot_payload,
        analysis_brief=brief_payload,
    )
    refined_context = "\n".join(
        [
            *(f"- 研究发现: {item}" for item in research_findings[:5]),
            *(f"- 证据引用: {item}" for item in combined_evidence[:5]),
        ]
    ).strip()
    return {
        "knowledge_snapshot": knowledge_snapshot_payload,
        "analysis_brief": brief_payload,
        "refined_context": refined_context,
        "next_actions": next_actions,
    }


def execute_task_flow(
    state: dict[str, Any],
    *,
    nodes: NodeMap,
) -> dict[str, Any]:
    """Run the canonical static/dynamic task flow."""

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
            continuation = str(dynamic_state.get("dynamic_continuation") or "finish")
            if dynamic_status == "completed":
                if continuation == "resume_static":
                    merged_state = _merge_dynamic_research_into_static_state(
                        {**state, **route_result, **dynamic_state}
                    )
                    static_result = _execute_static_flow(
                        state={**state, **route_result, **dynamic_state, **merged_state},
                        next_actions=list(merged_state.get("next_actions") or []),
                        nodes=nodes,
                        success_sub_status="动态研究回流后静态链执行完成",
                    )
                    if static_result.get("terminal_status") == "success":
                        static_result["dynamic_status"] = dynamic_status
                        static_result["dynamic_summary"] = dynamic_state.get("dynamic_summary")
                    return static_result

                harvested_state = _run_checkpointed_node(
                    node_name="skill_harvester",
                    node_fn=nodes["skill_harvester"],
                    state={**dynamic_state, **route_result, **state},
                )
                summary_state = _run_checkpointed_node(
                    node_name="summarizer",
                    node_fn=nodes["summarizer"],
                    state={**dynamic_state, **harvested_state, **route_result, **state},
                )
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
