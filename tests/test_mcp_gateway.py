"""Tests for the in-process MCP gateway."""
from __future__ import annotations

from src.blackboard import ExecutionData, execution_blackboard
from src.mcp_gateway import MCPClient, default_mcp_server


def test_mcp_server_lists_registered_tools():
    names = [tool["name"] for tool in default_mcp_server.list_tools()]
    assert {"knowledge_query", "sandbox_exec", "state_sync", "dynamic_trace", "skill_auth"}.issubset(set(names))


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
        {"patch": {"dynamic_summary": "synced"}},
        context={"tenant_id": "tenant-mcp", "task_id": "task-mcp"},
    )
    assert patched.dynamic_summary == "synced"
