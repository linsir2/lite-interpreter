"""Tests for bearer-token auth helpers and app-facing session bootstrap."""

from __future__ import annotations

import asyncio
import json

from src.api.auth import AuthContext, authenticate_request, request_bearer_token, request_skips_auth
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


def test_get_app_session_bootstraps_local_session_when_auth_disabled(monkeypatch):
    monkeypatch.setattr("src.api.routers.app_router.auth_enabled", lambda: False)
    monkeypatch.setattr("src.api.routers.app_router.API_AUTH_REQUIRED", False)
    monkeypatch.setattr("src.api.request_scope.auth_enabled", lambda: False)
    monkeypatch.setattr("src.api.request_scope.API_LOCAL_TENANT_ID", "tenant-local")
    monkeypatch.setattr("src.api.request_scope.API_LOCAL_WORKSPACE_ID", "ws-local")

    request = _make_request(
        method="GET",
        path="/api/app/session",
    )
    response = asyncio.run(get_app_session(request))
    body = json.loads(response.body.decode())

    assert response.status_code == 200
    assert body["authenticated"] is True
    assert body["subject"] == "local-dev-session"
    assert body["role"] == "local"
    assert body["currentTenantId"] == "tenant-local"
    assert body["currentWorkspaceId"] == "ws-local"
    assert body["grants"] == [
        {
            "tenantId": "tenant-local",
            "workspaceId": "ws-local",
            "label": "ws-local",
        }
    ]


def test_request_skips_auth_for_cors_preflight_and_non_api_paths():
    homepage_request = _make_request(
        method="GET",
        path="/",
    )
    assert request_skips_auth(homepage_request) is True

    preflight_request = _make_request(
        method="OPTIONS",
        path="/api/app/session",
        headers=[
            (b"origin", b"http://127.0.0.1:5173"),
            (b"access-control-request-method", b"GET"),
            (b"access-control-request-headers", b"authorization,content-type"),
        ],
    )
    assert request_skips_auth(preflight_request) is True

    protected_api_request = _make_request(
        method="GET",
        path="/api/app/session",
    )
    assert request_skips_auth(protected_api_request) is False
