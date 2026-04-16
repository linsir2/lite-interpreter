"""Shared compiler primitives for constrained knowledge processing."""

__all__ = [
    "CausalConstraint",
    "CompiledKnowledgeState",
    "CompiledLexicon",
    "FilterSpec",
    "GraphCandidate",
    "GraphCompilationResult",
    "GraphCompilationSummaryState",
    "GraphCompiler",
    "GraphConstraintViolation",
    "GraphValidator",
    "LLMHealthStatus",
    "LexiconCompiler",
    "LexiconMatch",
    "LexiconMatcher",
    "MetricSpec",
    "QueryLexicalSignals",
    "RuleSpec",
    "SpecCompilationResult",
    "SpecCompiler",
    "SpecParseError",
    "TemporalConstraint",
    "TripleProvenance",
    "ValidatedTriple",
]


def __getattr__(name: str):
    if name in {"CompiledLexicon", "LexiconCompiler", "LexiconMatch", "LexiconMatcher", "QueryLexicalSignals"}:
        from .lexicon import CompiledLexicon, LexiconCompiler, LexiconMatch, LexiconMatcher, QueryLexicalSignals

        return {
            "CompiledLexicon": CompiledLexicon,
            "LexiconCompiler": LexiconCompiler,
            "LexiconMatch": LexiconMatch,
            "LexiconMatcher": LexiconMatcher,
            "QueryLexicalSignals": QueryLexicalSignals,
        }[name]
    if name in {"SpecCompiler", "SpecCompilationResult"}:
        from .parser import SpecCompilationResult, SpecCompiler

        return {"SpecCompiler": SpecCompiler, "SpecCompilationResult": SpecCompilationResult}[name]
    if name in {"GraphCompilationResult", "GraphCompiler", "GraphConstraintViolation", "GraphValidator"}:
        from .graph import GraphCompilationResult, GraphCompiler, GraphConstraintViolation, GraphValidator

        return {
            "GraphCompilationResult": GraphCompilationResult,
            "GraphCompiler": GraphCompiler,
            "GraphConstraintViolation": GraphConstraintViolation,
            "GraphValidator": GraphValidator,
        }[name]

    from .types import (
        CausalConstraint,
        CompiledKnowledgeState,
        FilterSpec,
        GraphCandidate,
        GraphCompilationSummaryState,
        LLMHealthStatus,
        MetricSpec,
        RuleSpec,
        SpecParseError,
        TemporalConstraint,
        TripleProvenance,
        ValidatedTriple,
    )

    types_map = {
        "CausalConstraint": CausalConstraint,
        "CompiledKnowledgeState": CompiledKnowledgeState,
        "FilterSpec": FilterSpec,
        "GraphCandidate": GraphCandidate,
        "GraphCompilationSummaryState": GraphCompilationSummaryState,
        "LLMHealthStatus": LLMHealthStatus,
        "MetricSpec": MetricSpec,
        "RuleSpec": RuleSpec,
        "SpecParseError": SpecParseError,
        "TemporalConstraint": TemporalConstraint,
        "TripleProvenance": TripleProvenance,
        "ValidatedTriple": ValidatedTriple,
    }
    if name in types_map:
        return types_map[name]
    raise AttributeError(name)
