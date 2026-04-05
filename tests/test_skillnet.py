"""SkillNet capability-aware harvesting tests."""
from __future__ import annotations

from src.blackboard.schema import ExecutionData
from src.mcp_gateway.tools.skill_auth_tool import SkillAuthTool
from src.skillnet.dynamic_skill_adapter import build_dynamic_skill_candidate
from src.skillnet.skill_harvester import SkillHarvester
from src.skillnet.skill_promoter import SkillPromoter
from src.skillnet.skill_retriever import SkillRetriever
from src.skillnet.skill_schema import SkillDescriptor, SkillPromotionStatus
from src.skillnet.skill_validator import SkillValidator
from src.storage.repository.skill_repo import SkillRepo


def test_dynamic_skill_candidate_normalizes_required_capabilities():
    candidate = build_dynamic_skill_candidate(
        name="dynamic_skill_demo",
        source_task_type="dynamic_task",
        trace_records=[{"step_name": "research", "event_type": "completed"}],
        required_capabilities=["retrieval_query", "sandbox_execute"],
    )
    assert candidate.required_capabilities == ["knowledge_query", "sandbox_exec"]


def test_skill_harvester_derives_required_capabilities_from_governance():
    execution_data = ExecutionData(
        task_id="task-skill",
        tenant_id="tenant-skill",
        routing_mode="dynamic",
        dynamic_summary="done",
        dynamic_trace=[{"step_name": "research", "event_type": "completed"}],
        governance_profile="researcher",
        governance_decisions=[
            {
                "allowed_tools": ["knowledge_query", "web_search"],
            }
        ],
    )
    harvested = SkillHarvester.harvest(execution_data)
    assert harvested
    assert harvested[0]["required_capabilities"] == ["knowledge_query", "web_search"]
    assert harvested[0]["replay_cases"][0]["expected_signals"]
    assert harvested[0]["validation"]["valid"] is True


def test_skill_descriptor_round_trip_payload():
    descriptor = SkillDescriptor(
        name="skill_demo",
        description="demo",
        required_capabilities=["knowledge_query"],
        metadata={"summary": "demo"},
    )
    payload = descriptor.to_payload()
    restored = SkillDescriptor.from_payload(payload)
    assert restored.name == "skill_demo"
    assert restored.required_capabilities == ["knowledge_query"]


def test_skill_auth_tool_authorize_skill_uses_required_capabilities():
    result = SkillAuthTool.authorize_skill(
        skill=SkillDescriptor(
            name="skill_demo",
            required_capabilities=["knowledge_query", "sandbox_exec"],
        ),
        profile_name="reviewer",
    )
    assert result["skill_name"] == "skill_demo"
    assert result["allowed"] is False
    assert result["denied_capabilities"] == ["sandbox_exec"]


def test_skill_validator_marks_missing_capabilities_for_review():
    result = SkillValidator.validate(
        SkillDescriptor(
            name="skill_demo",
            required_capabilities=[],
        )
    )
    assert result["valid"] is False
    assert "missing required capabilities" in result["reasons"]


def test_skill_retriever_filters_by_available_capabilities():
    matches = SkillRetriever.filter_by_capabilities(
        [
            SkillDescriptor(name="skill_a", required_capabilities=["knowledge_query"]),
            SkillDescriptor(name="skill_b", required_capabilities=["sandbox_exec"]),
        ],
        available_capabilities=["retrieval_query", "state_sync"],
    )
    assert [skill.name for skill in matches] == ["skill_a"]


def test_skill_promoter_marks_valid_and_authorized_skill_as_approved():
    promotion = SkillPromoter.evaluate(
        SkillDescriptor(
            name="skill_a",
            required_capabilities=["knowledge_query"],
            replay_cases=[],
            validation={"valid": True},
            metadata={"authorization": {"allowed": True}},
        )
    )
    assert promotion["status"] == SkillPromotionStatus.APPROVED.value
    assert promotion["ready_for_router"] is True


def test_skill_retriever_filters_approved_skills():
    skills = SkillRetriever.filter_approved(
        [
            SkillDescriptor(name="approved", promotion={"status": "approved"}),
            SkillDescriptor(name="review", promotion={"status": "needs_review"}),
        ]
    )
    assert [skill.name for skill in skills] == ["approved"]


def test_skill_promoter_adds_provenance():
    promotion = SkillPromoter.evaluate(
        SkillDescriptor(
            name="skill_a",
            validation={"valid": True, "status": "validated"},
            metadata={"authorization": {"allowed": True}},
        )
    )
    assert promotion["provenance"]["validation_status"] == "validated"
    assert promotion["provenance"]["authorization_allowed"] is True


def test_skill_repo_round_trip_in_memory():
    SkillRepo.clear()
    SkillRepo.save_approved_skills(
        "tenant_repo",
        "ws_repo",
        [{"name": "skill_repo_demo", "promotion": {"status": "approved"}}],
    )
    skills = SkillRepo.list_approved_skills("tenant_repo", "ws_repo")
    assert skills[0]["name"] == "skill_repo_demo"


def test_skill_repo_find_approved_skills_filters_by_capability():
    SkillRepo.clear()
    SkillRepo.save_approved_skills(
        "tenant_repo_filter",
        "ws_repo_filter",
        [
            {"name": "skill_query", "required_capabilities": ["knowledge_query"], "promotion": {"status": "approved"}},
            {"name": "skill_exec", "required_capabilities": ["sandbox_exec"], "promotion": {"status": "approved"}},
        ],
    )
    skills = SkillRepo.find_approved_skills(
        "tenant_repo_filter",
        "ws_repo_filter",
        required_capabilities=["knowledge_query"],
    )
    assert [skill["name"] for skill in skills] == ["skill_query"]


def test_skill_repo_records_usage_in_memory():
    SkillRepo.clear()
    SkillRepo.save_approved_skills(
        "tenant_repo_usage",
        "ws_repo_usage",
        [{"name": "skill_usage_demo", "required_capabilities": ["knowledge_query"], "promotion": {"status": "approved"}}],
    )
    SkillRepo.record_skill_usage(
        "tenant_repo_usage",
        "ws_repo_usage",
        "skill_usage_demo",
        task_id="task-usage",
        stage="router",
    )
    skill = SkillRepo.list_approved_skills("tenant_repo_usage", "ws_repo_usage")[0]
    assert skill["usage"]["usage_count"] == 1
    assert skill["usage"]["last_task_id"] == "task-usage"


def test_skill_repo_records_outcome_in_memory():
    SkillRepo.clear()
    SkillRepo.save_approved_skills(
        "tenant_repo_outcome",
        "ws_repo_outcome",
        [{"name": "skill_outcome_demo", "required_capabilities": ["knowledge_query"], "promotion": {"status": "approved"}}],
    )
    SkillRepo.record_skill_outcome(
        "tenant_repo_outcome",
        "ws_repo_outcome",
        "skill_outcome_demo",
        task_id="task-outcome",
        success=True,
    )
    skill = SkillRepo.list_approved_skills("tenant_repo_outcome", "ws_repo_outcome")[0]
    assert skill["usage"]["success_count"] == 1
    assert skill["usage"]["failure_count"] == 0
    assert skill["usage"]["success_rate"] == 1.0
