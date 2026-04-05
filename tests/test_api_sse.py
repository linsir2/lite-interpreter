"""Tests for the task SSE endpoint helpers."""
from __future__ import annotations

import asyncio
import json

from starlette.requests import Request

from src.api.routers.sse_router import (
    _STREAM_TOPICS,
    _encode_sse,
    _event_matches_subscription,
    _publish_demo_trace,
    stream_task_events,
    trigger_demo_trace,
)
from src.api.routers.analysis_router import create_task, get_task_result
from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.schema import ExecutionData, GlobalStatus
from src.common import EventTopic, TraceEvent, event_journal
from src.common.event_bus import Event
from src.storage.repository.skill_repo import SkillRepo


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

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/tasks/task-1/events",
            "query_string": b"tenant_id=tenant-1",
            "path_params": {"task_id": "task-1"},
            "headers": [],
        },
        receive=receive,
    )
    response = asyncio.run(stream_task_events(request))
    assert response.media_type == "text/event-stream"


def test_stream_route_replays_journal_backlog():
    event_journal.clear()
    event_journal.append(
        TraceEvent(
            event_id="evt-backlog",
            topic=EventTopic.UI_TASK_STATUS_UPDATE.value,
            tenant_id="tenant-1",
            task_id="task-backlog",
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
            "path": "/api/tasks/task-backlog/events",
            "query_string": b"tenant_id=tenant-1&workspace_id=ws-1",
            "path_params": {"task_id": "task-backlog"},
            "headers": [],
        },
        receive=receive,
    )
    response = asyncio.run(stream_task_events(request))
    generator = response.body_iterator
    first = asyncio.run(generator.__anext__())
    second = asyncio.run(generator.__anext__())
    assert "stream.connected" in first
    assert "task-backlog" in second


def test_demo_trace_endpoint_accepts_request():
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
            "path": "/api/dev/tasks/demo-task/demo-trace",
            "query_string": b"",
            "path_params": {"task_id": "demo-task"},
            "headers": [(b"content-type", b"application/json")],
        },
        receive=receive,
    )
    response = asyncio.run(trigger_demo_trace(request))
    assert response.status_code == 200
    body = json.loads(response.body.decode())
    assert body["accepted"] is True
    assert body["task_id"] == "demo-task"


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
    assert persisted.task_envelope is not None


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
            generated_code="print('ok')",
        ),
    )

    monkeypatch.setattr("src.api.routers.analysis_router.router_node", lambda state: {"next_actions": ["analyst"]})
    invoked = {}

    def fake_executor(state):
        invoked.update(state)
        return {"execution_result": {"success": True}}

    monkeypatch.setattr("src.api.routers.analysis_router.executor_node", fake_executor)

    asyncio.run(
        _run_task_flow(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws-1",
            query="please analyze",
            allowed_tools=[],
            governance_profile="researcher",
        )
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
        lambda state: {"execution_result": {"success": True, "output": "ok"}},
    )
    harvested = {}
    monkeypatch.setattr("src.api.routers.analysis_router.skill_harvester_node", lambda state: harvested.update(state) or {})
    summarized = {}
    monkeypatch.setattr("src.api.routers.analysis_router.summarizer_node", lambda state: summarized.update(state) or {"final_response": {"mode": "static"}})

    asyncio.run(
        _run_task_flow(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws-1",
            query="please summarize",
            allowed_tools=[],
            governance_profile="researcher",
        )
    )

    persisted = execution_blackboard.read(tenant_id, task_id)
    assert persisted is not None
    assert persisted.analysis_plan
    assert persisted.generated_code
    assert harvested["task_id"] == task_id
    assert summarized["task_id"] == task_id


def test_run_task_flow_records_historical_skill_outcome(monkeypatch):
    from src.api.routers.analysis_router import _run_task_flow
    from src.blackboard import global_blackboard

    tenant_id = "tenant-history-outcome"
    workspace_id = "ws-history-outcome"
    SkillRepo.clear()
    SkillRepo.save_approved_skills(
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
        lambda state: {"execution_result": {"success": True, "output": "ok"}},
    )
    monkeypatch.setattr("src.api.routers.analysis_router.skill_harvester_node", lambda state: {})
    monkeypatch.setattr("src.api.routers.analysis_router.summarizer_node", lambda state: {"final_response": {"mode": "static"}})

    asyncio.run(
        _run_task_flow(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id=workspace_id,
            query="请总结规则",
            allowed_tools=[],
            governance_profile="researcher",
        )
    )

    skills = SkillRepo.list_approved_skills(tenant_id, workspace_id)
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

    asyncio.run(
        _run_task_flow(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws-1",
            query="please analyze",
            allowed_tools=[],
            governance_profile="researcher",
        )
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
        return {"execution_result": {"success": True, "output": "ok"}}

    monkeypatch.setattr("src.api.routers.analysis_router.executor_node", fake_executor)
    monkeypatch.setattr("src.api.routers.analysis_router.skill_harvester_node", lambda state: {})
    monkeypatch.setattr("src.api.routers.analysis_router.summarizer_node", lambda state: {"final_response": {"mode": "static"}})

    published_topics = []

    def fake_publish(**kwargs):
        published_topics.append(kwargs["topic"].value)
        return "evt-1"

    monkeypatch.setattr(event_bus, "publish", fake_publish)

    asyncio.run(
        _run_task_flow(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws-1",
            query="please analyze",
            allowed_tools=[],
            governance_profile="researcher",
        )
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

    asyncio.run(
        _run_task_flow(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws-1",
            query="please analyze",
            allowed_tools=[],
            governance_profile="researcher",
        )
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
            governance_profile="researcher",
            governance_decisions=[{"allowed": True}],
            execution_result={"success": True, "output": "ok"},
            final_response={"mode": "static", "headline": "done", "answer": "done", "key_findings": []},
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
            "query_string": b"",
            "path_params": {"task_id": task_id},
            "headers": [],
        },
        receive=receive,
    )
    response = asyncio.run(get_task_result(request))
    assert response.status_code == 200
    body = json.loads(response.body.decode())
    assert body["task_id"] == task_id
    assert body["final_response"]["headline"] == "done"
    assert body["final_response"]["answer"] == "done"
    assert body["governance_profile"] == "researcher"


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
