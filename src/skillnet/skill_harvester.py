"""Harvest reusable skill candidates from static and dynamic execution traces."""
from __future__ import annotations

from typing import Any, Dict, List

from src.common import capability_registry
from src.blackboard.schema import ExecutionData
from src.skillnet.dynamic_skill_adapter import build_dynamic_skill_candidate
from src.skillnet.skill_schema import SkillDescriptor, SkillReplayCase
from src.skillnet.skill_validator import SkillValidator


class SkillHarvester:
    """Turn execution outputs into reusable skill candidates."""

    @staticmethod
    def _required_capabilities(execution_data: ExecutionData, recommended: Dict[str, Any]) -> list[str]:
        requested = list(recommended.get("required_capabilities") or [])
        requested.extend(recommended.get("allowed_tools") or [])
        for decision in execution_data.governance_decisions[-3:]:
            requested.extend(decision.get("allowed_tools", []) or [])
        return capability_registry.normalize_names(requested)

    @staticmethod
    def _build_replay_cases(
        execution_data: ExecutionData,
        *,
        required_capabilities: list[str],
    ) -> list[SkillReplayCase]:
        expected_signals = [
            str(item.get("step_name"))
            for item in execution_data.dynamic_trace[:5]
            if isinstance(item, dict) and item.get("step_name")
        ]
        if execution_data.dynamic_summary:
            expected_signals.append(str(execution_data.dynamic_summary)[:120])
        case = SkillReplayCase(
            case_id=f"replay_{execution_data.task_id[:8]}",
            description="Replay the harvested dynamic path against a similar query.",
            input_query=(
                str(getattr(execution_data, "task_envelope", None).input_query)
                if getattr(execution_data, "task_envelope", None)
                else str(execution_data.dynamic_reason or execution_data.dynamic_summary or execution_data.task_id)
            ),
            expected_signals=list(dict.fromkeys(signal for signal in expected_signals if signal)),
            required_capabilities=required_capabilities,
            metadata={
                "routing_mode": execution_data.routing_mode,
                "task_id": execution_data.task_id,
            },
        )
        return [case]

    @staticmethod
    def harvest(execution_data: ExecutionData) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []

        if execution_data.routing_mode != "dynamic":
            return candidates

        trace_records = execution_data.dynamic_trace or []
        if not trace_records and execution_data.dynamic_trace_refs:
            trace_records = [
                {
                    "step_name": trace_ref,
                    "event_type": "selected",
                }
                for trace_ref in execution_data.dynamic_trace_refs
            ]

        if not trace_records and not execution_data.recommended_static_skill:
            return candidates

        recommended = execution_data.recommended_static_skill or {}
        candidate_name = recommended.get("name") or f"dynamic_skill_{execution_data.task_id[:8]}"
        source_task_type = recommended.get("source_task_type") or execution_data.dynamic_reason or "dynamic_task"
        code_refs = [artifact.get("path", "") for artifact in execution_data.artifacts if artifact.get("path")]
        code_refs.extend(execution_data.dynamic_artifacts)
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
                "summary": execution_data.dynamic_summary,
                "recommended": recommended,
                "governance_profile": execution_data.governance_profile,
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
