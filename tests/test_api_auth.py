"""Tests for API authentication and auth-bound scope handling."""

from __future__ import annotations

import asyncio
import json

from src.api.auth import AuthContext, AuthGrant, authenticate_request, request_bearer_token
from src.api.routers.analysis_router import create_task, get_task_result
from src.api.routers.diagnostics_router import get_conformance, get_diagnostics
from src.api.routers.policy_router import get_harness_policy
from src.api.routers.session_router import get_session_me, login_session
from src.api.routers.sse_router import trigger_demo_trace
from src.blackboard import ExecutionData, GlobalStatus, execution_blackboard, global_blackboard
from starlette.requests import Request


def _make_request(
    *,
    method: str,
    path: str,
    body: dict | None = None,
    path_params: dict[str, str] | None = None,
    query_string: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
    auth_context: AuthContext | None = None,
) -> Request:
    payload = json.dumps(body or {}).encode()

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": query_string,
        "path_params": path_params or {},
        "headers": headers or [],
    }
    if auth_context is not None:
        scope["state"] = {"auth_context": auth_context}
    return Request(scope, receive=receive)


def test_request_bearer_token_reads_query_access_token():
    request = _make_request(
        method="GET",
        path="/api/tasks/task-1/events",
        query_string=b"access_token=query-token",
    )
    assert request_bearer_token(request) == "query-token"


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


def test_login_session_returns_bearer_token_for_configured_user(monkeypatch):
    monkeypatch.setattr(
        "src.api.auth.API_AUTH_USERS",
        {
            "alice": {
                "password": "secret",
                "role": "admin",
                "subject": "alice-user",
                "grants": [
                    {"tenant_id": "tenant-a", "workspace_id": "ws-a"},
                    {"tenant_id": "tenant-b", "workspace_id": "ws-b"},
                ],
            }
        },
    )
    request = _make_request(
        method="POST",
        path="/api/session/login",
        body={"username": "alice", "password": "secret"},
        headers=[(b"content-type", b"application/json")],
    )
    response = asyncio.run(login_session(request))
    body = json.loads(response.body.decode())
    assert response.status_code == 200
    assert body["authenticated"] is True
    assert body["role"] == "admin"
    assert len(body["grants"]) == 2
    assert body["access_token"].startswith("lis.")


def test_session_me_returns_authenticated_identity():
    request = _make_request(
        method="GET",
        path="/api/session/me",
        auth_context=AuthContext(
            token="lis.token",
            subject="alice-user",
            tenant_id="tenant-a",
            workspace_id="ws-a",
            role="admin",
            grants=(AuthGrant("tenant-a", "ws-a"), AuthGrant("tenant-b", "ws-b")),
            auth_type="session",
        ),
    )
    response = asyncio.run(get_session_me(request))
    body = json.loads(response.body.decode())
    assert response.status_code == 200
    assert body["subject"] == "alice-user"
    assert body["auth_type"] == "session"
    assert len(body["grants"]) == 2


def test_create_task_rejects_scope_forbidden_when_auth_scope_mismatches():
    request = _make_request(
        method="POST",
        path="/api/tasks",
        body={
            "tenant_id": "tenant-other",
            "workspace_id": "ws-other",
            "input_query": "please analyze",
            "autorun": False,
        },
        headers=[(b"content-type", b"application/json")],
        auth_context=AuthContext(
            token="secret",
            subject="operator-user",
            tenant_id="tenant-auth",
            workspace_id="ws-auth",
        ),
    )
    response = asyncio.run(create_task(request))
    body = json.loads(response.body.decode())
    assert response.status_code == 403
    assert body["error"] == "scope forbidden"


def test_create_task_rejects_insufficient_role_for_viewer():
    request = _make_request(
        method="POST",
        path="/api/tasks",
        body={
            "tenant_id": "tenant-auth",
            "workspace_id": "ws-auth",
            "input_query": "please analyze",
            "autorun": False,
        },
        headers=[(b"content-type", b"application/json")],
        auth_context=AuthContext(
            token="secret",
            subject="viewer-user",
            tenant_id="tenant-auth",
            workspace_id="ws-auth",
            role="viewer",
        ),
    )
    response = asyncio.run(create_task(request))
    body = json.loads(response.body.decode())
    assert response.status_code == 403
    assert body["error"] == "insufficient role"
    assert body["required_role"] == "operator"


