"""Strategy-aware static generator registry and artifact-contract verification."""

from __future__ import annotations

import textwrap
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from config.settings import OUTPUT_DIR

from src.common.contracts import (
    ArtifactEmitSpec,
    ArtifactPlan,
    ArtifactSpec,
    ArtifactVerificationResult,
    ComputationStep,
    DebugHint,
    DynamicResumeOverlay,
    ExecutionRecord,
    ExecutionStrategy,
    GeneratorManifest,
    StaticEvidenceBundle,
    StaticProgramSpec,
    StrategyFamily,
    VerificationPlan,
)
from src.common.control_plane import (
    artifact_category_from_path,
    ensure_artifact_plan,
    ensure_artifact_verification_result,
    ensure_dynamic_resume_overlay,
    ensure_execution_strategy,
    ensure_generator_manifest,
    ensure_static_program_spec,
    ensure_verification_plan,
    sanitize_artifact_reference,
    static_artifacts,
)
from src.dag_engine.nodes.static_codegen_renderer import render_dataset_aware_code
from src.dag_engine.nodes.static_program_compiler import compile_static_program

_STATIC_ARTIFACT_SUFFIXES = {".md", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".csv", ".json", ".tsv"}


def resolve_strategy_family(
    *,
    analysis_mode: str,
    structured_count: int,
    document_count: int,
    has_business_signals: bool = False,
) -> StrategyFamily:
    normalized = str(analysis_mode or "").strip()
    if normalized in {"", "static"}:
        if structured_count and has_business_signals:
            return "hybrid_reconciliation"
        if structured_count:
            return "dataset_profile"
        if document_count or has_business_signals:
            return "document_rule_audit"
        return "input_gap_report"
    if normalized == "document_rule_analysis":
        return "document_rule_audit"
    if normalized == "hybrid_analysis":
        return "hybrid_reconciliation"
    if normalized == "need_more_inputs":
        return "input_gap_report"
    if normalized == "dynamic_research_analysis":
        return "hybrid_reconciliation"
    if normalized == "dataset_analysis":
        return "dataset_profile"
    if structured_count and document_count:
        return "hybrid_reconciliation"
    if document_count and not structured_count:
        return "document_rule_audit"
    if not structured_count and not document_count:
        return "input_gap_report"
    return "legacy_dataset_aware_generator"


def _artifact_spec(
    artifact_key: str,
    file_name: str,
    *,
    category: str,
    required: bool = True,
    summary: str = "",
    description: str = "",
) -> ArtifactSpec:
    return ArtifactSpec(
        artifact_key=artifact_key,
        file_name=file_name,
        category=category,
        artifact_type=category,
        format=Path(file_name).suffix.lstrip("."),
        required=required,
        summary=summary,
        description=description,
    )


def artifact_plan_for_family(strategy_family: StrategyFamily) -> ArtifactPlan:
    required: list[ArtifactSpec]
    optional: list[ArtifactSpec]
    notes: list[str]
    if strategy_family == "dataset_profile":
        required = [
            _artifact_spec("analysis_report", "analysis_report.md", category="report", summary="数据分析报告"),
            _artifact_spec("summary_json", "summary.json", category="export", summary="结构化摘要"),
        ]
        optional = [
            _artifact_spec("comparison_csv", "comparison.csv", category="export", required=False, summary="对比导出"),
        ]
        notes = ["趋势图不是 v1 强制项；优先保证报告与结构化导出稳定生成。"]
    elif strategy_family == "document_rule_audit":
        required = [
            _artifact_spec("rule_audit_report", "rule_audit_report.md", category="report", summary="规则审计报告"),
            _artifact_spec("rule_checks_json", "rule_checks.json", category="export", summary="规则检查结果"),
        ]
        optional = []
        notes = ["文档规则审计以报告和规则检查 JSON 作为最小交付面。"]
    elif strategy_family == "hybrid_reconciliation":
        required = [
            _artifact_spec("analysis_report", "analysis_report.md", category="report", summary="综合分析报告"),
            _artifact_spec(
                "cross_source_findings",
                "cross_source_findings.json",
                category="export",
                summary="跨来源发现",
            ),
            _artifact_spec("comparison_csv", "comparison.csv", category="export", summary="用户导向对比导出"),
        ]
        optional = []
        notes = ["v1 用 comparison.csv 代替更重的图表引擎。"]
    elif strategy_family == "input_gap_report":
        required = [
            _artifact_spec("input_gap_report", "input_gap_report.md", category="report", summary="输入缺口报告"),
        ]
        optional = [
            _artifact_spec(
                "requested_inputs_json",
                "requested_inputs.json",
                category="export",
                required=False,
                summary="补充输入请求",
            ),
        ]
        notes = ["input_gap_report 禁止产伪图表。"]
    else:
        required = [
            _artifact_spec("analysis_report", "analysis_report.md", category="report", summary="兼容报告"),
            _artifact_spec("summary_json", "summary.json", category="export", summary="兼容摘要"),
        ]
        optional = []
        notes = ["legacy fallback 继续使用 dataset-aware renderer，但产出新 artifact contract。"]

    return ensure_artifact_plan(
        {
            "strategy_family": strategy_family,
            "output_root": "/app/outputs",
            "required_artifacts": [item.model_dump(mode="json") for item in required],
            "optional_artifacts": [item.model_dump(mode="json") for item in optional],
            "notes": notes,
        },
        strategy_family=strategy_family,
    )


