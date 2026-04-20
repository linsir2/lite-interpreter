"""Streamlit shell helpers for the analysis workspace."""

from __future__ import annotations

from typing import Any


def render_workspace_summary(
    st: Any,
    *,
    header: dict[str, str],
    next_action: str,
    evidence_ref_count: int,
    execution_count: int,
    output_count: int,
) -> None:
    st.subheader("Analysis Summary")
    st.markdown(f"**Current Path**: `{header['mode']}`")
    st.markdown(f"### {header['headline']}")
    st.write(header["answer"])
    if next_action:
        st.info(f"Next step: {next_action}")

    summary_col1, summary_col2, summary_col3 = st.columns(3)
    summary_col1.metric("Evidence Refs", evidence_ref_count)
    summary_col2.metric("Executions", execution_count)
    summary_col3.metric("Output Assets", output_count)


def render_workspace_sidebar(
    st: Any,
    *,
    api_base_url: str,
    tenant_id: str,
    workspace_id: str,
    governance_profile: str,
    allowed_tools_text: str,
    default_task: str,
    default_query: str,
) -> dict[str, str]:
    st.caption("这是数据分析工作台，不是运行时控制台。先回答分析问题，再看系统细节。")
    tenant_value = st.text_input("Tenant ID", value=tenant_id)
    workspace_value = st.text_input("Workspace ID", value=workspace_id)
    governance_value = st.selectbox(
        "Governance Profile", options=["researcher", "planner", "executor", "reviewer"], index=0
    )
    tools_value = st.text_input("Allowed Tools (comma separated)", value=allowed_tools_text)
    task_value = st.text_input("Task ID", value=default_task)
    query_value = st.text_area("Task Query", value=default_query, height=120)
    return {
        "api_base_url": api_base_url,
        "tenant_id": tenant_value,
        "workspace_id": workspace_value,
        "governance_profile": governance_value,
        "allowed_tools_text": tools_value,
        "task_id": task_value,
        "query": query_value,
    }


def render_technical_details_shell(st: Any, *, body_renderer: Any) -> None:
    with st.expander("Technical Details"):
        body_renderer()
