"""Task console result formatting tests."""
from __future__ import annotations

from pathlib import Path

import httpx
from src.frontend.pages.task_console import (
    build_output_cards,
    collect_result_sections,
    describe_output_asset,
    fetch_json_payload,
    fetch_task_console_bundle,
    list_directory_entries,
    select_stream_target,
    summarize_result_header,
)


def test_summarize_result_header_prefers_final_response_fields():
    payload = {
        "status": {"global_status": "success"},
        "response": {
            "mode": "static",
            "headline": "分析完成",
            "answer": "这是最终回答。",
        },
    }

    header = summarize_result_header(payload)
    assert header["mode"] == "static"
    assert header["headline"] == "分析完成"
    assert header["answer"] == "这是最终回答。"


def test_collect_result_sections_extracts_lists():
    payload = {
        "executions": [{"execution_id": "sandbox:session-1", "kind": "sandbox"}],
        "tool_calls": [{"tool_name": "web_search", "phase": "start"}],
        "status": {
            "task_lease": {"owner_id": "host:pid", "lease_expires_at": "2026-04-05T00:00:00Z", "backend": "memory_fallback"}
        },
        "response": {
            "key_findings": ["f1", "f2"],
            "outputs": [{"type": "dataset", "name": "sales.csv"}],
            "caveats": ["limited"],
            "evidence_refs": ["chunk-1"],
        }
    }

    sections = collect_result_sections(payload)
    assert sections["findings"] == ["f1", "f2"]
    assert sections["outputs"][0]["name"] == "sales.csv"
    assert sections["caveats"] == ["limited"]
    assert sections["evidence_refs"] == ["chunk-1"]
    assert sections["executions"][0]["execution_id"] == "sandbox:session-1"
    assert sections["tool_calls"][0]["tool_name"] == "web_search"
    assert sections["task_lease"][0]["owner_id"] == "host:pid"
    assert sections["analysis_brief"] == []
    assert sections["parser_reports"] == []


def test_select_stream_target_prefers_execution_stream_when_available():
    target = select_stream_target(
        {
            "task": {"task_id": "task-1"},
            "executions": [{"execution_id": "runtime:task-1", "kind": "runtime"}],
        }
    )
    assert target["stream_kind"] == "execution"
    assert target["execution_id"] == "runtime:task-1"


def test_select_stream_target_honors_preferred_execution_id():
    target = select_stream_target(
        {
            "task": {"task_id": "task-1"},
            "executions": [
                {"execution_id": "runtime:task-1", "kind": "runtime"},
                {"execution_id": "sandbox:session-1", "kind": "sandbox"},
            ],
        },
        preferred_execution_id="sandbox:session-1",
    )
    assert target["stream_kind"] == "execution"
    assert target["execution_id"] == "sandbox:session-1"


def test_select_stream_target_falls_back_to_task_stream():
    target = select_stream_target({"task": {"task_id": "task-2"}, "executions": []})
    assert target["stream_kind"] == "task"
    assert target["task_id"] == "task-2"


def test_fetch_json_payload_returns_dict(monkeypatch):
    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    monkeypatch.setattr(httpx, "get", lambda url, timeout=20.0, headers=None: _FakeResponse())
    payload = fetch_json_payload("http://127.0.0.1:8000/api/tasks/task-1/result")
    assert payload["ok"] is True


def test_fetch_task_console_bundle_uses_execution_endpoints(monkeypatch):
    requested_urls = []

    class _FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_get(url, timeout=20.0, headers=None):
        requested_urls.append(url)
        if "/result?" in url:
            return _FakeResponse({"task": {"task_id": "task-1"}, "response": {"headline": "done"}})
        if "/executions?" in url:
            return _FakeResponse({"executions": [{"execution_id": "runtime:task-1", "kind": "runtime"}]})
        if "/tool-calls?" in url:
            return _FakeResponse({"tool_calls": [{"tool_name": "web_search", "phase": "start"}]})
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(httpx, "get", fake_get)
    payload = fetch_task_console_bundle(
        "http://127.0.0.1:8000",
        "task-1",
        tenant_id="tenant-1",
        workspace_id="ws-1",
    )

    assert payload["executions"][0]["execution_id"] == "runtime:task-1"
    assert payload["tool_calls"][0]["tool_name"] == "web_search"
    assert any(url.endswith("/api/tasks/task-1/result?tenant_id=tenant-1&workspace_id=ws-1") for url in requested_urls)
    assert any(url.endswith("/api/tasks/task-1/executions?tenant_id=tenant-1&workspace_id=ws-1") for url in requested_urls)
    assert any(url.endswith("/api/executions/runtime:task-1/tool-calls?tenant_id=tenant-1&workspace_id=ws-1") for url in requested_urls)


def test_collect_result_sections_extracts_parser_reports():
    payload = {
        "response": {
            "details": {
                "parser_reports": [
                    {"file_name": "rule.pdf", "parse_mode": "ocr+vision", "parser_diagnostics": {"image_description_count": 2}}
                ]
            }
        }
    }
    sections = collect_result_sections(payload)
    assert sections["parser_reports"][0]["parse_mode"] == "ocr+vision"


def test_collect_result_sections_extracts_knowledge_snapshot():
    payload = {
        "knowledge": {
            "knowledge_snapshot": {
                "rewritten_query": "报销 规则",
                "recall_strategies": ["bm25", "vector"],
                "filters": {"year": "2024"},
            }
        }
    }
    sections = collect_result_sections(payload)
    assert sections["knowledge_snapshot"][0]["rewritten_query"] == "报销 规则"
    assert sections["knowledge_snapshot"][0]["filters"]["year"] == "2024"


