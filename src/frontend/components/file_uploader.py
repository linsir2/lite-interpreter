"""Streamlit file-uploader component wired to the upload API."""
from __future__ import annotations

from typing import Any

import httpx


def upload_file_via_api(
    *,
    api_base_url: str,
    file_name: str,
    file_bytes: bytes,
    tenant_id: str,
    workspace_id: str,
    task_id: str = "",
    asset_kind: str = "auto",
) -> dict[str, Any]:
    files = {"file": (file_name, file_bytes)}
    data = {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "task_id": task_id,
        "asset_kind": asset_kind,
    }
    response = httpx.post(
        f"{api_base_url.rstrip('/')}/api/uploads",
        files=files,
        data=data,
        timeout=60.0,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def render_file_uploader(
    *,
    api_base_url: str,
    tenant_id: str,
    workspace_id: str,
    task_id: str = "",
) -> None:
    try:
        import streamlit as st
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Streamlit is not installed in the current environment") from exc

    uploaded_file = st.file_uploader("Upload file", type=None, key=f"upload-{task_id or 'global'}")
    asset_kind = st.selectbox(
        "Asset Kind",
        options=["auto", "structured_dataset", "business_document"],
        index=0,
        key=f"asset-kind-{task_id or 'global'}",
    )
    if uploaded_file is None:
        return

    if st.button("Send Upload", use_container_width=True, key=f"upload-button-{uploaded_file.name}-{task_id or 'global'}"):
        try:
            payload = upload_file_via_api(
                api_base_url=api_base_url,
                file_name=uploaded_file.name,
                file_bytes=uploaded_file.getvalue(),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                task_id=task_id,
                asset_kind=asset_kind,
            )
            st.success(f"Uploaded {payload.get('file_name', uploaded_file.name)}")
            st.json(payload)
        except Exception as exc:
            st.error(f"Upload failed: {exc}")
