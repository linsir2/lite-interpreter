"""Task-scoped state mutation services for the canonical execution flow."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.schema import (
    AnalysisBriefState,
    DynamicRequestState,
    DynamicResumeOverlay,
    DynamicTraceEventState,
    ExecutionData,
    KnowledgeSnapshotState,
    RuntimeMetadataState,
)


class ExecutionStateService:
    """Own writes to execution-domain task state."""

    @staticmethod
    def load(tenant_id: str, task_id: str) -> ExecutionData:
        execution_data = execution_blackboard.read(tenant_id, task_id)
        if execution_data is None and execution_blackboard.restore(tenant_id, task_id):
            execution_data = execution_blackboard.read(tenant_id, task_id)
        if execution_data is None:
            raise ValueError(f"missing execution state for task {task_id}")
        return execution_data

    @staticmethod
    def persist(execution_data: ExecutionData) -> ExecutionData:
        execution_blackboard.write(execution_data.tenant_id, execution_data.task_id, execution_data)
        execution_blackboard.persist(execution_data.tenant_id, execution_data.task_id)
        return execution_data

    @classmethod
    def update_control(
        cls,
        *,
        tenant_id: str,
        task_id: str,
        task_envelope: Any | None = None,
        execution_intent: Any | None = None,
        decision_log: list[dict[str, Any]] | None = None,
        governance_trace_ref: str | None = None,
    ) -> ExecutionData:
        execution_data = cls.load(tenant_id, task_id)
        if task_envelope is not None:
            execution_data.control.task_envelope = task_envelope
        if execution_intent is not None:
            execution_data.control.execution_intent = execution_intent
        if decision_log is not None:
            execution_data.control.decision_log = list(decision_log)
        if governance_trace_ref is not None:
            execution_data.control.governance_trace_ref = governance_trace_ref
        return cls.persist(execution_data)

    @classmethod
    def update_dynamic(
        cls,
        *,
        tenant_id: str,
        task_id: str,
        request: Mapping[str, Any] | None = None,
        runtime_backend: str | None = None,
        status: str | None = None,
        summary: str | None = None,
        continuation: str | None = None,
        resume_overlay: Mapping[str, Any] | DynamicResumeOverlay | None = None,
        next_static_steps: list[str] | None = None,
        runtime_metadata: Mapping[str, Any] | RuntimeMetadataState | None = None,
        trace: list[Mapping[str, Any]] | None = None,
        trace_refs: list[str] | None = None,
        artifacts: list[str] | None = None,
        research_findings: list[str] | None = None,
        evidence_refs: list[str] | None = None,
        open_questions: list[str] | None = None,
        suggested_static_actions: list[str] | None = None,
        recommended_static_skill: dict[str, Any] | None = None,
    ) -> ExecutionData:
        execution_data = cls.load(tenant_id, task_id)
        if request is not None:
            execution_data.dynamic.request = (
                request
                if isinstance(request, DynamicRequestState)
                else DynamicRequestState.model_validate(dict(request))
            )
        if runtime_backend is not None:
            execution_data.dynamic.runtime_backend = runtime_backend
        if status is not None:
            execution_data.dynamic.status = status
        if summary is not None:
            execution_data.dynamic.summary = summary
        if continuation is not None:
            execution_data.dynamic.continuation = continuation
        if resume_overlay is not None:
            execution_data.dynamic.resume_overlay = (
                resume_overlay
                if isinstance(resume_overlay, DynamicResumeOverlay)
                else DynamicResumeOverlay.model_validate(dict(resume_overlay))
            )
        if next_static_steps is not None:
            execution_data.dynamic.next_static_steps = list(next_static_steps)
        if runtime_metadata is not None:
            execution_data.dynamic.runtime_metadata = (
                runtime_metadata
                if isinstance(runtime_metadata, RuntimeMetadataState)
                else RuntimeMetadataState.model_validate(dict(runtime_metadata))
            )
        if trace is not None:
            execution_data.dynamic.trace = [
                item
                if isinstance(item, DynamicTraceEventState)
                else DynamicTraceEventState.model_validate(dict(item))
                for item in trace
            ]
        if trace_refs is not None:
            execution_data.dynamic.trace_refs = list(trace_refs)
        if artifacts is not None:
            execution_data.dynamic.artifacts = list(artifacts)
        if research_findings is not None:
            execution_data.dynamic.research_findings = list(research_findings)
        if evidence_refs is not None:
            execution_data.dynamic.evidence_refs = list(evidence_refs)
        if open_questions is not None:
            execution_data.dynamic.open_questions = list(open_questions)
        if suggested_static_actions is not None:
            execution_data.dynamic.suggested_static_actions = list(suggested_static_actions)
        if recommended_static_skill is not None:
            execution_data.dynamic.recommended_static_skill = dict(recommended_static_skill)
        return cls.persist(execution_data)

    @classmethod
    def append_dynamic_trace_event(
        cls,
        *,
        tenant_id: str,
        task_id: str,
        event: Mapping[str, Any],
    ) -> ExecutionData:
        execution_data = cls.load(tenant_id, task_id)
        execution_data.dynamic.trace.append(DynamicTraceEventState.model_validate(dict(event)))
        return cls.persist(execution_data)


class KnowledgeStateService:
    """Own writes to knowledge-domain task state."""

    @staticmethod
    def load(tenant_id: str, task_id: str) -> ExecutionData:
        return ExecutionStateService.load(tenant_id, task_id)

    @classmethod
    def update_snapshot_and_brief(
        cls,
        *,
        tenant_id: str,
        task_id: str,
        knowledge_snapshot: Mapping[str, Any] | KnowledgeSnapshotState,
        analysis_brief: Mapping[str, Any] | AnalysisBriefState | None = None,
    ) -> ExecutionData:
        execution_data = cls.load(tenant_id, task_id)
        execution_data.knowledge.knowledge_snapshot = (
            knowledge_snapshot
            if isinstance(knowledge_snapshot, KnowledgeSnapshotState)
            else KnowledgeSnapshotState.model_validate(dict(knowledge_snapshot))
        )
        if analysis_brief is not None:
            execution_data.knowledge.analysis_brief = (
                analysis_brief
                if isinstance(analysis_brief, AnalysisBriefState)
                else AnalysisBriefState.model_validate(dict(analysis_brief))
            )
        return ExecutionStateService.persist(execution_data)
