"""Structure raw web-search / web-fetch results inline via Instructor.

Each call extracts one ExternalKnowledge (LookupTable | NumericFact | TextualFinding).
The tagged union is auto-discriminated by the `kind` Literal field.
"""

from __future__ import annotations

import hashlib

import instructor
from litellm import completion
from pydantic import BaseModel

from src.common import get_logger
from src.common.llm_client import LiteLLMClient
from src.compiler.kag.types import ExternalKnowledge

logger = get_logger(__name__)

_client = instructor.from_litellm(completion)

_MAX_INPUT_CHARS = 8000


def _extract_content_window(raw_text: str, max_chars: int = _MAX_INPUT_CHARS) -> str:
    """Extract head + tail window instead of blind head-only truncation."""
    if len(raw_text) <= max_chars:
        return raw_text
    head_size = max_chars * 3 // 4
    tail_size = max_chars - head_size - 50
    return raw_text[:head_size] + f"\n\n... [{len(raw_text) - max_chars} chars omitted] ...\n\n" + raw_text[-tail_size:]


def structure_external_evidence(
    *,
    raw_text: str,
    url: str = "",
    model_alias: str = "fast_model",
) -> ExternalKnowledge | None:
    """Extract structured ExternalKnowledge from raw web text via Instructor.

    Returns None on failure; the caller falls back to a TextualFinding
    wrapping the raw text.
    """
    if not raw_text.strip():
        return None

    config = LiteLLMClient.get_model_config(model_alias)
    model = str(config.params.get("model") or model_alias)

    try:
        result = _client.chat.completions.create(
            model=model,
            response_model=ExternalKnowledge,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Extract structured information from the following web page content. "
                        "Choose the appropriate shape:\n"
                        "- lookup_table: for tabular data (tariff schedules, price lists, comparison tables)\n"
                        "- numeric_fact: for a single numeric data point with entity/metric/value/unit/period\n"
                        "- textual_finding: for prose findings that don't fit a table or numeric shape\n\n"
                        f"Source URL: {url}\n\n"
                        f"{_extract_content_window(raw_text)}"
                    ),
                }
            ],
            max_retries=2,
        )
        # Stamp source provenance
        if isinstance(result, BaseModel) and hasattr(result, "source_url"):
            result.source_url = result.source_url or url
            if hasattr(result, "source_sha256") and not result.source_sha256:
                result.source_sha256 = hashlib.sha256(raw_text.encode()).hexdigest()
        return result
    except Exception:
        logger.debug("Evidence structurization failed, caller will fall back", exc_info=True)
        return None
