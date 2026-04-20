"""Knowledge asset page for uploaded files and parser/index status."""

from __future__ import annotations

import httpx

from src.frontend.auth_client import api_auth_headers, render_auth_panel
from src.frontend.components.file_uploader import render_file_uploader


def render_knowledge_manager() -> None:
    try:
        import streamlit as st
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Streamlit is not installed in the current environment") from exc

    st.title("Knowledge Manager")
    api_base_url = st.text_input("API Base URL", value="http://127.0.0.1:8000", key="knowledge-api")
    api_token, session_info = render_auth_panel(api_base_url=api_base_url, state_prefix="workspace-auth")
    if session_info and session_info.get("grants"):
        first_grant = session_info["grants"][0]
        default_tenant = str(first_grant.get("tenant_id") or "demo-tenant")
        default_workspace = str(first_grant.get("workspace_id") or "demo-workspace")
    else:
        default_tenant = "demo-tenant"
        default_workspace = "demo-workspace"
    tenant_id = st.text_input("Tenant ID", value=default_tenant, key="knowledge-tenant")
    workspace_id = st.text_input("Workspace ID", value=default_workspace, key="knowledge-workspace")

    with st.expander("Upload Workspace Assets"):
        render_file_uploader(
            api_base_url=api_base_url,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            api_token=api_token,
        )

    if st.button("Refresh Assets", use_container_width=True):
        try:
            response = httpx.get(
                f"{api_base_url.rstrip('/')}/api/knowledge/assets",
                params={"tenant_id": tenant_id, "workspace_id": workspace_id},
                headers=api_auth_headers(api_token),
                timeout=20.0,
            )
            response.raise_for_status()
            payload = response.json()
            assets = list(payload.get("assets") or [])
            if not assets:
                st.info("No assets found for the selected workspace.")
            for asset in assets:
                st.markdown(f"**{asset.get('file_name', 'unknown')}**")
                st.caption(f"kind={asset.get('kind')} task_id={asset.get('task_id')}")
                if asset.get("path"):
                    st.code(asset.get("path"), language=None)
                if asset.get("kind") == "structured_dataset":
                    st.caption(f"schema_ready={asset.get('schema_ready')}")
                    load_kwargs = asset.get("load_kwargs") or {}
                    if load_kwargs:
                        st.caption(f"load_kwargs={load_kwargs}")
                else:
                    st.caption(
                        f"status={asset.get('status', 'unknown')} parse_mode={asset.get('parse_mode', 'default')}"
                    )
                    diagnostics = asset.get("parser_diagnostics") or {}
                    if diagnostics:
                        st.caption(str(diagnostics))
                st.divider()
        except Exception as exc:
            st.error(f"Failed to fetch assets: {exc}")
