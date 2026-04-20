# lite-interpreter 测试说明

## 1. 测试目标

当前测试通过基线数字统一记录在 `docs/project_status.md`，本文件只讲测试分层和执行方法。

这个项目的测试重点，不是“每个函数都跑一下”，而是确保下面这些主线不被破坏：

1. 任务创建、路由、执行、总结是否形成闭环
2. 控制面状态和事件回放是否一致
3. 动态链与静态链之间的 handoff 是否稳定
4. sandbox / auth / scope / artifact 边界是否安全
5. docs 与 runtime contract 是否没有明显漂移
6. workspace 资产、task 输入、artifact content API 这些产品流是否闭环

## 2. 常用命令

### 全量

```bash
conda run -n lite_interpreter python -m pytest -q
```

### lint

```bash
conda run -n lite_interpreter python -m ruff check src tests scripts config
```

### 快速 readiness

```bash
python3 scripts/check_hybrid_readiness.py
```

## 3. 测试分层

### 3.1 基础设施层

关键文件：

- `tests/test_blackboard.py`
- `tests/test_runtime_resilience.py`
- `tests/test_api_auth.py`
- `tests/test_sandbox.py`
- `tests/test_ast_auditor.py`

重点验证：

- blackboard / state repo 一致性
- 租约与恢复语义
- auth / scope 约束
- sandbox 审计与执行边界

### 3.2 编排层

关键文件：

- `tests/test_dag_engine.py`
- `tests/test_dynamic_runtime.py`
- `tests/test_deerflow_bridge.py`
- `tests/test_analysis_runtime.py`

重点验证：

- router 决策
- dynamic re-entry
- summarizer 最终输出
- DeerFlow bridge 行为

### 3.3 API / 读模型层

关键文件：

- `tests/test_api_sse.py`
- `tests/test_api_execution.py`
- `tests/test_api_upload.py`
- `tests/test_api_memory.py`
- `tests/test_api_diagnostics.py`

重点验证：

- task/result/workspace/execution 读模型
- 事件流与回放
- 上传与资产枚举
- workspace 资产显式挂接 task
- artifact content API
- diagnostics / conformance / runtime capability

### 3.4 前端层

关键文件：

- `tests/test_frontend_task_console.py`
- `tests/test_frontend_stream.py`

重点验证：

- Task Console 数据抽取逻辑
- stream 组件 HTML contract
- 前端与 API 约定是否一致

### 3.5 验收层

关键文件：

- `tests/test_e2e.py`

重点验证：

- static/dynamic 最小闭环
- 环境能力存在时的真实 sandbox / sidecar 验收

## 4. 当前测试结论怎么读

如果你看到：

- `passed` 很多
- `skipped` 少量

要先区分：

- `skipped` 是否只是环境能力缺失（Docker / 本地 TCP 绑定）
- 还是功能本身没有断言通过

当前基线里 5 个 skip 属于前者。

## 5. 改 bug 时最低要求

任何会改变系统行为的修复，至少要满足：

1. 先补一个能复现旧 bug 的测试，或更新现有断言覆盖旧 bug
2. 改代码
3. 跑相关模块测试
4. 最后跑全量 `pytest -q`

## 6. 当前最值得补强的测试方向

1. workspace 资产显式挂接 task 的产品流
2. artifact 内容 API 化之后的受控读取/下载
3. skill usage / outcome 的并发计数一致性
4. 更细粒度的多文件上传/大文件限制回归
