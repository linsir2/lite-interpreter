import pytest
from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.global_blackboard import global_blackboard
from src.blackboard.knowledge_blackboard import knowledge_blackboard
from src.blackboard.schema import ExecutionData, RetrievalPlan
from src.common import EvidencePacket
from src.dag_engine.nodes.context_builder_node import context_builder_node
from src.dag_engine.nodes.kag_retriever import kag_retriever_node
from src.kag.builder.chunker import ChunkingStrategy, DocumentChunker
from src.kag.builder.classifier import DocProcessClass, DocumentClassifier
from src.kag.builder.orchestrator import KagBuilderOrchestrator
from src.kag.builder.parser import DocumentParser
from src.kag.context.formatter import ContextFormatter
from src.kag.retriever.query_engine import QueryEngine, is_keyword_query
from src.kag.retriever.recall.graph_search import recall as graph_recall
from src.mcp_gateway.tools.knowledge_query_tool import KnowledgeQueryTool
from src.storage.schema import ParsedDocument


def test_document_classifier_rejects_structured_file(tmp_path):
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("a,b\n1,2\n", encoding="utf-8")
    assert DocumentClassifier.classify(str(csv_file)) == DocProcessClass.UNKNOWN


def test_kag_orchestrator_small_document(monkeypatch, tmp_path):
    doc_file = tmp_path / "rule.txt"
    doc_file.write_text("这是一个报销规则文档，用于描述审批标准和流程。", encoding="utf-8")

    saved = {"chunks": None, "triples": None}

    monkeypatch.setattr(
        "src.storage.repository.knowledge_repo.KnowledgeRepo.save_chunks_and_embeddings",
        lambda tenant_id, workspace_id, chunks, embeddings_map: saved.update({"chunks": chunks}) or True,
    )
    monkeypatch.setattr(
        "src.storage.repository.knowledge_repo.KnowledgeRepo.save_graph_triples",
        lambda tenant_id, workspace_id, triples: saved.update({"triples": triples}) or True,
    )

    results = KagBuilderOrchestrator.ingest_documents([str(doc_file)], tenant_id="tenant_a")

    assert len(results) == 1
    assert results[0]["process_class"] == "small"
    assert results[0]["chunk_count"] == 1
    assert saved["chunks"] is not None


def test_query_engine_uses_rrf_and_rerank(monkeypatch):
    monkeypatch.setattr(
        "src.kag.retriever.recall.bm25_search.recall",
        lambda *args, **kwargs: [
            {"chunk_id": "a", "text": "报销规则", "score": 1.0, "source": "bm25", "retrieval_type": "bm25"}
        ],
    )
    monkeypatch.setattr(
        "src.kag.retriever.recall.hybrid_search.vector_recall",
        lambda *args, **kwargs: [
            {"chunk_id": "a", "text": "报销规则", "score": 0.9, "source": "vector", "retrieval_type": "vector"}
        ],
    )
    monkeypatch.setattr(
        "src.kag.retriever.recall.graph_search.recall",
        lambda *args, **kwargs: [
            {"chunk_id": "b", "text": "审批链路", "score": 0.8, "source": "graph", "retrieval_type": "graph"}
        ],
    )

    plan = RetrievalPlan(recall_strategies=["bm25", "vector", "graph"], top_k=3)
    hits = QueryEngine.execute("报销规则链路", plan, tenant_id="tenant_a", workspace_id="ws")

    assert len(hits) >= 1
    assert hits[0]["chunk_id"] in {"a", "b"}


def test_query_engine_bounds_rerank_pool_and_top_k(monkeypatch):
    bm25_hits = [
        {"chunk_id": f"chunk-{index}", "text": f"报销规则 {index}", "score": float(index), "source": "bm25", "retrieval_type": "bm25"}
        for index in range(20)
    ]
    monkeypatch.setattr("src.kag.retriever.recall.bm25_search.recall", lambda *args, **kwargs: bm25_hits)
    monkeypatch.setattr("src.kag.retriever.recall.hybrid_search.vector_recall", lambda *args, **kwargs: [])
    monkeypatch.setattr("src.kag.retriever.recall.graph_search.recall", lambda *args, **kwargs: [])

    captured = {}

    def fake_rerank(query, candidates, top_k):
        captured["candidate_count"] = len(candidates)
        captured["top_k"] = top_k
        return list(candidates)[:top_k]

    monkeypatch.setattr("src.kag.retriever.query_engine.cross_encoder_rerank", fake_rerank)
    packet = QueryEngine.execute_with_evidence(
        "报销规则",
        RetrievalPlan(recall_strategies=["bm25"], top_k=50),
        tenant_id="tenant_bounds",
        workspace_id="ws_bounds",
    )

    assert captured["top_k"] == 50
    assert captured["candidate_count"] <= 60
    assert packet.metadata["final_top_k"] == 50


