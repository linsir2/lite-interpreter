"""Helpers for static coder payload assembly and code template rendering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.dag_engine.nodes.static_codegen_payload import (
    ensure_static_codegen_payload,
    prepare_static_codegen_payload,
)
from src.dag_engine.nodes.static_codegen_renderer import render_dataset_aware_code


@dataclass(frozen=True)
class PreparedStaticCodegen:
    """All artifacts required by the static coder node."""

    generated_code: str
    input_mounts: list[dict[str, Any]]


def prepare_static_codegen(
    *,
    exec_data: Any,
    state: dict[str, Any],
) -> PreparedStaticCodegen:
    """Recall reusable skills, assemble payloads, and render the code template."""

    payload, input_mounts = prepare_static_codegen_payload(exec_data=exec_data, state=state)
    return PreparedStaticCodegen(
        generated_code=build_dataset_aware_code(payload),
        input_mounts=input_mounts,
    )


def build_dataset_aware_code(payload: dict[str, Any]) -> str:
    return render_dataset_aware_code(ensure_static_codegen_payload(payload))
