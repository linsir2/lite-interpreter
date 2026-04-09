"""Built-in statistics skill seeds."""

from __future__ import annotations

from src.skillnet.skill_schema import SkillDescriptor


def load_stats_skills() -> list[SkillDescriptor]:
    return [
        SkillDescriptor(
            name="summary_stats_check",
            description="Generate descriptive statistics and sanity-check metric definitions against dataset columns.",
            required_capabilities=["knowledge_query", "sandbox_exec"],
            promotion={"status": "approved", "ready_for_router": True},
            metadata={"recommended": {"source_task_type": "statistical_analysis"}},
        )
    ]
