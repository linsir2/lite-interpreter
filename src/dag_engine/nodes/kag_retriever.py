"""
KAG Retriever 知识检索编排节点

职责：作为 DAG 的调度器，并行调用底层的 KAG 引擎进行解析与高级检索。

核心特性：
1. 调度层：发现新文档，触发 KAG Builder 进行全链路知识生产并落库。
2. 策略层：动态生成 Retrieval Plan，调用 KAG Retriever 的 Query Engine 进行多路召回。
3. 流转层：将召回的生肉数据（Raw Candidates）注入 GraphState，流转至 Context Builder。
"""

import os
from typing import Any

import jieba

from src.blackboard.execution_blackboard import execution_blackboard
from src.blackboard.global_blackboard import global_blackboard
from src.blackboard.knowledge_blackboard import knowledge_blackboard
from src.blackboard.schema import (
    BusinessDocumentState,
    GlobalStatus,
    KnowledgeData,
    KnowledgeSnapshotState,
    RetrievalPlan,
)
from src.common.logger import get_logger
from src.dag_engine.graphstate import DagGraphState
from src.kag.builder.classifier import DocProcessClass, DocumentClassifier
from src.kag.builder.orchestrator import KagBuilderOrchestrator
from src.kag.retriever.query_engine import QueryEngine
from src.storage.repository.knowledge_repo import KnowledgeRepo

logger = get_logger(__name__)


