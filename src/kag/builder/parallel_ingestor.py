"""KAG 并行文档预处理。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from src.common import get_logger
from src.kag.builder.cache import DocumentCache
from src.kag.builder.parser import DocumentParser
from src.storage.schema import ParsedDocument

logger = get_logger(__name__)


class ParallelIngestor:
    @classmethod
    def parse_documents(
        cls,
        doc_paths: list[str],
        tenant_id: str,
        upload_batch_id: str,
        max_workers: int = 4,
    ) -> list[ParsedDocument]:
        if not doc_paths:
            return []

        results: list[ParsedDocument] = []

        def _parse(path: str) -> ParsedDocument:
            cached = DocumentCache.get(path)
            if cached:
                logger.info(f"[ParallelIngestor] 命中文档缓存: {path}")
                return cached
            parsed = DocumentParser.parse(path, tenant_id, upload_batch_id)
            DocumentCache.set(path, parsed)
            return parsed

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_parse, path): path for path in doc_paths
            }  # 期物，每个path都会给一个标识，票据，非阻塞对象
            for future in as_completed(futures):
                path = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    logger.error(f"[ParallelIngestor] 文档解析失败 {path}: {exc}")
        return results
