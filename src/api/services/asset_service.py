"""Internal services for workspace asset upload and attachment."""

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
from src.api.request_scope import ensure_claimed_scope
from src.api.schemas import api_error_response
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
from src.common.utils import generate_uuid, validate_scope_identifier

STRUCTURED_EXTENSIONS = {".csv", ".tsv", ".json"}
BUSINESS_DOCUMENT_EXTENSIONS = {".pdf", ".md", ".txt", ".docx", ".doc"}
UPLOAD_STREAM_CHUNK_SIZE = 1024 * 1024
_WORKSPACE_UPLOAD_TASK_PREFIX = "workspace_upload"


def safe_upload_name(file_name: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9._-]+", "_", file_name).strip("._")
    return sanitized or "upload.bin"


def infer_asset_kind(file_name: str, requested_kind: str | None = None) -> str:
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
        existing = {
            (
                str(item.file_sha256 or ""),
                str(item.file_name or ""),
                str(item.path or ""),
            )
            for item in execution_data.inputs.structured_datasets
        }
        if (file_sha256, file_name, file_path) in existing or any(item[0] == file_sha256 and file_sha256 for item in existing):
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
        existing = {
            (
                str(item.file_sha256 or ""),
                str(item.file_name or ""),
                str(item.path or ""),
            )
            for item in execution_data.inputs.business_documents
        }
        if (file_sha256, file_name, file_path) in existing or any(item[0] == file_sha256 and file_sha256 for item in existing):
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
    return list(execution_data.inputs.structured_datasets) if asset_kind == "structured_dataset" else list(execution_data.inputs.business_documents)


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


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_target_path(target_dir: Path, file_name: str, file_sha256: str) -> tuple[Path, bool]:
    target_path = target_dir / file_name
    if not target_path.exists():
        return target_path, False
    existing_sha = hash_file(target_path)
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
                    chunk = await upload.read(UPLOAD_STREAM_CHUNK_SIZE)
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
    if temp_path and temp_path.exists():
        temp_path.unlink()


def _finalize_staged_upload(temp_path: Path, target_path: Path, file_sha256: str) -> tuple[Path, bool]:
    if target_path.exists():
        existing_sha = hash_file(target_path)
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
        execution_data = ExecutionData(task_id=task_id, tenant_id=task.tenant_id, workspace_id=task.workspace_id)
    return task, execution_data


def workspace_upload_task_id(file_sha256: str) -> str:
    return f"{_WORKSPACE_UPLOAD_TASK_PREFIX}:{file_sha256[:16]}"


def is_workspace_upload_task_id(task_id: str | None) -> bool:
    return str(task_id or "").startswith(f"{_WORKSPACE_UPLOAD_TASK_PREFIX}:")


def iter_uploads(form: Any) -> list[Any]:
    getlist = getattr(form, "getlist", None)
    if callable(getlist):
        uploads = [item for item in getlist("file") if item is not None]
        if uploads:
            return uploads
    upload = form.get("file")
    return [upload] if upload is not None else []


def resolve_workspace_asset_by_ref(*, tenant_id: str, workspace_id: str, asset_ref: str) -> tuple[str, Path, str] | None:
    normalized_ref = str(asset_ref or "").strip().lower()
    if not normalized_ref:
        return None
    upload_root = Path(UPLOAD_DIR) / tenant_id / workspace_id
    if not upload_root.exists():
        return None
    for file_path in sorted(upload_root.glob("*")):
        if not file_path.is_file():
            continue
        file_sha256 = hash_file(file_path)
        if file_sha256.lower() != normalized_ref:
            continue
        return infer_asset_kind(file_path.name), file_path, file_sha256
    return None


def sync_task_knowledge_documents(tenant_id: str, task_id: str, execution_data: ExecutionData) -> None:
    knowledge_data = knowledge_blackboard.read(tenant_id, task_id)
    if knowledge_data is None and knowledge_blackboard.restore(tenant_id, task_id):
        knowledge_data = knowledge_blackboard.read(tenant_id, task_id)
    if knowledge_data is None:
        knowledge_data = KnowledgeData(task_id=task_id, tenant_id=tenant_id, workspace_id=execution_data.workspace_id)
    knowledge_data.business_documents = [
        BusinessDocumentState.model_validate(item.model_dump(mode="json"))
        for item in execution_data.inputs.business_documents
    ]
    knowledge_blackboard.write(tenant_id, task_id, knowledge_data)
    knowledge_blackboard.persist(tenant_id, task_id)


