"""
全局统一blackboard: 项目状态中枢

- 子黑板注册中心

- 任务总状态管理

- 事件统一分发 -> 与前端交互
"""
import threading
from typing import Dict, Optional
from src.common.event_bus import event_bus
from src.blackboard.base_blackboard import BaseSubBlackboard
from src.blackboard.schema import TaskGlobalState, GlobalStatus
from src.blackboard.exceptions import SubBoardNotRegisteredError, TaskNotExistError, StatusUpdateError
from src.common import get_logger, generate_uuid, get_utc_now, EventTopic
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
        self._sub_boards: Dict[str, BaseSubBlackboard] = {} # board_name -> 子黑板实例
        self._task_states: Dict[str, TaskGlobalState] = {} # task_id -> TaskGlobalState
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

    def _restore_task_state(self, task_id: str) -> Optional[TaskGlobalState]:
        full_state = StateRepo.load_blackboard_state_by_task(task_id)
        if not full_state or "global" not in full_state:
            return None
        task_state = TaskGlobalState(**full_state["global"])
        self._task_states[task_id] = task_state
        return task_state

    def _get_task_state_locked(self, task_id: str) -> TaskGlobalState:
        task = self._task_states.get(task_id)
        if task:
            return task
        restored = self._restore_task_state(task_id)
        if restored:
            return restored
        raise TaskNotExistError(f"任务 {task_id} 不存在")

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
        input_query: Optional[str] = None,
        max_retry_times: int = 3,
    ) -> str:
        """
        创建新任务，生成唯一task_id，初始化总状态，发布TASK_CREATED事件

        :return: 任务ID
        """
        if input_query is None:
            # 兼容旧调用：create_task(tenant_id, input_query)
            input_query = workspace_id
            workspace_id = "default_ws"

        with self._rw_lock:
            task_id = generate_uuid()
            task_state = TaskGlobalState(
                task_id=task_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                input_query=input_query,
                max_retries=max_retry_times,
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
    
    def get_task_state(self, task_id: str) -> TaskGlobalState:
        """获取任务全局状态"""
        with self._rw_lock:
            return self._get_task_state_locked(task_id)
    
    def update_global_status(self, task_id: str, new_status: GlobalStatus, sub_status: Optional[str] = None, **kwargs) -> None:
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
            
            status_payload = {
                "old_status": old_status.value,
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
                    "cost_info": {"max_retries": task.max_retries, "used_retries": task.current_retries}
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
                GlobalStatus.EVALUATING
                # 注：WAITING_FOR_HUMAN 不包含在内，因为它需要等待前端用户主动触发，不能由系统自动盲目重启
                # SUCCESS, FAILED, ARCHIVED 属于终态
            ]
            known_tasks = {task.task_id: task for task in self._task_states.values()}
            for state in StateRepo.list_blackboard_states():
                payload = state.get("global")
                if not isinstance(payload, dict):
                    continue
                task = TaskGlobalState(**payload)
                known_tasks.setdefault(task.task_id, task)
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