def test_knowledge_query_tool_clamps_requested_top_k(monkeypatch):
    observed = {}

    def fake_execute_with_evidence(*, query, plan, tenant_id, workspace_id):
        observed["top_k"] = plan.top_k
        observed["preferred_date_terms"] = plan.preferred_date_terms
        observed["temporal_constraints"] = plan.temporal_constraints
        return EvidencePacket(
            query=query,
            rewritten_query=query,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            hits=[],
            evidence_refs=[],
            recall_strategies=plan.recall_strategies,
        )

    monkeypatch.setattr("src.kag.retriever.query_engine.QueryEngine.execute_with_evidence", fake_execute_with_evidence)
    KnowledgeQueryTool.run(
        "规则",
        tenant_id="tenant_a",
        workspace_id="ws",
        top_k=500,
        preferred_date_terms=["biz_date"],
        temporal_constraints=["2024"],
    )
    assert observed["top_k"] == 50
    assert observed["preferred_date_terms"] == ["biz_date"]
    assert observed["temporal_constraints"] == ["2024"]


def test_query_engine_returns_evidence_packet(monkeypatch):
    monkeypatch.setattr(
        "src.kag.retriever.recall.bm25_search.recall",
        lambda *args, **kwargs: [
            {"chunk_id": "a", "text": "报销规则", "score": 1.0, "source": "bm25", "retrieval_type": "bm25"}
        ],
    )
    monkeypatch.setattr(
        "src.kag.retriever.recall.hybrid_search.vector_recall",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.kag.retriever.recall.graph_search.recall",
        lambda *args, **kwargs: [],
    )

    plan = RetrievalPlan(recall_strategies=["bm25"], top_k=3)
    packet = QueryEngine.execute_with_evidence("报销规则", plan, tenant_id="tenant_packet", workspace_id="ws")
    assert packet.query == "报销规则"
    assert packet.hits
    assert packet.evidence_refs == ["a"]
    assert packet.recall_strategies == ["bm25"]


def test_query_engine_projects_retrieval_plan_temporal_preferences(monkeypatch):
    monkeypatch.setattr(
        "src.kag.retriever.recall.bm25_search.recall",
        lambda *args, **kwargs: [
            {"chunk_id": "a", "text": "报销规则", "score": 1.0, "source": "bm25", "retrieval_type": "bm25"}
        ],
    )
    monkeypatch.setattr("src.kag.retriever.recall.hybrid_search.vector_recall", lambda *args, **kwargs: [])
    monkeypatch.setattr("src.kag.retriever.recall.graph_search.recall", lambda *args, **kwargs: [])

    packet = QueryEngine.execute_with_evidence(
        "按biz_date筛选2024年报销规则",
        RetrievalPlan(
            recall_strategies=["bm25"],
            top_k=3,
            preferred_date_terms=["biz_date"],
            temporal_constraints=["2024"],
        ),
        tenant_id="tenant_temporal_plan",
        workspace_id="ws",
    )

    assert packet.filters["preferred_date_terms"] == ["biz_date"]
    assert packet.filters["temporal_constraints"] == ["2024"]
    assert packet.metadata["preferred_date_terms"] == ["biz_date"]
    assert packet.metadata["temporal_constraints"] == ["2024"]


def test_bm25_recall_extends_query_terms_with_temporal_preferences(monkeypatch):
    observed = {}

    def fake_search_text_chunks(*, tenant_id, workspace_id, query_terms, filters, limit):
        observed["query_terms"] = list(query_terms)
        observed["filters"] = dict(filters)
        return []

    monkeypatch.setattr("src.storage.repository.knowledge_repo.KnowledgeRepo.search_text_chunks", fake_search_text_chunks)

    from src.kag.retriever.recall.bm25_search import recall

    recall(
        "审批时效",
        tenant_id="tenant_a",
        workspace_id="ws",
        filters={"preferred_date_terms": ["biz_date"], "temporal_constraints": ["2024"], "year": "2024"},
    )

    assert "biz_date" in observed["query_terms"]
    assert "2024" in observed["query_terms"]
    assert observed["filters"] == {"year": "2024"}


