"""Hybrid DAG routing and harvesting tests."""

from unittest.mock import patch

from src.blackboard import ExecutionData, MemoryData, execution_blackboard, global_blackboard, memory_blackboard
from src.common import ExecutionRecord
from src.dag_engine.dag_exceptions import TaskLeaseLostError
from src.dag_engine.dag_graph import execute_task_flow
from src.dag_engine.nodes.analyst_node import analyst_node
from src.dag_engine.nodes.auditor_node import auditor_node
from src.dag_engine.nodes.coder_node import coder_node
from src.dag_engine.nodes.data_inspector import data_inspector_node
from src.dag_engine.nodes.debugger_node import debugger_node
from src.dag_engine.nodes.dynamic_swarm_node import dynamic_swarm_node
from src.dag_engine.nodes.executor_node import executor_node
from src.dag_engine.nodes.router_node import _has_business_context, router_node
from src.dag_engine.nodes.skill_harvester_node import skill_harvester_node
from src.dag_engine.nodes.static_codegen import build_dataset_aware_code
from src.dag_engine.nodes.summarizer_node import summarizer_node
from src.dynamic_engine.deerflow_bridge import DeerflowTaskResult
from src.mcp_gateway.tools.sandbox_exec_tool import normalize_execution_result
from src.storage.repository.memory_repo import MemoryRepo


def test_router_business_context_check_handles_default_empty_dict():
    exec_data = ExecutionData(task_id="task", tenant_id="tenant")
    assert _has_business_context(exec_data) is False
    exec_data.knowledge.business_context.rules = ["r1"]
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
        ),
    )
    memory_blackboard.write(
        tenant_id,
        task_id,
        MemoryData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws_router_skills",
            approved_skills=[{"name": "approved_skill"}],
            historical_matches=[{"name": "matched_skill"}],
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
    assert result["execution_intent"]["candidate_skills"][0]["name"] == "approved_skill"


def test_router_can_load_historical_approved_skills():
    tenant_id = "tenant_router_history"
    MemoryRepo.clear()
    MemoryRepo.save_approved_skills(
        tenant_id,
        "ws_router_history",
        [
            {
                "name": "historical_skill",
                "required_capabilities": ["knowledge_query"],
                "promotion": {"status": "approved"},
            }
        ],
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
    assert result["execution_intent"]["candidate_skills"][0]["name"] == "historical_skill"
    persisted = memory_blackboard.read(tenant_id, task_id)
    assert persisted is not None
    assert persisted.historical_matches[0].name == "historical_skill"
    assert persisted.historical_matches[0].match_source == "historical_repo"
    assert persisted.historical_matches[0].match_score >= 0
    assert persisted.historical_matches[0].selected_by_stages == ["router"]


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
    assert any(skill["name"] == "policy_clause_audit" for skill in result["execution_intent"]["candidate_skills"])


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

    assert result["execution_intent"]["intent"] == "dynamic_then_static_flow"
    assert result["next_actions"] == ["dynamic_swarm"]
    assert result["execution_intent"]["complexity_score"] >= 0.7
    assert result["execution_intent"]["metadata"]["analysis_mode"] == "dynamic_research_analysis"
    routing_stage = result["execution_intent"]["metadata"]["routing_stage"]
    expected_alias = "reasoning_model" if routing_stage in {"fine", "fallback"} else "fast_model"
    assert result["execution_intent"]["metadata"]["effective_model_alias"] == expected_alias
    assert result["execution_intent"]["metadata"]["final_mode"] == "dynamic"
    assert result["execution_intent"]["metadata"]["next_static_steps"]
    assert result["execution_intent"]["metadata"]["routing_stage"] in {"coarse", "fine", "fallback"}


def test_router_keeps_hybrid_analysis_static_even_when_query_is_long():
    tenant_id = "tenant_hybrid_long"
    task_id = global_blackboard.create_task(tenant_id, "ws_hybrid_long", "placeholder")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws_hybrid_long",
            inputs={
                "structured_datasets": [{"file_name": "expenses.csv", "path": "/tmp/expenses.csv"}],
                "business_documents": [{"file_name": "policy.pdf", "path": "/tmp/policy.pdf", "status": "parsed"}],
            },
            knowledge={"business_context": {"rules": ["合同必须上传"]}},
        ),
    )

    result = router_node(
        {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "workspace_id": "ws_hybrid_long",
            "input_query": "请结合费用数据和制度说明，逐步核对含税规则、合同要求、审批时效口径，并总结异常点和后续处理建议",
        }
    )

    assert result["execution_intent"]["metadata"]["analysis_mode"] == "hybrid_analysis"
    assert result["execution_intent"]["metadata"]["final_mode"] == "hybrid"
    assert result["next_actions"] != ["dynamic_swarm"]


