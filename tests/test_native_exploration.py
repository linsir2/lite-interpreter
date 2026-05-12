"""Unit tests for the native exploration loop and DynamicSupervisor."""

from __future__ import annotations

from unittest.mock import patch

from src.common import ExecutionIntent, TaskEnvelope
from src.dynamic_engine.dynamic_supervisor import DynamicPlan, DynamicSupervisor
from src.dynamic_engine.exploration_loop import (
    ExplorationResult,
    ExplorationStep,
    _build_exploration_system_prompt,
    _parse_final_answer,
    _truncate_result,
)
from src.harness import GovernanceDecision


def test_exploration_step_records_single_tool_call():
    step = ExplorationStep(
        step_index=1,
        tool_name="web_search",
        tool_args={"query": "test"},
        tool_result_summary="3 results found",
        rationale="need to search",
        observation="results relevant",
        decision="continue with web_fetch",
        success=True,
    )
    assert step.step_index == 1
    assert step.tool_name == "web_search"
    assert step.success is True


def test_exploration_step_records_failed_call():
    step = ExplorationStep(
        step_index=2,
        tool_name="web_fetch",
        tool_args={"url": "https://bad.example"},
        success=False,
        error="Connection timeout",
    )
    assert step.success is False
    assert step.error == "Connection timeout"


def test_exploration_result_to_state_patch_emits_overlay():
    result = ExplorationResult(
        summary="Research complete",
        continuation="resume_static",
        next_static_steps=["coder"],
        evidence_refs=["https://example.com/data"],
        open_questions=["Revenue by region not found"],
        suggested_static_actions=["Generate regional breakdown chart"],
        findings=[{"source": "web", "key": "market_size", "value": "10B"}],
        steps=[
            ExplorationStep(step_index=0, tool_name="web_search", tool_args={"query": "market"}, success=True),
        ],
    )

    patch_data = result.to_state_patch()
    assert patch_data["dynamic_status"] == "completed"
    assert patch_data["dynamic_continuation"] == "resume_static"
    assert "dynamic_resume_overlay" in patch_data
    overlay = patch_data["dynamic_resume_overlay"]
    assert overlay["continuation"] == "resume_static"
    assert "coder" in overlay["next_static_steps"]


def test_parse_final_answer_extracts_all_sections():
    content = """### Summary
Found key financial data.

### Open Questions
- Q1 revenue not disclosed
- Margin breakdown missing

### Next Steps
coder, evidence_collection

### Evidence References
- https://finance.example.com/q4_report.pdf
"""
    structured = _parse_final_answer(content, "resume_static")
    assert "Q1 revenue not disclosed" in structured["open_questions"]
    assert structured["next_static_steps"] == ["coder", "evidence_collection"]
    assert len(structured["evidence_refs"]) >= 1


def test_parse_final_answer_no_next_steps():
    content = """### Summary
Nothing actionable found.

### Open Questions
- Unknown data source

### Next Steps
none
"""
    structured = _parse_final_answer(content, "finish")
    assert structured["next_static_steps"] == []


def test_truncate_result_preserves_short_text():
    short = {"key": "value"}
    result = _truncate_result(short, max_chars=2000)
    assert "key" in result
    assert "[truncated" not in result


def test_truncate_result_cuts_long_text():
    long = "x" * 5000
    result = _truncate_result({"data": long}, max_chars=100)
    assert "[truncated" in result
    assert len(result) <= 150  # 100 + "[truncated..." overhead


def test_build_system_prompt_includes_tool_descriptions():
    prompt = _build_exploration_system_prompt("- **web_search**(query*): Search\n- **sandbox_exec**(code*): Execute")
    assert "web_search" in prompt
    assert "sandbox_exec" in prompt
    assert "ONE tool" in prompt
    assert "LIGHTWEIGHT temporary computation" in prompt


def test_dynamic_supervisor_prepare_denied_returns_no_context():
    plan = DynamicSupervisor.prepare(
        {
            "tenant_id": "tenant-d",
            "task_id": "task-d",
            "workspace_id": "ws-d",
            "input_query": "test",
            "routing_mode": "dynamic",
            "allowed_tools": ["shell_exec"],
        },
        {},
    )
    assert plan.governance_decision.allowed is False
    assert plan.context is None


def test_dynamic_supervisor_denied_patch_has_correct_fields():
    plan = DynamicSupervisor.prepare(
        {
            "tenant_id": "tenant-d2",
            "task_id": "task-d2",
            "workspace_id": "ws-d2",
            "input_query": "test",
            "routing_mode": "dynamic",
            "allowed_tools": ["shell_exec"],
        },
        {},
    )
    patch = plan.denied_patch()
    assert patch["dynamic_status"] == "denied"
    assert patch["dynamic_continuation"] == "finish"
    assert patch["execution_intent"].intent == "dynamic_flow"


def test_dynamic_plan_is_immutable():
    plan = DynamicSupervisor.prepare(
        {
            "tenant_id": "tenant-i",
            "task_id": "task-i",
            "workspace_id": "ws-i",
            "input_query": "test",
            "routing_mode": "dynamic",
            "allowed_tools": ["web_search"],
        },
        {},
    )
    assert isinstance(plan, DynamicPlan)
    assert isinstance(plan.task_envelope, TaskEnvelope)
    assert isinstance(plan.execution_intent, ExecutionIntent)
    assert isinstance(plan.governance_decision, GovernanceDecision)


def test_dynamic_supervisor_build_task_envelope_defaults():
    envelope = DynamicSupervisor.build_task_envelope(
        {
            "task_id": "task-e",
            "tenant_id": "tenant-e",
            "workspace_id": "ws-e",
            "input_query": "test query",
        }
    )
    assert envelope.task_id == "task-e"
    assert envelope.governance_profile == "researcher"
    assert envelope.metadata.get("runtime_backend") == "native"
