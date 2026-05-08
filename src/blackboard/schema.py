"""
黑板核心Schema：状态枚举、数据模型

所有模块的状态流转必须严格遵循此定义

优化说明：补齐Agent反思链路核心字段、修正知识流概念误区、补充业务场景必需的状态节点
"""

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.common.contracts import (
    ArtifactVerificationResult,
    DebugAttemptRecord,
    DynamicResumeOverlay,
    ExecutionIntent,
    ExecutionRecord,
    ExecutionStrategy,
    GeneratorManifest,
    StaticEvidenceBundle,
    StaticProgramSpec,
    StaticRepairPlan,
    TaskEnvelope,
)
from src.common.control_plane import parser_reports_from_documents
from src.common.utils import get_utc_now
from src.kag.compiler.types import CompiledKnowledgeState
from src.skillnet.skill_schema import SkillReplayCase


# -------------------------- 全局总状态枚举（Global Blackboard管控） --------------------------
class GlobalStatus(StrEnum):
    """
    任务全局总状态，定义任务的整体阶段
    """

    PENDING = "pending"  # 待处理，刚创建任务
    ROUTING = "routing"  # 意图路由（Router节点评估需求）
    PREPARING_CONTEXT = "preparing_context"  # 抽取结构化文件中的表格结构，像表头信息，使用data_inspector
    RETRIEVING = "retrieving"  # 检索，使用kag

    ANALYZING = "analyzing"  # 需求分析中（Analyst Agent负责）
    CODING = "coding"  # 代码生成中（Coder Agent负责）
    AUDITING = "auditing"  # 代码审计中（Auditor Agent负责）
    EXECUTING = "executing"  # 沙箱执行中（Executor Agent负责）
    DEBUGGING = "debugging"  # 代码调试中（Coder Agent负责，前端展示用）

    EVALUATING = "evaluating"  # 结果评估中（Evaluator Agent负责）
    SUMMARIZING = "summarizing"  # 总结回复中（生成最终自然语言报告）
    HARVESTING = "harvesting"  # 经验沉淀中（后台Skill Harvester异步提取技能）

    WAITING_FOR_HUMAN = "waiting_for_human"  # 新增：阻断/异常时等待人工介入
    SUCCESS = "success"  # 任务成功完成
    FAILED = "failed"  # 任务失败
    ARCHIVED = "archived"  # 任务已归档


# -------------------------- 核心数据模型 --------------------------
class StrictStateModel(BaseModel):
    """黑板内部严格状态模型基类。"""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class StructuredDatasetState(StrictStateModel):
    """结构化数据资产的任务态表示。"""

    file_name: str
    path: str
    file_sha256: str | None = None
    dataset_schema: str = Field(default="")
    load_kwargs: dict[str, Any] = Field(default_factory=dict)


class BusinessDocumentState(StrictStateModel):
    """业务文档资产的任务态表示。"""

    file_name: str = ""
    path: str = ""
    file_sha256: str | None = None
    status: str = "pending"
    is_newly_uploaded: bool = False
    parse_mode: str = "default"
    parser_diagnostics: dict[str, Any] = Field(default_factory=dict)


class BusinessContextState(StrictStateModel):
    """静态链压缩后的业务上下文。"""

    rules: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class AnalysisBriefState(StrictStateModel):
    """Compact data-analysis brief derived from current task context."""

    question: str = ""
    analysis_mode: str = ""
    dataset_summaries: list[str] = Field(default_factory=list)
    business_rules: list[str] = Field(default_factory=list)
    business_metrics: list[str] = Field(default_factory=list)
    business_filters: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    known_gaps: list[str] = Field(default_factory=list)
    recommended_next_step: str = ""


class KnowledgeSnapshotState(StrictStateModel):
    """检索平面返回的规范化快照。"""

    query: str = ""
    rewritten_query: str = ""
    created_at: str | None = None
    tenant_id: str = ""
    workspace_id: str = "default_ws"
    hits: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    recall_strategies: list[str] = Field(default_factory=list)
    cache_hit: bool = False
    difficulty_score: float = 0.0
    is_multi_hop: bool = False
    budget_tokens: int | None = None
    metadata: "KnowledgeSnapshotMetadataState" = Field(default_factory=lambda: KnowledgeSnapshotMetadataState())

    @model_validator(mode="after")
    def _coerce_nested(self) -> "KnowledgeSnapshotState":
        if not isinstance(self.metadata, KnowledgeSnapshotMetadataState):
            object.__setattr__(self, "metadata", KnowledgeSnapshotMetadataState.model_validate(self.metadata))
        return self