def test_router_uses_runtime_decision_as_single_semantic_source():
    tenant_id = "tenant_runtime_source"
    task_id = global_blackboard.create_task(tenant_id, "ws_runtime_source", "placeholder")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws_runtime_source",
        ),
    )

    fake_runtime_decision = type(
        "FakeRuntimeDecision",
        (),
        {
            "call_purpose": "routing_assess",
            "model_alias": "fast_model",
            "analysis_mode": "dataset_analysis",
            "coarse_mode": "static",
            "final_mode": "static",
            "evidence_strategy": "dataset_first",
            "routing_mode": "static",
            "destinations": ("analyst",),
            "route_candidates": ("static",),
            "routing_stage": "coarse",
            "routing_confidence": 0.91,
            "routing_degraded": False,
            "degrade_reason": "",
            "requires_static_execution": True,
            "requires_external_research": False,
            "fine_routing_invoked": False,
            "continuation": "finish",
            "next_static_steps": (),
            "effective_tools": (),
            "known_gaps": (),
            "routing_reasons": ("runtime selected analyst path",),
            "complexity_score": 0.11,
            "decision_reason": "runtime override",
            "to_metadata": lambda self: {
                "call_purpose": "routing_assess",
                "effective_model_alias": "fast_model",
                "analysis_mode": "dataset_analysis",
                "coarse_mode": "static",
                "final_mode": "static",
                "evidence_strategy": "dataset_first",
                "routing_mode": "static",
                "destinations": ["analyst"],
                "route_candidates": ["static"],
                "routing_stage": "coarse",
                "routing_confidence": 0.91,
                "routing_degraded": False,
                "degrade_reason": "",
                "requires_static_execution": True,
                "requires_external_research": False,
                "fine_routing_invoked": False,
                "continuation": "finish",
                "next_static_steps": [],
                "effective_tools": [],
                "known_gaps": [],
                "routing_reasons": ["runtime selected analyst path"],
                "complexity_score": 0.11,
                "decision_reason": "runtime override",
            },
        },
    )()

    with patch("src.dag_engine.nodes.router_node.resolve_runtime_decision", return_value=fake_runtime_decision):
        result = router_node(
            {
                "tenant_id": tenant_id,
                "task_id": task_id,
                "workspace_id": "ws_runtime_source",
                "input_query": "帮我分析这份财报，并结合宏观经济数据预测下季度走势，自己找数据并写代码验证",
            }
        )

    assert result["next_actions"] == ["analyst"]
    assert result["execution_intent"]["metadata"]["decision_reason"] == "runtime override"


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
    with patch("src.dag_engine.nodes.dynamic_swarm_node.DeerflowBridge.run", return_value=fake_result):
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
    assert harvested_state == {}
    persisted_execution = execution_blackboard.read(tenant_id, task_id)
    persisted_memory = memory_blackboard.read(tenant_id, task_id)
    assert persisted_execution is not None
    assert persisted_memory is not None
    assert persisted_execution.dynamic.summary
    assert persisted_execution.control.task_envelope is not None
    assert persisted_execution.control.execution_intent is not None
    assert persisted_execution.control.decision_log
    assert persisted_execution.dynamic.runtime_backend == "deerflow"
    assert persisted_execution.dynamic.continuation == "finish"
    assert persisted_memory.harvested_candidates
    assert persisted_memory.harvested_candidates[0].required_capabilities
    assert persisted_memory.harvested_candidates[0].authorization.allowed is True
    assert persisted_memory.harvested_candidates[0].replay_cases
    assert persisted_memory.harvested_candidates[0].validation.authorization_allowed is True
    assert persisted_memory.harvested_candidates[0].promotion.status == "approved"
    assert persisted_memory.harvested_candidates[0].promotion.source_task_id == task_id
    assert persisted_memory.harvested_candidates[0].promotion.source_trace_refs
    assert persisted_memory.approved_skills


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
    assert persisted.control.decision_log


def test_execute_task_flow_reenters_static_path_after_dynamic_success_when_required():
    result = execute_task_flow(
        {
            "tenant_id": "tenant-dynamic-reentry",
            "task_id": "task-dynamic-reentry",
            "workspace_id": "ws-dynamic-reentry",
            "input_query": "research then code",
        },
        nodes={
            "router": lambda state: {
                "next_actions": ["dynamic_swarm"],
                "execution_intent": {"metadata": {"next_static_steps": ["analyst"]}},
            },
            "dynamic_swarm": lambda state: {
                "dynamic_status": "completed",
                "dynamic_continuation": "resume_static",
                "dynamic_next_static_steps": ["analyst"],
                "dynamic_summary": "researched",
                "dynamic_research_findings": ["f1"],
                "dynamic_evidence_refs": ["trace-1"],
            },
            "skill_harvester": lambda state: {},
            "summarizer": lambda state: {"final_response": {"mode": "static"}},
            "data_inspector": lambda state: {},
            "kag_retriever": lambda state: {},
            "context_builder": lambda state: {},
            "analyst": lambda state: {"analysis": "ok"},
            "coder": lambda state: {"code": "print('ok')"},
            "auditor": lambda state: {"next_actions": ["executor"]},
            "debugger": lambda state: {},
            "executor": lambda state: {"execution_record": {"success": True, "output": "ok"}},
        },
    )

    assert result["terminal_status"] == "success"
    assert result["terminal_sub_status"] == "动态研究回流后静态链执行完成"
    assert result["dynamic_status"] == "completed"


