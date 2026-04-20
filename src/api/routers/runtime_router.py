"""Runtime capability inspection endpoints."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from src.api.audit_logging import record_api_audit
from src.api.auth import require_request_role
from src.dynamic_engine.runtime_backends import get_runtime_manifest, list_runtime_manifests


async def list_runtimes(_request: Request) -> JSONResponse:
    role_error = require_request_role(_request, "viewer")
    if role_error is not None:
        return role_error
    manifests = list_runtime_manifests()
    payload = {
        "runtimes": [
            {
                "runtime_id": manifest.runtime_id,
                "display_name": manifest.display_name,
                "description": manifest.description,
                "runtime_modes": manifest.runtime_modes,
                "domains": [
                    {
                        "domain_id": domain.domain_id,
                        "supported": domain.supported,
                    }
                    for domain in manifest.domains
                ],
                "limitations": manifest.limitations,
            }
            for manifest in manifests
        ]
    }
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
    try:
        manifest = get_runtime_manifest(runtime_id)
    except KeyError:
        return JSONResponse({"error": "runtime not found", "runtime_id": runtime_id}, status_code=404)
    payload = manifest.model_dump(mode="json")
    auth_context = getattr(getattr(request, "state", None), "auth_context", None)
    record_api_audit(
        request,
        action="runtime.capabilities.read",
        outcome="success",
        tenant_id=str(auth_context.tenant_id if auth_context else ""),
        workspace_id=str(auth_context.workspace_id if auth_context else ""),
        resource_type="runtime_capabilities",
        resource_id=runtime_id,
        metadata={"domain_count": len(payload.get("domains", []))},
    )
    return JSONResponse(payload)
