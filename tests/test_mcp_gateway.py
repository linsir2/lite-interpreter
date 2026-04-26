"""Tests for the in-process MCP gateway."""

from __future__ import annotations

from unittest.mock import patch

from src.blackboard import ExecutionData, execution_blackboard
from src.mcp_gateway import MCPClient, default_mcp_server


def test_mcp_server_lists_registered_tools():
    names = [tool["name"] for tool in default_mcp_server.list_tools()]
    assert {"knowledge_query", "sandbox_exec", "dynamic_trace", "memory_sync", "skill_auth", "web_search", "web_fetch"}.issubset(
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


class _FakeHttpResponse:
    def __init__(self, *, url: str, text: str = "", content_type: str = "text/html", json_data: dict | None = None):
        self.url = url
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = 200
        self.headers = {"content-type": content_type}
        self._json_data = json_data

    def raise_for_status(self):
        return None

    def json(self):
        return self._json_data or {}


def test_mcp_client_can_call_web_fetch():
    client = MCPClient()
    with patch(
        "src.mcp_gateway.tools.web_fetch_tool.httpx.Client.get",
        return_value=_FakeHttpResponse(url="http://127.0.0.1/test", text='{"value": 1}', content_type="application/json"),
    ):
        result = client.call_tool(
            "web_fetch",
            {"url": "http://127.0.0.1/test", "allowlist": ["127.0.0.1"]},
        )

    assert result["domain"] == "127.0.0.1"
    assert result["json"] == {"value": 1}


def test_mcp_client_can_call_web_search():
    client = MCPClient()
    with (
        patch(
            "src.mcp_gateway.tools.web_fetch_tool.TAVILY_API_KEY",
            "test-tavily-key",
        ),
        patch(
            "src.mcp_gateway.tools.web_fetch_tool.httpx.Client.post",
            return_value=_FakeHttpResponse(
                url="https://api.tavily.com/search",
                json_data={
                    "results": [
                        {"title": "Industry report", "url": "https://example.com/report", "content": "Average growth is 12%"},
                    ],
                },
            ),
        ),
    ):
        result = client.call_tool(
            "web_search",
            {"query": "industry growth", "allowlist": ["example.com"], "limit": 1},
        )

    assert result["query"] == "industry growth"
    assert result["provider"] == "tavily"
    assert result["items"][0]["title"] == "Industry report"
    assert result["items"][0]["url"] == "https://example.com/report"
