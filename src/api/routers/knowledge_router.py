"""Task-scoped knowledge read-model endpoints."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from src.api.audit_logging import record_api_audit
from src.api.auth import require_request_role
from src.api.execution_resources import read_task_execution_data, to_jsonable_payload
from src.api.request_scope import ensure_resource_scope
from src.blackboard import TaskNotExistError, global_blackboard, knowledge_blackboard
from src.common.control_plane import task_redaction_rules
from src.privacy import mask_payload


async def get_task_knowledge(request: Request) -> JSONResponse:
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
            action="task.knowledge.read",
            outcome="denied",
            tenant_id=task.tenant_id,
            workspace_id=task.workspace_id,
            task_id=task_id,
            resource_type="task_knowledge",
            resource_id=task_id,
            metadata={"reason": "scope_mismatch"},
        )
        return scope_error

    knowledge_data = knowledge_blackboard.read(task.tenant_id, task_id)
    if knowledge_data is None and knowledge_blackboard.restore(task.tenant_id, task_id):
        knowledge_data = knowledge_blackboard.read(task.tenant_id, task_id)
    execution_data = read_task_execution_data(task.tenant_id, task_id)
    if knowledge_data is None:
        return JSONResponse(
            {
                "task": {
                    "task_id": task_id,
                    "tenant_id": task.tenant_id,
                    "workspace_id": task.workspace_id,
                },
                "knowledge": None,
            }
        )

    payload = to_jsonable_payload(
        {
            "task": {
                "task_id": task_id,
                "tenant_id": task.tenant_id,
                "workspace_id": task.workspace_id,
            },
            "knowledge": {
                "business_documents": knowledge_data.business_documents,
                "latest_retrieval_snapshot": knowledge_data.latest_retrieval_snapshot,
                "parser_reports": knowledge_data.parser_reports,
                "updated_at": knowledge_data.updated_at,
            },
        }
    )
    redacted_payload, _ = mask_payload(
        payload,
        task_redaction_rules(execution_data.control.task_envelope) if execution_data else None,
    )
    record_api_audit(
        request,
        action="task.knowledge.read",
        outcome="success",
        tenant_id=task.tenant_id,
        workspace_id=task.workspace_id,
        task_id=task_id,
        resource_type="task_knowledge",
        resource_id=task_id,
        metadata={"has_knowledge": knowledge_data is not None},
    )
    return JSONResponse(redacted_payload)