def verification_plan_for_family(strategy_family: StrategyFamily) -> VerificationPlan:
    prohibited_extensions = [".png", ".jpg", ".jpeg", ".webp"] if strategy_family == "input_gap_report" else []
    artifact_plan = artifact_plan_for_family(strategy_family)
    return ensure_verification_plan(
        {
            "strategy_family": strategy_family,
            "required_artifact_keys": [item.artifact_key for item in artifact_plan.required_artifacts if item.required],
            "prohibited_extensions": prohibited_extensions,
            "allowed_output_roots": [str(Path(OUTPUT_DIR).resolve())],
            "require_declared_filenames": True,
        },
        strategy_family=strategy_family,
    )


def _artifact_writer_snippet() -> str:
    return textwrap.dedent(
        """
        artifact_plan = dict((payload.get("execution_strategy") or {}).get("artifact_plan") or {})
        artifact_specs = list(artifact_plan.get("required_artifacts") or []) + list(artifact_plan.get("optional_artifacts") or [])
        output_root = Path(str(artifact_plan.get("output_root") or "/app/outputs"))
        try:
            output_root.mkdir(parents=True, exist_ok=True)
        except OSError:
            output_root = Path("/tmp/lite_interpreter_artifacts")
            output_root.mkdir(parents=True, exist_ok=True)

        def _artifact_path(file_name):
            return output_root / str(file_name).strip()

        def _write_text_artifact(file_name, content):
            path = _artifact_path(file_name)
            path.write_text(str(content), encoding="utf-8")
            return path

        def _write_json_artifact(file_name, content):
            path = _artifact_path(file_name)
            path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
            return path

        def _write_csv_artifact(file_name, headers, rows):
            path = _artifact_path(file_name)
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=headers)
                writer.writeheader()
                for row in rows:
                    writer.writerow({header: row.get(header, "") for header in headers})
            return path

        def _take_strings(values, limit=8):
            return [str(item).strip() for item in list(values or [])[:limit] if str(item).strip()]

        def _report_lines(title):
            findings = _take_strings(result.get("derived_findings"), limit=12)
            rule_checks = list(result.get("rule_checks") or [])
            metric_checks = list(result.get("metric_checks") or [])
            filter_checks = list(result.get("filter_checks") or [])
            datasets = list(result.get("datasets") or [])
            documents = list(result.get("documents") or [])
            lines = [
                f"# {title}",
                "",
                f"- query: {payload.get('query', '')}",
                f"- analysis_mode: {payload.get('analysis_mode', '')}",
                f"- strategy_family: {(payload.get('execution_strategy') or {}).get('strategy_family', '')}",
                "",
                "## Key Findings",
            ]
            if findings:
                lines.extend([f"- {item}" for item in findings])
            else:
                lines.append("- 暂无结构化发现。")
            lines.extend(
                [
                    "",
                    "## Coverage",
                    f"- datasets: {len(datasets)}",
                    f"- documents: {len(documents)}",
                    f"- rule_checks: {len(rule_checks)}",
                    f"- metric_checks: {len(metric_checks)}",
                    f"- filter_checks: {len(filter_checks)}",
                ]
            )
            if datasets:
                lines.extend(["", "## Datasets"])
                for dataset in datasets[:5]:
                    lines.append(
                        f"- {dataset.get('file_name', 'dataset')}: rows={dataset.get('row_count', 0)}, columns={', '.join((dataset.get('columns') or [])[:6])}"
                    )
            if documents:
                lines.extend(["", "## Documents"])
                for document in documents[:5]:
                    lines.append(
                        f"- {document.get('file_name', 'document')}: keyword_hits={', '.join((document.get('keyword_hits') or [])[:6]) or 'none'}"
                    )
            return "\\n".join(lines) + "\\n"

        def _comparison_rows():
            rows = []
            for dataset in list(result.get("datasets") or [])[:5]:
                for profile in list(dataset.get("numeric_profiles") or [])[:4]:
                    rows.append(
                        {
                            "dataset": dataset.get("file_name", ""),
                            "column": profile.get("column", ""),
                            "mean": profile.get("mean", ""),
                            "min": profile.get("min", ""),
                            "max": profile.get("max", ""),
                        }
                    )
                for summary in list(dataset.get("group_summaries") or [])[:2]:
                    for group_name, group_value, group_count in list(summary.get("top_groups") or [])[:3]:
                        rows.append(
                            {
                                "dataset": dataset.get("file_name", ""),
                                "column": summary.get("group_by", ""),
                                "mean": group_value,
                                "min": group_count,
                                "max": summary.get("measure", ""),
                            }
                        )
            return rows

        def _cross_source_findings():
            findings = []
            for item in _take_strings(result.get("derived_findings"), limit=12):
                findings.append({"kind": "derived_finding", "message": item})
            for check in list(result.get("rule_checks") or [])[:6]:
                findings.append(
                    {
                        "kind": "rule_check",
                        "rule": check.get("rule", ""),
                        "issue_count": check.get("issue_count", 0),
                        "warnings": list(check.get("warnings") or []),
                    }
                )
            return findings

        generated_artifacts = []
        strategy_family = str((payload.get("execution_strategy") or {}).get("strategy_family") or "")

        def _register_artifact(spec, path, summary):
            generated_artifacts.append(
                {
                    "key": spec.get("artifact_key", ""),
                    "name": path.name,
                    "path": str(path),
                    "type": spec.get("artifact_type", spec.get("category", "artifact")),
                    "category": spec.get("category", "diagnostic"),
                    "summary": summary,
                }
            )

        specs_by_key = {str(item.get("artifact_key") or ""): item for item in artifact_specs}
        report_title = "Analysis Report"
        if strategy_family == "document_rule_audit":
            report_title = "Rule Audit Report"
        elif strategy_family == "input_gap_report":
            report_title = "Input Gap Report"

        if "analysis_report" in specs_by_key:
            spec = specs_by_key["analysis_report"]
            path = _write_text_artifact(spec.get("file_name"), _report_lines(report_title))
            _register_artifact(spec, path, spec.get("summary", "analysis report"))
        if "summary_json" in specs_by_key:
            spec = specs_by_key["summary_json"]
            path = _write_json_artifact(
                spec.get("file_name"),
                {
                    "query": payload.get("query", ""),
                    "analysis_mode": payload.get("analysis_mode", ""),
                    "key_findings": _take_strings(result.get("derived_findings"), limit=12),
                    "dataset_count": len(list(result.get("datasets") or [])),
                    "document_count": len(list(result.get("documents") or [])),
                },
            )
            _register_artifact(spec, path, spec.get("summary", "summary json"))
        if "rule_audit_report" in specs_by_key:
            spec = specs_by_key["rule_audit_report"]
            path = _write_text_artifact(spec.get("file_name"), _report_lines(report_title))
            _register_artifact(spec, path, spec.get("summary", "rule audit report"))
        if "rule_checks_json" in specs_by_key:
            spec = specs_by_key["rule_checks_json"]
            path = _write_json_artifact(spec.get("file_name"), list(result.get("rule_checks") or []))
            _register_artifact(spec, path, spec.get("summary", "rule checks"))
        if "cross_source_findings" in specs_by_key:
            spec = specs_by_key["cross_source_findings"]
            path = _write_json_artifact(spec.get("file_name"), _cross_source_findings())
            _register_artifact(spec, path, spec.get("summary", "cross source findings"))
        if "comparison_csv" in specs_by_key:
            spec = specs_by_key["comparison_csv"]
            rows = _comparison_rows()
            if not rows:
                rows = [{"dataset": "", "column": "", "mean": "", "min": "", "max": ""}]
            path = _write_csv_artifact(spec.get("file_name"), ["dataset", "column", "mean", "min", "max"], rows)
            _register_artifact(spec, path, spec.get("summary", "comparison csv"))
        if "input_gap_report" in specs_by_key:
            spec = specs_by_key["input_gap_report"]
            known_gaps = _take_strings((payload.get("analysis_brief") or {}).get("known_gaps"), limit=12)
            if not known_gaps:
                known_gaps = ["当前输入不足以完成稳定分析，请补充结构化数据或规则文档。"]
            report = "\\n".join(
                [
                    "# Input Gap Report",
                    "",
                    "## Missing Inputs",
                    *[f"- {item}" for item in known_gaps],
                    "",
                    "## Suggested Next Step",
                    f"- {(payload.get('analysis_brief') or {}).get('recommended_next_step', '补充输入后重新执行')}",
                    "",
                ]
            )
            path = _write_text_artifact(spec.get("file_name"), report)
            _register_artifact(spec, path, spec.get("summary", "input gap report"))
        if "requested_inputs_json" in specs_by_key:
            spec = specs_by_key["requested_inputs_json"]
            path = _write_json_artifact(
                spec.get("file_name"),
                {
                    "known_gaps": _take_strings((payload.get("analysis_brief") or {}).get("known_gaps"), limit=12),
                    "recommended_next_step": (payload.get("analysis_brief") or {}).get("recommended_next_step", ""),
                },
            )
            _register_artifact(spec, path, spec.get("summary", "requested inputs"))

        result["generated_artifacts"] = generated_artifacts
        result["execution_strategy"] = payload.get("execution_strategy", {})
        result["generator_manifest"] = payload.get("generator_manifest", {})
        print(json.dumps(result, ensure_ascii=False))
        """
    ).strip()


