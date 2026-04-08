"""Tests for upload and workspace asset endpoints."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from config.settings import UPLOAD_DIR
from src.api.routers.knowledge_router import get_task_knowledge
from src.api.routers.upload_router import list_knowledge_assets, list_workspace_skills, upload_asset
from src.blackboard import execution_blackboard, global_blackboard, knowledge_blackboard


class _FakeUploadFile:
    def __init__(self, filename: str, payload: bytes) -> None:
        self.filename = filename
        self._payload = payload

    async def read(self) -> bytes:
        return self._payload


class _ChunkedUploadFile:
    def __init__(self, filename: str, payload: bytes, chunk_size: int = 4) -> None:
        self.filename = filename
        self._payload = payload
        self._chunk_size = chunk_size
        self._offset = 0
        self.read_sizes: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if self._offset >= len(self._payload):
            return b""
        if size is None or size < 0:
            size = len(self._payload) - self._offset
        size = min(size, self._chunk_size)
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class _FakeRequest:
    def __init__(self, *, form_data=None, query_params=None) -> None:
        self._form_data = form_data or {}
        self.query_params = query_params or {}

    async def form(self):
        return self._form_data


class _FakeTaskRequest:
    def __init__(self, task_id: str, *, tenant_id: str, workspace_id: str) -> None:
        self.path_params = {"task_id": task_id}
        self.query_params = {"tenant_id": tenant_id, "workspace_id": workspace_id}


def _clear_upload_dir(tenant_id: str, workspace_id: str) -> None:
    upload_dir = Path(UPLOAD_DIR) / tenant_id / workspace_id
    if not upload_dir.exists():
        return
    for path in upload_dir.glob("*"):
        if path.is_file():
            path.unlink()


def test_upload_asset_and_list_workspace_assets():
    _clear_upload_dir("tenant-upload", "ws-upload")
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
    assert payload["deduplicated"] is False

    assets_response = asyncio.run(
        list_knowledge_assets(
            _FakeRequest(query_params={"tenant_id": "tenant-upload", "workspace_id": "ws-upload"})
        )
    )
    assert assets_response.status_code == 200
    assets = json.loads(assets_response.body.decode())["assets"]
    assert any(asset["file_name"] == "sales.csv" for asset in assets)


def test_workspace_business_document_upload_enters_typed_knowledge_state():
    _clear_upload_dir("tenant-upload-workspace-doc", "ws-upload-workspace-doc")
    request = _FakeRequest(
        form_data={
            "tenant_id": "tenant-upload-workspace-doc",
            "workspace_id": "ws-upload-workspace-doc",
            "asset_kind": "business_document",
            "file": _FakeUploadFile("rule.txt", b"rule body"),
        }
    )

    response = asyncio.run(upload_asset(request))
    assets_response = asyncio.run(
        list_knowledge_assets(
            _FakeRequest(query_params={"tenant_id": "tenant-upload-workspace-doc", "workspace_id": "ws-upload-workspace-doc"})
        )
    )
    assets = json.loads(assets_response.body.decode())["assets"]
    typed_asset = next(asset for asset in assets if asset["file_name"] == "rule.txt")
    knowledge_states = knowledge_blackboard.list_workspace_states("tenant-upload-workspace-doc", "ws-upload-workspace-doc")

    assert response.status_code == 200
    assert typed_asset["kind"] == "business_document"
    assert typed_asset["status"] == "pending"
    assert typed_asset["parse_mode"] == "default"
    assert knowledge_states
    assert knowledge_states[0].business_documents[0].file_name == "rule.txt"


def test_upload_asset_supports_chunked_reads():
    _clear_upload_dir("tenant-upload-chunked", "ws-upload-chunked")
    upload = _ChunkedUploadFile("sales.csv", b"region,amount\nsh,10\n", chunk_size=5)
    request = _FakeRequest(
        form_data={
            "tenant_id": "tenant-upload-chunked",
            "workspace_id": "ws-upload-chunked",
            "asset_kind": "structured_dataset",
            "file": upload,
        }
    )

    response = asyncio.run(upload_asset(request))
    body = json.loads(response.body.decode())

    assert response.status_code == 200
    assert body["size"] == len(b"region,amount\nsh,10\n")
    assert len(upload.read_sizes) >= 2


def test_upload_asset_is_idempotent_per_task():
    _clear_upload_dir("tenant-upload-idempotent", "ws-upload-idempotent")
    task_id = global_blackboard.create_task(
        "tenant-upload-idempotent",
        "ws-upload-idempotent",
        "upload",
    )
    request = _FakeRequest(
        form_data={
            "tenant_id": "tenant-upload-idempotent",
            "workspace_id": "ws-upload-idempotent",
            "task_id": task_id,
            "asset_kind": "business_document",
            "file": _FakeUploadFile("rule.txt", b"rule body"),
        }
    )
    first = asyncio.run(upload_asset(request))
    second = asyncio.run(upload_asset(request))

    assert first.status_code == 200
    assert second.status_code == 200
    assert json.loads(second.body.decode())["deduplicated"] is True

    assets_response = asyncio.run(
        list_knowledge_assets(
            _FakeRequest(query_params={"tenant_id": "tenant-upload-idempotent", "workspace_id": "ws-upload-idempotent"})
        )
    )
    assets = [asset for asset in json.loads(assets_response.body.decode())["assets"] if asset["file_name"] == "rule.txt"]
    assert len(assets) == 1
    execution_data = execution_blackboard.read("tenant-upload-idempotent", task_id)
    assert execution_data is not None
    assert len(execution_data.inputs.business_documents) == 1
    knowledge_data = knowledge_blackboard.read("tenant-upload-idempotent", task_id)
    assert knowledge_data is not None
    assert len(knowledge_data.business_documents) == 1


def test_upload_asset_deduplicates_same_payload_even_if_filename_changes():
    _clear_upload_dir("tenant-upload-hash", "ws-upload-hash")
    task_id = global_blackboard.create_task(
        "tenant-upload-hash",
        "ws-upload-hash",
        "upload",
    )
    request_a = _FakeRequest(
        form_data={
            "tenant_id": "tenant-upload-hash",
            "workspace_id": "ws-upload-hash",
            "task_id": task_id,
            "asset_kind": "business_document",
            "file": _FakeUploadFile("rule-a.txt", b"same payload"),
        }
    )
    request_b = _FakeRequest(
        form_data={
            "tenant_id": "tenant-upload-hash",
            "workspace_id": "ws-upload-hash",
            "task_id": task_id,
            "asset_kind": "business_document",
            "file": _FakeUploadFile("rule-b.txt", b"same payload"),
        }
    )

    first = asyncio.run(upload_asset(request_a))
    second = asyncio.run(upload_asset(request_b))

    execution_data = execution_blackboard.read("tenant-upload-hash", task_id)
    assert execution_data is not None
    assert len(execution_data.inputs.business_documents) == 1
    assert execution_data.inputs.business_documents[0].file_sha256
    first_body = json.loads(first.body.decode())
    second_body = json.loads(second.body.decode())
    assert first_body["deduplicated"] is False
    assert second_body["deduplicated"] is True
    upload_dir = Path(UPLOAD_DIR) / "tenant-upload-hash" / "ws-upload-hash"
    assert sorted(path.name for path in upload_dir.glob("*")) == ["rule-a.txt"]


def test_upload_asset_restores_existing_execution_state_before_append():
    _clear_upload_dir("tenant-upload-restore", "ws-upload-restore")
    task_id = global_blackboard.create_task(
        "tenant-upload-restore",
        "ws-upload-restore",
        "upload",
    )
    execution_data = execution_blackboard.read("tenant-upload-restore", task_id)
    if execution_data is None:
        from src.blackboard.schema import ExecutionData

        execution_data = ExecutionData(
            task_id=task_id,
            tenant_id="tenant-upload-restore",
            workspace_id="ws-upload-restore",
        )
    execution_data.static.analysis_plan = "keep-me"
    execution_data.control.final_response = {"headline": "keep-me"}
    execution_blackboard.write("tenant-upload-restore", task_id, execution_data)
    execution_blackboard.persist("tenant-upload-restore", task_id)
    execution_blackboard._storage.clear()

    request = _FakeRequest(
        form_data={
            "tenant_id": "tenant-upload-restore",
            "workspace_id": "ws-upload-restore",
            "task_id": task_id,
            "asset_kind": "business_document",
            "file": _FakeUploadFile("rule.txt", b"rule body"),
        }
    )
    response = asyncio.run(upload_asset(request))
    assert execution_blackboard.restore("tenant-upload-restore", task_id) is True
    refreshed = execution_blackboard.read("tenant-upload-restore", task_id)

    assert response.status_code == 200
    assert refreshed is not None
    assert refreshed.static.analysis_plan == "keep-me"
    assert refreshed.control.final_response == {"headline": "keep-me"}
    assert len(refreshed.inputs.business_documents) == 1


def test_upload_asset_rejects_mismatched_task_scope():
    _clear_upload_dir("tenant-upload-scope", "ws-upload-scope")
    task_id = global_blackboard.create_task(
        "tenant-upload-scope",
        "ws-upload-scope",
        "upload",
    )
    request = _FakeRequest(
        form_data={
            "tenant_id": "other-tenant",
            "workspace_id": "ws-upload-scope",
            "task_id": task_id,
            "asset_kind": "business_document",
            "file": _FakeUploadFile("rule.txt", b"rule body"),
        }
    )

    response = asyncio.run(upload_asset(request))
    body = json.loads(response.body.decode())

    assert response.status_code == 409
    assert body["error"] == "task tenant/workspace mismatch"


def test_upload_asset_returns_404_without_leaving_orphan_file():
    _clear_upload_dir("tenant-upload-orphan", "ws-upload-orphan")
    request = _FakeRequest(
        form_data={
            "tenant_id": "tenant-upload-orphan",
            "workspace_id": "ws-upload-orphan",
            "task_id": "missing-task",
            "asset_kind": "business_document",
            "file": _FakeUploadFile("orphan.txt", b"rule body"),
        }
    )

    response = asyncio.run(upload_asset(request))
    body = json.loads(response.body.decode())
    upload_path = Path(UPLOAD_DIR) / "tenant-upload-orphan" / "ws-upload-orphan" / "orphan.txt"

    assert response.status_code == 404
    assert body["error"] == "task not found"
    assert upload_path.exists() is False


def test_upload_asset_rejects_same_name_with_different_payload():
    _clear_upload_dir("tenant-upload-conflict", "ws-upload-conflict")
    request_a = _FakeRequest(
        form_data={
            "tenant_id": "tenant-upload-conflict",
            "workspace_id": "ws-upload-conflict",
            "asset_kind": "business_document",
            "file": _FakeUploadFile("rule.txt", b"payload-a"),
        }
    )
    request_b = _FakeRequest(
        form_data={
            "tenant_id": "tenant-upload-conflict",
            "workspace_id": "ws-upload-conflict",
            "asset_kind": "business_document",
            "file": _FakeUploadFile("rule.txt", b"payload-b"),
        }
    )

    first = asyncio.run(upload_asset(request_a))
    second = asyncio.run(upload_asset(request_b))

    assert first.status_code == 200
    assert second.status_code == 409
    assert json.loads(second.body.decode())["error"] == "file_name_conflict"


def test_list_workspace_skills_includes_preset_skills():
    response = asyncio.run(
        list_workspace_skills(
            _FakeRequest(query_params={"tenant_id": "tenant-upload", "workspace_id": "ws-upload"})
        )
    )
    assert response.status_code == 200
    skills = json.loads(response.body.decode())["skills"]
    assert any(skill["name"] == "policy_clause_audit" for skill in skills)


def test_list_knowledge_assets_reads_via_blackboard_accessors(monkeypatch):
    knowledge_called = {"value": False}
    execution_called = {"value": False}

    def fake_list_knowledge(tenant_id, workspace_id):
        knowledge_called["value"] = True
        return []

    def fake_list_execution(tenant_id, workspace_id):
        execution_called["value"] = True
        return []

    monkeypatch.setattr(knowledge_blackboard, "list_workspace_states", fake_list_knowledge)
    monkeypatch.setattr(execution_blackboard, "list_workspace_states", fake_list_execution)

    response = asyncio.run(
        list_knowledge_assets(
            _FakeRequest(query_params={"tenant_id": "tenant-upload", "workspace_id": "ws-upload"})
        )
    )

    assert response.status_code == 200
    assert knowledge_called["value"] is True
    assert execution_called["value"] is True


def test_get_task_knowledge_reads_via_knowledge_blackboard():
    task_id = global_blackboard.create_task(
        "tenant-task-knowledge",
        "ws-task-knowledge",
        "upload",
    )
    request = _FakeRequest(
        form_data={
            "tenant_id": "tenant-task-knowledge",
            "workspace_id": "ws-task-knowledge",
            "task_id": task_id,
            "asset_kind": "business_document",
            "file": _FakeUploadFile("rule.txt", b"rule body"),
        }
    )
    asyncio.run(upload_asset(request))

    response = asyncio.run(
        get_task_knowledge(
            _FakeTaskRequest(
                task_id,
                tenant_id="tenant-task-knowledge",
                workspace_id="ws-task-knowledge",
            )
        )
    )
    body = json.loads(response.body.decode())

    assert response.status_code == 200
    assert body["task"]["task_id"] == task_id
    assert body["knowledge"]["business_documents"][0]["file_name"] == "rule.txt"
    assert "parser_reports" in body["knowledge"]