def test_execute_task_flow_uses_real_dynamic_merge_contract_with_runtime_patch(monkeypatch):
    tenant_id = "tenant-dynamic-real-merge"
    task_id = global_blackboard.create_task(tenant_id, "ws-dynamic-real-merge", "placeholder")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(tenant_id=tenant_id, task_id=task_id, workspace_id="ws-dynamic-real-merge"),
    )

    fake_result = DeerflowTaskResult(
        status="completed",
        summary="外部研究结论：行业均值高于内部数据",
        continuation="resume_static",
        next_static_steps=["analyst"],
        trace_refs=["deerflow:test-thread"],
        artifacts=["/tmp/report.md"],
        research_findings=["行业均值高于内部数据", "建议先生成静态校验代码"],
        evidence_refs=["deerflow:test-thread", "/tmp/report.md"],
        suggested_static_actions=["将研究发现转成静态分析计划"],
        recommended_skill={"source": "dynamic_swarm", "source_task_type": "dynamic_task"},
        trace=[],
    )
    monkeypatch.setattr("src.dag_engine.nodes.dynamic_swarm_node.DeerflowBridge.run", lambda self, request, on_event=None: fake_result)

    result = execute_task_flow(
        {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "workspace_id": "ws-dynamic-real-merge",
            "input_query": "帮我自己找数据并写代码验证",
        },
        nodes={
            "router": lambda state: {
                "next_actions": ["dynamic_swarm"],
                "execution_intent": {
                    "intent": "dynamic_then_static_flow",
                    "destinations": ["dynamic_swarm"],
                    "metadata": {"next_static_steps": ["analyst"]},
                },
            },
            "dynamic_swarm": dynamic_swarm_node,
            "skill_harvester": lambda state: {},
            "summarizer": lambda state: {"final_response": {"mode": "static"}},
            "data_inspector": lambda state: {},
            "kag_retriever": lambda state: {},
            "context_builder": lambda state: {},
            "analyst": lambda state: {"analysis_plan": "plan"},
            "coder": lambda state: {"generated_code": "print('ok')"},
            "auditor": lambda state: {"next_actions": ["executor"]},
            "debugger": lambda state: {},
            "executor": lambda state: {
                "execution_record": ExecutionRecord(
                    session_id="session-dynamic-real-merge",
                    tenant_id=tenant_id,
                    workspace_id="ws-dynamic-real-merge",
                    task_id=task_id,
                    success=True,
                    trace_id="trace-dynamic-real-merge",
                    duration_seconds=0.1,
                    output="ok",
                ).model_dump(mode="json")
            },
        },
    )

    persisted = execution_blackboard.read(tenant_id, task_id)
    assert persisted is not None
    assert "deerflow:test-thread" in persisted.knowledge.knowledge_snapshot.evidence_refs
    assert persisted.knowledge.analysis_brief.recommended_next_step == "将研究发现转成静态分析计划"
    assert result["terminal_status"] == "success"


def test_dynamic_swarm_does_not_duplicate_trace_when_runtime_event_has_source():
    tenant_id = "tenant_dynamic_trace_dedupe"
    task_id = global_blackboard.create_task(tenant_id, "ws_dynamic_trace_dedupe", "placeholder")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws_dynamic_trace_dedupe",
        ),
    )

    fake_result = DeerflowTaskResult(
        status="completed",
        summary="dynamic answer",
        trace_refs=["deerflow:test-thread"],
        artifacts=[],
        recommended_skill={},
        trace=[
            {
                "agent_name": "deerflow-sidecar",
                "step_name": "research",
                "event_type": "progress",
                "source_event_type": "values",
                "source": "deerflow-sidecar",
                "payload": {"message": "working"},
            }
        ],
    )

    with patch("src.dag_engine.nodes.dynamic_swarm_node.DeerflowBridge.run", return_value=fake_result):
        dynamic_swarm_node(
            {
                "tenant_id": tenant_id,
                "task_id": task_id,
                "workspace_id": "ws_dynamic_trace_dedupe",
                "input_query": "自己找数据并验证预测结论",
                "routing_mode": "dynamic",
                "complexity_score": 0.8,
            }
        )

    persisted = execution_blackboard.read(tenant_id, task_id)
    assert persisted is not None
    assert len(persisted.dynamic.trace) == 1
    assert persisted.dynamic.trace[0].source == "deerflow-sidecar"


