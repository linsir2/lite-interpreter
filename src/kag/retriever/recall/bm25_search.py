"""基于 PG 真相源的稀疏文本召回。"""

from __future__ import annotations

from typing import Any

from src.storage.repository.knowledge_repo import KnowledgeRepo

from .filters import extract_query_terms, normalize_filters

DEFAULT_WORKSPACE = "default_ws"


def recall(
    query: str,
    tenant_id: str,
    filters: dict[str, Any] | None = None,
    workspace_id: str = DEFAULT_WORKSPACE,
    top_k: int = 20,
) -> list[dict[str, object]]:
    terms = extract_query_terms(query)
    results = KnowledgeRepo.search_text_chunks(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        query_terms=terms,
        filters=normalize_filters(filters or {}),
        limit=top_k,
    )
    for item in results:
        item["retrieval_type"] = "bm25"
    return results
