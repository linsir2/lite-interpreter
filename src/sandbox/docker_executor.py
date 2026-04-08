"""Docker沙箱执行器"""
import asyncio
import json
import os
import signal
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
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
from src.sandbox.execution_reporting import build_preflight_failure_response, build_sandbox_response
from src.sandbox.metrics import (
    sandbox_container_create_fail_total,
    sandbox_container_create_success_total,
    sandbox_container_oom_total,
    sandbox_container_remove_fail_total,
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
from src.sandbox.session_manager import sandbox_session_manager
from src.sandbox.utils import build_log_data, validate_code_basic, validate_tenant_id

load_dotenv()
logger = get_logger(__name__)

# Backward-compatible test hooks.
_tenant_concurrency: dict[str, int] = _runtime_tenant_concurrency
_running_containers: dict[str, str] = _runtime_running_containers

executor_pool = ThreadPoolExecutor(max_workers=50)

def get_docker_client() -> docker.DockerClient:
    """线程安全的Docker客户端单例"""
    return _get_docker_client()

def signal_handler(signum, frame):
    """信号处理器"""
    signal_name = signal.Signals(signum).name
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
        except Exception as e:
            logger.error(f"优雅关闭：容器清理失败 {container_id}: {str(e)}", extra={"trace_id": trace_id})
    close_docker_client()
    logger.info("优雅关闭完成，程序退出", extra={"trace_id": "system"})
    os._exit(0)

def clean_zombie_containers() -> None:
    """兜底清理僵尸容器"""
    from config.sandbox_config import DOCKER_CONFIG
    try:
        client = get_docker_client()
        timeout_seconds = DOCKER_CONFIG["timeout"] * ZOMBIE_CONTAINER_TIMEOUT_FACTOR
        now = time.time()
        containers = client.containers.list(all=True, filters={"name": "^sandbox-"})
        
        cleaned_count = 0
        for container in containers:
            try:
                # 修复：分离毫秒/纳秒部分，防止 fromisoformat 崩溃
                # 例如将 "2023-10-25T14:30:00.123456789Z" 变成 "2023-10-25T14:30:00"
                created_time_str = container.attrs["Created"].split(".")[0]
                created_time = datetime.fromisoformat(created_time_str + "+00:00").timestamp()
                if now - created_time > timeout_seconds:
                    container.remove(force=True)
                    cleaned_count += 1
                    logger.info(f"兜底清理超时容器: {container.name}", extra={"trace_id": "system"})
            except Exception as e:
                logger.error(f"兜底清理容器失败 {container.name}: {str(e)}", extra={"trace_id": "system"})
        
        if cleaned_count > 0:
            logger.info(f"兜底清理完成，共清理 {cleaned_count} 个僵尸容器", extra={"trace_id": "system"})
    except Exception as e:
        logger.error(f"兜底清理任务执行失败: {str(e)}", extra={"trace_id": "system"})

def _execute_code_in_docker(
    code: str,
    tenant_id: str,
    workspace_id: str,
    trace_id: str | None = None,
    task_id: str | None = None,
    input_mounts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """
    沙箱执行核心函数

    :param code: 待执行代码
    :param tenant_id: 租户ID
    :param workspace_id: 租户内部空间隔离存储
    :param trace_id: 追踪ID（多智能体流程里由全局黑板生成，这里复用）
    :return: 执行结果
    """
    trace_id = trace_id or generate_uuid()
    log_extra = {"trace_id": trace_id}
    start_time = get_current_timestamp()
    container: Any | None = None
    client: docker.DockerClient | None = None
    log_data = build_log_data(tenant_id, "sandbox_exec", code, trace_id)
    concurrency_incremented = False
    code_file_path = ""
    sandbox_inputs = list(input_mounts or [])
    session_spec = sandbox_session_manager.build_spec(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        input_mounts=sandbox_inputs,
    )
    sandbox_session_manager.create_session(session_spec, trace_id=trace_id)
    policy = load_harness_policy()
    sandbox_policy = dict(policy.get("sandbox") or {})
    require_policy_check = bool(sandbox_policy.get("require_policy_check", True))
    governance_decision = None
    governance_record = None

    try:
        if require_policy_check:
            governance_decision = HarnessGovernor.evaluate_sandbox_execution(
                code=code,
                tenant_id=tenant_id,
                trace_ref=f"governance:sandbox:{trace_id}",
            )
            governance_record = governance_decision.to_record()
        else:
            logger.info("sandbox.require_policy_check=false，跳过 harness 预检", extra=log_extra)

        if governance_decision is not None and not governance_decision.allowed:
            reason = "沙箱执行请求被 harness policy 拒绝"
            log_data.update({
                "exec_result": "fail",
                "error_type": "governance_denied",
                "reason": f"{reason}: {' | '.join(governance_decision.reasons)}",
                "exec_duration_seconds": 0.0,
            })
            logger.error(json.dumps(log_data, ensure_ascii=False), extra=log_extra)
            sandbox_exec_fail_total.labels(error_type="governance_denied").inc()
            return build_sandbox_response(
                success=False,
                trace_id=trace_id,
                duration_seconds=0.0,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                task_id=task_id,
                error=log_data["reason"],
                governance=governance_record,
                session_metadata={"phase": "governance", "error": log_data["reason"]},
            )

        if is_shutdown_requested():
            raise DockerOperationError("沙箱服务正在关闭，拒绝新的执行请求", trace_id)

        validate_code_basic(code, trace_id)
        validate_tenant_id(tenant_id, trace_id)

        current_concurrency = current_tenant_concurrency(tenant_id)
        if current_concurrency >= DOCKER_CONFIG["max_tenant_concurrency"]:
            raise InputValidationError(
                f"租户并发数超过限制，最大支持{DOCKER_CONFIG['max_tenant_concurrency']}并发",
                trace_id
            )
        increment_tenant_concurrency(tenant_id)
        concurrency_incremented = True
        
        logger.info("代码已通过前置审计，开始启动沙箱容器", extra=log_extra)

        client = get_docker_client()
        logger.info("开始启动沙箱容器", extra=log_extra)
        ensure_sandbox_image(client)
        prepared_run = prepare_sandbox_run(
            code=code,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            trace_id=trace_id,
            input_mounts=sandbox_inputs,
        )
        container_name = prepared_run.container_name
        code_file_path = prepared_run.code_file_path

        container = client.containers.run(
            image=DOCKER_CONFIG["image"],
            command=["python", "/app/code.py"],
            volumes=prepared_run.volume_bindings,
            detach=True,
            name=container_name,
            mem_limit=DOCKER_CONFIG["mem_limit"],
            memswap_limit=DOCKER_CONFIG["memswap_limit"],
            cpu_shares=DOCKER_CONFIG["cpu_shares"],
            network_disabled=True,
            user=DOCKER_CONFIG["user"],
            cap_drop=DOCKER_CONFIG["cap_drop"],
            security_opt=DOCKER_CONFIG["security_opt"],
            read_only=True,
            init=True,
            stdin_open=True,
            pids_limit=DOCKER_CONFIG["pids_limit"],
            tmpfs=DOCKER_CONFIG["tmpfs"],
            log_config=DOCKER_CONFIG["log_config"]
        )

        register_running_container(trace_id, container.id)
        sandbox_session_manager.mark_running(
            trace_id,
            container_name=container_name,
            container_id=container.id,
        )
        logger.info(f"沙箱容器启动成功，容器ID: {container.id}", extra=log_extra)
        sandbox_container_create_success_total.inc()

        exit_code, exec_duration = wait_for_container_exit(
            container,
            trace_id=trace_id,
            start_time=start_time,
        )
        logs = collect_container_logs(container)

        if exit_code == 137:
            sandbox_container_oom_total.inc()
            raise CodeExecError(f"容器内存超限被终止（OOM），退出码：{exit_code}", trace_id)
        if exit_code != 0:
            raise CodeExecError(f"代码执行失败，退出码：{exit_code}，错误日志：{logs}", trace_id)

        log_data.update({
            "exec_result": "success",
            "reason": "代码执行成功",
            "exec_duration_seconds": round(exec_duration, 3)
        })
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
            artifacts_dir=str(prepared_run.host_output_dir),
            mounted_inputs=sandbox_inputs,
            governance=governance_record,
            session_metadata={"phase": "completed", "artifacts_dir": str(prepared_run.host_output_dir)},
        )

    except RequestsTimeout:
        exec_duration = get_current_timestamp() - start_time
        error = ExecTimeoutError(f"代码执行超时，最大允许执行{DOCKER_CONFIG['timeout']}秒", trace_id)
        log_data.update({
            "exec_result": "fail",
            "error_type": error.error_type,
            "reason": error.message,
            "exec_duration_seconds": round(exec_duration, 3),
        })
        logger.error(json.dumps(log_data, ensure_ascii=False), extra=log_extra)
        sandbox_exec_fail_total.labels(error_type=error.error_type).inc()

        return build_sandbox_response(
            success=False,
            trace_id=trace_id,
            duration_seconds=round(exec_duration, 3),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            task_id=task_id,
            error=error.message,
            mounted_inputs=sandbox_inputs,
            governance=governance_record,
            session_metadata={"phase": "timeout", "error": error.message},
        )

    except SandboxBaseError as e:
        exec_duration = get_current_timestamp() - start_time
        log_data.update({
            "exec_result": "fail",
            "error_type": e.error_type,
            "reason": e.message,
            "exec_duration_seconds": round(exec_duration, 3),
        })
        logger.error(json.dumps(log_data, ensure_ascii=False), extra=log_extra)
        sandbox_exec_fail_total.labels(error_type=e.error_type).inc()

        return build_sandbox_response(
            success=False,
            trace_id=trace_id,
            duration_seconds=round(exec_duration, 3),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            task_id=task_id,
            error=e.message,
            mounted_inputs=sandbox_inputs,
            governance=governance_record,
            session_metadata={"phase": e.error_type, "error": e.message},
        )

    except ContainerError as e:
        exec_duration = get_current_timestamp() - start_time
        error_type = "container_start_error"
        container_logs = e.container.logs().decode("utf-8", errors="replace").strip() if e.container else "无容器日志"
        reason = f"容器启动失败，退出码：{e.exit_status}，日志：{container_logs}"
        log_data.update({
            "exec_result": "fail",
            "error_type": error_type,
            "reason": reason,
            "exec_duration_seconds": round(exec_duration, 3),
        })
        logger.error(json.dumps(log_data, ensure_ascii=False), extra=log_extra)
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
            session_metadata={"phase": error_type, "error": reason},
        )

    except DockerException as e:
        exec_duration = get_current_timestamp() - start_time
        error = DockerOperationError(f"Docker服务异常：{str(e)}", trace_id)
        log_data.update({
            "exec_result": "fail",
            "error_type": error.error_type,
            "reason": error.message,
            "exec_duration_seconds": round(exec_duration, 3),
        })
        logger.error(json.dumps(log_data, ensure_ascii=False), extra=log_extra)
        sandbox_container_create_fail_total.labels(error_type=error.error_type).inc()
        sandbox_exec_fail_total.labels(error_type=error.error_type).inc()
        return build_sandbox_response(
            success=False,
            trace_id=trace_id,
            duration_seconds=round(exec_duration, 3),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            task_id=task_id,
            error=error.message,
            mounted_inputs=sandbox_inputs,
            governance=governance_record,
            session_metadata={"phase": error.error_type, "error": error.message},
        )

    except Exception as e:
        exec_duration = get_current_timestamp() - start_time
        error_type = "unknown_exception"
        error = traceback.format_exc()
        reason = f"未知执行异常：{str(e)}; 具体报错：{error}"
        log_data.update({
            "exec_result": "fail",
            "error_type": error_type,
            "reason": reason,
            "exec_duration_seconds": round(exec_duration, 3),
        })
        logger.exception(json.dumps(log_data, ensure_ascii=False), extra=log_extra)
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
            session_metadata={"phase": error_type, "error": reason},
        )

    finally:
        # 增加判空，避免文件路径未定义时报错
        removed_container = cleanup_sandbox_run(
            code_file_path=code_file_path,
            container=container,
        )
        if code_file_path:
            logger.debug(f"临时代码文件已清理: {code_file_path}", extra=log_extra)
        if container and not removed_container:
            logger.error("沙箱容器清理失败", extra=log_extra)
            sandbox_container_remove_fail_total.inc()

        unregister_running_container(trace_id)

        if concurrency_incremented:
            decrement_tenant_concurrency(tenant_id)

