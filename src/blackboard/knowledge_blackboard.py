"""
知识流子黑板基础版：存储租户长期数据资产

- 读写特征：低频写入、高频读取、生命周期长
- 开发期：内存字典实现
- 生产期：完美委托给 StateRepo (PostgreSQL JSONB) 实现跨节点持久化
"""
import threading
from typing import Optional
from pathlib import Path
import json

from src.blackboard.base_blackboard import BaseSubBlackboard
from src.blackboard.schema import KnowledgeData
from src.common import get_logger, get_utc_now
from src.storage.repository.state_repo import StateRepo

logger = get_logger(__name__)

class KnowledgeBlackboard(BaseSubBlackboard):
    """知识流子黑板"""
    board_name: str = "knowledge"

    def __init__(self):
        self._storage: dict[str, dict[str, KnowledgeData]] = {} # tenant_id -> {task_id -> KnowledgeData}
        self._lock = threading.RLock()
        logger.info("知识流子黑板初始化完成", extra={"trace_id": "system"})
    
    def read(self, tenant_id: str, task_id: str) -> Optional[KnowledgeData]:
        with self._lock:
            tenant_data = self._storage.get(tenant_id, {})
        return tenant_data.get(task_id)
    
    def write(self, tenant_id: str, task_id: str, value: KnowledgeData) -> bool:
        if not isinstance(value, KnowledgeData):
            logger.error(f"写入数据类型错误，必须是KnowledgeData", extra={"trace_id": "system"})
            return False
        
        with self._lock:
            value.updated_at = get_utc_now()
            if tenant_id not in self._storage:
                self._storage[tenant_id] = {}
            self._storage[tenant_id][task_id] = value
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
        
        workspace_id = getattr(data, 'workspace_id', 'default_ws')
        try:
            full_state = StateRepo.load_blackboard_state(tenant_id, task_id) or {}
            full_state[self.board_name] = data.model_dump()
            StateRepo.save_blackboard_state(tenant_id, task_id, workspace_id, full_state)
            logger.debug(f"知识数据 DB 持久化成功 tenant_id={tenant_id}", extra={"trace_id": task_id})
            return True
        except Exception as e:
            logger.error(f"知识数据持久化失败: {str(e)}", extra={"trace_id": task_id})
            return False

    def restore(self, tenant_id: str, task_id: str) -> bool:
        """🚀 故障转移：从 Postgres 原样拉起知识流状态"""
        try:
            full_state = StateRepo.load_blackboard_state(tenant_id, task_id)
            if not full_state or self.board_name not in full_state:
                return False
            
            data = KnowledgeData(**full_state[self.board_name])
            self.write(tenant_id, task_id, data)
            logger.info(f"知识数据从 Postgres 恢复成功 tenant_id={tenant_id}", extra={"trace_id": task_id})
            return True
        except Exception as e:
            logger.error(f"知识数据恢复失败: {str(e)}", extra={"trace_id": task_id})
            return False

knowledge_blackboard = KnowledgeBlackboard()