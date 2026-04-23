"""Docker沙箱执行器"""

import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import docker
from config.sandbox_config import (
    DOCKER_CONFIG,
    ZOMBIE_CLEAN_INTERVAL,
    ZOMBIE_CONTAINER_TIMEOUT_FACTOR,
)
from docker.errors import ContainerError, DockerException
from dotenv import load_dotenv
from requests.exceptions import Timeout as RequestsTimeout

from src.common import generate_uuid, get_current_timestamp, get_logger
from src.harness import HarnessGovernor
from src.harness.policy import load_harness_policy
from src.sandbox.container_lifecycle import (
    cleanup_sandbox_run,
    collect_container_logs,
    ensure_sandbox_image,
    prepare_sandbox_run,
    wait_for_container_exit,
)
from src.sandbox.exceptions import (
    CodeExecError,
    DockerOperationError,
    ExecTimeoutError,
    InputValidationError,
    SandboxBaseError,
)
from src.sandbox.execution_entrypoints import (
    execute_in_sandbox_async_entrypoint_impl,
    execute_in_sandbox_entrypoint_impl,
    execute_in_sandbox_with_audit_entrypoint_impl,
)
from src.sandbox.execution_flow import (
    build_failure_response_impl,
    build_governance_denied_response_impl,
    build_success_response_impl,
    create_sandbox_session_impl,
    evaluate_sandbox_governance_impl,
    reserve_tenant_slot_impl,
    start_sandbox_container_impl,
)
from src.sandbox.execution_orchestration import (
    execute_code_in_docker_impl,
)
from src.sandbox.execution_reporting import build_preflight_failure_response, build_sandbox_response
from src.sandbox.metrics import (
    sandbox_container_create_fail_total,
    sandbox_container_create_success_total,
    sandbox_container_oom_total,
    sandbox_exec_duration_seconds,
    sandbox_exec_fail_total,
    sandbox_exec_success_total,
)
from src.sandbox.runtime_state import (
    _running_containers as _runtime_running_containers,
)
from src.sandbox.runtime_state import (
    _tenant_concurrency as _runtime_tenant_concurrency,
)
from src.sandbox.runtime_state import (
    clear_running_containers,
    close_docker_client,
    current_tenant_concurrency,
    decrement_tenant_concurrency,
    increment_tenant_concurrency,
    is_shutdown_requested,
    register_running_container,
    request_shutdown,
    should_start_zombie_cleaner,
    snapshot_running_containers,
    unregister_running_container,
)
from src.sandbox.runtime_state import (
    get_docker_client as _get_docker_client,
)
from src.sandbox.service_lifecycle import (
    clean_zombie_containers_impl,
    init_signal_handlers_impl,
    signal_handler_impl,
    start_zombie_cleaner_daemon_impl,
)
from src.sandbox.session_manager import sandbox_session_manager
from src.sandbox.utils import build_log_data, validate_code_basic, validate_tenant_id, validate_workspace_id

load_dotenv()
logger = get_logger(__name__)

# Backward-compatible test hooks.
_tenant_concurrency: dict[str, int] = _runtime_tenant_concurrency
_running_containers: dict[str, str] = _runtime_running_containers

executor_pool = ThreadPoolExecutor(max_workers=50)


def _execution_flow_dependencies() -> dict[str, Any]:
    return {
        "build_log_data": build_log_data,
        "create_sandbox_session": _create_sandbox_session,
        "evaluate_sandbox_governance": _evaluate_sandbox_governance,
        "build_governance_denied_response": _build_governance_denied_response,
        "validate_code_basic": validate_code_basic,
        "validate_tenant_id": validate_tenant_id,
        "validate_workspace_id": validate_workspace_id,
        "reserve_tenant_slot": _reserve_tenant_slot,
        "start_sandbox_container": _start_sandbox_container,
        "build_success_response": _build_success_response,
        "build_failure_response": _build_failure_response,
        "cleanup_sandbox_run": cleanup_sandbox_run,
        "unregister_running_container": unregister_running_container,
        "decrement_tenant_concurrency": decrement_tenant_concurrency,
        "docker_config": DOCKER_CONFIG,
        "requests_timeout_cls": RequestsTimeout,
        "sandbox_base_error_cls": SandboxBaseError,
        "container_error_cls": ContainerError,
        "docker_exception_cls": DockerException,
        "docker_operation_error_cls": DockerOperationError,
        "exec_timeout_error_cls": ExecTimeoutError,
        "logger": logger,
    }