def execute_in_sandbox_with_audit(
    code: str,
    tenant_id: str,
    workspace_id: str = "default_ws",
    task_id: str | None = None,
    input_mounts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """
    【独立服务入口】一站式沙箱执行（包含完整校验+审计+执行）
    
    适用场景：不需要多智能体、直接用沙箱的场景
    
    :param code: 待执行代码
    :param tenant_id: 租户ID
    :param workspace_id: 租户内部空间隔离
    :return: 执行结果
    """
    import json
    import traceback

    from src.common import generate_uuid, get_current_timestamp, get_logger
    from src.sandbox.ast_auditor import audit_code
    from src.sandbox.exceptions import AuditFailError, DockerOperationError, SandboxBaseError
    from src.sandbox.metrics import sandbox_exec_fail_total
    from src.sandbox.utils import build_log_data, validate_code, validate_tenant_id

    logger = get_logger(__name__)
    trace_id = generate_uuid()
    log_extra = {"trace_id": trace_id, "tenant_id": tenant_id, "workspace_id": workspace_id}
    log_data = build_log_data(tenant_id, "sandbox_exec_with_audit", code, trace_id)
    start_time = get_current_timestamp()

    try:
        # 服务关闭拦截
        if is_shutdown_requested():
            raise DockerOperationError("沙箱服务正在关闭，拒绝新的执行请求", trace_id)
        
        # 1. 输入合法性校验
        logger.info("开始代码输入合法性校验", extra=log_extra)
        validate_code(code, trace_id)
        validate_tenant_id(tenant_id, trace_id)

        # 2. AST安全审计
        logger.info("开始AST代码安全审计", extra=log_extra)
        audit_result = audit_code(code, tenant_id, trace_id=trace_id)
        if not audit_result["safe"]:
            raise AuditFailError(
                message=audit_result["reason"],
                trace_id=trace_id,
                risk_type=audit_result["risk_type"] or "audit_fail"
            )

        # 3. 调用核心执行器
        logger.info("AST审计通过，开始执行代码", extra=log_extra)
        return _execute_code_in_docker(
            code,
            tenant_id,
            trace_id=trace_id,
            workspace_id=workspace_id,
            task_id=task_id,
            input_mounts=input_mounts,
        )

    # 统一捕获沙箱业务异常，包装为标准返回格式
    except SandboxBaseError as e:
        exec_duration = get_current_timestamp() - start_time
        log_data.update({
            "exec_result": "fail",
            "error_type": e.error_type,
            "reason": e.message,
            "exec_duration_seconds": round(exec_duration, 3),
        })
        logger.error(json.dumps(log_data, ensure_ascii=False), extra=log_extra)
        sandbox_exec_fail_total.labels(error_type=e.error_type).inc()
        return build_preflight_failure_response(
            tenant_id=tenant_id,
            trace_id=trace_id,
            duration_seconds=round(exec_duration, 3),
            error=e.message,
        )

    # 捕获未知异常，兜底处理
    except Exception as e:
        exec_duration = get_current_timestamp() - start_time
        error_type = "unknown_exception"
        error_trace = traceback.format_exc()
        reason = f"沙箱执行前置处理异常：{str(e)}; 具体报错：{error_trace}"
        log_data.update({
            "exec_result": "fail",
            "error_type": error_type,
            "reason": reason,
            "exec_duration_seconds": round(exec_duration, 3),
        })
        logger.exception(json.dumps(log_data, ensure_ascii=False), extra=log_extra)
        sandbox_exec_fail_total.labels(error_type=error_type).inc()
        return build_preflight_failure_response(
            tenant_id=tenant_id,
            trace_id=trace_id,
            duration_seconds=round(exec_duration, 3),
            error=reason,
        )


def execute_in_sandbox(
    code: str,
    tenant_id: str,
    workspace_id: str = "default_ws",
    task_id: str | None = None,
    input_mounts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Raw sandbox execution without the extra AST audit wrapper."""
    return _execute_code_in_docker(
        code,
        tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        input_mounts=input_mounts,
    )

async def execute_in_sandbox_async(
    code: str,
    tenant_id: str,
    workspace_id: str = "default_ws",
    use_audit: bool = False,
    task_id: str | None = None,
    input_mounts: list[dict[str, str]] | None = None,
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
    else:
        return await loop.run_in_executor(
            executor_pool,
            _execute_code_in_docker,
            code,
            tenant_id,
            workspace_id,
            None,
            task_id,
            input_mounts,
        )

# -------------------------- 初始化信号处理 --------------------------
def init_signal_handlers() -> None:
    """初始化信号处理器（支持多信号）"""
    signal.signal(signal.SIGINT, signal_handler)    # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)   # 终止信号
    signal.signal(signal.SIGQUIT, signal_handler)   # 退出信号
    logger.info("信号处理器初始化完成", extra={"trace_id": "system"})

# -------------------------- 后台守护任务 --------------------------
def start_zombie_cleaner_daemon():
    """启动全局唯一的僵尸容器清理后台任务"""
    if not should_start_zombie_cleaner():
        logger.info("僵尸容器清理守护线程已存在，跳过重复启动", extra={"trace_id": "system"})
        return

    def cleaner_loop():
        while True:
            time.sleep(ZOMBIE_CLEAN_INTERVAL)
            trace_id = "zombie-cleaner-" + generate_uuid()[:8]
            logger.info("触发定时轮询：扫描并清理僵尸容器", extra={"trace_id": trace_id})
            try:
                clean_zombie_containers()
            except Exception as e:
                logger.error(
                    f"僵尸容器清理任务执行失败: {str(e)}",
                    extra={"trace_id": trace_id},
                    exc_info=True
                )
            
    # daemon=True 保证主进程退出时线程自动销毁；命名便于运维排查
    cleaner_thread = threading.Thread(
        target=cleaner_loop,
        daemon=True,
        name="GlobalZombieContainerCleaner"
    )
    cleaner_thread.start()
    logger.info("全局僵尸容器清理守护线程已启动", extra={"trace_id": "system"})
