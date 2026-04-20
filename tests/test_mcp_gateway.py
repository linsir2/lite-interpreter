"""Tests for the in-process MCP gateway."""

from __future__ import annotations

from unittest.mock import patch

from src.blackboard import ExecutionData, execution_blackboard
from src.mcp_gateway import MCPClient, default_mcp_server


def test_mcp_server_lists_registered_tools():
    names = [tool["name"] for tool in default_mcp_server.list_tools()]
    assert {"knowledge_query", "sandbox_exec", "dynamic_trace", "memory_sync", "skill_auth"}.issubset(
        set(names)
    )


def test_mcp_client_can_call_skill_auth():
    client = MCPClient()
    result = client.call_tool(
        "skill_auth",
        {
            "requested_capabilities": ["knowledge_query"],
            "profile_name": "reviewer",
        },
    )
    assert result["allowed"] is True
    assert result["requested_capabilities"] == ["knowledge_query"]


def test_mcp_client_can_append_dynamic_trace():
    execution_blackboard.write(
        "tenant-mcp",
        "task-mcp",
        ExecutionData(task_id="task-mcp", tenant_id="tenant-mcp", workspace_id="ws-mcp"),
    )
    client = MCPClient()
    patched = client.call_tool(
        "dynamic_trace",
        {"event": {"event_type": "progress", "agent_name": "runtime", "step_name": "sync", "payload": {}}},
        context={"tenant_id": "tenant-mcp", "task_id": "task-mcp"},
    )
    assert len(patched.dynamic.trace) == 1


def test_mcp_sandbox_exec_forces_ast_audit_even_if_caller_disables_it():
    with patch(
        "src.mcp_gateway.tools.sandbox_exec_tool.execute_in_sandbox", return_value={"success": True}
    ) as raw_mock:
        with patch(
            "src.mcp_gateway.tools.sandbox_exec_tool.execute_in_sandbox_with_audit", return_value={"success": False}
        ) as audit_mock:
            default_mcp_server.call_tool(
                "sandbox_exec",
                {"code": "print('x')", "tenant_id": "tenant_mcp", "use_audit": False},
            )

    assert audit_mock.called
    assert not raw_mock.called