def sync_workspace_knowledge_document(
    tenant_id: str,
    workspace_id: str,
    *,
    file_name: str,
    file_path: str,
    file_sha256: str,
) -> None:
    task_id = workspace_upload_task_id(file_sha256)
    knowledge_data = knowledge_blackboard.read(tenant_id, task_id)
    if knowledge_data is None and knowledge_blackboard.restore(tenant_id, task_id):
        knowledge_data = knowledge_blackboard.read(tenant_id, task_id)
    if knowledge_data is None:
        knowledge_data = KnowledgeData(task_id=task_id, tenant_id=tenant_id, workspace_id=workspace_id)
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


def attach_workspace_assets_to_execution(*, execution_data: ExecutionData, asset_refs: list[str]) -> ExecutionData:
    tenant_id = str(execution_data.tenant_id)
    workspace_id = str(execution_data.workspace_id)
    for asset_ref in asset_refs:
        resolved = resolve_workspace_asset_by_ref(tenant_id=tenant_id, workspace_id=workspace_id, asset_ref=asset_ref)
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
        sync_task_knowledge_documents(tenant_id, execution_data.task_id, execution_data)
    return execution_data


async def upload_assets_from_request(request: Request) -> JSONResponse:
    role_error = require_request_role(request, "operator")
    if role_error is not None:
        return role_error
    form = await request.form()
    uploads = iter_uploads(form)
    if not uploads:
        return api_error_response("MISSING_FILE_FIELD", "Missing file field.", status_code=400)

    requested_tenant_id = str(form.get("tenant_id") or "").strip()
    requested_workspace_id = str(form.get("workspace_id") or "").strip()
    task_id = str(form.get("task_id") or "").strip()
    try:
        if requested_tenant_id:
            requested_tenant_id = validate_scope_identifier(requested_tenant_id, field_name="tenant_id")
        if requested_workspace_id:
            requested_workspace_id = validate_scope_identifier(requested_workspace_id, field_name="workspace_id")
    except ValueError as exc:
        return api_error_response("INVALID_SCOPE", str(exc), status_code=400)

    execution_data: ExecutionData | None = None
    if task_id:
        try:
            task, execution_data = _load_execution_for_task(task_id)
        except TaskNotExistError:
            return api_error_response("TASK_NOT_FOUND", "Task not found.", status_code=404, details={"taskId": task_id})
        if requested_tenant_id and requested_tenant_id != task.tenant_id:
            return api_error_response(
                "TASK_SCOPE_MISMATCH",
                "Task tenant/workspace mismatch.",
                status_code=409,
                details={"taskId": task_id, "tenantId": task.tenant_id, "workspaceId": task.workspace_id},
            )
        if requested_workspace_id and requested_workspace_id != task.workspace_id:
            return api_error_response(
                "TASK_SCOPE_MISMATCH",
                "Task tenant/workspace mismatch.",
                status_code=409,
                details={"taskId": task_id, "tenantId": task.tenant_id, "workspaceId": task.workspace_id},
            )
        tenant_id = task.tenant_id
        workspace_id = task.workspace_id
        scope_error = ensure_claimed_scope(request, tenant_id=tenant_id, workspace_id=workspace_id)
        if scope_error is not None:
            record_api_audit(request, action="asset.upload", outcome="denied", tenant_id=tenant_id, workspace_id=workspace_id, task_id=task_id or None, resource_type="asset_upload", metadata={"reason": "scope_forbidden"})
            return scope_error
    else:
        tenant_id = requested_tenant_id
        workspace_id = requested_workspace_id
        if not tenant_id or not workspace_id:
            return api_error_response(
                "MISSING_SCOPE",
                "Missing tenant/workspace scope.",
                status_code=400,
                details={"requiredFormFields": ["tenant_id", "workspace_id"]},
            )
        scope_error = ensure_claimed_scope(request, tenant_id=tenant_id, workspace_id=workspace_id)
        if scope_error is not None:
            record_api_audit(request, action="asset.upload", outcome="denied", tenant_id=tenant_id, workspace_id=workspace_id, resource_type="asset_upload", metadata={"reason": "scope_forbidden"})
            return scope_error

    target_dir = Path(UPLOAD_DIR) / tenant_id / workspace_id
    uploaded_items: list[dict[str, Any]] = []
    total_request_size = 0
    for upload in uploads:
        safe_name = safe_upload_name(getattr(upload, "filename", "upload.bin"))
        deduplicated = False
        payload_size = 0
        try:
            asset_kind = infer_asset_kind(getattr(upload, "filename", "upload.bin"), str(form.get("asset_kind") or ""))
        except ValueError as exc:
            return api_error_response(
                "INVALID_ASSET_KIND",
                str(exc),
                status_code=400,
                details={"fileName": safe_name},
            )
        temp_path = _build_temp_upload_path(target_dir, safe_name)
        try:
            payload_sha256, payload_size = await _stream_upload_to_temp(upload, temp_path, max_bytes=UPLOAD_MAX_FILE_BYTES)
            total_request_size += payload_size
            if total_request_size > UPLOAD_MAX_REQUEST_BYTES:
                _cleanup_temp_upload(temp_path)
                return api_error_response(
                    "UPLOAD_REQUEST_TOO_LARGE",
                    "Upload request is too large.",
                    status_code=413,
                    details={"maxRequestBytes": UPLOAD_MAX_REQUEST_BYTES},
                )
            if task_id and execution_data is not None:
                try:
                    existing_path, deduplicated = _find_existing_task_asset(execution_data, asset_kind=asset_kind, file_name=safe_name, file_sha256=payload_sha256)
                except ValueError:
                    _cleanup_temp_upload(temp_path)
                    return api_error_response(
                        "FILE_NAME_CONFLICT",
                        "File name conflict.",
                        status_code=409,
                        details={"taskId": task_id, "fileName": safe_name},
                    )
                if existing_path:
                    target_path = Path(existing_path)
                    if not deduplicated:
                        try:
                            target_path, deduplicated = _resolve_target_path(target_path.parent, target_path.name, payload_sha256)
                        except ValueError:
                            _cleanup_temp_upload(temp_path)
                            return api_error_response(
                                "FILE_NAME_CONFLICT",
                                "File name conflict.",
                                status_code=409,
                                details={"taskId": task_id, "fileName": target_path.name},
                            )
                else:
                    try:
                        target_path, deduplicated = _resolve_target_path(target_dir, safe_name, payload_sha256)
                    except ValueError:
                        _cleanup_temp_upload(temp_path)
                        return api_error_response(
                            "FILE_NAME_CONFLICT",
                            "File name conflict.",
                            status_code=409,
                            details={"taskId": task_id, "fileName": safe_name},
                        )
                if deduplicated:
                    _cleanup_temp_upload(temp_path)
                else:
                    try:
                        target_path, deduplicated = _finalize_staged_upload(temp_path, target_path, payload_sha256)
                    except ValueError:
                        _cleanup_temp_upload(temp_path)
                        return api_error_response(
                            "FILE_NAME_CONFLICT",
                            "File name conflict.",
                            status_code=409,
                            details={"taskId": task_id, "fileName": target_path.name},
                        )
                _append_uploaded_asset(execution_data, file_name=target_path.name, file_path=str(target_path), asset_kind=asset_kind, file_sha256=payload_sha256)
                execution_blackboard.write(tenant_id, task_id, execution_data)
                execution_blackboard.persist(tenant_id, task_id)
                if asset_kind == "business_document":
                    sync_task_knowledge_documents(tenant_id, task_id, execution_data)
            else:
                try:
                    target_path, deduplicated = _resolve_target_path(target_dir, safe_name, payload_sha256)
                except ValueError:
                    _cleanup_temp_upload(temp_path)
                    return api_error_response(
                        "FILE_NAME_CONFLICT",
                        "File name conflict.",
                        status_code=409,
                        details={"fileName": safe_name, "tenantId": tenant_id, "workspaceId": workspace_id},
                    )
                if deduplicated:
                    _cleanup_temp_upload(temp_path)
                else:
                    try:
                        target_path, deduplicated = _finalize_staged_upload(temp_path, target_path, payload_sha256)
                    except ValueError:
                        _cleanup_temp_upload(temp_path)
                        return api_error_response(
                            "FILE_NAME_CONFLICT",
                            "File name conflict.",
                            status_code=409,
                            details={"fileName": safe_name, "tenantId": tenant_id, "workspaceId": workspace_id},
                        )
                if asset_kind == "business_document":
                    sync_workspace_knowledge_document(tenant_id, workspace_id, file_name=target_path.name, file_path=str(target_path), file_sha256=payload_sha256)
        except ValueError as exc:
            _cleanup_temp_upload(temp_path)
            if str(exc) == "upload_too_large":
                return api_error_response(
                    "UPLOAD_FILE_TOO_LARGE",
                    "Uploaded file is too large.",
                    status_code=413,
                    details={"fileName": safe_name, "maxFileBytes": UPLOAD_MAX_FILE_BYTES},
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
        record_api_audit(request, action="asset.upload", outcome="success", tenant_id=tenant_id, workspace_id=workspace_id, task_id=task_id or None, resource_type="asset_upload", resource_id=str(target_path), metadata={"asset_kind": asset_kind, "file_name": target_path.name, "deduplicated": deduplicated, "size": payload_size})

    if len(uploaded_items) == 1:
        return JSONResponse(uploaded_items[0])
    return JSONResponse({"uploaded": True, "tenant_id": tenant_id, "workspace_id": workspace_id, "task_id": task_id or None, "uploaded_files": uploaded_items, "file_count": len(uploaded_items)})