class KnowledgeSnapshotMetadataState(StrictStateModel):
    """知识快照中最稳定的一组 metadata 字段。"""

    routing_strategy: str = ""
    candidate_count: int = 0
    selected_count: int = 0
    compressed_count: int = 0
    compression_strategy: str = ""
    pinned_evidence_refs: list[str] = Field(default_factory=list)
    dropped_candidate_count: int = 0
    analysis_mode: str = ""
    evidence_strategy: str = ""
    preferred_date_terms: list[str] = Field(default_factory=list)
    temporal_constraints: list[str] = Field(default_factory=list)
    dynamic_research: dict[str, Any] = Field(default_factory=dict)


class DynamicTraceEventState(StrictStateModel):
    """动态链统一轨迹事件。"""

    event_type: str = "progress"
    source_event_type: str | None = None
    agent_name: str = "runtime"
    step_name: str = "runtime_step"
    source: str = "dynamic_swarm"
    message: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    tool_call: dict[str, Any] | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class RuntimeMetadataState(StrictStateModel):
    """动态运行时元数据。"""

    effective_runtime_mode: str = ""
    requested_runtime_mode: str = ""
    sidecar_fallback_reason: str = ""
    sidecar_url: str = ""
    confidence: str = ""


class InputMountState(StrictStateModel):
    """静态链传给沙箱的输入挂载描述。"""

    kind: str = "input"
    host_path: str = ""
    container_path: str = ""
    file_name: str = ""
    encoding: str | None = None
    sep: str | None = None


class AuditResultState(StrictStateModel):
    """AST 审计结果的任务态表示。"""

    safe: bool = False
    reason: str = ""
    risk_type: str | None = None
    source_layer: str | None = None
    source_config: str | None = None
    trace_id: str = ""
    duration_seconds: float = 0.0


class DynamicRequestRuntimeState(StrictStateModel):
    """动态运行时请求中的 runtime 配置壳。"""

    runtime_mode: str = ""
    python_package: str | None = None
    sidecar_url: str | None = None
    config_path: str | None = None
    model_name: str | None = None
    max_steps: int = 0
    recursion_limit: int = 0
    subagent_enabled: bool = False
    plan_mode: bool = False


class DynamicRequestState(StrictStateModel):
    """发往动态引擎的标准化请求壳。"""

    task_id: str = ""
    tenant_id: str = ""
    query: str = ""
    system_context: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    sandbox_backend: str = ""
    runtime: DynamicRequestRuntimeState = Field(default_factory=DynamicRequestRuntimeState)

    @model_validator(mode="after")
    def _coerce_nested(self) -> "DynamicRequestState":
        if not isinstance(self.runtime, DynamicRequestRuntimeState):
            object.__setattr__(self, "runtime", DynamicRequestRuntimeState.model_validate(self.runtime))
        return self


class NodeCheckpointState(StrictStateModel):
    """节点级检查点。"""

    status: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    failed_at: str | None = None
    error: str | None = None
    attempt_count: int = 0
    output_patch: "NodeOutputPatchState" = Field(default_factory=lambda: NodeOutputPatchState())


class SkillValidationState(StrictStateModel):
    """技能校验结果。"""

    status: str = ""
    valid: bool = False
    reason_count: int = 0
    reasons: list[str] = Field(default_factory=list)
    required_capability_count: int = 0
    replay_case_count: int = 0
    authorization_allowed: bool | None = None


class SkillPromotionState(StrictStateModel):
    """技能提升结果。"""

    status: str = ""
    summary: str = ""
    ready_for_router: bool = False
    provenance: "SkillProvenanceState" = Field(default_factory=lambda: SkillProvenanceState())
    promoted_at: str | None = None
    source_task_id: str | None = None
    source_trace_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _coerce_nested(self) -> "SkillPromotionState":
        if not isinstance(self.provenance, SkillProvenanceState):
            object.__setattr__(self, "provenance", SkillProvenanceState.model_validate(self.provenance))
        return self


class SkillProvenanceState(StrictStateModel):
    """技能提升来源信息。"""

    validation_status: str = ""
    authorization_allowed: bool | None = None


class SkillUsageState(StrictStateModel):
    """技能使用统计。"""

    usage_count: int = 0
    last_used_at: str | None = None
    last_task_id: str | None = None
    last_stage: str | None = None
    success_count: int = 0
    failure_count: int = 0
    success_rate: float = 0.0
    last_outcome_task_id: str | None = None
    last_outcome_success: bool | None = None


class SkillAuthorizationState(StrictStateModel):
    """技能授权结果。"""

    skill_name: str = ""
    profile: str = ""
    allowed: bool = False
    requested_capabilities: list[str] = Field(default_factory=list)
    allowed_capabilities: list[str] = Field(default_factory=list)
    denied_capabilities: list[str] = Field(default_factory=list)
    unknown_capabilities: list[str] = Field(default_factory=list)


