"""Task console page and result formatting helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import httpx

from src.frontend.components.file_uploader import render_file_uploader
from src.frontend.components.status_stream import render_status_stream


def summarize_result_header(task_result: Dict[str, Any]) -> Dict[str, str]:
    final_response = task_result.get("final_response") or {}
    return {
        "mode": str(final_response.get("mode") or task_result.get("global_status") or "unknown"),
        "headline": str(final_response.get("headline") or "No headline available"),
        "answer": str(final_response.get("answer") or final_response.get("headline") or "No answer available"),
    }


def select_stream_target(task_result: Dict[str, Any] | None, *, preferred_execution_id: str = "") -> Dict[str, str]:
    executions = list((task_result or {}).get("executions") or [])
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
            return {"stream_kind": "execution", "execution_id": execution_id, "task_id": str(task_result.get("task_id", ""))}
    return {
        "stream_kind": "task",
        "execution_id": "",
        "task_id": str((task_result or {}).get("task_id", "")),
    }


def fetch_json_payload(url: str, *, timeout: float = 20.0) -> Dict[str, Any]:
    response = httpx.get(url, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def fetch_task_console_bundle(api_base_url: str, task_id: str, *, timeout: float = 20.0) -> Dict[str, Any]:
    base_url = api_base_url.rstrip("/")
    result_payload = fetch_json_payload(f"{base_url}/api/tasks/{task_id}/result", timeout=timeout)

    executions: List[Dict[str, Any]] = []
    tool_calls: List[Dict[str, Any]] = []
    try:
        executions_payload = fetch_json_payload(f"{base_url}/api/tasks/{task_id}/executions", timeout=timeout)
        executions = list(executions_payload.get("executions") or [])
    except Exception:
        executions = list(result_payload.get("executions") or [])

    for execution in executions:
        execution_id = str(execution.get("execution_id", "")).strip()
        if not execution_id:
            continue
        try:
            tool_calls_payload = fetch_json_payload(
                f"{base_url}/api/executions/{execution_id}/tool-calls",
                timeout=timeout,
            )
        except Exception:
            continue
        tool_calls.extend(list(tool_calls_payload.get("tool_calls") or []))

    enriched = dict(result_payload)
    enriched["executions"] = executions
    enriched["tool_calls"] = tool_calls
    return enriched


def collect_result_sections(task_result: Dict[str, Any]) -> Dict[str, List[Any]]:
    final_response = task_result.get("final_response") or {}
    knowledge_snapshot = dict((final_response.get("details") or {}).get("knowledge_snapshot") or task_result.get("knowledge_snapshot") or {})
    return {
        "findings": list(final_response.get("key_findings") or []),
        "outputs": list(final_response.get("outputs") or []),
        "caveats": list(final_response.get("caveats") or []),
        "evidence_refs": list(final_response.get("evidence_refs") or []),
        "executions": list(task_result.get("executions") or []),
        "tool_calls": list(task_result.get("tool_calls") or []),
        "parser_reports": list((final_response.get("details") or {}).get("parser_reports") or []),
        "rule_checks": list((final_response.get("details") or {}).get("rule_checks") or []),
        "metric_checks": list((final_response.get("details") or {}).get("metric_checks") or []),
        "filter_checks": list((final_response.get("details") or {}).get("filter_checks") or []),
        "knowledge_snapshot": [knowledge_snapshot] if knowledge_snapshot else [],
        "historical_skill_matches": list(task_result.get("historical_skill_matches") or []),
        "used_historical_skills": list((final_response.get("details") or {}).get("used_historical_skills") or []),
        "task_lease": [dict(task_result.get("task_lease") or {})] if task_result.get("task_lease") else [],
    }


def build_output_cards(outputs: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    cards: List[Dict[str, str]] = []
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


def describe_output_asset(output: Dict[str, Any]) -> Dict[str, Any]:
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


def list_directory_entries(path_value: str, max_items: int = 12) -> List[Dict[str, Any]]:
    path_obj = Path(path_value)
    if not path_obj.exists() or not path_obj.is_dir():
        return []

    entries: List[Dict[str, Any]] = []
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


def render_task_console() -> None:
    try:
        import streamlit as st
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Streamlit is not installed in the current environment") from exc

    st.set_page_config(page_title="lite-interpreter Task Console", layout="wide")
    st.title("lite-interpreter Task Console")
    st.caption("Observe task status updates and DeerFlow dynamic trace events over SSE.")

    api_base_url = st.text_input("API Base URL", value="http://127.0.0.1:8000")
    tenant_id = st.text_input("Tenant ID", value="demo-tenant")
    workspace_id = st.text_input("Workspace ID", value="demo-workspace")
    governance_profile = st.selectbox("Governance Profile", options=["researcher", "planner", "executor", "reviewer"], index=0)
    allowed_tools_text = st.text_input("Allowed Tools (comma separated)", value="web_search,knowledge_query")
    default_task = st.session_state.get("task_id", "")
    task_id = st.text_input("Task ID", value=default_task)
    query = st.text_area(
        "Task Query",
        value="帮我分析这份财报，并结合宏观经济数据预测下季度走势，自己找数据并写代码验证",
        height=120,
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Create Real Task", use_container_width=True):
            response = httpx.post(
                f"{api_base_url.rstrip('/')}/api/tasks",
                json={
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "input_query": query,
                    "autorun": True,
                    "governance_profile": governance_profile,
                    "allowed_tools": [item.strip() for item in allowed_tools_text.split(",") if item.strip()],
                },
                timeout=20.0,
            )
            response.raise_for_status()
            task_info = response.json()
            st.session_state["task_id"] = task_info["task_id"]
            st.success(f"Created task: {task_info['task_id']}")
            st.rerun()
    with col2:
        if st.button("Trigger Demo Trace", use_container_width=True):
            if not task_id:
                st.warning("Enter or create a task id first.")
            else:
                response = httpx.post(
                    f"{api_base_url.rstrip('/')}/api/dev/tasks/{task_id}/demo-trace",
                    json={"tenant_id": tenant_id, "workspace_id": workspace_id},
                    timeout=20.0,
                )
                response.raise_for_status()
                st.success(f"Triggered demo trace for {task_id}")

    with st.expander("Upload Workspace Assets"):
        render_file_uploader(
            api_base_url=api_base_url,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            task_id=task_id,
        )

    if task_id:
        task_result = st.session_state.get("task_result")
        if st.button("Fetch Final Result", use_container_width=True):
            try:
                st.session_state["task_result"] = fetch_task_console_bundle(api_base_url, task_id)
                task_result = st.session_state["task_result"]
            except httpx.HTTPStatusError as exc:
                st.error(f"Failed to fetch result: {exc.response.status_code}")
            except Exception as exc:
                st.error(f"Failed to fetch result bundle: {exc}")

        if isinstance(task_result, dict) and task_result.get("task_id") == task_id:
            header = summarize_result_header(task_result)
            sections = collect_result_sections(task_result)

            st.subheader("Final Result")
            st.markdown(f"**Mode**: `{header['mode']}`")
            st.markdown(f"### {header['headline']}")
            st.write(header["answer"])

            info_col1, info_col2 = st.columns(2)
            with info_col1:
                st.markdown("#### Key Findings")
                if sections["findings"]:
                    for item in sections["findings"]:
                        st.markdown(f"- {item}")
                else:
                    st.caption("No key findings recorded.")

                st.markdown("#### Evidence")
                if sections["evidence_refs"]:
                    for ref in sections["evidence_refs"]:
                        st.code(ref, language=None)
                else:
                    st.caption("No evidence refs recorded.")

                st.markdown("#### Knowledge Snapshot")
                knowledge_snapshot = sections["knowledge_snapshot"][0] if sections["knowledge_snapshot"] else {}
                if knowledge_snapshot:
                    rewritten_query = knowledge_snapshot.get("rewritten_query")
                    if rewritten_query:
                        st.caption(f"rewritten_query={rewritten_query}")
                    recall_strategies = knowledge_snapshot.get("recall_strategies", []) or []
                    if recall_strategies:
                        st.caption(f"recall={', '.join(str(item) for item in recall_strategies)}")
                    filters = knowledge_snapshot.get("filters", {}) or {}
                    if filters:
                        st.caption(f"filters={filters}")
                    metadata = knowledge_snapshot.get("metadata", {}) or {}
                    if metadata:
                        st.caption(str(metadata))
                else:
                    st.caption("No knowledge snapshot recorded.")

                st.markdown("#### Historical Skill Matches")
                if sections["historical_skill_matches"]:
                    for match in sections["historical_skill_matches"]:
                        st.markdown(f"- **{match.get('name', 'unknown')}**")
                        required = match.get("required_capabilities", []) or []
                        if required:
                            st.caption(f"caps={', '.join(str(item) for item in required)}")
                        if match.get("match_source"):
                            st.caption(f"source={match.get('match_source')}")
                        if match.get("match_reason"):
                            st.caption(f"reason={match.get('match_reason')}")
                        if match.get("match_score") is not None:
                            st.caption(f"score={match.get('match_score')}")
                        usage = match.get("usage", {}) or {}
                        if usage:
                            st.caption(str(usage))
                else:
                    st.caption("No historical skill matches recorded.")

                st.markdown("#### Task Lease")
                if sections["task_lease"]:
                    lease = sections["task_lease"][0]
                    st.caption(f"owner={lease.get('owner_id')}")
                    st.caption(f"expires_at={lease.get('lease_expires_at')}")
                    st.caption(f"backend={lease.get('backend')}")
                else:
                    st.caption("No active task lease recorded.")

                st.markdown("#### Used Historical Skills")
                if sections["used_historical_skills"]:
                    for match in sections["used_historical_skills"]:
                        st.markdown(f"- **{match.get('name', 'unknown')}** used in code generation")
                        stages = match.get("selected_by_stages", []) or []
                        if stages:
                            st.caption(f"stages={', '.join(str(item) for item in stages)}")
                        replay_ids = match.get("used_replay_case_ids", []) or []
                        if replay_ids:
                            st.caption(f"replay_cases={', '.join(str(item) for item in replay_ids)}")
                        capabilities = match.get("used_capabilities", []) or []
                        if capabilities:
                            st.caption(f"used_caps={', '.join(str(item) for item in capabilities)}")
                        usage = match.get("usage", {}) or {}
                        if usage:
                            st.caption(str(usage))
                else:
                    st.caption("No historical skills were used in code generation.")

                st.markdown("#### Executions")
                if sections["executions"]:
                    for execution in sections["executions"]:
                        st.markdown(
                            f"- **{execution.get('execution_id', 'unknown')}**  \n"
                            f"  kind=`{execution.get('kind', 'unknown')}` backend=`{execution.get('backend', 'unknown')}` status=`{execution.get('status', 'unknown')}`"
                        )
                        if execution.get("summary"):
                            st.caption(str(execution.get("summary"))[:240])
                        if execution.get("artifact_count") is not None:
                            st.caption(f"artifacts={execution.get('artifact_count')} tool_calls={execution.get('tool_call_count', 0)}")
                else:
                    st.caption("No execution resources recorded.")

                st.markdown("#### Tool Calls")
                if sections["tool_calls"]:
                    for tool_call in sections["tool_calls"]:
                        st.markdown(
                            f"- **{tool_call.get('tool_name', 'unknown')}**  \n"
                            f"  phase=`{tool_call.get('phase', 'unknown')}` call_id=`{tool_call.get('tool_call_id', 'unknown')}`"
                        )
                        if tool_call.get("execution_id"):
                            st.caption(f"execution={tool_call.get('execution_id')}")
                        if tool_call.get("source_event_type"):
                            st.caption(f"source_event={tool_call.get('source_event_type')}")
                        if tool_call.get("status"):
                            st.caption(f"status={tool_call.get('status')}")
                        arguments = tool_call.get("arguments")
                        if arguments:
                            st.caption(f"args={arguments}")
                        result_payload = tool_call.get("result")
                        if result_payload:
                            st.caption(f"result={result_payload}")
                else:
                    st.caption("No tool-call resources recorded.")

                st.markdown("#### Parse Diagnostics")
                if sections["parser_reports"]:
                    for report in sections["parser_reports"]:
                        st.markdown(
                            f"- **{report.get('file_name', 'unknown')}**: mode=`{report.get('parse_mode', 'default')}`"
                        )
                        diagnostics = report.get("parser_diagnostics", {}) or {}
                        if diagnostics:
                            st.caption(str(diagnostics))
                else:
                    st.caption("No parser diagnostics recorded.")

                st.markdown("#### Rule Checks")
                if sections["rule_checks"]:
                    for check in sections["rule_checks"]:
                        st.markdown(
                            f"- **Rule**: {check.get('rule', 'unknown')}  \n"
                            f"  Issues: `{check.get('issue_count', 0)}`"
                        )
                        matched_datasets = check.get("matched_datasets", []) or []
                        matched_documents = check.get("matched_documents", []) or []
                        if matched_datasets:
                            st.caption(f"datasets: {', '.join(str(item) for item in matched_datasets)}")
                        if matched_documents:
                            st.caption(f"documents: {', '.join(str(item) for item in matched_documents)}")
                        warnings = check.get("warnings", []) or []
                        for warning in warnings[:3]:
                                st.caption(f"warning: {warning}")
                else:
                    st.caption("No rule checks recorded.")

                st.markdown("#### Metric Checks")
                if sections["metric_checks"]:
                    for check in sections["metric_checks"]:
                        st.markdown(
                            f"- **Metric**: {check.get('metric', 'unknown')}  \n"
                            f"  Matched columns: `{len(check.get('matched_columns', []) or [])}`"
                        )
                        matched_datasets = check.get("matched_datasets", []) or []
                        if matched_datasets:
                            st.caption(f"datasets: {', '.join(str(item) for item in matched_datasets)}")
                        highlights = check.get("highlights", []) or []
                        for highlight in highlights[:3]:
                            st.caption(f"highlight: {highlight}")
                else:
                    st.caption("No metric checks recorded.")

                st.markdown("#### Filter Checks")
                if sections["filter_checks"]:
                    for check in sections["filter_checks"]:
                        st.markdown(
                            f"- **Filter**: {check.get('filter', 'unknown')}"
                        )
                        matched_datasets = check.get("matched_datasets", []) or []
                        matched_documents = check.get("matched_documents", []) or []
                        matched_values = check.get("matched_values", []) or []
                        if matched_datasets:
                            st.caption(f"datasets: {', '.join(str(item) for item in matched_datasets)}")
                        if matched_documents:
                            st.caption(f"documents: {', '.join(str(item) for item in matched_documents)}")
                        for value in matched_values[:3]:
                            st.caption(f"value: {value}")
                else:
                    st.caption("No filter checks recorded.")

            with info_col2:
                st.markdown("#### Outputs")
                if sections["outputs"]:
                    for raw_output, card in zip(sections["outputs"], build_output_cards(sections["outputs"])):
                        asset = describe_output_asset(raw_output)
                        st.markdown(
                            "\n".join(
                                [
                                    f"**[{card['icon']}] {card['title']}**",
                                    f"`{card['type']}`",
                                    card["subtitle"],
                                ]
                            )
                        )
                        if asset["path"]:
                            st.code(asset["path"], language=None)
                        if asset["exists"] and asset["preview_kind"] == "image":
                            st.image(asset["path"], use_container_width=True)
                        elif asset["exists"] and asset["preview_kind"] == "text":
                            try:
                                preview_text = Path(asset["path"]).read_text(encoding="utf-8", errors="ignore")[:1200]
                                if preview_text:
                                    st.caption(preview_text)
                            except Exception:
                                pass
                        elif asset["exists"] and asset["preview_kind"] == "directory":
                            entries = list_directory_entries(asset["path"])
                            if entries:
                                with st.expander(f"Browse {asset['display_name']}"):
                                    for entry in entries:
                                        label = "DIR" if entry["is_dir"] else "FILE"
                                        st.markdown(f"- **[{label}] {entry['name']}**")
                                        st.code(entry["path"], language=None)
                                        if not entry["is_dir"] and entry["size"] is not None:
                                            st.caption(f"size={entry['size']} bytes")
                        if asset["exists"] and asset["preview_kind"] in {"image", "text"}:
                            try:
                                file_bytes = Path(asset["path"]).read_bytes()
                                st.download_button(
                                    label=f"Download {asset['display_name']}",
                                    data=file_bytes,
                                    file_name=asset["download_name"],
                                    key=f"download-{task_id}-{asset['download_name']}",
                                    use_container_width=True,
                                )
                            except Exception:
                                pass
                        st.divider()
                else:
                    st.caption("No outputs recorded.")

                st.markdown("#### Caveats")
                if sections["caveats"]:
                    for item in sections["caveats"]:
                        st.markdown(f"- {item}")
                else:
                    st.caption("No caveats recorded.")

            with st.expander("Raw Result JSON"):
                st.json(task_result)

    preferred_execution_id = ""
    if task_id and isinstance(task_result, dict):
        executions = list(task_result.get("executions") or [])
        if executions:
            execution_options = [str(item.get("execution_id", "")).strip() for item in executions if str(item.get("execution_id", "")).strip()]
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
            height=460,
        )
    else:
        st.info("Enter a task id to start streaming status and dynamic trace events.")
