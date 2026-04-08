"""Shared runtime state for the local Docker sandbox."""
from __future__ import annotations

import threading

import docker
from config.sandbox_config import DOCKER_CONFIG
from docker.errors import DockerException

from src.common import get_logger

logger = get_logger(__name__)

_docker_client: docker.DockerClient | None = None
_client_lock = threading.Lock()
_shutdown_requested = False
_shutdown_lock = threading.Lock()
_tenant_concurrency: dict[str, int] = {}
_concurrency_lock = threading.Lock()
_running_containers: dict[str, str] = {}
_containers_lock = threading.Lock()
_zombie_cleaner_started = False
_zombie_cleaner_lock = threading.Lock()


def get_docker_client() -> docker.DockerClient:
    """Return the process-wide Docker client singleton."""
    global _docker_client
    if _docker_client is None:
        with _client_lock:
            if _docker_client is None:
                try:
                    _docker_client = docker.from_env(timeout=DOCKER_CONFIG["container_operation_timeout"])
                    _docker_client.ping()
                    logger.info("docker client initialized success", extra={"trace_id": "system"})
                except DockerException as exc:
                    logger.critical(f"Docker服务连接失败: {str(exc)}", extra={"trace_id": "system"})
                    raise
    return _docker_client


def close_docker_client() -> None:
    """Close the singleton Docker client during process shutdown only."""
    global _docker_client
    with _client_lock:
        if _docker_client is None:
            return
        try:
            _docker_client.close()
        except Exception as exc:
            logger.warning(f"Docker客户端关闭失败: {str(exc)}", extra={"trace_id": "system"})
        finally:
            _docker_client = None


def request_shutdown() -> None:
    global _shutdown_requested
    with _shutdown_lock:
        _shutdown_requested = True


def clear_shutdown() -> None:
    global _shutdown_requested
    with _shutdown_lock:
        _shutdown_requested = False


def is_shutdown_requested() -> bool:
    with _shutdown_lock:
        return _shutdown_requested


def snapshot_running_containers() -> list[tuple[str, str]]:
    with _containers_lock:
        return list(_running_containers.items())


def clear_running_containers() -> None:
    with _containers_lock:
        _running_containers.clear()


def register_running_container(trace_id: str, container_id: str) -> None:
    with _containers_lock:
        _running_containers[trace_id] = container_id


def unregister_running_container(trace_id: str) -> None:
    with _containers_lock:
        _running_containers.pop(trace_id, None)


def current_tenant_concurrency(tenant_id: str) -> int:
    with _concurrency_lock:
        return int(_tenant_concurrency.get(tenant_id, 0))


def increment_tenant_concurrency(tenant_id: str) -> None:
    with _concurrency_lock:
        _tenant_concurrency[tenant_id] = int(_tenant_concurrency.get(tenant_id, 0)) + 1


def decrement_tenant_concurrency(tenant_id: str) -> None:
    with _concurrency_lock:
        if tenant_id not in _tenant_concurrency:
            return
        next_value = int(_tenant_concurrency.get(tenant_id, 0)) - 1
        if next_value <= 0:
            _tenant_concurrency.pop(tenant_id, None)
            return
        _tenant_concurrency[tenant_id] = next_value


def should_start_zombie_cleaner() -> bool:
    global _zombie_cleaner_started
    with _zombie_cleaner_lock:
        if _zombie_cleaner_started:
            return False
        _zombie_cleaner_started = True
        return True


def reset_runtime_state() -> None:
    """Reset in-process sandbox runtime state for tests."""
    clear_shutdown()
    with _concurrency_lock:
        _tenant_concurrency.clear()
    with _containers_lock:
        _running_containers.clear()
    global _zombie_cleaner_started
    with _zombie_cleaner_lock:
        _zombie_cleaner_started = False
    close_docker_client()
