"""ANTLR-backed narrow spec compiler for normalized rule, metric, and filter text."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from antlr4 import CommonTokenStream, InputStream

from .generated.KnowledgeSpecLexer import KnowledgeSpecLexer
from .generated.KnowledgeSpecParser import KnowledgeSpecParser
from .lexicon import LexiconMatcher
from .types import (
    CausalConstraint,
    FilterSpec,
    MetricSpec,
    RuleSpec,
    SpecParseError,
    TemporalConstraint,
)


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _temporal_constraints(text: str, matcher: LexiconMatcher) -> list[TemporalConstraint]:
    constraints: list[TemporalConstraint] = []
    for match in matcher.match_text(text):
        if match.category == "temporal":
            constraints.append(
                TemporalConstraint(anchor_type="lexical_marker", value=match.canonical, source_text=text)
            )
    for year in re.findall(r"(20\d{2})", text):
        constraints.append(TemporalConstraint(anchor_type="year", value=year, source_text=text))
    return constraints


def _causal_constraints(text: str, matcher: LexiconMatcher) -> list[CausalConstraint]:
    return [
        CausalConstraint(marker=match.canonical, source_text=text)
        for match in matcher.match_text(text)
        if match.category == "causal"
    ]


def _entity_terms(text: str, matcher: LexiconMatcher) -> list[str]:
    return list(dict.fromkeys(match.canonical for match in matcher.match_text(text) if match.category == "entity"))


def _preferred_date_terms(text: str) -> list[str]:
    terms: list[str] = []
    for pattern in (
        r"\b[a-zA-Z_]*date[a-zA-Z_]*\b",
        r"\b[a-zA-Z_]+_at\b",
        r"\b(?:year|month|quarter|week|day)\b",
    ):
        for value in re.findall(pattern, text):
            normalized = str(value).strip()
            if normalized and normalized not in terms:
                terms.append(normalized)
    for marker in ("biz_date", "created_at", "updated_at", "日期", "时间", "期间", "年度", "季度", "月份", "截至"):
        if marker in text and marker not in terms:
            terms.append(marker)
    return terms


def _parse_pairs_via_antlr(dsl: str) -> dict[str, list[str]]:
    lexer = KnowledgeSpecLexer(InputStream(dsl))
    stream = CommonTokenStream(lexer)
    parser = KnowledgeSpecParser(stream)
    parser.removeErrorListeners()
    tree = parser.spec()
    if parser.getNumberOfSyntaxErrors():
        raise ValueError("antlr_syntax_error")
    values: dict[str, list[str]] = {}

    def _collect_pairs(context) -> None:
        for pair_ctx in context.pair():
            key = str(pair_ctx.KEY().getText())
            value = str(pair_ctx.scalar().getText())
            values.setdefault(key, []).append(value)

    if tree.ruleSpec():
        _collect_pairs(tree.ruleSpec())
    elif tree.metricSpec():
        _collect_pairs(tree.metricSpec())
    elif tree.filterSpec():
        _collect_pairs(tree.filterSpec())
    return values


def _dsl_pair(key: str, value: str) -> str:
    return f"{key} = {value}"


@dataclass(frozen=True)
class SpecCompilationResult:
    rules: list[RuleSpec]
    metrics: list[MetricSpec]
    filters: list[FilterSpec]
    errors: list[SpecParseError]


class SpecCompiler:
    def __init__(self, matcher: LexiconMatcher | None = None):
        self._matcher = matcher or LexiconMatcher()

    def parse_rule(self, text: str) -> RuleSpec | SpecParseError:
        normalized = _normalize_text(text)
        entity_terms = _entity_terms(normalized, self._matcher)
        if not normalized or not entity_terms:
            return SpecParseError(
                spec_kind="rule",
                source_text=text,
                normalized_text=normalized,
                error_code="missing_entity_terms",
            )
        required_terms = list(entity_terms)
        prohibited_terms: list[str] = []
        if any(token in normalized for token in ("禁止", "不得")):
            prohibited_terms = required_terms
            required_terms = []
        dsl_parts = ["RULE", *(_dsl_pair("subject", term) for term in entity_terms)]
        dsl_parts.extend(_dsl_pair("required", term) for term in required_terms)
        dsl_parts.extend(_dsl_pair("prohibited", term) for term in prohibited_terms)
        for item in _temporal_constraints(normalized, self._matcher):
            dsl_parts.append(_dsl_pair("temporal", item.value))
        for item in _causal_constraints(normalized, self._matcher):
            dsl_parts.append(_dsl_pair("causal", item.marker))
        try:
            pairs = _parse_pairs_via_antlr(" ".join(dsl_parts))
        except Exception:
            return SpecParseError(
                spec_kind="rule",
                source_text=text,
                normalized_text=normalized,
                error_code="antlr_rule_parse_failed",
            )
        return RuleSpec(
            source_text=text,
            normalized_text=normalized,
            subject_terms=list(pairs.get("subject", [])),
            required_terms=list(pairs.get("required", [])),
            prohibited_terms=list(pairs.get("prohibited", [])),
            temporal_constraints=[
                TemporalConstraint(anchor_type="antlr_pair", value=value, source_text=text)
                for value in pairs.get("temporal", [])
            ],
            causal_constraints=[
                CausalConstraint(marker=value, source_text=text) for value in pairs.get("causal", [])
            ],
        )

    def parse_metric(self, text: str) -> MetricSpec | SpecParseError:
        normalized = _normalize_text(text)
        entity_terms = _entity_terms(normalized, self._matcher)
        if not normalized:
            return SpecParseError(
                spec_kind="metric",
                source_text=text,
                normalized_text=normalized,
                error_code="empty_metric",
            )
        metric_name = entity_terms[0] if entity_terms else normalized
        group_terms = [term for term in entity_terms if any(token in normalized for token in ("按", "分组", "group"))]
        dsl_parts = ["METRIC", _dsl_pair("name", metric_name)]
        dsl_parts.extend(_dsl_pair("measure", term) for term in (entity_terms or [metric_name]))
        dsl_parts.extend(_dsl_pair("group", term) for term in group_terms)
        for item in _temporal_constraints(normalized, self._matcher):
            dsl_parts.append(_dsl_pair("temporal", item.value))
        try:
            pairs = _parse_pairs_via_antlr(" ".join(dsl_parts))
        except Exception:
            return SpecParseError(
                spec_kind="metric",
                source_text=text,
                normalized_text=normalized,
                error_code="antlr_metric_parse_failed",
            )
        return MetricSpec(
            source_text=text,
            normalized_text=normalized,
            metric_name=str((pairs.get("name") or [metric_name])[0]),
            measure_terms=list(pairs.get("measure", [])) or [metric_name],
            group_terms=list(pairs.get("group", [])),
            preferred_date_terms=_preferred_date_terms(normalized),
            temporal_constraints=[
                TemporalConstraint(anchor_type="antlr_pair", value=value, source_text=text)
                for value in pairs.get("temporal", [])
            ],
        )

    def parse_filter(self, text: str) -> FilterSpec | SpecParseError:
        normalized = _normalize_text(text)
        year_match = re.search(r"(20\d{2})", normalized)
        if year_match:
            dsl = f"FILTER {_dsl_pair('field', 'year')} {_dsl_pair('operator', 'eq')} {_dsl_pair('value', year_match.group(1))}"
            try:
                pairs = _parse_pairs_via_antlr(dsl)
            except Exception:
                return SpecParseError(
                    spec_kind="filter",
                    source_text=text,
                    normalized_text=normalized,
                    error_code="antlr_filter_parse_failed",
                )
            return FilterSpec(
                source_text=text,
                normalized_text=normalized,
                field=str((pairs.get("field") or ["year"])[0]),
                operator=str((pairs.get("operator") or ["eq"])[0]),
                value=str((pairs.get("value") or [year_match.group(1)])[0]),
                preferred_date_terms=_preferred_date_terms(normalized),
                temporal_constraints=_temporal_constraints(normalized, self._matcher),
            )
        entity_terms = _entity_terms(normalized, self._matcher)
        if entity_terms:
            dsl = (
                f"FILTER {_dsl_pair('field', 'keyword')} "
                f"{_dsl_pair('operator', 'contains')} {_dsl_pair('value', entity_terms[0])}"
            )
            try:
                pairs = _parse_pairs_via_antlr(dsl)
            except Exception:
                return SpecParseError(
                    spec_kind="filter",
                    source_text=text,
                    normalized_text=normalized,
                    error_code="antlr_filter_parse_failed",
                )
            return FilterSpec(
                source_text=text,
                normalized_text=normalized,
                field=str((pairs.get("field") or ["keyword"])[0]),
                operator=str((pairs.get("operator") or ["contains"])[0]),
                value=str((pairs.get("value") or [entity_terms[0]])[0]),
                preferred_date_terms=_preferred_date_terms(normalized),
                temporal_constraints=_temporal_constraints(normalized, self._matcher),
            )
        return SpecParseError(
            spec_kind="filter",
            source_text=text,
            normalized_text=normalized,
            error_code="unsupported_filter_shape",
        )

    def compile_business_context(
        self,
        *,
        rules: Iterable[str],
        metrics: Iterable[str],
        filters: Iterable[str],
    ) -> SpecCompilationResult:
        parsed_rules: list[RuleSpec] = []
        parsed_metrics: list[MetricSpec] = []
        parsed_filters: list[FilterSpec] = []
        errors: list[SpecParseError] = []

        for item in rules:
            result = self.parse_rule(item)
            if isinstance(result, SpecParseError):
                errors.append(result)
            else:
                parsed_rules.append(result)
        for item in metrics:
            result = self.parse_metric(item)
            if isinstance(result, SpecParseError):
                errors.append(result)
            else:
                parsed_metrics.append(result)
        for item in filters:
            result = self.parse_filter(item)
            if isinstance(result, SpecParseError):
                errors.append(result)
            else:
                parsed_filters.append(result)

        return SpecCompilationResult(
            rules=parsed_rules,
            metrics=parsed_metrics,
            filters=parsed_filters,
            errors=errors,
        )
