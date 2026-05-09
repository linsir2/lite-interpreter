"""Strategy-aware static generator registry and artifact-contract verification."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.common.contracts import (
    ArtifactEmitSpec,
    ArtifactVerificationResult,
    ComputationStep,
    DebugHint,
    ExecutionRecord,
    ExecutionStrategy,
    GeneratorManifest,
    StaticEvidenceBundle,
    StaticProgramSpec,
    StrategyFamily,
    _derive_artifact_plan,
)
from src.common.control_plane import (
    artifact_category_from_path,
    ensure_artifact_verification_result,
    ensure_generator_manifest,
    ensure_static_program_spec,
    sanitize_artifact_reference,
    static_artifacts,
)
from src.dag_engine.nodes.static_program_compiler import compile_static_program

_STATIC_ARTIFACT_SUFFIXES = {".md", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".csv", ".json", ".tsv"}


def _build_fallback_program_spec(
    *,
    payload: Mapping[str, Any],
    strategy_family: StrategyFamily,
    research_mode: str,
) -> StaticProgramSpec:
    """Build StaticProgramSpec for the template compiler fallback path."""
    artifact_plan = _derive_artifact_plan(strategy_family)
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


def build_static_generation_bundle(
    payload: Mapping[str, Any],
    *,
    execution_strategy: ExecutionStrategy,
) -> tuple[str, GeneratorManifest, StaticProgramSpec]:
    """Template-based fallback code generator.

    Consumes the analyst's frozen ExecutionStrategy directly — no re-derivation
    of strategy_family.  Only called when LLM codegen fails.
    """
    strategy_family = execution_strategy.strategy_family
    artifact_plan = execution_strategy.artifact_plan

    expected_keys = [
        spec.artifact_key
        for spec in [*artifact_plan.required_artifacts, *artifact_plan.optional_artifacts]
    ]
    generator_manifest = ensure_generator_manifest(
        generator_id=execution_strategy.generator_id,
        strategy_family=strategy_family,
        renderer_id="compiler",
        fallback_used=True,
        expected_artifact_keys=expected_keys,
        metadata={
            "analysis_mode": execution_strategy.analysis_mode,
            "research_mode": execution_strategy.research_mode,
        },
    )
    enriched_payload = dict(payload)
    enriched_payload["generator_manifest"] = generator_manifest.model_dump(mode="json")
    program_spec = _build_fallback_program_spec(
        payload=enriched_payload,
        strategy_family=strategy_family,
        research_mode=execution_strategy.research_mode,
    )
    return (
        compile_static_program(program_spec.model_dump(mode="json"), enriched_payload),
        generator_manifest,
        program_spec,
    )


def verify_generated_artifacts(
    *,
    execution_strategy: ExecutionStrategy | Mapping[str, Any] | None,
    execution_record: ExecutionRecord | Mapping[str, Any] | None,
) -> ArtifactVerificationResult:
    from src.common.control_plane import ensure_execution_strategy

    strategy = ensure_execution_strategy(execution_strategy or {})
    verification_plan = strategy.verification_plan
    artifact_plan = strategy.artifact_plan
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
