"""Integration tests for the local DeerFlow sidecar adapter script."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path

from starlette.requests import Request

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_deerflow_sidecar.py"


def _load_sidecar_module():
    spec = importlib.util.spec_from_file_location("run_deerflow_sidecar", _SCRIPT_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError("Failed to load DeerFlow sidecar script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _install_fake_deerflow_client(monkeypatch):
    fake_package = types.ModuleType("deerflow")
    fake_client_module = types.ModuleType("deerflow.client")

    class _FakeEvent:
        def __init__(self, event_type: str, data: dict[str, object]) -> None:
            self.type = event_type
            self.data = data

    class _FakeDeerFlowClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def chat(self, message: str, thread_id: str | None = None):
            return {
                "message": message,
                "thread_id": thread_id,
                "thinking_enabled": self.kwargs.get("thinking_enabled"),
            }

        def stream(self, message: str, **kwargs):
            yield _FakeEvent("messages-tuple", {"type": "ai", "content": f"echo:{message}"})
            yield _FakeEvent("values", {"thread_id": kwargs.get("thread_id"), "plan_mode": kwargs.get("plan_mode")})

    fake_client_module.DeerFlowClient = _FakeDeerFlowClient
    fake_package.client = fake_client_module
    monkeypatch.setitem(sys.modules, "deerflow", fake_package)
    monkeypatch.setitem(sys.modules, "deerflow.client", fake_client_module)


def _make_json_request(path: str, payload: dict[str, object]) -> Request:
    body = json.dumps(payload).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
        },
        receive=receive,
    )


def test_sidecar_health_endpoint_reports_service_metadata():
    module = _load_sidecar_module()
    response = asyncio.run(module.health(_make_json_request("/health", {})))

    assert response.status_code == 200
    body = json.loads(response.body.decode())
    assert body["status"] == "ok"
    assert body["service"] == "deerflow-sidecar"


def test_sidecar_chat_endpoint_uses_embedded_client_contract(monkeypatch):
    _install_fake_deerflow_client(monkeypatch)
    module = _load_sidecar_module()
    response = asyncio.run(
        module.chat(
            _make_json_request(
                "/v1/chat",
                {"message": "hello sidecar", "thread_id": "thread-1", "thinking_enabled": False},
            )
        )
    )

    assert response.status_code == 200
    body = json.loads(response.body.decode())
    assert body["response"]["message"] == "hello sidecar"
    assert body["response"]["thread_id"] == "thread-1"
    assert body["response"]["thinking_enabled"] is False
