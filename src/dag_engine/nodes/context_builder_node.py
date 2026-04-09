"""Context Builder：把检索生肉压缩成 Analyst 可直接消费的业务上下文。"""

from __future__ import annotations

from typing import Any

from config.settings import CONTEXT_MAX_TOKENS

from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.knowledge_blackboard import knowledge_blackboard
from src.blackboard.schema import BusinessContextState, KnowledgeData, KnowledgeSnapshotState
from src.common import fit_items_to_budget, get_logger
from src.common.control_plane import knowledge_evidence_refs
from src.common.llm_client import LiteLLMClient
from src.dag_engine.graphstate import DagGraphState
from src.kag.context.compressor import ContextCompressor
from src.kag.context.formatter import ContextFormatter
from src.kag.context.selector import ContextSelector
from src.runtime import build_analysis_brief, resolve_runtime_decision

logger = get_logger(__name__)


def context_builder_node(state: DagGraphState) -> dict[str, Any]:
    tenant_id = state["tenant_id"]
    task_id = state["task_id"]
    query = state["input_query"]
    raw_candidates = list(state.get("raw_retrieved_candidates", []) or [])
    knowledge_snapshot = dict(state.get("knowledge_snapshot", {}) or {})

    exec_data = execution_blackboard.read(tenant_id, task_id)
    if not exec_data:
        logger.warning(f"[ContextBuilder] 找不到任务 {task_id} 的执行上下文")
        return {"refined_context": "", "next_actions": ["analyst"]}
    knowledge_data = knowledge_blackboard.read(tenant_id, task_id)
    if knowledge_data is None and knowledge_blackboard.restore(tenant_id, task_id):
        knowledge_data = knowledge_blackboard.read(tenant_id, task_id)
    if knowledge_data is None:
        knowledge_data = KnowledgeData(task_id=task_id, tenant_id=tenant_id, workspace_id=exec_data.workspace_id)
        knowledge_data.business_documents = list(exec_data.inputs.business_documents)

    if not raw_candidates and exec_data.knowledge.knowledge_snapshot.hits:
        raw_candidates = list(exec_data.knowledge.knowledge_snapshot.hits or [])
    if not raw_candidates and knowledge_snapshot.get("hits"):
        raw_candidates = list(knowledge_snapshot.get("hits", []) or [])

    runtime_decision = resolve_runtime_decision(
        call_purpose="context_compress",
        query=query,
        state=state,
        exec_data=exec_data,
        allowed_tools=list(state.get("allowed_tools") or []),
    )
    selected = ContextSelector.select(raw_candidates)
    compressed = ContextCompressor.compress(query, selected, model_alias=runtime_decision.model_alias)
    model_name = LiteLLMClient.resolve_model_name(runtime_decision.model_alias)
    compressed = fit_items_to_budget(
        compressed,
        budget_tokens=state.get("token_budget") or CONTEXT_MAX_TOKENS,
        base_messages=[{"role": "user", "content": query}],
        model_name=model_name,
        render_item=lambda item: (
            f"来源: {item.get('source', 'unknown')}\n"
            f"通道: {item.get('retrieval_type', 'text')}\n"
            f"内容: {item.get('compressed_text') or item.get('text') or ''}"
        ),
    )
    business_context, refined_context = ContextFormatter.format(compressed)
    business_context_state = BusinessContextState.model_validate(business_context)
    exec_data.knowledge.business_context = business_context_state
    analysis_brief = build_analysis_brief(
        query=query,
        exec_data=exec_data,
        knowledge_snapshot=knowledge_snapshot
        or {"evidence_refs": [item.get("chunk_id") for item in compressed if item.get("chunk_id")]},
        business_context=business_context_state.model_dump(mode="json"),
        analysis_mode=runtime_decision.analysis_mode,
        known_gaps=runtime_decision.known_gaps,
        recommended_next_step="先核对证据与规则，再生成模板化数据分析代码",
    )

    exec_data.knowledge.analysis_brief = analysis_brief.to_payload()
    snapshot_payload = knowledge_snapshot or exec_data.knowledge.knowledge_snapshot.model_dump(mode="json")
    metadata = dict(snapshot_payload.get("metadata", {}) or {})
    metadata.update(
        {
            "selected_count": len(selected),
            "compressed_count": len(compressed),
            "compression_strategy": "extractive_ranked_sentences",
            "pinned_evidence_refs": list(analysis_brief.evidence_refs),
            "dropped_candidate_count": max(0, len(raw_candidates) - len(compressed)),
            "analysis_mode": runtime_decision.analysis_mode,
            "evidence_strategy": runtime_decision.evidence_strategy,
        }
    )
    snapshot_payload["metadata"] = metadata
    if "hits" not in snapshot_payload:
        snapshot_payload["hits"] = list(raw_candidates)
    if not knowledge_evidence_refs(snapshot_payload):
        snapshot_payload["evidence_refs"] = [
            str(item) for item in [item.get("chunk_id") for item in compressed if item.get("chunk_id")] if item
        ]
    snapshot = KnowledgeSnapshotState.model_validate(snapshot_payload)
    exec_data.knowledge.knowledge_snapshot = snapshot
    knowledge_data.latest_retrieval_snapshot = snapshot
    execution_blackboard.write(tenant_id, task_id, exec_data)
    execution_blackboard.persist(tenant_id, task_id)
    knowledge_blackboard.write(tenant_id, task_id, knowledge_data)
    knowledge_blackboard.persist(tenant_id, task_id)

    logger.info(f"[ContextBuilder] 构建上下文完成，候选 {len(raw_candidates)} -> {len(compressed)}")
    return {
        "refined_context": refined_context,
        "analysis_brief": analysis_brief.to_payload(),
        "knowledge_snapshot": snapshot.model_dump(mode="json"),
        "next_actions": ["analyst"],
    }
