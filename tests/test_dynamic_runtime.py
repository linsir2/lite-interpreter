"""Tests for dynamic runtime supervision helpers."""

from __future__ import annotations

from unittest.mock import patch

from src.common import ExecutionIntent
from src.dynamic_engine.dynamic_supervisor import DynamicPlan, DynamicSupervisor
from src.dynamic_engine.exploration_loop import (
    ExplorationResult,
    ExplorationStep,
    _parse_final_answer,
    _truncate_result,
    run_exploration_loop,
)
from src.dynamic_engine.trace_normalizer import TraceNormalizer


def test_dynamic_supervisor_prepares_allowed_run_plan():
    plan = DynamicSupervisor.prepare(
        {
            "tenant_id": "tenant-supervisor",
            "task_id": "task-supervisor",
            "workspace_id": "ws-supervisor",
            "input_query": "自己找数据并验证结论",
            "routing_mode": "dynamic",
        },
        {},
    )
    assert plan.governance_decision.allowed is True
    assert plan.execution_intent.intent == "dynamic_flow"
    assert plan.task_envelope.task_id == "task-supervisor"


def test_dynamic_supervisor_builds_denied_patch_for_unknown_tools():
    plan = DynamicSupervisor.prepare(
        {
            "tenant_id": "tenant-denied",
            "task_id": "task-denied",
            "workspace_id": "ws-denied",
            "input_query": "帮我联网调研后执行结果",
            "allowed_tools": ["shell_exec"],
            "routing_mode": "dynamic",
        },
        {},
    )
    denied_patch = plan.denied_patch()
    assert plan.governance_decision.allowed is False
    assert denied_patch["dynamic_status"] == "denied"
    assert denied_patch["dynamic_continuation"] == "finish"
    assert denied_patch["execution_intent"].intent == "dynamic_flow"


def test_dynamic_supervisor_context_uses_knowledge_and_decision_log():
    plan = DynamicSupervisor.prepare(
        {
            "tenant_id": "tenant-context",
            "task_id": "task-context",
            "workspace_id": "ws-context",
            "input_query": "自己找数据并验证结论",
            "routing_mode": "dynamic",
        },
        {
            "knowledge_snapshot": {
                "rewritten_query": "验证 结论",
                "evidence_refs": ["chunk-9"],
            },
            "decision_log": [
                {
                    "action": "dynamic_precheck",
                    "profile": "reviewer",
                    "mode": "standard",
                    "allowed": True,
                    "risk_level": "low",
                    "risk_score": 0.1,
                    "reasons": ["previous decision"],
                    "allowed_tools": ["knowledge_query"],
                }
            ],
        },
    )

    assert plan.context is not None
    assert plan.context["knowledge_snapshot"]["evidence_refs"] == ["chunk-9"]


def test_dynamic_supervisor_prefers_canonical_task_envelope_fields():
    plan = DynamicSupervisor.prepare(
        {
            "tenant_id": "tenant-runtime-inherit",
            "task_id": "task-runtime-inherit",
            "workspace_id": "ws-runtime-inherit",
            "input_query": "分析销售数据并总结趋势",
            "routing_mode": "dynamic",
            "governance_profile": "reviewer",
            "max_dynamic_steps": 5,
        },
        {},
    )

    assert plan.task_envelope.governance_profile == "reviewer"
    assert plan.task_envelope.max_dynamic_steps == 5


def test_dynamic_supervisor_build_context_includes_execution_intent_metadata():
    task_envelope = plan = DynamicSupervisor.prepare(
        {
            "tenant_id": "tenant-meta",
            "task_id": "task-meta",
            "workspace_id": "ws-meta",
            "input_query": "分析销售数据",
            "routing_mode": "dynamic",
        },
        {},
    ).task_envelope

    from src.harness import GovernanceDecision

    ctx = DynamicSupervisor.build_context(
        state={
            "tenant_id": "tenant-meta",
            "task_id": "task-meta",
            "workspace_id": "ws-meta",
            "input_query": "分析销售数据",
        },
        execution_state={},
        task_envelope=task_envelope,
        governance_decision=GovernanceDecision(
            action="dynamic",
            profile="reviewer",
            mode="standard",
            allowed=True,
            risk_level="low",
            risk_score=0.1,
            reasons=["test"],
            allowed_tools=["knowledge_query"],
        ),
    )

    assert ctx["runtime_backend"] == "native"
    assert ctx["routing_mode"] == "dynamic"
    assert "knowledge_query" in ctx["allowed_tools"]


