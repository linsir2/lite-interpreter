"""
src/storage/graph_client.py
Neo4j 图数据库客户端

职责：执行 Cypher 语句，将知识三元组转化为图谱中的节点和边，并在检索阶段
提供面向租户/工作空间的事实查询能力。
"""
from __future__ import annotations

from typing import Any

try:
    from neo4j import GraphDatabase
except ImportError:  # pragma: no cover - optional runtime dependency
    GraphDatabase = None

from config.settings import NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER

from src.common.logger import get_logger
from src.storage.schema import KnowledgeTriple

logger = get_logger(__name__)


class GraphDBClient:
    def __init__(self) -> None:
        try:
            if GraphDatabase is None:
                raise ImportError("neo4j not installed")
            self.driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
            logger.info("[GraphClient] Neo4j 客户端初始化成功。")
        except Exception as exc:
            logger.error(f"[GraphClient] Neo4j 连接失败: {exc}")
            self.driver = None

    def has_graph(self, tenant_id: str, workspace_id: str) -> bool:
        if not self.driver:
            return False
        query = (
            "MATCH (n {tenant_id: $tenant_id, workspace_id: $workspace_id}) "
            "RETURN count(n) AS node_count LIMIT 1"
        )
        try:
            with self.driver.session() as session:
                result = session.run(query, tenant_id=tenant_id, workspace_id=workspace_id).single()
                return result.get("node_count", 0) > 0
        except Exception:
            return False

    def merge_triples(self, tenant_id: str, workspace_id: str, triples: list[KnowledgeTriple]):
        if not self.driver or not triples:
            return

        cypher_query = """
        UNWIND $batch AS row
        MERGE (h:Entity {id: row.head, tenant_id: $tenant_id, workspace_id: $workspace_id})
        ON CREATE SET h.label = row.head_label, h.created_at = row.created_at, h.source_chunks = [row.source_chunk_id]
        ON MATCH SET h.source_chunks = apoc.coll.toSet(coalesce(h.source_chunks, []) + row.source_chunk_id)
        MERGE (t:Entity {id: row.tail, tenant_id: $tenant_id, workspace_id: $workspace_id})
        ON CREATE SET t.label = row.tail_label, t.created_at = row.created_at, t.source_chunks = [row.source_chunk_id]
        ON MATCH SET t.source_chunks = apoc.coll.toSet(coalesce(t.source_chunks, []) + row.source_chunk_id)
        CALL apoc.merge.relationship(h, row.relation, {}, row.properties, t, row.properties) YIELD rel
        SET rel.graph_type = row.graph_type,
            rel.supported_by_chunk = row.source_chunk_id,
            rel.version = row.version,
            rel.created_at = row.created_at
        RETURN count(rel)
        """

        batch_data = []
        for triple in triples:
            properties = dict(triple.properties)
            version = properties.pop("version", "1.0")
            source_chunk_id = properties.pop("source_chunk_id", "unknown")
            graph_type = properties.get("graph_type", "entity")
            batch_data.append(
                {
                    "head": triple.head,
                    "head_label": triple.head_label,
                    "relation": triple.relation.replace(" ", "_").upper(),
                    "tail": triple.tail,
                    "tail_label": triple.tail_label,
                    "created_at": str(triple.created_at),
                    "properties": properties,
                    "source_chunk_id": source_chunk_id,
                    "version": version,
                    "graph_type": graph_type,
                }
            )

        try:
            with self.driver.session() as session:
                session.run(cypher_query, batch=batch_data, tenant_id=tenant_id, workspace_id=workspace_id)
        except Exception as exc:
            logger.error(f"[GraphClient] Cypher 执行失败: {exc}")
            raise

    def search_facts(
        self,
        tenant_id: str,
        workspace_id: str,
        query_terms: list[str],
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        if not self.driver or not query_terms:
            return []

        cypher = """
        MATCH (h:Entity {tenant_id: $tenant_id, workspace_id: $workspace_id})-[r]->(t:Entity {tenant_id: $tenant_id, workspace_id: $workspace_id})
        WHERE any(term IN $query_terms WHERE toLower(h.id) CONTAINS term OR toLower(t.id) CONTAINS term OR toLower(type(r)) CONTAINS term)
        RETURN h.id AS head,
               h.label AS head_label,
               type(r) AS relation,
               t.id AS tail,
               t.label AS tail_label,
               r.graph_type AS graph_type,
               r.supported_by_chunk AS source_chunk_id
        LIMIT $top_k
        """

        try:
            with self.driver.session() as session:
                rows = session.run(
                    cypher,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    query_terms=[term.lower() for term in query_terms],
                    top_k=top_k,
                )
                results = []
                for row in rows:
                    text = f"{row['head']} -[{row['relation']}]-> {row['tail']}"
                    results.append(
                        {
                            "text": text,
                            "score": 1.0,
                            "source": row.get("source_chunk_id") or "neo4j",
                            "graph_type": row.get("graph_type") or "entity",
                            "metadata": dict(row),
                            "retrieval_type": "graph",
                        }
                    )
                return results
        except Exception as exc:
            logger.error(f"[GraphClient] 图谱检索失败: {exc}")
            return []

    def close(self):
        if self.driver:
            self.driver.close()
            logger.info("[GraphClient] Neo4j 连接已安全断开。")


neo4j_client = GraphDBClient()
