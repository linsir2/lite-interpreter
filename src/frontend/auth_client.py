"""Frontend helpers for API session login and auth state."""
from __future__ import annotations

from typing import Any

import httpx


def api_auth_headers(api_token: str) -> dict[str, str] | None:
    normalized = str(api_token or "").strip()
    if not normalized:
        return None
    return {"Authorization": f"Bearer {normalized}"}


def login_via_api(*, api_base_url: str, username: str, password: str) -> dict[str, Any]:
    response = httpx.post(
        f"{api_base_url.rstrip('/')}/api/session/login",
        json={"username": username, "password": password},
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def fetch_session_me(*, api_base_url: str, api_token: str) -> dict[str, Any]:
    response = httpx.get(
        f"{api_base_url.rstrip('/')}/api/session/me",
        headers=api_auth_headers(api_token),
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def render_auth_panel(*, api_base_url: str, state_prefix: str = "auth") -> tuple[str, dict[str, Any] | None]:
    try:
        import streamlit as st
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Streamlit is not installed in the current environment") from exc

    token_key = f"{state_prefix}-token"
    session_key = f"{state_prefix}-session"
    api_token = str(st.session_state.get(token_key, ""))
    session_info = st.session_state.get(session_key)

    with st.expander("Session Login", expanded=False):
        username = st.text_input("Username", key=f"{state_prefix}-username")
        password = st.text_input("Password", type="password", key=f"{state_prefix}-password")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Login", key=f"{state_prefix}-login", use_container_width=True):
                try:
                    payload = login_via_api(api_base_url=api_base_url, username=username, password=password)
                    st.session_state[token_key] = str(payload.get("access_token") or "")
                    st.session_state[session_key] = payload
                    st.success(f"Authenticated as {payload.get('subject', username)}")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Login failed: {exc}")
        with col2:
            if st.button("Clear Session", key=f"{state_prefix}-logout", use_container_width=True):
                st.session_state.pop(token_key, None)
                st.session_state.pop(session_key, None)
                st.rerun()

        api_token = str(st.session_state.get(token_key, ""))
        if api_token:
            st.caption("Session token is active for this page.")
            if not session_info:
                try:
                    session_info = fetch_session_me(api_base_url=api_base_url, api_token=api_token)
                    st.session_state[session_key] = session_info
                except Exception:
                    session_info = None
            if session_info:
                st.caption(
                    f"subject={session_info.get('subject')} role={session_info.get('role')} auth_type={session_info.get('auth_type')}"
                )
                grants = list(session_info.get("grants") or [])
                if grants:
                    st.caption(f"grants={grants}")

    return str(st.session_state.get(token_key, "")), st.session_state.get(session_key)
