"""Canonical sandbox security policy surface.

这层的目标不是再造一份新配置，而是把：
- `config.security_config` 的默认语义规则
- `config/harness_policy.yaml` 的可运营扩展

统一收敛成运行时真正被 AST 审计和 diagnostics 消费的一份解析后策略面。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from config.security_config import HIGH_RISK_BUILTINS, HIGH_RISK_METHODS, HIGH_RISK_MODULES

from src.harness.policy import load_harness_policy


def _normalize_string_list(values: Iterable[object] | None) -> list[str]:
    result: list[str] = []
    for item in values or []:
        text = str(item or "").strip()
        if text:
            result.append(text)
    return result


def _normalize_method_tokens(values: Iterable[object] | None) -> list[tuple[str, str]]:
    methods: list[tuple[str, str]] = []
    for item in values or []:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            module_name = str(item[0] or "").strip()
            method_name = str(item[1] or "").strip()
        else:
            token = str(item or "").strip()
            if "." not in token:
                continue
            module_name, method_name = token.rsplit(".", 1)
            module_name = module_name.strip()
            method_name = method_name.strip()
        if module_name and method_name:
            methods.append((module_name, method_name))
    return methods


@dataclass(frozen=True)
class SandboxSecurityPolicySurface:
    """AST 审计与安全解释层共享的解析后策略面。"""

    high_risk_modules: frozenset[str]
    high_risk_builtins: frozenset[str]
    high_risk_methods: frozenset[tuple[str, str]]
    yaml_semantic_modules: tuple[str, ...]
    yaml_semantic_builtins: tuple[str, ...]
    yaml_semantic_methods: tuple[str, ...]
    deny_patterns: tuple[str, ...]

    @property
    def source_config(self) -> str:
        return "src.sandbox.security_policy"

    @property
    def default_source_config(self) -> str:
        return "config.security_config"

    @property
    def yaml_source_config(self) -> str:
        return "config/harness_policy.yaml"


def load_sandbox_security_policy_surface() -> SandboxSecurityPolicySurface:
    policy = load_harness_policy()
    sandbox_policy = dict(policy.get("sandbox") or {})
    yaml_modules = tuple(_normalize_string_list(sandbox_policy.get("deny_modules")))
    yaml_builtins = tuple(_normalize_string_list(sandbox_policy.get("deny_builtins")))
    yaml_method_tokens = tuple(
        f"{module}.{method}" for module, method in _normalize_method_tokens(sandbox_policy.get("deny_methods"))
    )
    merged_methods = frozenset(HIGH_RISK_METHODS).union(_normalize_method_tokens(sandbox_policy.get("deny_methods")))
    return SandboxSecurityPolicySurface(
        high_risk_modules=frozenset(HIGH_RISK_MODULES).union(yaml_modules),
        high_risk_builtins=frozenset(HIGH_RISK_BUILTINS).union(yaml_builtins),
        high_risk_methods=merged_methods,
        yaml_semantic_modules=yaml_modules,
        yaml_semantic_builtins=yaml_builtins,
        yaml_semantic_methods=yaml_method_tokens,
        deny_patterns=tuple(_normalize_string_list(sandbox_policy.get("deny_patterns"))),
    )
