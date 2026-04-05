"""KAG Builder 总调度器。"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

from src.common import generate_uuid, get_logger
from src.kag.builder.chunker import ChunkingStrategy, DocumentChunker
from src.kag.builder.classifier import DocProcessClass, DocumentClassifier
from src.kag.builder.embedding import EmbeddingGenerator
from src.kag.builder.entity_extractor import EntityExtractor
from src.kag.builder.fusion import KnowledgeFusion
from src.kag.builder.parallel_ingestor import ParallelIngestor
from src.kag.builder.relation_extractor import RelationExtractor
from src.storage.repository.knowledge_repo import KnowledgeRepo
from src.storage.schema import DocChunk, KnowledgeTriple, ParsedDocument

logger = get_logger(__name__)


@dataclass
class IngestedDocument:
    doc_id: str
    file_name: str
    process_class: str
    chunk_count: int
    vector_count: int
    triple_count: int
    parse_mode: str
    parser_diagnostics: Dict[str, object]


class KagBuilderOrchestrator:
    @classmethod
    def ingest_documents(
        cls,
        doc_paths: List[str],
        tenant_id: str,
        workspace_id: str = "default_ws",
        upload_batch_id: Optional[str] = None,
    ) -> List[Dict[str, object]]:
        if not doc_paths:
            return []

        upload_batch_id = upload_batch_id or generate_uuid()
        parsed_docs = ParallelIngestor.parse_documents(doc_paths, tenant_id, upload_batch_id)
        embedder = EmbeddingGenerator()
        extractor = EntityExtractor(use_llm=False)

        results: List[IngestedDocument] = []
        for parsed_doc in parsed_docs:
            file_path = str(parsed_doc.metadata.get("file_path", ""))
            process_class = DocumentClassifier.classify(file_path)
            if process_class == DocProcessClass.UNKNOWN:
                logger.warning(f"[Orchestrator] 跳过不受支持的文件: {file_path}")
                continue

            chunks = cls._build_chunks(parsed_doc, process_class)
            embeddings = embedder.generate_embeddings(chunks)
            embeddings_map = {item.chunk_id: item.reduced_embedding.tolist() for item in embeddings}
            KnowledgeRepo.save_chunks_and_embeddings(tenant_id, workspace_id, chunks, embeddings_map)

            triples: List[KnowledgeTriple] = []
            if process_class == DocProcessClass.LARGE:
                entities = []
                chunk_text_map = {chunk.chunk_id: chunk.content for chunk in chunks}
                for chunk in chunks:
                    if chunk.metadata.get("chunk_type") == "parent":
                        continue
                    entities.extend(extractor.extract_entities(chunk.content, chunk.doc_id, chunk.chunk_id))
                triples = KnowledgeFusion.fuse(RelationExtractor.extract_relations(chunk_text_map, entities))
                KnowledgeRepo.save_graph_triples(tenant_id, workspace_id, triples)

            results.append(
                IngestedDocument(
                    doc_id=str(parsed_doc.doc_id),
                    file_name=str(parsed_doc.metadata.get("file_name", "unknown")),
                    process_class=process_class.value,
                    chunk_count=len(chunks),
                    vector_count=len(embeddings_map),
                    triple_count=len(triples),
                    parse_mode=str(parsed_doc.metadata.get("parse_mode", "default")),
                    parser_diagnostics=dict(parsed_doc.parser_diagnostics),
                )
            )

        return [asdict(item) for item in results]

    @classmethod
    def _build_chunks(cls, parsed_doc: ParsedDocument, process_class: DocProcessClass) -> List[DocChunk]:
        if process_class == DocProcessClass.SMALL:
            content = str(parsed_doc.content).strip()
            if not content:
                return []
            chunk = DocChunk(
                chunk_id=generate_uuid(),
                doc_id=str(parsed_doc.doc_id),
                content=content,
                metadata={
                    **dict(parsed_doc.metadata),
                    "chunking_strategy": ChunkingStrategy.SENTENCE_SPLITTER.value,
                    "summary": content[:200],
                    "version": "1.0",
                },
            )
            return [chunk]

        chunks = DocumentChunker.chunk_document(parsed_doc)
        for chunk in chunks:
            chunk.metadata.setdefault("summary", chunk.content[:200])
            chunk.metadata.setdefault("version", "1.0")
        return chunks
