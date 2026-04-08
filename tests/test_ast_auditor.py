"""AST审计测试用例"""
from unittest.mock import patch

from src.sandbox.ast_auditor import audit_code


def test_audit_code_valid(valid_code, test_tenant_id):
    """测试合法代码审计通过"""
    result = audit_code(valid_code, test_tenant_id)
    assert result["safe"] is True
    assert "代码审计通过" in result["reason"]
    assert result["source_layer"] == "ast_auditor"
    assert result["source_config"] == "src.sandbox.security_policy"

def test_audit_code_high_risk_module(high_risk_code, test_tenant_id):
    """测试导入高危模块审计失败"""
    result = audit_code(high_risk_code, test_tenant_id)
    assert result["safe"] is False
    assert "禁止导入高危模块：os" in result["reason"]
    assert result["risk_type"] == "import_high_risk_module"
    assert result["source_layer"] == "ast_auditor"
    assert result["source_config"] == "src.sandbox.security_policy"

def test_audit_code_high_risk_alias(test_tenant_id):
    """测试高危模块别名导入和子模块调用拦截"""
    codes = [
        "import os as my_os\nmy_os.system('ls')",
        "from os import system\nsystem('ls')",
        "import subprocess\nsubprocess.Popen(['ls'])"
    ]
    for code in codes:
        result = audit_code(code, test_tenant_id)
        assert result["safe"] is False

def test_audit_code_high_risk_builtin(test_tenant_id):
    """测试调用高危内置函数审计失败"""
    code = "x = '100+200'\nresult = eval(x)"
    result = audit_code(code, test_tenant_id)
    assert result["safe"] is False
    assert "禁止调用高危内置函数：eval" in result["reason"]
    assert result["risk_type"] == "call_high_risk_builtin"

def test_audit_code_syntax_error(test_tenant_id):
    """测试语法错误代码审计失败"""
    code = "a = 1 + \nb = 2"
    result = audit_code(code, test_tenant_id)
    assert result["safe"] is False
    assert "代码语法错误" in result["reason"]
    assert result["risk_type"] == "syntax_error"

def test_audit_code_empty_code(test_tenant_id):
    """测试空代码审计失败"""
    result = audit_code("", test_tenant_id)
    assert result["safe"] is False
    assert "待执行代码不能为空" in result["reason"]
    assert result["risk_type"] == "input_validation_error"

def test_audit_code_tenant_id_invalid(test_tenant_id, valid_code):
    """测试非法租户ID审计失败"""
    invalid_tenant_id = "tenant@123"
    result = audit_code(valid_code, invalid_tenant_id)
    assert result["safe"] is False
    assert "租户ID仅支持字母、数字、下划线、横杠" in result["reason"]
    assert result["risk_type"] == "input_validation_error"


def test_audit_code_respects_yaml_semantic_extensions(test_tenant_id):
    custom_policy = {
        "mode": "standard",
        "profiles": {},
        "sandbox": {
            "deny_modules": ["pathlib"],
            "deny_builtins": ["sorted"],
            "deny_methods": ["json.dumps"],
            "deny_patterns": [],
        },
    }

    with patch("src.sandbox.security_policy.load_harness_policy", return_value=custom_policy):
        result_module = audit_code("import pathlib\nprint('x')", test_tenant_id)
        result_builtin = audit_code("sorted([3,2,1])", test_tenant_id)
        result_method = audit_code("import json\njson.dumps({'a': 1})", test_tenant_id)

    assert result_module["safe"] is False
    assert "pathlib" in result_module["reason"]
    assert result_builtin["safe"] is False
    assert "sorted" in result_builtin["reason"]
    assert result_method["safe"] is False
    assert "json.dumps" in result_method["reason"]
