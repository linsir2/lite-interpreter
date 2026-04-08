"""Static coder node that emits sandbox-safe, dataset-aware analysis Python."""
from __future__ import annotations

from typing import Any

from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.global_blackboard import global_blackboard
from src.blackboard.schema import GlobalStatus
from src.common import get_logger
from src.dag_engine.graphstate import DagGraphState
from src.dag_engine.nodes.static_codegen import (
    build_dataset_aware_code,
    build_static_coder_payload,
    build_static_input_mounts,
)
from src.memory import MemoryService

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

    recall_result = MemoryService.recall_skills(
        tenant_id=tenant_id,
        task_id=task_id,
        workspace_id=exec_data.workspace_id,
        query=str(state.get("input_query", "")),
        stage="coder",
        available_capabilities=exec_data.control.task_envelope.allowed_tools if exec_data.control.task_envelope else [],
        match_reason_detail="coder incorporated historical skills into the code-generation payload",
    )
    memory_data = MemoryService.mark_matches_used_in_codegen(
        memory_data=recall_result.memory_data,
        query=str(state.get("input_query", "")),
        merged_skills=recall_result.merged_skills,
    )

    input_mounts = build_static_input_mounts(exec_data)
    payload = build_static_coder_payload(
        exec_data=exec_data,
        state=state,
        input_mounts=input_mounts,
        approved_skills=list(memory_data.approved_skills or []),
    )
    generated_code = build_dataset_aware_code(payload)
    exec_data.static.generated_code = generated_code
    execution_blackboard.write(tenant_id, task_id, exec_data)
    execution_blackboard.persist(tenant_id, task_id)
    return {"generated_code": generated_code, "input_mounts": input_mounts, "next_actions": ["auditor"]}
