"""检索过滤器工具。"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List


def normalize_filters(filters: Dict[str, Any]) -> Dict[str, str]:
    return {str(key): str(value) for key, value in (filters or {}).items() if value is not None}


def extract_query_terms(query: str) -> List[str]:
    return [term.lower() for term in query.replace("/", " ").replace("_", " ").split() if term.strip()]
