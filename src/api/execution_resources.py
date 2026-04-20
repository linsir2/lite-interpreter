"""Helpers for deriving execution resources from persisted task state."""

from __future__ import annotations

import mimetypes
from collections.abc import Mapping
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from src.blackboard import execution_blackboard
from src.blackboard.schema import ExecutionData
from src.common import ToolCallRecord
from src.common.control_plane import sanitize_artifact_reference
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
    sandbox_execution_id = f"sandbox:{execution_data.task_id}:{execution_record['session_id']}" if execution_record else None
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
        if execution_record and execution_id in {
            f"sandbox:{execution_data.task_id}:{execution_record['session_id']}",
            f"sandbox:{execution_record['session_id']}",
        }:
            return [
                {
                    **dict(artifact),
                    "artifact_id": f"{execution_id}:artifact:{index}",
                }
                for index, artifact in enumerate(list(execution_record.get("artifacts", []) or []), start=1)
            ]
        return []

    if execution_id == f"runtime:{execution_data.task_id}":
        return [
            {
                "artifact_id": f"{execution_id}:artifact:{index}",
                "path": sanitize_artifact_reference(str(artifact)),
                "artifact_type": "runtime_artifact",
                "summary": str(artifact),
            }
            for index, artifact in enumerate(execution_data.dynamic.artifacts, start=1)
            if artifact
        ]
    return []


def resolve_execution_artifact(
    execution_data: ExecutionData,
    execution_id: str,
    artifact_id: str,
) -> dict[str, Any] | None:
    for artifact in build_execution_artifacts(execution_data, execution_id):
        if str(artifact.get("artifact_id") or "").strip() == str(artifact_id or "").strip():
            return artifact
    return None


def read_artifact_content(artifact: Mapping[str, Any]) -> tuple[bytes, str, str] | None:
    artifact_path = str(artifact.get("path") or "").strip()
    if not artifact_path:
        return None
    path = Path(artifact_path)
    if not path.exists() or not path.is_file():
        return None
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return path.read_bytes(), path.name, media_type


def build_execution_tool_calls(execution_data: ExecutionData, execution_id: str | None) -> list[dict[str, Any]]:
    if not execution_id:
        return []

    records: list[dict[str, Any]] = []
    execution_record = serialize_execution_record(execution_data.static.execution_record)

    if execution_id.startswith("sandbox:"):
        sandbox_session_id = execution_id.split(":")[-1]
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
        sandbox_session_id = execution_id.split(":")[-1]
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
    if execution_id.startswith("runtime:"):
        task_id = execution_id.removeprefix("runtime:").strip()
        state = StateRepo.load_blackboard_state_by_task(task_id)
        execution_data = _normalize_execution_data(state)
        if execution_data is not None:
            for summary in build_task_execution_summaries(execution_data):
                if summary["execution_id"] == execution_id:
                    return summary, execution_data
    if execution_id.startswith("sandbox:"):
        parts = execution_id.split(":", 2)
        if len(parts) == 3:
            task_id = parts[1].strip()
            state = StateRepo.load_blackboard_state_by_task(task_id)
            execution_data = _normalize_execution_data(state)
            if execution_data is not None:
                for summary in build_task_execution_summaries(execution_data):
                    if summary["execution_id"] == execution_id:
                        return summary, execution_data
    for state in StateRepo.list_blackboard_states():
        execution_data = _normalize_execution_data(state)
        if execution_data is None:
            continue
        for summary in build_task_execution_summaries(execution_data):
            if summary["execution_id"] == execution_id:
                return summary, execution_data
    return None, None


