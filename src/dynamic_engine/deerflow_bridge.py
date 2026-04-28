"""Isolation layer for DeerFlow sidecar-backed dynamic runs."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx
from config.settings import (
    DEERFLOW_CONFIG_PATH,
    DEERFLOW_MAX_EVENTS,
    DEERFLOW_MAX_STEPS,
    DEERFLOW_MODEL_NAME,
    DEERFLOW_RECURSION_LIMIT,
    DEERFLOW_SIDECAR_TIMEOUT,
    DEERFLOW_SIDECAR_URL,
)

from src.common.contracts import TraceEvent
from src.common.control_plane import ensure_dynamic_resume_overlay
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
    continuation: Literal["finish", "resume_static"] = "finish"
    next_static_steps: list[str] = field(default_factory=list)
    skip_static_steps: list[str] = field(default_factory=list)
    trace_refs: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    research_findings: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    suggested_static_actions: list[str] = field(default_factory=list)
    recommended_static_action: str = ""
    strategy_family: str | None = None
    recommended_skill: dict[str, Any] = field(default_factory=dict)
    trace: list[dict[str, Any]] = field(default_factory=list)
    runtime_metadata: dict[str, Any] = field(default_factory=dict)

    def to_state_patch(self) -> dict[str, Any]:
        from src.dynamic_engine.trace_normalizer import TraceNormalizer

        resume_overlay = ensure_dynamic_resume_overlay(
            {
                "continuation": self.continuation,
                "next_static_steps": self.next_static_steps,
                "skip_static_steps": self.skip_static_steps,
                "evidence_refs": self.evidence_refs,
                "suggested_static_actions": self.suggested_static_actions,
                "recommended_static_action": self.recommended_static_action,
                "open_questions": self.open_questions,
                "strategy_family": self.strategy_family,
            }
        )
        return {
            "dynamic_status": self.status,
            "dynamic_summary": self.summary,
            "dynamic_continuation": self.continuation,
            "dynamic_resume_overlay": resume_overlay.model_dump(mode="json"),
            "dynamic_next_static_steps": list(self.next_static_steps),
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
            "dynamic_research_findings": list(self.research_findings),
            "dynamic_evidence_refs": list(self.evidence_refs),
            "dynamic_open_questions": list(self.open_questions),
            "dynamic_suggested_static_actions": list(self.suggested_static_actions),
            "recommended_static_skill": dict(self.recommended_skill),
        }


@dataclass(frozen=True)
class DeerflowRuntimeConfig:
    """Runtime settings for the DeerFlow sidecar adapter."""

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

    The only supported runtime boundary is a DeerFlow sidecar over HTTP.
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
            "runtime_mode": "sidecar",
            "sidecar_url": self.runtime_config.sidecar_url or None,
            "config_path": self.runtime_config.config_path or None,
            "model_name": self.runtime_config.model_name or None,
            "max_steps": self.runtime_config.max_steps,
            "recursion_limit": self.runtime_config.recursion_limit,
            "subagent_enabled": self.runtime_config.subagent_enabled,
            "plan_mode": self.runtime_config.plan_mode,
        }
        return payload

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
    def _continuation_payload(request: DeerflowTaskRequest) -> tuple[Literal["finish", "resume_static"], list[str]]:
        continuation = str(request.metadata.get("continuation") or "finish").strip().lower()
        next_static_steps = [
            str(item).strip()
            for item in list(request.metadata.get("next_static_steps") or [])
            if str(item).strip()
        ]
        if continuation == "resume_static" and next_static_steps:
            return "resume_static", next_static_steps
        return "finish", []

    @staticmethod
    def _resume_overlay_payload(request: DeerflowTaskRequest) -> dict[str, Any]:
        continuation, next_static_steps = DeerflowBridge._continuation_payload(request)
        metadata = dict(request.metadata or {})
        return ensure_dynamic_resume_overlay(
            {
                "continuation": continuation,
                "next_static_steps": next_static_steps,
                "skip_static_steps": metadata.get("skip_static_steps") or [],
                "evidence_refs": metadata.get("evidence_refs") or [],
                "suggested_static_actions": metadata.get("suggested_static_actions") or [],
                "recommended_static_action": metadata.get("recommended_static_action") or "",
                "open_questions": metadata.get("open_questions") or [],
                "strategy_family": metadata.get("strategy_family"),
            }
        ).model_dump(mode="json")

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
                    "runtime_mode": "sidecar",
                    "sidecar_url": self.runtime_config.sidecar_url or None,
                    "network_boundary": request.system_context.get("constraints", {}).get("network_boundary", {}),
                },
            }
        ]
        return DeerflowTaskResult(
            status="unavailable",
            summary="Dynamic runtime sidecar is unavailable; no fallback runtime exists.",
            trace_refs=[trace_id],
            artifacts=[],
            research_findings=[],
            evidence_refs=[],
            open_questions=["DeerFlow runtime not available yet"],
            suggested_static_actions=[],
            recommended_skill={
                "source": "dynamic_swarm",
                "confidence": metadata.get("confidence", "pending"),
            },
            trace=trace,
            runtime_metadata={
                "requested_runtime_mode": "sidecar",
                "effective_runtime_mode": "unavailable",
            },
        )

    @staticmethod
    def _copy_research_payload(result: DeerflowTaskResult) -> dict[str, Any]:
        return {
            "research_findings": list(result.research_findings),
            "evidence_refs": list(result.evidence_refs),
            "open_questions": list(result.open_questions),
            "suggested_static_actions": list(result.suggested_static_actions),
        }

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
        resume_overlay = self._resume_overlay_payload(request)
        continuation = resume_overlay["continuation"]
        next_static_steps = list(resume_overlay["next_static_steps"])
        suggested_static_actions = (
            list(resume_overlay["suggested_static_actions"])
            or (["将动态研究结论转为静态分析计划并生成可审计代码"] if continuation == "resume_static" else [])
        )
        evidence_refs = [
            *list(resume_overlay["evidence_refs"]),
            f"deerflow-sidecar:{request.task_id}",
            *artifacts,
        ]
        return DeerflowTaskResult(
            status="completed",
            summary=summary,
            continuation=continuation,
            next_static_steps=next_static_steps,
            skip_static_steps=list(resume_overlay["skip_static_steps"]),
            trace_refs=[f"deerflow-sidecar:{request.task_id}"],
            artifacts=artifacts,
            research_findings=[summary] if summary else [],
            evidence_refs=list(dict.fromkeys(evidence_refs)),
            open_questions=list(resume_overlay["open_questions"]),
            suggested_static_actions=suggested_static_actions,
            recommended_static_action=str(resume_overlay.get("recommended_static_action") or ""),
            strategy_family=resume_overlay.get("strategy_family"),
            recommended_skill={
                "source": "dynamic_swarm",
                "confidence": "medium",
                "source_task_type": request.metadata.get("dynamic_reason") or "dynamic_task",
            },
            trace=trace,
            runtime_metadata={
                "requested_runtime_mode": "sidecar",
                "effective_runtime_mode": "sidecar",
                "sidecar_url": self.runtime_config.sidecar_url or None,
            },
        )

    def run(
        self,
        request: DeerflowTaskRequest,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> DeerflowTaskResult:
        """Execute the request through the DeerFlow sidecar boundary."""
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
                **self._copy_research_payload(preview),
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
