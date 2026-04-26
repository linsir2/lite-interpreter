"""Compiler for constrained static program specs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

_COMPILER_TEMPLATE = r'''
import csv
import json
from datetime import datetime
from pathlib import Path

payload = json.loads(__PAYLOAD_LITERAL__)
spec = json.loads(__SPEC_LITERAL__)
generation_directives = payload.get("generation_directives", {}) or {}
compiled_knowledge = payload.get("compiled_knowledge", {}) or {}
business_context = payload.get("business_context", {}) or {}
rule_specs = list(compiled_knowledge.get("rule_specs") or [])
metric_specs = list(compiled_knowledge.get("metric_specs") or [])
filter_specs = list(compiled_knowledge.get("filter_specs") or [])
result = {
    "query": payload.get("query", ""),
    "analysis_mode": payload.get("analysis_mode", ""),
    "analysis_plan": payload.get("analysis_plan", ""),
    "datasets": [],
    "documents": [],
    "external_evidence": [],
    "derived_findings": [],
    "rule_checks": [],
    "metric_checks": [],
    "filter_checks": [],
    "status": "static_chain_generated",
}
class DerivedFindingsCollector(list):
    pass

def finalize_derived_findings():
    return None

def take_strings(values, limit=12):
    return [str(item).strip() for item in list(values or [])[:limit] if str(item).strip()]

business_terms = []
for key in ("rules", "metrics", "filters"):
    business_terms.extend(take_strings(business_context.get(key), limit=10))
for spec_item in rule_specs + metric_specs + filter_specs:
    if isinstance(spec_item, dict):
        business_terms.extend(take_strings(spec_item.get("subject_terms"), limit=8))
        business_terms.extend(take_strings(spec_item.get("required_terms"), limit=8))
        business_terms.extend(take_strings(spec_item.get("measure_terms"), limit=8))
        business_terms.extend(take_strings(spec_item.get("group_terms"), limit=8))
        if spec_item.get("metric_name"):
            business_terms.append(str(spec_item.get("metric_name")).strip())
        if spec_item.get("value"):
            business_terms.append(str(spec_item.get("value")).strip())
business_terms = [item for index, item in enumerate(business_terms) if item and item not in business_terms[:index]]
if compiled_knowledge.get("graph_compilation_summary"):
    summary = compiled_knowledge.get("graph_compilation_summary") or {}
    result["derived_findings"].append(
        f"图谱编译摘要：候选={summary.get('candidate_count', 0)}，接受={summary.get('accepted_count', 0)}，拒绝={summary.get('rejected_count', 0)}。"
    )
if compiled_knowledge.get("spec_parse_errors"):
    result["derived_findings"].append(f"编译态记录了 {len(list(compiled_knowledge.get('spec_parse_errors') or []))} 条未成功解析的规则/指标/过滤表达。")

def to_number(value):
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None

def looks_like_date(value):
    text = str(value or "").strip()
    if not text:
        return False
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return True
    except Exception:
        pass
    return False

def load_rows(mount):
    path = Path(str(mount.get("container_path") or mount.get("host_path") or ""))
    suffix = path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        if isinstance(payload, list):
            return [dict(item) for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            return [payload]
        return []
    delimiter = "\t" if suffix == ".tsv" else str(mount.get("sep") or ",")
    with path.open("r", encoding=str(mount.get("encoding") or "utf-8"), errors="ignore", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter=delimiter)]

def summarize_dataset(mount):
    rows = load_rows(mount)
    path = Path(str(mount.get("container_path") or mount.get("host_path") or ""))
    columns = list(rows[0].keys()) if rows else []
    numeric_profiles = []
    categorical_profiles = []
    date_profiles = []
    group_summaries = []
    for column in columns[:24]:
        values = [row.get(column) for row in rows]
        numeric_values = [to_number(value) for value in values]
        numeric_values = [value for value in numeric_values if value is not None]
        if numeric_values:
            numeric_profiles.append(
                {
                    "column": column,
                    "mean": round(sum(numeric_values) / len(numeric_values), 4),
                    "min": round(min(numeric_values), 4),
                    "max": round(max(numeric_values), 4),
                }
            )
        string_values = [str(value).strip() for value in values if str(value).strip()]
        if string_values and all(looks_like_date(value) for value in string_values[: min(8, len(string_values))]):
            date_profiles.append({"column": column, "min": min(string_values), "max": max(string_values)})
        elif string_values and len(set(string_values)) <= 20:
            counts = {}
            for item in string_values:
                counts[item] = counts.get(item, 0) + 1
            categorical_profiles.append(
                {
                    "column": column,
                    "top_values": [[key, value] for key, value in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:5]],
                }
            )
    preferred_date_terms = []
    preferred_measure_terms = []
    for metric_spec in metric_specs[:6]:
        if isinstance(metric_spec, dict):
            preferred_measure_terms.extend(take_strings(metric_spec.get("measure_terms"), limit=4))
            preferred_date_terms.extend(take_strings(metric_spec.get("preferred_date_terms"), limit=4))
    for filter_spec in filter_specs[:6]:
        if isinstance(filter_spec, dict):
            preferred_date_terms.extend(take_strings(filter_spec.get("preferred_date_terms"), limit=4))
    preferred_date_terms = [item for index, item in enumerate(preferred_date_terms) if item and item not in preferred_date_terms[:index]]
    preferred_measure_terms = [item for index, item in enumerate(preferred_measure_terms) if item and item not in preferred_measure_terms[:index]]
    date_profiles.sort(key=lambda item: (0 if item.get("column") in preferred_date_terms else 1, str(item.get("column") or "")))
    if preferred_date_terms:
        prioritized = [item for item in date_profiles if item.get("column") in preferred_date_terms]
        if prioritized:
            date_profiles = prioritized
    summary = {
        "file_name": mount.get("file_name", path.name or "dataset"),
        "row_count": len(rows),
        "columns": columns,
        "numeric_profiles": numeric_profiles[:6],
        "categorical_profiles": categorical_profiles[:6],
        "date_profiles": date_profiles[:4],
        "group_summaries": group_summaries,
        "missing_counts": {
            column: sum(1 for row in rows if str(row.get(column, "")).strip() == "")
            for column in columns[:12]
        },
    }
    for metric_spec in metric_specs[:6]:
        if not isinstance(metric_spec, dict):
            continue
        group_terms = take_strings(metric_spec.get("group_terms"), limit=4)
        measure_terms = take_strings(metric_spec.get("measure_terms"), limit=4)
        for group_term in group_terms:
            for measure_term in measure_terms:
                if group_term in columns and measure_term in columns:
                    totals = {}
                    counts = {}
                    for row in rows:
                        group_value = str(row.get(group_term, "")).strip()
                        measure_value = to_number(row.get(measure_term))
                        if not group_value or measure_value is None:
                            continue
                        totals[group_value] = totals.get(group_value, 0.0) + measure_value
                        counts[group_value] = counts.get(group_value, 0) + 1
                    top_groups = [
                        [group_name, round(total, 4), counts.get(group_name, 0)]
                        for group_name, total in sorted(totals.items(), key=lambda item: item[1], reverse=True)[:3]
                    ]
                    if top_groups:
                        summary["group_summaries"].append(
                            {
                                "group_by": group_term,
                                "measure": measure_term,
                                "top_groups": top_groups,
                            }
                        )
                    break
            if summary["group_summaries"]:
                break
    result["datasets"].append(summary)
    if numeric_profiles:
        result["derived_findings"].append(f"数据集 {summary['file_name']} 识别出 {len(numeric_profiles)} 个数值列。")
        preferred_numeric = next((item["column"] for item in numeric_profiles if item["column"] in preferred_measure_terms), None)
        if preferred_numeric:
            result["derived_findings"].append(f"数据集 {summary['file_name']} 的编译态优先指标列为 {preferred_numeric}。")
    if date_profiles:
        result["derived_findings"].append(f"数据集 {summary['file_name']} 识别出 {len(date_profiles)} 个日期列。")
        if preferred_date_terms and date_profiles:
            result["derived_findings"].append(f"数据集 {summary['file_name']} 的编译态优先日期列为 {date_profiles[0]['column']}。")

def summarize_document(mount):
    path = Path(str(mount.get("container_path") or mount.get("host_path") or ""))
    content = path.read_text(encoding="utf-8", errors="ignore")
    keywords = []
    for token in business_terms:
        if token and token in content and token not in keywords:
            keywords.append(token)
    summary = {
        "file_name": mount.get("file_name", path.name),
        "preview": content[:240],
        "keyword_hits": keywords[:10],
        "char_count": len(content),
        "line_count": len(content.splitlines()),
    }
    result["documents"].append(summary)
    if keywords:
        result["derived_findings"].append(f"文档 {summary['file_name']} 命中了 {len(keywords)} 个业务关键词。")

def summarize_evidence(bundle):
    for record in list((bundle or {}).get("records") or [])[:6]:
        normalized = {
            "title": str(record.get("title") or record.get("url") or "external evidence"),
            "url": str(record.get("url") or ""),
            "domain": str(record.get("domain") or ""),
            "snippet": str(record.get("snippet") or ""),
            "source_type": str(record.get("source_type") or "search_result"),
        }
        result["external_evidence"].append(normalized)
        if normalized["title"] or normalized["snippet"]:
            result["derived_findings"].append(
                f"外部证据 {normalized['title']}：{(normalized['snippet'] or normalized['url'])[:120]}"
            )

def derive_checks():
    for rule in take_strings(business_context.get("rules"), limit=8) + [
        str(item.get("source_text") or item.get("normalized_text") or "规则").strip()
        for item in rule_specs[:8]
        if isinstance(item, dict)
    ]:
        result["rule_checks"].append({"rule": rule, "issue_count": 0, "warnings": []})
    for metric in (
        take_strings(business_context.get("metrics"), limit=8)
        + [str(item.get("metric_name") or item.get("source_text") or "指标").strip() for item in metric_specs[:8] if isinstance(item, dict)]
    ):
        matched_columns = []
        matched_groups = []
        for dataset in result["datasets"]:
            matched_columns.extend(
                [
                    column
                    for column in dataset.get("columns", [])
                    if metric in column
                    or column in metric
                    or any(column == term for spec_item in metric_specs if isinstance(spec_item, dict) for term in take_strings(spec_item.get("measure_terms"), limit=8))
                ]
            )
            group_terms = [
                term
                for spec_item in metric_specs
                if isinstance(spec_item, dict)
                and metric in {str(spec_item.get("metric_name") or ""), str(spec_item.get("source_text") or "")}
                for term in take_strings(spec_item.get("group_terms"), limit=8)
            ]
            for group_term in group_terms:
                if group_term in dataset.get("columns", []) and matched_columns:
                    matched_groups.append(f"{group_term} -> {matched_columns[0]}")
        result["metric_checks"].append({"metric": metric, "matched_columns": matched_columns[:8], "matched_groups": matched_groups[:4], "highlights": []})
    for item in (
        take_strings(business_context.get("filters"), limit=8)
        + [str(spec_item.get("value") or spec_item.get("source_text") or "过滤条件").strip() for spec_item in filter_specs[:8] if isinstance(spec_item, dict)]
    ):
        matched_documents = [document.get("file_name") for document in result["documents"] if item in "".join(document.get("keyword_hits", []))]
        matched_evidence = [evidence.get("url") for evidence in result["external_evidence"] if item in evidence.get("snippet", "")]
        matched_datasets = []
        matched_values = []
        for dataset in result["datasets"]:
            for column in dataset.get("columns", []):
                if item in str(column):
                    matched_datasets.append(dataset.get("file_name"))
            for profile in dataset.get("categorical_profiles", []):
                flattened = " ".join(str(value) for value in profile.get("top_values", []))
                if item in flattened:
                    matched_datasets.append(dataset.get("file_name"))
                    matched_values.append(item)
            if item in json.dumps(dataset.get("date_profiles", []), ensure_ascii=False):
                matched_datasets.append(dataset.get("file_name"))
                matched_values.append(item)
        result["filter_checks"].append(
            {
                "filter": item,
                "matched_documents": matched_documents,
                "matched_evidence": matched_evidence,
                "matched_datasets": [value for index, value in enumerate(matched_datasets) if value and value not in matched_datasets[:index]],
                "matched_values": [value for index, value in enumerate(matched_values) if value and value not in matched_values[:index]],
                "matched_date_ranges": [],
            }
        )

steps = {step.get("kind"): step for step in list(spec.get("steps") or [])}
input_mounts = list(payload.get("input_mounts") or [])
for mount in input_mounts:
    if mount.get("kind") == "structured_dataset" and "load_datasets" in steps:
        summarize_dataset(mount)
    elif mount.get("kind") == "business_document" and "load_documents" in steps:
        summarize_document(mount)
if "load_evidence" in steps:
    summarize_evidence(payload.get("static_evidence_bundle") or {})
if any(kind in steps for kind in ("derive_rule_checks", "derive_metric_checks", "derive_filter_checks")):
    derive_checks()

output_root = Path(str((payload.get("execution_strategy") or {}).get("artifact_plan", {}).get("output_root") or "/app/outputs"))
try:
    output_root.mkdir(parents=True, exist_ok=True)
except OSError:
    output_root = Path("/tmp/lite_interpreter_artifacts")
    output_root.mkdir(parents=True, exist_ok=True)

generated_artifacts = []
def register_artifact(emit_spec, path, summary):
    generated_artifacts.append(
        {
            "key": emit_spec.get("artifact_key", ""),
            "name": path.name,
            "path": str(path),
            "type": emit_spec.get("category", "diagnostic"),
            "category": emit_spec.get("category", "diagnostic"),
            "summary": summary,
        }
    )

def write_text(file_name, content):
    path = output_root / str(file_name)
    path.write_text(content, encoding="utf-8")
    return path

def write_json(file_name, content):
    path = output_root / str(file_name)
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    return path

def write_csv(file_name, headers, rows):
    path = output_root / str(file_name)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in headers})
    return path

for emit_spec in list(spec.get("artifact_emits") or []):
    emit_kind = emit_spec.get("emit_kind")
    if emit_kind == "analysis_report":
        findings_lines = [f"- {item}" for item in take_strings(result.get("derived_findings"))] or ["- 暂无结构化发现。"]
        content = "\n".join(
            [
                f"# {spec.get('strategy_family', 'analysis')} report",
                "",
                f"- query: {payload.get('query', '')}",
                f"- research_mode: {spec.get('research_mode', 'none')}",
                "",
                "## Findings",
                *findings_lines,
                "",
            ]
        )
        path = write_text(emit_spec.get("file_name"), content)
        register_artifact(emit_spec, path, "analysis report")
    elif emit_kind == "summary_json":
        path = write_json(
            emit_spec.get("file_name"),
            {
                "query": payload.get("query", ""),
                "datasets": result.get("datasets", []),
                "documents": result.get("documents", []),
                "external_evidence": result.get("external_evidence", []),
                "key_findings": take_strings(result.get("derived_findings")),
            },
        )
        register_artifact(emit_spec, path, "summary json")
    elif emit_kind == "rule_checks_json":
        path = write_json(emit_spec.get("file_name"), result.get("rule_checks", []))
        register_artifact(emit_spec, path, "rule checks")
    elif emit_kind == "cross_source_findings_json":
        path = write_json(
            emit_spec.get("file_name"),
            {
                "dataset_count": len(result.get("datasets", [])),
                "document_count": len(result.get("documents", [])),
                "external_evidence_count": len(result.get("external_evidence", [])),
                "findings": take_strings(result.get("derived_findings")),
            },
        )
        register_artifact(emit_spec, path, "cross source findings")
    elif emit_kind == "comparison_csv":
        rows = []
        for dataset in result.get("datasets", []):
            for profile in dataset.get("numeric_profiles", [])[:4]:
                rows.append(
                    {
                        "dataset": dataset.get("file_name", ""),
                        "column": profile.get("column", ""),
                        "mean": profile.get("mean", ""),
                        "min": profile.get("min", ""),
                        "max": profile.get("max", ""),
                    }
                )
        if not rows:
            rows = [{"dataset": "", "column": "", "mean": "", "min": "", "max": ""}]
        path = write_csv(emit_spec.get("file_name"), ["dataset", "column", "mean", "min", "max"], rows)
        register_artifact(emit_spec, path, "comparison csv")
    elif emit_kind == "input_gap_report":
        known_gaps = take_strings((payload.get("analysis_brief") or {}).get("known_gaps"))
        if not known_gaps:
            known_gaps = ["当前输入不足以完成稳定分析，请补充资料后重试。"]
        content = "\n".join(["# Input Gap Report", "", "## Missing Inputs", *[f"- {item}" for item in known_gaps], ""])
        path = write_text(emit_spec.get("file_name"), content)
        register_artifact(emit_spec, path, "input gap report")
    elif emit_kind == "requested_inputs_json":
        path = write_json(
            emit_spec.get("file_name"),
            {
                "known_gaps": take_strings((payload.get("analysis_brief") or {}).get("known_gaps")),
                "recommended_next_step": (payload.get("analysis_brief") or {}).get("recommended_next_step", ""),
            },
        )
        register_artifact(emit_spec, path, "requested inputs")

result["generated_artifacts"] = generated_artifacts
result["execution_strategy"] = payload.get("execution_strategy", {})
result["generator_manifest"] = payload.get("generator_manifest", {})
print(json.dumps(result, ensure_ascii=False))
'''


def compile_static_program(spec: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    return (
        _COMPILER_TEMPLATE.replace("__PAYLOAD_LITERAL__", repr(json.dumps(dict(payload), ensure_ascii=False)))
        .replace("__SPEC_LITERAL__", repr(json.dumps(dict(spec), ensure_ascii=False)))
    )
