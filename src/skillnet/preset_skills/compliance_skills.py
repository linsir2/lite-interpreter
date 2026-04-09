"""Built-in compliance-oriented skill seeds."""

from __future__ import annotations

from src.skillnet.skill_schema import SkillDescriptor


def load_compliance_skills() -> list[SkillDescriptor]:
    return [
        SkillDescriptor(
            name="policy_clause_audit",
            description="Extract policy clauses and check structured outputs against compliance rules.",
            required_capabilities=["knowledge_query"],
            promotion={"status": "approved", "ready_for_router": True},
            metadata={"recommended": {"source_task_type": "compliance_review"}},
        )
    ]