class SkillRecommendedState(StrictStateModel):
    """技能推荐来源元数据。"""

    source: str = ""
    source_task_type: str = ""
    confidence: str = ""


class SkillMetadataState(StrictStateModel):
    """技能任务态元数据。"""

    summary: str = ""
    source: str = ""
    trace_count: int = 0
    match_source: str = ""
    governance_profile: str = ""
    recommended: SkillRecommendedState = Field(default_factory=SkillRecommendedState)
    authorization: SkillAuthorizationState = Field(default_factory=SkillAuthorizationState)

    @model_validator(mode="after")
    def _coerce_nested(self) -> "SkillMetadataState":
        if not isinstance(self.recommended, SkillRecommendedState):
            object.__setattr__(self, "recommended", SkillRecommendedState.model_validate(self.recommended))
        if not isinstance(self.authorization, SkillAuthorizationState):
            object.__setattr__(self, "authorization", SkillAuthorizationState.model_validate(self.authorization))
        return self


class ReplayCaseState(StrictStateModel):
    """任务态中的 replay case 表示。"""

    case_id: str = ""
    description: str = ""
    input_query: str = ""
    expected_signals: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_skill_replay_case(cls, case: SkillReplayCase) -> "ReplayCaseState":
        return cls.model_validate(case.model_dump(mode="json"))


class SkillPayloadState(StrictStateModel):
    """任务态中可复用技能的统一表示。"""

    name: str = ""
    description: str = ""
    source_task_type: str = ""
    winning_steps: list[str] = Field(default_factory=list)
    code_refs: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    replay_cases: list[ReplayCaseState] = Field(default_factory=list)
    validation: SkillValidationState = Field(default_factory=SkillValidationState)
    promotion: SkillPromotionState = Field(default_factory=SkillPromotionState)
    metadata: SkillMetadataState = Field(default_factory=SkillMetadataState)
    usage: SkillUsageState = Field(default_factory=SkillUsageState)
    authorization: SkillAuthorizationState = Field(default_factory=SkillAuthorizationState)

    @model_validator(mode="after")
    def _coerce_nested(self) -> "SkillPayloadState":
        object.__setattr__(
            self,
            "replay_cases",
            [
                item if isinstance(item, ReplayCaseState) else ReplayCaseState.model_validate(item)
                for item in self.replay_cases
            ],
        )
        if not isinstance(self.validation, SkillValidationState):
            object.__setattr__(self, "validation", SkillValidationState.model_validate(self.validation))
        if not isinstance(self.promotion, SkillPromotionState):
            object.__setattr__(self, "promotion", SkillPromotionState.model_validate(self.promotion))
        if not isinstance(self.metadata, SkillMetadataState):
            object.__setattr__(self, "metadata", SkillMetadataState.model_validate(self.metadata))
        if not isinstance(self.usage, SkillUsageState):
            object.__setattr__(self, "usage", SkillUsageState.model_validate(self.usage))
        if not isinstance(self.authorization, SkillAuthorizationState):
            object.__setattr__(self, "authorization", SkillAuthorizationState.model_validate(self.authorization))
        return self


class HistoricalSkillMatchState(StrictStateModel):
    """历史技能命中记录的统一表示。"""

    name: str = ""
    required_capabilities: list[str] = Field(default_factory=list)
    promotion: SkillPromotionState = Field(default_factory=SkillPromotionState)
    usage: SkillUsageState = Field(default_factory=SkillUsageState)
    match_source: str = ""
    match_reason: str = ""
    match_score: int = 0
    selected_by_stages: list[str] = Field(default_factory=list)
    selected_by_stage_details: list[dict[str, Any]] = Field(default_factory=list)
    used_in_codegen: bool = False
    used_replay_case_ids: list[str] = Field(default_factory=list)
    used_capabilities: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _coerce_nested(self) -> "HistoricalSkillMatchState":
        if not isinstance(self.promotion, SkillPromotionState):
            object.__setattr__(self, "promotion", SkillPromotionState.model_validate(self.promotion))
        if not isinstance(self.usage, SkillUsageState):
            object.__setattr__(self, "usage", SkillUsageState.model_validate(self.usage))
        return self