def test_trace_normalizer_enriches_runtime_event():
    normalized = TraceNormalizer.normalize_runtime_event(
        {
            "agent_name": "exploration",
            "step_name": "research",
            "event_type": "completed",
            "payload": {"foo": "bar"},
        }
    )
    assert normalized["source"] == "dynamic"
    assert normalized["step_name"] == "research"
    assert normalized["payload"]["foo"] == "bar"
    assert normalized["event_type"] == "progress"
    assert normalized["source_event_type"] == "completed"


def test_trace_normalizer_maps_ai_message_and_artifact_events_to_v2():
    text_event = TraceNormalizer.normalize_runtime_event(
        {
            "agent_name": "exploration",
            "step_name": "answer",
            "event_type": "messages-tuple",
            "payload": {"type": "ai", "content": "hello"},
        }
    )
    artifact_event = TraceNormalizer.normalize_runtime_event(
        {
            "agent_name": "exploration",
            "step_name": "artifact_step",
            "event_type": "values",
            "payload": {"artifacts": [{"path": "/tmp/report.md"}]},
        }
    )

    assert text_event["event_type"] == "text"
    assert text_event["message"] == "hello"
    assert artifact_event["event_type"] == "artifact"
    assert artifact_event["artifact_refs"] == ["/tmp/report.md"]


def test_trace_normalizer_maps_tool_call_payloads_to_v2():
    start_event = TraceNormalizer.normalize_runtime_event(
        {
            "agent_name": "exploration",
            "step_name": "search_start",
            "event_type": "values",
            "payload": {"tool_name": "web_search", "tool_call_id": "call-1", "arguments": {"q": "lite interpreter"}},
        }
    )
    result_event = TraceNormalizer.normalize_runtime_event(
        {
            "agent_name": "exploration",
            "step_name": "search_result",
            "event_type": "values",
            "payload": {
                "tool_name": "web_search",
                "tool_call_id": "call-1",
                "result": {"items": 3},
                "status": "completed",
            },
        }
    )

    assert start_event["event_type"] == "tool_call_start"
    assert start_event["tool_call"]["tool_name"] == "web_search"
    assert result_event["event_type"] == "tool_result"
    assert result_event["tool_call"]["result"]["items"] == 3


def test_exploration_result_parses_final_answer_sections():
    content = """### Summary
Research complete — found relevant data.

### Open Questions
- Question one remains
- Question two outstanding

### Next Steps
analyst, coder

### Evidence References
- https://example.com/report
- https://data.gov/stats
"""
    structured = _parse_final_answer(content, "resume_static")
    assert structured["open_questions"] == ["Question one remains", "Question two outstanding"]
    assert structured["next_static_steps"] == ["analyst", "coder"]
    assert structured["evidence_refs"] == ["https://example.com/report", "https://data.gov/stats"]
    assert structured["continuation"] == "resume_static"


def test_exploration_result_parses_empty_sections():
    content = """### Summary
Nothing found.
"""
    structured = _parse_final_answer(content, "finish")
    assert structured["open_questions"] == []
    assert structured["next_static_steps"] == []
    assert structured["evidence_refs"] == []


def test_truncate_result_handles_none():
    assert _truncate_result(None) == "(no result)"


def test_truncate_result_handles_long_output():
    long_text = "x" * 3000
    result = _truncate_result({"text": long_text})
    assert len(result) <= 2500
    assert "[truncated" in result


def test_exploration_step_records_tool_results():
    step = ExplorationStep(
        step_index=0,
        tool_name="web_search",
        tool_args={"query": "test"},
        tool_result_summary="Found 3 results",
        success=True,
    )
    assert step.step_index == 0
    assert step.tool_name == "web_search"
    assert step.success is True


