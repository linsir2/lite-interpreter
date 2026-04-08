"""In-process task lease loss tracking for scheduler workers."""
from __future__ import annotations

import threading

from src.dag_engine.dag_exceptions import TaskLeaseLostError
from src.storage.repository.state_repo import StateRepo

_lost_task_leases: dict[str, str] = {}
_lock = threading.RLock()


def mark_task_lease_lost(task_id: str, reason: str) -> None:
    with _lock:
        _lost_task_leases[task_id] = reason


def clear_task_lease_loss(task_id: str) -> None:
    with _lock:
        _lost_task_leases.pop(task_id, None)


def get_task_lease_loss(task_id: str) -> str | None:
    with _lock:
        return _lost_task_leases.get(task_id)


def ensure_task_lease_owned(task_id: str, lease_owner_id: str) -> None:
    normalized_task_id = str(task_id or "").strip()
    normalized_owner = str(lease_owner_id or "").strip()
    if not normalized_task_id or not normalized_owner:
        return
    loss_reason = get_task_lease_loss(normalized_task_id)
    if loss_reason:
        raise TaskLeaseLostError(loss_reason)
    status = StateRepo.task_lease_status(normalized_task_id, normalized_owner)
    if status.get("status") != "owned":
        raise TaskLeaseLostError(
            str(
                status.get("reason")
                or status.get("error")
                or f"task lease not owned for {normalized_task_id}"
            )
        )
