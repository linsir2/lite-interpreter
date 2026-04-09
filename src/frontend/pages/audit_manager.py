"""Audit log page for admin inspection."""

from __future__ import annotations

import httpx

from src.frontend.auth_client import api_auth_headers, render_auth_panel


def render_audit_manager() -> None:
    try:
        import streamlit as st
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Streamlit is not installed in the current environment") from exc

    st.title("Audit Manager")
    api_base_url = st.text_input("API Base URL", value="http://127.0.0.1:8000", key="audit-api")
    api_token, session_info = render_auth_panel(api_base_url=api_base_url, state_prefix="audit-auth")
    if session_info and session_info.get("grants"):
        first_grant = session_info["grants"][0]
        default_tenant = str(first_grant.get("tenant_id") or "demo-tenant")
        default_workspace = str(first_grant.get("workspace_id") or "demo-workspace")
    else:
        default_tenant = "demo-tenant"
        default_workspace = "demo-workspace"

    tenant_id = st.text_input("Tenant ID", value=default_tenant, key="audit-tenant")
    workspace_id = st.text_input("Workspace ID", value=default_workspace, key="audit-workspace")
    subject = st.text_input("Subject", value="", key="audit-subject")
    role = st.selectbox("Role", options=["", "viewer", "operator", "admin"], index=0, key="audit-role")
    action = st.text_input("Action", value="", key="audit-action")
    outcome = st.selectbox("Outcome", options=["", "success", "failure", "denied"], index=0, key="audit-outcome")
    resource_type = st.text_input("Resource Type", value="", key="audit-resource-type")
    task_id = st.text_input("Task ID", value="", key="audit-task-id")
    execution_id = st.text_input("Execution ID", value="", key="audit-execution-id")
    recorded_after = st.text_input("Recorded After", value="", key="audit-recorded-after")
    recorded_before = st.text_input("Recorded Before", value="", key="audit-recorded-before")
    limit = st.slider("Limit", min_value=10, max_value=200, value=50, step=10)

    if st.button("Refresh Audit Logs", use_container_width=True):
        params = {
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "limit": str(limit),
        }
        optional_filters = {
            "subject": subject,
            "role": role,
            "action": action,
            "outcome": outcome,
            "resource_type": resource_type,
            "task_id": task_id,
            "execution_id": execution_id,
            "recorded_after": recorded_after,
            "recorded_before": recorded_before,
        }
        params.update({key: value for key, value in optional_filters.items() if str(value).strip()})
        try:
            response = httpx.get(
                f"{api_base_url.rstrip('/')}/api/audit/logs",
                params=params,
                headers=api_auth_headers(api_token),
                timeout=20.0,
            )
            response.raise_for_status()
            payload = response.json()
            records = list(payload.get("records") or [])
            if not records:
                st.info("No audit records matched the selected filters.")
                return
            for record in records:
                st.markdown(f"**{record.get('action', 'unknown')}**")
                st.caption(f"outcome={record.get('outcome')} subject={record.get('subject')} role={record.get('role')}")
                st.caption(
                    f"resource_type={record.get('resource_type')} resource_id={record.get('resource_id')} recorded_at={record.get('recorded_at')}"
                )
                if record.get("task_id"):
                    st.caption(f"task_id={record.get('task_id')}")
                if record.get("execution_id"):
                    st.caption(f"execution_id={record.get('execution_id')}")
                metadata = record.get("metadata") or {}
                if metadata:
                    st.json(metadata)
                st.divider()
        except Exception as exc:
            st.error(f"Failed to fetch audit logs: {exc}")
