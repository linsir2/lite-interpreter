"""查询理解：坚持规则优先，避免无依据生成过滤条件。"""

from __future__ import annotations

import re
from typing import Any

from src.common.logger import get_logger
from src.kag.compiler import KnowledgeCompilerService, SpecParseError

logger = get_logger(__name__)

ALLOWED_FILTER_KEYS = {"year", "doc_type", "department", "status"}
DOC_TYPE_KEYWORDS = {"制度": "policy", "手册": "manual", "合同": "contract", "规范": "spec"}


def validate_filters(filters: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(filters, dict):
        return {}
    valid_filters = {}
    for key, value in filters.items():
        if key in ALLOWED_FILTER_KEYS:
            valid_filters[key] = value
        else:
            logger.warning(f"[QU] 剔除非法 Filter: {key}={value}")
    return valid_filters


def analyze_query(query: str, tenant_id: str) -> tuple[str, dict[str, Any], float, bool]:
    signals = KnowledgeCompilerService.classify_query(query)
    filters: dict[str, Any] = {}
    year_match = re.search(r"(20\d{2})", query)
    if year_match:
        filters["year"] = year_match.group(1)
    for keyword, doc_type in DOC_TYPE_KEYWORDS.items():
        if keyword in query or any(item.canonical == keyword for item in signals.entity_hits):
            filters["doc_type"] = doc_type
            break
    filter_spec = KnowledgeCompilerService.parse_filter(query)
    if not isinstance(filter_spec, SpecParseError):
        if filter_spec.field == "year" and str(filter_spec.value).strip():
            filters["year"] = str(filter_spec.value).strip()
        if filter_spec.preferred_date_terms:
            filters["preferred_date_terms"] = list(filter_spec.preferred_date_terms)

    keywords = [
        *[item.canonical for item in signals.entity_hits],
        *[item.canonical for item in signals.document_hits],
        *[item.canonical for item in signals.dataset_hits],
    ]
    if not isinstance(filter_spec, SpecParseError):
        keywords.extend(list(filter_spec.preferred_date_terms or []))
    if not keywords:
        keywords = [term for term in re.split(r"\W+", query) if term]
    rewritten_query = " ".join(dict.fromkeys(keywords)) or query

    difficulty_score = 0.25
    if len(keywords) >= 6:
        difficulty_score = 0.6
    if any(word in query for word in ["对比", "总结", "链路", "原因", "影响"]) or signals.causal_hits:
        difficulty_score = max(difficulty_score, 0.8)

    is_multi_hop = any(word in query for word in ["关系", "链路", "影响", "原因", "依赖", "牵连"]) or bool(
        signals.causal_hits or signals.temporal_hits
    )
    return rewritten_query, validate_filters(filters), difficulty_score, is_multi_hop