def test_is_keyword_query_rejects_long_chinese_question_without_spaces():
    assert is_keyword_query("马斯克的火星计划是哪一年开始的呀为什么他这么执着") is False


def test_knowledge_query_tool_returns_evidence_packet(monkeypatch):
    monkeypatch.setattr(
        "src.kag.retriever.query_engine.QueryEngine.execute_with_evidence",
        lambda **kwargs: EvidencePacket(
            query=kwargs["query"],
            rewritten_query=kwargs["query"],
            tenant_id=kwargs["tenant_id"],
            workspace_id=kwargs["workspace_id"],
            hits=[{"chunk_id": "chunk-1", "text": "规则"}],
            evidence_refs=["chunk-1"],
            recall_strategies=["bm25"],
        ),
    )
    result = KnowledgeQueryTool.run("规则", tenant_id="tenant_a", workspace_id="ws")
    assert result["evidence_refs"] == ["chunk-1"]
    assert result["hits"][0]["chunk_id"] == "chunk-1"


def test_context_formatter_uses_compiled_signals_for_rule_and_metric_detection():
    context, refined = ContextFormatter.format(
        [
            {"text": "合同必须上传，否则审批流程会被影响。", "source": "rule.pdf", "retrieval_type": "bm25"},
            {"text": "审批时效按合同分组统计。", "source": "metric.pdf", "retrieval_type": "vector"},
        ]
    )

    assert context["rules"]
    assert context["metrics"]
    assert "审批流程" in refined


def test_context_builder_writes_business_context():
    tenant_id = "tenant_ctx"
    task_id = "task_ctx"
    exec_data = ExecutionData(task_id=task_id, tenant_id=tenant_id)
    execution_blackboard.write(tenant_id, task_id, exec_data)

    state = {
        "tenant_id": tenant_id,
        "task_id": task_id,
        "workspace_id": "default_ws",
        "input_query": "请总结报销规则和指标口径",
        "raw_retrieved_candidates": [
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
        ],
        "next_actions": [],
        "retry_count": 0,
        "current_error_type": None,
    }

    result = context_builder_node(state)
    updated = execution_blackboard.read(tenant_id, task_id)

    assert result["next_actions"] == ["analyst"]
    assert updated is not None
    assert updated.knowledge.business_context.rules
    assert updated.knowledge.business_context.metrics
    assert updated.knowledge.analysis_brief.business_rules
    assert updated.knowledge.analysis_brief.business_metrics
    assert result["knowledge_snapshot"]["metadata"]["selected_count"] >= 1
    assert result["analysis_brief"]["analysis_mode"] == "document_rule_analysis"
    assert tuple(result["knowledge_snapshot"]["metadata"]["pinned_evidence_refs"]) == ("c1", "c2")


def test_context_builder_can_fall_back_to_knowledge_snapshot_hits():
    tenant_id = "tenant_ctx_snapshot"
    task_id = "task_ctx_snapshot"
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            knowledge={
                "knowledge_snapshot": {
                    "hits": [
                        {
                            "chunk_id": "c9",
                            "text": "报销规则：合同必须上传。",
                            "score": 1.0,
                            "source": "rule.pdf",
                            "retrieval_type": "bm25",
                        }
                    ],
                    "evidence_refs": ["c9"],
                },
            },
        ),
    )
    state = {
        "tenant_id": tenant_id,
        "task_id": task_id,
        "workspace_id": "default_ws",
        "input_query": "请总结报销规则",
        "knowledge_snapshot": {
            "hits": [
                {
                    "chunk_id": "c9",
                    "text": "报销规则：合同必须上传。",
                    "score": 1.0,
                    "source": "rule.pdf",
                    "retrieval_type": "bm25",
                }
            ],
            "evidence_refs": ["c9"],
        },
        "raw_retrieved_candidates": [],
        "next_actions": [],
        "retry_count": 0,
        "current_error_type": None,
    }

    result = context_builder_node(state)
    updated = execution_blackboard.read(tenant_id, task_id)
    assert "合同必须上传" in result["refined_context"]
    assert updated is not None
    assert updated.knowledge.knowledge_snapshot.evidence_refs == ["c9"]
    assert updated.knowledge.analysis_brief.evidence_refs == ["c9"]
    assert result["analysis_brief"]["evidence_refs"] == ["c9"]


