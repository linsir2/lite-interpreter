"""Service lifecycle helpers for sandbox daemon and signal handling."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def signal_handler_impl(
    signum: int,
    frame: Any,
    *,
    logger: Any,
    request_shutdown: Any,
    snapshot_running_containers: Any,
    clear_running_containers: Any,
    get_docker_client: Any,
    close_docker_client: Any,
    signal_module: Any,
    os_module: Any,
) -> None:
    signal_name = signal_module.Signals(signum).name
    logger.warning(f"收到退出信号 {signal_name}，开始优雅关闭", extra={"trace_id": "system"})

    request_shutdown()
    containers_to_kill = snapshot_running_containers()
    clear_running_containers()

    client = get_docker_client()
    for trace_id, container_id in containers_to_kill:
        try:
            container = client.containers.get(container_id)
            container.remove(force=True)
            logger.info(f"优雅关闭：清理容器 {container_id}", extra={"trace_id": trace_id})
        except Exception as exc:
            logger.error(f"优雅关闭：容器清理失败 {container_id}: {str(exc)}", extra={"trace_id": trace_id})
    close_docker_client()
    logger.info("优雅关闭完成，程序退出", extra={"trace_id": "system"})
    os_module._exit(0)


def clean_zombie_containers_impl(
    *,
    logger: Any,
    get_docker_client: Any,
    docker_config: dict[str, Any],
    zombie_container_timeout_factor: int,
) -> None:
    try:
        client = get_docker_client()
        timeout_seconds = docker_config["timeout"] * zombie_container_timeout_factor
        now = __import__("time").time()
        containers = client.containers.list(all=True, filters={"name": "^sandbox-"})

        cleaned_count = 0
        for container in containers:
            try:
                created_time_str = container.attrs["Created"].split(".")[0]
                created_time = datetime.fromisoformat(created_time_str + "+00:00").timestamp()
                if now - created_time > timeout_seconds:
                    container.remove(force=True)
                    cleaned_count += 1
                    logger.info(f"兜底清理超时容器: {container.name}", extra={"trace_id": "system"})
            except Exception as exc:
                logger.error(f"兜底清理容器失败 {container.name}: {str(exc)}", extra={"trace_id": "system"})

        if cleaned_count > 0:
            logger.info(f"兜底清理完成，共清理 {cleaned_count} 个僵尸容器", extra={"trace_id": "system"})
    except Exception as exc:
        logger.error(f"兜底清理任务执行失败: {str(exc)}", extra={"trace_id": "system"})


def init_signal_handlers_impl(*, signal_handler: Any, logger: Any, signal_module: Any) -> None:
    signal_module.signal(signal_module.SIGINT, signal_handler)
    signal_module.signal(signal_module.SIGTERM, signal_handler)
    signal_module.signal(signal_module.SIGQUIT, signal_handler)
    logger.info("信号处理器初始化完成", extra={"trace_id": "system"})


def start_zombie_cleaner_daemon_impl(
    *,
    should_start_zombie_cleaner: Any,
    thread_factory: Any,
    clean_zombie_containers: Any,
    zombie_clean_interval: int,
    generate_uuid: Any,
    logger: Any,
    time_module: Any,
) -> None:
    if not should_start_zombie_cleaner():
        logger.info("僵尸容器清理守护线程已存在，跳过重复启动", extra={"trace_id": "system"})
        return

    def cleaner_loop():
        while True:
            time_module.sleep(zombie_clean_interval)
            trace_id = "zombie-cleaner-" + generate_uuid()[:8]
            logger.info("触发定时轮询：扫描并清理僵尸容器", extra={"trace_id": trace_id})
            try:
                clean_zombie_containers()
            except Exception as exc:
                logger.error(f"僵尸容器清理任务执行失败: {str(exc)}", extra={"trace_id": trace_id}, exc_info=True)

    cleaner_thread = thread_factory(target=cleaner_loop, daemon=True, name="GlobalZombieContainerCleaner")
    cleaner_thread.start()
    logger.info("全局僵尸容器清理守护线程已启动", extra={"trace_id": "system"})
