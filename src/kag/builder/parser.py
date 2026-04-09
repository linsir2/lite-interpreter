"""
src/kag/builder/parser.py
文档解析器 (Document Parser)

职责：集成 Docling，支持 PDF/Word/TXT/MD 等格式解析，输出统一的 ParsedDocument。
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from src.common import generate_uuid, get_logger, get_utc_now
from src.harness.policy import load_harness_policy
from src.storage.schema import DocChunk, ParsedDocument, ParsedImage, ParsedSection, ParsedTable

logger = get_logger(__name__)


@dataclass(frozen=True)
class PdfParseProfile:
    """Policy + heuristic decision for PDF parsing."""

    mode: str
    use_ocr: bool
    use_picture_description: bool
    generate_picture_images: bool
    diagnostics: dict[str, Any]


class DocumentParser:
    """文档解析器"""

    DOC_TITLE_LEVEL = 0
    DEFAULT_SECTION_LEVEL = 1

    @classmethod
    def parse(cls, file_path: str, tenant_id: str, upload_batch_id: str) -> ParsedDocument:
        if not os.path.exists(file_path):
            logger.error(f"[Parser] 文件不存在: {file_path}")
            raise FileNotFoundError(f"文件不存在: {file_path}")

        ext = os.path.splitext(file_path)[-1].lower()
        logger.info(f"[Parser] 开始解析文档: {file_path} (格式: {ext})")

        try:
            return cls._parse_with_docling(file_path, tenant_id, upload_batch_id)
        except ImportError:
            logger.warning("[Parser] Docling 库未安装，使用纯文本解析")
            return cls._parse_as_text(file_path, tenant_id, upload_batch_id)
        except Exception as e:
            logger.error(f"[Parser] Docling 解析失败: {e}, 降级为纯文本解析")
            return cls._parse_as_text(file_path, tenant_id, upload_batch_id, error=str(e))

    @classmethod
    def _build_metadata(cls, file_path: str, tenant_id: str, upload_batch_id: str, parser: str) -> dict[str, Any]:
        return {
            "file_name": os.path.basename(file_path),
            "file_path": file_path,
            "file_size": os.path.getsize(file_path),
            "file_extension": os.path.splitext(file_path)[-1].lower(),
            "tenant_id": tenant_id,
            "upload_batch_id": upload_batch_id,
            "parsed_at": get_utc_now().isoformat(),
            "parser": parser,
        }

    @classmethod
    def _pdf_policy(cls) -> dict[str, Any]:
        policy = load_harness_policy()
        return ((policy.get("docling") or {}).get("pdf")) or {}

    @classmethod
    def infer_pdf_parse_profile(cls, file_path: str) -> PdfParseProfile:
        """Infer whether a PDF should use OCR / picture-description handling."""
        policy = cls._pdf_policy()
        threshold_chars = int(policy.get("scanned_text_chars_per_page_threshold", 120))
        threshold_images = int(policy.get("scanned_image_count_threshold", 1))
        enable_ocr = bool(policy.get("enable_ocr_for_scanned", True))
        enable_picture_description = bool(policy.get("enable_picture_description", False))
        enable_picture_description_for_image_heavy = bool(
            policy.get("enable_picture_description_for_image_heavy", True)
        )
        image_heavy_threshold = int(policy.get("image_heavy_count_threshold", 3))
        generate_picture_images = bool(policy.get("generate_picture_images", False))

        diagnostics: dict[str, Any] = {
            "sampled_pages": 0,
            "sample_chars": 0,
            "avg_chars_per_page": 0.0,
            "image_count": 0,
            "threshold_chars": threshold_chars,
            "threshold_images": threshold_images,
            "image_heavy_threshold": image_heavy_threshold,
        }
        scanned_like = False
        image_heavy = False

        try:
            import fitz

            doc = fitz.open(file_path)
            sample_pages = min(3, doc.page_count)
            diagnostics["sampled_pages"] = sample_pages
            chars = 0
            images = 0
            for page_index in range(sample_pages):
                page = doc[page_index]
                text = page.get_text() or ""
                chars += len(text.strip())
                images += len(page.get_images(full=True))
            diagnostics["sample_chars"] = chars
            diagnostics["image_count"] = images
            diagnostics["avg_chars_per_page"] = round(chars / sample_pages, 2) if sample_pages else 0.0
            scanned_like = (
                sample_pages > 0 and diagnostics["avg_chars_per_page"] <= threshold_chars and images >= threshold_images
            )
            image_heavy = images >= image_heavy_threshold
        except Exception as exc:
            diagnostics["heuristic_error"] = str(exc)

        use_ocr = scanned_like and enable_ocr
        use_picture_description = bool(
            enable_picture_description and (use_ocr or (enable_picture_description_for_image_heavy and image_heavy))
        )
        if use_ocr and use_picture_description:
            mode = "ocr+vision"
        elif use_ocr:
            mode = "ocr"
        elif use_picture_description:
            mode = "vision"
        else:
            mode = "text"
        return PdfParseProfile(
            mode=mode,
            use_ocr=use_ocr,
            use_picture_description=use_picture_description,
            generate_picture_images=use_picture_description and generate_picture_images,
            diagnostics={
                **diagnostics,
                "scanned_like": scanned_like,
                "image_heavy": image_heavy,
            },
        )

    @classmethod
    def _build_docling_converter(cls, file_path: str) -> tuple[Any, dict[str, Any]]:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        ext = os.path.splitext(file_path)[-1].lower()
        if ext != ".pdf":
            return DocumentConverter(), {"parse_mode": "default"}

        profile = cls.infer_pdf_parse_profile(file_path)
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = profile.use_ocr
        pipeline_options.do_picture_description = profile.use_picture_description
        pipeline_options.generate_picture_images = profile.generate_picture_images
        pipeline_options.enable_remote_services = profile.use_picture_description

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
            }
        )
        return converter, {
            "parse_mode": profile.mode,
            "pdf_profile": profile.diagnostics,
            "ocr_enabled": profile.use_ocr,
            "picture_description_enabled": profile.use_picture_description,
        }

    @classmethod
    def _parse_with_docling(cls, file_path: str, tenant_id: str, upload_batch_id: str) -> ParsedDocument:
        converter, parser_profile = cls._build_docling_converter(file_path)
        result = converter.convert(file_path)
        document = getattr(result, "document", None)
        if document is None:
            raise ValueError("Docling convert 结果不包含 document")

        content = getattr(document, "text", "") or cls._join_text_items(getattr(document, "texts", []))
        sections = cls._extract_sections(document)
        tables = cls._extract_tables(getattr(document, "tables", []), document=document)
        images = cls._extract_images(getattr(document, "pictures", []), document=document)
        content = cls._augment_content_with_image_descriptions(content, images)
        metadata = cls._build_metadata(file_path, tenant_id, upload_batch_id, parser="docling")
        metadata.update(cls._extract_metadata(getattr(result, "metadata", None)))
        metadata["parse_mode"] = parser_profile.get("parse_mode", "default")

        return ParsedDocument(
            doc_id=generate_uuid(),
            content=content,
            metadata=metadata,
            sections=sections,
            tables=tables,
            images=images,
            parser_diagnostics={
                "parser": "docling",
                "section_count": len(sections),
                "table_count": len(tables),
                "image_count": len(images),
                "image_description_count": len([image for image in images if image.description]),
                "has_structured_texts": bool(getattr(document, "texts", [])),
                **parser_profile,
            },
        )

    @classmethod
    def _parse_as_text(
        cls,
        file_path: str,
        tenant_id: str,
        upload_batch_id: str,
        error: str | None = None,
    ) -> ParsedDocument:
        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            with open(file_path, "rb") as f:
                content = f.read().decode("utf-8", errors="ignore")

        return ParsedDocument(
            doc_id=generate_uuid(),
            content=content,
            metadata={
                **cls._build_metadata(file_path, tenant_id, upload_batch_id, parser="fallback_text"),
                "title": os.path.basename(file_path),
                "format": "plain_text",
            },
            sections=[
                ParsedSection(
                    id=generate_uuid(),
                    title="全文",
                    content=content,
                    level=1,
                )
            ],
            tables=[],
            images=[],
            parser_diagnostics={
                "parser": "fallback_text",
                "fallback_reason": error or "docling_unavailable",
            },
        )

    @classmethod
    def _extract_metadata(cls, metadata: Any) -> dict[str, Any]:
        if not metadata:
            return {}
        result: dict[str, Any] = {}
        try:
            metadata_dict = vars(metadata)
        except TypeError:
            metadata_dict = {}
        for key, value in metadata_dict.items():
            if key.startswith("_") or value in (None, ""):
                continue
            if key in {
                "title",
                "author",
                "subject",
                "keywords",
                "creator",
                "producer",
                "creation_date",
                "modification_date",
            }:
                result[key] = str(value)
        return result

    @classmethod
    def _join_text_items(cls, items: Iterable[Any]) -> str:
        fragments = [str(getattr(item, "text", "")).strip() for item in items]
        return "\n".join(fragment for fragment in fragments if fragment)

    @classmethod
    def _page_range(cls, item: Any) -> tuple[int | None, int | None]:
        prov = getattr(item, "prov", None) or []
        page_numbers = []
        for record in prov:
            page_no = getattr(record, "page_no", None)
            if page_no is not None:
                page_numbers.append(int(page_no))
        if not page_numbers:
            return None, None
        return min(page_numbers), max(page_numbers)

    @classmethod
    def _extract_sections(cls, document: Any) -> list[ParsedSection]:
        text_items = list(getattr(document, "texts", []) or [])
        if not text_items:
            return []

        sections: list[ParsedSection] = []
        current_title = "导入内容"
        current_level = cls.DEFAULT_SECTION_LEVEL
        current_metadata = {
            "section_kind": "synthetic_root",
            "source_label": "",
            "level_source": "parser_default",
        }
        current_chunks: list[str] = []
        start_page: int | None = None
        end_page: int | None = None

        def flush_section() -> None:
            nonlocal current_chunks, start_page, end_page
            content = "\n".join(chunk for chunk in current_chunks if chunk).strip()
            if not content:
                current_chunks = []
                start_page = None
                end_page = None
                return
            sections.append(
                ParsedSection(
                    id=generate_uuid(),
                    title=current_title,
                    content=content,
                    level=current_level,
                    start_page=start_page,
                    end_page=end_page,
                    metadata=dict(current_metadata),
                )
            )
            current_chunks = []
            start_page = None
            end_page = None

        for item in text_items:
            label = cls._item_label(item)
            text = str(getattr(item, "text", "")).strip()
            if not text:
                continue
            item_start, item_end = cls._page_range(item)
            if label in {"title", "section_header"}:
                flush_section()
                current_title = text
                current_level, current_metadata = cls._resolve_section_header(item, label)
                start_page = item_start
                end_page = item_end
                continue
            current_chunks.append(text)
            if item_start is not None:
                start_page = item_start if start_page is None else min(start_page, item_start)
            if item_end is not None:
                end_page = item_end if end_page is None else max(end_page, item_end)

        flush_section()
        if sections:
            return sections

        fallback_content = getattr(document, "text", "") or cls._join_text_items(text_items)
        if not fallback_content:
            return []
        return [
            ParsedSection(
                id=generate_uuid(),
                title="全文",
                content=fallback_content,
                level=cls.DEFAULT_SECTION_LEVEL,
                metadata={
                    "section_kind": "fallback_fulltext",
                    "source_label": "",
                    "level_source": "fallback_default",
                },
            )
        ]

    @classmethod
    def _extract_tables(cls, tables: Iterable[Any], document: Any | None = None) -> list[ParsedTable]:
        result: list[ParsedTable] = []
        for i, table in enumerate(tables):
            try:
                page_start, _ = cls._page_range(table)
                table_data = getattr(table, "data", None)
                result.append(
                    ParsedTable(
                        id=generate_uuid(),
                        title=cls._extract_floating_title(table, document, f"表格{i + 1}"),
                        data=cls._table_to_dict(table),
                        rows=int(getattr(table, "row_count", 0) or getattr(table_data, "num_rows", 0) or 0),
                        columns=int(getattr(table, "column_count", 0) or getattr(table_data, "num_cols", 0) or 0),
                        page=page_start,
                    )
                )
            except Exception as e:
                logger.warning(f"[Parser] 提取表格失败: {e}")
        return result

    @classmethod
    def _table_to_dict(cls, table: Any) -> list[list[str]]:
        try:
            if hasattr(table, "export_to_dataframe"):
                df = table.export_to_dataframe()
                return [[str(cell) for cell in row] for row in df.values.tolist()]
            if hasattr(table, "to_pandas"):
                df = table.to_pandas()
                return [[str(cell) for cell in row] for row in df.values.tolist()]
            if hasattr(table, "data"):
                return [[str(cell) for cell in row] for row in table.data]
        except Exception:
            return []
        return []

    @classmethod
    def _extract_images(cls, images: Iterable[Any], document: Any | None = None) -> list[ParsedImage]:
        result: list[ParsedImage] = []
        for i, image in enumerate(images):
            try:
                page_start, _ = cls._page_range(image)
                description = cls._extract_picture_description(image)
                result.append(
                    ParsedImage(
                        id=generate_uuid(),
                        caption=cls._extract_floating_title(image, document, f"图片{i + 1}"),
                        description=description,
                        page=page_start,
                        position=cls._extract_picture_position(image),
                        size=cls._extract_picture_size(image),
                        metadata={
                            "has_description": bool(description),
                            "caption_source": "docling_caption_refs"
                            if document is not None
                            else "direct_attr_fallback",
                            "annotation_count": len(getattr(image, "annotations", []) or []),
                        },
                    )
                )
            except Exception as e:
                logger.warning(f"[Parser] 提取图片失败: {e}")
        return result

    @classmethod
    def _item_label(cls, item: Any) -> str:
        return str(getattr(getattr(item, "label", None), "value", getattr(item, "label", ""))).strip().lower()

    @classmethod
    def _resolve_section_header(cls, item: Any, label: str) -> tuple[int, dict[str, Any]]:
        if label == "title":
            return cls.DOC_TITLE_LEVEL, {
                "section_kind": "document_title",
                "source_label": label,
                "level_source": "docling_title",
            }

        raw_level = getattr(item, "level", cls.DEFAULT_SECTION_LEVEL)
        try:
            level = max(int(raw_level or cls.DEFAULT_SECTION_LEVEL), cls.DEFAULT_SECTION_LEVEL)
        except (TypeError, ValueError):
            level = cls.DEFAULT_SECTION_LEVEL
        return level, {
            "section_kind": "section_header",
            "source_label": label,
            "level_source": "docling_section_header",
            "docling_level": raw_level,
        }

    @classmethod
    def _extract_floating_title(cls, item: Any, document: Any | None, fallback: str) -> str:
        caption_text = getattr(item, "caption_text", None)
        if callable(caption_text) and document is not None:
            try:
                resolved = str(caption_text(document) or "").strip()
            except Exception:
                resolved = ""
            if resolved:
                return resolved

        direct_title = str(getattr(item, "title", "") or "").strip()
        if direct_title:
            return direct_title

        direct_caption = str(getattr(item, "caption", "") or "").strip()
        if direct_caption:
            return direct_caption

        return fallback

    @classmethod
    def _extract_picture_description(cls, image: Any) -> str:
        meta_description = getattr(getattr(image, "meta", None), "description", None)
        meta_text = str(getattr(meta_description, "text", "") or "").strip()
        if meta_text:
            return meta_text

        annotations = getattr(image, "annotations", []) or []
        for annotation in annotations:
            kind = str(getattr(annotation, "kind", ""))
            if kind == "description":
                text = str(getattr(annotation, "text", "")).strip()
                if text:
                    return text
        return ""

    @classmethod
    def _extract_picture_position(cls, image: Any) -> dict[str, Any]:
        prov = getattr(image, "prov", None) or []
        if prov:
            bbox = getattr(prov[0], "bbox", None)
            bbox_dump = cls._model_dump_dict(bbox)
            if bbox_dump:
                return bbox_dump
        return cls._model_dump_dict(getattr(image, "position", None))

    @classmethod
    def _extract_picture_size(cls, image: Any) -> dict[str, Any]:
        image_ref = getattr(image, "image", None)
        image_size = cls._model_dump_dict(getattr(image_ref, "size", None))
        if image_size:
            return image_size
        return cls._model_dump_dict(getattr(image, "size", None))

    @classmethod
    def _model_dump_dict(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return dict(value)
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump()
            if isinstance(dumped, dict):
                return dumped
        return {}

    @classmethod
    def _augment_content_with_image_descriptions(cls, content: str, images: list[ParsedImage]) -> str:
        descriptions = [f"- {image.caption or '图片'}: {image.description}" for image in images if image.description]
        if not descriptions:
            return content
        multimodal_block = "图片说明:\n" + "\n".join(descriptions)
        return f"{content}\n\n{multimodal_block}".strip()

    @classmethod
    def create_doc_chunk(cls, doc_id: str, content: str, metadata: dict[str, Any]) -> DocChunk:
        return DocChunk(
            chunk_id=generate_uuid(),
            doc_id=doc_id,
            content=content,
            metadata=metadata,
        )
