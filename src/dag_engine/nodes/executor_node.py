"""Execution node that runs generated code in the local sandbox."""
from __future__ import annotations

from typing import Any

from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.global_blackboard import global_blackboard
from src.blackboard.schema import GlobalStatus
from src.common import get_logger
from src.common.contracts import ExecutionRecord
from src.common.task_lease_runtime import ensure_task_lease_owned
from src.dag_engine.graphstate import DagGraphState
from src.mcp_gateway.tools.sandbox_exec_tool import SandboxExecTool, build_input_mount_manifest

logger = get_logger(__name__)


def executor_node(state: DagGraphState) -> dict[str, Any]:
    tenant_id = state["tenant_id"]
    task_id = state["task_id"]
    workspace_id = state.get("workspace_id", "default_ws")
    lease_owner_id = str(state.get("lease_owner_id", "")).strip()

    exec_data = execution_blackboard.read(tenant_id, task_id)
    if not exec_data or not exec_data.static.generated_code:
        logger.warning(f"[Executor] 任务 {task_id} 没有可执行代码")
        return {"next_actions": ["skill_harvester"], "execution_record": None}

    ensure_task_lease_owned(task_id, lease_owner_id)
    global_blackboard.update_global_status(
        task_id=task_id,
        new_status=GlobalStatus.EXECUTING,
        sub_status="正在将生成代码送入本地沙箱执行",
    )

    ensure_task_lease_owned(task_id, lease_owner_id)
    result = SandboxExecTool.run_sync(
        code=exec_data.static.generated_code,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        use_audit=True,
        input_mounts=list(
            state.get("input_mounts")
            or build_input_mount_manifest(exec_data.inputs.structured_datasets, exec_data.inputs.business_documents)
        ),
    )

    ensure_task_lease_owned(task_id, lease_owner_id)
    execution_record = None
    if result.get("execution_record"):
        execution_record = ExecutionRecord.model_validate(result["execution_record"])
        exec_data.static.execution_record = execution_record

    ensure_task_lease_owned(task_id, lease_owner_id)
    execution_blackboard.write(tenant_id, task_id, exec_data)
    execution_blackboard.persist(tenant_id, task_id)

    return {
        "execution_record": execution_record.model_dump(mode="json") if execution_record else None,
        "next_actions": ["skill_harvester"],
    }
