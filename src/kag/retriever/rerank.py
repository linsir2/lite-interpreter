"""轻量重排器。"""

from __future__ import annotations

import re

from config.settings import RERANK_CANDIDATE_LIMIT, RERANK_CANDIDATE_MULTIPLIER

from src.kag.compiler import KnowledgeCompilerService


class KeywordReranker:
    @staticmethod
    def score(query: str, text: str) -> float:
        lexical_terms = [match.canonical for match in KnowledgeCompilerService.match_text(query) if match.canonical]
        keywords = lexical_terms or [token for token in re.split(r"\W+", query.lower()) if token]
        lowered_text = text.lower()
        return float(sum(lowered_text.count(keyword) for keyword in keywords))


def _candidate_identity(candidate: dict[str, object]) -> str:
    return str(candidate.get("chunk_id") or candidate.get("path") or candidate.get("text") or "")


def _dedup_candidates(candidates: list[dict[str, object]]) -> list[dict[str, object]]:
    deduped: list[dict[str, object]] = []
    seen: set[str] = set()
    for candidate in candidates:
        identity = _candidate_identity(candidate)
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        deduped.append(candidate)
    return deduped


def cross_encoder_rerank(query: str, candidates: list[dict[str, object]], top_k: int = 15) -> list[dict[str, object]]:
    bounded_top_k = max(1, int(top_k or 1))
    candidate_limit = min(RERANK_CANDIDATE_LIMIT, max(bounded_top_k, bounded_top_k * RERANK_CANDIDATE_MULTIPLIER))
    bounded_candidates = _dedup_candidates(list(candidates or []))[:candidate_limit]
    rescored = []
    for candidate in bounded_candidates:
        text = str(candidate.get("text", ""))
        score = float(candidate.get("score", 0.0)) + KeywordReranker.score(query, text)
        rescored.append({**candidate, "score": score})
    rescored.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
    return rescored[:bounded_top_k]
