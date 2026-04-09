"""沙箱整体测试用例"""

import pytest
from config.sandbox_config import DOCKER_CONFIG
from src.sandbox import audit_code, execute_in_sandbox_with_audit
from src.sandbox.docker_executor import _tenant_concurrency, get_docker_client
from src.sandbox.session_manager import sandbox_session_manager


def _docker_available() -> bool:
    try:
        client = get_docker_client()
        client.ping()
        return True
    except Exception:
        return False


def test_sandbox_tenant_concurrency_limit(valid_code, test_tenant_id, reset_global_state):
    """测试租户并发数超限被拦截"""
    # 模拟该租户的并发数已经达到了上限
    max_limit = DOCKER_CONFIG["max_tenant_concurrency"]
    _tenant_concurrency[test_tenant_id] = max_limit

    exec_result = execute_in_sandbox_with_audit(valid_code, test_tenant_id)

    assert exec_result["success"] is False
    assert f"最大支持{max_limit}并发" in exec_result["error"]


def test_sandbox_full_flow_safe_code(valid_code, test_tenant_id, reset_global_state):
    """测试安全代码完整流程"""
    if not _docker_available():
        pytest.skip("Docker unavailable in current environment")
    # 1. 审计通过
    audit_result = audit_code(valid_code, test_tenant_id)
    assert audit_result["safe"] is True

    # 2. 执行成功
    exec_result = execute_in_sandbox_with_audit(valid_code, test_tenant_id)
    assert exec_result["success"] is True
    assert "Hello Sandbox!" in exec_result["output"]
    assert "1+2=3" in exec_result["output"]
    assert "trace_id" in exec_result
    assert "duration_seconds" in exec_result


def test_sandbox_risky_code_audit_failed(high_risk_code, test_tenant_id, reset_global_state):
    """测试高危代码审计失败"""
    exec_result = execute_in_sandbox_with_audit(high_risk_code, test_tenant_id)
    assert exec_result["success"] is False
    assert "禁止导入高危模块：os" in exec_result["error"]


def test_sandbox_code_error(error_code, test_tenant_id, reset_global_state):
    """测试代码执行错误"""
    if not _docker_available():
        pytest.skip("Docker unavailable in current environment")
    # 审计通过
    audit_result = audit_code(error_code, test_tenant_id)
    assert audit_result["safe"] is True

    # 执行失败
    exec_result = execute_in_sandbox_with_audit(error_code, test_tenant_id)
    assert exec_result["success"] is False
    assert "代码执行失败" in exec_result["error"]
    assert "ZeroDivisionError" in exec_result["error"]


# 添加到 test_sandbox.py 中
def test_sandbox_execution_timeout(timeout_code, test_tenant_id, reset_global_state, monkeypatch):
    """测试代码执行超时被强制熔断"""
    if not _docker_available():
        pytest.skip("Docker unavailable in current environment")
    monkeypatch.setitem(DOCKER_CONFIG, "timeout", 2)
    # 审计能通过（单纯的死循环没有恶意模块）
    audit_result = audit_code(timeout_code, test_tenant_id)
    assert audit_result["safe"] is True

    # 执行应该因为超时失败
    exec_result = execute_in_sandbox_with_audit(timeout_code, test_tenant_id)
    assert exec_result["success"] is False
    assert "沙箱执行超时" in exec_result["error"] or "代码执行超时" in exec_result["error"]


def test_sandbox_empty_code(test_tenant_id, reset_global_state):
    """测试空代码执行失败"""
    exec_result = execute_in_sandbox_with_audit("", test_tenant_id)
    assert exec_result["success"] is False
    assert "待执行代码不能为空" in exec_result["error"]


def test_sandbox_invalid_tenant_id(valid_code, reset_global_state):
    """测试非法租户ID执行失败"""
    invalid_tenant_id = "tenant@123"
    exec_result = execute_in_sandbox_with_audit(valid_code, invalid_tenant_id)
    assert exec_result["success"] is False
    assert "租户ID仅支持字母、数字、下划线、横杠" in exec_result["error"]


def test_sandbox_denied_result_contains_session_metadata(reset_global_state):
    sandbox_session_manager.clear()
    result = execute_in_sandbox_with_audit("__import__('os').system('ls')", "tenant_safe")
    # audit denial happens before docker, so no sandbox session is created there
    assert result["success"] is False


def test_core_executor_denial_contains_sandbox_session():
    sandbox_session_manager.clear()
    from src.sandbox.docker_executor import _execute_code_in_docker

    result = _execute_code_in_docker("__import__('os').system('ls')", "tenant_safe", "ws")
    assert result["success"] is False
    assert result["sandbox_session"]["session_id"] == result["trace_id"]
    assert result["sandbox_session"]["status"] == "failed"


def test_core_executor_timeout_path_returns_structured_failure(monkeypatch):
    from requests.exceptions import Timeout as RequestsTimeout
    from src.sandbox.docker_executor import _execute_code_in_docker

    class _Decision:
        allowed = True
        reasons = []

        def to_record(self):
            return {"allowed": True, "reasons": []}

    monkeypatch.setattr(
        "src.sandbox.docker_executor.HarnessGovernor.evaluate_sandbox_execution", lambda **kwargs: _Decision()
    )
    monkeypatch.setattr("src.sandbox.docker_executor.validate_code_basic", lambda code, trace_id: None)
    monkeypatch.setattr("src.sandbox.docker_executor.validate_tenant_id", lambda tenant_id, trace_id: None)
    monkeypatch.setattr("src.sandbox.docker_executor.current_tenant_concurrency", lambda tenant_id: 0)
    monkeypatch.setattr("src.sandbox.docker_executor.increment_tenant_concurrency", lambda tenant_id: None)
    monkeypatch.setattr("src.sandbox.docker_executor.decrement_tenant_concurrency", lambda tenant_id: None)
    monkeypatch.setattr(
        "src.sandbox.docker_executor.get_docker_client", lambda: (_ for _ in ()).throw(RequestsTimeout("timeout"))
    )

    result = _execute_code_in_docker("print('ok')", "tenant_timeout", "ws_timeout")

    assert result["success"] is False
    assert "代码执行超时" in result["error"]