def test_exploration_result_to_state_patch_includes_overlay_fields():
    result = ExplorationResult(
        summary="Test summary",
        continuation="finish",
        next_static_steps=["coder"],
        evidence_refs=["https://example.com"],
        open_questions=["Unresolved question"],
        suggested_static_actions=["generate report"],
    )
    patch = result.to_state_patch()
    assert patch["dynamic_status"] == "completed"
    assert patch["dynamic_summary"] == "Test summary"
    assert patch["dynamic_continuation"] == "finish"
    assert "dynamic_resume_overlay" in patch


def test_exploration_loop_no_tools_available_returns_early():
    result = run_exploration_loop(
        query="test query",
        context={},
        allowed_tools=["nonexistent_tool"],
        max_steps=1,
    )
    assert result.summary == "No exploration tools available for this task."
    assert result.continuation == "finish"


def test_exploration_loop_llm_unavailable_returns_gracefully(monkeypatch):
    def fake_completion(**kwargs):
        raise ConnectionError("LLM unavailable")

    monkeypatch.setattr(
        "src.common.llm_client.LiteLLMClient.completion",
        fake_completion,
    )

    # Mock MCP server at the source to provide tools
    def fake_list_tools():
        return [{"name": "web_search", "description": "Search the web"}]

    monkeypatch.setattr(
        "src.mcp_gateway.mcp_server.default_mcp_server",
        type("FakeMCPServer", (), {"list_tools": staticmethod(fake_list_tools)})(),
    )

    result = run_exploration_loop(
        query="test query",
        context={},
        allowed_tools=[],
        max_steps=3,
    )
    assert "LLM unavailable" in result.summary
    assert len(result.trace_events) == 1
    assert result.trace_events[0]["event_type"] == "error"


def test_exploration_loop_llm_returns_final_answer_without_tool_calls(monkeypatch):
    def fake_completion(**kwargs):
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": """### Summary
All done.
### Open Questions
### Next Steps
none
### Evidence References
""",
                    }
                }
            ]
        }

    monkeypatch.setattr(
        "src.common.llm_client.LiteLLMClient.completion",
        fake_completion,
    )

    def fake_list_tools():
        return [{"name": "web_search", "description": "Search the web"}]

    monkeypatch.setattr(
        "src.mcp_gateway.mcp_server.default_mcp_server",
        type("FakeMCPServer", (), {"list_tools": staticmethod(fake_list_tools)})(),
    )

    result = run_exploration_loop(
        query="test query",
        context={},
        allowed_tools=[],
        max_steps=3,
    )
    assert "All done" in result.summary
    assert len(result.steps) == 0  # No tool calls


def test_exploration_loop_step_budget_exhausted_forces_summary(monkeypatch):
    call_count = {"count": 0}

    def fake_completion(**kwargs):
        call_count["count"] += 1
        if call_count["count"] <= 2:  # two calls → two tool-call rounds
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Let me search.",
                            "tool_calls": [
                                {
                                    "id": f"call-{call_count['count']}",
                                    "type": "function",
                                    "function": {
                                        "name": "web_search",
                                        "arguments": '{"query": "test"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        # Third call (budget exhausted) → summary
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "### Summary\nBudget exhausted, here is what I found.\n",
                    }
                }
            ]
        }

    monkeypatch.setattr(
        "src.common.llm_client.LiteLLMClient.completion",
        fake_completion,
    )

    def fake_list_tools():
        return [{"name": "web_search", "description": "Search the web"}]

    def fake_call_tool(name, arguments=None, context=None):
        return {"items": [{"title": "result", "snippet": "data"}]}

    monkeypatch.setattr(
        "src.mcp_gateway.mcp_server.default_mcp_server",
        type(
            "FakeMCPServer",
            (),
            {
                "list_tools": staticmethod(fake_list_tools),
                "call_tool": staticmethod(fake_call_tool),
            },
        )(),
    )

    result = run_exploration_loop(
        query="test query",
        context={},
        allowed_tools=[],
        max_steps=2,
    )
    assert "Budget exhausted" in result.summary
    assert len(result.steps) == 2
    assert result.trace_events[-1]["budget_exhausted"] is True
