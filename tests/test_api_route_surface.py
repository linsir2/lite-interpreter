"""Tests for the supported public API route surface after hard cut migration."""

from __future__ import annotations

from src.api.main import app


def test_supported_public_routes_are_present():
    route_paths = {route.path for route in app.routes}
    assert "/api/app/session" in route_paths
    assert "/api/app/analyses" in route_paths
    assert "/api/app/analyses/{analysis_id}" in route_paths
    assert "/api/app/analyses/{analysis_id}/events" in route_paths
    assert "/api/app/analyses/{analysis_id}/outputs/{output_id}" in route_paths
    assert "/api/app/assets" in route_paths
    assert "/api/app/methods" in route_paths
    assert "/api/app/audit" in route_paths


def test_legacy_public_routes_are_gone_from_router_table():
    route_paths = {route.path for route in app.routes}
    legacy_paths = {
        "/api/session/login",
        "/api/session/me",
        "/api/tasks",
        "/api/tasks/{task_id}/result",
        "/api/tasks/{task_id}/workspace",
        "/api/tasks/{task_id}/executions",
        "/api/uploads",
        "/api/knowledge/assets",
        "/api/skills",
        "/api/audit/logs",
        "/api/executions/{execution_id}",
        "/api/executions/{execution_id}/artifacts",
        "/api/executions/{execution_id}/tool-calls",
        "/api/executions/{execution_id}/events",
    }
    assert legacy_paths.isdisjoint(route_paths)
