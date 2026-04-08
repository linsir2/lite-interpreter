"""
实体抽取器：支持基于规则的 MAGMA 实体抽取。

为了避免幻觉，默认优先使用强约束规则；若未来接入真实 LLM，也必须返回同构结构。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from src.common import generate_uuid, get_logger
from src.storage.schema import EntityNode

logger = get_logger(__name__)


class EntityType(StrEnum):
    SEMANTIC = "semantic"
    TEMPORAL = "temporal"
    CAUSAL = "causal"
    NAMED = "named"
    UNKNOWN = "unknown"


@dataclass
class ExtractedEntity:
    text: str
    type: EntityType
    start_pos: int
    end_pos: int
    confidence: float
    properties: dict[str, Any]


class EntityExtractor:
    def __init__(self, use_llm: bool = True):
        self.use_llm = False if use_llm else False
        logger.info(f"[EntityExtractor] 初始化完成，use_llm={self.use_llm}")

    def extract_entities(self, text: str, doc_id: str, chunk_id: str) -> list[EntityNode]:
        if not text.strip():
            return []
        extracted_entities = self._extract_with_rules(text)
        entity_nodes = self._convert_to_entity_nodes(extracted_entities, doc_id, chunk_id)
        logger.info(f"[EntityExtractor] chunk={chunk_id} 抽取实体 {len(entity_nodes)} 个")
        return entity_nodes

    def _extract_with_rules(self, text: str) -> list[ExtractedEntity]:
        entities: list[ExtractedEntity] = []
        entities.extend(self._extract_named_entities(text))
        entities.extend(self._extract_temporal_entities(text))
        entities.extend(self._extract_causal_entities(text))
        entities.extend(self._extract_semantic_entities(text))
        return self._deduplicate_entities(entities)

    def _extract_named_entities(self, text: str) -> list[ExtractedEntity]:
        entities: list[ExtractedEntity] = []
        patterns = [
            r"[\u4e00-\u9fa5A-Za-z0-9]+(?:公司|集团|组织|机构|平台|系统|大学|学院|医院)",
            r"[A-Z][A-Za-z0-9_-]{2,}",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                entities.append(
                    ExtractedEntity(
                        text=match.group(),
                        type=EntityType.NAMED,
                        start_pos=match.start(),
                        end_pos=match.end(),
                        confidence=0.75,
                        properties={"category": "named"},
                    )
                )
        return entities

    def _extract_temporal_entities(self, text: str) -> list[ExtractedEntity]:
        entities: list[ExtractedEntity] = []
        patterns = [
            r"\d{4}年\d{1,2}月\d{1,2}日",
            r"\d{4}-\d{1,2}-\d{1,2}",
            r"\d{4}年\d{1,2}月",
            r"\d{4}年",
            r"第[一二三四]季度",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                entities.append(
                    ExtractedEntity(
                        text=match.group(),
                        type=EntityType.TEMPORAL,
                        start_pos=match.start(),
                        end_pos=match.end(),
                        confidence=0.9,
                        properties={"category": "time"},
                    )
                )
        return entities

    def _extract_causal_entities(self, text: str) -> list[ExtractedEntity]:
        keywords = ["因为", "由于", "导致", "因此", "影响", "造成"]
        entities: list[ExtractedEntity] = []
        for keyword in keywords:
            for match in re.finditer(keyword, text):
                entities.append(
                    ExtractedEntity(
                        text=match.group(),
                        type=EntityType.CAUSAL,
                        start_pos=match.start(),
                        end_pos=match.end(),
                        confidence=0.65,
                        properties={"category": "causal_marker"},
                    )
                )
        return entities

    def _extract_semantic_entities(self, text: str) -> list[ExtractedEntity]:
        entities: list[ExtractedEntity] = []
        patterns = [
            r"[\u4e00-\u9fa5]{2,}(?:规则|标准|流程|指标|口径|模型|算法|系统|能力|协议|风险|成本)",
            r"[\u4e00-\u9fa5]{2,}(?:分析|治理|优化|检索|融合|规划)",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                entities.append(
                    ExtractedEntity(
                        text=match.group(),
                        type=EntityType.SEMANTIC,
                        start_pos=match.start(),
                        end_pos=match.end(),
                        confidence=0.7,
                        properties={"category": "semantic"},
                    )
                )
        return entities

    def _deduplicate_entities(self, entities: list[ExtractedEntity]) -> list[ExtractedEntity]:
        unique: dict[tuple[int, int, str], ExtractedEntity] = {}
        for entity in entities:
            key = (entity.start_pos, entity.end_pos, entity.text)
            if key not in unique:
                unique[key] = entity
        return list(unique.values())

    def _convert_to_entity_nodes(self, extracted_entities: list[ExtractedEntity], doc_id: str, chunk_id: str) -> list[EntityNode]:
        nodes: list[EntityNode] = []
        for entity in extracted_entities:
            nodes.append(
                EntityNode(
                    id=entity.text,
                    label=entity.type.value,
                    properties={
                        **entity.properties,
                        "entity_id": generate_uuid(),
                        "doc_id": doc_id,
                        "chunk_id": chunk_id,
                        "start_pos": entity.start_pos,
                        "end_pos": entity.end_pos,
                        "confidence": entity.confidence,
                    },
                )
            )
        return nodes
