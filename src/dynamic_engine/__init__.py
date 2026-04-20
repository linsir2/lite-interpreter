"""Dynamic execution adapters for DeerFlow-backed sub-agents."""

from src.dynamic_engine.blackboard_context import (
    DynamicContextEnvelope,
    build_dynamic_context,
)
from src.dynamic_engine.deerflow_bridge import (
    DeerflowBridge,
    DeerflowTaskRequest,
    DeerflowTaskResult,
)
from src.dynamic_engine.runtime_backends import get_runtime_manifest, list_runtime_manifests
from src.dynamic_engine.supervisor import DynamicRunPlan, DynamicSupervisor
from src.dynamic_engine.trace_normalizer import TraceNormalizer

__all__ = [
    "DynamicContextEnvelope",
    "build_dynamic_context",
    "DynamicRunPlan",
    "DynamicSupervisor",
    "DeerflowBridge",
    "DeerflowTaskRequest",
    "DeerflowTaskResult",
    "TraceNormalizer",
    "get_runtime_manifest",
    "list_runtime_manifests",
]
