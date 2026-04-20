"""Skill inventory page for approved reusable skills."""

from __future__ import annotations

import httpx

from src.frontend.auth_client import api_auth_headers, render_auth_panel


def render_skill_manager() -> None:
    try:
        import streamlit as st
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Streamlit is not installed in the current environment") from exc

    st.title("Skill Manager")
    api_base_url = st.text_input("API Base URL", value="http://127.0.0.1:8000", key="skill-api")
    api_token, session_info = render_auth_panel(api_base_url=api_base_url, state_prefix="workspace-auth")
    if session_info and session_info.get("grants"):
        first_grant = session_info["grants"][0]
        default_tenant = str(first_grant.get("tenant_id") or "demo-tenant")
        default_workspace = str(first_grant.get("workspace_id") or "demo-workspace")
    else:
        default_tenant = "demo-tenant"
        default_workspace = "demo-workspace"
    tenant_id = st.text_input("Tenant ID", value=default_tenant, key="skill-tenant")
    workspace_id = st.text_input("Workspace ID", value=default_workspace, key="skill-workspace")

    if st.button("Refresh Skills", use_container_width=True):
        try:
            response = httpx.get(
                f"{api_base_url.rstrip('/')}/api/skills",
                params={"tenant_id": tenant_id, "workspace_id": workspace_id},
                headers=api_auth_headers(api_token),
                timeout=20.0,
            )
            response.raise_for_status()
            payload = response.json()
            skills = list(payload.get("skills") or [])
            if not skills:
                st.info("No approved skills found for the selected workspace.")
            for skill in skills:
                st.markdown(f"**{skill.get('name', 'unknown')}**")
                st.caption(str(skill.get("description") or "No description"))
                required = skill.get("required_capabilities") or []
                if required:
                    st.caption(f"required_capabilities={', '.join(str(item) for item in required)}")
                promotion = skill.get("promotion") or {}
                if promotion:
                    st.caption(f"promotion={promotion.get('status', 'unknown')}")
                usage = skill.get("usage") or skill.get("metadata", {}).get("usage") or {}
                if usage:
                    st.caption(f"usage={usage}")
                replay_cases = skill.get("replay_cases") or []
                if replay_cases:
                    st.caption(f"replay_cases={len(replay_cases)}")
                st.divider()
        except Exception as exc:
            st.error(f"Failed to fetch skills: {exc}")
