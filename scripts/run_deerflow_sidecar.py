#!/usr/bin/env python3
"""Run a local DeerFlow sidecar service for lite-interpreter."""

from __future__ import annotations

import argparse
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

# Load .env file from project root before any other code runs
_project_root = Path(__file__).resolve().parents[1]
load_dotenv(_project_root / ".env")


def build_client_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "thinking_enabled": payload.get("thinking_enabled", True),
        "subagent_enabled": payload.get("subagent_enabled", True),
        "plan_mode": payload.get("plan_mode", True),
    }
    if payload.get("config_path"):
        candidate = Path(str(payload["config_path"])).expanduser()
        if not candidate.is_absolute():
            candidate = (_project_root / candidate).resolve()
        kwargs["config_path"] = str(candidate)
    if payload.get("model_name"):
        kwargs["model_name"] = payload["model_name"]
    return kwargs


def resolve_client_config_dir(payload: dict[str, Any]) -> Path:
    raw_value = str(payload.get("config_path") or "").strip()
    if raw_value:
        candidate = Path(raw_value).expanduser().resolve()
        if candidate.is_file():
            return candidate.parent
        if candidate.is_dir():
            return candidate
    return (_project_root / "config").resolve()


@contextmanager
def deerflow_config_workdir(payload: dict[str, Any]):
    previous_cwd = Path.cwd()
    target_dir = resolve_client_config_dir(payload)
    os.chdir(target_dir)
    try:
        yield
    finally:
        os.chdir(previous_cwd)


async def health(_: Request):
    return JSONResponse(
        {
            "status": "ok",
            "service": "deerflow-sidecar",
            "python": os.sys.version,
        }
    )


async def chat(request: Request):
    from deerflow.client import DeerFlowClient

    payload = await request.json()
    with deerflow_config_workdir(payload):
        client = DeerFlowClient(**build_client_kwargs(payload))
        response = client.chat(payload["message"], thread_id=payload.get("thread_id"))
    return JSONResponse({"response": response})


async def stream(request: Request):
    from deerflow.client import DeerFlowClient

    payload = await request.json()

    def event_iter():
        with deerflow_config_workdir(payload):
            client = DeerFlowClient(**build_client_kwargs(payload))
            for event in client.stream(
                payload["message"],
                thread_id=payload.get("thread_id"),
                subagent_enabled=payload.get("subagent_enabled", True),
                plan_mode=payload.get("plan_mode", True),
                thinking_enabled=payload.get("thinking_enabled", True),
                recursion_limit=payload.get("recursion_limit", 32),
            ):
                yield json.dumps({"type": event.type, "data": event.data}, ensure_ascii=False) + "\n"

    return StreamingResponse(event_iter(), media_type="application/x-ndjson")


def build_app() -> Starlette:
    return Starlette(
        debug=False,
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/v1/chat", chat, methods=["POST"]),
            Route("/v1/stream", stream, methods=["POST"]),
        ],
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the DeerFlow sidecar service for lite-interpreter.")
    parser.add_argument("--host", default=os.getenv("DEERFLOW_SIDECAR_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("DEERFLOW_SIDECAR_PORT", "8765")))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    uvicorn.run(build_app(), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
