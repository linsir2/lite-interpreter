"""Tests for dynamic runtime supervision helpers."""
from __future__ import annotations

from dataclasses import dataclass

from src.common import CapabilityDomainManifest, RuntimeCapabilityManifest
from src.dynamic_engine.runtime_gateway import RuntimeGateway
from src.dynamic_engine.runtime_registry import RuntimeRegistry
from src.dynamic_engine.runtime_backends import build_deerflow_runtime_manifest
from src.dynamic_engine.supervisor import DynamicSupervisor
from src.dynamic_engine.trace_normalizer import TraceNormalizer


def test_dynamic_supervisor_prepares_allowed_run_plan():
    plan = DynamicSupervisor.prepare(
        {
            "tenant_id": "tenant-supervisor",
            "task_id": "task-supervisor",
            "workspace_id": "ws-supervisor",
            "input_query": "自己找数据并验证结论",
            "routing_mode": "dynamic",
            "complexity_score": 0.9,
        },
        {},
    )
    assert plan.governance_decision.allowed is True
    assert plan.request is not None
    assert plan.execution_intent.intent == "dynamic_flow"
    assert plan.task_envelope.task_id == "task-supervisor"


def test_dynamic_supervisor_builds_denied_patch_for_unknown_tools():
    plan = DynamicSupervisor.prepare(
        {
            "tenant_id": "tenant-denied",
            "task_id": "task-denied",
            "workspace_id": "ws-denied",
            "input_query": "帮我联网调研后执行结果",
            "allowed_tools": ["shell_exec"],
            "routing_mode": "dynamic",
        },
        {},
    )
    denied_patch = plan.denied_patch()
    assert plan.governance_decision.allowed is False
    assert denied_patch["dynamic_status"] == "denied"
    assert denied_patch["execution_intent"].intent == "dynamic_flow"


def test_trace_normalizer_enriches_runtime_event():
    normalized = TraceNormalizer.normalize_runtime_event(
        {
            "agent_name": "deerflow",
            "step_name": "research",
            "event_type": "completed",
            "payload": {"foo": "bar"},
        }
    )
    assert normalized["source"] == "dynamic_swarm"
    assert normalized["step_name"] == "research"
    assert normalized["payload"]["foo"] == "bar"
    assert normalized["event_type"] == "progress"
    assert normalized["source_event_type"] == "completed"


def test_trace_normalizer_maps_ai_message_and_artifact_events_to_v2():
    text_event = TraceNormalizer.normalize_runtime_event(
        {
            "agent_name": "deerflow",
            "step_name": "answer",
            "event_type": "messages-tuple",
            "payload": {"type": "ai", "content": "hello"},
        }
    )
    artifact_event = TraceNormalizer.normalize_runtime_event(
        {
            "agent_name": "deerflow",
            "step_name": "artifact_step",
            "event_type": "values",
            "payload": {"artifacts": [{"path": "/tmp/report.md"}]},
        }
    )

    assert text_event["event_type"] == "text"
    assert text_event["message"] == "hello"
    assert artifact_event["event_type"] == "artifact"
    assert artifact_event["artifact_refs"] == ["/tmp/report.md"]


def test_trace_normalizer_maps_tool_call_payloads_to_v2():
    start_event = TraceNormalizer.normalize_runtime_event(
        {
            "agent_name": "deerflow",
            "step_name": "search_start",
            "event_type": "values",
            "payload": {"tool_name": "web_search", "tool_call_id": "call-1", "arguments": {"q": "lite interpreter"}},
        }
    )
    result_event = TraceNormalizer.normalize_runtime_event(
        {
            "agent_name": "deerflow",
            "step_name": "search_result",
            "event_type": "values",
            "payload": {"tool_name": "web_search", "tool_call_id": "call-1", "result": {"items": 3}, "status": "completed"},
        }
    )

    assert start_event["event_type"] == "tool_call_start"
    assert start_event["tool_call"]["tool_name"] == "web_search"
    assert result_event["event_type"] == "tool_result"
    assert result_event["tool_call"]["result"]["items"] == 3


@dataclass
class _FakeBackend:
    name: str = "fake"

    def build_payload(self, plan):
        return {"backend": "fake", "task_id": plan.task_envelope.task_id}

    def run(self, plan, on_event=None):
        if on_event:
            on_event({"agent_name": "fake", "step_name": "run", "event_type": "completed", "payload": {}})
        return {"status": "ok"}


def test_runtime_gateway_uses_registry_backend():
    registry = RuntimeRegistry()
    registry.register("fake", lambda **kwargs: _FakeBackend())
    plan = DynamicSupervisor.prepare(
        {
            "tenant_id": "tenant-runtime",
            "task_id": "task-runtime",
            "workspace_id": "ws-runtime",
            "input_query": "自己找数据并验证结论",
            "runtime_backend": "fake",
            "routing_mode": "dynamic",
        },
        {},
    )
    gateway = RuntimeGateway(max_steps=4, backend_name="fake", registry=registry)
    assert gateway.backend_name == "fake"
    assert gateway.build_payload(plan)["backend"] == "fake"


def test_deerflow_runtime_manifest_describes_capabilities():
    manifest = build_deerflow_runtime_manifest(max_steps=8)
    assert manifest.runtime_id == "deerflow"
    assert "sidecar" in manifest.runtime_modes
    assert any(domain.domain_id == "research" and domain.supported for domain in manifest.domains)
    sandbox_domain = next(domain for domain in manifest.domains if domain.domain_id == "sandbox_execution")
    assert sandbox_domain.supported is False
    assert "max_steps=8" in manifest.limitations[0]


def test_runtime_registry_lists_manifests():
    manifests = RuntimeRegistry()
    manifests.register(
        "fake",
        lambda **kwargs: _FakeBackend(),
        manifest=lambda: RuntimeCapabilityManifest(
            runtime_id="fake",
            display_name="Fake Runtime",
            description="test runtime",
            runtime_modes=["test"],
            domains=[CapabilityDomainManifest(domain_id="research", description="test")],
        ),
    )
    listed = manifests.list_manifests()
    assert listed
    assert listed[0].runtime_id == "fake"