class NodeOutputPatchState(StrictStateModel):
    """
    节点 checkpoint 中缓存的输出 patch。

    这层的目标不是把每个节点的返回值收成完全封闭的 union，
    而是先把恢复链路里最常见、最关键的字段纳入统一结构，
    同时保留 `extra` 容忍未知补丁字段。
    """

    next_actions: list[str] = Field(default_factory=list)
    execution_intent: ExecutionIntent | None = None
    task_envelope: TaskEnvelope | None = None
    refined_context: str = ""
    raw_retrieved_candidates: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_snapshot: KnowledgeSnapshotState | None = None
    analysis_brief: AnalysisBriefState | None = None
    analysis_plan: str = ""
    generated_code: str = ""
    execution_strategy: ExecutionStrategy | None = None
    static_evidence_bundle: StaticEvidenceBundle | None = None
    program_spec: StaticProgramSpec | None = None
    repair_plan: StaticRepairPlan | None = None
    debug_attempts: list[DebugAttemptRecord] = Field(default_factory=list)
    generator_manifest: GeneratorManifest | None = None
    artifact_verification: ArtifactVerificationResult | None = None
    input_mounts: list[InputMountState] = Field(default_factory=list)
    audit_result: AuditResultState = Field(default_factory=AuditResultState)
    retry_count: int | None = None
    blocked: bool | None = None
    block_reason: str | None = None
    execution_record: ExecutionRecord | None = None
    dynamic_request: DynamicRequestState | None = None
    runtime_backend: str | None = None
    dynamic_status: str | None = None
    dynamic_summary: str | None = None
    dynamic_continuation: str | None = None
    dynamic_resume_overlay: DynamicResumeOverlay | None = None
    dynamic_next_static_steps: list[str] = Field(default_factory=list)
    dynamic_runtime_metadata: RuntimeMetadataState | None = None
    dynamic_trace: list[DynamicTraceEventState] = Field(default_factory=list)
    dynamic_trace_refs: list[str] = Field(default_factory=list)
    dynamic_artifacts: list[str] = Field(default_factory=list)
    dynamic_research_findings: list[str] = Field(default_factory=list)
    dynamic_evidence_refs: list[str] = Field(default_factory=list)
    dynamic_open_questions: list[str] = Field(default_factory=list)
    dynamic_suggested_static_actions: list[str] = Field(default_factory=list)
    recommended_static_skill: dict[str, Any] | None = None
    final_response: dict[str, Any] = Field(default_factory=dict)
    decision_log: list[dict[str, Any]] = Field(default_factory=list)
    governance_trace_ref: str | None = None

    @model_validator(mode="after")
    def _coerce_nested(self) -> "NodeOutputPatchState":
        if self.execution_intent is not None and not isinstance(self.execution_intent, ExecutionIntent):
            object.__setattr__(self, "execution_intent", ExecutionIntent.model_validate(self.execution_intent))
        if self.task_envelope is not None and not isinstance(self.task_envelope, TaskEnvelope):
            object.__setattr__(self, "task_envelope", TaskEnvelope.model_validate(self.task_envelope))
        if self.knowledge_snapshot is not None and not isinstance(self.knowledge_snapshot, KnowledgeSnapshotState):
            object.__setattr__(
                self, "knowledge_snapshot", KnowledgeSnapshotState.model_validate(self.knowledge_snapshot)
            )
        if self.analysis_brief is not None and not isinstance(self.analysis_brief, AnalysisBriefState):
            object.__setattr__(self, "analysis_brief", AnalysisBriefState.model_validate(self.analysis_brief))
        if self.execution_strategy is not None and not isinstance(self.execution_strategy, ExecutionStrategy):
            object.__setattr__(self, "execution_strategy", ExecutionStrategy.model_validate(self.execution_strategy))
        if self.static_evidence_bundle is not None and not isinstance(self.static_evidence_bundle, StaticEvidenceBundle):
            object.__setattr__(
                self,
                "static_evidence_bundle",
                StaticEvidenceBundle.model_validate(self.static_evidence_bundle),
            )
        if self.program_spec is not None and not isinstance(self.program_spec, StaticProgramSpec):
            object.__setattr__(self, "program_spec", StaticProgramSpec.model_validate(self.program_spec))
        if self.repair_plan is not None and not isinstance(self.repair_plan, StaticRepairPlan):
            object.__setattr__(self, "repair_plan", StaticRepairPlan.model_validate(self.repair_plan))
        object.__setattr__(
            self,
            "debug_attempts",
            [
                item if isinstance(item, DebugAttemptRecord) else DebugAttemptRecord.model_validate(item)
                for item in self.debug_attempts
            ],
        )
        if self.generator_manifest is not None and not isinstance(self.generator_manifest, GeneratorManifest):
            object.__setattr__(self, "generator_manifest", GeneratorManifest.model_validate(self.generator_manifest))
        if self.artifact_verification is not None and not isinstance(
            self.artifact_verification, ArtifactVerificationResult
        ):
            object.__setattr__(
                self,
                "artifact_verification",
                ArtifactVerificationResult.model_validate(self.artifact_verification),
            )
        if self.execution_record is not None and not isinstance(self.execution_record, ExecutionRecord):
            object.__setattr__(self, "execution_record", ExecutionRecord.model_validate(self.execution_record))
        if not isinstance(self.audit_result, AuditResultState):
            object.__setattr__(self, "audit_result", AuditResultState.model_validate(self.audit_result))
        if self.dynamic_request is not None and not isinstance(self.dynamic_request, DynamicRequestState):
            object.__setattr__(self, "dynamic_request", DynamicRequestState.model_validate(self.dynamic_request))
        if self.dynamic_resume_overlay is not None and not isinstance(
            self.dynamic_resume_overlay, DynamicResumeOverlay
        ):
            object.__setattr__(
                self,
                "dynamic_resume_overlay",
                DynamicResumeOverlay.model_validate(self.dynamic_resume_overlay),
            )
        if self.dynamic_runtime_metadata is not None and not isinstance(
            self.dynamic_runtime_metadata, RuntimeMetadataState
        ):
            object.__setattr__(
                self,
                "dynamic_runtime_metadata",
                RuntimeMetadataState.model_validate(self.dynamic_runtime_metadata),
            )
        object.__setattr__(
            self,
            "dynamic_trace",
            [
                item if isinstance(item, DynamicTraceEventState) else DynamicTraceEventState.model_validate(item)
                for item in self.dynamic_trace
            ],
        )
        object.__setattr__(
            self,
            "input_mounts",
            [
                item if isinstance(item, InputMountState) else InputMountState.model_validate(item)
                for item in self.input_mounts
            ],
        )
        return self


