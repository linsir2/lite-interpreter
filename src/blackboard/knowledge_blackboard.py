"""
知识子黑板：存储知识资产与解析状态。

为什么单独要有这一层：

1. `ExecutionBlackboard` 更偏“执行编排态”
   它关心的是当前任务走静态链还是动态链、生成了什么代码、
   执行结果是什么、最终回复是什么。

2. 知识面状态有自己独立的观察需求
   前端/运维经常只想知道：
   - 这批业务文档有没有解析完
   - 当前任务最近一次检索拿到了哪些 evidence refs
   - 这些文档的 parse_mode / parser_diagnostics 是什么

3. 如果继续全部塞回 execution blackboard
   执行态和知识态会重新耦合，后面做知识资产页、知识链路恢复、
   或知识态审计时，又会退回到“从一大坨执行对象里反查”的状态。

因此这里保留一个独立的 knowledge 子黑板，但职责刻意收窄：
- 存“任务级知识快照”
- 不存真正的长期知识库内容
- 不接管执行编排主状态
"""

from __future__ import annotations

import threading

from src.blackboard.base_blackboard import BaseSubBlackboard
from src.blackboard.schema import KnowledgeData
from src.common import get_logger, get_utc_now
from src.storage.repository.state_repo import StateRepo

logger = get_logger(__name__)


class KnowledgeBlackboard(BaseSubBlackboard):
    """
    知识流子黑板。

    当前只负责两类任务级知识状态：
    - `business_documents`
      文档是否 pending/parsed，以及解析元数据
    - `latest_retrieval_snapshot`
      最近一次 QueryEngine / ContextBuilder 之后的检索快照

    这里故意不保存：
    - `business_context`
      这是执行链路给 Analyst/Coder 的压缩上下文，属于执行态
    - `ExecutionIntent / final_response / execution_record`
      这些都属于执行编排主状态，不属于知识子域
    """

    board_name: str = "knowledge"

    def __init__(self):
        self._storage: dict[str, dict[str, KnowledgeData]] = {}
        self._lock = threading.RLock()
        logger.info("知识流子黑板初始化完成", extra={"trace_id": "system"})

    def read(self, tenant_id: str, task_id: str) -> KnowledgeData | None:
        with self._lock:
            tenant_data = self._storage.get(tenant_id, {})
            return tenant_data.get(task_id)

    def _load_persisted_knowledge_data(self, tenant_id: str, task_id: str) -> KnowledgeData | None:
        full_state = StateRepo.load_blackboard_state(tenant_id, task_id)
        if not full_state or self.board_name not in full_state:
            return None
        payload = full_state.get(self.board_name)
        if not isinstance(payload, dict):
            return None
        try:
            return KnowledgeData(**payload)
        except Exception:
            return None

    def write(
        self,
        tenant_id: str,
        task_id: str,
        value: KnowledgeData,
        *,
        refresh_updated_at: bool = True,
    ) -> bool:
        if not isinstance(value, KnowledgeData):
            logger.error("写入数据类型错误，必须是KnowledgeData", extra={"trace_id": task_id})
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
            StateRepo.merge_blackboard_sections(
                tenant_id,
                task_id,
                data.workspace_id,
                {self.board_name: data.model_dump(mode="json")},
            )
            return True
        except Exception as exc:
            logger.error(f"知识数据持久化失败: {exc}", extra={"trace_id": task_id})
            return False

    def restore(self, tenant_id: str, task_id: str) -> bool:
        try:
            full_state = StateRepo.load_blackboard_state(tenant_id, task_id)
            if not full_state or self.board_name not in full_state:
                return False
            data = KnowledgeData(**full_state[self.board_name])
            return self.write(tenant_id, task_id, data, refresh_updated_at=False)
        except Exception as exc:
            logger.error(f"知识数据恢复失败: {exc}", extra={"trace_id": task_id})
            return False

    @staticmethod
    def _is_newer_knowledge_data(candidate: KnowledgeData, current: KnowledgeData | None) -> bool:
        if current is None:
            return True
        return candidate.updated_at > current.updated_at

    def list_workspace_states(self, tenant_id: str, workspace_id: str) -> list[KnowledgeData]:
        """
        列出某个 tenant/workspace 下的知识态快照。

        对外暴露的是 `KnowledgeData`，且只从 knowledge 自己的持久化状态恢复。
        """

        known: dict[str, KnowledgeData] = {}
        cache_updates: list[KnowledgeData] = []

        with self._lock:
            for task_id, payload in self._storage.get(tenant_id, {}).items():
                if payload.workspace_id != workspace_id:
                    continue
                known[task_id] = payload

        for state in StateRepo.list_blackboard_states():
            knowledge_payload = state.get(self.board_name)
            if isinstance(knowledge_payload, dict):
                try:
                    data = KnowledgeData(**knowledge_payload)
                except Exception:
                    data = None
                if data and data.tenant_id == tenant_id and data.workspace_id == workspace_id:
                    current = known.get(data.task_id)
                    if current is None or self._is_newer_knowledge_data(data, current):
                        known[data.task_id] = data
                        cache_updates.append(data)

        for item in cache_updates:
            self.write(item.tenant_id, item.task_id, item, refresh_updated_at=False)

        return list(known.values())


knowledge_blackboard = KnowledgeBlackboard()