def test_get_task_result_uses_auth_bound_scope_without_query_params():
    tenant_id = "tenant-auth-bound"
    workspace_id = "ws-auth-bound"
    task_id = global_blackboard.create_task(tenant_id, workspace_id, "please summarize")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            control={
                "task_envelope": {
                    "task_id": task_id,
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "input_query": "please summarize",
                    "governance_profile": "researcher",
                },
                "final_response": {"mode": "static", "headline": "done", "answer": "done", "key_findings": []},
            },
        ),
    )
    global_blackboard.update_global_status(task_id, GlobalStatus.SUCCESS)

    request = _make_request(
        method="GET",
        path=f"/api/tasks/{task_id}/result",
        path_params={"task_id": task_id},
        auth_context=AuthContext(
            token="secret",
            subject="viewer-user",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            role="viewer",
        ),
    )
    response = asyncio.run(get_task_result(request))
    body = json.loads(response.body.decode())

    assert response.status_code == 200
    assert body["task"]["task_id"] == task_id
    assert body["response"]["headline"] == "done"


def test_get_task_result_allows_explicit_scope_from_multi_grant_session():
    tenant_id = "tenant-multi-b"
    workspace_id = "ws-multi-b"
    task_id = global_blackboard.create_task(tenant_id, workspace_id, "please summarize")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            control={
                "task_envelope": {
                    "task_id": task_id,
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "input_query": "please summarize",
                    "governance_profile": "researcher",
                },
                "final_response": {"mode": "static", "headline": "done", "answer": "done", "key_findings": []},
            },
        ),
    )
    global_blackboard.update_global_status(task_id, GlobalStatus.SUCCESS)
    request = _make_request(
        method="GET",
        path=f"/api/tasks/{task_id}/result",
        path_params={"task_id": task_id},
        query_string=b"tenant_id=tenant-multi-b&workspace_id=ws-multi-b",
        auth_context=AuthContext(
            token="lis.token",
            subject="alice-user",
            tenant_id="tenant-multi-a",
            workspace_id="ws-multi-a",
            role="viewer",
            grants=(AuthGrant("tenant-multi-a", "ws-multi-a"), AuthGrant("tenant-multi-b", "ws-multi-b")),
            auth_type="session",
        ),
    )
    response = asyncio.run(get_task_result(request))
    assert response.status_code == 200


def test_policy_endpoint_requires_admin_role(monkeypatch):
    monkeypatch.setattr("src.api.routers.policy_router.API_ENABLE_POLICY_API", True)
    request = _make_request(
        method="GET",
        path="/api/policy",
        auth_context=AuthContext(
            token="secret",
            subject="operator-user",
            tenant_id="tenant-auth",
            workspace_id="ws-auth",
            role="operator",
        ),
    )
    response = asyncio.run(get_harness_policy(request))
    body = json.loads(response.body.decode())
    assert response.status_code == 403
    assert body["required_role"] == "admin"


def test_diagnostics_endpoint_requires_admin_role(monkeypatch):
    monkeypatch.setattr("src.api.routers.diagnostics_router.API_ENABLE_DIAGNOSTICS", True)
    request = _make_request(
        method="GET",
        path="/api/diagnostics",
        auth_context=AuthContext(
            token="secret",
            subject="operator-user",
            tenant_id="tenant-auth",
            workspace_id="ws-auth",
            role="operator",
        ),
    )
    response = asyncio.run(get_diagnostics(request))
    body = json.loads(response.body.decode())
    assert response.status_code == 403
    assert body["required_role"] == "admin"


def test_conformance_endpoint_allows_viewer_role():
    request = _make_request(
        method="GET",
        path="/api/conformance",
        auth_context=AuthContext(
            token="secret",
            subject="viewer-user",
            tenant_id="tenant-auth",
            workspace_id="ws-auth",
            role="viewer",
        ),
    )
    response = asyncio.run(get_conformance(request))
    assert response.status_code == 200


def test_demo_trace_endpoint_requires_admin_role(monkeypatch):
    monkeypatch.setattr("src.api.routers.sse_router.API_ENABLE_DEMO_TRACE", True)
    task_id = global_blackboard.create_task("tenant-auth", "ws-auth", "demo task")
    request = _make_request(
        method="POST",
        path=f"/api/dev/tasks/{task_id}/demo-trace",
        path_params={"task_id": task_id},
        headers=[(b"content-type", b"application/json")],
        body={"tenant_id": "tenant-auth", "workspace_id": "ws-auth"},
        auth_context=AuthContext(
            token="secret",
            subject="operator-user",
            tenant_id="tenant-auth",
            workspace_id="ws-auth",
            role="operator",
        ),
    )
    response = asyncio.run(trigger_demo_trace(request))
    body = json.loads(response.body.decode())
    assert response.status_code == 403
    assert body["required_role"] == "admin"
