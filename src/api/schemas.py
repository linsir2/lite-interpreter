"""Shared API schema helpers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, StrictStr, ValidationError, model_validator
from starlette.responses import JSONResponse


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


class AppPaginationQuery(BaseModel):
    """Shared pagination query model for app-facing list endpoints."""

    model_config = ConfigDict(extra="forbid")

    page: int = 1
    pageSize: int = 20

    @model_validator(mode="after")
    def _normalize(self) -> AppPaginationQuery:
        self.page = max(1, int(self.page))
        self.pageSize = max(1, min(100, int(self.pageSize)))
        return self


def api_error_payload(code: str, message: str, *, details: dict[str, Any] | list[Any] | None = None) -> dict[str, Any]:
    return {
        "error": {
            "code": str(code or "UNKNOWN_ERROR").strip() or "UNKNOWN_ERROR",
            "message": str(message or "Request failed.").strip() or "Request failed.",
            "details": details or {},
        }
    }


def api_error_response(
    code: str,
    message: str,
    *,
    status_code: int,
    details: dict[str, Any] | list[Any] | None = None,
) -> JSONResponse:
    return JSONResponse(api_error_payload(code, message, details=details), status_code=status_code)


def validation_error_details(exc: ValidationError) -> list[dict[str, Any]]:
    """Return stable validation details without wrapping them in an error envelope."""

    normalized_details: list[dict[str, Any]] = []
    for detail in exc.errors(include_url=False):
        ctx = detail.get("ctx")
        if isinstance(ctx, dict):
            detail = {
                **detail,
                "ctx": {str(key): str(value) for key, value in ctx.items()},
            }
        normalized_details.append(detail)
    return normalized_details


def validation_error_payload(exc: ValidationError) -> dict[str, Any]:
    """Return a stable error payload for strict request validation failures."""
    return {
        "error": "validation_error",
        "details": validation_error_details(exc),
    }
