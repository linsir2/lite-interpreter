"""Tests for the task SSE endpoint helpers."""
from __future__ import annotations

import asyncio
import json

from src.api.routers.analysis_router import create_task, get_task_result
from src.api.routers.sse_router import (
    _STREAM_TOPICS,
    _encode_sse,
    _event_matches_subscription,
    _publish_demo_trace,
    stream_task_events,
    trigger_demo_trace,
)
from src.blackboard import global_blackboard
from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.memory_blackboard import memory_blackboard
from src.blackboard.schema import ExecutionData, GlobalStatus, MemoryData
from src.common import EventTopic, ExecutionRecord, TraceEvent, event_journal
from src.common.event_bus import Event
from src.storage.repository.memory_repo import MemoryRepo
from starlette.requests import Request


def _run_task_flow_inline(monkeypatch, coroutine):
    class FakeLoop:
        def run_in_executor(self, executor, func):  # noqa: ARG002
            future = asyncio.Future()
            try:
                future.set_result(func())
            except Exception as exc:  # pragma: no cover - test helper
                future.set_exception(exc)
            return future

    monkeypatch.setattr("src.api.routers.analysis_router.asyncio.get_running_loop", lambda: FakeLoop())
    asyncio.run(coroutine)


def test_encode_sse_wraps_json_payload():
    encoded = _encode_sse({"topic": "ui.task.status_update", "payload": {"new_status": "coding"}})
    assert encoded.startswith("data: ")
    assert encoded.endswith("\n\n")


def test_event_match_filters_by_task_tenant_and_workspace():
    event = Event(
        event_id="evt-1",
        topic=EventTopic.UI_TASK_STATUS_UPDATE,
        tenant_id="tenant-1",
        task_id="task-1",
        workspace_id="ws-1",
        payload={"new_status": "coding"},
        timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        trace_id="trace-1",
    )
    assert _event_matches_subscription(event, task_id="task-1", tenant_id="tenant-1", workspace_id="ws-1")
    assert not _event_matches_subscription(event, task_id="task-2", tenant_id="tenant-1", workspace_id="ws-1")
    assert not _event_matches_subscription(event, task_id="task-1", tenant_id="tenant-2", workspace_id="ws-1")
    assert not _event_matches_subscription(event, task_id="task-1", tenant_id="tenant-1", workspace_id="ws-2")


def test_stream_route_returns_event_stream_response():
    assert EventTopic.UI_TASK_GOVERNANCE_UPDATE in _STREAM_TOPICS
    task_id = global_blackboard.create_task("tenant-1", "ws-1", "stream")

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/api/tasks/{task_id}/events",
            "query_string": b"tenant_id=tenant-1&workspace_id=ws-1",
            "path_params": {"task_id": task_id},
            "headers": [],
        },
        receive=receive,
    )
    response = asyncio.run(stream_task_events(request))
    assert response.media_type == "text/event-stream"


def test_stream_route_replays_journal_backlog():
    event_journal.clear()
    task_id = global_blackboard.create_task("tenant-1", "ws-1", "backlog")
    event_journal.append(
        TraceEvent(
            event_id="evt-backlog",
            topic=EventTopic.UI_TASK_STATUS_UPDATE.value,
            tenant_id="tenant-1",
            task_id=task_id,
            workspace_id="ws-1",
            trace_id="trace-backlog",
            payload={"new_status": "routing"},
        )
    )

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/api/tasks/{task_id}/events",
            "query_string": b"tenant_id=tenant-1&workspace_id=ws-1",
            "path_params": {"task_id": task_id},
            "headers": [],
        },
        receive=receive,
    )
    response = asyncio.run(stream_task_events(request))
    generator = response.body_iterator
    first = asyncio.run(generator.__anext__())
    second = asyncio.run(generator.__anext__())
    assert "stream.connected" in first
    assert task_id in second