def _as_mapping_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


class TaskGlobalState(StrictStateModel):
    """任务全局状态模型（Global Blackboard存储）"""

    task_id: str = Field(description="任务唯一ID")
    tenant_id: str = Field(description="租户ID")
    workspace_id: str = Field(description="让事件具备空间隔离属性", default="default_ws")
    input_query: str = Field(description="用户原始查询")
    global_status: GlobalStatus = Field(default=GlobalStatus.PENDING, description="全局总状态")
    sub_status: str | None = Field(default=None, description="当前子状态，用于前端进度展示")

    # 细化重试控制，防止代码修复链路陷入无限回退死循环。
    # 这里的语义已经明确收窄：
    # - 只统计 Auditor <-> Debugger 之间的修复重试
    # - 不等同于“整个任务生命周期中的所有重试”
    max_retries: int = Field(default=3, description="最大允许代码修复回退重试次数")
    current_retries: int = Field(default=0, description="当前已代码修复回退重试次数")

    # 作用：前端直接取这两个字段展示友好的报错，运维看这个字段秒懂卡在哪一步
    failure_type: str | None = Field(
        default=None, description="失败类型/节点，如: routing / retrieval / coding / executing / other"
    )
    error_message: str | None = Field(
        default=None, description="失败极简描述（200字内），如 '代码重试3次仍未能修复语法错误'"
    )
    idempotency_key: str | None = Field(default=None, description="客户端可选传入的幂等键")
    request_fingerprint: str | None = Field(default=None, description="用于校验同一幂等键下请求体是否一致")

    created_at: datetime = Field(default_factory=get_utc_now, description="创建时间")
    updated_at: datetime = Field(default_factory=get_utc_now, description="更新时间")

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class RetrievalPlan(BaseModel):
    """DAG 传递给 Query Engine 的高级可控检索执行计划"""

    enable_qu: bool = Field(default=True, description="是否启用前置查询理解(QU)")
    enable_rewrite: bool = Field(default=True, description="是否启用 Query 重写")
    enable_filter: bool = Field(default=True, description="是否提取并下发 Filter")
    recall_strategies: list[str] = Field(
        default=["bm25", "splade", "vector", "graph"], description="授权启用的召回通道"
    )
    routing_strategy: str = Field(default="hybrid", description="路由策略: rule / llm / hybrid")
    enable_rerank: bool = Field(default=True, description="是否启用交叉重排")
    top_k: int = Field(default=15, ge=1, le=50, description="最终保留的文档片段数")
    budget_tokens: int = Field(default=4000, description="上下文预算上限")
    max_latency_ms: int = Field(default=800, description="最大允许延迟(超时降级用)")
    cost_budget: float = Field(default=0.01, description="单次检索LLM成本预算($)")
    preferred_date_terms: list[str] = Field(default_factory=list, description="编译态偏好的日期列名")
    temporal_constraints: list[str] = Field(default_factory=list, description="编译态时间约束摘要")


