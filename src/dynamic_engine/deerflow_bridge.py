"""Isolation layer for DeerFlow-backed dynamic swarms."""

from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx
from config.settings import (
    DEERFLOW_CLIENT_MODULE,
    DEERFLOW_CONFIG_PATH,
    DEERFLOW_MAX_EVENTS,
    DEERFLOW_MAX_STEPS,
    DEERFLOW_MODEL_NAME,
    DEERFLOW_RECURSION_LIMIT,
    DEERFLOW_RUNTIME_MODE,
    DEERFLOW_SIDECAR_TIMEOUT,
    DEERFLOW_SIDECAR_URL,
)

from src.common.contracts import TraceEvent
from src.common.utils import generate_uuid, get_utc_now
from src.dag_engine.dag_exceptions import TaskLeaseLostError


@dataclass(frozen=True)
class DeerflowTaskRequest:
    """Normalized task request passed from the DAG layer to DeerFlow."""

    task_id: str
    tenant_id: str
    query: str
    system_context: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeerflowTaskResult:
    """Normalized response contract returned by the dynamic engine."""

    status: str
    summary: str
    trace_refs: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    recommended_skill: dict[str, Any] = field(default_factory=dict)
    trace: list[dict[str, Any]] = field(default_factory=list)
    runtime_metadata: dict[str, Any] = field(default_factory=dict)

    def to_state_patch(self) -> dict[str, Any]:
        from src.dynamic_engine.trace_normalizer import TraceNormalizer

        return {
            "dynamic_status": self.status,
            "dynamic_summary": self.summary,
            "dynamic_runtime_metadata": dict(self.runtime_metadata),
            "dynamic_trace": [
                TraceNormalizer.normalize_runtime_event(
                    event,
                    source=str(event.get("source") or "dynamic_swarm"),
                )
                for event in self.trace
            ],
            "dynamic_trace_refs": list(self.trace_refs),
            "dynamic_artifacts": list(self.artifacts),
            "recommended_static_skill": dict(self.recommended_skill),
        }


@dataclass(frozen=True)
class DeerflowRuntimeConfig:
    """Runtime settings for the dynamic DeerFlow adapter."""

    module_name: str = DEERFLOW_CLIENT_MODULE
    runtime_mode: str = DEERFLOW_RUNTIME_MODE
    sidecar_url: str = DEERFLOW_SIDECAR_URL
    sidecar_timeout: int = DEERFLOW_SIDECAR_TIMEOUT
    config_path: str = DEERFLOW_CONFIG_PATH
    model_name: str = DEERFLOW_MODEL_NAME
    max_events: int = DEERFLOW_MAX_EVENTS
    max_steps: int = DEERFLOW_MAX_STEPS
    recursion_limit: int = DEERFLOW_RECURSION_LIMIT
    subagent_enabled: bool = True
    plan_mode: bool = True
    thinking_enabled: bool = True


