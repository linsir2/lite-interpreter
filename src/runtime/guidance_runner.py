"""Real-LLM Guidance runner for constrained leaf programs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.common.llm_client import LiteLLMClient


@dataclass(frozen=True)
class GuidanceProgramResult:
    program_id: str
    status: str
    payload: dict[str, Any]
    degraded: bool
    degrade_reason: str
    backend: str


def _guidance_available() -> bool:
    try:
        import guidance  # noqa: F401

        return True
    except Exception:
        return False


def probe_guidance_runtime(alias: str = "reasoning_model") -> dict[str, Any]:
    llm_status = LiteLLMClient.probe_alias(alias, live=False)
    return {
        "package_importable": _guidance_available(),
        "alias": alias,
        "model": llm_status.model,
        "provider": llm_status.provider,
        "api_key_present": llm_status.api_key_present,
        "configured": llm_status.configured,
        "supports_roles": True,
        "supports_select": False,
        "supports_regex": False,
    }


def _validate_route_payload(payload: dict[str, Any], route_candidates: list[str]) -> dict[str, Any]:
    final_mode = str(payload.get("final_mode") or "").strip()
    if final_mode not in route_candidates:
        raise ValueError(f"unexpected candidate `{final_mode}`")
    confidence = float(payload.get("confidence") or 0.0)
    rationale = str(payload.get("rationale") or "").strip()
    return {
        "final_mode": final_mode,
        "confidence": max(0.0, min(confidence or 0.0, 0.99)),
        "rationale": rationale,
    }


def _run_guidance_route_selection(query: str, route_candidates: list[str], model_alias: str) -> dict[str, Any]:
    import guidance

    config = LiteLLMClient.get_model_config(model_alias)
    model_name = str(config.params.get("model") or model_alias)
    if "/" in model_name:
        model_name = model_name.split("/", 1)[1]
    api_key = str(config.params.get("api_key") or "").strip()
    base_url = str(config.params.get("api_base") or "").strip()
    if not api_key:
        raise ValueError("missing_api_key")
    model = guidance.models.OpenAI(model=model_name, api_key=api_key, base_url=base_url, echo=False)
    with guidance.system():
        model += "Return only JSON."
    with guidance.user():
        model += (
            "Choose exactly one route from "
            + json.dumps(route_candidates, ensure_ascii=False)
            + " for the given query, then return a JSON object with keys "
            + '"final_mode", "confidence", "rationale". Query: '
            + query
        )
    with guidance.assistant():
        model += guidance.gen(name="payload", max_tokens=120)
    return json.loads(str(model["payload"]).strip())


def _run_litellm_route_selection(query: str, route_candidates: list[str], model_alias: str) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": "Return JSON only."},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "query": query,
                    "candidate_routes": route_candidates,
                    "required_keys": ["final_mode", "confidence", "rationale"],
                },
                ensure_ascii=False,
            ),
        },
    ]
    text = LiteLLMClient.chat(model_alias, messages, max_tokens=120)
    stripped = str(text or "").strip()
    if stripped.startswith("```"):
        stripped = "\n".join(line for line in stripped.splitlines() if not line.strip().startswith("```")).strip()
    return json.loads(stripped)


def run_route_selection(query: str, route_candidates: list[str], model_alias: str) -> GuidanceProgramResult:
    if not route_candidates:
        return GuidanceProgramResult(
            program_id="route_selection",
            status="error",
            payload={},
            degraded=True,
            degrade_reason="empty_route_candidates",
            backend="none",
        )
    if _guidance_available():
        try:
            payload = _validate_route_payload(_run_guidance_route_selection(query, route_candidates, model_alias), route_candidates)
            return GuidanceProgramResult(
                program_id="route_selection",
                status="ok",
                payload=payload,
                degraded=False,
                degrade_reason="",
                backend="guidance_openai",
            )
        except Exception as exc:
            guidance_error = str(exc)
    else:
        guidance_error = "guidance_unavailable"

    payload = _validate_route_payload(_run_litellm_route_selection(query, route_candidates, model_alias), route_candidates)
    return GuidanceProgramResult(
        program_id="route_selection",
        status="ok",
        payload=payload,
        degraded=True,
        degrade_reason=f"guidance_fallback:{guidance_error}",
        backend="litellm_json",
    )
