"""Harvest reusable skill candidates from static and dynamic execution traces."""

from __future__ import annotations

from typing import Any

from src.blackboard.schema import ExecutionData
from src.common import capability_registry
from src.common.control_plane import (
    decision_allowed_tools,
    execution_intent_dynamic_reason,
    execution_intent_routing_mode,
    static_artifacts,
    task_governance_profile,
)
from src.skillnet.dynamic_skill_adapter import build_dynamic_skill_candidate
from src.skillnet.skill_schema import SkillDescriptor, SkillReplayCase
from src.skillnet.skill_validator import SkillValidator


class SkillHarvester:
    """Turn execution outputs into reusable skill candidates."""

    @staticmethod
    def _required_capabilities(execution_data: ExecutionData, recommended: dict[str, Any]) -> list[str]:
        requested = list(recommended.get("required_capabilities") or [])
        requested.extend(recommended.get("allowed_tools") or [])
        requested.extend(decision_allowed_tools(execution_data.control.decision_log))
        return capability_registry.normalize_names(requested)

    @staticmethod
    def _build_replay_cases(
        execution_data: ExecutionData,
        *,
        required_capabilities: list[str],
    ) -> list[SkillReplayCase]:
        expected_signals = [
            str(item.step_name) for item in execution_data.dynamic.trace[:5] if getattr(item, "step_name", "")
        ]
        if execution_data.dynamic.summary:
            expected_signals.append(str(execution_data.dynamic.summary)[:120])
        case = SkillReplayCase(
            case_id=f"replay_{execution_data.task_id[:8]}",
            description="Replay the harvested dynamic path against a similar query.",
            input_query=(
                str(getattr(execution_data.control, "task_envelope", None).input_query).strip()
                if getattr(execution_data.control, "task_envelope", None)
                and str(getattr(execution_data.control, "task_envelope", None).input_query or "").strip()
                else str(
                    execution_intent_dynamic_reason(execution_data.control.execution_intent)
                    or execution_data.dynamic.summary
                    or execution_data.task_id
                )
            ),
            expected_signals=list(dict.fromkeys(signal for signal in expected_signals if signal)),
            required_capabilities=required_capabilities,
            metadata={
                "routing_mode": execution_intent_routing_mode(execution_data.control.execution_intent),
                "task_id": execution_data.task_id,
            },
        )
        return [case]

    @staticmethod
    def harvest(execution_data: ExecutionData) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []

        if execution_intent_routing_mode(execution_data.control.execution_intent) != "dynamic":
            return candidates

        trace_records = execution_data.dynamic.trace or []
        if not trace_records and execution_data.dynamic.trace_refs:
            trace_records = [
                {
                    "step_name": trace_ref,
                    "event_type": "selected",
                }
                for trace_ref in execution_data.dynamic.trace_refs
            ]

        if not trace_records and not execution_data.dynamic.recommended_static_skill:
            return candidates

        recommended = execution_data.dynamic.recommended_static_skill or {}
        candidate_name = recommended.get("name") or f"dynamic_skill_{execution_data.task_id[:8]}"
        source_task_type = (
            recommended.get("source_task_type")
            or execution_intent_dynamic_reason(execution_data.control.execution_intent)
            or "dynamic_task"
        )
        code_refs = [
            artifact.get("path", "")
            for artifact in static_artifacts(execution_data.static.execution_record)
            if artifact.get("path")
        ]
        code_refs.extend(execution_data.dynamic.artifacts)
        required_capabilities = SkillHarvester._required_capabilities(execution_data, recommended)
        replay_cases = SkillHarvester._build_replay_cases(
            execution_data,
            required_capabilities=required_capabilities,
        )

        candidate = build_dynamic_skill_candidate(
            name=candidate_name,
            source_task_type=source_task_type,
            trace_records=trace_records,
            code_refs=code_refs,
            required_capabilities=required_capabilities,
        ).to_skill_payload()
        candidate["metadata"].update(
            {
                "summary": execution_data.dynamic.summary,
                "recommended": recommended,
                "governance_profile": task_governance_profile(execution_data.control.task_envelope),
            }
        )
        descriptor = SkillDescriptor(
            name=str(candidate["name"]),
            description=str(candidate["metadata"].get("summary") or ""),
            required_capabilities=required_capabilities,
            replay_cases=replay_cases,
            metadata=dict(candidate.get("metadata", {}) or {}),
        )
        candidate["replay_cases"] = [case.model_dump(mode="json") for case in replay_cases]
        candidate["validation"] = SkillValidator.validate(descriptor)
        candidates.append(candidate)
        return candidates
