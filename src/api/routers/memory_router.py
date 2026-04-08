"""Task-scoped memory read-model endpoints."""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from src.api.audit_logging import record_api_audit
from src.api.auth import require_request_role
from src.api.execution_resources import read_task_execution_data, to_jsonable_payload
from src.api.request_scope import ensure_resource_scope
from src.blackboard import TaskNotExistError, global_blackboard, memory_blackboard
from src.common.control_plane import task_redaction_rules
from src.privacy import mask_payload


async def get_task_memory(request: Request) -> JSONResponse:
    role_error = require_request_role(request, "viewer")
    if role_error is not None:
        return role_error
    task_id = request.path_params["task_id"]
    try:
        task = global_blackboard.get_task_state(task_id)
    except TaskNotExistError:
        return JSONResponse({"error": "task not found", "task_id": task_id}, status_code=404)
    scope_error = ensure_resource_scope(
        request,
        tenant_id=task.tenant_id,
        workspace_id=task.workspace_id,
    )
    if scope_error is not None:
        record_api_audit(
            request,
            action="task.memory.read",
            outcome="denied",
            tenant_id=task.tenant_id,
            workspace_id=task.workspace_id,
            task_id=task_id,
            resource_type="task_memory",
            resource_id=task_id,
            metadata={"reason": "scope_mismatch"},
        )
        return scope_error

    memory_data = memory_blackboard.read(task.tenant_id, task_id)
    if memory_data is None and memory_blackboard.restore(task.tenant_id, task_id):
        memory_data = memory_blackboard.read(task.tenant_id, task_id)
    execution_data = read_task_execution_data(task.tenant_id, task_id)
    if memory_data is None:
        return JSONResponse(
            {
                "task": {
                    "task_id": task_id,
                    "tenant_id": task.tenant_id,
                    "workspace_id": task.workspace_id,
                },
                "memory": None,
            }
        )

    payload = to_jsonable_payload(
        {
            "task": {
                "task_id": task_id,
                "tenant_id": task.tenant_id,
                "workspace_id": task.workspace_id,
            },
            "memory": {
                "harvested_candidates": memory_data.harvested_candidates,
                "approved_skills": memory_data.approved_skills,
                "historical_matches": memory_data.historical_matches,
                "task_summary": memory_data.task_summary,
                "workspace_preferences": memory_data.workspace_preferences,
                "cache_hints": memory_data.cache_hints,
                "updated_at": memory_data.updated_at,
            },
        }
    )
    redacted_payload, _ = mask_payload(
        payload,
        task_redaction_rules(execution_data.control.task_envelope) if execution_data else None,
    )
    record_api_audit(
        request,
        action="task.memory.read",
        outcome="success",
        tenant_id=task.tenant_id,
        workspace_id=task.workspace_id,
        task_id=task_id,
        resource_type="task_memory",
        resource_id=task_id,
        metadata={"has_memory": memory_data is not None},
    )
    return JSONResponse(redacted_payload)
