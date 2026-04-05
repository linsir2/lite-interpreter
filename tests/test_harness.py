"""Tests for the local harness governance layer."""
from __future__ import annotations

from unittest.mock import patch

from src.common import capability_registry
from src.harness import HarnessGovernor
from src.mcp_gateway.tools.skill_auth_tool import SkillAuthTool
from src.mcp_gateway.tools.sandbox_exec_tool import SandboxExecTool
from src.sandbox.docker_executor import _execute_code_in_docker


def test_harness_governor_denies_unknown_dynamic_tools():
    decision = HarnessGovernor.evaluate_dynamic_request(
        query="帮我联网搜索并执行结果",
        requested_tools=["shell_exec"],
        profile_name="researcher",
        trace_ref="trace:test",
    )

    assert decision.allowed is False
    assert decision.risk_level == "high"


def test_harness_governor_resolves_capability_aliases():
    decision = HarnessGovernor.evaluate_dynamic_request(
        query="请帮我检索制度文档",
        requested_tools=["kag_query"],
        profile_name="researcher",
        trace_ref="trace:alias",
    )

    assert decision.allowed is True
    assert decision.allowed_tools == ["knowledge_query"]
    assert decision.metadata["requested_capabilities"] == ["knowledge_query"]


def test_capability_registry_resolves_alias():
    descriptor = capability_registry.get("retrieval_query")
    assert descriptor is not None
    assert descriptor.capability_id == "knowledge_query"


def test_skill_auth_tool_uses_capability_registry():
    result = SkillAuthTool.authorize(
        requested_capabilities=["knowledge_query", "sandbox_execute"],
        profile_name="reviewer",
    )
    assert result["profile"] == "reviewer"
    assert result["allowed"] is False
    assert result["denied_capabilities"] == ["sandbox_exec"]


def test_sandbox_execution_can_be_denied_before_docker():
    result = _execute_code_in_docker("__import__('os').system('ls')", "tenant_safe", "ws")

    assert result["success"] is False
    assert "harness policy" in result["error"]
    assert result["governance"]["allowed"] is False


def test_sandbox_denial_publishes_governance_event_for_task():
    with patch("src.sandbox.execution_reporting.event_bus.publish") as mocked:
        result = _execute_code_in_docker(
            "__import__('os').system('ls')",
            "tenant_safe",
            "ws",
            task_id="task-123",
        )

    assert result["success"] is False
    topics = [call.kwargs["topic"].value for call in mocked.call_args_list]
    assert "ui.task.governance_update" in topics
    assert "ui.task.status_update" in topics


def test_sandbox_exec_tool_honors_use_audit_flag():
    with patch("src.mcp_gateway.tools.sandbox_exec_tool.execute_in_sandbox", return_value={"success": True}) as raw_mock:
        with patch("src.mcp_gateway.tools.sandbox_exec_tool.execute_in_sandbox_with_audit", return_value={"success": False}) as audit_mock:
            SandboxExecTool.run_sync(code="print('x')", tenant_id="tenant_x", use_audit=False)
    assert raw_mock.called
    assert not audit_mock.called
