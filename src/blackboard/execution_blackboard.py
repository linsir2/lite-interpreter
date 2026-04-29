"""
执行流子黑板：存储任务执行全流程的中间数据

- 读写特征：高频读写、生命周期短、精确查找

- 开发期：内存字典实现

- 生产期：完美委托给 StateRepo (PostgreSQL JSONB) 实现跨节点持久化
"""

import threading

from src.blackboard.base_blackboard import BaseSubBlackboard
from src.blackboard.schema import ExecutionData
from src.common import get_logger, get_utc_now
from src.storage.repository.state_repo import StateRepo

logger = get_logger(__name__)


class ExecutionBlackboard(BaseSubBlackboard):
    board_name: str = "execution"

    def __init__(self):
        self._storage: dict[str, dict[str, ExecutionData]] = {}  # 内存存储：tenant_id -> {task_id -> ExecutionData}
        self._lock = threading.RLock()
        logger.info("执行流子黑板初始化完成(已成功接入 Postgres StateRepo)", extra={"trace_id": "system"})

    def read(self, tenant_id: str, task_id: str) -> ExecutionData | None:
        """
        读取执行数据

        :param tenant_id: 租户ID
        :param task_id: task_id 任务ID
        :return: ExecutionData 不存在返回None
        """
        with self._lock:
            tenant_data = self._storage.get(tenant_id, {})
            return tenant_data.get(task_id)

    @staticmethod
    def _is_newer_execution_data(candidate: ExecutionData, current: ExecutionData | None) -> bool:
        if current is None:
            return True
        return candidate.control.updated_at > current.control.updated_at

    def write(
        self,
        tenant_id: str,
        task_id: str,
        value: ExecutionData,
        *,
        refresh_updated_at: bool = True,
    ) -> bool:
        """
        写入执行数据

        :param tenant_id: 租户ID
        :param task_id: task_id 任务ID
        :param value: ExecutionData 实例
        :param refresh_updated_at:
            - True: 正常业务写入，刷新 updated_at
            - False: 恢复/缓存回填，保留原始更新时间
        :return: 写入成功返回True
        """
        if not isinstance(value, ExecutionData):
            logger.error("写入数据类型错误，必须是ExecutionData", extra={"trace_id": task_id})
            return False

        with self._lock:
            if refresh_updated_at:
                value.control.updated_at = get_utc_now()
            if tenant_id not in self._storage:
                self._storage[tenant_id] = {}
            self._storage[tenant_id][task_id] = value
            logger.debug(f"执行数据写入成功 tenant_id={tenant_id} task_id={task_id}", extra={"trace_id": task_id})
            return True

    def delete(self, tenant_id: str, task_id: str) -> bool:
        with self._lock:
            if tenant_id in self._storage and task_id in self._storage[tenant_id]:
                del self._storage[tenant_id][task_id]
                logger.info(f"执行数据删除成功 tenant_id={tenant_id} task_id={task_id}", extra={"trace_id": task_id})
                return True
            return False

    def persist(self, tenant_id: str, task_id: str) -> bool:
        data = self.read(tenant_id, task_id)
        if not data:
            logger.warning(
                f"持久化失败，数据不存在 tenant_id={tenant_id} task_id={task_id}", extra={"trace_id": task_id}
            )
            return False

        workspace_id = getattr(data, "workspace_id", "default_ws")

        try:
            StateRepo.merge_blackboard_sections(
                tenant_id,
                task_id,
                workspace_id,
                {self.board_name: data.model_dump()},
            )

            logger.debug(f"执行数据持久化成功 tenant_id={tenant_id} task_id={task_id}", extra={"trace_id": task_id})
            return True
        except Exception as e:
            logger.error(
                f"执行数据持久化失败 tenant_id={tenant_id} task_id={task_id}: {str(e)}", extra={"trace_id": task_id}
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

            # restore 的目标是把持久化态原样回填到当前单例缓存，
            # 不是制造一次新的执行状态写入。
            self.write(tenant_id, task_id, data, refresh_updated_at=False)
            logger.info(f"执行数据恢复成功 tenant_id={tenant_id} task_id={task_id}", extra={"trace_id": task_id})
            return True
        except Exception as e:
            logger.error(
                f"执行数据恢复失败 tenant_id={tenant_id} task_id={task_id}: {str(e)}", extra={"trace_id": task_id}
            )
            return False

    def list_workspace_states(self, tenant_id: str, workspace_id: str) -> list[ExecutionData]:
        """
        列出某个 tenant/workspace 下的执行态快照。

        这个方法的目的不是替代查询层，而是避免上层 API 直接扫描
        `StateRepo.list_blackboard_states()` 再自己拼 execution payload。
        """

        known: dict[str, ExecutionData] = {}
        with self._lock:
            for task_id, payload in self._storage.get(tenant_id, {}).items():
                if payload.workspace_id != workspace_id:
                    continue
                known[task_id] = payload

        for state in StateRepo.list_blackboard_states():
            payload = state.get(self.board_name)
            if not isinstance(payload, dict):
                continue
            try:
                data = ExecutionData(**payload)
            except Exception:
                continue
            if data.tenant_id != tenant_id or data.workspace_id != workspace_id:
                continue
            current = known.get(data.task_id)
            if current is None or self._is_newer_execution_data(data, current):
                known[data.task_id] = data
        return list(known.values())


execution_blackboard = ExecutionBlackboard()
