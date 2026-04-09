"""Prometheus指标"""

from prometheus_client import Counter, Histogram

# AST审计指标
ast_audit_fail_total = Counter("ast_audit_fail_nums", "Total number of failed ast audits in sandbox", ["risk_type"])
ast_audit_success_total = Counter(
    "ast_audit_success_total",
    "Total number of passed AST audits",
)
ast_audit_duration_seconds = Histogram(
    "ast_audit_duration_seconds",
    "AST audit duration distribution",
)

# 沙箱执行指标
sandbox_exec_duration_seconds = Histogram(
    "sandbox_exec_duration_seconds",
    "Sandbox execution duration distribution",
)
sandbox_exec_success_total = Counter(
    "sandbox_exec_success_total",
    "Total number of successful sandbox executions",
)
sandbox_exec_fail_total = Counter(
    "sandbox_exec_fail_total", "Total number of failed sandbox executions", ["error_type"]
)
sandbox_container_oom_total = Counter(
    "sandbox_container_oom_total",
    "Total number of OOM killed containers",
)
sandbox_container_create_fail_total = Counter(
    "sandbox_container_create_fail_total", "Total number of container create failures", ["error_type"]
)
sandbox_container_create_success_total = Counter(
    "sandbox_container_create_success_total",
    "Total number of container create success",
)
sandbox_container_remove_fail_total = Counter(
    "sandbox_container_remove_fail_total",
    "Total number of container remove failures",
)
