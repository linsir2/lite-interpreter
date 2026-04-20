"""通用工具函数"""

from __future__ import annotations

import datetime
import os
import re
import time
import uuid
from collections.abc import Callable, Sequence
from hashlib import sha256
from typing import Any

from config.settings import DATETIME_FORMAT, LOG_MAX_LENGTH

_WORD_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]|[^\s]")
_SCOPE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_MAX_SCOPE_ID_LENGTH = 64


def generate_uuid() -> str:
    """生成唯一ID"""
    return str(uuid.uuid4())


def get_utc_now() -> datetime.datetime:
    """获取UTC当前时间"""
    return datetime.datetime.now(datetime.UTC)


def format_utc_datetime(dt: datetime.datetime) -> str:
    """格式化UTC时间"""
    return dt.strftime(DATETIME_FORMAT)


def truncate_string(s: str, max_length: int = LOG_MAX_LENGTH) -> str:
    """截断字符串（超出长度时添加提示）"""
    if len(s) <= max_length:
        return s
    return f"{s[:max_length]}...[内容已截断，超出最大长度{max_length}字节]"


def get_current_timestamp() -> float:
    return time.time()


def build_tenant_key(board_name: str, tenant_id: str, key: str) -> str:
    """
    构建租户级隔离的Key，适配命名空间隔离

    规则：lite_interpreter:{board_name}:tenant:{tenant_id}:{key}
    """
    return f"lite_interpreter:{board_name}:tenant:{tenant_id}:{key}"


def validate_scope_identifier(value: str, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if len(normalized) > _MAX_SCOPE_ID_LENGTH:
        raise ValueError(f"{field_name} must be <= {_MAX_SCOPE_ID_LENGTH} characters")
    if not _SCOPE_ID_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field_name} must contain only letters, digits, `_`, or `-`")
    return normalized


def scope_identifier_to_db_name(value: str, *, prefix: str = "") -> str:
    normalized = validate_scope_identifier(value, field_name="scope identifier")
    hashed = sha256(normalized.encode("utf-8")).hexdigest()[:8]
    base = normalized.lower().replace("-", "_")
    if prefix:
        return f"{prefix}{base}_{hashed}"
    return f"{base}_{hashed}"


def estimate_tokens_fast(content: str) -> int:
    """轻量启发式 token 估算，供分类/粗筛用。"""
    if not content:
        return 0
    tokens = _WORD_PATTERN.findall(content)
    if not tokens:
        return 0
    return int(len(tokens) * 1.05)


def _count_with_litellm(
    *,
    model_name: str,
    messages: list[dict[str, Any]] | None = None,
) -> int | None:
    if str(os.getenv("LITE_INTERPRETER_DISABLE_LITELLM_TOKEN_COUNTER", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return None
    try:
        from litellm import token_counter
    except ImportError:
        return None

    try:
        return int(token_counter(model=model_name, messages=messages or []))
    except TypeError:
        try:
            text = " ".join(str(item.get("content", "")) for item in messages or [])
            return int(token_counter(model=model_name, text=text))
        except Exception:
            return None
    except Exception:
        return None


def count_message_tokens_exact(messages: Sequence[dict[str, Any]], model_name: str | None = None) -> int:
    """尽量按目标模型精确计数，失败时降级到启发式估算。"""
    normalized = [{"role": str(item.get("role", "user")), "content": str(item.get("content", ""))} for item in messages]
    if model_name:
        exact = _count_with_litellm(model_name=model_name, messages=normalized)
        if exact is not None:
            return exact
    return sum(estimate_tokens_fast(str(item.get("content", ""))) + 4 for item in normalized) + 2


def count_text_tokens_exact(content: str, model_name: str | None = None) -> int:
    return count_message_tokens_exact([{"role": "user", "content": content}], model_name=model_name)


def fit_items_to_budget(
    items: Sequence[Any],
    *,
    budget_tokens: int,
    base_messages: Sequence[dict[str, Any]] | None = None,
    model_name: str | None = None,
    render_item: Callable[[Any], str] | None = None,
) -> list[Any]:
    """Greedily keep items while respecting the final message budget."""
    if budget_tokens <= 0:
        return []

    base = list(base_messages or [])
    kept: list[Any] = []
    render = render_item or (lambda item: str(item))
    for item in items:
        trial_messages = list(base)
        trial_messages.extend({"role": "system", "content": render(existing)} for existing in kept)
        trial_messages.append({"role": "system", "content": render(item)})
        if count_message_tokens_exact(trial_messages, model_name=model_name) > budget_tokens:
            break
        kept.append(item)
    return kept


def estimate_tokens(content: str) -> int:
    """Estimate token usage with the fast heuristic."""
    return estimate_tokens_fast(content)
