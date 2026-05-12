"""Canonical task orchestrator for lite-interpreter."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from src.blackboard.execution_blackboard import execution_blackboard
from src.common import get_utc_now
from src.common.contracts import FailureType, TerminalVerdict
from src.common.control_plane import ensure_dynamic_resume_overlay
from src.common.task_lease_runtime import ensure_task_lease_owned
from src.dag_engine.dag_exceptions import TaskLeaseLostError

NodeMap = Mapping[str, Callable[[dict[str, Any]], dict[str, Any]]]
_WAITING_FOR_HUMAN_OUTPUT_KEYS = {"input_gap_report", "requested_inputs_json"}
_WAITING_FOR_HUMAN_OUTPUT_NAMES = {"input_gap_report.md", "requested_inputs.json"}



def _normalize_output_patch(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    if not isinstance(value, dict):
        return {}
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def _final_response_requires_human_follow_up(final_response: Any) -> bool:
    if not isinstance(final_response, dict):
        return False
    details = dict(final_response.get("details") or {})
    execution_strategy = dict(details.get("execution_strategy") or {})
    if str(execution_strategy.get("strategy_family") or "").strip() == "input_gap_report":
        return True
    for output in list(final_response.get("outputs") or []):
        if not isinstance(output, dict):
            continue
        artifact_key = str(output.get("artifact_key") or "").strip()
        name = str(output.get("name") or "").strip().lower()
        if artifact_key in _WAITING_FOR_HUMAN_OUTPUT_KEYS or name in _WAITING_FOR_HUMAN_OUTPUT_NAMES:
            return True
    return False


def _ensure_task_lease(state: Mapping[str, Any]) -> None:
    task_id = str(state.get("task_id", "")).strip()
    lease_owner_id = str(state.get("lease_owner_id", "")).strip()
    ensure_task_lease_owned(task_id, lease_owner_id)


def _run_checkpointed_node(
    *,
    node_name: str,
    node_fn: Callable[[dict[str, Any]], dict[str, Any]],
    state: dict[str, Any],
) -> dict[str, Any]:
    _ensure_task_lease(state)
    tenant_id = str(state.get("tenant_id", ""))
    task_id = str(state.get("task_id", ""))
    execution_data = execution_blackboard.read(tenant_id, task_id)

    if execution_data:
        checkpoint = dict((execution_data.control.node_checkpoints or {}).get(node_name) or {})
        if checkpoint.get("status") == "completed":
            normalized_patch = _normalize_output_patch(checkpoint.get("output_patch"))
            if normalized_patch:
                return normalized_patch

        checkpoints = dict(execution_data.control.node_checkpoints or {})
        previous = dict(checkpoints.get(node_name) or {})
        checkpoints[node_name] = {
            **previous,
            "status": "running",
            "started_at": get_utc_now().isoformat(),
            "attempt_count": int(previous.get("attempt_count", 0) or 0) + 1,
        }
        execution_data.control.node_checkpoints = checkpoints
        execution_blackboard.write(tenant_id, task_id, execution_data)
        execution_blackboard.persist(tenant_id, task_id)

    try:
        output_patch = node_fn(state) or {}
    except Exception as exc:
        if execution_data:
            latest = execution_blackboard.read(tenant_id, task_id) or execution_data
            checkpoints = dict(latest.control.node_checkpoints or {})
            previous = dict(checkpoints.get(node_name) or {})
            checkpoints[node_name] = {
                **previous,
                "status": "failed",
                "failed_at": get_utc_now().isoformat(),
                "error": str(exc),
            }
            latest.control.node_checkpoints = checkpoints
            execution_blackboard.write(tenant_id, task_id, latest)
            execution_blackboard.persist(tenant_id, task_id)
        raise

    normalized_output_patch = _normalize_output_patch(output_patch)
    if execution_data:
        latest = execution_blackboard.read(tenant_id, task_id) or execution_data
        checkpoints = dict(latest.control.node_checkpoints or {})
        previous = dict(checkpoints.get(node_name) or {})
        checkpoints[node_name] = {
            **previous,
            "status": "completed",
            "completed_at": get_utc_now().isoformat(),
            "error": None,
            "output_patch": normalized_output_patch,
        }
        latest.control.node_checkpoints = checkpoints
        execution_blackboard.write(tenant_id, task_id, latest)
        execution_blackboard.persist(tenant_id, task_id)
    return normalized_output_patch


def _run_evidence_compiler_if_needed(
    *,
    current_state: dict[str, Any],
    nodes: NodeMap,
    source: str,
) -> dict[str, Any]:
    """Compile raw static/dynamic evidence into existing material models once."""

    compiled_sources = [
        str(item).strip() for item in list(current_state.get("compiled_evidence_sources") or []) if str(item).strip()
    ]
    if source in compiled_sources:
        return current_state
    evidence_compiler_node = nodes.get("evidence_compiler")
    if evidence_compiler_node is None:
        return current_state
    current_state.update(
        _run_checkpointed_node(
            node_name=f"evidence_compiler:{source}",
            node_fn=evidence_compiler_node,
            state={**current_state, "evidence_compiler_source": source},
        )
    )
    current_state["compiled_evidence_sources"] = [*compiled_sources, source]
    current_state["evidence_material_compiled"] = True
    current_state["material_refresh_done"] = False
    return current_state


def _run_material_refresh_actions(
    *,
    current_state: dict[str, Any],
    nodes: NodeMap,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Refresh canonical material owners after evidence compilation.

    The compiler may append existing material-model records. This bounded
    refresh sends those materials through their canonical owners before coder.
    """

    if current_state.get("material_refresh_done"):
        return current_state, None
    refresh_actions = [
        str(item).strip() for item in list(current_state.get("material_refresh_actions") or []) if str(item).strip()
    ]
    if not refresh_actions:
        return current_state, None

    current_state["material_refresh_done"] = True
    for action in list(dict.fromkeys(refresh_actions)):
        if action == "data_inspector":
            current_state.update(
                _run_checkpointed_node(
                    node_name="data_inspector:material_refresh",
                    node_fn=nodes["data_inspector"],
                    state=current_state,
                )
            )
            if current_state.get("blocked"):
                summary_state = _run_checkpointed_node(
                    node_name="summarizer",
                    node_fn=nodes["summarizer"],
                    state=current_state,
                )
                verdict = TerminalVerdict.waiting(
                    sub_status="结构化数据探查失败，等待人工介入",
                    failure_type=FailureType.DATA_INSPECTION,
                    error_message=str(current_state.get("block_reason") or "data inspection blocked"),
                )
                return current_state, {
                    **current_state,
                    **summary_state,
                    **verdict.to_dict(),
                }
        elif action == "kag_retriever":
            current_state.update(
                _run_checkpointed_node(
                    node_name="kag_retriever:material_refresh",
                    node_fn=nodes["kag_retriever"],
                    state=current_state,
                )
            )
            if current_state.get("blocked"):
                summary_state = _run_checkpointed_node(
                    node_name="summarizer",
                    node_fn=nodes["summarizer"],
                    state=current_state,
                )
                verdict = TerminalVerdict.waiting(
                    sub_status="知识构建失败，等待人工介入",
                    failure_type=FailureType.KNOWLEDGE_INGESTION,
                    error_message=str(current_state.get("block_reason") or "knowledge ingestion blocked"),
                )
                return current_state, {
                    **current_state,
                    **summary_state,
                    **verdict.to_dict(),
                }
            current_state.update(
                _run_checkpointed_node(
                    node_name="context_builder:material_refresh",
                    node_fn=nodes["context_builder"],
                    state=current_state,
                )
            )
        elif action == "context_builder":
            current_state.update(
                _run_checkpointed_node(
                    node_name="context_builder:material_refresh",
                    node_fn=nodes["context_builder"],
                    state=current_state,
                )
            )
    if refresh_actions:
        current_state["force_analyst_after_material_refresh"] = True
    return current_state, None


