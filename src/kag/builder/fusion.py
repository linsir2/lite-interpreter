"""知识融合：对候选三元组做归一化、去重与轻量合并。"""
from __future__ import annotations

from src.common import get_logger
from src.storage.schema import KnowledgeTriple

logger = get_logger(__name__)


class KnowledgeFusion:
    @classmethod
    def fuse(cls, triples: list[KnowledgeTriple]) -> list[KnowledgeTriple]:
        unique: dict[tuple[str, str, str, str], KnowledgeTriple] = {}
        for triple in triples:
            key = (
                triple.head.strip().lower(),
                triple.relation.strip().upper(),
                triple.tail.strip().lower(),
                str(triple.properties.get("graph_type", "entity")),
            )
            if key not in unique:
                triple.head = triple.head.strip()
                triple.tail = triple.tail.strip()
                triple.relation = triple.relation.strip().upper()
                unique[key] = triple
                continue

            existing = unique[key]
            if triple.properties.get("source_chunk_id") != existing.properties.get("source_chunk_id"):
                existing.properties.setdefault("supporting_chunks", [])
                existing.properties["supporting_chunks"] = sorted(
                    set(existing.properties["supporting_chunks"] + [triple.properties.get("source_chunk_id")])
                )
        fused = list(unique.values())
        logger.info(f"[Fusion] 三元组去重完成: {len(triples)} -> {len(fused)}")
        return fused
