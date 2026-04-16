"""MCP 知识查询工具：供 DAG 或外部网关以统一协议调用 KAG。"""

from __future__ import annotations

from typing import Any

from config.settings import MAX_RETRIEVAL_TOP_K

from src.blackboard.schema import RetrievalPlan
from src.kag.retriever.query_engine import QueryEngine


class KnowledgeQueryTool:
    CAPABILITY_ID = "knowledge_query"

    @staticmethod
    def run(
        query: str,
        tenant_id: str,
        workspace_id: str = "default_ws",
        top_k: int = 8,
        preferred_date_terms: list[str] | None = None,
        temporal_constraints: list[str] | None = None,
    ) -> dict[str, Any]:
        bounded_top_k = max(1, min(int(top_k or 1), MAX_RETRIEVAL_TOP_K))
        plan = RetrievalPlan(
            top_k=bounded_top_k,
            preferred_date_terms=list(preferred_date_terms or []),
            temporal_constraints=list(temporal_constraints or []),
        )
        packet = QueryEngine.execute_with_evidence(
            query=query, plan=plan, tenant_id=tenant_id, workspace_id=workspace_id
        )
        return packet.model_dump(mode="json")
