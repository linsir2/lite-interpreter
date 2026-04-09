"""AST静态代码审计"""

import ast
import json
import logging
from typing import Any

from config.sandbox_config import MAX_RECURSION_DEPTH

from src.common import generate_uuid, get_logger, get_utc_now
from src.sandbox.exceptions import AuditFailError, SandboxBaseError, SyntaxParseError
from src.sandbox.metrics import ast_audit_duration_seconds, ast_audit_fail_total, ast_audit_success_total
from src.sandbox.schema import AuditResult
from src.sandbox.security_policy import load_sandbox_security_policy_surface
from src.sandbox.utils import build_log_data, validate_code, validate_tenant_id

logger = get_logger(__name__)


def audit_code(code: str, tenant_id: str, trace_id: str | None = None) -> dict[str, Any]:
    """
    AST安全审计核心函数

    :param code: 待审计代码
    :param tenant_id: 租户ID
    :param trace_id: 追踪ID（不传则自动生成）
    :return: 审计结果
    """
    trace_id = trace_id or generate_uuid()
    log_extra = {"trace_id": trace_id}
    start_time = get_utc_now()
    log_data = build_log_data(tenant_id, "ast_audit", code, trace_id)
    security_surface = load_sandbox_security_policy_surface()
    high_risk_modules = set(security_surface.high_risk_modules)
    high_risk_builtins = set(security_surface.high_risk_builtins)
    high_risk_methods = set(security_surface.high_risk_methods)

    try:
        # 输入校验
        validate_code(code, trace_id)
        validate_tenant_id(tenant_id, trace_id)

        # AST解析
        try:
            tree = ast.parse(code)
            logger.debug("代码AST解析成功", extra=log_extra)
        except SyntaxError as e:
            raise SyntaxParseError(f"代码语法错误：行{e.lineno}，列{e.offset}，原因：{e.msg}", trace_id) from e

        # 初始化追踪映射表
        imported_aliases: dict[str, str] = {}
        imported_method_aliases: dict[str, tuple[str, str]] = {}
        var_module_mapping: dict[str, str] = {}
        var_method_mapping: dict[str, tuple[str, str]] = {}
        wildcard_imported_modules: set[str] = set()

        # 遍历AST节点
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                _check_import_node(node, imported_aliases, var_module_mapping, trace_id, high_risk_modules)
            elif isinstance(node, ast.ImportFrom):
                _check_import_from_node(
                    node,
                    imported_method_aliases,
                    var_method_mapping,
                    wildcard_imported_modules,
                    trace_id,
                    high_risk_modules,
                )
            elif isinstance(node, ast.Assign):
                _check_assign_node(node, var_module_mapping, var_method_mapping, trace_id)
            elif isinstance(node, ast.Call):
                _check_call_node(
                    node,
                    var_module_mapping,
                    var_method_mapping,
                    wildcard_imported_modules,
                    trace_id,
                    high_risk_builtins,
                    high_risk_methods,
                )

        # 审计通过
        duration_seconds = (get_utc_now() - start_time).total_seconds()
        success_reason = "代码审计通过，无高危操作"
        log_data.update(
            {
                "audit_result": "success",
                "reason": success_reason,
                "duration_seconds": round(duration_seconds, 3),
            }
        )
        logger.info(json.dumps(log_data, ensure_ascii=False), extra=log_extra)

        ast_audit_success_total.inc()
        ast_audit_duration_seconds.observe(duration_seconds)

        return AuditResult(
            safe=True,
            reason=success_reason,
            source_layer="ast_auditor",
            source_config=security_surface.source_config,
            trace_id=trace_id,
            duration_seconds=round(duration_seconds, 3),
        ).model_dump()

    except SandboxBaseError as e:
        duration_seconds = (get_utc_now() - start_time).total_seconds()
        risk_type = e.risk_type if isinstance(e, AuditFailError) else e.error_type
        log_level = logging.ERROR if isinstance(e, AuditFailError) else logging.WARNING

        log_data.update(
            {
                "audit_result": "fail",
                "risk_type": risk_type,
                "reason": e.message,
                "duration_seconds": round(duration_seconds, 3),
            }
        )
        logger.log(log_level, json.dumps(log_data, ensure_ascii=False), extra=log_extra)

        ast_audit_fail_total.labels(risk_type=e.error_type).inc()
        ast_audit_duration_seconds.observe(duration_seconds)

        return AuditResult(
            safe=False,
            reason=e.message,
            risk_type=risk_type,
            source_layer="ast_auditor",
            source_config=security_surface.source_config,
            trace_id=trace_id,
            duration_seconds=round(duration_seconds, 3),
        ).model_dump()

    except Exception as e:
        duration_seconds = (get_utc_now() - start_time).total_seconds()
        error_type = "unknown_exception"
        reason = f"审计过程发生未知异常：{str(e)}"
        log_data.update(
            {
                "audit_result": "fail",
                "risk_type": error_type,
                "reason": reason,
                "duration_seconds": round(duration_seconds, 3),
            }
        )
        logger.exception(json.dumps(log_data, ensure_ascii=False), extra=log_extra)

        ast_audit_fail_total.labels(risk_type=error_type).inc()
        ast_audit_duration_seconds.observe(duration_seconds)

        return AuditResult(
            safe=False,
            reason=reason,
            risk_type=error_type,
            source_layer="ast_auditor",
            source_config=security_surface.source_config,
            trace_id=trace_id,
            duration_seconds=round(duration_seconds, 3),
        ).model_dump()


