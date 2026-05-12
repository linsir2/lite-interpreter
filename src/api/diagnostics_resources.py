"""Diagnostics and conformance helpers for runtime/system inspection."""

from __future__ import annotations

import os
import sys
from typing import Any

from config.settings import DYNAMIC_NATIVE_MAX_STEPS, DYNAMIC_NATIVE_MODEL, DYNAMIC_NATIVE_TIMEOUT, PROJECT_ROOT

from src.api.auth import auth_enabled
from src.api.services.task_flow_service import get_startup_recovery_status
from src.blackboard import build_strict_state_report
from src.common.llm_client import LiteLLMClient
from src.compiler.kag.lexicon import LexiconCompiler
from src.mcp_gateway import default_mcp_server
from src.runtime.guidance_runner import probe_guidance_runtime
from src.sandbox.security_explainer import build_security_policy_summary
from src.skillnet.preset_skills import load_preset_skills
from src.storage.graph_client import neo4j_client
from src.storage.postgres_client import pg_client
from src.storage.repository.audit_repo import AuditRepo
from src.storage.repository.memory_repo import MemoryRepo
from src.storage.repository.state_repo import StateRepo
from src.storage.vector_client import qdrant_client


def build_diagnostics_report() -> dict[str, Any]:
    current_prefix = os.environ.get("CONDA_PREFIX", "")
    expected_suffix = os.path.join("envs", "lite_interpreter")
    conda_env_ok = current_prefix.endswith(expected_suffix)

    mcp_tools = default_mcp_server.list_tools()
    preset_skills = load_preset_skills()
    state_repo_status = StateRepo.status()
    memory_repo_status = MemoryRepo.status()
    startup_recovery = get_startup_recovery_status()
    security_policy = build_security_policy_summary()
    strict_state = build_strict_state_report()
    llm_health = {
        alias: status.model_dump(mode="json") for alias, status in LiteLLMClient.probe_required_aliases().items()
    }
    try:
        compiled = LexiconCompiler.compile()
        compiler_health = {
            "lexicon_compiled": True,
            "lexicon_surface_count": len(compiled.entries_by_surface),
        }
    except Exception as exc:
        compiler_health = {
            "lexicon_compiled": False,
            "error": str(exc),
        }

    return {
        "service": "lite-interpreter-api",
        "project_root": str(PROJECT_ROOT),
        "python": {
            "version": sys.version.split()[0],
            "major": sys.version_info.major,
            "minor": sys.version_info.minor,
        },
        "environment": {
            "conda_prefix": current_prefix or None,
            "lite_interpreter_env_active": conda_env_ok,
            "runtime_mode": "native",
            "api_auth_enabled": auth_enabled(),
        },
        "dependencies": {
            "postgres_available": pg_client.engine is not None,
            "postgres_driver": getattr(pg_client, "driver_name", None),
            "postgres_driver_error": getattr(pg_client, "driver_error", None),
            "qdrant_available": qdrant_client.client is not None,
            "neo4j_available": neo4j_client.driver is not None,
        },
        "repositories": {
            "state_repo": state_repo_status,
            "memory_repo": memory_repo_status,
            "audit_repo": AuditRepo.status(),
        },
        "llm_health": llm_health,
        "guidance_health": probe_guidance_runtime(),
        "compiler_health": compiler_health,
        "security_policy": security_policy,
        "strict_state": strict_state,
        "startup_recovery": startup_recovery,
        "dynamic_exploration": {
            "model": DYNAMIC_NATIVE_MODEL,
            "max_steps": DYNAMIC_NATIVE_MAX_STEPS,
            "timeout_seconds": DYNAMIC_NATIVE_TIMEOUT,
        },
        "capabilities": {
            "mcp_tool_count": len(mcp_tools),
            "mcp_tools": [tool["name"] for tool in mcp_tools],
            "preset_skill_count": len(preset_skills),
            "preset_skill_names": [skill.name for skill in preset_skills],
        },
    }


def build_conformance_report() -> dict[str, Any]:
    mcp_tools = default_mcp_server.list_tools()
    tool_names = sorted(tool["name"] for tool in mcp_tools)

    return {
        "status": "ok",
        "summary": {
            "execution_event_model": "canonical",
            "execution_resource_layer": True,
            "runtime_backend": "native_exploration_loop",
            "tool_count": len(tool_names),
        },
        "tools": tool_names,
    }
