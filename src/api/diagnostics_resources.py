"""Diagnostics and conformance helpers for runtime/system inspection."""
from __future__ import annotations

import importlib
import os
import sys
from typing import Any

import httpx

from config.settings import DEERFLOW_RUNTIME_MODE, DEERFLOW_SIDECAR_URL, PROJECT_ROOT
from src.api.routers.analysis_router import get_startup_recovery_status
from src.mcp_gateway import default_mcp_server
from src.skillnet.preset_skills import load_preset_skills
from src.dynamic_engine.runtime_registry import runtime_registry
from src.storage.graph_client import neo4j_client
from src.storage.postgres_client import pg_client
from src.storage.repository.skill_repo import SkillRepo
from src.storage.repository.state_repo import StateRepo
from src.storage.vector_client import qdrant_client


def _module_available(module_name: str) -> bool:
    try:
        importlib.import_module(module_name)
        return True
    except Exception:
        return False


def _probe_sidecar_health(sidecar_url: str) -> dict[str, Any]:
    if not str(sidecar_url).strip():
        return {"configured": False, "reachable": False, "status_code": None}
    try:
        response = httpx.get(f"{sidecar_url.rstrip('/')}/health", timeout=2.0)
        return {
            "configured": True,
            "reachable": response.is_success,
            "status_code": response.status_code,
        }
    except Exception as exc:
        return {
            "configured": True,
            "reachable": False,
            "status_code": None,
            "error": str(exc),
        }


def build_diagnostics_report() -> dict[str, Any]:
    current_prefix = os.environ.get("CONDA_PREFIX", "")
    expected_suffix = os.path.join("envs", "lite_interpreter")
    conda_env_ok = current_prefix.endswith(expected_suffix)

    deerflow_sidecar_configured = bool(str(DEERFLOW_SIDECAR_URL).strip())
    deerflow_client_importable = _module_available("deerflow.client")
    sidecar_health = _probe_sidecar_health(DEERFLOW_SIDECAR_URL)
    mcp_tools = default_mcp_server.list_tools()
    preset_skills = load_preset_skills()
    state_repo_status = StateRepo.status()
    skill_repo_status = SkillRepo.status()
    startup_recovery = get_startup_recovery_status()

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
            "runtime_mode": DEERFLOW_RUNTIME_MODE,
            "sidecar_url": DEERFLOW_SIDECAR_URL or None,
        },
        "dependencies": {
            "deerflow_client_importable": deerflow_client_importable,
            "sidecar_configured": deerflow_sidecar_configured,
            "postgres_available": pg_client.engine is not None,
            "qdrant_available": qdrant_client.client is not None,
            "neo4j_available": neo4j_client.driver is not None,
        },
        "repositories": {
            "state_repo": state_repo_status,
            "skill_repo": skill_repo_status,
        },
        "runtime": {
            "sidecar_health": sidecar_health,
        },
        "startup_recovery": startup_recovery,
        "capabilities": {
            "mcp_tool_count": len(mcp_tools),
            "mcp_tools": [tool["name"] for tool in mcp_tools],
            "preset_skill_count": len(preset_skills),
            "preset_skill_names": [skill.name for skill in preset_skills],
        },
    }


def build_conformance_report() -> dict[str, Any]:
    manifests = runtime_registry.list_manifests()
    runtime_summaries = []

    for manifest in manifests:
        domain_map = {domain.domain_id: domain for domain in manifest.domains}
        runtime_summaries.append(
            {
                "runtime_id": manifest.runtime_id,
                "display_name": manifest.display_name,
                "supports_streaming": bool(domain_map.get("streaming") and domain_map["streaming"].supported),
                "supports_attach_stream": bool(manifest.metadata.get("supports_attach_stream")),
                "supports_resume": bool(manifest.metadata.get("supports_resume")),
                "supports_artifacts": bool(domain_map.get("artifacts") and domain_map["artifacts"].supported),
                "supports_subagents": bool(domain_map.get("subagents") and domain_map["subagents"].supported),
                "supports_final_code_execution": bool(
                    domain_map.get("sandbox_execution") and domain_map["sandbox_execution"].supported
                ),
                "limitations": manifest.limitations,
            }
        )

    return {
        "status": "ok",
        "summary": {
            "runtime_count": len(runtime_summaries),
            "execution_event_model": "canonical",
            "execution_resource_layer": True,
            "runtime_capability_manifest": True,
        },
        "runtimes": runtime_summaries,
    }
