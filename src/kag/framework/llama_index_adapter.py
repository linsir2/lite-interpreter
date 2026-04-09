"""LlamaIndex adapters used by the KAG module without changing its core design."""

from __future__ import annotations

try:
    from llama_index.core.node_parser import SentenceSplitter
except ImportError:  # pragma: no cover - optional dependency in lightweight test envs
    SentenceSplitter = None

from config.settings import CHUNK_OVERLAP, CHUNK_SIZE, EMBEDDING_MODEL_NAME

from src.common.llm_client import LiteLLMClient
from src.storage.schema import DocChunk


class DashScopeLiteLLMEmbedding:
    """LlamaIndex-oriented embedding adapter backed by LiteLLM + DashScope."""

    def __init__(self, model_alias: str = EMBEDDING_MODEL_NAME):
        self.model_alias = model_alias

    def get_query_embedding(self, query: str) -> list[float]:
        return LiteLLMClient.embedding(self.model_alias, [query])[0]

    def get_text_embedding(self, text: str) -> list[float]:
        return LiteLLMClient.embedding(self.model_alias, [text])[0]

    def get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return LiteLLMClient.embedding(self.model_alias, texts)


def build_sentence_splitter(chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> SentenceSplitter:
    if SentenceSplitter is None:
        raise ImportError("llama_index is not installed")
    return SentenceSplitter(chunk_size=chunk_size, chunk_overlap=overlap)


def split_text_with_llama_index(text: str, *, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    if SentenceSplitter is None:
        if not text.strip():
            return []
        stride = max(1, chunk_size - overlap)
        return [text[index : index + chunk_size] for index in range(0, len(text), stride)]
    splitter = build_sentence_splitter(chunk_size=chunk_size, overlap=overlap)
    return splitter.split_text(text)


def chunks_to_nodes(chunks: list[DocChunk]):
    nodes = []
    for chunk in chunks:
        try:
            nodes.append(chunk.to_llama_index_node())
        except ImportError:
            nodes.append(
                {
                    "id": chunk.chunk_id,
                    "text": chunk.content,
                    "metadata": {"doc_id": chunk.doc_id, **chunk.metadata},
                }
            )
    return nodes
