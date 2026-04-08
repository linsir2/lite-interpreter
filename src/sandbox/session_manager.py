"""Session-oriented wrapper around the current Docker sandbox executor."""
from __future__ import annotations

import threading
from typing import Any

from config.sandbox_config import DOCKER_CONFIG

from src.common import InputLease, SandboxSessionHandle, SandboxSessionSpec, get_utc_now


class SandboxSessionManager:
    """Track lightweight sandbox sessions.

    This is intentionally in-process for now; it provides a stable session
    abstraction without changing the current executor into a remote service.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SandboxSessionHandle] = {}
        self._lock = threading.RLock()

    def build_spec(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        task_id: str | None = None,
        input_mounts: list[dict[str, Any]] | None = None,
    ) -> SandboxSessionSpec:
        return SandboxSessionSpec(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            task_id=task_id,
            image=str(DOCKER_CONFIG["image"]),
            network_disabled=bool(DOCKER_CONFIG["network_disabled"]),
            mem_limit=str(DOCKER_CONFIG["mem_limit"]),
            cpu_shares=int(DOCKER_CONFIG["cpu_shares"]),
            timeout_seconds=int(DOCKER_CONFIG["timeout"]),
            input_leases=[
                InputLease(
                    kind=str(item.get("kind", "input")),
                    host_path=str(item.get("host_path", "")),
                    container_path=str(item.get("container_path", "")),
                    file_name=str(item.get("file_name", "")),
                )
                for item in (input_mounts or [])
            ],
        )

    def create_session(self, spec: SandboxSessionSpec, *, trace_id: str) -> SandboxSessionHandle:
        handle = SandboxSessionHandle(
            session_id=trace_id,
            spec=spec,
            metadata={"trace_id": trace_id},
        )
        with self._lock:
            self._sessions[handle.session_id] = handle
        return handle

    def mark_running(
        self,
        session_id: str,
        *,
        container_name: str | None = None,
        container_id: str | None = None,
    ) -> SandboxSessionHandle | None:
        with self._lock:
            handle = self._sessions.get(session_id)
            if handle is None:
                return None
            handle.status = "running"
            handle.container_name = container_name
            handle.container_id = container_id
            handle.updated_at = get_utc_now()
            return handle

    def complete_session(
        self,
        session_id: str,
        *,
        success: bool,
        metadata: dict[str, Any] | None = None,
    ) -> SandboxSessionHandle | None:
        with self._lock:
            handle = self._sessions.get(session_id)
            if handle is None:
                return None
            handle.status = "completed" if success else "failed"
            handle.updated_at = get_utc_now()
            if metadata:
                merged = dict(handle.metadata)
                merged.update(metadata)
                handle.metadata = merged
            return handle

    def get(self, session_id: str) -> SandboxSessionHandle | None:
        with self._lock:
            return self._sessions.get(session_id)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()


sandbox_session_manager = SandboxSessionManager()
