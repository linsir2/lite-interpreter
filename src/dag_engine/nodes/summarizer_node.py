"""Unified final-response node for static and dynamic execution paths."""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Mapping

from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.global_blackboard import global_blackboard
from src.blackboard.schema import GlobalStatus
from src.common import EventTopic, event_bus
from src.privacy import mask_payload


def _trim(value: str, limit: int = 600) -> str:
    compact = " ".join((value or "").split())
    return compact[:limit]


def _as_json(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _build_static_response(task_id: str, exec_data) -> Dict[str, Any]:
    result = exec_data.execution_result or {}
    output = str(result.get("output") or "")
    structured_output = _as_json(output)
    dataset_items = structured_output.get("datasets", []) if isinstance(structured_output.get("datasets"), list) else []
    document_items = structured_output.get("documents", []) if isinstance(structured_output.get("documents"), list) else []
    derived_findings = structured_output.get("derived_findings", []) if isinstance(structured_output.get("derived_findings"), list) else []
    rule_checks = structured_output.get("rule_checks", []) if isinstance(structured_output.get("rule_checks"), list) else []
    metric_checks = structured_output.get("metric_checks", []) if isinstance(structured_output.get("metric_checks"), list) else []
    filter_checks = structured_output.get("filter_checks", []) if isinstance(structured_output.get("filter_checks"), list) else []

    findings = []
    if dataset_items:
        findings.append(f"识别到 {len(dataset_items)} 份结构化数据输入")
    if document_items:
        findings.append(f"识别到 {len(document_items)} 份业务文档输入")
    if exec_data.business_context.get("rules"):
        findings.append(f"命中 {len(exec_data.business_context['rules'])} 条业务规则")
    if exec_data.knowledge_snapshot.get("recall_strategies"):
        findings.append(
            f"知识检索通道: {', '.join(str(item) for item in exec_data.knowledge_snapshot.get('recall_strategies', [])[:4])}"
        )
    if exec_data.knowledge_snapshot.get("cache_hit") is True:
        findings.append("知识检索命中缓存")
    findings.extend([_trim(str(item), limit=240) for item in derived_findings[:5]])
    findings.extend(
        [
            _trim(f"规则《{check.get('rule', '')[:20]}》发现 {check.get('issue_count', 0)} 个潜在问题", limit=240)
            for check in rule_checks[:5]
            if int(check.get("issue_count", 0) or 0) > 0
        ]
    )
    findings.extend(
        [
            _trim(f"指标《{check.get('metric', '')[:20]}》关联字段 {len(check.get('matched_columns', []) or [])} 个", limit=240)
            for check in metric_checks[:5]
            if check.get("matched_columns")
        ]
    )
    findings.extend(
        [
            _trim(f"指标《{check.get('metric', '')[:20]}》可复用 {len(check.get('matched_groups', []) or [])} 个分组统计", limit=240)
            for check in metric_checks[:5]
            if check.get("matched_groups")
        ]
    )
    findings.extend(
        [
            _trim(f"过滤条件《{check.get('filter', '')[:20]}》存在命中", limit=240)
            for check in filter_checks[:5]
            if check.get("matched_datasets") or check.get("matched_documents") or check.get("matched_date_ranges")
        ]
    )
    if not findings:
        findings.append("静态链已成功执行，但未提取出更多结构化结论")

    answer = (
        "已完成静态链分析。"
        f" {'；'.join(findings)}。"
        f" 任务输出状态为 {'成功' if result.get('success') else '失败'}。"
    )
    evidence_refs = [str(item) for item in exec_data.business_context_refs if item]
    if not evidence_refs:
        evidence_refs = [str(item.get("path")) for item in exec_data.artifacts if item.get("path")]

    outputs = []
    for item in dataset_items:
        outputs.append(
            {
                "type": "dataset",
                "name": item.get("file_name"),
                "path": item.get("container_path") or item.get("file_name"),
                "summary": _trim(
                    f"rows={item.get('row_count', 0)}, columns={','.join(item.get('columns', [])[:6])}"
                ),
                "metrics": {
                    "row_count": item.get("row_count", 0),
                    "numeric_profiles": item.get("numeric_profiles", []),
                    "categorical_profiles": item.get("categorical_profiles", []),
                    "date_profiles": item.get("date_profiles", []),
                    "group_summaries": item.get("group_summaries", []),
                    "missing_counts": item.get("missing_counts", {}),
                },
            }
        )
    for item in document_items:
        outputs.append(
            {
                "type": "document",
                "name": item.get("file_name"),
                "path": item.get("container_path") or item.get("file_name"),
                "summary": _trim(str(item.get("preview", ""))),
                "metrics": {
                    "char_count": item.get("char_count", 0),
                    "line_count": item.get("line_count", 0),
                    "keyword_hits": item.get("keyword_hits", []),
                },
            }
        )
    for report in exec_data.parser_reports:
        outputs.append(
            {
                "type": "parser_report",
                "name": report.get("file_name"),
                "path": None,
                "summary": _trim(
                    f"parse_mode={report.get('parse_mode', 'default')}, "
                    f"image_desc={((report.get('parser_diagnostics') or {}).get('image_description_count', 0))}"
                ),
                "parse_mode": report.get("parse_mode", "default"),
            }
        )
    for artifact in exec_data.artifacts:
        artifact_path = artifact.get("path")
        outputs.append(
            {
                "type": artifact.get("type", "artifact"),
                "name": os.path.basename(str(artifact_path)) if artifact_path else artifact.get("type", "artifact"),
                "path": artifact_path,
                "summary": str(artifact_path),
            }
        )

    caveats = []
    if exec_data.latest_error_traceback:
        caveats.append(_trim(exec_data.latest_error_traceback))
    for check in rule_checks[:5]:
        warnings = check.get("warnings", []) or []
        for warning in warnings[:2]:
            caveats.append(_trim(str(warning), limit=240))
    for check in metric_checks[:5]:
        for highlight in (check.get("highlights", []) or [])[:2]:
            caveats.append(_trim(f"指标提示: {highlight}", limit=240))
    for check in filter_checks[:5]:
        for matched_range in (check.get("matched_date_ranges", []) or [])[:2]:
            caveats.append(_trim(f"过滤条件命中日期范围: {matched_range}", limit=240))
    if not dataset_items and exec_data.structured_datasets:
        caveats.append("结构化数据已挂载，但当前最小代码仅输出概览，不做深度统计。")
    if not document_items and exec_data.business_documents:
        caveats.append("业务文档已挂载，但当前最小代码仅输出预览，不做全文语义推理。")

    details = {
        "analysis_plan": exec_data.analysis_plan,
        "execution_success": bool(result.get("success")),
        "artifacts": exec_data.artifacts,
        "execution_record": exec_data.execution_record.model_dump(mode="json") if exec_data.execution_record else None,
        "business_context": exec_data.business_context,
        "knowledge_snapshot": exec_data.knowledge_snapshot,
        "approved_skills": exec_data.approved_skills,
        "historical_skill_matches": exec_data.historical_skill_matches,
        "used_historical_skills": [
            match for match in exec_data.historical_skill_matches
            if bool(match.get("used_in_codegen"))
        ],
        "skill_strategy_hints": (
            structured_output.get("skill_strategy_hints", [])
            if isinstance(structured_output.get("skill_strategy_hints"), list)
            else [
                {
                    "name": skill.get("name"),
                    "promotion_status": (skill.get("promotion") or {}).get("status"),
                }
                for skill in exec_data.approved_skills[:5]
            ]
        ),
        "structured_output": structured_output,
        "parser_reports": exec_data.parser_reports,
        "derived_findings": derived_findings,
        "rule_checks": rule_checks,
        "metric_checks": metric_checks,
        "filter_checks": filter_checks,
    }

    return {
        "mode": "static",
        "task_id": task_id,
        "headline": _trim(answer),
        "answer": _trim(answer, limit=1200),
        "key_findings": findings,
        "evidence_refs": evidence_refs,
        "outputs": outputs,
        "caveats": caveats,
        "details": details,
    }


def _build_dynamic_response(task_id: str, exec_data) -> Dict[str, Any]:
    dynamic_summary = exec_data.dynamic_summary or "Dynamic chain finished without summary."
    findings = [
        f"动态链路状态: {exec_data.dynamic_status or 'unknown'}",
        f"轨迹事件: {len(exec_data.dynamic_trace)} 条",
    ]
    if exec_data.recommended_static_skill:
        findings.append("生成了可候选沉淀的静态技能建议")

    answer = f"已完成动态探索。{_trim(dynamic_summary, limit=800)}"
    outputs = [
        {
            "type": "artifact",
            "name": os.path.basename(str(artifact)) if artifact else "artifact",
            "path": artifact,
            "summary": artifact,
        }
        for artifact in exec_data.dynamic_artifacts
    ]
    caveats = []
    if exec_data.dynamic_status and exec_data.dynamic_status != "completed":
        caveats.append(f"动态链路最终状态为 {exec_data.dynamic_status}，请结合轨迹核实结果完整性。")

    details = {
        "dynamic_status": exec_data.dynamic_status,
        "runtime_metadata": exec_data.dynamic_runtime_metadata,
        "trace_refs": exec_data.dynamic_trace_refs,
        "artifacts": exec_data.dynamic_artifacts,
        "recommended_skill": exec_data.recommended_static_skill,
        "decision_log": exec_data.decision_log,
        "knowledge_snapshot": exec_data.knowledge_snapshot,
        "historical_skill_matches": exec_data.historical_skill_matches,
        "parser_reports": exec_data.parser_reports,
    }

    return {
        "mode": "dynamic",
        "task_id": task_id,
        "headline": _trim(dynamic_summary),
        "answer": answer,
        "key_findings": findings,
        "evidence_refs": [str(item) for item in exec_data.dynamic_trace_refs if item],
        "outputs": outputs,
        "caveats": caveats,
        "details": details,
    }


def summarizer_node(state: Mapping[str, Any]) -> Dict[str, Any]:
    tenant_id = str(state.get("tenant_id", ""))
    task_id = str(state.get("task_id", ""))
    workspace_id = str(state.get("workspace_id", "default_ws"))

    exec_data = execution_blackboard.read(tenant_id, task_id)
    if not exec_data:
        return {"final_response": {}}

    global_blackboard.update_global_status(
        task_id=task_id,
        new_status=GlobalStatus.SUMMARIZING,
        sub_status="正在组装最终回复",
    )

    mode = "dynamic" if exec_data.routing_mode == "dynamic" or exec_data.dynamic_summary else "static"
    final_response = _build_dynamic_response(task_id, exec_data) if mode == "dynamic" else _build_static_response(task_id, exec_data)
    final_response["governance"] = {
        "profile": exec_data.governance_profile,
        "decision_count": len(exec_data.governance_decisions),
    }
    final_response, redaction_report = mask_payload(final_response, list(exec_data.task_envelope.redaction_rules or []) if exec_data.task_envelope else None)
    if isinstance(final_response, dict) and redaction_report["match_count"]:
        final_response.setdefault("governance", {})
        final_response["governance"]["redaction_report"] = {
            "match_count": redaction_report["match_count"],
            "rule_hits": redaction_report["rule_hits"],
        }

    exec_data.final_response = final_response
    execution_blackboard.write(tenant_id, task_id, exec_data)
    execution_blackboard.persist(tenant_id, task_id)

    event_bus.publish(
        topic=EventTopic.UI_TASK_STATUS_UPDATE,
        tenant_id=tenant_id,
        task_id=task_id,
        workspace_id=workspace_id,
        payload={
            "new_status": GlobalStatus.SUMMARIZING.value,
            "message": "Final response ready",
            "final_response": final_response,
        },
        trace_id=task_id,
    )

    return {"final_response": final_response}
