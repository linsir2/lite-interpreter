"""Blackboard state sync helpers for DAG and dynamic-swarm writeback."""
from __future__ import annotations

from typing import Any, Dict

from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.schema import ExecutionData


class StateSyncTool:
    """Apply a partial state patch to the execution blackboard."""

    CAPABILITY_ID = "state_sync"

    @staticmethod
    def _merge_value(current: Any, incoming: Any) -> Any:
        if incoming is None:
            return current
        if isinstance(current, list) and isinstance(incoming, list):
            return current + incoming
        if isinstance(current, dict) and isinstance(incoming, dict):
            merged = dict(current)
            merged.update(incoming)
            return merged
        return incoming

    @classmethod
    def apply_execution_patch(cls, execution_data: ExecutionData, patch: Dict[str, Any]) -> ExecutionData:
        for key, value in patch.items():
            if not hasattr(execution_data, key):
                continue
            current_value = getattr(execution_data, key)
            setattr(execution_data, key, cls._merge_value(current_value, value))
        return execution_data

    @classmethod
    def sync_execution_patch(cls, tenant_id: str, task_id: str, patch: Dict[str, Any]) -> ExecutionData:
        execution_data = execution_blackboard.read(tenant_id, task_id)
        if not execution_data:
            execution_data = ExecutionData(task_id=task_id, tenant_id=tenant_id)
        execution_data = cls.apply_execution_patch(execution_data, patch)
        execution_blackboard.write(tenant_id, task_id, execution_data)
        execution_blackboard.persist(tenant_id, task_id)
        return execution_data

    @classmethod
    def append_dynamic_trace_event(
        cls,
        tenant_id: str,
        task_id: str,
        event: Dict[str, Any],
    ) -> ExecutionData:
        return cls.sync_execution_patch(
            tenant_id,
            task_id,
            {
                "dynamic_trace": [event],
            },
        )
