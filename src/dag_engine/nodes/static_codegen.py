"""Helpers for static coder payload assembly and code template rendering."""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from src.mcp_gateway.tools.sandbox_exec_tool import build_input_mount_manifest


def serialize_preview(text: str, limit: int = 160) -> str:
    collapsed = " ".join(text.split())
    return collapsed[:limit]


def build_skill_strategy_hints(approved_skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    for skill in approved_skills[:5]:
        capabilities = [str(item) for item in skill.get("required_capabilities", []) if str(item).strip()]
        focus_areas: list[str] = []
        if "knowledge_query" in capabilities:
            focus_areas.append("优先复用已有知识检索证据")
        if "sandbox_exec" in capabilities:
            focus_areas.append("保留可执行验证闭环")
        if "web_search" in capabilities or "web_fetch" in capabilities:
            focus_areas.append("在证据不足时补充外部检索")
        replay_cases = skill.get("replay_cases", []) or []
        expected_signals = []
        if replay_cases and isinstance(replay_cases[0], Mapping):
            expected_signals = [str(item) for item in replay_cases[0].get("expected_signals", [])[:3] if str(item).strip()]
        hints.append(
            {
                "name": str(skill.get("name", "unknown_skill")),
                "focus_areas": focus_areas or ["复用该技能的既有执行模式"],
                "expected_signals": expected_signals,
                "promotion_status": str((skill.get("promotion") or {}).get("status", "unknown")),
            }
        )
    return hints


def build_static_input_mounts(exec_data: Any) -> list[dict[str, Any]]:
    input_mounts = build_input_mount_manifest(exec_data.inputs.structured_datasets, exec_data.inputs.business_documents)
    for mount in input_mounts:
        if mount["kind"] != "structured_dataset":
            continue
        dataset_meta = next(
            (item for item in exec_data.inputs.structured_datasets if str(item.path) == mount["host_path"]),
            {},
        )
        load_kwargs = dataset_meta.load_kwargs if hasattr(dataset_meta, "load_kwargs") else {}
        mount["encoding"] = str(load_kwargs.get("encoding") or "utf-8")
        mount["sep"] = str(load_kwargs.get("sep") or ",")
    return input_mounts


def build_static_coder_payload(
    *,
    exec_data: Any,
    state: Mapping[str, Any],
    input_mounts: list[dict[str, Any]],
    approved_skills: list[dict[str, Any]],
) -> dict[str, Any]:
    approved_skill_payloads = [
        skill.model_dump(mode="json", by_alias=True) if hasattr(skill, "model_dump") else dict(skill)
        for skill in approved_skills
    ]
    payload: dict[str, Any] = {
        "query": state["input_query"],
        "analysis_plan": exec_data.static.analysis_plan or "",
        "analysis_mode": str(((state.get("analysis_brief") or {}).get("analysis_mode")) or ""),
        "analysis_brief": dict(state.get("analysis_brief") or {}),
        "business_context": dict(exec_data.knowledge.business_context),
        "approved_skills": [
            (
                {
                    "name": skill_payload.get("name"),
                    "required_capabilities": skill_payload.get("required_capabilities", []),
                    "promotion": skill_payload.get("promotion", {}),
                    "replay_cases": skill_payload.get("replay_cases", []),
                }
            )
            for skill_payload in approved_skill_payloads
        ],
        "skill_strategy_hints": build_skill_strategy_hints(approved_skill_payloads),
        "refined_context_excerpt": serialize_preview(str(state.get("refined_context", "") or ""), limit=400),
        "input_mounts": input_mounts,
        "structured_dataset_summaries": [
            {
                "file_name": item.file_name,
                "schema": serialize_preview(str(item.dataset_schema), limit=240),
                "load_kwargs": item.load_kwargs,
            }
            for item in exec_data.inputs.structured_datasets
        ],
    }
    if exec_data.static.latest_error_traceback:
        payload["previous_error"] = serialize_preview(exec_data.static.latest_error_traceback, limit=400)
    return payload


def build_dataset_aware_code(payload: dict[str, Any]) -> str:
    payload_literal = json.dumps(payload, ensure_ascii=False)
    return f"""import csv
import json
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path

payload = json.loads({payload_literal!r})
result = {{
    "query": payload["query"],
    "analysis_plan": payload["analysis_plan"],
    "analysis_mode": payload.get("analysis_mode", ""),
    "analysis_brief": payload.get("analysis_brief", {{}}),
    "business_context": payload["business_context"],
    "approved_skills": payload.get("approved_skills", []),
    "skill_strategy_hints": payload.get("skill_strategy_hints", []),
    "datasets": [],
    "documents": [],
    "derived_findings": [],
    "rule_checks": [],
    "metric_checks": [],
    "filter_checks": [],
    "status": "static_chain_generated",
}}

business_keywords = []
business_rules = [str(item).strip() for item in payload.get("business_context", {{}}).get("rules", []) if str(item).strip()]
business_metrics = [str(item).strip() for item in payload.get("business_context", {{}}).get("metrics", []) if str(item).strip()]
business_filters = [str(item).strip() for item in payload.get("business_context", {{}}).get("filters", []) if str(item).strip()]
approved_skills = payload.get("approved_skills", []) or []
skill_strategy_hints = payload.get("skill_strategy_hints", []) or []
for values in payload.get("business_context", {{}}).values():
    if isinstance(values, list):
        for item in values:
            text = str(item).strip()
            if text:
                business_keywords.extend([token for token in text.replace('，', ' ').replace(',', ' ').split() if token])
for skill in approved_skills:
    skill_name = str(skill.get("name", "")).strip()
    if skill_name:
        result["derived_findings"].append(
            f"已加载可复用技能 {{skill_name}}，其能力要求为 {{', '.join(str(item) for item in skill.get('required_capabilities', [])[:4]) or 'none'}}。"
        )
for hint in skill_strategy_hints:
    focus = "；".join(str(item) for item in hint.get("focus_areas", [])[:3]) or "复用既有执行模式"
    expected = "；".join(str(item) for item in hint.get("expected_signals", [])[:3]) or "none"
    result["derived_findings"].append(
        f"技能策略 {{hint.get('name', 'unknown_skill')}}: {{focus}}；预期信号={{expected}}。"
    )

def to_number(value):
    text = str(value).strip().replace(',', '')
    if text == '':
        return None
    try:
        return float(text)
    except Exception:
        return None

def to_date(value):
    text = str(value).strip()
    if text == '':
        return None
    formats = [
        '%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d',
        '%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S',
        '%Y%m%d',
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    return None

def contains_any(text, keywords):
    lowered = str(text).lower()
    return any(keyword.lower() in lowered for keyword in keywords)

def collect_rule_checks(rule_text, dataset_summaries, document_summaries):
    check = {{
        "rule": rule_text,
        "matched_datasets": [],
        "matched_documents": [],
        "warnings": [],
        "issue_count": 0,
    }}
    lowered_rule = rule_text.lower()
    for dataset in dataset_summaries:
        columns = dataset.get("columns", [])
        column_text = " ".join(str(column) for column in columns)
        if contains_any(column_text, ["金额", "税", "合同", "审批", "时效", "rate", "tax", "contract", "amount"]):
            check["matched_datasets"].append(dataset.get("file_name"))
        if "含税" in rule_text and dataset.get("tax_missing_count", 0) > 0:
            check["warnings"].append(f"{{dataset.get('file_name')}} 存在 {{dataset.get('tax_missing_count')}} 行税额缺失/为0")
            check["issue_count"] += int(dataset.get("tax_missing_count", 0))
        if ("合同" in rule_text or "contract" in lowered_rule) and dataset.get("contract_missing_count", 0) > 0:
            check["warnings"].append(f"{{dataset.get('file_name')}} 存在 {{dataset.get('contract_missing_count')}} 行合同字段缺失")
            check["issue_count"] += int(dataset.get("contract_missing_count", 0))
    for document in document_summaries:
        if document.get("keyword_hits"):
            check["matched_documents"].append(document.get("file_name"))
    if not check["matched_datasets"] and not check["matched_documents"]:
        check["warnings"].append("未在当前输入中找到与该规则明显对应的数据列或文档命中")
    return check

def collect_metric_checks(metric_text, dataset_summaries):
    check = {{
        "metric": metric_text,
        "matched_datasets": [],
        "matched_columns": [],
        "matched_groups": [],
        "matched_date_columns": [],
        "highlights": [],
    }}
    lowered_metric = metric_text.lower()
    for dataset in dataset_summaries:
        for profile in dataset.get("numeric_profiles", []):
            column = str(profile.get("column", ""))
            if contains_any(column, ["金额", "tax", "rate", "ratio", "amount", "审批", "时效"]) or contains_any(metric_text, [column]):
                check["matched_datasets"].append(dataset.get("file_name"))
                check["matched_columns"].append(column)
                mean_value = profile.get("mean")
                check["highlights"].append(f"{{dataset.get('file_name')}}.{{column}} mean={{mean_value}}")
        for profile in dataset.get("date_profiles", []):
            column = str(profile.get("column", ""))
            if "时效" in metric_text or contains_any(metric_text, [column]):
                check["matched_datasets"].append(dataset.get("file_name"))
                check["matched_columns"].append(column)
                check["matched_date_columns"].append(column)
                check["highlights"].append(f"{{dataset.get('file_name')}}.{{column}} range={{profile.get('min')}} -> {{profile.get('max')}}")
        for group_summary in dataset.get("group_summaries", []):
            group_by = str(group_summary.get("group_by", ""))
            measure = str(group_summary.get("measure", ""))
            if contains_any(metric_text, [group_by, measure, "分布", "分组", "top", "topn", "排行"]):
                check["matched_datasets"].append(dataset.get("file_name"))
                check["matched_groups"].append(f"{{group_by}} -> {{measure}}")
                top_groups = group_summary.get("top_groups", []) or []
                if top_groups:
                    top_name = top_groups[0][0]
                    top_value = top_groups[0][1]
                    check["highlights"].append(f"{{dataset.get('file_name')}} 按 {{group_by}} 分组后，{{top_name}} 的 {{measure}} 最高={{top_value}}")
        if "时效" in metric_text and dataset.get("categorical_profiles"):
            check["highlights"].append(f"{{dataset.get('file_name')}} 可进一步按分类字段查看时效分布")
    return check

def collect_filter_checks(filter_text, dataset_summaries, document_summaries):
    check = {{
        "filter": filter_text,
        "matched_datasets": [],
        "matched_values": [],
        "matched_documents": [],
        "matched_date_ranges": [],
    }}
    lowered_filter = filter_text.lower()
    for dataset in dataset_summaries:
        for profile in dataset.get("categorical_profiles", []):
            top_values = profile.get("top_values", []) or []
            flattened = " ".join(str(value) for value in top_values)
            if lowered_filter and lowered_filter in flattened.lower():
                check["matched_datasets"].append(dataset.get("file_name"))
                check["matched_values"].append(f"{{profile.get('column')}} => {{flattened}}")
        for profile in dataset.get("date_profiles", []):
            date_min = str(profile.get("min", ""))
            date_max = str(profile.get("max", ""))
            if lowered_filter and (lowered_filter in date_min.lower() or lowered_filter in date_max.lower()):
                check["matched_datasets"].append(dataset.get("file_name"))
                check["matched_date_ranges"].append(f"{{profile.get('column')}} => {{date_min}} -> {{date_max}}")
    for document in document_summaries:
        for keyword in document.get("keyword_hits", []):
            if lowered_filter and lowered_filter in str(keyword).lower():
                check["matched_documents"].append(document.get("file_name"))
    return check

for item in payload.get("input_mounts", []):
    path = Path(item["container_path"])
    summary = {{
        "kind": item["kind"],
        "file_name": item["file_name"],
        "container_path": item["container_path"],
        "exists": path.exists(),
    }}
    if path.exists() and item["kind"] == "structured_dataset":
        try:
            with path.open("r", encoding=item.get("encoding") or "utf-8", errors="ignore", newline="") as handle:
                reader = csv.DictReader(handle, delimiter=item.get("sep") or ",")
                rows = list(reader)
            columns = list(reader.fieldnames or [])
            summary["row_count"] = len(rows)
            summary["columns"] = columns
            summary["sample_rows"] = rows[:3]
            summary["missing_counts"] = {{
                column: sum(1 for row in rows if not str(row.get(column, '')).strip())
                for column in columns[:20]
            }}
            tax_columns = [column for column in columns if contains_any(column, ["税", "tax", "vat"])]
            contract_columns = [column for column in columns if contains_any(column, ["合同", "contract"])]
            summary["tax_missing_count"] = sum(
                1
                for row in rows
                for column in tax_columns[:3]
                if to_number(row.get(column, '')) in (None, 0.0)
            ) if tax_columns else 0
            summary["contract_missing_count"] = sum(
                1
                for row in rows
                for column in contract_columns[:3]
                if not str(row.get(column, '')).strip()
            ) if contract_columns else 0

            numeric_profiles = []
            numeric_columns = []
            for column in columns[:20]:
                numeric_values = [to_number(row.get(column, '')) for row in rows]
                numeric_values = [value for value in numeric_values if value is not None]
                if len(numeric_values) >= max(2, len(rows) // 3 if rows else 2):
                    numeric_columns.append(column)
                    numeric_profiles.append(
                        {{
                            "column": column,
                            "count": len(numeric_values),
                            "min": min(numeric_values),
                            "max": max(numeric_values),
                            "mean": round(statistics.fmean(numeric_values), 4),
                        }}
                    )
            summary["numeric_profiles"] = numeric_profiles[:5]

            categorical_profiles = []
            for column in columns[:10]:
                values = [str(row.get(column, '')).strip() for row in rows if str(row.get(column, '')).strip()]
                if not values:
                    continue
                counter = Counter(values)
                top_values = counter.most_common(3)
                categorical_profiles.append(
                    {{
                        "column": column,
                        "unique_count": len(counter),
                        "top_values": top_values,
                    }}
                )
            summary["categorical_profiles"] = categorical_profiles[:5]

            date_profiles = []
            date_columns = []
            for column in columns[:12]:
                date_values = [to_date(row.get(column, '')) for row in rows]
                date_values = [value for value in date_values if value is not None]
                if len(date_values) >= max(2, len(rows) // 2 if rows else 2):
                    date_columns.append(column)
                    date_profiles.append(
                        {{
                            "column": column,
                            "count": len(date_values),
                            "min": min(date_values).isoformat(),
                            "max": max(date_values).isoformat(),
                        }}
                    )
            summary["date_profiles"] = date_profiles[:4]

            group_summaries = []
            primary_numeric = numeric_columns[0] if numeric_columns else None
            if primary_numeric:
                for column in columns[:8]:
                    if column == primary_numeric:
                        continue
                    values = [str(row.get(column, '')).strip() for row in rows if str(row.get(column, '')).strip()]
                    if not values:
                        continue
                    counter = Counter(values)
                    if len(counter) > 20:
                        continue
                    totals = {{}}
                    counts = {{}}
                    for row in rows:
                        key = str(row.get(column, '')).strip()
                        number = to_number(row.get(primary_numeric, ''))
                        if not key or number is None:
                            continue
                        totals[key] = totals.get(key, 0.0) + number
                        counts[key] = counts.get(key, 0) + 1
                    if totals:
                        top_groups = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:3]
                        group_summaries.append(
                            {{
                                "group_by": column,
                                "measure": primary_numeric,
                                "top_groups": [(key, round(value, 4), counts.get(key, 0)) for key, value in top_groups],
                            }}
                        )
            summary["group_summaries"] = group_summaries[:4]

            if numeric_profiles:
                result["derived_findings"].append(
                    f"数据集 {{item['file_name']}} 识别出 {{len(numeric_profiles)}} 个数值列，可进行统计分析。"
                )
            if date_profiles:
                result["derived_findings"].append(
                    f"数据集 {{item['file_name']}} 识别出 {{len(date_profiles)}} 个日期列，可进行趋势/时序分析。"
                )
            if group_summaries:
                first_group = group_summaries[0]
                result["derived_findings"].append(
                    f"数据集 {{item['file_name']}} 可按 {{first_group['group_by']}} 对 {{first_group['measure']}} 做分组统计。"
                )
            if rows:
                result["derived_findings"].append(
                    f"数据集 {{item['file_name']}} 共 {{len(rows)}} 行，前几个字段为：{{', '.join(columns[:5])}}。"
                )
        except Exception as exc:
            summary["error"] = str(exc)
        result["datasets"].append(summary)
    elif path.exists():
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            lowered = content.lower()
            keyword_hits = []
            for keyword in business_keywords[:40]:
                if keyword.lower() in lowered:
                    keyword_hits.append(keyword)
            summary["preview"] = content[:240]
            summary["char_count"] = len(content)
            summary["keyword_hits"] = keyword_hits[:10]
            summary["line_count"] = len(content.splitlines())
            if keyword_hits:
                result["derived_findings"].append(
                    f"文档 {{item['file_name']}} 命中了 {{len(keyword_hits[:10])}} 个业务关键词。"
                )
        except Exception as exc:
            summary["error"] = str(exc)
        result["documents"].append(summary)

for rule_text in business_rules[:10]:
    check = collect_rule_checks(rule_text, result["datasets"], result["documents"])
    result["rule_checks"].append(check)
    if check["issue_count"] > 0:
        result["derived_findings"].append(
            f"规则检查发现 {{check['issue_count']}} 个潜在问题：{{rule_text[:40]}}"
        )
    elif check["warnings"]:
        result["derived_findings"].append(
            f"规则检查提示：{{check['warnings'][0]}}"
        )

for metric_text in business_metrics[:10]:
    check = collect_metric_checks(metric_text, result["datasets"])
    result["metric_checks"].append(check)
    if check["highlights"]:
        result["derived_findings"].append(
            f"指标口径 {{metric_text[:30]}} 可关联 {{len(check['matched_columns'])}} 个字段。"
        )

for filter_text in business_filters[:10]:
    check = collect_filter_checks(filter_text, result["datasets"], result["documents"])
    result["filter_checks"].append(check)
    if check["matched_datasets"] or check["matched_documents"]:
        result["derived_findings"].append(
            f"过滤条件 {{filter_text[:30]}} 在当前输入中存在命中。"
        )

print(json.dumps(result, ensure_ascii=False))
"""
