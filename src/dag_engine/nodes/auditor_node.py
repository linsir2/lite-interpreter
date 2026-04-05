"""Minimal auditor node that AST-checks generated code before execution."""
from __future__ import annotations

from typing import Any, Dict

from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.global_blackboard import global_blackboard
from src.blackboard.schema import GlobalStatus
from src.common import get_logger
from src.dag_engine.graphstate import DagGraphState
from src.sandbox import audit_code

logger = get_logger(__name__)
MAX_DEBUG_RETRIES = 1


def auditor_node(state: DagGraphState) -> Dict[str, Any]:
    tenant_id = state["tenant_id"]
    task_id = state["task_id"]

    global_blackboard.update_global_status(
        task_id=task_id,
        new_status=GlobalStatus.AUDITING,
        sub_status="正在执行 AST 安全审计",
    )

    exec_data = execution_blackboard.read(tenant_id, task_id)
    if not exec_data or not exec_data.generated_code:
        logger.warning(f"[Auditor] 任务 {task_id} 没有待审计代码")
        return {"audit_result": None, "next_actions": ["executor"]}

    audit_result = audit_code(exec_data.generated_code, tenant_id, trace_id=task_id)
    exec_data.audit_result = audit_result
    if not audit_result.get("safe"):
        exec_data.latest_error_traceback = audit_result.get("reason")
        retry_count = int(state.get("retry_count", 0) or 0)
        if retry_count >= MAX_DEBUG_RETRIES:
            global_blackboard.update_global_status(
                task_id=task_id,
                new_status=GlobalStatus.FAILED,
                sub_status="静态链路审计失败且已达到最大修复次数",
                failure_type="auditing",
                error_message=str(audit_result.get("reason", "audit failed")),
            )
            next_actions = ["skill_harvester"]
        else:
            next_actions = ["debugger"]
    else:
        next_actions = ["executor"]

    execution_blackboard.write(tenant_id, task_id, exec_data)
    execution_blackboard.persist(tenant_id, task_id)
    return {"audit_result": audit_result, "next_actions": next_actions}
