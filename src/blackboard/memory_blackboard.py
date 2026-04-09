"""
记忆子黑板：存储任务级 memory 快照。

职责边界：
- 存当前任务关联的技能记忆、历史命中、任务摘要、workspace 偏好快照
- 不接管执行编排主状态
- 不存长期知识库内容，长期 durable memory 由 MemoryRepo 持有
"""

from __future__ import annotations

import threading

from src.blackboard.base_blackboard import BaseSubBlackboard
from src.blackboard.schema import MemoryData
from src.common import get_logger, get_utc_now
from src.storage.repository.state_repo import StateRepo

logger = get_logger(__name__)


class MemoryBlackboard(BaseSubBlackboard):
    """Task-scoped memory snapshot blackboard."""

    board_name: str = "memory"

    def __init__(self):
        self._storage: dict[str, dict[str, MemoryData]] = {}
        self._lock = threading.RLock()
        logger.info("记忆子黑板初始化完成", extra={"trace_id": "system"})

    def read(self, tenant_id: str, task_id: str) -> MemoryData | None:
        with self._lock:
            tenant_data = self._storage.get(tenant_id, {})
            return tenant_data.get(task_id)

    def write(
        self,
        tenant_id: str,
        task_id: str,
        value: MemoryData,
        *,
        refresh_updated_at: bool = True,
    ) -> bool:
        if not isinstance(value, MemoryData):
            logger.error("写入数据类型错误，必须是MemoryData", extra={"trace_id": task_id})
            return False
        with self._lock:
            if refresh_updated_at:
                value.updated_at = get_utc_now()
            self._storage.setdefault(tenant_id, {})[task_id] = value
            return True

    def delete(self, tenant_id: str, task_id: str) -> bool:
        with self._lock:
            if tenant_id in self._storage and task_id in self._storage[tenant_id]:
                del self._storage[tenant_id][task_id]
                return True
            return False

    def persist(self, tenant_id: str, task_id: str) -> bool:
        data = self.read(tenant_id, task_id)
        if not data:
            return False
        try:
            full_state = StateRepo.load_blackboard_state(tenant_id, task_id) or {}
            full_state[self.board_name] = data.model_dump(mode="json")
            StateRepo.save_blackboard_state(tenant_id, task_id, data.workspace_id, full_state)
            return True
        except Exception as exc:
            logger.error(f"记忆数据持久化失败: {exc}", extra={"trace_id": task_id})
            return False

    def restore(self, tenant_id: str, task_id: str) -> bool:
        try:
            full_state = StateRepo.load_blackboard_state(tenant_id, task_id)
            if not full_state or self.board_name not in full_state:
                return False
            data = MemoryData(**full_state[self.board_name])
            return self.write(tenant_id, task_id, data, refresh_updated_at=False)
        except Exception as exc:
            logger.error(f"记忆数据恢复失败: {exc}", extra={"trace_id": task_id})
            return False

    def _load_persisted_memory_data(self, tenant_id: str, task_id: str) -> MemoryData | None:
        full_state = StateRepo.load_blackboard_state(tenant_id, task_id)
        if not full_state or self.board_name not in full_state:
            return None
        payload = full_state.get(self.board_name)
        if not isinstance(payload, dict):
            return None
        try:
            return MemoryData(**payload)
        except Exception:
            return None

    @staticmethod
    def _is_newer_memory_data(candidate: MemoryData, current: MemoryData | None) -> bool:
        if current is None:
            return True
        return candidate.updated_at > current.updated_at

    def list_workspace_states(self, tenant_id: str, workspace_id: str) -> list[MemoryData]:
        known: dict[str, MemoryData] = {}
        cache_updates: list[MemoryData] = []
        with self._lock:
            for task_id, payload in self._storage.get(tenant_id, {}).items():
                if payload.workspace_id != workspace_id:
                    continue
                known[task_id] = payload

        for state in StateRepo.list_blackboard_states():
            memory_payload = state.get(self.board_name)
            if isinstance(memory_payload, dict):
                try:
                    data = MemoryData(**memory_payload)
                except Exception:
                    data = None
                if data and data.tenant_id == tenant_id and data.workspace_id == workspace_id:
                    current = known.get(data.task_id)
                    if current is None or self._is_newer_memory_data(data, current):
                        known[data.task_id] = data
                        cache_updates.append(data)

        for item in cache_updates:
            self.write(item.tenant_id, item.task_id, item, refresh_updated_at=False)

        return list(known.values())


memory_blackboard = MemoryBlackboard()
