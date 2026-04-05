"""Tests for diagnostics and conformance endpoints."""
from __future__ import annotations

import asyncio
import json

from starlette.requests import Request

from src.api.routers.diagnostics_router import get_conformance, get_diagnostics


def _make_request(path: str) -> Request:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": b"",
            "path_params": {},
            "headers": [],
        },
        receive=receive,
    )


def test_get_diagnostics_returns_environment_and_dependency_summary():
    response = asyncio.run(get_diagnostics(_make_request("/api/diagnostics")))
    assert response.status_code == 200
    body = json.loads(response.body.decode())
    assert body["service"] == "lite-interpreter-api"
    assert "lite_interpreter_env_active" in body["environment"]
    assert "runtime_mode" in body["environment"]
    assert "deerflow_client_importable" in body["dependencies"]
    assert "mcp_tool_count" in body["capabilities"]
    assert body["capabilities"]["preset_skill_count"] >= 1
    assert "state_repo" in body["repositories"]
    assert "skill_repo" in body["repositories"]
    assert "startup_recovery" in body
    assert "task_leases" in body["startup_recovery"]


def test_get_conformance_returns_runtime_summary():
    response = asyncio.run(get_conformance(_make_request("/api/conformance")))
    assert response.status_code == 200
    body = json.loads(response.body.decode())
    assert body["status"] == "ok"
    assert body["summary"]["runtime_capability_manifest"] is True
    assert body["summary"]["execution_resource_layer"] is True
    assert body["summary"]["execution_event_model"] == "canonical"
    assert body["runtimes"]
    assert body["runtimes"][0]["runtime_id"] == "deerflow"
    assert "supports_attach_stream" in body["runtimes"][0]
    assert "supports_resume" in body["runtimes"][0]
