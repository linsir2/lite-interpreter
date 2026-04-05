"""Built-in data-cleaning skill seeds."""
from __future__ import annotations

from src.skillnet.skill_schema import SkillDescriptor


def load_data_clean_skills() -> list[SkillDescriptor]:
    return [
        SkillDescriptor(
            name="dataset_profile_and_clean",
            description="Profile a tabular dataset, detect missing values and prepare a cleaning checklist.",
            required_capabilities=["sandbox_exec"],
            promotion={"status": "approved", "ready_for_router": True},
            metadata={"recommended": {"source_task_type": "data_cleaning"}},
        )
    ]
