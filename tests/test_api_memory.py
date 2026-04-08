"""Tests for the task memory endpoint."""
from __future__ import annotations

import asyncio
import json

from src.api.routers.memory_router import get_task_memory
from src.blackboard import MemoryData, global_blackboard, memory_blackboard
from starlette.requests import Request


def _make_request(task_id: str, *, tenant_id: str, workspace_id: str) -> Request:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/api/tasks/{task_id}/memory",
            "query_string": f"tenant_id={tenant_id}&workspace_id={workspace_id}".encode(),
            "path_params": {"task_id": task_id},
            "headers": [],
        },
        receive=receive,
    )


def test_get_task_memory_returns_task_scoped_memory_snapshot():
    tenant_id = "tenant-memory-api"
    task_id = global_blackboard.create_task(tenant_id, "ws-memory-api", "please summarize")
    memory_blackboard.write(
        tenant_id,
        task_id,
        MemoryData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id="ws-memory-api",
            approved_skills=[{"name": "memory-skill"}],
            historical_matches=[{"name": "memory-history"}],
            task_summary={"headline": "memory headline", "answer": "memory answer"},
        ),
    )

    response = asyncio.run(get_task_memory(_make_request(task_id, tenant_id=tenant_id, workspace_id="ws-memory-api")))
    body = json.loads(response.body.decode())

    assert response.status_code == 200
    assert body["memory"]["approved_skills"][0]["name"] == "memory-skill"
    assert body["memory"]["historical_matches"][0]["name"] == "memory-history"
    assert body["memory"]["task_summary"]["headline"] == "memory headline"