def test_demo_trace_endpoint_accepts_request():
    task_id = global_blackboard.create_task("tenant-1", "ws-1", "demo task")

    async def receive():
        return {
            "type": "http.request",
            "body": json.dumps({"tenant_id": "tenant-1", "workspace_id": "ws-1"}).encode(),
            "more_body": False,
        }

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/api/dev/tasks/{task_id}/demo-trace",
            "query_string": b"",
            "path_params": {"task_id": task_id},
            "headers": [(b"content-type", b"application/json")],
        },
        receive=receive,
    )
    with __import__("pytest").MonkeyPatch.context() as mp:
        mp.setattr("src.api.routers.sse_router.API_ENABLE_DEMO_TRACE", True)
        response = asyncio.run(trigger_demo_trace(request))
    assert response.status_code == 200
    body = json.loads(response.body.decode())
    assert body["accepted"] is True
    assert body["task_id"] == task_id


def test_demo_trace_endpoint_is_disabled_by_default():
    task_id = global_blackboard.create_task("tenant-1", "ws-1", "demo task disabled")

    async def receive():
        return {
            "type": "http.request",
            "body": json.dumps({"tenant_id": "tenant-1", "workspace_id": "ws-1"}).encode(),
            "more_body": False,
        }

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": f"/api/dev/tasks/{task_id}/demo-trace",
            "query_string": b"",
            "path_params": {"task_id": task_id},
            "headers": [(b"content-type", b"application/json")],
        },
        receive=receive,
    )
    response = asyncio.run(trigger_demo_trace(request))
    body = json.loads(response.body.decode())
    assert response.status_code == 404
    assert body["error"] == "demo trace api disabled"


def test_demo_trace_payload_contains_canonical_execution_event():
    event_journal.clear()
    asyncio.run(_publish_demo_trace("demo-v2", "tenant-1", "ws-1"))
    records = event_journal.read("tenant-1", "demo-v2", workspace_id="ws-1")
    trace_record = next(record for record in records if record["topic"] == EventTopic.UI_TASK_TRACE_UPDATE.value)
    event_payload = trace_record["payload"]["event"]
    assert event_payload["event_type"] == "progress"
    assert event_payload["source_event_type"] == "progress"


def test_create_task_endpoint_returns_task_id():
    async def receive():
        return {
            "type": "http.request",
            "body": json.dumps(
                {
                    "tenant_id": "tenant-1",
                    "workspace_id": "ws-1",
                    "input_query": "please analyze",
                    "autorun": False,
                    "governance_profile": "reviewer",
                }
            ).encode(),
            "more_body": False,
        }

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/tasks",
            "query_string": b"",
            "path_params": {},
            "headers": [(b"content-type", b"application/json")],
        },
        receive=receive,
    )
    response = asyncio.run(create_task(request))
    assert response.status_code == 200
    body = json.loads(response.body.decode())
    assert body["tenant_id"] == "tenant-1"
    assert body["workspace_id"] == "ws-1"
    assert body["autorun"] is False
    assert body["autorun_scheduled"] is False
    assert body["autorun_reason"] == "not_requested"
    assert body["governance_profile"] == "reviewer"
    assert body["task_id"]
    persisted = execution_blackboard.read("tenant-1", body["task_id"])
    assert persisted is not None
    assert persisted.control.task_envelope is not None


def test_create_task_endpoint_rejects_string_bool_and_tool_list_types():
    async def receive():
        return {
            "type": "http.request",
            "body": json.dumps(
                {
                    "tenant_id": "tenant-invalid",
                    "workspace_id": "ws-invalid",
                    "input_query": "please analyze",
                    "autorun": "false",
                    "allowed_tools": "web_search",
                }
            ).encode(),
            "more_body": False,
        }

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/tasks",
            "query_string": b"",
            "path_params": {},
            "headers": [(b"content-type", b"application/json")],
        },
        receive=receive,
    )
    response = asyncio.run(create_task(request))
    body = json.loads(response.body.decode())

    assert response.status_code == 422
    assert body["error"] == "validation_error"


