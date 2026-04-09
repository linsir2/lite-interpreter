"""Result/session/event helpers for sandbox execution flows."""

from __future__ import annotations

from typing import Any

from src.common import EventTopic, event_bus
from src.sandbox.schema import SandboxResult
from src.sandbox.session_manager import sandbox_session_manager


def attach_sandbox_session(
    result: dict[str, Any],
    *,
    trace_id: str,
    success: bool,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    handle = sandbox_session_manager.complete_session(
        trace_id,
        success=success,
        metadata=metadata,
    )
    if handle is not None:
        result["sandbox_session"] = handle.model_dump(mode="json")
    return result


def publish_sandbox_task_events(
    *,
    tenant_id: str,
    workspace_id: str,
    task_id: str | None,
    trace_id: str,
    governance: dict[str, Any] | None = None,
    success: bool | None = None,
    artifacts_dir: str | None = None,
    error: str | None = None,
) -> None:
    """Publish task-scoped sandbox events when the execution is tied to a task."""
    if not task_id:
        return

    if governance:
        event_bus.publish(
            topic=EventTopic.UI_TASK_GOVERNANCE_UPDATE,
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id=workspace_id,
            payload={
                "source": "sandbox",
                "decision": governance,
            },
            trace_id=trace_id,
        )

    if success is not None:
        event_bus.publish(
            topic=EventTopic.UI_TASK_STATUS_UPDATE,
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id=workspace_id,
            payload={
                "new_status": "executing" if success else "execution_failed",
                "message": "Sandbox execution completed"
                if success
                else f"Sandbox execution failed: {error or 'unknown error'}",
                "source": "sandbox",
            },
            trace_id=trace_id,
        )

    if success and artifacts_dir:
        event_bus.publish(
            topic=EventTopic.UI_ARTIFACT_READY,
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id=workspace_id,
            payload={
                "source": "sandbox",
                "artifacts_dir": artifacts_dir,
            },
            trace_id=trace_id,
        )


def build_sandbox_response(
    *,
    success: bool,
    trace_id: str,
    tenant_id: str,
    duration_seconds: float,
    workspace_id: str,
    task_id: str | None,
    governance: dict[str, Any] | None = None,
    output: str | None = None,
    error: str | None = None,
    artifacts_dir: str | None = None,
    mounted_inputs: list[dict[str, Any]] | None = None,
    session_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = SandboxResult(
        success=success,
        output=output,
        error=error,
        trace_id=trace_id,
        duration_seconds=duration_seconds,
        tenant_id=tenant_id,
        artifacts_dir=artifacts_dir,
        mounted_inputs=mounted_inputs,
        governance=governance,
    ).model_dump()
    result = attach_sandbox_session(
        result,
        trace_id=trace_id,
        success=success,
        metadata=session_metadata,
    )
    publish_sandbox_task_events(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        trace_id=trace_id,
        governance=governance,
        success=success,
        artifacts_dir=artifacts_dir,
        error=error,
    )
    return result


def build_preflight_failure_response(
    *,
    tenant_id: str,
    trace_id: str,
    duration_seconds: float,
    error: str,
) -> dict[str, Any]:
    """Build a standard failure payload for errors raised before Docker execution starts."""
    return SandboxResult(
        success=False,
        error=error,
        trace_id=trace_id,
        duration_seconds=duration_seconds,
        tenant_id=tenant_id,
    ).model_dump()
