"""API schema helpers for task streaming endpoints."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict

from src.common.event_bus import Event


@dataclass
class TaskStreamEvent:
    event_id: str
    topic: str
    task_id: str
    tenant_id: str
    workspace_id: str
    trace_id: str
    timestamp: str
    payload: Dict[str, Any]

    @classmethod
    def from_event(cls, event: Event) -> "TaskStreamEvent":
        return cls(
            event_id=event.event_id,
            topic=event.topic.value,
            task_id=event.task_id,
            tenant_id=event.tenant_id,
            workspace_id=event.workspace_id,
            trace_id=event.trace_id,
            timestamp=event.timestamp.isoformat(),
            payload=event.payload,
        )

    @classmethod
    def from_record(cls, record: Dict[str, Any]) -> "TaskStreamEvent":
        return cls(
            event_id=str(record.get("event_id", "")),
            topic=str(record.get("topic", "")),
            task_id=str(record.get("task_id", "")),
            tenant_id=str(record.get("tenant_id", "")),
            workspace_id=str(record.get("workspace_id", "")),
            trace_id=str(record.get("trace_id", "")),
            timestamp=str(record.get("timestamp", "")),
            payload=dict(record.get("payload", {}) or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionStreamEvent:
    event_id: str
    topic: str
    execution_id: str
    task_id: str
    tenant_id: str
    workspace_id: str
    trace_id: str
    timestamp: str
    payload: Dict[str, Any]

    @classmethod
    def from_task_event(
        cls,
        event: Event,
        *,
        execution_id: str,
    ) -> "ExecutionStreamEvent":
        return cls(
            event_id=event.event_id,
            topic=event.topic.value,
            execution_id=execution_id,
            task_id=event.task_id,
            tenant_id=event.tenant_id,
            workspace_id=event.workspace_id,
            trace_id=event.trace_id,
            timestamp=event.timestamp.isoformat(),
            payload=event.payload,
        )

    @classmethod
    def from_task_record(
        cls,
        record: Dict[str, Any],
        *,
        execution_id: str,
    ) -> "ExecutionStreamEvent":
        return cls(
            event_id=str(record.get("event_id", "")),
            topic=str(record.get("topic", "")),
            execution_id=execution_id,
            task_id=str(record.get("task_id", "")),
            tenant_id=str(record.get("tenant_id", "")),
            workspace_id=str(record.get("workspace_id", "")),
            trace_id=str(record.get("trace_id", "")),
            timestamp=str(record.get("timestamp", "")),
            payload=dict(record.get("payload", {}) or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
