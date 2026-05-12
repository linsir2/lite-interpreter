"""Bounded static evidence collection for single-pass external verification."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config.settings import OUTPUT_DIR, STATIC_EVIDENCE_ALLOWED_DOMAINS

from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.global_blackboard import global_blackboard
from src.blackboard.schema import GlobalStatus
from src.common import get_logger
from src.common.control_plane import (
    ensure_evidence_plan,
    ensure_execution_strategy,
    ensure_static_evidence_bundle,
    ensure_static_evidence_request,
)
from src.dag_engine.graphstate import DagGraphState
from src.harness.governor import HarnessGovernor
from src.mcp_gateway import default_mcp_client

logger = get_logger(__name__)


def _build_evidence_request(*, query: str, evidence_plan) -> dict[str, Any]:
    return ensure_static_evidence_request(
        {
            "query": query,
            "research_mode": evidence_plan.research_mode,
            "search_queries": evidence_plan.search_queries or ([query] if evidence_plan.research_mode == "single_pass" else []),
            "urls": evidence_plan.urls,
            "allowed_domains": evidence_plan.allowed_domains or list(STATIC_EVIDENCE_ALLOWED_DOMAINS),
            "allowed_capabilities": evidence_plan.allowed_capabilities or ["web_search", "web_fetch"],
            "max_results": evidence_plan.max_results,
            "timeout_seconds": evidence_plan.timeout_seconds,
            "max_bytes": evidence_plan.max_bytes,
        }
    ).model_dump(mode="json")


def _persist_bundle_file(*, tenant_id: str, workspace_id: str, task_id: str, bundle_payload: dict[str, Any]) -> dict[str, str]:
    output_dir = Path(OUTPUT_DIR).resolve() / tenant_id / workspace_id / f"static-evidence-{task_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / "static_evidence.json"
    bundle_path.write_text(json.dumps(bundle_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "kind": "static_evidence",
        "host_path": str(bundle_path),
        "container_path": f"/app/inputs/static_evidence_{task_id}.json",
        "file_name": bundle_path.name,
    }


def static_evidence_node(state: DagGraphState) -> dict[str, Any]:
    tenant_id = state["tenant_id"]
    task_id = state["task_id"]
    workspace_id = str(state.get("workspace_id", "default_ws"))

    global_blackboard.update_global_status(
        task_id=task_id,
        new_status=GlobalStatus.RETRIEVING,
        sub_status="正在执行受控外部取证",
    )

    exec_data = execution_blackboard.read(tenant_id, task_id)
    if not exec_data:
        logger.warning("[StaticEvidence] missing execution context for task %s", task_id)
        return {"next_actions": ["coder"]}

    strategy = ensure_execution_strategy(exec_data.static.execution_strategy or {})
    evidence_plan = ensure_evidence_plan(
        strategy.evidence_plan,
        research_mode=strategy.research_mode,
    )
    if strategy.research_mode != "single_pass":
        return {"next_actions": ["coder"]}

    decision = HarnessGovernor.evaluate_tool_request(
        requested_tools=evidence_plan.allowed_capabilities or ["web_search", "web_fetch"],
        profile_name="static_evidence",
        trace_ref=f"static-evidence:{task_id}",
    )
    exec_data.control.decision_log = [*list(exec_data.control.decision_log or []), decision.to_record()]
    if not decision.allowed:
        bundle = ensure_static_evidence_bundle(
            {
                "request": _build_evidence_request(query=state["input_query"], evidence_plan=evidence_plan),
                "errors": ["static evidence request denied by governance"],
            }
        )
        exec_data.static.static_evidence_bundle = bundle
        exec_data.static.latest_error_traceback = "static evidence request denied by governance"
        execution_blackboard.write(tenant_id, task_id, exec_data)
        execution_blackboard.persist(tenant_id, task_id)
        return {
            "static_evidence_bundle": bundle.model_dump(mode="json"),
            "blocked": True,
            "block_reason": "static evidence request denied by governance",
            "next_actions": ["coder"],
        }

    request_payload = _build_evidence_request(query=state["input_query"], evidence_plan=evidence_plan)
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    allowed_domains = list(request_payload.get("allowed_domains") or [])

    for search_query in list(request_payload.get("search_queries") or [])[:2]:
        try:
            response = default_mcp_client.call_tool(
                "web_search",
                {
                    "query": search_query,
                    "allowlist": allowed_domains,
                    "limit": int(request_payload.get("max_results", 3) or 3),
                },
                context={"tenant_id": tenant_id, "task_id": task_id, "workspace_id": workspace_id},
            )
            for item in list((response or {}).get("items") or [])[: int(request_payload.get("max_results", 3) or 3)]:
                records.append(
                    {
                        "source_type": "search_result",
                        "title": str(item.get("title") or search_query),
                        "url": str(item.get("url") or ""),
                        "domain": str(item.get("domain") or ""),
                        "snippet": str(item.get("snippet") or ""),
                        "status": "ok",
                    }
                )
        except Exception as exc:
            errors.append(f"web_search failed: {exc}")

    for url in list(request_payload.get("urls") or [])[:3]:
        try:
            response = default_mcp_client.call_tool(
                "web_fetch",
                {
                    "url": url,
                    "allowlist": allowed_domains,
                    "timeout_seconds": int(request_payload.get("timeout_seconds", 8) or 8),
                    "max_bytes": int(request_payload.get("max_bytes", 200_000) or 200_000),
                },
                context={"tenant_id": tenant_id, "task_id": task_id, "workspace_id": workspace_id},
            )
            records.append(
                {
                    "source_type": "fetched_document",
                    "title": str(response.get("url") or url),
                    "url": str(response.get("url") or url),
                    "domain": str(response.get("domain") or ""),
                    "snippet": str(response.get("text") or "")[:400],
                    "content_type": str(response.get("content_type") or ""),
                    "text": str(response.get("text") or ""),
                    "status": "ok",
                }
            )
        except Exception as exc:
            errors.append(f"web_fetch failed: {exc}")

    bundle = ensure_static_evidence_bundle(
        {
            "request": request_payload,
            "records": records,
            "errors": errors,
        }
    )
    exec_data.static.static_evidence_bundle = bundle
    strategy = strategy.model_copy(update={"evidence_plan": evidence_plan})
    exec_data.static.execution_strategy = strategy
    mount = _persist_bundle_file(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        bundle_payload=bundle.model_dump(mode="json"),
    )
    execution_blackboard.write(tenant_id, task_id, exec_data)
    execution_blackboard.persist(tenant_id, task_id)
    input_mounts = list(state.get("input_mounts") or [])
    input_mounts.append(mount)
    return {
        "static_evidence_bundle": bundle.model_dump(mode="json"),
        "input_mounts": input_mounts,
        "next_actions": ["coder"],
    }
