"""
src/kag/builder/classifier.py
文档复杂度分类器 (The Gatekeeper)

职责：通过极低成本的预读取和 Token 估算，将非结构化文档分流至最合适的解析通道。
拒绝处理 Structured (CSV/Excel) 数据，因为 DAG Router 已经将其引流至 Inspector。
"""
import os
from enum import Enum
from typing import Optional
from src.common import get_logger, estimate_tokens
from config.settings import CLASSIFIER_SMALL_THRESHOLD, CLASSIFIER_MEDIUM_THRESHOLD

logger = get_logger(__name__)

class DocProcessClass(str, Enum):
    SMALL = "small"       # 单chunk, 直接向量化
    MEDIUM = "medium"     # 分块 + 向量化
    LARGE = "large"       # 分块 + 向量化 + 图谱抽取
    UNKNOWN = "unknown"   # 无法识别或被拒绝的格式

class DocumentClassifier:
    @classmethod
    def classify(cls, file_path: str) -> DocProcessClass:
        if not os.path.exists(file_path):
            logger.error(f"[Classifier] 文件不存在，拒绝分类: {file_path}")
            return DocProcessClass.UNKNOWN
        
        ext = os.path.splitext(file_path)[-1].lower()

        if ext in [".csv", ".xlsx", ".xls", ".parquet"]:
            logger.error(f"[Classifier] 架构违规：KAG 引擎拒绝处理结构化表单 {file_path}。请检查 Router 节点。")
            return DocProcessClass.UNKNOWN
        
        # 分类
        try:
            token_count = cls._fast_estimate_tokens(file_path, ext)
            logger.info(f"[Classifier] 文件 {os.path.basename(file_path)} 预估 Token 数量: {token_count}")

            if token_count <= CLASSIFIER_SMALL_THRESHOLD:
                return DocProcessClass.SMALL
            elif token_count <= CLASSIFIER_MEDIUM_THRESHOLD:
                return DocProcessClass.MEDIUM
            else:
                return DocProcessClass.LARGE
            
        except Exception as e:
            logger.warning(f"[Classifier] Token 估算失败 ({e})，降级至基于文件物理大小判断。")
            return cls._fallback_size_classify(file_path)
    
    @classmethod
    def _fast_estimate_tokens(cls, file_path: str, ext: str) -> int:
        if ext in ['.txt', '.md']:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            return estimate_tokens(content)
        
        elif ext == '.pdf':
            import fitz
            try:
                doc = fitz.open(file_path)
                sample_pages = min(3, doc.page_count)
                if sample_pages == 0:
                    return 0
                
                text = "".join([str(doc[i].get_text()) for i in range(sample_pages)])
                avg_tokens_per_page = estimate_tokens(text) / sample_pages
                return int(avg_tokens_per_page * doc.page_count)
            except Exception as pdf_err:
                logger.error(f"PDF 抽样读取失败: {pdf_err}")
                raise pdf_err
        
        # 其他格式（如 Word）暂时给个安全默认值触发降级
        raise ValueError(f"暂不支持极速估算的扩展名: {ext}")
    
    @classmethod
    def _fallback_size_classify(cls, file_path: str) -> DocProcessClass:
        """灾备方案：当无法读取文本时，靠物理大小粗略兜底"""
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if size_mb < 0.5:
            return DocProcessClass.SMALL
        elif size_mb < 5.0:
            return DocProcessClass.MEDIUM
        return DocProcessClass.LARGE