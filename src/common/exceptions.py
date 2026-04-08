"""
全局异常基类（所有模块共用）
"""


class BaseAppException(Exception):
    """全局基础异常类（所有自定义异常的基类）"""
    error_type: str = "base_error"

    def __init__(self, message: str, trace_id: str | None = None):
        self.message = message
        self.trace_id = trace_id or "no-trace"
        super().__init__(f"[{self.error_type}] trace_id={self.trace_id}: {message}")