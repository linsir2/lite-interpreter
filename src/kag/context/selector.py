"""候选片段选择器。"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List


class ContextSelector:
    @classmethod
    def select(cls, candidates: List[Dict[str, object]], top_k: int = 8) -> List[Dict[str, object]]:
        if not candidates:
            return []
        ordered = sorted(candidates, key=lambda item: float(item.get("score", 0.0)), reverse=True)
        selected: List[Dict[str, object]] = []
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
