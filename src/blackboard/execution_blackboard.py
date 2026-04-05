"""
执行流子黑板：存储任务执行全流程的中间数据

- 读写特征：高频读写、生命周期短、精确查找

- 开发期：内存字典实现

- 生产期：完美委托给 StateRepo (PostgreSQL JSONB) 实现跨节点持久化
"""
import threading
from typing import Optional, Dict

from src.blackboard.base_blackboard import BaseSubBlackboard
from src.blackboard.schema import ExecutionData
from src.common import get_logger, get_utc_now
from src.storage.repository.state_repo import StateRepo

logger = get_logger(__name__)

class ExecutionBlackboard(BaseSubBlackboard):
    board_name: str = "execution"

    def __init__(self):
        self._storage: Dict[str, Dict[str, ExecutionData]] = {} # 内存存储：tenant_id -> {task_id -> ExecutionData}
        self._lock = threading.RLock()
        logger.info("执行流子黑板初始化完成(已成功接入 Postgres StateRepo)", extra={"trace_id": "system"})

    def read(self, tenant_id: str, task_id: str) -> Optional[ExecutionData]:
        """
        读取执行数据

        :param tenant_id: 租户ID
        :param task_id: task_id 任务ID
        :return: ExecutionData 不存在返回None
        """
        with self._lock:
            tenant_data = self._storage.get(tenant_id, {})
            return tenant_data.get(task_id)
    
    def write(self, tenant_id: str, task_id: str, value: ExecutionData) -> bool:
        """
        写入执行数据

        :param tenant_id: 租户ID
        :param task_id: task_id 任务ID
        :param value: ExecutionData 实例
        :return: 写入成功返回True
        """
        if not isinstance(value, ExecutionData):
            logger.error(f"写入数据类型错误，必须是ExecutionData", extra={"trace_id": task_id})
            return False
        
        with self._lock:
            value.updated_at = get_utc_now()
            if tenant_id not in self._storage:
                self._storage[tenant_id] = {}
            self._storage[tenant_id][task_id] = value
            logger.debug(
                f"执行数据写入成功 tenant_id={tenant_id} task_id={task_id}",
                extra={"trace_id": task_id}
            )
            return True
    
    def delete(self, tenant_id: str, task_id: str) -> bool:
        with self._lock:
            if tenant_id and self._storage and  task_id in self._storage[tenant_id]:
                del self._storage[tenant_id][task_id]
                logger.info(
                    f"执行数据删除成功 tenant_id={tenant_id} task_id={task_id}",
                    extra={"trace_id": task_id}
                )
                return True
            return False

    def persist(self, tenant_id: str, task_id: str) -> bool:
        """🚀 委托模式：将持久化动作甩给底层 Repo"""
        data = self.read(tenant_id, task_id)
        if not data:
            logger.warning(f"持久化失败，数据不存在 tenant_id={tenant_id} task_id={task_id}", extra={"trace_id": task_id})
            return False
        
        workspace_id = getattr(data, 'workspace_id', 'default_ws')

        try:
            # 1. 从 DB 中捞出该 task_id 的全局混合状态 (避免覆盖 Knowledge 的数据)
            full_state = StateRepo.load_blackboard_state(tenant_id, task_id) or {}

            # 2. 局部更新当前子黑板 (execution) 的数据
            full_state[self.board_name] = data.model_dump()

            # 3. 整体回写给大管家，打入 Postgres
            StateRepo.save_blackboard_state(tenant_id, task_id, workspace_id, full_state)

            logger.debug(
                f"执行数据持久化成功 tenant_id={tenant_id} task_id={task_id}",
                extra={"trace_id": task_id}
            )
            return True
        except Exception as e:
            logger.error(
                f"执行数据持久化失败 tenant_id={tenant_id} task_id={task_id}: {str(e)}",
                extra={"trace_id": task_id}
            )
            return False
    
    def restore(self, tenant_id: str, task_id: str) -> bool:
        """从持久化文件恢复数据"""
        try:
            full_state = StateRepo.load_blackboard_state(tenant_id, task_id)

            if not full_state or self.board_name not in full_state:
                logger.warning(f"恢复跳过：DB 中不存在该任务的 {self.board_name} 状态", extra={"trace_id": task_id})
                return False

            data = ExecutionData(**full_state[self.board_name])

            self.write(tenant_id, task_id, data)
            logger.info(
                f"执行数据恢复成功 tenant_id={tenant_id} task_id={task_id}",
                extra={"trace_id": task_id}
            )
            return True
        except Exception as e:
            logger.error(
                f"执行数据恢复失败 tenant_id={tenant_id} task_id={task_id}: {str(e)}",
                extra={"trace_id": task_id}
            )
            return False

execution_blackboard = ExecutionBlackboard()