class ExecutionControlState(StrictStateModel):
    """Control-plane state for one task execution."""

    task_envelope: TaskEnvelope | None = None
    execution_intent: ExecutionIntent | None = None
    decision_log: list[dict[str, Any]] = Field(default_factory=list)
    governance_trace_ref: str | None = None
    node_checkpoints: dict[str, NodeCheckpointState] = Field(default_factory=dict)
    final_response: dict[str, Any] | None = None
    updated_at: datetime = Field(default_factory=get_utc_now)

    @model_validator(mode="after")
    def _coerce_typed_payloads(self) -> "ExecutionControlState":
        if self.task_envelope is not None and not isinstance(self.task_envelope, TaskEnvelope):
            object.__setattr__(self, "task_envelope", TaskEnvelope.model_validate(self.task_envelope))
        if self.execution_intent is not None and not isinstance(self.execution_intent, ExecutionIntent):
            object.__setattr__(self, "execution_intent", ExecutionIntent.model_validate(self.execution_intent))
        object.__setattr__(
            self,
            "node_checkpoints",
            {
                str(name): checkpoint
                if isinstance(checkpoint, NodeCheckpointState)
                else NodeCheckpointState.model_validate(checkpoint)
                for name, checkpoint in dict(self.node_checkpoints or {}).items()
            },
        )
        return self


class ExecutionInputState(StrictStateModel):
    """Physical input assets attached to one task execution."""

    structured_datasets: list[StructuredDatasetState] = Field(default_factory=list)
    business_documents: list[BusinessDocumentState] = Field(default_factory=list)

    @model_validator(mode="after")
    def _coerce_typed_payloads(self) -> "ExecutionInputState":
        object.__setattr__(
            self,
            "structured_datasets",
            [
                item if isinstance(item, StructuredDatasetState) else StructuredDatasetState.model_validate(item)
                for item in self.structured_datasets
            ],
        )
        object.__setattr__(
            self,
            "business_documents",
            [
                item if isinstance(item, BusinessDocumentState) else BusinessDocumentState.model_validate(item)
                for item in self.business_documents
            ],
        )
        return self


class ExecutionKnowledgeState(StrictStateModel):
    """Knowledge-side facts used by static and dynamic execution."""

    business_context: BusinessContextState = Field(default_factory=BusinessContextState)
    knowledge_snapshot: KnowledgeSnapshotState = Field(default_factory=KnowledgeSnapshotState)
    analysis_brief: AnalysisBriefState = Field(default_factory=AnalysisBriefState)
    compiled: CompiledKnowledgeState = Field(default_factory=CompiledKnowledgeState)

    @model_validator(mode="after")
    def _coerce_typed_payloads(self) -> "ExecutionKnowledgeState":
        if not isinstance(self.business_context, BusinessContextState):
            object.__setattr__(self, "business_context", BusinessContextState.model_validate(self.business_context))
        if not isinstance(self.knowledge_snapshot, KnowledgeSnapshotState):
            object.__setattr__(
                self, "knowledge_snapshot", KnowledgeSnapshotState.model_validate(self.knowledge_snapshot)
            )
        if not isinstance(self.analysis_brief, AnalysisBriefState):
            object.__setattr__(self, "analysis_brief", AnalysisBriefState.model_validate(self.analysis_brief))
        if not isinstance(self.compiled, CompiledKnowledgeState):
            object.__setattr__(self, "compiled", CompiledKnowledgeState.model_validate(self.compiled))
        return self


class ExecutionStaticState(StrictStateModel):
    """Static execution chain outputs and execution results."""

    generated_code: str | None = None
    execution_strategy: ExecutionStrategy | None = None
    static_evidence_bundle: StaticEvidenceBundle | None = None
    program_spec: StaticProgramSpec | None = None
    repair_plan: StaticRepairPlan | None = None
    debug_attempts: list[DebugAttemptRecord] = Field(default_factory=list)
    generator_manifest: GeneratorManifest | None = None
    artifact_verification: ArtifactVerificationResult | None = None
    latest_error_traceback: str | None = None
    audit_result: AuditResultState | None = None
    execution_record: ExecutionRecord | None = None

    @model_validator(mode="after")
    def _coerce_typed_payloads(self) -> "ExecutionStaticState":
        if self.execution_strategy is not None and not isinstance(self.execution_strategy, ExecutionStrategy):
            object.__setattr__(self, "execution_strategy", ExecutionStrategy.model_validate(self.execution_strategy))
        if self.static_evidence_bundle is not None and not isinstance(self.static_evidence_bundle, StaticEvidenceBundle):
            object.__setattr__(
                self,
                "static_evidence_bundle",
                StaticEvidenceBundle.model_validate(self.static_evidence_bundle),
            )
        if self.program_spec is not None and not isinstance(self.program_spec, StaticProgramSpec):
            object.__setattr__(self, "program_spec", StaticProgramSpec.model_validate(self.program_spec))
        if self.repair_plan is not None and not isinstance(self.repair_plan, StaticRepairPlan):
            object.__setattr__(self, "repair_plan", StaticRepairPlan.model_validate(self.repair_plan))
        object.__setattr__(
            self,
            "debug_attempts",
            [
                item if isinstance(item, DebugAttemptRecord) else DebugAttemptRecord.model_validate(item)
                for item in self.debug_attempts
            ],
        )
        if self.generator_manifest is not None and not isinstance(self.generator_manifest, GeneratorManifest):
            object.__setattr__(self, "generator_manifest", GeneratorManifest.model_validate(self.generator_manifest))
        if self.artifact_verification is not None and not isinstance(
            self.artifact_verification, ArtifactVerificationResult
        ):
            object.__setattr__(
                self,
                "artifact_verification",
                ArtifactVerificationResult.model_validate(self.artifact_verification),
            )
        if self.audit_result is not None and not isinstance(self.audit_result, AuditResultState):
            object.__setattr__(self, "audit_result", AuditResultState.model_validate(self.audit_result))
        if self.execution_record is not None and not isinstance(self.execution_record, ExecutionRecord):
            object.__setattr__(self, "execution_record", ExecutionRecord.model_validate(self.execution_record))
        return self


