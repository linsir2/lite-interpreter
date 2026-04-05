"""
LangGraph 状态图定义
"""
from typing import TypedDict, Annotated, List, Optional, Dict, Any
import operator

class DagGraphState(TypedDict, total=False):
    tenant_id: str
    task_id: str
    workspace_id: str

    input_query: str

    # 传给context_builder_node.py
    # [{"text": text, "score": score, "source": os.path.basename(doc["path"]), "type": "fast_path_injection"}]
    raw_retrieved_candidates: List[Dict[str, Any]] 

    # 🚀 【熟肉区】：由 context_builder 节点输出
    # 格式：经过 LLM 降噪、去重、压缩后的精炼 Markdown 文本
    refined_context: str

    next_actions: Annotated[List[str], operator.add]
    routing_mode: str
    complexity_score: float
    dynamic_reason: Optional[str]
    candidate_skills: List[Dict[str, Any]]
    token_budget: int
    max_dynamic_steps: int
    allowed_tools: List[str]
    redaction_rules: List[str]
    governance_mode: str
    governance_profile: str
    governance_decisions: List[Dict[str, Any]]
    decision_log: List[Dict[str, Any]]
    governance_trace_ref: Optional[str]
    task_envelope: Dict[str, Any]
    execution_intent: Dict[str, Any]
    execution_record: Dict[str, Any]
    runtime_backend: str
    knowledge_snapshot: Dict[str, Any]
    execution_snapshot: Dict[str, Any]
    dynamic_request: Dict[str, Any]
    dynamic_status: str
    dynamic_summary: str
    dynamic_trace: List[Dict[str, Any]]
    dynamic_trace_refs: List[str]
    dynamic_artifacts: List[str]
    recommended_static_skill: Dict[str, Any]
    harvested_skill_candidates: List[Dict[str, Any]]
    approved_skills: List[Dict[str, Any]]
    historical_skill_matches: List[Dict[str, Any]]
    return_to_node: str
    final_response: Dict[str, Any]
    blocked: bool
    block_reason: Optional[str]

    retry_count: int
    current_error_type: Optional[str]
