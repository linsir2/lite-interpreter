"""
全局统一blackboard: 项目状态中枢

- 子黑板注册中心

- 任务总状态管理

- 事件统一分发 -> 与前端交互 ：前端、SSE、监控、恢复逻辑需要一个很轻量、稳定、统一的任务状态对象
"""
import threading
from typing import Optional

from src.blackboard.base_blackboard import BaseSubBlackboard
from src.blackboard.exceptions import StatusUpdateError, SubBoardNotRegisteredError, TaskNotExistError
from src.blackboard.schema import GlobalStatus, TaskGlobalState
from src.common import EventTopic, generate_uuid, get_logger, get_utc_now
from src.common.event_bus import event_bus
from src.storage.repository.state_repo import StateRepo

logger = get_logger(__name__)

class GlobalBlackboard:
    """全局黑板单例"""
    _instance: Optional["GlobalBlackboard"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance
    
    def _init(self):
        self._sub_boards: dict[str, BaseSubBlackboard] = {} # board_name -> 子黑板实例
        self._task_states: dict[str, TaskGlobalState] = {} # task_id -> TaskGlobalState
        self._rw_lock = threading.RLock()
        logger.info("全局黑板初始化完成", extra={"trace_id": "system"})

    def _persist_task_state(self, task_state: TaskGlobalState) -> None:
        full_state = StateRepo.load_blackboard_state(task_state.tenant_id, task_state.task_id) or {}
        full_state["global"] = task_state.model_dump(mode="json")
        StateRepo.save_blackboard_state(
            task_state.tenant_id,
            task_state.task_id,
            task_state.workspace_id,
            full_state,
        )

    @staticmethod
    def _is_newer_task_state(candidate: TaskGlobalState, current: TaskGlobalState | None) -> bool:
        if current is None:
            return True
        return candidate.updated_at > current.updated_at

    def _load_persisted_task_state(self, task_id: str) -> TaskGlobalState | None:
        full_state = StateRepo.load_blackboard_state_by_task(task_id)
        if not full_state or "global" not in full_state:
            return None
        try:
            return TaskGlobalState(**full_state["global"])
        except Exception:
            return None

    def _restore_task_state(self, task_id: str) -> TaskGlobalState | None:
        task_state = self._load_persisted_task_state(task_id)
        if task_state is None:
            return None
        self._task_states[task_id] = task_state
        return task_state

    def _get_task_state_locked(self, task_id: str) -> TaskGlobalState:
        task = self._task_states.get(task_id)
        persisted = self._load_persisted_task_state(task_id)
        if persisted and self._is_newer_task_state(persisted, task):
            # 这里不能只要“内存里有”就直接返回。
            # 在租约/多实例场景下，其他进程可能已经把更晚的任务状态写入持久层；
            # 如果继续抱着旧缓存不放，结果接口和恢复逻辑都会看到陈旧状态。
            self._task_states[task_id] = persisted
            return persisted
        if task:
            return task
        if persisted:
            self._task_states[task_id] = persisted
            return persisted
        raise TaskNotExistError(f"任务 {task_id} 不存在")

    def _iter_known_global_states_locked(self) -> list[TaskGlobalState]:
        known_tasks = {task.task_id: task for task in self._task_states.values()}
        for state in StateRepo.list_blackboard_states():
            payload = state.get("global")
            if not isinstance(payload, dict):
                continue
            try:
                task = TaskGlobalState(**payload)
            except Exception:
                continue
            current = known_tasks.get(task.task_id)
            if current is None or self._is_newer_task_state(task, current):
                known_tasks[task.task_id] = task
        return list(known_tasks.values())

    def register_sub_board(self, sub_board: BaseSubBlackboard) -> None:
        """
        注册子黑板，后续新增子黑板只需调用此方法，无需修改全局黑板代码

        :param sub_board: 继承BaseSubBlackboard的子黑板实例
        """
        with self._rw_lock:
            board_name = sub_board.board_name
            if board_name in self._sub_boards:
                logger.warning(f"子黑板 {board_name} 已注册，将覆盖原有实例", extra={"trace_id": "system"})
            self._sub_boards[board_name] = sub_board
            logger.info(f"子黑板 {board_name} 注册成功", extra={"trace_id": "system"})
    
    def get_sub_board(self, board_name: str) -> BaseSubBlackboard:
        with self._rw_lock:
            board = self._sub_boards.get(board_name)
            if not board:
                raise SubBoardNotRegisteredError(f"sub_blackboard {board_name} 未注册")
            return board
    
    # -------------------------- 任务生命周期管理 --------------------------
    def create_task(
        self,
        tenant_id: str,
        workspace_id: str,
        input_query: str,
        max_retry_times: int = 3,
        idempotency_key: str | None = None,
        request_fingerprint: str | None = None,
    ) -> str:
        """
        创建新任务，生成唯一task_id，初始化总状态，发布TASK_CREATED事件

        :return: 任务ID
        """
        with self._rw_lock:
            if idempotency_key:
                existing = self.find_task_by_idempotency(
                    tenant_id,
                    workspace_id,
                    idempotency_key,
                )
                if existing:
                    existing_fingerprint = str(existing.request_fingerprint or "")
                    incoming_fingerprint = str(request_fingerprint or "")
                    if existing_fingerprint and incoming_fingerprint and existing_fingerprint != incoming_fingerprint:
                        raise StatusUpdateError("相同 idempotency_key 对应的请求体不一致，拒绝复用旧任务")
                    return existing.task_id

            task_id = generate_uuid()
            task_state = TaskGlobalState(
                task_id=task_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                input_query=input_query,
                max_retries=max_retry_times,
                idempotency_key=str(idempotency_key or "").strip() or None,
                request_fingerprint=str(request_fingerprint or "").strip() or None,
            )
            self._task_states[task_id] = task_state

            event_bus.publish(
                topic=EventTopic.UI_TASK_CREATED,
                tenant_id=tenant_id,
                task_id=task_id,
                workspace_id=workspace_id,
                payload={
                    "task_info": task_state.model_dump(),
                    "message": "任务已创建，等待处理"
                },
                trace_id=task_id
            )
            logger.info(
                f"任务创建成功 task_id={task_id}",
                extra={"trace_id": task_id, "tenant_id": tenant_id}
            )
            self._persist_task_state(task_state)
            return task_id

    def find_task_by_idempotency(
        self,
        tenant_id: str,
        workspace_id: str,
        idempotency_key: str,
    ) -> TaskGlobalState | None:
        normalized_key = str(idempotency_key or "").strip()
        if not normalized_key:
            return None
        with self._rw_lock:
            for task in self._iter_known_global_states_locked():
                if task.tenant_id != tenant_id or task.workspace_id != workspace_id:
                    continue
                if str(task.idempotency_key or "") != normalized_key:
                    continue
                return task
        return None
    
    def get_task_state(self, task_id: str) -> TaskGlobalState:
        """获取任务全局状态"""
        with self._rw_lock:
            return self._get_task_state_locked(task_id)
    
    def update_global_status(self, task_id: str, new_status: GlobalStatus, sub_status: str | None = None, **kwargs) -> None:
        """
        更新任务全局状态

        :param task_id: 任务ID
        :param new_status: 新的全局状态
        :param sub_status: 可选，子状态
        :param kwargs: 额外要更新的字段
        """
        with self._rw_lock:
            task = self._get_task_state_locked(task_id)
            
            old_status = task.global_status

            task.global_status = new_status
            task.sub_status = sub_status
            task.updated_at = get_utc_now()

            for key, value in kwargs.items():
                if hasattr(task, key):
                    setattr(task, key, value)
            
            display_message = sub_status if sub_status else f"任务状态更新为 {new_status.value}"
            old_status_value = old_status.value if hasattr(old_status, "value") else str(old_status)
            
            status_payload = {
                "old_status": old_status_value,
                "new_status": new_status.value,
                "sub_status": sub_status,
                "message": display_message,  # 前端友好提示
                **kwargs
            }

            event_bus.publish(
                topic=EventTopic.UI_TASK_STATUS_UPDATE,  # 替换原 STATUS_CHANGED
                tenant_id=task.tenant_id,
                task_id=task_id,
                workspace_id=task.workspace_id,
                payload=status_payload,
                trace_id=task_id
            )

            if new_status in [GlobalStatus.SUCCESS, GlobalStatus.FAILED]:
                finish_payload = {
                    "task_id": task_id,
                    "final_status": new_status.value,
                    "failure_type": task.failure_type,
                    "error_message": task.error_message,
                    # 这里明确暴露“修复重试”语义，避免把它误解成整个任务的通用 retry 统计。
                    "retry_info": {
                        "scope": "codegen_debug_loop",
                        "max_repair_retries": task.max_retries,
                        "used_repair_retries": task.current_retries,
                    },
                }
                event_bus.publish(
                    topic=EventTopic.SYS_TASK_FINISHED,
                    tenant_id=task.tenant_id,
                    task_id=task_id,
                    workspace_id=task.workspace_id,
                    payload=finish_payload,
                    trace_id=task_id
                )
                # 失败任务额外发布监控告警事件
                if new_status == GlobalStatus.FAILED:
                    event_bus.publish(
                        topic=EventTopic.MONITOR_TASK_FAILED,
                        tenant_id=task.tenant_id,
                        task_id=task_id,
                        workspace_id=task.workspace_id,
                        payload={
                            "task_id": task_id,
                            "failure_type": task.failure_type,
                            "error_message": task.error_message,
                            "tenant_id": task.tenant_id,
                            "timestamp": task.updated_at.strftime("%Y-%m-%d %H:%M:%S")
                        },
                        trace_id=task_id
                    )

            logger.info(
                f"任务状态更新 task_id={task_id} {old_status.value} -> {new_status.value}",
                extra={"trace_id": task_id, "tenant_id": task.tenant_id}
            )
            self._persist_task_state(task)

    def list_unfinished_tasks(self) -> list[TaskGlobalState]:
        """获取当前所有未完成的任务（服务重启恢复用，防止每次重新处理）"""
        with self._rw_lock:
            # 必须包含所有处于 "流转中" 的节点状态
            unfinished_status = [
                GlobalStatus.PENDING, 
                GlobalStatus.ROUTING,             # Router 阶段
                GlobalStatus.PREPARING_CONTEXT,   # Data Inspector 阶段
                GlobalStatus.RETRIEVING,          # KAG Retriever 阶段
                GlobalStatus.ANALYZING, 
                GlobalStatus.CODING,
                GlobalStatus.AUDITING, 
                GlobalStatus.EXECUTING, 
                GlobalStatus.DEBUGGING,
                GlobalStatus.EVALUATING,
                GlobalStatus.HARVESTING,
                GlobalStatus.SUMMARIZING,
                # 注：WAITING_FOR_HUMAN 不包含在内，因为它需要等待前端用户主动触发，不能由系统自动盲目重启
                # SUCCESS, FAILED, ARCHIVED 属于终态
            ]
            known_tasks = {task.task_id: task for task in self._iter_known_global_states_locked()}
            return [
                task for task in known_tasks.values()
                if task.global_status in unfinished_status
            ]
    
    def archive_task(self, task_id: str) -> None:
        """归档已完成的任务"""
        with self._rw_lock:
            task = self._get_task_state_locked(task_id)
            if task.global_status not in [GlobalStatus.SUCCESS, GlobalStatus.FAILED]:
                raise StatusUpdateError(f"仅成功/失败的任务可归档，当前状态：{task.global_status.value}")
            
            task.global_status = GlobalStatus.ARCHIVED
            task.updated_at = get_utc_now()

            event_bus.publish(
                topic=EventTopic.MONITOR_TASK_ARCHIVED,
                tenant_id=task.tenant_id,
                task_id=task_id,
                workspace_id=task.workspace_id,
                payload={
                    "task_id": task_id,
                    "archive_time": task.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "final_status": task.global_status.value
                },
                trace_id=task_id
            )

            logger.info(f"任务已归档 task_id={task_id}", extra={"trace_id": task_id})
            self._persist_task_state(task)

global_blackboard = GlobalBlackboard()
