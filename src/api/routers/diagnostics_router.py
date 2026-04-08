"""Diagnostics and conformance inspection endpoints."""
from __future__ import annotations

from src.api.audit_logging import record_api_audit
from src.api.auth import require_request_role
from config.settings import API_ENABLE_DIAGNOSTICS
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.api.diagnostics_resources import build_conformance_report, build_diagnostics_report
from src.api.request_scope import endpoint_disabled


async def get_diagnostics(_request: Request) -> JSONResponse:
    role_error = require_request_role(_request, "admin")
    if role_error is not None:
        return role_error
    if not API_ENABLE_DIAGNOSTICS:
        return endpoint_disabled("diagnostics api disabled")
    payload = build_diagnostics_report()
    auth_context = getattr(getattr(_request, "state", None), "auth_context", None)
    record_api_audit(
        _request,
        action="diagnostics.read",
        outcome="success",
        tenant_id=str(auth_context.tenant_id if auth_context else ""),
        workspace_id=str(auth_context.workspace_id if auth_context else ""),
        resource_type="diagnostics",
        metadata={"sections": sorted(payload.keys())},
    )
    return JSONResponse(payload)


async def get_conformance(_request: Request) -> JSONResponse:
    role_error = require_request_role(_request, "viewer")
    if role_error is not None:
        return role_error
    payload = build_conformance_report()
    auth_context = getattr(getattr(_request, "state", None), "auth_context", None)
    record_api_audit(
        _request,
        action="conformance.read",
        outcome="success",
        tenant_id=str(auth_context.tenant_id if auth_context else ""),
        workspace_id=str(auth_context.workspace_id if auth_context else ""),
        resource_type="conformance",
        metadata={"runtime_count": int((payload.get("summary") or {}).get("runtime_count", 0) or 0)},
    )
    return JSONResponse(payload)
