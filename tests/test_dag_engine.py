"""Hybrid DAG routing and harvesting tests."""
from unittest.mock import patch

from src.blackboard import ExecutionData, execution_blackboard, global_blackboard
from src.dag_engine.dag_graph import build_dag_graph, get_route_map
from src.dag_engine.nodes.analyst_node import analyst_node
from src.dag_engine.nodes.auditor_node import auditor_node
from src.dag_engine.nodes.coder_node import coder_node
from src.dag_engine.nodes.data_inspector import data_inspector_node
from src.dag_engine.nodes.debugger_node import debugger_node
from src.dag_engine.nodes.dynamic_swarm_node import dynamic_swarm_node
from src.dag_engine.nodes.executor_node import executor_node
from src.dag_engine.nodes.summarizer_node import summarizer_node
from src.dynamic_engine.deerflow_bridge import DeerflowTaskResult
from src.dag_engine.nodes.router_node import _has_business_context, router_node
from src.dag_engine.nodes.skill_harvester_node import skill_harvester_node
from src.mcp_gateway.tools.sandbox_exec_tool import normalize_execution_result
from src.storage.repository.skill_repo import SkillRepo


def test_route_map_exposes_dynamic_swarm():
    route_map = get_route_map()
    assert route_map["dynamic_swarm"] == "dynamic_swarm"


def test_router_business_context_check_handles_default_empty_dict():
    exec_data = ExecutionData(task_id="task", tenant_id="tenant")
    assert _has_business_context(exec_data) is False
    exec_data.business_context["rules"] = ["r1"]
    assert _has_business_context(exec_data) is True


def test_router_prefers_approved_skills_over_matched_skills():
    tenant_id = "tenant_router_skills"
    task_id = global_blackboard.create_task(tenant_id, "ws_router_skills", "placeholder")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws_router_skills",
            approved_skills=[{"name": "approved_skill"}],
            matched_skills=[{"name": "matched_skill"}],
        ),
    )
    result = router_node(
        {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "workspace_id": "ws_router_skills",
            "input_query": "简要说明规则",
        }
    )
    assert result["candidate_skills"][0]["name"] == "approved_skill"


def test_router_can_load_historical_approved_skills():
    tenant_id = "tenant_router_history"
    SkillRepo.clear()
    SkillRepo.save_approved_skills(
        tenant_id,
        "ws_router_history",
        [{"name": "historical_skill", "required_capabilities": ["knowledge_query"], "promotion": {"status": "approved"}}],
    )
    task_id = global_blackboard.create_task(tenant_id, "ws_router_history", "placeholder")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws_router_history",
        ),
    )
    result = router_node(
        {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "workspace_id": "ws_router_history",
            "input_query": "简要说明规则",
        }
    )
    assert result["candidate_skills"][0]["name"] == "historical_skill"
    persisted = execution_blackboard.read(tenant_id, task_id)
    assert persisted is not None
    assert persisted.historical_skill_matches[0]["name"] == "historical_skill"
    assert persisted.historical_skill_matches[0]["match_source"] == "historical_repo"
    assert persisted.historical_skill_matches[0]["match_score"] >= 0
    assert persisted.historical_skill_matches[0]["selected_by_stages"] == ["router"]


def test_router_can_load_preset_skills_without_repo_state():
    tenant_id = "tenant_router_presets"
    task_id = global_blackboard.create_task(tenant_id, "ws_router_presets", "placeholder")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws_router_presets",
        ),
    )
    result = router_node(
        {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "workspace_id": "ws_router_presets",
            "input_query": "请说明规则口径并核对合规要求",
            "allowed_tools": ["knowledge_query"],
        }
    )
    assert any(skill["name"] == "policy_clause_audit" for skill in result["candidate_skills"])


def test_build_dag_graph_compiles_or_gracefully_skips():
    graph = build_dag_graph()
    assert graph is None or hasattr(graph, "invoke")


