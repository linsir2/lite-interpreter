"""App-facing routes for the real web frontend."""

from __future__ import annotations

import json

from config.settings import API_AUTH_REQUIRED
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.api.app_presenters import (
    build_analysis_detail,
    build_analysis_events,
    build_analysis_list_item,
    list_workspace_assets_for_app,
    list_workspace_audit_items_for_app,
    list_workspace_methods_for_app,
    parse_asset_public_id,
    resolve_analysis_output_content,
    status_label,
)
from src.api.app_schemas import (
    AnalysisEventsResponse,
    AnalysisListResponse,
    AppAuditQuery,
    AppSessionResponse,
    AssetListResponse,
    AssetUploadItem,
    AssetUploadResponse,
    CreateAnalysisRequest,
    CreateAnalysisResponse,
    MethodListResponse,
    PaginationMeta,
    WorkspaceGrantResponse,
)
from src.api.audit_logging import record_api_audit
from src.api.auth import request_auth_context, require_request_role, role_allows
from src.api.request_scope import ensure_claimed_scope, require_request_scope
from src.api.schemas import AppPaginationQuery, api_error_response, validation_error_details
from src.api.services.asset_service import attach_workspace_assets_to_execution, upload_assets_from_request
from src.api.services.task_flow_service import create_execution_data_for_task, schedule_task_flow
from src.blackboard import GlobalStatus, TaskNotExistError, execution_blackboard, global_blackboard


def _resolve_app_scope(request: Request, *, requested_workspace_id: str | None = None) -> tuple[str, str] | JSONResponse:
    auth_context = request_auth_context(request)
    if auth_context is not None and auth_context.grants:
        workspace_id = str(
            requested_workspace_id
            or request.query_params.get("workspaceId")
            or request.headers.get("x-workspace-id")
            or auth_context.grants[0].workspace_id
        ).strip()
        grant = next((item for item in auth_context.grants if item.workspace_id == workspace_id), None)
        if grant is None:
            return api_error_response(
                "WORKSPACE_FORBIDDEN",
                "The selected workspace is not available in the current session.",
                status_code=403,
            )
        return grant.tenant_id, grant.workspace_id

    scope = require_request_scope(request)
    if isinstance(scope, JSONResponse):
        return scope
    return scope


async def get_app_session(request: Request) -> JSONResponse:
    auth_context = request_auth_context(request)
    if auth_context is None:
        scope = require_request_scope(request)
        if isinstance(scope, JSONResponse):
            if API_AUTH_REQUIRED:
                return api_error_response("AUTH_REQUIRED", "Authentication required.", status_code=401)
            return JSONResponse(
                AppSessionResponse(
                    authenticated=False,
                    grants=[],
                    currentWorkspaceId=None,
                    currentTenantId=None,
                    uiCapabilities={"canViewAudit": False, "canManageMethods": False},
                ).model_dump(mode="json")
            )
        tenant_id, workspace_id = scope
        payload = AppSessionResponse(
            authenticated=False,
            grants=[
                WorkspaceGrantResponse(
                    tenantId=tenant_id,
                    workspaceId=workspace_id,
                    label=f"{workspace_id}",
                )
            ],
            currentWorkspaceId=workspace_id,
            currentTenantId=tenant_id,
            uiCapabilities={"canViewAudit": False, "canManageMethods": False},
        )
        return JSONResponse(payload.model_dump(mode="json"))

    grants = [
        WorkspaceGrantResponse(
            tenantId=grant.tenant_id,
            workspaceId=grant.workspace_id,
            label=grant.workspace_id,
        )
        for grant in auth_context.grants
    ] or [
        WorkspaceGrantResponse(
            tenantId=auth_context.tenant_id,
            workspaceId=auth_context.workspace_id,
            label=auth_context.workspace_id,
        )
    ]
    current_workspace_id = str(request.query_params.get("workspaceId") or grants[0].workspaceId)
    current_grant = next((grant for grant in grants if grant.workspaceId == current_workspace_id), grants[0])
    payload = AppSessionResponse(
        authenticated=True,
        subject=auth_context.subject,
        role=auth_context.role,
        grants=grants,
        currentWorkspaceId=current_grant.workspaceId,
        currentTenantId=current_grant.tenantId,
        uiCapabilities={
            "canViewAudit": role_allows(auth_context.role, "admin"),
            "canManageMethods": role_allows(auth_context.role, "viewer"),
        },
    )
    return JSONResponse(payload.model_dump(mode="json"))