def test_dynamic_swarm_node_aborts_when_lease_is_lost_mid_event(monkeypatch):
    tenant_id = "tenant_dynamic_lease_abort"
    task_id = global_blackboard.create_task(tenant_id, "ws_dynamic_lease_abort", "placeholder")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws_dynamic_lease_abort",
        ),
    )

    lease_checks = {"count": 0}

    def fake_lease_guard(task_id_arg, owner_id_arg):
        lease_checks["count"] += 1
        if lease_checks["count"] >= 3:
            raise TaskLeaseLostError("task lease lost during runtime event")

    fake_result = DeerflowTaskResult(
        status="completed",
        summary="dynamic answer",
        trace_refs=["deerflow:test-thread"],
        artifacts=[],
        recommended_skill={},
        trace=[],
    )

    def fake_run(self, plan, on_event=None):
        assert on_event is not None
        on_event(
            {
                "agent_name": "deerflow",
                "step_name": "research",
                "event_type": "completed",
                "payload": {"message": "working"},
            }
        )
        return fake_result

    monkeypatch.setattr("src.dag_engine.nodes.dynamic_swarm_node.ensure_task_lease_owned", fake_lease_guard)
    monkeypatch.setattr("src.dag_engine.nodes.dynamic_swarm_node.DeerflowBridge.run", fake_run)
    monkeypatch.setattr("src.dag_engine.nodes.dynamic_swarm_node.event_bus.publish", lambda **kwargs: "evt-1")

    try:
        dynamic_swarm_node(
            {
                "tenant_id": tenant_id,
                "task_id": task_id,
                "workspace_id": "ws_dynamic_lease_abort",
                "input_query": "自己找数据并验证预测结论",
                "routing_mode": "dynamic",
                "complexity_score": 0.8,
                "lease_owner_id": "owner-a",
            }
        )
    except TaskLeaseLostError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("dynamic_swarm_node should stop on lease loss")


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
            inputs={
                "structured_datasets": [
                    {
                        "file_name": "sales.csv",
                        "path": str(csv_path),
                    }
                ],
            },
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
    assert restored.inputs.structured_datasets[0].dataset_schema
    assert restored.inputs.structured_datasets[0].load_kwargs == {}


def test_data_inspector_persists_partial_progress_before_later_failure(tmp_path, monkeypatch):
    tenant_id = "tenant_inspector_partial"
    task_id = global_blackboard.create_task(tenant_id, "ws_inspector_partial", "inspect dataset")
    first_csv = tmp_path / "sales_a.csv"
    second_csv = tmp_path / "sales_b.csv"
    first_csv.write_text("col1,col2\n1,2\n", encoding="utf-8")
    second_csv.write_text("col1,col2\n3,4\n", encoding="utf-8")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws_inspector_partial",
            inputs={
                "structured_datasets": [
                    {"file_name": "sales_a.csv", "path": str(first_csv)},
                    {"file_name": "sales_b.csv", "path": str(second_csv)},
                ],
            },
        ),
    )

    class _FakeDF:
        def to_markdown(self):
            return "|col|type|\n|---|---|\n|col1|BIGINT|"

    class _FakeConn:
        def execute(self, _query):
            class _FakeResult:
                def df(self_inner):
                    return _FakeDF()

            return _FakeResult()

    call_index = {"value": 0}

    def fake_connect(_dsn):
        call_index["value"] += 1
        if call_index["value"] == 1:
            return _FakeConn()
        raise RuntimeError("duckdb failed")

    monkeypatch.setattr("src.dag_engine.nodes.data_inspector.duckdb.connect", fake_connect)
    monkeypatch.setattr(
        "src.dag_engine.nodes.data_inspector.pd.read_csv",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("pandas failed")),
    )
    monkeypatch.setattr(
        "src.dag_engine.nodes.data_inspector.fast_llm_call",
        lambda prompt: (_ for _ in ()).throw(RuntimeError("llm failed")),
    )

    result = data_inspector_node(
        {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "workspace_id": "ws_inspector_partial",
            "input_query": "inspect dataset",
        }
    )

    assert result["blocked"] is True
    execution_blackboard._storage.clear()
    assert execution_blackboard.restore(tenant_id, task_id) is True
    restored = execution_blackboard.read(tenant_id, task_id)
    assert restored is not None
    assert restored.inputs.structured_datasets[0].dataset_schema
    assert restored.inputs.structured_datasets[1].dataset_schema == ""


def test_execute_task_flow_waits_for_human_when_kag_ingestion_blocks():
    result = execute_task_flow(
        {
            "tenant_id": "tenant-kag-block",
            "task_id": "task-kag-block",
            "workspace_id": "ws-kag-block",
            "input_query": "规则",
        },
        nodes={
            "router": lambda state: {"next_actions": ["kag_retriever"]},
            "dynamic_swarm": lambda state: {},
            "skill_harvester": lambda state: {},
            "summarizer": lambda state: {"final_response": {"mode": "static"}},
            "data_inspector": lambda state: {},
            "kag_retriever": lambda state: {
                "blocked": True,
                "block_reason": "knowledge build failed",
                "next_actions": ["wait_for_human"],
            },
            "context_builder": lambda state: (_ for _ in ()).throw(AssertionError("context_builder should not run")),
            "analyst": lambda state: {},
            "coder": lambda state: {},
            "auditor": lambda state: {},
            "debugger": lambda state: {},
            "executor": lambda state: {},
        },
    )

    assert result["terminal_status"] == "waiting_for_human"
    assert result["failure_type"] == "knowledge_ingestion"


