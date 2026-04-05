"""Minimal API application for task streaming and local health checks."""
from __future__ import annotations

from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route

from src.api.routers.diagnostics_router import get_conformance, get_diagnostics
from src.api.routers.execution_router import (
    get_execution,
    list_execution_artifacts,
    list_execution_tool_calls,
    list_task_executions,
    stream_execution_events,
)
from src.api.routers.analysis_router import create_task, get_task_result, recover_unfinished_tasks
from src.api.routers.runtime_router import get_runtime_capabilities, list_runtimes
from src.api.routers.sse_router import stream_task_events, trigger_demo_trace
from src.api.routers.upload_router import list_knowledge_assets, list_workspace_skills, upload_asset
from src.common import event_bus
from src.sandbox.docker_executor import start_zombie_cleaner_daemon
from src.sandbox.runtime_state import close_docker_client
from src.storage.repository.knowledge_repo import KnowledgeRepo


async def health(_request):
    return JSONResponse({"status": "ok", "service": "lite-interpreter-api"})


@asynccontextmanager
async def app_lifespan(app: Starlette):
    start_zombie_cleaner_daemon()
    try:
        app.state.recovered_task_ids = await recover_unfinished_tasks()
        app.state.recovery_error = None
    except Exception as exc:  # pragma: no cover - startup best effort
        app.state.recovered_task_ids = []
        app.state.recovery_error = str(exc)
    try:
        yield
    finally:
        event_bus.stop()
        KnowledgeRepo.close_all_connections()
        close_docker_client()


app = Starlette(
    debug=False,
    lifespan=app_lifespan,
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    ],
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/api/diagnostics", get_diagnostics, methods=["GET"]),
        Route("/api/conformance", get_conformance, methods=["GET"]),
        Route("/api/runtimes", list_runtimes, methods=["GET"]),
        Route("/api/runtimes/{runtime_id}/capabilities", get_runtime_capabilities, methods=["GET"]),
        Route("/api/tasks", create_task, methods=["POST"]),
        Route("/api/tasks/{task_id}/executions", list_task_executions, methods=["GET"]),
        Route("/api/tasks/{task_id}/result", get_task_result, methods=["GET"]),
        Route("/api/tasks/{task_id}/events", stream_task_events, methods=["GET"]),
        Route("/api/dev/tasks/{task_id}/demo-trace", trigger_demo_trace, methods=["POST"]),
        Route("/api/uploads", upload_asset, methods=["POST"]),
        Route("/api/knowledge/assets", list_knowledge_assets, methods=["GET"]),
        Route("/api/skills", list_workspace_skills, methods=["GET"]),
        Route("/api/executions/{execution_id}", get_execution, methods=["GET"]),
        Route("/api/executions/{execution_id}/artifacts", list_execution_artifacts, methods=["GET"]),
        Route("/api/executions/{execution_id}/tool-calls", list_execution_tool_calls, methods=["GET"]),
        Route("/api/executions/{execution_id}/events", stream_execution_events, methods=["GET"]),
    ],
)
