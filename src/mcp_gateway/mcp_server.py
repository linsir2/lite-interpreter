"""In-process MCP-style tool registry for lite-interpreter."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.mcp_gateway.tools.knowledge_query_tool import KnowledgeQueryTool
from src.mcp_gateway.tools.memory_sync_tool import MemorySyncTool
from src.mcp_gateway.tools.sandbox_exec_tool import SandboxExecTool
from src.mcp_gateway.tools.skill_auth_tool import SkillAuthTool
from src.mcp_gateway.tools.state_sync_tool import StateSyncTool

ToolHandler = Callable[[dict[str, Any], dict[str, Any]], Any]


@dataclass(frozen=True)
class ToolSpec:
    """One registered MCP-style tool."""

    name: str
    capability_id: str
    description: str
    handler: ToolHandler

    def metadata(self) -> dict[str, str]:
        return {
            "name": self.name,
            "capability_id": self.capability_id,
            "description": self.description,
        }


class MCPToolServer:
    """Minimal in-process server that exposes existing tools through one registry."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, tool: ToolSpec) -> None:
        self._tools[tool.name] = tool

    def list_tools(self) -> list[dict[str, str]]:
        return [tool.metadata() for tool in sorted(self._tools.values(), key=lambda item: item.name)]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> Any:
        normalized = str(name).strip()
        if normalized not in self._tools:
            raise KeyError(f"Unknown MCP tool: {name}")
        return self._tools[normalized].handler(arguments or {}, context or {})


def _build_default_server() -> MCPToolServer:
    server = MCPToolServer()
    server.register(
        ToolSpec(
            name="knowledge_query",
            capability_id=KnowledgeQueryTool.CAPABILITY_ID,
            description="Run KAG retrieval for the current tenant/workspace.",
            handler=lambda args, ctx: KnowledgeQueryTool.run(
                query=str(args.get("query", "")),
                tenant_id=str(args.get("tenant_id") or ctx.get("tenant_id") or ""),
                workspace_id=str(args.get("workspace_id") or ctx.get("workspace_id") or "default_ws"),
                top_k=int(args.get("top_k", 8)),
            ),
        )
    )
    server.register(
        ToolSpec(
            name="sandbox_exec",
            capability_id=SandboxExecTool.CAPABILITY_ID,
            description="Execute generated Python in the governed local sandbox.",
            handler=lambda args, ctx: SandboxExecTool.run_sync(
                code=str(args.get("code", "")),
                tenant_id=str(args.get("tenant_id") or ctx.get("tenant_id") or ""),
                workspace_id=str(args.get("workspace_id") or ctx.get("workspace_id") or "default_ws"),
                task_id=args.get("task_id") or ctx.get("task_id"),
                # MCP 暴露的是“受治理的沙箱执行”能力，不允许通过参数把 AST 审计关掉。
                # 如果未来确实需要原始/不审计执行面，应该单独暴露一个显式命名的内部工具，
                # 而不是复用同一个 governed capability id。
                use_audit=True,
                input_mounts=list(args.get("input_mounts") or []),
            ),
        )
    )
    server.register(
        ToolSpec(
            name="state_sync",
            capability_id=StateSyncTool.CAPABILITY_ID,
            description="Apply a partial execution-blackboard patch.",
            handler=lambda args, ctx: StateSyncTool.sync_execution_patch(
                str(args.get("tenant_id") or ctx.get("tenant_id") or ""),
                str(args.get("task_id") or ctx.get("task_id") or ""),
                dict(args.get("patch") or {}),
            ),
        )
    )
    server.register(
        ToolSpec(
            name="dynamic_trace",
            capability_id="dynamic_trace",
            description="Append one normalized dynamic trace event.",
            handler=lambda args, ctx: StateSyncTool.append_dynamic_trace_event(
                str(args.get("tenant_id") or ctx.get("tenant_id") or ""),
                str(args.get("task_id") or ctx.get("task_id") or ""),
                dict(args.get("event") or {}),
            ),
        )
    )
    server.register(
        ToolSpec(
            name="memory_sync",
            capability_id=MemorySyncTool.CAPABILITY_ID,
            description="Apply a partial memory-blackboard patch.",
            handler=lambda args, ctx: MemorySyncTool.sync_memory_patch(
                str(args.get("tenant_id") or ctx.get("tenant_id") or ""),
                str(args.get("task_id") or ctx.get("task_id") or ""),
                dict(args.get("patch") or {}),
            ),
        )
    )
    server.register(
        ToolSpec(
            name="skill_auth",
            capability_id=SkillAuthTool.CAPABILITY_ID,
            description="Authorize requested capabilities or a full skill against a profile.",
            handler=lambda args, _ctx: (
                SkillAuthTool.authorize_skill(
                    skill=dict(args.get("skill") or {}),
                    profile_name=str(args.get("profile_name") or "reviewer"),
                )
                if args.get("skill") is not None
                else SkillAuthTool.authorize(
                    requested_capabilities=list(args.get("requested_capabilities") or []),
                    profile_name=str(args.get("profile_name") or "reviewer"),
                )
            ),
        )
    )
    return server


default_mcp_server = _build_default_server()