def test_execute_task_flow_degrades_to_static_path_when_dynamic_is_denied():
    result = execute_task_flow(
        {
            "tenant_id": "tenant-dynamic-denied-fallback",
            "task_id": "task-dynamic-denied-fallback",
            "workspace_id": "ws-dynamic-denied-fallback",
            "input_query": "research then execute",
        },
        nodes={
            "router": lambda state: {
                "next_actions": ["dynamic_swarm"],
                "execution_intent": {"metadata": {}},
            },
            "dynamic_swarm": lambda state: {"dynamic_status": "denied", "dynamic_summary": "policy denied"},
            "skill_harvester": lambda state: {},
            "summarizer": lambda state: {"final_response": {"mode": "fallback"}, "observed_degrade_reason": state.get("degrade_reason")},
            "data_inspector": lambda state: {},
            "kag_retriever": lambda state: {},
            "context_builder": lambda state: {},
            "analyst": lambda state: {"analysis": "ok"},
            "coder": lambda state: {"code": "print('ok')"},
            "auditor": lambda state: {"next_actions": ["executor"]},
            "debugger": lambda state: {},
            "executor": lambda state: {"execution_record": {"success": True, "output": "ok"}},
        },
    )

    assert result["terminal_status"] == "waiting_for_human"
    assert result["failure_type"] == "dynamic_governance"
    assert result["error_message"] == "policy denied"


def test_execute_task_flow_degrades_to_static_path_when_dynamic_is_unavailable():
    result = execute_task_flow(
        {
            "tenant_id": "tenant-dynamic-unavailable-fallback",
            "task_id": "task-dynamic-unavailable-fallback",
            "workspace_id": "ws-dynamic-unavailable-fallback",
            "input_query": "research then execute",
        },
        nodes={
            "router": lambda state: {
                "next_actions": ["dynamic_swarm"],
                "execution_intent": {"metadata": {}},
            },
            "dynamic_swarm": lambda state: {"dynamic_status": "unavailable", "dynamic_summary": "runtime unavailable"},
            "skill_harvester": lambda state: {},
            "summarizer": lambda state: {"final_response": {"mode": "fallback"}},
            "data_inspector": lambda state: {"inspected": True},
            "kag_retriever": lambda state: {"blocked": False},
            "context_builder": lambda state: {"context_ready": True},
            "analyst": lambda state: {"analysis": "ok"},
            "coder": lambda state: {"code": "print('ok')"},
            "auditor": lambda state: {"next_actions": ["executor"]},
            "debugger": lambda state: {},
            "executor": lambda state: {"execution_record": {"success": True, "output": "ok"}},
        },
    )

    assert result["terminal_status"] == "failed"
    assert result["failure_type"] == "dynamic_runtime"
    assert result["error_message"] == "runtime unavailable"


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
            static={"generated_code": "print('ok')"},
        ),
    )

    calls = {}

    def fake_run_sync(**kwargs):
        calls.update(kwargs)
        return normalize_execution_result(
            {"success": True, "output": "ok", "artifacts_dir": "/tmp/out"},
            tenant_id=tenant_id,
            workspace_id="ws_exec",
            task_id=task_id,
        )

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
    assert result["execution_record"]["success"] is True


