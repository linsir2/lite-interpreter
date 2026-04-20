"""End-to-end task flow tests covering API entrypoints and result retrieval."""

from __future__ import annotations

import asyncio
import json

import pytest
from src.api.routers.analysis_router import _run_task_flow, create_task, get_task_result
from src.api.routers.execution_router import get_execution, list_task_executions
from src.blackboard import MemoryData, execution_blackboard, memory_blackboard
from src.mcp_gateway.tools.sandbox_exec_tool import normalize_execution_result
from src.sandbox.docker_executor import get_docker_client
from starlette.requests import Request


def _docker_available() -> bool:
    try:
        client = get_docker_client()
        client.ping()
        return True
    except Exception:
        return False


def _run_task_flow_inline(monkeypatch, coroutine):
    class FakeLoop:
        def run_in_executor(self, executor, func):  # noqa: ARG002
            future = asyncio.Future()
            try:
                future.set_result(func())
            except Exception as exc:  # pragma: no cover - test helper
                future.set_exception(exc)
            return future

    monkeypatch.setattr("src.api.routers.analysis_router.asyncio.get_running_loop", lambda: FakeLoop())
    asyncio.run(coroutine)


def _make_request(
    *,
    method: str,
    path: str,
    path_params: dict[str, str] | None = None,
    body: dict | None = None,
    query_params: dict[str, str] | None = None,
) -> Request:
    payload = json.dumps(body or {}).encode()

    async def receive():
        return {
            "type": "http.request",
            "body": payload,
            "more_body": False,
        }

    headers = [(b"content-type", b"application/json")] if body is not None else []
    query_string = "&".join(f"{key}={value}" for key, value in (query_params or {}).items()).encode()
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": query_string,
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

    _run_task_flow_inline(
        monkeypatch,
        _run_task_flow(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id=workspace_id,
            query="请做简单分析",
            allowed_tools=[],
            governance_profile="researcher",
        ),
    )

    result_request = _make_request(
        method="GET",
        path=f"/api/tasks/{task_id}/result",
        path_params={"task_id": task_id},
        query_params={"tenant_id": tenant_id, "workspace_id": workspace_id},
    )
    result_response = asyncio.run(get_task_result(result_request))
    result_body = json.loads(result_response.body.decode())

    assert result_body["status"]["global_status"] == "success"
    assert result_body["response"]["mode"] == "static"
    assert result_body["response"]["details"]["execution_success"] is True
    assert result_body["control"]["task_envelope"]["task_id"] == task_id
    assert result_body["control"]["execution_intent"]["intent"] == "static_flow"
    executions_response = asyncio.run(
        list_task_executions(
            _make_request(
                method="GET",
                path=f"/api/tasks/{task_id}/executions",
                path_params={"task_id": task_id},
                query_params={"tenant_id": tenant_id, "workspace_id": workspace_id},
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
                query_params={"tenant_id": tenant_id, "workspace_id": workspace_id},
            )
        )
    )
    execution_body = json.loads(execution_response.body.decode())
    assert execution_body["kind"] == "sandbox"


def test_static_task_flow_e2e_via_api_with_real_sandbox(monkeypatch):
    if not _docker_available():
        pytest.skip("Docker unavailable in current environment")

    tenant_id = "tenant-e2e-static-real"
    workspace_id = "ws-e2e-static-real"
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

    _run_task_flow_inline(
        monkeypatch,
        _run_task_flow(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id=workspace_id,
            query="请做简单分析",
            allowed_tools=[],
            governance_profile="researcher",
        ),
    )

    result_request = _make_request(
        method="GET",
        path=f"/api/tasks/{task_id}/result",
        path_params={"task_id": task_id},
        query_params={"tenant_id": tenant_id, "workspace_id": workspace_id},
    )
    result_response = asyncio.run(get_task_result(result_request))
    result_body = json.loads(result_response.body.decode())

    assert result_body["status"]["global_status"] == "success"
    assert result_body["response"]["mode"] == "static"
    assert result_body["response"]["details"]["execution_success"] is True
    assert result_body["control"]["execution_intent"]["intent"] == "static_flow"

    executions_response = asyncio.run(
        list_task_executions(
            _make_request(
                method="GET",
                path=f"/api/tasks/{task_id}/executions",
                path_params={"task_id": task_id},
                query_params={"tenant_id": tenant_id, "workspace_id": workspace_id},
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
                query_params={"tenant_id": tenant_id, "workspace_id": workspace_id},
            )
        )
    )
    execution_body = json.loads(execution_response.body.decode())

    assert execution_body["kind"] == "sandbox"
    assert execution_body["success"] is True


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

    def fake_execute_task_flow(state, *, nodes):  # noqa: ARG001
        approved_skills = [{"name": "dynamic_skill_demo"}]
        memory_blackboard.write(
            tenant_id,
            task_id,
            MemoryData(
                tenant_id=tenant_id,
                task_id=task_id,
                workspace_id=workspace_id,
                approved_skills=approved_skills,
            ),
        )
        memory_blackboard.persist(tenant_id, task_id)
        execution = execution_blackboard.read(tenant_id, task_id)
        assert execution is not None
        execution.dynamic.summary = "dynamic e2e answer"
        execution.dynamic.status = "completed"
        execution.dynamic.trace_refs = [f"deerflow:{task_id}"]
        execution.dynamic.artifacts = ["/tmp/e2e-report.md"]
        execution.control.execution_intent = {
            "intent": "dynamic_then_static_flow",
            "destinations": ["dynamic_swarm"],
            "metadata": {"next_static_steps": ["analyst"]},
        }
        execution.control.final_response = {
            "mode": "static",
            "headline": "dynamic reentered static path",
            "answer": "dynamic reentered static path",
            "key_findings": [],
        }
        execution_blackboard.write(tenant_id, task_id, execution)
        execution_blackboard.persist(tenant_id, task_id)
        return {
            "terminal_status": "success",
            "terminal_sub_status": "动态研究回流后静态链执行完成",
            "execution_intent": execution.control.execution_intent,
            "dynamic_status": "completed",
            "dynamic_summary": "dynamic e2e answer",
            "final_response": execution.control.final_response,
        }

    monkeypatch.setattr("src.api.routers.analysis_router.execute_task_flow", fake_execute_task_flow)
    monkeypatch.setattr("src.api.routers.analysis_router._record_historical_skill_outcomes", lambda **kwargs: None)

    _run_task_flow_inline(
        monkeypatch,
        _run_task_flow(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id=workspace_id,
            query="帮我分析这份财报，并结合宏观经济数据预测下季度走势，自己找数据并写代码验证",
            allowed_tools=[],
            governance_profile="researcher",
        ),
    )

    result_request = _make_request(
        method="GET",
        path=f"/api/tasks/{task_id}/result",
        path_params={"task_id": task_id},
        query_params={"tenant_id": tenant_id, "workspace_id": workspace_id},
    )
    result_response = asyncio.run(get_task_result(result_request))
    result_body = json.loads(result_response.body.decode())

    assert result_body["status"]["global_status"] == "success"
    assert result_body["response"]["mode"] == "static"
    assert result_body["dynamic"]["summary"] == "dynamic e2e answer"
    assert result_body["skills"]["approved"]
    assert result_body["control"]["execution_intent"]["intent"] == "dynamic_then_static_flow"
