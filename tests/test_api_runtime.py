"""Tests for runtime capability inspection endpoints."""

from __future__ import annotations

import asyncio
import json

from src.api.routers.runtime_router import get_runtime_capabilities, list_runtimes
from starlette.requests import Request


def _make_request(path: str, runtime_id: str | None = None) -> Request:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": b"",
            "path_params": {"runtime_id": runtime_id} if runtime_id is not None else {},
            "headers": [],
        },
        receive=receive,
    )


def test_list_runtimes_returns_runtime_summaries():
    response = asyncio.run(list_runtimes(_make_request("/api/runtimes")))
    assert response.status_code == 200
    body = json.loads(response.body.decode())
    assert body["runtimes"]
    assert body["runtimes"][0]["runtime_id"] == "deerflow"
    assert any(domain["domain_id"] == "research" for domain in body["runtimes"][0]["domains"])


def test_get_runtime_capabilities_returns_manifest():
    response = asyncio.run(get_runtime_capabilities(_make_request("/api/runtimes/deerflow/capabilities", "deerflow")))
    assert response.status_code == 200
    body = json.loads(response.body.decode())
    assert body["runtime_id"] == "deerflow"
    assert "sidecar" in body["runtime_modes"]


def test_get_runtime_capabilities_returns_404_for_missing_runtime():
    response = asyncio.run(get_runtime_capabilities(_make_request("/api/runtimes/missing/capabilities", "missing")))
    assert response.status_code == 404
    body = json.loads(response.body.decode())
    assert body["runtime_id"] == "missing"
