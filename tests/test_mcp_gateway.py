"""Tests for the in-process MCP gateway."""

from __future__ import annotations

from unittest.mock import patch

from src.blackboard import ExecutionData, execution_blackboard
from src.mcp_gateway import MCPClient, default_mcp_server


def test_mcp_server_lists_registered_tools():
    names = [tool["name"] for tool in default_mcp_server.list_tools()]
    assert {"knowledge_query", "sandbox_exec", "state_sync", "dynamic_trace", "memory_sync", "skill_auth"}.issubset(
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


def test_mcp_client_can_apply_state_sync_patch():
    execution_blackboard.write(
        "tenant-mcp",
        "task-mcp",
        ExecutionData(task_id="task-mcp", tenant_id="tenant-mcp", workspace_id="ws-mcp"),
    )
    client = MCPClient()
    patched = client.call_tool(
        "state_sync",
        {"patch": {"dynamic": {"summary": "synced"}}},
        context={"tenant_id": "tenant-mcp", "task_id": "task-mcp"},
    )
    assert patched.dynamic.summary == "synced"


def test_mcp_client_state_sync_restores_execution_state_before_patch():
    execution_blackboard.write(
        "tenant-mcp-restore",
        "task-mcp-restore",
        ExecutionData(
            task_id="task-mcp-restore",
            tenant_id="tenant-mcp-restore",
            workspace_id="ws-mcp-restore",
            static={"analysis_plan": "keep-me"},
            control={"final_response": {"headline": "keep-me"}},
        ),
    )
    execution_blackboard.persist("tenant-mcp-restore", "task-mcp-restore")
    execution_blackboard._storage.clear()

    client = MCPClient()
    patched = client.call_tool(
        "state_sync",
        {"patch": {"dynamic": {"summary": "synced"}}},
        context={"tenant_id": "tenant-mcp-restore", "task_id": "task-mcp-restore"},
    )

    assert patched.static.analysis_plan == "keep-me"
    assert patched.control.final_response == {"headline": "keep-me"}
    assert patched.dynamic.summary == "synced"


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
