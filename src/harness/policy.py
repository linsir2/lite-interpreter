"""Policy loading helpers for the local harness governance layer."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from config.settings import HARNESS_POLICY_PATH

SUPPORTED_GOVERNANCE_MODES = {"standard", "core"}
SUPPORTED_NETWORK_ACCESS = {"none", "tool-mediated-only"}
SUPPORTED_HOST_BASH_ACCESS = {"forbidden"}


def _default_policy() -> dict[str, Any]:
    return {
        "mode": "standard",
        "default_dynamic_profile": "researcher",
        "risk_thresholds": {"medium": 0.35, "high": 0.7},
        "profiles": {},
        "dynamic": {"max_steps": 6, "allow_unknown_tools": False},
        "sandbox": {
            "require_policy_check": True,
            "deny_patterns": [],
            "deny_modules": [],
            "deny_builtins": [],
            "deny_methods": [],
        },
        "redaction_rules": [],
    }


def _merge_defaults(policy: dict[str, Any]) -> dict[str, Any]:
    merged = _default_policy()
    merged.update(policy)
    merged["risk_thresholds"] = {
        **_default_policy()["risk_thresholds"],
        **dict(policy.get("risk_thresholds") or {}),
    }
    merged["dynamic"] = {
        **_default_policy()["dynamic"],
        **dict(policy.get("dynamic") or {}),
    }
    merged["sandbox"] = {
        **_default_policy()["sandbox"],
        **dict(policy.get("sandbox") or {}),
    }
    merged["profiles"] = dict(policy.get("profiles") or {})
    merged["redaction_rules"] = list(policy.get("redaction_rules") or [])
    return merged


def _normalize_policy(policy: dict[str, Any]) -> dict[str, Any]:
    normalized = _merge_defaults(policy)
    mode = str(normalized.get("mode") or "standard").strip().lower()
    if mode not in SUPPORTED_GOVERNANCE_MODES:
        mode = "standard"
    normalized["mode"] = mode

    profiles: dict[str, Any] = {}
    for profile_name, raw_profile in (normalized.get("profiles") or {}).items():
        profile = dict(raw_profile or {})
        network_access = str(profile.get("network_access") or "none").strip().lower()
        if network_access not in SUPPORTED_NETWORK_ACCESS:
            network_access = "none"
        host_bash_access = str(profile.get("host_bash_access") or "forbidden").strip().lower()
        if host_bash_access not in SUPPORTED_HOST_BASH_ACCESS:
            host_bash_access = "forbidden"
        profile["network_access"] = network_access
        profile["host_bash_access"] = host_bash_access
        profile["allowed_tools"] = list(profile.get("allowed_tools") or [])
        profile["sandbox_execute"] = bool(profile.get("sandbox_execute", False))
        profiles[str(profile_name)] = profile
    normalized["profiles"] = profiles
    normalized["dynamic"]["max_steps"] = int(normalized["dynamic"].get("max_steps", 6) or 6)
    normalized["dynamic"]["allow_unknown_tools"] = bool(normalized["dynamic"].get("allow_unknown_tools", False))
    normalized["sandbox"]["require_policy_check"] = bool(normalized["sandbox"].get("require_policy_check", True))
    normalized["sandbox"]["max_code_chars"] = int(normalized["sandbox"].get("max_code_chars", 153600) or 153600)
    normalized["sandbox"]["deny_patterns"] = [str(item) for item in normalized["sandbox"].get("deny_patterns", []) or [] if str(item)]
    normalized["sandbox"]["deny_modules"] = [str(item) for item in normalized["sandbox"].get("deny_modules", []) or [] if str(item)]
    normalized["sandbox"]["deny_builtins"] = [str(item) for item in normalized["sandbox"].get("deny_builtins", []) or [] if str(item)]
    normalized["sandbox"]["deny_methods"] = [
        str(item) if not isinstance(item, (list, tuple)) else ".".join(str(part) for part in item[:2])
        for item in normalized["sandbox"].get("deny_methods", []) or []
        if str(item)
    ]
    return normalized


@lru_cache(maxsize=1)
def load_harness_policy(path: str | None = None) -> dict[str, Any]:
    policy_path = Path(path) if path else Path(HARNESS_POLICY_PATH)
    if not policy_path.exists():
        return _default_policy()
    payload = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        return _default_policy()
    return _normalize_policy(payload)


def refresh_harness_policy() -> dict[str, Any]:
    load_harness_policy.cache_clear()
    return load_harness_policy()


def get_profile(profile_name: str | None = None) -> tuple[str, dict[str, Any], dict[str, Any]]:
    policy = load_harness_policy()
    profiles = policy.get("profiles", {}) or {}
    resolved_profile = str(profile_name or policy.get("default_dynamic_profile", "researcher"))
    profile = dict(profiles.get(resolved_profile, {}) or {})
    profile.setdefault("network_access", "none")
    profile.setdefault("host_bash_access", "forbidden")
    profile.setdefault("allowed_tools", [])
    profile.setdefault("sandbox_execute", False)
    return resolved_profile, profile, policy
