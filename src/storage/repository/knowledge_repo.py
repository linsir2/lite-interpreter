"""
src/storage/repository/knowledge_repo.py
知识存储统一仓库 (Knowledge Repository)

职责：
1. 作为 KAG Builder 的唯一落库入口，隔离底层数据库方言。
2. 调度多库协同 (PG 为真相源，Qdrant 为热缓存，Neo4j 为推理网)。
3. 为检索层提供统一访问接口。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd
from src.common.logger import get_logger
from src.common.utils import get_utc_now
from src.storage.graph_client import neo4j_client
from src.storage.postgres_client import pg_client
from src.storage.schema import DocChunk, KnowledgeTriple, StructuredDatasetMeta
from src.storage.vector_client import qdrant_client

logger = get_logger(__name__)


class KnowledgeRepo:
    @classmethod
    def save_chunks_and_embeddings(
        cls,
        tenant_id: str,
        workspace_id: str,
        chunks: list[DocChunk],
        embeddings_map: dict[str, list[float]],
    ) -> bool:
        if not chunks:
            logger.error("[KnowledgeRepo] 数据为空，拒绝入库。")
            return False

        try:
            pg_client.insert_chunks(tenant_id, workspace_id, chunks)
            logger.info(f"[KnowledgeRepo] PG 落库成功: {len(chunks)} 条全量 Chunk。")

            if embeddings_map:
                qdrant_chunks: list[DocChunk] = []
                qdrant_embeddings: list[list[float]] = []
                for chunk in chunks:
                    vector = embeddings_map.get(chunk.chunk_id)
                    if vector is None:
                        continue
                    qdrant_chunks.append(chunk)
                    qdrant_embeddings.append(vector)
                if qdrant_chunks:
                    qdrant_client.upsert(tenant_id, workspace_id, qdrant_chunks, qdrant_embeddings)
                    logger.info(f"[KnowledgeRepo] Qdrant 索引成功: {len(qdrant_chunks)} 条语义子块。")
            return True
        except Exception as exc:
            logger.error(f"[KnowledgeRepo] 非结构化数据落库失败: {exc}", exc_info=True)
            return False

    @classmethod
    def save_graph_triples(cls, tenant_id: str, workspace_id: str, triples: list[KnowledgeTriple]) -> bool:
        if not triples:
            return True
        try:
            neo4j_client.merge_triples(tenant_id, workspace_id, triples)
            return True
        except Exception as exc:
            logger.error(f"[KnowledgeRepo] 图谱三元组写入失败: {exc}", exc_info=True)
            return False

    @classmethod
    def save_structured_data(
        cls,
        tenant_id: str,
        workspace_id: str,
        file_name: str,
        df: pd.DataFrame,
        semantic_summary: str | None,
        persist: bool = False,
    ):
        try:
            safe_name = file_name.replace(".", "_").replace("-", "_").lower()
            timestamp = get_utc_now().strftime("%Y%m%d_%H%M")
            db_table_name = f"ws_{workspace_id}_{safe_name}_{timestamp}"
            pg_client.df_to_sql_table(tenant_id, db_table_name, df)
            expires_at = None if persist else get_utc_now() + timedelta(hours=24)
            catalog_data = {
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "original_file_name": file_name,
                "db_table_name": db_table_name,
                "semantic_summary": semantic_summary,
                "time_coverage": "自动推断",
                "keywords": df.columns.tolist()[:10],
                "is_persisted": persist,
                "expires_at": expires_at,
            }
            pg_client.register_dataset_catalog(catalog_data)
            logger.info(f"[KnowledgeRepo] 结构化资产 '{file_name}' 注册完毕，物理表: {db_table_name}")
            return StructuredDatasetMeta(**catalog_data, columns=df.columns.tolist())
        except Exception as exc:
            logger.error(f"[KnowledgeRepo] 结构化数据处理失败: {exc}", exc_info=True)
            return None

    @classmethod
    def get_full_chunks(cls, tenant_id: str, workspace_id: str, chunk_ids: list[str]) -> list[dict[str, Any]]:
        if not chunk_ids:
            return []
        return pg_client.get_chunks_by_ids(tenant_id, workspace_id, chunk_ids)

    @classmethod
    def search_text_chunks(
        cls,
        tenant_id: str,
        workspace_id: str,
        query_terms: list[str],
        filters: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        rows = pg_client.search_chunks(tenant_id, workspace_id, query_terms, filters=filters, limit=limit)
        results = []
        for row in rows:
            metadata = row.get("metadata") or {}
            results.append(
                {
                    "chunk_id": row.get("chunk_id"),
                    "doc_id": row.get("doc_id"),
                    "text": row.get("content", ""),
                    "metadata": metadata,
                    "score": float(row.get("score", 0.0)),
                    "source": metadata.get("file_name") or row.get("doc_id") or "postgres",
                    "retrieval_type": "text",
                }
            )
        return results

    @classmethod
    def search_vector_chunks(
        cls,
        tenant_id: str,
        workspace_id: str,
        query_vector: list[float],
        filters: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return qdrant_client.search(
            tenant_id=tenant_id,
            query_vector=query_vector,
            workspace_id=workspace_id,
            filters=filters,
            top_k=limit,
        )

    @classmethod
    def search_graph_facts(
        cls,
        tenant_id: str,
        workspace_id: str,
        query_terms: list[str],
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return neo4j_client.search_facts(tenant_id, workspace_id, query_terms, top_k=limit)

    @classmethod
    def has_vector_index(cls, tenant_id: str, workspace_id: str) -> bool:
        return qdrant_client.has_index(tenant_id, workspace_id)

    @classmethod
    def has_graph_index(cls, tenant_id: str, workspace_id: str) -> bool:
        return neo4j_client.has_graph(tenant_id, workspace_id)

    @classmethod
    def close_all_connections(cls):
        logger.info("[KnowledgeRepo] 收到停机指令，正在释放所有数据库连接...")
        try:
            pg_client.close()
            neo4j_client.close()
            qdrant_client.close()
            logger.info("[KnowledgeRepo] 所有数据库连接释放完毕。")
        except Exception as exc:
            logger.error(f"[KnowledgeRepo] 释放数据库连接时发生异常: {exc}")
