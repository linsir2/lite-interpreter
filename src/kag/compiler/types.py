"""Typed compiler state for the constrained knowledge pipeline."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.storage.schema import KnowledgeTriple


class CompilerStateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class LexiconMatch(CompilerStateModel):
    match_id: str
    surface: str
    canonical: str
    category: str
    source_lexicon: str
    span_start: int
    span_end: int
    confidence: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class QueryLexicalSignals(CompilerStateModel):
    dynamic_hits: list[LexiconMatch] = Field(default_factory=list)
    dataset_hits: list[LexiconMatch] = Field(default_factory=list)
    document_hits: list[LexiconMatch] = Field(default_factory=list)
    entity_hits: list[LexiconMatch] = Field(default_factory=list)
    temporal_hits: list[LexiconMatch] = Field(default_factory=list)
    causal_hits: list[LexiconMatch] = Field(default_factory=list)


class TemporalConstraint(CompilerStateModel):
    anchor_type: str
    value: str
    source_text: str


class CausalConstraint(CompilerStateModel):
    marker: str
    source_text: str


class RuleSpec(CompilerStateModel):
    source_text: str
    normalized_text: str
    subject_terms: list[str] = Field(default_factory=list)
    required_terms: list[str] = Field(default_factory=list)
    prohibited_terms: list[str] = Field(default_factory=list)
    temporal_constraints: list[TemporalConstraint] = Field(default_factory=list)
    causal_constraints: list[CausalConstraint] = Field(default_factory=list)


class MetricSpec(CompilerStateModel):
    source_text: str
    normalized_text: str
    metric_name: str
    measure_terms: list[str] = Field(default_factory=list)
    group_terms: list[str] = Field(default_factory=list)
    preferred_date_terms: list[str] = Field(default_factory=list)
    temporal_constraints: list[TemporalConstraint] = Field(default_factory=list)


class FilterSpec(CompilerStateModel):
    source_text: str
    normalized_text: str
    field: str
    operator: str
    value: str
    preferred_date_terms: list[str] = Field(default_factory=list)
    temporal_constraints: list[TemporalConstraint] = Field(default_factory=list)


class SpecParseError(CompilerStateModel):
    spec_kind: str
    source_text: str
    normalized_text: str
    error_code: str
    error_span: list[int] | None = None
    recoverable: bool = True


class TripleProvenance(CompilerStateModel):
    lexical_match_ids: list[str] = Field(default_factory=list)
    template_id: str
    source_chunk_id: str
    validator_version: str = "1.0"


class GraphCandidate(CompilerStateModel):
    head: str
    head_label: str
    relation: str
    tail: str
    tail_label: str
    graph_type: str
    confidence: float
    provenance: TripleProvenance


class GraphConstraintViolation(Exception):
    """Raised when a candidate triple violates the constrained graph contract."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ValidatedTriple(CompilerStateModel):
    triple: KnowledgeTriple
    provenance: TripleProvenance


class GraphCompilationSummaryState(CompilerStateModel):
    candidate_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    reject_reasons: dict[str, int] = Field(default_factory=dict)


class CompiledKnowledgeState(CompilerStateModel):
    query_signals: QueryLexicalSignals = Field(default_factory=QueryLexicalSignals)
    rule_specs: list[RuleSpec] = Field(default_factory=list)
    metric_specs: list[MetricSpec] = Field(default_factory=list)
    filter_specs: list[FilterSpec] = Field(default_factory=list)
    spec_parse_errors: list[SpecParseError] = Field(default_factory=list)
    compiled_graph_triples: list[KnowledgeTriple] = Field(default_factory=list)
    graph_compilation_summary: GraphCompilationSummaryState = Field(default_factory=GraphCompilationSummaryState)


class LLMHealthStatus(CompilerStateModel):
    alias: str
    model: str
    provider: str
    api_key_present: bool
    configured: bool
    reachable: bool
    smoke_ok: bool
    is_embedding: bool = False
    error: str = ""
