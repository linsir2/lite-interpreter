"""Repository for durable memory records reusable across tasks and sessions."""
from __future__ import annotations

import json
import threading
from typing import Any

from config.settings import STRICT_PERSISTENCE
from sqlalchemy import text
from src.common.logger import get_logger
from src.common.utils import get_utc_now
from src.storage.postgres_client import pg_client

logger = get_logger(__name__)


class MemoryRepo:
    """Store and retrieve durable task/workspace memories."""

    _memory_store: dict[str, dict[str, dict[tuple[str, str], dict[str, Any]]]] = {}
    _lock = threading.RLock()
    _last_error: str | None = None

    @classmethod
    def status(cls) -> dict[str, Any]:
        memory_record_count = sum(
            len(records)
            for tenant_bucket in cls._memory_store.values()
            for records in tenant_bucket.values()
        )
        return {
            "backend": "postgres" if pg_client.engine else "memory_fallback",
            "postgres_available": pg_client.engine is not None,
            "postgres_driver": getattr(pg_client, "driver_name", None),
            "postgres_driver_error": getattr(pg_client, "driver_error", None),
            "strict_persistence": bool(STRICT_PERSISTENCE),
            "memory_record_count": memory_record_count,
            "last_error": cls._last_error,
        }

    @classmethod
    def _require_backend(cls, operation: str) -> None:
        if pg_client.engine is not None:
            return
        if not STRICT_PERSISTENCE:
            return
        message = f"MemoryRepo requires Postgres for `{operation}` when STRICT_PERSISTENCE is enabled"
        cls._last_error = message
        raise RuntimeError(message)

    @classmethod
    def _handle_backend_error(cls, operation: str, exc: Exception) -> None:
        cls._last_error = str(exc)
        logger.error(f"[MemoryRepo] {operation}失败: {exc}")
        if STRICT_PERSISTENCE:
            raise RuntimeError(f"MemoryRepo {operation} failed under STRICT_PERSISTENCE: {exc}") from exc

    @classmethod
    def _ensure_table(cls) -> None:
        if not pg_client.engine:
            return
        sql = """
        CREATE TABLE IF NOT EXISTS agent_memories (
            tenant_id VARCHAR(255) NOT NULL,
            workspace_id VARCHAR(255) NOT NULL,
            memory_kind VARCHAR(128) NOT NULL,
            memory_key VARCHAR(255) NOT NULL,
            memory_payload JSONB NOT NULL,
            usage_count INTEGER DEFAULT 0,
            last_used_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            PRIMARY KEY (tenant_id, workspace_id, memory_kind, memory_key)
        );
        CREATE INDEX IF NOT EXISTS idx_agent_memories_lookup
        ON agent_memories(tenant_id, workspace_id, memory_kind, updated_at DESC);
        """
        try:
            with pg_client.engine.begin() as conn:
                conn.execute(text(sql))
        except Exception as exc:
            cls._handle_backend_error("初始化记忆表", exc)

    @classmethod
    def _set_memory_record(
        cls,
        tenant_id: str,
        workspace_id: str,
        memory_kind: str,
        memory_key: str,
        payload: dict[str, Any],
    ) -> None:
        with cls._lock:
            workspace_bucket = cls._memory_store.setdefault(tenant_id, {}).setdefault(workspace_id, {})
            workspace_bucket[(memory_kind, memory_key)] = dict(payload)

    @classmethod
    def _list_memory_records(
        cls,
        tenant_id: str,
        workspace_id: str,
        *,
        memory_kind: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with cls._lock:
            workspace_bucket = cls._memory_store.get(tenant_id, {}).get(workspace_id, {})
            items = [
                dict(payload)
                for (kind, _key), payload in workspace_bucket.items()
                if kind == memory_kind
            ]
        return items[:limit]

    @classmethod
    def _upsert_records(
        cls,
        tenant_id: str,
        workspace_id: str,
        *,
        memory_kind: str,
        records: list[tuple[str, dict[str, Any]]],
    ) -> bool:
        normalized: list[tuple[str, dict[str, Any]]] = []
        for memory_key, payload in records:
            key = str(memory_key or "").strip()
            if not key:
                continue
            payload_dict = dict(payload or {})
            normalized.append((key, payload_dict))
        if not normalized:
            return True

        cls._require_backend("upsert_records")
        if not pg_client.engine:
            for key, payload_dict in normalized:
                cls._set_memory_record(tenant_id, workspace_id, memory_kind, key, payload_dict)
            return True

        cls._ensure_table()
        sql = text(
            """
            INSERT INTO agent_memories (
                tenant_id,
                workspace_id,
                memory_kind,
                memory_key,
                memory_payload,
                usage_count,
                last_used_at,
                created_at,
                updated_at
            )
            VALUES (
                :tenant_id,
                :workspace_id,
                :memory_kind,
                :memory_key,
                :memory_payload,
                :usage_count,
                :last_used_at,
                NOW(),
                NOW()
            )
            ON CONFLICT (tenant_id, workspace_id, memory_kind, memory_key)
            DO UPDATE SET
                memory_payload = EXCLUDED.memory_payload,
                usage_count = EXCLUDED.usage_count,
                last_used_at = EXCLUDED.last_used_at,
                updated_at = NOW();
            """
        )
        payload = [
            {
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "memory_kind": memory_kind,
                "memory_key": key,
                "memory_payload": json.dumps(item, default=str, ensure_ascii=False),
                "usage_count": int(dict(item.get("usage", {}) or {}).get("usage_count", 0) or 0),
                "last_used_at": dict(item.get("usage", {}) or {}).get("last_used_at"),
            }
            for key, item in normalized
        ]
        try:
            with pg_client.engine.begin() as conn:
                conn.execute(sql, payload)
        except Exception as exc:
            cls._handle_backend_error("upsert 记忆记录", exc)
            return False
        for key, payload_dict in normalized:
            cls._set_memory_record(tenant_id, workspace_id, memory_kind, key, payload_dict)
        return True

    @classmethod
    def _load_postgres_records(
        cls,
        tenant_id: str,
        workspace_id: str,
        *,
        memory_kind: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        cls._require_backend(f"list_{memory_kind}")
        if not pg_client.engine:
            return []
        cls._ensure_table()
        sql = text(
            """
            SELECT memory_payload
            FROM agent_memories
            WHERE tenant_id = :tenant_id
              AND workspace_id = :workspace_id
              AND memory_kind = :memory_kind
            ORDER BY updated_at DESC
            LIMIT :limit
            """
        )
        try:
            with pg_client.engine.connect() as conn:
                rows = conn.execute(
                    sql,
                    {
                        "tenant_id": tenant_id,
                        "workspace_id": workspace_id,
                        "memory_kind": memory_kind,
                        "limit": limit,
                    },
                )
                items: list[dict[str, Any]] = []
                for row in rows:
                    payload = row[0]
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    if isinstance(payload, dict):
                        items.append(payload)
                return items
        except Exception as exc:
            cls._handle_backend_error(f"读取 {memory_kind}", exc)
            return []

    @classmethod
    def save_approved_skills(
        cls,
        tenant_id: str,
        workspace_id: str,
        skills: list[dict[str, Any]],
    ) -> bool:
        return cls._upsert_records(
            tenant_id,
            workspace_id,
            memory_kind="approved_skill",
            records=[
                (str(skill.get("name", "")).strip(), dict(skill))
                for skill in skills
                if str(skill.get("name", "")).strip()
            ],
        )

    @classmethod
    def list_approved_skills(
        cls,
        tenant_id: str,
        workspace_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        memory_items = cls._list_memory_records(
            tenant_id,
            workspace_id,
            memory_kind="approved_skill",
            limit=limit,
        )
        items = cls._load_postgres_records(
            tenant_id,
            workspace_id,
            memory_kind="approved_skill",
            limit=limit,
        )
        if memory_items:
            memory_by_name = {
                str(item.get("name", "")).strip(): dict(item)
                for item in memory_items
                if str(item.get("name", "")).strip()
            }
            if items:
                merged = list(items)
                seen = {
                    str(item.get("name", "")).strip()
                    for item in items
                    if str(item.get("name", "")).strip()
                }
                for name, item in memory_by_name.items():
                    if name in seen:
                        merged = [
                            dict(item) if str(existing.get("name", "")).strip() == name else existing
                            for existing in merged
                        ]
                    else:
                        merged.append(dict(item))
                return merged[:limit]
            return list(memory_by_name.values())[:limit]
        if items:
            return items[:limit]
        return []

    @classmethod
    def find_approved_skills(
        cls,
        tenant_id: str,
        workspace_id: str,
        *,
        required_capabilities: list[str] | None = None,
        source_task_type: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        skills = cls.list_approved_skills(tenant_id, workspace_id, limit=max(limit * 3, limit))
        filtered: list[dict[str, Any]] = []
        required = {str(item).strip() for item in (required_capabilities or []) if str(item).strip()}
        for skill in skills:
            skill_required = {
                str(item).strip()
                for item in (skill.get("required_capabilities") or [])
                if str(item).strip()
            }
            recommended = (skill.get("metadata") or {}).get("recommended", {}) or {}
            skill_task_type = recommended.get("source_task_type")
            if required and not skill_required.intersection(required):
                continue
            if source_task_type and skill_task_type and skill_task_type != source_task_type:
                continue
            filtered.append(skill)
        return filtered[:limit]

    @classmethod
    def save_task_summary(
        cls,
        tenant_id: str,
        workspace_id: str,
        task_id: str,
        summary: dict[str, Any],
    ) -> bool:
        return cls._upsert_records(
            tenant_id,
            workspace_id,
            memory_kind="task_summary",
            records=[(task_id, dict(summary))],
        )

    @classmethod
    def load_task_summary(
        cls,
        tenant_id: str,
        workspace_id: str,
        task_id: str,
    ) -> dict[str, Any] | None:
        items = cls._list_memory_records(
            tenant_id,
            workspace_id,
            memory_kind="task_summary",
            limit=1000,
        )
        for item in items:
            if str(item.get("task_id", "")).strip() == str(task_id).strip():
                return item
        postgres_items = cls._load_postgres_records(
            tenant_id,
            workspace_id,
            memory_kind="task_summary",
            limit=1000,
        )
        for item in postgres_items:
            if str(item.get("task_id", "")).strip() == str(task_id).strip():
                return item
        return None

    @classmethod
    def save_workspace_preferences(
        cls,
        tenant_id: str,
        workspace_id: str,
        preferences: list[dict[str, Any]],
    ) -> bool:
        return cls._upsert_records(
            tenant_id,
            workspace_id,
            memory_kind="workspace_preference",
            records=[
                (str(item.get("key", "")).strip(), dict(item))
                for item in preferences
                if str(item.get("key", "")).strip()
            ],
        )

    @classmethod
    def list_workspace_preferences(
        cls,
        tenant_id: str,
        workspace_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        items = cls._load_postgres_records(
            tenant_id,
            workspace_id,
            memory_kind="workspace_preference",
            limit=limit,
        )
        if items:
            return items[:limit]
        return cls._list_memory_records(
            tenant_id,
            workspace_id,
            memory_kind="workspace_preference",
            limit=limit,
        )

    @classmethod
    def _load_skill_usage_snapshot(
        cls,
        tenant_id: str,
        workspace_id: str,
        skill_name: str,
    ) -> tuple[dict[str, Any] | None, int]:
        existing_payload = next(
            (
                skill
                for skill in cls.list_approved_skills(tenant_id, workspace_id, limit=1000)
                if str(skill.get("name", "")).strip() == str(skill_name).strip()
            ),
            None,
        )
        usage_count = int(dict((existing_payload or {}).get("usage", {}) or {}).get("usage_count", 0) or 0)

        cls._require_backend("load_skill_usage_snapshot")
        if not pg_client.engine:
            return existing_payload, usage_count

        cls._ensure_table()
        sql = text(
            """
            SELECT memory_payload, usage_count
            FROM agent_memories
            WHERE tenant_id = :tenant_id
              AND workspace_id = :workspace_id
              AND memory_kind = 'approved_skill'
              AND memory_key = :memory_key
            LIMIT 1
            """
        )
        try:
            with pg_client.engine.connect() as conn:
                row = conn.execute(
                    sql,
                    {
                        "tenant_id": tenant_id,
                        "workspace_id": workspace_id,
                        "memory_key": skill_name,
                    },
                ).fetchone()
                if not row:
                    return existing_payload, usage_count
                payload = row[0]
                if isinstance(payload, str):
                    payload = json.loads(payload)
                db_payload = payload if isinstance(payload, dict) else existing_payload
                db_usage_count = int(row[1] or 0)
                return db_payload or existing_payload, max(usage_count, db_usage_count)
        except Exception as exc:
            cls._handle_backend_error("读取 skill usage snapshot", exc)
            return existing_payload, usage_count

    @classmethod
    def record_skill_usage(
        cls,
        tenant_id: str,
        workspace_id: str,
        skill_name: str,
        *,
        task_id: str,
        stage: str,
    ) -> dict[str, Any] | None:
        existing_payload, existing_count = cls._load_skill_usage_snapshot(
            tenant_id,
            workspace_id,
            skill_name,
        )
        existing_usage = dict((existing_payload or {}).get("usage", {}) or {})
        if (
            str(existing_usage.get("last_task_id", "")) == str(task_id)
            and str(existing_usage.get("last_stage", "")) == str(stage)
        ):
            return existing_payload

        updated_skill = dict(existing_payload or {})
        if not updated_skill:
            return None
        usage = dict(updated_skill.get("usage", {}) or {})
        usage["last_used_at"] = get_utc_now().isoformat()
        usage["usage_count"] = max(existing_count, int(usage.get("usage_count", 0) or 0)) + 1
        usage["last_task_id"] = task_id
        usage["last_stage"] = stage
        updated_skill["usage"] = usage
        if cls.save_approved_skills(tenant_id, workspace_id, [updated_skill]):
            return updated_skill
        return None

    @classmethod
    def record_skill_outcome(
        cls,
        tenant_id: str,
        workspace_id: str,
        skill_name: str,
        *,
        task_id: str,
        success: bool,
    ) -> dict[str, Any] | None:
        existing_payload = next(
            (
                skill
                for skill in cls.list_approved_skills(tenant_id, workspace_id, limit=1000)
                if str(skill.get("name", "")).strip() == str(skill_name).strip()
            ),
            None,
        )
        existing_usage = dict((existing_payload or {}).get("usage", {}) or {})
        if (
            str(existing_usage.get("last_outcome_task_id", "")) == str(task_id)
            and bool(existing_usage.get("last_outcome_success")) == bool(success)
        ):
            return existing_payload

        updated_skill = dict(existing_payload or {})
        if not updated_skill:
            return None
        usage = dict(updated_skill.get("usage", {}) or {})
        usage["success_count"] = int(usage.get("success_count", 0) or 0) + (1 if success else 0)
        usage["failure_count"] = int(usage.get("failure_count", 0) or 0) + (0 if success else 1)
        total = usage["success_count"] + usage["failure_count"]
        usage["success_rate"] = round(usage["success_count"] / total, 4) if total else 0.0
        usage["last_outcome_task_id"] = task_id
        usage["last_outcome_success"] = bool(success)
        updated_skill["usage"] = usage
        if cls.save_approved_skills(tenant_id, workspace_id, [updated_skill]):
            return updated_skill
        return None

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._memory_store.clear()
