"""Presenter helpers for app-facing web frontend contracts."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from config.settings import OUTPUT_DIR, UPLOAD_DIR

from src.api.app_schemas import (
    AnalysisDetailResponse,
    AnalysisEventItem,
    AnalysisEvidenceItem,
    AnalysisListItem,
    AnalysisOutputItem,
    AnalysisProgressSummary,
    AssetListItem,
    MethodCard,
)
from src.api.execution_resources import (
    build_task_workspace_payload,
    read_artifact_content,
    read_task_execution_data,
)
from src.blackboard import execution_blackboard, knowledge_blackboard, memory_blackboard
from src.blackboard.schema import GlobalStatus, TaskGlobalState
from src.common.control_plane import artifact_category_from_path, parser_reports_from_documents, sort_output_entries
from src.common.event_bus import EventTopic
from src.common.event_journal import event_journal
from src.skillnet.preset_skills import load_preset_skills
from src.storage.repository.audit_repo import AuditRepo
from src.storage.repository.memory_repo import MemoryRepo
from src.storage.repository.state_repo import StateRepo

_STATUS_LABELS = {
    GlobalStatus.PENDING.value: "等待开始",
    GlobalStatus.ROUTING.value: "正在判断分析路径",
    GlobalStatus.PREPARING_CONTEXT.value: "正在准备数据上下文",
    GlobalStatus.RETRIEVING.value: "正在检索相关资料",
    GlobalStatus.ANALYZING.value: "正在分析问题",
    GlobalStatus.CODING.value: "正在生成分析代码",
    GlobalStatus.AUDITING.value: "正在校验执行方案",
    GlobalStatus.EXECUTING.value: "正在运行分析",
    GlobalStatus.DEBUGGING.value: "正在修复问题",
    GlobalStatus.EVALUATING.value: "正在评估结果",
    GlobalStatus.SUMMARIZING.value: "正在整理结论",
    GlobalStatus.HARVESTING.value: "正在沉淀分析方法",
    GlobalStatus.WAITING_FOR_HUMAN.value: "等待人工处理",
    GlobalStatus.SUCCESS.value: "已完成",
    GlobalStatus.FAILED.value: "执行失败",
    GlobalStatus.ARCHIVED.value: "已归档",
}

_TECHNICAL_COPY_MARKERS = (
    "图谱编译",
    "静态链",
    "静态执行计划",
    "动态链",
    "knowledge_query",
    "sandbox_exec",
    "task_envelope",
    "runtime",
    "trace",
    "skill",
    "技能策略",
    "policy_clause_audit",
    "summary_stats_check",
    "execution",
    "候选/接受/拒绝",
)


def status_label(status: str) -> str:
    normalized = str(status or "").strip()
    return _STATUS_LABELS.get(normalized, normalized or "未知状态")


def _business_progress_copy(task: TaskGlobalState, primary_mode: str) -> tuple[str, str]:
    status = task.global_status.value
    if status == GlobalStatus.SUCCESS.value:
        return "结果已生成", "系统已完成本次分析并生成结果，可继续查看证据与产物。"
    if status == GlobalStatus.FAILED.value:
        return "分析已中断", "系统未能顺利完成本次分析，请查看详情中的原因与建议动作。"
    if status == GlobalStatus.WAITING_FOR_HUMAN.value:
        return "等待人工处理", "当前任务需要人工确认或补充信息后才能继续。"
    if status == GlobalStatus.ROUTING.value:
        return "判断分析路径", "系统正在判断问题类型、资料情况和后续分析路径。"
    if status == GlobalStatus.RETRIEVING.value:
        return "检索相关资料", "系统正在提取和筛选与当前问题相关的资料。"
    if status == GlobalStatus.ANALYZING.value:
        return "整理分析上下文", "系统正在整理关键指标、业务口径和分析要点。"
    if status in {GlobalStatus.CODING.value, GlobalStatus.AUDITING.value, GlobalStatus.EXECUTING.value}:
        return "执行分析", "系统正在运行并校验分析过程，确保结果可复核。"
    if status in {GlobalStatus.SUMMARIZING.value, GlobalStatus.EVALUATING.value, GlobalStatus.HARVESTING.value}:
        return "整理结果", "系统正在汇总分析结果并生成可阅读输出。"
    if status == GlobalStatus.PENDING.value:
        return "等待开始", "分析任务已经创建，系统即将开始处理。"
    if primary_mode and primary_mode not in {status, "unknown"}:
        return "处理进行中", "系统正在推进本次分析，请稍后查看最新结果。"
    return status_label(status), "分析正在处理中。"


def _looks_like_internal_copy(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    if normalized.startswith("正在") and any(
        marker in normalized for marker in ("静态执行计划", "分析路径", "处理步骤", "执行计划")
    ):
        return True
    lowered = normalized.lower()
    marker_hits = sum(1 for marker in _TECHNICAL_COPY_MARKERS if marker.lower() in lowered)
    separator_hits = normalized.count("；") + normalized.count(";")
    return marker_hits >= 2 or (marker_hits >= 1 and separator_hits >= 2) or len(normalized) > 160


def _business_safe_summary(task: TaskGlobalState, response: dict[str, Any] | None) -> str:
    payload = dict(response or {})
    answer = str(payload.get("answer") or "").strip()
    headline = str(payload.get("headline") or "").strip()
    _, progress_summary = _business_progress_copy(task, headline)
    if task.global_status == GlobalStatus.SUCCESS:
        if answer and not _looks_like_internal_copy(answer):
            return answer
        if headline and not _looks_like_internal_copy(headline):
            return headline
        return "分析已完成，请打开详情查看结论、证据和结果产物。"
    if answer and answer != "No answer available" and not _looks_like_internal_copy(answer):
        return answer
    if headline and headline != "No headline available" and not _looks_like_internal_copy(headline):
        return headline
    if task.global_status == GlobalStatus.FAILED:
        return "分析执行失败，请打开详情查看可复核的原因与下一步建议。"
    if task.global_status == GlobalStatus.WAITING_FOR_HUMAN:
        return "当前任务需要人工介入后才能继续。"
    if task.sub_status and not _looks_like_internal_copy(str(task.sub_status)):
        return str(task.sub_status)
    return progress_summary


def _business_safe_title(task: TaskGlobalState, response: dict[str, Any] | None) -> str:
    payload = dict(response or {})
    headline = str(payload.get("headline") or "").strip()
    if headline and not _looks_like_internal_copy(headline) and headline != "No headline available":
        return headline
    if task.global_status == GlobalStatus.SUCCESS:
        return "分析已完成"
    query = str(task.input_query or "").strip()
    if not query:
        return "未命名分析"
    return query[:48]


def _opaque_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(f"{prefix}:{value}".encode()).hexdigest()[:12]
    return f"{prefix}_{digest}"


def asset_public_id(asset: dict[str, Any]) -> str:
    file_sha256 = str(asset.get("file_sha256") or "").strip()
    if file_sha256:
        return f"asset_{file_sha256}"
    path = str(asset.get("path") or "").strip()
    file_name = str(asset.get("file_name") or asset.get("name") or "").strip()
    kind = str(asset.get("kind") or "asset").strip()
    return _opaque_id("asset", f"{kind}:{file_name}:{path}")


def parse_asset_public_id(asset_id: str) -> str | None:
    normalized = str(asset_id or "").strip()
    if not normalized.startswith("asset_"):
        return None
    return normalized.removeprefix("asset_")


def build_analysis_list_item(task: TaskGlobalState) -> AnalysisListItem:
    execution_data = read_task_execution_data(task.tenant_id, task.task_id)
    final_response = execution_data.control.final_response if execution_data else {}
    outputs = list((final_response or {}).get("outputs") or [])
    warnings = list((final_response or {}).get("caveats") or [])
    return AnalysisListItem(
        analysisId=task.task_id,
        title=_business_safe_title(task, final_response),
        question=task.input_query,
        status=task.global_status.value,
        statusLabel=status_label(task.global_status.value),
        createdAt=task.created_at.isoformat(),
        updatedAt=task.updated_at.isoformat(),
        summary=_business_safe_summary(task, final_response),
        hasOutputs=bool(outputs),
        hasWarnings=bool(warnings or task.error_message),
    )


def build_analysis_detail(task: TaskGlobalState) -> AnalysisDetailResponse:
    execution_data = read_task_execution_data(task.tenant_id, task.task_id)
    memory_data = memory_blackboard.read(task.tenant_id, task.task_id)
    if memory_data is None and memory_blackboard.restore(task.tenant_id, task.task_id):
        memory_data = memory_blackboard.read(task.tenant_id, task.task_id)
    task_lease = StateRepo.get_task_lease(task.task_id)
    payload = build_task_workspace_payload(
        task=task,
        execution_data=execution_data,
        memory_data=memory_data,
        task_lease=task_lease,
    )
    workspace = dict(payload.get("workspace") or {})
    primary = dict(workspace.get("primary") or {})
    response = dict(payload.get("response") or {})
    evidence_refs = list((workspace.get("evidence") or {}).get("evidence_refs") or [])
    outputs = list(response.get("outputs") or [])
    executions = list(payload.get("executions") or [])
    current_step, activity_summary = _business_progress_copy(task, str(primary.get("mode") or ""))
    output_items = build_analysis_outputs(task, execution_data, outputs)

    return AnalysisDetailResponse(
        analysisId=task.task_id,
        title=_business_safe_title(task, primary if primary else response),
        question=task.input_query,
        status=task.global_status.value,
        statusLabel=status_label(task.global_status.value),
        createdAt=task.created_at.isoformat(),
        updatedAt=task.updated_at.isoformat(),
        summary=_business_safe_summary(task, primary if primary else response),
        keyFindings=[str(item) for item in list(response.get("key_findings") or [])],
        evidence=[AnalysisEvidenceItem(id=f"evidence_{index}", label=str(ref)) for index, ref in enumerate(evidence_refs, start=1)],
        outputs=output_items,
        warnings=[str(item) for item in list(response.get("caveats") or [])],
        nextAction=str(primary.get("next_action") or ""),
        progress=AnalysisProgressSummary(
            currentStatus=task.global_status.value,
            statusLabel=status_label(task.global_status.value),
            currentStep=current_step,
            activitySummary=activity_summary,
            executionCount=len(executions),
            updatedAt=task.updated_at.isoformat(),
        ),
        isDebugAvailable=bool(executions),
    )


def build_analysis_outputs(
    task: TaskGlobalState,
    execution_data: Any,
    outputs: list[dict[str, Any]],
) -> list[AnalysisOutputItem]:
    output_items: list[AnalysisOutputItem] = []
    for index, output in enumerate(sort_output_entries(outputs), start=1):
        item = dict(output or {})
        path = str(item.get("path") or "").strip()
        preview_kind = "none"
        resolved_path = _resolve_output_file_path(path)
        suffix = resolved_path.suffix.lower() if resolved_path else Path(path).suffix.lower() if path else ""
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
            preview_kind = "image"
        elif suffix in {".txt", ".md", ".csv", ".json", ".log"}:
            preview_kind = "text"
        download_url = (
            f"/api/app/analyses/{task.task_id}/outputs/output_{task.task_id}_{index}"
            f"?workspaceId={task.workspace_id}"
        ) if resolved_path is not None else None
        output_items.append(
            AnalysisOutputItem(
                id=f"output_{task.task_id}_{index}",
                title=str(item.get("name") or f"输出 {index}"),
                type=str(item.get("type") or artifact_category_from_path(path, str(item.get("category") or "")) or "artifact"),
                summary=str(item.get("summary") or ""),
                downloadUrl=download_url,
                previewKind=preview_kind,
            )
        )
    return output_items


def resolve_analysis_output_content(task: TaskGlobalState, output_id: str) -> tuple[bytes, str, str] | None:
    execution_data = read_task_execution_data(task.tenant_id, task.task_id)
    if execution_data is None:
        return None
    memory_data = memory_blackboard.read(task.tenant_id, task.task_id)
    if memory_data is None and memory_blackboard.restore(task.tenant_id, task.task_id):
        memory_data = memory_blackboard.read(task.tenant_id, task.task_id)
    task_lease = StateRepo.get_task_lease(task.task_id)
    payload = build_task_workspace_payload(
        task=task,
        execution_data=execution_data,
        memory_data=memory_data,
        task_lease=task_lease,
    )
    response = dict(payload.get("response") or {})
    outputs = sort_output_entries(response.get("outputs") or [])
    target = next((item for item in build_analysis_outputs(task, execution_data, outputs) if item.id == output_id), None)
    if target is None:
        return None
    try:
        index = int(output_id.rsplit("_", 1)[-1]) - 1
    except ValueError:
        return None
    if index < 0 or index >= len(outputs):
        return None
    raw_output = dict(outputs[index] or {})
    path_value = str(raw_output.get("path") or "").strip()
    if not path_value:
        return None
    safe_root_candidates = [
        (Path(UPLOAD_DIR).resolve() / task.tenant_id / task.workspace_id).resolve(),
        (Path(OUTPUT_DIR).resolve() / task.tenant_id / task.workspace_id).resolve(),
    ]
    path = Path(path_value).resolve()
    if not any(_path_within_root(path, root) for root in safe_root_candidates):
        return None
    if path.is_dir():
        candidate = _resolve_output_file_path(str(path))
        if candidate is None:
            return None
        path = candidate
    return read_artifact_content({"path": str(path)})


def _path_within_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_output_file_path(path_value: str) -> Path | None:
    path = Path(str(path_value or "").strip())
    if not str(path).strip():
        return None
    resolved = path.resolve()
    if resolved.is_file():
        return resolved
    if resolved.is_dir():
        candidate = next((item for item in sorted(resolved.rglob("*")) if item.is_file()), None)
        if candidate is not None:
            return candidate.resolve()
    return None


def build_analysis_events(task: TaskGlobalState, *, after_event_id: str | None = None) -> tuple[list[AnalysisEventItem], str | None]:
    records = event_journal.read(task.tenant_id, task.task_id, workspace_id=task.workspace_id)
    if after_event_id:
        filtered: list[dict[str, Any]] = []
        seen = False
        for record in records:
            if seen:
                filtered.append(record)
                continue
            if str(record.get("event_id") or "") == after_event_id:
                seen = True
        records = filtered

    items: list[AnalysisEventItem] = []
    for record in records:
        topic = str(record.get("topic") or "")
        payload = dict(record.get("payload") or {})
        if topic == EventTopic.UI_TASK_STATUS_UPDATE.value:
            kind = "status"
            title = status_label(str(payload.get("new_status") or ""))
            message = str(payload.get("message") or payload.get("sub_status") or "")
            status = str(payload.get("new_status") or "") or None
        elif topic == EventTopic.UI_TASK_GOVERNANCE_UPDATE.value:
            kind = "governance"
            title = "系统风险检查"
            decision = dict(payload.get("decision") or {})
            message = "系统已完成风险检查，当前任务可以继续。" if decision.get("allowed") else "当前任务被策略拦截，需要调整后再继续。"
            status = None
        elif topic == EventTopic.UI_TASK_TRACE_UPDATE.value:
            kind = "trace"
            event = dict(payload.get("event") or payload)
            title = "系统处理进度"
            raw_message = str(event.get("message") or event.get("event_type") or "")
            message = raw_message if raw_message and not _looks_like_internal_copy(raw_message) else "系统已完成一项内部处理步骤。"
            status = None
        elif topic == EventTopic.UI_ARTIFACT_READY.value:
            kind = "artifact"
            title = "结果产物已生成"
            message = str(payload.get("message") or "")
            status = None
        elif topic == EventTopic.SYS_TASK_FINISHED.value:
            kind = "finished"
            title = status_label(str(payload.get("final_status") or ""))
            message = str(payload.get("message") or "")
            status = str(payload.get("final_status") or "") or None
        else:
            continue
        items.append(
            AnalysisEventItem(
                eventId=str(record.get("event_id") or ""),
                kind=kind,
                timestamp=str(record.get("timestamp") or ""),
                title=title,
                message=message,
                status=status,
            )
        )
    last_event_id = items[-1].eventId if items else after_event_id
    return items, last_event_id


def list_workspace_assets_for_app(tenant_id: str, workspace_id: str) -> list[AssetListItem]:
    raw_assets: list[dict[str, Any]] = []
    execution_states = execution_blackboard.list_workspace_states(tenant_id, workspace_id)
    for execution_data in execution_states:
        for dataset in execution_data.inputs.structured_datasets:
            raw_assets.append(
                {
                    "kind": "structured_dataset",
                    "task_id": execution_data.task_id,
                    "file_name": dataset.file_name,
                    "path": dataset.path,
                    "schema_ready": bool(dataset.dataset_schema),
                    "file_sha256": dataset.file_sha256,
                    "status": "ready" if dataset.dataset_schema else "uploaded",
                }
            )

    business_assets_by_path: dict[str, dict[str, Any]] = {}
    knowledge_states = knowledge_blackboard.list_workspace_states(tenant_id, workspace_id)
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
                "status": str(parser_report.get("status") or document.status or "pending"),
                "file_sha256": document.file_sha256,
            }
            asset_key = str(document.path or f"{knowledge_data.task_id}:{file_name}")
            existing = business_assets_by_path.get(asset_key)
            if existing is None or (existing.get("status") != "parsed" and candidate.get("status") == "parsed"):
                business_assets_by_path[asset_key] = candidate
    raw_assets.extend(business_assets_by_path.values())

    upload_root = Path(UPLOAD_DIR) / tenant_id / workspace_id
    upload_files = sorted(upload_root.glob("*")) if upload_root.exists() else []
    for file_path in upload_files:
        if not any(str(asset.get("path") or "") == str(file_path) for asset in raw_assets):
            suffix = file_path.suffix.lower()
            kind = "structured_dataset" if suffix in {".csv", ".tsv", ".json"} else "business_document"
            raw_assets.append(
                {
                    "kind": kind,
                    "task_id": None,
                    "file_name": file_path.name,
                    "path": str(file_path),
                    "status": "uploaded",
                }
            )

    items: list[AssetListItem] = []
    for asset in raw_assets:
        status = str(asset.get("status") or "uploaded")
        readiness = "可直接分析" if status in {"ready", "parsed"} or bool(asset.get("schema_ready")) else "待处理"
        items.append(
            AssetListItem(
                assetId=asset_public_id(asset),
                name=str(asset.get("file_name") or "未命名资料"),
                kind=str(asset.get("kind") or "asset"),
                status=status,
                readinessLabel=readiness,
                filePath=str(asset.get("path") or "") or None,
                schemaReady=bool(asset.get("schema_ready")),
            )
        )
    items.sort(key=lambda item: (item.kind, item.name.lower()))
    return items


def list_workspace_methods_for_app(tenant_id: str, workspace_id: str) -> list[MethodCard]:
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

    items: list[MethodCard] = []
    for skill in skills:
        usage = dict(skill.get("usage") or skill.get("metadata", {}).get("usage") or {})
        promotion = dict(skill.get("promotion") or {})
        items.append(
            MethodCard(
                methodId=_opaque_id("method", str(skill.get("name") or "unknown")),
                name=str(skill.get("name") or "unknown"),
                description=str(skill.get("description") or ""),
                requiredCapabilities=[str(item) for item in list(skill.get("required_capabilities") or [])],
                usageCount=int(usage.get("usage_count") or 0),
                promotionStatus=str(promotion.get("status") or "available"),
            )
        )
    items.sort(key=lambda item: item.name.lower())
    return items


def list_workspace_audit_items_for_app(
    tenant_id: str,
    workspace_id: str,
    **filters: Any,
) -> tuple[list[dict[str, Any]], int]:
    return AuditRepo.query_records(tenant_id, workspace_id, **filters)
