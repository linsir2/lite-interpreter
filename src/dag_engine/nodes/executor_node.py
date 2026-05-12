"""Execution node that runs generated code in the local sandbox."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.global_blackboard import global_blackboard
from src.blackboard.schema import GlobalStatus
from src.common import get_logger
from src.common.contracts import ExecutionRecord, IterationMode
from src.common.control_plane import ensure_execution_strategy
from src.common.task_lease_runtime import ensure_task_lease_owned
from src.dag_engine.graphstate import DagGraphState
from src.dag_engine.nodes.static_generation_registry import verify_generated_artifacts
from src.mcp_gateway.tools.sandbox_exec_tool import SandboxExecTool, build_input_mount_manifest

logger = get_logger(__name__)


@dataclass(frozen=True)
class PreparedExecutionRun:
    """Static execution request assembled from node state and persisted inputs."""

    workspace_id: str
    lease_owner_id: str
    input_mounts: list[dict[str, str]]
    generated_code: str


def _prepare_execution_run(state: DagGraphState, exec_data: Any) -> PreparedExecutionRun:
    workspace_id = str(state.get("workspace_id", "default_ws"))
    lease_owner_id = str(state.get("lease_owner_id", "")).strip()
    input_mounts = list(
        state.get("input_mounts")
        or build_input_mount_manifest(exec_data.inputs.structured_datasets, exec_data.inputs.business_documents)
    )
    return PreparedExecutionRun(
        workspace_id=workspace_id,
        lease_owner_id=lease_owner_id,
        input_mounts=input_mounts,
        generated_code=exec_data.static.generated_code,
    )


def _persist_execution_result(
    *,
    tenant_id: str,
    task_id: str,
    exec_data: Any,
    result: dict[str, Any],
) -> ExecutionRecord | None:
    if not result.get("execution_record"):
        execution_blackboard.write(tenant_id, task_id, exec_data)
        execution_blackboard.persist(tenant_id, task_id)
        return None

    execution_record = ExecutionRecord.model_validate(result["execution_record"])
    exec_data.static.execution_record = execution_record
    execution_blackboard.write(tenant_id, task_id, exec_data)
    execution_blackboard.persist(tenant_id, task_id)
    return execution_record


def executor_node(state: DagGraphState) -> dict[str, Any]:
    tenant_id = state["tenant_id"]
    task_id = state["task_id"]

    exec_data = execution_blackboard.read(tenant_id, task_id)
    round_idx = int(state.get("round_index", 0))
    if not exec_data or not exec_data.static.generated_code:
        logger.warning(f"[Executor] 任务 {task_id} 没有可执行代码")
        return {
            "execution_record": None,
            "round_output": {
                "round_index": round_idx,
                "key_findings": "",
                "artifacts_produced": [],
                "additional_rounds": 0,
                "requires_dynamic": False,
                "termination_reason": "no_generated_code",
            },
        }
    prepared = _prepare_execution_run(state, exec_data)

    ensure_task_lease_owned(task_id, prepared.lease_owner_id)
    global_blackboard.update_global_status(
        task_id=task_id,
        new_status=GlobalStatus.EXECUTING,
        sub_status="正在将生成代码送入本地沙箱执行",
    )

    ensure_task_lease_owned(task_id, prepared.lease_owner_id)
    result = SandboxExecTool.run_sync(
        code=prepared.generated_code,
        tenant_id=tenant_id,
        workspace_id=prepared.workspace_id,
        task_id=task_id,
        use_audit=True,
        input_mounts=prepared.input_mounts,
    )

    ensure_task_lease_owned(task_id, prepared.lease_owner_id)
    execution_record = _persist_execution_result(
        tenant_id=tenant_id,
        task_id=task_id,
        exec_data=exec_data,
        result=result,
    )

    execution_strategy = ensure_execution_strategy(exec_data.static.execution_strategy or {})
    artifact_verification = verify_generated_artifacts(
        execution_strategy=execution_strategy,
        execution_record=execution_record,
    )
    exec_data.static.execution_strategy = execution_strategy
    exec_data.static.artifact_verification = artifact_verification
    execution_blackboard.write(tenant_id, task_id, exec_data)
    execution_blackboard.persist(tenant_id, task_id)

    is_multi_round = execution_strategy.iteration_mode == IterationMode.MULTI_ROUND
    passed = artifact_verification.passed
    round_output = {
        "round_index": round_idx,
        "key_findings": (getattr(execution_record, "summary", None) or execution_record.output) if execution_record else "",
        "artifacts_produced": list(artifact_verification.verified_artifact_keys) if passed else [],
        "additional_rounds": 1 if is_multi_round and passed else 0,
        "requires_dynamic": False,
        "termination_reason": "" if passed else "verification_failed",
    }

    if not passed:
        exec_data.static.latest_error_traceback = "; ".join(artifact_verification.failure_reasons)
        execution_blackboard.write(tenant_id, task_id, exec_data)
        execution_blackboard.persist(tenant_id, task_id)
        return {
            "execution_record": execution_record.model_dump(mode="json") if execution_record else None,
            "artifact_verification": artifact_verification.model_dump(mode="json"),
            "round_output": round_output,
        }

    return {
        "execution_record": execution_record.model_dump(mode="json") if execution_record else None,
        "artifact_verification": artifact_verification.model_dump(mode="json"),
        "round_output": round_output,
    }
