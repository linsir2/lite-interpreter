"""
src/storage/postgres_client.py
关系型数据库客户端 (The Single Source of Truth)

职责：
1. 存储 Chunk 全文及版本。
2. 支持按需拉取全文与轻量文本检索。
3. 管理结构化数据目录与任务状态基座。
"""

from __future__ import annotations

import importlib
import json
from typing import Any

import pandas as pd
from config.settings import POSTGRES_URI
from sqlalchemy import bindparam, create_engine, text

from src.common.logger import get_logger
from src.common.utils import scope_identifier_to_db_name
from src.storage.schema import DocChunk

logger = get_logger(__name__)


def _module_available(module_name: str) -> bool:
    try:
        importlib.import_module(module_name)
        return True
    except Exception:
        return False


def _resolve_postgres_uri(raw_uri: str) -> tuple[str, str]:
    normalized = str(raw_uri or "").strip()
    if normalized.startswith("postgresql+"):
        driver = normalized.split("://", 1)[0].split("+", 1)[1]
        return normalized, driver
    if _module_available("psycopg"):
        return normalized.replace("postgresql://", "postgresql+psycopg://", 1), "psycopg"
    if _module_available("psycopg2"):
        return normalized.replace("postgresql://", "postgresql+psycopg2://", 1), "psycopg2"
    raise ModuleNotFoundError("Postgres driver unavailable: install `psycopg` or `psycopg2`")


