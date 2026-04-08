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


def test_runtime_decision_classifies_dynamic_research():
    decision = resolve_runtime_decision(
        call_purpose="dynamic_research",
        query="结合财报和宏观经济数据自己找资料做 benchmark",
        allowed_tools=["web_search", "web_fetch"],
    )

    assert decision.analysis_mode == "dynamic_research_analysis"
    assert decision.routing_mode == "dynamic"
    assert "外部事实核验" in decision.known_gaps[0] or "联网检索" in "".join(decision.known_gaps)


def test_runtime_decision_prefers_document_rule_analysis_for_rule_only_query():
    decision = resolve_runtime_decision(
        call_purpose="routing_assess",
        query="请解释审批口径和合同上传规则",
        allowed_tools=[],
    )

    assert decision.analysis_mode == "document_rule_analysis"


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