def _audit_entrypoint_dependencies() -> dict[str, Any]:
    from src.sandbox.ast_auditor import audit_code
    from src.sandbox.exceptions import AuditFailError
    from src.sandbox.metrics import sandbox_exec_fail_total
    from src.sandbox.utils import validate_code

    return {
        "is_shutdown_requested": is_shutdown_requested,
        "docker_operation_error_cls": DockerOperationError,
        "generate_uuid": generate_uuid,
        "get_current_timestamp": get_current_timestamp,
        "build_log_data": build_log_data,
        "validate_code": validate_code,
        "validate_tenant_id": validate_tenant_id,
        "validate_workspace_id": validate_workspace_id,
        "audit_code": audit_code,
        "audit_fail_error_cls": AuditFailError,
        "sandbox_base_error_cls": SandboxBaseError,
        "sandbox_exec_fail_total": sandbox_exec_fail_total,
        "build_preflight_failure_response": build_preflight_failure_response,
        "execute_code_in_docker": _execute_code_in_docker,
        "logger": logger,
    }


def _async_entrypoint_dependencies() -> dict[str, Any]:
    return {
        "executor_pool": executor_pool,
        "execute_in_sandbox_with_audit": execute_in_sandbox_with_audit,
        "execute_code_in_docker": _execute_code_in_docker,
    }


def _sandbox_entrypoint_dependencies() -> dict[str, Any]:
    return {
        "execute_code_in_docker": _execute_code_in_docker,
    }


def get_docker_client() -> docker.DockerClient:
    """线程安全的Docker客户端单例"""
    return _get_docker_client()


def signal_handler(signum, frame):
    """信号处理器"""
    signal_handler_impl(
        signum,
        frame,
        logger=logger,
        request_shutdown=request_shutdown,
        snapshot_running_containers=snapshot_running_containers,
        clear_running_containers=clear_running_containers,
        get_docker_client=get_docker_client,
        close_docker_client=close_docker_client,
        signal_module=signal,
        os_module=os,
    )


def clean_zombie_containers() -> None:
    """兜底清理僵尸容器"""
    clean_zombie_containers_impl(
        logger=logger,
        get_docker_client=get_docker_client,
        docker_config=DOCKER_CONFIG,
        zombie_container_timeout_factor=ZOMBIE_CONTAINER_TIMEOUT_FACTOR,
    )


def _create_sandbox_session(
    *,
    tenant_id: str,
    workspace_id: str,
    task_id: str | None,
    trace_id: str,
    input_mounts: list[dict[str, str]] | None,
) -> list[dict[str, str]]:
    return create_sandbox_session_impl(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        trace_id=trace_id,
        input_mounts=input_mounts,
        sandbox_session_manager=sandbox_session_manager,
    )


def _evaluate_sandbox_governance(
    *,
    code: str,
    tenant_id: str,
    trace_id: str,
    log_extra: dict[str, Any],
) -> tuple[Any | None, dict[str, Any] | None]:
    return evaluate_sandbox_governance_impl(
        code=code,
        tenant_id=tenant_id,
        trace_id=trace_id,
        log_extra=log_extra,
        load_harness_policy=load_harness_policy,
        evaluate_execution=HarnessGovernor.evaluate_sandbox_execution,
        logger=logger,
    )


def _build_governance_denied_response(
    *,
    trace_id: str,
    tenant_id: str,
    workspace_id: str,
    task_id: str | None,
    governance_reasons: list[str],
    governance_record: dict[str, Any] | None,
    sandbox_inputs: list[dict[str, str]],
    log_data: dict[str, Any],
    log_extra: dict[str, Any],
) -> dict[str, Any]:
    return build_governance_denied_response_impl(
        trace_id=trace_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        governance_reasons=governance_reasons,
        governance_record=governance_record,
        sandbox_inputs=sandbox_inputs,
        log_data=log_data,
        log_extra=log_extra,
        logger=logger,
        sandbox_exec_fail_total=sandbox_exec_fail_total,
        build_sandbox_response=build_sandbox_response,
    )


def _reserve_tenant_slot(tenant_id: str, trace_id: str) -> None:
    reserve_tenant_slot_impl(
        tenant_id=tenant_id,
        trace_id=trace_id,
        current_tenant_concurrency=current_tenant_concurrency,
        increment_tenant_concurrency=increment_tenant_concurrency,
        max_tenant_concurrency=DOCKER_CONFIG["max_tenant_concurrency"],
        input_validation_error_cls=InputValidationError,
    )


def _start_sandbox_container(
    *,
    code: str,
    tenant_id: str,
    workspace_id: str,
    trace_id: str,
    sandbox_inputs: list[dict[str, str]],
    log_extra: dict[str, Any],
) -> tuple[Any, str, str]:
    return start_sandbox_container_impl(
        code=code,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        trace_id=trace_id,
        sandbox_inputs=sandbox_inputs,
        log_extra=log_extra,
        logger=logger,
        docker_config=DOCKER_CONFIG,
        get_docker_client=get_docker_client,
        ensure_sandbox_image=ensure_sandbox_image,
        prepare_sandbox_run=prepare_sandbox_run,
        register_running_container=register_running_container,
        sandbox_session_manager=sandbox_session_manager,
        sandbox_container_create_success_total=sandbox_container_create_success_total,
    )


