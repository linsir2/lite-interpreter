"""Helpers for API audit recording."""

from __future__ import annotations

from typing import Any

from src.api.auth import request_auth_context
from src.common import generate_uuid
from src.common.contracts import AuditRecord
from src.storage.repository.audit_repo import AuditRepo


def record_api_audit(
    request: Any,
    *,
    action: str,
    outcome: str,
    tenant_id: str,
    workspace_id: str,
    task_id: str | None = None,
    execution_id: str | None = None,
    resource_type: str = "api",
    resource_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    auth_context = request_auth_context(request)
    headers = getattr(request, "headers", {}) or {}
    path = ""
    method = ""
    try:
        path = str(getattr(request, "url", None).path)
    except Exception:
        path = str(getattr(request, "path_params", {}) or "")
    try:
        method = str(getattr(request, "method", "") or "")
    except Exception:
        method = ""

    trace_id = str(headers.get("x-request-id") or headers.get("x-trace-id") or "").strip() or None
    record = AuditRecord(
        audit_id=generate_uuid(),
        subject=(auth_context.subject if auth_context is not None else "anonymous"),
        role=(auth_context.role if auth_context is not None else "anonymous"),
        action=action,
        outcome=outcome,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        execution_id=execution_id,
        resource_type=resource_type,
        resource_id=resource_id,
        request_method=method or "UNKNOWN",
        request_path=path or "unknown",
        trace_id=trace_id,
        metadata=dict(metadata or {}),
    )
    return AuditRepo.append_record(record)