class PostgresDBClient:
    def __init__(self) -> None:
        self.driver_name: str | None = None
        self.driver_error: str | None = None
        try:
            resolved_uri, driver_name = _resolve_postgres_uri(POSTGRES_URI)
            self.driver_name = driver_name
            self.engine = create_engine(resolved_uri, pool_pre_ping=True, pool_size=10)
            self._init_core_tables()
            logger.info("[PostgresClient] 初始化成功：确立唯一真相源。")
        except Exception as exc:
            logger.error(f"[PostgresClient] 连接失败: {exc}")
            self.driver_error = str(exc)
            self.engine = None

    def _init_core_tables(self):
        if not self.engine:
            return
        init_sql = """
        CREATE TABLE IF NOT EXISTS kag_doc_chunks (
            chunk_id VARCHAR(255) NOT NULL,
            version VARCHAR(50) DEFAULT '1.0',
            tenant_id VARCHAR(255) NOT NULL,
            workspace_id VARCHAR(255) NOT NULL,
            doc_id VARCHAR(255) NOT NULL,
            content TEXT NOT NULL,
            summary TEXT,
            parent_chunk_id VARCHAR(255),
            metadata JSONB,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            PRIMARY KEY (chunk_id, version)
        );
        CREATE INDEX IF NOT EXISTS idx_tenant_ws ON kag_doc_chunks(tenant_id, workspace_id);
        CREATE TABLE IF NOT EXISTS kag_data_catalog (
            id SERIAL PRIMARY KEY,
            tenant_id VARCHAR(255) NOT NULL,
            workspace_id VARCHAR(255) NOT NULL,
            original_file_name VARCHAR(255) NOT NULL,
            db_table_name VARCHAR(255) NOT NULL,
            semantic_summary TEXT,
            time_coverage VARCHAR(255),
            keywords JSONB,
            is_persisted BOOLEAN DEFAULT FALSE,
            expires_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """
        with self.engine.begin() as conn:
            conn.execute(text(init_sql))

    def insert_chunks(self, tenant_id: str, workspace_id: str, chunks: list[DocChunk]):
        if not self.engine or not chunks:
            return

        insert_sql = text(
            """
            INSERT INTO kag_doc_chunks
            (chunk_id, version, tenant_id, workspace_id, doc_id, content, summary, parent_chunk_id, metadata, created_at)
            VALUES
            (:chunk_id, :version, :tenant_id, :workspace_id, :doc_id, :content, :summary, :parent_chunk_id, :metadata, :created_at)
            ON CONFLICT (chunk_id, version)
            DO UPDATE SET
                content = EXCLUDED.content,
                summary = EXCLUDED.summary,
                metadata = EXCLUDED.metadata,
                updated_at = NOW();
            """
        )

        payload = []
        for chunk in chunks:
            metadata = dict(chunk.metadata)
            payload.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "version": str(metadata.pop("version", "1.0")),
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "doc_id": chunk.doc_id,
                    "content": chunk.content,
                    "summary": metadata.get("summary"),
                    "parent_chunk_id": metadata.get("parent_chunk_id"),
                    "metadata": json.dumps(metadata, ensure_ascii=False),
                    "created_at": chunk.created_at,
                }
            )

        try:
            with self.engine.begin() as conn:
                conn.execute(insert_sql, payload)
        except Exception as exc:
            logger.error(f"[PostgresClient] 写入失败: {exc}")
            raise

    def get_chunks_by_ids(self, tenant_id: str, workspace_id: str, chunk_ids: list[str]) -> list[dict[str, Any]]:
        if not self.engine or not chunk_ids:
            return []

        sql = text(
            """
            SELECT chunk_id, version, doc_id, content, summary, metadata
            FROM kag_doc_chunks
            WHERE tenant_id = :tenant_id
              AND workspace_id = :workspace_id
              AND chunk_id IN :chunk_ids
            """
        ).bindparams(bindparam("chunk_ids", expanding=True))

        try:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    sql,
                    {"tenant_id": tenant_id, "workspace_id": workspace_id, "chunk_ids": chunk_ids},
                )
                return [dict(row._mapping) for row in rows]
        except Exception as exc:
            logger.error(f"[PostgresClient] 拉取原文失败: {exc}")
            return []

    def search_chunks(
        self,
        tenant_id: str,
        workspace_id: str,
        query_terms: list[str],
        filters: dict[str, Any] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if not self.engine or not query_terms:
            return []

        sql = text(
            """
            SELECT chunk_id, doc_id, content, summary, metadata, created_at
            FROM kag_doc_chunks
            WHERE tenant_id = :tenant_id
              AND workspace_id = :workspace_id
            ORDER BY created_at DESC
            LIMIT :limit
            """
        )

        try:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    sql,
                    {"tenant_id": tenant_id, "workspace_id": workspace_id, "limit": max(limit * 4, 100)},
                )
                results = []
                lowered_terms = [term.lower() for term in query_terms if term]
                for row in rows:
                    data = dict(row._mapping)
                    metadata = data.get("metadata") or {}
                    if isinstance(metadata, str):
                        try:
                            metadata = json.loads(metadata)
                        except json.JSONDecodeError:
                            metadata = {}
                    if filters and any(str(metadata.get(key)) != str(value) for key, value in filters.items()):
                        continue

                    haystack = " ".join(
                        [
                            str(data.get("content") or ""),
                            str(data.get("summary") or ""),
                            json.dumps(metadata, ensure_ascii=False),
                        ]
                    ).lower()
                    score = sum(haystack.count(term) for term in lowered_terms)
                    if score <= 0:
                        continue
                    data["metadata"] = metadata
                    data["score"] = float(score)
                    results.append(data)
                results.sort(key=lambda item: item["score"], reverse=True)
                return results[:limit]
        except Exception as exc:
            logger.error(f"[PostgresClient] 文本检索失败: {exc}")
            return []

    def register_dataset_catalog(self, catalog_data: dict[str, Any]):
        if not self.engine:
            return
        insert_sql = text(
            """
            INSERT INTO kag_data_catalog
            (tenant_id, workspace_id, original_file_name, db_table_name, semantic_summary, time_coverage, keywords, is_persisted, expires_at)
            VALUES
            (:tenant_id, :workspace_id, :original_file_name, :db_table_name, :semantic_summary, :time_coverage, :keywords, :is_persisted, :expires_at)
            """
        )
        if "keywords" in catalog_data and isinstance(catalog_data["keywords"], list):
            catalog_data["keywords"] = json.dumps(catalog_data["keywords"], ensure_ascii=False)
        try:
            with self.engine.begin() as conn:
                conn.execute(insert_sql, catalog_data)
            logger.info(f"[PostgresClient] 成功注册数据集户口本: {catalog_data.get('original_file_name')}")
        except Exception as exc:
            logger.error(f"[PostgresClient] 资产目录注册失败: {exc}", exc_info=True)

    def df_to_sql_table(self, tenant_id: str, table_name: str, df: pd.DataFrame):
        if not self.engine:
            raise ConnectionError("Postgres engine not initialized.")
        schema_name = scope_identifier_to_db_name(tenant_id, prefix="t_")
        try:
            with self.engine.begin() as conn:
                conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
            df.to_sql(name=table_name, con=self.engine, schema=schema_name, if_exists="replace", index=False)
            logger.info(f"[PostgresClient] 动态建表成功: {schema_name}.{table_name} ({len(df)} 行)")
        except Exception as exc:
            logger.error(f"[PostgresClient] DataFrame 动态建表失败: {exc}", exc_info=True)
            raise

    def close(self):
        if self.engine:
            self.engine.dispose()
            logger.info("[PostgresClient] 数据库连接池已销毁。")


pg_client = PostgresDBClient()
