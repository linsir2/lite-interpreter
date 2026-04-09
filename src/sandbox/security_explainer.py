"""安全策略分层说明与代码级解释辅助。"""

from __future__ import annotations

from typing import Any

from config.sandbox_config import DOCKER_CONFIG

from src.harness.policy import load_harness_policy
from src.sandbox.ast_auditor import audit_code
from src.sandbox.security_policy import load_sandbox_security_policy_surface


def build_security_policy_summary() -> dict[str, Any]:
    """
    返回当前系统的安全策略分层摘要。

    这个摘要不是“某一层取代另一层”，而是显式回答：
    - 语义级主防线是谁
    - YAML deny_patterns 在哪里生效
    - Docker 隔离承担什么兜底责任
    """

    policy = load_harness_policy()
    sandbox_policy = dict(policy.get("sandbox") or {})
    security_surface = load_sandbox_security_policy_surface()
    return {
        "primary_semantic_policy": {
            "role": "主防线",
            "source_config": security_surface.source_config,
            "default_source_config": security_surface.default_source_config,
            "yaml_source_config": security_surface.yaml_source_config,
            "enforcer": "src.sandbox.ast_auditor",
            "high_risk_module_count": len(security_surface.high_risk_modules),
            "high_risk_builtin_count": len(security_surface.high_risk_builtins),
            "high_risk_method_count": len(security_surface.high_risk_methods),
            "yaml_semantic_extensions": {
                "deny_modules": list(security_surface.yaml_semantic_modules),
                "deny_builtins": list(security_surface.yaml_semantic_builtins),
                "deny_methods": list(security_surface.yaml_semantic_methods),
            },
        },
        "supplemental_yaml_policy": {
            "role": "补充层",
            "source_config": "config/harness_policy.yaml",
            "enforcer": "src.harness.governor",
            "require_policy_check": bool(sandbox_policy.get("require_policy_check", True)),
            "deny_patterns": list(security_surface.deny_patterns),
            "notes": [
                "deny_patterns 现在只承担 substring 级补充阻断，不再是假装的唯一危险规则入口",
                "语义级扩展规则应使用 sandbox.deny_modules / deny_builtins / deny_methods",
            ],
        },
        "runtime_containment": {
            "role": "运行时兜底隔离",
            "source_config": "config.sandbox_config",
            "enforcer": "src.sandbox.docker_executor",
            "network_disabled": bool(DOCKER_CONFIG.get("network_disabled")),
            "read_only": True,
            "cap_drop": list(DOCKER_CONFIG.get("cap_drop") or []),
            "security_opt": list(DOCKER_CONFIG.get("security_opt") or []),
            "tmpfs": dict(DOCKER_CONFIG.get("tmpfs") or {}),
        },
        "typical_guarded_execution_order": [
            "input_validation",
            "ast_auditor",
            "harness_yaml_policy",
            "docker_isolation",
        ],
    }


def explain_code_security_layers(code: str, tenant_id: str) -> dict[str, Any]:
    """
    对一段代码给出按层级拆开的解释结果。

    用途：
    - diagnostics / 审计页面
    - 测试里验证“命中的是哪一层”
    - 后续治理解释接口的统一底座
    """

    load_harness_policy()
    security_surface = load_sandbox_security_policy_surface()
    deny_patterns = list(security_surface.deny_patterns)
    yaml_matches = [pattern for pattern in deny_patterns if pattern and pattern in code]
    ast_result = audit_code(code, tenant_id)
    effective_blocking_layer = None
    if not ast_result.get("safe"):
        effective_blocking_layer = "ast_auditor"
    elif yaml_matches:
        effective_blocking_layer = "harness_yaml_policy"

    return {
        "ast_audit": ast_result,
        "yaml_deny_pattern_matches": yaml_matches,
        "effective_blocking_layer": effective_blocking_layer,
        "summary": build_security_policy_summary(),
    }
