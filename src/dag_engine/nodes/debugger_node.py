"""Bounded debugger node for one static repair attempt."""

from __future__ import annotations

from typing import Any

from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.global_blackboard import global_blackboard
from src.blackboard.schema import GlobalStatus
from src.common import get_logger
from src.common.control_plane import ensure_debug_attempt_record, ensure_execution_strategy, ensure_static_repair_plan
from src.dag_engine.graphstate import DagGraphState
from src.dag_engine.nodes.static_codegen import prepare_static_codegen

logger = get_logger(__name__)


def debugger_node(state: DagGraphState) -> dict[str, Any]:
    tenant_id = state["tenant_id"]
    task_id = state["task_id"]
    retry_count = int(state.get("retry_count", 0) or 0) + 1

    global_blackboard.update_global_status(
        task_id=task_id,
        new_status=GlobalStatus.DEBUGGING,
        sub_status="正在回退到安全调试版本代码",
        current_retries=retry_count,
    )

    exec_data = execution_blackboard.read(tenant_id, task_id)
    if not exec_data:
        logger.warning(f"[Debugger] 缺少任务 {task_id} 的执行上下文")
        return {"generated_code": "", "next_actions": ["auditor"], "retry_count": 1}
    strategy = ensure_execution_strategy(exec_data.static.execution_strategy or {})
    artifact_verification = getattr(exec_data.static, "artifact_verification", None)
    failure_reason = (
        exec_data.static.latest_error_traceback
        or (
            "; ".join(list(getattr(artifact_verification, "failure_reasons", []) or []))
            if artifact_verification is not None
            else ""
        )
        or "static execution failed"
    )
    repair_plan = ensure_static_repair_plan(
        {
            "reason": failure_reason,
            "attempt_index": retry_count,
            "action": (
                "fallback_to_legacy"
                if strategy.strategy_family != "legacy_dataset_aware_generator"
                else "simplify_program"
            ),
            "updates": {
                "previous_strategy_family": strategy.strategy_family,
                "retry_count": retry_count,
            },
        },
        reason=failure_reason,
        attempt_index=retry_count,
    )
    debug_attempt = ensure_debug_attempt_record(
        {
            "attempt_index": retry_count,
            "reason": failure_reason,
            "repair_plan": repair_plan.model_dump(mode="json"),
            "outcome": "regenerating",
        },
        attempt_index=retry_count,
        reason=failure_reason,
    )
    exec_data.static.repair_plan = repair_plan
    exec_data.static.debug_attempts = [*list(exec_data.static.debug_attempts or []), debug_attempt]
    prepared = prepare_static_codegen(
        exec_data=exec_data,
        state={**state, "repair_plan": repair_plan.model_dump(mode="json")},
    )
    exec_data.static.generated_code = prepared.generated_code
    exec_data.static.execution_strategy = prepared.execution_strategy
    exec_data.static.static_evidence_bundle = prepared.static_evidence_bundle or None
    exec_data.static.program_spec = prepared.program_spec or None
    exec_data.static.generator_manifest = prepared.generator_manifest
    exec_data.static.artifact_plan = prepared.artifact_plan
    exec_data.static.verification_plan = prepared.verification_plan
    execution_blackboard.write(tenant_id, task_id, exec_data)
    execution_blackboard.persist(tenant_id, task_id)
    return {
        "generated_code": exec_data.static.generated_code,
        "execution_strategy": prepared.execution_strategy,
        "static_evidence_bundle": prepared.static_evidence_bundle,
        "program_spec": prepared.program_spec,
        "repair_plan": repair_plan.model_dump(mode="json"),
        "debug_attempts": [item.model_dump(mode="json") for item in exec_data.static.debug_attempts],
        "next_actions": ["auditor"],
        "retry_count": retry_count,
    }