def test_collect_result_sections_extracts_analysis_brief():
    payload = {
        "knowledge": {
            "analysis_brief": {
                "question": "结合费用数据和规则，检查合同缺失",
                "analysis_mode": "hybrid_analysis",
                "dataset_summaries": ["expenses.csv: schema=contract_id,tax_amount"],
                "business_rules": ["规则：必须上传合同。"],
                "business_metrics": ["审批时效口径"],
                "business_filters": ["上海"],
                "evidence_refs": ["rule-1"],
                "known_gaps": ["业务规则尚未抽取完成"],
                "recommended_next_step": "先核对证据与规则，再生成模板化数据分析代码",
            }
        }
    }
    sections = collect_result_sections(payload)
    assert sections["analysis_brief"][0]["analysis_mode"] == "hybrid_analysis"
    assert sections["analysis_brief"][0]["dataset_summaries"][0].startswith("expenses.csv")
    assert sections["analysis_brief"][0]["business_rules"] == ["规则：必须上传合同。"]


def test_collect_result_sections_extracts_historical_skill_matches():
    payload = {
        "skills": {
            "historical_matches": [
                {
                    "name": "historical_skill_demo",
                    "required_capabilities": ["knowledge_query"],
                    "match_source": "historical_repo",
                    "match_reason": "query_capabilities=knowledge_query",
                    "match_score": 5,
                    "usage": {"usage_count": 3},
                }
            ]
        },
        "response": {
            "details": {
                "used_historical_skills": [
                    {
                        "name": "historical_skill_demo",
                        "selected_by_stages": ["router", "coder"],
                        "used_in_codegen": True,
                        "used_replay_case_ids": ["replay_123"],
                        "used_capabilities": ["knowledge_query"],
                        "usage": {"success_rate": 0.8},
                    }
                ]
            }
        },
    }
    sections = collect_result_sections(payload)
    assert sections["historical_skill_matches"][0]["name"] == "historical_skill_demo"
    assert sections["historical_skill_matches"][0]["match_source"] == "historical_repo"
    assert sections["used_historical_skills"][0]["used_in_codegen"] is True
    assert sections["used_historical_skills"][0]["used_replay_case_ids"] == ["replay_123"]
    assert sections["used_historical_skills"][0]["usage"]["success_rate"] == 0.8


def test_collect_result_sections_extracts_rule_checks():
    payload = {
        "response": {
            "details": {
                "rule_checks": [
                    {
                        "rule": "报销金额必须含税并上传合同",
                        "issue_count": 2,
                        "warnings": ["sales.csv 存在 1 行税额缺失/为0"],
                        "matched_datasets": ["sales.csv"],
                        "matched_documents": ["rule.txt"],
                    }
                ]
            }
        }
    }
    sections = collect_result_sections(payload)
    assert sections["rule_checks"][0]["issue_count"] == 2
    assert sections["rule_checks"][0]["matched_datasets"] == ["sales.csv"]


def test_collect_result_sections_extracts_metric_and_filter_checks():
    payload = {
        "response": {
            "details": {
                "metric_checks": [
                    {
                        "metric": "审批时效口径",
                        "matched_datasets": ["sales.csv"],
                        "matched_columns": ["duration_days"],
                        "highlights": ["sales.csv.duration_days mean=2.0"],
                    }
                ],
                "filter_checks": [
                    {
                        "filter": "上海",
                        "matched_datasets": ["sales.csv"],
                        "matched_documents": ["rule.txt"],
                        "matched_values": ["city => [('上海', 3)]"],
                    }
                ],
            }
        }
    }
    sections = collect_result_sections(payload)
    assert sections["metric_checks"][0]["metric"] == "审批时效口径"
    assert sections["filter_checks"][0]["filter"] == "上海"


def test_build_output_cards_formats_known_types():
    cards = build_output_cards(
        [
            {"type": "dataset", "name": "sales.csv", "summary": "rows=10"},
            {"type": "artifact", "name": "/tmp/out.json", "summary": "saved output"},
        ]
    )

    assert cards[0]["icon"] == "TABLE"
    assert cards[0]["title"] == "sales.csv"
    assert cards[1]["icon"] == "FILE"
    assert cards[1]["subtitle"] == "saved output"


def test_describe_output_asset_detects_previewable_text(tmp_path: Path):
    file_path = tmp_path / "report.json"
    file_path.write_text('{"ok": true}', encoding="utf-8")

    asset = describe_output_asset({"type": "artifact", "name": "report.json", "path": str(file_path)})
    assert asset["exists"] is True
    assert asset["preview_kind"] == "text"
    assert asset["download_name"] == "report.json"


def test_describe_output_asset_handles_missing_paths():
    asset = describe_output_asset({"type": "dataset", "name": "sales.csv", "path": "/tmp/missing.csv"})
    assert asset["exists"] is False
    assert asset["preview_kind"] == "text"


def test_list_directory_entries_returns_sorted_children(tmp_path: Path):
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    file_a = tmp_path / "a.txt"
    file_a.write_text("hello", encoding="utf-8")
    file_b = tmp_path / "b.txt"
    file_b.write_text("world", encoding="utf-8")

    entries = list_directory_entries(str(tmp_path))
    assert entries[0]["is_dir"] is True
    assert entries[0]["name"] == "subdir"
    assert any(entry["name"] == "a.txt" for entry in entries)
    assert any(entry["name"] == "b.txt" for entry in entries)