def test_router_routes_complex_task_to_dynamic_swarm():
    tenant_id = "tenant_dynamic"
    task_id = global_blackboard.create_task(tenant_id, "ws_dynamic", "placeholder")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws_dynamic",
        ),
    )

    result = router_node(
        {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "workspace_id": "ws_dynamic",
            "input_query": "帮我分析这份财报，并结合宏观经济数据预测下季度走势，自己找数据并写代码验证",
        }
    )

    assert result["routing_mode"] == "dynamic"
    assert result["next_actions"] == ["dynamic_swarm"]
    assert result["complexity_score"] >= 0.7


def test_dynamic_swarm_and_harvester_form_minimal_closed_loop():
    tenant_id = "tenant_hybrid"
    task_id = global_blackboard.create_task(tenant_id, "ws_hybrid", "placeholder")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws_hybrid",
            routing_mode="dynamic",
            dynamic_reason="需要未知多步探索",
        ),
    )

    fake_result = DeerflowTaskResult(
        status="completed",
        summary="dynamic answer",
        trace_refs=["deerflow:test-thread"],
        artifacts=["/tmp/report.md"],
        recommended_skill={"source": "dynamic_swarm", "source_task_type": "dynamic_task"},
        trace=[
            {
                "agent_name": "deerflow",
                "step_name": "research",
                "event_type": "completed",
                "payload": {"artifacts": [{"path": "/tmp/report.md"}]},
            }
        ],
    )
    with patch("src.dag_engine.nodes.dynamic_swarm_node.RuntimeGateway.run", return_value=fake_result):
        dynamic_state = dynamic_swarm_node(
            {
                "tenant_id": tenant_id,
                "task_id": task_id,
                "workspace_id": "ws_hybrid",
                "input_query": "自己找数据并验证预测结论",
                "routing_mode": "dynamic",
                "complexity_score": 0.8,
            }
        )
    harvested_state = skill_harvester_node(
        {
            "tenant_id": tenant_id,
            "task_id": task_id,
            **dynamic_state,
        }
    )

    assert dynamic_state["dynamic_status"] == "completed"
    assert harvested_state["harvested_skill_candidates"]
    persisted = execution_blackboard.read(tenant_id, task_id)
    assert persisted is not None
    assert persisted.dynamic_summary
    assert persisted.harvested_skill_candidates
    assert persisted.task_envelope is not None
    assert persisted.execution_intent is not None
    assert persisted.decision_log
    assert persisted.runtime_backend == "deerflow"
    assert persisted.harvested_skill_candidates[0]["required_capabilities"]
    assert "authorization" in persisted.harvested_skill_candidates[0]
    assert persisted.harvested_skill_candidates[0]["replay_cases"]
    assert persisted.harvested_skill_candidates[0]["validation"]["authorization_allowed"] is True
    assert persisted.harvested_skill_candidates[0]["promotion"]["status"] == "approved"
    assert persisted.harvested_skill_candidates[0]["promotion"]["source_task_id"] == task_id
    assert persisted.harvested_skill_candidates[0]["promotion"]["source_trace_refs"]
    assert persisted.approved_skills


def test_dynamic_swarm_denies_unknown_tool_requests():
    tenant_id = "tenant_denied"
    task_id = global_blackboard.create_task(tenant_id, "ws_denied", "placeholder")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws_denied",
            routing_mode="dynamic",
        ),
    )

    dynamic_state = dynamic_swarm_node(
        {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "workspace_id": "ws_denied",
            "input_query": "帮我联网调研后执行结果",
            "routing_mode": "dynamic",
            "complexity_score": 0.9,
            "allowed_tools": ["shell_exec"],
        }
    )

    assert dynamic_state["dynamic_status"] == "denied"
    persisted = execution_blackboard.read(tenant_id, task_id)
    assert persisted is not None
    assert persisted.governance_decisions


def test_data_inspector_persists_successful_schema_updates(tmp_path):
    tenant_id = "tenant_inspector"
    task_id = global_blackboard.create_task(tenant_id, "ws_inspector", "inspect dataset")
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text("col1,col2\n1,2\n3,4\n", encoding="utf-8")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws_inspector",
            structured_datasets=[
                {
                    "file_name": "sales.csv",
                    "path": str(csv_path),
                }
            ],
        ),
    )

    result = data_inspector_node(
        {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "workspace_id": "ws_inspector",
            "input_query": "inspect dataset",
        }
    )

    assert result["blocked"] is False
    execution_blackboard._storage.clear()
    assert execution_blackboard.restore(tenant_id, task_id) is True
    restored = execution_blackboard.read(tenant_id, task_id)
    assert restored is not None
    assert restored.structured_datasets[0]["schema"]
    assert "load_kwargs" in restored.structured_datasets[0]


