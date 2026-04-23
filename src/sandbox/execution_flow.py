"""Execution-flow helpers for the docker sandbox executor."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any


def create_sandbox_session_impl(
    *,
    tenant_id: str,
    workspace_id: str,
    task_id: str | None,
    trace_id: str,
    input_mounts: list[dict[str, str]] | None,
    sandbox_session_manager: Any,
) -> list[dict[str, str]]:
    sandbox_inputs = list(input_mounts or [])
    session_spec = sandbox_session_manager.build_spec(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        input_mounts=sandbox_inputs,
    )
    sandbox_session_manager.create_session(session_spec, trace_id=trace_id)
    return sandbox_inputs


def evaluate_sandbox_governance_impl(
    *,
    code: str,
    tenant_id: str,
    trace_id: str,
    log_extra: dict[str, Any],
    load_harness_policy: Callable[[], dict[str, Any]],
    evaluate_execution: Callable[..., Any],
    logger: Any,
) -> tuple[Any | None, dict[str, Any] | None]:
    policy = load_harness_policy()
    sandbox_policy = dict(policy.get("sandbox") or {})
    require_policy_check = bool(sandbox_policy.get("require_policy_check", True))

    if not require_policy_check:
        logger.info("sandbox.require_policy_check=false，跳过 harness 预检", extra=log_extra)
        return None, None

    governance_decision = evaluate_execution(
        code=code,
        tenant_id=tenant_id,
        trace_ref=f"governance:sandbox:{trace_id}",
    )
    return governance_decision, governance_decision.to_record()


def build_governance_denied_response_impl(
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
    logger: Any,
    sandbox_exec_fail_total: Any,
    build_sandbox_response: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    reason = "沙箱执行请求被 harness policy 拒绝"
    full_reason = f"{reason}: {' | '.join(governance_reasons)}"
    log_data.update(
        {
            "exec_result": "fail",
            "error_type": "governance_denied",
            "reason": full_reason,
            "exec_duration_seconds": 0.0,
        }
    )
    logger.error(json.dumps(log_data, ensure_ascii=False), extra=log_extra)
    sandbox_exec_fail_total.labels(error_type="governance_denied").inc()
    return build_sandbox_response(
        success=False,
        trace_id=trace_id,
        duration_seconds=0.0,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        error=full_reason,
        mounted_inputs=sandbox_inputs,
        governance=governance_record,
        session_metadata={"phase": "governance", "error": full_reason},
    )


def reserve_tenant_slot_impl(
    *,
    tenant_id: str,
    trace_id: str,
    current_tenant_concurrency: Callable[[str], int],
    increment_tenant_concurrency: Callable[[str], None],
    max_tenant_concurrency: int,
    input_validation_error_cls: type[Exception],
) -> None:
    current_concurrency = current_tenant_concurrency(tenant_id)
    if current_concurrency >= max_tenant_concurrency:
        raise input_validation_error_cls(
            f"租户并发数超过限制，最大支持{max_tenant_concurrency}并发",
            trace_id,
        )
    increment_tenant_concurrency(tenant_id)


def start_sandbox_container_impl(
    *,
    code: str,
    tenant_id: str,
    workspace_id: str,
    trace_id: str,
    sandbox_inputs: list[dict[str, str]],
    log_extra: dict[str, Any],
    logger: Any,
    docker_config: dict[str, Any],
    get_docker_client: Callable[[], Any],
    ensure_sandbox_image: Callable[[Any], None],
    prepare_sandbox_run: Callable[..., Any],
    register_running_container: Callable[[str, str], None],
    sandbox_session_manager: Any,
    sandbox_container_create_success_total: Any,
) -> tuple[Any, str, str]:
    logger.info("代码已通过前置审计，开始启动沙箱容器", extra=log_extra)
    client = get_docker_client()
    ensure_sandbox_image(client)
    prepared_run = prepare_sandbox_run(
        code=code,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        trace_id=trace_id,
        input_mounts=sandbox_inputs,
    )
    container = client.containers.run(
        image=docker_config["image"],
        command=["python", "/app/code.py"],
        volumes=prepared_run.volume_bindings,
        detach=True,
        name=prepared_run.container_name,
        mem_limit=docker_config["mem_limit"],
        memswap_limit=docker_config["memswap_limit"],
        cpu_shares=docker_config["cpu_shares"],
        network_disabled=True,
        user=docker_config["user"],
        cap_drop=docker_config["cap_drop"],
        security_opt=docker_config["security_opt"],
        read_only=True,
        init=True,
        stdin_open=True,
        pids_limit=docker_config["pids_limit"],
        tmpfs=docker_config["tmpfs"],
        log_config=docker_config["log_config"],
    )

    register_running_container(trace_id, container.id)
    sandbox_session_manager.mark_running(
        trace_id,
        container_name=prepared_run.container_name,
        container_id=container.id,
    )
    logger.info(f"沙箱容器启动成功，容器ID: {container.id}", extra=log_extra)
    sandbox_container_create_success_total.inc()
    return container, str(prepared_run.host_output_dir), prepared_run.code_file_path


def build_success_response_impl(
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
    wait_for_container_exit: Callable[..., tuple[int, float]],
    collect_container_logs: Callable[[Any], str],
    logger: Any,
    sandbox_exec_duration_seconds: Any,
    sandbox_exec_success_total: Any,
    sandbox_container_oom_total: Any,
    code_exec_error_cls: type[Exception],
    build_sandbox_response: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    exit_code, exec_duration = wait_for_container_exit(
        container,
        trace_id=trace_id,
        start_time=start_time,
    )
    logs = collect_container_logs(container)

    if exit_code == 137:
        sandbox_container_oom_total.inc()
        raise code_exec_error_cls(f"容器内存超限被终止（OOM），退出码：{exit_code}", trace_id)
    if exit_code != 0:
        raise code_exec_error_cls(f"代码执行失败，退出码：{exit_code}，错误日志：{logs}", trace_id)

    log_data.update(
        {
            "exec_result": "success",
            "reason": "代码执行成功",
            "exec_duration_seconds": round(exec_duration, 3),
        }
    )
    logger.info(json.dumps(log_data, ensure_ascii=False), extra=log_extra)
    sandbox_exec_duration_seconds.observe(exec_duration)
    sandbox_exec_success_total.inc()

    return build_sandbox_response(
        success=True,
        trace_id=trace_id,
        duration_seconds=round(exec_duration, 3),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        output=logs,
        artifacts_dir=artifacts_dir,
        mounted_inputs=sandbox_inputs,
        governance=governance_record,
        session_metadata={"phase": "completed", "artifacts_dir": artifacts_dir},
    )


def build_failure_response_impl(
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
    logger: Any,
    sandbox_exec_fail_total: Any,
    build_sandbox_response: Callable[..., dict[str, Any]],
    get_current_timestamp: Callable[[], float],
    sandbox_container_create_fail_total: Any | None = None,
    logger_method: str = "error",
    mark_container_create_failure: bool = False,
) -> dict[str, Any]:
    exec_duration = get_current_timestamp() - start_time
    log_data.update(
        {
            "exec_result": "fail",
            "error_type": error_type,
            "reason": reason,
            "exec_duration_seconds": round(exec_duration, 3),
        }
    )
    log_line = json.dumps(log_data, ensure_ascii=False)
    if logger_method == "exception":
        logger.exception(log_line, extra=log_extra)
    else:
        logger.error(log_line, extra=log_extra)
    if mark_container_create_failure and sandbox_container_create_fail_total is not None:
        sandbox_container_create_fail_total.labels(error_type=error_type).inc()
    sandbox_exec_fail_total.labels(error_type=error_type).inc()
    return build_sandbox_response(
        success=False,
        trace_id=trace_id,
        duration_seconds=round(exec_duration, 3),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        error=reason,
        mounted_inputs=sandbox_inputs,
        governance=governance_record,
        session_metadata={"phase": session_phase, "error": reason},
    )
