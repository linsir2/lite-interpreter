"""Memory-blackboard sync helpers for harvested and durable task memories."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.blackboard import MemoryData, memory_blackboard
from src.common.control_plane import merge_domain_patch


class MemorySyncTool:
    """Apply a partial state patch to the memory blackboard."""

    CAPABILITY_ID = "memory_sync"
    ALLOWED_DOMAINS = {
        "harvested_candidates",
        "approved_skills",
        "historical_matches",
        "task_summary",
        "workspace_preferences",
        "cache_hints",
    }

    @classmethod
    def apply_memory_patch(cls, memory_data: MemoryData, patch: dict[str, Any]) -> MemoryData:
        for domain, value in patch.items():
            if domain not in cls.ALLOWED_DOMAINS:
                raise ValueError(f"unsupported memory patch domain: {domain}")
            current_value = getattr(memory_data, domain)
            if hasattr(current_value, "model_dump"):
                if not isinstance(value, Mapping):
                    raise ValueError(f"memory patch domain `{domain}` must be a mapping")
                merged_payload = merge_domain_patch(current_value.model_dump(mode="json"), dict(value))
                setattr(memory_data, domain, merged_payload)
                continue
            if isinstance(current_value, list):
                if not isinstance(value, list):
                    raise ValueError(f"memory patch domain `{domain}` must be a list")
                merged = list(current_value)
                for item in value:
                    if item in merged:
                        continue
                    merged.append(item)
                setattr(memory_data, domain, merged)
                continue
            setattr(memory_data, domain, value)
        return memory_data

    @classmethod
    def sync_memory_patch(cls, tenant_id: str, task_id: str, patch: dict[str, Any]) -> MemoryData:
        memory_data = memory_blackboard.read(tenant_id, task_id)
        if memory_data is None and memory_blackboard.restore(tenant_id, task_id):
            memory_data = memory_blackboard.read(tenant_id, task_id)
        if not memory_data:
            memory_data = MemoryData(task_id=task_id, tenant_id=tenant_id)
        memory_data = cls.apply_memory_patch(memory_data, patch)
        memory_blackboard.write(tenant_id, task_id, memory_data)
        memory_blackboard.persist(tenant_id, task_id)
        return memory_data
