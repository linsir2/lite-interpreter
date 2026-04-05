"""Execution resource endpoints derived from task execution state."""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from src.api.schemas import ExecutionStreamEvent
from src.blackboard import TaskNotExistError, execution_blackboard, global_blackboard
from src.api.execution_resources import (
    build_execution_artifacts,
    build_execution_tool_calls,
    build_task_execution_summaries,
    filter_records_after_event_id,
    matches_execution_stream_record,
    resolve_execution_resource,
    task_identity_for_execution,
)
from src.common import EventTopic, event_bus, event_journal
from src.common.event_bus import Event
from src.privacy import mask_payload

_EXECUTION_STREAM_TOPICS = [
    EventTopic.UI_TASK_STATUS_UPDATE,
    EventTopic.UI_TASK_TRACE_UPDATE,
    EventTopic.UI_TASK_GOVERNANCE_UPDATE,
    EventTopic.UI_ARTIFACT_READY,
    EventTopic.SYS_TASK_FINISHED,
]


def _encode_sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def list_task_executions(request: Request) -> JSONResponse:
    task_id = request.path_params["task_id"]
    try:
        task = global_blackboard.get_task_state(task_id)
    except TaskNotExistError:
        return JSONResponse({"error": "task not found", "task_id": task_id}, status_code=404)

    execution_data = execution_blackboard.read(task.tenant_id, task_id)
    payload, _ = mask_payload(
        {"task_id": task_id, "executions": build_task_execution_summaries(execution_data)},
        list(execution_data.task_envelope.redaction_rules or []) if execution_data and execution_data.task_envelope else None,
    )
    return JSONResponse(payload)


async def get_execution(request: Request) -> JSONResponse:
    execution_id = request.path_params["execution_id"]
    summary, execution_data = resolve_execution_resource(execution_id)
    if summary is None or execution_data is None:
        return JSONResponse({"error": "execution not found", "execution_id": execution_id}, status_code=404)

    artifacts = build_execution_artifacts(execution_data, execution_id)
    payload, _ = mask_payload(
        {
            **summary,
            "artifacts": artifacts,
            "tool_calls": build_execution_tool_calls(execution_data, execution_id),
        },
        list(execution_data.task_envelope.redaction_rules or []) if execution_data.task_envelope else None,
    )
    return JSONResponse(payload)


async def list_execution_artifacts(request: Request) -> JSONResponse:
    execution_id = request.path_params["execution_id"]
    summary, execution_data = resolve_execution_resource(execution_id)
    if summary is None or execution_data is None:
        return JSONResponse({"error": "execution not found", "execution_id": execution_id}, status_code=404)

    payload, _ = mask_payload(
        {
            "execution_id": execution_id,
            "artifacts": build_execution_artifacts(execution_data, execution_id),
        },
        list(execution_data.task_envelope.redaction_rules or []) if execution_data.task_envelope else None,
    )
    return JSONResponse(payload)


async def list_execution_tool_calls(request: Request) -> JSONResponse:
    execution_id = request.path_params["execution_id"]
    summary, execution_data = resolve_execution_resource(execution_id)
    if summary is None or execution_data is None:
        return JSONResponse({"error": "execution not found", "execution_id": execution_id}, status_code=404)

    payload, _ = mask_payload(
        {
            "execution_id": execution_id,
            "tool_calls": build_execution_tool_calls(execution_data, execution_id),
        },
        list(execution_data.task_envelope.redaction_rules or []) if execution_data.task_envelope else None,
    )
    return JSONResponse(payload)


async def stream_execution_events(request: Request) -> StreamingResponse:
    execution_id = request.path_params["execution_id"]
    summary, execution_data = resolve_execution_resource(execution_id)
    if summary is None or execution_data is None:
        return JSONResponse({"error": "execution not found", "execution_id": execution_id}, status_code=404)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict] = asyncio.Queue()
    callbacks = []
    after_event_id = request.headers.get("last-event-id") or request.query_params.get("after_event_id")

    def build_callback(topic: EventTopic):
        def _callback(event: Event) -> None:
            event_record = {
                "event_id": event.event_id,
                "topic": event.topic.value,
                "task_id": event.task_id,
                "tenant_id": event.tenant_id,
                "workspace_id": event.workspace_id,
                "trace_id": event.trace_id,
                "timestamp": event.timestamp.isoformat(),
                "payload": event.payload,
            }
            if not matches_execution_stream_record(execution_data, execution_id, event_record):
                return
            loop.call_soon_threadsafe(
                queue.put_nowait,
                ExecutionStreamEvent.from_task_event(event, execution_id=execution_id).to_dict(),
            )

        return _callback

    for topic in _EXECUTION_STREAM_TOPICS:
        callback = build_callback(topic)
        callbacks.append((topic, callback))
        event_bus.subscribe(topic, callback)

    identity = task_identity_for_execution(execution_data)

    async def event_generator() -> AsyncIterator[str]:
        try:
            yield _encode_sse(
                {
                    "topic": "execution.stream.connected",
                    "execution_id": execution_id,
                    **identity,
                    "payload": {"message": "Execution stream connected", "after_event_id": after_event_id},
                }
            )
            backlog = event_journal.read(
                identity["tenant_id"],
                identity["task_id"],
                workspace_id=identity["workspace_id"],
            )
            filtered_backlog = [
                record
                for record in backlog
                if matches_execution_stream_record(execution_data, execution_id, record)
            ]
            for record in filter_records_after_event_id(filtered_backlog, after_event_id):
                yield _encode_sse(ExecutionStreamEvent.from_task_record(record, execution_id=execution_id).to_dict())
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield _encode_sse(event)
                except asyncio.TimeoutError:
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