def test_context_builder_projects_temporal_preferences_into_snapshot_metadata():
    tenant_id = "tenant_ctx_temporal"
    task_id = "task_ctx_temporal"
    exec_data = ExecutionData(task_id=task_id, tenant_id=tenant_id)
    execution_blackboard.write(tenant_id, task_id, exec_data)

    state = {
        "tenant_id": tenant_id,
        "task_id": task_id,
        "workspace_id": "default_ws",
        "input_query": "按biz_date筛选2024年审批时效",
        "raw_retrieved_candidates": [
            {
                "chunk_id": "c-time",
                "text": "审批时效口径：按biz_date统计审批时效，并按2024年过滤。",
                "score": 1.0,
                "source": "metric.pdf",
                "retrieval_type": "bm25",
            }
        ],
        "next_actions": [],
        "retry_count": 0,
        "current_error_type": None,
    }

    result = context_builder_node(state)
    metadata = result["knowledge_snapshot"]["metadata"]
    assert "biz_date" in metadata["preferred_date_terms"]
    assert "2024" in metadata["temporal_constraints"]


def test_context_builder_compiles_temporal_graph_from_business_specs(monkeypatch):
    tenant_id = "tenant_ctx_temporal_graph"
    task_id = "task_ctx_temporal_graph"
    exec_data = ExecutionData(task_id=task_id, tenant_id=tenant_id)
    execution_blackboard.write(tenant_id, task_id, exec_data)
    persisted = {}

    def fake_save_graph_triples(*, tenant_id, workspace_id, triples):
        persisted["tenant_id"] = tenant_id
        persisted["workspace_id"] = workspace_id
        persisted["triples"] = list(triples)
        return True

    state = {
        "tenant_id": tenant_id,
        "task_id": task_id,
        "workspace_id": "default_ws",
        "input_query": "按biz_date筛选2024年审批时效",
        "raw_retrieved_candidates": [
            {
                "chunk_id": "c-time-graph",
                "text": "审批时效口径：按biz_date统计审批时效，并按2024年过滤。",
                "score": 1.0,
                "source": "metric.pdf",
                "retrieval_type": "bm25",
            }
        ],
        "next_actions": [],
        "retry_count": 0,
        "current_error_type": None,
    }

    monkeypatch.setattr("src.storage.repository.knowledge_repo.KnowledgeRepo.save_graph_triples", fake_save_graph_triples)
    context_builder_node(state)
    updated = execution_blackboard.read(tenant_id, task_id)

    assert updated is not None
    assert updated.knowledge.compiled.graph_compilation_summary.accepted_count > 0
    assert updated.knowledge.compiled.graph_compilation_summary.candidate_count >= updated.knowledge.compiled.graph_compilation_summary.accepted_count
    assert any(triple.relation == "OCCURS_AT" for triple in updated.knowledge.compiled.compiled_graph_triples)
    assert any(triple.tail == "biz_date" for triple in updated.knowledge.compiled.compiled_graph_triples)
    assert any(triple.tail == "2024" for triple in updated.knowledge.compiled.compiled_graph_triples)
    assert persisted["tenant_id"] == tenant_id
    assert persisted["workspace_id"] == "default_ws"
    assert any(triple.tail == "biz_date" for triple in persisted["triples"])
    assert any(triple.tail == "2024" for triple in persisted["triples"])


def test_graph_recall_extends_query_terms_with_temporal_preferences(monkeypatch):
    observed = {}

    def fake_search_graph_facts(*, tenant_id, workspace_id, query_terms, temporal_terms, prefer_temporal, limit):
        observed["tenant_id"] = tenant_id
        observed["workspace_id"] = workspace_id
        observed["query_terms"] = list(query_terms)
        observed["temporal_terms"] = list(temporal_terms)
        observed["prefer_temporal"] = prefer_temporal
        observed["limit"] = limit
        return []

    monkeypatch.setattr("src.storage.repository.knowledge_repo.KnowledgeRepo.search_graph_facts", fake_search_graph_facts)

    graph_recall(
        "审批时效",
        tenant_id="tenant_graph_temporal",
        workspace_id="ws_graph_temporal",
        top_k=4,
        filters={"preferred_date_terms": ["biz_date"], "temporal_constraints": ["2024"]},
    )

    assert observed["tenant_id"] == "tenant_graph_temporal"
    assert observed["workspace_id"] == "ws_graph_temporal"
    assert observed["limit"] == 4
    assert "审批时效" in observed["query_terms"]
    assert "biz_date" in observed["query_terms"]
    assert "2024" in observed["query_terms"]
    assert observed["temporal_terms"] == ["biz_date", "2024"]
    assert observed["prefer_temporal"] is True


