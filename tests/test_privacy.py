"""Tests for privacy masking and redaction hooks."""

from __future__ import annotations

from src.common import TaskEnvelope
from src.dynamic_engine.dynamic_supervisor import DynamicSupervisor
from src.harness import GovernanceDecision
from src.privacy import mask_payload, mask_text, scan_text


def test_mask_text_redacts_api_key_and_email():
    redacted, report = mask_text("api_key=secret-123 contact me at foo@example.com")
    assert "[REDACTED]" in redacted
    assert "[REDACTED_EMAIL]" in redacted
    assert report["match_count"] >= 2


def test_mask_payload_redacts_nested_sensitive_values():
    redacted, report = mask_payload(
        {
            "headers": {"Authorization": "Bearer abc.def.ghi"},
            "contact": ["13800138000", "foo@example.com"],
        }
    )
    assert "[REDACTED]" in redacted["headers"]["Authorization"]
    assert redacted["contact"][0] == "[REDACTED_PHONE]"
    assert redacted["contact"][1] == "[REDACTED_EMAIL]"
    assert report["match_count"] >= 3


def test_scan_text_detects_sensitive_patterns():
    findings = scan_text("access_token=my-token api_key=demo-key")
    assert {item["rule"] for item in findings} >= {"access_token", "api_key"}


def test_dynamic_supervisor_build_context_includes_canonical_fields():
    task_envelope = TaskEnvelope(
        task_id="task-2",
        tenant_id="tenant-2",
        workspace_id="ws-2",
        input_query="继续分析",
        governance_profile="reviewer",
        allowed_tools=["knowledge_query"],
        redaction_rules=[],
        max_dynamic_steps=9,
    )
    governance_decision = GovernanceDecision(
        action="dynamic",
        profile="reviewer",
        mode="standard",
        allowed=True,
        risk_level="low",
        risk_score=0.1,
        reasons=["test"],
        allowed_tools=["knowledge_query"],
    )

    ctx = DynamicSupervisor.build_context(
        state={
            "tenant_id": "tenant-2",
            "task_id": "task-2",
            "workspace_id": "ws-2",
            "input_query": "继续分析",
        },
        execution_state={},
        task_envelope=task_envelope,
        governance_decision=governance_decision,
    )

    assert ctx["tenant_id"] == "tenant-2"
    assert ctx["task_id"] == "task-2"
    assert ctx["governance_profile"] == "reviewer"
    assert ctx["allowed_tools"] == ["knowledge_query"]
    assert ctx["routing_mode"] == "dynamic"
    assert ctx["runtime_backend"] == "native"
    assert ctx["max_dynamic_steps"] == 9
