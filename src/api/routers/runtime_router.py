"""Runtime capability inspection endpoints — native exploration."""

from __future__ import annotations

from config.settings import DYNAMIC_NATIVE_MAX_STEPS, DYNAMIC_NATIVE_MODEL, DYNAMIC_NATIVE_TIMEOUT
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.api.audit_logging import record_api_audit
from src.api.auth import require_request_role
from src.mcp_gateway import default_mcp_server

_NATIVE_RUNTIME = {
    "runtime_id": "native",
    "display_name": "Native Exploration Loop",
    "description": "In-process LLM tool-calling exploration via MCP gateway",
    "runtime_modes": ["in_process"],
    "domains": [
        {"domain_id": "research", "supported": True},
        {"domain_id": "sandbox_execution", "supported": True},
        {"domain_id": "streaming", "supported": True},
        {"domain_id": "artifacts", "supported": True},
        {"domain_id": "subagents", "supported": False},
    ],
    "limitations": [
        f"max_steps={DYNAMIC_NATIVE_MAX_STEPS}",
        f"timeout={DYNAMIC_NATIVE_TIMEOUT}s",
        f"model={DYNAMIC_NATIVE_MODEL}",
    ],
    "tools": [tool["name"] for tool in default_mcp_server.list_tools()],
}

_RUNTIMES = {"native": _NATIVE_RUNTIME}


async def list_runtimes(_request: Request) -> JSONResponse:
    role_error = require_request_role(_request, "viewer")
    if role_error is not None:
        return role_error
    payload = {"runtimes": list(_RUNTIMES.values())}
    auth_context = getattr(getattr(_request, "state", None), "auth_context", None)
    record_api_audit(
        _request,
        action="runtimes.read",
        outcome="success",
        tenant_id=str(auth_context.tenant_id if auth_context else ""),
        workspace_id=str(auth_context.workspace_id if auth_context else ""),
        resource_type="runtime_inventory",
        metadata={"runtime_count": len(payload["runtimes"])},
    )
    return JSONResponse(payload)


async def get_runtime_capabilities(request: Request) -> JSONResponse:
    role_error = require_request_role(request, "viewer")
    if role_error is not None:
        return role_error
    runtime_id = request.path_params["runtime_id"]
    manifest = _RUNTIMES.get(runtime_id)
    if manifest is None:
        return JSONResponse({"error": "runtime not found", "runtime_id": runtime_id}, status_code=404)
    auth_context = getattr(getattr(request, "state", None), "auth_context", None)
    record_api_audit(
        request,
        action="runtime.capabilities.read",
        outcome="success",
        tenant_id=str(auth_context.tenant_id if auth_context else ""),
        workspace_id=str(auth_context.workspace_id if auth_context else ""),
        resource_type="runtime_capabilities",
        resource_id=runtime_id,
        metadata={"domain_count": len(manifest.get("domains", []))},
    )
    return JSONResponse(manifest)
