"""Policy management endpoints for harness policy inspection and updates."""
from __future__ import annotations

from pathlib import Path

import yaml
from config.settings import API_ENABLE_POLICY_API, HARNESS_POLICY_PATH
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.api.audit_logging import record_api_audit
from src.api.auth import require_request_role
from src.api.schemas import PolicyUpdateRequest, validation_error_payload
from src.api.request_scope import endpoint_disabled
from src.harness.policy import load_harness_policy, refresh_harness_policy


async def get_harness_policy(_request: Request) -> JSONResponse:
    role_error = require_request_role(_request, "admin")
    if role_error is not None:
        return role_error
    if not API_ENABLE_POLICY_API:
        return endpoint_disabled("policy api disabled")
    policy = load_harness_policy()
    path = Path(HARNESS_POLICY_PATH)
    record_api_audit(
        _request,
        action="policy.read",
        outcome="success",
        tenant_id=str(getattr(getattr(_request, "state", None), "auth_context", None).tenant_id if getattr(getattr(_request, "state", None), "auth_context", None) else ""),
        workspace_id=str(getattr(getattr(_request, "state", None), "auth_context", None).workspace_id if getattr(getattr(_request, "state", None), "auth_context", None) else ""),
        resource_type="policy",
        resource_id=str(path),
        metadata={"exists": path.exists()},
    )
    return JSONResponse(
        {
            "path": str(path),
            "exists": path.exists(),
            "policy": policy,
        }
    )


async def update_harness_policy(request: Request) -> JSONResponse:
    role_error = require_request_role(request, "admin")
    if role_error is not None:
        return role_error
    if not API_ENABLE_POLICY_API:
        return endpoint_disabled("policy api disabled")
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "invalid json body"}, status_code=400)
    try:
        command = PolicyUpdateRequest.model_validate(body)
    except ValidationError as exc:
        return JSONResponse(validation_error_payload(exc), status_code=422)

    path = Path(HARNESS_POLICY_PATH)

    def _persist_policy() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if command.policy is not None:
            path.write_text(
                yaml.safe_dump(command.policy, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            return
        yaml_text = str(command.yaml or "")
        parsed = yaml.safe_load(yaml_text)
        if not isinstance(parsed, dict):
            raise ValueError("policy yaml must parse to a mapping")
        path.write_text(yaml_text, encoding="utf-8")

    try:
        _persist_policy()
    except (ValueError, yaml.YAMLError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    policy = refresh_harness_policy()
    auth_context = getattr(getattr(request, "state", None), "auth_context", None)
    record_api_audit(
        request,
        action="policy.update",
        outcome="success",
        tenant_id=str(auth_context.tenant_id if auth_context else ""),
        workspace_id=str(auth_context.workspace_id if auth_context else ""),
        resource_type="policy",
        resource_id=str(path),
        metadata={"updated": True},
    )
    return JSONResponse(
        {
            "updated": True,
            "path": str(path),
            "policy": policy,
        }
    )
