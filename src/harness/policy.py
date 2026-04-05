"""Policy loading helpers for the local harness governance layer."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from config.settings import HARNESS_POLICY_PATH


@lru_cache(maxsize=1)
def load_harness_policy(path: str | None = None) -> dict[str, Any]:
    policy_path = Path(path) if path else Path(HARNESS_POLICY_PATH)
    if not policy_path.exists():
        return {
            "mode": "standard",
            "default_dynamic_profile": "researcher",
            "risk_thresholds": {"medium": 0.35, "high": 0.7},
            "profiles": {},
            "dynamic": {"max_steps": 6, "allow_unknown_tools": False},
            "sandbox": {"require_policy_check": True, "deny_patterns": []},
            "redaction_rules": [],
        }
    payload = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        return {}
    return payload


def get_profile(profile_name: str | None = None) -> tuple[str, dict[str, Any], dict[str, Any]]:
    policy = load_harness_policy()
    profiles = policy.get("profiles", {}) or {}
    resolved_profile = profile_name or str(policy.get("default_dynamic_profile", "researcher"))
    profile = profiles.get(resolved_profile, {})
    return resolved_profile, profile, policy
