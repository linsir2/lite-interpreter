"""Request scope and endpoint exposure helpers for API routes."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from src.api.auth import auth_context_allows_scope, request_auth_context
from src.api.schemas import api_error_response
from src.common.utils import validate_scope_identifier


def request_scope(request: Request) -> tuple[str, str]:
    auth_context = request_auth_context(request)
    default_tenant = ""
    default_workspace = ""
    if auth_context is not None:
        if len(auth_context.grants) == 1:
            default_tenant = auth_context.grants[0].tenant_id
            default_workspace = auth_context.grants[0].workspace_id
        elif not auth_context.grants:
            default_tenant = auth_context.tenant_id
            default_workspace = auth_context.workspace_id
    tenant_id = str(
        request.query_params.get("tenant_id") or request.headers.get("x-tenant-id") or default_tenant
    ).strip()
    workspace_id = str(
        request.query_params.get("workspace_id") or request.headers.get("x-workspace-id") or default_workspace
    ).strip()
    return tenant_id, workspace_id


def require_request_scope(request: Request) -> tuple[str, str] | JSONResponse:
    tenant_id, workspace_id = request_scope(request)
    if tenant_id and workspace_id:
        try:
            return (
                validate_scope_identifier(tenant_id, field_name="tenant_id"),
                validate_scope_identifier(workspace_id, field_name="workspace_id"),
            )
        except ValueError as exc:
            return api_error_response("INVALID_SCOPE", str(exc), status_code=400)
    return api_error_response(
        "MISSING_SCOPE",
        "Missing tenant/workspace scope.",
        status_code=400,
        details={"requiredQueryParams": ["tenant_id", "workspace_id"]},
    )


def ensure_resource_scope(
    request: Request,
    *,
    tenant_id: str,
    workspace_id: str,
) -> JSONResponse | None:
    requested_scope = require_request_scope(request)
    if isinstance(requested_scope, JSONResponse):
        return requested_scope
    requested_tenant_id, requested_workspace_id = requested_scope
    if requested_tenant_id != tenant_id or requested_workspace_id != workspace_id:
        return api_error_response("NOT_FOUND", "Resource not found.", status_code=404)
    return None


def ensure_claimed_scope(
    request: Request,
    *,
    tenant_id: str,
    workspace_id: str,
) -> JSONResponse | None:
    auth_context = request_auth_context(request)
    if auth_context is None:
        return None
    if not auth_context_allows_scope(auth_context, tenant_id, workspace_id):
        return api_error_response(
            "SCOPE_FORBIDDEN",
            "The selected scope is not available in the current session.",
            status_code=403,
        )
    return None


def endpoint_disabled(error: str) -> JSONResponse:
    return api_error_response("ENDPOINT_DISABLED", error, status_code=404)