def test_executor_node_stops_before_persist_when_lease_is_lost_after_run(monkeypatch):
    tenant_id = "tenant_exec_lease_abort"
    task_id = global_blackboard.create_task(tenant_id, "ws_exec_lease_abort", "placeholder")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws_exec_lease_abort",
            static={"generated_code": "print('ok')"},
        ),
    )

    lease_checks = {"count": 0}

    def fake_lease_guard(task_id_arg, owner_id_arg):
        lease_checks["count"] += 1
        if lease_checks["count"] >= 3:
            raise TaskLeaseLostError("task lease lost after sandbox run")

    persisted = {"called": False}

    def fake_persist(tenant_id_arg, task_id_arg):
        persisted["called"] = True
        return True

    monkeypatch.setattr("src.dag_engine.nodes.executor_node.ensure_task_lease_owned", fake_lease_guard)
    monkeypatch.setattr(
        "src.dag_engine.nodes.executor_node.SandboxExecTool.run_sync",
        lambda **kwargs: normalize_execution_result(
            {"success": True, "output": "ok", "artifacts_dir": "/tmp/out"},
            tenant_id=tenant_id,
            workspace_id="ws_exec_lease_abort",
            task_id=task_id,
        ),
    )
    monkeypatch.setattr("src.dag_engine.nodes.executor_node.execution_blackboard.persist", fake_persist)

    try:
        executor_node(
            {
                "tenant_id": tenant_id,
                "task_id": task_id,
                "workspace_id": "ws_exec_lease_abort",
                "lease_owner_id": "owner-a",
            }
        )
    except TaskLeaseLostError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("executor_node should stop on lease loss")

    assert persisted["called"] is False


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
    MemoryRepo.clear()
    MemoryRepo.save_approved_skills(
        tenant_id,
        "ws_static",
        [
            {
                "name": "historical_skill_demo",
                "required_capabilities": ["knowledge_query"],
                "replay_cases": [{"case_id": "replay_hist_1"}],
                "promotion": {"status": "approved", "provenance": {"validation_status": "validated"}},
            }
        ],
    )
    task_id = global_blackboard.create_task(tenant_id, "ws_static", "总结报销规则")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws_static",
            inputs={
                "structured_datasets": [
                    {
                        "file_name": "sales.csv",
                        "path": "/tmp/sales.csv",
                        "dataset_schema": "col1,col2",
                        "load_kwargs": {"sep": ",", "encoding": "utf-8"},
                    }
                ],
            },
            knowledge={
                "business_context": {"rules": ["报销金额需含税"], "metrics": [], "filters": [], "sources": ["rule.pdf"]},
                "compiled": {
                    "rule_specs": [
                        {
                            "source_text": "报销金额需含税",
                            "normalized_text": "报销金额需含税",
                            "subject_terms": ["报销规则"],
                            "required_terms": ["合同"],
                            "prohibited_terms": [],
                            "temporal_constraints": [],
                            "causal_constraints": [],
                        }
                    ]
                },
            },
        ),
    )
    memory_blackboard.write(
        tenant_id,
        task_id,
        MemoryData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws_static",
            approved_skills=[
                {
                    "name": "approved_skill_demo",
                    "required_capabilities": ["knowledge_query"],
                    "promotion": {"status": "approved", "provenance": {"validation_status": "validated"}},
                }
            ],
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
    assert "任务类型:" in state["analysis_plan"]
    assert "证据引用:" in state["analysis_plan"]
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
    assert "compiled_knowledge" in state["generated_code"]
    persisted = memory_blackboard.read(tenant_id, task_id)
    persisted_execution = execution_blackboard.read(tenant_id, task_id)
    assert persisted is not None
    assert persisted_execution is not None
    assert persisted_execution.knowledge.analysis_brief.question == "总结报销规则"
    assert any(match.name == "historical_skill_demo" for match in persisted.historical_matches)
    historical_match = next(match for match in persisted.historical_matches if match.name == "historical_skill_demo")
    assert "analyst" in historical_match.selected_by_stages
    assert "coder" in historical_match.selected_by_stages
    assert historical_match.used_in_codegen is True
    assert historical_match.used_replay_case_ids
    assert "knowledge_query" in historical_match.used_capabilities
    assert state["input_mounts"][0]["container_path"].startswith("/app/inputs/")
    state.update(auditor_node(state))
    assert state["audit_result"]["safe"] is True
    assert state["next_actions"] == ["executor"]


def test_build_dataset_aware_code_executes_with_compiled_signal_globals():
    payload = {
        "query": "总结报销规则",
        "analysis_plan": "plan",
        "analysis_mode": "static",
        "analysis_brief": {},
        "business_context": {"rules": ["报销金额需含税"], "metrics": ["审批时效口径"], "filters": ["上海"]},
        "compiled_knowledge": {
            "rule_specs": [
                {
                    "source_text": "报销金额需含税",
                    "subject_terms": ["报销规则"],
                    "required_terms": ["合同"],
                    "prohibited_terms": [],
                }
            ],
            "metric_specs": [
                {
                    "source_text": "审批时效口径",
                    "metric_name": "审批时效口径",
                    "measure_terms": ["审批时效"],
                    "group_terms": ["contract_id"],
                }
            ],
            "filter_specs": [
                {
                    "source_text": "上海",
                    "field": "keyword",
                    "operator": "contains",
                    "value": "上海",
                    "preferred_date_terms": ["biz_date"],
                }
            ],
            "spec_parse_errors": [{"spec_kind": "rule", "error_code": "antlr_rule_parse_failed"}],
            "graph_compilation_summary": {"candidate_count": 3, "accepted_count": 2, "rejected_count": 1},
        },
        "approved_skills": [],
        "skill_strategy_hints": [],
        "refined_context_excerpt": "",
        "input_mounts": [],
        "structured_dataset_summaries": [],
    }
    code = build_dataset_aware_code(payload)
    namespace: dict[str, object] = {}
    exec(code, namespace)
    result = namespace["result"]
    assert result["status"] == "static_chain_generated"
    assert any("图谱编译摘要" in item for item in result["derived_findings"])
    assert any("编译态记录了" in item for item in result["derived_findings"])


def test_build_dataset_aware_code_uses_compiled_terms_for_document_keyword_hits(tmp_path):
    document_path = tmp_path / "rule.txt"
    document_path.write_text("上海合同审批规则说明。", encoding="utf-8")
    payload = {
        "query": "检查上海合同规则",
        "analysis_plan": "plan",
        "analysis_mode": "static",
        "analysis_brief": {},
        "business_context": {"rules": [], "metrics": [], "filters": []},
        "compiled_knowledge": {
            "rule_specs": [
                {
                    "source_text": "合同必须上传",
                    "subject_terms": ["合同"],
                    "required_terms": ["合同"],
                    "prohibited_terms": [],
                }
            ],
            "metric_specs": [],
            "filter_specs": [{"source_text": "上海", "field": "keyword", "operator": "contains", "value": "上海"}],
            "spec_parse_errors": [],
            "graph_compilation_summary": {},
        },
        "approved_skills": [],
        "skill_strategy_hints": [],
        "refined_context_excerpt": "",
        "input_mounts": [
            {
                "kind": "business_document",
                "file_name": "rule.txt",
                "container_path": str(document_path),
            }
        ],
        "structured_dataset_summaries": [],
    }
    code = build_dataset_aware_code(payload)
    namespace: dict[str, object] = {}
    exec(code, namespace)
    result = namespace["result"]
    assert result["documents"][0]["keyword_hits"]
    assert "合同" in result["documents"][0]["keyword_hits"] or "上海" in result["documents"][0]["keyword_hits"]


def test_build_dataset_aware_code_uses_spec_terms_for_metric_and_filter_checks(tmp_path):
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text(
        "contract_id,amount,duration_days,created_at,biz_date,city\n"
        "A,100,3,2023-12-31,2024-01-01,上海\n"
        "A,120,1,2024-01-02,2024-01-03,上海\n"
        "B,90,2,2024-01-04,2024-01-05,北京\n",
        encoding="utf-8",
    )
    payload = {
        "query": "检查审批时效和上海过滤",
        "analysis_plan": "plan",
        "analysis_mode": "static",
        "analysis_brief": {},
        "business_context": {"rules": [], "metrics": [], "filters": []},
        "compiled_knowledge": {
            "rule_specs": [],
            "metric_specs": [
                {
                    "source_text": "审批时效口径",
                    "metric_name": "审批时效口径",
                    "measure_terms": ["duration_days", "审批时效"],
                    "group_terms": ["contract_id"],
                    "preferred_date_terms": ["biz_date"],
                }
            ],
            "filter_specs": [{"source_text": "上海", "field": "keyword", "operator": "contains", "value": "上海"}],
            "spec_parse_errors": [],
            "graph_compilation_summary": {},
        },
        "approved_skills": [],
        "skill_strategy_hints": [],
        "refined_context_excerpt": "",
        "input_mounts": [
            {
                "kind": "structured_dataset",
                "file_name": "sales.csv",
                "container_path": str(csv_path),
                "encoding": "utf-8",
                "sep": ",",
            }
        ],
        "structured_dataset_summaries": [],
    }
    code = build_dataset_aware_code(payload)
    namespace: dict[str, object] = {}
    exec(code, namespace)
    result = namespace["result"]
    assert result["metric_checks"][0]["matched_columns"]
    assert "duration_days" in result["metric_checks"][0]["matched_columns"]
    assert result["metric_checks"][0]["matched_groups"]
    assert result["metric_checks"][0]["matched_groups"] == ["contract_id -> duration_days"]
    assert result["datasets"][0]["group_summaries"][0]["measure"] == "duration_days"
    assert result["datasets"][0]["group_summaries"][0]["group_by"] == "contract_id"
    assert result["datasets"][0]["date_profiles"][0]["column"] == "biz_date"
    assert len(result["datasets"][0]["date_profiles"]) == 1
    assert result["filter_checks"][0]["matched_datasets"]
    assert result["filter_checks"][0]["matched_values"]
    assert any("编译态优先指标列为 duration_days" in item for item in result["derived_findings"])
    assert any("编译态优先日期列为 biz_date" in item for item in result["derived_findings"])


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
            static={"latest_error_traceback": "bad import"},
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
            static={"generated_code": "import os\nos.system('ls')"},
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
            static={
                "analysis_plan": "plan",
                "execution_record": ExecutionRecord(
                    session_id="session-summary-static",
                    tenant_id=tenant_id,
                    workspace_id="ws_summary_static",
                    task_id=task_id,
                    success=True,
                    trace_id="trace-summary-static",
                    duration_seconds=0.2,
                    output='{"status":"ok","datasets":[{"file_name":"sales.csv","row_count":3,"columns":["a","tax_amount","contract_id","biz_date"],"numeric_profiles":[{"column":"a","mean":2.0}],"categorical_profiles":[{"column":"contract_id","top_values":[["A",2]]}],"date_profiles":[{"column":"biz_date","min":"2024-01-01T00:00:00","max":"2024-01-03T00:00:00"}],"group_summaries":[{"group_by":"contract_id","measure":"a","top_groups":[["A",4.0,2]]}],"missing_counts":{"a":0},"tax_missing_count":1,"contract_missing_count":1}],"documents":[{"file_name":"rule.txt","preview":"报销规则","keyword_hits":["报销规则","上海"]}],"derived_findings":["数据集 sales.csv 识别出 1 个数值列，可进行统计分析。","数据集 sales.csv 识别出 1 个日期列，可进行趋势/时序分析。","数据集 sales.csv 可按 contract_id 对 a 做分组统计。"],"rule_checks":[{"rule":"报销金额必须含税并上传合同","issue_count":2,"warnings":["sales.csv 存在 1 行税额缺失/为0","sales.csv 存在 1 行合同字段缺失"]}],"metric_checks":[{"metric":"审批时效口径","matched_columns":["a","biz_date"],"matched_groups":["contract_id -> a"],"matched_date_columns":["biz_date"],"highlights":["sales.csv.a mean=2.0","sales.csv.biz_date range=2024-01-01T00:00:00 -> 2024-01-03T00:00:00","sales.csv 按 contract_id 分组后，A 的 a 最高=4.0"]}],"filter_checks":[{"filter":"上海","matched_datasets":[],"matched_documents":["rule.txt"],"matched_date_ranges":["biz_date => 2024-01-01T00:00:00 -> 2024-01-03T00:00:00"]}]}',
                ),
            },
            knowledge={
                "business_context": {
                    "rules": ["rule1"],
                    "metrics": ["审批时效口径"],
                    "filters": ["上海"],
                    "sources": ["rule.pdf"],
                },
                "compiled": {
                    "rule_specs": [
                        {
                            "source_text": "报销金额必须含税并上传合同",
                            "normalized_text": "报销金额必须含税并上传合同",
                            "subject_terms": ["合同"],
                            "required_terms": ["合同"],
                            "prohibited_terms": [],
                            "temporal_constraints": [],
                            "causal_constraints": [],
                        }
                    ],
                    "metric_specs": [
                        {
                            "source_text": "审批时效口径",
                            "normalized_text": "审批时效口径",
                            "metric_name": "审批时效口径",
                            "measure_terms": ["审批时效"],
                            "group_terms": ["contract_id"],
                            "preferred_date_terms": ["biz_date"],
                            "temporal_constraints": [{"anchor_type": "year", "value": "2024", "source_text": "审批时效口径"}],
                        }
                    ],
                    "filter_specs": [
                        {
                            "source_text": "上海",
                            "normalized_text": "上海",
                            "field": "keyword",
                            "operator": "contains",
                            "value": "上海",
                            "preferred_date_terms": ["biz_date"],
                            "temporal_constraints": [{"anchor_type": "year", "value": "2024", "source_text": "上海"}],
                        }
                    ],
                    "graph_compilation_summary": {
                        "candidate_count": 3,
                        "accepted_count": 2,
                        "rejected_count": 1,
                        "reject_reasons": {"missing_causal_marker": 1},
                    },
                },
                "knowledge_snapshot": {
                    "rewritten_query": "报销 规则 上海",
                    "recall_strategies": ["bm25", "vector"],
                    "cache_hit": True,
                    "metadata": {
                        "selected_count": 2,
                        "preferred_date_terms": ["biz_date"],
                        "temporal_constraints": ["2024"],
                    },
                    "evidence_refs": ["chunk-1"],
                },
            },
            inputs={
                "business_documents": [
                    {
                        "file_name": "rule.pdf",
                        "path": "/tmp/rule.pdf",
                        "status": "parsed",
                        "parse_mode": "ocr+vision",
                        "parser_diagnostics": {"image_description_count": 2},
                    }
                ]
            },
        ),
    )
    memory_blackboard.write(
        tenant_id,
        task_id,
        MemoryData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="ws_summary_static",
            approved_skills=[
                {
                    "name": "approved_skill_demo",
                    "required_capabilities": ["knowledge_query"],
                    "promotion": {"status": "approved", "provenance": {"validation_status": "validated"}},
                }
            ],
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
    assert any("编译态优先日期列" in item for item in result["final_response"]["key_findings"])
    assert any("检索偏好日期列" in item for item in result["final_response"]["key_findings"])
    assert result["final_response"]["details"]["rule_checks"][0]["issue_count"] == 2
    assert result["final_response"]["details"]["metric_checks"][0]["metric"] == "审批时效口径"
    assert result["final_response"]["details"]["metric_checks"][0]["matched_groups"][0] == "contract_id -> a"
    assert result["final_response"]["details"]["filter_checks"][0]["filter"] == "上海"
    assert result["final_response"]["details"]["knowledge_snapshot"]["rewritten_query"] == "报销 规则 上海"
    assert result["final_response"]["details"]["knowledge_snapshot"]["metadata"]["preferred_date_terms"] == ["biz_date"]
    assert result["final_response"]["details"]["analysis_brief"]["question"] == ""
    assert result["final_response"]["details"]["compiled_knowledge"]["rule_specs"][0]["source_text"] == "报销金额必须含税并上传合同"
    assert result["final_response"]["details"]["compiled_knowledge"]["graph_compilation_summary"]["accepted_count"] == 2
    assert result["final_response"]["details"]["approved_skills"][0]["name"] == "approved_skill_demo"
    assert result["final_response"]["details"]["skill_strategy_hints"][0]["name"] == "approved_skill_demo"
    assert result["final_response"]["details"]["used_historical_skills"] == []
    assert any("税额缺失" in item for item in result["final_response"]["caveats"])
    assert any("指标提示" in item for item in result["final_response"]["caveats"])
    assert any("日期范围" in item for item in result["final_response"]["caveats"])
    assert any("编译态时间约束" in item for item in result["final_response"]["caveats"])
    assert any("检索时间约束" in item for item in result["final_response"]["caveats"])
    assert result["final_response"]["key_findings"]
    assert any("知识检索通道" in item for item in result["final_response"]["key_findings"])
    assert any("编译态规则规格" in item for item in result["final_response"]["key_findings"])


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
            dynamic={
                "summary": "dynamic done",
                "status": "completed",
                "trace_refs": ["trace-1"],
                "artifacts": ["/tmp/a.md"],
            },
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
    assert result["final_response"]["details"]["analysis_brief"]["question"] == ""
    assert result["final_response"]["outputs"][0]["path"] is None
    assert result["final_response"]["outputs"][0]["summary"] == "/tmp/a.md"
    assert result["final_response"]["key_findings"]
