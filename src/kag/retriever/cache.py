"""检索缓存。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Any


@dataclass
class CacheEntry:
    value: list[dict[str, Any]]
    expires_at: float


class RetrievalCache:
    _cache: dict[str, CacheEntry] = {}
    ttl_seconds: int = 300

    @classmethod
    def make_key(cls, tenant_id: str, workspace_id: str, query: str, filters: dict[str, Any]) -> str:
        raw = f"{tenant_id}:{workspace_id}:{query}:{sorted(filters.items())}".encode()
        return sha256(raw).hexdigest()

    @classmethod
    def get(cls, key: str) -> list[dict[str, Any]] | None:
        entry = cls._cache.get(key)
        if not entry:
            return None
        if entry.expires_at < time.time():
            cls._cache.pop(key, None)
            return None
        return entry.value

    @classmethod
    def set(cls, key: str, value: list[dict[str, Any]]) -> None:
        cls._cache[key] = CacheEntry(value=value, expires_at=time.time() + cls.ttl_seconds)
