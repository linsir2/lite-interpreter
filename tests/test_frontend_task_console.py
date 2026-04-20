"""Task console result formatting tests."""

from __future__ import annotations

from pathlib import Path

import httpx
from src.frontend.components.workspace_shell import render_workspace_sidebar
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


def test_summarize_result_header_prefers_workspace_primary_fields():
    payload = {
        "workspace": {
            "primary": {
                "mode": "dynamic_then_static",
                "headline": "统一工作台标题",
                "answer": "统一工作台回答",
            }
        },
        "response": {"mode": "static", "headline": "旧标题", "answer": "旧回答"},
    }

    header = summarize_result_header(payload)
    assert header["mode"] == "dynamic_then_static"
    assert header["headline"] == "统一工作台标题"
    assert header["answer"] == "统一工作台回答"


def test_render_workspace_sidebar_returns_updated_fields():
    class _FakeStreamlit:
        def caption(self, value):  # noqa: ARG002
            return None

        def text_input(self, _label, value=""):
            return value

        def selectbox(self, _label, options, index=0):
            return options[index]

        def text_area(self, _label, value="", height=120):  # noqa: ARG002
            return value

    state = render_workspace_sidebar(
        _FakeStreamlit(),
        api_base_url="http://127.0.0.1:8000",
        tenant_id="tenant-a",
        workspace_id="ws-a",
        governance_profile="researcher",
        allowed_tools_text="knowledge_query",
        default_task="task-a",
        default_query="分析销售数据",
    )
    assert state["tenant_id"] == "tenant-a"
    assert state["workspace_id"] == "ws-a"
    assert state["task_id"] == "task-a"
    assert state["query"] == "分析销售数据"


def test_collect_result_sections_extracts_lists():
    payload = {
        "executions": [{"execution_id": "sandbox:session-1", "kind": "sandbox"}],
        "tool_calls": [{"tool_name": "web_search", "phase": "start"}],
        "status": {
            "task_lease": {
                "owner_id": "host:pid",
                "lease_expires_at": "2026-04-05T00:00:00Z",
                "backend": "test_stub",
            }
        },
        "response": {
            "key_findings": ["f1", "f2"],
            "outputs": [{"type": "dataset", "name": "sales.csv"}],
            "caveats": ["limited"],
            "evidence_refs": ["chunk-1"],
        },
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
    assert sections["compiled_knowledge"] == []


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
        if "/workspace?" in url:
            return _FakeResponse(
                {
                    "task": {"task_id": "task-1"},
                    "workspace": {"primary": {"headline": "done", "answer": "done", "mode": "static"}},
                    "executions": [{"execution_id": "runtime:task-1", "kind": "runtime"}],
                    "tool_calls": [{"tool_name": "web_search", "phase": "start"}],
                }
            )
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
    assert payload["workspace"]["primary"]["headline"] == "done"
    assert any(url.endswith("/api/tasks/task-1/workspace?tenant_id=tenant-1&workspace_id=ws-1") for url in requested_urls)
    assert not any(url.endswith("/api/tasks/task-1/result?tenant_id=tenant-1&workspace_id=ws-1") for url in requested_urls)


def test_collect_result_sections_preserves_task_lease_backend_value():
    payload = {
        "status": {
            "task_lease": {
                "owner_id": "host:pid",
                "lease_expires_at": "2026-04-05T00:00:00Z",
                "backend": "test_stub",
            }
        }
    }
    sections = collect_result_sections(payload)
    assert sections["task_lease"][0]["backend"] == "test_stub"


def test_collect_result_sections_prefers_workspace_evidence_and_knowledge():
    payload = {
        "workspace": {
            "evidence": {"evidence_refs": ["chunk-workspace"]},
            "knowledge": {
                "analysis_brief": {"question": "workspace q", "analysis_mode": "dynamic"},
                "knowledge_snapshot": {"rewritten_query": "workspace rq"},
                "compiled_knowledge": {"rule_specs": [{"source_text": "合同必须上传"}]},
            },
        },
        "response": {"evidence_refs": ["chunk-old"]},
    }
    sections = collect_result_sections(payload)
    assert sections["evidence_refs"] == ["chunk-workspace"]
    assert sections["analysis_brief"][0]["question"] == "workspace q"
    assert sections["knowledge_snapshot"][0]["rewritten_query"] == "workspace rq"
    assert sections["compiled_knowledge"][0]["rule_specs"][0]["source_text"] == "合同必须上传"


def test_collect_result_sections_extracts_parser_reports():
    payload = {
        "response": {
            "details": {
                "parser_reports": [
                    {
                        "file_name": "rule.pdf",
                        "parse_mode": "ocr+vision",
                        "parser_diagnostics": {"image_description_count": 2},
                    }
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
                "metadata": {"preferred_date_terms": ["biz_date"], "temporal_constraints": ["2024"]},
            }
        }
    }
    sections = collect_result_sections(payload)
    assert sections["knowledge_snapshot"][0]["rewritten_query"] == "报销 规则"
    assert sections["knowledge_snapshot"][0]["filters"]["year"] == "2024"
    assert sections["knowledge_snapshot"][0]["metadata"]["preferred_date_terms"] == ["biz_date"]


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


def test_collect_result_sections_extracts_compiled_knowledge():
    payload = {
        "response": {
            "details": {
                "compiled_knowledge": {
                    "rule_specs": [{"source_text": "合同必须上传"}],
                    "metric_specs": [{"metric_name": "审批时效"}],
                    "filter_specs": [{"field": "keyword", "operator": "contains", "value": "上海"}],
                    "spec_parse_errors": [{"spec_kind": "rule", "error_code": "antlr_rule_parse_failed"}],
                    "graph_compilation_summary": {
                        "candidate_count": 3,
                        "accepted_count": 2,
                        "rejected_count": 1,
                        "reject_reasons": {"missing_causal_marker": 1},
                    },
                }
            }
        }
    }
    sections = collect_result_sections(payload)
    assert sections["compiled_knowledge"][0]["rule_specs"][0]["source_text"] == "合同必须上传"
    assert sections["compiled_knowledge"][0]["graph_compilation_summary"]["accepted_count"] == 2


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
