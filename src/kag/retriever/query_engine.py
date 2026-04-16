"""KAG 统一查询引擎。"""

from __future__ import annotations

from config.settings import MAX_RETRIEVAL_TOP_K, RERANK_CANDIDATE_LIMIT

from src.blackboard.schema import RetrievalPlan
from src.common import EvidencePacket
from src.common.logger import get_logger
from src.kag.compiler import LexiconMatcher

from .budget import enforce_budget
from .cache import RetrievalCache
from .dedup import semantic_dedup
from .query_understanding import analyze_query
from .recall import bm25_search, graph_search, hybrid_search, splade_search
from .rerank import cross_encoder_rerank

logger = get_logger(__name__)


def _bounded_top_k(value: int) -> int:
    return max(1, min(int(value or 1), MAX_RETRIEVAL_TOP_K))


def is_keyword_query(query: str) -> bool:
    normalized = " ".join(query.strip().split())
    if not normalized:
        return False
    question_words = ["如何", "为什么", "怎么", "啥", "哪", "帮我"]
    if any(word in normalized for word in question_words):
        return False

    has_chinese = any("\u4e00" <= char <= "\u9fff" for char in normalized)
    if has_chinese:
        lexical_hits = LexiconMatcher().match_text(normalized)
        if lexical_hits and len(lexical_hits) <= 4:
            return True
        compact = normalized.replace(" ", "")
        if len(compact) > 12:
            return False
        try:
            import jieba

            tokens = [token for token in jieba.lcut(normalized) if token.strip()]
            return len(tokens) <= 4
        except Exception:
            return len(compact) <= 12

    words = normalized.split()
    return len(words) <= 3 and len(normalized) <= 32


class QueryEngine:
    @staticmethod
    def execute_with_evidence(
        query: str,
        plan: RetrievalPlan,
        tenant_id: str,
        workspace_id: str = "default_ws",
    ) -> EvidencePacket:
        logger.info(f"[QueryEngine] 启动检索，query={query}")
        bounded_top_k = _bounded_top_k(plan.top_k)
        search_query = query
        filters: dict[str, object] = {}
        difficulty_score = 0.5
        is_multi_hop = False

        if plan.enable_qu:
            search_query, filters, difficulty_score, is_multi_hop = analyze_query(query, tenant_id)
            if not plan.enable_filter:
                filters = {}
        if plan.preferred_date_terms:
            filters["preferred_date_terms"] = list(dict.fromkeys(str(item).strip() for item in plan.preferred_date_terms if str(item).strip()))
        if plan.temporal_constraints:
            filters["temporal_constraints"] = list(dict.fromkeys(str(item).strip() for item in plan.temporal_constraints if str(item).strip()))

        cache_key = RetrievalCache.make_key(tenant_id, workspace_id, search_query, filters)
        cached = RetrievalCache.get(cache_key)
        cache_hit = cached is not None
        if cached is not None:
            return EvidencePacket(
                query=query,
                rewritten_query=search_query,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                hits=cached,
                evidence_refs=[str(item.get("chunk_id")) for item in cached if item.get("chunk_id")],
                filters=dict(filters),
                recall_strategies=list(plan.recall_strategies),
                cache_hit=True,
                difficulty_score=difficulty_score,
                is_multi_hop=is_multi_hop,
                budget_tokens=plan.budget_tokens,
                metadata={
                    "routing_strategy": plan.routing_strategy,
                    "preferred_date_terms": list(plan.preferred_date_terms),
                    "temporal_constraints": list(plan.temporal_constraints),
                },
            )

        sparse_results: list[dict[str, object]] = []
        if is_keyword_query(query) or difficulty_score < 0.4:
            if "bm25" in plan.recall_strategies:
                sparse_results.extend(
                    bm25_search.recall(search_query, tenant_id, filters=filters, workspace_id=workspace_id)
                )
        else:
            if "splade" in plan.recall_strategies:
                sparse_results.extend(
                    splade_search.recall(search_query, tenant_id, filters=filters, workspace_id=workspace_id)
                )
            elif "bm25" in plan.recall_strategies:
                sparse_results.extend(
                    bm25_search.recall(search_query, tenant_id, filters=filters, workspace_id=workspace_id)
                )

        vector_results: list[dict[str, object]] = []
        if "vector" in plan.recall_strategies and difficulty_score >= 0.3:
            vector_results = hybrid_search.vector_recall(
                search_query, tenant_id, filters=filters, workspace_id=workspace_id
            )

        graph_results: list[dict[str, object]] = []
        if "graph" in plan.recall_strategies and (difficulty_score >= 0.7 or is_multi_hop):
            graph_results = graph_search.recall(search_query, tenant_id, filters=filters, workspace_id=workspace_id)

        if vector_results or graph_results:
            candidates = hybrid_search.fuse_results(
                [sparse_results, vector_results, graph_results],
                top_k=min(max(bounded_top_k * 2, bounded_top_k), RERANK_CANDIDATE_LIMIT),
            )
        else:
            candidates = sparse_results

        if not candidates:
            RetrievalCache.set(cache_key, [])
            return EvidencePacket(
                query=query,
                rewritten_query=search_query,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                hits=[],
                evidence_refs=[],
                filters=dict(filters),
                recall_strategies=list(plan.recall_strategies),
                cache_hit=cache_hit,
                difficulty_score=difficulty_score,
                is_multi_hop=is_multi_hop,
                budget_tokens=plan.budget_tokens,
                metadata={
                    "routing_strategy": plan.routing_strategy,
                    "preferred_date_terms": list(plan.preferred_date_terms),
                    "temporal_constraints": list(plan.temporal_constraints),
                },
            )

        unique_candidates = semantic_dedup(candidates)
        if plan.enable_rerank:
            ranked_docs = cross_encoder_rerank(query, unique_candidates, top_k=bounded_top_k)
        else:
            ranked_docs = sorted(unique_candidates, key=lambda item: float(item.get("score", 0.0)), reverse=True)[
                : bounded_top_k
            ]

        final_docs = enforce_budget(ranked_docs, plan.budget_tokens, query=query)
        RetrievalCache.set(cache_key, final_docs)
        return EvidencePacket(
            query=query,
            rewritten_query=search_query,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            hits=final_docs,
            evidence_refs=[str(item.get("chunk_id")) for item in final_docs if item.get("chunk_id")],
            filters=dict(filters),
            recall_strategies=list(plan.recall_strategies),
            cache_hit=cache_hit,
            difficulty_score=difficulty_score,
            is_multi_hop=is_multi_hop,
            budget_tokens=plan.budget_tokens,
            metadata={
                "routing_strategy": plan.routing_strategy,
                "candidate_count": len(candidates),
                "deduped_candidate_count": len(unique_candidates),
                "rerank_candidate_limit": min(max(bounded_top_k * 2, bounded_top_k), RERANK_CANDIDATE_LIMIT),
                "selected_count": len(final_docs),
                "final_top_k": bounded_top_k,
                "preferred_date_terms": list(plan.preferred_date_terms),
                "temporal_constraints": list(plan.temporal_constraints),
            },
        )

    @staticmethod
    def execute(
        query: str,
        plan: RetrievalPlan,
        tenant_id: str,
        workspace_id: str = "default_ws",
    ) -> list[dict[str, object]]:
        packet = QueryEngine.execute_with_evidence(query, plan, tenant_id, workspace_id=workspace_id)
        return packet.hits