def test_graph_client_scores_temporal_hits_higher_than_generic_hits():
    from src.storage.graph_client import GraphDBClient

    generic_row = {
        "head": "审批时效",
        "tail": "合同",
        "relation": "RELATED_TO",
        "graph_type": "semantic",
        "provenance": {"template_id": "semantic.cooccurrence.related_to"},
    }
    temporal_row = {
        "head": "审批时效",
        "tail": "biz_date",
        "relation": "OCCURS_AT",
        "graph_type": "temporal",
        "provenance": {"template_id": "metric.temporal.preference.occurs_at"},
    }

    generic_score = GraphDBClient._fact_score(
        generic_row,
        query_terms=["审批时效", "biz_date", "2024"],
        temporal_terms=["biz_date", "2024"],
        prefer_temporal=True,
    )
    temporal_score = GraphDBClient._fact_score(
        temporal_row,
        query_terms=["审批时效", "biz_date", "2024"],
        temporal_terms=["biz_date", "2024"],
        prefer_temporal=True,
    )

    assert temporal_score > generic_score


def test_query_engine_uses_graph_chunk_ids_as_evidence_refs(monkeypatch):
    monkeypatch.setattr(
        "src.kag.retriever.query_engine.analyze_query",
        lambda *args, **kwargs: ("审批时效 关系", {}, 0.9, True),
    )
    monkeypatch.setattr("src.kag.retriever.recall.bm25_search.recall", lambda *args, **kwargs: [])
    monkeypatch.setattr("src.kag.retriever.recall.hybrid_search.vector_recall", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "src.kag.retriever.recall.graph_search.recall",
        lambda *args, **kwargs: [
            {
                "chunk_id": "compiled:metric:0",
                "text": "审批时效 -[OCCURS_AT]-> biz_date",
                "score": 3.0,
                "source": "compiled:metric:0",
                "graph_type": "temporal",
                "retrieval_type": "graph",
            }
        ],
    )

    packet = QueryEngine.execute_with_evidence(
        "审批时效关系",
        RetrievalPlan(recall_strategies=["graph"], top_k=3),
        tenant_id="tenant_graph_packet",
        workspace_id="ws_graph_packet",
    )

    assert packet.hits[0]["chunk_id"] == "compiled:metric:0"
    assert packet.evidence_refs == ["compiled:metric:0"]


def test_kag_retriever_writes_knowledge_snapshot(monkeypatch):
    tenant_id = "tenant_snapshot"
    task_id = global_blackboard.create_task(tenant_id, "ws", "规则")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(task_id=task_id, tenant_id=tenant_id, workspace_id="ws"),
    )
    monkeypatch.setattr(
        "src.storage.repository.knowledge_repo.KnowledgeRepo.has_vector_index", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(
        "src.storage.repository.knowledge_repo.KnowledgeRepo.has_graph_index", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(
        "src.kag.retriever.query_engine.QueryEngine.execute_with_evidence",
        lambda *args, **kwargs: EvidencePacket(
            query="规则",
            rewritten_query="规则",
            tenant_id=tenant_id,
            workspace_id="ws",
            hits=[
                {
                    "chunk_id": "chunk-9",
                    "text": "规则文本",
                    "score": 1.0,
                    "source": "rule.pdf",
                    "retrieval_type": "bm25",
                }
            ],
            evidence_refs=["chunk-9"],
            recall_strategies=["bm25", "splade"],
            metadata={"selected_count": 1},
        ),
    )
    result = kag_retriever_node(
        {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "workspace_id": "ws",
            "input_query": "规则",
        }
    )
    updated = execution_blackboard.read(tenant_id, task_id)
    knowledge_state = knowledge_blackboard.read(tenant_id, task_id)
    assert result["knowledge_snapshot"]["evidence_refs"] == ["chunk-9"]
    assert updated is not None
    assert updated.knowledge.knowledge_snapshot.evidence_refs == ["chunk-9"]
    assert knowledge_state is not None
    assert knowledge_state.latest_retrieval_snapshot.evidence_refs == ["chunk-9"]


def test_kag_retriever_fast_path_injection_uses_lexical_overlap(monkeypatch, tmp_path):
    tenant_id = "tenant_fast_path_lexical"
    task_id = global_blackboard.create_task(tenant_id, "ws", "费用报销规则")
    small_doc = tmp_path / "rule-small.txt"
    small_doc.write_text("报销规则：合同必须上传。", encoding="utf-8")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id="ws",
            inputs={
                "business_documents": [
                    {
                        "file_name": "rule-small.txt",
                        "path": str(small_doc),
                        "status": "parsed",
                        "is_newly_uploaded": True,
                    }
                ]
            },
        ),
    )
    monkeypatch.setattr("src.storage.repository.knowledge_repo.KnowledgeRepo.has_vector_index", lambda *args, **kwargs: False)
    monkeypatch.setattr("src.storage.repository.knowledge_repo.KnowledgeRepo.has_graph_index", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        "src.kag.retriever.query_engine.QueryEngine.execute_with_evidence",
        lambda *args, **kwargs: EvidencePacket(
            query="费用报销规则",
            rewritten_query="费用报销规则",
            tenant_id=tenant_id,
            workspace_id="ws",
            hits=[],
            evidence_refs=[],
            recall_strategies=["bm25"],
            metadata={},
        ),
    )

    result = kag_retriever_node(
        {"tenant_id": tenant_id, "task_id": task_id, "workspace_id": "ws", "input_query": "费用报销规则"}
    )

    assert result["raw_retrieved_candidates"]
    assert result["raw_retrieved_candidates"][0]["type"] == "fast_path_injection"


