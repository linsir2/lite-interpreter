"""Deterministic evaluation runner for data-analysis behavior."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.blackboard import ExecutionData, execution_blackboard, global_blackboard
from src.dag_engine.nodes.context_builder_node import context_builder_node
from src.dag_engine.nodes.router_node import router_node

from .cases import SEED_EVAL_CASES, EvalCase


@dataclass(frozen=True)
class EvalResult:
    case_id: str
    description: str
    passed: bool
    checks: dict[str, bool]
    observed: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def _prepare_execution(case: EvalCase) -> tuple[str, str]:
    tenant_id = f"eval:{case.case_id}"
    task_id = global_blackboard.create_task(tenant_id, "eval_ws", case.query)
    execution_blackboard.write(
        tenant_id,
        task_id,
        ExecutionData(
            tenant_id=tenant_id,
            task_id=task_id,
            workspace_id="eval_ws",
            inputs={
                "structured_datasets": list(case.structured_datasets),
                "business_documents": list(case.business_documents),
            },
        ),
    )
    return tenant_id, task_id


def run_case(case: EvalCase) -> EvalResult:
    tenant_id, task_id = _prepare_execution(case)
    state = {
        "tenant_id": tenant_id,
        "task_id": task_id,
        "workspace_id": "eval_ws",
        "input_query": case.query,
        "allowed_tools": list(case.allowed_tools),
    }
    route_result = router_node(state)
    intent_metadata = dict((route_result.get("execution_intent") or {}).get("metadata") or {})
    observed: dict[str, Any] = {
        "analysis_mode": intent_metadata.get("analysis_mode"),
        "next_actions": list(route_result.get("next_actions") or []),
        "effective_model_alias": intent_metadata.get("effective_model_alias"),
        "known_gaps": list(intent_metadata.get("known_gaps") or []),
    }
    checks = {
        "analysis_mode": observed["analysis_mode"] == case.expected_analysis_mode,
        "route": case.expected_route in observed["next_actions"],
    }
    if case.expected_known_gap_substrings:
        checks["known_gaps"] = all(
            any(expected in observed_gap for observed_gap in observed["known_gaps"])
            for expected in case.expected_known_gap_substrings
        )

    if case.knowledge_hits:
        context_state = {
            **state,
            "knowledge_snapshot": {
                "hits": list(case.knowledge_hits),
                "evidence_refs": [item["chunk_id"] for item in case.knowledge_hits if item.get("chunk_id")],
            },
            "raw_retrieved_candidates": list(case.knowledge_hits),
        }
        context_result = context_builder_node(context_state)
        brief = dict(context_result.get("analysis_brief") or {})
        snapshot = dict(context_result.get("knowledge_snapshot") or {})
        observed["analysis_brief"] = brief
        observed["evidence_refs"] = list(snapshot.get("evidence_refs") or [])
        observed["pinned_evidence_refs"] = list((snapshot.get("metadata") or {}).get("pinned_evidence_refs") or [])
        checks["evidence_refs"] = tuple(observed["evidence_refs"]) == case.expected_evidence_refs
        checks["pinned_evidence_refs"] = tuple(observed["pinned_evidence_refs"]) == case.expected_evidence_refs
        if case.expected_known_gap_substrings:
            checks["brief_known_gaps"] = all(
                any(expected in observed_gap for observed_gap in list(brief.get("known_gaps") or []))
                for expected in case.expected_known_gap_substrings
            )
        if case.expected_dataset_summary_min:
            checks["dataset_summaries"] = len(list(brief.get("dataset_summaries") or [])) >= case.expected_dataset_summary_min

    return EvalResult(
        case_id=case.case_id,
        description=case.description,
        passed=all(checks.values()),
        checks=checks,
        observed=observed,
    )


def run_seed_evals(*, output_dir: str | Path | None = None) -> dict[str, Any]:
    previous_disable = os.getenv("LITE_INTERPRETER_DISABLE_LITELLM_TOKEN_COUNTER")
    os.environ["LITE_INTERPRETER_DISABLE_LITELLM_TOKEN_COUNTER"] = "1"
    try:
        results = [run_case(case) for case in SEED_EVAL_CASES]
    finally:
        if previous_disable is None:
            os.environ.pop("LITE_INTERPRETER_DISABLE_LITELLM_TOKEN_COUNTER", None)
        else:
            os.environ["LITE_INTERPRETER_DISABLE_LITELLM_TOKEN_COUNTER"] = previous_disable
    payload = {
        "summary": {
            "total": len(results),
            "passed": sum(1 for item in results if item.passed),
            "failed": sum(1 for item in results if not item.passed),
        },
        "results": [result.to_payload() for result in results],
    }
    if output_dir is not None:
        target = Path(output_dir)
        target.mkdir(parents=True, exist_ok=True)
        (target / "seed_eval_report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_lines = [
            "# lite-interpreter deterministic eval report",
            "",
            f"- total: {payload['summary']['total']}",
            f"- passed: {payload['summary']['passed']}",
            f"- failed: {payload['summary']['failed']}",
            "",
        ]
        for item in results:
            markdown_lines.append(f"## {item.case_id}")
            markdown_lines.append(f"- passed: {item.passed}")
            markdown_lines.append(f"- checks: {json.dumps(item.checks, ensure_ascii=False)}")
            markdown_lines.append(f"- observed: {json.dumps(item.observed, ensure_ascii=False)}")
            markdown_lines.append("")
        (target / "seed_eval_report.md").write_text("\n".join(markdown_lines), encoding="utf-8")
    return payload
