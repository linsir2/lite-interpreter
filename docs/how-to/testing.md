# lite-interpreter 测试说明

本文件是 **Reference + How-to**：回答“仓库如何分层测试、不同改动至少应该跑什么”。

当前测试通过基线数字统一记录在 `docs/reference/project-status.md`，本文件不重复维护基线数字。

## 1. 测试目标

这个项目的测试重点不是“每个函数都碰一下”，而是确保下面这些主线不被破坏：

1. 分析任务创建、路由、执行、总结是否形成闭环
2. 控制面状态和事件回放是否一致
3. 动态链与静态链的 handoff 是否稳定
4. sandbox / auth / scope / artifact 边界是否安全
5. app-facing API 与 Web 前端契约是否一致
6. 文档、配置与运行时 contract 是否没有明显漂移

## 2. 最常用命令

### 全量回归

```bash
cd /home/linsir365/projects/lite-interpreter
conda run -n lite_interpreter python -m pytest -q
```

### 静态检查

```bash
cd /home/linsir365/projects/lite-interpreter
conda run -n lite_interpreter python -m ruff check src tests scripts config
```

### 前端构建验证

```bash
cd /home/linsir365/projects/lite-interpreter/apps/web
npm run lint
npm run build
```

### readiness / smoke

```bash
cd /home/linsir365/projects/lite-interpreter
python3 scripts/check_hybrid_readiness.py
conda run -n lite_interpreter python scripts/smoke_deerflow_bridge.py
```

## 3. 测试分层

### 3.1 控制面与基础设施层

关键文件：

- `tests/test_blackboard.py`
- `tests/test_runtime_resilience.py`
- `tests/test_api_auth.py`
- `tests/test_sandbox.py`
- `tests/test_ast_auditor.py`

重点验证：

- Blackboard / 状态仓储一致性
- 恢复语义和降级语义
- auth / scope / role 边界
- sandbox 审计与执行边界

### 3.2 编排与运行时层

关键文件：

- `tests/test_dag_engine.py`
- `tests/test_dynamic_runtime.py`
- `tests/test_deerflow_bridge.py`
- `tests/test_analysis_runtime.py`

重点验证：

- router 决策
- dynamic research handoff
- summarizer 最终输出
- DeerFlow sidecar bridge 行为

### 3.3 app-facing API 层

关键文件：

- `tests/test_api_app.py`
- `tests/test_api_auth.py`
- `tests/test_api_route_surface.py`
- `tests/test_api_diagnostics.py`
- `tests/test_api_policy.py`

重点验证：

- `/api/app/*` 合同字段与行为
- 旧公开产品接口是否已移除
- 认证、工作区 scope、角色控制
- diagnostics / conformance / policy 接口

### 3.4 产品流层

关键文件：

- `tests/test_api_app.py`
- `scripts/create_analysis.py`
- `apps/web/src/lib/api.ts`

重点验证：

- 资料上传 -> `assetIds` 挂接 -> 创建分析
- 分析详情 -> 事件轮询 -> 结果产物读取
- 前端消费的字段和后端 presenter/schema 是否仍一致

说明：当前仓库没有单独的前端单元测试套件；Web 前端主要通过 app-facing API 契约测试、构建检查和浏览器 smoke 验证。

### 3.5 文档与契约一致性

关键文件：

- `tests/test_docs_consistency.py`

重点验证：

- `docs/reference/project-status.md` 是否仍是唯一测试基线真相源
- 主文档是否都引用了 `docs/reference/project-status.md`

## 4. 不同改动至少跑什么

### 只改文档

至少跑：

```bash
cd /home/linsir365/projects/lite-interpreter
conda run -n lite_interpreter python -m pytest -q tests/test_docs_consistency.py
```

### 改 app-facing API 或认证

至少跑：

```bash
cd /home/linsir365/projects/lite-interpreter
conda run -n lite_interpreter python -m pytest -q tests/test_api_app.py tests/test_api_auth.py tests/test_api_route_surface.py
```

### 改 DAG / 动态运行时 / 执行链

至少跑：

```bash
cd /home/linsir365/projects/lite-interpreter
conda run -n lite_interpreter python -m pytest -q tests/test_dag_engine.py tests/test_dynamic_runtime.py tests/test_deerflow_bridge.py
```

### 改前端页面或前端 API 消费

至少跑：

```bash
cd /home/linsir365/projects/lite-interpreter/apps/web
npm run lint
npm run build

cd /home/linsir365/projects/lite-interpreter
conda run -n lite_interpreter python -m pytest -q tests/test_api_app.py tests/test_api_route_surface.py
```

## 5. 如何读 `skipped`

如果你看到测试里有 `skipped`，先区分：

- 是 Docker / 本地 TCP 绑定等环境能力缺失
- 还是某条功能主链本身没有通过

只有前者才属于当前可接受的环境型跳过。

## 6. 当前最值得补强的测试方向

1. 长任务中的前端事件反馈与结果产物体验
2. skill usage / outcome 的并发计数一致性
3. 多文件上传 / 大文件限制的更细粒度回归
4. 对配置默认值与前端联调约定的契约测试
