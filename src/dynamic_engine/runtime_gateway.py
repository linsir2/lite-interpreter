"""Runtime gateway for bounded dynamic runs."""
from __future__ import annotations

from typing import Any, Callable

from src.dynamic_engine.runtime_backends import DynamicRuntimeBackend
from src.dynamic_engine.runtime_registry import RuntimeRegistry, runtime_registry
from src.dynamic_engine.supervisor import DynamicRunPlan


class RuntimeGateway:
    """Small adapter around the configured dynamic runtime backend.

    The DAG keeps ownership of planning and governance; this gateway only knows
    how to execute the already-approved request.
    """

    def __init__(
        self,
        *,
        max_steps: int,
        backend_name: str = "deerflow",
        registry: RuntimeRegistry | None = None,
    ) -> None:
        self._backend_name = backend_name
        self._registry = registry or runtime_registry
        self._backend: DynamicRuntimeBackend = self._registry.create(
            backend_name,
            max_steps=max_steps,
        )

    def build_payload(self, plan: DynamicRunPlan) -> dict[str, Any]:
        if plan.request is None:
            raise ValueError("Cannot build runtime payload for a denied plan")
        return self._backend.build_payload(plan)

    def run(
        self,
        plan: DynamicRunPlan,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ):
        if plan.request is None:
            raise ValueError("Cannot execute a denied plan")
        return self._backend.run(plan, on_event=on_event)

    @property
    def backend_name(self) -> str:
        return self._backend_name
