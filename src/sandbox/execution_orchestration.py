"""Orchestration helpers for sandbox execution entrypoints."""

from __future__ import annotations

import json
import traceback
from collections.abc import Callable
from typing import Any


def execute_code_in_docker_impl(
    *,
    code: str,
    tenant_id: str,
    workspace_id: str,
    trace_id: str,
    task_id: str | None,
    input_mounts: list[dict[str, str]] | None,
    generate_uuid: Callable[[], str],
    get_current_timestamp: Callable[[], float],
    build_log_data: Callable[[str, str, str, str], dict[str, Any]],
    create_sandbox_session: Callable[..., list[dict[str, str]]],
    evaluate_sandbox_governance: Callable[..., tuple[Any | None, dict[str, Any] | None]],
    build_governance_denied_response: Callable[..., dict[str, Any]],
    is_shutdown_requested: Callable[[], bool],
    validate_code_basic: Callable[[str, str], None],
    validate_tenant_id: Callable[[str, str], None],
    validate_workspace_id: Callable[[str, str], None],
    reserve_tenant_slot: Callable[[str, str], None],
    start_sandbox_container: Callable[..., tuple[Any, str, str]],
    build_success_response: Callable[..., dict[str, Any]],
    build_failure_response: Callable[..., dict[str, Any]],
    cleanup_sandbox_run: Callable[..., bool],
    unregister_running_container: Callable[[str], None],
    decrement_tenant_concurrency: Callable[[str], None],
    docker_config: dict[str, Any],
    requests_timeout_cls: type[Exception],
    sandbox_base_error_cls: type[Exception],
    container_error_cls: type[Exception],
    docker_exception_cls: type[Exception],
    docker_operation_error_cls: type[Exception],
    exec_timeout_error_cls: type[Exception],
    logger: Any,
) -> dict[str, Any]:
    trace_id = trace_id or generate_uuid()
    log_extra = {"trace_id": trace_id}
    start_time = get_current_timestamp()
    container: Any | None = None
    log_data = build_log_data(tenant_id, "sandbox_exec", code, trace_id)
    concurrency_incremented = False
    code_file_path = ""
    sandbox_inputs = create_sandbox_session(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        trace_id=trace_id,
        input_mounts=input_mounts,
    )
    governance_decision, governance_record = evaluate_sandbox_governance(
        code=code,
        tenant_id=tenant_id,
        trace_id=trace_id,
        log_extra=log_extra,
    )

    try:
        if governance_decision is not None and not governance_decision.allowed:
            return build_governance_denied_response(
                trace_id=trace_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                task_id=task_id,
                governance_reasons=list(governance_decision.reasons),
                governance_record=governance_record,
                sandbox_inputs=sandbox_inputs,
                log_data=log_data,
                log_extra=log_extra,
            )

        if is_shutdown_requested():
            raise docker_operation_error_cls("沙箱服务正在关闭，拒绝新的执行请求", trace_id)

        validate_code_basic(code, trace_id)
        validate_tenant_id(tenant_id, trace_id)
        validate_workspace_id(workspace_id, trace_id)
        reserve_tenant_slot(tenant_id, trace_id)
        concurrency_incremented = True
        container, artifacts_dir, code_file_path = start_sandbox_container(
            code=code,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            trace_id=trace_id,
            sandbox_inputs=sandbox_inputs,
            log_extra=log_extra,
        )
        return build_success_response(
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
        )

    except requests_timeout_cls:
        error = exec_timeout_error_cls(f"代码执行超时，最大允许执行{docker_config['timeout']}秒", trace_id)
        return build_failure_response(
            trace_id=trace_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            task_id=task_id,
            start_time=start_time,
            sandbox_inputs=sandbox_inputs,
            governance_record=governance_record,
            error_type=error.error_type,
            reason=error.message,
            session_phase="timeout",
            log_data=log_data,
            log_extra=log_extra,
        )

    except sandbox_base_error_cls as exc:
        return build_failure_response(
            trace_id=trace_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            task_id=task_id,
            start_time=start_time,
            sandbox_inputs=sandbox_inputs,
            governance_record=governance_record,
            error_type=exc.error_type,
            reason=exc.message,
            session_phase=exc.error_type,
            log_data=log_data,
            log_extra=log_extra,
        )

    except container_error_cls as exc:
        error_type = "container_start_error"
        container_logs = exc.container.logs().decode("utf-8", errors="replace").strip() if exc.container else "无容器日志"
        reason = f"容器启动失败，退出码：{exc.exit_status}，日志：{container_logs}"
        return build_failure_response(
            trace_id=trace_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            task_id=task_id,
            start_time=start_time,
            sandbox_inputs=sandbox_inputs,
            governance_record=governance_record,
            error_type=error_type,
            reason=reason,
            session_phase=error_type,
            log_data=log_data,
            log_extra=log_extra,
            mark_container_create_failure=True,
        )

    except docker_exception_cls as exc:
        error = docker_operation_error_cls(f"Docker服务异常：{str(exc)}", trace_id)
        return build_failure_response(
            trace_id=trace_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            task_id=task_id,
            start_time=start_time,
            sandbox_inputs=sandbox_inputs,
            governance_record=governance_record,
            error_type=error.error_type,
            reason=error.message,
            session_phase=error.error_type,
            log_data=log_data,
            log_extra=log_extra,
            mark_container_create_failure=True,
        )

    except Exception as exc:
        error_type = "unknown_exception"
        reason = f"未知执行异常：{str(exc)}; 具体报错：{traceback.format_exc()}"
        return build_failure_response(
            trace_id=trace_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            task_id=task_id,
            start_time=start_time,
            sandbox_inputs=sandbox_inputs,
            governance_record=governance_record,
            error_type=error_type,
            reason=reason,
            session_phase=error_type,
            log_data=log_data,
            log_extra=log_extra,
            logger_method="exception",
        )

    finally:
        removed_container = cleanup_sandbox_run(
            code_file_path=code_file_path,
            container=container,
        )
        if code_file_path:
            logger.debug(f"临时代码文件已清理: {code_file_path}", extra=log_extra)
        if container and not removed_container:
            logger.error("沙箱容器清理失败", extra=log_extra)

        unregister_running_container(trace_id)

        if concurrency_incremented:
            decrement_tenant_concurrency(tenant_id)