async def list_app_analyses(request: Request) -> JSONResponse:
    role_error = require_request_role(request, "viewer")
    if role_error is not None:
        return role_error
    scope = _resolve_app_scope(request)
    if isinstance(scope, JSONResponse):
        return scope
    tenant_id, workspace_id = scope
    scope_error = ensure_claimed_scope(request, tenant_id=tenant_id, workspace_id=workspace_id)
    if scope_error is not None:
        return scope_error

    try:
        pagination = AppPaginationQuery.model_validate(
            {
                "page": request.query_params.get("page") or "1",
                "pageSize": request.query_params.get("pageSize") or "20",
            }
        )
    except ValidationError as exc:
        return api_error_response(
            "VALIDATION_ERROR",
            "Invalid analyses query.",
            status_code=422,
            details=validation_error_details(exc),
        )
    status_filter = str(request.query_params.get("status") or "").strip()
    tasks = global_blackboard.list_workspace_tasks(tenant_id, workspace_id)
    if status_filter:
        tasks = [task for task in tasks if task.global_status.value == status_filter]
    items = [build_analysis_list_item(task) for task in tasks]
    total_items = len(items)
    start = (pagination.page - 1) * pagination.pageSize
    paginated = items[start : start + pagination.pageSize]
    payload = AnalysisListResponse(
        items=paginated,
        pagination=PaginationMeta.build(page=pagination.page, page_size=pagination.pageSize, total_items=total_items),
        currentWorkspaceId=workspace_id,
    )
    record_api_audit(
        request,
        action="app.analyses.read",
        outcome="success",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        resource_type="app_analyses",
        metadata={"item_count": len(paginated)},
    )
    return JSONResponse(payload.model_dump(mode="json"))


async def create_app_analysis(request: Request) -> JSONResponse:
    role_error = require_request_role(request, "operator")
    if role_error is not None:
        return role_error
    try:
        body = await request.json()
    except ValueError:
        return api_error_response("INVALID_JSON", "Invalid JSON body.", status_code=400)
    try:
        command = CreateAnalysisRequest.model_validate(body)
    except ValidationError as exc:
        return api_error_response(
            "VALIDATION_ERROR",
            "Invalid analysis request.",
            status_code=422,
            details=validation_error_details(exc),
        )

    scope = _resolve_app_scope(request, requested_workspace_id=command.workspaceId)
    if isinstance(scope, JSONResponse):
        return scope
    tenant_id, workspace_id = scope
    scope_error = ensure_claimed_scope(request, tenant_id=tenant_id, workspace_id=workspace_id)
    if scope_error is not None:
        return scope_error

    task_id = global_blackboard.create_task(tenant_id, workspace_id, command.question)
    asset_hashes = [parsed for asset_id in command.assetIds if (parsed := parse_asset_public_id(asset_id))]
    execution_data = create_execution_data_for_task(
        task_id=task_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        query=command.question,
        governance_profile=command.analysisModePreset or "researcher",
        allowed_tools=["web_search", "knowledge_query"],
    )
    if asset_hashes:
        execution_data = attach_workspace_assets_to_execution(execution_data=execution_data, asset_refs=asset_hashes)
    execution_blackboard.write(tenant_id, task_id, execution_data)
    execution_blackboard.persist(tenant_id, task_id)
    schedule_task_flow(
        tenant_id=tenant_id,
        task_id=task_id,
        workspace_id=workspace_id,
        query=command.question,
        allowed_tools=["web_search", "knowledge_query"],
        governance_profile=command.analysisModePreset or "researcher",
    )
    payload = CreateAnalysisResponse(
        analysisId=task_id,
        status=GlobalStatus.PENDING.value,
        statusLabel=status_label(GlobalStatus.PENDING.value),
    )
    record_api_audit(
        request,
        action="app.analysis.create",
        outcome="success",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        task_id=task_id,
        resource_type="app_analysis",
        resource_id=task_id,
        metadata={"asset_count": len(asset_hashes)},
    )
    return JSONResponse(payload.model_dump(mode="json"), status_code=201)


