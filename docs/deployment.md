# lite-interpreter 部署与运行说明

## 1. 默认运行环境

默认环境是 conda 的：

- `lite_interpreter`

推荐做法：

- 单条命令执行时：`conda run -n lite_interpreter <command>`
- 长时间交互调试时：`conda activate lite_interpreter`

## 2. 前置依赖

至少要准备：

- DashScope API Key
- Postgres
- Qdrant
- Neo4j
- Docker
- 可选：DeerFlow sidecar

常见环境变量：

- `DASHSCOPE_API_KEY`
- `POSTGRES_URI`
- `QDRANT_HOST`
- `QDRANT_PORT`
- `NEO4J_URI`
- `NEO4J_USER`
- `NEO4J_PASSWORD`
- `DEERFLOW_RUNTIME_MODE`
- `DEERFLOW_SIDECAR_URL`
- `DEERFLOW_CONFIG_PATH`
- `API_AUTH_REQUIRED`
- `API_AUTH_TOKENS_JSON`
- `API_AUTH_USERS_JSON`
- `API_SESSION_SECRET`
- `API_SESSION_TTL_SECONDS`
- `API_ALLOW_ORIGINS`
- `API_ENABLE_POLICY_API`
- `API_ENABLE_DEMO_TRACE`
- `API_ENABLE_DIAGNOSTICS`
- `STRICT_PERSISTENCE`

## 3. 本地启动

### 3.1 启动 API

```bash
cd /home/linsir365/projects/lite-interpreter
conda run -n lite_interpreter python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

如果你启用了 API 认证，至少还需要：

```bash
export API_AUTH_REQUIRED=true
export API_AUTH_TOKENS_JSON='{"viewer-token":{"tenant_id":"demo-tenant","workspace_id":"demo-workspace","role":"viewer","subject":"viewer-user"},"operator-token":{"tenant_id":"demo-tenant","workspace_id":"demo-workspace","role":"operator","subject":"operator-user"},"admin-token":{"tenant_id":"demo-tenant","workspace_id":"demo-workspace","role":"admin","subject":"admin-user"}}'
export API_AUTH_USERS_JSON='{"alice":{"password":"alice-pass","role":"admin","subject":"alice-user","grants":[{"tenant_id":"demo-tenant","workspace_id":"demo-workspace"},{"tenant_id":"finance-tenant","workspace_id":"finance-ws"}]}}'
export API_SESSION_SECRET=change-me-in-production
```

推荐角色：

- `viewer`: 只读任务、执行、知识、记忆、运行时与流式观察
- `operator`: 在 `viewer` 基础上允许创建任务、上传文件
- `admin`: 在 `operator` 基础上允许策略管理、诊断和 demo trace

会话登录接口：

```bash
curl -X POST http://127.0.0.1:8000/api/session/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"alice-pass"}'
```

拿到 `access_token` 后，可调用：

```bash
curl -H "Authorization: Bearer <access_token>" \
  http://127.0.0.1:8000/api/session/me
```

或：

```bash
make run-api
```

### 3.2 启动 DeerFlow sidecar

```bash
cd /home/linsir365/projects/lite-interpreter
export DEERFLOW_CONFIG_PATH=/home/linsir365/projects/deer-flow/config.yaml
conda run -n lite_interpreter python scripts/run_deerflow_sidecar.py --host 127.0.0.1 --port 8765
```

或：

```bash
make run-sidecar
```

### 3.3 启动前端

```bash
cd /home/linsir365/projects/lite-interpreter
conda run -n lite_interpreter streamlit run src/frontend/app.py
```

或：

```bash
make run-frontend
```

## 4. 推荐运行模式

本项目当前推荐：

- `DEERFLOW_RUNTIME_MODE=sidecar`

原因：

- `lite_interpreter` 主进程与 DeerFlow 运行时边界更清晰
- 更接近真实生产部署形态
- 避免把 DeerFlow 全部依赖栈和主进程硬绑定在一起

推荐环境变量：

```bash
export DEERFLOW_RUNTIME_MODE=sidecar
export DEERFLOW_SIDECAR_URL=http://127.0.0.1:8765
export DEERFLOW_CONFIG_PATH=/home/linsir365/projects/deer-flow/config.yaml
export API_ALLOW_ORIGINS=http://127.0.0.1:8501,http://localhost:8501
```

如果你要启用受保护的调试/运维接口，再显式开启：

```bash
export API_ENABLE_DIAGNOSTICS=true
export API_ENABLE_POLICY_API=true
export API_ENABLE_DEMO_TRACE=true
```

高风险控制面操作会写入持久化审计日志，可通过：

```bash
curl -H "Authorization: Bearer admin-token" \
  "http://127.0.0.1:8000/api/audit/logs?tenant_id=demo-tenant&workspace_id=demo-workspace&limit=50"
