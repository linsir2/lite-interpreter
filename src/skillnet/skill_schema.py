"""Skill schema models used by SkillNet and capability-aware governance."""
from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field


class SkillPromotionStatus(str, Enum):
    HARVESTED = "harvested"
    VALIDATED = "validated"
    APPROVED = "approved"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class SkillReplayCase(BaseModel):
    """Minimal replay case distilled from a successful execution path."""

    case_id: str
    description: str = ""
    input_query: str = ""
    expected_signals: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class SkillDescriptor(BaseModel):
    """Minimal stable shape for registered or harvested skills."""

    name: str
    description: str = ""
    required_capabilities: list[str] = Field(default_factory=list)
    replay_cases: list[SkillReplayCase] = Field(default_factory=list)
    validation: dict[str, object] = Field(default_factory=dict)
    promotion: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> "SkillDescriptor":
        metadata = dict(payload.get("metadata", {}) or {})
        description = str(payload.get("description") or metadata.get("summary") or "")
        return cls(
            name=str(payload.get("name") or "unnamed_skill"),
            description=description,
            required_capabilities=list(payload.get("required_capabilities") or []),
            replay_cases=[
                SkillReplayCase.model_validate(case)
                for case in list(payload.get("replay_cases") or [])
                if isinstance(case, dict)
            ],
            validation=dict(payload.get("validation", {}) or {}),
            promotion=dict(payload.get("promotion", {}) or {}),
            metadata=metadata,
        )

    def to_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json")