# 主节点
def kag_retriever_node(state: DagGraphState) -> dict[str, Any]:
    """知识检索引擎：并行解析新文档，执行高级检索组装结构化上下文"""
    tenant_id = state["tenant_id"]
    task_id = state["task_id"]
    workspace_id = state["workspace_id"]
    query = state["input_query"]

    logger.info(f"[KAG Retriever] 启动，为任务 {task_id} 编排知识生产与检索策略...")

    exec_data = execution_blackboard.read(tenant_id, task_id)
    if not exec_data:
        logger.error(f"[KAG Node] 无法读取任务 {task_id} 的执行黑板！")
        return {"next_actions": ["analyst"]}

    # 触发kag builder，对文档进行解析入库
    knowledge_data = knowledge_blackboard.read(tenant_id, task_id)
    if knowledge_data is None and knowledge_blackboard.restore(tenant_id, task_id):
        knowledge_data = knowledge_blackboard.read(tenant_id, task_id)
    if knowledge_data is None:
        knowledge_data = KnowledgeData(task_id=task_id, tenant_id=tenant_id, workspace_id=workspace_id)
        knowledge_data.business_documents = [
            BusinessDocumentState.model_validate(item.model_dump(mode="json"))
            for item in exec_data.inputs.business_documents
        ]

    unparsed_docs = [doc for doc in exec_data.inputs.business_documents if doc.status != "parsed"]

    if unparsed_docs:
        global_blackboard.update_global_status(
            task_id, GlobalStatus.RETRIEVING, f"正在调度 KAG BUILDER 并行处理 {len(unparsed_docs)} 个新文档"
        )

        completed_docs = 0
        failed_docs: list[str] = []
        for doc in unparsed_docs:
            doc_path = doc.path
            if not doc_path:
                continue
            try:
                ingest_results = KagBuilderOrchestrator.ingest_documents(
                    [doc_path],
                    tenant_id,
                    workspace_id=workspace_id,
                )
                ingest_info = dict(ingest_results[0]) if ingest_results else {}
                doc.status = "parsed"
                doc.parse_mode = str(ingest_info.get("parse_mode", "default"))
                doc.parser_diagnostics = dict(ingest_info.get("parser_diagnostics", {}) or {})
                knowledge_data.business_documents = [
                    BusinessDocumentState.model_validate(item.model_dump(mode="json"))
                    for item in exec_data.inputs.business_documents
                ]
                execution_blackboard.write(tenant_id, task_id, exec_data)
                execution_blackboard.persist(tenant_id, task_id)
                knowledge_blackboard.write(tenant_id, task_id, knowledge_data)
                knowledge_blackboard.persist(tenant_id, task_id)
                completed_docs += 1
            except Exception as e:
                logger.error(f"[KAG NODE] 文档 {os.path.basename(doc_path)} 入库异常：{e}")
                failed_docs.append(os.path.basename(doc_path))

        if completed_docs:
            logger.info(f"[KAG Node] {completed_docs} 份文档知识生产流水线执行完毕。")
        if failed_docs:
            failed_reason = "以下业务文档知识构建失败，当前任务不再继续基于陈旧知识快照作答：" + ", ".join(failed_docs)
            exec_data.static.latest_error_traceback = failed_reason
            execution_blackboard.write(tenant_id, task_id, exec_data)
            execution_blackboard.persist(tenant_id, task_id)
            global_blackboard.update_global_status(
                task_id=task_id,
                new_status=GlobalStatus.WAITING_FOR_HUMAN,
                sub_status="业务文档知识构建部分失败，等待人工介入",
                failure_type="knowledge_ingestion",
                error_message=failed_reason,
            )
            return {
                "blocked": True,
                "block_reason": failed_reason,
                "raw_retrieved_candidates": [],
                "knowledge_snapshot": exec_data.knowledge.knowledge_snapshot,
                "next_actions": ["wait_for_human"],
            }

    # 确定检索策略
    has_vector = KnowledgeRepo.has_vector_index(tenant_id, workspace_id)
    has_graph = KnowledgeRepo.has_graph_index(tenant_id, workspace_id)

    active_strategies = ["bm25", "splade"]  # 稀疏检索默认授权
    if has_vector:
        active_strategies.append("vector")
    if has_graph:
        active_strategies.append("graph")

    # 只要任务中有大文件，说明neo4j中有图谱数据，则必须要有图谱检索，不需要管是哪个文件的；当然底层可以增加元数据区分不同文档
    active_strategies = ["bm25", "splade"]
    if has_vector:
        active_strategies.append("vector")
    if has_graph:
        active_strategies.append("graph")

    logger.info(f"[KAG Node] 动态评估当前任务知识资产，决定启用召回通道: {active_strategies}")

    plan = RetrievalPlan(
        enable_qu=True,
        enable_rewrite=True,
        enable_filter=True,
        recall_strategies=active_strategies,
        routing_strategy="hybrid",
        enable_rerank=True,
        top_k=15,
        budget_tokens=4000,
    )

    # 调用kag-retriever
    global_blackboard.update_global_status(task_id, GlobalStatus.RETRIEVING, "正在执行多路知识召回与语义重排...")

    evidence_packet = QueryEngine.execute_with_evidence(query, plan, tenant_id, workspace_id=workspace_id)
    raw_candidates = list(evidence_packet.hits)
    exec_data.knowledge.knowledge_snapshot = KnowledgeSnapshotState.model_validate(
        evidence_packet.model_dump(mode="json")
    )
    knowledge_data.latest_retrieval_snapshot = KnowledgeSnapshotState.model_validate(
        evidence_packet.model_dump(mode="json")
    )
    execution_blackboard.write(tenant_id, task_id, exec_data)
    execution_blackboard.persist(tenant_id, task_id)
    knowledge_blackboard.write(tenant_id, task_id, knowledge_data)
    knowledge_blackboard.persist(tenant_id, task_id)

    query_keywords = set(jieba.lcut(query)) - {"的", "是", "了", "怎么", "如何", "帮我"}
    for doc in exec_data.inputs.business_documents:
        if doc.is_newly_uploaded and DocumentClassifier.classify(doc.path) == DocProcessClass.SMALL:
            with open(doc.path) as f:
                raw_text = f.read()

            # 🛡️ 极其关键的轻量拦截：如果原文里连用户的核心词都没命中任何一个，拒绝强插！
            text_keywords = set(jieba.lcut(raw_text))
            overlap = query_keywords.intersection(text_keywords)

            if not overlap and len(query_keywords) > 0:
                logger.warning(f"[KAG Node] 小文件 {os.path.basename(doc.path)} 与提问无关，拒绝强插，防止上下文污染！")
                continue

            raw_candidates.append(
                {
                    "text": raw_text,
                    "score": 1.0,
                    "source": os.path.basename(doc.path),
                    "type": "fast_path_injection",
                }
            )

    if not raw_candidates:
        logger.warning(f"[KAG Node] Query Engine 未召回任何强相关知识，Query: {query}")
        return {
            "raw_retrieved_candidates": [],
            "knowledge_snapshot": evidence_packet.model_dump(mode="json"),
            "next_actions": ["context_builder"],
        }

    logger.info(f"[KAG Node] 成功召回 {len(raw_candidates)} 条原始片段，流转至 Context Builder。")

    # ==========================================
    # 阶段四：状态流转 (交棒给 Context Builder)
    # ==========================================
    return {
        "raw_retrieved_candidates": raw_candidates,
        "knowledge_snapshot": evidence_packet.model_dump(mode="json"),
        "next_actions": ["context_builder"],
    }
