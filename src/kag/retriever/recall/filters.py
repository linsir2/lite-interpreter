"""检索过滤器工具。"""

from __future__ import annotations

from typing import Any

TEMPORAL_FILTER_KEYS = {"preferred_date_terms", "temporal_constraints"}


def normalize_filters(filters: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in (filters or {}).items():
        if value is None:
            continue
        key_text = str(key)
        if key_text in TEMPORAL_FILTER_KEYS:
            normalized[key_text] = [str(item).strip() for item in (value or []) if str(item).strip()]
        else:
            normalized[key_text] = str(value)
    return normalized


def exact_match_filters(filters: dict[str, Any]) -> dict[str, str]:
    return {
        str(key): str(value)
        for key, value in (filters or {}).items()
        if key not in TEMPORAL_FILTER_KEYS and value is not None
    }


def temporal_query_terms(filters: dict[str, Any] | None) -> list[str]:
    terms: list[str] = []
    for key in TEMPORAL_FILTER_KEYS:
        for value in list((filters or {}).get(key) or []):
            text = str(value).strip().lower()
            if text and text not in terms:
                terms.append(text)
    return terms


def extract_query_terms(query: str, extra_terms: list[str] | None = None) -> list[str]:
    terms = [term.lower() for term in query.replace("/", " ").replace("_", " ").split() if term.strip()]
    for term in extra_terms or []:
        text = str(term).strip().lower()
        if text and text not in terms:
            terms.append(text)
    return terms
