"""Local governance decisions inspired by AutoHarness-style harnessing."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from src.common import capability_registry
from src.harness.policy import get_profile
from src.harness.types import GovernanceDecision


def _normalize_tools(tools: Iterable[str] | None) -> list[str]:
    values = []
    for tool in tools or []:
        normalized = str(tool).strip()
        if normalized:
            values.append(normalized)
    return values


def _network_access_allowed(profile_access: str, capability_access: str) -> bool:
    if capability_access == "none":
        return True
    return profile_access == "tool-mediated-only" and capability_access == "tool-mediated-only"


class HarnessGovernor:
    """Make lightweight allow/deny decisions for dynamic and sandbox actions."""

    @staticmethod
    def evaluate_dynamic_request(
        *,
        query: str,
        requested_tools: Sequence[str] | None = None,
        profile_name: str | None = None,
        max_steps: int | None = None,
        trace_ref: str | None = None,
    ) -> GovernanceDecision:
        profile_name, profile, policy = get_profile(profile_name)
        effective_max_steps = int(
            max_steps if max_steps is not None else (policy.get("dynamic", {}) or {}).get("max_steps", 6)
        )
        allowed_capabilities, _ = capability_registry.resolve_names(profile.get("allowed_tools"))
        allowed_tools = [descriptor.capability_id for descriptor in allowed_capabilities]
        requested = _normalize_tools(requested_tools)
        requested_capabilities, unknown_tools = capability_registry.resolve_names(requested)
        requested_capability_ids = [descriptor.capability_id for descriptor in requested_capabilities]
        reasons: list[str] = []
        risk_score = 0.15
        profile_network_access = str(profile.get("network_access") or "none")
        profile_host_bash_access = str(profile.get("host_bash_access") or "forbidden")

        lowered_query = query.lower()
        if any(keyword in lowered_query for keyword in ["自己找数据", "联网", "research", "探索", "验证"]):
            risk_score += 0.25
            reasons.append("任务包含外部检索或探索意图")
        if any(keyword in lowered_query for keyword in ["执行", "run code", "写代码验证"]):
            risk_score += 0.25
            reasons.append("任务包含代码执行或验证闭环")
        if requested:
            risk_score += min(0.2, 0.05 * len(requested))
            reasons.append(f"请求工具数量={len(requested)}")
        if any(descriptor.network_access != "none" for descriptor in requested_capabilities):
            risk_score += 0.1
            reasons.append("请求能力包含外部/网络访问")
        if any(descriptor.executes_code for descriptor in requested_capabilities):
            risk_score += 0.15
            reasons.append("请求能力包含代码执行")

        mode = str(policy.get("mode", "standard"))
        high_threshold = float((policy.get("risk_thresholds", {}) or {}).get("high", 0.7))
        denied_known = [tool for tool in requested_capability_ids if tool not in allowed_tools]
        denied_by_profile = [
            descriptor.capability_id
            for descriptor in requested_capabilities
            if not _network_access_allowed(profile_network_access, descriptor.network_access)
        ]
        allow_unknown = bool((policy.get("dynamic", {}) or {}).get("allow_unknown_tools", False))
        unknown_or_denied = list(unknown_tools) + list(denied_known) + list(denied_by_profile)
        if denied_known:
            reasons.append(f"请求未授权能力: {', '.join(denied_known)}")
        if denied_by_profile:
            reasons.append(f"profile.network_access={profile_network_access}，无法授权: {', '.join(denied_by_profile)}")
        if unknown_tools:
            reasons.append(f"请求未授权工具: {', '.join(unknown_tools)}")
            risk_score = max(risk_score, high_threshold)
        if denied_known or denied_by_profile:
            risk_score = max(risk_score, high_threshold)

        allowed = allow_unknown or not unknown_or_denied
        if mode == "core" and risk_score >= high_threshold:
            allowed = False
        if not requested:
            requested = allowed_tools
            reasons.append("未显式请求工具，回退为 profile 默认工具集")
            requested_capability_ids = list(allowed_tools)

        risk_level = "high" if risk_score >= high_threshold else "medium" if risk_score >= 0.35 else "low"
        return GovernanceDecision(
            action="dynamic_swarm",
            profile=profile_name,
            mode=mode,
            allowed=allowed,
            risk_level=risk_level,
            risk_score=min(risk_score, 1.0),
            reasons=reasons,
            allowed_tools=[tool for tool in requested_capability_ids if allow_unknown or tool in allowed_tools],
            metadata={
                "requested_tools": requested,
                "requested_capabilities": requested_capability_ids,
                "unknown_tools": unknown_tools,
                "denied_capabilities": denied_known,
                "denied_by_profile": denied_by_profile,
                "profile_network_access": profile_network_access,
                "profile_host_bash_access": profile_host_bash_access,
                "max_steps": effective_max_steps,
                "trace_ref": trace_ref,
            },
        )

    @staticmethod
    def evaluate_sandbox_execution(
        *,
        code: str,
        tenant_id: str,
        profile_name: str = "executor",
        trace_ref: str | None = None,
    ) -> GovernanceDecision:
        profile_name, profile, policy = get_profile(profile_name)
        sandbox_policy = policy.get("sandbox", {}) or {}
        reasons: list[str] = []
        risk_score = 0.55
        deny_matches: list[str] = []

        if not bool(profile.get("sandbox_execute", False)):
            reasons.append("当前 profile 不允许沙箱执行")
            allowed = False
        else:
            allowed = True

        for pattern in sandbox_policy.get("deny_patterns", []) or []:
            if pattern and pattern in code:
                deny_matches.append(str(pattern))
                reasons.append(f"命中 deny pattern: {pattern}")
                allowed = False
                risk_score = 0.95

        if len(code) > int(sandbox_policy.get("max_code_chars", 153600)):
            reasons.append("代码长度超过 harness policy 上限")
            allowed = False
            risk_score = 0.95

        reasons.append(f"tenant={tenant_id}")
        high_threshold = float((policy.get("risk_thresholds", {}) or {}).get("high", 0.7))
        risk_level = "high" if risk_score >= high_threshold else "medium"
        return GovernanceDecision(
            action="sandbox_execute",
            profile=profile_name,
            mode=str(policy.get("mode", "standard")),
            allowed=allowed,
            risk_level=risk_level,
            risk_score=min(risk_score, 1.0),
            reasons=reasons,
            allowed_tools=["sandbox_exec"] if allowed else [],
            metadata={
                "trace_ref": trace_ref,
                "policy_layer": "harness_yaml_policy",
                "source_config": "config/harness_policy.yaml",
                "deny_pattern_matches": deny_matches,
                "semantic_primary_layer": "ast_auditor",
                "semantic_primary_config": "src.sandbox.security_policy",
            },
        )
