"""KAG 文档构建缓存。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from hashlib import sha256
from typing import Dict, Optional

from src.storage.schema import ParsedDocument


@dataclass
class CachedDocument:
    cache_key: str
    parsed_doc: ParsedDocument


class DocumentCache:
    """基于文件指纹的轻量内存缓存，避免同一轮 DAG 中重复解析同一文档。"""

    _cache: Dict[str, CachedDocument] = {}

    @classmethod
    def build_key(cls, file_path: str) -> str:
        stat = os.stat(file_path)
        raw = f"{file_path}:{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8")
        return sha256(raw).hexdigest()

    @classmethod
    def get(cls, file_path: str) -> Optional[ParsedDocument]:
        key = cls.build_key(file_path)
        cached = cls._cache.get(key)
        return cached.parsed_doc if cached else None

    @classmethod
    def set(cls, file_path: str, parsed_doc: ParsedDocument) -> None:
        key = cls.build_key(file_path)
        cls._cache[key] = CachedDocument(cache_key=key, parsed_doc=parsed_doc)

    @classmethod
    def clear(cls) -> None:
        cls._cache.clear()
