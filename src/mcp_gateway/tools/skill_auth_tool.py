"""Skill authorization helpers backed by the capability registry."""
from __future__ import annotations

from typing import Any, Dict, Iterable

from src.common import capability_registry
from src.harness import get_profile
from src.skillnet.skill_schema import SkillDescriptor


class SkillAuthTool:
    """Validate requested skill/admin capabilities against a profile."""

    CAPABILITY_ID = "skill_admin"

    @staticmethod
    def authorize(
        *,
        requested_capabilities: Iterable[str],
        profile_name: str = "reviewer",
    ) -> Dict[str, Any]:
        resolved_profile, profile, _ = get_profile(profile_name)
        allowed, _ = capability_registry.resolve_names(profile.get("allowed_tools"))
        allowed_ids = {descriptor.capability_id for descriptor in allowed}
        requested, unknown = capability_registry.resolve_names(requested_capabilities)
        requested_ids = [descriptor.capability_id for descriptor in requested]
        denied = [capability_id for capability_id in requested_ids if capability_id not in allowed_ids]
        return {
            "profile": resolved_profile,
            "allowed": not denied and not unknown,
            "requested_capabilities": requested_ids,
            "denied_capabilities": denied,
            "unknown_capabilities": unknown,
        }

    @staticmethod
    def authorize_skill(
        *,
        skill: SkillDescriptor | dict[str, object],
        profile_name: str = "reviewer",
    ) -> Dict[str, Any]:
        descriptor = skill if isinstance(skill, SkillDescriptor) else SkillDescriptor.from_payload(dict(skill))
        result = SkillAuthTool.authorize(
            requested_capabilities=descriptor.required_capabilities,
            profile_name=profile_name,
        )
        result["skill_name"] = descriptor.name
        return result