def test_executor_node_passes_task_context_to_sandbox(monkeypatch):
    tenant_id = "tenant_exec"
    task_id = global_blackboard.create_task(tenant_id, "ws_exec", "placeholder")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws_exec",
            generated_code="print('ok')",
        ),
    )

    calls = {}

    def fake_run_sync(**kwargs):
        calls.update(kwargs)
        return {"success": True, "output": "ok", "artifacts_dir": "/tmp/out"}

    monkeypatch.setattr("src.dag_engine.nodes.executor_node.SandboxExecTool.run_sync", fake_run_sync)
    result = executor_node(
        {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "workspace_id": "ws_exec",
            "input_query": "run",
        }
    )

    assert calls["task_id"] == task_id
    assert calls["workspace_id"] == "ws_exec"
    assert result["execution_result"]["success"] is True


def test_normalize_execution_result_adds_execution_record():
    normalized = normalize_execution_result(
        {
            "success": True,
            "output": "ok",
            "trace_id": "trace-123",
            "duration_seconds": 1.25,
            "sandbox_session": {
                "session_id": "session-123",
                "status": "completed",
            },
            "artifacts_dir": "/tmp/out",
            "mounted_inputs": [
                {
                    "kind": "structured_dataset",
                    "host_path": "/tmp/in.csv",
                    "container_path": "/app/inputs/in.csv",
                    "file_name": "in.csv",
                }
            ],
        },
        tenant_id="tenant-normalize",
        workspace_id="ws-normalize",
        task_id="task-normalize",
    )
    assert normalized["execution_record"]["tenant_id"] == "tenant-normalize"
    assert normalized["execution_record"]["session_id"] == "session-123"
    assert normalized["execution_record"]["artifacts"][0]["path"] == "/tmp/out"


def test_static_nodes_form_minimal_safe_chain():
    tenant_id = "tenant_static"
    SkillRepo.clear()
    SkillRepo.save_approved_skills(
        tenant_id,
        "ws_static",
        [{"name": "historical_skill_demo", "required_capabilities": ["knowledge_query"], "replay_cases": [{"case_id": "replay_hist_1"}], "promotion": {"status": "approved", "provenance": {"validation_status": "validated"}}}],
    )
    task_id = global_blackboard.create_task(tenant_id, "ws_static", "总结报销规则")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws_static",
            structured_datasets=[
                {
                    "file_name": "sales.csv",
                    "path": "/tmp/sales.csv",
                    "schema": "col1,col2",
                    "load_kwargs": {"sep": ",", "encoding": "utf-8"},
                }
            ],
            business_context={"rules": ["报销金额需含税"], "metrics": [], "filters": [], "sources": ["rule.pdf"]},
            approved_skills=[{"name": "approved_skill_demo", "required_capabilities": ["knowledge_query"], "promotion": {"status": "approved", "provenance": {"validation_status": "validated"}}}],
        ),
    )
    state = {
        "tenant_id": tenant_id,
        "task_id": task_id,
        "workspace_id": "ws_static",
        "input_query": "总结报销规则",
        "refined_context": "报销金额需含税。",
        "retry_count": 0,
    }

    state.update(analyst_node(state))
    assert state["analysis_plan"]
    assert "approved_skill_demo" in state["analysis_plan"]
    assert "historical_skill_demo" in state["analysis_plan"]
    assert "validation=validated" in state["analysis_plan"]
    state.update(coder_node(state))
    assert "print(" in state["generated_code"]
    assert "derived_findings" in state["generated_code"]
    assert "rule_checks" in state["generated_code"]
    assert "metric_checks" in state["generated_code"]
    assert "filter_checks" in state["generated_code"]
    assert "approved_skills" in state["generated_code"]
    assert "skill_strategy_hints" in state["generated_code"]
    assert "historical_skill_demo" in state["generated_code"]
    persisted = execution_blackboard.read(tenant_id, task_id)
    assert persisted is not None
    assert any(match["name"] == "historical_skill_demo" for match in persisted.historical_skill_matches)
    historical_match = next(match for match in persisted.historical_skill_matches if match["name"] == "historical_skill_demo")
    assert "analyst" in historical_match["selected_by_stages"]
    assert "coder" in historical_match["selected_by_stages"]
    assert historical_match["used_in_codegen"] is True
    assert historical_match["used_replay_case_ids"]
    assert "knowledge_query" in historical_match["used_capabilities"]
    assert state["input_mounts"][0]["container_path"].startswith("/app/inputs/")
    state.update(auditor_node(state))
    assert state["audit_result"]["safe"] is True
    assert state["next_actions"] == ["executor"]


