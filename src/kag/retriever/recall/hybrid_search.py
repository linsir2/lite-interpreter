"""混合检索与 RRF 融合。"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from src.kag.builder.embedding import EmbeddingGenerator
from src.storage.repository.knowledge_repo import KnowledgeRepo
from config.settings import HYBRID_RRF_K, VECTOR_TOP_K
from .filters import normalize_filters


DEFAULT_WORKSPACE = "default_ws"


def vector_recall(
    query: str,
    tenant_id: str,
    filters: Optional[Dict[str, Any]] = None,
    workspace_id: str = DEFAULT_WORKSPACE,
    top_k: int = VECTOR_TOP_K,
) -> List[Dict[str, object]]:
    embedder = EmbeddingGenerator()
    query_vector = embedder.embed_query(query)
    results = KnowledgeRepo.search_vector_chunks(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        query_vector=query_vector,
        filters=normalize_filters(filters or {}),
        limit=top_k,
    )
    for item in results:
        item["retrieval_type"] = "vector"
    return results


def fuse_results(result_sets: List[List[Dict[str, object]]], top_k: int = 15, rrf_k: int = HYBRID_RRF_K) -> List[Dict[str, object]]:
    score_board: Dict[str, float] = defaultdict(float)
    payloads: Dict[str, Dict[str, object]] = {}
    for result_set in result_sets:
        for rank, item in enumerate(result_set, start=1):
            key = str(item.get("chunk_id") or item.get("text") or rank)
            score_board[key] += 1.0 / (rrf_k + rank)
            payloads[key] = item
    fused = []
    for key, score in score_board.items():
        fused.append({**payloads[key], "score": float(score)})
    fused.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
    return fused[:top_k]