def test_create_task_endpoint_rejects_missing_input_query():
    async def receive():
        return {
            "type": "http.request",
            "body": json.dumps(
                {
                    "tenant_id": "tenant-missing-query",
                    "workspace_id": "ws-missing-query",
                    "autorun": False,
                }
            ).encode(),
            "more_body": False,
        }

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/tasks",
            "query_string": b"",
            "path_params": {},
            "headers": [(b"content-type", b"application/json")],
        },
        receive=receive,
    )
    response = asyncio.run(create_task(request))

    assert response.status_code == 422


def test_create_task_endpoint_reuses_task_for_same_idempotency_key():
    body = {
        "tenant_id": "tenant-idempotent",
        "workspace_id": "ws-idempotent",
        "input_query": "please analyze",
        "autorun": False,
        "idempotency_key": "idem-1",
    }

    async def receive():
        return {
            "type": "http.request",
            "body": json.dumps(body).encode(),
            "more_body": False,
        }

    request_a = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/tasks",
            "query_string": b"",
            "path_params": {},
            "headers": [(b"content-type", b"application/json")],
        },
        receive=receive,
    )
    request_b = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/tasks",
            "query_string": b"",
            "path_params": {},
            "headers": [(b"content-type", b"application/json")],
        },
        receive=receive,
    )

    first = json.loads(asyncio.run(create_task(request_a)).body.decode())
    second = json.loads(asyncio.run(create_task(request_b)).body.decode())

    assert first["task_id"] == second["task_id"]
    assert first["idempotency_hit"] is False
    assert second["idempotency_hit"] is True


def test_create_task_endpoint_rejects_conflicting_idempotency_payload():
    async def receive_first():
        return {
            "type": "http.request",
            "body": json.dumps(
                {
                    "tenant_id": "tenant-idempotent-conflict",
                    "workspace_id": "ws-idempotent-conflict",
                    "input_query": "query-a",
                    "autorun": False,
                    "idempotency_key": "idem-conflict",
                }
            ).encode(),
            "more_body": False,
        }

    async def receive_second():
        return {
            "type": "http.request",
            "body": json.dumps(
                {
                    "tenant_id": "tenant-idempotent-conflict",
                    "workspace_id": "ws-idempotent-conflict",
                    "input_query": "query-b",
                    "autorun": False,
                    "idempotency_key": "idem-conflict",
                }
            ).encode(),
            "more_body": False,
        }

    request_a = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/tasks",
            "query_string": b"",
            "path_params": {},
            "headers": [(b"content-type", b"application/json")],
        },
        receive=receive_first,
    )
    request_b = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/tasks",
            "query_string": b"",
            "path_params": {},
            "headers": [(b"content-type", b"application/json")],
        },
        receive=receive_second,
    )

    first = asyncio.run(create_task(request_a))
    second = asyncio.run(create_task(request_b))

    assert first.status_code == 200
    assert second.status_code == 409


