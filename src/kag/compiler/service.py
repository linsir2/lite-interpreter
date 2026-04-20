"""Canonical access layer for compiler-backed knowledge semantics."""

from __future__ import annotations

from collections.abc import Iterable

from .lexicon import LexiconMatcher, QueryLexicalSignals
from .parser import SpecCompilationResult, SpecCompiler
from .types import FilterSpec, LexiconMatch, MetricSpec, RuleSpec, SpecParseError


class KnowledgeCompilerService:
    """Thin service that centralizes compiler object ownership and access."""

    _matcher = LexiconMatcher()
    _spec_compiler = SpecCompiler(_matcher)

    @classmethod
    def matcher(cls) -> LexiconMatcher:
        return cls._matcher

    @classmethod
    def spec_compiler(cls) -> SpecCompiler:
        return cls._spec_compiler

    @classmethod
    def classify_query(cls, query: str) -> QueryLexicalSignals:
        return cls._matcher.classify_query(query)

    @classmethod
    def match_text(cls, text: str) -> list[LexiconMatch]:
        return cls._matcher.match_text(text)

    @classmethod
    def parse_rule(cls, text: str) -> RuleSpec | SpecParseError:
        return cls._spec_compiler.parse_rule(text)

    @classmethod
    def parse_metric(cls, text: str) -> MetricSpec | SpecParseError:
        return cls._spec_compiler.parse_metric(text)

    @classmethod
    def parse_filter(cls, text: str) -> FilterSpec | SpecParseError:
        return cls._spec_compiler.parse_filter(text)

    @classmethod
    def compile_business_context(
        cls,
        *,
        rules: Iterable[str],
        metrics: Iterable[str],
        filters: Iterable[str],
    ) -> SpecCompilationResult:
        return cls._spec_compiler.compile_business_context(rules=rules, metrics=metrics, filters=filters)
