"""Thin client wrapper around the in-process MCP-style tool server."""

from __future__ import annotations

from typing import Any

from src.mcp_gateway.mcp_server import MCPToolServer, default_mcp_server


class MCPClient:
    """Small client used by DAG/runtime nodes to call registered tools."""

    def __init__(self, server: MCPToolServer | None = None) -> None:
        self._server = server or default_mcp_server

    def list_tools(self) -> list[dict[str, str]]:
        return self._server.list_tools()

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        context: dict[str, Any] | None = None,
    ) -> Any:
        return self._server.call_tool(name, arguments, context)


default_mcp_client = MCPClient()
