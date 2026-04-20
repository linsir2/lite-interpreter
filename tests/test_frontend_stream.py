"""Frontend stream rendering tests."""

from __future__ import annotations

from src.frontend.components.status_stream import build_status_stream_html


def test_status_stream_html_mentions_governance_panel():
    html = build_status_stream_html(
        api_base_url="http://127.0.0.1:8000",
        task_id="task-1",
        tenant_id="tenant-1",
        workspace_id="ws-1",
    )

    assert "Harness Governance" in html
    assert "ui.task.governance_update" in html
    assert "traceEvent.event_type" in html


def test_status_stream_html_supports_execution_stream():
    html = build_status_stream_html(
        api_base_url="http://127.0.0.1:8000",
        execution_id="runtime:task-1",
        tenant_id="tenant-1",
        workspace_id="ws-1",
        api_token="secret-token",
    )

    assert "/api/executions/runtime:task-1/events/poll" in html
    assert "Authorization" in html
    assert "Execution Detail Stream" in html