class ExecutionDynamicState(StrictStateModel):
    """Dynamic runtime state for one task execution."""

    request: DynamicRequestState | None = None
    runtime_backend: str | None = None
    status: str | None = None
    summary: str | None = None
    continuation: str | None = None
    resume_overlay: DynamicResumeOverlay | None = None
    next_static_steps: list[str] = Field(default_factory=list)
    runtime_metadata: RuntimeMetadataState = Field(default_factory=RuntimeMetadataState)
    trace: list[DynamicTraceEventState] = Field(default_factory=list)
    trace_refs: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    research_findings: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    suggested_static_actions: list[str] = Field(default_factory=list)
    recommended_static_skill: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _coerce_typed_payloads(self) -> "ExecutionDynamicState":
        if self.request is not None and not isinstance(self.request, DynamicRequestState):
            object.__setattr__(self, "request", DynamicRequestState.model_validate(self.request))
        if self.resume_overlay is not None and not isinstance(self.resume_overlay, DynamicResumeOverlay):
            object.__setattr__(self, "resume_overlay", DynamicResumeOverlay.model_validate(self.resume_overlay))
        if not isinstance(self.runtime_metadata, RuntimeMetadataState):
            object.__setattr__(self, "runtime_metadata", RuntimeMetadataState.model_validate(self.runtime_metadata))
        object.__setattr__(
            self,
            "trace",
            [
                item if isinstance(item, DynamicTraceEventState) else DynamicTraceEventState.model_validate(item)
                for item in self.trace
            ],
        )
        return self


class ExecutionData(StrictStateModel):
    """
    执行流数据模型（Execution Blackboard存储）

    生命周期：与单任务绑定，任务结束后归档

    采用指针模式，防止黑板膨胀
    """

    task_id: str
    tenant_id: str
    workspace_id: str = Field(default="default_ws", description="当前任务所属的工作空间")
    control: ExecutionControlState = Field(default_factory=ExecutionControlState)
    inputs: ExecutionInputState = Field(default_factory=ExecutionInputState)
    knowledge: ExecutionKnowledgeState = Field(default_factory=ExecutionKnowledgeState)
    static: ExecutionStaticState = Field(default_factory=ExecutionStaticState)
    dynamic: ExecutionDynamicState = Field(default_factory=ExecutionDynamicState)

    @model_validator(mode="after")
    def _coerce_typed_payloads(self) -> "ExecutionData":
        if not isinstance(self.control, ExecutionControlState):
            object.__setattr__(self, "control", ExecutionControlState.model_validate(self.control))
        if not isinstance(self.inputs, ExecutionInputState):
            object.__setattr__(self, "inputs", ExecutionInputState.model_validate(self.inputs))
        if not isinstance(self.knowledge, ExecutionKnowledgeState):
            object.__setattr__(self, "knowledge", ExecutionKnowledgeState.model_validate(self.knowledge))
        if not isinstance(self.static, ExecutionStaticState):
            object.__setattr__(self, "static", ExecutionStaticState.model_validate(self.static))
        if not isinstance(self.dynamic, ExecutionDynamicState):
            object.__setattr__(self, "dynamic", ExecutionDynamicState.model_validate(self.dynamic))
        return self


