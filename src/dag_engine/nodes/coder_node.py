"""Static coder node that emits sandbox-safe, dataset-aware analysis Python."""

from __future__ import annotations

from typing import Any

from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.global_blackboard import global_blackboard
from src.blackboard.schema import GlobalStatus
from src.common import get_logger
from src.dag_engine.graphstate import DagGraphState
from src.dag_engine.nodes.static_codegen import (
    prepare_static_codegen,
)

logger = get_logger(__name__)


def coder_node(state: DagGraphState) -> dict[str, Any]:
    tenant_id = state["tenant_id"]
    task_id = state["task_id"]

    global_blackboard.update_global_status(
        task_id=task_id,
        new_status=GlobalStatus.CODING,
        sub_status="正在生成静态链路代码",
    )

    exec_data = execution_blackboard.read(tenant_id, task_id)
    if not exec_data:
        logger.warning(f"[Coder] 缺少任务 {task_id} 的执行上下文")
        return {"generated_code": "", "next_actions": ["auditor"]}

    prepared = prepare_static_codegen(
        exec_data=exec_data,
        state=state,
    )
    exec_data.static.generated_code = prepared.generated_code
    execution_blackboard.write(tenant_id, task_id, exec_data)
    execution_blackboard.persist(tenant_id, task_id)
    return {
        "generated_code": prepared.generated_code,
        "input_mounts": prepared.input_mounts,
        "next_actions": ["auditor"],
    }
