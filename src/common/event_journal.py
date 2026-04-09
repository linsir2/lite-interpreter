"""Append-only task event journal used for SSE replay and audit."""

from __future__ import annotations

import threading
from typing import Any

from src.common.contracts import TraceEvent
from src.common.logger import get_logger
from src.storage.repository.state_repo import StateRepo

logger = get_logger(__name__)


class EventJournal:
    """Store task-scoped events for replay.

    The journal is kept in memory for fast reads and mirrored into StateRepo
    when available so task streams survive process restarts.
    """

    def __init__(self) -> None:
        self._storage: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self._lock = threading.RLock()

    def append(self, event: TraceEvent) -> None:
        record = event.model_dump(mode="json")
        with self._lock:
            tenant_events = self._storage.setdefault(event.tenant_id, {})
            tenant_events.setdefault(event.task_id, []).append(record)
        self._persist(event.tenant_id, event.task_id, event.workspace_id)

    def read(
        self,
        tenant_id: str,
        task_id: str,
        workspace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            if tenant_id:
                tenant_events = self._storage.get(tenant_id, {})
                if task_id in tenant_events:
                    records = list(tenant_events.get(task_id, []))
                else:
                    records = self._restore_from_repo(tenant_id, task_id)
                    if records:
                        tenant_events[task_id] = list(records)
                        self._storage[tenant_id] = tenant_events
            else:
                records = []
                for tenant_events in self._storage.values():
                    if task_id in tenant_events:
                        records = list(tenant_events.get(task_id, []))
                        break
            if workspace_id:
                return [record for record in records if record.get("workspace_id") == workspace_id]
            return records

    def clear(self) -> None:
        with self._lock:
            self._storage.clear()

    def _persist(self, tenant_id: str, task_id: str, workspace_id: str) -> None:
        try:
            state = StateRepo.load_blackboard_state(tenant_id, task_id) or {}
            with self._lock:
                events = list(self._storage.get(tenant_id, {}).get(task_id, []))
            state["event_journal"] = {
                "workspace_id": workspace_id,
                "events": events,
            }
            StateRepo.save_blackboard_state(tenant_id, task_id, workspace_id, state)
        except Exception as exc:  # pragma: no cover - best-effort persistence
            logger.warning(f"event journal persist failed for {task_id}: {exc}", extra={"trace_id": task_id})

    def _restore_from_repo(self, tenant_id: str, task_id: str) -> list[dict[str, Any]]:
        try:
            state = StateRepo.load_blackboard_state(tenant_id, task_id) or {}
            payload = state.get("event_journal", {}) or {}
            events = payload.get("events", []) or []
            return [event for event in events if isinstance(event, dict)]
        except Exception as exc:  # pragma: no cover - best-effort restore
            logger.warning(f"event journal restore failed for {task_id}: {exc}", extra={"trace_id": task_id})
            return []


event_journal = EventJournal()
