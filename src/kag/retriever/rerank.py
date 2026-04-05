"""轻量重排器。"""
from __future__ import annotations

import re
from typing import Dict, List


class KeywordReranker:
    @staticmethod
    def score(query: str, text: str) -> float:
        keywords = [token for token in re.split(r"\W+", query.lower()) if token]
        lowered_text = text.lower()
        return float(sum(lowered_text.count(keyword) for keyword in keywords))


def cross_encoder_rerank(query: str, candidates: List[Dict[str, object]], top_k: int = 15) -> List[Dict[str, object]]:
    rescored = []
    for candidate in candidates:
        text = str(candidate.get("text", ""))
        score = float(candidate.get("score", 0.0)) + KeywordReranker.score(query, text)
        rescored.append({**candidate, "score": score})
    rescored.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
    return rescored[:top_k]
