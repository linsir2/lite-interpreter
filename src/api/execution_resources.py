"""Helpers for deriving execution resources from persisted task state."""
from __future__ import annotations

from typing import Any, Mapping

from src.blackboard.schema import ExecutionData
from src.common import ToolCallRecord
from src.common.schema import EventTopic
from src.storage.repository.state_repo import StateRepo


def _normalize_execution_data(value: Any) -> ExecutionData | None:
    if isinstance(value, ExecutionData):
        return value
    if not isinstance(value, dict):
        return None
    execution_payload = value.get("execution") if "execution" in value else value
    if not isinstance(execution_payload, dict):
        return None
    return ExecutionData.model_validate(execution_payload)


def serialize_execution_record(execution_record: Any) -> dict[str, Any] | None:
    if execution_record is None:
        return None
    if hasattr(execution_record, "model_dump"):
        return execution_record.model_dump(mode="json")
    if isinstance(execution_record, dict):
        return dict(execution_record)
    return None


def build_task_execution_summaries(execution_data: ExecutionData | None) -> list[dict[str, Any]]:
    if execution_data is None:
        return []

    summaries: list[dict[str, Any]] = []
    execution_record = serialize_execution_record(execution_data.execution_record)
    sandbox_execution_id = f"sandbox:{execution_record['session_id']}" if execution_record else None
    runtime_execution_id = f"runtime:{execution_data.task_id}" if execution_data.runtime_backend and execution_data.dynamic_status else None
    if execution_record:
        summaries.append(
            {
                "execution_id": sandbox_execution_id,
                "task_id": execution_data.task_id,
                "tenant_id": execution_data.tenant_id,
                "workspace_id": execution_data.workspace_id,
                "kind": "sandbox",
                "backend": "sandbox",
                "status": "completed" if execution_record.get("success") else "failed",
                "success": bool(execution_record.get("success")),
                "trace_id": execution_record.get("trace_id"),
                "summary": execution_record.get("output") or execution_record.get("error"),
                "artifact_count": len(execution_record.get("artifacts", []) or []),
                "tool_call_count": len(build_execution_tool_calls(execution_data, sandbox_execution_id)),
            }
        )

    if execution_data.runtime_backend and execution_data.dynamic_status:
        summaries.append(
            {
                "execution_id": runtime_execution_id,
                "task_id": execution_data.task_id,
                "tenant_id": execution_data.tenant_id,
                "workspace_id": execution_data.workspace_id,
                "kind": "runtime",
                "backend": execution_data.runtime_backend,
                "status": execution_data.dynamic_status,
                "success": execution_data.dynamic_status == "completed",
                "trace_id": execution_data.dynamic_trace_refs[0] if execution_data.dynamic_trace_refs else None,
                "summary": execution_data.dynamic_summary,
                "artifact_count": len(execution_data.dynamic_artifacts),
                "tool_call_count": len(build_execution_tool_calls(execution_data, runtime_execution_id)),
                "runtime_metadata": dict(execution_data.dynamic_runtime_metadata or {}),
            }
        )

    return summaries


def build_execution_artifacts(execution_data: ExecutionData, execution_id: str) -> list[dict[str, Any]]:
    execution_record = serialize_execution_record(execution_data.execution_record)
    if execution_id.startswith("sandbox:"):
        if execution_record and execution_id == f"sandbox:{execution_record['session_id']}":
            return list(execution_record.get("artifacts", []) or [])
        return [
            {
                "path": artifact.get("path"),
                "artifact_type": artifact.get("type", "artifact"),
                "summary": artifact.get("path"),
            }
            for artifact in execution_data.artifacts
            if artifact.get("path")
        ]

    if execution_id == f"runtime:{execution_data.task_id}":
        return [
            {
                "path": artifact,
                "artifact_type": "runtime_artifact",
                "summary": artifact,
            }
            for artifact in execution_data.dynamic_artifacts
            if artifact
        ]
    return []


