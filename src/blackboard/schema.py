"""
黑板核心Schema：状态枚举、数据模型

所有模块的状态流转必须严格遵循此定义

优化说明：补齐Agent反思链路核心字段、修正知识流概念误区、补充业务场景必需的状态节点
"""
from enum import Enum
from typing import Dict, Any, Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from src.common.contracts import ExecutionIntent, ExecutionRecord, TaskEnvelope
from src.common.utils import get_utc_now


# -------------------------- 全局总状态枚举（Global Blackboard管控） --------------------------
class GlobalStatus(str, Enum):
    """
    任务全局总状态，定义任务的整体阶段
    """
    PENDING = "pending"                # 待处理，刚创建任务
    ROUTING = "routing"                # 意图路由（Router节点评估需求）
    PREPARING_CONTEXT = "preparing_context" # 抽取结构化文件中的表格结构，像表头信息，使用data_inspector
    RETRIEVING = "retrieving"          # 检索，使用kag
    
    ANALYZING = "analyzing"            # 需求分析中（Analyst Agent负责）
    CODING = "coding"                  # 代码生成中（Coder Agent负责）
    AUDITING = "auditing"              # 代码审计中（Auditor Agent负责）
    EXECUTING = "executing"            # 沙箱执行中（Executor Agent负责）
    DEBUGGING = "debugging"            # 代码调试中（Coder Agent负责，前端展示用）
    
    EVALUATING = "evaluating"          # 结果评估中（Evaluator Agent负责）
    SUMMARIZING = "summarizing"              # 总结回复中（生成最终自然语言报告）
    HARVESTING = "harvesting"                # 经验沉淀中（后台Skill Harvester异步提取技能）

    WAITING_FOR_HUMAN = "waiting_for_human"  # 新增：阻断/异常时等待人工介入
    SUCCESS = "success"                # 任务成功完成
    FAILED = "failed"                  # 任务失败
    ARCHIVED = "archived"              # 任务已归档


# -------------------------- 核心数据模型 --------------------------
class TaskGlobalState(BaseModel):
    """任务全局状态模型（Global Blackboard存储）"""
    task_id: str = Field(description="任务唯一ID")
    tenant_id: str = Field(description="租户ID")
    workspace_id: str = Field(description="让事件具备空间隔离属性", default="default_ws")
    input_query: str = Field(description="用户原始查询")
    global_status: GlobalStatus = Field(default=GlobalStatus.PENDING, description="全局总状态")
    sub_status: Optional[str] = Field(default=None, description="当前子状态，用于前端进度展示")
    
    # 细化重试控制，防止大模型陷入无限回退死循环
    max_retries: int = Field(default=3, description="最大允许回退重试次数")
    current_retries: int = Field(default=0, description="当前已回退重试次数")

    # 作用：前端直接取这两个字段展示友好的报错，运维看这个字段秒懂卡在哪一步
    failure_type: Optional[str] = Field(
        default=None, 
        description="失败类型/节点，如: routing / retrieval / coding / executing / other"
    )
    error_message: Optional[str] = Field(
        default=None, 
        description="失败极简描述（200字内），如 '代码重试3次仍未能修复语法错误'"
    )
    
    created_at: datetime = Field(default_factory=get_utc_now, description="创建时间")
    updated_at: datetime = Field(default_factory=get_utc_now, description="更新时间")

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

class RetrievalPlan(BaseModel):
    """DAG 传递给 Query Engine 的高级可控检索执行计划"""
    enable_qu: bool = Field(default=True, description="是否启用前置查询理解(QU)")
    enable_rewrite: bool = Field(default=True, description="是否启用 Query 重写")
    enable_filter: bool = Field(default=True, description="是否提取并下发 Filter")
    recall_strategies: List[str] = Field(default=["bm25", "splade", "vector", "graph"], description="授权启用的召回通道")
    routing_strategy: str = Field(default="hybrid", description="路由策略: rule / llm / hybrid")
    enable_rerank: bool = Field(default=True, description="是否启用交叉重排")
    top_k: int = Field(default=15, description="最终保留的文档片段数")
    budget_tokens: int = Field(default=4000, description="上下文预算上限")
    max_latency_ms: int = Field(default=800, description="最大允许延迟(超时降级用)")
    cost_budget: float = Field(default=0.01, description="单次检索LLM成本预算($)")

