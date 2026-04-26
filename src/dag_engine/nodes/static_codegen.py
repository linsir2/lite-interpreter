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
    """All artifacts required by the static coder node."""

    generated_code: str
    input_mounts: list[dict[str, Any]]
    execution_strategy: dict[str, Any]
    static_evidence_bundle: dict[str, Any]
    program_spec: dict[str, Any]
    repair_plan: dict[str, Any]
    generator_manifest: dict[str, Any]
    artifact_plan: dict[str, Any]
    verification_plan: dict[str, Any]


def prepare_static_codegen(
    *,
    exec_data: Any,
    state: dict[str, Any],
) -> PreparedStaticCodegen:
    """Recall reusable skills, assemble payloads, and render the code template."""

    payload, input_mounts = prepare_static_codegen_payload(exec_data=exec_data, state=state)
    dynamic_resume_overlay = ensure_dynamic_resume_overlay(
        {
            "continuation": str(
                state.get("dynamic_continuation")
                or getattr(getattr(exec_data, "dynamic", None), "continuation", None)
                or "finish"
            ),
            "next_static_steps": list(
                state.get("dynamic_next_static_steps")
                or getattr(getattr(exec_data, "dynamic", None), "next_static_steps", None)
                or []
            ),
            "evidence_refs": list(
                state.get("dynamic_evidence_refs")
                or getattr(getattr(exec_data, "dynamic", None), "evidence_refs", None)
                or []
            ),
            "suggested_static_actions": list(
                state.get("dynamic_suggested_static_actions")
                or getattr(getattr(exec_data, "dynamic", None), "suggested_static_actions", None)
                or []
            ),
            "open_questions": list(
                state.get("dynamic_open_questions")
                or getattr(getattr(exec_data, "dynamic", None), "open_questions", None)
                or []
            ),
        }
    )
    generated_code, execution_strategy, generator_manifest = build_static_generation_bundle(
        payload,
        dynamic_resume_overlay=dynamic_resume_overlay if dynamic_resume_overlay.next_static_steps else None,
        repair_plan=(
            state.get("repair_plan")
            or (exec_data.static.repair_plan.model_dump(mode="json") if getattr(exec_data.static, "repair_plan", None) else None)
        ),
    )
    return PreparedStaticCodegen(
        generated_code=generated_code,
        input_mounts=input_mounts,
        execution_strategy=execution_strategy.model_dump(mode="json"),
        static_evidence_bundle=(
            exec_data.static.static_evidence_bundle.model_dump(mode="json")
            if getattr(exec_data.static, "static_evidence_bundle", None)
            else {}
        ),
        program_spec=execution_strategy.program_spec.model_dump(mode="json") if execution_strategy.program_spec else {},
        repair_plan=execution_strategy.repair_plan.model_dump(mode="json") if execution_strategy.repair_plan else {},
        generator_manifest=generator_manifest.model_dump(mode="json"),
        artifact_plan=execution_strategy.artifact_plan.model_dump(mode="json"),
        verification_plan=execution_strategy.verification_plan.model_dump(mode="json"),
    )


def build_dataset_aware_code(payload: dict[str, Any]) -> str:
    generated_code, _strategy, _manifest = build_static_generation_bundle(payload)
    return generated_code
