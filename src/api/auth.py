"""Authentication helpers and middleware for API routes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from config.settings import (
    API_AUTH_REQUIRED,
    API_AUTH_TOKENS,
    API_AUTH_USERS,
    API_SESSION_SECRET,
    API_SESSION_TTL_SECONDS,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


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


def _urlsafe_b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _urlsafe_b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(f"{data}{padding}".encode("ascii"))


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


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


def _normalize_user_store() -> dict[str, dict[str, Any]]:
    users: dict[str, dict[str, Any]] = {}
    for username, raw in dict(API_AUTH_USERS or {}).items():
        normalized_username = str(username or "").strip()
        if not normalized_username or not isinstance(raw, dict):
            continue
        password = str(raw.get("password") or "").strip()
        role = str(raw.get("role") or "viewer").strip().lower() or "viewer"
        grants = _normalize_grants(raw.get("grants"))
        if not password or role not in ROLE_HIERARCHY or not grants:
            continue
        users[normalized_username] = {
            "password": password,
            "role": role,
            "grants": grants,
            "subject": str(raw.get("subject") or normalized_username).strip() or normalized_username,
        }
    return users


def session_auth_enabled() -> bool:
    return bool(_normalize_user_store())


def _session_secret_bytes() -> bytes:
    return API_SESSION_SECRET.encode("utf-8")


def issue_session_token(*, username: str, subject: str, role: str, grants: tuple[AuthGrant, ...]) -> str:
    issued_at = datetime.now(UTC)
    payload = {
        "typ": "session",
        "sub": subject,
        "usr": username,
        "role": role,
        "grants": [{"tenant_id": grant.tenant_id, "workspace_id": grant.workspace_id} for grant in grants],
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + timedelta(seconds=API_SESSION_TTL_SECONDS)).timestamp()),
    }
    payload_b64 = _urlsafe_b64encode(_json_bytes(payload))
    signature = hmac.new(_session_secret_bytes(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return f"lis.{payload_b64}.{_urlsafe_b64encode(signature)}"


def _decode_session_token(token: str) -> dict[str, Any] | None:
    normalized = str(token or "").strip()
    if not normalized.startswith("lis."):
        return None
    parts = normalized.split(".", 2)
    if len(parts) != 3:
        return None
    _, payload_b64, signature_b64 = parts
    expected_sig = hmac.new(_session_secret_bytes(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    actual_sig = _urlsafe_b64decode(signature_b64)
    if not hmac.compare_digest(expected_sig, actual_sig):
        return None
    payload = json.loads(_urlsafe_b64decode(payload_b64))
    if not isinstance(payload, dict) or payload.get("typ") != "session":
        return None
    if int(payload.get("exp", 0) or 0) < int(datetime.now(UTC).timestamp()):
        return None
    return payload


def _auth_context_from_session(token: str) -> AuthContext | None:
    payload = _decode_session_token(token)
    if payload is None:
        return None
    grants = _normalize_grants(payload.get("grants"))
    if not grants:
        return None
    role = str(payload.get("role") or "viewer").strip().lower() or "viewer"
    if role not in ROLE_HIERARCHY:
        return None
    subject = str(payload.get("sub") or payload.get("usr") or "").strip()
    username = str(payload.get("usr") or subject).strip()
    return AuthContext(
        token=token,
        subject=subject or username,
        tenant_id=grants[0].tenant_id,
        workspace_id=grants[0].workspace_id,
        role=role,
        grants=grants,
        auth_type="session",
    )


def authenticate_user_credentials(username: str, password: str) -> AuthContext | None:
    users = _normalize_user_store()
    normalized_username = str(username or "").strip()
    user = users.get(normalized_username)
    if user is None:
        return None
    if str(password or "") != str(user.get("password") or ""):
        return None
    token = issue_session_token(
        username=normalized_username,
        subject=str(user["subject"]),
        role=str(user["role"]),
        grants=tuple(user["grants"]),
    )
    grants = tuple(user["grants"])
    return AuthContext(
        token=token,
        subject=str(user["subject"]),
        tenant_id=grants[0].tenant_id,
        workspace_id=grants[0].workspace_id,
        role=str(user["role"]),
        grants=grants,
        auth_type="session",
    )


def auth_enabled() -> bool:
    return bool(API_AUTH_REQUIRED or _normalize_token_store() or _normalize_user_store())


def request_bearer_token(request: Request) -> str:
    authorization = str(request.headers.get("authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    header_token = str(request.headers.get("x-api-key") or "").strip()
    if header_token:
        return header_token
    return str(request.query_params.get("access_token") or "").strip()


def authenticate_request(request: Request) -> AuthContext | JSONResponse | None:
    token_store = _normalize_token_store()
    enabled = bool(API_AUTH_REQUIRED or token_store or _normalize_user_store())
    if not enabled:
        return None
    if not token_store and not session_auth_enabled():
        return JSONResponse({"error": "api auth misconfigured"}, status_code=503)
    token = request_bearer_token(request)
    if not token:
        return JSONResponse({"error": "authentication required"}, status_code=401)
    auth_context = token_store.get(token)
    if auth_context is None:
        auth_context = _auth_context_from_session(token)
    if auth_context is None:
        return JSONResponse({"error": "invalid api token"}, status_code=403)
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
    auth_context = request_auth_context(request)
    if auth_context is None:
        return None
    if role_allows(auth_context.role, minimum_role):
        return None
    return JSONResponse(
        {
            "error": "insufficient role",
            "required_role": minimum_role,
            "current_role": auth_context.role,
        },
        status_code=403,
    )


def auth_context_allows_scope(auth_context: AuthContext | None, tenant_id: str, workspace_id: str) -> bool:
    if auth_context is None:
        return True
    if not auth_context.grants:
        return auth_context.tenant_id == tenant_id and auth_context.workspace_id == workspace_id
    return any(grant.tenant_id == tenant_id and grant.workspace_id == workspace_id for grant in auth_context.grants)


class ApiAuthMiddleware(BaseHTTPMiddleware):
    """Optional API token authentication with request-scoped auth context."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path == "/health":
            request.state.auth_context = None
            return await call_next(request)
        authenticated = authenticate_request(request)
        if isinstance(authenticated, JSONResponse):
            return authenticated
        request.state.auth_context = authenticated
        return await call_next(request)