def build_execution_tool_calls(execution_data: ExecutionData, execution_id: str | None) -> list[dict[str, Any]]:
    if not execution_id:
        return []

    records: list[dict[str, Any]] = []
    execution_record = serialize_execution_record(execution_data.execution_record)

    if execution_id.startswith("sandbox:"):
        sandbox_session_id = execution_id.removeprefix("sandbox:")
        if execution_record and execution_record.get("session_id") == sandbox_session_id:
            records.append(
                ToolCallRecord(
                    tool_call_id=f"{execution_id}:sandbox_exec",
                    execution_id=execution_id,
                    tool_name="sandbox_exec",
                    phase="result",
                    status="completed" if execution_record.get("success") else "failed",
                    agent_name="sandbox",
                    step_name="sandbox_exec",
                    result={
                        "success": execution_record.get("success"),
                        "trace_id": execution_record.get("trace_id"),
                        "artifact_count": len(execution_record.get("artifacts", []) or []),
                        "duration_seconds": execution_record.get("duration_seconds"),
                    },
                    source_event_type="synthetic_sandbox_execution",
                    payload=execution_record,
                ).model_dump(mode="json")
            )

        knowledge_snapshot = dict(execution_data.knowledge_snapshot or {})
        if knowledge_snapshot:
            records.append(
                ToolCallRecord(
                    tool_call_id=f"{execution_id}:knowledge_query",
                    execution_id=execution_id,
                    tool_name="knowledge_query",
                    phase="result",
                    status="completed",
                    agent_name="static_chain",
                    step_name="kag_retriever",
                    arguments={
                        "query": execution_data.task_envelope.input_query if execution_data.task_envelope else None,
                    },
                    result={
                        "rewritten_query": knowledge_snapshot.get("rewritten_query"),
                        "recall_strategies": knowledge_snapshot.get("recall_strategies", []),
                        "evidence_refs": knowledge_snapshot.get("evidence_refs", []),
                        "selected_count": (knowledge_snapshot.get("metadata") or {}).get("selected_count"),
                    },
                    source_event_type="synthetic_knowledge_query",
                    payload=knowledge_snapshot,
                ).model_dump(mode="json")
            )
        return records

    if not execution_id.startswith("runtime:"):
        return []

    for index, event in enumerate(execution_data.dynamic_trace):
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("event_type") or "")
        if not event_type.startswith("tool_call") and event_type != "tool_result":
            continue
        tool_call = dict(event.get("tool_call") or {})
        tool_name = str(tool_call.get("tool_name") or event.get("payload", {}).get("tool_name") or "").strip()
        if not tool_name:
            continue
        tool_call_id = str(tool_call.get("tool_call_id") or f"{execution_id}:tool:{index}")
        phase_map = {
            "tool_call_start": "start",
            "tool_call_delta": "delta",
            "tool_call_end": "end",
            "tool_result": "result",
        }
        record = ToolCallRecord(
            tool_call_id=tool_call_id,
            execution_id=execution_id,
            tool_name=tool_name,
            phase=phase_map.get(event_type, "start"),
            status=tool_call.get("status"),
            agent_name=event.get("agent_name"),
            step_name=event.get("step_name"),
            arguments=tool_call.get("arguments"),
            result=tool_call.get("result"),
            source_event_type=event.get("source_event_type"),
            payload=dict(event.get("payload", {}) or {}),
        )
        records.append(record.model_dump(mode="json"))
    return records


def task_identity_for_execution(execution_data: ExecutionData) -> dict[str, str]:
    return {
        "task_id": execution_data.task_id,
        "tenant_id": execution_data.tenant_id,
        "workspace_id": execution_data.workspace_id,
    }


def matches_execution_stream_record(
    execution_data: ExecutionData,
    execution_id: str,
    record: Mapping[str, Any],
) -> bool:
    topic = str(record.get("topic", ""))
    payload = dict(record.get("payload", {}) or {})
    trace_id = str(record.get("trace_id", ""))
    task_id = str(record.get("task_id", ""))

    if task_id != execution_data.task_id:
        return False

    if execution_id.startswith("sandbox:"):
        sandbox_session_id = execution_id.removeprefix("sandbox:")
        if trace_id == sandbox_session_id:
            return True
        if payload.get("source") == "sandbox":
            return True
        return False

    runtime_execution_id = f"runtime:{execution_data.task_id}"
    if execution_id != runtime_execution_id:
        return False

    if topic == EventTopic.UI_TASK_TRACE_UPDATE.value and payload.get("source") in {"dynamic_swarm", "demo"}:
        return True
    if topic == EventTopic.UI_TASK_GOVERNANCE_UPDATE.value and payload.get("source") in {"dynamic_swarm", "demo"}:
        return True
    if topic == EventTopic.SYS_TASK_FINISHED.value and trace_id == execution_data.task_id:
        return True
    if topic == EventTopic.UI_TASK_STATUS_UPDATE.value and trace_id == execution_data.task_id:
        return True
    return False


def filter_records_after_event_id(records: list[dict[str, Any]], after_event_id: str | None) -> list[dict[str, Any]]:
    if not after_event_id:
        return records
    seen = False
    filtered: list[dict[str, Any]] = []
    for record in records:
        if seen:
            filtered.append(record)
            continue
        if str(record.get("event_id", "")) == after_event_id:
            seen = True
    return filtered


def resolve_execution_resource(execution_id: str) -> tuple[dict[str, Any] | None, ExecutionData | None]:
    for state in StateRepo.list_blackboard_states():
        execution_data = _normalize_execution_data(state)
        if execution_data is None:
            continue
        for summary in build_task_execution_summaries(execution_data):
            if summary["execution_id"] == execution_id:
                return summary, execution_data
    return None, None