async def get_app_analysis_detail(request: Request) -> JSONResponse:
    role_error = require_request_role(request, "viewer")
    if role_error is not None:
        return role_error
    analysis_id = request.path_params["analysis_id"]
    try:
        task = global_blackboard.get_task_state(analysis_id)
    except TaskNotExistError:
        return api_error_response("NOT_FOUND", "Analysis not found.", status_code=404)
    scope = _resolve_app_scope(request)
    if isinstance(scope, JSONResponse):
        return scope
    tenant_id, workspace_id = scope
    if task.tenant_id != tenant_id or task.workspace_id != workspace_id:
        return api_error_response("NOT_FOUND", "Analysis not found.", status_code=404)
    payload = build_analysis_detail(task)
    return JSONResponse(payload.model_dump(mode="json"))


async def get_app_analysis_events(request: Request) -> JSONResponse:
    role_error = require_request_role(request, "viewer")
    if role_error is not None:
        return role_error
    analysis_id = request.path_params["analysis_id"]
    try:
        task = global_blackboard.get_task_state(analysis_id)
    except TaskNotExistError:
        return api_error_response("NOT_FOUND", "Analysis not found.", status_code=404)
    scope = _resolve_app_scope(request)
    if isinstance(scope, JSONResponse):
        return scope
    tenant_id, workspace_id = scope
    if task.tenant_id != tenant_id or task.workspace_id != workspace_id:
        return api_error_response("NOT_FOUND", "Analysis not found.", status_code=404)
    after_event_id = str(request.query_params.get("afterEventId") or "").strip() or None
    events, last_event_id = build_analysis_events(task, after_event_id=after_event_id)
    payload = AnalysisEventsResponse(analysisId=analysis_id, lastEventId=last_event_id, events=events)
    return JSONResponse(payload.model_dump(mode="json"))


