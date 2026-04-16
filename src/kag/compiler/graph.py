"""Strongly constrained graph candidate assembly and validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.storage.schema import EntityNode, KnowledgeTriple

from .types import (
    FilterSpec,
    GraphCandidate,
    GraphConstraintViolation,
    MetricSpec,
    RuleSpec,
    TripleProvenance,
    ValidatedTriple,
)


@dataclass(frozen=True)
class GraphCompilationResult:
    accepted: list[ValidatedTriple]
    rejected: list[dict[str, str]]


class GraphValidator:
    VERSION = "1.0"
    _ALLOWED_RELATIONS = {
        ("entity", "HAS_CONTEXT", "named", "semantic"),
        ("semantic", "RELATED_TO", "semantic", "semantic"),
        ("semantic", "RELATED_TO", "named", "semantic"),
        ("semantic", "RELATED_TO", "semantic", "named"),
        ("semantic", "RELATED_TO", "named", "named"),
        ("temporal", "OCCURS_AT", "semantic", "temporal"),
        ("temporal", "OCCURS_AT", "named", "temporal"),
        ("causal", "CAUSES", "semantic", "semantic"),
        ("causal", "CAUSES", "named", "semantic"),
        ("causal", "CAUSES", "semantic", "named"),
        ("causal", "CAUSES", "named", "named"),
    }

    @classmethod
    def validate(cls, candidate: GraphCandidate) -> ValidatedTriple:
        provenance = candidate.provenance
        if not provenance.source_chunk_id or not provenance.template_id or not provenance.lexical_match_ids:
            raise GraphConstraintViolation("missing_provenance", "candidate provenance is incomplete")
        key = (candidate.graph_type, candidate.relation, candidate.head_label, candidate.tail_label)
        if key not in cls._ALLOWED_RELATIONS:
            raise GraphConstraintViolation("illegal_type_combo", f"unsupported relation combo: {key}")
        if candidate.graph_type == "causal" and not provenance.lexical_match_ids:
            raise GraphConstraintViolation("missing_causal_marker", "causal relation missing lexical marker")
        if candidate.graph_type == "temporal" and candidate.tail_label != "temporal":
            raise GraphConstraintViolation("missing_temporal_anchor", "temporal relation missing temporal anchor")
        triple = KnowledgeTriple(
            head=candidate.head,
            head_label=candidate.head_label,
            relation=candidate.relation,
            tail=candidate.tail,
            tail_label=candidate.tail_label,
            properties={
                "graph_type": candidate.graph_type,
                "source_chunk_id": provenance.source_chunk_id,
                "validator_version": cls.VERSION,
                "confidence": candidate.confidence,
                "provenance": provenance.model_dump(mode="json"),
            },
        )
        return ValidatedTriple(triple=triple, provenance=provenance)


class GraphCompiler:
    @staticmethod
    def _unique_terms(values: list[Any]) -> list[str]:
        return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))

    @staticmethod
    def _support_id(entity: EntityNode) -> str:
        return str(entity.properties.get("match_id") or entity.properties.get("entity_id") or "")

    @classmethod
    def compile_relations(
        cls,
        *,
        chunk_text_map: dict[str, str],
        entities: list[EntityNode],
    ) -> GraphCompilationResult:
        grouped: dict[str, list[EntityNode]] = {}
        for entity in entities:
            chunk_id = str(entity.properties.get("chunk_id") or "")
            if not chunk_id:
                continue
            grouped.setdefault(chunk_id, []).append(entity)

        accepted: list[ValidatedTriple] = []
        rejected: list[dict[str, str]] = []
        for chunk_id, chunk_entities in grouped.items():
            text = chunk_text_map.get(chunk_id, "")
            accepted.extend(cls._compile_entity_graph(chunk_entities, chunk_id, rejected))
            accepted.extend(cls._compile_semantic_graph(chunk_entities, chunk_id, rejected))
            accepted.extend(cls._compile_temporal_graph(chunk_entities, chunk_id, rejected))
            accepted.extend(cls._compile_causal_graph(chunk_entities, text, chunk_id, rejected))
        return GraphCompilationResult(accepted=accepted, rejected=rejected)

    @classmethod
    def compile_spec_relations(
        cls,
        *,
        rule_specs: list[RuleSpec] | None = None,
        metric_specs: list[MetricSpec] | None = None,
        filter_specs: list[FilterSpec] | None = None,
    ) -> GraphCompilationResult:
        accepted: list[ValidatedTriple] = []
        rejected: list[dict[str, str]] = []

        for index, spec in enumerate(list(rule_specs or [])):
            accepted.extend(cls._compile_rule_temporal_spec_graph(spec, index, rejected))
        for index, spec in enumerate(list(metric_specs or [])):
            accepted.extend(cls._compile_metric_temporal_spec_graph(spec, index, rejected))
        for index, spec in enumerate(list(filter_specs or [])):
            accepted.extend(cls._compile_filter_temporal_spec_graph(spec, index, rejected))
        return GraphCompilationResult(accepted=accepted, rejected=rejected)

    @classmethod
    def _provenance(cls, *, lexical_match_ids: list[str], template_id: str, chunk_id: str) -> TripleProvenance:
        return TripleProvenance(
            lexical_match_ids=[item for item in lexical_match_ids if item],
            template_id=template_id,
            source_chunk_id=chunk_id,
            validator_version=GraphValidator.VERSION,
        )

    @classmethod
    def _validate(cls, candidate: GraphCandidate, rejected: list[dict[str, str]]) -> list[ValidatedTriple]:
        try:
            return [GraphValidator.validate(candidate)]
        except GraphConstraintViolation as exc:
            rejected.append({"code": exc.code, "message": exc.message, "template_id": candidate.provenance.template_id})
            return []

    @classmethod
    def _compile_spec_temporal_candidates(
        cls,
        *,
        chunk_id: str,
        target_terms: list[str],
        preferred_date_terms: list[str],
        temporal_constraints: list[str],
        template_prefix: str,
        rejected: list[dict[str, str]],
    ) -> list[ValidatedTriple]:
        validated: list[ValidatedTriple] = []
        for category, temporal_terms, confidence in (
            ("preference", preferred_date_terms, 0.74),
            ("constraint", temporal_constraints, 0.82),
        ):
            template_id = f"{template_prefix}.temporal.{category}.occurs_at"
            for target in cls._unique_terms(target_terms)[:4]:
                for temporal in cls._unique_terms(temporal_terms)[:4]:
                    candidate = GraphCandidate(
                        head=target,
                        head_label="semantic",
                        relation="OCCURS_AT",
                        tail=temporal,
                        tail_label="temporal",
                        graph_type="temporal",
                        confidence=confidence,
                        provenance=cls._provenance(
                            lexical_match_ids=[f"{chunk_id}:head:{target}", f"{chunk_id}:temporal:{temporal}"],
                            template_id=template_id,
                            chunk_id=chunk_id,
                        ),
                    )
                    validated.extend(cls._validate(candidate, rejected))
        return validated

    @classmethod
    def _compile_rule_temporal_spec_graph(
        cls,
        spec: RuleSpec,
        index: int,
        rejected: list[dict[str, str]],
    ) -> list[ValidatedTriple]:
        target_terms = cls._unique_terms(
            [
                *list(spec.subject_terms or []),
                *list(spec.required_terms or []),
                *list(spec.prohibited_terms or []),
                spec.normalized_text or spec.source_text,
            ]
        )
        temporal_constraints = cls._unique_terms(
            [constraint.value for constraint in list(spec.temporal_constraints or [])]
        )
        return cls._compile_spec_temporal_candidates(
            chunk_id=f"compiled:rule:{index}",
            target_terms=target_terms,
            preferred_date_terms=[],
            temporal_constraints=temporal_constraints,
            template_prefix="rule",
            rejected=rejected,
        )

    @classmethod
    def _compile_metric_temporal_spec_graph(
        cls,
        spec: MetricSpec,
        index: int,
        rejected: list[dict[str, str]],
    ) -> list[ValidatedTriple]:
        target_terms = cls._unique_terms(
            [
                spec.metric_name,
                *list(spec.measure_terms or []),
                *list(spec.group_terms or []),
                spec.normalized_text or spec.source_text,
            ]
        )
        temporal_constraints = cls._unique_terms(
            [constraint.value for constraint in list(spec.temporal_constraints or [])]
        )
        return cls._compile_spec_temporal_candidates(
            chunk_id=f"compiled:metric:{index}",
            target_terms=target_terms,
            preferred_date_terms=cls._unique_terms(list(spec.preferred_date_terms or [])),
            temporal_constraints=temporal_constraints,
            template_prefix="metric",
            rejected=rejected,
        )

    @classmethod
    def _compile_filter_temporal_spec_graph(
        cls,
        spec: FilterSpec,
        index: int,
        rejected: list[dict[str, str]],
    ) -> list[ValidatedTriple]:
        target_terms = cls._unique_terms(
            [
                spec.value if spec.field != "year" else "",
                spec.field if spec.field not in {"", "year"} else "",
                spec.normalized_text or spec.source_text,
            ]
        )
        temporal_constraints = cls._unique_terms(
            [constraint.value for constraint in list(spec.temporal_constraints or [])]
        )
        return cls._compile_spec_temporal_candidates(
            chunk_id=f"compiled:filter:{index}",
            target_terms=target_terms,
            preferred_date_terms=cls._unique_terms(list(spec.preferred_date_terms or [])),
            temporal_constraints=temporal_constraints,
            template_prefix="filter",
            rejected=rejected,
        )

    @classmethod
    def _compile_entity_graph(
        cls, entities: list[EntityNode], chunk_id: str, rejected: list[dict[str, str]]
    ) -> list[ValidatedTriple]:
        validated: list[ValidatedTriple] = []
        named = [entity for entity in entities if entity.label == "named"]
        semantic = [entity for entity in entities if entity.label == "semantic"]
        for left in named:
            for right in semantic[:3]:
                if left.id == right.id:
                    continue
                candidate = GraphCandidate(
                    head=left.id,
                    head_label=left.label,
                    relation="HAS_CONTEXT",
                    tail=right.id,
                    tail_label=right.label,
                    graph_type="entity",
                    confidence=0.75,
                    provenance=cls._provenance(
                        lexical_match_ids=[cls._support_id(left), cls._support_id(right)],
                        template_id="entity.named_has_context.semantic",
                        chunk_id=chunk_id,
                    ),
                )
                validated.extend(cls._validate(candidate, rejected))
        return validated

    @classmethod
    def _compile_semantic_graph(
        cls, entities: list[EntityNode], chunk_id: str, rejected: list[dict[str, str]]
    ) -> list[ValidatedTriple]:
        validated: list[ValidatedTriple] = []
        semantic_like = [entity for entity in entities if entity.label in {"semantic", "named"}]
        for index, left in enumerate(semantic_like):
            for right in semantic_like[index + 1 : index + 4]:
                if left.id == right.id:
                    continue
                candidate = GraphCandidate(
                    head=left.id,
                    head_label=left.label,
                    relation="RELATED_TO",
                    tail=right.id,
                    tail_label=right.label,
                    graph_type="semantic",
                    confidence=0.65,
                    provenance=cls._provenance(
                        lexical_match_ids=[cls._support_id(left), cls._support_id(right)],
                        template_id="semantic.cooccurrence.related_to",
                        chunk_id=chunk_id,
                    ),
                )
                validated.extend(cls._validate(candidate, rejected))
        return validated

    @classmethod
    def _compile_temporal_graph(
        cls, entities: list[EntityNode], chunk_id: str, rejected: list[dict[str, str]]
    ) -> list[ValidatedTriple]:
        validated: list[ValidatedTriple] = []
        temporals = [entity for entity in entities if entity.label == "temporal"]
        targets = [entity for entity in entities if entity.label in {"named", "semantic"}]
        for temporal in temporals:
            for target in targets[:4]:
                candidate = GraphCandidate(
                    head=target.id,
                    head_label=target.label,
                    relation="OCCURS_AT",
                    tail=temporal.id,
                    tail_label=temporal.label,
                    graph_type="temporal",
                    confidence=0.8,
                    provenance=cls._provenance(
                        lexical_match_ids=[cls._support_id(target), cls._support_id(temporal)],
                        template_id="temporal.anchor.occurs_at",
                        chunk_id=chunk_id,
                    ),
                )
                validated.extend(cls._validate(candidate, rejected))
        return validated

    @classmethod
    def _compile_causal_graph(
        cls,
        entities: list[EntityNode],
        text: str,
        chunk_id: str,
        rejected: list[dict[str, str]],
    ) -> list[ValidatedTriple]:
        causal_markers = [entity for entity in entities if entity.label == "causal"]
        candidates = [entity for entity in entities if entity.label in {"semantic", "named"}]
        if not text or len(candidates) < 2:
            return []
        if not causal_markers:
            rejected.append(
                {
                    "code": "missing_causal_marker",
                    "message": "causal graph requires an explicit lexical causal marker",
                    "template_id": "causal.marker.causes",
                }
            )
            return []
        candidate = GraphCandidate(
            head=candidates[0].id,
            head_label=candidates[0].label,
            relation="CAUSES",
            tail=candidates[-1].id,
            tail_label=candidates[-1].label,
            graph_type="causal",
            confidence=0.7,
            provenance=cls._provenance(
                lexical_match_ids=[cls._support_id(item) for item in (candidates[0], candidates[-1], causal_markers[0])],
                template_id="causal.marker.causes",
                chunk_id=chunk_id,
            ),
        )
        return cls._validate(candidate, rejected)
