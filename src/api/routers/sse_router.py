"""SSE router for task status and dynamic trace streaming."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from config.settings import API_ENABLE_DEMO_TRACE
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from src.api.audit_logging import record_api_audit
from src.api.auth import require_request_role
from src.api.request_scope import endpoint_disabled, ensure_resource_scope
from src.api.schemas import TaskStreamEvent
from src.blackboard import TaskNotExistError, global_blackboard
from src.common import EventTopic, event_bus, event_journal
from src.common.event_bus import Event
from src.dynamic_engine.trace_normalizer import TraceNormalizer

_STREAM_TOPICS = [
    EventTopic.UI_TASK_CREATED,
    EventTopic.UI_TASK_STATUS_UPDATE,
    EventTopic.UI_TASK_TRACE_UPDATE,
    EventTopic.UI_TASK_GOVERNANCE_UPDATE,
    EventTopic.UI_ARTIFACT_READY,
    EventTopic.SYS_TASK_FINISHED,
]


def _encode_sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _event_matches_subscription(
    event: Event,
    *,
    task_id: str,
    tenant_id: str | None,
    workspace_id: str | None,
) -> bool:
    if event.task_id != task_id:
        return False
    if tenant_id and event.tenant_id != tenant_id:
        return False
    if workspace_id and event.workspace_id != workspace_id:
        return False
    return True


async def stream_task_events(request: Request) -> StreamingResponse:
    role_error = require_request_role(request, "viewer")
    if role_error is not None:
        return role_error
    task_id = request.path_params["task_id"]
    try:
        task = global_blackboard.get_task_state(task_id)
    except TaskNotExistError:
        return JSONResponse({"error": "task not found", "task_id": task_id}, status_code=404)
    scope_error = ensure_resource_scope(
        request,
        tenant_id=task.tenant_id,
        workspace_id=task.workspace_id,
    )
    if scope_error is not None:
        return scope_error
    tenant_id = task.tenant_id
    workspace_id = task.workspace_id
    record_api_audit(
        request,
        action="task.events.stream",
        outcome="success",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        resource_type="task_stream",
        resource_id=task_id,
        metadata={},
    )

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict] = asyncio.Queue()
    callbacks = []

    def build_callback(topic: EventTopic):
        def _callback(event: Event) -> None:
            if not _event_matches_subscription(
                event,
                task_id=task_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            ):
                return
            loop.call_soon_threadsafe(
                queue.put_nowait,
                TaskStreamEvent.from_event(event).to_dict(),
            )

        return _callback

    for topic in _STREAM_TOPICS:
        callback = build_callback(topic)
        callbacks.append((topic, callback))
        event_bus.subscribe(topic, callback)

    async def event_generator() -> AsyncIterator[str]:
        try:
            yield _encode_sse(
                {
                    "topic": "stream.connected",
                    "task_id": task_id,
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "payload": {"message": "SSE stream connected"},
                }
            )
            backlog = event_journal.read(tenant_id or "", task_id, workspace_id=workspace_id)
            for record in backlog:
                if tenant_id and record.get("tenant_id") != tenant_id:
                    continue
                yield _encode_sse(TaskStreamEvent.from_record(record).to_dict())
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield _encode_sse(event)
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            for topic, callback in callbacks:
                event_bus.unsubscribe(topic, callback)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


async def _publish_demo_trace(task_id: str, tenant_id: str, workspace_id: str) -> None:
    event_bus.publish(
        topic=EventTopic.UI_TASK_CREATED,
        tenant_id=tenant_id,
        task_id=task_id,
        workspace_id=workspace_id,
        payload={"message": "demo task created"},
        trace_id=task_id,
    )
    await asyncio.sleep(0.1)
    for status in ["routing", "dynamic_swarm", "harvesting", "finished"]:
        topic = EventTopic.UI_TASK_STATUS_UPDATE if status != "finished" else EventTopic.SYS_TASK_FINISHED
        payload: dict[str, Any]
        if status == "finished":
            payload = {"final_status": "success", "message": "demo task finished"}
        else:
            payload = {"new_status": status, "message": f"demo status: {status}"}
        event_bus.publish(
            topic=topic,
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id=workspace_id,
            payload=payload,
            trace_id=task_id,
        )
        if status != "finished":
            if status == "dynamic_swarm":
                event_bus.publish(
                    topic=EventTopic.UI_TASK_GOVERNANCE_UPDATE,
                    tenant_id=tenant_id,
                    task_id=task_id,
                    workspace_id=workspace_id,
                    payload={
                        "source": "demo",
                        "decision": {
                            "action": "dynamic_swarm",
                            "profile": "researcher",
                            "mode": "standard",
                            "allowed": True,
                            "risk_level": "medium",
                            "risk_score": 0.58,
                            "reasons": ["demo trace governance decision"],
                            "allowed_tools": ["web_search", "knowledge_query"],
                        },
                    },
                    trace_id=task_id,
                )
            event_bus.publish(
                topic=EventTopic.UI_TASK_TRACE_UPDATE,
                tenant_id=tenant_id,
                task_id=task_id,
                workspace_id=workspace_id,
                payload={
                    "source": "demo",
                    "event": TraceNormalizer.normalize_runtime_event(
                        {
                            "agent_name": "demo-subagent",
                            "step_name": status,
                            "event_type": "progress",
                            "payload": {"message": f"demo trace at {status}"},
                        },
                        source="demo",
                    ),
                },
                trace_id=task_id,
            )
        await asyncio.sleep(0.15)


async def trigger_demo_trace(request: Request) -> JSONResponse:
    role_error = require_request_role(request, "admin")
    if role_error is not None:
        return role_error
    if not API_ENABLE_DEMO_TRACE:
        return endpoint_disabled("demo trace api disabled")
    task_id = request.path_params["task_id"]
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    tenant_id = body.get("tenant_id") or request.query_params.get("tenant_id") or "demo-tenant"
    workspace_id = body.get("workspace_id") or request.query_params.get("workspace_id") or "demo-workspace"
    asyncio.create_task(_publish_demo_trace(task_id, tenant_id, workspace_id))
    record_api_audit(
        request,
        action="demo_trace.trigger",
        outcome="success",
        tenant_id=str(tenant_id),
        workspace_id=str(workspace_id),
        task_id=task_id,
        resource_type="demo_trace",
        resource_id=task_id,
        metadata={"accepted": True},
    )
    return JSONResponse(
        {
            "accepted": True,
            "task_id": task_id,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
        }
    )
