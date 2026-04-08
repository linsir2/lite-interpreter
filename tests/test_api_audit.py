"""Tests for audit log recording and query APIs."""
from __future__ import annotations

import asyncio
import json

from src.api.auth import AuthContext
from src.api.routers.analysis_router import create_task
from src.api.routers.audit_router import list_audit_logs
from src.api.routers.diagnostics_router import get_diagnostics
from src.api.routers.policy_router import update_harness_policy
from src.common.contracts import AuditRecord
from src.storage.repository.audit_repo import AuditRepo
from starlette.requests import Request


def _make_request(
    *,
    method: str,
    path: str,
    body: dict | None = None,
    query_params: dict[str, str] | None = None,
    auth_context: AuthContext | None = None,
) -> Request:
    payload = json.dumps(body or {}).encode()

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    query_string = "&".join(
        f"{key}={value}"
        for key, value in (query_params or {}).items()
    ).encode()
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": query_string,
        "path_params": {},
        "headers": [(b"content-type", b"application/json")] if body is not None else [],
    }
    if auth_context is not None:
        scope["state"] = {"auth_context": auth_context}
    return Request(scope, receive=receive)


def test_create_task_records_audit_log():
    auth_context = AuthContext(
        token="operator-token",
        subject="operator-user",
        tenant_id="tenant-audit",
        workspace_id="ws-audit",
        role="operator",
    )
    response = asyncio.run(
        create_task(
            _make_request(
                method="POST",
                path="/api/tasks",
                body={
                    "tenant_id": "tenant-audit",
                    "workspace_id": "ws-audit",
                    "input_query": "please analyze",
                    "autorun": False,
                },
                auth_context=auth_context,
            )
        )
    )
    body = json.loads(response.body.decode())
    assert response.status_code == 200
    records = AuditRepo.list_records("tenant-audit", "ws-audit")
    assert records[0]["action"] == "task.create"
    assert records[0]["subject"] == "operator-user"
    assert records[0]["resource_id"] == body["task_id"]


def test_list_audit_logs_requires_admin_role():
    response = asyncio.run(
        list_audit_logs(
            _make_request(
                method="GET",
                path="/api/audit/logs",
                query_params={"tenant_id": "tenant-audit", "workspace_id": "ws-audit"},
                auth_context=AuthContext(
                    token="viewer-token",
                    subject="viewer-user",
                    tenant_id="tenant-audit",
                    workspace_id="ws-audit",
                    role="viewer",
                ),
            )
        )
    )
    body = json.loads(response.body.decode())
    assert response.status_code == 403
    assert body["required_role"] == "admin"


def test_list_audit_logs_returns_filtered_records(monkeypatch, tmp_path):
    auth_context = AuthContext(
        token="admin-token",
        subject="admin-user",
        tenant_id="tenant-audit",
        workspace_id="ws-audit",
        role="admin",
    )
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text("mode: standard\nprofiles: {}\n", encoding="utf-8")
    monkeypatch.setattr("src.api.routers.policy_router.HARNESS_POLICY_PATH", policy_file)
    monkeypatch.setattr("src.harness.policy.HARNESS_POLICY_PATH", policy_file)
    monkeypatch.setattr("src.api.routers.policy_router.API_ENABLE_POLICY_API", True)
    monkeypatch.setattr("src.api.routers.diagnostics_router.API_ENABLE_DIAGNOSTICS", True)

    asyncio.run(
        update_harness_policy(
            _make_request(
                method="POST",
                path="/api/policy",
                body={"policy": {"mode": "core", "profiles": {}}},
                auth_context=auth_context,
            )
        )
    )
    asyncio.run(
        get_diagnostics(
            _make_request(
                method="GET",
                path="/api/diagnostics",
                auth_context=auth_context,
            )
        )
    )

    response = asyncio.run(
        list_audit_logs(
            _make_request(
                method="GET",
                path="/api/audit/logs",
                query_params={
                    "tenant_id": "tenant-audit",
                    "workspace_id": "ws-audit",
                    "action": "policy.update",
                },
                auth_context=auth_context,
            )
        )
    )
    body = json.loads(response.body.decode())
    assert response.status_code == 200
    assert len(body["records"]) == 1
    assert body["records"][0]["action"] == "policy.update"
    assert body["records"][0]["subject"] == "admin-user"


def test_list_audit_logs_supports_subject_and_resource_filters():
    AuditRepo.append_record(
        AuditRecord(
            audit_id="audit-1",
            subject="alice-user",
            role="admin",
            action="policy.update",
            outcome="success",
            tenant_id="tenant-audit",
            workspace_id="ws-audit",
            request_method="POST",
            request_path="/api/policy",
            resource_type="policy",
            resource_id="config/harness_policy.yaml",
            metadata={},
        )
    )
    AuditRepo.append_record(
        AuditRecord(
            audit_id="audit-2",
            subject="bob-user",
            role="operator",
            action="task.create",
            outcome="success",
            tenant_id="tenant-audit",
            workspace_id="ws-audit",
            request_method="POST",
            request_path="/api/tasks",
            resource_type="task",
            resource_id="task-1",
            metadata={},
        )
    )
    auth_context = AuthContext(
        token="admin-token",
        subject="admin-user",
        tenant_id="tenant-audit",
        workspace_id="ws-audit",
        role="admin",
    )
    response = asyncio.run(
        list_audit_logs(
            _make_request(
                method="GET",
                path="/api/audit/logs",
                query_params={
                    "tenant_id": "tenant-audit",
                    "workspace_id": "ws-audit",
                    "subject": "alice-user",
                    "resource_type": "policy",
                },
                auth_context=auth_context,
            )
        )
    )
    body = json.loads(response.body.decode())
    assert response.status_code == 200
    assert len(body["records"]) == 1
    assert body["records"][0]["subject"] == "alice-user"
    assert body["records"][0]["resource_type"] == "policy"
