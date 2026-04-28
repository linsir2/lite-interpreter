from unittest.mock import patch

from src.blackboard import ExecutionData
from src.runtime import build_analysis_brief, resolve_runtime_decision


def test_runtime_decision_classifies_dataset_analysis():
    exec_data = ExecutionData(
        tenant_id="tenant",
        task_id="task",
        inputs={
            "structured_datasets": [
                {"file_name": "sales.csv", "path": "/tmp/sales.csv", "dataset_schema": "region,amount"}
            ]
        },
    )

    decision = resolve_runtime_decision(
        call_purpose="routing_assess",
        query="分析销售数据并统计趋势",
        exec_data=exec_data,
        allowed_tools=["knowledge_query"],
    )

    assert decision.analysis_mode == "dataset_analysis"
    assert decision.routing_mode == "static"
    assert decision.model_alias == "fast_model"
    assert decision.final_mode == "static"
    assert decision.research_mode == "none"
    assert decision.destinations == ("analyst",)
    assert decision.route_candidates == ("static",)
    assert decision.routing_stage == "coarse"
    assert decision.fine_routing_invoked is False


def test_runtime_decision_classifies_dynamic_research():
    decision = resolve_runtime_decision(
        call_purpose="dynamic_research",
        query="结合财报和宏观经济数据自己找资料做 benchmark",
        allowed_tools=["web_search", "web_fetch"],
    )

    assert decision.analysis_mode == "dynamic_research_analysis"
    assert decision.research_mode == "iterative"
    assert decision.routing_mode == "dynamic"
    assert decision.final_mode == "dynamic"
    assert decision.coarse_mode == "dynamic"
    assert decision.destinations == ("dynamic_swarm",)
    assert decision.continuation == "finish"
    assert decision.next_static_steps == ()
    assert decision.requires_external_research is True
    assert decision.routing_stage in {"coarse", "fine", "fallback"}
    assert "外部事实核验" in decision.known_gaps[0] or "联网检索" in "".join(decision.known_gaps)


def test_runtime_decision_routes_macro_outlook_queries_to_dynamic_research():
    decision = resolve_runtime_decision(
        call_purpose="routing_assess",
        query="分析当前美国的经济走向",
        allowed_tools=["web_search", "web_fetch"],
    )

    assert decision.analysis_mode == "dynamic_research_analysis"
    assert decision.final_mode == "dynamic"
    assert decision.destinations == ("dynamic_swarm",)


def test_runtime_decision_prefers_document_rule_analysis_for_rule_only_query():
    decision = resolve_runtime_decision(
        call_purpose="routing_assess",
        query="请解释审批口径和合同上传规则",
        allowed_tools=[],
    )

    assert decision.analysis_mode == "document_rule_analysis"
    assert decision.final_mode == "static"
    assert decision.research_mode == "none"
    assert decision.continuation == "finish"


def test_runtime_decision_marks_hybrid_mode_and_metadata():
    exec_data = ExecutionData(
        tenant_id="tenant",
        task_id="task",
        inputs={
            "structured_datasets": [{"file_name": "expenses.csv", "path": "/tmp/expenses.csv"}],
            "business_documents": [{"file_name": "policy.pdf", "path": "/tmp/policy.pdf", "status": "parsed"}],
        },
        knowledge={"business_context": {"rules": ["合同必须上传"]}},
    )

    decision = resolve_runtime_decision(
        call_purpose="routing_assess",
        query="结合费用数据和制度规则检查异常",
        exec_data=exec_data,
        allowed_tools=["knowledge_query"],
    )

    assert decision.analysis_mode == "hybrid_analysis"
    assert decision.final_mode == "hybrid"
    assert decision.research_mode == "none"
    assert decision.destinations == ("data_inspector",)
    assert decision.route_candidates == ("hybrid", "static")
    assert decision.requires_static_execution is True


def test_runtime_decision_uses_refine_model_alias_from_runtime_boundary():
    policy = {
        "call_purposes": {
            "routing_assess": {"model_alias": "fast_model"},
            "routing_refine": {"model_alias": "reasoning_model"},
        },
        "profiles": {
            "dataset_analysis": {"evidence_strategy": "dataset_first", "routing_mode": "static"},
            "document_rule_analysis": {"evidence_strategy": "rules_first", "routing_mode": "static"},
            "hybrid_analysis": {"evidence_strategy": "dataset_and_rules", "routing_mode": "static"},
            "dynamic_research_analysis": {"evidence_strategy": "external_research", "routing_mode": "dynamic"},
            "need_more_inputs": {"evidence_strategy": "input_gap", "routing_mode": "static"},
        },
        "fine_routing": {"enabled": True, "ambiguity_threshold": 0.1, "min_candidate_count": 2},
        "dynamic_patterns": ["财报", "宏观", "自己找数据"],
        "dataset_keywords": [],
        "document_keywords": [],
    }

    with patch("src.runtime.analysis_runtime.load_analysis_runtime_policy", return_value=policy):
        with patch("src.runtime.analysis_runtime._fine_routing_runtime_enabled", return_value=True):
            with patch(
                "src.runtime.analysis_runtime.run_route_selection",
                return_value=type(
                    "RouteResult",
                    (),
                    {
                        "payload": {"final_mode": "dynamic", "confidence": 0.96, "rationale": "keep dynamic"},
                        "degraded": False,
                        "degrade_reason": "",
                    },
                )(),
            ) as mocked_route:
                decision = resolve_runtime_decision(
                    call_purpose="routing_assess",
                    query="帮我分析财报并结合宏观经济自己找数据验证",
                    state={"task_envelope": {"metadata": {"model_overrides": {"routing_refine": "fast_model"}}}},
                    allowed_tools=["web_search"],
                )

    assert mocked_route.call_args.kwargs["model_alias"] == "fast_model"
    assert decision.routing_stage == "fine"
    assert decision.model_alias == "fast_model"


