"""
src/storage/vector_client.py
Qdrant 向量数据库客户端

职责：管理向量索引的创建、向量 Upsert 与检索操作。
KAG 约定仅把经过 MRL 截断后的叶子块向量写入 Qdrant，因此 collection 维度应与
MRL_DIMENSION 保持一致，而不是原始 embedding 维度。
"""
from __future__ import annotations

from typing import Any

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http.models import (
        Distance,
        FieldCondition,
        Filter,
        MatchValue,
        PointStruct,
        VectorParams,
    )
except ImportError:  # pragma: no cover - optional runtime dependency
    QdrantClient = None
    Distance = FieldCondition = Filter = MatchValue = PointStruct = VectorParams = None

from config.settings import MRL_DIMENSION, QDRANT_HOST, QDRANT_PORT

from src.common.logger import get_logger
from src.storage.schema import DocChunk

logger = get_logger(__name__)


class VectorDBClient:
    def __init__(self):
        try:
            if QdrantClient is None:
                raise ImportError("qdrant-client not installed")
            self.client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, check_compatibility=False)
            self.vector_size = MRL_DIMENSION
            logger.info("[VectorClient] Qdrant 客户端初始化成功。")
        except Exception as exc:
            logger.error(f"[VectorClient] Qdrant 连接失败: {exc}")
            self.client = None

    def _get_collection_name(self, tenant_id: str) -> str:
        return f"tenant_{tenant_id}_knowledge"

    def _ensure_collection(self, collection_name: str):
        if not self.client:
            return
        if not self.client.collection_exists(collection_name):
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=self.vector_size, distance=Distance.COSINE),
            )
            logger.info(f"[VectorClient] 创建全新的向量 Collection: {collection_name}")

    def _build_filter(self, workspace_id: str | None, filters: dict[str, Any] | None) -> Filter | None:
        must = []
        if workspace_id:
            must.append(FieldCondition(key="workspace_id", match=MatchValue(value=workspace_id)))
        for key, value in (filters or {}).items():
            must.append(FieldCondition(key=key, match=MatchValue(value=str(value))))
        if not must or Filter is None:
            return None
        return Filter(must=must)

    def has_index(self, tenant_id: str, workspace_id: str) -> bool:
        if not self.client:
            return False
        collection_name = self._get_collection_name(tenant_id)
        if not self.client.collection_exists(collection_name):
            return False
        try:
            count_result = self.client.count(
                collection_name=collection_name,
                count_filter=self._build_filter(workspace_id, None),
            )
            return count_result.count > 0
        except Exception as exc:
            logger.error(f"[VectorClient] 探查索引失败: {exc}")
            return False

    def upsert(self, tenant_id: str, workspace_id: str, chunks: list[DocChunk], embeddings: list[list[float]]):
        if not self.client:
            raise ConnectionError("Qdrant client not initialized.")

        collection_name = self._get_collection_name(tenant_id)
        self._ensure_collection(collection_name)

        points: list[PointStruct] = []
        for chunk, emb in zip(chunks, embeddings, strict=False):
            metadata = dict(chunk.metadata)
            version = metadata.pop("version", "1.0")
            summary = metadata.get("summary")
            payload = {
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "workspace_id": workspace_id,
                "preview": chunk.content[:300],
                "created_at": str(chunk.created_at),
                "version": version,
                "summary": summary,
                **metadata,
            }
            points.append(PointStruct(id=chunk.chunk_id, vector=emb, payload=payload))

        self.client.upsert(collection_name=collection_name, points=points)
        logger.info(f"[VectorClient] 成功 Upsert {len(points)} 条记录至 {collection_name}")

    def search(
        self,
        tenant_id: str,
        query_vector: list[float],
        workspace_id: str | None = None,
        filters: dict[str, Any] | None = None,
        top_k: int = 20,
    ) -> list[dict[str, Any]]:
        if not self.client:
            return []
        collection_name = self._get_collection_name(tenant_id)
        if not self.client.collection_exists(collection_name):
            return []

        try:
            points = self.client.search(
                collection_name=collection_name,
                query_vector=query_vector,
                query_filter=self._build_filter(workspace_id, filters),
                limit=top_k,
            )
        except Exception as exc:
            logger.error(f"[VectorClient] 向量检索失败: {exc}")
            return []

        results = []
        for point in points:
            payload = point.payload or {}
            results.append(
                {
                    "chunk_id": payload.get("chunk_id", str(point.id)),
                    "doc_id": payload.get("doc_id"),
                    "text": payload.get("preview", ""),
                    "metadata": payload,
                    "score": float(point.score),
                    "source": payload.get("file_name") or payload.get("doc_id") or "vector_db",
                    "retrieval_type": "vector",
                }
            )
        return results

    def close(self):
        if self.client:
            self.client.close()
            logger.info("[VectorClient] Qdrant 连接已安全断开。")


qdrant_client = VectorDBClient()
