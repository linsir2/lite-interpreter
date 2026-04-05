"""Upload and lightweight asset-inspection endpoints."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from config.settings import UPLOAD_DIR
from src.blackboard import ExecutionData, TaskNotExistError, execution_blackboard, global_blackboard
from src.skillnet.preset_skills import load_preset_skills
from src.storage.repository.skill_repo import SkillRepo
from src.storage.repository.state_repo import StateRepo

STRUCTURED_EXTENSIONS = {".csv", ".tsv", ".xlsx", ".xls", ".parquet", ".json"}
BUSINESS_DOCUMENT_EXTENSIONS = {".pdf", ".md", ".txt", ".docx", ".doc"}


def _safe_name(file_name: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9._-]+", "_", file_name).strip("._")
    return sanitized or "upload.bin"


def _infer_asset_kind(file_name: str, requested_kind: str | None = None) -> str:
    requested = str(requested_kind or "").strip().lower()
    if requested in {"structured_dataset", "business_document"}:
        return requested
    suffix = Path(file_name).suffix.lower()
    if suffix in STRUCTURED_EXTENSIONS:
        return "structured_dataset"
    if suffix in BUSINESS_DOCUMENT_EXTENSIONS:
        return "business_document"
    return "business_document"


def _append_uploaded_asset(execution_data: ExecutionData, *, file_name: str, file_path: str, asset_kind: str) -> ExecutionData:
    if asset_kind == "structured_dataset":
        execution_data.structured_datasets.append(
            {
                "file_name": file_name,
                "path": file_path,
                "schema": "",
                "load_kwargs": {},
            }
        )
    else:
        execution_data.business_documents.append(
            {
                "file_name": file_name,
                "path": file_path,
                "status": "pending",
                "is_newly_uploaded": True,
            }
        )
    return execution_data


async def upload_asset(request: Request) -> JSONResponse:
    form = await request.form()
    upload = form.get("file")
    if upload is None:
        return JSONResponse({"error": "missing file field"}, status_code=400)

    tenant_id = str(form.get("tenant_id") or "demo-tenant")
    workspace_id = str(form.get("workspace_id") or "demo-workspace")
    task_id = str(form.get("task_id") or "").strip()
    asset_kind = _infer_asset_kind(getattr(upload, "filename", "upload.bin"), str(form.get("asset_kind") or ""))
    safe_name = _safe_name(getattr(upload, "filename", "upload.bin"))

    target_dir = Path(UPLOAD_DIR) / tenant_id / workspace_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / safe_name
    payload = await upload.read()
    target_path.write_bytes(payload)

    if task_id:
        try:
            task = global_blackboard.get_task_state(task_id)
        except TaskNotExistError:
            return JSONResponse({"error": "task not found", "task_id": task_id}, status_code=404)
        execution_data = execution_blackboard.read(task.tenant_id, task_id) or ExecutionData(
            task_id=task_id,
            tenant_id=task.tenant_id,
            workspace_id=task.workspace_id,
        )
        _append_uploaded_asset(execution_data, file_name=safe_name, file_path=str(target_path), asset_kind=asset_kind)
        execution_blackboard.write(task.tenant_id, task_id, execution_data)
        execution_blackboard.persist(task.tenant_id, task_id)

    return JSONResponse(
        {
            "uploaded": True,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "task_id": task_id or None,
            "asset_kind": asset_kind,
            "file_name": safe_name,
            "path": str(target_path),
            "size": len(payload),
        }
    )


async def list_knowledge_assets(request: Request) -> JSONResponse:
    tenant_id = str(request.query_params.get("tenant_id") or "demo-tenant")
    workspace_id = str(request.query_params.get("workspace_id") or "demo-workspace")

    assets: list[dict[str, Any]] = []
    for state in StateRepo.list_blackboard_states():
        execution = state.get("execution") or {}
        if not isinstance(execution, dict):
            continue
        if str(execution.get("tenant_id") or "") != tenant_id:
            continue
        if str(execution.get("workspace_id") or "") != workspace_id:
            continue

        for dataset in execution.get("structured_datasets", []) or []:
            assets.append(
                {
                    "kind": "structured_dataset",
                    "task_id": execution.get("task_id"),
                    "file_name": dataset.get("file_name"),
                    "path": dataset.get("path"),
                    "schema_ready": bool(dataset.get("schema")),
                    "load_kwargs": dataset.get("load_kwargs", {}),
                }
            )
        parser_reports = {str(item.get("file_name")): item for item in (execution.get("parser_reports") or []) if isinstance(item, dict)}
        for document in execution.get("business_documents", []) or []:
            file_name = str(document.get("file_name") or Path(str(document.get("path") or "")).name)
            parser_report = parser_reports.get(file_name, {})
            assets.append(
                {
                    "kind": "business_document",
                    "task_id": execution.get("task_id"),
                    "file_name": file_name,
                    "path": document.get("path"),
                    "status": document.get("status"),
                    "parse_mode": parser_report.get("parse_mode", "default"),
                    "parser_diagnostics": parser_report.get("parser_diagnostics", {}),
                }
            )

    upload_root = Path(UPLOAD_DIR) / tenant_id / workspace_id
    for file_path in sorted(upload_root.glob("*")) if upload_root.exists() else []:
        if not any(asset.get("path") == str(file_path) for asset in assets):
            assets.append(
                {
                    "kind": _infer_asset_kind(file_path.name),
                    "task_id": None,
                    "file_name": file_path.name,
                    "path": str(file_path),
                    "size": file_path.stat().st_size,
                }
            )

    return JSONResponse({"tenant_id": tenant_id, "workspace_id": workspace_id, "assets": assets})


async def list_workspace_skills(request: Request) -> JSONResponse:
    tenant_id = str(request.query_params.get("tenant_id") or "demo-tenant")
    workspace_id = str(request.query_params.get("workspace_id") or "demo-workspace")
    stored_skills = SkillRepo.list_approved_skills(tenant_id, workspace_id, limit=100)
    preset_skills = []
    for descriptor in load_preset_skills():
        payload = descriptor.to_payload()
        payload["metadata"] = {
            **dict(payload.get("metadata", {}) or {}),
            "match_source": "preset_seed",
        }
        preset_skills.append(payload)
    seen = {str(skill.get("name", "")) for skill in stored_skills}
    skills = list(stored_skills) + [skill for skill in preset_skills if str(skill.get("name", "")) not in seen]
    return JSONResponse({"tenant_id": tenant_id, "workspace_id": workspace_id, "skills": skills})
