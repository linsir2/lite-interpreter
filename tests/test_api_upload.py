"""Tests for upload and workspace asset endpoints."""
from __future__ import annotations

import asyncio
import json

from src.api.routers.upload_router import list_knowledge_assets, list_workspace_skills, upload_asset


class _FakeUploadFile:
    def __init__(self, filename: str, payload: bytes) -> None:
        self.filename = filename
        self._payload = payload

    async def read(self) -> bytes:
        return self._payload


class _FakeRequest:
    def __init__(self, *, form_data=None, query_params=None) -> None:
        self._form_data = form_data or {}
        self.query_params = query_params or {}

    async def form(self):
        return self._form_data


def test_upload_asset_and_list_workspace_assets():
    request = _FakeRequest(
        form_data={
            "tenant_id": "tenant-upload",
            "workspace_id": "ws-upload",
            "asset_kind": "structured_dataset",
            "file": _FakeUploadFile("sales.csv", b"region,amount\nsh,10\n"),
        }
    )
    response = asyncio.run(upload_asset(request))
    assert response.status_code == 200
    payload = json.loads(response.body.decode())
    assert payload["uploaded"] is True
    assert payload["asset_kind"] == "structured_dataset"

    assets_response = asyncio.run(
        list_knowledge_assets(
            _FakeRequest(query_params={"tenant_id": "tenant-upload", "workspace_id": "ws-upload"})
        )
    )
    assert assets_response.status_code == 200
    assets = json.loads(assets_response.body.decode())["assets"]
    assert any(asset["file_name"] == "sales.csv" for asset in assets)


def test_list_workspace_skills_includes_preset_skills():
    response = asyncio.run(
        list_workspace_skills(
            _FakeRequest(query_params={"tenant_id": "tenant-upload", "workspace_id": "ws-upload"})
        )
    )
    assert response.status_code == 200
    skills = json.loads(response.body.decode())["skills"]
    assert any(skill["name"] == "policy_clause_audit" for skill in skills)