def _check_import_node(
    node: ast.Import,
    imported_aliases: dict[str, str],
    var_module_mapping: dict[str, str],
    trace_id: str,
    high_risk_modules: set[str],
) -> None:
    """检查Import节点"""
    for alias in node.names:
        module_name = alias.name
        alias_name = alias.asname or module_name
        if module_name in high_risk_modules:
            raise AuditFailError(
                f"禁止导入高危模块：{module_name} (别名：{alias_name})", trace_id, "import_high_risk_module"
            )
        imported_aliases[alias_name] = module_name
        var_module_mapping[alias_name] = module_name


def _check_import_from_node(
    node: ast.ImportFrom,
    imported_method_aliases: dict[str, tuple[str, str]],
    var_method_mapping: dict[str, tuple[str, str]],
    wildcard_imported_modules: set[str],
    trace_id: str,
    high_risk_modules: set[str],
) -> None:
    """检查ImportFrom节点"""
    module_name = node.module or ""
    if node.level > 0:
        raise AuditFailError("sandbox禁止相对导入", trace_id, "relative_import_not_allowed")
    if any(alias.name == "*" for alias in node.names):
        if module_name in high_risk_modules:
            raise AuditFailError(
                f"禁止从高危模块{module_name}进行通配符导入", trace_id, "wildbard_import_high_risk_module"
            )
        wildcard_imported_modules.add(module_name)
    if module_name in high_risk_modules:
        raise AuditFailError(f"禁止从高危模块 {module_name} 导入内容", trace_id, "import_from_high_risk_module")
    for alias in node.names:
        if alias.name == "*":
            continue
        method_name = alias.name
        alias_name = alias.asname or method_name
        imported_method_aliases[alias_name] = (module_name, method_name)
        var_method_mapping[alias_name] = (module_name, method_name)


def _check_assign_node(
    node: ast.Assign, var_module_mapping: dict[str, str], var_method_mapping: dict[str, tuple[str, str]], trace_id: str
) -> None:
    """检查Assign节点"""
    for target in node.targets:
        if isinstance(target, ast.Name):
            target_name = target.id
            if isinstance(node.value, ast.Name):
                source_name = node.value.id
                if source_name in var_module_mapping:
                    var_module_mapping[target_name] = var_module_mapping[source_name]
                if source_name in var_method_mapping:
                    var_method_mapping[target_name] = var_method_mapping[source_name]
            elif isinstance(node.value, ast.Attribute):
                root_module = _get_attribute_root_module(node.value, var_module_mapping, trace_id=trace_id)
                if root_module:
                    method_name = node.value.attr
                    var_method_mapping[target_name] = (root_module, method_name)


def _check_call_node(
    node: ast.Call,
    var_module_mapping: dict[str, str],
    var_method_mapping: dict[str, tuple[str, str]],
    wildcard_imported_modules: set[str],
    trace_id: str,
    high_risk_builtins: set[str],
    high_risk_methods: set[tuple[str, str]],
) -> None:
    """检查Call节点"""
    if isinstance(node.func, ast.Name):
        func_name = node.func.id
        if func_name in high_risk_builtins:
            raise AuditFailError(f"禁止调用高危内置函数：{func_name}", trace_id, "call_high_risk_builtin")
        if func_name in var_method_mapping:
            original_module, original_method = var_method_mapping[func_name]
            if (original_module, original_method) in high_risk_methods:
                raise AuditFailError(
                    f"禁止调用高危方法：{original_module}.{original_method} (别名：{func_name})",
                    trace_id,
                    "call_high_risk_method",
                )
        for module_name in wildcard_imported_modules:
            if (module_name, func_name) in high_risk_methods:
                raise AuditFailError(
                    f"禁止调用通配符导入的高危方法：{module_name}.{func_name}",
                    trace_id,
                    "call_wildcard_imported_high_risk_method",
                )
        if func_name == "getattr" and len(node.args) >= 2:
            _check_getattr_call(node, var_module_mapping, trace_id, high_risk_methods)
    elif isinstance(node.func, ast.Attribute):
        root_module = _get_attribute_root_module(node.func.value, var_module_mapping, trace_id=trace_id)
        method_name = node.func.attr
        if root_module and (root_module, method_name) in high_risk_methods:
            raise AuditFailError(f"禁止调用高危方法：{root_module}.{method_name}", trace_id, "call_high_risk_method")


def _check_getattr_call(
    node: ast.Call,
    var_module_mapping: dict[str, str],
    trace_id: str,
    high_risk_methods: set[tuple[str, str]],
) -> None:
    """检查getattr反射调用"""
    target_node = node.args[0]
    attr_node = node.args[1]
    if isinstance(target_node, ast.Name) and isinstance(attr_node, ast.Constant):
        target_name = target_node.id
        attr_name = attr_node.value
        if target_name in var_module_mapping:
            original_module = var_module_mapping[target_name]
            if (original_module, attr_name) in high_risk_methods:
                raise AuditFailError(
                    f"禁止通过反射调用高危方法：{original_module}.{attr_name}",
                    trace_id,
                    "reflect_call_high_risk_method",
                )
    else:
        raise AuditFailError("沙箱环境禁止使用动态属性名的反射调用", trace_id, "dynamic_reflect_call_not_allowed")


def _get_attribute_root_module(
    node: ast.AST,
    var_module_mapping: dict[str, str],
    trace_id: str,
    depth: int = 0,
) -> str | None:
    """递归解析属性访问的根模块名"""
    if depth > MAX_RECURSION_DEPTH:
        raise AuditFailError(
            "代码复杂度过高或涉嫌恶意混淆，超过AST最大解析深度", trace_id, "ast_recursion_limit_exceeded"
        )
    if isinstance(node, ast.Name):
        return var_module_mapping.get(node.id)
    elif isinstance(node, ast.Attribute):
        return _get_attribute_root_module(node.value, var_module_mapping, trace_id, depth + 1)
    return None
