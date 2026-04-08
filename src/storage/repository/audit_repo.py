"""Repository for durable API audit records."""
from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Any

from config.settings import STRICT_PERSISTENCE
from sqlalchemy import text

from src.common.contracts import AuditRecord
from src.common.logger import get_logger
from src.storage.postgres_client import pg_client

logger = get_logger(__name__)


class AuditRepo:
    _memory_store: dict[str, dict[str, list[dict[str, Any]]]] = {}
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
    def clear(cls) -> None:
        with cls._lock:
            cls._memory_store.clear()

    @classmethod
    def _require_backend(cls, operation: str) -> None:
        if pg_client.engine is not None:
            return
        if not STRICT_PERSISTENCE:
            return
        message = f"AuditRepo requires Postgres for `{operation}` when STRICT_PERSISTENCE is enabled"
        cls._last_error = message
        raise RuntimeError(message)

    @classmethod
    def _handle_backend_error(cls, operation: str, exc: Exception) -> None:
        cls._last_error = str(exc)
        logger.error(f"[AuditRepo] {operation}失败: {exc}")
        if STRICT_PERSISTENCE:
            raise RuntimeError(f"AuditRepo {operation} failed under STRICT_PERSISTENCE: {exc}") from exc

    @classmethod
    def _ensure_table(cls) -> None:
        if not pg_client.engine:
            return
        sql = """
        CREATE TABLE IF NOT EXISTS api_audit_logs (
            audit_id VARCHAR(255) PRIMARY KEY,
            tenant_id VARCHAR(255) NOT NULL,
            workspace_id VARCHAR(255) NOT NULL,
            subject VARCHAR(255) NOT NULL,
            role VARCHAR(64) NOT NULL,
            action VARCHAR(255) NOT NULL,
            outcome VARCHAR(32) NOT NULL,
            resource_type VARCHAR(128) NOT NULL,
            resource_id VARCHAR(255),
            task_id VARCHAR(255),
            execution_id VARCHAR(255),
            request_method VARCHAR(16) NOT NULL,
            request_path TEXT NOT NULL,
            trace_id VARCHAR(255),
            metadata JSONB NOT NULL,
            recorded_at TIMESTAMP WITH TIME ZONE NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_api_audit_scope
        ON api_audit_logs(tenant_id, workspace_id, recorded_at DESC);
        CREATE INDEX IF NOT EXISTS idx_api_audit_action
        ON api_audit_logs(action, recorded_at DESC);
        """
        try:
            with pg_client.engine.begin() as conn:
                conn.execute(text(sql))
        except Exception as exc:
            cls._handle_backend_error("初始化审计表", exc)

    @classmethod
    def append_record(cls, record: AuditRecord) -> bool:
        payload = record.model_dump(mode="json")
        with cls._lock:
            workspace_bucket = cls._memory_store.setdefault(record.tenant_id, {}).setdefault(record.workspace_id, [])
            workspace_bucket.append(dict(payload))

        cls._require_backend("append_record")
        if not pg_client.engine:
            return True

        cls._ensure_table()
        sql = text(
            """
            INSERT INTO api_audit_logs (
                audit_id,
                tenant_id,
                workspace_id,
                subject,
                role,
                action,
                outcome,
                resource_type,
                resource_id,
                task_id,
                execution_id,
                request_method,
                request_path,
                trace_id,
                metadata,
                recorded_at
            )
            VALUES (
                :audit_id,
                :tenant_id,
                :workspace_id,
                :subject,
                :role,
                :action,
                :outcome,
                :resource_type,
                :resource_id,
                :task_id,
                :execution_id,
                :request_method,
                :request_path,
                :trace_id,
                :metadata,
                :recorded_at
            )
            """
        )
        try:
            with pg_client.engine.begin() as conn:
                conn.execute(
                    sql,
                    {
                        **payload,
                        "metadata": json.dumps(payload.get("metadata", {}), ensure_ascii=False, default=str),
                    },
                )
            return True
        except Exception as exc:
            cls._handle_backend_error("写入审计记录", exc)
            return False

    @classmethod
    def list_records(
        cls,
        tenant_id: str,
        workspace_id: str,
        *,
        subject: str | None = None,
        role: str | None = None,
        action: str | None = None,
        outcome: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        task_id: str | None = None,
        execution_id: str | None = None,
        recorded_after: str | None = None,
        recorded_before: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        normalized_subject = str(subject or "").strip()
        normalized_role = str(role or "").strip()
        normalized_action = str(action or "").strip()
        normalized_outcome = str(outcome or "").strip()
        normalized_resource_type = str(resource_type or "").strip()
        normalized_resource_id = str(resource_id or "").strip()
        normalized_task_id = str(task_id or "").strip()
        normalized_execution_id = str(execution_id or "").strip()
        recorded_after_dt = datetime.fromisoformat(recorded_after) if recorded_after else None
        recorded_before_dt = datetime.fromisoformat(recorded_before) if recorded_before else None
        with cls._lock:
            memory_records = list(cls._memory_store.get(tenant_id, {}).get(workspace_id, []))

        def _matches(record: dict[str, Any]) -> bool:
            if normalized_subject and str(record.get("subject") or "") != normalized_subject:
                return False
            if normalized_role and str(record.get("role") or "") != normalized_role:
                return False
            if normalized_action and str(record.get("action") or "") != normalized_action:
                return False
            if normalized_outcome and str(record.get("outcome") or "") != normalized_outcome:
                return False
            if normalized_resource_type and str(record.get("resource_type") or "") != normalized_resource_type:
                return False
            if normalized_resource_id and str(record.get("resource_id") or "") != normalized_resource_id:
                return False
            if normalized_task_id and str(record.get("task_id") or "") != normalized_task_id:
                return False
            if normalized_execution_id and str(record.get("execution_id") or "") != normalized_execution_id:
                return False
            recorded_at = str(record.get("recorded_at") or "").strip()
            if recorded_at:
                recorded_at_dt = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
                if recorded_after_dt and recorded_at_dt < recorded_after_dt:
                    return False
                if recorded_before_dt and recorded_at_dt > recorded_before_dt:
                    return False
            return True

        filtered_memory = [record for record in reversed(memory_records) if _matches(record)]

        cls._require_backend("list_records")
        if not pg_client.engine:
            return filtered_memory[:limit]

        cls._ensure_table()
        sql = """
            SELECT audit_id, tenant_id, workspace_id, subject, role, action, outcome,
                   resource_type, resource_id, task_id, execution_id, request_method,
                   request_path, trace_id, metadata, recorded_at
            FROM api_audit_logs
            WHERE tenant_id = :tenant_id
              AND workspace_id = :workspace_id
        """
        params: dict[str, Any] = {
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "limit": limit,
        }
        if normalized_subject:
            sql += " AND subject = :subject"
            params["subject"] = normalized_subject
        if normalized_role:
            sql += " AND role = :role"
            params["role"] = normalized_role
        if normalized_action:
            sql += " AND action = :action"
            params["action"] = normalized_action
        if normalized_outcome:
            sql += " AND outcome = :outcome"
            params["outcome"] = normalized_outcome
        if normalized_resource_type:
            sql += " AND resource_type = :resource_type"
            params["resource_type"] = normalized_resource_type
        if normalized_resource_id:
            sql += " AND resource_id = :resource_id"
            params["resource_id"] = normalized_resource_id
        if normalized_task_id:
            sql += " AND task_id = :task_id"
            params["task_id"] = normalized_task_id
        if normalized_execution_id:
            sql += " AND execution_id = :execution_id"
            params["execution_id"] = normalized_execution_id
        if recorded_after:
            sql += " AND recorded_at >= :recorded_after"
            params["recorded_after"] = recorded_after
        if recorded_before:
            sql += " AND recorded_at <= :recorded_before"
            params["recorded_before"] = recorded_before
        sql += " ORDER BY recorded_at DESC LIMIT :limit"

        try:
            with pg_client.engine.connect() as conn:
                rows = conn.execute(text(sql), params)
                records: list[dict[str, Any]] = []
                for row in rows:
                    payload = dict(row._mapping)
                    metadata = payload.get("metadata")
                    if isinstance(metadata, str):
                        payload["metadata"] = json.loads(metadata)
                    records.append(payload)
                return records or filtered_memory[:limit]
        except Exception as exc:
            cls._handle_backend_error("读取审计记录", exc)
            return filtered_memory[:limit]
