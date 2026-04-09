"""MCP 知识查询工具：供 DAG 或外部网关以统一协议调用 KAG。"""

from __future__ import annotations

from typing import Any

from src.blackboard.schema import RetrievalPlan
from src.kag.retriever.query_engine import QueryEngine


class KnowledgeQueryTool:
    CAPABILITY_ID = "knowledge_query"

    @staticmethod
    def run(query: str, tenant_id: str, workspace_id: str = "default_ws", top_k: int = 8) -> dict[str, Any]:
        plan = RetrievalPlan(top_k=top_k)
        packet = QueryEngine.execute_with_evidence(
            query=query, plan=plan, tenant_id=tenant_id, workspace_id=workspace_id
        )
        return packet.model_dump(mode="json")
