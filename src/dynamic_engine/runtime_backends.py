"""Runtime capability manifests for dynamic execution."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.common import CapabilityDomainManifest, CapabilityOperation, RuntimeCapabilityManifest
from src.dynamic_engine.deerflow_bridge import DeerflowBridge, DeerflowRuntimeConfig
from src.dynamic_engine.supervisor import DynamicRunPlan


class DeerflowRuntimeBackend:
    """Default DeerFlow-backed runtime backend."""

    name = "deerflow"

    def __init__(self, *, max_steps: int) -> None:
        self._bridge = DeerflowBridge(
            runtime_config=DeerflowRuntimeConfig(max_steps=max_steps),
        )

    def capability_manifest(self) -> RuntimeCapabilityManifest:
        return build_deerflow_runtime_manifest(max_steps=self._bridge.runtime_config.max_steps)

    def build_payload(self, plan: DynamicRunPlan) -> dict[str, Any]:
        if plan.request is None:
            raise ValueError("Cannot build runtime payload for a denied plan")
        return self._bridge.build_payload(plan.request)

    def run(
        self,
        plan: DynamicRunPlan,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ):
        if plan.request is None:
            raise ValueError("Cannot execute a denied plan")
        return self._bridge.run(plan.request, on_event=on_event)


def build_deerflow_runtime_manifest(*, max_steps: int = 6) -> RuntimeCapabilityManifest:
    """Describe the current DeerFlow runtime surface in a machine-readable form."""
    return RuntimeCapabilityManifest(
        runtime_id="deerflow",
        display_name="DeerFlow Runtime",
        description="Bounded dynamic research runtime used behind lite-interpreter's dynamic super node.",
        runtime_modes=["sidecar"],
        domains=[
            CapabilityDomainManifest(
                domain_id="planning",
                description="Task decomposition and bounded dynamic planning.",
                operations=[
                    CapabilityOperation(
                        operation_id="bounded_dynamic_planning",
                        description="Plan a dynamic run under governance and max-step constraints.",
                    )
                ],
                limitations=["Planning is still owned by the DAG; DeerFlow is invoked only after router approval."],
            ),
            CapabilityDomainManifest(
                domain_id="research",
                description="Tool-mediated external research and exploration.",
                operations=[
                    CapabilityOperation(
                        operation_id="tool_mediated_research",
                        description="Perform web-assisted or knowledge-assisted research through approved tools.",
                    )
                ],
                limitations=["Only tool-mediated network access is allowed; host bash access remains forbidden."],
            ),
            CapabilityDomainManifest(
                domain_id="streaming",
                description="Runtime trace event emission.",
                operations=[
                    CapabilityOperation(
                        operation_id="trace_stream",
                        description="Emit normalized runtime events for writeback and UI projection.",
                    ),
                    CapabilityOperation(
                        operation_id="execution_stream_attach",
                        description="Attach to the normalized execution stream through lite-interpreter APIs.",
                    ),
                ],
                limitations=[
                    "Execution streams are replayed from task-backed journals rather than directly from the backend transport."
                ],
            ),
            CapabilityDomainManifest(
                domain_id="tool_calls",
                description="Tool-call events and derived tool-call resources.",
                operations=[
                    CapabilityOperation(
                        operation_id="tool_call_trace_projection",
                        description="Project runtime tool-call events into normalized execution traces.",
                    )
                ],
                limitations=[
                    "Tool-call resources are derived from available trace events and may be partial if the backend omits tool metadata."
                ],
            ),
            CapabilityDomainManifest(
                domain_id="artifacts",
                description="Artifact references surfaced through runtime traces.",
                operations=[
                    CapabilityOperation(
                        operation_id="artifact_reference_emission",
                        description="Report artifact paths or references discovered during the dynamic run.",
                    )
                ],
                limitations=[
                    "Artifacts are currently exposed as task-level references, not yet as execution-level resources."
                ],
            ),
            CapabilityDomainManifest(
                domain_id="subagents",
                description="Delegated dynamic sub-agent orchestration within DeerFlow.",
                operations=[
                    CapabilityOperation(
                        operation_id="bounded_subagent_orchestration",
                        description="Use DeerFlow sub-agents inside the bounded runtime envelope.",
                        metadata={"enabled_by_default": True},
                    )
                ],
                limitations=[
                    "Sub-agents operate only inside DeerFlow; final code execution remains owned by lite-interpreter sandbox."
                ],
            ),
            CapabilityDomainManifest(
                domain_id="sandbox_execution",
                description="Final code execution boundary.",
                supported=False,
                operations=[
                    CapabilityOperation(
                        operation_id="final_code_execution",
                        description="Execute generated code in the final execution environment.",
                        supported=False,
                        limitations=[
                            "Not supported by DeerFlow runtime; final code execution is delegated back to lite-interpreter sandbox."
                        ],
                    )
                ],
                limitations=["This runtime must not directly own final Python execution."],
            ),
        ],
        limitations=[
            f"Dynamic runs are bounded by max_steps={max_steps}.",
            "Final code execution must remain inside lite-interpreter sandbox.",
            "The only supported runtime mode is an out-of-process DeerFlow sidecar.",
            "Execution streams are projected from lite-interpreter control-plane journals, not attached directly to DeerFlow transport.",
        ],
        metadata={
            "code_execution_owner": "lite_interpreter_sandbox",
            "network_access": "tool-mediated-only",
            "host_bash_access": "forbidden",
            "supports_resume": True,
            "supports_attach_stream": True,
            "supports_tool_call_resources": True,
        },
    )


def list_runtime_manifests() -> list[RuntimeCapabilityManifest]:
    return [build_deerflow_runtime_manifest(max_steps=6)]


def get_runtime_manifest(runtime_id: str) -> RuntimeCapabilityManifest:
    normalized = str(runtime_id or "").strip().lower()
    if normalized != "deerflow":
        raise KeyError(f"Unknown dynamic runtime backend: {runtime_id}")
    return build_deerflow_runtime_manifest(max_steps=6)
