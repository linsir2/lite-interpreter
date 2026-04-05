from typing import Optional
from pydantic import BaseModel

from src.common.contracts import ExecutionRecord

class AuditResult(BaseModel): 
    """审计结果类型注解"""
    safe: bool
    reason: str
    risk_type: Optional[str] = None
    trace_id: str
    duration_seconds: float

class SandboxResult(BaseModel):
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    trace_id: str
    duration_seconds: float
    tenant_id: str
    artifacts_dir: Optional[str] = None
    mounted_inputs: Optional[list[dict]] = None
    governance: Optional[dict] = None
    execution_record: Optional[ExecutionRecord] = None
