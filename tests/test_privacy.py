"""Tests for privacy masking and redaction hooks."""

from __future__ import annotations

from src.dynamic_engine.blackboard_context import build_dynamic_context
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


def test_build_dynamic_context_redacts_query_and_snapshots():
    envelope = build_dynamic_context(
        {
            "tenant_id": "tenant-1",
            "task_id": "task-1",
            "workspace_id": "ws-1",
            "input_query": "请分析 api_key=secret-1 对系统的影响",
            "knowledge_snapshot": {"note": "联系 foo@example.com"},
            "memory_snapshot": {"task_summary": {"answer": "手机号 13800138000"}},
            "allowed_tools": ["knowledge_query"],
        },
        {"execution_result": {"output": "手机号 13800138000"}},
        redaction_rules=["api_key", "email", "phone"],
    )
    assert "[REDACTED]" in envelope.input_query
    assert "[REDACTED_EMAIL]" in envelope.knowledge_snapshot["note"]
    assert envelope.memory_snapshot["task_summary"]["answer"] == "手机号 [REDACTED_PHONE]"
    assert envelope.execution_snapshot["execution_result"]["output"] == "手机号 [REDACTED_PHONE]"


def test_build_dynamic_context_prefers_canonical_task_contract_fields():
    envelope = build_dynamic_context(
        {
            "tenant_id": "tenant-2",
            "task_id": "task-2",
            "workspace_id": "ws-2",
            "input_query": "继续分析",
            "task_envelope": {
                "task_id": "task-2",
                "tenant_id": "tenant-2",
                "workspace_id": "ws-2",
                "input_query": "继续分析",
                "governance_profile": "reviewer",
                "allowed_tools": ["knowledge_query"],
                "max_dynamic_steps": 9,
            },
            "execution_intent": {
                "intent": "dynamic_flow",
                "destinations": ["dynamic_swarm"],
            },
            # 故意给扁平字段放冲突值，验证优先使用规范契约
            "allowed_tools": ["shell_exec"],
            "governance_profile": "researcher",
            "max_dynamic_steps": 2,
        },
        {},
    )

    assert envelope.constraints["allowed_tools"] == ["knowledge_query"]
    assert envelope.constraints["governance_profile"] == "reviewer"
    assert envelope.constraints["routing_mode"] == "dynamic"
    assert envelope.budget["max_steps"] == 9
