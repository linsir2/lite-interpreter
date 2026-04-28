"""Minimal API application for task streaming and local health checks."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from config.settings import API_ALLOW_ORIGINS
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from src.api.auth import ApiAuthMiddleware
from src.api.routers.app_router import (
    create_app_analysis,
    get_app_analysis_detail,
    get_app_analysis_events,
    get_app_analysis_output,
    get_app_session,
    list_app_analyses,
    list_app_assets,
    list_app_audit,
    list_app_methods,
    upload_app_assets,
)
from src.api.routers.diagnostics_router import get_conformance, get_diagnostics
from src.api.routers.policy_router import get_harness_policy, update_harness_policy
from src.api.routers.runtime_router import get_runtime_capabilities, list_runtimes
from src.api.services.task_flow_service import recover_unfinished_tasks
from src.blackboard import execution_blackboard, global_blackboard, knowledge_blackboard, memory_blackboard
from src.common import event_bus
from src.sandbox.docker_executor import start_zombie_cleaner_daemon
from src.sandbox.runtime_state import close_docker_client
from src.storage.repository.knowledge_repo import KnowledgeRepo


async def health(_request):
    return JSONResponse({"status": "ok", "service": "lite-interpreter-api"})


WEB_DIST_DIR = Path(__file__).resolve().parents[2] / "apps/web/dist"
web_static = StaticFiles(directory=str(WEB_DIST_DIR), html=True) if WEB_DIST_DIR.exists() else None


async def serve_web_app(request):
    if web_static is None:  # pragma: no cover - guarded by route construction
        return JSONResponse({"error": "web_dist_missing"}, status_code=404)
    requested_path = str(request.path_params.get("path") or "").lstrip("/")
    try:
        response = await web_static.get_response(requested_path, request.scope)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        return FileResponse(WEB_DIST_DIR / "index.html")
    if response.status_code == 404:
        return FileResponse(WEB_DIST_DIR / "index.html")
    return response


@asynccontextmanager
async def app_lifespan(app: Starlette):
    global_blackboard.register_sub_board(execution_blackboard)
    global_blackboard.register_sub_board(knowledge_blackboard)
    global_blackboard.register_sub_board(memory_blackboard)
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
        Middleware(ApiAuthMiddleware),
        Middleware(
            CORSMiddleware,
            allow_origins=API_ALLOW_ORIGINS,
            allow_methods=["*"],
            allow_headers=["*"],
        ),
    ],
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/api/app/session", get_app_session, methods=["GET"]),
        Route("/api/app/analyses", list_app_analyses, methods=["GET"]),
        Route("/api/app/analyses", create_app_analysis, methods=["POST"]),
        Route("/api/app/analyses/{analysis_id}", get_app_analysis_detail, methods=["GET"]),
        Route("/api/app/analyses/{analysis_id}/events", get_app_analysis_events, methods=["GET"]),
        Route("/api/app/analyses/{analysis_id}/outputs/{output_id}", get_app_analysis_output, methods=["GET"]),
        Route("/api/app/assets", list_app_assets, methods=["GET"]),
        Route("/api/app/assets", upload_app_assets, methods=["POST"]),
        Route("/api/app/methods", list_app_methods, methods=["GET"]),
        Route("/api/app/audit", list_app_audit, methods=["GET"]),
        Route("/api/diagnostics", get_diagnostics, methods=["GET"]),
        Route("/api/conformance", get_conformance, methods=["GET"]),
        Route("/api/policy", get_harness_policy, methods=["GET"]),
        Route("/api/policy", update_harness_policy, methods=["POST"]),
        Route("/api/runtimes", list_runtimes, methods=["GET"]),
        Route("/api/runtimes/{runtime_id}/capabilities", get_runtime_capabilities, methods=["GET"]),
        *(
            [
                Route("/", serve_web_app, methods=["GET", "HEAD"]),
                Route("/{path:path}", serve_web_app, methods=["GET", "HEAD"]),
            ]
            if WEB_DIST_DIR.exists()
            else []
        ),
    ],
)
