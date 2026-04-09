"""Unit tests for the DeerFlow bridge using a stub embedded client."""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda: None))

from src.dynamic_engine.deerflow_bridge import (  # noqa: E402
    DeerflowBridge,
    DeerflowRuntimeConfig,
    DeerflowTaskRequest,
)


class _FakeEvent:
    def __init__(self, event_type: str, data: dict):
        self.type = event_type
        self.data = data


class _FakeDeerFlowClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def stream(self, message: str, **kwargs):
        yield _FakeEvent(
            "messages-tuple",
            {"type": "ai", "content": "dynamic answer", "id": "ai-1"},
        )
        yield _FakeEvent(
            "values",
            {"artifacts": [{"path": "/tmp/report.md"}]},
        )
        yield _FakeEvent("end", {"usage": {"total_tokens": 10}})


class _FakeStreamResponse:
    def __init__(self, status_code: int, lines: list[str]):
        self.status_code = status_code
        self._lines = lines

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status={self.status_code}")

    def iter_lines(self):
        yield from self._lines

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class DeerflowBridgeTests(unittest.TestCase):
    def test_run_returns_degraded_result_when_package_is_missing(self):
        bridge = DeerflowBridge(
            runtime_config=DeerflowRuntimeConfig(
                module_name="missing.deerflow.client",
            )
        )
        result = bridge.run(
            DeerflowTaskRequest(
                task_id="task-1",
                tenant_id="tenant-1",
                query="analyze something",
                system_context={"constraints": {}},
            )
        )
        self.assertEqual(result.status, "unavailable")
        self.assertTrue(result.trace)
        self.assertEqual(result.runtime_metadata["effective_runtime_mode"], "unavailable")

    def test_run_uses_embedded_client_when_import_succeeds(self):
        bridge = DeerflowBridge(
            runtime_config=DeerflowRuntimeConfig(
                module_name="deerflow.client",
                runtime_mode="embedded",
                config_path=str(Path(__file__)),
                max_events=8,
            )
        )
        request = DeerflowTaskRequest(
            task_id="task-2",
            tenant_id="tenant-2",
            query="analyze something",
            system_context={
                "constraints": {
                    "network_boundary": {
                        "platform_network_access": "tool-mediated-only",
                        "sandbox_network_access": "disabled",
                    }
                }
            },
        )
        fake_module = types.SimpleNamespace(DeerFlowClient=_FakeDeerFlowClient)
        with patch("importlib.import_module", return_value=fake_module):
            result = bridge.run(request)

        self.assertEqual(result.status, "completed")
        self.assertIn("dynamic answer", result.summary)
        self.assertIn("/tmp/report.md", result.artifacts)
        self.assertEqual(result.trace_refs, ["deerflow:lite-interpreter-task-2"])
        self.assertEqual(bridge.build_payload(request)["runtime"]["python_package"], "deerflow.client")
        self.assertEqual(result.runtime_metadata["effective_runtime_mode"], "embedded")

    def test_run_uses_sidecar_stream_when_configured(self):
        bridge = DeerflowBridge(
            runtime_config=DeerflowRuntimeConfig(
                runtime_mode="sidecar",
                sidecar_url="http://127.0.0.1:8765",
                config_path="",
                max_events=8,
            )
        )
        request = DeerflowTaskRequest(
            task_id="task-3",
            tenant_id="tenant-3",
            query="analyze something",
            system_context={"constraints": {}},
        )
        sidecar_lines = [
            '{"type":"messages-tuple","data":{"type":"ai","content":"sidecar answer"}}',
            '{"type":"values","data":{"artifacts":[{"path":"/tmp/sidecar.md"}]}}',
            '{"type":"end","data":{"usage":{"total_tokens":1}}}',
        ]
        with patch(
            "src.dynamic_engine.deerflow_bridge.httpx.stream", return_value=_FakeStreamResponse(200, sidecar_lines)
        ):
            result = bridge.run(request)

        self.assertEqual(result.status, "completed")
        self.assertIn("sidecar answer", result.summary)
        self.assertIn("/tmp/sidecar.md", result.artifacts)
        self.assertEqual(result.trace_refs, ["deerflow-sidecar:task-3"])
        self.assertEqual(result.runtime_metadata["effective_runtime_mode"], "sidecar")

    def test_run_records_auto_sidecar_fallback_reason_when_embedded_succeeds(self):
        bridge = DeerflowBridge(
            runtime_config=DeerflowRuntimeConfig(
                module_name="deerflow.client",
                runtime_mode="auto",
                sidecar_url="http://127.0.0.1:8765",
                max_events=8,
            )
        )
        request = DeerflowTaskRequest(
            task_id="task-4",
            tenant_id="tenant-4",
            query="analyze something",
            system_context={"constraints": {}},
        )
        fake_module = types.SimpleNamespace(DeerFlowClient=_FakeDeerFlowClient)
        with patch("src.dynamic_engine.deerflow_bridge.httpx.stream", side_effect=RuntimeError("sidecar down")):
            with patch("importlib.import_module", return_value=fake_module):
                result = bridge.run(request)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.runtime_metadata["effective_runtime_mode"], "embedded")
        self.assertEqual(result.runtime_metadata["requested_runtime_mode"], "auto")
        self.assertIn("sidecar down", result.runtime_metadata["sidecar_fallback_reason"])


if __name__ == "__main__":
    unittest.main()