async def get_app_analysis_output(request: Request) -> Response:
    role_error = require_request_role(request, "viewer")
    if role_error is not None:
        return role_error
    analysis_id = request.path_params["analysis_id"]
    output_id = request.path_params["output_id"]
    try:
        task = global_blackboard.get_task_state(analysis_id)
    except TaskNotExistError:
        return api_error_response("NOT_FOUND", "Analysis not found.", status_code=404)
    scope = _resolve_app_scope(request)
    if isinstance(scope, JSONResponse):
        return scope
    tenant_id, workspace_id = scope
    if task.tenant_id != tenant_id or task.workspace_id != workspace_id:
        return api_error_response("NOT_FOUND", "Analysis not found.", status_code=404)
    content = resolve_analysis_output_content(task, output_id)
    if content is None:
        return api_error_response("NOT_FOUND", "Output not found.", status_code=404)
    payload, file_name, media_type = content
    return Response(
        payload,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


async def list_app_assets(request: Request) -> JSONResponse:
    role_error = require_request_role(request, "viewer")
    if role_error is not None:
        return role_error
    scope = _resolve_app_scope(request)
    if isinstance(scope, JSONResponse):
        return scope
    tenant_id, workspace_id = scope
    scope_error = ensure_claimed_scope(request, tenant_id=tenant_id, workspace_id=workspace_id)
    if scope_error is not None:
        return scope_error
    try:
        pagination = AppPaginationQuery.model_validate(
            {
                "page": request.query_params.get("page") or "1",
                "pageSize": request.query_params.get("pageSize") or "20",
            }
        )
    except ValidationError as exc:
        return api_error_response(
            "VALIDATION_ERROR",
            "Invalid assets query.",
            status_code=422,
            details=validation_error_details(exc),
        )
    items = list_workspace_assets_for_app(tenant_id, workspace_id)
    total_items = len(items)
    start = (pagination.page - 1) * pagination.pageSize
    payload = AssetListResponse(
        items=items[start : start + pagination.pageSize],
        pagination=PaginationMeta.build(page=pagination.page, page_size=pagination.pageSize, total_items=total_items),
        currentWorkspaceId=workspace_id,
    )
    return JSONResponse(payload.model_dump(mode="json"))


async def upload_app_assets(request: Request) -> JSONResponse:
    role_error = require_request_role(request, "operator")
    if role_error is not None:
        return role_error
    response = await upload_assets_from_request(request)
    if response.status_code >= 400:
        return response
    payload = json.loads(response.body.decode())
    uploaded_items = list(payload.get("uploaded_files") or [])
    if not uploaded_items:
        uploaded_items = [payload]
    uploaded = [
        AssetUploadItem(
            assetId=f"asset_{str(item.get('file_sha256') or '')}",
            name=str(item.get("file_name") or "uploaded-file"),
            kind=str(item.get("asset_kind") or item.get("kind") or "asset"),
            status="uploaded",
        )
        for item in uploaded_items
    ]
    return JSONResponse(AssetUploadResponse(uploaded=uploaded).model_dump(mode="json"), status_code=response.status_code)


async def list_app_methods(request: Request) -> JSONResponse:
    role_error = require_request_role(request, "viewer")
    if role_error is not None:
        return role_error
    scope = _resolve_app_scope(request)
    if isinstance(scope, JSONResponse):
        return scope
    tenant_id, workspace_id = scope
    scope_error = ensure_claimed_scope(request, tenant_id=tenant_id, workspace_id=workspace_id)
    if scope_error is not None:
        return scope_error
    payload = MethodListResponse(items=list_workspace_methods_for_app(tenant_id, workspace_id), currentWorkspaceId=workspace_id)
    return JSONResponse(payload.model_dump(mode="json"))


async def list_app_audit(request: Request) -> JSONResponse:
    role_error = require_request_role(request, "admin")
    if role_error is not None:
        return role_error
    scope = _resolve_app_scope(request)
    if isinstance(scope, JSONResponse):
        return scope
    tenant_id, workspace_id = scope
    scope_error = ensure_claimed_scope(request, tenant_id=tenant_id, workspace_id=workspace_id)
    if scope_error is not None:
        return scope_error
    try:
        query = AppAuditQuery.model_validate(
            {
                "page": request.query_params.get("page") or "1",
                "pageSize": request.query_params.get("pageSize") or "20",
                "subject": request.query_params.get("subject"),
                "role": request.query_params.get("role"),
                "action": request.query_params.get("action"),
                "outcome": request.query_params.get("outcome"),
                "taskId": request.query_params.get("taskId"),
                "executionId": request.query_params.get("executionId"),
            }
        )
    except ValidationError as exc:
        return api_error_response(
            "VALIDATION_ERROR",
            "Invalid audit query.",
            status_code=422,
            details=validation_error_details(exc),
        )

    page_items, total_items = list_workspace_audit_items_for_app(
        tenant_id,
        workspace_id,
        subject=query.subject,
        role=query.role,
        action=query.action,
        outcome=query.outcome,
        task_id=query.taskId,
        execution_id=query.executionId,
        page=query.page,
        page_size=query.pageSize,
    )
    payload = {
        "items": [
            {
                "auditId": str(item.get("audit_id") or ""),
                "action": str(item.get("action") or ""),
                "outcome": str(item.get("outcome") or ""),
                "subject": str(item.get("subject") or ""),
                "role": str(item.get("role") or ""),
                "resourceType": str(item.get("resource_type") or ""),
                "recordedAt": str(item.get("recorded_at") or ""),
                "taskId": str(item.get("task_id") or "") or None,
                "executionId": str(item.get("execution_id") or "") or None,
            }
            for item in page_items
        ],
        "pagination": PaginationMeta.build(page=query.page, page_size=query.pageSize, total_items=total_items).model_dump(mode="json"),
        "currentWorkspaceId": workspace_id,
    }
    return JSONResponse(payload)