_MAX_STATIC_ROUNDS = 3


def _execute_round(
    *,
    current_state: dict[str, Any],
    nodes: NodeMap,
    round_idx: int,
) -> dict[str, Any]:
    """Execute one round of the unified loop.

    Phases:
    0. Dynamic resume overlay (checked every round)
    1. Pre-analyst data prep (data_inspector, kag_retriever)
    2. Analyst → produces next_actions
    3. Execute analyst's actions (static_evidence, coder, dynamic)
    4. Auditor + intra-round debugger
    5. Executor → RoundOutput (or dynamic flag)
    6. Skill harvesting
    """
    r = str(round_idx)

    # ── Phase 0: Dynamic resume overlay ──
    resume_overlay = ensure_dynamic_resume_overlay(current_state.get("dynamic_resume_overlay") or {})
    is_dynamic_resume = resume_overlay.continuation == "resume_static"
    skip_steps: set[str] = set()
    overlay_actions: list[str] = []
    if is_dynamic_resume:
        current_state = _run_evidence_compiler_if_needed(
            current_state=current_state, nodes=nodes, source="dynamic_resume"
        )
        current_state, terminal_result = _run_material_refresh_actions(
            current_state=current_state, nodes=nodes,
        )
        if terminal_result is not None:
            return terminal_result
        skip_steps = set(resume_overlay.skip_static_steps)
        # Filter overlay's next_static_steps to valid resume targets
        for step in resume_overlay.next_static_steps or []:
            if step in ("analyst", "coder"):
                overlay_actions.append(step)

    # ── Phase 1: Pre-analyst data prep ──
    for action in current_state.get("next_actions", []):
        if action == "data_inspector" and action not in skip_steps:
            current_state.update(
                _run_checkpointed_node(
                    node_name="data_inspector", node_fn=nodes["data_inspector"], state=current_state
                )
            )
            if current_state.get("blocked"):
                summary_state = _run_checkpointed_node(
                    node_name="summarizer", node_fn=nodes["summarizer"], state=current_state
                )
                verdict = TerminalVerdict.waiting(
                    sub_status="结构化数据探查失败，等待人工介入",
                    failure_type=FailureType.DATA_INSPECTION,
                    error_message=str(current_state.get("block_reason") or "data inspection blocked"),
                )
                return {**current_state, **summary_state, **verdict.to_dict(), "terminal_status": "waiting_for_human"}
        elif action == "kag_retriever" and action not in skip_steps:
            current_state.update(
                _run_checkpointed_node(
                    node_name="kag_retriever", node_fn=nodes["kag_retriever"], state=current_state
                )
            )
            if current_state.get("blocked"):
                summary_state = _run_checkpointed_node(
                    node_name="summarizer", node_fn=nodes["summarizer"], state=current_state
                )
                verdict = TerminalVerdict.waiting(
                    sub_status="知识构建失败，等待人工介入",
                    failure_type=FailureType.KNOWLEDGE_INGESTION,
                    error_message=str(current_state.get("block_reason") or "knowledge ingestion blocked"),
                )
                return {**current_state, **summary_state, **verdict.to_dict(), "terminal_status": "waiting_for_human"}
            current_state.update(
                _run_checkpointed_node(
                    node_name="context_builder", node_fn=nodes["context_builder"], state=current_state
                )
            )

    # ── Phase 2: Analyst ──
    # During dynamic resume: analyst runs only if overlay requests it or forced by material_refresh.
    # In static mode: analyst always runs (it's the router).
    run_analyst = (
        not is_dynamic_resume
        or "analyst" in overlay_actions
        or current_state.get("force_analyst_after_material_refresh")
    )
    if "analyst" in skip_steps:
        run_analyst = False  # explicit skip overrides

    if run_analyst:
        analyst_result = _run_checkpointed_node(
            node_name=f"analyst:r{r}", node_fn=nodes["analyst"], state=current_state
        )
        current_state.update(analyst_result)
        new_actions = list(analyst_result.get("next_actions", []) or [])
    else:
        # Use overlay's filtered next_static_steps (pre-analyst steps already filtered out)
        new_actions = [a for a in overlay_actions if a != "analyst"]
    current_state["next_actions"] = new_actions

    # ── Phase 3: Execute analyst's actions ──
    has_coder = False
    has_dynamic = False
    for action in new_actions:
        if action == "static_evidence" and action not in skip_steps and not is_dynamic_resume:
            static_evidence_node = nodes.get("static_evidence")
            if static_evidence_node is not None:
                current_state.update(
                    _run_checkpointed_node(
                        node_name=f"static_evidence:r{r}", node_fn=static_evidence_node, state=current_state
                    )
                )
            if current_state.get("blocked"):
                summary_state = _run_checkpointed_node(
                    node_name="summarizer", node_fn=nodes["summarizer"], state=current_state
                )
                verdict = TerminalVerdict.waiting(
                    sub_status="静态取证失败，等待人工介入",
                    failure_type=FailureType.STATIC_EVIDENCE,
                    error_message=str(current_state.get("block_reason") or "static evidence blocked"),
                )
                return {**current_state, **summary_state, **verdict.to_dict(), "terminal_status": "waiting_for_human"}
            current_state = _run_evidence_compiler_if_needed(
                current_state=current_state, nodes=nodes, source="static_evidence"
            )
            current_state, terminal_result = _run_material_refresh_actions(
                current_state=current_state, nodes=nodes,
            )
            if terminal_result is not None:
                return terminal_result
            if current_state.get("force_analyst_after_material_refresh"):
                current_state.update(
                    _run_checkpointed_node(
                        node_name=f"analyst:r{r}:material_refresh", node_fn=nodes["analyst"], state=current_state
                    )
                )
                # After material refresh, coder runs (analyst re-ran, evidence is compiled)
                if "coder" not in skip_steps:
                    current_state.update(
                        _run_checkpointed_node(
                            node_name=f"coder:r{r}", node_fn=nodes["coder"], state=current_state
                        )
                    )
                    has_coder = True
        elif action == "coder" and action not in skip_steps:
            current_state.update(
                _run_checkpointed_node(
                    node_name=f"coder:r{r}", node_fn=nodes["coder"], state=current_state
                )
            )
            has_coder = True
        elif action == "dynamic":
            has_dynamic = True

    # During dynamic resume, if analyst ran and no coder was explicitly requested,
    # auto-run coder (preserving legacy contract: analyst implies coder on reentry)
    if is_dynamic_resume and "analyst" not in skip_steps and not has_coder and "coder" not in skip_steps:
        current_state.update(
            _run_checkpointed_node(
                node_name=f"coder:r{r}", node_fn=nodes["coder"], state=current_state
            )
        )
        has_coder = True

    # ── Phase 4: Auditor + intra-round debugger ──
    audit_state = _run_checkpointed_node(
        node_name=f"auditor:r{r}", node_fn=nodes["auditor"], state=current_state
    )
    current_state.update(audit_state)
    if audit_state.get("next_actions") == ["debugger"]:
        current_state.update(
            _run_checkpointed_node(
                node_name=f"debugger:r{r}", node_fn=nodes["debugger"], state=current_state
            )
        )
        current_state.update(
            _run_checkpointed_node(
                node_name=f"auditor:r{r}:post_debug", node_fn=nodes["auditor"], state=current_state
            )
        )

    # ── Phase 5: Executor → RoundOutput (or dynamic flag) ──
    if has_coder and not has_dynamic:
        executor_state = _run_checkpointed_node(
            node_name=f"executor:r{r}", node_fn=nodes["executor"], state=current_state
        )
        current_state.update(executor_state)
        round_output = executor_state.get("round_output", {})

        # Intra-round debugger (post-executor verification failure)
        if round_output.get("termination_reason") == "verification_failed":
            current_state.update(
                _run_checkpointed_node(
                    node_name=f"debugger:r{r}:post_exec", node_fn=nodes["debugger"], state=current_state
                )
            )
            current_state.update(
                _run_checkpointed_node(
                    node_name=f"auditor:r{r}:post_exec", node_fn=nodes["auditor"], state=current_state
                )
            )
            executor_state = _run_checkpointed_node(
                node_name=f"executor:r{r}:retry", node_fn=nodes["executor"], state=current_state
            )
            current_state.update(executor_state)
            round_output = executor_state.get("round_output", {})
    elif has_dynamic:
        round_output = {"round_index": round_idx, "additional_rounds": 0, "requires_dynamic": True}
    else:
        round_output = {"round_index": round_idx, "additional_rounds": 0, "requires_dynamic": False}

    # ── Phase 6: Skill harvesting ──
    harvested_state = _run_checkpointed_node(
        node_name=f"skill_harvester:r{r}", node_fn=nodes["skill_harvester"], state=current_state
    )
    current_state.update(harvested_state)

    return {**current_state, "round_output": round_output}