def build_static_program_spec(
    *,
    payload: Mapping[str, Any],
    strategy_family: StrategyFamily,
    research_mode: str,
) -> StaticProgramSpec:
    artifact_plan = artifact_plan_for_family(strategy_family)
    step_kinds = ["load_datasets", "load_documents"]
    if research_mode == "single_pass":
        step_kinds.append("load_evidence")
    if strategy_family in {"document_rule_audit", "hybrid_reconciliation"}:
        step_kinds.append("derive_rule_checks")
    if strategy_family in {"dataset_profile", "hybrid_reconciliation"}:
        step_kinds.append("derive_metric_checks")
        step_kinds.append("derive_filter_checks")
    if strategy_family == "input_gap_report":
        step_kinds.append("emit_input_gap")
    steps = [
        ComputationStep(step_id=f"{strategy_family}:{index}:{kind}", kind=kind)
        for index, kind in enumerate(dict.fromkeys(step_kinds), start=1)
    ]
    emit_specs: list[ArtifactEmitSpec] = []
    emit_kind_by_key = {
        "analysis_report": "analysis_report",
        "summary_json": "summary_json",
        "rule_audit_report": "analysis_report",
        "rule_checks_json": "rule_checks_json",
        "cross_source_findings": "cross_source_findings_json",
        "comparison_csv": "comparison_csv",
        "input_gap_report": "input_gap_report",
        "requested_inputs_json": "requested_inputs_json",
    }
    for spec in [*artifact_plan.required_artifacts, *artifact_plan.optional_artifacts]:
        emit_specs.append(
            ArtifactEmitSpec(
                artifact_key=spec.artifact_key,
                file_name=spec.file_name,
                emit_kind=emit_kind_by_key[spec.artifact_key],
                category=spec.category,
                required=spec.required,
            )
        )
    debug_hints = [
        DebugHint(code="missing_required_artifact", message="检查 artifact emit 列表与 required artifact 是否一致。"),
    ]
    static_evidence_bundle = (
        StaticEvidenceBundle.model_validate(dict(payload.get("static_evidence_bundle") or {}))
        if payload.get("static_evidence_bundle")
        else None
    )
    return ensure_static_program_spec(
        {
            "spec_id": f"{strategy_family}:spec:v1",
            "strategy_family": strategy_family,
            "analysis_mode": str(payload.get("analysis_mode") or ""),
            "research_mode": research_mode,
            "steps": [item.model_dump(mode="json") for item in steps],
            "artifact_emits": [item.model_dump(mode="json") for item in emit_specs],
            "debug_hints": [item.model_dump(mode="json") for item in debug_hints],
            "evidence_bundle": static_evidence_bundle.model_dump(mode="json") if static_evidence_bundle else None,
            "metadata": {
                "input_mount_count": len(list(payload.get("input_mounts") or [])),
                "query": str(payload.get("query") or ""),
            },
        },
        spec_id=f"{strategy_family}:spec:v1",
        strategy_family=strategy_family,
        analysis_mode=str(payload.get("analysis_mode") or ""),
        research_mode=research_mode,
    )


