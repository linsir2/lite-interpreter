"""MCP gateway exports."""
from .mcp_client import MCPClient, default_mcp_client
from .mcp_server import MCPToolServer, ToolSpec, default_mcp_server

__all__ = [
    "MCPClient",
    "MCPToolServer",
    "ToolSpec",
    "default_mcp_client",
    "default_mcp_server",
]