def execute_task_flow(
    state: dict[str, Any],
    *,
    nodes: NodeMap,
) -> dict[str, Any]:
    """Unified round loop — no more static_flow / dynamic_flow branching.

    Every task enters the same loop. Analyst drives routing via next_actions;
    RoundOutput from executor determines continuation or termination.
    """
    try:
        for round_idx in range(_MAX_STATIC_ROUNDS):
            state["round_index"] = round_idx
            result = _execute_round(current_state=state, nodes=nodes, round_idx=round_idx)
            state.update(result)

            if result.get("terminal_status"):
                return {**state, **result}

            round_output = result.get("round_output") or {}
            if round_output.get("additional_rounds", 0) > 0:
                continue
            if round_output.get("requires_dynamic"):
                dynamic_result = _run_checkpointed_node(
                    node_name="dynamic", node_fn=nodes["dynamic"], state=state
                )
                state.update(dynamic_result)
                if state.get("dynamic_continuation") == "resume_static":
                    continue
                break
            break

        # Terminal: summarizer + verdict
        summary_state = _run_checkpointed_node(
            node_name="summarizer", node_fn=nodes["summarizer"], state=state
        )
        state.update(summary_state)
        dynamic_status = str(state.get("dynamic_status") or "")
        execution_record = state.get("execution_record")
        final_response = state.get("final_response") or {}

        if dynamic_status == "denied":
            verdict = TerminalVerdict.waiting(
                sub_status="动态任务被治理策略阻断，等待人工介入",
                failure_type=FailureType.DYNAMIC_GOVERNANCE,
                error_message=str(state.get("dynamic_summary") or "dynamic swarm denied by governance policy"),
            )
        elif dynamic_status == "unavailable":
            verdict = TerminalVerdict.fail(
                sub_status="动态任务链路未能完成",
                failure_type=FailureType.DYNAMIC_RUNTIME,
                error_message=str(state.get("dynamic_summary") or "dynamic swarm unavailable"),
            )
        elif execution_record and execution_record.get("success") and _final_response_requires_human_follow_up(final_response):
            verdict = TerminalVerdict.waiting(
                sub_status="已生成输入缺口报告，等待人工补充资料",
                failure_type=FailureType.NEED_MORE_INPUTS,
                error_message="input gap report generated",
            )
        elif execution_record and execution_record.get("success"):
            verdict = TerminalVerdict.ok(sub_status="任务执行完成")
        else:
            verdict = TerminalVerdict.fail(
                sub_status="任务执行失败",
                failure_type=FailureType.EXECUTING,
                error_message=str(
                    execution_record.get("error", "sandbox execution failed")
                    if execution_record
                    else "sandbox execution result missing"
                ),
            )
        return {**state, **verdict.to_dict()}
    except TaskLeaseLostError as exc:
        verdict = TerminalVerdict.fail(
            sub_status="任务租约已丢失，本地执行已停止",
            failure_type=FailureType.LEASE_LOST,
            error_message=str(exc),
        )
        return {**state, **verdict.to_dict()}
