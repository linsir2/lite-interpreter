from pydantic import BaseModel

from src.common.contracts import ExecutionRecord


class AuditResult(BaseModel):
    """审计结果类型注解"""

    safe: bool
    reason: str
    risk_type: str | None = None
    source_layer: str | None = None
    source_config: str | None = None
    trace_id: str
    duration_seconds: float


class SandboxResult(BaseModel):
    success: bool
    output: str | None = None
    error: str | None = None
    trace_id: str
    duration_seconds: float
    tenant_id: str
    artifacts_dir: str | None = None
    mounted_inputs: list[dict] | None = None
    governance: dict | None = None
    execution_record: ExecutionRecord | None = None
