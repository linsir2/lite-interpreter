"""Session login and identity inspection endpoints."""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from src.api.auth import (
    authenticate_user_credentials,
    request_auth_context,
)
from src.api.schemas import SessionLoginRequest, validation_error_payload
from pydantic import ValidationError


async def login_session(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "invalid json body"}, status_code=400)
    try:
        command = SessionLoginRequest.model_validate(body)
    except ValidationError as exc:
        return JSONResponse(validation_error_payload(exc), status_code=422)
    auth_context = authenticate_user_credentials(command.username, command.password)
    if auth_context is None:
        return JSONResponse({"error": "invalid credentials"}, status_code=403)
    return JSONResponse(
        {
            "authenticated": True,
            "access_token": auth_context.token,
            "token_type": "bearer",
            "subject": auth_context.subject,
            "role": auth_context.role,
            "auth_type": auth_context.auth_type,
            "grants": [
                {"tenant_id": grant.tenant_id, "workspace_id": grant.workspace_id}
                for grant in auth_context.grants
            ],
        }
    )


async def get_session_me(request: Request) -> JSONResponse:
    auth_context = request_auth_context(request)
    if auth_context is None:
        return JSONResponse({"error": "authentication required"}, status_code=401)
    return JSONResponse(
        {
            "authenticated": True,
            "subject": auth_context.subject,
            "role": auth_context.role,
            "auth_type": auth_context.auth_type,
            "grants": [
                {"tenant_id": grant.tenant_id, "workspace_id": grant.workspace_id}
                for grant in auth_context.grants
            ],
        }
    )
