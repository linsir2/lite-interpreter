"""Helpers for static coder payload assembly and code template rendering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.common.control_plane import ensure_dynamic_resume_overlay
from src.dag_engine.nodes.static_codegen_payload import (
    prepare_static_codegen_payload,
)
from src.dag_engine.nodes.static_generation_registry import build_static_generation_bundle


@dataclass(frozen=True)
class PreparedStaticCodegen:
    """Artifacts required by the static coder node.

    execution_strategy is NOT included — it is owned by the analyst and
    read from blackboard, never overwritten by coder/debugger.
    """

    generated_code: str
    input_mounts: list[dict[str, Any]]
    static_evidence_bundle: dict[str, Any]
    program_spec: dict[str, Any]
    repair_plan: dict[str, Any]
    generator_manifest: dict[str, Any]


def prepare_static_codegen(
    *,
    exec_data: Any,
    state: dict[str, Any],
) -> PreparedStaticCodegen:
    """Recall reusable skills, assemble payloads, and render the code template."""

    payload, input_mounts = prepare_static_codegen_payload(exec_data=exec_data, state=state)
    persisted_overlay = getattr(getattr(exec_data, "dynamic", None), "resume_overlay", None)
    execution_metadata = dict((state.get("execution_intent") or {}).get("metadata") or {})
    overlay_source = (
        state.get("dynamic_resume_overlay")
        or (persisted_overlay.model_dump(mode="json") if persisted_overlay else None)
        or {
            "continuation": str(
                state.get("dynamic_continuation")
                or getattr(getattr(exec_data, "dynamic", None), "continuation", None)
                or "finish"
            ),
            "next_static_steps": list(
                state.get("dynamic_next_static_steps")
                or execution_metadata.get("next_static_steps")
                or getattr(getattr(exec_data, "dynamic", None), "next_static_steps", None)
                or []
            ),
            "skip_static_steps": list(execution_metadata.get("skip_static_steps") or []),
            "evidence_refs": list(
                state.get("dynamic_evidence_refs")
                or execution_metadata.get("evidence_refs")
                or getattr(getattr(exec_data, "dynamic", None), "evidence_refs", None)
                or []
            ),
            "suggested_static_actions": list(
                state.get("dynamic_suggested_static_actions")
                or execution_metadata.get("suggested_static_actions")
                or getattr(getattr(exec_data, "dynamic", None), "suggested_static_actions", None)
                or []
            ),
            "recommended_static_action": str(execution_metadata.get("recommended_static_action") or ""),
            "open_questions": list(
                state.get("dynamic_open_questions")
                or execution_metadata.get("open_questions")
                or getattr(getattr(exec_data, "dynamic", None), "open_questions", None)
                or []
            ),
            "strategy_family": execution_metadata.get("strategy_family"),
        }
    )
    dynamic_resume_overlay = ensure_dynamic_resume_overlay(
        overlay_source,
        skip_static_steps=list(execution_metadata.get("skip_static_steps") or []),
        evidence_refs=list(execution_metadata.get("evidence_refs") or []),
        suggested_static_actions=list(execution_metadata.get("suggested_static_actions") or []),
        recommended_static_action=str(execution_metadata.get("recommended_static_action") or ""),
        open_questions=list(execution_metadata.get("open_questions") or []),
        strategy_family=execution_metadata.get("strategy_family"),
    )
    generated_code, generator_manifest, program_spec = build_static_generation_bundle(
        payload,
        dynamic_resume_overlay=dynamic_resume_overlay if dynamic_resume_overlay.continuation == "resume_static" else None,
        repair_plan=(
            state.get("repair_plan")
            or (exec_data.static.repair_plan.model_dump(mode="json") if getattr(exec_data.static, "repair_plan", None) else None)
        ),
    )
    return PreparedStaticCodegen(
        generated_code=generated_code,
        input_mounts=input_mounts,
        static_evidence_bundle=(
            exec_data.static.static_evidence_bundle.model_dump(mode="json")
            if getattr(exec_data.static, "static_evidence_bundle", None)
            else {}
        ),
        program_spec=program_spec.model_dump(mode="json") if program_spec else {},
        repair_plan=(
            state.get("repair_plan")
            or (exec_data.static.repair_plan.model_dump(mode="json") if getattr(exec_data.static, "repair_plan", None) else None)
        ) or {},
        generator_manifest=generator_manifest.model_dump(mode="json"),
    )


def build_dataset_aware_code(payload: dict[str, Any]) -> str:
    generated_code, *_ = build_static_generation_bundle(payload)
    return generated_code
