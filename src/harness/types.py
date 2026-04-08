"""Typed contracts for lite-interpreter's local harness governance layer."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.common.contracts import DecisionRecord


@dataclass(frozen=True)
class GovernanceDecision:
    """A normalized policy decision emitted by the harness layer."""

    action: str
    profile: str
    mode: str
    allowed: bool
    risk_level: str
    risk_score: float
    reasons: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return DecisionRecord(
            action=self.action,
            profile=self.profile,
            mode=self.mode,
            allowed=self.allowed,
            risk_level=self.risk_level,
            risk_score=round(self.risk_score, 4),
            reasons=list(self.reasons),
            allowed_tools=list(self.allowed_tools),
            metadata=dict(self.metadata),
        ).model_dump(mode="json")

    def to_patch(self) -> dict[str, Any]:
        record = self.to_record()
        return {
            "decision_log": [record],
            "governance_trace_ref": self.metadata.get("trace_ref"),
        }
