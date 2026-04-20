"""Upload and lightweight asset-inspection endpoints."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from config.settings import UPLOAD_DIR, UPLOAD_MAX_FILE_BYTES, UPLOAD_MAX_REQUEST_BYTES
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.api.audit_logging import record_api_audit
from src.api.auth import require_request_role
from src.api.request_scope import ensure_claimed_scope, require_request_scope
from src.blackboard import (
    BusinessDocumentState,
    ExecutionData,
    KnowledgeData,
    StructuredDatasetState,
    TaskNotExistError,
    execution_blackboard,
    global_blackboard,
    knowledge_blackboard,
)
from src.common.control_plane import parser_reports_from_documents
from src.common.utils import generate_uuid, validate_scope_identifier
from src.skillnet.preset_skills import load_preset_skills
from src.storage.repository.memory_repo import MemoryRepo

STRUCTURED_EXTENSIONS = {".csv", ".tsv", ".json"}
BUSINESS_DOCUMENT_EXTENSIONS = {".pdf", ".md", ".txt", ".docx", ".doc"}
UPLOAD_CHUNK_SIZE = 1024 * 1024
_WORKSPACE_UPLOAD_TASK_PREFIX = "workspace_upload"


def _safe_name(file_name: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9._-]+", "_", file_name).strip("._")
    return sanitized or "upload.bin"


def _infer_asset_kind(file_name: str, requested_kind: str | None = None) -> str:
    requested = str(requested_kind or "").strip().lower()
    suffix = Path(file_name).suffix.lower()
    if requested in {"structured_dataset", "business_document"}:
        if requested == "structured_dataset" and suffix in BUSINESS_DOCUMENT_EXTENSIONS:
            raise ValueError("asset_kind_conflicts_with_extension")
        if requested == "structured_dataset" and suffix not in STRUCTURED_EXTENSIONS:
            raise ValueError("unsupported_structured_extension")
        if requested == "business_document" and suffix in STRUCTURED_EXTENSIONS:
            raise ValueError("asset_kind_conflicts_with_extension")
        return requested
    if suffix in STRUCTURED_EXTENSIONS:
        return "structured_dataset"
    if suffix in BUSINESS_DOCUMENT_EXTENSIONS:
        return "business_document"
    return "business_document"


def _append_uploaded_asset(
    execution_data: ExecutionData,
    *,
    file_name: str,
    file_path: str,
    asset_kind: str,
    file_sha256: str,
) -> ExecutionData:
    if asset_kind == "structured_dataset":
        # 结构化数据目前仍然保留在 execution blackboard：
        # 原因是它和 Data Inspector / static codegen / sandbox input mounts
        # 这条执行链耦合非常紧，暂时没有单独拆成 data blackboard。
        #
        # 这里先只做去重，避免重复上传在当前任务里追加多份相同资产。
        existing = {
            (
                str(item.file_sha256 or ""),
                str(item.file_name or ""),
                str(item.path or ""),
            )
            for item in execution_data.inputs.structured_datasets
        }
        if (file_sha256, file_name, file_path) in existing or any(
            item[0] == file_sha256 and file_sha256 for item in existing
        ):
            return execution_data
        execution_data.inputs.structured_datasets.append(
            StructuredDatasetState(
                file_name=file_name,
                path=file_path,
                file_sha256=file_sha256,
                dataset_schema="",
                load_kwargs={},
            )
        )
    else:
        # 业务文档同时属于“执行输入”与“知识资产”。
        # 这里先写 execution_data，随后调用方会显式同步 knowledge blackboard，
        # 保证当前任务链路和知识观察面同时可见。
        existing = {
            (
                str(item.file_sha256 or ""),
                str(item.file_name or ""),
                str(item.path or ""),
            )
            for item in execution_data.inputs.business_documents
        }
        if (file_sha256, file_name, file_path) in existing or any(
            item[0] == file_sha256 and file_sha256 for item in existing
        ):
            return execution_data
        execution_data.inputs.business_documents.append(
            BusinessDocumentState(
                file_name=file_name,
                path=file_path,
                file_sha256=file_sha256,
                status="pending",
                is_newly_uploaded=True,
            )
        )
    return execution_data


def _iter_existing_assets(execution_data: ExecutionData, asset_kind: str) -> list[Any]:
    if asset_kind == "structured_dataset":
        return list(execution_data.inputs.structured_datasets)
    return list(execution_data.inputs.business_documents)


def _find_existing_task_asset(
    execution_data: ExecutionData,
    *,
    asset_kind: str,
    file_name: str,
    file_sha256: str,
) -> tuple[str | None, bool]:
    for item in _iter_existing_assets(execution_data, asset_kind):
        existing_sha = str(getattr(item, "file_sha256", "") or "").strip()
        existing_name = str(getattr(item, "file_name", "") or "").strip()
        existing_path = str(getattr(item, "path", "") or "").strip() or None
        if existing_name == file_name:
            if existing_sha and existing_sha != file_sha256:
                raise ValueError("file_name_conflict")
            return existing_path, bool(existing_sha and existing_sha == file_sha256)
        if existing_sha and existing_sha == file_sha256:
            return existing_path, True
    return None, False


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_target_path(target_dir: Path, file_name: str, file_sha256: str) -> tuple[Path, bool]:
    target_path = target_dir / file_name
    if not target_path.exists():
        return target_path, False
    existing_sha = _hash_file(target_path)
    if existing_sha == file_sha256:
        return target_path, True
    raise ValueError("file_name_conflict")


def _build_temp_upload_path(target_dir: Path, file_name: str) -> Path:
    return target_dir / f".{file_name}.{generate_uuid()}.uploading"


async def _stream_upload_to_temp(upload: Any, temp_path: Path, *, max_bytes: int) -> tuple[str, int]:
    hasher = hashlib.sha256()
    total_size = 0
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    with temp_path.open("wb") as handle:
        supports_sized_reads = True
        while True:
            if supports_sized_reads:
                try:
                    chunk = await upload.read(UPLOAD_CHUNK_SIZE)
                except TypeError:
                    supports_sized_reads = False
                    chunk = await upload.read()
            else:
                chunk = await upload.read()
            if not chunk:
                break
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8")
            hasher.update(chunk)
            handle.write(chunk)
            total_size += len(chunk)
            if total_size > max_bytes:
                raise ValueError("upload_too_large")
            if not supports_sized_reads:
                break
    return hasher.hexdigest(), total_size


def _cleanup_temp_upload(temp_path: Path | None) -> None:
    if not temp_path or not temp_path.exists():
        return
    temp_path.unlink()


def _finalize_staged_upload(temp_path: Path, target_path: Path, file_sha256: str) -> tuple[Path, bool]:
    if target_path.exists():
        existing_sha = _hash_file(target_path)
        if existing_sha == file_sha256:
            _cleanup_temp_upload(temp_path)
            return target_path, True
        raise ValueError("file_name_conflict")
    temp_path.replace(target_path)
    return target_path, False


def _load_execution_for_task(task_id: str) -> tuple[Any, ExecutionData]:
    task = global_blackboard.get_task_state(task_id)
    execution_data = execution_blackboard.read(task.tenant_id, task_id)
    if execution_data is None and execution_blackboard.restore(task.tenant_id, task_id):
        execution_data = execution_blackboard.read(task.tenant_id, task_id)
    if execution_data is None:
        execution_data = ExecutionData(
            task_id=task_id,
            tenant_id=task.tenant_id,
            workspace_id=task.workspace_id,
        )
    return task, execution_data


def _workspace_upload_task_id(file_sha256: str) -> str:
    return f"{_WORKSPACE_UPLOAD_TASK_PREFIX}:{file_sha256[:16]}"


def _is_workspace_upload_task_id(task_id: str | None) -> bool:
    return str(task_id or "").startswith(f"{_WORKSPACE_UPLOAD_TASK_PREFIX}:")


def _iter_uploads(form: Any) -> list[Any]:
    getlist = getattr(form, "getlist", None)
    if callable(getlist):
        uploads = [item for item in getlist("file") if item is not None]
        if uploads:
            return uploads
    upload = form.get("file")
    return [upload] if upload is not None else []


def _resolve_workspace_asset_by_ref(
    *,
    tenant_id: str,
    workspace_id: str,
    asset_ref: str,
) -> tuple[str, Path, str] | None:
    normalized_ref = str(asset_ref or "").strip().lower()
    if not normalized_ref:
        return None
    upload_root = Path(UPLOAD_DIR) / tenant_id / workspace_id
    if not upload_root.exists():
        return None
    for file_path in sorted(upload_root.glob("*")):
        if not file_path.is_file():
            continue
        file_sha256 = _hash_file(file_path)
        if file_sha256.lower() != normalized_ref:
            continue
        return _infer_asset_kind(file_path.name), file_path, file_sha256
    return None


def attach_workspace_assets_to_execution(
    *,
    execution_data: ExecutionData,
    asset_refs: list[str],
) -> ExecutionData:
    tenant_id = str(execution_data.tenant_id)
    workspace_id = str(execution_data.workspace_id)
    for asset_ref in asset_refs:
        resolved = _resolve_workspace_asset_by_ref(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            asset_ref=asset_ref,
        )
        if resolved is None:
            continue
        asset_kind, file_path, file_sha256 = resolved
        _append_uploaded_asset(
            execution_data,
            file_name=file_path.name,
            file_path=str(file_path),
            asset_kind=asset_kind,
            file_sha256=file_sha256,
        )
    if execution_data.inputs.business_documents:
        _sync_task_knowledge_documents(tenant_id, execution_data.task_id, execution_data)
    return execution_data


def _sync_task_knowledge_documents(tenant_id: str, task_id: str, execution_data: ExecutionData) -> None:
    knowledge_data = knowledge_blackboard.read(tenant_id, task_id)
    if knowledge_data is None and knowledge_blackboard.restore(tenant_id, task_id):
        knowledge_data = knowledge_blackboard.read(tenant_id, task_id)
    if knowledge_data is None:
        knowledge_data = KnowledgeData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id=execution_data.workspace_id,
        )
    knowledge_data.business_documents = [
        BusinessDocumentState.model_validate(item.model_dump(mode="json"))
        for item in execution_data.inputs.business_documents
    ]
    knowledge_blackboard.write(tenant_id, task_id, knowledge_data)
    knowledge_blackboard.persist(tenant_id, task_id)


def _sync_workspace_knowledge_document(
    tenant_id: str,
    workspace_id: str,
    *,
    file_name: str,
    file_path: str,
    file_sha256: str,
) -> None:
    task_id = _workspace_upload_task_id(file_sha256)
    knowledge_data = knowledge_blackboard.read(tenant_id, task_id)
    if knowledge_data is None and knowledge_blackboard.restore(tenant_id, task_id):
        knowledge_data = knowledge_blackboard.read(tenant_id, task_id)
    if knowledge_data is None:
        knowledge_data = KnowledgeData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
    knowledge_data.business_documents = [
        BusinessDocumentState(
            file_name=file_name,
            path=file_path,
            file_sha256=file_sha256,
            status="pending",
            is_newly_uploaded=True,
            parse_mode="default",
            parser_diagnostics={},
        )
    ]
    knowledge_blackboard.write(tenant_id, task_id, knowledge_data)
    knowledge_blackboard.persist(tenant_id, task_id)


async def upload_asset(request: Request) -> JSONResponse:
    role_error = require_request_role(request, "operator")
    if role_error is not None:
        return role_error
    form = await request.form()
    uploads = _iter_uploads(form)
    if not uploads:
        return JSONResponse({"error": "missing file field"}, status_code=400)

    requested_tenant_id = str(form.get("tenant_id") or "").strip()
    requested_workspace_id = str(form.get("workspace_id") or "").strip()
    task_id = str(form.get("task_id") or "").strip()
    try:
        if requested_tenant_id:
            requested_tenant_id = validate_scope_identifier(requested_tenant_id, field_name="tenant_id")
        if requested_workspace_id:
            requested_workspace_id = validate_scope_identifier(requested_workspace_id, field_name="workspace_id")
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    execution_data: ExecutionData | None = None
    if task_id:
        try:
            task, execution_data = _load_execution_for_task(task_id)
        except TaskNotExistError:
            return JSONResponse({"error": "task not found", "task_id": task_id}, status_code=404)
        if requested_tenant_id and requested_tenant_id != task.tenant_id:
            return JSONResponse(
                {
                    "error": "task tenant/workspace mismatch",
                    "task_id": task_id,
                    "tenant_id": task.tenant_id,
                    "workspace_id": task.workspace_id,
                },
                status_code=409,
            )
        if requested_workspace_id and requested_workspace_id != task.workspace_id:
            return JSONResponse(
                {
                    "error": "task tenant/workspace mismatch",
                    "task_id": task_id,
                    "tenant_id": task.tenant_id,
                    "workspace_id": task.workspace_id,
                },
                status_code=409,
            )
        tenant_id = task.tenant_id
        workspace_id = task.workspace_id
        scope_error = ensure_claimed_scope(
            request,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        if scope_error is not None:
            record_api_audit(
                request,
                action="asset.upload",
                outcome="denied",
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                task_id=task_id or None,
                resource_type="asset_upload",
                metadata={"reason": "scope_forbidden"},
            )
            return scope_error
    else:
        tenant_id = requested_tenant_id
        workspace_id = requested_workspace_id
        if not tenant_id or not workspace_id:
            return JSONResponse(
                {
                    "error": "missing tenant/workspace scope",
                    "required_form_fields": ["tenant_id", "workspace_id"],
                },
                status_code=400,
            )
        scope_error = ensure_claimed_scope(
            request,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        if scope_error is not None:
            record_api_audit(
                request,
                action="asset.upload",
                outcome="denied",
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                resource_type="asset_upload",
                metadata={"reason": "scope_forbidden"},
            )
            return scope_error

    target_dir = Path(UPLOAD_DIR) / tenant_id / workspace_id
    uploaded_items: list[dict[str, Any]] = []
    total_request_size = 0
    for upload in uploads:
        safe_name = _safe_name(getattr(upload, "filename", "upload.bin"))
        deduplicated = False
        payload_size = 0
        try:
            asset_kind = _infer_asset_kind(getattr(upload, "filename", "upload.bin"), str(form.get("asset_kind") or ""))
        except ValueError as exc:
            return JSONResponse({"error": str(exc), "file_name": safe_name}, status_code=400)
        temp_path = _build_temp_upload_path(target_dir, safe_name)
        try:
            payload_sha256, payload_size = await _stream_upload_to_temp(
                upload,
                temp_path,
                max_bytes=UPLOAD_MAX_FILE_BYTES,
            )
            total_request_size += payload_size
            if total_request_size > UPLOAD_MAX_REQUEST_BYTES:
                _cleanup_temp_upload(temp_path)
                return JSONResponse(
                    {
                        "error": "upload_request_too_large",
                        "max_request_bytes": UPLOAD_MAX_REQUEST_BYTES,
                    },
                    status_code=413,
                )
            if task_id and execution_data is not None:
                try:
                    existing_path, deduplicated = _find_existing_task_asset(
                        execution_data,
                        asset_kind=asset_kind,
                        file_name=safe_name,
                        file_sha256=payload_sha256,
                    )
                except ValueError:
                    _cleanup_temp_upload(temp_path)
                    return JSONResponse(
                        {"error": "file_name_conflict", "task_id": task_id, "file_name": safe_name},
                        status_code=409,
                    )
                if existing_path:
                    target_path = Path(existing_path)
                    if not deduplicated:
                        try:
                            target_path, deduplicated = _resolve_target_path(
                                target_path.parent,
                                target_path.name,
                                payload_sha256,
                            )
                        except ValueError:
                            _cleanup_temp_upload(temp_path)
                            return JSONResponse(
                                {"error": "file_name_conflict", "task_id": task_id, "file_name": target_path.name},
                                status_code=409,
                            )
                else:
                    try:
                        target_path, deduplicated = _resolve_target_path(target_dir, safe_name, payload_sha256)
                    except ValueError:
                        _cleanup_temp_upload(temp_path)
                        return JSONResponse(
                            {"error": "file_name_conflict", "task_id": task_id, "file_name": safe_name},
                            status_code=409,
                        )
                if deduplicated:
                    _cleanup_temp_upload(temp_path)
                else:
                    try:
                        target_path, deduplicated = _finalize_staged_upload(temp_path, target_path, payload_sha256)
                    except ValueError:
                        _cleanup_temp_upload(temp_path)
                        return JSONResponse(
                            {"error": "file_name_conflict", "task_id": task_id, "file_name": target_path.name},
                            status_code=409,
                        )
                _append_uploaded_asset(
                    execution_data,
                    file_name=target_path.name,
                    file_path=str(target_path),
                    asset_kind=asset_kind,
                    file_sha256=payload_sha256,
                )
                execution_blackboard.write(tenant_id, task_id, execution_data)
                execution_blackboard.persist(tenant_id, task_id)
                if asset_kind == "business_document":
                    _sync_task_knowledge_documents(tenant_id, task_id, execution_data)
            else:
                try:
                    target_path, deduplicated = _resolve_target_path(target_dir, safe_name, payload_sha256)
                except ValueError:
                    _cleanup_temp_upload(temp_path)
                    return JSONResponse(
                        {
                            "error": "file_name_conflict",
                            "file_name": safe_name,
                            "tenant_id": tenant_id,
                            "workspace_id": workspace_id,
                        },
                        status_code=409,
                    )
                if deduplicated:
                    _cleanup_temp_upload(temp_path)
                else:
                    try:
                        target_path, deduplicated = _finalize_staged_upload(temp_path, target_path, payload_sha256)
                    except ValueError:
                        _cleanup_temp_upload(temp_path)
                        return JSONResponse(
                            {
                                "error": "file_name_conflict",
                                "file_name": safe_name,
                                "tenant_id": tenant_id,
                                "workspace_id": workspace_id,
                            },
                            status_code=409,
                        )
                if asset_kind == "business_document":
                    _sync_workspace_knowledge_document(
                        tenant_id,
                        workspace_id,
                        file_name=target_path.name,
                        file_path=str(target_path),
                        file_sha256=payload_sha256,
                    )
        except ValueError as exc:
            _cleanup_temp_upload(temp_path)
            if str(exc) == "upload_too_large":
                return JSONResponse(
                    {
                        "error": "upload_file_too_large",
                        "file_name": safe_name,
                        "max_file_bytes": UPLOAD_MAX_FILE_BYTES,
                    },
                    status_code=413,
                )
            raise
        except Exception:
            _cleanup_temp_upload(temp_path)
            raise

        item_payload = {
            "uploaded": True,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "task_id": task_id or None,
            "asset_kind": asset_kind,
            "file_name": target_path.name,
            "path": str(target_path),
            "file_sha256": payload_sha256,
            "size": payload_size,
            "deduplicated": deduplicated,
        }
        uploaded_items.append(item_payload)
        record_api_audit(
            request,
            action="asset.upload",
            outcome="success",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            task_id=task_id or None,
            resource_type="asset_upload",
            resource_id=str(target_path),
            metadata={
                "asset_kind": asset_kind,
                "file_name": target_path.name,
                "deduplicated": deduplicated,
                "size": payload_size,
            },
        )
    if len(uploaded_items) == 1:
        return JSONResponse(uploaded_items[0])
    return JSONResponse(
        {
            "uploaded": True,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "task_id": task_id or None,
            "uploaded_files": uploaded_items,
            "file_count": len(uploaded_items),
        }
    )


async def list_knowledge_assets(request: Request) -> JSONResponse:
    role_error = require_request_role(request, "viewer")
    if role_error is not None:
        return role_error
    scope = require_request_scope(request)
    if isinstance(scope, JSONResponse):
        return scope
    tenant_id, workspace_id = scope
    scope_error = ensure_claimed_scope(
        request,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    if scope_error is not None:
        record_api_audit(
            request,
            action="workspace.assets.read",
            outcome="denied",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            resource_type="workspace_assets",
            metadata={"reason": "scope_forbidden"},
        )
        return scope_error

    assets: list[dict[str, Any]] = []
    # 资产查询不再直接扫描 StateRepo 原始 blob，而是通过黑板接口读取。
    # 这样 knowledge / execution 两个子域的读取边界会更稳定：
    # - 业务文档资产 -> knowledge blackboard
    # - 结构化数据资产 -> execution blackboard
    execution_states = execution_blackboard.list_workspace_states(tenant_id, workspace_id)
    for execution_data in execution_states:
        for dataset in execution_data.inputs.structured_datasets:
            # 结构化数据目前仍由 execution blackboard 持有。
            # 这是当前边界设计的显式结论，不是暂时遗漏。
            assets.append(
                {
                    "kind": "structured_dataset",
                    "task_id": execution_data.task_id,
                    "file_name": dataset.file_name,
                    "path": dataset.path,
                    "schema_ready": bool(dataset.dataset_schema),
                    "load_kwargs": dataset.load_kwargs,
                }
            )

    knowledge_states = knowledge_blackboard.list_workspace_states(tenant_id, workspace_id)
    business_assets_by_path: dict[str, dict[str, Any]] = {}
    for knowledge_data in knowledge_states:
        parser_reports = {
            str(item.get("file_name") or ""): item
            for item in parser_reports_from_documents(knowledge_data.business_documents)
            if isinstance(item, dict)
        }
        for document in knowledge_data.business_documents:
            file_name = str(document.file_name or Path(str(document.path or "")).name)
            parser_report = parser_reports.get(file_name, {})
            candidate = {
                "kind": "business_document",
                "task_id": knowledge_data.task_id,
                "file_name": file_name,
                "path": document.path,
                "status": document.status,
                "parse_mode": parser_report.get("parse_mode", document.parse_mode),
                "parser_diagnostics": parser_report.get("parser_diagnostics", document.parser_diagnostics),
            }
            asset_key = str(document.path or f"{knowledge_data.task_id}:{file_name}")
            existing = business_assets_by_path.get(asset_key)
            if existing is None:
                business_assets_by_path[asset_key] = candidate
                continue
            existing_is_workspace = _is_workspace_upload_task_id(existing.get("task_id"))
            candidate_is_workspace = _is_workspace_upload_task_id(candidate.get("task_id"))
            if existing_is_workspace and not candidate_is_workspace:
                business_assets_by_path[asset_key] = candidate
                continue
            if existing.get("status") != "parsed" and candidate.get("status") == "parsed":
                business_assets_by_path[asset_key] = candidate
                continue
            if existing.get("parse_mode") == "default" and candidate.get("parse_mode") != "default":
                business_assets_by_path[asset_key] = candidate
    assets.extend(business_assets_by_path.values())

    upload_root = Path(UPLOAD_DIR) / tenant_id / workspace_id
    upload_files = sorted(upload_root.glob("*")) if upload_root.exists() else []
    for file_path in upload_files:
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

    record_api_audit(
        request,
        action="workspace.assets.read",
        outcome="success",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        resource_type="workspace_assets",
        metadata={"asset_count": len(assets)},
    )
    return JSONResponse({"tenant_id": tenant_id, "workspace_id": workspace_id, "assets": assets})


async def list_workspace_skills(request: Request) -> JSONResponse:
    role_error = require_request_role(request, "viewer")
    if role_error is not None:
        return role_error
    scope = require_request_scope(request)
    if isinstance(scope, JSONResponse):
        return scope
    tenant_id, workspace_id = scope
    scope_error = ensure_claimed_scope(
        request,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    if scope_error is not None:
        record_api_audit(
            request,
            action="workspace.skills.read",
            outcome="denied",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            resource_type="workspace_skills",
            metadata={"reason": "scope_forbidden"},
        )
        return scope_error
    stored_skills = MemoryRepo.list_approved_skills(tenant_id, workspace_id, limit=100)
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
    record_api_audit(
        request,
        action="workspace.skills.read",
        outcome="success",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        resource_type="workspace_skills",
        metadata={"skill_count": len(skills)},
    )
    return JSONResponse({"tenant_id": tenant_id, "workspace_id": workspace_id, "skills": skills})