```

审计过滤还支持：

- `subject`
- `role`
- `action`
- `outcome`
- `resource_type`
- `resource_id`
- `task_id`
- `execution_id`
- `recorded_after`
- `recorded_before`

## 5. 常用验收命令

### 5.1 全量测试

```bash
conda run -n lite_interpreter python -m pytest -q
```

首次部署前建议先确保 Postgres driver 已装好：

```bash
conda run -n lite_interpreter python -c "import psycopg"
```

如果你仍在使用 `psycopg2`：

```bash
conda run -n lite_interpreter python -c "import psycopg2"
```

### 5.2 关键链路测试

```bash
conda run -n lite_interpreter python -m pytest -q \
  tests/test_blackboard.py \
  tests/test_api_sse.py \
  tests/test_dag_engine.py \
  tests/test_dynamic_runtime.py \
  tests/test_e2e.py
```

### 5.3 Makefile 快捷命令

```bash
make test-stream
make smoke-models
make demo-trace
make create-task
```

## 6. 演示流程

### 6.1 假 trace 演示

1. 启动 API
2. 启动前端
3. 执行：

```bash
make demo-trace
```

4. 在前端输入：
   - API Base URL: `http://127.0.0.1:8000`
   - API Token: `viewer-token` / `operator-token` / `admin-token`（按操作权限选择）
   - Task ID: `demo-task-001`

### 6.2 最小真实任务

1. 启动 API
2. 可选启动 sidecar
3. 执行：

```bash
make create-task
```

## 7. 故障排查

### 7.1 API 起不来

检查：

- 是否在 `lite_interpreter` 环境
- `uvicorn` 是否可 import
- `config/settings.py` 中路径/环境变量是否正确
- 如果启用了 Postgres，`psycopg` 或 `psycopg2` 是否可 import
- 如果启用了认证，`API_AUTH_TOKENS_JSON` 是否是合法 JSON 且包含 `tenant_id/workspace_id`
- 如果启用了会话登录，`API_AUTH_USERS_JSON` 是否是合法 JSON 且包含 `password/role/grants`

### 7.2 sidecar 连不上

检查：

- `DEERFLOW_RUNTIME_MODE` 是否为 `sidecar`
- `DEERFLOW_SIDECAR_URL` 是否和 sidecar 端口一致
- `scripts/run_deerflow_sidecar.py` 是否已启动

### 7.3 Sandbox 执行失败

检查：

- Docker 是否可访问
- 当前环境是否允许 Docker 调用
- `config/sandbox_config.py` 中镜像与资源限制是否可用

### 7.4 KAG 检索为空

检查：

- Postgres / Qdrant / Neo4j 是否可用
- 是否已先完成文档解析和入库
- query 是否命中了 `router -> kag_retriever`

### 7.5 为什么接口返回 401 / 403 / 404

检查：

- 是否已配置并携带 bearer token
- token 绑定的 `tenant_id/workspace_id` 是否和请求作用域一致
- 任务/执行资源查询时是否带上了正确作用域
- `/api/policy`、`/api/diagnostics`、`/api/dev/tasks/{task_id}/demo-trace` 是否被显式开启

## 8. 部署建议

当前最适合的部署形态是：

- 主进程：`lite-interpreter` API + frontend
- 外部依赖：Postgres / Qdrant / Neo4j / Docker
- 动态 runtime：本地或同机 sidecar DeerFlow

在这个阶段，不建议直接把它当成“零配置生产系统”上线，更合适的定位是：

- 架构验证环境
- 受控原型环境
- 内部演示与试点环境
