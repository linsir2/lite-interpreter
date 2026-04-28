"""Authentication helpers and middleware for API routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config.settings import API_AUTH_REQUIRED, API_AUTH_TOKENS
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.api.schemas import api_error_response


@dataclass(frozen=True)
class AuthGrant:
    tenant_id: str
    workspace_id: str


@dataclass(frozen=True)
class AuthContext:
    token: str
    subject: str
    tenant_id: str
    workspace_id: str
    role: str = "operator"
    grants: tuple[AuthGrant, ...] = ()
    auth_type: str = "token"


ROLE_HIERARCHY = {  # 用户权限
    "viewer": 10,
    "operator": 20,
    "admin": 30,
}

def _normalize_grants(raw: Any, *, tenant_id: str = "", workspace_id: str = "") -> tuple[AuthGrant, ...]:
    grants: list[AuthGrant] = []
    if tenant_id and workspace_id:
        grants.append(AuthGrant(tenant_id=tenant_id, workspace_id=workspace_id))
    for item in list(raw or []):
        if not isinstance(item, dict):
            continue
        grant_tenant = str(item.get("tenant_id") or "").strip()
        grant_workspace = str(item.get("workspace_id") or "").strip()
        if not grant_tenant or not grant_workspace:
            continue
        grant = AuthGrant(tenant_id=grant_tenant, workspace_id=grant_workspace)
        if grant not in grants:
            grants.append(grant)
    return tuple(grants)


def _normalize_token_store() -> dict[str, AuthContext]:
    contexts: dict[str, AuthContext] = {}
    for token, raw in dict(API_AUTH_TOKENS or {}).items():
        normalized_token = str(token or "").strip()
        if not normalized_token:
            continue
        if isinstance(raw, dict):
            subject = str(raw.get("subject") or raw.get("user_id") or normalized_token).strip() or normalized_token
            tenant_id = str(raw.get("tenant_id") or "").strip()
            workspace_id = str(raw.get("workspace_id") or "").strip()
            role = str(raw.get("role") or "operator").strip().lower() or "operator"
            grants = _normalize_grants(raw.get("grants"), tenant_id=tenant_id, workspace_id=workspace_id)
        else:
            subject = normalized_token
            tenant_id = ""
            workspace_id = ""
            role = "operator"
            grants = ()
        if role not in ROLE_HIERARCHY:
            role = "operator"
        if not grants:
            continue
        contexts[normalized_token] = AuthContext(
            token=normalized_token,
            subject=subject,
            tenant_id=grants[0].tenant_id,
            workspace_id=grants[0].workspace_id,
            role=role,
            grants=grants,
            auth_type="token",
        )
    return contexts

def auth_enabled() -> bool:
    return bool(API_AUTH_REQUIRED or _normalize_token_store())


def request_bearer_token(request: Request) -> str:
    authorization = str(request.headers.get("authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    header_token = str(request.headers.get("x-api-key") or "").strip()
    if header_token:
        return header_token
    return ""


def authenticate_request(request: Request) -> AuthContext | JSONResponse | None:
    token_store = _normalize_token_store()
    enabled = bool(API_AUTH_REQUIRED or token_store)
    if not enabled:
        return None
    if not token_store:
        return api_error_response(
            "AUTH_MISCONFIGURED",
            "API authentication is misconfigured.",
            status_code=503,
        )
    token = request_bearer_token(request)
    if not token:
        return api_error_response("AUTH_REQUIRED", "Authentication required.", status_code=401)
    auth_context = token_store.get(token)
    if auth_context is None:
        return api_error_response("INVALID_TOKEN", "Invalid API token.", status_code=403)
    return auth_context


def request_auth_context(request: Request) -> AuthContext | None:
    state = getattr(request, "state", None)
    if state is None:
        return None
    return getattr(state, "auth_context", None)


def role_allows(current_role: str, minimum_role: str) -> bool:
    current_rank = ROLE_HIERARCHY.get(str(current_role or "").strip().lower(), -1)
    minimum_rank = ROLE_HIERARCHY.get(str(minimum_role or "").strip().lower(), -1)
    return current_rank >= minimum_rank >= 0


def require_request_role(request: Request, minimum_role: str) -> JSONResponse | None:
    state = getattr(request, "state", None)
    auth_context = request_auth_context(request)
    if auth_context is None and (state is None or not getattr(state, "auth_checked", False)):
        return None
    if auth_context is None:
        return api_error_response("AUTH_REQUIRED", "Authentication required.", status_code=401)
    if role_allows(auth_context.role, minimum_role):
        return None
    return api_error_response(
        "INSUFFICIENT_ROLE",
        "The current role does not have access to this endpoint.",
        status_code=403,
        details={
            "requiredRole": minimum_role,
            "currentRole": auth_context.role,
        },
    )


def auth_context_allows_scope(auth_context: AuthContext | None, tenant_id: str, workspace_id: str) -> bool:
    if auth_context is None:
        return True
    if not auth_context.grants:
        return auth_context.tenant_id == tenant_id and auth_context.workspace_id == workspace_id
    return any(grant.tenant_id == tenant_id and grant.workspace_id == workspace_id for grant in auth_context.grants)


def request_skips_auth(request: Request) -> bool:
    path = request.url.path
    if path == "/health":
        return True
    if request.method.upper() == "OPTIONS" and request.headers.get("origin") and request.headers.get("access-control-request-method"):
        return True
    return not path.startswith("/api/")


class ApiAuthMiddleware(BaseHTTPMiddleware):
    """Optional API token authentication with request-scoped auth context."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request_skips_auth(request):
            request.state.auth_context = None
            request.state.auth_checked = False
            return await call_next(request)
        authenticated = authenticate_request(request)
        if isinstance(authenticated, JSONResponse):
            return authenticated
        if authenticated is None:
            # Auth is disabled - mark as not checked so require_request_role allows
            request.state.auth_context = None
            request.state.auth_checked = False
        else:
            request.state.auth_context = authenticated
            request.state.auth_checked = True
        return await call_next(request)
