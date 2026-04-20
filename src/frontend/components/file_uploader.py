"""Streamlit file-uploader component wired to the upload API."""

from __future__ import annotations

from typing import Any

import httpx

from src.frontend.auth_client import api_auth_headers


def upload_file_via_api(
    *,
    api_base_url: str,
    files_to_upload: list[tuple[str, bytes]],
    tenant_id: str,
    workspace_id: str,
    task_id: str = "",
    asset_kind: str = "auto",
    api_token: str = "",
) -> dict[str, Any]:
    files = [("file", (file_name, file_bytes)) for file_name, file_bytes in files_to_upload]
    data = {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "task_id": task_id,
        "asset_kind": asset_kind,
    }
    headers = api_auth_headers(api_token)
    response = httpx.post(
        f"{api_base_url.rstrip('/')}/api/uploads",
        files=files,
        data=data,
        headers=headers,
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
    api_token: str = "",
) -> None:
    try:
        import streamlit as st
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Streamlit is not installed in the current environment") from exc

    uploaded_files = st.file_uploader(
        "Upload file",
        type=None,
        accept_multiple_files=True,
        key=f"upload-{task_id or 'global'}",
    )
    asset_kind = st.selectbox(
        "Asset Kind",
        options=["auto", "structured_dataset", "business_document"],
        index=0,
        key=f"asset-kind-{task_id or 'global'}",
    )
    if not uploaded_files:
        return

    if st.button(
        "Send Upload", use_container_width=True, key=f"upload-button-{task_id or 'global'}"
    ):
        try:
            file_payloads = [(uploaded_file.name, uploaded_file.getvalue()) for uploaded_file in uploaded_files]
            payload = upload_file_via_api(
                api_base_url=api_base_url,
                files_to_upload=file_payloads,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                task_id=task_id,
                asset_kind=asset_kind,
                api_token=api_token,
            )
            if payload.get("uploaded_files"):
                st.success(f"Uploaded {len(payload.get('uploaded_files', []))} files")
            else:
                st.success(f"Uploaded {payload.get('file_name', uploaded_files[0].name)}")
            st.json(payload)
        except Exception as exc:
            st.error(f"Upload failed: {exc}")
