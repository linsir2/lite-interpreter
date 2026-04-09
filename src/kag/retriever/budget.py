"""上下文预算裁剪。"""

from __future__ import annotations

from config.settings import CONTEXT_MODEL_NAME

from src.common import fit_items_to_budget
from src.common.llm_client import LiteLLMClient


def enforce_budget(
    candidates: list[dict[str, object]],
    budget_tokens: int,
    *,
    query: str = "",
    model_alias: str = CONTEXT_MODEL_NAME,
) -> list[dict[str, object]]:
    if budget_tokens <= 0:
        return []
    model_name = LiteLLMClient.resolve_model_name(model_alias)
    base_messages = [{"role": "user", "content": query}] if query else []
    return fit_items_to_budget(
        candidates,
        budget_tokens=budget_tokens,
        base_messages=base_messages,
        model_name=model_name,
        render_item=lambda item: str(item.get("text", "")),
    )
