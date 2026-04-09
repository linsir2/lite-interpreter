"""检索结果去重。"""

from __future__ import annotations


def semantic_dedup(candidates: list[dict[str, object]]) -> list[dict[str, object]]:
    unique = {}
    for candidate in candidates:
        key = (
            str(candidate.get("chunk_id") or ""),
            str(candidate.get("text") or "").strip().lower(),
        )
        existing = unique.get(key)
        if not existing or float(candidate.get("score", 0.0)) > float(existing.get("score", 0.0)):
            unique[key] = candidate
    return list(unique.values())
