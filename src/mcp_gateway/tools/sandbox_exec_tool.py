"""Task-aware sandbox execution helper used by DAG/runtime callsites."""
from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List

from src.common.contracts import ArtifactRecord, ExecutionRecord, InputLease
from src.common.utils import generate_uuid
from src.sandbox import execute_in_sandbox, execute_in_sandbox_async, execute_in_sandbox_with_audit


def build_input_mount_manifest(
    structured_datasets: Iterable[Dict[str, Any]] | None = None,
    business_documents: Iterable[Dict[str, Any]] | None = None,
) -> List[Dict[str, str]]:
    """Build a read-only host/container manifest for sandbox-visible inputs."""
    manifest: List[Dict[str, str]] = []
    seen_paths: set[str] = set()
    for kind, items in (("structured_dataset", structured_datasets or []), ("business_document", business_documents or [])):
        for index, item in enumerate(items):
            host_path = str(item.get("path", "")).strip()
            if not host_path or host_path in seen_paths:
                continue
            seen_paths.add(host_path)
            container_path = f"/app/inputs/{kind}_{index}_{os.path.basename(host_path)}"
            manifest.append(
                {
                    "kind": kind,
                    "host_path": host_path,
                    "container_path": container_path,
                    "file_name": str(item.get("file_name") or os.path.basename(host_path)),
                }
            )
    return manifest


def normalize_execution_result(
    result: Dict[str, Any],
    *,
    tenant_id: str,
    workspace_id: str,
    task_id: str | None = None,
) -> Dict[str, Any]:
    """Attach a normalized execution record without breaking legacy callers."""
    if result.get("execution_record"):
        return result

    mounted_inputs = [
        InputLease(
            kind=str(item.get("kind", "input")),
            host_path=str(item.get("host_path", "")),
            container_path=str(item.get("container_path", "")),
            file_name=str(item.get("file_name", "")),
        )
        for item in result.get("mounted_inputs", []) or []
        if isinstance(item, dict)
    ]

    artifacts: list[ArtifactRecord] = []
    artifacts_dir = str(result.get("artifacts_dir", "") or "").strip()
    if artifacts_dir:
        artifacts.append(
            ArtifactRecord(
                path=artifacts_dir,
                artifact_type="sandbox_output",
                summary=artifacts_dir,
            )
        )

    sandbox_session = dict(result.get("sandbox_session", {}) or {})
    session_id = str(sandbox_session.get("session_id") or result.get("trace_id") or generate_uuid())

    execution_record = ExecutionRecord(
        session_id=session_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        success=bool(result.get("success")),
        trace_id=str(result.get("trace_id") or ""),
        duration_seconds=float(result.get("duration_seconds", 0.0) or 0.0),
        output=result.get("output"),
        error=result.get("error"),
        artifacts=artifacts,
        mounted_inputs=mounted_inputs,
        governance=result.get("governance"),
        metadata={"sandbox_session": sandbox_session} if sandbox_session else {},
    ).model_dump(mode="json")

    normalized = dict(result)
    normalized["execution_record"] = execution_record
    return normalized


class SandboxExecTool:
    """Thin wrapper that preserves task/workspace context for sandbox runs."""

    CAPABILITY_ID = "sandbox_exec"

    @staticmethod
    def run_sync(
        *,
        code: str,
        tenant_id: str,
        workspace_id: str = "default_ws",
        task_id: str | None = None,
        use_audit: bool = True,
        input_mounts: List[Dict[str, str]] | None = None,
    ) -> Dict[str, Any]:
        runner = execute_in_sandbox_with_audit if use_audit else execute_in_sandbox
        return normalize_execution_result(
            runner(
                code,
                tenant_id,
                workspace_id=workspace_id,
                task_id=task_id,
                input_mounts=input_mounts or [],
            ),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            task_id=task_id,
        )

    @staticmethod
    async def run_async(
        *,
        code: str,
        tenant_id: str,
        workspace_id: str = "default_ws",
        task_id: str | None = None,
        use_audit: bool = True,
        input_mounts: List[Dict[str, str]] | None = None,
    ) -> Dict[str, Any]:
        result = await execute_in_sandbox_async(
            code,
            tenant_id,
            workspace_id=workspace_id,
            task_id=task_id,
            use_audit=use_audit,
            input_mounts=input_mounts or [],
        )
        return normalize_execution_result(
            result,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            task_id=task_id,
        )
