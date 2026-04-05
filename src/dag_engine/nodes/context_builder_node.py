"""Context Builder：把检索生肉压缩成 Analyst 可直接消费的业务上下文。"""
from __future__ import annotations

from typing import Any, Dict

from src.blackboard.execution_blackboard import execution_blackboard
from config.settings import CONTEXT_MAX_TOKENS, CONTEXT_MODEL_NAME
from src.common import fit_items_to_budget, get_logger
from src.common.llm_client import LiteLLMClient
from src.dag_engine.graphstate import DagGraphState
from src.kag.context.compressor import ContextCompressor
from src.kag.context.formatter import ContextFormatter
from src.kag.context.selector import ContextSelector

logger = get_logger(__name__)


def context_builder_node(state: DagGraphState) -> Dict[str, Any]:
    tenant_id = state["tenant_id"]
    task_id = state["task_id"]
    query = state["input_query"]
    raw_candidates = list(state.get("raw_retrieved_candidates", []) or [])
    knowledge_snapshot = dict(state.get("knowledge_snapshot", {}) or {})

    exec_data = execution_blackboard.read(tenant_id, task_id)
    if not exec_data:
        logger.warning(f"[ContextBuilder] 找不到任务 {task_id} 的执行上下文")
        return {"refined_context": "", "next_actions": ["analyst"]}

    if not raw_candidates and exec_data.knowledge_snapshot.get("hits"):
        raw_candidates = list(exec_data.knowledge_snapshot.get("hits", []) or [])
    if not raw_candidates and knowledge_snapshot.get("hits"):
        raw_candidates = list(knowledge_snapshot.get("hits", []) or [])

    selected = ContextSelector.select(raw_candidates)
    compressed = ContextCompressor.compress(query, selected)
    model_name = LiteLLMClient.resolve_model_name(CONTEXT_MODEL_NAME)
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

    exec_data.business_context = business_context
    exec_data.business_context_refs = [
        str(item)
        for item in (
            knowledge_snapshot.get("evidence_refs")
            or exec_data.knowledge_snapshot.get("evidence_refs")
            or [item.get("chunk_id") for item in compressed if item.get("chunk_id")]
        )
        if item
    ]
    snapshot = knowledge_snapshot or dict(exec_data.knowledge_snapshot or {})
    metadata = dict(snapshot.get("metadata", {}) or {})
    metadata.update(
        {
            "selected_count": len(selected),
            "compressed_count": len(compressed),
        }
    )
    snapshot["metadata"] = metadata
    if "hits" not in snapshot:
        snapshot["hits"] = list(raw_candidates)
    if "evidence_refs" not in snapshot:
        snapshot["evidence_refs"] = list(exec_data.business_context_refs)
    exec_data.knowledge_snapshot = snapshot
    execution_blackboard.write(tenant_id, task_id, exec_data)
    execution_blackboard.persist(tenant_id, task_id)

    logger.info(f"[ContextBuilder] 构建上下文完成，候选 {len(raw_candidates)} -> {len(compressed)}")
    return {
        "refined_context": refined_context,
        "knowledge_snapshot": exec_data.knowledge_snapshot,
        "next_actions": ["analyst"],
    }
