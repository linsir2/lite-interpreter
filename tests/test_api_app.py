"""Tests for app-facing web frontend API endpoints."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from config.settings import OUTPUT_DIR, UPLOAD_DIR
from src.api.auth import AuthContext, AuthGrant
from src.api.routers.app_router import (
    create_app_analysis,
    get_app_analysis_detail,
    get_app_analysis_events,
    get_app_analysis_output,
    get_app_session,
    list_app_analyses,
    list_app_assets,
    list_app_audit,
    list_app_methods,
    upload_app_assets,
)
from src.blackboard import ExecutionData, GlobalStatus, execution_blackboard, global_blackboard
from src.common import EventTopic, event_bus
from src.common.contracts import AuditRecord
from src.storage.repository.audit_repo import AuditRepo
from starlette.requests import Request


def _make_request(
    *,
    method: str,
    path: str,
    body: dict | None = None,
    path_params: dict[str, str] | None = None,
    query_params: dict[str, str] | None = None,
    headers: list[tuple[bytes, bytes]] | None = None,
    auth_context: AuthContext | None = None,
) -> Request:
    payload = json.dumps(body or {}).encode()
    query_string = "&".join(f"{key}={value}" for key, value in (query_params or {}).items()).encode()

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": query_string,
        "path_params": path_params or {},
        "headers": headers or [],
    }
    if auth_context is not None:
        scope["state"] = {"auth_context": auth_context, "auth_checked": True}
    return Request(scope, receive=receive)


def _viewer_auth(*, tenant_id: str = "tenant-app", workspace_id: str = "ws-app", role: str = "viewer") -> AuthContext:
    return AuthContext(
        token="secret",
        subject="tester",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        role=role,
        grants=(AuthGrant(tenant_id, workspace_id),),
        auth_type="session",
    )


def _assert_structured_error(body: dict, *, code: str) -> None:
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str)
    assert body["error"]["message"]


def test_get_app_session_returns_current_workspace_and_capabilities():
    request = _make_request(
        method="GET",
        path="/api/app/session",
        auth_context=AuthContext(
            token="secret",
            subject="alice",
            tenant_id="tenant-a",
            workspace_id="ws-a",
            role="admin",
            grants=(AuthGrant("tenant-a", "ws-a"), AuthGrant("tenant-a", "ws-b")),
            auth_type="session",
        ),
        query_params={"workspaceId": "ws-b"},
    )
    response = asyncio.run(get_app_session(request))
    body = json.loads(response.body.decode())

    assert response.status_code == 200
    assert body["currentWorkspaceId"] == "ws-b"
    assert body["uiCapabilities"]["canViewAudit"] is True
    assert len(body["grants"]) == 2


def test_list_app_analyses_returns_paginated_items():
    tenant_id = "tenant-app-analyses"
    workspace_id = "ws-app-analyses"
    task_id = global_blackboard.create_task(tenant_id, workspace_id, "分析利润下滑")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            control={"final_response": {"headline": "利润下滑原因", "answer": "费用上升", "outputs": []}},
        ),
    )
    global_blackboard.update_global_status(task_id, GlobalStatus.SUCCESS)

    request = _make_request(
        method="GET",
        path="/api/app/analyses",
        query_params={"workspaceId": workspace_id},
        auth_context=_viewer_auth(tenant_id=tenant_id, workspace_id=workspace_id),
    )
    response = asyncio.run(list_app_analyses(request))
    body = json.loads(response.body.decode())

    assert response.status_code == 200
    assert body["items"][0]["analysisId"] == task_id
    assert body["items"][0]["title"] == "利润下滑原因"
    assert body["pagination"]["totalItems"] >= 1


def test_list_app_analyses_rejects_invalid_pagination_query():
    request = _make_request(
        method="GET",
        path="/api/app/analyses",
        query_params={"workspaceId": "ws-app", "page": "oops"},
        auth_context=_viewer_auth(),
    )
    response = asyncio.run(list_app_analyses(request))
    body = json.loads(response.body.decode())

    assert response.status_code == 422
    _assert_structured_error(body, code="VALIDATION_ERROR")


def test_list_app_analyses_hides_raw_failure_trace_text():
    tenant_id = "tenant-app-failed"
    workspace_id = "ws-app-failed"
    task_id = global_blackboard.create_task(tenant_id, workspace_id, "分析失败任务")
    global_blackboard.update_global_status(
        task_id,
        GlobalStatus.FAILED,
        sub_status="任务执行失败: 1 validation error for MemoryData",
        error_message="任务执行失败: 1 validation error for MemoryData",
    )

    request = _make_request(
        method="GET",
        path="/api/app/analyses",
        query_params={"workspaceId": workspace_id},
        auth_context=_viewer_auth(tenant_id=tenant_id, workspace_id=workspace_id),
    )
    response = asyncio.run(list_app_analyses(request))
    body = json.loads(response.body.decode())

    failed_item = next(item for item in body["items"] if item["analysisId"] == task_id)
    assert response.status_code == 200
    assert "validation error" not in failed_item["summary"]
    assert failed_item["summary"] == "分析执行失败，请打开详情查看可复核的原因与下一步建议。"


def test_list_app_analyses_hides_internal_success_jargon():
    tenant_id = "tenant-app-success-jargon"
    workspace_id = "ws-app-success-jargon"
    task_id = global_blackboard.create_task(tenant_id, workspace_id, "请分析利润下降原因")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            control={
                "final_response": {
                    "headline": "已完成静态链分析。 图谱编译候选/接受/拒绝: 0/0/0；已加载可复用技能 policy_clause_audit。",
                    "answer": "已完成静态链分析。 图谱编译候选/接受/拒绝: 0/0/0；技能策略 summary_stats_check: 优先复用已有知识检索证据；任务输出状态为 成功。",
                    "outputs": [],
                }
            },
        ),
    )
    global_blackboard.update_global_status(task_id, GlobalStatus.SUCCESS)

    request = _make_request(
        method="GET",
        path="/api/app/analyses",
        query_params={"workspaceId": workspace_id},
        auth_context=_viewer_auth(tenant_id=tenant_id, workspace_id=workspace_id),
    )
    response = asyncio.run(list_app_analyses(request))
    body = json.loads(response.body.decode())

    item = next(entry for entry in body["items"] if entry["analysisId"] == task_id)
    assert response.status_code == 200
    assert item["title"] == "分析已完成"
    assert item["summary"] == "分析已完成，请打开详情查看结论、证据和结果产物。"


def test_create_and_get_app_analysis_detail(monkeypatch):
    tenant_id = "tenant-app-create"
    workspace_id = "ws-app-create"
    monkeypatch.setattr(
        "src.api.routers.app_router.schedule_task_flow",
        lambda **_kwargs: {"scheduled": False, "reason": "test_disabled"},
    )
    request = _make_request(
        method="POST",
        path="/api/app/analyses",
        body={"question": "请分析利润下降原因", "assetIds": [], "workspaceId": workspace_id},
        auth_context=_viewer_auth(tenant_id=tenant_id, workspace_id=workspace_id, role="operator"),
    )
    response = asyncio.run(create_app_analysis(request))
    body = json.loads(response.body.decode())
    assert response.status_code == 201

    analysis_id = body["analysisId"]
    execution_blackboard.write(
        tenant_id,
        analysis_id,
        ExecutionData(
            task_id=analysis_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            control={
                "final_response": {
                    "headline": "利润下降原因",
                    "answer": "折扣扩大且费用分摊增加",
                    "key_findings": ["华东地区折扣率上升"],
                    "caveats": ["费用口径待复核"],
                    "outputs": [{"name": "profit-report.csv", "type": "dataset", "summary": "利润拆解", "path": ""}],
                }
            },
            knowledge={"analysis_brief": {"question": "请分析利润下降原因", "recommended_next_step": "复核销售折扣政策"}},
        ),
    )
    global_blackboard.update_global_status(analysis_id, GlobalStatus.SUCCESS)

    detail_request = _make_request(
        method="GET",
        path=f"/api/app/analyses/{analysis_id}",
        path_params={"analysis_id": analysis_id},
        query_params={"workspaceId": workspace_id},
        auth_context=_viewer_auth(tenant_id=tenant_id, workspace_id=workspace_id),
    )
    detail_response = asyncio.run(get_app_analysis_detail(detail_request))
    detail_body = json.loads(detail_response.body.decode())

    assert detail_response.status_code == 200
    assert detail_body["summary"] == "折扣扩大且费用分摊增加"
    assert detail_body["keyFindings"] == ["华东地区折扣率上升"]
    assert detail_body["nextAction"] == "复核销售折扣政策"
    assert detail_body["progress"]["currentStep"] == "结果已生成"
    assert "生成结果" in detail_body["progress"]["activitySummary"]


def test_get_app_analysis_output_uses_app_facing_download_route(tmp_path):
    tenant_id = "tenant-app-output"
    workspace_id = "ws-app-output"
    task_id = global_blackboard.create_task(tenant_id, workspace_id, "导出分析结果")
    output_dir = Path(OUTPUT_DIR) / tenant_id / workspace_id
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "profit-report.csv"
    report_path.write_text("month,profit\n2026-01,10\n", encoding="utf-8")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            control={
                "final_response": {
                    "headline": "分析已完成",
                    "answer": "结果已导出",
                    "outputs": [{"name": "profit-report.csv", "type": "dataset", "summary": "利润拆解", "path": str(report_path)}],
                }
            },
            static={
                "execution_record": {
                    "session_id": "session-output",
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "task_id": task_id,
                    "success": True,
                    "trace_id": "trace-output",
                    "duration_seconds": 0.2,
                    "artifacts": [{"path": str(report_path), "artifact_type": "artifact"}],
                }
            },
        ),
    )
    global_blackboard.update_global_status(task_id, GlobalStatus.SUCCESS)

    detail_request = _make_request(
        method="GET",
        path=f"/api/app/analyses/{task_id}",
        path_params={"analysis_id": task_id},
        query_params={"workspaceId": workspace_id},
        auth_context=_viewer_auth(tenant_id=tenant_id, workspace_id=workspace_id),
    )
    detail_response = asyncio.run(get_app_analysis_detail(detail_request))
    detail_body = json.loads(detail_response.body.decode())
    download_url = detail_body["outputs"][0]["downloadUrl"]

    output_request = _make_request(
        method="GET",
        path=f"/api/app/analyses/{task_id}/outputs/output_{task_id}_1",
        path_params={"analysis_id": task_id, "output_id": f"output_{task_id}_1"},
        query_params={"workspaceId": workspace_id},
        auth_context=_viewer_auth(tenant_id=tenant_id, workspace_id=workspace_id),
    )
    output_response = asyncio.run(get_app_analysis_output(output_request))

    assert detail_response.status_code == 200
    assert download_url == f"/api/app/analyses/{task_id}/outputs/output_{task_id}_1?workspaceId={workspace_id}"
    assert output_response.status_code == 200
    assert output_response.body == b"month,profit\n2026-01,10\n"


def test_get_app_analysis_output_rejects_sibling_prefix_escape(tmp_path):
    tenant_id = "tenant-app-output-escape"
    workspace_id = "ws-app-output-escape"
    task_id = global_blackboard.create_task(tenant_id, workspace_id, "导出分析结果")
    rogue_dir = Path(f"{OUTPUT_DIR}_evil") / tenant_id / workspace_id
    rogue_dir.mkdir(parents=True, exist_ok=True)
    rogue_path = rogue_dir / "secret.txt"
    rogue_path.write_text("secret-data", encoding="utf-8")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            control={
                "final_response": {
                    "headline": "分析已完成",
                    "answer": "结果已导出",
                    "outputs": [{"name": "secret.txt", "type": "dataset", "summary": "逃逸路径", "path": str(rogue_path)}],
                }
            },
            static={
                "execution_record": {
                    "session_id": "session-output-escape",
                    "tenant_id": tenant_id,
                    "workspace_id": workspace_id,
                    "task_id": task_id,
                    "success": True,
                    "trace_id": "trace-output-escape",
                    "duration_seconds": 0.2,
                    "artifacts": [{"path": str(rogue_path), "artifact_type": "artifact"}],
                }
            },
        ),
    )
    global_blackboard.update_global_status(task_id, GlobalStatus.SUCCESS)

    output_request = _make_request(
        method="GET",
        path=f"/api/app/analyses/{task_id}/outputs/output_{task_id}_1",
        path_params={"analysis_id": task_id, "output_id": f"output_{task_id}_1"},
        query_params={"workspaceId": workspace_id},
        auth_context=_viewer_auth(tenant_id=tenant_id, workspace_id=workspace_id),
    )
    output_response = asyncio.run(get_app_analysis_output(output_request))
    body = json.loads(output_response.body.decode())

    assert output_response.status_code == 404
    _assert_structured_error(body, code="NOT_FOUND")


def test_get_app_analysis_events_normalizes_task_events():
    tenant_id = "tenant-app-events"
    workspace_id = "ws-app-events"
    task_id = global_blackboard.create_task(tenant_id, workspace_id, "分析异常")
    event_bus.publish(
        topic=EventTopic.UI_TASK_STATUS_UPDATE,
        tenant_id=tenant_id,
        task_id=task_id,
        workspace_id=workspace_id,
        payload={"new_status": "analyzing", "message": "正在整理指标"},
        trace_id=task_id,
    )

    request = _make_request(
        method="GET",
        path=f"/api/app/analyses/{task_id}/events",
        path_params={"analysis_id": task_id},
        query_params={"workspaceId": workspace_id},
        auth_context=_viewer_auth(tenant_id=tenant_id, workspace_id=workspace_id),
    )
    response = asyncio.run(get_app_analysis_events(request))
    body = json.loads(response.body.decode())

    assert response.status_code == 200
    assert body["events"][-1]["kind"] == "status"
    assert body["events"][-1]["title"] == "正在分析问题"


def test_get_app_analysis_events_hides_trace_jargon():
    tenant_id = "tenant-app-trace-jargon"
    workspace_id = "ws-app-trace-jargon"
    task_id = global_blackboard.create_task(tenant_id, workspace_id, "分析过程")
    event_bus.publish(
        topic=EventTopic.UI_TASK_TRACE_UPDATE,
        tenant_id=tenant_id,
        task_id=task_id,
        workspace_id=workspace_id,
        payload={
            "event": {
                "step_name": "static_codegen",
                "message": "已完成静态链分析。 图谱编译候选/接受/拒绝: 0/0/0；技能策略 summary_stats_check。",
            }
        },
        trace_id=task_id,
    )

    request = _make_request(
        method="GET",
        path=f"/api/app/analyses/{task_id}/events",
        path_params={"analysis_id": task_id},
        query_params={"workspaceId": workspace_id},
        auth_context=_viewer_auth(tenant_id=tenant_id, workspace_id=workspace_id),
    )
    response = asyncio.run(get_app_analysis_events(request))
    body = json.loads(response.body.decode())

    trace_event = next(item for item in body["events"] if item["kind"] == "trace")
    assert response.status_code == 200
    assert trace_event["title"] == "系统处理进度"
    assert trace_event["message"] == "系统已完成一项内部处理步骤。"


def test_get_app_analysis_detail_hides_internal_in_progress_title_and_empty_summary():
    tenant_id = "tenant-app-inprogress"
    workspace_id = "ws-app-inprogress"
    task_id = global_blackboard.create_task(tenant_id, workspace_id, "请分析利润下降原因")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            control={"final_response": {"headline": "正在生成静态执行计划", "answer": "No answer available"}},
        ),
    )
    global_blackboard.update_global_status(task_id, GlobalStatus.ANALYZING, sub_status="正在生成静态执行计划")

    request = _make_request(
        method="GET",
        path=f"/api/app/analyses/{task_id}",
        path_params={"analysis_id": task_id},
        query_params={"workspaceId": workspace_id},
        auth_context=_viewer_auth(tenant_id=tenant_id, workspace_id=workspace_id),
    )
    response = asyncio.run(get_app_analysis_detail(request))
    body = json.loads(response.body.decode())

    assert response.status_code == 200
    assert body["title"] == "请分析利润下降原因"
    assert body["summary"] == "系统正在整理关键指标、业务口径和分析要点。"


def test_list_app_assets_returns_business_facing_items(tmp_path):
    tenant_id = "tenant-app-assets"
    workspace_id = "ws-app-assets"
    upload_dir = Path(UPLOAD_DIR) / tenant_id / workspace_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / "profit.csv").write_text("month,profit\n2026-01,10\n", encoding="utf-8")

    request = _make_request(
        method="GET",
        path="/api/app/assets",
        query_params={"workspaceId": workspace_id},
        auth_context=_viewer_auth(tenant_id=tenant_id, workspace_id=workspace_id),
    )
    response = asyncio.run(list_app_assets(request))
    body = json.loads(response.body.decode())

    assert response.status_code == 200
    assert body["items"][0]["assetId"].startswith("asset_")
    assert body["items"][0]["readinessLabel"] in {"可直接分析", "待处理"}


def test_list_app_assets_rejects_invalid_pagination_query():
    request = _make_request(
        method="GET",
        path="/api/app/assets",
        query_params={"workspaceId": "ws-app", "pageSize": "oops"},
        auth_context=_viewer_auth(),
    )
    response = asyncio.run(list_app_assets(request))
    body = json.loads(response.body.decode())

    assert response.status_code == 422
    _assert_structured_error(body, code="VALIDATION_ERROR")


def test_list_app_assets_returns_structured_workspace_forbidden_error():
    request = _make_request(
        method="GET",
        path="/api/app/assets",
        query_params={"workspaceId": "ws-other"},
        auth_context=_viewer_auth(tenant_id="tenant-app", workspace_id="ws-app"),
    )
    response = asyncio.run(list_app_assets(request))
    body = json.loads(response.body.decode())

    assert response.status_code == 403
    _assert_structured_error(body, code="WORKSPACE_FORBIDDEN")


def test_upload_app_assets_returns_structured_errors_for_missing_file(monkeypatch):
    request = _make_request(
        method="POST",
        path="/api/app/assets",
        auth_context=_viewer_auth(role="operator"),
    )

    async def _empty_form():
        return {}

    monkeypatch.setattr(request, "form", _empty_form)
    response = asyncio.run(upload_app_assets(request))
    body = json.loads(response.body.decode())

    assert response.status_code == 400
    _assert_structured_error(body, code="MISSING_FILE_FIELD")


def test_list_app_methods_and_audit():
    tenant_id = "tenant-app-admin"
    workspace_id = "ws-app-admin"
    AuditRepo.append_record(
        AuditRecord(
            audit_id="audit-app-1",
            subject="alice",
            role="admin",
            action="app.analysis.create",
            outcome="success",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            request_method="POST",
            request_path="/api/app/analyses",
            resource_type="task",
        )
    )

    methods_request = _make_request(
        method="GET",
        path="/api/app/methods",
        query_params={"workspaceId": workspace_id},
        auth_context=_viewer_auth(tenant_id=tenant_id, workspace_id=workspace_id),
    )
    methods_response = asyncio.run(list_app_methods(methods_request))
    methods_body = json.loads(methods_response.body.decode())
    assert methods_response.status_code == 200
    assert "items" in methods_body

    audit_request = _make_request(
        method="GET",
        path="/api/app/audit",
        query_params={"workspaceId": workspace_id},
        auth_context=_viewer_auth(tenant_id=tenant_id, workspace_id=workspace_id, role="admin"),
    )
    audit_response = asyncio.run(list_app_audit(audit_request))
    audit_body = json.loads(audit_response.body.decode())
    assert audit_response.status_code == 200
    assert audit_body["items"][0]["auditId"] == "audit-app-1"


def test_list_app_audit_supports_real_pagination_beyond_500_records():
    tenant_id = "tenant-app-audit-pagination"
    workspace_id = "ws-app-audit-pagination"
    for index in range(520):
        AuditRepo.append_record(
            AuditRecord(
                audit_id=f"audit-app-{index}",
                subject="alice",
                role="admin",
                action="app.analysis.create",
                outcome="success",
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                request_method="POST",
                request_path="/api/app/analyses",
                resource_type="task",
            )
        )

    request = _make_request(
        method="GET",
        path="/api/app/audit",
        query_params={"workspaceId": workspace_id, "page": "26", "pageSize": "20"},
        auth_context=_viewer_auth(tenant_id=tenant_id, workspace_id=workspace_id, role="admin"),
    )
    response = asyncio.run(list_app_audit(request))
    body = json.loads(response.body.decode())

    assert response.status_code == 200
    assert body["pagination"]["totalItems"] == 520
    assert body["pagination"]["totalPages"] == 26
    assert len(body["items"]) == 20
    assert body["items"][0]["auditId"] == "audit-app-19"


def test_list_app_audit_rejects_invalid_pagination_query():
    request = _make_request(
        method="GET",
        path="/api/app/audit",
        query_params={"workspaceId": "ws-app", "page": "oops"},
        auth_context=_viewer_auth(role="admin"),
    )
    response = asyncio.run(list_app_audit(request))
    body = json.loads(response.body.decode())

    assert response.status_code == 422
    _assert_structured_error(body, code="VALIDATION_ERROR")