def test_create_task_static_flow_can_use_executor_node(monkeypatch):
    from src.api.routers.analysis_router import _run_task_flow
    from src.blackboard import global_blackboard

    tenant_id = "tenant-static-exec"
    task_id = global_blackboard.create_task(tenant_id, "ws-1", "please analyze")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id="ws-1",
            static={"generated_code": "print('ok')"},
        ),
    )

    monkeypatch.setattr("src.api.routers.analysis_router.router_node", lambda state: {"next_actions": ["analyst"]})
    monkeypatch.setattr("src.api.routers.analysis_router.analyst_node", lambda state: {"analysis_plan": "plan", "next_actions": ["coder"]})
    monkeypatch.setattr("src.api.routers.analysis_router.coder_node", lambda state: {"generated_code": "print('ok')", "next_actions": ["auditor"]})
    monkeypatch.setattr(
        "src.api.routers.analysis_router.auditor_node",
        lambda state: {"audit_result": {"safe": True}, "next_actions": ["executor"]},
    )
    invoked = {}

    def fake_executor(state):
        invoked.update(state)
        return {
            "execution_record": ExecutionRecord(
                session_id="session-static-exec",
                tenant_id=tenant_id,
                workspace_id="ws-1",
                task_id=task_id,
                success=True,
                trace_id="trace-static-exec",
                duration_seconds=0.1,
                output="ok",
            ).model_dump(mode="json")
        }

    monkeypatch.setattr("src.api.routers.analysis_router.executor_node", fake_executor)
    monkeypatch.setattr("src.api.routers.analysis_router.skill_harvester_node", lambda state: {})
    monkeypatch.setattr("src.api.routers.analysis_router.summarizer_node", lambda state: {"final_response": {"mode": "static"}})

    _run_task_flow_inline(
        monkeypatch,
        _run_task_flow(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws-1",
            query="please analyze",
            allowed_tools=[],
            governance_profile="researcher",
        ),
    )

    assert invoked["task_id"] == task_id


def test_create_task_static_flow_runs_minimal_chain(monkeypatch):
    from src.api.routers.analysis_router import _run_task_flow
    from src.blackboard import global_blackboard

    tenant_id = "tenant-static-chain"
    task_id = global_blackboard.create_task(tenant_id, "ws-1", "please summarize")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id="ws-1",
        ),
    )

    monkeypatch.setattr("src.api.routers.analysis_router.router_node", lambda state: {"next_actions": ["analyst"]})
    monkeypatch.setattr(
        "src.api.routers.analysis_router.executor_node",
        lambda state: {
            "execution_record": ExecutionRecord(
                session_id="session-static-chain",
                tenant_id=tenant_id,
                workspace_id="ws-1",
                task_id=task_id,
                success=True,
                trace_id="trace-static-chain",
                duration_seconds=0.1,
                output="ok",
            ).model_dump(mode="json")
        },
    )
    harvested = {}
    monkeypatch.setattr("src.api.routers.analysis_router.skill_harvester_node", lambda state: harvested.update(state) or {})
    summarized = {}
    monkeypatch.setattr("src.api.routers.analysis_router.summarizer_node", lambda state: summarized.update(state) or {"final_response": {"mode": "static"}})

    _run_task_flow_inline(
        monkeypatch,
        _run_task_flow(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws-1",
            query="please summarize",
            allowed_tools=[],
            governance_profile="researcher",
        ),
    )

    persisted = execution_blackboard.read(tenant_id, task_id)
    assert persisted is not None
    assert persisted.static.analysis_plan
    assert persisted.static.generated_code
    assert harvested["task_id"] == task_id
    assert summarized["task_id"] == task_id


def test_run_task_flow_records_historical_skill_outcome(monkeypatch):
    from src.api.routers.analysis_router import _run_task_flow
    from src.blackboard import global_blackboard

    tenant_id = "tenant-history-outcome"
    workspace_id = "ws-history-outcome"
    MemoryRepo.clear()
    MemoryRepo.save_approved_skills(
        tenant_id,
        workspace_id,
        [{"name": "historical_skill_demo", "required_capabilities": ["knowledge_query"], "promotion": {"status": "approved"}}],
    )
    task_id = global_blackboard.create_task(tenant_id, workspace_id, "please summarize")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(task_id=task_id, tenant_id=tenant_id, workspace_id=workspace_id),
    )

    monkeypatch.setattr("src.api.routers.analysis_router.router_node", lambda state: {"next_actions": ["analyst"]})
    monkeypatch.setattr(
        "src.api.routers.analysis_router.executor_node",
        lambda state: {
            "execution_record": ExecutionRecord(
                session_id="session-history-outcome",
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                task_id=task_id,
                success=True,
                trace_id="trace-history-outcome",
                duration_seconds=0.1,
                output="ok",
            ).model_dump(mode="json")
        },
    )
    monkeypatch.setattr("src.api.routers.analysis_router.skill_harvester_node", lambda state: {})
    monkeypatch.setattr("src.api.routers.analysis_router.summarizer_node", lambda state: {"final_response": {"mode": "static"}})

    _run_task_flow_inline(
        monkeypatch,
        _run_task_flow(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id=workspace_id,
            query="请总结规则",
            allowed_tools=[],
            governance_profile="researcher",
        ),
    )

    skills = MemoryRepo.list_approved_skills(tenant_id, workspace_id)
    assert skills[0]["usage"]["success_count"] >= 1


