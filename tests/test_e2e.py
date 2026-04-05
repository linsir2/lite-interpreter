"""End-to-end task flow tests covering API entrypoints and result retrieval."""
from __future__ import annotations

import asyncio
import json

from starlette.requests import Request

from src.api.routers.analysis_router import _run_task_flow, create_task, get_task_result
from src.api.routers.execution_router import get_execution, list_task_executions
from src.dynamic_engine.deerflow_bridge import DeerflowTaskResult
from src.mcp_gateway.tools.sandbox_exec_tool import normalize_execution_result


def _make_request(
    *,
    method: str,
    path: str,
    path_params: dict[str, str] | None = None,
    body: dict | None = None,
) -> Request:
    payload = json.dumps(body or {}).encode()

    async def receive():
        return {
            "type": "http.request",
            "body": payload,
            "more_body": False,
        }

    headers = [(b"content-type", b"application/json")] if body is not None else []
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": b"",
            "path_params": path_params or {},
            "headers": headers,
        },
        receive=receive,
    )


def test_static_task_flow_e2e_via_api(monkeypatch):
    tenant_id = "tenant-e2e-static"
    workspace_id = "ws-e2e-static"
    request = _make_request(
        method="POST",
        path="/api/tasks",
        body={
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "input_query": "请做简单分析",
            "autorun": False,
        },
    )
    response = asyncio.run(create_task(request))
    body = json.loads(response.body.decode())
    task_id = body["task_id"]

    def fake_run_sync(**kwargs):
        return normalize_execution_result(
            {
                "success": True,
                "output": json.dumps(
                    {
                        "status": "ok",
                        "datasets": [],
                        "documents": [],
                        "derived_findings": ["完成静态分析"],
                        "rule_checks": [],
                        "metric_checks": [],
                        "filter_checks": [],
                    },
                    ensure_ascii=False,
                ),
                "trace_id": f"trace-{task_id}",
                "duration_seconds": 0.12,
                "sandbox_session": {"session_id": f"session-{task_id}", "status": "completed"},
                "mounted_inputs": [],
            },
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            task_id=task_id,
        )

    monkeypatch.setattr("src.dag_engine.nodes.executor_node.SandboxExecTool.run_sync", fake_run_sync)

    asyncio.run(
        _run_task_flow(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id=workspace_id,
            query="请做简单分析",
            allowed_tools=[],
            governance_profile="researcher",
        )
    )

    result_request = _make_request(
        method="GET",
        path=f"/api/tasks/{task_id}/result",
        path_params={"task_id": task_id},
    )
    result_response = asyncio.run(get_task_result(result_request))
    result_body = json.loads(result_response.body.decode())

    assert result_body["global_status"] == "success"
    assert result_body["final_response"]["mode"] == "static"
    assert result_body["final_response"]["details"]["execution_success"] is True
    assert result_body["task_envelope"]["task_id"] == task_id
    assert result_body["execution_intent"]["intent"] == "static_flow"
    executions_response = asyncio.run(
        list_task_executions(
            _make_request(
                method="GET",
                path=f"/api/tasks/{task_id}/executions",
                path_params={"task_id": task_id},
            )
        )
    )
    executions_body = json.loads(executions_response.body.decode())
    execution_id = executions_body["executions"][0]["execution_id"]
    execution_response = asyncio.run(
        get_execution(
            _make_request(
                method="GET",
                path=f"/api/executions/{execution_id}",
                path_params={"execution_id": execution_id},
            )
        )
    )
    execution_body = json.loads(execution_response.body.decode())
    assert execution_body["kind"] == "sandbox"


def test_dynamic_task_flow_e2e_via_api(monkeypatch):
    tenant_id = "tenant-e2e-dynamic"
    workspace_id = "ws-e2e-dynamic"
    request = _make_request(
        method="POST",
        path="/api/tasks",
        body={
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "input_query": "帮我分析这份财报，并结合宏观经济数据预测下季度走势，自己找数据并写代码验证",
            "autorun": False,
        },
    )
    response = asyncio.run(create_task(request))
    body = json.loads(response.body.decode())
    task_id = body["task_id"]

    fake_result = DeerflowTaskResult(
        status="completed",
        summary="dynamic e2e answer",
        trace_refs=[f"deerflow:{task_id}"],
        artifacts=["/tmp/e2e-report.md"],
        recommended_skill={"source": "dynamic_swarm", "source_task_type": "dynamic_task"},
        trace=[
            {
                "agent_name": "deerflow",
                "step_name": "research",
                "event_type": "completed",
                "payload": {"artifacts": [{"path": "/tmp/e2e-report.md"}]},
            }
        ],
    )

    monkeypatch.setattr("src.dag_engine.nodes.dynamic_swarm_node.RuntimeGateway.run", lambda self, plan, on_event=None: fake_result)

    asyncio.run(
        _run_task_flow(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id=workspace_id,
            query="帮我分析这份财报，并结合宏观经济数据预测下季度走势，自己找数据并写代码验证",
            allowed_tools=[],
            governance_profile="researcher",
        )
    )

    result_request = _make_request(
        method="GET",
        path=f"/api/tasks/{task_id}/result",
        path_params={"task_id": task_id},
    )
    result_response = asyncio.run(get_task_result(result_request))
    result_body = json.loads(result_response.body.decode())

    assert result_body["global_status"] == "success"
    assert result_body["final_response"]["mode"] == "dynamic"
    assert result_body["dynamic_summary"] == "dynamic e2e answer"
    assert result_body["approved_skills"]
    assert result_body["execution_intent"]["intent"] == "dynamic_flow"
    executions_response = asyncio.run(
        list_task_executions(
            _make_request(
                method="GET",
                path=f"/api/tasks/{task_id}/executions",
                path_params={"task_id": task_id},
            )
        )
    )
    executions_body = json.loads(executions_response.body.decode())
    assert executions_body["executions"][0]["kind"] == "runtime"
