from src.common.exceptions import BaseAppException


class BlackboardException(BaseAppException):
    """黑板基础异常"""
    error_type: str = "blackboard_error"

class SubBoardNotRegisteredError(BlackboardException):
    """子黑板未注册异常"""
    error_type: str = "sub_board_not_registered"

class TaskNotExistError(BlackboardException):
    """任务不存在异常"""
    error_type: str = "task_not_exist"

class StatusUpdateError(BlackboardException):
    """状态更新失败异常"""
    error_type: str = "status_update_error"