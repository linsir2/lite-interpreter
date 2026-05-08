"""Shared control-plane contract models.

These contracts are intentionally lightweight so existing modules can adopt
them incrementally without rewriting the whole runtime in one pass.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from src.common.utils import get_utc_now


class TaskEnvelope(BaseModel):
    """Stable task metadata owned by the control plane."""

    task_id: str
    tenant_id: str
    workspace_id: str = "default_ws"
    input_query: str
    governance_profile: str = "researcher"
    allowed_tools: list[str] = Field(default_factory=list)
    redaction_rules: list[str] = Field(default_factory=list)
    token_budget: int | None = None
    max_dynamic_steps: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=get_utc_now)


class EvidencePacket(BaseModel):
    """Structured retrieval payload returned by the knowledge plane."""

    query: str
    rewritten_query: str
    tenant_id: str
    workspace_id: str = "default_ws"
    hits: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    recall_strategies: list[str] = Field(default_factory=list)
    cache_hit: bool = False
    difficulty_score: float = 0.0
    is_multi_hop: bool = False
    budget_tokens: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=get_utc_now)


class ExecutionIntent(BaseModel):
    """Lightweight routing decision. Analyst owns downstream refinement."""

    model_config = ConfigDict(extra="ignore")

    intent: Literal["static_flow", "dynamic_flow"]
    destinations: list[str] = Field(default_factory=list)
    reason: str = ""
    complexity_score: float = 0.0
    candidate_skills: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DecisionRecord(BaseModel):
    """Normalized governance/policy decision captured in the control plane."""

    action: str
    profile: str
    mode: str
    allowed: bool
    risk_level: str
    risk_score: float
    reasons: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: str = "harness"
    recorded_at: datetime = Field(default_factory=get_utc_now)


class TraceEvent(BaseModel):
    """Canonical event record for runtime tracing and replay."""

    event_id: str
    topic: str
    tenant_id: str
    task_id: str
    workspace_id: str
    trace_id: str
    timestamp: datetime = Field(default_factory=get_utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)
    source: str = "event_bus"


class ExecutionEvent(BaseModel):
    """Structured execution-stream event for runtime and sandbox execution streams."""

    event_type: Literal[
        "text",
        "thinking",
        "progress",
        "tool_call_start",
        "tool_call_delta",
        "tool_call_end",
        "tool_result",
        "artifact",
        "governance",
        "error",
        "done",
    ]
    source_event_type: str | None = None
    agent_name: str
    step_name: str
    source: str = "dynamic_swarm"
    message: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    tool_call: dict[str, Any] | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class InputLease(BaseModel):
    """Read-only input lease exposed to sandbox/runtime executions."""

    kind: str
    host_path: str
    container_path: str
    file_name: str


class SandboxSessionSpec(BaseModel):
    """Requested execution boundary for one sandbox session."""

    tenant_id: str
    workspace_id: str
    task_id: str | None = None
    image: str
    network_disabled: bool = True
    mem_limit: str
    cpu_shares: int
    timeout_seconds: int
    input_leases: list[InputLease] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SandboxSessionHandle(BaseModel):
    """Runtime handle for a sandbox session."""

    session_id: str
    spec: SandboxSessionSpec
    status: Literal["created", "running", "completed", "failed", "terminated"] = "created"
    container_name: str | None = None
    container_id: str | None = None
    created_at: datetime = Field(default_factory=get_utc_now)
    updated_at: datetime = Field(default_factory=get_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactRecord(BaseModel):
    """Normalized artifact emitted by a runtime or sandbox session."""

    path: str
    artifact_type: str = "artifact"
    summary: str | None = None


StrategyFamily = Literal[
    "dataset_profile",
    "document_rule_audit",
    "hybrid_reconciliation",
    "input_gap_report",
    "legacy_dataset_aware_generator",
]


ResearchMode = Literal["none", "single_pass", "iterative"]


class CapabilityTier(str, Enum):
    """Capability gradient — how much runtime power the task needs.

    Filled by analyst; router does NOT set this.  Router only decides
    static_flow vs dynamic_flow at the DAG-entry level; analyst then
    declares the specific tier and any per-tier skip_static_steps via
    DynamicResumeOverlay so the DAG can skip nodes without changing topology.
    """

    STATIC_ONLY = "static_only"
    STATIC_WITH_NETWORK = "static_with_network"
    DYNAMIC_EXPLORATION_THEN_STATIC = "dynamic_exploration_then_static"
    DYNAMIC_ONLY = "dynamic_only"


def _derive_research_mode(tier: CapabilityTier) -> str:
    return {
        CapabilityTier.STATIC_ONLY: "none",
        CapabilityTier.STATIC_WITH_NETWORK: "single_pass",
        CapabilityTier.DYNAMIC_EXPLORATION_THEN_STATIC: "iterative",
        CapabilityTier.DYNAMIC_ONLY: "iterative",
    }.get(tier, "none")


def _derive_execution_intent(tier: CapabilityTier) -> str:
    return {
        CapabilityTier.STATIC_ONLY: "static_flow",
        CapabilityTier.STATIC_WITH_NETWORK: "static_flow",
        CapabilityTier.DYNAMIC_EXPLORATION_THEN_STATIC: "dynamic_flow",
        CapabilityTier.DYNAMIC_ONLY: "dynamic_flow",
    }.get(tier, "static_flow")


ArtifactCategory = Literal["report", "chart", "export", "diagnostic"]


class ArtifactSpec(BaseModel):
    """One expected user-facing or diagnostic artifact within an execution strategy."""

    artifact_key: str
    file_name: str
    category: ArtifactCategory = "diagnostic"
    artifact_type: str = "artifact"
    format: str = ""
    required: bool = True
    summary: str = ""
    description: str = ""


class ArtifactPlan(BaseModel):
    """Artifact contract declared by the selected generator strategy."""

    strategy_family: StrategyFamily = "dataset_profile"
    output_root: str = "/app/outputs"
    required_artifacts: list[ArtifactSpec] = Field(default_factory=list)
    optional_artifacts: list[ArtifactSpec] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class StaticEvidenceRequest(BaseModel):
    """Request envelope for one static evidence collection pass."""

    query: str = ""
    research_mode: ResearchMode = "none"
    search_queries: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    allowed_capabilities: list[str] = Field(default_factory=list)
    max_results: int = 3
    timeout_seconds: float = 8.0
    max_bytes: int = 200_000


class StaticEvidenceRecord(BaseModel):
    """One normalized external evidence record collected for a static run."""

    source_type: Literal["search_result", "fetched_document"] = "search_result"
    title: str = ""
    url: str = ""
    domain: str = ""
    snippet: str = ""
    content_type: str = ""
    text: str = ""
    status: str = "ok"
    metadata: dict[str, Any] = Field(default_factory=dict)


class StaticEvidenceBundle(BaseModel):
    """Collected static evidence attached to one execution."""

    request: StaticEvidenceRequest = Field(default_factory=StaticEvidenceRequest)
    records: list[StaticEvidenceRecord] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=get_utc_now)


class EvidencePlan(BaseModel):
    """Planner-owned specification for one bounded static evidence pass."""

    research_mode: ResearchMode = "none"
    search_queries: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    allowed_capabilities: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    max_results: int = 3
    timeout_seconds: float = 8.0
    max_bytes: int = 200_000


class VerificationPlan(BaseModel):
    """Rules used to validate post-execution artifact delivery."""

    strategy_family: StrategyFamily = "dataset_profile"
    required_artifact_keys: list[str] = Field(default_factory=list)
    prohibited_extensions: list[str] = Field(default_factory=list)
    allowed_output_roots: list[str] = Field(default_factory=list)
    require_declared_filenames: bool = True
    criteria: list[dict[str, Any]] = Field(default_factory=list)
    """Semantic verification criteria. Each entry is {check, params, severity}.
    e.g. {"check": "csv_has_min_columns", "params": {"min": 3}, "severity": "error"}"""


class ComputationStep(BaseModel):
    """One compiler-consumable step inside a static program."""

    step_id: str
    kind: Literal[
        "load_datasets",
        "load_documents",
        "load_evidence",
        "derive_rule_checks",
        "derive_metric_checks",
        "derive_filter_checks",
        "emit_report",
        "emit_json",
        "emit_csv",
        "emit_input_gap",
    ]
    config: dict[str, Any] = Field(default_factory=dict)


class ArtifactEmitSpec(BaseModel):
    """One compiler-consumable artifact emission instruction."""

    artifact_key: str
    file_name: str
    emit_kind: Literal[
        "analysis_report",
        "summary_json",
        "rule_checks_json",
        "cross_source_findings_json",
        "comparison_csv",
        "input_gap_report",
        "requested_inputs_json",
    ]
    category: ArtifactCategory = "diagnostic"
    required: bool = True


class DebugHint(BaseModel):
    """One debug hint emitted by strategy construction or verification."""

    code: str
    message: str


class RepairHint(BaseModel):
    """One repair hint emitted by verification or debugger analysis."""

    code: str
    message: str


class StaticProgramSpec(BaseModel):
    """Compiler-owned declarative representation of one static program."""

    spec_id: str
    strategy_family: StrategyFamily = "dataset_profile"
    analysis_mode: str = ""
    research_mode: ResearchMode = "none"
    steps: list[ComputationStep] = Field(default_factory=list)
    artifact_emits: list[ArtifactEmitSpec] = Field(default_factory=list)
    debug_hints: list[DebugHint] = Field(default_factory=list)
    evidence_bundle: StaticEvidenceBundle | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class StaticRepairPlan(BaseModel):
    """Debugger-owned bounded repair instruction for one failed static attempt.

    Actions are scoped to specific plan regions; debugger may not rewrite
    strategy_family or generator_id (those are frozen in ExecutionStrategy).
    """

    reason: str = ""
    attempt_index: int = 1
    action: Literal[
        "simplify_program",
        "drop_external_evidence",
        "patch_evidence_plan",
        "patch_artifact_plan",
        "retry_with_evidence",
    ] = "simplify_program"
    updates: dict[str, Any] = Field(default_factory=dict)


class DebugAttemptRecord(BaseModel):
    """Persistent record of one debugger attempt in the static path."""

    attempt_index: int
    reason: str
    repair_plan: StaticRepairPlan | None = None
    outcome: str = "pending"
    recorded_at: datetime = Field(default_factory=get_utc_now)


class GeneratorManifest(BaseModel):
    """Generator metadata persisted for replay, debugging, and migration cutover."""

    generator_id: str
    strategy_family: StrategyFamily = "dataset_profile"
    renderer_id: str = "dataset_aware_renderer"
    fallback_used: bool = False
    expected_artifact_keys: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=get_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DynamicResumeOverlay(BaseModel):
    """Dynamic-to-static handoff state captured independently from legacy metadata fields."""

    continuation: Literal["finish", "resume_static"] = "finish"
    next_static_steps: list[str] = Field(default_factory=list)
    skip_static_steps: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    suggested_static_actions: list[str] = Field(default_factory=list)
    recommended_static_action: str = ""
    open_questions: list[str] = Field(default_factory=list)
    strategy_family: StrategyFamily | None = None


class ArtifactVerificationResult(BaseModel):
    """Post-execution verification result for an artifact plan."""

    strategy_family: StrategyFamily = "dataset_profile"
    passed: bool = False
    verified_artifact_keys: list[str] = Field(default_factory=list)
    missing_artifact_keys: list[str] = Field(default_factory=list)
    unexpected_artifacts: list[str] = Field(default_factory=list)
    failure_reasons: list[str] = Field(default_factory=list)
    debug_hints: list[RepairHint] = Field(default_factory=list)


def _artifact_spec(
    artifact_key: str,
    file_name: str,
    *,
    category: str,
    required: bool = True,
    summary: str = "",
    description: str = "",
) -> ArtifactSpec:
    return ArtifactSpec(
        artifact_key=artifact_key,
        file_name=file_name,
        category=category,
        artifact_type=category,
        format=Path(file_name).suffix.lstrip("."),
        required=required,
        summary=summary,
        description=description,
    )


def _derive_artifact_plan(strategy_family: StrategyFamily) -> ArtifactPlan:
    if strategy_family == "dataset_profile":
        required = [
            _artifact_spec("analysis_report", "analysis_report.md", category="report", summary="数据分析报告"),
            _artifact_spec("summary_json", "summary.json", category="export", summary="结构化摘要"),
        ]
        optional = [
            _artifact_spec("comparison_csv", "comparison.csv", category="export", required=False, summary="对比导出"),
        ]
        notes = ["趋势图不是 v1 强制项；优先保证报告与结构化导出稳定生成。"]
    elif strategy_family == "document_rule_audit":
        required = [
            _artifact_spec("rule_audit_report", "rule_audit_report.md", category="report", summary="规则审计报告"),
            _artifact_spec("rule_checks_json", "rule_checks.json", category="export", summary="规则检查结果"),
        ]
        optional = []
        notes = ["文档规则审计以报告和规则检查 JSON 作为最小交付面。"]
    elif strategy_family == "hybrid_reconciliation":
        required = [
            _artifact_spec("analysis_report", "analysis_report.md", category="report", summary="综合分析报告"),
            _artifact_spec("cross_source_findings", "cross_source_findings.json", category="export", summary="跨来源发现"),
            _artifact_spec("comparison_csv", "comparison.csv", category="export", summary="用户导向对比导出"),
        ]
        optional = []
        notes = ["v1 用 comparison.csv 代替更重的图表引擎。"]
    elif strategy_family == "input_gap_report":
        required = [
            _artifact_spec("input_gap_report", "input_gap_report.md", category="report", summary="输入缺口报告"),
        ]
        optional = [
            _artifact_spec("requested_inputs_json", "requested_inputs.json", category="export", required=False, summary="补充输入请求"),
        ]
        notes = ["input_gap_report 禁止产伪图表。"]
    else:
        required = [
            _artifact_spec("analysis_report", "analysis_report.md", category="report", summary="兼容报告"),
            _artifact_spec("summary_json", "summary.json", category="export", summary="兼容摘要"),
        ]
        optional = []
        notes = ["legacy fallback 继续使用 dataset-aware renderer，但产出新 artifact contract。"]

    return ArtifactPlan(
        strategy_family=strategy_family,
        output_root="/app/outputs",
        required_artifacts=list(required),
        optional_artifacts=list(optional),
        notes=list(notes),
    )


def _derive_verification_plan(strategy_family: StrategyFamily) -> VerificationPlan:
    from config.settings import OUTPUT_DIR as _OUTPUT_DIR

    artifact_plan = _derive_artifact_plan(strategy_family)
    prohibited_extensions: list[str] = [".png", ".jpg", ".jpeg", ".webp"] if strategy_family == "input_gap_report" else []
    return VerificationPlan(
        strategy_family=strategy_family,
        required_artifact_keys=[item.artifact_key for item in artifact_plan.required_artifacts if item.required],
        prohibited_extensions=prohibited_extensions,
        allowed_output_roots=[str(Path(_OUTPUT_DIR).resolve())],
        require_declared_filenames=True,
    )


def _derive_strategy_family(analysis_mode: str) -> StrategyFamily:
    """Derive strategy family from analyst-written analysis_mode.

    This replaces the old runtime derivation in static_generation_registry.
    Mapping is deterministic: one analysis_mode maps to one strategy_family.
    """
    mode = str(analysis_mode or "").strip()
    if mode == "document_rule_analysis":
        return "document_rule_audit"
    if mode == "hybrid_analysis":
        return "hybrid_reconciliation"
    if mode == "need_more_inputs":
        return "input_gap_report"
    if mode == "dataset_analysis":
        return "dataset_profile"
    if mode == "dynamic_research_analysis":
        return "hybrid_reconciliation"
    return "dataset_profile"


class ExecutionStrategy(BaseModel):
    """Immutable execution-strategy truth source. Analyst is the sole writer.

    Analyst-written fields:
        - capability_tier  — how much runtime power the task needs
        - fallback_tier    — fallback if the primary tier fails
        - analysis_mode    — what type of analysis (dataset_analysis, etc.)
        - summary          — human-readable plan summary
        - evidence_plan    — external evidence collection spec

    Derived fields (@computed_field, never stored):
        - research_mode      — from capability_tier
        - strategy_family    — from analysis_mode
        - generator_id       — from strategy_family
        - execution_intent   — from capability_tier
        - artifact_plan      — from strategy_family
        - verification_plan  — from strategy_family
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    # ---- Analyst-written plan fields ----
    capability_tier: CapabilityTier = CapabilityTier.STATIC_ONLY
    fallback_tier: CapabilityTier | None = None
    analysis_mode: str = ""
    summary: str = ""
    evidence_plan: EvidencePlan = Field(default_factory=EvidencePlan)

    # ---- Derived fields (@computed_field) ----
    @computed_field
    @property
    def research_mode(self) -> str:
        return _derive_research_mode(self.capability_tier)

    @computed_field
    @property
    def strategy_family(self) -> StrategyFamily:
        return _derive_strategy_family(self.analysis_mode)

    @computed_field
    @property
    def generator_id(self) -> str:
        return f"{self.strategy_family}_generator"

    @computed_field
    @property
    def execution_intent(self) -> str:
        return _derive_execution_intent(self.capability_tier)

    @computed_field
    @property
    def artifact_plan(self) -> ArtifactPlan:
        return _derive_artifact_plan(self.strategy_family)

    @computed_field
    @property
    def verification_plan(self) -> VerificationPlan:
        return _derive_verification_plan(self.strategy_family)

    @model_validator(mode="before")
    @classmethod
    def _migrate_old_checkpoint(cls, data: Any) -> Any:
        """Infer new fields from old stored fields so legacy checkpoints load."""
        if not isinstance(data, Mapping):
            return data
        d = dict(data)
        # Strip old stored fields that are now @computed_field
        for key in (
            "research_mode", "strategy_family", "generator_id", "execution_intent",
            "artifact_plan", "verification_plan",
        ):
            d.pop(key, None)
        # Infer capability_tier from old research_mode if missing
        if "capability_tier" not in d or not d.get("capability_tier"):
            old_rm = str(data.get("research_mode") or "")
            if old_rm == "iterative":
                d["capability_tier"] = CapabilityTier.DYNAMIC_ONLY
            elif old_rm == "single_pass":
                d["capability_tier"] = CapabilityTier.STATIC_WITH_NETWORK
            else:
                d.setdefault("capability_tier", CapabilityTier.STATIC_ONLY)
        return d


