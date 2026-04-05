"""Execution node that runs generated code in the local sandbox."""
from __future__ import annotations

from typing import Any, Dict

from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.global_blackboard import global_blackboard
from src.blackboard.schema import GlobalStatus
from src.common.contracts import ExecutionRecord
from src.common import get_logger
from src.dag_engine.graphstate import DagGraphState
from src.mcp_gateway.tools.sandbox_exec_tool import SandboxExecTool, build_input_mount_manifest

logger = get_logger(__name__)


def executor_node(state: DagGraphState) -> Dict[str, Any]:
    tenant_id = state["tenant_id"]
    task_id = state["task_id"]
    workspace_id = state.get("workspace_id", "default_ws")

    exec_data = execution_blackboard.read(tenant_id, task_id)
    if not exec_data or not exec_data.generated_code:
        logger.warning(f"[Executor] 任务 {task_id} 没有可执行代码")
        return {"next_actions": ["skill_harvester"], "execution_result": None}

    global_blackboard.update_global_status(
        task_id=task_id,
        new_status=GlobalStatus.EXECUTING,
        sub_status="正在将生成代码送入本地沙箱执行",
    )

    result = SandboxExecTool.run_sync(
        code=exec_data.generated_code,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        use_audit=True,
        input_mounts=list(
            state.get("input_mounts")
            or build_input_mount_manifest(exec_data.structured_datasets, exec_data.business_documents)
        ),
    )

    exec_data.execution_result = result
    if result.get("execution_record"):
        execution_record = ExecutionRecord.model_validate(result["execution_record"])
        exec_data.execution_record = execution_record
        for artifact in execution_record.artifacts:
            artifact_path = artifact.path
            if artifact_path:
                exec_data.artifacts.append({"path": artifact_path, "type": artifact.artifact_type})
    else:
        artifacts_dir = result.get("artifacts_dir")
        if artifacts_dir:
            exec_data.artifacts.append({"path": artifacts_dir, "type": "sandbox_output"})

    execution_blackboard.write(tenant_id, task_id, exec_data)
    execution_blackboard.persist(tenant_id, task_id)

    return {
        "execution_result": result,
        "next_actions": ["skill_harvester"],
    }