class ExecutionData(BaseModel):
    """
    执行流数据模型（Execution Blackboard存储）

    生命周期：与单任务绑定，任务结束后归档

    采用指针模式，防止黑板膨胀
    """
    task_id: str
    tenant_id: str
    workspace_id: str = Field(default="default_ws", description="当前任务所属的工作空间")
    task_envelope: Optional[TaskEnvelope] = Field(default=None, description="控制面生成的稳定任务信封")
    execution_intent: Optional[ExecutionIntent] = Field(default=None, description="Router 生成的静态/动态执行意图")
    
    # 作用：虽然LangGraph有自己的图状态，但把决策落盘到黑板，可以让后续的总结节点(Summarizer)
    # 知道“我们刚才有没有查过数据库”，同时方便后期回溯分析。
    routing_decision: Optional[str] = Field(
        default=None, 
        description="路由决策结果：to_inspector / to_kag / to_analyst"
    )
    routing_reasons: Optional[str] = Field(
        default=None,
        description="决策缘由"
    )
    routing_mode: str = Field(default="static", description="本轮任务的主路由模式：static / dynamic")
    complexity_score: float = Field(default=0.0, description="Router 输出的复杂度评分")
    dynamic_reason: Optional[str] = Field(default=None, description="触发动态节点的解释")
    candidate_skills: List[Dict[str, Any]] = Field(default_factory=list, description="Router 命中的静态 Skill 候选")

    # === 【瘦身1】环境与物理数据感知 ===
    structured_datasets: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="""
        结构化数据集列表。API上传时写入基础信息，Data Inspector探查后补全Schema和读取参数。
        格式示例：
        [{
            "file_name": "销售表.csv",
            "path": "/data/tenant_1/sales.csv",
            "schema": "【表头】...", 
            "load_kwargs": {"encoding": "gbk", "sep": ","}
        }]
        """
    )

    # === 【瘦身2】知识与技能上下文 (Retriever注入) ===
    business_documents: List[Dict[str, Any]] = Field(
        default_factory=list, 
        description="""
        上传的非结构化文档列表及处理状态。
        格式示例：
        [{
            "path": "/data/docs/rule_A.pdf",
            "is_newly_uploaded": True,
            "status": "parsed"  # pending / parsed
        }]
        """
    )
    business_context: Dict[str, Any] = Field(
        default_factory=lambda: {
            "rules": [],    # 具体的业务规则文本
            "metrics": [],  # 指标口径定义
            "filters": [],  # 数据过滤条件
            "sources": []   # 溯源文档列表
        },
        description="从KAG检索到的结构化强相关业务规则，供下游精准调用"
    )
    knowledge_snapshot: Dict[str, Any] = Field(default_factory=dict, description="知识平面返回的规范化 EvidencePacket 投影")
    business_context_refs: List[str] = Field(default_factory=list, description="相关PDF片段在向量库中的Doc_ID，用于溯源")
    matched_skills: List[Dict[str, Any]] = Field(default_factory=list, description="检索到的可用Skill函数签名与描述")
    
    # --- 核心生产物 ---
    analysis_plan: Optional[str] = Field(default=None, description="Analyst Agent输出的分析执行计划")
    generated_code: Optional[str] = Field(default=None, description="Coder Agent输出的可执行Python代码")

    # 这个任务可用的历史资产名录（通过检索户口本表获得）
    # 当 Analyst 节点启动时，它第一眼看到的就是这个名录！
    available_history_assets: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="包含历史文件的 semantic_summary 和 物理ID，供 LLM 挑选"
    )
    
    # --- 反思与自愈机制核心字段 ---
    latest_error_traceback: Optional[str] = Field(
        default=None,
        description="上一环节打回的反馈原因（审计失败/执行报错/评估不通过），Agent生成时强制注入Prompt"
    )
    
    # --- 执行结果与产物 ---
    audit_result: Optional[Dict[str, Any]] = Field(default=None, description="Auditor Agent输出的审计结果")
    execution_result: Optional[Dict[str, Any]] = Field(default=None, description="沙箱执行stdout/stderr、退出码等日志")
    artifacts: List[Dict[str, str]] = Field(
        default_factory=list,
        description="沙箱生成的产物文件路径/URL列表（如图表PNG、清洗后的CSV、Excel文件），格式：产物列表，格式: [{'path': '/outputs/a.png', 'type': 'image'}, {'path': 'b.csv', 'type': 'data'}]"
    )

    # === 生产级追踪与运维区 ===
    trace_log_path: Optional[str] = Field(
        default=None, 
        description="详细的 intermediate_steps (每一步的完整Prompt/Response) 写入本地日志，黑板只存路径"
    )
    token_usage: Dict[str, int] = Field(
        default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        description="当前任务累计消耗的Token统计，用于租户计费预警"
    )
    
    evaluation_result: Optional[Dict[str, Any]] = Field(default=None, description="Evaluator Agent输出的评估结果")
    dynamic_request: Optional[Dict[str, Any]] = Field(default=None, description="发往动态引擎的标准化请求载荷")
    runtime_backend: Optional[str] = Field(default=None, description="当前动态链路选择的运行时后端")
    dynamic_status: Optional[str] = Field(default=None, description="动态引擎执行状态")
    dynamic_summary: Optional[str] = Field(default=None, description="动态引擎返回的摘要")
    dynamic_runtime_metadata: Dict[str, Any] = Field(default_factory=dict, description="动态运行时的实际模式、fallback 原因与诊断元数据")
    dynamic_trace: List[Dict[str, Any]] = Field(default_factory=list, description="动态子代理关键轨迹事件")
    dynamic_trace_refs: List[str] = Field(default_factory=list, description="动态执行轨迹引用")
    dynamic_artifacts: List[str] = Field(default_factory=list, description="动态执行产物引用")
    recommended_static_skill: Optional[Dict[str, Any]] = Field(default=None, description="动态链路推荐沉淀的静态 Skill")
    harvested_skill_candidates: List[Dict[str, Any]] = Field(default_factory=list, description="Skill Harvester 抽取出的技能候选")
    approved_skills: List[Dict[str, Any]] = Field(default_factory=list, description="通过验证和授权、可供路由与分析阶段复用的技能")
    historical_skill_matches: List[Dict[str, Any]] = Field(default_factory=list, description="当前任务命中的历史 approved skill 及其匹配来源/用途")
    return_to_node: Optional[str] = Field(default=None, description="动态链路执行后建议回流的 DAG 节点")
    governance_mode: str = Field(default="standard", description="Harness 治理模式：core / standard")
    governance_profile: str = Field(default="researcher", description="当前执行所使用的治理 profile")
    governance_decisions: List[Dict[str, Any]] = Field(default_factory=list, description="Harness 生成的 allow/deny 决策记录")
    decision_log: List[Dict[str, Any]] = Field(default_factory=list, description="控制面的规范化决策日志")
    governance_trace_ref: Optional[str] = Field(default=None, description="治理链路审计/trace 引用")
    execution_record: Optional[ExecutionRecord] = Field(default=None, description="标准化沙箱/运行时执行记录")
    parser_reports: List[Dict[str, Any]] = Field(default_factory=list, description="文档解析模式与诊断摘要")
    final_response: Optional[Dict[str, Any]] = Field(default=None, description="最终面向用户的统一响应载荷")
    updated_at: datetime = Field(default_factory=get_utc_now)


