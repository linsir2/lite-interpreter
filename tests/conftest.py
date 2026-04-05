"""pytest全局配置"""
import pytest
import uuid
from src.sandbox.docker_executor import (
    _tenant_concurrency, _running_containers
)
from src.sandbox.runtime_state import clear_shutdown, reset_runtime_state
from src.storage.repository.state_repo import StateRepo


@pytest.fixture(scope="function", autouse=True)
def reset_state_repo():
    StateRepo.clear()
    yield
    StateRepo.clear()

@pytest.fixture(scope="function")
def reset_global_state():
    """重置全局状态"""
    yield
    clear_shutdown()
    _tenant_concurrency.clear()
    _running_containers.clear()
    reset_runtime_state()

@pytest.fixture(scope="function")
def test_tenant_id():
    """生成测试用租户ID"""
    return f"test_tenant_{uuid.uuid4().hex[:8]}"

@pytest.fixture(scope="function")
def test_trace_id():
    """生成测试用追踪ID"""
    return str(uuid.uuid4())

@pytest.fixture(scope="function")
def valid_code():
    """有效测试代码"""
    return "print('Hello Sandbox!')\na = 1 + 2\nprint(f'1+2={a}')"

@pytest.fixture(scope="function")
def high_risk_code():
    """高危测试代码"""
    return "import os\nos.system('ls')"

@pytest.fixture(scope="function")
def timeout_code():
    """超时测试代码"""
    return "import time\nwhile True:\n    time.sleep(1)"

@pytest.fixture(scope="function")
def error_code():
    """执行错误测试代码"""
    return "a = 1 / 0"
