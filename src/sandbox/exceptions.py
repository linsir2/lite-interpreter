from src.common import BaseAppException


class SandboxBaseError(BaseAppException):
    """沙箱基础异常类"""

    error_type: str = "sandbox_base_error"


class InputValidationError(SandboxBaseError):
    """输入校验异常"""

    error_type: str = "input_validation_error"


# AST语法解析异常
class SyntaxParseError(SandboxBaseError):
    error_type: str = "syntax_error"


# AST审计失败异常（扩展risk_type）
class AuditFailError(SandboxBaseError):
    error_type: str = "audit_fail"

    def __init__(self, message: str, trace_id: str, risk_type: str):
        self.risk_type = risk_type
        super().__init__(message, trace_id)


# 执行层专属异常
class ExecTimeoutError(SandboxBaseError):
    error_type: str = "execution_timeout"


class DockerOperationError(SandboxBaseError):
    error_type: str = "docker_exception"


class CodeExecError(SandboxBaseError):
    error_type: str = "code_exec_error"
