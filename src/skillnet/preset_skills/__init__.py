"""Preset skill seeds for cold start."""

from .compliance_skills import load_compliance_skills
from .data_clean_skills import load_data_clean_skills
from .stats_skills import load_stats_skills
from .visualization_skills import load_visualization_skills


def load_preset_skills():
    skills = []
    skills.extend(load_compliance_skills())
    skills.extend(load_data_clean_skills())
    skills.extend(load_stats_skills())
    skills.extend(load_visualization_skills())
    return skills


__all__ = [
    "load_compliance_skills",
    "load_data_clean_skills",
    "load_stats_skills",
    "load_visualization_skills",
    "load_preset_skills",
]
