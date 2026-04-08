"""
集中配置管理模块

修改点：抽离所有分散的常量/配置，避免重复定义，提升可维护性
"""
import os
from typing import Any, Final

from docker.types import LogConfig
from dotenv import load_dotenv

load_dotenv()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    return int(raw)


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    return raw if raw else default

# -------------------------- 基础常量 --------------------------
MAX_CODE_LENGTH: Final[int] = _env_int("MAX_CODE_LENGTH", 1024 * 150)  # 150KB
MAX_TENANT_ID_LENGTH: Final[int] = 64
CONTAINER_NAME_PREFIX: Final[str] = "sandbox-"
MAX_RECURSION_DEPTH: Final[int] = 10  # AST解析最大递归深度
CODE_SNIPPET_MAX_LENGTH: Final[int] = 100  # 日志中代码片段最大长度
ZOMBIE_CONTAINER_TIMEOUT_FACTOR: Final[int] = 2  # 僵尸容器超时倍数

# -------------------------- Docker配置 --------------------------
DOCKER_CONFIG: Final[dict[str, Any]] = {
    "image": _env_str(
        "SANDBOX_IMAGE",
        "python:3.11-slim@sha256:6d98ca198cea726f2c86da2699594339a7b7ff08e49728797b4ed6e3b5c3b62a"
    ),
    "mem_limit": _env_str("SANDBOX_MEM_LIMIT", "128m"),
    "memswap_limit": _env_str("SANDBOX_MEM_LIMIT", "128m"),  # 禁用swap
    "cpu_shares": _env_int("SANDBOX_CPU_SHARES", 1024),
    "network_disabled": _env_str("SANDBOX_NETWORK_DISABLED", "true").lower() == "true",
    "user": _env_str("SANDBOX_RUN_USER", "1000:1000"),
    "timeout": _env_int("SANDBOX_EXEC_TIMEOUT", 60),  # 代码执行超时
    "container_operation_timeout": _env_int("SANDBOX_CONTAINER_OP_TIMEOUT", 10),  # 容器操作超时
    "max_tenant_concurrency": _env_int("SANDBOX_MAX_TENANT_CONCURRENCY", 10),  # 单租户最大并发
    "pids_limit": 64,
    "cap_drop": [
        "ALL",  # 移除所有权限
    ],
    "security_opt": [
        "no-new-privileges:true",  # 禁止提权
    ],
    "tmpfs": {"/tmp": "size=64m,mode=1777,nosuid,nodev,noexec"},  # 增强tmpfs安全
    "log_config": LogConfig(
        type="json-file",
        config={"max-size": "1m", "max-file": "1"}  # 单个容器最多写 1MB 日志，超过就覆盖
    )
}

# -------------------------- 服务配置 --------------------------
ZOMBIE_CLEAN_INTERVAL: Final[int] = _env_int("ZOMBIE_CLEAN_INTERVAL", 300)  # 僵尸容器清理间隔（秒）