def _inject_artifact_writer(legacy_code: str) -> str:
    final_print = "print(json.dumps(result, ensure_ascii=False))"
    if final_print not in legacy_code:
        return legacy_code
    return legacy_code.replace(final_print, _artifact_writer_snippet())


def build_static_generation_bundle(
    payload: Mapping[str, Any],
    *,
    dynamic_resume_overlay: Mapping[str, Any] | DynamicResumeOverlay | None = None,
    repair_plan: Mapping[str, Any] | None = None,
) -> tuple[str, ExecutionStrategy, GeneratorManifest]:
    existing_strategy_payload = dict(payload.get("execution_strategy") or {})
    analysis_mode = str(payload.get("analysis_mode") or existing_strategy_payload.get("analysis_mode") or "").strip()
    research_mode = str(payload.get("research_mode") or existing_strategy_payload.get("research_mode") or "none").strip() or "none"
    structured_count = len(list(payload.get("structured_dataset_summaries") or []))
    if not structured_count:
        structured_count = len([item for item in list(payload.get("input_mounts") or []) if item.get("kind") == "structured_dataset"])
    document_count = len([item for item in list(payload.get("input_mounts") or []) if item.get("kind") == "business_document"])
    business_context = dict(payload.get("business_context") or {})
    compiled_knowledge = dict(payload.get("compiled_knowledge") or {})
    has_business_signals = bool(
        list(business_context.get("rules") or [])
        or list(business_context.get("metrics") or [])
        or list(business_context.get("filters") or [])
        or list(compiled_knowledge.get("rule_specs") or [])
        or list(compiled_knowledge.get("metric_specs") or [])
        or list(compiled_knowledge.get("filter_specs") or [])
    )
    resolved_strategy_family = resolve_strategy_family(
        analysis_mode=analysis_mode,
        structured_count=structured_count,
        document_count=document_count,
        has_business_signals=has_business_signals,
    )
    existing_strategy_family = str(existing_strategy_payload.get("strategy_family") or "").strip()
    strategy_family = (
        existing_strategy_family
        if existing_strategy_family and existing_strategy_family != "legacy_dataset_aware_generator"
        else resolved_strategy_family
    )
    if repair_plan and str(repair_plan.get("action") or "") == "fallback_to_legacy":
        strategy_family = "legacy_dataset_aware_generator"
    artifact_plan = artifact_plan_for_family(strategy_family)
    verification_plan = verification_plan_for_family(strategy_family)
    resume_overlay = (
        ensure_dynamic_resume_overlay(dynamic_resume_overlay)
        if dynamic_resume_overlay is not None
        else None
    )
    strategy_seed = dict(existing_strategy_payload)
    strategy_seed["analysis_mode"] = analysis_mode
    strategy_seed["research_mode"] = research_mode
    strategy_seed["strategy_family"] = strategy_family
    strategy_seed["generator_id"] = f"{strategy_family}_generator"
    execution_strategy = ensure_execution_strategy(
        strategy_seed,
        analysis_mode=analysis_mode,
        research_mode=research_mode,
        strategy_family=strategy_family,
        generator_id=f"{strategy_family}_generator",
        evidence_plan=existing_strategy_payload.get("evidence_plan"),
        artifact_plan=artifact_plan,
        verification_plan=verification_plan,
        repair_plan=repair_plan,
        resume_overlay=resume_overlay,
        legacy_compatibility={
            "analysis_plan": str(payload.get("analysis_plan") or ""),
            "generation_directives": dict(payload.get("generation_directives") or {}),
            "next_static_steps": list((resume_overlay.next_static_steps if resume_overlay else []) or []),
        },
    )
    expected_keys = [
        *(item.artifact_key for item in artifact_plan.required_artifacts),
        *(item.artifact_key for item in artifact_plan.optional_artifacts),
    ]
    generator_manifest = ensure_generator_manifest(
        generator_id=f"{strategy_family}_generator",
        strategy_family=strategy_family,
        renderer_id="dataset_aware_renderer",
        fallback_used=strategy_family == "legacy_dataset_aware_generator",
        expected_artifact_keys=expected_keys,
        metadata={"analysis_mode": analysis_mode, "research_mode": research_mode},
    )
    enriched_payload = dict(payload)
    enriched_payload["execution_strategy"] = execution_strategy.model_dump(mode="json")
    enriched_payload["generator_manifest"] = generator_manifest.model_dump(mode="json")
    enriched_payload["artifact_plan"] = artifact_plan.model_dump(mode="json")
    enriched_payload["verification_plan"] = verification_plan.model_dump(mode="json")
    if strategy_family == "legacy_dataset_aware_generator":
        legacy_code = render_dataset_aware_code(enriched_payload)
        return _inject_artifact_writer(legacy_code), execution_strategy, generator_manifest
    program_spec = build_static_program_spec(
        payload=enriched_payload,
        strategy_family=strategy_family,
        research_mode=research_mode,
    )
    execution_strategy.program_spec = program_spec
    return compile_static_program(program_spec.model_dump(mode="json"), enriched_payload), execution_strategy, generator_manifest


