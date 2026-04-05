"""Knowledge asset page for uploaded files and parser/index status."""
from __future__ import annotations

import httpx


def render_knowledge_manager() -> None:
    try:
        import streamlit as st
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Streamlit is not installed in the current environment") from exc

    st.title("Knowledge Manager")
    api_base_url = st.text_input("API Base URL", value="http://127.0.0.1:8000", key="knowledge-api")
    tenant_id = st.text_input("Tenant ID", value="demo-tenant", key="knowledge-tenant")
    workspace_id = st.text_input("Workspace ID", value="demo-workspace", key="knowledge-workspace")

    if st.button("Refresh Assets", use_container_width=True):
        try:
            response = httpx.get(
                f"{api_base_url.rstrip('/')}/api/knowledge/assets",
                params={"tenant_id": tenant_id, "workspace_id": workspace_id},
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
                    st.caption(f"status={asset.get('status', 'unknown')} parse_mode={asset.get('parse_mode', 'default')}")
                    diagnostics = asset.get("parser_diagnostics") or {}
                    if diagnostics:
                        st.caption(str(diagnostics))
                st.divider()
        except Exception as exc:
            st.error(f"Failed to fetch assets: {exc}")
