"""Unit tests for the DeerFlow sidecar bridge."""

from __future__ import annotations

import json
import sys
import threading
import types
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda: None))

from src.dynamic_engine.deerflow_bridge import (  # noqa: E402
    DeerflowBridge,
    DeerflowRuntimeConfig,
    DeerflowTaskRequest,
)


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


class _SidecarRequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        content_length = int(self.headers.get("content-length", "0") or 0)
        self.server.last_body = self.rfile.read(content_length).decode("utf-8")  # type: ignore[attr-defined]
        if self.path != "/v1/stream":
            self.send_response(404)
            self.end_headers()
            return
        body = ("\n".join(self.server.response_lines) + "\n").encode("utf-8")  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def log_message(self, format, *args):  # noqa: A003
        return


@contextmanager
def _run_fake_sidecar(lines: list[str]):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SidecarRequestHandler)
    server.response_lines = lines  # type: ignore[attr-defined]
    server.last_body = ""  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", server
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


class DeerflowBridgeTests(unittest.TestCase):
    def test_run_uses_sidecar_stream_when_configured(self):
        bridge = DeerflowBridge(
            runtime_config=DeerflowRuntimeConfig(
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
            metadata={
                "continuation": "resume_static",
                "next_static_steps": ["analyst"],
                "skip_static_steps": ["analyst"],
                "evidence_refs": ["dynamic-evidence"],
                "open_questions": ["which policy applies?"],
                "suggested_static_actions": ["use rule audit"],
                "recommended_static_action": "生成规则审计",
                "strategy_family": "document_rule_audit",
            },
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
        self.assertEqual(result.continuation, "resume_static")
        self.assertEqual(result.next_static_steps, ["analyst"])
        self.assertEqual(result.skip_static_steps, ["analyst"])
        self.assertIn("dynamic-evidence", result.evidence_refs)
        self.assertIn("which policy applies?", result.open_questions)
        self.assertEqual(result.suggested_static_actions, ["use rule audit"])
        self.assertEqual(result.recommended_static_action, "生成规则审计")
        self.assertEqual(result.strategy_family, "document_rule_audit")
        self.assertIn("sidecar answer", result.summary)
        self.assertIn("/tmp/sidecar.md", result.artifacts)
        self.assertEqual(result.trace_refs, ["deerflow-sidecar:task-3"])
        self.assertEqual(result.runtime_metadata["effective_runtime_mode"], "sidecar")
        state_patch = result.to_state_patch()
        self.assertEqual(state_patch["dynamic_resume_overlay"]["evidence_refs"][0], "dynamic-evidence")
        self.assertEqual(state_patch["dynamic_resume_overlay"]["strategy_family"], "document_rule_audit")

    def test_run_uses_sidecar_over_real_local_http_transport(self):
        sidecar_lines = [
            '{"type":"messages-tuple","data":{"type":"ai","content":"sidecar transport answer"}}',
            '{"type":"values","data":{"artifacts":[{"path":"/tmp/transport.md"}]}}',
        ]
        try:
            with _run_fake_sidecar(sidecar_lines) as (sidecar_url, server):
                bridge = DeerflowBridge(
                    runtime_config=DeerflowRuntimeConfig(
                        sidecar_url=sidecar_url,
                        config_path="",
                        max_events=8,
                    )
                )
                request = DeerflowTaskRequest(
                    task_id="task-sidecar-transport",
                    tenant_id="tenant-sidecar-transport",
                    query="analyze something",
                    system_context={"constraints": {}},
                )
                result = bridge.run(request)
        except PermissionError:
            self.skipTest("Local TCP bind unavailable in current environment")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.continuation, "finish")
        self.assertIn("sidecar transport answer", result.summary)
        self.assertIn("/tmp/transport.md", result.artifacts)
        self.assertEqual(result.trace_refs, ["deerflow-sidecar:task-sidecar-transport"])
        self.assertEqual(result.runtime_metadata["effective_runtime_mode"], "sidecar")
        payload = json.loads(server.last_body)  # type: ignore[attr-defined]
        self.assertEqual(payload["thread_id"], "lite-interpreter-task-sidecar-transport")
        self.assertIn("Task:", payload["message"])

    def test_run_sidecar_mode_returns_unavailable_result_when_sidecar_fails(self):
        bridge = DeerflowBridge(
            runtime_config=DeerflowRuntimeConfig(
                sidecar_url="http://127.0.0.1:8765",
                max_events=8,
            )
        )
        request = DeerflowTaskRequest(
            task_id="task-5",
            tenant_id="tenant-5",
            query="analyze something",
            system_context={"constraints": {}},
        )
        with patch("src.dynamic_engine.deerflow_bridge.httpx.stream", side_effect=RuntimeError("sidecar down")):
            result = bridge.run(request)

        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.continuation, "finish")
        self.assertIn("Failed to reach DeerFlow sidecar", result.summary)
        self.assertEqual(result.trace_refs, ["dynamic-preview:task-5"])
        self.assertEqual(result.runtime_metadata["requested_runtime_mode"], "sidecar")
        self.assertEqual(result.runtime_metadata["effective_runtime_mode"], "unavailable")
        self.assertIn("sidecar down", result.runtime_metadata["sidecar_fallback_reason"])
        self.assertEqual(result.runtime_metadata["sidecar_url"], "http://127.0.0.1:8765")


if __name__ == "__main__":
    unittest.main()