def _build_success_response(
    *,
    container: Any,
    trace_id: str,
    start_time: float,
    tenant_id: str,
    workspace_id: str,
    task_id: str | None,
    artifacts_dir: str,
    sandbox_inputs: list[dict[str, str]],
    governance_record: dict[str, Any] | None,
    log_data: dict[str, Any],
    log_extra: dict[str, Any],
) -> dict[str, Any]:
    return build_success_response_impl(
        container=container,
        trace_id=trace_id,
        start_time=start_time,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        artifacts_dir=artifacts_dir,
        sandbox_inputs=sandbox_inputs,
        governance_record=governance_record,
        log_data=log_data,
        log_extra=log_extra,
        wait_for_container_exit=wait_for_container_exit,
        collect_container_logs=collect_container_logs,
        logger=logger,
        sandbox_exec_duration_seconds=sandbox_exec_duration_seconds,
        sandbox_exec_success_total=sandbox_exec_success_total,
        sandbox_container_oom_total=sandbox_container_oom_total,
        code_exec_error_cls=CodeExecError,
        build_sandbox_response=build_sandbox_response,
    )


def _build_failure_response(
    *,
    trace_id: str,
    tenant_id: str,
    workspace_id: str,
    task_id: str | None,
    start_time: float,
    sandbox_inputs: list[dict[str, str]],
    governance_record: dict[str, Any] | None,
    error_type: str,
    reason: str,
    session_phase: str,
    log_data: dict[str, Any],
    log_extra: dict[str, Any],
    logger_method: str = "error",
    mark_container_create_failure: bool = False,
) -> dict[str, Any]:
    return build_failure_response_impl(
        trace_id=trace_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        start_time=start_time,
        sandbox_inputs=sandbox_inputs,
        governance_record=governance_record,
        error_type=error_type,
        reason=reason,
        session_phase=session_phase,
        log_data=log_data,
        log_extra=log_extra,
        logger=logger,
        sandbox_exec_fail_total=sandbox_exec_fail_total,
        build_sandbox_response=build_sandbox_response,
        get_current_timestamp=get_current_timestamp,
        sandbox_container_create_fail_total=sandbox_container_create_fail_total,
        logger_method=logger_method,
        mark_container_create_failure=mark_container_create_failure,
    )


def _execute_code_in_docker(
    code: str,
    tenant_id: str,
    workspace_id: str,
    trace_id: str | None = None,
    task_id: str | None = None,
    input_mounts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """沙箱执行核心函数。"""
    return execute_code_in_docker_impl(
        code=code,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        trace_id=trace_id,
        task_id=task_id,
        input_mounts=input_mounts,
        generate_uuid=generate_uuid,
        get_current_timestamp=get_current_timestamp,
        is_shutdown_requested=is_shutdown_requested,
        **_execution_flow_dependencies(),
    )


def execute_in_sandbox_with_audit(
    code: str,
    tenant_id: str,
    workspace_id: str = "default_ws",
    task_id: str | None = None,
    input_mounts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """【独立服务入口】一站式沙箱执行（包含完整校验+审计+执行）。"""
    return execute_in_sandbox_with_audit_entrypoint_impl(
        code=code,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        input_mounts=input_mounts,
        **_audit_entrypoint_dependencies(),
    )


def execute_in_sandbox(
    code: str,
    tenant_id: str,
    workspace_id: str = "default_ws",
    task_id: str | None = None,
    input_mounts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Raw sandbox execution without the extra AST audit wrapper."""
    return execute_in_sandbox_entrypoint_impl(
        code=code,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        input_mounts=input_mounts,
        **_sandbox_entrypoint_dependencies(),
    )


async def execute_in_sandbox_async(
    code: str,
    tenant_id: str,
    workspace_id: str = "default_ws",
    use_audit: bool = False,
    task_id: str | None = None,
    input_mounts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return await execute_in_sandbox_async_entrypoint_impl(
        code=code,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        use_audit=use_audit,
        task_id=task_id,
        input_mounts=input_mounts,
        **_async_entrypoint_dependencies(),
    )


# -------------------------- 初始化信号处理 --------------------------
def init_signal_handlers() -> None:
    """初始化信号处理器（支持多信号）"""
    init_signal_handlers_impl(signal_handler=signal_handler, logger=logger, signal_module=signal)


# -------------------------- 后台守护任务 --------------------------
def start_zombie_cleaner_daemon():
    """启动全局唯一的僵尸容器清理后台任务"""
    start_zombie_cleaner_daemon_impl(
        should_start_zombie_cleaner=should_start_zombie_cleaner,
        thread_factory=threading.Thread,
        clean_zombie_containers=clean_zombie_containers,
        zombie_clean_interval=ZOMBIE_CLEAN_INTERVAL,
        generate_uuid=generate_uuid,
        logger=logger,
        time_module=time,
    )
