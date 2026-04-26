"""Shared control-plane contract models.

These contracts are intentionally lightweight so existing modules can adopt
them incrementally without rewriting the whole runtime in one pass.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

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
    """Routing decision for the current task run."""

    intent: Literal["static_flow", "dynamic_only", "dynamic_then_static_flow"]
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

    strategy_family: StrategyFamily = "legacy_dataset_aware_generator"
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

    strategy_family: StrategyFamily = "legacy_dataset_aware_generator"
    required_artifact_keys: list[str] = Field(default_factory=list)
    prohibited_extensions: list[str] = Field(default_factory=list)
    allowed_output_roots: list[str] = Field(default_factory=list)
    require_declared_filenames: bool = True


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
    strategy_family: StrategyFamily = "legacy_dataset_aware_generator"
    analysis_mode: str = ""
    research_mode: ResearchMode = "none"
    steps: list[ComputationStep] = Field(default_factory=list)
    artifact_emits: list[ArtifactEmitSpec] = Field(default_factory=list)
    debug_hints: list[DebugHint] = Field(default_factory=list)
    evidence_bundle: StaticEvidenceBundle | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class StaticRepairPlan(BaseModel):
    """Debugger-owned bounded repair instruction for one failed static attempt."""

    reason: str = ""
    attempt_index: int = 1
    action: Literal["fallback_to_legacy", "simplify_program", "drop_external_evidence"] = "simplify_program"
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
    strategy_family: StrategyFamily = "legacy_dataset_aware_generator"
    renderer_id: str = "dataset_aware_renderer"
    fallback_used: bool = False
    expected_artifact_keys: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=get_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DynamicResumeOverlay(BaseModel):
    """Dynamic-to-static handoff state captured independently from legacy metadata fields."""

    continuation: Literal["finish", "resume_static"] = "finish"
    next_static_steps: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    suggested_static_actions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class ArtifactVerificationResult(BaseModel):
    """Post-execution verification result for an artifact plan."""

    strategy_family: StrategyFamily = "legacy_dataset_aware_generator"
    passed: bool = False
    verified_artifact_keys: list[str] = Field(default_factory=list)
    missing_artifact_keys: list[str] = Field(default_factory=list)
    unexpected_artifacts: list[str] = Field(default_factory=list)
    failure_reasons: list[str] = Field(default_factory=list)
    debug_hints: list[RepairHint] = Field(default_factory=list)


class ExecutionStrategy(BaseModel):
    """Internal execution-strategy truth source for static artifact-producing runs."""

    analysis_mode: str = ""
    research_mode: ResearchMode = "none"
    strategy_family: StrategyFamily = "legacy_dataset_aware_generator"
    generator_id: str = "legacy_dataset_aware_generator"
    evidence_plan: EvidencePlan = Field(default_factory=EvidencePlan)
    artifact_plan: ArtifactPlan = Field(default_factory=ArtifactPlan)
    verification_plan: VerificationPlan = Field(default_factory=VerificationPlan)
    program_spec: StaticProgramSpec | None = None
    repair_plan: StaticRepairPlan | None = None
    resume_overlay: DynamicResumeOverlay | None = None
    legacy_compatibility: dict[str, Any] = Field(default_factory=dict)


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