class ToolCallRecord(BaseModel):
    """Normalized tool-call resource derived from execution traces."""

    tool_call_id: str
    execution_id: str
    tool_name: str
    phase: Literal["start", "delta", "end", "result"]
    status: str | None = None
    agent_name: str | None = None
    step_name: str | None = None
    arguments: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    source_event_type: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ExecutionRecord(BaseModel):
    """Normalized execution result for a sandbox/runtime session."""

    session_id: str
    tenant_id: str
    workspace_id: str
    task_id: str | None = None
    success: bool
    trace_id: str
    duration_seconds: float
    output: str | None = None
    error: str | None = None
    exit_code: int | None = None
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    mounted_inputs: list[InputLease] = Field(default_factory=list)
    governance: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityOperation(BaseModel):
    """One supported operation within a capability domain."""

    operation_id: str
    description: str
    supported: bool = True
    limitations: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityDomainManifest(BaseModel):
    """Capability summary for one runtime domain."""

    domain_id: str
    description: str
    supported: bool = True
    operations: list[CapabilityOperation] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeCapabilityManifest(BaseModel):
    """Runtime-level self-description inspired by OpenHarness capability manifests."""

    runtime_id: str
    display_name: str
    description: str
    runtime_modes: list[str] = Field(default_factory=list)
    domains: list[CapabilityDomainManifest] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=get_utc_now)


class AuditRecord(BaseModel):
    """Persistent API audit record for high-risk control-plane operations."""

    audit_id: str
    subject: str
    role: str
    action: str
    outcome: Literal["success", "failure", "denied"]
    tenant_id: str
    workspace_id: str
    task_id: str | None = None
    execution_id: str | None = None
    resource_type: str = "api"
    resource_id: str | None = None
    request_method: str
    request_path: str
    trace_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    recorded_at: datetime = Field(default_factory=get_utc_now)