def test_debugger_node_rewrites_safe_fallback():
    tenant_id = "tenant_debug"
    task_id = global_blackboard.create_task(tenant_id, "ws_debug", "placeholder")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws_debug",
            latest_error_traceback="bad import",
        ),
    )
    state = debugger_node(
        {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "workspace_id": "ws_debug",
            "input_query": "placeholder",
            "retry_count": 0,
        }
    )
    assert state["retry_count"] == 1
    assert "print(" in state["generated_code"]


def test_auditor_node_stops_after_retry_budget():
    tenant_id = "tenant_audit_stop"
    task_id = global_blackboard.create_task(tenant_id, "ws_audit_stop", "placeholder")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws_audit_stop",
            generated_code="import os\nos.system('ls')",
        ),
    )
    state = auditor_node(
        {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "workspace_id": "ws_audit_stop",
            "input_query": "placeholder",
            "retry_count": 1,
        }
    )
    assert state["next_actions"] == ["skill_harvester"]


def test_summarizer_node_builds_static_final_response():
    tenant_id = "tenant_summary_static"
    task_id = global_blackboard.create_task(tenant_id, "ws_summary_static", "placeholder")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws_summary_static",
            analysis_plan="plan",
            execution_result={"success": True, "output": "{\"status\":\"ok\",\"datasets\":[{\"file_name\":\"sales.csv\",\"row_count\":3,\"columns\":[\"a\",\"tax_amount\",\"contract_id\",\"biz_date\"],\"numeric_profiles\":[{\"column\":\"a\",\"mean\":2.0}],\"categorical_profiles\":[{\"column\":\"contract_id\",\"top_values\":[[\"A\",2]]}],\"date_profiles\":[{\"column\":\"biz_date\",\"min\":\"2024-01-01T00:00:00\",\"max\":\"2024-01-03T00:00:00\"}],\"group_summaries\":[{\"group_by\":\"contract_id\",\"measure\":\"a\",\"top_groups\":[[\"A\",4.0,2]]}],\"missing_counts\":{\"a\":0},\"tax_missing_count\":1,\"contract_missing_count\":1}],\"documents\":[{\"file_name\":\"rule.txt\",\"preview\":\"报销规则\",\"keyword_hits\":[\"报销规则\",\"上海\"]}],\"derived_findings\":[\"数据集 sales.csv 识别出 1 个数值列，可进行统计分析。\",\"数据集 sales.csv 识别出 1 个日期列，可进行趋势/时序分析。\",\"数据集 sales.csv 可按 contract_id 对 a 做分组统计。\"],\"rule_checks\":[{\"rule\":\"报销金额必须含税并上传合同\",\"issue_count\":2,\"warnings\":[\"sales.csv 存在 1 行税额缺失/为0\",\"sales.csv 存在 1 行合同字段缺失\"]}],\"metric_checks\":[{\"metric\":\"审批时效口径\",\"matched_columns\":[\"a\",\"biz_date\"],\"matched_groups\":[\"contract_id -> a\"],\"matched_date_columns\":[\"biz_date\"],\"highlights\":[\"sales.csv.a mean=2.0\",\"sales.csv.biz_date range=2024-01-01T00:00:00 -> 2024-01-03T00:00:00\",\"sales.csv 按 contract_id 分组后，A 的 a 最高=4.0\"]}],\"filter_checks\":[{\"filter\":\"上海\",\"matched_datasets\":[],\"matched_documents\":[\"rule.txt\"],\"matched_date_ranges\":[\"biz_date => 2024-01-01T00:00:00 -> 2024-01-03T00:00:00\"]}]}"},
            business_context={"rules": ["rule1"], "metrics": ["审批时效口径"], "filters": ["上海"], "sources": ["rule.pdf"]},
            knowledge_snapshot={"rewritten_query": "报销 规则 上海", "recall_strategies": ["bm25", "vector"], "cache_hit": True, "metadata": {"selected_count": 2}},
            business_context_refs=["chunk-1"],
            approved_skills=[{"name": "approved_skill_demo", "required_capabilities": ["knowledge_query"], "promotion": {"status": "approved", "provenance": {"validation_status": "validated"}}}],
            parser_reports=[{"file_name": "rule.pdf", "parse_mode": "ocr+vision", "parser_diagnostics": {"image_description_count": 2}}],
        ),
    )
    result = summarizer_node(
        {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "workspace_id": "ws_summary_static",
        }
    )
    assert result["final_response"]["mode"] == "static"
    assert result["final_response"]["evidence_refs"] == ["chunk-1"]
    assert result["final_response"]["answer"].startswith("已完成静态链分析")
    assert result["final_response"]["outputs"][0]["type"] == "dataset"
    assert result["final_response"]["outputs"][0]["path"] == "sales.csv"
    assert result["final_response"]["outputs"][0]["metrics"]["numeric_profiles"][0]["column"] == "a"
    assert result["final_response"]["outputs"][0]["metrics"]["date_profiles"][0]["column"] == "biz_date"
    assert result["final_response"]["outputs"][0]["metrics"]["group_summaries"][0]["group_by"] == "contract_id"
    assert result["final_response"]["details"]["parser_reports"][0]["parse_mode"] == "ocr+vision"
    assert any("数值列" in item for item in result["final_response"]["key_findings"])
    assert any("日期列" in item for item in result["final_response"]["key_findings"])
    assert any("过滤条件" in item for item in result["final_response"]["key_findings"])
    assert any("分组统计" in item for item in result["final_response"]["key_findings"])
    assert result["final_response"]["details"]["rule_checks"][0]["issue_count"] == 2
    assert result["final_response"]["details"]["metric_checks"][0]["metric"] == "审批时效口径"
    assert result["final_response"]["details"]["metric_checks"][0]["matched_groups"][0] == "contract_id -> a"
    assert result["final_response"]["details"]["filter_checks"][0]["filter"] == "上海"
    assert result["final_response"]["details"]["knowledge_snapshot"]["rewritten_query"] == "报销 规则 上海"
    assert result["final_response"]["details"]["approved_skills"][0]["name"] == "approved_skill_demo"
    assert result["final_response"]["details"]["skill_strategy_hints"][0]["name"] == "approved_skill_demo"
    assert result["final_response"]["details"]["used_historical_skills"] == []
    assert any("税额缺失" in item for item in result["final_response"]["caveats"])
    assert any("指标提示" in item for item in result["final_response"]["caveats"])
    assert any("日期范围" in item for item in result["final_response"]["caveats"])
    assert result["final_response"]["key_findings"]
    assert any("知识检索通道" in item for item in result["final_response"]["key_findings"])


def test_summarizer_node_builds_dynamic_final_response():
    tenant_id = "tenant_summary_dynamic"
    task_id = global_blackboard.create_task(tenant_id, "ws_summary_dynamic", "placeholder")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws_summary_dynamic",
            routing_mode="dynamic",
            dynamic_summary="dynamic done",
            dynamic_status="completed",
            dynamic_trace_refs=["trace-1"],
            dynamic_artifacts=["/tmp/a.md"],
        ),
    )
    result = summarizer_node(
        {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "workspace_id": "ws_summary_dynamic",
        }
    )
    assert result["final_response"]["mode"] == "dynamic"
    assert result["final_response"]["headline"] == "dynamic done"
    assert result["final_response"]["answer"].startswith("已完成动态探索")
    assert result["final_response"]["outputs"][0]["path"] == "/tmp/a.md"
    assert result["final_response"]["key_findings"]