def verify_generated_artifacts(
    *,
    execution_strategy: ExecutionStrategy | Mapping[str, Any] | None,
    execution_record: ExecutionRecord | Mapping[str, Any] | None,
) -> ArtifactVerificationResult:
    strategy = ensure_execution_strategy(execution_strategy or {})
    verification_plan = ensure_verification_plan(strategy.verification_plan)
    artifact_plan = ensure_artifact_plan(strategy.artifact_plan)
    artifacts = static_artifacts(execution_record)
    artifact_names = {
        Path(str(item.get("path") or "")).name: item
        for item in artifacts
        if str(item.get("path") or "").strip()
    }
    verified_keys: list[str] = []
    missing_keys: list[str] = []
    failure_reasons: list[str] = []
    unexpected_artifacts: list[str] = []

    for spec in artifact_plan.required_artifacts:
        matched = artifact_names.get(spec.file_name)
        if matched and sanitize_artifact_reference(str(matched.get("path") or "")):
            verified_keys.append(spec.artifact_key)
            continue
        missing_keys.append(spec.artifact_key)
        failure_reasons.append(f"missing required artifact: {spec.file_name}")

    declared_file_names = {
        item.file_name
        for item in [*artifact_plan.required_artifacts, *artifact_plan.optional_artifacts]
    }
    for item in artifacts:
        artifact_path = str(item.get("path") or "").strip()
        if not artifact_path:
            continue
        resolved = sanitize_artifact_reference(artifact_path)
        if resolved is None:
            unexpected_artifacts.append(artifact_path)
            failure_reasons.append(f"artifact escaped allowed output roots: {artifact_path}")
            continue
        suffix = Path(artifact_path).suffix.lower()
        if suffix and suffix not in _STATIC_ARTIFACT_SUFFIXES:
            unexpected_artifacts.append(artifact_path)
            failure_reasons.append(f"unexpected artifact suffix for strategy {strategy.strategy_family}: {suffix}")
            continue
        if verification_plan.require_declared_filenames and Path(artifact_path).name not in declared_file_names:
            category = artifact_category_from_path(artifact_path, str(item.get("type") or ""))
            if category in {"report", "chart", "export"}:
                unexpected_artifacts.append(artifact_path)
                failure_reasons.append(f"undeclared user-facing artifact emitted: {Path(artifact_path).name}")
        if suffix in set(verification_plan.prohibited_extensions):
            unexpected_artifacts.append(artifact_path)
            failure_reasons.append(f"prohibited artifact suffix for strategy {strategy.strategy_family}: {suffix}")

    return ensure_artifact_verification_result(
        {
            "strategy_family": strategy.strategy_family,
            "passed": not missing_keys and not unexpected_artifacts and not failure_reasons,
            "verified_artifact_keys": verified_keys,
            "missing_artifact_keys": missing_keys,
            "unexpected_artifacts": unexpected_artifacts,
            "failure_reasons": failure_reasons,
            "debug_hints": [
                {
                    "code": "missing_required_artifact",
                    "message": f"required artifacts missing: {', '.join(missing_keys)}",
                }
                for _ in [0]
                if missing_keys
            ]
            + [
                {
                    "code": "unexpected_artifact",
                    "message": f"unexpected artifacts emitted: {', '.join(unexpected_artifacts)}",
                }
                for _ in [0]
                if unexpected_artifacts
            ],
        },
        strategy_family=strategy.strategy_family,
    )