def test_run_task_flow_dynamic_denied_does_not_mark_success(monkeypatch):
    from src.api.routers.analysis_router import _run_task_flow
    from src.blackboard import global_blackboard

    tenant_id = "tenant-dynamic-denied"
    task_id = global_blackboard.create_task(tenant_id, "ws-1", "please analyze")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(task_id=task_id, tenant_id=tenant_id, workspace_id="ws-1"),
    )

    monkeypatch.setattr("src.api.routers.analysis_router.router_node", lambda state: {"next_actions": ["dynamic_swarm"]})
    monkeypatch.setattr("src.api.routers.analysis_router.dynamic_swarm_node", lambda state: {"dynamic_status": "denied", "dynamic_summary": "blocked"})
    monkeypatch.setattr("src.api.routers.analysis_router.summarizer_node", lambda state: {"final_response": {"mode": "dynamic"}})

    _run_task_flow_inline(
        monkeypatch,
        _run_task_flow(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws-1",
            query="please analyze",
            allowed_tools=[],
            governance_profile="researcher",
        ),
    )

    task_state = global_blackboard.get_task_state(task_id)
    assert task_state.global_status == GlobalStatus.WAITING_FOR_HUMAN


def test_run_task_flow_static_success_emits_single_finish_event(monkeypatch):
    from src.api.routers.analysis_router import _run_task_flow
    from src.blackboard import global_blackboard
    from src.common.event_bus import event_bus

    tenant_id = "tenant-single-finish"
    task_id = global_blackboard.create_task(tenant_id, "ws-1", "please analyze")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(task_id=task_id, tenant_id=tenant_id, workspace_id="ws-1"),
    )

    monkeypatch.setattr("src.api.routers.analysis_router.router_node", lambda state: {"next_actions": ["analyst"]})
    monkeypatch.setattr("src.api.routers.analysis_router.analyst_node", lambda state: {"analysis_plan": "plan", "next_actions": ["coder"]})
    monkeypatch.setattr("src.api.routers.analysis_router.coder_node", lambda state: {"generated_code": "print('ok')", "next_actions": ["auditor"]})
    monkeypatch.setattr(
        "src.api.routers.analysis_router.auditor_node",
        lambda state: {"audit_result": {"safe": True}, "next_actions": ["executor"]},
    )

    def fake_executor(state):
        return {
            "execution_record": ExecutionRecord(
                session_id="session-single-finish",
                tenant_id=tenant_id,
                workspace_id="ws-1",
                task_id=task_id,
                success=True,
                trace_id="trace-single-finish",
                duration_seconds=0.1,
                output="ok",
            ).model_dump(mode="json")
        }

    monkeypatch.setattr("src.api.routers.analysis_router.executor_node", fake_executor)
    monkeypatch.setattr("src.api.routers.analysis_router.skill_harvester_node", lambda state: {})
    monkeypatch.setattr("src.api.routers.analysis_router.summarizer_node", lambda state: {"final_response": {"mode": "static"}})

    published_topics = []

    def fake_publish(**kwargs):
        published_topics.append(kwargs["topic"].value)
        return "evt-1"

    monkeypatch.setattr(event_bus, "publish", fake_publish)

    _run_task_flow_inline(
        monkeypatch,
        _run_task_flow(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws-1",
            query="please analyze",
            allowed_tools=[],
            governance_profile="researcher",
        ),
    )

    assert published_topics.count(EventTopic.SYS_TASK_FINISHED.value) == 1


