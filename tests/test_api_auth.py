"""Tests for bearer-token auth helpers and app-facing session bootstrap."""

from __future__ import annotations

import asyncio
import json

from src.api.auth import AuthContext, authenticate_request, request_bearer_token
from src.api.routers.app_router import get_app_session
from starlette.requests import Request


def _make_request(
    *,
    method: str,
    path: str,
    query_string: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
    auth_context: AuthContext | None = None,
) -> Request:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": query_string,
        "path_params": {},
        "headers": headers or [],
    }
    if auth_context is not None:
        scope["state"] = {"auth_context": auth_context, "auth_checked": True}
    return Request(scope, receive=receive)


def test_request_bearer_token_ignores_query_access_token():
    request = _make_request(
        method="GET",
        path="/api/app/session",
        query_string=b"access_token=query-token",
    )
    assert request_bearer_token(request) == ""


def test_authenticate_request_accepts_configured_bearer_token(monkeypatch):
    monkeypatch.setattr("src.api.auth.API_AUTH_REQUIRED", True)
    monkeypatch.setattr(
        "src.api.auth.API_AUTH_TOKENS",
        {"secret-token": {"tenant_id": "tenant-auth", "workspace_id": "ws-auth", "role": "operator"}},
    )
    request = _make_request(
        method="GET",
        path="/health",
        headers=[(b"authorization", b"Bearer secret-token")],
    )
    result = authenticate_request(request)
    assert isinstance(result, AuthContext)
    assert result.tenant_id == "tenant-auth"
    assert result.workspace_id == "ws-auth"
    assert result.subject == "secret-token"


def test_authenticate_request_returns_structured_error_for_invalid_token(monkeypatch):
    monkeypatch.setattr("src.api.auth.API_AUTH_REQUIRED", True)
    monkeypatch.setattr(
        "src.api.auth.API_AUTH_TOKENS",
        {"secret-token": {"tenant_id": "tenant-auth", "workspace_id": "ws-auth", "role": "operator"}},
    )
    request = _make_request(
        method="GET",
        path="/api/app/session",
        headers=[(b"authorization", b"Bearer wrong-token")],
    )
    response = authenticate_request(request)
    assert response is not None
    body = json.loads(response.body.decode())
    assert response.status_code == 403
    assert body["error"]["code"] == "INVALID_TOKEN"


def test_get_app_session_returns_authenticated_identity():
    request = _make_request(
        method="GET",
        path="/api/app/session",
        query_string=b"workspaceId=ws-a",
        auth_context=AuthContext(
            token="secret",
            subject="alice-user",
            tenant_id="tenant-a",
            workspace_id="ws-a",
            role="admin",
            grants=(),
            auth_type="token",
        ),
    )
    response = asyncio.run(get_app_session(request))
    body = json.loads(response.body.decode())
    assert response.status_code == 200
    assert body["subject"] == "alice-user"
    assert body["role"] == "admin"
