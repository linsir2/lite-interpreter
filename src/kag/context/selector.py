"""候选片段选择器。"""
from __future__ import annotations

from collections import defaultdict


class ContextSelector:
    @classmethod
    def select(cls, candidates: list[dict[str, object]], top_k: int = 8) -> list[dict[str, object]]:
        if not candidates:
            return []
        ordered = sorted(candidates, key=lambda item: float(item.get("score", 0.0)), reverse=True)
        selected: list[dict[str, object]] = []
        per_source = defaultdict(int)
        for candidate in ordered:
            source = str(candidate.get("source", "unknown"))
            if per_source[source] >= 3:
                continue
            selected.append(candidate)
            per_source[source] += 1
            if len(selected) >= top_k:
                break
        return selected
