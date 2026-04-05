"""Repository for approved skills reusable across tasks."""
from __future__ import annotations

import json
import threading
from typing import Any

from sqlalchemy import text

from src.common import get_utc_now

from src.common import get_logger
from src.storage.postgres_client import pg_client
from config.settings import STRICT_PERSISTENCE

logger = get_logger(__name__)


class SkillRepo:
    """Store and retrieve approved skills across tasks.

    Falls back to in-memory storage when Postgres is unavailable so the
    development/test flow still works.
    """

    _memory_store: dict[str, dict[str, list[dict[str, Any]]]] = {}
    _lock = threading.RLock()
    _last_error: str | None = None

    @classmethod
    def status(cls) -> dict[str, Any]:
        memory_skill_count = sum(len(skills) for tenant_bucket in cls._memory_store.values() for skills in tenant_bucket.values())
        return {
            "backend": "postgres" if pg_client.engine else "memory_fallback",
            "postgres_available": pg_client.engine is not None,
            "strict_persistence": bool(STRICT_PERSISTENCE),
            "memory_skill_count": memory_skill_count,
            "last_error": cls._last_error,
        }

    @classmethod
    def _require_backend(cls, operation: str) -> None:
        if pg_client.engine is not None:
            return
        if not STRICT_PERSISTENCE:
            return
        message = f"SkillRepo requires Postgres for `{operation}` when STRICT_PERSISTENCE is enabled"
        cls._last_error = message
        raise RuntimeError(message)

    @classmethod
    def _ensure_table(cls) -> None:
        if not pg_client.engine:
            return
        sql = """
        CREATE TABLE IF NOT EXISTS kag_approved_skills (
            tenant_id VARCHAR(255) NOT NULL,
            workspace_id VARCHAR(255) NOT NULL,
            skill_name VARCHAR(255) NOT NULL,
            skill_payload JSONB NOT NULL,
            promoted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            last_used_at TIMESTAMP WITH TIME ZONE,
            usage_count INTEGER DEFAULT 0,
            PRIMARY KEY (tenant_id, workspace_id, skill_name)
        );
        CREATE INDEX IF NOT EXISTS idx_approved_skills_ws
        ON kag_approved_skills(tenant_id, workspace_id, promoted_at DESC);
        """
        try:
            with pg_client.engine.begin() as conn:
                conn.execute(text(sql))
        except Exception as exc:
            cls._last_error = str(exc)
            logger.error(f"[SkillRepo] 初始化技能表失败: {exc}")

    @classmethod
    def save_approved_skills(
        cls,
        tenant_id: str,
        workspace_id: str,
        skills: list[dict[str, Any]],
    ) -> None:
        if not skills:
            return

        with cls._lock:
            tenant_bucket = cls._memory_store.setdefault(tenant_id, {})
            existing = {str(item.get("name")): item for item in tenant_bucket.get(workspace_id, []) if item.get("name")}
            for skill in skills:
                name = str(skill.get("name", "")).strip()
                if not name:
                    continue
                existing[name] = dict(skill)
            tenant_bucket[workspace_id] = list(existing.values())

        cls._require_backend("save_approved_skills")
        if not pg_client.engine:
            return

        cls._ensure_table()
        sql = text(
            """
            INSERT INTO kag_approved_skills (tenant_id, workspace_id, skill_name, skill_payload, promoted_at)
            VALUES (:tenant_id, :workspace_id, :skill_name, :skill_payload, NOW())
            ON CONFLICT (tenant_id, workspace_id, skill_name)
            DO UPDATE SET
                skill_payload = EXCLUDED.skill_payload,
                promoted_at = NOW();
            """
        )
        payload = [
            {
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "skill_name": str(skill.get("name", "")).strip(),
                "skill_payload": json.dumps(skill, default=str, ensure_ascii=False),
            }
            for skill in skills
            if str(skill.get("name", "")).strip()
        ]
        if not payload:
            return
        try:
            with pg_client.engine.begin() as conn:
                conn.execute(sql, payload)
        except Exception as exc:
            cls._last_error = str(exc)
            logger.error(f"[SkillRepo] 保存 approved skills 失败: {exc}")

    @classmethod
    def list_approved_skills(
        cls,
        tenant_id: str,
        workspace_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        with cls._lock:
            memory_items = list(cls._memory_store.get(tenant_id, {}).get(workspace_id, []))

        cls._require_backend("list_approved_skills")
        if not pg_client.engine:
            return memory_items[:limit]

        cls._ensure_table()
        sql = text(
            """
            SELECT skill_payload
            FROM kag_approved_skills
            WHERE tenant_id = :tenant_id
              AND workspace_id = :workspace_id
            ORDER BY promoted_at DESC
            LIMIT :limit
            """
        )
        try:
            with pg_client.engine.connect() as conn:
                rows = conn.execute(
                    sql,
                    {"tenant_id": tenant_id, "workspace_id": workspace_id, "limit": limit},
                )
                items: list[dict[str, Any]] = []
                for row in rows:
                    payload = row[0]
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    if isinstance(payload, dict):
                        items.append(payload)
                return items or memory_items[:limit]
        except Exception as exc:
            cls._last_error = str(exc)
            logger.error(f"[SkillRepo] 读取 approved skills 失败: {exc}")
            return memory_items[:limit]

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
        required = set(str(item).strip() for item in (required_capabilities or []) if str(item).strip())
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
    def clear(cls) -> None:
        with cls._lock:
            cls._memory_store.clear()

    @classmethod
    def record_skill_usage(
        cls,
        tenant_id: str,
        workspace_id: str,
        skill_name: str,
        *,
        task_id: str,
        stage: str,
    ) -> None:
        with cls._lock:
            tenant_bucket = cls._memory_store.setdefault(tenant_id, {})
            items = tenant_bucket.get(workspace_id, [])
            for item in items:
                if str(item.get("name", "")).strip() != str(skill_name).strip():
                    continue
                usage = dict(item.get("usage", {}) or {})
                usage["last_used_at"] = get_utc_now().isoformat()
                usage["usage_count"] = int(usage.get("usage_count", 0) or 0) + 1
                usage["last_task_id"] = task_id
                usage["last_stage"] = stage
                item["usage"] = usage
                break

        if not pg_client.engine:
            return

        cls._ensure_table()
        sql = text(
            """
            UPDATE kag_approved_skills
            SET last_used_at = NOW(),
                usage_count = COALESCE(usage_count, 0) + 1
            WHERE tenant_id = :tenant_id
              AND workspace_id = :workspace_id
              AND skill_name = :skill_name
            """
        )
        try:
            with pg_client.engine.begin() as conn:
                conn.execute(
                    sql,
                    {
                        "tenant_id": tenant_id,
                        "workspace_id": workspace_id,
                        "skill_name": skill_name,
                    },
                )
        except Exception as exc:
            cls._last_error = str(exc)
            logger.error(f"[SkillRepo] 记录 skill usage 失败: {exc}")

    @classmethod
    def record_skill_outcome(
        cls,
        tenant_id: str,
        workspace_id: str,
        skill_name: str,
        *,
        task_id: str,
        success: bool,
    ) -> None:
        updated_skill: dict[str, Any] | None = None
        with cls._lock:
            tenant_bucket = cls._memory_store.setdefault(tenant_id, {})
            items = tenant_bucket.get(workspace_id, [])
            for item in items:
                if str(item.get("name", "")).strip() != str(skill_name).strip():
                    continue
                usage = dict(item.get("usage", {}) or {})
                usage["success_count"] = int(usage.get("success_count", 0) or 0) + (1 if success else 0)
                usage["failure_count"] = int(usage.get("failure_count", 0) or 0) + (0 if success else 1)
                total = usage["success_count"] + usage["failure_count"]
                usage["success_rate"] = round(usage["success_count"] / total, 4) if total else 0.0
                usage["last_outcome_task_id"] = task_id
                usage["last_outcome_success"] = bool(success)
                item["usage"] = usage
                updated_skill = dict(item)
                break

        if not pg_client.engine or not updated_skill:
            return

        try:
            cls.save_approved_skills(tenant_id, workspace_id, [updated_skill])
        except Exception as exc:
            cls._last_error = str(exc)
            logger.error(f"[SkillRepo] 记录 skill outcome 失败: {exc}")