def execute_in_sandbox_with_audit_impl(
    *,
    code: str,
    tenant_id: str,
    workspace_id: str,
    task_id: str | None,
    input_mounts: list[dict[str, str]] | None,
    is_shutdown_requested: Callable[[], bool],
    docker_operation_error_cls: type[Exception],
    generate_uuid: Callable[[], str],
    get_current_timestamp: Callable[[], float],
    build_log_data: Callable[[str, str, str, str], dict[str, Any]],
    validate_code: Callable[[str, str], None],
    validate_tenant_id: Callable[[str, str], None],
    validate_workspace_id: Callable[[str, str], None],
    audit_code: Callable[..., dict[str, Any]],
    audit_fail_error_cls: type[Exception],
    sandbox_base_error_cls: type[Exception],
    sandbox_exec_fail_total: Any,
    build_preflight_failure_response: Callable[..., dict[str, Any]],
    execute_code_in_docker: Callable[..., dict[str, Any]],
    logger: Any,
) -> dict[str, Any]:
    log_extra = {"trace_id": generate_uuid(), "tenant_id": tenant_id, "workspace_id": workspace_id}
    trace_id = log_extra["trace_id"]
    log_data = build_log_data(tenant_id, "sandbox_exec_with_audit", code, trace_id)
    start_time = get_current_timestamp()

    try:
        if is_shutdown_requested():
            raise docker_operation_error_cls("沙箱服务正在关闭，拒绝新的执行请求", trace_id)

        logger.info("开始代码输入合法性校验", extra=log_extra)
        validate_code(code, trace_id)
        validate_tenant_id(tenant_id, trace_id)
        validate_workspace_id(workspace_id, trace_id)

        logger.info("开始AST代码安全审计", extra=log_extra)
        audit_result = audit_code(code, tenant_id, trace_id=trace_id)
        if not audit_result["safe"]:
            raise audit_fail_error_cls(
                message=audit_result["reason"],
                trace_id=trace_id,
                risk_type=audit_result["risk_type"] or "audit_fail",
            )

        logger.info("AST审计通过，开始执行代码", extra=log_extra)
        return execute_code_in_docker(
            code,
            tenant_id,
            trace_id=trace_id,
            workspace_id=workspace_id,
            task_id=task_id,
            input_mounts=input_mounts,
        )

    except sandbox_base_error_cls as exc:
        exec_duration = get_current_timestamp() - start_time
        log_data.update(
            {
                "exec_result": "fail",
                "error_type": exc.error_type,
                "reason": exc.message,
                "exec_duration_seconds": round(exec_duration, 3),
            }
        )
        logger.error(json.dumps(log_data, ensure_ascii=False), extra=log_extra)
        sandbox_exec_fail_total.labels(error_type=exc.error_type).inc()
        return build_preflight_failure_response(
            tenant_id=tenant_id,
            trace_id=trace_id,
            duration_seconds=round(exec_duration, 3),
            error=exc.message,
        )

    except Exception as exc:
        exec_duration = get_current_timestamp() - start_time
        error_type = "unknown_exception"
        reason = f"沙箱执行前置处理异常：{str(exc)}; 具体报错：{traceback.format_exc()}"
        log_data.update(
            {
                "exec_result": "fail",
                "error_type": error_type,
                "reason": reason,
                "exec_duration_seconds": round(exec_duration, 3),
            }
        )
        logger.exception(json.dumps(log_data, ensure_ascii=False), extra=log_extra)
        sandbox_exec_fail_total.labels(error_type=error_type).inc()
        return build_preflight_failure_response(
            tenant_id=tenant_id,
            trace_id=trace_id,
            duration_seconds=round(exec_duration, 3),
            error=reason,
        )
