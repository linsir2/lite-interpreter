"""Built-in visualization skill seeds."""
from __future__ import annotations

from src.skillnet.skill_schema import SkillDescriptor


def load_visualization_skills() -> list[SkillDescriptor]:
    return [
        SkillDescriptor(
            name="chart_generation_summary",
            description="Produce a chart-oriented analysis summary and emit visualization artifacts from sandbox outputs.",
            required_capabilities=["sandbox_exec"],
            promotion={"status": "approved", "ready_for_router": True},
            metadata={"recommended": {"source_task_type": "visualization"}},
        )
    ]
