"""
LangGraph 状态图定义
"""

import operator
from typing import Annotated, Any, TypedDict


class DagGraphState(TypedDict, total=False):
    """
    DAG 运行时的“瞬时传输态”。

    这里刻意强调边界：
    - 持久化主状态在 `ExecutionData`
    - `DagGraphState` 只描述节点之间临时传递、或在当前轮执行里
      需要被显式合并的 patch 字段

    也就是说，它不是另一个 blackboard schema，不负责成为第二真源。
    """

    # --------------------------
    # 基础身份
    # --------------------------
    tenant_id: str
    task_id: str
    workspace_id: str
    input_query: str

    # --------------------------
    # 控制面 / 契约投影
    # --------------------------
    task_envelope: dict[str, Any]
    execution_intent: dict[str, Any]
    execution_snapshot: dict[str, Any]
    allowed_tools: list[str]
    governance_profile: str
    redaction_rules: list[str]
    token_budget: int
    max_dynamic_steps: int
    routing_mode: str
    complexity_score: float
    dynamic_reason: str | None
    decision_log: list[dict[str, Any]]
    runtime_backend: str

    # --------------------------
    # 静态知识链 / 上下文链
    # --------------------------
    # 传给 context_builder_node.py 的检索生肉：
    # [{"text": text, "score": score, "source": "...", "type": "fast_path_injection"}]
    raw_retrieved_candidates: list[dict[str, Any]]
    knowledge_snapshot: dict[str, Any]
    memory_snapshot: dict[str, Any]
    analysis_brief: dict[str, Any]
    # 经过压缩后的精炼 Markdown 文本
    refined_context: str
    analysis_plan: str
    generated_code: str
    execution_strategy: dict[str, Any]
    static_evidence_bundle: dict[str, Any]
    program_spec: dict[str, Any]
    repair_plan: dict[str, Any]
    debug_attempts: list[dict[str, Any]]
    generator_manifest: dict[str, Any]
    artifact_plan: dict[str, Any]
    verification_plan: dict[str, Any]
    artifact_verification: dict[str, Any]
    input_mounts: list[dict[str, Any]]
    audit_result: dict[str, Any]
    execution_record: dict[str, Any]

    # --------------------------
    # 动态链写回 patch
    # --------------------------
    next_actions: Annotated[list[str], operator.add]
    dynamic_request: dict[str, Any]
    dynamic_status: str
    dynamic_summary: str
    dynamic_continuation: str
    dynamic_resume_overlay: dict[str, Any]
    dynamic_next_static_steps: list[str]
    dynamic_trace: list[dict[str, Any]]
    dynamic_trace_refs: list[str]
    dynamic_artifacts: list[str]
    dynamic_research_findings: list[str]
    dynamic_evidence_refs: list[str]
    dynamic_open_questions: list[str]
    dynamic_suggested_static_actions: list[str]
    recommended_static_skill: dict[str, Any]

    # --------------------------
    # 中断 / 重试 / 终态 patch
    # --------------------------
    blocked: bool
    block_reason: str | None
    retry_count: int
    final_response: dict[str, Any]
