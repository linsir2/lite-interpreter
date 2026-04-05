"""
src/kag/builder/chunker.py
文档分块器 (Document Chunker)

职责：实现三层分块策略，防止巨型章节：
1. 结构化感知 (Layout-aware) - 基于文档结构进行分块
2. 按节定父块 (Parent-child Chunking) - 父子分块关系，保持上下文连贯性
3. 长度兜底防御 (SentenceSplitter 兜底) - 当上述策略失效时，使用 SentenceSplitter 进行安全分块
"""
import re
from typing import Dict, List, Any, Tuple, Optional
from enum import Enum

from src.common import get_logger, generate_uuid, estimate_tokens
from src.kag.framework.llama_index_adapter import split_text_with_llama_index
from src.storage.schema import DocChunk, ParsedDocument
from config.settings import CHUNK_SIZE, CHUNK_OVERLAP, PARENT_CHUNK_SIZE

logger = get_logger(__name__)

class ChunkingStrategy(str, Enum):
    """分块策略枚举"""
    LAYOUT_AWARE = "layout_aware"  # 结构化感知分块
    PARENT_CHILD = "parent_child"  # 父子分块
    SENTENCE_SPLITTER = "sentence_splitter"  # 句子分割器兜底

class DocumentChunker:
    """文档分块器"""
    
    @classmethod
    def chunk_document(cls, parsed_doc: ParsedDocument, strategy: ChunkingStrategy = None) -> List[DocChunk]:
        """
        对解析后的文档进行分块
        
        Args:
            parsed_doc: 解析后的文档字典
            strategy: 分块策略，如果为None则自动选择
            
        Returns:
            DocChunk对象列表
        """
        doc_id = parsed_doc.doc_id or generate_uuid()
        metadata = dict(parsed_doc.metadata)
        sections = [section.model_dump() for section in parsed_doc.sections]
        content = parsed_doc.content
        
        logger.info(f"[Chunker] 开始分块文档: {metadata.get('file_name', 'unknown')}, 文档ID: {doc_id}")
        
        # 如果没有指定策略，则根据文档特征自动选择
        if strategy is None:
            strategy = cls._select_strategy(sections, content)
        
        logger.info(f"[Chunker] 使用分块策略: {strategy.value}")
        
        # 根据策略进行分块
        if strategy == ChunkingStrategy.LAYOUT_AWARE:
            chunks = cls._layout_aware_chunking(sections, doc_id, metadata)
        elif strategy == ChunkingStrategy.PARENT_CHILD:
            chunks = cls._parent_child_chunking(sections, doc_id, metadata)
        else:  # SENTENCE_SPLITTER
            chunks = cls._sentence_splitter_chunking(content, doc_id, metadata)
        
        # 验证分块结果
        chunks = cls._validate_chunks(chunks)
        
        logger.info(f"[Chunker] 分块完成，共生成 {len(chunks)} 个chunk")
        return chunks
    
    @classmethod
    def _select_strategy(cls, sections: List[Dict[str, Any]], content: str) -> ChunkingStrategy:
        """根据文档特征选择分块策略"""
        
        # 如果有清晰的章节结构，使用结构化感知分块
        if sections and len(sections) > 1:
            # 检查章节是否有清晰的层级关系
            levels = [s.get('level', 1) for s in sections]
            if len(set(levels)) > 1:  # 有多个层级
                return ChunkingStrategy.LAYOUT_AWARE
        
        # 如果有章节但层级单一，使用父子分块
        if sections and len(sections) > 0:
            return ChunkingStrategy.PARENT_CHILD
        
        # 否则使用句子分割器兜底
        return ChunkingStrategy.SENTENCE_SPLITTER
    
    @classmethod
    def _layout_aware_chunking(cls, sections: List[Dict[str, Any]], doc_id: str, metadata: Dict[str, Any]) -> List[DocChunk]:
        """结构化感知分块：基于文档结构进行分块"""
        chunks = []
        
        for section in sections:
            section_id = section.get('id', generate_uuid())
            section_title = section.get('title', '')
            section_content = section.get('content', '')
            section_level = section.get('level', 1)
            
            if not section_content.strip():
                continue
            
            # 根据章节级别和内容长度决定是否进一步分块
            if section_level <= 2 and len(section_content) > PARENT_CHUNK_SIZE:
                # 高级别章节且内容较长，进行子分块
                sub_chunks = cls._split_by_sentences(section_content, CHUNK_SIZE, CHUNK_OVERLAP)
                
                for i, sub_content in enumerate(sub_chunks):
                    chunk_metadata = {
                        **metadata,
                        'section_id': section_id,
                        'section_title': section_title,
                        'section_level': section_level,
                        'chunk_index': i,
                        'total_chunks': len(sub_chunks),
                        'chunking_strategy': 'layout_aware_sub'
                    }
                    
                    chunk = DocChunk(
                        chunk_id=generate_uuid(),
                        doc_id=doc_id,
                        content=sub_content,
                        metadata=chunk_metadata
                    )
                    chunks.append(chunk)
            else:
                # 低级别章节或内容较短，直接作为一个chunk
                chunk_metadata = {
                    **metadata,
                    'section_id': section_id,
                    'section_title': section_title,
                    'section_level': section_level,
                    'chunk_index': 0,
                    'total_chunks': 1,
                    'chunking_strategy': 'layout_aware_direct'
                }
                
                chunk = DocChunk(
                    chunk_id=generate_uuid(),
                    doc_id=doc_id,
                    content=section_content,
                    metadata=chunk_metadata
                )
                chunks.append(chunk)
        
        return chunks
    
    @classmethod
    def _parent_child_chunking(cls, sections: List[Dict[str, Any]], doc_id: str, metadata: Dict[str, Any]) -> List[DocChunk]:
        """父子分块：创建父子关系的chunk"""
        chunks = []
        
        for section in sections:
            section_id = section.get('id', generate_uuid())
            section_title = section.get('title', '')
            section_content = section.get('content', '')
            
            if not section_content.strip():
                continue
            
            # 创建父chunk（摘要或标题）
            parent_content = f"{section_title}\n\n{cls._create_summary(section_content)}"
            
            parent_metadata = {
                **metadata,
                'section_id': section_id,
                'section_title': section_title,
                'chunk_type': 'parent',
                'chunking_strategy': 'parent_child'
            }
            
            parent_chunk = DocChunk(
                chunk_id=generate_uuid(),
                doc_id=doc_id,
                content=parent_content[:CHUNK_SIZE],  # 限制长度
                metadata=parent_metadata
            )
            chunks.append(parent_chunk)
            
            # 如果内容较长，创建子chunk
            if len(section_content) > CHUNK_SIZE:
                child_chunks = cls._split_by_sentences(section_content, CHUNK_SIZE, CHUNK_OVERLAP)
                
                for i, child_content in enumerate(child_chunks):
                    child_metadata = {
                        **metadata,
                        'section_id': section_id,
                        'section_title': section_title,
                        'chunk_type': 'child',
                        'parent_chunk_id': parent_chunk.chunk_id,
                        'child_index': i,
                        'total_children': len(child_chunks),
                        'chunking_strategy': 'parent_child'
                    }
                    
                    child_chunk = DocChunk(
                        chunk_id=generate_uuid(),
                        doc_id=doc_id,
                        content=child_content,
                        metadata=child_metadata
                    )
                    chunks.append(child_chunk)
        
        return chunks
    
    @classmethod
    def _sentence_splitter_chunking(cls, content: str, doc_id: str, metadata: Dict[str, Any]) -> List[DocChunk]:
        """句子分割器分块：兜底策略"""
        chunks = []
        
        # 使用 LlamaIndex SentenceSplitter 进行兜底分块
        sentence_chunks = split_text_with_llama_index(content, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
        
        for i, chunk_content in enumerate(sentence_chunks):
            chunk_metadata = {
                **metadata,
                'chunk_index': i,
                'total_chunks': len(sentence_chunks),
                'chunking_strategy': 'sentence_splitter'
            }
            
            chunk = DocChunk(
                chunk_id=generate_uuid(),
                doc_id=doc_id,
                content=chunk_content,
                metadata=chunk_metadata
            )
            chunks.append(chunk)
        
        return chunks
    
    @classmethod
    def _split_by_sentences(cls, text: str, chunk_size: int, overlap: int) -> List[str]:
        """按句子分割文本，考虑chunk大小和重叠"""
        if not text.strip():
            return []
        return split_text_with_llama_index(text, chunk_size=chunk_size, overlap=overlap)
    
    @classmethod
    def _create_summary(cls, text: str, max_length: int = 200) -> str:
        """创建文本摘要"""
        if len(text) <= max_length:
            return text
        
        # 简单的摘要生成：取开头和结尾的部分
        prefix = text[:max_length//2]
        suffix = text[-max_length//2:] if len(text) > max_length else ""
        
        return f"{prefix}...{suffix}"
    
    @classmethod
    def _validate_chunks(cls, chunks: List[DocChunk]) -> List[DocChunk]:
        """验证分块结果，确保质量"""
        valid_chunks = []
        
        for chunk in chunks:
            # 检查内容是否为空
            if not chunk.content or not chunk.content.strip():
                logger.warning(f"[Chunker] 跳过空chunk: {chunk.chunk_id}")
                continue
            
            # 检查内容是否过短
            if len(chunk.content.strip()) < 20:
                logger.warning(f"[Chunker] 跳过过短chunk: {chunk.chunk_id} (长度: {len(chunk.content)})")
                continue
            
            # 检查Token数量
            token_count = estimate_tokens(chunk.content)
            if token_count > CHUNK_SIZE * 2:  # 允许一定的超出
                logger.warning(f"[Chunker] chunk过长: {chunk.chunk_id} (Token: {token_count})")
                # 可以在这里进行进一步分割，但暂时先保留
            
            valid_chunks.append(chunk)
        
        return valid_chunks
    
    @classmethod
    def get_chunk_statistics(cls, chunks: List[DocChunk]) -> Dict[str, Any]:
        """获取分块统计信息"""
        if not chunks:
            return {}
        
        total_chunks = len(chunks)
        total_chars = sum(len(chunk.content) for chunk in chunks)
        avg_chars = total_chars / total_chunks if total_chunks > 0 else 0
        
        # 按策略分组
        strategy_counts = {}
        for chunk in chunks:
            strategy = chunk.metadata.get('chunking_strategy', 'unknown')
            strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
        
        return {
            'total_chunks': total_chunks,
            'total_characters': total_chars,
            'average_chars_per_chunk': avg_chars,
            'strategy_distribution': strategy_counts
        }
