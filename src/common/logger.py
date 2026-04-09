"""
全局日志配置（所有模块共用）

1. 统一日志格式、轮转策略

2. 支持trace_id字段

3. 提供get_logger函数，所有模块直接调用
"""

import logging
from logging.handlers import RotatingFileHandler

from config.settings import DATETIME_FORMAT, LOG_LEVEL, LOG_MAX_LENGTH, PROJECT_ROOT

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    """
    配置日志器（添加轮转、统一格式）

    :param name: 日志器名称
    :return: 配置后的日志器
    """
    logger = logging.getLogger(name)
    logger.setLevel(LOG_LEVEL)

    # 避免重复添加处理器
    if logger.handlers:
        return logger

    # 格式器：统一trace_id字段
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - [%(levelname)s] - tenant:%(tenant_id)s | ws:%(workspace_id)s | trace:%(trace_id)s - %(message)s",
        datefmt=DATETIME_FORMAT,
    )

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件轮转处理器（修改：添加日志轮转，避免日志文件过大）
    log_file_path = LOG_DIR / "system.log"
    file_handler = RotatingFileHandler(
        filename=str(log_file_path), maxBytes=LOG_MAX_LENGTH, backupCount=10, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 添加trace_id过滤器（默认填充no-trace）
    class ContextFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            if not hasattr(record, "trace_id"):
                record.trace_id = "no-trace"
            if not hasattr(record, "tenant_id"):
                record.tenant_id = "system"
            if not hasattr(record, "workspace_id"):
                record.workspace_id = "system"
            return True

    logger.addFilter(ContextFilter())
    return logger
