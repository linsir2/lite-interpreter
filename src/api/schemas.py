"""Shared API schema helpers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, StrictStr, ValidationError, model_validator


class PolicyUpdateRequest(BaseModel):
    """Strict request model for harness policy updates."""

    model_config = ConfigDict(extra="forbid")

    policy: dict[str, Any] | None = None
    yaml: StrictStr | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> PolicyUpdateRequest:
        has_policy = self.policy is not None
        has_yaml = self.yaml is not None and bool(self.yaml.strip())
        if has_policy == has_yaml:
            raise ValueError("exactly one of `policy` or `yaml` must be provided")
        if self.yaml is not None:
            self.yaml = self.yaml.strip()
        return self

def validation_error_payload(exc: ValidationError) -> dict[str, Any]:
    """Return a stable error payload for strict request validation failures."""

    normalized_details = []
    for detail in exc.errors(include_url=False):
        ctx = detail.get("ctx")
        if isinstance(ctx, dict):
            detail = {
                **detail,
                "ctx": {str(key): str(value) for key, value in ctx.items()},
            }
        normalized_details.append(detail)
    return {
        "error": "validation_error",
        "details": normalized_details,
    }

