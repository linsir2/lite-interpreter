"""Public entrypoint helpers for sandbox execution wrappers."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from src.sandbox.execution_orchestration import execute_in_sandbox_with_audit_impl


def execute_in_sandbox_entrypoint_impl(
    *,
    code: str,
    tenant_id: str,
    workspace_id: str,
    task_id: str | None,
    input_mounts: list[dict[str, str]] | None,
    execute_code_in_docker: Any,
) -> dict[str, Any]:
    return execute_code_in_docker(
        code,
        tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        input_mounts=input_mounts,
    )


async def execute_in_sandbox_async_entrypoint_impl(
    *,
    code: str,
    tenant_id: str,
    workspace_id: str,
    use_audit: bool,
    task_id: str | None,
    input_mounts: list[dict[str, str]] | None,
    executor_pool: ThreadPoolExecutor,
    execute_in_sandbox_with_audit: Any,
    execute_code_in_docker: Any,
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    if use_audit:
        return await loop.run_in_executor(
            executor_pool,
            execute_in_sandbox_with_audit,
            code,
            tenant_id,
            workspace_id,
            task_id,
            input_mounts,
        )
    return await loop.run_in_executor(
        executor_pool,
        execute_code_in_docker,
        code,
        tenant_id,
        workspace_id,
        None,
        task_id,
        input_mounts,
    )


def execute_in_sandbox_with_audit_entrypoint_impl(
    *,
    code: str,
    tenant_id: str,
    workspace_id: str,
    task_id: str | None,
    input_mounts: list[dict[str, str]] | None,
    is_shutdown_requested: Any,
    docker_operation_error_cls: type[Exception],
    generate_uuid: Any,
    get_current_timestamp: Any,
    build_log_data: Any,
    validate_code: Any,
    validate_tenant_id: Any,
    validate_workspace_id: Any,
    audit_code: Any,
    audit_fail_error_cls: type[Exception],
    sandbox_base_error_cls: type[Exception],
    sandbox_exec_fail_total: Any,
    build_preflight_failure_response: Any,
    execute_code_in_docker: Any,
    logger: Any,
) -> dict[str, Any]:
    return execute_in_sandbox_with_audit_impl(
        code=code,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        input_mounts=input_mounts,
        is_shutdown_requested=is_shutdown_requested,
        docker_operation_error_cls=docker_operation_error_cls,
        generate_uuid=generate_uuid,
        get_current_timestamp=get_current_timestamp,
        build_log_data=build_log_data,
        validate_code=validate_code,
        validate_tenant_id=validate_tenant_id,
        validate_workspace_id=validate_workspace_id,
        audit_code=audit_code,
        audit_fail_error_cls=audit_fail_error_cls,
        sandbox_base_error_cls=sandbox_base_error_cls,
        sandbox_exec_fail_total=sandbox_exec_fail_total,
        build_preflight_failure_response=build_preflight_failure_response,
        execute_code_in_docker=execute_code_in_docker,
        logger=logger,
    )
