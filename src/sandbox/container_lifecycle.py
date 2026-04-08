"""Container lifecycle helpers for sandbox execution."""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import docker
from config.sandbox_config import CONTAINER_NAME_PREFIX, DOCKER_CONFIG
from config.settings import LOG_MAX_LENGTH, PROJECT_ROOT
from docker.errors import ImageNotFound
from requests.exceptions import ConnectionError, ReadTimeout
from requests.exceptions import Timeout as RequestsTimeout

from src.common import get_current_timestamp, truncate_string
from src.sandbox.exceptions import ExecTimeoutError


@dataclass(frozen=True)
class PreparedSandboxRun:
    """Filesystem and bind-mount preparation for one sandbox execution."""

    container_name: str
    host_output_dir: Path
    code_file_path: str
    volume_bindings: dict[str, dict[str, str]]


def ensure_sandbox_image(client: docker.DockerClient) -> None:
    """Ensure the configured sandbox image is already available locally."""
    try:
        client.images.get(DOCKER_CONFIG["image"])
    except ImageNotFound as exc:
        raise RuntimeError(f"沙箱基础镜像缺失，为保证安全，拒绝运行时拉取: {str(exc)}") from exc


def prepare_sandbox_run(
    *,
    code: str,
    tenant_id: str,
    workspace_id: str,
    trace_id: str,
    input_mounts: list[dict[str, str]] | None = None,
) -> PreparedSandboxRun:
    """Prepare temp code file, output directory, and Docker volume bindings."""
    container_name = f"{CONTAINER_NAME_PREFIX}{tenant_id}-{int(get_current_timestamp() * 1000)}-{trace_id[:8]}"
    host_output_dir = PROJECT_ROOT / "data" / "outputs" / tenant_id / workspace_id / trace_id
    host_output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", encoding="utf-8", delete=False) as handle:
        handle.write(code)
        code_file_path = handle.name

    volume_bindings: dict[str, dict[str, str]] = {
        code_file_path: {"bind": "/app/code.py", "mode": "ro"},
        str(host_output_dir): {"bind": "/app/outputs", "mode": "rw"},
    }
    for mount in input_mounts or []:
        host_path = str(mount.get("host_path", "")).strip()
        container_path = str(mount.get("container_path", "")).strip()
        if not host_path or not container_path or not os.path.exists(host_path):
            continue
        volume_bindings[host_path] = {"bind": container_path, "mode": "ro"}

    return PreparedSandboxRun(
        container_name=container_name,
        host_output_dir=host_output_dir,
        code_file_path=code_file_path,
        volume_bindings=volume_bindings,
    )


def wait_for_container_exit(
    container: Any,
    *,
    trace_id: str,
    start_time: float,
) -> tuple[int, float]:
    """Wait for container completion and return exit code plus duration."""
    try:
        wait_result = container.wait(timeout=DOCKER_CONFIG["timeout"])
        exit_code = int(wait_result["StatusCode"])
        duration = get_current_timestamp() - start_time
        return exit_code, duration
    except (RequestsTimeout, ConnectionError, ReadTimeout) as exc:
        try:
            container.kill()
        except Exception:
            pass
        raise ExecTimeoutError(f"沙箱执行超时，已强制熔断:{str(exc)}", trace_id) from exc


def collect_container_logs(container: Any) -> str:
    """Collect and truncate container logs for user-facing results."""
    raw_logs = container.logs(tail=1000).decode("utf-8", errors="replace").strip()
    logs = truncate_string(raw_logs)
    if len(raw_logs) > LOG_MAX_LENGTH:
        logs += f"\n[日志已截断，超出最大长度{LOG_MAX_LENGTH}字节]"
    return logs


def cleanup_sandbox_run(
    *,
    code_file_path: str,
    container: Any | None,
) -> bool:
    """Clean up temp code file and best-effort remove the container."""
    removed_container = True
    if code_file_path and os.path.exists(code_file_path):
        try:
            os.remove(code_file_path)
        except Exception:
            pass
    if container is not None:
        try:
            container.remove(force=True)
        except Exception:
            removed_container = False
    return removed_container
