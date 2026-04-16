"""Query-aware 上下文压缩器。"""

from __future__ import annotations

import re

from config.settings import COMPRESSION_RATIO, CONTEXT_MAX_TOKENS, CONTEXT_MODEL_NAME

from src.common import count_text_tokens_exact
from src.common.llm_client import LiteLLMClient
from src.kag.compiler import LexiconMatcher


class ContextCompressor:
    @classmethod
    def compress(
        cls,
        query: str,
        candidates: list[dict[str, object]],
        max_tokens: int = CONTEXT_MAX_TOKENS,
        model_alias: str | None = None,
    ) -> list[dict[str, object]]:
        if not candidates:
            return []
        matcher = LexiconMatcher()
        lexical_terms = {match.canonical.lower() for match in matcher.match_text(query) if match.canonical}
        keywords = lexical_terms or {token for token in re.split(r"\W+", query.lower()) if token}
        budget = max_tokens
        compressed: list[dict[str, object]] = []
        model_name = LiteLLMClient.resolve_model_name(model_alias or CONTEXT_MODEL_NAME)
        for candidate in candidates:
            text = str(candidate.get("text", "")).strip()
            if not text:
                continue
            sentences = re.split(r"(?<=[。！？.!?])\s*", text)
            ranked = sorted(
                [sentence for sentence in sentences if sentence.strip()],
                key=lambda sentence: sum(keyword in sentence.lower() for keyword in keywords),
                reverse=True,
            )
            keep_count = max(1, int(len(ranked) * max(COMPRESSION_RATIO, 0.2)))
            summary = " ".join(ranked[:keep_count]).strip() or text[:240]
            token_cost = count_text_tokens_exact(summary, model_name=model_name)
            if token_cost > budget:
                break
            budget -= token_cost
            compressed.append({**candidate, "compressed_text": summary})
        return compressed
