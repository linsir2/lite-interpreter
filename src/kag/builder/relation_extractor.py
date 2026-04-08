"""关系抽取器：在强约束规则下为 MAGMA 四张图生成三元组。"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from src.common import get_logger
from src.storage.schema import EntityNode, KnowledgeTriple

logger = get_logger(__name__)


@dataclass
class ChunkEntityGroup:
    chunk_id: str
    entities: list[EntityNode]
    text: str


class RelationExtractor:
    """
    不使用 openie，只根据可解释规则生成四类图谱关系：
    - entity: 实体属性/别名/包含
    - semantic: 术语共现与概念关联
    - temporal: 实体/事件与时间绑定
    - causal: 由明确因果触发词驱动的弱因果边
    """

    CAUSAL_MARKERS = ("因为", "由于", "导致", "因此", "所以", "造成", "影响")

    @classmethod
    def extract_relations(
        cls,
        chunk_text_map: dict[str, str],
        entities: list[EntityNode],
    ) -> list[KnowledgeTriple]:
        grouped: dict[str, list[EntityNode]] = defaultdict(list)
        for entity in entities:
            chunk_id = str(entity.properties.get("chunk_id", ""))
            if chunk_id:
                grouped[chunk_id].append(entity)

        triples: list[KnowledgeTriple] = []
        for chunk_id, chunk_entities in grouped.items():
            text = chunk_text_map.get(chunk_id, "")
            triples.extend(cls._extract_entity_graph(chunk_entities, chunk_id))
            triples.extend(cls._extract_semantic_graph(chunk_entities, chunk_id))
            triples.extend(cls._extract_temporal_graph(chunk_entities, chunk_id))
            triples.extend(cls._extract_causal_graph(chunk_entities, text, chunk_id))
        logger.info(f"[RelationExtractor] 生成 {len(triples)} 条候选关系")
        return triples

    @classmethod
    def _extract_entity_graph(cls, entities: list[EntityNode], chunk_id: str) -> list[KnowledgeTriple]:
        triples: list[KnowledgeTriple] = []
        named = [entity for entity in entities if entity.label == "named"]
        semantic = [entity for entity in entities if entity.label == "semantic"]
        for left in named:
            for right in semantic[:3]:
                if left.id == right.id:
                    continue
                triples.append(
                    cls._triple(
                        head=left.id,
                        head_label=left.label,
                        relation="HAS_CONTEXT",
                        tail=right.id,
                        tail_label=right.label,
                        chunk_id=chunk_id,
                        graph_type="entity",
                    )
                )
        return triples

    @classmethod
    def _extract_semantic_graph(cls, entities: list[EntityNode], chunk_id: str) -> list[KnowledgeTriple]:
        triples: list[KnowledgeTriple] = []
        semantic_like = [entity for entity in entities if entity.label in {"semantic", "named"}]
        for index, left in enumerate(semantic_like):
            for right in semantic_like[index + 1 : index + 4]:
                if left.id == right.id:
                    continue
                triples.append(
                    cls._triple(
                        head=left.id,
                        head_label=left.label,
                        relation="RELATED_TO",
                        tail=right.id,
                        tail_label=right.label,
                        chunk_id=chunk_id,
                        graph_type="semantic",
                    )
                )
        return triples

    @classmethod
    def _extract_temporal_graph(cls, entities: list[EntityNode], chunk_id: str) -> list[KnowledgeTriple]:
        triples: list[KnowledgeTriple] = []
        temporals = [entity for entity in entities if entity.label == "temporal"]
        targets = [entity for entity in entities if entity.label in {"named", "semantic"}]
        for temporal in temporals:
            for target in targets[:4]:
                triples.append(
                    cls._triple(
                        head=target.id,
                        head_label=target.label,
                        relation="OCCURS_AT",
                        tail=temporal.id,
                        tail_label=temporal.label,
                        chunk_id=chunk_id,
                        graph_type="temporal",
                    )
                )
        return triples

    @classmethod
    def _extract_causal_graph(cls, entities: list[EntityNode], text: str, chunk_id: str) -> list[KnowledgeTriple]:
        if not text or not any(marker in text for marker in cls.CAUSAL_MARKERS):
            return []
        candidates = [entity for entity in entities if entity.label in {"semantic", "named"}]
        if len(candidates) < 2:
            return []
        return [
            cls._triple(
                head=candidates[0].id,
                head_label=candidates[0].label,
                relation="CAUSES",
                tail=candidates[-1].id,
                tail_label=candidates[-1].label,
                chunk_id=chunk_id,
                graph_type="causal",
            )
        ]

    @classmethod
    def _triple(
        cls,
        head: str,
        head_label: str,
        relation: str,
        tail: str,
        tail_label: str,
        chunk_id: str,
        graph_type: str,
    ) -> KnowledgeTriple:
        return KnowledgeTriple(
            head=head,
            head_label=head_label,
            relation=relation,
            tail=tail,
            tail_label=tail_label,
            properties={
                "graph_type": graph_type,
                "source_chunk_id": chunk_id,
                "version": "1.0",
                "confidence": 0.6,
            },
        )
