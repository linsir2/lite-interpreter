"""API schema helpers for task streaming endpoints."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, ValidationError, model_validator

from src.common.event_bus import Event


class CreateTaskRequest(BaseModel):
    """Strict request model for task creation."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: StrictStr
    workspace_id: StrictStr
    input_query: StrictStr
    autorun: StrictBool = True
    allowed_tools: list[StrictStr] = Field(default_factory=list)
    governance_profile: StrictStr = "researcher"
    idempotency_key: StrictStr | None = None

    @model_validator(mode="after")
    def _normalize(self) -> CreateTaskRequest:
        self.tenant_id = self.tenant_id.strip()
        self.workspace_id = self.workspace_id.strip()
        self.input_query = self.input_query.strip()
        self.governance_profile = self.governance_profile.strip() or "researcher"
        if not self.tenant_id:
            raise ValueError("tenant_id must not be empty")
        if not self.workspace_id:
            raise ValueError("workspace_id must not be empty")
        if not self.input_query:
            raise ValueError("input_query must not be empty")
        normalized_tools = []
        for tool_name in self.allowed_tools:
            stripped = tool_name.strip()
            if not stripped:
                raise ValueError("allowed_tools must not contain empty values")
            normalized_tools.append(stripped)
        self.allowed_tools = normalized_tools
        if self.idempotency_key is not None:
            self.idempotency_key = self.idempotency_key.strip() or None
        return self


class PolicyUpdateRequest(BaseModel):
    """Strict request model for harness policy updates."""

    model_config = ConfigDict(extra="forbid")

    policy: dict[str, Any] | None = None
    yaml: StrictStr | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> PolicyUpdateRequest:
        has_policy = self.policy is not None
        has_yaml = self.yaml is not None and bool(self.yaml.strip())
        if has_policy == has_yaml:
            raise ValueError("exactly one of `policy` or `yaml` must be provided")
        if self.yaml is not None:
            self.yaml = self.yaml.strip()
        return self


class SessionLoginRequest(BaseModel):
    """Request model for API session login."""

    model_config = ConfigDict(extra="forbid")

    username: StrictStr
    password: StrictStr

    @model_validator(mode="after")
    def _normalize(self) -> SessionLoginRequest:
        self.username = self.username.strip()
        self.password = self.password.strip()
        if not self.username:
            raise ValueError("username must not be empty")
        if not self.password:
            raise ValueError("password must not be empty")
        return self


def validation_error_payload(exc: ValidationError) -> dict[str, Any]:
    """Return a stable error payload for strict request validation failures."""

    normalized_details = []
    for detail in exc.errors(include_url=False):
        ctx = detail.get("ctx")
        if isinstance(ctx, dict):
            detail = {
                **detail,
                "ctx": {str(key): str(value) for key, value in ctx.items()},
            }
        normalized_details.append(detail)
    return {
        "error": "validation_error",
        "details": normalized_details,
    }


@dataclass
class TaskStreamEvent:
    event_id: str
    topic: str
    task_id: str
    tenant_id: str
    workspace_id: str
    trace_id: str
    timestamp: str
    payload: dict[str, Any]

    @classmethod
    def from_event(cls, event: Event) -> TaskStreamEvent:
        return cls(
            event_id=event.event_id,
            topic=event.topic.value,
            task_id=event.task_id,
            tenant_id=event.tenant_id,
            workspace_id=event.workspace_id,
            trace_id=event.trace_id,
            timestamp=event.timestamp.isoformat(),
            payload=event.payload,
        )

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> TaskStreamEvent:
        return cls(
            event_id=str(record.get("event_id", "")),
            topic=str(record.get("topic", "")),
            task_id=str(record.get("task_id", "")),
            tenant_id=str(record.get("tenant_id", "")),
            workspace_id=str(record.get("workspace_id", "")),
            trace_id=str(record.get("trace_id", "")),
            timestamp=str(record.get("timestamp", "")),
            payload=dict(record.get("payload", {}) or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionStreamEvent:
    event_id: str
    topic: str
    execution_id: str
    task_id: str
    tenant_id: str
    workspace_id: str
    trace_id: str
    timestamp: str
    payload: dict[str, Any]

    @classmethod
    def from_task_event(
        cls,
        event: Event,
        *,
        execution_id: str,
    ) -> ExecutionStreamEvent:
        return cls(
            event_id=event.event_id,
            topic=event.topic.value,
            execution_id=execution_id,
            task_id=event.task_id,
            tenant_id=event.tenant_id,
            workspace_id=event.workspace_id,
            trace_id=event.trace_id,
            timestamp=event.timestamp.isoformat(),
            payload=event.payload,
        )

    @classmethod
    def from_task_record(
        cls,
        record: dict[str, Any],
        *,
        execution_id: str,
    ) -> ExecutionStreamEvent:
        return cls(
            event_id=str(record.get("event_id", "")),
            topic=str(record.get("topic", "")),
            execution_id=execution_id,
            task_id=str(record.get("task_id", "")),
            tenant_id=str(record.get("tenant_id", "")),
            workspace_id=str(record.get("workspace_id", "")),
            trace_id=str(record.get("trace_id", "")),
            timestamp=str(record.get("timestamp", "")),
            payload=dict(record.get("payload", {}) or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
