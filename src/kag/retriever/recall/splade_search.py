"""SPLADE 的规则化 MVP 实现：扩展关键词后再做稀疏召回。"""

from __future__ import annotations

from typing import Any

from src.storage.repository.knowledge_repo import KnowledgeRepo

from .filters import exact_match_filters, extract_query_terms, normalize_filters, temporal_query_terms

SYNONYMS = {
    "规则": ["标准", "制度", "口径"],
    "指标": ["metric", "口径", "ratio"],
    "合规": ["风控", "审计", "规范"],
}


def recall(
    query: str,
    tenant_id: str,
    filters: dict[str, Any] | None = None,
    workspace_id: str = "default_ws",
    top_k: int = 20,
) -> list[dict[str, object]]:
    normalized_filters = normalize_filters(filters or {})
    terms = extract_query_terms(query, temporal_query_terms(normalized_filters))
    expanded = list(terms)
    for term in terms:
        expanded.extend(SYNONYMS.get(term, []))
    results = KnowledgeRepo.search_text_chunks(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        query_terms=expanded,
        filters=exact_match_filters(normalized_filters),
        limit=top_k,
    )
    for item in results:
        item["score"] = float(item.get("score", 0.0)) * 1.05
        item["retrieval_type"] = "splade"
    return results
