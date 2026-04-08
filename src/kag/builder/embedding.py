"""
src/kag/builder/embedding.py
向量化引擎 (Embedding Generator)

职责：
1. 叶子节点计算：只挑出 Leaf（叶子节点）计算向量
2. MRL 降维：把叶子节点的向量截断到 256 维
3. 存储：降维后的向量存入 Qdrant
"""
from dataclasses import dataclass
from typing import Any

import numpy as np
from config.settings import EMBEDDING_BATCH_SIZE, EMBEDDING_DIM, EMBEDDING_MODEL_NAME, MRL_DIMENSION

from src.common import get_logger
from src.kag.framework.llama_index_adapter import DashScopeLiteLLMEmbedding, chunks_to_nodes
from src.storage.schema import DocChunk

logger = get_logger(__name__)

@dataclass
class EmbeddingResult:
    """向量化结果"""
    chunk_id: str
    original_embedding: np.ndarray  # 原始高维向量
    reduced_embedding: np.ndarray   # 降维后的向量
    metadata: dict[str, Any]

class EmbeddingGenerator:
    """向量化生成器"""
    
    def __init__(self, model_name: str = None):
        """
        初始化向量化生成器
        
        Args:
            model_name: 嵌入模型名称，如果为None则使用配置中的默认值
        """
        self.model_name = model_name or EMBEDDING_MODEL_NAME
        self.batch_size = EMBEDDING_BATCH_SIZE
        self.mrl_dimension = MRL_DIMENSION
        self.embedding_dim = EMBEDDING_DIM
        
        # 延迟加载模型
        self._model = None
        self._tokenizer = None
        self._llama_index_embedder = DashScopeLiteLLMEmbedding(model_alias=self.model_name)
        
        logger.info(f"[Embedding] 初始化向量化生成器，模型: {self.model_name}")
    
    def generate_embeddings(self, chunks: list[DocChunk]) -> list[EmbeddingResult]:
        """
        为chunk列表生成向量
        
        Args:
            chunks: DocChunk对象列表
            
        Returns:
            EmbeddingResult对象列表
        """
        if not chunks:
            logger.warning("[Embedding] 没有需要向量化的chunk")
            return []
        
        logger.info(f"[Embedding] 开始为 {len(chunks)} 个chunk生成向量")
        
        # 筛选叶子节点（根据chunk类型）
        leaf_chunks = self._filter_leaf_chunks(chunks)
        
        if not leaf_chunks:
            logger.warning("[Embedding] 没有找到叶子节点chunk")
            return []
        
        logger.info(f"[Embedding] 筛选出 {len(leaf_chunks)} 个叶子节点chunk")
        
        # 批量生成向量
        results = []
        for i in range(0, len(leaf_chunks), self.batch_size):
            batch = leaf_chunks[i:i + self.batch_size]
            batch_results = self._process_batch(batch)
            results.extend(batch_results)
            
            logger.info(f"[Embedding] 处理批次 {i//self.batch_size + 1}/{(len(leaf_chunks)-1)//self.batch_size + 1}")
        
        logger.info(f"[Embedding] 向量化完成，共生成 {len(results)} 个向量")
        return results
    
    def _filter_leaf_chunks(self, chunks: list[DocChunk]) -> list[DocChunk]:
        """筛选叶子节点chunk"""
        leaf_chunks = []
        
        for chunk in chunks:
            # 根据chunk类型判断是否为叶子节点
            chunk_type = chunk.metadata.get('chunk_type', '')
            # 叶子节点判断逻辑：
            # 1. 没有指定chunk_type的（默认就是叶子节点）
            # 2. chunk_type为'child'的（父子分块中的子节点）
            # 3. 不是parent类型的chunk
            if not chunk_type or chunk_type == 'child' or chunk_type != 'parent':
                leaf_chunks.append(chunk)
        
        return leaf_chunks
    
    def _process_batch(self, chunks: list[DocChunk]) -> list[EmbeddingResult]:
        """处理一个批次的chunk"""
        # 提取文本内容
        texts = [chunk.content for chunk in chunks]
        _ = chunks_to_nodes(chunks)
        
        # 生成原始向量
        original_embeddings = self._generate_original_embeddings(texts)
        
        # 应用MRL降维
        reduced_embeddings = self._apply_mrl_reduction(original_embeddings)
        
        # 构建结果
        results = []
        for i, chunk in enumerate(chunks):
            result = EmbeddingResult(
                chunk_id=chunk.chunk_id,
                original_embedding=original_embeddings[i],
                reduced_embedding=reduced_embeddings[i],
                metadata={
                    'doc_id': chunk.doc_id,
                    'chunk_metadata': chunk.metadata,
                    'model_name': self.model_name,
                    'original_dim': original_embeddings[i].shape[0],
                    'reduced_dim': reduced_embeddings[i].shape[0]
                }
            )
            results.append(result)
        
        return results
    
    def _generate_original_embeddings(self, texts: list[str]) -> list[np.ndarray]:
        """生成原始高维向量"""
        try:
            embeddings = self._llama_index_embedder.get_text_embeddings(texts)
            embeddings_np = np.array(embeddings, dtype=float)
            embeddings_np = self._normalize_embeddings(embeddings_np)
            return [embeddings_np[i] for i in range(len(texts))]
            
        except Exception as e:
            logger.error(f"[Embedding] 使用LiteLLM/DashScope生成向量失败: {e}")
            
            # 降级方案：使用简单的词向量平均
            return self._fallback_embedding(texts)
    
    def _load_model(self):
        """加载嵌入模型"""
        logger.info(f"[Embedding] 当前使用 LiteLLM + DashScope，不再加载本地 Transformer 模型: {self.model_name}")
        return None
    
    def _fallback_embedding(self, texts: list[str]) -> list[np.ndarray]:
        """降级方案：简单的词向量平均"""
        logger.warning("[Embedding] 使用降级方案生成向量")
        
        embeddings = []
        for text in texts:
            # 简单的基于字符的嵌入
            char_vectors = []
            for char in text[:100]:  # 只取前100个字符
                # 简单的字符编码
                char_code = ord(char) % 256
                char_vector = np.zeros(256)
                char_vector[char_code] = 1.0
                char_vectors.append(char_vector)
            
            if char_vectors:
                # 平均所有字符向量
                avg_vector = np.mean(char_vectors, axis=0)
            else:
                # 空文本使用零向量
                avg_vector = np.zeros(256)
            
            # 扩展到配置的维度
            if len(avg_vector) < self.embedding_dim:
                # 填充零
                padded = np.zeros(self.embedding_dim)
                padded[:len(avg_vector)] = avg_vector
                avg_vector = padded
            elif len(avg_vector) > self.embedding_dim:
                # 截断
                avg_vector = avg_vector[:self.embedding_dim]
            
            embeddings.append(avg_vector)
        
        return embeddings

    def embed_query(self, query: str) -> list[float]:
        """为检索 query 生成向量。"""
        try:
            vector = self._llama_index_embedder.get_query_embedding(query)
            reduced = self._apply_mrl_reduction([np.array(vector, dtype=float)])[0]
            return reduced.tolist()
        except Exception as e:
            logger.error(f"[Embedding] query 向量化失败，降级为简单向量: {e}")
            fallback = self._fallback_embedding([query])[0]
            reduced = self._apply_mrl_reduction([fallback])[0]
            return reduced.tolist()
    
    def _apply_mrl_reduction(self, embeddings: list[np.ndarray]) -> list[np.ndarray]:
        """应用MRL降维"""
        reduced_embeddings = []
        
        for emb in embeddings:
            # 简单的降维策略：取前MRL_DIMENSION维
            if len(emb) > self.mrl_dimension:
                reduced = emb[:self.mrl_dimension]
            else:
                # 如果原始维度小于目标维度，填充零
                reduced = np.zeros(self.mrl_dimension)
                reduced[:len(emb)] = emb
            
            # 归一化
            reduced = self._normalize_embeddings(reduced.reshape(1, -1))[0]
            reduced_embeddings.append(reduced)
        
        return reduced_embeddings
    
    def _normalize_embeddings(self, embeddings: np.ndarray) -> np.ndarray:
        """归一化向量（L2归一化）"""
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1  # 避免除以零
        return embeddings / norms
    
    def save_to_qdrant(self, embedding_results: list[EmbeddingResult], collection_name: str):
        """
        将向量保存到Qdrant
        
        Args:
            embedding_results: 向量化结果列表
            collection_name: Qdrant集合名称
        """
        try:
            from config.settings import QDRANT_HOST, QDRANT_PORT
            from qdrant_client import QdrantClient
            from qdrant_client.http import models as qdrant_models
            
            logger.info(f"[Embedding] 保存向量到Qdrant: {collection_name}")
            
            # 连接Qdrant
            client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, check_compatibility=False)
            
            # 准备数据
            points = []
            for result in embedding_results:
                point = qdrant_models.PointStruct(
                    id=result.chunk_id,
                    vector=result.reduced_embedding.tolist(),
                    payload={
                        'doc_id': result.metadata['doc_id'],
                        'chunk_metadata': result.metadata['chunk_metadata'],
                        'model_name': result.metadata['model_name'],
                        'original_dim': result.metadata['original_dim'],
                        'reduced_dim': result.metadata['reduced_dim']
                    }
                )
                points.append(point)
            
            # 上传到Qdrant
            client.upsert(
                collection_name=collection_name,
                points=points
            )
            
            logger.info(f"[Embedding] 成功保存 {len(points)} 个向量到Qdrant")
            
        except ImportError:
            logger.error("[Embedding] Qdrant客户端未安装")
            raise
        except Exception as e:
            logger.error(f"[Embedding] 保存到Qdrant失败: {e}")
            raise
    
    def get_embedding_stats(self, embedding_results: list[EmbeddingResult]) -> dict[str, Any]:
        """获取向量化统计信息"""
        if not embedding_results:
            return {}
        
        original_dims = [r.metadata['original_dim'] for r in embedding_results]
        reduced_dims = [r.metadata['reduced_dim'] for r in embedding_results]
        
        # 计算向量范数
        original_norms = [np.linalg.norm(r.original_embedding) for r in embedding_results]
        reduced_norms = [np.linalg.norm(r.reduced_embedding) for r in embedding_results]
        
        return {
            'total_embeddings': len(embedding_results),
            'original_dimension': {
                'min': min(original_dims),
                'max': max(original_dims),
                'avg': sum(original_dims) / len(original_dims)
            },
            'reduced_dimension': {
                'min': min(reduced_dims),
                'max': max(reduced_dims),
                'avg': sum(reduced_dims) / len(reduced_dims)
            },
            'norm_statistics': {
                'original_avg_norm': sum(original_norms) / len(original_norms),
                'reduced_avg_norm': sum(reduced_norms) / len(reduced_norms),
                'norm_preservation_ratio': sum(reduced_norms) / sum(original_norms) if sum(original_norms) > 0 else 0
            }
        }