class DeerflowBridge:
    """Adapter entrypoint used by the dynamic super-node.

    Supported runtime modes:
    - `embedded`: import `deerflow.client` directly in-process
    - `sidecar`: call an out-of-process local DeerFlow sidecar over HTTP
    - `auto`: prefer sidecar when configured, otherwise fall back to embedded
    """

    def __init__(
        self,
        sandbox_backend: str = "docker",
        runtime_config: DeerflowRuntimeConfig | None = None,
    ) -> None:
        self.sandbox_backend = sandbox_backend
        self.runtime_config = runtime_config or DeerflowRuntimeConfig()

    def build_payload(self, request: DeerflowTaskRequest) -> dict[str, Any]:
        payload = asdict(request)
        payload["sandbox_backend"] = self.sandbox_backend
        payload["runtime"] = {
            "runtime_mode": self.runtime_config.runtime_mode,
            "python_package": self.runtime_config.module_name,
            "sidecar_url": self.runtime_config.sidecar_url or None,
            "config_path": self.runtime_config.config_path or None,
            "model_name": self.runtime_config.model_name or None,
            "max_steps": self.runtime_config.max_steps,
            "recursion_limit": self.runtime_config.recursion_limit,
            "subagent_enabled": self.runtime_config.subagent_enabled,
            "plan_mode": self.runtime_config.plan_mode,
        }
        return payload

    def _load_client_class(self):
        module = importlib.import_module(self.runtime_config.module_name)
        return module.DeerFlowClient

    def _resolved_config_path(self) -> str | None:
        raw_path = self.runtime_config.config_path.strip()
        if not raw_path:
            return None
        path = Path(raw_path)
        return str(path) if path.exists() else None

    def _build_client_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "thinking_enabled": self.runtime_config.thinking_enabled,
            "subagent_enabled": self.runtime_config.subagent_enabled,
            "plan_mode": self.runtime_config.plan_mode,
        }
        config_path = self._resolved_config_path()
        if config_path:
            kwargs["config_path"] = config_path
        if self.runtime_config.model_name:
            kwargs["model_name"] = self.runtime_config.model_name
        return kwargs

    def _build_message(self, request: DeerflowTaskRequest) -> str:
        boundary = request.system_context.get("constraints", {}).get("network_boundary", {})
        boundary_text = json.dumps(boundary, ensure_ascii=False, indent=2)
        context_text = json.dumps(request.system_context, ensure_ascii=False, indent=2)
        budget = request.system_context.get("budget", {}) or {}
        return (
            "You are being invoked by lite-interpreter's Dynamic Swarm Super Node.\n"
            "Follow the execution boundary exactly:\n"
            f"{boundary_text}\n\n"
            "Important constraints:\n"
            "- Use DeerFlow tool-mediated network access only when research is necessary.\n"
            "- Do not execute generated Python directly on the host.\n"
            "- lite-interpreter owns final code execution through its sandbox.\n"
            f"- Stop after at most {self.runtime_config.max_steps} meaningful steps.\n"
            f"- Respect the provided budget envelope: {json.dumps(budget, ensure_ascii=False)}.\n"
            "- If you discover a reusable workflow, summarize it as a potential static skill.\n\n"
            f"Task:\n{request.query}\n\n"
            f"Injected context:\n{context_text}"
        )

    @staticmethod
    def _python_version_hint() -> str:
        current = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        return (
            f"Current interpreter is Python {current}. DeerFlow harness metadata requires Python >= 3.12, "
            "so environments below 3.12 cannot host the embedded client."
        )

    @staticmethod
    def _normalize_trace_event(index: int, event: Any) -> dict[str, Any]:
        event_type = getattr(event, "type", "unknown")
        payload = getattr(event, "data", {}) or {}
        step_name = payload.get("name") or payload.get("type") or f"event_{index}"
        trace_event = TraceEvent(
            event_id=generate_uuid(),
            topic="runtime.deerflow.trace",
            tenant_id="",
            task_id="",
            workspace_id="",
            trace_id=f"deerflow-trace-{index}",
            timestamp=get_utc_now(),
            payload={
                "agent_name": "deerflow",
                "step_name": str(step_name),
                "event_type": str(event_type),
                "payload": payload,
            },
            source="deerflow-embedded",
        )
        payload = dict(trace_event.payload)
        payload["source"] = trace_event.source
        return payload

    @staticmethod
    def _normalize_sidecar_event(index: int, event: dict[str, Any]) -> dict[str, Any]:
        event_type = str(event.get("type", "unknown"))
        payload = event.get("data", {}) or {}
        step_name = payload.get("name") or payload.get("type") or f"event_{index}"
        trace_event = TraceEvent(
            event_id=generate_uuid(),
            topic="runtime.deerflow.trace",
            tenant_id="",
            task_id="",
            workspace_id="",
            trace_id=f"deerflow-sidecar-trace-{index}",
            timestamp=get_utc_now(),
            payload={
                "agent_name": "deerflow-sidecar",
                "step_name": str(step_name),
                "event_type": event_type,
                "payload": payload,
            },
            source="deerflow-sidecar",
        )
        payload = dict(trace_event.payload)
        payload["source"] = trace_event.source
        return payload

    @staticmethod
    def _extract_artifacts(trace: list[dict[str, Any]]) -> list[str]:
        artifacts: list[str] = []
        for item in trace:
            payload = item.get("payload", {})
            if not isinstance(payload, dict):
                continue
            for artifact in payload.get("artifacts", []):
                if isinstance(artifact, dict):
                    artifact_ref = artifact.get("path") or artifact.get("url") or artifact.get("name")
                    if artifact_ref:
                        artifacts.append(str(artifact_ref))
                elif artifact:
                    artifacts.append(str(artifact))
        return artifacts

    def preview(self, request: DeerflowTaskRequest) -> DeerflowTaskResult:
        """Return a deterministic planning preview for docs and degraded mode."""
        metadata = dict(request.metadata)
        trace_id = metadata.get("trace_id", f"dynamic-preview:{request.task_id}")
        trace = [
            {
                "agent_name": "dynamic_swarm",
                "step_name": "prepare_request",
                "event_type": "selected",
                "payload": {
                    "trace_id": trace_id,
                    "routing_mode": metadata.get("routing_mode", "dynamic"),
                    "runtime_mode": self.runtime_config.runtime_mode,
                    "python_package": self.runtime_config.module_name,
                    "sidecar_url": self.runtime_config.sidecar_url or None,
                    "network_boundary": request.system_context.get("constraints", {}).get("network_boundary", {}),
                },
            }
        ]
        return DeerflowTaskResult(
            status="planned",
            summary="Dynamic swarm request prepared; install/configure DeerFlow before live execution.",
            trace_refs=[trace_id],
            artifacts=[],
            recommended_skill={
                "source": "dynamic_swarm",
                "confidence": metadata.get("confidence", "pending"),
            },
            trace=trace,
            runtime_metadata={
                "requested_runtime_mode": self.runtime_config.runtime_mode,
                "effective_runtime_mode": "preview",
            },
        )

    def _run_via_embedded(
        self,
        request: DeerflowTaskRequest,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> DeerflowTaskResult:
        deerflow_client_cls = self._load_client_class()
        client = deerflow_client_cls(**self._build_client_kwargs())

        trace: list[dict[str, Any]] = []
        summary_chunks: list[str] = []
        thread_id = f"lite-interpreter-{request.task_id}"
        for index, event in enumerate(
            client.stream(
                self._build_message(request),
                thread_id=thread_id,
                subagent_enabled=self.runtime_config.subagent_enabled,
                plan_mode=self.runtime_config.plan_mode,
                thinking_enabled=self.runtime_config.thinking_enabled,
                recursion_limit=self.runtime_config.recursion_limit,
            )
        ):
            if index >= self.runtime_config.max_events:
                truncated_event = {
                    "agent_name": "deerflow",
                    "step_name": "event_limit",
                    "event_type": "truncated",
                    "payload": {"max_events": self.runtime_config.max_events},
                }
                trace.append(truncated_event)
                if on_event:
                    on_event(truncated_event)
                break

            normalized = self._normalize_trace_event(index, event)
            trace.append(normalized)
            if on_event:
                on_event(normalized)
            payload = normalized.get("payload", {})
            if normalized["event_type"] == "messages-tuple" and payload.get("type") == "ai":
                content = payload.get("content")
                if content:
                    summary_chunks.append(str(content))

        artifacts = self._extract_artifacts(trace)
        summary = "\n".join(summary_chunks).strip() or "DeerFlow completed without emitting AI text."
        return DeerflowTaskResult(
            status="completed",
            summary=summary,
            trace_refs=[f"deerflow:{thread_id}"],
            artifacts=artifacts,
            recommended_skill={
                "source": "dynamic_swarm",
                "confidence": "medium",
                "source_task_type": request.metadata.get("dynamic_reason") or "dynamic_task",
            },
            trace=trace,
            runtime_metadata={
                "requested_runtime_mode": self.runtime_config.runtime_mode,
                "effective_runtime_mode": "embedded",
                "thread_id": thread_id,
            },
        )

    def _run_via_sidecar(
        self,
        request: DeerflowTaskRequest,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> DeerflowTaskResult:
        if not self.runtime_config.sidecar_url:
            raise ValueError("Sidecar mode requires DEERFLOW_SIDECAR_URL")

        payload = {
            "message": self._build_message(request),
            "thread_id": f"lite-interpreter-{request.task_id}",
            "config_path": self._resolved_config_path(),
            "model_name": self.runtime_config.model_name or None,
            "thinking_enabled": self.runtime_config.thinking_enabled,
            "subagent_enabled": self.runtime_config.subagent_enabled,
            "plan_mode": self.runtime_config.plan_mode,
            "recursion_limit": self.runtime_config.recursion_limit,
        }

        trace: list[dict[str, Any]] = []
        summary_chunks: list[str] = []
        with httpx.stream(
            "POST",
            f"{self.runtime_config.sidecar_url.rstrip('/')}/v1/stream",
            json=payload,
            timeout=self.runtime_config.sidecar_timeout,
        ) as response:
            response.raise_for_status()
            for index, line in enumerate(response.iter_lines()):
                if not line:
                    continue
                event = json.loads(line)
                normalized = self._normalize_sidecar_event(index, event)
                trace.append(normalized)
                if on_event:
                    on_event(normalized)
                if normalized["event_type"] == "messages-tuple" and normalized["payload"].get("type") == "ai":
                    content = normalized["payload"].get("content")
                    if content:
                        summary_chunks.append(str(content))
                if index + 1 >= self.runtime_config.max_events:
                    break

        artifacts = self._extract_artifacts(trace)
        summary = "\n".join(summary_chunks).strip() or "DeerFlow sidecar completed without emitting AI text."
        return DeerflowTaskResult(
            status="completed",
            summary=summary,
            trace_refs=[f"deerflow-sidecar:{request.task_id}"],
            artifacts=artifacts,
            recommended_skill={
                "source": "dynamic_swarm",
                "confidence": "medium",
                "source_task_type": request.metadata.get("dynamic_reason") or "dynamic_task",
            },
            trace=trace,
            runtime_metadata={
                "requested_runtime_mode": self.runtime_config.runtime_mode,
                "effective_runtime_mode": "sidecar",
                "sidecar_url": self.runtime_config.sidecar_url or None,
            },
        )

    def run(
        self,
        request: DeerflowTaskRequest,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> DeerflowTaskResult:
        """Execute the request through sidecar or embedded mode."""
        runtime_mode = self.runtime_config.runtime_mode or "auto"

        if runtime_mode == "sidecar":
            try:
                return self._run_via_sidecar(request, on_event=on_event)
            except TaskLeaseLostError:
                raise
            except Exception as exc:
                preview = self.preview(request)
                return DeerflowTaskResult(
                    status="unavailable",
                    summary=f"Failed to reach DeerFlow sidecar `{self.runtime_config.sidecar_url}`: {exc}",
                    trace_refs=preview.trace_refs,
                    artifacts=preview.artifacts,
                    recommended_skill=preview.recommended_skill,
                    trace=preview.trace,
                    runtime_metadata={
                        **preview.runtime_metadata,
                        "requested_runtime_mode": "sidecar",
                        "effective_runtime_mode": "unavailable",
                        "sidecar_fallback_reason": str(exc),
                        "sidecar_url": self.runtime_config.sidecar_url or None,
                    },
                )

        auto_sidecar_error: str | None = None
        if runtime_mode == "auto" and self.runtime_config.sidecar_url:
            try:
                return self._run_via_sidecar(request, on_event=on_event)
            except TaskLeaseLostError:
                raise
            except Exception as exc:
                auto_sidecar_error = str(exc)

        try:
            result = self._run_via_embedded(request, on_event=on_event)
            if auto_sidecar_error:
                return DeerflowTaskResult(
                    status=result.status,
                    summary=result.summary,
                    trace_refs=result.trace_refs,
                    artifacts=result.artifacts,
                    recommended_skill=result.recommended_skill,
                    trace=result.trace,
                    runtime_metadata={
                        **result.runtime_metadata,
                        "requested_runtime_mode": "auto",
                        "sidecar_fallback_reason": auto_sidecar_error,
                        "sidecar_url": self.runtime_config.sidecar_url or None,
                    },
                )
            return result
        except TaskLeaseLostError:
            raise
        except Exception as exc:
            preview = self.preview(request)
            return DeerflowTaskResult(
                status="unavailable",
                summary=(
                    f"Failed to use DeerFlow runtime in `{runtime_mode}` mode: {exc}. {self._python_version_hint()}"
                ),
                trace_refs=preview.trace_refs,
                artifacts=preview.artifacts,
                recommended_skill=preview.recommended_skill,
                trace=preview.trace,
                runtime_metadata={
                    **preview.runtime_metadata,
                    "requested_runtime_mode": runtime_mode,
                    "effective_runtime_mode": "unavailable",
                    "embedded_error": str(exc),
                    "sidecar_fallback_reason": auto_sidecar_error,
                },
            )