class KnowledgeData(StrictStateModel):
    """
    知识子黑板中的任务级知识态快照。

    这里强调两点：

    1. 它不是 `ExecutionData` 的替代品。
       `ExecutionData` 仍然是“任务怎么被执行”的主状态，
       包含执行意图、执行结果、最终回复等编排态信息。

    2. 它也不是长期知识库本身。
       真正的 chunk / vector / graph 资产仍然在存储层与知识库里；
       `KnowledgeData` 只保留“这次任务当前关联了哪些文档、
       这些文档解析到了什么状态、最近一次检索拿到了什么快照”。

    这样拆分的目的，是让知识面状态有独立边界，后续如果：
    - 前端单独做知识资产页
    - 只看文档解析与检索状态
    - 为知识链路做独立恢复/审计
    都不需要再从执行态对象里反推。
    """

    task_id: str
    tenant_id: str
    workspace_id: str = Field(default="default_ws", description="知识资产所属工作空间")
    business_documents: list[BusinessDocumentState] = Field(
        default_factory=list,
        description="当前任务关联的业务文档及其解析/入库状态",
    )
    latest_retrieval_snapshot: KnowledgeSnapshotState = Field(
        default_factory=KnowledgeSnapshotState,
        description="最近一次知识检索返回的 EvidencePacket 投影",
    )
    updated_at: datetime = Field(default_factory=get_utc_now)

    @property
    def parser_reports(self) -> list[dict[str, Any]]:
        # 不再额外持久化 parser_reports。
        # 统一从 business_documents 上的 parse_mode / parser_diagnostics 派生，
        # 避免任务态里再维护第三份解析元数据副本。
        return parser_reports_from_documents(self.business_documents)

    @model_validator(mode="after")
    def _coerce_typed_payloads(self) -> "KnowledgeData":
        object.__setattr__(
            self,
            "business_documents",
            [
                item if isinstance(item, BusinessDocumentState) else BusinessDocumentState.model_validate(item)
                for item in self.business_documents
            ],
        )
        if not isinstance(self.latest_retrieval_snapshot, KnowledgeSnapshotState):
            object.__setattr__(
                self,
                "latest_retrieval_snapshot",
                KnowledgeSnapshotState.model_validate(self.latest_retrieval_snapshot),
            )
        return self


class TaskMemorySummaryState(StrictStateModel):
    """Task-scoped compact summary persisted into the memory plane."""

    mode: str = ""
    headline: str = ""
    answer: str = ""
    key_findings: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class WorkspacePreferenceState(StrictStateModel):
    """Workspace-level durable preference snapshot copied into task memory."""

    key: str = ""
    value: Any = None
    source: str = ""
    updated_at: str | None = None


class MemoryCacheHintState(StrictStateModel):
    """Memory-plane cache metadata without storing full cached responses."""

    scope: str = "task"
    cache_key: str = ""
    cache_hit: bool = False
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryData(StrictStateModel):
    """Task-scoped memory snapshot owned by the memory blackboard."""

    task_id: str
    tenant_id: str
    workspace_id: str = Field(default="default_ws", description="memory snapshot 所属工作空间")
    harvested_candidates: list[SkillPayloadState] = Field(default_factory=list)
    approved_skills: list[SkillPayloadState] = Field(default_factory=list)
    historical_matches: list[HistoricalSkillMatchState] = Field(default_factory=list)
    task_summary: TaskMemorySummaryState = Field(default_factory=TaskMemorySummaryState)
    workspace_preferences: list[WorkspacePreferenceState] = Field(default_factory=list)
    cache_hints: list[MemoryCacheHintState] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=get_utc_now)

    @model_validator(mode="after")
    def _coerce_typed_payloads(self) -> "MemoryData":
        object.__setattr__(
            self,
            "harvested_candidates",
            [
                item if isinstance(item, SkillPayloadState) else SkillPayloadState.model_validate(item)
                for item in self.harvested_candidates
            ],
        )
        object.__setattr__(
            self,
            "approved_skills",
            [
                item if isinstance(item, SkillPayloadState) else SkillPayloadState.model_validate(item)
                for item in self.approved_skills
            ],
        )
        object.__setattr__(
            self,
            "historical_matches",
            [
                item if isinstance(item, HistoricalSkillMatchState) else HistoricalSkillMatchState.model_validate(item)
                for item in self.historical_matches
            ],
        )
        if not isinstance(self.task_summary, TaskMemorySummaryState):
            object.__setattr__(self, "task_summary", TaskMemorySummaryState.model_validate(self.task_summary))
        object.__setattr__(
            self,
            "workspace_preferences",
            [
                item if isinstance(item, WorkspacePreferenceState) else WorkspacePreferenceState.model_validate(item)
                for item in self.workspace_preferences
            ],
        )
        object.__setattr__(
            self,
            "cache_hints",
            [
                item if isinstance(item, MemoryCacheHintState) else MemoryCacheHintState.model_validate(item)
                for item in self.cache_hints
            ],
        )
        return self
