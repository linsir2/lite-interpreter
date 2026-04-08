"""Tests for execution resource endpoints."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from src.api.routers.execution_router import (
    get_execution,
    list_execution_artifacts,
    list_execution_tool_calls,
    list_task_executions,
    stream_execution_events,
)
from src.blackboard import ExecutionData, execution_blackboard, global_blackboard
from src.common import ArtifactRecord, EventTopic, ExecutionRecord, TraceEvent, event_journal
from starlette.requests import Request


def _make_request(
    path: str,
    *,
    task_id: str | None = None,
    execution_id: str | None = None,
    tenant_id: str = "tenant-default",
    workspace_id: str = "ws-default",
) -> Request:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    path_params = {}
    if task_id is not None:
        path_params["task_id"] = task_id
    if execution_id is not None:
        path_params["execution_id"] = execution_id

    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": f"tenant_id={tenant_id}&workspace_id={workspace_id}".encode(),
            "path_params": path_params,
            "headers": [],
        },
        receive=receive,
    )


def test_list_task_executions_returns_sandbox_execution():
    tenant_id = "tenant-execution-api"
    task_id = global_blackboard.create_task(tenant_id, "ws-execution-api", "run")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id="ws-execution-api",
            static={
                "execution_record": ExecutionRecord(
                    session_id="session-123",
                    tenant_id=tenant_id,
                    workspace_id="ws-execution-api",
                    task_id=task_id,
                    success=True,
                    trace_id="trace-123",
                    duration_seconds=0.4,
                    artifacts=[ArtifactRecord(path="/tmp/out", artifact_type="sandbox_output")],
                ),
            },
            knowledge={
                "knowledge_snapshot": {
                    "rewritten_query": "run",
                    "recall_strategies": ["bm25"],
                    "evidence_refs": ["chunk-1"],
                    "metadata": {"selected_count": 1},
                }
            },
        ),
    )

    response = asyncio.run(
        list_task_executions(
            _make_request(
                f"/api/tasks/{task_id}/executions",
                task_id=task_id,
                tenant_id=tenant_id,
                workspace_id="ws-execution-api",
            )
        )
    )
    body = json.loads(response.body.decode())

    assert response.status_code == 200
    assert body["executions"][0]["execution_id"] == "sandbox:session-123"
    assert body["executions"][0]["kind"] == "sandbox"
    assert body["executions"][0]["tool_call_count"] == 2


def test_list_task_executions_restores_execution_state_when_memory_is_cold():
    tenant_id = "tenant-execution-restore"
    task_id = global_blackboard.create_task(tenant_id, "ws-execution-restore", "run")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id="ws-execution-restore",
            static={
                "execution_record": ExecutionRecord(
                    session_id="session-restore",
                    tenant_id=tenant_id,
                    workspace_id="ws-execution-restore",
                    task_id=task_id,
                    success=True,
                    trace_id="trace-restore",
                    duration_seconds=0.2,
                )
            },
        ),
    )
    execution_blackboard.persist(tenant_id, task_id)
    execution_blackboard._storage.clear()

    response = asyncio.run(
        list_task_executions(
            _make_request(
                f"/api/tasks/{task_id}/executions",
                task_id=task_id,
                tenant_id=tenant_id,
                workspace_id="ws-execution-restore",
            )
        )
    )
    body = json.loads(response.body.decode())

    assert response.status_code == 200
    assert body["executions"][0]["execution_id"] == "sandbox:session-restore"


def test_list_execution_tool_calls_returns_static_sandbox_tool_calls():
    tenant_id = "tenant-static-tool-call-api"
    task_id = global_blackboard.create_task(tenant_id, "ws-static-tool-call-api", "summarize")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id="ws-static-tool-call-api",
            control={
                "task_envelope": {
                    "task_id": task_id,
                    "tenant_id": tenant_id,
                    "workspace_id": "ws-static-tool-call-api",
                    "input_query": "summarize",
                }
            },
            static={
                "execution_record": ExecutionRecord(
                    session_id="session-static-1",
                    tenant_id=tenant_id,
                    workspace_id="ws-static-tool-call-api",
                    task_id=task_id,
                    success=True,
                    trace_id="trace-static-1",
                    duration_seconds=0.3,
                )
            },
            knowledge={
                "knowledge_snapshot": {
                    "rewritten_query": "summarize",
                    "recall_strategies": ["bm25", "vector"],
                    "evidence_refs": ["chunk-1"],
                    "metadata": {"selected_count": 2},
                }
            },
        ),
    )
    execution_blackboard.persist(tenant_id, task_id)

    execution_id = "sandbox:session-static-1"
    response = asyncio.run(
        list_execution_tool_calls(
            _make_request(
                f"/api/executions/{execution_id}/tool-calls",
                execution_id=execution_id,
                tenant_id=tenant_id,
                workspace_id="ws-static-tool-call-api",
            )
        )
    )
    body = json.loads(response.body.decode())

    assert response.status_code == 200
    tool_names = [tool_call["tool_name"] for tool_call in body["tool_calls"]]
    assert "sandbox_exec" in tool_names
    assert "knowledge_query" in tool_names


def test_get_execution_returns_runtime_execution_and_artifacts():
    tenant_id = "tenant-runtime-execution-api"
    task_id = global_blackboard.create_task(tenant_id, "ws-runtime-execution-api", "dynamic")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id="ws-runtime-execution-api",
            dynamic={
                "runtime_backend": "deerflow",
                "status": "completed",
                "summary": "done",
                "runtime_metadata": {"effective_runtime_mode": "embedded", "sidecar_fallback_reason": "sidecar down"},
                "trace_refs": ["trace-runtime"],
                "artifacts": ["/tmp/runtime-report.md"],
                "trace": [
                    {
                        "event_type": "tool_call_start",
                        "source_event_type": "values",
                        "agent_name": "deerflow",
                        "step_name": "search",
                        "tool_call": {
                            "tool_name": "web_search",
                            "tool_call_id": "call-1",
                            "arguments": {"q": "dynamic"},
                        },
                        "payload": {
                            "tool_name": "web_search",
                            "tool_call_id": "call-1",
                            "arguments": {"q": "dynamic"},
                        },
                    }
                ],
            },
        ),
    )
    execution_blackboard.persist(tenant_id, task_id)

    execution_id = f"runtime:{task_id}"
    response = asyncio.run(
        get_execution(
            _make_request(
                f"/api/executions/{execution_id}",
                execution_id=execution_id,
                tenant_id=tenant_id,
                workspace_id="ws-runtime-execution-api",
            )
        )
    )
    body = json.loads(response.body.decode())

    assert response.status_code == 200
    assert body["execution_id"] == execution_id
    assert body["backend"] == "deerflow"
    assert body["runtime_metadata"]["effective_runtime_mode"] == "embedded"
    assert body["artifacts"][0]["path"] == "/tmp/runtime-report.md"
    assert body["tool_calls"][0]["tool_name"] == "web_search"


def test_list_execution_tool_calls_returns_runtime_tool_calls():
    tenant_id = "tenant-runtime-tool-call-api"
    task_id = global_blackboard.create_task(tenant_id, "ws-runtime-tool-call-api", "dynamic")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id="ws-runtime-tool-call-api",
            dynamic={
                "runtime_backend": "deerflow",
                "status": "completed",
                "trace": [
                    {
                        "event_type": "tool_result",
                        "source_event_type": "values",
                        "agent_name": "deerflow",
                        "step_name": "fetch",
                        "tool_call": {
                            "tool_name": "web_fetch",
                            "tool_call_id": "call-2",
                            "result": {"status": 200},
                            "status": "completed",
                        },
                        "payload": {
                            "tool_name": "web_fetch",
                            "tool_call_id": "call-2",
                            "result": {"status": 200},
                            "status": "completed",
                        },
                    }
                ],
            },
        ),
    )
    execution_blackboard.persist(tenant_id, task_id)

    execution_id = f"runtime:{task_id}"
    response = asyncio.run(
        list_execution_tool_calls(
            _make_request(
                f"/api/executions/{execution_id}/tool-calls",
                execution_id=execution_id,
                tenant_id=tenant_id,
                workspace_id="ws-runtime-tool-call-api",
            )
        )
    )
    body = json.loads(response.body.decode())

    assert response.status_code == 200
    assert body["tool_calls"][0]["tool_name"] == "web_fetch"
    assert body["tool_calls"][0]["phase"] == "result"


def test_list_execution_artifacts_returns_404_for_missing_execution():
    response = asyncio.run(
        list_execution_artifacts(
            _make_request("/api/executions/missing/artifacts", execution_id="missing")
        )
    )
    assert response.status_code == 404


def test_stream_execution_events_replays_runtime_backlog_and_supports_resume():
    event_journal.clear()
    tenant_id = "tenant-execution-stream"
    task_id = global_blackboard.create_task(tenant_id, "ws-execution-stream", "dynamic")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id="ws-execution-stream",
            dynamic={"runtime_backend": "deerflow", "status": "completed"},
        ),
    )
    execution_blackboard.persist(tenant_id, task_id)

    first_event = TraceEvent(
        event_id="evt-runtime-1",
        topic=EventTopic.UI_TASK_GOVERNANCE_UPDATE.value,
        tenant_id=tenant_id,
        task_id=task_id,
        workspace_id="ws-execution-stream",
        trace_id=task_id,
        timestamp=datetime.now(UTC),
        payload={"source": "dynamic_swarm", "decision": {"allowed": True}},
    )
    second_event = TraceEvent(
        event_id="evt-runtime-2",
        topic=EventTopic.UI_TASK_TRACE_UPDATE.value,
        tenant_id=tenant_id,
        task_id=task_id,
        workspace_id="ws-execution-stream",
        trace_id=task_id,
        timestamp=datetime.now(UTC),
        payload={"source": "dynamic_swarm", "event": {"event_type": "progress", "source_event_type": "progress"}},
    )
    event_journal.append(first_event)
    event_journal.append(second_event)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    execution_id = f"runtime:{task_id}"
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/api/executions/{execution_id}/events",
            "query_string": f"tenant_id={tenant_id}&workspace_id=ws-execution-stream".encode(),
            "path_params": {"execution_id": execution_id},
            "headers": [(b"last-event-id", b"evt-runtime-1")],
        },
        receive=receive,
    )

    response = asyncio.run(stream_execution_events(request))
    first = asyncio.run(response.body_iterator.__anext__())
    second = asyncio.run(response.body_iterator.__anext__())

    assert response.status_code == 200
    assert "execution.stream.connected" in first
    assert "evt-runtime-2" in second
