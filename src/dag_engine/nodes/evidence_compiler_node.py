"""Apply evidence compiler patches onto canonical execution state."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from src.blackboard.execution_blackboard import execution_blackboard
from src.dag_engine.graphstate import DagGraphState
from src.compiler.kag.service import KnowledgeCompilerService
from src.compiler.kag.types import EvidenceCompilationInput


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _unique_hits(existing: list[dict[str, Any]], additions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for item in [*existing, *additions]:
        if not isinstance(item, Mapping):
            continue
        payload = dict(item)
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        if serialized in seen:
            continue
        seen.add(serialized)
        merged.append(payload)
    return merged


def _build_compilation_input(
    *,
    state: DagGraphState,
    source: str,
    execution_data: Any,
) -> EvidenceCompilationInput:
    if source == "static_evidence":
        bundle = execution_data.static.static_evidence_bundle
        records = list(getattr(bundle, "records", None) or [])
        findings: list[str] = []
        artifact_refs: list[str] = []
    else:
        records = []
        overlay = getattr(execution_data.dynamic, "resume_overlay", None)
        findings = _unique_strings(
            [
                *[str(item) for item in list(state.get("dynamic_open_questions") or [])],
                *[str(item) for item in list(overlay.open_questions if overlay else [])],
            ]
        )
        artifact_refs = _unique_strings(
            [
                *[str(item) for item in list(state.get("dynamic_artifacts") or [])],
                *[str(item) for item in list(state.get("dynamic_evidence_refs") or [])],
                *[str(item) for item in list(execution_data.dynamic.artifacts or [])],
                *[str(item) for item in list(overlay.evidence_refs if overlay else [])],
            ]
        )
    return EvidenceCompilationInput(
        source=source,  # type: ignore[arg-type]
        query=str(state.get("input_query") or ""),
        tenant_id=str(state.get("tenant_id") or execution_data.tenant_id),
        workspace_id=str(state.get("workspace_id") or execution_data.workspace_id),
        task_id=str(state.get("task_id") or execution_data.task_id),
        records=records,
        findings=findings,
        artifact_refs=artifact_refs,
    )


def evidence_compiler_node(state: DagGraphState) -> dict[str, Any]:
    tenant_id = str(state["tenant_id"])
    task_id = str(state["task_id"])
    source = str(state.get("evidence_compiler_source") or "static_evidence").strip() or "static_evidence"
    execution_data = execution_blackboard.read(tenant_id, task_id)
    if execution_data is None:
        return {"material_refresh_actions": []}

    patch = KnowledgeCompilerService.compile_external_evidence(
        _build_compilation_input(state=state, source=source, execution_data=execution_data)
    )

    for dataset_state in patch.structured_datasets:
        if any(str(existing.path or "") == dataset_state.path for existing in execution_data.inputs.structured_datasets):
            continue
        execution_data.inputs.structured_datasets.append(dataset_state)

    for document_state in patch.business_documents:
        if any(str(existing.path or "") == document_state.path for existing in execution_data.inputs.business_documents):
            continue
        execution_data.inputs.business_documents.append(document_state)

    business_context = execution_data.knowledge.business_context
    business_context.rules = _unique_strings([*business_context.rules, *patch.business_context_delta.rules])
    business_context.metrics = _unique_strings([*business_context.metrics, *patch.business_context_delta.metrics])
    business_context.filters = _unique_strings([*business_context.filters, *patch.business_context_delta.filters])
    business_context.sources = _unique_strings([*business_context.sources, *patch.business_context_delta.sources])

    knowledge_snapshot = execution_data.knowledge.knowledge_snapshot
    if not knowledge_snapshot.query:
        knowledge_snapshot.query = str(state.get("input_query") or "")
    if not knowledge_snapshot.tenant_id:
        knowledge_snapshot.tenant_id = tenant_id
    if not knowledge_snapshot.workspace_id:
        knowledge_snapshot.workspace_id = str(state.get("workspace_id") or execution_data.workspace_id)
    knowledge_snapshot.hits = _unique_hits(knowledge_snapshot.hits, patch.knowledge_hits)

    # Merge external_knowledge from dynamic resume_overlay (ADR-005 Phase 2)
    overlay = getattr(execution_data.dynamic, "resume_overlay", None)
    ek_list: list[dict[str, Any]] = list(getattr(overlay, "external_knowledge", None) or [])
    if ek_list:
        knowledge_snapshot.hits = _unique_hits(
            knowledge_snapshot.hits,
            [{**ek, "type": f"external_{ek.get('kind', 'finding')}"} for ek in ek_list],
        )

    knowledge_snapshot.evidence_refs = _unique_strings([*knowledge_snapshot.evidence_refs, *patch.evidence_refs])

    execution_blackboard.write(tenant_id, task_id, execution_data)
    execution_blackboard.persist(tenant_id, task_id)
    return {
        "material_refresh_actions": patch.material_refresh_actions,
        "evidence_compiler_diagnostics": patch.diagnostics,
        "knowledge_snapshot": knowledge_snapshot.model_dump(mode="json"),
    }
