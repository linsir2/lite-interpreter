"""Skill inventory page for approved reusable skills."""
from __future__ import annotations

import httpx


def render_skill_manager() -> None:
    try:
        import streamlit as st
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Streamlit is not installed in the current environment") from exc

    st.title("Skill Manager")
    api_base_url = st.text_input("API Base URL", value="http://127.0.0.1:8000", key="skill-api")
    tenant_id = st.text_input("Tenant ID", value="demo-tenant", key="skill-tenant")
    workspace_id = st.text_input("Workspace ID", value="demo-workspace", key="skill-workspace")

    if st.button("Refresh Skills", use_container_width=True):
        try:
            response = httpx.get(
                f"{api_base_url.rstrip('/')}/api/skills",
                params={"tenant_id": tenant_id, "workspace_id": workspace_id},
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
