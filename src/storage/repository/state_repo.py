"""
src/storage/repository/state_repo.py
系统运行状态仓库 (State Repository)

职责：
持久化 DAG 引擎和 Blackboard 的运行状态，实现防崩溃、断点续传。
"""
import json
from datetime import datetime, timedelta
from typing import Any

from config.settings import STRICT_PERSISTENCE, TASK_LEASE_TTL_SECONDS
from sqlalchemy import text
from src.common.logger import get_logger
from src.common.utils import get_utc_now
from src.storage.postgres_client import pg_client

logger = get_logger(__name__)

class StateRepo:
    _memory_store: dict[str, dict[str, dict[str, Any]]] = {}
    _memory_task_leases: dict[str, dict[str, Any]] = {}
    _last_error: str | None = None

    @classmethod
    def status(cls) -> dict[str, Any]:
        memory_task_count = sum(len(bucket) for bucket in cls._memory_store.values())
        memory_lease_count = len(cls._memory_task_leases)
        return {
            "backend": "postgres" if pg_client.engine else "memory_fallback",
            "postgres_available": pg_client.engine is not None,
            "postgres_driver": getattr(pg_client, "driver_name", None),
            "postgres_driver_error": getattr(pg_client, "driver_error", None),
            "strict_persistence": bool(STRICT_PERSISTENCE),
            "memory_task_count": memory_task_count,
            "memory_lease_count": memory_lease_count,
            "distributed_claims_supported": pg_client.engine is not None,
            "last_error": cls._last_error,
        }

    @classmethod
    def _require_backend(cls, operation: str) -> None:
        if pg_client.engine is not None:
            return
        if not STRICT_PERSISTENCE:
            return
        message = f"StateRepo requires Postgres for `{operation}` when STRICT_PERSISTENCE is enabled"
        cls._last_error = message
        raise RuntimeError(message)

    @classmethod
    def _handle_backend_error(cls, operation: str, exc: Exception) -> None:
        cls._last_error = str(exc)
        logger.error(f"[StateRepo] {operation}失败: {exc}")
        if STRICT_PERSISTENCE:
            raise RuntimeError(f"StateRepo {operation} failed under STRICT_PERSISTENCE: {exc}") from exc

    @classmethod
    def _normalize_state(cls, state_dict: dict[str, Any]) -> dict[str, Any]:
        return json.loads(json.dumps(state_dict, default=str))

    @classmethod
    def clear(cls) -> None:
        cls._memory_store.clear()
        cls._memory_task_leases.clear()

    @classmethod
    def _ensure_state_table(cls):
        if not pg_client.engine:
            return
        
        sql = """
        CREATE TABLE IF NOT EXISTS kag_execution_states (
            tenant_id VARCHAR(255) NOT NULL,
            task_id VARCHAR(255) NOT NULL,
            workspace_id VARCHAR(255) NOT NULL,
            state_data JSONB NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            PRIMARY KEY (tenant_id, task_id)
        );
        CREATE INDEX IF NOT EXISTS idx_state_ws ON kag_execution_states(tenant_id, workspace_id);
        """
        try:
            with pg_client.engine.begin() as conn:
                conn.execute(text(sql))
        except Exception as e:
            cls._handle_backend_error("初始化状态表", e)

    @classmethod
    def _ensure_task_lease_table(cls) -> None:
        if not pg_client.engine:
            return

        sql = """
        CREATE TABLE IF NOT EXISTS kag_task_leases (
            task_id VARCHAR(255) PRIMARY KEY,
            tenant_id VARCHAR(255) NOT NULL,
            workspace_id VARCHAR(255) NOT NULL,
            owner_id VARCHAR(255) NOT NULL,
            lease_expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            claimed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            heartbeat_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_task_leases_owner
        ON kag_task_leases(owner_id, lease_expires_at DESC);
        """
        try:
            with pg_client.engine.begin() as conn:
                conn.execute(text(sql))
        except Exception as exc:
            cls._handle_backend_error("初始化任务租约表", exc)

    @classmethod
    def claim_task_lease(
        cls,
        *,
        tenant_id: str,
        task_id: str,
        workspace_id: str,
        owner_id: str,
        lease_ttl_seconds: int = TASK_LEASE_TTL_SECONDS,
    ) -> dict[str, Any]:
        now = get_utc_now()
        expires_at = now + timedelta(seconds=lease_ttl_seconds)
        cls._require_backend("claim_task_lease")
        if not pg_client.engine:
            current = cls._memory_task_leases.get(task_id)
            if current and current["owner_id"] != owner_id and current["lease_expires_at"] > now:
                return {
                    "acquired": False,
                    "owner_id": current["owner_id"],
                    "lease_expires_at": current["lease_expires_at"].isoformat(),
                    "backend": "memory_fallback",
                }
            cls._memory_task_leases[task_id] = {
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "owner_id": owner_id,
                "lease_expires_at": expires_at,
                "heartbeat_at": now,
            }
            return {
                "acquired": True,
                "owner_id": owner_id,
                "lease_expires_at": expires_at.isoformat(),
                "backend": "memory_fallback",
            }

        cls._ensure_task_lease_table()
        sql = text(
            """
            INSERT INTO kag_task_leases (
                task_id, tenant_id, workspace_id, owner_id, lease_expires_at, claimed_at, heartbeat_at, updated_at
            )
            VALUES (
                :task_id, :tenant_id, :workspace_id, :owner_id, :lease_expires_at, NOW(), NOW(), NOW()
            )
            ON CONFLICT (task_id) DO UPDATE SET
                tenant_id = EXCLUDED.tenant_id,
                workspace_id = EXCLUDED.workspace_id,
                owner_id = EXCLUDED.owner_id,
                lease_expires_at = EXCLUDED.lease_expires_at,
                heartbeat_at = NOW(),
                updated_at = NOW()
            WHERE kag_task_leases.lease_expires_at < NOW()
               OR kag_task_leases.owner_id = EXCLUDED.owner_id
            RETURNING owner_id, lease_expires_at
            """
        )
        try:
            with pg_client.engine.begin() as conn:
                row = conn.execute(
                    sql,
                    {
                        "task_id": task_id,
                        "tenant_id": tenant_id,
                        "workspace_id": workspace_id,
                        "owner_id": owner_id,
                        "lease_expires_at": expires_at,
                    },
                ).fetchone()
                if row:
                    return {
                        "acquired": True,
                        "owner_id": row[0],
                        "lease_expires_at": row[1].isoformat() if row[1] else None,
                        "backend": "postgres",
                    }
            with pg_client.engine.connect() as conn:
                row = conn.execute(
                    text("SELECT owner_id, lease_expires_at FROM kag_task_leases WHERE task_id = :task_id"),
                    {"task_id": task_id},
                ).fetchone()
                return {
                    "acquired": False,
                    "owner_id": row[0] if row else None,
                    "lease_expires_at": row[1].isoformat() if row and row[1] else None,
                    "backend": "postgres",
                }
        except Exception as exc:
            cls._last_error = str(exc)
            logger.error(f"[StateRepo] 任务租约申请失败: {exc}")
            return {
                "acquired": False,
                "owner_id": None,
                "lease_expires_at": None,
                "backend": "postgres",
                "error": str(exc),
            }

    @classmethod
    def renew_task_lease(
        cls,
        *,
        task_id: str,
        owner_id: str,
        lease_ttl_seconds: int = TASK_LEASE_TTL_SECONDS,
    ) -> bool:
        now = get_utc_now()
        expires_at = now + timedelta(seconds=lease_ttl_seconds)
        cls._require_backend("renew_task_lease")
        if not pg_client.engine:
            current = cls._memory_task_leases.get(task_id)
            if not current or current["owner_id"] != owner_id:
                return False
            current["lease_expires_at"] = expires_at
            current["heartbeat_at"] = now
            return True

        cls._ensure_task_lease_table()
        sql = text(
            """
            UPDATE kag_task_leases
            SET lease_expires_at = :lease_expires_at,
                heartbeat_at = NOW(),
                updated_at = NOW()
            WHERE task_id = :task_id
              AND owner_id = :owner_id
            """
        )
        try:
            with pg_client.engine.begin() as conn:
                result = conn.execute(
                    sql,
                    {
                        "task_id": task_id,
                        "owner_id": owner_id,
                        "lease_expires_at": expires_at,
                    },
                )
                return bool(result.rowcount)
        except Exception as exc:
            cls._last_error = str(exc)
            logger.error(f"[StateRepo] 任务租约续约失败: {exc}")
            return False

    @classmethod
    def release_task_lease(cls, *, task_id: str, owner_id: str) -> None:
        cls._require_backend("release_task_lease")
        if not pg_client.engine:
            current = cls._memory_task_leases.get(task_id)
            if current and current["owner_id"] == owner_id:
                cls._memory_task_leases.pop(task_id, None)
            return

        cls._ensure_task_lease_table()
        try:
            with pg_client.engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM kag_task_leases WHERE task_id = :task_id AND owner_id = :owner_id"),
                    {"task_id": task_id, "owner_id": owner_id},
                )
        except Exception as exc:
            cls._last_error = str(exc)
            logger.error(f"[StateRepo] 任务租约释放失败: {exc}")

    @classmethod
    def list_task_leases(cls) -> list[dict[str, Any]]:
        cls._require_backend("list_task_leases")
        if not pg_client.engine:
            return [
                {
                    "task_id": task_id,
                    "owner_id": payload["owner_id"],
                    "workspace_id": payload["workspace_id"],
                    "lease_expires_at": payload["lease_expires_at"].isoformat(),
                    "backend": "memory_fallback",
                }
                for task_id, payload in cls._memory_task_leases.items()
            ]

        cls._ensure_task_lease_table()
        try:
            with pg_client.engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT task_id, owner_id, workspace_id, lease_expires_at
                        FROM kag_task_leases
                        ORDER BY updated_at DESC
                        """
                    )
                )
                return [
                    {
                        "task_id": row[0],
                        "owner_id": row[1],
                        "workspace_id": row[2],
                        "lease_expires_at": row[3].isoformat() if row[3] else None,
                        "backend": "postgres",
                    }
                    for row in rows
                ]
        except Exception as exc:
            cls._last_error = str(exc)
            logger.error(f"[StateRepo] 列出任务租约失败: {exc}")
            return []

    @classmethod
    def get_task_lease(cls, task_id: str) -> dict[str, Any] | None:
        if not pg_client.engine:
            payload = cls._memory_task_leases.get(task_id)
            if not payload:
                return None
            return {
                "task_id": task_id,
                "owner_id": payload["owner_id"],
                "workspace_id": payload["workspace_id"],
                "lease_expires_at": payload["lease_expires_at"].isoformat(),
                "backend": "memory_fallback",
            }

        cls._ensure_task_lease_table()
        try:
            with pg_client.engine.connect() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT task_id, owner_id, workspace_id, lease_expires_at
                        FROM kag_task_leases
                        WHERE task_id = :task_id
                        LIMIT 1
                        """
                    ),
                    {"task_id": task_id},
                ).fetchone()
                if not row:
                    return None
                return {
                    "task_id": row[0],
                    "owner_id": row[1],
                    "workspace_id": row[2],
                    "lease_expires_at": row[3].isoformat() if row[3] else None,
                    "backend": "postgres",
                }
        except Exception as exc:
            cls._last_error = str(exc)
            logger.error(f"[StateRepo] 读取任务租约失败: {exc}")
            return None

    @classmethod
    def task_lease_status(cls, task_id: str, owner_id: str) -> dict[str, Any]:
        if not pg_client.engine:
            payload = cls._memory_task_leases.get(task_id)
            if not payload:
                return {"status": "lost", "reason": "task lease missing"}
            if str(payload.get("owner_id") or "") != owner_id:
                return {"status": "lost", "reason": f"task lease owned by {payload.get('owner_id')}"}
            if payload["lease_expires_at"] <= get_utc_now():
                return {"status": "lost", "reason": "task lease expired"}
            return {
                "status": "owned",
                "lease": {
                    "task_id": task_id,
                    "owner_id": payload["owner_id"],
                    "workspace_id": payload["workspace_id"],
                    "lease_expires_at": payload["lease_expires_at"].isoformat(),
                    "backend": "memory_fallback",
                },
            }

        cls._ensure_task_lease_table()
        try:
            with pg_client.engine.connect() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT task_id, owner_id, workspace_id, lease_expires_at
                        FROM kag_task_leases
                        WHERE task_id = :task_id
                        LIMIT 1
                        """
                    ),
                    {"task_id": task_id},
                ).fetchone()
            if not row:
                return {"status": "lost", "reason": "task lease missing"}
            lease = {
                "task_id": row[0],
                "owner_id": row[1],
                "workspace_id": row[2],
                "lease_expires_at": row[3].isoformat() if row[3] else None,
                "backend": "postgres",
            }
            if str(lease.get("owner_id") or "") != owner_id:
                return {"status": "lost", "reason": f"task lease owned by {lease.get('owner_id')}", "lease": lease}
            lease_expires_at = str(lease.get("lease_expires_at") or "").strip()
            if not lease_expires_at:
                return {"status": "unknown", "error": "lease expiry unavailable", "lease": lease}
            expires_at = datetime.fromisoformat(lease_expires_at.replace("Z", "+00:00"))
            if expires_at <= get_utc_now():
                return {"status": "lost", "reason": "task lease expired", "lease": lease}
            return {"status": "owned", "lease": lease}
        except Exception as exc:
            cls._last_error = str(exc)
            logger.error(f"[StateRepo] 读取任务租约状态失败: {exc}")
            return {"status": "unknown", "error": str(exc)}

    @classmethod
    def task_lease_owned_by(cls, task_id: str, owner_id: str) -> bool:
        return cls.task_lease_status(task_id, owner_id).get("status") == "owned"
    
    @classmethod
    def save_blackboard_state(
        cls, 
        tenant_id: str,
        task_id: str,
        workspace_id: str,
        state_dict: dict[str, Any]
    ):
        """将黑板数据序列化并落库，实现任务级持久化"""
        normalized_state = cls._normalize_state(state_dict)

        cls._require_backend("save_blackboard_state")
        if not pg_client.engine:
            tenant_bucket = cls._memory_store.setdefault(tenant_id, {})
            tenant_bucket[task_id] = normalized_state
            return
        cls._ensure_state_table()
        
        sql = text("""
            INSERT INTO kag_execution_states (tenant_id, task_id, workspace_id, state_data, updated_at)
            VALUES (:tenant_id, :task_id, :workspace_id, :state_data, :updated_at)
            ON CONFLICT (tenant_id, task_id) 
            DO UPDATE SET 
                state_data = EXCLUDED.state_data,
                workspace_id = EXCLUDED.workspace_id,
                updated_at = NOW();
        """)

        try:
            with pg_client.engine.begin() as conn:
                conn.execute(
                    sql,
                    {
                        "tenant_id": tenant_id,
                        "task_id": task_id,
                        "workspace_id": workspace_id,
                        # 避免 datetime 等特殊类型报错
                        "state_data": json.dumps(normalized_state, default=str), 
                        "updated_at": get_utc_now()
                    }
                )
            tenant_bucket = cls._memory_store.setdefault(tenant_id, {})
            tenant_bucket[task_id] = normalized_state
        except Exception as e:
            cls._handle_backend_error(f"保存任务 {task_id} 的状态", e)

    @classmethod
    def load_blackboard_state(cls, tenant_id: str, task_id: str) -> dict[str, Any] | None:
        """在进程重启或页面刷新时，从数据库恢复任务状态"""
        cls._require_backend("load_blackboard_state")
        cls._ensure_state_table()
        if not pg_client.engine:
            return cls._memory_store.get(tenant_id, {}).get(task_id)
        
        sql = text("""
            SELECT state_data FROM kag_execution_states 
            WHERE tenant_id = :tenant_id AND task_id = :task_id
        """)

        try:
            with pg_client.engine.connect() as conn:
                # 一个租户中的一个task_id对应一个任务，所以数据库中对应的记录也只会有一条
                result = conn.execute(sql, {"tenant_id": tenant_id, "task_id": task_id}).fetchone()
                if result and result[0]:
                    data = result[0]
                    return json.loads(data) if isinstance(data, str) else data
                return cls._memory_store.get(tenant_id, {}).get(task_id)
        except Exception as e:
            cls._handle_backend_error("恢复任务状态", e)
            return cls._memory_store.get(tenant_id, {}).get(task_id)

    @classmethod
    def load_blackboard_state_by_task(cls, task_id: str) -> dict[str, Any] | None:
        """按 task_id 恢复状态，适用于 task_id 全局唯一的控制面查询。"""
        cls._require_backend("load_blackboard_state_by_task")
        cls._ensure_state_table()
        if pg_client.engine:
            sql = text("""
                SELECT state_data FROM kag_execution_states
                WHERE task_id = :task_id
                ORDER BY updated_at DESC
                LIMIT 1
            """)

            try:
                with pg_client.engine.connect() as conn:
                    result = conn.execute(sql, {"task_id": task_id}).fetchone()
                    if result and result[0]:
                        data = result[0]
                        return json.loads(data) if isinstance(data, str) else data
            except Exception as e:
                cls._handle_backend_error("按 task_id 恢复任务状态", e)

        # 这里把进程内 memory fallback 放到最后。
        # 原因是当 Postgres 可用且项目以“租约 + 持久化”方式跨进程协作时，
        # 数据库才是共享真源；如果先返回本进程旧缓存，就会把别的实例
        # 已经写入的新状态遮掉，导致控制面出现“读到旧任务状态”的错觉。
        for tenant_bucket in cls._memory_store.values():
            if task_id in tenant_bucket:
                return tenant_bucket[task_id]
        return None

    @classmethod
    def list_blackboard_states(cls) -> list[dict[str, Any]]:
        """列出当前已持久化的所有黑板状态。"""
        memory_items = [
            state
            for tenant_bucket in cls._memory_store.values()
            for state in tenant_bucket.values()
        ]

        cls._require_backend("list_blackboard_states")
        cls._ensure_state_table()
        if not pg_client.engine:
            return memory_items

        sql = text("""
            SELECT state_data FROM kag_execution_states
            ORDER BY updated_at DESC
        """)

        try:
            with pg_client.engine.connect() as conn:
                rows = conn.execute(sql)
                states: list[dict[str, Any]] = []
                for row in rows:
                    payload = row[0]
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    if isinstance(payload, dict):
                        states.append(payload)
                return states or memory_items
        except Exception as e:
            cls._handle_backend_error("列出任务状态", e)
            return memory_items
