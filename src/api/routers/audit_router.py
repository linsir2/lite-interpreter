"""Audit log read-model endpoints."""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from src.api.auth import require_request_role
from src.api.request_scope import ensure_claimed_scope, require_request_scope
from src.storage.repository.audit_repo import AuditRepo


async def list_audit_logs(request: Request) -> JSONResponse:
    role_error = require_request_role(request, "admin")
    if role_error is not None:
        return role_error
    scope = require_request_scope(request)
    if isinstance(scope, JSONResponse):
        return scope
    tenant_id, workspace_id = scope
    scope_error = ensure_claimed_scope(
        request,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    if scope_error is not None:
        return scope_error
    subject = str(request.query_params.get("subject") or "").strip() or None
    role = str(request.query_params.get("role") or "").strip() or None
    action = str(request.query_params.get("action") or "").strip() or None
    outcome = str(request.query_params.get("outcome") or "").strip() or None
    resource_type = str(request.query_params.get("resource_type") or "").strip() or None
    resource_id = str(request.query_params.get("resource_id") or "").strip() or None
    task_id = str(request.query_params.get("task_id") or "").strip() or None
    execution_id = str(request.query_params.get("execution_id") or "").strip() or None
    recorded_after = str(request.query_params.get("recorded_after") or "").strip() or None
    recorded_before = str(request.query_params.get("recorded_before") or "").strip() or None
    limit = int(str(request.query_params.get("limit") or "100"))
    records = AuditRepo.list_records(
        tenant_id,
        workspace_id,
        subject=subject,
        role=role,
        action=action,
        outcome=outcome,
        resource_type=resource_type,
        resource_id=resource_id,
        task_id=task_id,
        execution_id=execution_id,
        recorded_after=recorded_after,
        recorded_before=recorded_before,
        limit=max(1, min(limit, 500)),
    )
    return JSONResponse(
        {
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "subject": subject,
            "role": role,
            "action": action,
            "outcome": outcome,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "task_id": task_id,
            "execution_id": execution_id,
            "recorded_after": recorded_after,
            "recorded_before": recorded_before,
            "records": records,
        }
    )