def test_kag_retriever_persists_document_progress_incrementally(monkeypatch, tmp_path):
    tenant_id = "tenant_snapshot_incremental"
    task_id = global_blackboard.create_task(tenant_id, "ws", "规则")
    first_doc = tmp_path / "rule-a.txt"
    second_doc = tmp_path / "rule-b.txt"
    first_doc.write_text("规则A", encoding="utf-8")
    second_doc.write_text("规则B", encoding="utf-8")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id="ws",
            inputs={
                "business_documents": [
                    {"file_name": "rule-a.txt", "path": str(first_doc), "status": "pending"},
                    {"file_name": "rule-b.txt", "path": str(second_doc), "status": "pending"},
                ]
            },
        ),
    )
    monkeypatch.setattr(
        "src.storage.repository.knowledge_repo.KnowledgeRepo.has_vector_index", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(
        "src.storage.repository.knowledge_repo.KnowledgeRepo.has_graph_index", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(
        "src.kag.retriever.query_engine.QueryEngine.execute_with_evidence",
        lambda *args, **kwargs: EvidencePacket(
            query="规则",
            rewritten_query="规则",
            tenant_id=tenant_id,
            workspace_id="ws",
            hits=[],
            evidence_refs=[],
            recall_strategies=["bm25", "splade"],
            metadata={"selected_count": 0},
        ),
    )

    call_index = {"value": 0}

    def fake_ingest(doc_paths, tenant_id, workspace_id="default_ws"):
        call_index["value"] += 1
        if call_index["value"] == 1:
            return [{"file_name": "rule-a.txt", "parse_mode": "default", "parser_diagnostics": {}}]
        raise RuntimeError("second document failed")

    monkeypatch.setattr("src.kag.builder.orchestrator.KagBuilderOrchestrator.ingest_documents", fake_ingest)

    kag_retriever_node(
        {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "workspace_id": "ws",
            "input_query": "规则",
        }
    )

    updated = execution_blackboard.read(tenant_id, task_id)
    assert updated is not None
    assert updated.inputs.business_documents[0].status == "parsed"
    assert updated.inputs.business_documents[1].status == "pending"


def test_kag_retriever_blocks_when_new_document_ingest_fails(monkeypatch, tmp_path):
    tenant_id = "tenant_snapshot_block"
    task_id = global_blackboard.create_task(tenant_id, "ws", "规则")
    failed_doc = tmp_path / "rule-fail.txt"
    failed_doc.write_text("规则", encoding="utf-8")
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            task_id=task_id,
            tenant_id=tenant_id,
            workspace_id="ws",
            inputs={
                "business_documents": [
                    {"file_name": "rule-fail.txt", "path": str(failed_doc), "status": "pending"},
                ]
            },
        ),
    )
    monkeypatch.setattr(
        "src.storage.repository.knowledge_repo.KnowledgeRepo.has_vector_index", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(
        "src.storage.repository.knowledge_repo.KnowledgeRepo.has_graph_index", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(
        "src.kag.builder.orchestrator.KagBuilderOrchestrator.ingest_documents",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("ingest failed")),
    )

    result = kag_retriever_node(
        {
            "tenant_id": tenant_id,
            "task_id": task_id,
            "workspace_id": "ws",
            "input_query": "规则",
        }
    )

    assert result["blocked"] is True
    assert result["next_actions"] == ["wait_for_human"]
    task_state = global_blackboard.get_task_state(task_id)
    assert task_state.global_status == "waiting_for_human"
    assert task_state.failure_type == "knowledge_ingestion"


def test_context_builder_applies_final_budget_fit(monkeypatch):
    tenant_id = "tenant_budget"
    task_id = "task_budget"
    execution_blackboard.write(tenant_id, task_id, ExecutionData(task_id=task_id, tenant_id=tenant_id))
    monkeypatch.setattr(
        "src.dag_engine.nodes.context_builder_node.fit_items_to_budget",
        lambda items, **kwargs: list(items[:1]),
    )
    state = {
        "tenant_id": tenant_id,
        "task_id": task_id,
        "workspace_id": "default_ws",
        "input_query": "请总结规则",
        "token_budget": 128,
        "raw_retrieved_candidates": [
            {
                "chunk_id": "c1",
                "text": "规则一：金额必须含税。",
                "score": 1.0,
                "source": "rule.pdf",
                "retrieval_type": "bm25",
            },
            {
                "chunk_id": "c2",
                "text": "规则二：必须上传合同。",
                "score": 0.9,
                "source": "rule.pdf",
                "retrieval_type": "bm25",
            },
        ],
        "next_actions": [],
        "retry_count": 0,
        "current_error_type": None,
    }

    result = context_builder_node(state)
    assert "规则一" in result["refined_context"]
    assert "规则二" not in result["refined_context"]
    assert result["knowledge_snapshot"]["metadata"]["dropped_candidate_count"] == 1


def test_document_parser_returns_typed_document(tmp_path):
    doc_file = tmp_path / "rule.txt"
    doc_file.write_text("这是一个文档。\n第二段。", encoding="utf-8")

    parsed = DocumentParser.parse(str(doc_file), tenant_id="tenant_a", upload_batch_id="batch_1")

    assert isinstance(parsed, ParsedDocument)
    assert parsed.sections
    assert parsed.sections[0].level == 1


def test_document_parser_distinguishes_title_and_heading_levels(tmp_path):
    pytest.importorskip("docling.document_converter")

    doc_file = tmp_path / "outline.md"
    doc_file.write_text(
        "# Title\n\nIntro paragraph.\n\n## Section One\n\nSection one body.\n\n### Subsection A\n\nSubsection body.\n",
        encoding="utf-8",
    )

    parsed = DocumentParser.parse(str(doc_file), tenant_id="tenant_a", upload_batch_id="batch_1")

    assert [section.title for section in parsed.sections] == ["Title", "Section One", "Subsection A"]
    assert [section.level for section in parsed.sections] == [0, 1, 2]
    assert parsed.sections[0].metadata["section_kind"] == "document_title"
    assert parsed.sections[1].metadata["docling_level"] == 1
    assert parsed.sections[2].metadata["docling_level"] == 2


def test_document_chunker_detects_docling_outline_structure():
    strategy = DocumentChunker._select_strategy(
        sections=[
            {
                "id": "s1",
                "title": "Title",
                "content": "intro",
                "level": 0,
                "metadata": {"section_kind": "document_title"},
            },
            {
                "id": "s2",
                "title": "Section One",
                "content": "body",
                "level": 1,
                "metadata": {"section_kind": "section_header"},
            },
        ],
        content="intro\nbody",
    )

    assert strategy == ChunkingStrategy.LAYOUT_AWARE


def test_document_parser_infers_scanned_pdf_profile(monkeypatch):
    class FakePage:
        def get_text(self):
            return ""

        def get_images(self, full=True):
            return [("img",)]

    class FakeDoc:
        page_count = 2

        def __getitem__(self, idx):
            return FakePage()

    monkeypatch.setattr("fitz.open", lambda path: FakeDoc())
    profile = DocumentParser.infer_pdf_parse_profile("/tmp/fake.pdf")
    assert profile.mode == "ocr"
    assert profile.use_ocr is True
    assert profile.diagnostics["scanned_like"] is True


def test_document_parser_infers_vision_profile_for_image_heavy_pdf(monkeypatch):
    class FakePage:
        def get_text(self):
            return "This page already has extractable text " * 20

        def get_images(self, full=True):
            return [("img",), ("img2",), ("img3",), ("img4",)]

    class FakeDoc:
        page_count = 1

        def __getitem__(self, idx):
            return FakePage()

    monkeypatch.setattr("fitz.open", lambda path: FakeDoc())
    monkeypatch.setattr(
        "src.kag.builder.parser.DocumentParser._pdf_policy",
        lambda: {
            "enable_ocr_for_scanned": True,
            "scanned_text_chars_per_page_threshold": 120,
            "scanned_image_count_threshold": 1,
            "enable_picture_description": True,
            "enable_picture_description_for_image_heavy": True,
            "image_heavy_count_threshold": 3,
            "generate_picture_images": True,
        },
    )
    profile = DocumentParser.infer_pdf_parse_profile("/tmp/fake.pdf")
    assert profile.mode == "vision"
    assert profile.use_ocr is False
    assert profile.use_picture_description is True
    assert profile.generate_picture_images is True
    assert profile.diagnostics["image_heavy"] is True


def test_document_parser_builds_default_pdf_converter_profile(monkeypatch, tmp_path):
    pdf_file = tmp_path / "sample.pdf"
    pdf_file.write_bytes(b"%PDF-1.4")

    class FakeConverter:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(
        "src.kag.builder.parser.DocumentParser.infer_pdf_parse_profile",
        lambda _: type(
            "Profile",
            (),
            {
                "mode": "ocr",
                "use_ocr": True,
                "use_picture_description": False,
                "generate_picture_images": False,
                "diagnostics": {"scanned_like": True},
            },
        )(),
    )
    monkeypatch.setattr("docling.document_converter.DocumentConverter", FakeConverter)

    converter, parser_profile = DocumentParser._build_docling_converter(str(pdf_file))
    assert parser_profile["parse_mode"] == "ocr"
    assert parser_profile["ocr_enabled"] is True


def test_document_parser_extracts_picture_description_into_images_and_content():
    class FakeAnnotation:
        kind = "description"
        text = "这是一张流程图，描述审批步骤。"

    class FakeImage:
        caption = "图1"
        annotations = [FakeAnnotation()]
        position = {"x": 1}
        size = {"w": 2}
        prov = []

    images = DocumentParser._extract_images([FakeImage()])
    assert images[0].description == "这是一张流程图，描述审批步骤。"
    content = DocumentParser._augment_content_with_image_descriptions("正文内容", images)
    assert "图片说明" in content
    assert "流程图" in content


def test_document_parser_extracts_table_title_from_docling_caption():
    class FakeTableData(list):
        def __init__(self):
            super().__init__([["A", "B"], ["1", "2"]])
            self.num_rows = 2
            self.num_cols = 2

    class FakeTable:
        data = FakeTableData()
        prov = []

        def caption_text(self, document):
            return "统计表"

    tables = DocumentParser._extract_tables([FakeTable()], document=object())
    assert tables[0].title == "统计表"
    assert tables[0].rows == 2
    assert tables[0].columns == 2


def test_document_parser_extracts_picture_caption_and_meta_description():
    class FakeBBox:
        def model_dump(self):
            return {"l": 1, "t": 2, "r": 3, "b": 4}

    class FakeProv:
        bbox = FakeBBox()
        page_no = 1

    class FakeSize:
        def model_dump(self):
            return {"width": 256, "height": 128}

    class FakeImageRef:
        size = FakeSize()

    class FakeDescription:
        text = "图中展示了审批流转。"

    class FakeMeta:
        description = FakeDescription()

    class FakeImage:
        meta = FakeMeta()
        annotations = []
        prov = [FakeProv()]
        image = FakeImageRef()

        def caption_text(self, document):
            return "审批流程图"

    images = DocumentParser._extract_images([FakeImage()], document=object())
    assert images[0].caption == "审批流程图"
    assert images[0].description == "图中展示了审批流转。"
    assert images[0].position == {"l": 1, "t": 2, "r": 3, "b": 4}
    assert images[0].size == {"width": 256, "height": 128}
