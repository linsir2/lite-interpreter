"""Promotion-state helpers for harvested skills."""
from __future__ import annotations

from typing import Any

from src.skillnet.skill_schema import SkillDescriptor, SkillPromotionStatus


class SkillPromoter:
    """Derive a promotion state from validation and authorization metadata."""

    @staticmethod
    def evaluate(skill: SkillDescriptor | dict[str, Any]) -> dict[str, Any]:
        descriptor = skill if isinstance(skill, SkillDescriptor) else SkillDescriptor.from_payload(dict(skill))
        validation = dict(descriptor.validation or {})
        authorization = dict(descriptor.metadata.get("authorization", {}) or {})
        valid = bool(validation.get("valid"))
        authorized = bool(authorization.get("allowed"))

        if valid and authorized:
            status = SkillPromotionStatus.APPROVED
            summary = "Skill candidate is validated and approved for reuse."
        elif valid:
            status = SkillPromotionStatus.NEEDS_REVIEW
            summary = "Skill candidate is structurally valid but still needs authorization review."
        elif validation:
            status = SkillPromotionStatus.REJECTED
            summary = "Skill candidate failed validation and should not be promoted automatically."
        else:
            status = SkillPromotionStatus.HARVESTED
            summary = "Skill candidate was harvested and awaits validation."

        return {
            "status": status.value,
            "summary": summary,
            "ready_for_router": status == SkillPromotionStatus.APPROVED,
            "provenance": {
                "validation_status": validation.get("status"),
                "authorization_allowed": authorized,
            },
        }