def test_runtime_decision_marks_fallback_when_refine_unavailable():
    policy = {
        "call_purposes": {
            "routing_assess": {"model_alias": "fast_model"},
            "routing_refine": {"model_alias": "reasoning_model"},
        },
        "profiles": {
            "dataset_analysis": {"evidence_strategy": "dataset_first", "routing_mode": "static"},
            "document_rule_analysis": {"evidence_strategy": "rules_first", "routing_mode": "static"},
            "hybrid_analysis": {"evidence_strategy": "dataset_and_rules", "routing_mode": "static"},
            "dynamic_research_analysis": {"evidence_strategy": "external_research", "routing_mode": "dynamic"},
            "need_more_inputs": {"evidence_strategy": "input_gap", "routing_mode": "static"},
        },
        "fine_routing": {"enabled": True, "ambiguity_threshold": 0.1, "min_candidate_count": 2},
        "dynamic_patterns": ["财报", "宏观", "自己找数据"],
        "dataset_keywords": [],
        "document_keywords": [],
    }

    with patch("src.runtime.analysis_runtime.load_analysis_runtime_policy", return_value=policy):
        with patch("src.runtime.analysis_runtime._fine_routing_runtime_enabled", return_value=True):
            with patch("src.runtime.analysis_runtime.run_route_selection", side_effect=RuntimeError("boom")):
                decision = resolve_runtime_decision(
                    call_purpose="routing_assess",
                    query="帮我分析财报并结合宏观经济自己找数据验证",
                    state={"task_envelope": {"metadata": {"model_overrides": {"routing_refine": "fast_model"}}}},
                    allowed_tools=["web_search"],
                )

    assert decision.routing_stage == "fallback"
    assert decision.routing_degraded is True
    assert decision.final_mode == "dynamic"


def test_runtime_decision_keeps_coarse_when_fine_routing_lacks_credentials():
    policy = {
        "call_purposes": {
            "routing_assess": {"model_alias": "fast_model"},
            "routing_refine": {"model_alias": "reasoning_model"},
        },
        "profiles": {
            "dataset_analysis": {"evidence_strategy": "dataset_first", "routing_mode": "static"},
            "document_rule_analysis": {"evidence_strategy": "rules_first", "routing_mode": "static"},
            "hybrid_analysis": {"evidence_strategy": "dataset_and_rules", "routing_mode": "static"},
            "dynamic_research_analysis": {"evidence_strategy": "external_research", "routing_mode": "dynamic"},
            "need_more_inputs": {"evidence_strategy": "input_gap", "routing_mode": "static"},
        },
        "fine_routing": {"enabled": True, "ambiguity_threshold": 0.1, "min_candidate_count": 2},
        "dynamic_patterns": ["财报", "宏观", "自己找数据"],
        "dataset_keywords": [],
        "document_keywords": [],
    }

    with patch("src.runtime.analysis_runtime.load_analysis_runtime_policy", return_value=policy):
        with patch("src.runtime.analysis_runtime._fine_routing_runtime_enabled", return_value=False):
            decision = resolve_runtime_decision(
                call_purpose="routing_assess",
                query="帮我分析财报并结合宏观经济自己找数据验证",
                allowed_tools=["web_search"],
            )

    assert decision.routing_stage == "coarse"
    assert decision.fine_routing_invoked is False
    assert decision.model_alias == "fast_model"


def test_build_analysis_brief_keeps_dataset_rules_and_evidence_refs():
    exec_data = ExecutionData(
        tenant_id="tenant",
        task_id="task",
        inputs={
            "structured_datasets": [
                {"file_name": "expenses.csv", "path": "/tmp/expenses.csv", "dataset_schema": "contract_id,tax_amount"}
            ]
        },
        knowledge={
            "business_context": {
                "rules": ["合同必须上传"],
                "metrics": ["审批时效"],
                "filters": ["上海"],
            }
        },
    )

    brief = build_analysis_brief(
        query="结合费用数据和规则检查合同缺失",
        exec_data=exec_data,
        knowledge_snapshot={"evidence_refs": ["rule-1"]},
        analysis_mode="hybrid_analysis",
        known_gaps=[],
    )

    assert brief.analysis_mode == "hybrid_analysis"
    assert brief.dataset_summaries
    assert brief.business_rules == ("合同必须上传",)
    assert brief.evidence_refs == ("rule-1",)


def test_runtime_decision_routes_single_pass_external_verification_to_static():
    exec_data = ExecutionData(
        tenant_id="tenant",
        task_id="task",
        inputs={
            "structured_datasets": [{"file_name": "sales.csv", "path": "/tmp/sales.csv", "dataset_schema": "month,revenue"}]
        },
    )

    decision = resolve_runtime_decision(
        call_purpose="routing_assess",
        query="查一个公开数据，对比一下我们和行业平均增速，再做计算",
        exec_data=exec_data,
        allowed_tools=["web_search", "web_fetch", "knowledge_query"],
    )

    assert decision.final_mode == "static"
    assert decision.research_mode == "single_pass"
    assert decision.destinations == ("analyst",)
    assert decision.requires_external_research is True
