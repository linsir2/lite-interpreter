"""Diagnostics and conformance inspection endpoints."""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from src.api.diagnostics_resources import build_conformance_report, build_diagnostics_report


async def get_diagnostics(_request: Request) -> JSONResponse:
    return JSONResponse(build_diagnostics_report())


async def get_conformance(_request: Request) -> JSONResponse:
    return JSONResponse(build_conformance_report())
