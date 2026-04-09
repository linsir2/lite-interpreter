"""沙箱专属工具函数"""

import re
from typing import Any

from config.sandbox_config import CODE_SNIPPET_MAX_LENGTH, MAX_CODE_LENGTH, MAX_TENANT_ID_LENGTH
from config.security_config import TENANT_ID_PATTERN

from src.common import format_utc_datetime, get_utc_now, truncate_string
from src.sandbox.exceptions import InputValidationError


def validate_code_basic(code: str, trace_id: str) -> None:
    """校验代码合法性"""
    if not code or not code.strip():
        raise InputValidationError("待执行代码不能为空", trace_id)
    if len(code) > MAX_CODE_LENGTH:
        raise InputValidationError(
            f"代码长度超过限制，最大支持{MAX_CODE_LENGTH}字节（当前：{len(code)}字节）", trace_id
        )


def validate_code(code: str, trace_id: str) -> None:
    """完整代码校验：包含基础校验+额外规则，给一站式入口用"""
    # 先做基础校验
    validate_code_basic(code, trace_id)
    # 可以在这里加额外的完整校验规则（比如禁止某些特定的注释格式等）
    # ...


def validate_tenant_id(tenant_id: str, trace_id: str) -> None:
    """校验租户ID合法性"""
    if not tenant_id or not tenant_id.strip():
        raise InputValidationError("租户ID不能为空", trace_id)
    if len(tenant_id) > MAX_TENANT_ID_LENGTH:
        raise InputValidationError(
            f"租户ID长度超过限制，最大支持{MAX_TENANT_ID_LENGTH}字符（当前：{len(tenant_id)}字符）", trace_id
        )
    if not re.match(TENANT_ID_PATTERN, tenant_id):
        raise InputValidationError("租户ID仅支持字母、数字、下划线、横杠", trace_id)


def build_log_data(tenant_id: str, event_type: str, code: str, trace_id: str) -> dict[str, Any]:
    """构建标准化日志数据"""
    return {
        "tenant_id": tenant_id,
        "event_type": event_type,
        "code_snippet": truncate_string(code.replace("\n", "\\n"), CODE_SNIPPET_MAX_LENGTH),
        "audit_result": None,
        "risk_type": None,
        "reason": None,
        "exec_duration_seconds": None,
        "timestamp": format_utc_datetime(get_utc_now()),
        "trace_id": trace_id,
    }
