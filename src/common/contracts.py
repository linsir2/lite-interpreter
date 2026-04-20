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
