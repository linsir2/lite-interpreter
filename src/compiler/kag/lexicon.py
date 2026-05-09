"""Shared lexical compiler built on top of pyahocorasick."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import ahocorasick
import yaml
from config.settings import ANALYSIS_RUNTIME_POLICY_PATH, GRAPH_LEXICON_PATH

from src.common import generate_uuid

from .types import LexiconMatch, QueryLexicalSignals


@dataclass(frozen=True)
class CompiledLexicon:
    automaton: ahocorasick.Automaton
    entries_by_surface: dict[str, list[dict[str, Any]]]


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _load_graph_lexicon() -> dict[str, Any]:
    if not GRAPH_LEXICON_PATH.exists():
        return {}
    raw = yaml.safe_load(GRAPH_LEXICON_PATH.read_text(encoding="utf-8")) or {}
    return raw if isinstance(raw, dict) else {}


def _load_analysis_runtime_policy() -> dict[str, Any]:
    if not ANALYSIS_RUNTIME_POLICY_PATH.exists():
        return {}
    raw = yaml.safe_load(ANALYSIS_RUNTIME_POLICY_PATH.read_text(encoding="utf-8")) or {}
    return raw if isinstance(raw, dict) else {}


class LexiconCompiler:
    @classmethod
    @lru_cache(maxsize=1)
    def compile(cls) -> CompiledLexicon:
        entries: list[dict[str, Any]] = []
        graph_lexicon = _load_graph_lexicon()
        for canonical, payload in dict(graph_lexicon.get("aliases") or {}).items():
            aliases = [canonical, *(payload.get("aliases") or [])]
            node_type = str(payload.get("node_type") or "concept")
            graph_label = "named" if node_type == "named" else "semantic"
            for alias in aliases:
                normalized = _normalize_text(alias)
                if not normalized:
                    continue
                entries.append(
                    {
                        "surface": alias,
                        "normalized_surface": normalized,
                        "canonical": str(canonical),
                        "category": "entity",
                        "source_lexicon": "graph.aliases",
                        "metadata": {"node_type": node_type, "graph_label": graph_label},
                    }
                )
        for item in list(graph_lexicon.get("domain_terms") or []):
            surface = str(item.get("value") or "").strip()
            normalized = _normalize_text(surface)
            if not normalized:
                continue
            node_type = str(item.get("node_type") or "concept")
            graph_label = "named" if node_type == "named" else "semantic"
            entries.append(
                {
                    "surface": surface,
                    "normalized_surface": normalized,
                    "canonical": str(item.get("canonical_name") or surface),
                    "category": "entity",
                    "source_lexicon": "graph.domain_terms",
                    "metadata": {"node_type": node_type, "graph_label": graph_label},
                }
            )
        for marker in list(graph_lexicon.get("causal_markers") or []):
            normalized = _normalize_text(marker)
            if normalized:
                entries.append(
                    {
                        "surface": marker,
                        "normalized_surface": normalized,
                        "canonical": str(marker),
                        "category": "causal",
                        "source_lexicon": "graph.causal_markers",
                        "metadata": {"graph_label": "causal"},
                    }
                )
        for marker in list(graph_lexicon.get("temporal_markers") or []):
            normalized = _normalize_text(marker)
            if normalized:
                entries.append(
                    {
                        "surface": marker,
                        "normalized_surface": normalized,
                        "canonical": str(marker),
                        "category": "temporal",
                        "source_lexicon": "graph.temporal_markers",
                        "metadata": {"graph_label": "temporal"},
                    }
                )

        policy = _load_analysis_runtime_policy()
        for key, category in (
            ("dynamic_patterns", "dynamic"),
            ("dataset_keywords", "dataset"),
            ("document_keywords", "document"),
        ):
            for value in list(policy.get(key) or []):
                normalized = _normalize_text(value)
                if normalized:
                    entries.append(
                        {
                            "surface": value,
                            "normalized_surface": normalized,
                            "canonical": str(value),
                            "category": category,
                            "source_lexicon": f"analysis_runtime.{key}",
                            "metadata": {},
                        }
                    )

        automaton = ahocorasick.Automaton()
        entries_by_surface: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            normalized = str(entry["normalized_surface"])
            entries_by_surface.setdefault(normalized, []).append(entry)
        for normalized in entries_by_surface:
            automaton.add_word(normalized, normalized)
        automaton.make_automaton()
        return CompiledLexicon(automaton=automaton, entries_by_surface=entries_by_surface)


class LexiconMatcher:
    def __init__(self, compiled: CompiledLexicon | None = None):
        self._compiled = compiled or LexiconCompiler.compile()

    def match_text(self, text: str) -> list[LexiconMatch]:
        normalized = _normalize_text(text)
        if not normalized:
            return []
        raw_matches: list[LexiconMatch] = []
        category_priority = {
            "entity": 0,
            "temporal": 1,
            "causal": 2,
            "document": 3,
            "dataset": 4,
            "dynamic": 5,
        }
        for end_index, normalized_surface in self._compiled.automaton.iter(normalized):
            start_index = end_index - len(normalized_surface) + 1
            for entry in self._compiled.entries_by_surface.get(normalized_surface, []):
                raw_matches.append(
                    LexiconMatch(
                        match_id=generate_uuid(),
                        surface=str(entry["surface"]),
                        canonical=str(entry["canonical"]),
                        category=str(entry["category"]),
                        source_lexicon=str(entry["source_lexicon"]),
                        span_start=start_index,
                        span_end=end_index + 1,
                        metadata=dict(entry.get("metadata") or {}),
                    )
                )
        raw_matches.sort(
            key=lambda item: (
                item.span_start,
                -(item.span_end - item.span_start),
                category_priority.get(item.category, 99),
                item.category,
            )
        )

        accepted: list[LexiconMatch] = []
        for match in raw_matches:
            if any(
                not (match.span_end <= existing.span_start or match.span_start >= existing.span_end)
                and (match.span_start, match.span_end) != (existing.span_start, existing.span_end)
                for existing in accepted
            ):
                continue
            accepted.append(match)
        return accepted

    def classify_query(self, query: str) -> QueryLexicalSignals:
        matches = self.match_text(query)
        return QueryLexicalSignals(
            dynamic_hits=[item for item in matches if item.category == "dynamic"],
            dataset_hits=[item for item in matches if item.category == "dataset"],
            document_hits=[item for item in matches if item.category == "document"],
            entity_hits=[item for item in matches if item.category == "entity"],
            temporal_hits=[item for item in matches if item.category == "temporal"],
            causal_hits=[item for item in matches if item.category == "causal"],
        )
