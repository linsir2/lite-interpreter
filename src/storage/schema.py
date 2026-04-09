"""
src/storage/schema.py
存储层统一数据结构定义 (Data Access Object Schema)

职责：规定上层业务实体必须转化为以下标准结构，才能交由 Storage 层入库。
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from src.common.utils import get_utc_now


# 文本块存储模型，存入postgres，vectordb只存向量与metadata，专门负责检索，postgres负责存储文本
class DocChunk(BaseModel):
    chunk_id: str = Field(description="Chunk 的全局唯一 ID")
    doc_id: str = Field(description="所属物理文档的唯一ID")
    content: str = Field(description="纯文本切片内容")

    created_at: datetime = Field(default_factory=get_utc_now, description="入库时间戳")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="必须包含: file_name, upload_batch_id, author 等用于后续 Filter 过滤的溯源信息",
    )

    # ==========================================
    # 🔌 框架适配器 (Adapters)
    # ==========================================
    def to_llama_index_node(self) -> Any:
        """转化为 LlamaIndex 兼容的 TextNode。"""
        from llama_index.core.schema import TextNode

        return TextNode(
            id_=self.chunk_id,
            text=self.content,
            metadata={"doc_id": self.doc_id, "created_at": str(self.created_at), **self.metadata},
        )

    @classmethod
    def from_llama_index_node(cls, node: Any, doc_id: str) -> "DocChunk":
        """从 LlamaIndex 的 TextNode 解析回内部的 DocChunk。"""
        return cls(
            chunk_id=getattr(node, "id_", ""),
            doc_id=doc_id,
            content=getattr(node, "text", ""),
            metadata=getattr(node, "metadata", {}) or {},
        )


class EntityNode(BaseModel):
    """图谱实体节点模型"""

    id: str = Field(description="实体的业务主键")
    label: str = Field(description="实体类型/标签")
    properties: dict[str, Any] = Field(default_factory=dict)  # chunk_id啥的都在这里面
    created_at: datetime = Field(default_factory=get_utc_now)


class KnowledgeTriple(BaseModel):
    """知识三元组模型"""

    head: str
    head_label: str
    relation: str
    tail: str
    tail_label: str
    properties: dict[str, Any] = Field(default_factory=dict, description="边的属性")
    # 🚀 【你的优化1】：图谱边也必须有时间戳，支持图谱的时间旅行查询（Temporal Graph）
    created_at: datetime = Field(default_factory=get_utc_now)


class StructuredDatasetMeta(BaseModel):
    """🚀 结构化数据表元数据（供大模型分析时查阅）"""

    tenant_id: str
    original_file_name: str = Field(description="用户上传的原始文件名 (如 sales.csv)")
    db_table_name: str = Field(description="在数据库中实际映射的表名 (如 tenant_1_sales_20260327)")
    is_persisted: bool = Field(default=False, description="用户是否授权将其永久存入数据库")
    expires_at: datetime | None = Field(description="如果是临时数据，24小时后清理")
    columns: list[str] = Field(description="表头字段名列表")
    created_at: datetime = Field(default_factory=get_utc_now)

    semantic_summary: str = Field(
        description="LLM自动生成的摘要（例：记录了2023年Q3上海厂区的所有发电机检修与故障数据）"
    )
    time_coverage: str = Field(description="数据涵盖的时间范围（例：2023-07 至 2023-09）")
    keywords: list[str] = Field(description="核心实体词（例：['发电机', '上海', 'Q3', '检修']）")


class ParsedSection(BaseModel):
    """结构化文档章节。"""

    id: str
    title: str = ""
    content: str = ""
    level: int = 1
    start_page: int | None = None
    end_page: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParsedTable(BaseModel):
    """解析后的表格。"""

    id: str
    title: str = ""
    data: list[list[str]] = Field(default_factory=list)
    rows: int = 0
    columns: int = 0
    page: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParsedImage(BaseModel):
    """解析后的图片元信息。"""

    id: str
    caption: str = ""
    description: str = ""
    page: int | None = None
    position: dict[str, Any] = Field(default_factory=dict)
    size: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParsedDocument(BaseModel):
    """Docling/fallback 解析后的统一文档结构。"""

    doc_id: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    sections: list[ParsedSection] = Field(default_factory=list)
    tables: list[ParsedTable] = Field(default_factory=list)
    images: list[ParsedImage] = Field(default_factory=list)
    parser_diagnostics: dict[str, Any] = Field(default_factory=dict)

    def build_knowledge_data(self, tenant_id: str, workspace_id: str = "default_ws") -> dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "file_id": self.doc_id,
            "file_meta": dict(self.metadata),
            "parsed_doc_ref": self.doc_id,
            "parser_name": self.metadata.get("parser"),
            "parser_diagnostics": dict(self.parser_diagnostics),
            "content_stats": {
                "sections": len(self.sections),
                "tables": len(self.tables),
                "images": len(self.images),
                "content_chars": len(self.content),
            },
        }
