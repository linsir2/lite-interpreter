"""Adapters for harvesting reusable skills from dynamic swarm traces."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from src.common import capability_registry


@dataclass(frozen=True)
class DynamicSkillCandidate:
    """A normalized candidate skill distilled from a dynamic run."""

    name: str
    source_task_type: str
    winning_steps: list[str] = field(default_factory=list)
    code_refs: list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_skill_payload(self) -> dict[str, Any]:
        return asdict(self)


def build_dynamic_skill_candidate(
    *,
    name: str,
    source_task_type: str,
    trace_records: Sequence[Mapping[str, Any]],
    code_refs: Sequence[str] | None = None,
    required_capabilities: Sequence[str] | None = None,
) -> DynamicSkillCandidate:
    """Summarize successful dynamic traces into a future static skill candidate."""

    normalized_trace_records = [
        record.model_dump(mode="json") if hasattr(record, "model_dump") else dict(record)
        for record in trace_records
    ]
    winning_steps = [
        str(record.get("step_name"))
        for record in normalized_trace_records
        if str(record.get("event_type") or "") in {
            "success",
            "completed",
            "selected",
            "progress",
            "tool_result",
            "artifact",
            "done",
        }
    ]
    metadata = {
        "trace_count": len(normalized_trace_records),
        "source": "dynamic_swarm",
    }
    normalized_capabilities = capability_registry.normalize_names(required_capabilities or [])
    return DynamicSkillCandidate(
        name=name,
        source_task_type=source_task_type,
        winning_steps=winning_steps,
        code_refs=list(code_refs or []),
        required_capabilities=normalized_capabilities,
        metadata=metadata,
    )
