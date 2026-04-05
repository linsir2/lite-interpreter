"""Validation helpers for harvested skill candidates."""
from __future__ import annotations

from typing import Any

from src.skillnet.skill_schema import SkillDescriptor


class SkillValidator:
    """Run lightweight validation over harvested skills before promotion."""

    @staticmethod
    def validate(skill: SkillDescriptor | dict[str, Any]) -> dict[str, Any]:
        descriptor = skill if isinstance(skill, SkillDescriptor) else SkillDescriptor.from_payload(dict(skill))
        reasons: list[str] = []

        if not descriptor.name.strip():
            reasons.append("skill name is empty")
        if not descriptor.required_capabilities:
            reasons.append("missing required capabilities")
        if not descriptor.replay_cases:
            reasons.append("missing replay cases")
        if descriptor.replay_cases:
            first_case = descriptor.replay_cases[0]
            if not first_case.input_query:
                reasons.append("replay case missing input query")
            if not first_case.expected_signals:
                reasons.append("replay case missing expected signals")

        status = "validated" if not reasons else "needs_review"
        return {
            "status": status,
            "valid": not reasons,
            "reason_count": len(reasons),
            "reasons": reasons,
            "required_capability_count": len(descriptor.required_capabilities),
            "replay_case_count": len(descriptor.replay_cases),
        }
