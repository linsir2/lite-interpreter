"""Task console page and result formatting helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from src.frontend.auth_client import api_auth_headers, render_auth_panel
from src.frontend.components.file_uploader import render_file_uploader
from src.frontend.components.status_stream import render_status_stream
from src.frontend.components.workspace_sections import (
    render_analysis_body as render_workspace_analysis_body,
)
from src.frontend.components.workspace_sections import (
    render_technical_details as render_workspace_technical_details,
)
from src.frontend.components.workspace_shell import (
    render_technical_details_shell,
    render_workspace_sidebar,
    render_workspace_summary,
)


def summarize_result_header(task_result: dict[str, Any]) -> dict[str, str]:
    workspace = dict(task_result.get("workspace") or {})
    primary = dict(workspace.get("primary") or {})
    final_response = task_result.get("response") or task_result.get("final_response") or {}
    status = dict(task_result.get("status") or {})
    return {
        "mode": str(
            primary.get("mode")
            or final_response.get("mode")
            or status.get("global_status")
            or task_result.get("global_status")
            or "unknown"
        ),
        "headline": str(primary.get("headline") or final_response.get("headline") or "No headline available"),
        "answer": str(
            primary.get("answer")
            or final_response.get("answer")
            or final_response.get("headline")
            or "No answer available"
        ),
    }


def select_stream_target(task_result: dict[str, Any] | None, *, preferred_execution_id: str = "") -> dict[str, str]:
    executions = list((task_result or {}).get("executions") or [])
    task_payload = dict((task_result or {}).get("task") or {})
    if executions:
        execution_id = ""
        if preferred_execution_id:
            for execution in executions:
                if str(execution.get("execution_id", "")).strip() == preferred_execution_id:
                    execution_id = preferred_execution_id
                    break
        if not execution_id:
            execution_id = str(executions[0].get("execution_id", "")).strip()
        if execution_id:
            return {
                "stream_kind": "execution",
                "execution_id": execution_id,
                "task_id": str(task_payload.get("task_id") or (task_result or {}).get("task_id", "")),
            }
    return {
        "stream_kind": "task",
        "execution_id": "",
        "task_id": str(task_payload.get("task_id") or (task_result or {}).get("task_id", "")),
    }


def fetch_json_payload(url: str, *, timeout: float = 20.0, api_token: str = "") -> dict[str, Any]:
    headers = api_auth_headers(api_token)
    response = httpx.get(url, timeout=timeout, headers=headers)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _scoped_url(base_url: str, path: str, *, tenant_id: str, workspace_id: str) -> str:
    query = urlencode({"tenant_id": tenant_id, "workspace_id": workspace_id})
    return f"{base_url.rstrip('/')}{path}?{query}"


def fetch_task_console_bundle(
    api_base_url: str,
    task_id: str,
    *,
    tenant_id: str,
    workspace_id: str,
    timeout: float = 20.0,
    api_token: str = "",
) -> dict[str, Any]:
    base_url = api_base_url.rstrip("/")
    try:
        result_payload = fetch_json_payload(
            _scoped_url(base_url, f"/api/tasks/{task_id}/workspace", tenant_id=tenant_id, workspace_id=workspace_id),
            timeout=timeout,
            api_token=api_token,
        )
    except Exception:
        result_payload = fetch_json_payload(
            _scoped_url(base_url, f"/api/tasks/{task_id}/result", tenant_id=tenant_id, workspace_id=workspace_id),
            timeout=timeout,
            api_token=api_token,
        )

    executions: list[dict[str, Any]] = list(result_payload.get("executions") or [])
    tool_calls: list[dict[str, Any]] = list(result_payload.get("tool_calls") or [])
    execution_artifacts: dict[str, list[dict[str, Any]]] = {}
    if not executions:
        try:
            executions_payload = fetch_json_payload(
                _scoped_url(base_url, f"/api/tasks/{task_id}/executions", tenant_id=tenant_id, workspace_id=workspace_id),
                timeout=timeout,
                api_token=api_token,
            )
            executions = list(executions_payload.get("executions") or [])
        except Exception:
            executions = []
    if not tool_calls:
        for execution in executions:
            execution_id = str(execution.get("execution_id", "")).strip()
            if not execution_id:
                continue
            try:
                tool_calls_payload = fetch_json_payload(
                    _scoped_url(
                        base_url,
                        f"/api/executions/{execution_id}/tool-calls",
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                    ),
                    timeout=timeout,
                    api_token=api_token,
                )
            except Exception:
                continue
            tool_calls.extend(list(tool_calls_payload.get("tool_calls") or []))
            try:
                artifacts_payload = fetch_json_payload(
                    _scoped_url(
                        base_url,
                        f"/api/executions/{execution_id}/artifacts",
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                    ),
                    timeout=timeout,
                    api_token=api_token,
                )
                execution_artifacts[execution_id] = list(artifacts_payload.get("artifacts") or [])
            except Exception:
                execution_artifacts[execution_id] = []
    elif executions:
        for execution in executions:
            execution_id = str(execution.get("execution_id", "")).strip()
            if not execution_id:
                continue
            try:
                artifacts_payload = fetch_json_payload(
                    _scoped_url(
                        base_url,
                        f"/api/executions/{execution_id}/artifacts",
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                    ),
                    timeout=timeout,
                    api_token=api_token,
                )
                execution_artifacts[execution_id] = list(artifacts_payload.get("artifacts") or [])
            except Exception:
                execution_artifacts[execution_id] = []

    enriched = dict(result_payload)
    enriched["executions"] = executions
    enriched["tool_calls"] = tool_calls
    enriched["execution_artifacts"] = execution_artifacts
    return enriched


def fetch_workspace_assets(
    api_base_url: str,
    *,
    tenant_id: str,
    workspace_id: str,
    timeout: float = 20.0,
    api_token: str = "",
) -> list[dict[str, Any]]:
    payload = fetch_json_payload(
        _scoped_url(api_base_url.rstrip("/"), "/api/knowledge/assets", tenant_id=tenant_id, workspace_id=workspace_id),
        timeout=timeout,
        api_token=api_token,
    )
    return list(payload.get("assets") or [])


def fetch_execution_artifact_bytes(
    api_base_url: str,
    *,
    execution_id: str,
    artifact_id: str,
    tenant_id: str,
    workspace_id: str,
    api_token: str = "",
    timeout: float = 20.0,
) -> tuple[bytes, str] | None:
    headers = api_auth_headers(api_token) or {}
    response = httpx.get(
        _scoped_url(
            api_base_url.rstrip("/"),
            f"/api/executions/{execution_id}/artifacts/{artifact_id}",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        ),
        timeout=timeout,
        headers=headers,
    )
    if response.is_error:
        return None
    return response.content, str(response.headers.get("content-type") or "application/octet-stream")


def collect_result_sections(task_result: dict[str, Any]) -> dict[str, list[Any]]:
    workspace = dict(task_result.get("workspace") or {})
    final_response = task_result.get("response") or task_result.get("final_response") or {}
    knowledge = dict(task_result.get("knowledge") or {})
    skills = dict(task_result.get("skills") or {})
    status = dict(task_result.get("status") or {})
    analysis_brief = dict(
        workspace.get("knowledge", {}).get("analysis_brief")
        or (final_response.get("details") or {}).get("analysis_brief")
        or knowledge.get("analysis_brief")
        or {}
    )
    knowledge_snapshot = dict(
        workspace.get("knowledge", {}).get("knowledge_snapshot")
        or (final_response.get("details") or {}).get("knowledge_snapshot")
        or knowledge.get("knowledge_snapshot")
        or task_result.get("knowledge_snapshot")
        or {}
    )
    compiled_knowledge = dict(
        workspace.get("knowledge", {}).get("compiled_knowledge")
        or (final_response.get("details") or {}).get("compiled_knowledge")
        or {}
    )
    return {
        "findings": list(final_response.get("key_findings") or []),
        "outputs": list(final_response.get("outputs") or []),
        "caveats": list(final_response.get("caveats") or []),
        "evidence_refs": list(
            (workspace.get("evidence") or {}).get("evidence_refs") or final_response.get("evidence_refs") or []
        ),
        "executions": list(task_result.get("executions") or []),
        "tool_calls": list(task_result.get("tool_calls") or []),
        "structured_inputs": list((workspace.get("inputs") or {}).get("structured_datasets") or []),
        "document_inputs": list((workspace.get("inputs") or {}).get("business_documents") or []),
        "parser_reports": list((final_response.get("details") or {}).get("parser_reports") or []),
        "rule_checks": list((final_response.get("details") or {}).get("rule_checks") or []),
        "metric_checks": list((final_response.get("details") or {}).get("metric_checks") or []),
        "filter_checks": list((final_response.get("details") or {}).get("filter_checks") or []),
        "analysis_brief": [analysis_brief] if analysis_brief else [],
        "knowledge_snapshot": [knowledge_snapshot] if knowledge_snapshot else [],
        "compiled_knowledge": [compiled_knowledge] if compiled_knowledge else [],
        "historical_skill_matches": list(
            skills.get("historical_matches") or task_result.get("historical_skill_matches") or []
        ),
        "used_historical_skills": list((final_response.get("details") or {}).get("used_historical_skills") or []),
        "task_lease": [dict(status.get("task_lease") or task_result.get("task_lease") or {})]
        if (status.get("task_lease") or task_result.get("task_lease"))
        else [],
    }


def build_output_cards(outputs: list[dict[str, Any]]) -> list[dict[str, str]]:
    cards: list[dict[str, str]] = []
    icon_map = {
        "dataset": "TABLE",
        "document": "DOC",
        "artifact": "FILE",
        "sandbox_output": "DIR",
    }
    for output in outputs:
        output_type = str(output.get("type") or "output")
        name = str(output.get("name") or "unknown")
        summary = str(output.get("summary") or "")
        cards.append(
            {
                "type": output_type,
                "icon": icon_map.get(output_type, "ITEM"),
                "title": name,
                "subtitle": summary or "No summary available.",
            }
        )
    return cards


def describe_output_asset(output: dict[str, Any]) -> dict[str, Any]:
    path_value = str(output.get("path") or "").strip()
    path_obj = Path(path_value) if path_value else None
    suffix = path_obj.suffix.lower() if path_obj else ""
    preview_kind = "none"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        preview_kind = "image"
    elif suffix in {".json", ".txt", ".md", ".csv", ".log"}:
        preview_kind = "text"
    elif output.get("type") == "sandbox_output":
        preview_kind = "directory"
    return {
        "path": path_value,
        "exists": bool(path_obj and path_obj.exists()),
        "display_name": str(output.get("name") or (path_obj.name if path_obj else "unknown")),
        "preview_kind": preview_kind,
        "download_name": str((path_obj.name if path_obj else output.get("name")) or "artifact"),
    }


def find_artifact_reference(task_result: dict[str, Any], output: dict[str, Any]) -> dict[str, str] | None:
    path_value = str(output.get("path") or "").strip()
    if not path_value:
        return None
    execution_artifacts = dict(task_result.get("execution_artifacts") or {})
    for execution_id, artifacts in execution_artifacts.items():
        for artifact in list(artifacts or []):
            if str(artifact.get("path") or "").strip() != path_value:
                continue
            artifact_id = str(artifact.get("artifact_id") or "").strip()
            if not artifact_id:
                continue
            return {"execution_id": str(execution_id), "artifact_id": artifact_id}
    return None


def list_directory_entries(path_value: str, max_items: int = 12) -> list[dict[str, Any]]:
    path_obj = Path(path_value)
    if not path_obj.exists() or not path_obj.is_dir():
        return []

    entries: list[dict[str, Any]] = []
    for entry in sorted(path_obj.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))[:max_items]:
        entries.append(
            {
                "name": entry.name,
                "path": str(entry),
                "is_dir": entry.is_dir(),
                "size": entry.stat().st_size if entry.is_file() else None,
            }
        )
    return entries


def _render_analysis_summary(st: Any, *, header: dict[str, str], primary: dict[str, Any], sections: dict[str, list[Any]], evidence: dict[str, Any]) -> None:
    render_workspace_summary(
        st,
        header=header,
        next_action=str(primary.get("next_action") or ""),
        evidence_ref_count=len(evidence.get("evidence_refs") or sections["evidence_refs"]),
        execution_count=len(sections["executions"]),
        output_count=len(sections["outputs"]),
    )


def _render_analysis_body(
    st: Any,
    *,
    sections: dict[str, list[Any]],
    task_result: dict[str, Any],
    api_base_url: str,
    tenant_id: str,
    workspace_id: str,
    api_token: str,
    task_id: str,
) -> None:
    render_workspace_analysis_body(
        st,
        sections=sections,
        build_output_cards=build_output_cards,
        describe_output_asset=describe_output_asset,
        find_artifact_reference=find_artifact_reference,
        fetch_execution_artifact_bytes=fetch_execution_artifact_bytes,
        list_directory_entries=list_directory_entries,
        task_result=task_result,
        api_base_url=api_base_url,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        api_token=api_token,
        task_id=task_id,
    )


def _render_technical_details(st: Any, *, sections: dict[str, list[Any]]) -> None:
    render_technical_details_shell(st, body_renderer=lambda: render_workspace_technical_details(st, sections=sections))


def render_task_console() -> None:
    try:
        import streamlit as st
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Streamlit is not installed in the current environment") from exc

    st.set_page_config(page_title="lite-interpreter Analysis Workspace", layout="wide")
    st.title("lite-interpreter Analysis Workspace")
    st.caption("面向数据分析任务的主工作台。先看问题、证据、数据与规则，再看执行和技术细节。")

    api_base_url = st.text_input("API Base URL", value="http://127.0.0.1:8000")
    api_token, session_info = render_auth_panel(api_base_url=api_base_url, state_prefix="workspace-auth")
    if session_info and session_info.get("grants"):
        first_grant = session_info["grants"][0]
        default_tenant = str(first_grant.get("tenant_id") or "demo-tenant")
        default_workspace = str(first_grant.get("workspace_id") or "demo-workspace")
    else:
        default_tenant = "demo-tenant"
        default_workspace = "demo-workspace"
    default_task = st.session_state.get("task_id", "")
    sidebar_state = render_workspace_sidebar(
        st,
        api_base_url=api_base_url,
        tenant_id=default_tenant,
        workspace_id=default_workspace,
        governance_profile="researcher",
        allowed_tools_text="web_search,knowledge_query",
        default_task=default_task,
        default_query="帮我分析这份财报，并结合宏观经济数据预测下季度走势，自己找数据并写代码验证",
    )
    tenant_id = sidebar_state["tenant_id"]
    workspace_id = sidebar_state["workspace_id"]
    governance_profile = sidebar_state["governance_profile"]
    allowed_tools_text = sidebar_state["allowed_tools_text"]
    task_id = sidebar_state["task_id"]
    query = sidebar_state["query"]
    available_assets: list[dict[str, Any]] = []
    asset_option_labels: list[str] = []
    asset_ref_map: dict[str, str] = {}
    try:
        available_assets = fetch_workspace_assets(
            api_base_url,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            api_token=api_token,
        )
        for asset in available_assets:
            file_sha256 = str(asset.get("file_sha256") or "").strip()
            if not file_sha256:
                continue
            label = f"{asset.get('file_name', 'unknown')} [{asset.get('kind', 'unknown')}]"
            asset_option_labels.append(label)
            asset_ref_map[label] = file_sha256
    except Exception:
        available_assets = []
    selected_asset_labels = st.multiselect(
        "Workspace Assets To Attach",
        options=asset_option_labels,
        default=asset_option_labels,
        help="新建任务时显式挂接这些 workspace 资产。",
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Start Analysis Task", use_container_width=True):
            try:
                response = httpx.post(
                    f"{api_base_url.rstrip('/')}/api/tasks",
                    json={
                        "tenant_id": tenant_id,
                        "workspace_id": workspace_id,
                        "input_query": query,
                        "autorun": True,
                        "governance_profile": governance_profile,
                        "allowed_tools": [item.strip() for item in allowed_tools_text.split(",") if item.strip()],
                        "workspace_asset_refs": [asset_ref_map[label] for label in selected_asset_labels if label in asset_ref_map],
                    },
                    headers={"Authorization": f"Bearer {api_token}"} if api_token else None,
                    timeout=20.0,
                )
                response.raise_for_status()
                task_info = response.json()
                st.session_state["task_id"] = task_info["task_id"]
                st.session_state.pop("task_result", None)
                st.success(f"Created task: {task_info['task_id']}")
                st.rerun()
            except httpx.HTTPStatusError as exc:
                st.error(f"Create task failed: {exc.response.status_code}")
            except Exception as exc:
                st.error(f"Create task failed: {exc}")
    with col2:
        if st.button("Trigger Demo Stream", use_container_width=True):
            if not task_id:
                st.warning("Enter or create a task id first.")
            else:
                try:
                    response = httpx.post(
                        f"{api_base_url.rstrip('/')}/api/dev/tasks/{task_id}/demo-trace",
                        json={"tenant_id": tenant_id, "workspace_id": workspace_id},
                        headers={"Authorization": f"Bearer {api_token}"} if api_token else None,
                        timeout=20.0,
                    )
                    response.raise_for_status()
                    st.success(f"Triggered demo trace for {task_id}")
                except httpx.HTTPStatusError as exc:
                    st.error(f"Trigger demo trace failed: {exc.response.status_code}")
                except Exception as exc:
                    st.error(f"Trigger demo trace failed: {exc}")

    with st.expander("Upload Analysis Inputs"):
        render_file_uploader(
            api_base_url=api_base_url,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            task_id=task_id,
            api_token=api_token,
        )

    if task_id:
        task_result = st.session_state.get("task_result")
        if task_result is None:
            try:
                st.session_state["task_result"] = fetch_task_console_bundle(
                    api_base_url,
                    task_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    api_token=api_token,
                )
                task_result = st.session_state["task_result"]
            except Exception:
                task_result = None
        if st.button("Refresh Analysis Workspace", use_container_width=True):
            try:
                st.session_state["task_result"] = fetch_task_console_bundle(
                    api_base_url,
                    task_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    api_token=api_token,
                )
                task_result = st.session_state["task_result"]
            except httpx.HTTPStatusError as exc:
                st.error(f"Failed to fetch result: {exc.response.status_code}")
            except Exception as exc:
                st.error(f"Failed to fetch result bundle: {exc}")

        if isinstance(task_result, dict) and task_result.get("task_id") == task_id:
            header = summarize_result_header(task_result)
            sections = collect_result_sections(task_result)

            workspace = dict(task_result.get("workspace") or {})
            primary = dict(workspace.get("primary") or {})
            evidence = dict(workspace.get("evidence") or {})

            st.subheader("Analysis Summary")
            st.markdown(f"**Current Path**: `{header['mode']}`")
            st.markdown(f"### {header['headline']}")
            st.write(header["answer"])
            if primary.get("next_action"):
                st.info(f"Next step: {primary.get('next_action')}")

            summary_col1, summary_col2, summary_col3 = st.columns(3)
            summary_col1.metric("Evidence Refs", len(evidence.get("evidence_refs") or sections["evidence_refs"]))
            summary_col2.metric("Executions", len(sections["executions"]))
            summary_col3.metric("Output Assets", len(sections["outputs"]))
            _render_analysis_body(
                st,
                sections=sections,
                task_result=task_result,
                api_base_url=api_base_url,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                api_token=api_token,
                task_id=task_id,
            )

            with st.expander("Technical Details"):
                _render_technical_details(st, sections=sections)

            with st.expander("Raw Workspace JSON"):
                st.json(task_result)

    preferred_execution_id = ""
    if task_id and isinstance(task_result, dict):
        executions = list(task_result.get("executions") or [])
        if executions:
            execution_options = [
                str(item.get("execution_id", "")).strip()
                for item in executions
                if str(item.get("execution_id", "")).strip()
            ]
            if execution_options:
                preferred_execution_id = st.selectbox(
                    "Execution Stream Target",
                    options=execution_options,
                    index=0,
                    key=f"execution-target-{task_id}",
                )

    if task_id:
        stream_target = select_stream_target(
            task_result if isinstance(task_result, dict) else {"task_id": task_id},
            preferred_execution_id=preferred_execution_id,
        )
        render_status_stream(
            api_base_url=api_base_url,
            task_id=stream_target["task_id"] or task_id,
            execution_id=stream_target["execution_id"],
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            api_token=api_token,
            height=460,
        )
    else:
        st.info("Enter a task id to open an analysis workspace and stream task or execution status.")