def test_run_task_flow_stops_when_data_inspector_blocks(monkeypatch):
    from src.api.routers.analysis_router import _run_task_flow
    from src.blackboard import global_blackboard

    tenant_id = "tenant-blocked"
    task_id = global_blackboard.create_task(tenant_id, "ws-1", "please analyze")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(task_id=task_id, tenant_id=tenant_id, workspace_id="ws-1"),
    )

    monkeypatch.setattr("src.api.routers.analysis_router.router_node", lambda state: {"next_actions": ["data_inspector"]})
    monkeypatch.setattr("src.api.routers.analysis_router.data_inspector_node", lambda state: {"blocked": True, "block_reason": "bad file"})
    coder_called = {"value": False}
    monkeypatch.setattr("src.api.routers.analysis_router.coder_node", lambda state: coder_called.update(value=True) or {})
    monkeypatch.setattr("src.api.routers.analysis_router.summarizer_node", lambda state: {"final_response": {"mode": "static"}})

    _run_task_flow_inline(
        monkeypatch,
        _run_task_flow(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws-1",
            query="please analyze",
            allowed_tools=[],
            governance_profile="researcher",
        ),
    )

    assert coder_called["value"] is False


def test_get_task_result_returns_final_response():
    from src.blackboard import global_blackboard

    tenant_id = "tenant-result"
    task_id = global_blackboard.create_task(tenant_id, "ws-1", "please summarize")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id="ws-1",
            control={
                "task_envelope": {"task_id": task_id, "tenant_id": tenant_id, "workspace_id": "ws-1", "input_query": "please summarize", "governance_profile": "researcher"},
                "decision_log": [{"action": "sandbox_execute", "profile": "researcher", "mode": "standard", "allowed": True, "risk_level": "low", "risk_score": 0.1}],
                "final_response": {"mode": "static", "headline": "done", "answer": "done", "key_findings": []},
            },
            static={
                "execution_record": ExecutionRecord(
                    session_id="session-result",
                    tenant_id=tenant_id,
                    workspace_id="ws-1",
                    task_id=task_id,
                    success=True,
                    trace_id="trace-result",
                    duration_seconds=0.1,
                    output="ok",
                )
            },
        ),
    )
    global_blackboard.update_global_status(task_id, GlobalStatus.SUCCESS)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/api/tasks/{task_id}/result",
            "query_string": f"tenant_id={tenant_id}&workspace_id=ws-1".encode(),
            "path_params": {"task_id": task_id},
            "headers": [],
        },
        receive=receive,
    )
    response = asyncio.run(get_task_result(request))
    assert response.status_code == 200
    body = json.loads(response.body.decode())
    assert body["task"]["task_id"] == task_id
    assert body["response"]["headline"] == "done"
    assert body["response"]["answer"] == "done"
    assert "analysis_brief" in body["knowledge"]
    assert body["control"]["task_envelope"]["governance_profile"] == "researcher"
    assert body["control"]["decision_log"][0]["allowed"] is True


