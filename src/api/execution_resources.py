"""Helpers for deriving execution resources from persisted task state."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time
from typing import Any

from src.blackboard import execution_blackboard
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


def to_jsonable_payload(value: Any) -> Any:
    """
    把 blackboard / pydantic / dict-like typed state 递归投影成原生 JSON 结构。

    这里的目标不是做业务裁剪，而是把 API 出口上的：
    - Pydantic 模型
    - 以及它们的嵌套 list/dict
    统一变成 `JSONResponse` 可以直接消费的原生对象。
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return to_jsonable_payload(value.model_dump(mode="json", by_alias=True))
    if isinstance(value, Mapping):
        return {str(key): to_jsonable_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable_payload(item) for item in value]
    return value


def read_task_execution_data(tenant_id: str, task_id: str) -> ExecutionData | None:
    """
    读取任务 execution 主状态；当前进程缓存为空时，显式从 execution 持久化状态恢复。
    """
    execution_data = execution_blackboard.read(tenant_id, task_id)
    if execution_data is not None:
        return execution_data
    if execution_blackboard.restore(tenant_id, task_id):
        return execution_blackboard.read(tenant_id, task_id)
    return None


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
    execution_record = serialize_execution_record(execution_data.static.execution_record)
    sandbox_execution_id = f"sandbox:{execution_record['session_id']}" if execution_record else None
    runtime_execution_id = (
        f"runtime:{execution_data.task_id}"
        if execution_data.dynamic.runtime_backend and execution_data.dynamic.status
        else None
    )
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

    if execution_data.dynamic.runtime_backend and execution_data.dynamic.status:
        summaries.append(
            {
                "execution_id": runtime_execution_id,
                "task_id": execution_data.task_id,
                "tenant_id": execution_data.tenant_id,
                "workspace_id": execution_data.workspace_id,
                "kind": "runtime",
                "backend": execution_data.dynamic.runtime_backend,
                "status": execution_data.dynamic.status,
                "success": execution_data.dynamic.status == "completed",
                "trace_id": execution_data.dynamic.trace_refs[0] if execution_data.dynamic.trace_refs else None,
                "summary": execution_data.dynamic.summary,
                "artifact_count": len(execution_data.dynamic.artifacts),
                "tool_call_count": len(build_execution_tool_calls(execution_data, runtime_execution_id)),
                "runtime_metadata": execution_data.dynamic.runtime_metadata.model_dump(mode="json"),
            }
        )

    return summaries


def build_execution_artifacts(execution_data: ExecutionData, execution_id: str) -> list[dict[str, Any]]:
    execution_record = serialize_execution_record(execution_data.static.execution_record)
    if execution_id.startswith("sandbox:"):
        if execution_record and execution_id == f"sandbox:{execution_record['session_id']}":
            return list(execution_record.get("artifacts", []) or [])
        return []

    if execution_id == f"runtime:{execution_data.task_id}":
        return [
            {
                "path": artifact,
                "artifact_type": "runtime_artifact",
                "summary": artifact,
            }
            for artifact in execution_data.dynamic.artifacts
            if artifact
        ]
    return []


def build_execution_tool_calls(execution_data: ExecutionData, execution_id: str | None) -> list[dict[str, Any]]:
    if not execution_id:
        return []

    records: list[dict[str, Any]] = []
    execution_record = serialize_execution_record(execution_data.static.execution_record)

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

        knowledge_snapshot = execution_data.knowledge.knowledge_snapshot.model_dump(mode="json")
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
                        "query": execution_data.control.task_envelope.input_query
                        if execution_data.control.task_envelope
                        else None,
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

    for index, event in enumerate(execution_data.dynamic.trace):
        event_payload = event.model_dump(mode="json") if hasattr(event, "model_dump") else dict(event)
        event_type = str(event_payload.get("event_type") or "")
        if not event_type.startswith("tool_call") and event_type != "tool_result":
            continue
        tool_call = dict(event_payload.get("tool_call") or {})
        tool_name = str(tool_call.get("tool_name") or event_payload.get("payload", {}).get("tool_name") or "").strip()
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
            agent_name=event_payload.get("agent_name"),
            step_name=event_payload.get("step_name"),
            arguments=tool_call.get("arguments"),
            result=tool_call.get("result"),
            source_event_type=event_payload.get("source_event_type"),
            payload=dict(event_payload.get("payload", {}) or {}),
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