def build_task_workspace_payload(
    *,
    task: Any,
    execution_data: ExecutionData | None,
    memory_data: Any | None,
    task_lease: dict[str, Any] | None,
) -> dict[str, Any]:
    final_response = execution_data.control.final_response if execution_data else None
    knowledge_snapshot = execution_data.knowledge.knowledge_snapshot.model_dump(mode="json") if execution_data else {}
    analysis_brief = execution_data.knowledge.analysis_brief.model_dump(mode="json") if execution_data else {}
    compiled_knowledge = execution_data.knowledge.compiled.model_dump(mode="json") if execution_data else {}
    executions = build_task_execution_summaries(execution_data)
    tool_calls: list[dict[str, Any]] = []
    for execution in executions:
        execution_id = str(execution.get("execution_id") or "").strip()
        if not execution_id:
            continue
        tool_calls.extend(build_execution_tool_calls(execution_data, execution_id))

    status_payload = {
        "global_status": getattr(task.global_status, "value", str(task.global_status)),
        "sub_status": task.sub_status,
        "failure_type": task.failure_type,
        "error_message": task.error_message,
        "task_lease": task_lease or {},
    }
    primary_mode = str((final_response or {}).get("mode") or status_payload["global_status"] or "unknown")
    primary_headline = str(
        (final_response or {}).get("headline")
        or (final_response or {}).get("answer")
        or status_payload.get("sub_status")
        or "No headline available"
    )
    primary_answer = str(
        (final_response or {}).get("answer")
        or (final_response or {}).get("headline")
        or status_payload.get("error_message")
        or "No answer available"
    )
    evidence_refs = list((final_response or {}).get("evidence_refs") or knowledge_snapshot.get("evidence_refs") or [])
    workspace = {
        "task": {
            "task_id": task.task_id,
            "tenant_id": task.tenant_id,
            "workspace_id": task.workspace_id,
            "query": task.input_query,
        },
        "inputs": {
            "structured_datasets": (
                [item.model_dump(mode="json") for item in list(execution_data.inputs.structured_datasets or [])]
                if execution_data
                else []
            ),
            "business_documents": (
                [item.model_dump(mode="json") for item in list(execution_data.inputs.business_documents or [])]
                if execution_data
                else []
            ),
        },
        "status": status_payload,
        "primary": {
            "mode": primary_mode,
            "headline": primary_headline,
            "answer": primary_answer,
            "next_action": str(analysis_brief.get("recommended_next_step") or ""),
        },
        "evidence": {
            "evidence_refs": evidence_refs,
            "rewritten_query": knowledge_snapshot.get("rewritten_query", ""),
            "recall_strategies": list(knowledge_snapshot.get("recall_strategies") or []),
            "selected_count": dict(knowledge_snapshot.get("metadata") or {}).get("selected_count", 0),
            "preferred_date_terms": dict(knowledge_snapshot.get("metadata") or {}).get("preferred_date_terms", []),
            "temporal_constraints": dict(knowledge_snapshot.get("metadata") or {}).get("temporal_constraints", []),
        },
        "execution": {
            "executions": executions,
            "dynamic": execution_data.dynamic.model_dump(mode="json") if execution_data else {},
            "static": execution_data.static.model_dump(mode="json") if execution_data else {},
        },
        "knowledge": {
            "analysis_brief": analysis_brief,
            "knowledge_snapshot": knowledge_snapshot,
            "compiled_knowledge": compiled_knowledge,
        },
        "technical_details": {
            "control": execution_data.control.model_dump(mode="json") if execution_data else {},
            "tool_calls": tool_calls,
            "historical_skill_matches": (
                [item.model_dump(mode="json") for item in list(memory_data.historical_matches or [])]
                if memory_data and getattr(memory_data, "historical_matches", None) is not None
                else []
            ),
        },
    }
    return {
        "task_id": task.task_id,
        "tenant_id": task.tenant_id,
        "workspace_id": task.workspace_id,
        "workspace": workspace,
        "status": status_payload,
        "response": final_response,
        "knowledge": {
            "analysis_brief": analysis_brief,
            "knowledge_snapshot": knowledge_snapshot,
        },
        "executions": executions,
        "tool_calls": tool_calls,
    }
