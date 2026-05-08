"""Tests for dynamic runtime supervision helpers."""

from __future__ import annotations

from src.dynamic_engine.runtime_backends import (
    build_deerflow_runtime_manifest,
    get_runtime_manifest,
    list_runtime_manifests,
)
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
    assert denied_patch["dynamic_continuation"] == "finish"
    assert denied_patch["execution_intent"].intent == "dynamic_flow"


def test_dynamic_supervisor_context_prefers_execution_state_snapshot_and_history():
    plan = DynamicSupervisor.prepare(
        {
            "tenant_id": "tenant-context",
            "task_id": "task-context",
            "workspace_id": "ws-context",
            "input_query": "自己找数据并验证结论",
            "routing_mode": "dynamic",
        },
        {
            "task_envelope": {
                "task_id": "task-context",
                "tenant_id": "tenant-context",
                "workspace_id": "ws-context",
                "input_query": "自己找数据并验证结论",
                "governance_profile": "reviewer",
                "allowed_tools": ["knowledge_query"],
                "redaction_rules": ["foo@example.com"],
                "max_dynamic_steps": 9,
                "metadata": {"routing_mode": "dynamic", "runtime_backend": "deerflow"},
            },
            "knowledge_snapshot": {
                "rewritten_query": "验证 结论",
                "evidence_refs": ["chunk-9"],
            },
            "decision_log": [
                {
                    "action": "dynamic_precheck",
                    "profile": "reviewer",
                    "mode": "standard",
                    "allowed": True,
                    "risk_level": "low",
                    "risk_score": 0.1,
                    "reasons": ["previous decision"],
                    "allowed_tools": ["knowledge_query"],
                }
            ],
        },
    )

    assert plan.context_envelope is not None
    assert plan.task_envelope.governance_profile == "reviewer"
    assert plan.task_envelope.allowed_tools == ["knowledge_query"]
    assert plan.task_envelope.max_dynamic_steps == 9
    assert plan.context_envelope.knowledge_snapshot["evidence_refs"] == ["chunk-9"]
    assert plan.context_envelope.memory_snapshot["task_id"] == "task-context"
    assert len(plan.context_envelope.constraints["decision_log"]) == 2
    assert plan.context_envelope.constraints["decision_log"][0]["reasons"] == ["previous decision"]


def test_dynamic_supervisor_prefers_router_metadata_over_recomputed_profile():
    plan = DynamicSupervisor.prepare(
        {
            "tenant_id": "tenant-runtime-inherit",
            "task_id": "task-runtime-inherit",
            "workspace_id": "ws-runtime-inherit",
            "input_query": "分析销售数据并总结趋势",
            "routing_mode": "dynamic",
        },
        {
            "execution_intent": {
                "intent": "dynamic_flow",
                "destinations": ["dynamic_swarm"],
                "metadata": {
                    "analysis_mode": "dynamic_research_analysis",
                    "evidence_strategy": "external_research",
                    "effective_model_alias": "reasoning_model",
                    "effective_tools": ["web_search"],
                },
            }
        },
    )

    assert plan.request is not None
    assert plan.request.metadata["analysis_mode"] == "dynamic_research_analysis"
    assert plan.request.metadata["evidence_strategy"] == "external_research"
    assert plan.request.metadata["effective_model_alias"] == "reasoning_model"


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
            "payload": {
                "tool_name": "web_search",
                "tool_call_id": "call-1",
                "result": {"items": 3},
                "status": "completed",
            },
        }
    )

    assert start_event["event_type"] == "tool_call_start"
    assert start_event["tool_call"]["tool_name"] == "web_search"
    assert result_event["event_type"] == "tool_result"
    assert result_event["tool_call"]["result"]["items"] == 3

def test_deerflow_runtime_manifest_describes_capabilities():
    manifest = build_deerflow_runtime_manifest(max_steps=8)
    assert manifest.runtime_id == "deerflow"
    assert "sidecar" in manifest.runtime_modes
    assert any(domain.domain_id == "research" and domain.supported for domain in manifest.domains)
    sandbox_domain = next(domain for domain in manifest.domains if domain.domain_id == "sandbox_execution")
    assert sandbox_domain.supported is False
    assert "max_steps=8" in manifest.limitations[0]


def test_runtime_manifest_helpers_expose_deerflow_only():
    listed = list_runtime_manifests()
    assert listed
    assert listed[0].runtime_id == "deerflow"
    manifest = get_runtime_manifest("deerflow")
    assert manifest.runtime_id == "deerflow"
