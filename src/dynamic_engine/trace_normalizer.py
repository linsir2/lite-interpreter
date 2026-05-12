"""Normalize runtime events before they enter the control plane."""

from __future__ import annotations

from typing import Any

from src.common import ExecutionEvent


class TraceNormalizer:
    """Keep runtime-emitted events consistent for state sync and UI projection."""

    _CANONICAL_EVENT_TYPES = {
        "text",
        "thinking",
        "progress",
        "tool_call_start",
        "tool_call_delta",
        "tool_call_end",
        "tool_result",
        "artifact",
        "governance",
        "error",
        "done",
    }

    @staticmethod
    def _artifact_refs(payload: dict[str, Any]) -> list[str]:
        refs: list[str] = []
        for artifact in payload.get("artifacts", []) or []:
            if isinstance(artifact, dict):
                ref = artifact.get("path") or artifact.get("url") or artifact.get("name")
            else:
                ref = artifact
            if ref:
                refs.append(str(ref))
        return refs

    @classmethod
    def _map_event_type(cls, event_type: str, payload: dict[str, Any]) -> str:
        lowered = str(event_type).strip().lower()
        payload_type = str(payload.get("type", "")).strip().lower()
        has_tool_context = any(key in payload for key in {"tool_name", "tool_call_id", "arguments", "result", "status"})

        if cls._artifact_refs(payload):
            return "artifact"
        if lowered in {"error", "failed", "failure"}:
            return "error"
        if lowered in {"end", "done"}:
            return "done"
        if lowered == "messages-tuple" and payload_type in {"thinking", "reasoning"}:
            return "thinking"
        if lowered == "messages-tuple" and payload_type == "ai":
            return "text"
        if lowered in {"tool_call_start", "tool_call_delta", "tool_call_end", "tool_result"}:
            return lowered
        if has_tool_context and payload.get("result") is not None:
            return "tool_result"
        if has_tool_context and lowered in {"delta", "stream"}:
            return "tool_call_delta"
        if has_tool_context and payload.get("status") in {"completed", "failed"}:
            return "tool_call_end"
        if has_tool_context:
            return "tool_call_start"
        return "progress"

    @classmethod
    def build_execution_event(cls, event: dict[str, Any], *, source: str = "dynamic") -> ExecutionEvent:
        if cls._is_canonical_event(event):
            return ExecutionEvent.model_validate(event)

        payload = dict(event.get("payload", {}) or {})
        agent_name = str(event.get("agent_name", source))
        step_name = str(event.get("step_name", payload.get("name", "runtime_step")))
        source_event_type = str(event.get("event_type", "progress"))
        normalized_event_type = cls._map_event_type(source_event_type, payload)
        message = payload.get("message")
        if message is None and normalized_event_type in {"text", "thinking"}:
            message = payload.get("content")

        tool_call = None
        if normalized_event_type.startswith("tool_call") or normalized_event_type == "tool_result":
            tool_call = {
                key: value
                for key, value in payload.items()
                if key in {"tool_name", "tool_call_id", "arguments", "result", "status"}
            } or None

        return ExecutionEvent(
            event_type=normalized_event_type,
            source_event_type=source_event_type,
            agent_name=agent_name,
            step_name=step_name,
            source=source,
            message=str(message) if message is not None else None,
            artifact_refs=cls._artifact_refs(payload),
            tool_call=tool_call,
            payload=payload,
        )

    @staticmethod
    def _is_canonical_event(event: dict[str, Any]) -> bool:
        return (
            isinstance(event, dict)
            and {
                "event_type",
                "agent_name",
                "step_name",
                "payload",
            }.issubset(event.keys())
            and "source_event_type" in event
            and "source" in event
            and str(event.get("event_type") or "") in TraceNormalizer._CANONICAL_EVENT_TYPES
        )

    @staticmethod
    def normalize_runtime_event(event: dict[str, Any], *, source: str = "dynamic") -> dict[str, Any]:
        execution_event = TraceNormalizer.build_execution_event(event, source=source)
        return execution_event.model_dump(mode="json")
