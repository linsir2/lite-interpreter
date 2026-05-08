"""Seed evaluation cases for the data-analysis workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    description: str
    query: str
    expected_intent: str  # "static_flow" or "dynamic_flow"
    expected_route: str
    structured_datasets: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    business_documents: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    business_context: dict[str, Any] = field(default_factory=dict)
    knowledge_hits: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    expected_evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    allowed_tools: tuple[str, ...] = field(default_factory=tuple)
    expected_known_gap_substrings: tuple[str, ...] = field(default_factory=tuple)
    expected_dataset_summary_min: int = 0


SEED_EVAL_CASES: tuple[EvalCase, ...] = (
    EvalCase(
        case_id="route_dataset_only",
        description="Structured dataset questions should stay on the static data-analysis path.",
        query="分析这份销售数据，统计各地区销售额并给出趋势结论",
        expected_intent="static_flow",
        expected_route="analyst",
        structured_datasets=(
            {"file_name": "sales.csv", "path": "/tmp/sales.csv", "dataset_schema": "region,amount,biz_date"},
        ),
    ),
    EvalCase(
        case_id="route_rules_only",
        description="Document-based questions should stay on the static path when business documents are present.",
        query="请解释报销制度里的审批时效口径和合同上传要求",
        expected_intent="static_flow",
        expected_route="analyst",
        business_documents=({"file_name": "rule.pdf", "path": "/tmp/rule.pdf", "status": "parsed"},),
    ),
    EvalCase(
        case_id="route_hybrid",
        description="Dataset plus business document questions stay on the static path.",
        query="结合费用数据和报销制度，核对哪些记录违反了含税和合同规则",
        expected_intent="static_flow",
        expected_route="analyst",
        structured_datasets=({"file_name": "expenses.csv", "path": "/tmp/expenses.csv"},),
        business_documents=({"file_name": "policy.pdf", "path": "/tmp/policy.pdf", "status": "parsed"},),
    ),
    EvalCase(
        case_id="route_dynamic_research",
        description="External research style tasks should escalate to the bounded dynamic node.",
        query="帮我分析这份财报，并结合宏观经济数据自己找资料做 benchmark 后给出判断",
        expected_intent="dynamic_flow",
        expected_route="dynamic_swarm",
    ),
    EvalCase(
        case_id="route_need_inputs",
        description="Questions with no usable dataset or rule input route to analyst for gap detection.",
        query="帮我做一份费用异常分析",
        expected_intent="static_flow",
        expected_route="analyst",
    ),
    EvalCase(
        case_id="route_dataset_dynamic_signal",
        description="With a dataset, queries with external signals stay static — analyst decides capability tier.",
        query="基于这份销售数据自己找行业公开数据做benchmark并验证趋势结论",
        expected_intent="static_flow",
        expected_route="analyst",
        structured_datasets=(
            {"file_name": "sales.csv", "path": "/tmp/sales.csv", "dataset_schema": "region,amount,biz_date"},
        ),
    ),
    EvalCase(
        case_id="route_rules_without_doc_asset",
        description="Queries with external-domain signals (合规) and no local data route to dynamic.",
        query="请说明审批口径和合规规则",
        expected_intent="dynamic_flow",
        expected_route="dynamic_swarm",
    ),
    EvalCase(
        case_id="route_hybrid_with_known_rules",
        description="Dataset questions with extracted business context remain static — analyst refines capability tier.",
        query="结合当前数据和已抽取规则，检查合同缺失与税额缺失问题",
        expected_intent="static_flow",
        expected_route="analyst",
        structured_datasets=(
            {"file_name": "expenses.csv", "path": "/tmp/expenses.csv", "dataset_schema": "contract_id,tax_amount"},
        ),
        business_documents=({"file_name": "policy.pdf", "path": "/tmp/policy.pdf", "status": "parsed"},),
        business_context={"rules": ["合同必须上传"], "metrics": ["审批时效"], "filters": []},
    ),
    EvalCase(
        case_id="context_evidence_pinning",
        description="Context building must preserve evidence refs when knowledge hits provide rules and metrics.",
        query="请总结报销规则和指标口径",
        expected_intent="static_flow",
        expected_route="analyst",
        knowledge_hits=(
            {
                "chunk_id": "c1",
                "text": "报销规则：发票金额必须含税。",
                "score": 1.0,
                "source": "rule.pdf",
                "retrieval_type": "bm25",
            },
            {
                "chunk_id": "c2",
                "text": "指标口径：审批时效按提交到通过计算。",
                "score": 0.9,
                "source": "metric.pdf",
                "retrieval_type": "vector",
            },
        ),
        expected_evidence_refs=("c1", "c2"),
    ),
    EvalCase(
        case_id="context_dataset_plus_rule",
        description="Mixed-material context briefs must keep both evidence refs and dataset/rule summaries.",
        query="结合费用数据和规则，检查合同缺失",
        expected_intent="static_flow",
        expected_route="analyst",
        structured_datasets=(
            {"file_name": "expenses.csv", "path": "/tmp/expenses.csv", "dataset_schema": "contract_id,tax_amount"},
        ),
        business_documents=({"file_name": "policy.pdf", "path": "/tmp/policy.pdf", "status": "parsed"},),
        business_context={"rules": ["必须上传合同"], "metrics": [], "filters": []},
        knowledge_hits=(
            {
                "chunk_id": "rule-1",
                "text": "规则：必须上传合同。",
                "score": 1.0,
                "source": "policy.pdf",
                "retrieval_type": "bm25",
            },
        ),
        expected_evidence_refs=("rule-1",),
        expected_dataset_summary_min=1,
    ),
)
