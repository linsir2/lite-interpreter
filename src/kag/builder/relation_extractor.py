"""关系抽取器：在强约束规则下为 MAGMA 四张图生成三元组。"""

from __future__ import annotations

from src.common import get_logger
from src.compiler.kag.graph import GraphCompiler
from src.storage.schema import EntityNode, KnowledgeTriple

logger = get_logger(__name__)


class RelationExtractor:
    """
    不使用 openie，只根据可解释规则生成四类图谱关系：
    - entity: 实体属性/别名/包含
    - semantic: 术语共现与概念关联
    - temporal: 实体/事件与时间绑定
    - causal: 由明确因果触发词驱动的弱因果边
    """

    @classmethod
    def extract_relations(
        cls,
        chunk_text_map: dict[str, str],
        entities: list[EntityNode],
    ) -> list[KnowledgeTriple]:
        compilation = GraphCompiler.compile_relations(chunk_text_map=chunk_text_map, entities=entities)
        triples = [item.triple for item in compilation.accepted]
        logger.info(f"[RelationExtractor] 生成 {len(triples)} 条候选关系")
        return triples