class KnowledgeData(BaseModel):
    """
    文件解析结果暂存模型（KAG解析流产物）

    生命周期：与单文件解析任务绑定，解析完成后持久化到租户级知识库

    概念纠正：租户级持久化知识资产通过独立的知识库接口对接，不与单任务状态绑定
    """
    tenant_id: str
    workspace_id: str = Field(default="default_ws", description="当前资产所属的工作空间")
    file_id: str = Field(description="文件唯一ID")
    file_meta: Optional[Dict[str, Any]] = Field(default=None, description="文件元数据：文件名、大小、类型、上传时间等")
    parsed_content_path: Optional[str] = Field(default=None, description="文档解析后生成的TXT/Markdown物理存储路径")
    parsed_doc_ref: Optional[str] = Field(default=None, description="结构化解析结果引用，如 doc_id 或对象存储键")
    parser_name: Optional[str] = Field(default=None, description="解析器名称，如 docling / fallback_text")
    parser_diagnostics: Dict[str, Any] = Field(default_factory=dict, description="解析阶段的诊断信息")
    content_stats: Dict[str, Any] = Field(default_factory=dict, description="解析后的内容统计，如 section/table/image 数量")
    
    # 抽取的海量实体直接送入Neo4j，黑板只存进度与统计指标
    extraction_status: str = Field(default="pending", description="状态：pending / extracting / completed / failed")
    extracted_node_count: int = Field(default=0, description="已成功写入Neo4j的实体节点数量统计")
    extracted_edge_count: int = Field(default=0, description="已成功写入Neo4j的关系数量统计")
    
    updated_at: datetime = Field(default_factory=get_utc_now)
