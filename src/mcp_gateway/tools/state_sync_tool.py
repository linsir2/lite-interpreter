"""Blackboard state sync helpers for DAG and dynamic-swarm writeback."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.schema import ExecutionData
from src.common.control_plane import merge_domain_patch


class StateSyncTool:
    """Apply a partial state patch to the execution blackboard."""

    CAPABILITY_ID = "state_sync"
    ALLOWED_DOMAINS = {"control", "inputs", "knowledge", "static", "dynamic"}

    @staticmethod
    def _merge_list(current: list[Any], incoming: list[Any]) -> list[Any]:
        merged = list(current)
        for item in incoming:
            if item in merged:
                continue
            merged.append(item)
        return merged

    @staticmethod
    def _merge_value(current: Any, incoming: Any) -> Any:
        if incoming is None:
            return current
        if isinstance(current, list) and isinstance(incoming, list):
            return StateSyncTool._merge_list(current, incoming)
        if isinstance(current, dict) and isinstance(incoming, dict):
            merged = dict(current)
            merged.update(incoming)
            return merged
        return incoming

    @classmethod
    def apply_execution_patch(cls, execution_data: ExecutionData, patch: dict[str, Any]) -> ExecutionData:
        for domain, value in patch.items():
            if domain not in cls.ALLOWED_DOMAINS:
                raise ValueError(f"unsupported execution patch domain: {domain}")
            if not isinstance(value, Mapping):
                raise ValueError(f"execution patch domain `{domain}` must be a mapping")
            current_value = getattr(execution_data, domain)
            merged_payload = merge_domain_patch(current_value.model_dump(mode="json"), dict(value))
            setattr(execution_data, domain, merged_payload)
        return execution_data

    @classmethod
    def sync_execution_patch(cls, tenant_id: str, task_id: str, patch: dict[str, Any]) -> ExecutionData:
        execution_data = execution_blackboard.read(tenant_id, task_id)
        if execution_data is None and execution_blackboard.restore(tenant_id, task_id):
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
        event: dict[str, Any],
    ) -> ExecutionData:
        return cls.sync_execution_patch(
            tenant_id,
            task_id,
            {
                "dynamic": {
                    "trace": [event],
                },
            },
        )
