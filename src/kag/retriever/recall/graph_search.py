"""图谱检索。"""

from __future__ import annotations

from typing import Any

from src.storage.repository.knowledge_repo import KnowledgeRepo

from .filters import extract_query_terms


def recall(
    query: str,
    tenant_id: str,
    filters: dict[str, Any] | None = None,
    workspace_id: str = "default_ws",
    top_k: int = 10,
) -> list[dict[str, object]]:
    terms = extract_query_terms(query)
    results = KnowledgeRepo.search_graph_facts(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        query_terms=terms,
        limit=top_k,
    )
    for item in results:
        item["retrieval_type"] = "graph"
    return results
