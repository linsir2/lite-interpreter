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
from src.kag.builder.fusion import KnowledgeFusion
from src.kag.compiler import GraphCompilationSummaryState, GraphCompiler, KnowledgeCompilerService
from src.kag.context.compressor import ContextCompressor
from src.kag.context.formatter import ContextFormatter
from src.kag.context.selector import ContextSelector
from src.runtime import build_analysis_brief, resolve_runtime_decision
from src.storage.repository.knowledge_repo import KnowledgeRepo

logger = get_logger(__name__)


def _build_graph_summary(compilation: Any) -> GraphCompilationSummaryState:
    reject_reasons: dict[str, int] = {}
    for item in list(getattr(compilation, "rejected", []) or []):
        code = str(item.get("code") or "").strip()
        if code:
            reject_reasons[code] = reject_reasons.get(code, 0) + 1
    return GraphCompilationSummaryState(
        candidate_count=len(list(getattr(compilation, "accepted", []) or [])) + len(list(getattr(compilation, "rejected", []) or [])),
        accepted_count=len(list(getattr(compilation, "accepted", []) or [])),
        rejected_count=len(list(getattr(compilation, "rejected", []) or [])),
        reject_reasons=reject_reasons,
    )


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
    spec_result = KnowledgeCompilerService.compile_business_context(
        rules=business_context_state.rules,
        metrics=business_context_state.metrics,
        filters=business_context_state.filters,
    )
    exec_data.knowledge.compiled.query_signals = KnowledgeCompilerService.classify_query(query)
    exec_data.knowledge.compiled.rule_specs = list(spec_result.rules)
    exec_data.knowledge.compiled.metric_specs = list(spec_result.metrics)
    exec_data.knowledge.compiled.filter_specs = list(spec_result.filters)
    exec_data.knowledge.compiled.spec_parse_errors = list(spec_result.errors)
    graph_compilation = GraphCompiler.compile_spec_relations(
        rule_specs=list(spec_result.rules),
        metric_specs=list(spec_result.metrics),
        filter_specs=list(spec_result.filters),
    )
    compiled_graph_triples = KnowledgeFusion.fuse([item.triple for item in list(graph_compilation.accepted or [])])
    exec_data.knowledge.compiled.compiled_graph_triples = compiled_graph_triples
    exec_data.knowledge.compiled.graph_compilation_summary = _build_graph_summary(graph_compilation)
    if compiled_graph_triples:
        persisted = KnowledgeRepo.save_graph_triples(
            tenant_id=tenant_id,
            workspace_id=exec_data.workspace_id,
            triples=compiled_graph_triples,
        )
        if not persisted:
            logger.warning("[ContextBuilder] 编译态图谱三元组写入失败，保留任务态结果继续执行。")
    brief_decision = resolve_runtime_decision(
        call_purpose="context_compress",
        query=query,
        state=state,
        exec_data=exec_data,
        allowed_tools=list(state.get("allowed_tools") or []),
    )
    analysis_brief = build_analysis_brief(
        query=query,
        exec_data=exec_data,
        knowledge_snapshot=knowledge_snapshot
        or {"evidence_refs": [item.get("chunk_id") for item in compressed if item.get("chunk_id")]},
        business_context=business_context_state.model_dump(mode="json"),
        analysis_mode=brief_decision.analysis_mode,
        known_gaps=brief_decision.known_gaps,
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
            "analysis_mode": brief_decision.analysis_mode,
            "evidence_strategy": brief_decision.evidence_strategy,
            "preferred_date_terms": list(
                dict.fromkeys(
                    str(value).strip()
                    for spec in list(spec_result.metrics) + list(spec_result.filters)
                    for value in list(getattr(spec, "preferred_date_terms", []) or [])
                    if str(value).strip()
                )
            ),
            "temporal_constraints": list(
                dict.fromkeys(
                    str(constraint.value).strip()
                    for spec in list(spec_result.metrics) + list(spec_result.filters)
                    for constraint in list(getattr(spec, "temporal_constraints", []) or [])
                    if str(getattr(constraint, "value", "")).strip()
                )
            ),
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