def test_get_task_result_serializes_typed_blackboard_models():
    from src.blackboard import global_blackboard

    tenant_id = "tenant-result-typed"
    task_id = global_blackboard.create_task(tenant_id, "ws-typed", "please summarize")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id="ws-typed",
            control={
                "task_envelope": {"task_id": task_id, "tenant_id": tenant_id, "workspace_id": "ws-typed", "input_query": "please summarize", "governance_profile": "researcher"},
                "final_response": {"mode": "static", "headline": "done", "answer": "done", "key_findings": []},
            },
            knowledge={
                "knowledge_snapshot": {
                    "rewritten_query": "typed query",
                    "recall_strategies": ["bm25"],
                    "evidence_refs": ["chunk-typed"],
                    "metadata": {"selected_count": 1},
                }
            },
            dynamic={"runtime_metadata": {"effective_runtime_mode": "embedded"}},
        ),
    )
    memory_blackboard.write(
        tenant_id,
        task_id,
        MemoryData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id="ws-typed",
            approved_skills=[{"name": "typed-skill"}],
            historical_matches=[{"name": "typed-history"}],
        ),
    )
    global_blackboard.update_global_status(task_id, GlobalStatus.SUCCESS)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/api/tasks/{task_id}/result",
            "query_string": f"tenant_id={tenant_id}&workspace_id=ws-typed".encode(),
            "path_params": {"task_id": task_id},
            "headers": [],
        },
        receive=receive,
    )
    response = asyncio.run(get_task_result(request))
    body = json.loads(response.body.decode())

    assert response.status_code == 200
    assert body["dynamic"]["runtime_metadata"]["effective_runtime_mode"] == "embedded"
    assert body["knowledge"]["knowledge_snapshot"]["evidence_refs"] == ["chunk-typed"]
    assert "analysis_brief" in body["knowledge"]
    assert body["skills"]["approved"][0]["name"] == "typed-skill"
    assert body["skills"]["historical_matches"][0]["name"] == "typed-history"


def test_get_task_result_restores_execution_state_when_memory_is_cold():
    from src.blackboard import global_blackboard

    tenant_id = "tenant-result-restore"
    task_id = global_blackboard.create_task(tenant_id, "ws-restore", "please summarize")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id="ws-restore",
            control={
                "task_envelope": {"task_id": task_id, "tenant_id": tenant_id, "workspace_id": "ws-restore", "input_query": "please summarize", "governance_profile": "researcher"},
                "final_response": {"mode": "static", "headline": "restored", "answer": "restored", "key_findings": []},
            },
        ),
    )
    execution_blackboard.persist(tenant_id, task_id)
    execution_blackboard._storage.clear()
    global_blackboard.update_global_status(task_id, GlobalStatus.SUCCESS)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/api/tasks/{task_id}/result",
            "query_string": f"tenant_id={tenant_id}&workspace_id=ws-restore".encode(),
            "path_params": {"task_id": task_id},
            "headers": [],
        },
        receive=receive,
    )
    response = asyncio.run(get_task_result(request))
    body = json.loads(response.body.decode())

    assert response.status_code == 200
    assert body["response"]["headline"] == "restored"
    assert "analysis_brief" in body["knowledge"]


def test_get_task_result_returns_404_for_missing_task():
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/tasks/missing/result",
            "query_string": b"",
            "path_params": {"task_id": "missing"},
            "headers": [],
        },
        receive=receive,
    )
    response = asyncio.run(get_task_result(request))
    assert response.status_code == 404


def test_get_task_result_returns_404_for_scope_mismatch():
    tenant_id = "tenant-result-mismatch"
    task_id = global_blackboard.create_task(tenant_id, "ws-match", "please summarize")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id="ws-match",
            control={
                "task_envelope": {
                    "task_id": task_id,
                    "tenant_id": tenant_id,
                    "workspace_id": "ws-match",
                    "input_query": "please summarize",
                    "governance_profile": "researcher",
                },
                "final_response": {"mode": "static", "headline": "done", "answer": "done", "key_findings": []},
            },
        ),
    )
    global_blackboard.update_global_status(task_id, GlobalStatus.SUCCESS)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/api/tasks/{task_id}/result",
            "query_string": b"tenant_id=tenant-result-mismatch&workspace_id=ws-other",
            "path_params": {"task_id": task_id},
            "headers": [],
        },
        receive=receive,
    )
    response = asyncio.run(get_task_result(request))
    body = json.loads(response.body.decode())
    assert response.status_code == 404
    assert body["error"] == "resource not found"
