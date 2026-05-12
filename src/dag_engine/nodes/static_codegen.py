"""Helpers for static coder payload assembly and code generation.

Primary path: LLM-driven codegen via build_codegen_prompt() + LiteLLM.
Fallback path: template compiler via build_static_generation_bundle().
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.common import get_logger
from src.common.contracts import ExecutionStrategy
from src.common.control_plane import ensure_generator_manifest
from src.compiler.code_compiler import build_codegen_prompt
from src.dag_engine.nodes.static_codegen_payload import (
    prepare_static_codegen_payload,
)
from src.dag_engine.nodes.static_generation_registry import build_static_generation_bundle

logger = get_logger(__name__)

# LLM call failures we expect and can recover from via template fallback.
# Programming errors (TypeError, AttributeError, etc.) must NOT be silenced.
_RECOVERABLE_EXCEPTIONS = (
    ImportError,          # litellm not installed
    ModuleNotFoundError,  # litellm not installed
    ConnectionError,      # network failure
    TimeoutError,         # LLM timeout
    OSError,              # file/network I/O
)


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


def _extract_code_from_llm_response(response: str) -> str:
    """Extract Python code from an LLM response that may use markdown fences."""
    match = re.search(r"```python\s*\n(.*?)```", response, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"```\s*\n(.*?)```", response, re.DOTALL)
    if match:
        return match.group(1).strip()
    return response.strip()


def _validate_code(code: str) -> None:
    """Raise ValueError if code is empty or syntactically invalid Python."""
    if not code.strip():
        raise ValueError("LLM returned empty code")
    compile(code, "<llm_codegen>", "exec")


def _select_codegen_model(network_mode) -> str:
    """Select the appropriate LLM model alias from network mode.

    No network or bounded queries can use a fast model;
    open-ended exploration benefits from a reasoning model.
    """
    from src.common.contracts import NetworkMode

    nm = NetworkMode(network_mode) if isinstance(network_mode, str) else network_mode
    if nm in {NetworkMode.NONE, NetworkMode.BOUNDED}:
        return "fast_model"
    return "reasoning_model"


def prepare_static_codegen(
    *,
    exec_data: Any,
    state: dict[str, Any],
) -> PreparedStaticCodegen:
    """Recall reusable skills, assemble payloads, generate code.

    Primary path: LLM-driven codegen consuming the analyst's frozen
    ExecutionStrategy.  Generated code passes a syntax check before
    acceptance; on any recoverable failure the template compiler
    takes over as fallback.

    Non-recoverable errors (programming bugs) propagate to the caller.
    """

    payload, input_mounts = prepare_static_codegen_payload(exec_data=exec_data, state=state)
    execution_strategy: ExecutionStrategy = exec_data.static.execution_strategy
    approved_skills = list(payload.get("approved_skills") or [])

    # Primary path: LLM codegen
    try:
        prompt = build_codegen_prompt(
            execution_strategy=execution_strategy,
            skills=approved_skills,
            payload=payload,
        )
        from src.common.llm_client import LiteLLMClient

        model_alias = _select_codegen_model(execution_strategy.network_mode)
        raw_response = LiteLLMClient.chat(
            alias=model_alias,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Generate the Python code now. Output only the Python code, no explanations."},
            ],
            max_tokens=8192,
        )
        generated_code = _extract_code_from_llm_response(raw_response)
        _validate_code(generated_code)

        expected_keys = [
            spec.artifact_key
            for spec in [
                *execution_strategy.artifact_plan.required_artifacts,
                *execution_strategy.artifact_plan.optional_artifacts,
            ]
        ]
        generator_manifest = ensure_generator_manifest(
            generator_id=execution_strategy.generator_id,
            strategy_family=execution_strategy.strategy_family,
            renderer_id="llm_codegen",
            fallback_used=False,
            expected_artifact_keys=expected_keys,
            metadata={
                "analysis_mode": execution_strategy.analysis_mode,
                "research_mode": execution_strategy.research_mode,
            },
        )
        program_spec = None
    except _RECOVERABLE_EXCEPTIONS:
        logger.warning("LLM codegen unavailable, falling back to template compiler", exc_info=True)
        generated_code, generator_manifest, program_spec = build_static_generation_bundle(
            payload,
            execution_strategy=execution_strategy,
        )
    except ValueError:
        logger.warning("LLM codegen produced invalid code, falling back to template compiler", exc_info=True)
        generated_code, generator_manifest, program_spec = build_static_generation_bundle(
            payload,
            execution_strategy=execution_strategy,
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
            exec_data.static.repair_plan.model_dump(mode="json")
            if getattr(exec_data.static, "repair_plan", None)
            else None
        ) or {},
        generator_manifest=generator_manifest.model_dump(mode="json"),
    )


def build_dataset_aware_code(
    payload: dict[str, Any],
    *,
    execution_strategy: ExecutionStrategy,
) -> str:
    """Convenience wrapper for tests — always uses the template fallback path."""
    generated_code, *_ = build_static_generation_bundle(
        payload,
        execution_strategy=execution_strategy,
    )
    return generated_code
